"""Служебные команды: `python -m app.cli migrate|seed|sync|reset|openapi`."""

import argparse
import sys
from pathlib import Path

import yaml
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.catalog import CATALOG
from app.config import get_settings
from app.db import get_engine, get_sessionmaker
from app.marketplaces import get_clients
from app.models import Operator, Product, ReplyTemplate
from app.security import hash_password
from app.sync import sync_all

BACKEND_DIR = Path(__file__).resolve().parent.parent
OPENAPI_PATH = BACKEND_DIR.parent / "docs" / "03-design" / "openapi.yaml"

SEED_TEMPLATES = [
    (
        "Статус заказа",
        "Здравствуйте, {{buyer_name}}! Заказ {{order_number}} передан в доставку, "
        "площадка обновит трекинг в течение суток.\nКоманда «Северный свет»",
    ),
    (
        "Гарантия",
        "Здравствуйте! На «{{product}}» действует гарантия 12 месяцев с даты получения. "
        "Если что-то сломается — напишите сюда.\nКоманда «Северный свет»",
    ),
    (
        "Спасибо за отзыв",
        "{{buyer_name}}, спасибо за отзыв о «{{product}}»! Нам важно, что вы выбрали нас.\nКоманда «Северный свет»",
    ),
]


def alembic_config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return cfg


def migrate() -> None:
    command.upgrade(alembic_config(), "head")


def seed(session: Session) -> None:
    settings = get_settings()
    for sku, title, category in CATALOG:
        if session.get(Product, sku) is None:
            session.add(Product(sku=sku, title=title, category=category))
    login = settings.demo_operator_login
    if session.execute(select(Operator).where(Operator.login == login)).scalar_one_or_none() is None:
        session.add(
            Operator(
                login=login,
                display_name="Оператор Мария",
                password_hash=hash_password(settings.demo_operator_password),
            )
        )
    for name, body in SEED_TEMPLATES:
        if session.execute(select(ReplyTemplate).where(ReplyTemplate.name == name)).scalar_one_or_none() is None:
            session.add(ReplyTemplate(name=name, body=body))
    session.commit()


def sync_now(session: Session) -> None:
    stats = sync_all(session, list(get_clients().values()))
    session.commit()
    print(f"sync: chats={stats.chats_upserted} messages+={stats.messages_inserted} feedback={stats.feedback_upserted}")


def reset() -> None:
    """Чистая демо-база: схема с нуля, сид, одна синхронизация."""
    with get_engine().begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    migrate()
    with get_sessionmaker()() as session:
        seed(session)
        sync_now(session)


def openapi_yaml() -> str:
    from app.main import create_app

    return yaml.safe_dump(create_app().openapi(), allow_unicode=True, sort_keys=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli")
    parser.add_argument("command", choices=["migrate", "seed", "sync", "reset", "bootstrap", "openapi"])
    args = parser.parse_args(argv)
    if args.command == "migrate":
        migrate()
    elif args.command == "seed":
        with get_sessionmaker()() as s:
            seed(s)
    elif args.command == "sync":
        with get_sessionmaker()() as s:
            sync_now(s)
    elif args.command == "bootstrap":
        migrate()
        with get_sessionmaker()() as s:
            seed(s)
            sync_now(s)
    elif args.command == "reset":
        reset()
    elif args.command == "openapi":
        OPENAPI_PATH.parent.mkdir(parents=True, exist_ok=True)
        OPENAPI_PATH.write_text(openapi_yaml(), encoding="utf-8")
        print(f"openapi: {OPENAPI_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
