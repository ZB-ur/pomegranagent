"""Add the schema-3 teacher PIN throttle compatibility state.

Revision ID: 20260905_0003
Revises: 20260902_0002
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260905_0003"
down_revision = "20260902_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    throttle = op.create_table(
        "teacher_pin_throttle",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("failure_timestamps", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "id = 1",
            name="ck_teacher_pin_throttle_singleton",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.bulk_insert(
        throttle,
        [{"id": 1, "failure_timestamps": "[]"}],
    )


def downgrade() -> None:
    op.drop_table("teacher_pin_throttle")
