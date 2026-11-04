"""Claude API для агента-маркетолога. Структурированный ответ — через tool use с JSON Schema."""

from collections.abc import Sequence
from typing import Any

import anthropic

from app.llm.anthropic_provider import failure_reason
from app.llm.insights import Case, InsightsUnavailable, ProposalDraft, Theme, ThemeBrief
from app.models import ProposalKind
from app.templating import KNOWN_VARIABLES

CLASSIFY_SYSTEM = (
    "Ты анализируешь обращения покупателей маркетплейса. Сгруппируй их по повторяющимся темам "
    "претензий и вопросов. Ключ темы — латиницей в snake_case, для одной темы всегда один и тот же. "
    "Обращения без повторяющейся темы пропусти. В refs указывай только ссылки из списка."
)
PROPOSE_SYSTEM = (
    "Ты помогаешь продавцу на маркетплейсе. По теме претензий предложи одно действие: шаблон ответа "
    "покупателю (reply_template) или правку описания карточки товара (card_edit). Пиши по-русски, коротко, "
    "без обещаний, которых нельзя проверить. В шаблоне допустимы только переменные: "
    + ", ".join("{{" + v + "}}" for v in KNOWN_VARIABLES)
    + "."
)

CLASSIFY_TOOL: dict[str, Any] = {
    "name": "report_themes",
    "description": "Темы, найденные в обращениях",
    "input_schema": {
        "type": "object",
        "properties": {
            "themes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "pattern": "^[a-z][a-z0-9_]{1,40}$"},
                        "title": {"type": "string", "maxLength": 100},
                        "refs": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["key", "title", "refs"],
                },
            }
        },
        "required": ["themes"],
    },
}
PROPOSE_TOOL: dict[str, Any] = {
    "name": "propose_action",
    "description": "Предложение для согласования с человеком",
    "input_schema": {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": [k.value for k in ProposalKind]},
            "title": {"type": "string", "maxLength": 100},
            "body": {"type": "string", "maxLength": 1500},
        },
        "required": ["kind", "title", "body"],
    },
}


MAX_TOKENS = 2048


class AnthropicInsights:
    name = "anthropic"
    max_output_tokens = MAX_TOKENS

    def __init__(self, client: Any, model: str = "claude-opus-5-5") -> None:
        self._client = client
        self._model = model

    def _call(self, system: str, content: str, tool: dict[str, Any]) -> tuple[dict[str, Any], int]:
        try:
            response = self._client.beta.messages.create(
                model=self._model,
                max_tokens=MAX_TOKENS,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                output_config={"effort": "low"},
                system=system,
                messages=[{"role": "user", "content": content}],
                tools=[tool],
                tool_choice={"type": "tool", "name": tool["name"]},
            )
        except anthropic.APIError as exc:
            raise InsightsUnavailable(failure_reason(exc)) from exc

        if response.stop_reason == "refusal":
            raise InsightsUnavailable("модель отказалась")
        block = next(
            (b for b in response.content if getattr(b, "type", None) == "tool_use" and b.name == tool["name"]), None
        )
        if block is None or not isinstance(block.input, dict):
            raise InsightsUnavailable("нет структурированного ответа")
        return block.input, response.usage.input_tokens + response.usage.output_tokens

    def classify(self, batch: Sequence[Case]) -> tuple[list[Theme], int]:
        lines = [
            f"[{c.ref}] ({c.kind}{f', оценка {c.rating}' if c.rating is not None else ''}) {c.text}" for c in batch
        ]
        data, tokens = self._call(CLASSIFY_SYSTEM, "\n".join(lines), CLASSIFY_TOOL)
        try:
            themes = [Theme(str(t["key"]), str(t["title"]), [str(r) for r in t["refs"]]) for t in data["themes"]]
        except (KeyError, TypeError) as exc:
            raise InsightsUnavailable("неверный формат ответа") from exc
        return themes, tokens

    def propose(self, theme: ThemeBrief) -> tuple[ProposalDraft, int]:
        content = f"Тема: {theme.title}\nСлучаев: {theme.count}\nПримеры:\n" + "\n".join(
            f"- {e}" for e in theme.examples
        )
        data, tokens = self._call(PROPOSE_SYSTEM, content, PROPOSE_TOOL)
        try:
            draft = ProposalDraft(str(data["kind"]), str(data["title"]), str(data["body"]))
        except KeyError as exc:
            raise InsightsUnavailable("неверный формат ответа") from exc
        if draft.kind not in {k.value for k in ProposalKind}:
            raise InsightsUnavailable("неверный формат ответа")
        return draft, tokens
