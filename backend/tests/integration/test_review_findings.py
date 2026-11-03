"""Регрессии по находкам ревью Codex (docs/04-ai-development.md, CR-NN)."""

import threading
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import event, func, select, text, update
from sqlalchemy.orm import Session

from app.db import get_engine, get_sessionmaker
from app.marketplaces import get_clients
from app.models import Chat, JobStatus, Marketplace, Message, SyncJob
from app.sync import enqueue_sync


def _chat(session, marketplace="ozon"):
    return session.execute(select(Chat).where(Chat.marketplace == marketplace).order_by(Chat.id).limit(1)).scalar_one()


def test_cr01_lost_ack_retry_does_not_send_twice(client, auth, synced, mocks):
    """CR-01: площадка приняла ответ, но подтверждение потерялось (таймаут). Повтор с тем же
    ключом не должен дать второе сообщение покупателю."""
    chat = _chat(synced)
    mock = mocks[Marketplace.OZON]
    mock.fail_after_accept_once = True
    h = {**auth, "Idempotency-Key": "key-lost-ack-1"}
    first = client.post(f"/api/chats/{chat.id}/reply", json={"text": "Ответ"}, headers=h)
    assert first.status_code == 502
    second = client.post(f"/api/chats/{chat.id}/reply", json={"text": "Ответ"}, headers=h)
    assert second.status_code == 200
    assert len(mock.sent_log) == 1


def test_cr03_external_id_survives_restart(client, auth, synced):
    """CR-03: после перезапуска процесса заглушка не должна выдать уже занятый внешний id."""
    chat = _chat(synced)
    r1 = client.post(
        f"/api/chats/{chat.id}/reply", json={"text": "Первый"}, headers={**auth, "Idempotency-Key": "key-restart-1"}
    )
    assert r1.status_code == 200
    get_clients.cache_clear()  # «перезапуск» API: состояние заглушки потеряно, БД осталась
    r2 = client.post(
        f"/api/chats/{chat.id}/reply", json={"text": "Второй"}, headers={**auth, "Idempotency-Key": "key-restart-2"}
    )
    assert r2.status_code == 200
    n = synced.execute(
        select(func.count()).select_from(Message).where(Message.chat_id == chat.id, Message.author == "operator")
    ).scalar_one()
    assert n == 2


def test_cr05_same_key_other_text_is_conflict(client, auth, synced, mocks):
    """CR-05: ключ уже использован для другого текста — 409, а не молчаливый «успех» со старым ответом."""
    chat = _chat(synced)
    h = {**auth, "Idempotency-Key": "key-text-change"}
    assert client.post(f"/api/chats/{chat.id}/reply", json={"text": "A"}, headers=h).status_code == 200
    r = client.post(f"/api/chats/{chat.id}/reply", json={"text": "B"}, headers=h)
    assert r.status_code == 409


def _wait_until(cond) -> None:
    while not cond():
        time.sleep(0.005)


def test_cr06_concurrent_enqueue_creates_one_job(session):
    """CR-06 / R2-04: транзакция A вставила задачу и не закоммитила; B ставит задачу параллельно.

    Детерминированно, без таймаутов: A коммитит только после того, как B либо закончил
    (старая реализация не видит строку A и создаёт вторую), либо стоит в ожидании блокировки
    на уникальном индексе (исправление). Состояние B читается из pg_stat_activity по его pid.
    """
    a = get_sessionmaker()()
    a.add(SyncJob(status=JobStatus.QUEUED))
    a.flush()  # строка есть, но не видна другим транзакциям
    b_pid: list[int] = []
    result: list[int] = []

    def other() -> None:
        # Сессия B привязана к одному соединению: иначе после commit пул выдаст другое,
        # и pid из pg_backend_pid() будет не тем, что ждёт блокировку.
        with get_engine().connect() as conn, Session(bind=conn) as b:
            b_pid.append(b.execute(text("SELECT pg_backend_pid()")).scalar_one())
            b.commit()
            job, _ = enqueue_sync(b)
            result.append(job.id)

    t = threading.Thread(target=other)
    t.start()
    _wait_until(lambda: bool(b_pid))

    def b_waits_on_lock() -> bool:
        with get_engine().connect() as c:
            return bool(
                c.execute(
                    text("SELECT wait_event_type = 'Lock' FROM pg_stat_activity WHERE pid = :p"), {"p": b_pid[0]}
                ).scalar()
            )

    _wait_until(lambda: not t.is_alive() or b_waits_on_lock())
    a.commit()
    t.join()
    a.close()
    active = session.execute(
        select(func.count()).select_from(SyncJob).where(SyncJob.status.in_(["queued", "running"]))
    ).scalar_one()
    assert active == 1
    assert len(result) == 1


