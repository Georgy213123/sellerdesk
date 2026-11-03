"""Одна активная задача синхронизации: частичный уникальный индекс (CR-06).

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-03 22:00:00
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # До этого индекса параллельные запросы могли создать несколько активных задач (CR-06).
    # Оставляем активной самую новую, остальные закрываем с причиной, иначе индекс не создать (R2-02).
    op.execute(
        """
        UPDATE sync_jobs
        SET status = 'failed', finished_at = now(),
            error = 'прервана: дубль активной задачи, закрыта миграцией 0002'
        WHERE status IN ('queued', 'running')
          AND id <> (SELECT max(id) FROM sync_jobs WHERE status IN ('queued', 'running'))
        """
    )
    op.create_index(
        "uq_sync_jobs_one_active",
        "sync_jobs",
        [sa.text("(true)")],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )


def downgrade() -> None:
    op.drop_index("uq_sync_jobs_one_active", table_name="sync_jobs")
