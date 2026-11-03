"""Заглушка площадки: детерминированные вымышленные чаты, отзывы и вопросы.

Данные генерируются из seed, поэтому каждый запуск даёт один и тот же набор.
Отметки времени отдаются «как у площадки» — в своём формате у каждой (см. TS_FORMAT),
а адаптер приводит их к UTC так же, как это делал бы настоящий клиент.
Каждый вызов спит `delay_ms`: так ведёт себя медленный кабинет, и ради этого в продукте кэш.
"""

import random
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone

from app.catalog import CATALOG
from app.marketplaces.base import ChatDTO, FeedbackDTO, MessageDTO, SentMessage, parse_marketplace_ts
from app.models import Author, FeedbackKind, Marketplace

MSK = timezone(timedelta(hours=3), "MSK")

# Опорная точка вымышленных данных: все события — за неделю до неё.
BASE_TIME = datetime(2026, 10, 30, 18, 0, tzinfo=UTC)

BUYERS = [
    "Анна",
    "Илья",
    "Марина",
    "Олег",
    "Светлана",
    "Денис",
    "Ксения",
    "Павел",
    "Елена",
    "Тимур",
    None,  # площадка скрыла имя покупателя
]

CHAT_TOPICS = [
    ("Когда приедет заказ? В трекинге третий день одно и то же.", "Спасибо, жду."),
    ("Какая цветовая температура у лампы? Нужен тёплый свет для спальни.", None),
    ("Пришла с трещиной на абажуре. Что делать?", "Фото приложил в заявке."),
    ("Подойдёт ли лампа E27 на 12 Вт или будет перегрев?", None),
    ("Можно поменять цвет на чёрный, пока заказ не отправлен?", None),
    ("Есть ли гарантия и сколько?", None),
    ("Не включается после недели работы, кнопка щёлкает впустую.", None),
    ("В комплекте нет инструкции по сборке торшера.", "Собрал по картинке, но шатается."),
]

REVIEW_TEXTS = {
    5: [
        "Свет мягкий, глаза не устают. Беру вторую в детскую.",
        "Собрал за десять минут, выглядит дороже своей цены.",
        "Отличная лампа <img src=x onerror=alert('xss')> всем советую",
    ],
    4: ["Хорошая, но провод короче, чем хотелось бы.", "Всё нравится, только упаковка помята."],
    3: ["Нормально за свои деньги. Абажур пахнет первые дни."],
    2: ["Мигает на минимальной яркости.", "Цвет в жизни темнее, чем на фото."],
    1: ["Пришла разбитой, курьер ничего не знает.", "Через неделю перестала включаться."],
}

QUESTION_TEXTS = [
    "Можно ли повесить на стену?",
    "Какая длина провода?",
    "Лампочка в комплекте?",
    "Подходит ли для натяжного потолка?",
]


# Формат времени у каждой площадки: так выглядят ответы их API.
def _fmt(code: Marketplace, ts: datetime) -> str:
    if code is Marketplace.WILDBERRIES:
        return ts.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if code is Marketplace.OZON:
        return ts.astimezone(MSK).isoformat()
    # Яндекс Маркет в этой заглушке отдаёт время без зоны, по документации — московское.
    return ts.astimezone(MSK).replace(tzinfo=None).isoformat()


@dataclass
class _RawMessage:
    external_id: str
    author: Author
    text: str
    ts: str


@dataclass
class _RawChat:
    external_id: str
    buyer_name: str | None
    product_sku: str
    order_number: str | None
    messages: list[_RawMessage]


@dataclass
class _RawFeedback:
    external_id: str
    kind: FeedbackKind
    product_sku: str
    buyer_name: str | None
    rating: int | None
    text: str
    ts: str
    answer_text: str | None


