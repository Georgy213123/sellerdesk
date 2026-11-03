"""Синхронизация площадок в БД.

Интерфейс читает только из БД; площадка опрашивается фоновой задачей. Запись идемпотентна:
чаты и отзывы — upsert по (площадка, внешний id), сообщения — вставка с ON CONFLICT DO NOTHING
по (чат, внешний id). Повторная синхронизация того же набора ничего не меняет (BUG-03).
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.marketplaces.base import MarketplaceClient
from app.models import Author, Chat, ChatStatus, Feedback, JobStatus, Message, SyncJob

log = logging.getLogger(__name__)


@dataclass
class SyncStats:
    chats_upserted: int = 0
    messages_inserted: int = 0
    feedback_upserted: int = 0


def sync_marketplace(session: Session, client: MarketplaceClient) -> SyncStats:
    stats = SyncStats()
    code = client.code.value

    for chat in client.fetch_chats():
        last_at = max((m.created_at for m in chat.messages), default=datetime.now(UTC))
        stmt = (
            insert(Chat)
            .values(
                marketplace=code,
                external_id=chat.external_id,
                buyer_name=chat.buyer_name,
                product_sku=chat.product_sku,
                order_number=chat.order_number,
                status=ChatStatus.NEW,
                last_message_at=last_at,
            )
            .on_conflict_do_update(
                constraint="uq_chats_marketplace_external",
                set_={
                    "buyer_name": chat.buyer_name,
                    "order_number": chat.order_number,
                    "last_message_at": func.greatest(Chat.last_message_at, last_at),
                    "synced_at": func.now(),
                },
            )
            .returning(Chat.id)
        )
        chat_id = session.execute(stmt).scalar_one()
        stats.chats_upserted += 1

        for m in chat.messages:
            res = session.execute(
                insert(Message)
                .values(
                    chat_id=chat_id,
                    external_id=m.external_id,
                    author=m.author,
                    text=m.text,
                    created_at=m.created_at,
                )
                .on_conflict_do_nothing(constraint="uq_messages_chat_external")
                .returning(Message.id)
            )
            if res.scalar_one_or_none() is not None:
                stats.messages_inserted += 1

        _refresh_status(session, chat_id)

    for fb in client.fetch_feedback():
        session.execute(
            insert(Feedback)
            .values(
                marketplace=code,
                external_id=fb.external_id,
                kind=fb.kind,
                product_sku=fb.product_sku,
                buyer_name=fb.buyer_name,
                rating=fb.rating,
                text=fb.text,
                created_at=fb.created_at,
                answer_text=fb.answer_text,
                answered_at=fb.created_at if fb.answer_text else None,
            )
            .on_conflict_do_update(
                constraint="uq_feedback_marketplace_external",
                set_={
                    "text": fb.text,
                    "rating": fb.rating,
                    # Ответ мог быть дан в SellerDesk раньше, чем площадка его отдала обратно.
                    "answer_text": func.coalesce(Feedback.answer_text, fb.answer_text),
                },
            )
        )
        stats.feedback_upserted += 1

    return stats


def _refresh_status(session: Session, chat_id: int) -> None:
    """Новое сообщение покупателя после ответа возвращает чат в «новые»."""
    last_author = session.execute(
        select(Message.author)
        .where(Message.chat_id == chat_id)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    chat = session.get(Chat, chat_id, populate_existing=True)
    if chat is None or last_author is None:
        return
    if last_author == Author.BUYER and chat.status == ChatStatus.ANSWERED:
        chat.status = ChatStatus.NEW
    elif last_author == Author.OPERATOR:
        chat.status = ChatStatus.ANSWERED


def sync_all(session: Session, clients: list[MarketplaceClient]) -> SyncStats:
    total = SyncStats()
    for client in clients:
        s = sync_marketplace(session, client)
        total.chats_upserted += s.chats_upserted
        total.messages_inserted += s.messages_inserted
        total.feedback_upserted += s.feedback_upserted
    return total


ACTIVE = (JobStatus.QUEUED, JobStatus.RUNNING)
_ENQUEUE_ATTEMPTS = 5


def _fail_stale_jobs(session: Session) -> None:
    """Задача, которую никто не завершил за `sync_job_stale_after_s`, прервана: процесс упал (CR-07)."""
    limit = get_settings().sync_job_stale_after_s
    cutoff = datetime.now(UTC) - timedelta(seconds=limit)
    session.execute(
        update(SyncJob)
        .where(
            SyncJob.status.in_(ACTIVE),
            func.coalesce(SyncJob.started_at, SyncJob.created_at) < cutoff,
        )
        .values(
            status=JobStatus.FAILED,
            finished_at=func.now(),
            error=f"прервана: не завершилась за {limit} с",
        )
    )


def enqueue_sync(session: Session) -> tuple[SyncJob, bool]:
    """Ставит задачу. Если задача уже в очереди или идёт — возвращает её же (вторая не нужна).

    Единственность активной задачи держит частичный уникальный индекс, а не SELECT: два
    параллельных запроса оба видели пустую выборку и создавали две задачи (CR-06).
    """
    # Между конфликтом вставки и выборкой активная задача может успеть завершиться (R2-01):
    # тогда выборка пуста, и задачу нужно поставить заново. Каждый круг — либо вставка, либо
    # найденная активная задача; пустой круг возможен, только если задача завершилась в окне.
    for _ in range(_ENQUEUE_ATTEMPTS):
        _fail_stale_jobs(session)
        new_id = session.execute(
            insert(SyncJob).values(status=JobStatus.QUEUED).on_conflict_do_nothing().returning(SyncJob.id)
        ).scalar_one_or_none()
        if new_id is not None:
            session.commit()
            job = session.get(SyncJob, new_id)
            if job is None:  # строка вставлена этой же транзакцией
                raise RuntimeError("вставленная задача пропала")
            return job, True
        active = session.execute(select(SyncJob).where(SyncJob.status.in_(ACTIVE))).scalar_one_or_none()
        session.commit()
        if active is not None:
            return active, False
    raise RuntimeError("не удалось поставить задачу синхронизации: активные задачи завершаются слишком часто")


def run_sync_job(factory: sessionmaker[Session], job_id: int, clients: list[MarketplaceClient]) -> None:
    """Выполняет задачу, только если она всё ещё в очереди.

    Захват — условный UPDATE `queued → running`. Обработчик, проснувшийся после того, как его
    задачу закрыли как зависшую и заменили новой, ничего не делает: раньше он переводил
    `failed → running`, падал на уникальном индексе или синхронизировал второй раз (R2-03).
    Итог пишется тоже условно — только если задачу за это время не закрыли.
    """
    with factory() as session:
        claimed = session.execute(
            update(SyncJob)
            .where(SyncJob.id == job_id, SyncJob.status == JobStatus.QUEUED)
            .values(status=JobStatus.RUNNING, started_at=func.now())
            .returning(SyncJob.id)
        ).scalar_one_or_none()
        session.commit()
        if claimed is None:
            log.warning("sync job %s: уже не в очереди, пропускаю", job_id)
            return
        values: dict[str, object]
        try:
            stats = sync_all(session, clients)
            session.flush()
            values = {
                "status": JobStatus.DONE,
                "chats_upserted": stats.chats_upserted,
                "messages_inserted": stats.messages_inserted,
                "feedback_upserted": stats.feedback_upserted,
            }
        except Exception as exc:
            session.rollback()
            log.exception("sync job %s failed", job_id)
            values = {"status": JobStatus.FAILED, "error": str(exc)[:500]}
        finished = session.execute(
            update(SyncJob)
            .where(SyncJob.id == job_id, SyncJob.status == JobStatus.RUNNING)
            .values(finished_at=func.now(), **values)
            .returning(SyncJob.id)
        ).scalar_one_or_none()
        if finished is None:
            log.warning("sync job %s закрыта как зависшая во время работы, итог не записан", job_id)
        session.commit()
