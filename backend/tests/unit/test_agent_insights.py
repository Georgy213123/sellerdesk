"""LLM агента-маркетолога без сети: заглушка по ключевым словам и Claude с подменённым клиентом."""

from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2
import pytest

from app.llm.anthropic_insights import AnthropicInsights
from app.llm.insights import Case, InsightsUnavailable, StubInsightsProvider, ThemeBrief, get_insights_provider
from app.templating import KNOWN_VARIABLES, template_variables
from tests.unit.test_anthropic_provider import REQ, FakeClient


def _case(ref: str, text: str) -> Case:
    return Case(ref, "review", 1, text)


def _tool_use(name: str, data: dict[str, Any], usage: tuple[int, int] = (120, 30), stop: str = "tool_use") -> Any:
    return SimpleNamespace(
        stop_reason=stop,
        content=[SimpleNamespace(type="text", text="..."), SimpleNamespace(type="tool_use", name=name, input=data)],
        usage=SimpleNamespace(input_tokens=usage[0], output_tokens=usage[1]),
    )


def test_stub_groups_cases_by_keywords_and_counts_tokens():
    batch = [_case("feedback:1", "Пришла разбитой"), _case("feedback:2", "Абажур помят"), _case("feedback:3", "Ок")]
    themes, tokens = StubInsightsProvider().classify(batch)
    assert [(t.key, t.refs) for t in themes] == [("damaged", ["feedback:1", "feedback:2"])]
    assert tokens > 0
    assert StubInsightsProvider().classify(batch) == (themes, tokens)  # детерминированно


def test_stub_templates_use_only_known_variables():
    stub = StubInsightsProvider()
    used: set[str] = set()
    for key in ("delivery", "damaged", "malfunction", "assembly", "color", "warranty"):
        draft, tokens = stub.propose(ThemeBrief(key, "тема", 3, ["пример"]))
        assert draft.kind in ("reply_template", "card_edit")
        assert draft.title
        assert tokens > 0
        if draft.kind == "reply_template":
            variables = set(template_variables(draft.body))
            assert variables <= set(KNOWN_VARIABLES), draft.body
            used |= variables
    assert used  # проверка не пустая: хотя бы один шаблон действительно с переменными


def test_stub_rejects_unknown_theme():
    with pytest.raises(InsightsUnavailable):
        StubInsightsProvider().propose(ThemeBrief("zzz", "тема", 3, []))


def test_default_provider_is_stub():
    from app.config import Settings

    assert isinstance(get_insights_provider(Settings()), StubInsightsProvider)


def test_claude_classify_parses_tool_use_and_counts_usage():
    data = {"themes": [{"key": "delivery", "title": "Доставка", "refs": ["feedback:1", "message:5"]}]}
    client = FakeClient(_tool_use("report_themes", data, usage=(200, 55)))
    themes, tokens = AnthropicInsights(client).classify([_case("feedback:1", "Когда приедет?")])
    assert [(t.key, t.title, t.refs) for t in themes] == [("delivery", "Доставка", ["feedback:1", "message:5"])]
    assert tokens == 255

    call = client.calls[0]
    assert call["tool_choice"] == {"type": "tool", "name": "report_themes"}
    assert call["tools"][0]["name"] == "report_themes"
    assert "[feedback:1]" in call["messages"][0]["content"]


def test_claude_propose_parses_tool_use():
    data = {"kind": "card_edit", "title": "Уточнить цвет", "body": "Добавить в описание оттенок."}
    client = FakeClient(_tool_use("propose_action", data, usage=(80, 20)))
    draft, tokens = AnthropicInsights(client).propose(ThemeBrief("color", "Цвет", 4, ["Цвет темнее"]))
    assert (draft.kind, draft.title, draft.body) == ("card_edit", "Уточнить цвет", "Добавить в описание оттенок.")
    assert tokens == 100
    assert client.calls[0]["tool_choice"] == {"type": "tool", "name": "propose_action"}


@pytest.mark.parametrize(
    "response",
    [
        _tool_use("report_themes", {"themes": []}, stop="refusal"),
        SimpleNamespace(stop_reason="end_turn", content=[], usage=SimpleNamespace(input_tokens=1, output_tokens=1)),
        _tool_use("other_tool", {"themes": []}),
        _tool_use("report_themes", {"themes": [{"key": "x"}]}),
        _tool_use("report_themes", {}),
    ],
    ids=["refusal", "no-blocks", "wrong-tool", "missing-fields", "no-themes-key"],
)
def test_claude_bad_responses_become_unavailable(response):
    with pytest.raises(InsightsUnavailable):
        AnthropicInsights(FakeClient(response)).classify([_case("feedback:1", "текст")])


def test_claude_propose_rejects_unknown_kind():
    data = {"kind": "publish_now", "title": "x", "body": "y"}
    with pytest.raises(InsightsUnavailable):
        AnthropicInsights(FakeClient(_tool_use("propose_action", data))).propose(ThemeBrief("k", "т", 1, []))


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (anthropic.APITimeoutError(request=REQ), "таймаут"),
        (anthropic.RateLimitError("limit", response=httpx2.Response(429, request=REQ), body=None), "лимит"),
        (anthropic.APIStatusError("boom", response=httpx2.Response(500, request=REQ), body=None), "ошибка 500"),
    ],
)
def test_claude_sdk_errors_become_unavailable(error, reason):
    with pytest.raises(InsightsUnavailable) as info:
        AnthropicInsights(FakeClient(error=error)).propose(ThemeBrief("k", "т", 1, []))
    assert str(info.value) == reason
