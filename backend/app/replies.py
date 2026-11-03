"""Ответы покупателям: отправка в чат, ответ на отзыв, шаблоны, AI-черновики."""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.llm import DraftRequest, LLMProvider
from app.marketplaces.base import MarketplaceClient
from app.models import Author, Chat, ChatStatus, Feedback, Message, Operator
from app.templating import render_template


class NotFoundError(Exception):
    pass


class ConflictError(Exception):
    pass


class MarketplaceError(Exception):
    pass


@dataclass
class SendResult:
    message: Message
    duplicate: bool


def send_chat_reply(
    session: Session, client: MarketplaceClient, chat_id: int, text: str, idempotency_key: str
) -> SendResult:
    """Отправляет ответ в чат ровно один раз на ключ идемпотентности.

    Сначала резервируем строку сообщения с ключом (INSERT ... ON CONFLICT DO NOTHING), и только
    потом зовём площадку. Параллельный запрос с тем же ключом ждёт на уникальном индексе, пока первый
    не завершится, и получает уже готовое сообщение. Без ключа двойной клик давал два ответа
    покупателю (BUG-01).
    """
    chat = session.get(Chat, chat_id)
    if chat is None:
        raise NotFoundError("чат не найден")

    reserved = session.execute(
        insert(Message)
        .values(
            chat_id=chat_id,
            author=Author.OPERATOR,
            text=text,
            created_at=datetime.now(UTC),
            idempotency_key=idempotency_key,
        )
        .on_conflict_do_nothing(constraint="uq_messages_chat_idem")
        .returning(Message.id)
    ).scalar_one_or_none()

    if reserved is None:
        session.rollback()
        existing = session.execute(
            select(Message).where(Message.chat_id == chat_id, Message.idempotency_key == idempotency_key)
        ).scalar_one()
        if existing.text != text:
            # Ключ уже занят другим текстом: молча вернуть старый ответ значит потерять новый (CR-05).
            raise ConflictError("этот Idempotency-Key уже использован для другого текста")
        return SendResult(existing, duplicate=True)

    try:
        sent = client.send_chat_message(chat.external_id, text, idempotency_key)
    except Exception as exc:
        session.rollback()
        raise MarketplaceError(f"площадка не приняла ответ: {exc}") from exc

    message = session.get(Message, reserved)
    if message is None:  # строка зарезервирована в этой же транзакции
        raise RuntimeError("зарезервированное сообщение пропало")
    message.external_id = sent.external_id
    message.created_at = sent.created_at
    chat.status = ChatStatus.ANSWERED
    chat.last_message_at = max(chat.last_message_at, sent.created_at)
    chat.draft_text = None
    chat.draft_note = None
    session.commit()
    return SendResult(message, duplicate=False)


def answer_feedback(session: Session, client: MarketplaceClient, feedback_id: int, text: str) -> Feedback:
    """Ответ на отзыв или вопрос. Условный UPDATE — второй одновременный ответ получит 409."""
    fb = session.get(Feedback, feedback_id)
    if fb is None:
        raise NotFoundError("отзыв не найден")
    now = datetime.now(UTC)
    updated = session.execute(
        update(Feedback)
        .where(Feedback.id == feedback_id, Feedback.answer_text.is_(None))
        .values(answer_text=text, answered_at=now, draft_text=None, draft_note=None)
        .returning(Feedback.id)
    ).scalar_one_or_none()
    if updated is None:
        session.rollback()
        raise ConflictError("на этот отзыв уже ответили")
    try:
        client.answer_feedback(fb.external_id, text)
    except Exception as exc:
        session.rollback()
        raise MarketplaceError(f"площадка не приняла ответ: {exc}") from exc
    session.commit()
    session.refresh(fb)
    return fb


def chat_context(chat: Chat, operator: Operator) -> dict[str, str | None]:
    return {
        "buyer_name": chat.buyer_name,
        "product": chat.product.title if chat.product else None,
        "order_number": chat.order_number,
        "marketplace": MARKETPLACE_TITLES.get(chat.marketplace),
        "operator_name": operator.display_name,
    }


def feedback_context(fb: Feedback, operator: Operator) -> dict[str, str | None]:
    return {
        "buyer_name": fb.buyer_name,
        "product": fb.product.title if fb.product else None,
        "order_number": None,  # у отзыва нет номера заказа в API площадок
        "marketplace": MARKETPLACE_TITLES.get(fb.marketplace),
        "operator_name": operator.display_name,
    }


MARKETPLACE_TITLES = {"wildberries": "Wildberries", "ozon": "Ozon", "yandex_market": "Яндекс Маркет"}


@dataclass
class TemplateOutcome:
    sent: bool
    text: str
    missing: list[str]
    note: str | None


def missing_note(missing: list[str]) -> str:
    return "Не отправлено: не подставились переменные " + ", ".join(missing) + ". Допишите вручную."


def template_reply_chat(
    session: Session,
    client: MarketplaceClient,
    chat: Chat,
    body: str,
    operator: Operator,
    idempotency_key: str,
) -> TemplateOutcome:
    result = render_template(body, chat_context(chat, operator))
    if not result.ok:
        chat.draft_text = result.text
        chat.draft_note = missing_note(result.missing)
        if chat.status == ChatStatus.NEW:
            chat.status = ChatStatus.IN_PROGRESS
        session.commit()
        return TemplateOutcome(False, result.text, result.missing, chat.draft_note)
    send_chat_reply(session, client, chat.id, result.text, idempotency_key)
    return TemplateOutcome(True, result.text, [], None)


def template_reply_feedback(
    session: Session, client: MarketplaceClient, fb: Feedback, body: str, operator: Operator
) -> TemplateOutcome:
    result = render_template(body, feedback_context(fb, operator))
    if not result.ok:
        fb.draft_text = result.text
        fb.draft_note = missing_note(result.missing)
        session.commit()
        return TemplateOutcome(False, result.text, result.missing, fb.draft_note)
    answer_feedback(session, client, fb.id, result.text)
    return TemplateOutcome(True, result.text, [], None)


def ai_draft_chat(session: Session, llm: LLMProvider, chat: Chat) -> tuple[str, str]:
    last_buyer = next((m.text for m in reversed(chat.messages) if m.author == Author.BUYER), "")
    draft = llm.draft_reply(
        DraftRequest(
            kind="chat",
            product_title=chat.product.title if chat.product else None,
            buyer_name=chat.buyer_name,
            rating=None,
            last_buyer_text=last_buyer,
        )
    )
    chat.draft_text = draft.text
    chat.draft_note = None
    if chat.status == ChatStatus.NEW:
        chat.status = ChatStatus.IN_PROGRESS
    session.commit()
    return draft.text, draft.provider


def ai_draft_feedback(session: Session, llm: LLMProvider, fb: Feedback) -> tuple[str, str]:
    draft = llm.draft_reply(
        DraftRequest(
            kind=fb.kind,
            product_title=fb.product.title if fb.product else None,
            buyer_name=fb.buyer_name,
            rating=fb.rating,
            last_buyer_text=fb.text,
        )
    )
    fb.draft_text = draft.text
    fb.draft_note = None
    session.commit()
    return draft.text, draft.provider
