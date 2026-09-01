"""Immutable schema-2 baseline.

Revision ID: 20260902_0001
Revises: None
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260902_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assessment_dimensions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    op.create_table(
        "children",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("nickname", sa.String(length=64), nullable=True),
        sa.Column("avatar", sa.String(length=255), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("deactivated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "ducks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("avatar", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=255), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("deactivated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "roster_requests",
        sa.Column("request_id", sa.String(length=36), nullable=False),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("response_json", sa.Text(), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("last_error_message", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("request_id"),
    )
    op.create_index(
        "ix_roster_requests_operation",
        "roster_requests",
        ["operation"],
        unique=False,
    )
    op.create_index(
        "ix_roster_requests_status",
        "roster_requests",
        ["status"],
        unique=False,
    )
    op.create_table(
        "teacher_credentials",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pin_salt", sa.String(length=64), nullable=False),
        sa.Column("pin_hash", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "teacher_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_teacher_sessions_token_hash",
        "teacher_sessions",
        ["token_hash"],
        unique=True,
    )
    op.create_table(
        "conversations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("child_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("end_reason", sa.String(length=32), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("pending_end_reason", sa.String(length=32), nullable=True),
        sa.Column("frozen_last_message_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["child_id"], ["children.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_conversations_child_active",
        "conversations",
        ["child_id"],
        unique=True,
        sqlite_where=sa.text("status = 'active'"),
    )
    op.create_table(
        "duck_archives",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("duck_id", sa.Integer(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["duck_id"], ["ducks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "duty_rosters",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("cycle", sa.String(length=64), nullable=False),
        sa.Column("date", sa.String(length=16), nullable=False),
        sa.Column("child_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["child_id"], ["children.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("date", "child_id", name="uq_roster_date_child"),
    )
    op.create_table(
        "assessments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("child_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("overall", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["child_id"], ["children.id"]),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("conversation_id", name="uq_assessment_conversation"),
    )
    op.create_table(
        "emotion_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("child_id", sa.Integer(), nullable=False),
        sa.Column("emotion", sa.String(length=32), nullable=False),
        sa.Column("intensity", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["child_id"], ["children.id"]),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("conversation_id", name="uq_emotion_conversation"),
    )
    op.create_table(
        "feeding_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("child_id", sa.Integer(), nullable=False),
        sa.Column("duck_id", sa.Integer(), nullable=True),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["child_id"], ["children.id"]),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
        sa.ForeignKeyConstraint(["duck_id"], ["ducks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "insight_notes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("child_id", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["child_id"], ["children.id"]),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("conversation_id", name="uq_insight_conversation"),
    )
    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "analysis_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("frozen_last_message_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(), nullable=False),
        sa.Column("lease_owner", sa.String(length=64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("last_error_message", sa.String(length=255), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
        sa.ForeignKeyConstraint(["frozen_last_message_id"], ["messages.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("conversation_id", name="uq_analysis_job_conversation"),
    )
    op.create_index(
        "ix_analysis_jobs_available_at",
        "analysis_jobs",
        ["available_at"],
        unique=False,
    )
    op.create_index(
        "ix_analysis_jobs_lease_expires_at",
        "analysis_jobs",
        ["lease_expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_analysis_jobs_status",
        "analysis_jobs",
        ["status"],
        unique=False,
    )
    op.create_table(
        "assessment_scores",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("assessment_id", sa.Integer(), nullable=False),
        sa.Column("dimension_id", sa.Integer(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["assessment_id"], ["assessments.id"]),
        sa.ForeignKeyConstraint(
            ["dimension_id"],
            ["assessment_dimensions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "assessment_id",
            "dimension_id",
            name="uq_assessment_dimension",
        ),
    )
    op.create_table(
        "chat_requests",
        sa.Column("request_id", sa.String(length=36), nullable=False),
        sa.Column("child_id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=True),
        sa.Column("base_last_message_id", sa.Integer(), nullable=True),
        sa.Column("child_message_id", sa.Integer(), nullable=True),
        sa.Column("diary_message_id", sa.Integer(), nullable=True),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(), nullable=False),
        sa.Column("lease_owner", sa.String(length=64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("last_error_message", sa.String(length=255), nullable=True),
        sa.Column("response_json", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["base_last_message_id"], ["messages.id"]),
        sa.ForeignKeyConstraint(["child_id"], ["children.id"]),
        sa.ForeignKeyConstraint(["child_message_id"], ["messages.id"]),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
        sa.ForeignKeyConstraint(["diary_message_id"], ["messages.id"]),
        sa.PrimaryKeyConstraint("request_id"),
    )
    op.create_index(
        "ix_chat_requests_available_at",
        "chat_requests",
        ["available_at"],
        unique=False,
    )
    op.create_index(
        "ix_chat_requests_lease_expires_at",
        "chat_requests",
        ["lease_expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_chat_requests_status",
        "chat_requests",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_chat_requests_status", table_name="chat_requests")
    op.drop_index("ix_chat_requests_lease_expires_at", table_name="chat_requests")
    op.drop_index("ix_chat_requests_available_at", table_name="chat_requests")
    op.drop_table("chat_requests")
    op.drop_table("assessment_scores")
    op.drop_index("ix_analysis_jobs_status", table_name="analysis_jobs")
    op.drop_index("ix_analysis_jobs_lease_expires_at", table_name="analysis_jobs")
    op.drop_index("ix_analysis_jobs_available_at", table_name="analysis_jobs")
    op.drop_table("analysis_jobs")
    op.drop_table("messages")
    op.drop_table("insight_notes")
    op.drop_table("feeding_logs")
    op.drop_table("emotion_logs")
    op.drop_table("assessments")
    op.drop_table("duty_rosters")
    op.drop_table("duck_archives")
    op.drop_index("uq_conversations_child_active", table_name="conversations")
    op.drop_table("conversations")
    op.drop_index(
        "ix_teacher_sessions_token_hash",
        table_name="teacher_sessions",
    )
    op.drop_table("teacher_sessions")
    op.drop_table("teacher_credentials")
    op.drop_index("ix_roster_requests_status", table_name="roster_requests")
    op.drop_index("ix_roster_requests_operation", table_name="roster_requests")
    op.drop_table("roster_requests")
    op.drop_table("ducks")
    op.drop_table("children")
    op.drop_table("assessment_dimensions")
