"""Каркасы настоящих адаптеров. В демо не реализованы: нет ключей и нет сети.

Каждый адаптер получает токен из переменной окружения и реализует MarketplaceClient.
Подключение — замена `MARKETPLACE_MODE=mock` на `real` в окружении, код сервисов не меняется.
"""

import os
from datetime import datetime

from app.marketplaces.base import ChatDTO, FeedbackDTO, SentMessage
from app.models import Marketplace


class _NotConfiguredClient:
    code: Marketplace
    token_env: str

    def __init__(self) -> None:
        self.token = os.environ.get(self.token_env)

    def _todo(self) -> None:
        raise NotImplementedError(f"{type(self).__name__}: адаптер не реализован в демо, задайте MARKETPLACE_MODE=mock")

    def fetch_chats(self) -> list[ChatDTO]:
        # TODO: постраничная выгрузка чатов, ретраи с backoff на 429, разбор времени через parse_marketplace_ts.
        self._todo()
        return []

    def fetch_feedback(self) -> list[FeedbackDTO]:
        # TODO: отзывы и вопросы — у площадок это разные методы, объединяются здесь.
        self._todo()
        return []

    def send_chat_message(self, chat_external_id: str, text: str, idempotency_key: str) -> SentMessage:
        # TODO: передать idempotency_key площадке. Если API его не принимает — перед повтором искать
        # своё сообщение в выгрузке чата по тексту и времени, иначе потерянное подтверждение даст дубль.
        self._todo()
        return SentMessage(external_id="", created_at=datetime.min)

    def answer_feedback(self, feedback_external_id: str, text: str) -> None:
        self._todo()


class WildberriesClient(_NotConfiguredClient):
    code = Marketplace.WILDBERRIES
    token_env = "WB_API_TOKEN"  # noqa: S105 — имя переменной окружения, не секрет


class OzonClient(_NotConfiguredClient):
    code = Marketplace.OZON
    token_env = "OZON_API_KEY"  # noqa: S105 — имя переменной окружения, не секрет


class YandexMarketClient(_NotConfiguredClient):
    code = Marketplace.YANDEX
    token_env = "YANDEX_MARKET_TOKEN"  # noqa: S105 — имя переменной окружения, не секрет
