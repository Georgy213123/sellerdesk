"""Модель данных. Все отметки времени хранятся как timestamptz в UTC (см. docs/06-bugs.md, BUG-02)."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Marketplace(StrEnum):
    WILDBERRIES = "wildberries"
    OZON = "ozon"
    YANDEX = "yandex_market"


class ChatStatus(StrEnum):
    NEW = "new"
    IN_PROGRESS = "in_progress"
    ANSWERED = "answered"


class Author(StrEnum):
    BUYER = "buyer"
    OPERATOR = "operator"


class FeedbackKind(StrEnum):
    REVIEW = "review"
    QUESTION = "question"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class AgentKind(StrEnum):
    WEEKLY_INSIGHTS = "weekly_insights"


class AgentRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BUDGET_EXHAUSTED = "budget_exhausted"


class AgentEventKind(StrEnum):
    STEP_STARTED = "step_started"
    STEP_DONE = "step_done"
    LLM_CALL = "llm_call"
    BUDGET_STOP = "budget_stop"
    ERROR = "error"
    RESUMED = "resumed"


class ProposalKind(StrEnum):
    REPLY_TEMPLATE = "reply_template"
    CARD_EDIT = "card_edit"


class ProposalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


def _tz() -> DateTime:
    return DateTime(timezone=True)


class Operator(Base):
    __tablename__ = "operators"

    id: Mapped[int] = mapped_column(primary_key=True)
    login: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str] = mapped_column(String(128))
    password_hash: Mapped[str] = mapped_column(String(256))


class Product(Base):
    __tablename__ = "products"

    sku: Mapped[str] = mapped_column(String(32), primary_key=True)
    title: Mapped[str] = mapped_column(String(256))
    category: Mapped[str] = mapped_column(String(64))


class Chat(Base):
    __tablename__ = "chats"
    __table_args__ = (UniqueConstraint("marketplace", "external_id", name="uq_chats_marketplace_external"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    marketplace: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str] = mapped_column(String(64))
    buyer_name: Mapped[str | None] = mapped_column(String(128))
    product_sku: Mapped[str | None] = mapped_column(ForeignKey("products.sku"))
    order_number: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default=ChatStatus.NEW)
    last_message_at: Mapped[datetime] = mapped_column(_tz())
    draft_text: Mapped[str | None] = mapped_column(Text)
    draft_note: Mapped[str | None] = mapped_column(Text)
    synced_at: Mapped[datetime] = mapped_column(_tz(), server_default=func.now())

    product: Mapped[Product | None] = relationship(lazy="joined")
    messages: Mapped[list["Message"]] = relationship(back_populates="chat", order_by="Message.created_at, Message.id")


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        # Повторная синхронизация не должна размножать сообщения (BUG-03).
        UniqueConstraint("chat_id", "external_id", name="uq_messages_chat_external"),
        # Двойной клик «Отправить» — одно сообщение (BUG-01).
        UniqueConstraint("chat_id", "idempotency_key", name="uq_messages_chat_idem"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"), index=True)
    external_id: Mapped[str | None] = mapped_column(String(64))
    author: Mapped[str] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(_tz())
    idempotency_key: Mapped[str | None] = mapped_column(String(64))

    chat: Mapped[Chat] = relationship(back_populates="messages")


class Feedback(Base):
    """Отзыв или вопрос о товаре."""

    __tablename__ = "feedback"
    __table_args__ = (
        UniqueConstraint("marketplace", "external_id", name="uq_feedback_marketplace_external"),
        CheckConstraint("rating IS NULL OR rating BETWEEN 1 AND 5", name="ck_feedback_rating"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    marketplace: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16))
    product_sku: Mapped[str | None] = mapped_column(ForeignKey("products.sku"))
    buyer_name: Mapped[str | None] = mapped_column(String(128))
    rating: Mapped[int | None] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(_tz())
    answer_text: Mapped[str | None] = mapped_column(Text)
    answered_at: Mapped[datetime | None] = mapped_column(_tz())
    draft_text: Mapped[str | None] = mapped_column(Text)
    draft_note: Mapped[str | None] = mapped_column(Text)

    product: Mapped[Product | None] = relationship(lazy="joined")


class ReplyTemplate(Base):
    __tablename__ = "reply_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    body: Mapped[str] = mapped_column(Text)


class SyncJob(Base):
    __tablename__ = "sync_jobs"
    __table_args__ = (
        # Активная задача одна: параллельные «Обновить» не создают вторую.
        Index(
            "uq_sync_jobs_one_active",
            text("(true)"),
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String(16), default=JobStatus.QUEUED)
    created_at: Mapped[datetime] = mapped_column(_tz(), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(_tz())
    finished_at: Mapped[datetime | None] = mapped_column(_tz())
    chats_upserted: Mapped[int] = mapped_column(Integer, default=0)
    messages_inserted: Mapped[int] = mapped_column(Integer, default=0)
    feedback_upserted: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)


class AgentRun(Base):
    """Прогон агента. Чекпоинт и аренда позволяют подобрать прогон, упавший посередине."""

    __tablename__ = "agent_runs"
    __table_args__ = (
        # Один активный прогон на вид: параллельные запуски не плодят дубли.
        Index(
            "uq_agent_runs_one_active",
            "kind",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(24), default=AgentRunStatus.QUEUED)
    period_from: Mapped[datetime] = mapped_column(_tz())
    period_to: Mapped[datetime] = mapped_column(_tz())
    checkpoint: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    token_budget: Mapped[int] = mapped_column(Integer)
    steps_done: Mapped[int] = mapped_column(Integer, default=0)
    max_steps: Mapped[int] = mapped_column(Integer)
    lease_until: Mapped[datetime | None] = mapped_column(_tz())
    heartbeat_at: Mapped[datetime | None] = mapped_column(_tz())
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(_tz(), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(_tz())
    finished_at: Mapped[datetime | None] = mapped_column(_tz())

    events: Mapped[list["AgentEvent"]] = relationship(order_by="AgentEvent.id")


class AgentEvent(Base):
    """Журнал прогона: что сделано на каком шаге и сколько токенов ушло."""

    __tablename__ = "agent_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True)
    step: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))
    message: Mapped[str] = mapped_column(Text)
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(_tz(), server_default=func.now())


class AgentProposal(Base):
    """Предложение агента на согласование. Наружу не уходит, пока его не одобрил оператор."""

    __tablename__ = "agent_proposals"
    # Повтор шага после обрыва не создаёт второе такое же предложение.
    __table_args__ = (UniqueConstraint("run_id", "theme_key", "kind", name="uq_agent_proposals_run_theme_kind"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True)
    theme_key: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(128))
    body: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), default=ProposalStatus.PENDING)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("operators.id"))
    decided_at: Mapped[datetime | None] = mapped_column(_tz())
    created_at: Mapped[datetime] = mapped_column(_tz(), server_default=func.now())
