"""Настройки приложения. Читаются только из переменных окружения (и .env для локального запуска)."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://sellerdesk:sellerdesk@localhost:55101/sellerdesk"

    # Подпись JWT. Значение по умолчанию годится только для демо-стенда.
    jwt_secret: str = "demo-only-change-me-0123456789abcdef"  # noqa: S105 — демо-значение, в окружении задаётся своё
    jwt_ttl_minutes: int = 480

    # Учётка оператора из сида. Пароль задаётся окружением, в коде только демо-значение.
    demo_operator_login: str = "operator"
    demo_operator_password: str = "demo-password"  # noqa: S105 — пароль демо-учётки из .env.example

    # mock — заглушки площадок с вымышленными данными; real — классы-адаптеры (не реализованы).
    marketplace_mode: Literal["mock", "real"] = "mock"
    # Искусственная задержка заглушки на каждый вызов «площадки», мс.
    mock_marketplace_delay_ms: int = 800
    mock_seed: int = 42

    llm_provider: Literal["stub"] = "stub"

    # Задача синхронизации, не завершившаяся за это время, считается прерванной (процесс упал).
    sync_job_stale_after_s: int = 600

    cors_origins: str = "http://localhost:5101,http://127.0.0.1:5101"


@lru_cache
def get_settings() -> Settings:
    return Settings()
