"""LLM для агента-маркетолога: темы обращений и предложения. Провайдер за интерфейсом, по умолчанию заглушка.

Агент отдаёт модели только обезличенный текст (см. app/llm/pii.py). Каждый метод возвращает
результат и число потраченных токенов: по ним runner держит бюджет прогона.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from app.config import Settings


class InsightsUnavailable(Exception):
    """Провайдер не дал результат. Текст исключения — короткая причина для журнала прогона.

    `tokens` — сколько токенов вызов всё же стоил (отказ модели оплачивается): раннер спишет их.
    """

    def __init__(self, reason: str, tokens: int = 0) -> None:
        super().__init__(reason)
        self.tokens = tokens


@dataclass(frozen=True)
class Case:
    """Обращение покупателя без ПД. `ref` — ссылка на строку в БД: `feedback:12` или `message:5`."""

    ref: str
    kind: str  # review | question | chat
    rating: int | None
    text: str


@dataclass(frozen=True)
class Theme:
    key: str
    title: str
    refs: list[str]


KnownTheme = tuple[str, str]  # (ключ, название) темы, уже найденной в прошлых пачках


@dataclass(frozen=True)
class ThemeBrief:
    key: str
    title: str
    count: int
    examples: list[str]


@dataclass(frozen=True)
class ProposalDraft:
    kind: str  # reply_template | card_edit
    title: str
    body: str


class InsightsProvider(Protocol):
    name: str
    # Потолок ответа за один вызов: на него runner резервирует бюджет до вызова.
    max_output_tokens: int

    def classify(self, batch: Sequence[Case], known: Sequence[KnownTheme] = ()) -> tuple[list[Theme], int]: ...

    def propose(self, theme: ThemeBrief) -> tuple[ProposalDraft, int]: ...


@dataclass(frozen=True)
class _StubTheme:
    key: str
    title: str
    keywords: tuple[str, ...]
    kind: str
    proposal_title: str
    proposal_body: str


_SIGNATURE = "\nКоманда «Северный свет»"
_STUB_THEMES = [
    _StubTheme(
        "delivery",
        "Долгая доставка",
        ("приедет", "трекинг", "доставк"),
        "reply_template",
        "Задержка доставки",
        "Здравствуйте, {{buyer_name}}! Заказ {{order_number}} в пути, площадка обновит трекинг в течение суток."
        + _SIGNATURE,
    ),
    _StubTheme(
        "damaged",
        "Пришло повреждённым",
        ("трещин", "разбит", "помят"),
        "card_edit",
        "Усилить упаковку и сказать об этом в карточке",
        "Добавить в описание: «Хрупкие детали упакованы в пенный короб. Если товар пришёл повреждённым, "
        "оформите возврат через площадку».",
    ),
    _StubTheme(
        "malfunction",
        "Не включается или мигает",
        ("не включается", "щёлкает", "перестала", "мигает"),
        "reply_template",
        "Лампа не включается",
        "Здравствуйте, {{buyer_name}}! Похоже на неисправность выключателя. Оформите возврат через площадку, "
        "заменим «{{product}}»." + _SIGNATURE,
    ),
    _StubTheme(
        "assembly",
        "Сборка и инструкция",
        ("инструкци", "сборк", "шатается"),
        "card_edit",
        "Добавить в карточку инструкцию по сборке",
        "Приложить к карточке схему сборки и написать: «Опору затяните до упора, после этого конструкция не шатается».",
    ),
    _StubTheme(
        "color",
        "Цвет не совпал с ожиданием",
        ("цвет",),
        "card_edit",
        "Уточнить цвет в описании",
        "Добавить в описание: «Цвет на фото может отличаться от реального из-за подсветки экрана».",
    ),
    _StubTheme(
        "warranty",
        "Вопросы по гарантии",
        ("гаранти",),
        "reply_template",
        "Гарантия на товар",
        "Здравствуйте! На «{{product}}» действует гарантия 12 месяцев с даты получения." + _SIGNATURE,
    ),
]


def _stub_tokens(*texts: str) -> int:
    """Условная стоимость вызова: токен на четыре символа плюс накладные расходы."""
    return 20 + sum(len(t) for t in texts) // 4


class StubInsightsProvider:
    """Заглушка по ключевым словам: детерминированная, без сети, токены считает по длине текста."""

    name = "stub"
    max_output_tokens = 512

    def classify(self, batch: Sequence[Case], known: Sequence[KnownTheme] = ()) -> tuple[list[Theme], int]:
        refs: dict[str, list[str]] = {}
        for case in batch:
            lower = case.text.lower()
            theme = next((t for t in _STUB_THEMES if any(k in lower for k in t.keywords)), None)
            if theme:
                refs.setdefault(theme.key, []).append(case.ref)
        titles = {t.key: t.title for t in _STUB_THEMES}
        return [Theme(key, titles[key], found) for key, found in refs.items()], _stub_tokens(*(c.text for c in batch))

    def propose(self, theme: ThemeBrief) -> tuple[ProposalDraft, int]:
        spec = next((t for t in _STUB_THEMES if t.key == theme.key), None)
        if spec is None:
            raise InsightsUnavailable(f"заглушка не знает тему {theme.key}")
        draft = ProposalDraft(spec.kind, spec.proposal_title, spec.proposal_body)
        return draft, _stub_tokens(theme.title, *theme.examples)


@lru_cache
def _build(provider: str, model: str, timeout_s: float) -> InsightsProvider:
    if provider == "anthropic":
        import anthropic

        from app.llm.anthropic_insights import AnthropicInsights

        client = anthropic.Anthropic(timeout=timeout_s, max_retries=2)
        return AnthropicInsights(client, model=model)
    return StubInsightsProvider()


def get_insights_provider(settings: "Settings | None" = None) -> InsightsProvider:
    if settings is None:
        from app.config import get_settings

        settings = get_settings()
    return _build(settings.llm_provider, settings.llm_model, settings.llm_timeout_s)
