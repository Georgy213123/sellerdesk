"""FR-03…FR-07: лента чатов, карточка, ответ, AI-черновик, шаблоны в чате."""

import threading
from datetime import UTC, datetime

from sqlalchemy import func, select

from app import replies
from app.db import get_sessionmaker
from app.marketplaces import get_client
from app.models import Chat, Marketplace, Message


def test_requires_login(client):
    assert client.get("/api/chats").status_code == 401


def test_wrong_password(client):
    r = client.post("/api/auth/login", json={"login": "operator", "password": "nope"})
    assert r.status_code == 401


def test_me(client, auth):
    assert client.get("/api/auth/me", headers=auth).json()["login"] == "operator"


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok", "database": "ok"}


def test_us01_feed_lists_all_marketplaces_newest_first(client, auth, synced):
    data = client.get("/api/chats", headers=auth).json()
    assert data["total"] == 24
    times = [datetime.fromisoformat(i["last_message_at"]) for i in data["items"]]
    assert times == sorted(times, reverse=True)
    assert {i["marketplace"] for i in data["items"]} == {"wildberries", "ozon", "yandex_market"}


def test_bug02_feed_sorted_by_real_time_across_zones(client, auth, synced, mocks):
    """BUG-02: сообщение Ozon (+03:00) и Яндекс Маркета (без зоны, MSK) против Wildberries (Z)."""
    wb = mocks[Marketplace.WILDBERRIES].fetch_chats()[3].external_id
    oz = mocks[Marketplace.OZON].fetch_chats()[3].external_id
    # Wildberries: 21:00 UTC. Ozon: 23:30 MSK = 20:30 UTC. По «настенным часам» Ozon был бы выше.
    mocks[Marketplace.WILDBERRIES].push_buyer_message(wb, "wb", datetime(2026, 11, 1, 21, 0, tzinfo=UTC))
    mocks[Marketplace.OZON].push_buyer_message(oz, "oz", datetime(2026, 11, 1, 20, 30, tzinfo=UTC))
    from app import cli

    cli.sync_now(synced)
    items = client.get("/api/chats?limit=2", headers=auth).json()["items"]
    assert [i["last_message_preview"] for i in items] == ["wb", "oz"]
    assert items[0]["last_message_at"].endswith("Z") or "+00:00" in items[0]["last_message_at"]


def test_us01_filter_by_marketplace_and_status(client, auth, synced):
    data = client.get("/api/chats?marketplace=ozon", headers=auth).json()
    assert data["total"] == 8
    assert {i["marketplace"] for i in data["items"]} == {"ozon"}
    assert client.get("/api/chats?status=answered", headers=auth).json()["total"] == 0
    assert client.get("/api/chats?marketplace=amazon", headers=auth).status_code == 422


def test_us02_chat_card(client, auth, synced):
    chat_id = client.get("/api/chats", headers=auth).json()["items"][0]["id"]
    card = client.get(f"/api/chats/{chat_id}", headers=auth).json()
    assert card["messages"]
    assert all(m["author"] == "buyer" for m in card["messages"])
    assert client.get("/api/chats/99999", headers=auth).status_code == 404


def test_us02_reply_marks_answered_and_reaches_marketplace(client, auth, synced, mocks):
    chat = synced.execute(select(Chat).where(Chat.marketplace == "wildberries").limit(1)).scalar_one()
    r = client.post(
        f"/api/chats/{chat.id}/reply",
        json={"text": "Добрый день!"},
        headers={**auth, "Idempotency-Key": "key-reply-0001"},
    )
    assert r.status_code == 200
    assert r.json()["duplicate"] is False
    card = client.get(f"/api/chats/{chat.id}", headers=auth).json()
    assert card["status"] == "answered"
    assert card["messages"][-1]["text"] == "Добрый день!"
    assert mocks[Marketplace.WILDBERRIES].sent_log == [(chat.external_id, "Добрый день!")]


