"""Миграции совпадают с моделями: autogenerate не находит расхождений."""

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from app.db import get_engine
from app.models import Base


def test_models_match_migrations():
    with get_engine().connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def test_r2_02_migration_0002_survives_existing_duplicate_active_jobs():
    """R2-02: в базе на ревизии 0001 уже две активные задачи (последствие CR-06) — миграция 0002
    должна оставить активной одну, а не упасть на создании уникального индекса."""
    from alembic import command
    from sqlalchemy import text

    from app import cli

    cfg = cli.alembic_config()
    with get_engine().begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    try:
        command.upgrade(cfg, "0001")
        with get_engine().begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO sync_jobs (status, chats_upserted, messages_inserted, feedback_upserted) "
                    "VALUES ('queued', 0, 0, 0), ('running', 0, 0, 0)"
                )
            )
        command.upgrade(cfg, "head")
        with get_engine().connect() as conn:
            rows = conn.execute(text("SELECT id, status, error FROM sync_jobs ORDER BY id")).all()
    finally:
        # Остальные тесты сессии ждут схему на head — восстанавливаем её при любом исходе.
        with get_engine().begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
        command.upgrade(cfg, "head")
    assert [r.status for r in rows] == ["failed", "running"]
    assert rows[0].error
