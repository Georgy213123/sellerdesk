"""Провайдер Claude API без сети: фейковый клиент записывает аргументы и отдаёт заготовленный ответ."""

from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2
import pytest
from pydantic import ValidationError

from app.config import Settings
from app.llm import DraftRequest, DraftUnavailable, StubLLMProvider, get_llm_provider
from app.llm.anthropic_provider import AnthropicProvider, mask_pii

REQ = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


class FakeClient:
    def __init__(self, response: Any = None, error: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._response = response
        self._error = error
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self._error:
            raise self._error
        return self._response


def _ok(text: str = "Спасибо, уточним детали.", stop: str = "end_turn") -> SimpleNamespace:
    return SimpleNamespace(stop_reason=stop, content=[SimpleNamespace(type="text", text=text)])


def _req(**kw: Any) -> DraftRequest:
    base: dict[str, Any] = {
        "kind": "chat",
        "product_title": "Торшер «Дуга»",
        "buyer_name": "Олег",
        "rating": None,
        "last_buyer_text": "Заказ 123456789 не приехал, звоните +7 (901) 111-22-33 или oleg@mail.ru",
    }
    return DraftRequest(**{**base, **kw})


def _resp(status: int) -> httpx2.Response:
    return httpx2.Response(status, request=REQ)


def test_successful_draft():
    client = FakeClient(_ok())
    draft = AnthropicProvider(client).draft_reply(_req())
    assert draft.provider == "anthropic"
    assert draft.text == "Олег, здравствуйте! Спасибо, уточним детали."


def test_model_greeting_is_not_doubled():
    draft = AnthropicProvider(FakeClient(_ok("Здравствуйте! Заказ уже в пути."))).draft_reply(_req())
    assert draft.text == "Олег, здравствуйте! Заказ уже в пути."


def test_draft_is_truncated():
    draft = AnthropicProvider(FakeClient(_ok("а" * 3000))).draft_reply(_req(buyer_name=None))
    assert len(draft.text) <= len("Здравствуйте! ") + 1000


def test_pii_masked_and_name_not_sent():
    client = FakeClient(_ok())
    AnthropicProvider(client).draft_reply(_req(last_buyer_text="Заказ 123456789, +7 901 111 22 33, a.b@mail.ru"))
    sent = str(client.calls[0])
    for leaked in ("123456789", "901 111", "a.b@mail.ru", "Олег"):
        assert leaked not in sent
    for mask in ("[номер]", "[телефон]", "[email]"):
        assert mask in sent


@pytest.mark.parametrize(
    ("raw", "masked"),
    [
        ("8 (999) 123-45-67", "[телефон]"),
        ("+79991234567", "[телефон]"),
        ("заказ 12345678", "заказ [номер]"),
        ("заказ 1234567 и 12", "заказ 1234567 и 12"),
    ],
)
def test_mask_pii(raw, masked):
    assert mask_pii(raw) == masked


def test_request_arguments():
    client = FakeClient(_ok())
    AnthropicProvider(client).draft_reply(_req())
    call = client.calls[0]
    assert call["fallbacks"] == "default"
    assert call["output_config"] == {"effort": "low"}
    assert call["betas"] == ["server-side-fallback-2026-07-01"]
    assert call["max_tokens"] == 1024
    assert not {"temperature", "top_p", "thinking"} & call.keys()


def test_refusal():
    with pytest.raises(DraftUnavailable, match="отказалась"):
        AnthropicProvider(FakeClient(_ok(stop="refusal"))).draft_reply(_req())


def test_empty_response():
    with pytest.raises(DraftUnavailable):
        AnthropicProvider(FakeClient(SimpleNamespace(stop_reason="end_turn", content=[]))).draft_reply(_req())


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (anthropic.APITimeoutError(request=REQ), "таймаут"),
        (anthropic.APIConnectionError(request=REQ), "нет связи"),
        (anthropic.RateLimitError("limit", response=_resp(429), body=None), "лимит"),
        (anthropic.AuthenticationError("auth", response=_resp(401), body=None), "ключ не принят"),
        (anthropic.APIStatusError("boom", response=_resp(500), body=None), "ошибка 500"),
    ],
)
def test_sdk_errors_become_draft_unavailable(error, reason):
    with pytest.raises(DraftUnavailable) as info:
        AnthropicProvider(FakeClient(error=error)).draft_reply(_req())
    assert str(info.value) == reason


def test_fail_closed_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ValidationError, match="ANTHROPIC_API_KEY"):
        Settings(llm_provider="anthropic")


def test_default_is_stub_and_key_allows_anthropic(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert isinstance(get_llm_provider(Settings()), StubLLMProvider)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake")
    assert get_llm_provider(Settings(llm_provider="anthropic")).name == "anthropic"
