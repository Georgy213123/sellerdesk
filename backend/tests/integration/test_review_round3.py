"""Третий круг ревью Codex.

SD-01 (reset, дополнение к BUG-12), BUG-14 (повтор после синхронизации), BUG-15 (поздний черновик).
"""

import pytest
from sqlalchemy import func, select

from app import cli
from app.db_guard import NotATestDatabaseError
from app.llm import Draft
from app.marketplaces import get_clients
from app.models import Chat, Marketplace, Message


def test_reset_refuses_working_database(monkeypatch):
    """SD-01: `app.cli reset` делает DROP SCHEMA, на рабочей базе он отказывается."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost:5432/sellerdesk")
    from app.config import get_settings
    from app.db import get_engine

    get_settings.cache_clear()
    get_engine.cache_clear()
    try:
        with pytest.raises(NotATestDatabaseError):
            cli.reset()
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
        get_engine.cache_clear()


def test_bug14_retry_after_sync_imported_the_message(client, auth, synced, mocks):
    """Подтверждение потеряно, между попытками прошла синхронизация, повтор с тем же ключом: 200, без дубля."""
    chat = synced.execute(select(Chat).where(Chat.marketplace == "ozon").order_by(Chat.id).limit(1)).scalar_one()
    mock = mocks[Marketplace.OZON]
    mock.fail_after_accept_once = True
    h = {**auth, "Idempotency-Key": "key-sd03"}
    assert client.post(f"/api/chats/{chat.id}/reply", json={"text": "Ответ"}, headers=h).status_code == 502
    synced.expire_all()
    cli.sync_now(synced)  # площадка отдаёт принятое сообщение, синхронизация его импортирует
    second = client.post(f"/api/chats/{chat.id}/reply", json={"text": "Ответ"}, headers=h)
    assert second.status_code == 200, second.text
    assert second.json()["duplicate"] is True
    synced.expire_all()
    n = synced.execute(
        select(func.count()).select_from(Message).where(Message.chat_id == chat.id, Message.author == "operator")
    ).scalar_one()
    assert n == 1
    assert len(mock.sent_log) == 1
    assert synced.get(Chat, chat.id).status == "answered"
    # ещё один повтор тоже идемпотентен
    third = client.post(f"/api/chats/{chat.id}/reply", json={"text": "Ответ"}, headers=h)
    assert third.status_code == 200 and third.json()["duplicate"] is True


def test_bug15_late_draft_does_not_reopen_answered_chat(client, auth, synced, monkeypatch):
    """Пока считался черновик, оператор ответил: черновик отбрасывается, статус остаётся answered."""
    chat = synced.execute(select(Chat).where(Chat.status == "new").order_by(Chat.id).limit(1)).scalar_one()
    chat_id = chat.id

    class Slow:
        name = "slow"

        def draft_reply(self, request):
            r = client.post(
                f"/api/chats/{chat_id}/reply",
                json={"text": "Ответил сам"},
                headers={**auth, "Idempotency-Key": "key-sd04-late"},
            )
            assert r.status_code == 200
            return Draft(text="Поздний черновик", provider="slow")

    monkeypatch.setattr("app.api.routes.get_llm_provider", lambda: Slow())
    r = client.post(f"/api/chats/{chat_id}/ai-draft", headers=auth)
    assert r.status_code == 409
    assert r.json() == {"detail": "чат изменился, черновик устарел"}
    card = client.get(f"/api/chats/{chat_id}", headers=auth).json()
    assert card["status"] == "answered"
    assert card["draft_text"] is None
    get_clients.cache_clear()


def test_ensure_db_refuses_working_database(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost:5432/app")
    from app.config import get_settings
    from app.db import get_engine

    get_settings.cache_clear()
    get_engine.cache_clear()
    try:
        with pytest.raises(NotATestDatabaseError):
            cli.ensure_database()
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
        get_engine.cache_clear()
