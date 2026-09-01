"""Add schema-3 media storage and bounded query indexes.

Revision ID: 20260902_0002
Revises: 20260902_0001
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260902_0002"
down_revision = "20260902_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "avatar_media",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=32), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("height > 0", name="ck_avatar_media_height_positive"),
        sa.CheckConstraint(
            "mime_type = 'image/webp'",
            name="ck_avatar_media_webp",
        ),
        sa.CheckConstraint(
            "length(sha256) = 64",
            name="ck_avatar_media_sha256_length",
        ),
        sa.CheckConstraint(
            "size_bytes > 0",
            name="ck_avatar_media_size_positive",
        ),
        sa.CheckConstraint("width > 0", name="ck_avatar_media_width_positive"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("file_name", name="uq_avatar_media_file_name"),
    )
    op.create_index(
        "ix_conversations_status_date_ended_id",
        "conversations",
        ["status", "date", "ended_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_conversations_child_status_date_ended_id",
        "conversations",
        ["child_id", "status", "date", "ended_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_messages_conversation_id_id",
        "messages",
        ["conversation_id", "id"],
        unique=False,
    )
    op.create_index(
        "ix_analysis_jobs_status_conversation_id",
        "analysis_jobs",
        ["status", "conversation_id"],
        unique=False,
    )
    op.create_index(
        "ix_assessments_status_conversation_id",
        "assessments",
        ["status", "conversation_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_assessments_status_conversation_id",
        table_name="assessments",
    )
    op.drop_index(
        "ix_analysis_jobs_status_conversation_id",
        table_name="analysis_jobs",
    )
    op.drop_index("ix_messages_conversation_id_id", table_name="messages")
    op.drop_index(
        "ix_conversations_child_status_date_ended_id",
        table_name="conversations",
    )
    op.drop_index(
        "ix_conversations_status_date_ended_id",
        table_name="conversations",
    )
    op.drop_table("avatar_media")
