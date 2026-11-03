"""FR-06 / US-03: заглушка LLM даёт детерминированный черновик с учётом оценки и товара."""

from dataclasses import replace
from typing import Any

from app.llm import DraftRequest, StubLLMProvider

llm = StubLLMProvider()


BASE = DraftRequest(kind="review", product_title="Торшер «Дуга»", buyer_name="Олег", rating=5, last_buyer_text="")


def _req(**kw: Any) -> DraftRequest:
    return replace(BASE, **kw)


def test_deterministic():
    assert llm.draft_reply(_req()) == llm.draft_reply(_req())


def test_positive_review_thanks():
    assert "Спасибо за отзыв" in llm.draft_reply(_req(rating=5)).text


def test_negative_review_offers_replacement():
    text = llm.draft_reply(_req(rating=1)).text
    assert "замену или возврат" in text
    assert "Торшер «Дуга»" in text


def test_chat_topic_detected():
    text = llm.draft_reply(_req(kind="chat", rating=None, last_buyer_text="Есть ли гарантия?")).text
    assert "12 месяцев" in text


def test_anonymous_buyer_gets_neutral_greeting():
    text = llm.draft_reply(_req(buyer_name=None)).text
    assert text.startswith("Здравствуйте!")
    assert "None" not in text
