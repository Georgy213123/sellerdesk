"""Провайдер Claude API за интерфейсом LLMProvider. Включается флагом LLM_PROVIDER=anthropic."""

import logging
import re
from typing import Any

import anthropic

from app.llm import Draft, DraftRequest, DraftUnavailable
from app.llm.pii import mask_pii

log = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "Ты помогаешь оператору поддержки продавца на маркетплейсе. Напиши вежливый черновик ответа "
    "покупателю на русском, 1–3 предложения, без обещаний, которых нельзя проверить, "
    "без выдуманных фактов о заказе. Только текст ответа."
)
MAX_DRAFT_CHARS = 1000


def failure_reason(exc: anthropic.APIError) -> str:
    """Короткая причина сбоя Claude API для оператора. Тело ошибки и ключ в неё не попадают."""
    if isinstance(exc, anthropic.AuthenticationError):
        return "ключ не принят"
    if isinstance(exc, anthropic.RateLimitError):
        return "лимит"
    if isinstance(exc, anthropic.APITimeoutError):
        return "таймаут"
    if isinstance(exc, anthropic.APIConnectionError):
        return "нет связи"
    if isinstance(exc, anthropic.APIStatusError):
        log.warning("anthropic: статус %s", exc.status_code)
        return f"ошибка {exc.status_code}"
    return "ошибка API"


# Приветствие с именем подставляем сами: имя в модель не уходит, поэтому её «Здравствуйте» убираем.
_LEADING_GREETING = re.compile(r"^(здравствуйте|добрый день|добрый вечер|доброе утро)[!,.]?\s*", re.IGNORECASE)


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, client: Any, model: str = "claude-opus-5-5") -> None:
        self._client = client
        self._model = model

    def _context(self, request: DraftRequest) -> str:
        # Имя покупателя в промпт не попадает: обращение подставляется после ответа модели.
        lines = [f"Тип обращения: {request.kind}"]
        if request.product_title:
            lines.append(f"Товар: {mask_pii(request.product_title)}")
        if request.rating is not None:
            lines.append(f"Оценка: {request.rating} из 5")
        lines.append(f"Последнее сообщение покупателя: {mask_pii(request.last_buyer_text)}")
        return "\n".join(lines)

    def draft_reply(self, request: DraftRequest) -> Draft:
        try:
            response = self._client.beta.messages.create(
                model=self._model,
                max_tokens=1024,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                output_config={"effort": "low"},
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": self._context(request)}],
            )
        except anthropic.APIError as exc:
            raise DraftUnavailable(failure_reason(exc)) from exc

        if response.stop_reason == "refusal":
            raise DraftUnavailable("модель отказалась")
        body = "".join(b.text for b in response.content if getattr(b, "type", None) == "text").strip()
        if not body:
            raise DraftUnavailable("пустой ответ")
        body = _LEADING_GREETING.sub("", body, count=1).strip()[:MAX_DRAFT_CHARS]
        greeting = f"{request.buyer_name}, здравствуйте!" if request.buyer_name else "Здравствуйте!"
        return Draft(text=f"{greeting} {body}", provider=self.name)
