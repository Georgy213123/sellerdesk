"""Единый интерфейс площадки. Сервисы знают только его, а не конкретные API."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, tzinfo
from typing import Protocol

from app.models import Author, FeedbackKind, Marketplace


@dataclass(frozen=True)
class MessageDTO:
    external_id: str
    author: Author
    text: str
    created_at: datetime  # всегда aware, UTC


@dataclass(frozen=True)
class ChatDTO:
    external_id: str
    buyer_name: str | None
    product_sku: str | None
    order_number: str | None
    messages: list[MessageDTO] = field(default_factory=list)


@dataclass(frozen=True)
class FeedbackDTO:
    external_id: str
    kind: FeedbackKind
    product_sku: str | None
    buyer_name: str | None
    rating: int | None
    text: str
    created_at: datetime
    answer_text: str | None = None


@dataclass(frozen=True)
class SentMessage:
    external_id: str
    created_at: datetime


class MarketplaceClient(Protocol):
    code: Marketplace

    def fetch_chats(self) -> list[ChatDTO]: ...

    def fetch_feedback(self) -> list[FeedbackDTO]: ...

    def send_chat_message(self, chat_external_id: str, text: str, idempotency_key: str) -> SentMessage:
        """Ключ передаётся площадке: если подтверждение потерялось, повтор не создаёт второе сообщение."""
        ...

    def answer_feedback(self, feedback_external_id: str, text: str) -> None: ...


def parse_marketplace_ts(value: str, default_tz: tzinfo) -> datetime:
    """Разбирает отметку времени площадки и приводит к UTC.

    Площадки отдают время по-разному: с `Z`, со смещением `+03:00` или вовсе без зоны
    (тогда зона берётся из документации площадки — `default_tz`). Раньше смещение
    отбрасывалось через `.replace(tzinfo=None)`, и лента сортировалась по «местному»
    времени разных площадок вперемешку (BUG-02).
    """
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=default_tz)
    return parsed.astimezone(UTC)
