"""Начальная схема: операторы, товары, чаты, сообщения, отзывы, шаблоны, задачи синхронизации.

Revision ID: 0001
Revises:
Create Date: 2026-11-03 20:16:15.975739
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operators",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("login", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("password_hash", sa.String(length=256), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("login"),
    )
    op.create_table(
        "products",
        sa.Column("sku", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("sku"),
    )
    op.create_table(
        "reply_templates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "sync_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("chats_upserted", sa.Integer(), nullable=False),
        sa.Column("messages_inserted", sa.Integer(), nullable=False),
        sa.Column("feedback_upserted", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "chats",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("marketplace", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.String(length=64), nullable=False),
        sa.Column("buyer_name", sa.String(length=128), nullable=True),
        sa.Column("product_sku", sa.String(length=32), nullable=True),
        sa.Column("order_number", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("draft_text", sa.Text(), nullable=True),
        sa.Column("draft_note", sa.Text(), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["product_sku"],
            ["products.sku"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("marketplace", "external_id", name="uq_chats_marketplace_external"),
    )
    op.create_table(
        "feedback",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("marketplace", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("product_sku", sa.String(length=32), nullable=True),
        sa.Column("buyer_name", sa.String(length=128), nullable=True),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("draft_text", sa.Text(), nullable=True),
        sa.Column("draft_note", sa.Text(), nullable=True),
        sa.CheckConstraint("rating IS NULL OR rating BETWEEN 1 AND 5", name="ck_feedback_rating"),
        sa.ForeignKeyConstraint(
            ["product_sku"],
            ["products.sku"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("marketplace", "external_id", name="uq_feedback_marketplace_external"),
    )
    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("chat_id", sa.Integer(), nullable=False),
        sa.Column("external_id", sa.String(length=64), nullable=True),
        sa.Column("author", sa.String(length=16), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chat_id", "external_id", name="uq_messages_chat_external"),
        sa.UniqueConstraint("chat_id", "idempotency_key", name="uq_messages_chat_idem"),
    )
    op.create_index(op.f("ix_messages_chat_id"), "messages", ["chat_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_messages_chat_id"), table_name="messages")
    op.drop_table("messages")
    op.drop_table("feedback")
    op.drop_table("chats")
    op.drop_table("sync_jobs")
    op.drop_table("reply_templates")
    op.drop_table("products")
    op.drop_table("operators")