class MockMarketplace:
    """Площадка-заглушка. Хранит состояние в памяти процесса: отправленные ответы видны в следующей выгрузке."""

    def __init__(self, code: Marketplace, seed: int = 42, delay_ms: int = 0) -> None:
        self.code = code
        self.delay_ms = delay_ms
        self._lock = threading.Lock()
        offset = list(Marketplace).index(code)
        rng = random.Random(seed * 10 + offset)  # noqa: S311 — генератор демо-данных, не криптография
        self._chats = self._gen_chats(rng, offset)
        self._feedback = self._gen_feedback(rng)
        self._sent_by_key: dict[tuple[str, str], SentMessage] = {}
        self.sent_log: list[tuple[str, str]] = []
        # Для тестов: принять отправку и «потерять» подтверждение один раз (таймаут после приёма).
        self.fail_after_accept_once = False

    # --- генерация ---------------------------------------------------------------
    def _prefix(self) -> str:
        return {Marketplace.WILDBERRIES: "wb", Marketplace.OZON: "oz", Marketplace.YANDEX: "ym"}[self.code]

    def _gen_chats(self, rng: random.Random, offset: int) -> list[_RawChat]:
        chats: list[_RawChat] = []
        for i in range(8):
            sku = rng.choice(CATALOG)[0]
            first, follow_up = rng.choice(CHAT_TOPICS)
            # Смещение по площадке ставит события разных площадок вперемешку во времени.
            started = BASE_TIME - timedelta(hours=6 * i + offset * 2, minutes=rng.randint(0, 50))
            messages = [_RawMessage(f"{self._prefix()}-m{i}-1", Author.BUYER, first, _fmt(self.code, started))]
            if follow_up:
                messages.append(
                    _RawMessage(
                        f"{self._prefix()}-m{i}-2",
                        Author.BUYER,
                        follow_up,
                        _fmt(self.code, started + timedelta(minutes=rng.randint(3, 40))),
                    )
                )
            order = f"{self._prefix().upper()}-{rng.randint(100000, 999999)}" if rng.random() < 0.6 else None
            chats.append(_RawChat(f"{self._prefix()}-c{i}", rng.choice(BUYERS), sku, order, messages))
        return chats

    def _gen_feedback(self, rng: random.Random) -> list[_RawFeedback]:
        items: list[_RawFeedback] = []
        for i in range(10):
            rating = rng.choice([5, 5, 4, 4, 3, 2, 1, 1])
            text = rng.choice(REVIEW_TEXTS[rating])
            ts = BASE_TIME - timedelta(hours=9 * i + 1, minutes=rng.randint(0, 59))
            answered = "Спасибо за отзыв!" if rng.random() < 0.25 else None
            items.append(
                _RawFeedback(
                    f"{self._prefix()}-r{i}",
                    FeedbackKind.REVIEW,
                    rng.choice(CATALOG)[0],
                    rng.choice(BUYERS),
                    rating,
                    text,
                    _fmt(self.code, ts),
                    answered,
                )
            )
        for i in range(3):
            ts = BASE_TIME - timedelta(hours=11 * i + 2, minutes=rng.randint(0, 59))
            items.append(
                _RawFeedback(
                    f"{self._prefix()}-q{i}",
                    FeedbackKind.QUESTION,
                    rng.choice(CATALOG)[0],
                    rng.choice(BUYERS),
                    None,
                    rng.choice(QUESTION_TEXTS),
                    _fmt(self.code, ts),
                    None,
                )
            )
        return items

    # --- интерфейс MarketplaceClient ------------------------------------------------
    def _wait(self) -> None:
        if self.delay_ms > 0:
            time.sleep(self.delay_ms / 1000)

    def _parse(self, ts: str) -> datetime:
        return parse_marketplace_ts(ts, default_tz=MSK)

    def fetch_chats(self) -> list[ChatDTO]:
        self._wait()
        with self._lock:
            return [
                ChatDTO(
                    external_id=c.external_id,
                    buyer_name=c.buyer_name,
                    product_sku=c.product_sku,
                    order_number=c.order_number,
                    messages=[MessageDTO(m.external_id, m.author, m.text, self._parse(m.ts)) for m in c.messages],
                )
                for c in self._chats
            ]

    def fetch_feedback(self) -> list[FeedbackDTO]:
        self._wait()
        with self._lock:
            return [
                FeedbackDTO(
                    external_id=f.external_id,
                    kind=f.kind,
                    product_sku=f.product_sku,
                    buyer_name=f.buyer_name,
                    rating=f.rating,
                    text=f.text,
                    created_at=self._parse(f.ts),
                    answer_text=f.answer_text,
                )
                for f in self._feedback
            ]

    def send_chat_message(self, chat_external_id: str, text: str, idempotency_key: str) -> SentMessage:
        """Как API площадки с ключом идемпотентности: повтор с тем же ключом возвращает уже принятое
        сообщение и не отправляет его второй раз (CR-01)."""
        self._wait()
        with self._lock:
            chat = next((c for c in self._chats if c.external_id == chat_external_id), None)
            if chat is None:
                raise KeyError(chat_external_id)
            accepted = self._sent_by_key.get((chat_external_id, idempotency_key))
            if accepted is None:
                now = datetime.now(UTC)
                # Глобально уникальный id, как у площадки: счётчик в памяти после перезапуска
                # процесса повторял уже сохранённые в БД id (CR-03).
                ext = f"{self._prefix()}-out-{uuid.uuid4().hex[:12]}"
                chat.messages.append(_RawMessage(ext, Author.OPERATOR, text, _fmt(self.code, now)))
                self.sent_log.append((chat_external_id, text))
                accepted = SentMessage(external_id=ext, created_at=self._parse(_fmt(self.code, now)))
                self._sent_by_key[(chat_external_id, idempotency_key)] = accepted
            if self.fail_after_accept_once:
                self.fail_after_accept_once = False
                raise TimeoutError("подтверждение площадки не получено")
            return accepted

    def answer_feedback(self, feedback_external_id: str, text: str) -> None:
        self._wait()
        with self._lock:
            item = next((f for f in self._feedback if f.external_id == feedback_external_id), None)
            if item is None:
                raise KeyError(feedback_external_id)
            item.answer_text = text  # ответ на отзыв один: повтор перезаписывает, а не добавляет
            self.sent_log.append((feedback_external_id, text))
            if self.fail_after_accept_once:
                self.fail_after_accept_once = False
                raise TimeoutError("подтверждение площадки не получено")

    # --- для тестов ------------------------------------------------------------------
    def push_buyer_message(self, chat_external_id: str, text: str, ts: datetime) -> None:
        with self._lock:
            chat = next(c for c in self._chats if c.external_id == chat_external_id)
            n = len(chat.messages) + 1
            chat.messages.append(_RawMessage(f"{chat_external_id}-in-{n}", Author.BUYER, text, _fmt(self.code, ts)))
