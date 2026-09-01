"""Guard and run the immutable schema-2 to schema-3 Alembic chain."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import SQLAlchemyError


SCHEMA_2_REVISION = "20260902_0001"
SCHEMA_3_REVISION = "20260902_0002"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_CONFIG_PATH = PROJECT_ROOT / "alembic.ini"
MIGRATIONS_PATH = PROJECT_ROOT / "migrations"

_SCHEMA_2_COLUMNS = {
    "analysis_jobs": {
        "id",
        "conversation_id",
        "frozen_last_message_id",
        "status",
        "attempt_count",
        "max_attempts",
        "available_at",
        "lease_owner",
        "lease_expires_at",
        "last_error_code",
        "last_error_message",
        "started_at",
        "finished_at",
        "created_at",
        "updated_at",
    },
    "assessment_dimensions": {
        "id",
        "key",
        "name",
        "enabled",
        "weight",
        "description",
    },
    "assessment_scores": {
        "id",
        "assessment_id",
        "dimension_id",
        "score",
        "reason",
    },
    "assessments": {"id", "conversation_id", "child_id", "status", "overall"},
    "chat_requests": {
        "request_id",
        "child_id",
        "conversation_id",
        "base_last_message_id",
        "child_message_id",
        "diary_message_id",
        "payload_hash",
        "status",
        "attempt_count",
        "available_at",
        "lease_owner",
        "lease_expires_at",
        "last_error_code",
        "last_error_message",
        "response_json",
        "started_at",
        "finished_at",
        "created_at",
        "updated_at",
    },
    "children": {"id", "name", "nickname", "avatar", "active", "deactivated_at"},
    "conversations": {
        "id",
        "child_id",
        "date",
        "started_at",
        "ended_at",
        "status",
        "end_reason",
        "revision",
        "pending_end_reason",
        "frozen_last_message_id",
    },
    "duck_archives": {"id", "duck_id", "summary", "updated_at"},
    "ducks": {
        "id",
        "name",
        "avatar",
        "status",
        "note",
        "active",
        "deactivated_at",
    },
    "duty_rosters": {"id", "cycle", "date", "child_id"},
    "emotion_logs": {
        "id",
        "conversation_id",
        "child_id",
        "emotion",
        "intensity",
        "note",
        "occurred_at",
    },
    "feeding_logs": {
        "id",
        "conversation_id",
        "child_id",
        "duck_id",
        "category",
        "content",
        "occurred_at",
    },
    "insight_notes": {"id", "conversation_id", "child_id", "content", "created_at"},
    "messages": {"id", "conversation_id", "role", "text", "created_at"},
    "roster_requests": {
        "request_id",
        "operation",
        "payload_hash",
        "status",
        "response_json",
        "last_error_code",
        "last_error_message",
        "created_at",
        "updated_at",
    },
    "teacher_credentials": {
        "id",
        "pin_salt",
        "pin_hash",
        "created_at",
        "updated_at",
    },
    "teacher_sessions": {"id", "token_hash", "created_at"},
}


class SchemaMigrationError(RuntimeError):
    """Base class for fail-closed database startup errors."""


class SchemaFingerprintError(SchemaMigrationError):
    """An unversioned database is not the immutable schema-2 shape."""


class UnsupportedDatabaseRevisionError(SchemaMigrationError):
    """A version table contains an unknown, malformed, or newer revision."""


def _alembic_config(connection) -> Config:
    config = Config(str(ALEMBIC_CONFIG_PATH))
    config.set_main_option("script_location", str(MIGRATIONS_PATH))
    config.attributes["connection"] = connection
    return config


def _require_schema_2_fingerprint(connection) -> None:
    inspector = inspect(connection)
    actual_tables = set(inspector.get_table_names())
    expected_tables = set(_SCHEMA_2_COLUMNS)
    if actual_tables != expected_tables or inspector.get_view_names():
        raise SchemaFingerprintError(
            "database does not match the required schema-2 fingerprint"
        )
    for table, expected_columns in _SCHEMA_2_COLUMNS.items():
        actual_columns = {
            column["name"] for column in inspector.get_columns(table)
        }
        if actual_columns != expected_columns:
            raise SchemaFingerprintError(
                "database does not match the required schema-2 fingerprint"
            )


def _database_action(engine: Engine) -> Literal[
    "upgrade_blank",
    "stamp_schema_2",
    "upgrade_schema_2",
    "current",
]:
    with engine.connect() as connection:
        inspector = inspect(connection)
        tables = set(inspector.get_table_names())
        views = set(inspector.get_view_names())
        if not tables and not views:
            return "upgrade_blank"
        if "alembic_version" not in tables:
            _require_schema_2_fingerprint(connection)
            return "stamp_schema_2"
        try:
            version_columns = {
                column["name"]
                for column in inspector.get_columns("alembic_version")
            }
            revisions = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalars().all()
        except SQLAlchemyError:
            raise UnsupportedDatabaseRevisionError(
                "unsupported database revision"
            ) from None
        if version_columns != {"version_num"} or len(revisions) != 1:
            raise UnsupportedDatabaseRevisionError(
                "unsupported database revision"
            )
        revision = revisions[0]
        if revision == SCHEMA_3_REVISION:
            return "current"
        if revision == SCHEMA_2_REVISION:
            return "upgrade_schema_2"
        raise UnsupportedDatabaseRevisionError(
            "unsupported database revision"
        )


def ensure_database_schema(
    engine: Engine,
    db_mode: Literal["app", "test"],
) -> None:
    """Upgrade app databases safely; test schemas remain fixture-owned."""

    if db_mode == "test":
        return
    if db_mode != "app":
        raise SchemaMigrationError("unsupported database mode")

    action = _database_action(engine)
    if action == "current":
        return
    with engine.connect() as connection:
        config = _alembic_config(connection)
        if action == "stamp_schema_2":
            command.stamp(config, SCHEMA_2_REVISION)
        command.upgrade(config, "head")
