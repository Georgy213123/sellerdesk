"""FR-02 / US-06: синхронизация площадок в БД, идемпотентный upsert, фоновая задача."""

import time
from datetime import UTC, datetime

from sqlalchemy import func, select

from app import cli
from app.models import Chat, ChatStatus, Feedback, Marketplace, Message


def _counts(session):
    return tuple(session.execute(select(func.count()).select_from(t)).scalar_one() for t in (Chat, Message, Feedback))


def test_first_sync_loads_all_marketplaces(synced):
    per_mp = dict(synced.execute(select(Chat.marketplace, func.count()).group_by(Chat.marketplace)).all())
    assert set(per_mp) == {m.value for m in Marketplace}
    assert all(n > 0 for n in per_mp.values())


def test_bug03_repeated_sync_creates_no_duplicates(synced):
    """BUG-03: повторная синхронизация вставляла сообщения чатов заново."""
    before = _counts(synced)
    cli.sync_now(synced)
    cli.sync_now(synced)
    assert _counts(synced) == before


def test_bug03_operator_reply_is_not_duplicated_by_sync(client, auth, synced):
    """Ответ, отправленный из SellerDesk, возвращается с площадки в следующей выгрузке —
    он должен совпасть с локальной строкой по внешнему id, а не лечь второй копией."""
    chat_id = synced.execute(select(Chat.id).order_by(Chat.id).limit(1)).scalar_one()
    r = client.post(
        f"/api/chats/{chat_id}/reply",
        json={"text": "Ответ"},
        headers={**auth, "Idempotency-Key": "key-sync-0001"},
    )
    assert r.status_code == 200
    cli.sync_now(synced)
    n = synced.execute(
        select(func.count()).select_from(Message).where(Message.chat_id == chat_id, Message.text == "Ответ")
    ).scalar_one()
    assert n == 1


def test_new_buyer_message_reopens_answered_chat(client, auth, synced, mocks):
    chat = synced.execute(select(Chat).where(Chat.marketplace == "ozon").order_by(Chat.id).limit(1)).scalar_one()
    client.post(
        f"/api/chats/{chat.id}/reply",
        json={"text": "Ответ"},
        headers={**auth, "Idempotency-Key": "key-reopen-01"},
    )
    mocks[Marketplace.OZON].push_buyer_message(chat.external_id, "А ещё вопрос", datetime.now(UTC))
    cli.sync_now(synced)
    synced.refresh(chat)
    assert chat.status == ChatStatus.NEW


def test_sync_endpoint_enqueues_and_returns_immediately(client, auth):
    r = client.post("/api/sync", headers=auth)
    assert r.status_code == 202
    job = r.json()
    assert job["status"] == "queued"
    # TestClient выполняет фоновые задачи до возврата ответа — проверяем итог.
    for _ in range(50):
        state = client.get(f"/api/sync/{job['id']}", headers=auth).json()
        if state["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert state["status"] == "done", state
    assert state["chats_upserted"] == 24
    assert client.get("/api/sync/latest", headers=auth).json()["id"] == job["id"]


def test_active_job_is_reused(session, client, auth):
    from app.sync import enqueue_sync

    job, created = enqueue_sync(session)  # «висит» в очереди
    assert created
    r = client.post("/api/sync", headers=auth)
    assert r.status_code == 200
    assert r.json()["id"] == job.id


def test_unknown_job_404(client, auth):
    assert client.get("/api/sync/999", headers=auth).status_code == 404


def test_nfr01_feed_does_not_wait_for_marketplace(client, auth, synced, mocks):
    """NFR-01: лента читается из БД; медленная площадка на время ответа не влияет."""
    for m in mocks.values():
        m.delay_ms = 500
    started = time.perf_counter()
    r = client.get("/api/chats", headers=auth)
    elapsed = time.perf_counter() - started
    assert r.status_code == 200
    assert elapsed < 0.3, f"лента ответила за {elapsed:.3f} с"
