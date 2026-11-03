from functools import lru_cache

from app.config import get_settings
from app.marketplaces.base import MarketplaceClient
from app.marketplaces.mock import MockMarketplace
from app.marketplaces.real import OzonClient, WildberriesClient, YandexMarketClient
from app.models import Marketplace


@lru_cache
def get_clients() -> dict[Marketplace, MarketplaceClient]:
    """Клиенты всех площадок. Один экземпляр на процесс: у заглушки состояние в памяти."""
    settings = get_settings()
    if settings.marketplace_mode == "real":
        return {
            Marketplace.WILDBERRIES: WildberriesClient(),
            Marketplace.OZON: OzonClient(),
            Marketplace.YANDEX: YandexMarketClient(),
        }
    return {
        code: MockMarketplace(code, seed=settings.mock_seed, delay_ms=settings.mock_marketplace_delay_ms)
        for code in Marketplace
    }


def get_client(code: str) -> MarketplaceClient:
    return get_clients()[Marketplace(code)]
