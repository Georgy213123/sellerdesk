"""AI-черновик ответа. Провайдер за интерфейсом; по умолчанию — детерминированная заглушка без сети.

Правило продукта: черновик никогда не отправляется сам. Сервис только сохраняет его в карточке,
отправляет оператор отдельным действием.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class DraftRequest:
    kind: str  # chat | review | question
    product_title: str | None
    buyer_name: str | None
    rating: int | None
    last_buyer_text: str


@dataclass(frozen=True)
class Draft:
    text: str
    provider: str


class LLMProvider(Protocol):
    name: str

    def draft_reply(self, request: DraftRequest) -> Draft: ...


_TOPICS: list[tuple[tuple[str, ...], str]] = [
    (
        ("приедет", "трекинг", "доставк"),
        "Проверили заказ: он в пути, площадка обновит статус в течение суток.",
    ),
    (
        ("трещин", "разбит", "сломан"),
        "Жаль, что так вышло. Оформите возврат через площадку, мы одобрим его сразу.",
    ),
    (("температур", "тёпл", "тепл"), "Цветовая температура — 3000 K, это тёплый свет."),
    (("гаранти",), "Гарантия на светильник — 12 месяцев с даты получения."),
    (
        ("не включается", "щёлкает", "перестала"),
        "Похоже на неисправность выключателя. Оформите возврат, заменим лампу.",
    ),
    (
        ("инструкци", "сборк", "шатается"),
        "Отправим инструкцию по сборке в этот чат. Шатание обычно уходит после затяжки опоры.",
    ),
    (("цвет",), "Изменить заказ после оформления нельзя, но можно отменить его и оформить заново."),
    (("e27", "вт"), "Подойдут светодиодные лампы E27 до 12 Вт, лампы накаливания — до 40 Вт."),
]


class StubLLMProvider:
    """Шаблонная заглушка: учитывает оценку, товар и ключевые слова последнего сообщения."""

    name = "stub"

    def draft_reply(self, request: DraftRequest) -> Draft:
        greeting = f"{request.buyer_name}, здравствуйте!" if request.buyer_name else "Здравствуйте!"
        product = f"«{request.product_title}»" if request.product_title else "товар"
        lower = request.last_buyer_text.lower()

        if request.kind == "review" and request.rating is not None:
            if request.rating >= 4:
                body = f"Спасибо за отзыв о {product}. Рады, что лампа пришлась к месту."
            elif request.rating == 3:
                body = f"Спасибо за честную оценку {product}. Передали замечания в отдел качества."
            else:
                body = (
                    f"Нам жаль, что {product} вас подвёл. Напишите в чат продавца номер заказа — "
                    "предложим замену или возврат."
                )
        else:
            body = next(
                (answer for keys, answer in _TOPICS if any(k in lower for k in keys)),
                f"Спасибо за вопрос о {product}. Уточним и ответим в течение рабочего дня.",
            )
        return Draft(text=f"{greeting} {body}\nКоманда «Северный свет»", provider=self.name)


def get_llm_provider() -> LLMProvider:
    return StubLLMProvider()
