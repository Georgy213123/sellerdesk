"""FR-01: заглушка площадки детерминирована и ведёт себя как медленный внешний API."""

import time

from app.marketplaces.base import MarketplaceClient
from app.marketplaces.mock import MockMarketplace
from app.models import Author, FeedbackKind, Marketplace


def test_same_seed_same_data():
    a = MockMarketplace(Marketplace.OZON, seed=7).fetch_chats()
    b = MockMarketplace(Marketplace.OZON, seed=7).fetch_chats()
    assert a == b


def test_different_marketplaces_have_own_ids():
    wb = {c.external_id for c in MockMarketplace(Marketplace.WILDBERRIES).fetch_chats()}
    oz = {c.external_id for c in MockMarketplace(Marketplace.OZON).fetch_chats()}
    assert wb.isdisjoint(oz)


def test_satisfies_protocol():
    client: MarketplaceClient = MockMarketplace(Marketplace.YANDEX)
    assert client.code is Marketplace.YANDEX


def test_feedback_contains_reviews_and_questions():
    items = MockMarketplace(Marketplace.WILDBERRIES).fetch_feedback()
    kinds = {f.kind for f in items}
    assert kinds == {FeedbackKind.REVIEW, FeedbackKind.QUESTION}
    assert all(f.rating is None for f in items if f.kind is FeedbackKind.QUESTION)
    assert all(1 <= (f.rating or 0) <= 5 for f in items if f.kind is FeedbackKind.REVIEW)


def test_sent_message_is_returned_by_next_fetch():
    m = MockMarketplace(Marketplace.OZON)
    chat = m.fetch_chats()[0]
    sent = m.send_chat_message(chat.external_id, "Ответ", "key-1")
    again = next(c for c in m.fetch_chats() if c.external_id == chat.external_id)
    last = again.messages[-1]
    assert (last.external_id, last.author, last.text) == (sent.external_id, Author.OPERATOR, "Ответ")


def test_delay_is_applied():
    m = MockMarketplace(Marketplace.OZON, delay_ms=50)
    started = time.perf_counter()
    m.fetch_feedback()
    assert time.perf_counter() - started >= 0.05


def test_cr01_same_key_is_accepted_once():
    m = MockMarketplace(Marketplace.OZON)
    chat = m.fetch_chats()[0].external_id
    a = m.send_chat_message(chat, "Ответ", "key-1")
    b = m.send_chat_message(chat, "Ответ", "key-1")
    assert a == b
    assert len(m.sent_log) == 1


def test_cr03_external_ids_unique_across_restarts():
    chat = MockMarketplace(Marketplace.OZON).fetch_chats()[0].external_id
    first = MockMarketplace(Marketplace.OZON).send_chat_message(chat, "x", "k1").external_id
    after_restart = MockMarketplace(Marketplace.OZON).send_chat_message(chat, "x", "k2").external_id
    assert first != after_restart