def test_r2_01_active_job_finished_between_conflict_and_select(session):
    """R2-01: вставка B упёрлась в активную задачу, но та завершилась до SELECT активной задачи.
    enqueue_sync не должен падать NoResultFound — он должен поставить новую задачу.

    Окно воспроизводится детерминированно: перед первым SELECT по sync_jobs, идущим после
    INSERT в sync_jobs в соединении B, другая сессия завершает первую задачу.
    """
    first, created = enqueue_sync(session)
    assert created
    b = get_sessionmaker()()
    b_conn = b.connection()
    state = {"insert_seen": False, "fired": False}

    def before(conn, cursor, statement, params, context, executemany):
        if conn is not b_conn or state["fired"]:
            return
        sql = statement.lstrip().upper()
        if sql.startswith("INSERT INTO SYNC_JOBS"):
            state["insert_seen"] = True
        elif state["insert_seen"] and sql.startswith("SELECT") and "SYNC_JOBS" in sql:
            state["fired"] = True
            with get_sessionmaker()() as other:
                other.execute(update(SyncJob).where(SyncJob.id == first.id).values(status=JobStatus.DONE))
                other.commit()

    event.listen(get_engine(), "before_cursor_execute", before)
    try:
        job, created = enqueue_sync(b)
    finally:
        event.remove(get_engine(), "before_cursor_execute", before)
        b.close()
    assert state["fired"], "окно между конфликтом и SELECT не воспроизведено"
    assert job.id != first.id
    assert created is True


def test_r2_03_late_worker_does_not_revive_replaced_job(session, mocks):
    """R2-03: обработчик устаревшей задачи проснулся после её замены. Он не должен перевести
    failed → running, упасть на уникальном индексе или синхронизировать второй раз."""
    from app.sync import run_sync_job

    old = SyncJob(status=JobStatus.FAILED, error="прервана: не завершилась за 600 с")
    session.add(old)
    session.commit()
    new, created = enqueue_sync(session)
    assert created
    calls: list[str] = []
    for m in mocks.values():
        real = m.fetch_chats

        def spy(real=real):
            calls.append("fetch")
            return real()

        m.fetch_chats = spy
    run_sync_job(get_sessionmaker(), old.id, list(mocks.values()))
    session.refresh(old)
    assert old.status == JobStatus.FAILED
    assert calls == []
    session.refresh(new)
    assert new.status == JobStatus.QUEUED


def test_cr07_stale_job_does_not_block_sync(client, auth, session):
    """CR-07: задача «running», чей процесс умер, не блокирует «Обновить» навсегда."""
    old = datetime.now(UTC) - timedelta(hours=1)
    stale = SyncJob(status=JobStatus.RUNNING, created_at=old, started_at=old)
    session.add(stale)
    session.commit()
    r = client.post("/api/sync", headers=auth)
    assert r.status_code == 202
    assert r.json()["id"] != stale.id
    session.refresh(stale)
    assert stale.status == JobStatus.FAILED
    assert stale.error


def test_cr11_validation_422_matches_contract(client, auth):
    """CR-11: 422 в контракте — стандартная ошибка валидации (detail — массив)."""
    r = client.post("/api/templates", json={"name": "", "body": ""}, headers=auth)
    assert r.status_code == 422
    assert isinstance(r.json()["detail"], list)
    spec = client.app.openapi()
    ref = spec["paths"]["/api/templates"]["post"]["responses"]["422"]["content"]["application/json"]["schema"]
    assert ref["$ref"].endswith("/HTTPValidationError")


def test_cr11_unknown_variable_is_400(client, auth):
    r = client.post("/api/templates", json={"name": "Плохой", "body": "{{nickname}}"}, headers=auth)
    assert r.status_code == 400
    assert isinstance(r.json()["detail"], str)


def test_cr12_sync_200_is_in_contract(client, auth, session):
    """CR-12: повтор при активной задаче отвечает 200 — этот код должен быть в контракте."""
    enqueue_sync(session)
    r = client.post("/api/sync", headers=auth)
    assert r.status_code == 200
    assert "200" in client.app.openapi()["paths"]["/api/sync"]["post"]["responses"]


def test_cr01_review_answer_retry_after_lost_ack_leaves_one_answer(client, auth, synced, mocks):
    """CR-01, часть про отзывы: у отзыва на площадке одно поле ответа, повтор его перезаписывает.
    Покупатель видит один ответ — находка для отзывов не подтвердилась."""
    from app.models import Feedback

    fb = synced.execute(
        select(Feedback).where(Feedback.answer_text.is_(None), Feedback.marketplace == "ozon").limit(1)
    ).scalar_one()
    mock = mocks[Marketplace.OZON]
    mock.fail_after_accept_once = True
    assert client.post(f"/api/feedback/{fb.id}/answer", json={"text": "Спасибо"}, headers=auth).status_code == 502
    assert client.post(f"/api/feedback/{fb.id}/answer", json={"text": "Спасибо"}, headers=auth).status_code == 200
    on_platform = next(f for f in mock.fetch_feedback() if f.external_id == fb.external_id)
    assert on_platform.answer_text == "Спасибо"
