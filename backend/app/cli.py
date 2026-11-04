"""Служебные команды: `python -m app.cli migrate|seed|sync|reset|openapi|agent run`."""

import argparse
import sys
from pathlib import Path

import yaml
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.agent import run_agent
from app.catalog import CATALOG
from app.config import get_settings
from app.db import get_engine, get_sessionmaker
from app.db_guard import require_disposable_database
from app.llm.insights import get_insights_provider
from app.marketplaces import get_clients
from app.models import AgentKind, AgentRunStatus, Operator, Product, ReplyTemplate
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
    """Чистая демо-база: схема с нуля, сид, одна синхронизация. Только для баз `*_test` и `*_e2e`."""
    require_disposable_database(get_engine().url.render_as_string(hide_password=False), ("_test", "_e2e"))
    with get_engine().begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    migrate()
    with get_sessionmaker()() as session:
        seed(session)
        sync_now(session)


def ensure_database() -> None:
    """Создаёт одноразовую базу из DATABASE_URL (`*_test` или `*_e2e`), если её ещё нет."""
    url = make_url(get_engine().url.render_as_string(hide_password=False))
    require_disposable_database(url.render_as_string(hide_password=False), ("_test", "_e2e"))
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        if conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": url.database}).scalar() is None:
            conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    admin.dispose()


def agent_run() -> int:
    """Один прогон агента (запускается по таймеру). Код выхода: 0 — готово, 2 — бюджет исчерпан, 1 — ошибка."""
    settings = get_settings()
    status = run_agent(get_sessionmaker(), AgentKind.WEEKLY_INSIGHTS, get_insights_provider(settings), settings)
    if status is None:
        print("agent: не запущен (выключен или прогон ведёт другой процесс)")
        return 0
    print(f"agent: {status}")
    return {AgentRunStatus.SUCCEEDED: 0, AgentRunStatus.BUDGET_EXHAUSTED: 2}.get(status, 1)


def openapi_yaml() -> str:
    from app.main import create_app

    return yaml.safe_dump(create_app().openapi(), allow_unicode=True, sort_keys=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli")
    parser.add_argument(
        "command", choices=["migrate", "seed", "sync", "reset", "ensure-db", "bootstrap", "openapi", "agent"]
    )
    parser.add_argument("action", nargs="?", choices=["run"], help="для agent: run")
    args = parser.parse_args(argv)
    if args.command == "agent":
        if args.action != "run":
            parser.error("agent: нужно действие run")
        return agent_run()
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
    elif args.command == "ensure-db":
        ensure_database()
    elif args.command == "openapi":
        OPENAPI_PATH.parent.mkdir(parents=True, exist_ok=True)
        OPENAPI_PATH.write_text(openapi_yaml(), encoding="utf-8")
        print(f"openapi: {OPENAPI_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
