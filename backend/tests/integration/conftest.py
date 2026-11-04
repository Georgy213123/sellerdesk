"""Интеграционные тесты: PostgreSQL из TEST_DATABASE_URL (база оканчивается на _test)."""

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import cli
from app.config import get_settings
from app.db import get_engine, get_sessionmaker
from app.marketplaces import get_clients
from app.marketplaces.mock import MockMarketplace
from app.models import Marketplace
from tests.db_guard import NotATestDatabaseError, require_test_database

_test_url = os.environ.get("TEST_DATABASE_URL")
if not _test_url:
    pytest.skip("TEST_DATABASE_URL не задан — интеграционные тесты пропущены", allow_module_level=True)
try:
    require_test_database(_test_url)
except NotATestDatabaseError as exc:
    pytest.exit(str(exc), returncode=3)
# Приложение и тесты работают с одной и той же тестовой базой, рабочий DATABASE_URL не используется.
os.environ["DATABASE_URL"] = _test_url
get_settings.cache_clear()
get_engine.cache_clear()
get_sessionmaker.cache_clear()

TABLES = "agent_runs, messages, chats, feedback, reply_templates, sync_jobs, operators, products"


@pytest.fixture(scope="session", autouse=True)
def _schema() -> None:
    require_test_database(str(get_engine().url.render_as_string(hide_password=False)))
    with get_engine().begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    cli.migrate()


@pytest.fixture(autouse=True)
def _clean(_schema: None) -> Iterator[None]:
    with get_engine().begin() as conn:
        conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
    get_clients.cache_clear()  # свежее состояние заглушек площадок
    with get_sessionmaker()() as s:
        cli.seed(s)
    yield


@pytest.fixture
def session() -> Iterator[Session]:
    with get_sessionmaker()() as s:
        yield s


@pytest.fixture
def synced(session: Session) -> Session:
    cli.sync_now(session)
    return session


@pytest.fixture
def mocks() -> dict[Marketplace, MockMarketplace]:
    return get_clients()  # type: ignore[return-value]


@pytest.fixture
def client() -> Iterator[TestClient]:
    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


@pytest.fixture
def auth(client: TestClient) -> dict[str, str]:
    r = client.post("/api/auth/login", json={"login": "operator", "password": "demo-password"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
