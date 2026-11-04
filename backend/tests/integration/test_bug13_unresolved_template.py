"""BUG-13: текст с неподставленной переменной шаблона нельзя отправить покупателю.

Шаблон с пропущенной переменной становится черновиком, но кнопка «Отправить» принимала любой
непустой текст, а сервер передавал его площадке без проверки. Найдено ревью Codex (SD-02).
Проверка должна стоять на сервере: интерфейс можно обойти прямым запросом к API.
"""

import pytest
from sqlalchemy import select

from app.models import Chat, Feedback

UNRESOLVED = [
    "Здравствуйте, {{buyer_name}}! Заказ в пути.",
    "Здравствуйте, {{ Buyer_Name }}!",
    "Спасибо за отзыв о {{product}",
]


@pytest.mark.parametrize("text", UNRESOLVED)
def test_chat_reply_with_template_markup_is_rejected(client, auth, synced, mocks, text):
    chat = synced.execute(select(Chat).order_by(Chat.id).limit(1)).scalar_one()
    r = client.post(
        f"/api/chats/{chat.id}/reply",
        json={"text": text},
        headers={**auth, "Idempotency-Key": f"bug13-{abs(hash(text))}"},
    )
    assert r.status_code == 422
    assert "шаблон" in r.json()["detail"]
    assert all(not m.sent_log for m in mocks.values())


@pytest.mark.parametrize("text", UNRESOLVED)
def test_feedback_answer_with_template_markup_is_rejected(client, auth, synced, mocks, text):
    fb = synced.execute(select(Feedback).where(Feedback.answer_text.is_(None)).limit(1)).scalar_one()
    r = client.post(f"/api/feedback/{fb.id}/answer", json={"text": text}, headers=auth)
    assert r.status_code == 422
    assert all(not m.sent_log for m in mocks.values())
