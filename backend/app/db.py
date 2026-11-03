from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


@lru_cache
def get_engine() -> Engine:
    # Сессия БД в UTC: API отдаёт время с +00:00 независимо от зоны сервера.
    return create_engine(get_settings().database_url, pool_pre_ping=True, connect_args={"options": "-c timezone=UTC"})


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """Зависимость FastAPI: одна сессия на запрос."""
    with get_sessionmaker()() as session:
        yield session