def test_reply_requires_idempotency_key(client, auth, synced):
    chat_id = client.get("/api/chats", headers=auth).json()["items"][0]["id"]
    assert client.post(f"/api/chats/{chat_id}/reply", json={"text": "x"}, headers=auth).status_code == 422


def test_bug01_same_key_twice_sends_once(client, auth, synced, mocks):
    """BUG-01: двойной клик «Отправить» — два запроса, раньше покупатель получал два ответа."""
    chat = synced.execute(select(Chat).where(Chat.marketplace == "ozon").limit(1)).scalar_one()
    h = {**auth, "Idempotency-Key": "key-double-01"}
    first = client.post(f"/api/chats/{chat.id}/reply", json={"text": "Ответ"}, headers=h).json()
    second = client.post(f"/api/chats/{chat.id}/reply", json={"text": "Ответ"}, headers=h).json()
    assert second["duplicate"] is True
    assert second["message"]["id"] == first["message"]["id"]
    assert len(mocks[Marketplace.OZON].sent_log) == 1


def test_bug01_concurrent_requests_with_same_key_send_once(synced, mocks):
    """Два одновременных запроса: второй ждёт на уникальном индексе и получает готовое сообщение."""
    chat = synced.execute(select(Chat).where(Chat.marketplace == "yandex_market").limit(1)).scalar_one()
    mock = mocks[Marketplace.YANDEX]
    mock.delay_ms = 200  # первый запрос «висит» на площадке, второй успевает прийти
    results: list[replies.SendResult] = []
    barrier = threading.Barrier(2)

    def worker() -> None:
        with get_sessionmaker()() as s:
            barrier.wait()
            results.append(replies.send_chat_reply(s, get_client(chat.marketplace), chat.id, "Ответ", "key-race-0001"))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(r.duplicate for r in results) == [False, True]
    assert len(mock.sent_log) == 1
    n = synced.execute(
        select(func.count()).select_from(Message).where(Message.chat_id == chat.id, Message.author == "operator")
    ).scalar_one()
    assert n == 1


def test_us03_ai_draft_is_saved_not_sent(client, auth, synced, mocks):
    chat_id = client.get("/api/chats", headers=auth).json()["items"][0]["id"]
    draft = client.post(f"/api/chats/{chat_id}/ai-draft", headers=auth).json()
    assert draft["provider"] == "stub"
    assert "Северный свет" in draft["text"]
    card = client.get(f"/api/chats/{chat_id}", headers=auth).json()
    assert card["draft_text"] == draft["text"]
    assert card["status"] == "in_progress"
    assert all(not m.sent_log for m in mocks.values())


def _tpl_id(client, auth, name):
    return next(t["id"] for t in client.get("/api/templates", headers=auth).json() if t["name"] == name)


def test_us05_template_with_all_values_is_sent(client, auth, synced, mocks):
    chat = synced.execute(select(Chat).where(Chat.product_sku.is_not(None)).limit(1)).scalar_one()
    r = client.post(
        f"/api/chats/{chat.id}/template-reply",
        json={"template_id": _tpl_id(client, auth, "Гарантия")},
        headers={**auth, "Idempotency-Key": "key-tpl-00001"},
    ).json()
    assert r["sent"] is True
    assert "{{" not in r["text"]
    assert sum(len(m.sent_log) for m in mocks.values()) == 1


def test_us05_template_with_missing_value_becomes_draft(client, auth, synced, mocks):
    chat = synced.execute(select(Chat).where(Chat.order_number.is_(None)).limit(1)).scalar_one()
    r = client.post(
        f"/api/chats/{chat.id}/template-reply",
        json={"template_id": _tpl_id(client, auth, "Статус заказа")},
        headers={**auth, "Idempotency-Key": "key-tpl-00002"},
    ).json()
    assert r["sent"] is False
    assert "order_number" in r["missing"]
    card = client.get(f"/api/chats/{chat.id}", headers=auth).json()
    assert card["draft_text"] == r["text"]
    assert "order_number" in card["draft_note"]
    assert card["status"] == "in_progress"
    assert all(not m.sent_log for m in mocks.values())
