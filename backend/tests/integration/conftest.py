"""Интеграционные тесты: настоящий PostgreSQL по DATABASE_URL. Схема создаётся миграциями."""

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import cli
from app.db import get_engine, get_sessionmaker
from app.marketplaces import get_clients
from app.marketplaces.mock import MockMarketplace
from app.models import Marketplace

if not os.environ.get("DATABASE_URL"):
    pytest.skip("DATABASE_URL не задан — интеграционные тесты пропущены", allow_module_level=True)

TABLES = "messages, chats, feedback, reply_templates, sync_jobs, operators, products"


@pytest.fixture(scope="session", autouse=True)
def _schema() -> None:
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
