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
    "analysis_jobs": (
        ("id", "INTEGER", False, None, 1),
        ("conversation_id", "INTEGER", False, None, 0),
        ("frozen_last_message_id", "INTEGER", False, None, 0),
        ("status", "VARCHAR(16)", False, None, 0),
        ("attempt_count", "INTEGER", False, None, 0),
        ("max_attempts", "INTEGER", False, None, 0),
        ("available_at", "DATETIME", False, None, 0),
        ("lease_owner", "VARCHAR(64)", True, None, 0),
        ("lease_expires_at", "DATETIME", True, None, 0),
        ("last_error_code", "VARCHAR(64)", True, None, 0),
        ("last_error_message", "VARCHAR(255)", True, None, 0),
        ("started_at", "DATETIME", True, None, 0),
        ("finished_at", "DATETIME", True, None, 0),
        ("created_at", "DATETIME", False, None, 0),
        ("updated_at", "DATETIME", False, None, 0),
    ),
    "assessment_dimensions": (
        ("id", "INTEGER", False, None, 1),
        ("key", "VARCHAR(32)", False, None, 0),
        ("name", "VARCHAR(64)", False, None, 0),
        ("enabled", "BOOLEAN", False, None, 0),
        ("weight", "FLOAT", False, None, 0),
        ("description", "TEXT", True, None, 0),
    ),
    "assessment_scores": (
        ("id", "INTEGER", False, None, 1),
        ("assessment_id", "INTEGER", False, None, 0),
        ("dimension_id", "INTEGER", False, None, 0),
        ("score", "INTEGER", False, None, 0),
        ("reason", "TEXT", True, None, 0),
    ),
    "assessments": (
        ("id", "INTEGER", False, None, 1),
        ("conversation_id", "INTEGER", False, None, 0),
        ("child_id", "INTEGER", False, None, 0),
        ("status", "VARCHAR(16)", False, None, 0),
        ("overall", "FLOAT", True, None, 0),
    ),
    "chat_requests": (
        ("request_id", "VARCHAR(36)", False, None, 1),
        ("child_id", "INTEGER", False, None, 0),
        ("conversation_id", "INTEGER", True, None, 0),
        ("base_last_message_id", "INTEGER", True, None, 0),
        ("child_message_id", "INTEGER", True, None, 0),
        ("diary_message_id", "INTEGER", True, None, 0),
        ("payload_hash", "VARCHAR(64)", False, None, 0),
        ("status", "VARCHAR(16)", False, None, 0),
        ("attempt_count", "INTEGER", False, None, 0),
        ("available_at", "DATETIME", False, None, 0),
        ("lease_owner", "VARCHAR(64)", True, None, 0),
        ("lease_expires_at", "DATETIME", True, None, 0),
        ("last_error_code", "VARCHAR(64)", True, None, 0),
        ("last_error_message", "VARCHAR(255)", True, None, 0),
        ("response_json", "TEXT", True, None, 0),
        ("started_at", "DATETIME", False, None, 0),
        ("finished_at", "DATETIME", True, None, 0),
        ("created_at", "DATETIME", False, None, 0),
        ("updated_at", "DATETIME", False, None, 0),
    ),
    "children": (
        ("id", "INTEGER", False, None, 1),
        ("name", "VARCHAR(64)", False, None, 0),
        ("nickname", "VARCHAR(64)", True, None, 0),
        ("avatar", "VARCHAR(255)", True, None, 0),
        ("active", "BOOLEAN", False, None, 0),
        ("deactivated_at", "DATETIME", True, None, 0),
    ),
    "conversations": (
        ("id", "INTEGER", False, None, 1),
        ("child_id", "INTEGER", False, None, 0),
        ("date", "VARCHAR(16)", False, None, 0),
        ("started_at", "DATETIME", False, None, 0),
        ("ended_at", "DATETIME", True, None, 0),
        ("status", "VARCHAR(16)", False, None, 0),
        ("end_reason", "VARCHAR(32)", True, None, 0),
        ("revision", "INTEGER", False, None, 0),
        ("pending_end_reason", "VARCHAR(32)", True, None, 0),
        ("frozen_last_message_id", "INTEGER", True, None, 0),
    ),
    "duck_archives": (
        ("id", "INTEGER", False, None, 1),
        ("duck_id", "INTEGER", False, None, 0),
        ("summary", "TEXT", True, None, 0),
        ("updated_at", "DATETIME", False, None, 0),
    ),
    "ducks": (
        ("id", "INTEGER", False, None, 1),
        ("name", "VARCHAR(64)", False, None, 0),
        ("avatar", "VARCHAR(255)", True, None, 0),
        ("status", "VARCHAR(255)", True, None, 0),
        ("note", "TEXT", True, None, 0),
        ("active", "BOOLEAN", False, None, 0),
        ("deactivated_at", "DATETIME", True, None, 0),
    ),
    "duty_rosters": (
        ("id", "INTEGER", False, None, 1),
        ("cycle", "VARCHAR(64)", False, None, 0),
        ("date", "VARCHAR(16)", False, None, 0),
        ("child_id", "INTEGER", False, None, 0),
    ),
    "emotion_logs": (
        ("id", "INTEGER", False, None, 1),
        ("conversation_id", "INTEGER", False, None, 0),
        ("child_id", "INTEGER", False, None, 0),
        ("emotion", "VARCHAR(32)", False, None, 0),
        ("intensity", "INTEGER", False, None, 0),
        ("note", "TEXT", True, None, 0),
        ("occurred_at", "DATETIME", False, None, 0),
    ),
    "feeding_logs": (
        ("id", "INTEGER", False, None, 1),
        ("conversation_id", "INTEGER", False, None, 0),
        ("child_id", "INTEGER", False, None, 0),
        ("duck_id", "INTEGER", True, None, 0),
        ("category", "VARCHAR(32)", False, None, 0),
        ("content", "TEXT", False, None, 0),
        ("occurred_at", "DATETIME", False, None, 0),
    ),
    "insight_notes": (
        ("id", "INTEGER", False, None, 1),
        ("conversation_id", "INTEGER", False, None, 0),
        ("child_id", "INTEGER", False, None, 0),
        ("content", "TEXT", False, None, 0),
        ("created_at", "DATETIME", False, None, 0),
    ),
    "messages": (
        ("id", "INTEGER", False, None, 1),
        ("conversation_id", "INTEGER", False, None, 0),
        ("role", "VARCHAR(16)", False, None, 0),
        ("text", "TEXT", False, None, 0),
        ("created_at", "DATETIME", False, None, 0),
    ),
    "roster_requests": (
        ("request_id", "VARCHAR(36)", False, None, 1),
        ("operation", "VARCHAR(32)", False, None, 0),
        ("payload_hash", "VARCHAR(64)", False, None, 0),
        ("status", "VARCHAR(16)", False, None, 0),
        ("response_json", "TEXT", True, None, 0),
        ("last_error_code", "VARCHAR(64)", True, None, 0),
        ("last_error_message", "VARCHAR(255)", True, None, 0),
        ("created_at", "DATETIME", False, None, 0),
        ("updated_at", "DATETIME", False, None, 0),
    ),
    "teacher_credentials": (
        ("id", "INTEGER", False, None, 1),
        ("pin_salt", "VARCHAR(64)", False, None, 0),
        ("pin_hash", "VARCHAR(128)", False, None, 0),
        ("created_at", "DATETIME", False, None, 0),
        ("updated_at", "DATETIME", False, None, 0),
    ),
    "teacher_sessions": (
        ("id", "INTEGER", False, None, 1),
        ("token_hash", "VARCHAR(64)", False, None, 0),
        ("created_at", "DATETIME", False, None, 0),
    ),
}

_SCHEMA_2_FOREIGN_KEYS = {
    "analysis_jobs": (
        (("conversation_id",), None, "conversations", ("id",), ()),
        (("frozen_last_message_id",), None, "messages", ("id",), ()),
    ),
    "assessment_scores": (
        (("assessment_id",), None, "assessments", ("id",), ()),
        (("dimension_id",), None, "assessment_dimensions", ("id",), ()),
    ),
    "assessments": (
        (("child_id",), None, "children", ("id",), ()),
        (("conversation_id",), None, "conversations", ("id",), ()),
    ),
    "chat_requests": (
        (("base_last_message_id",), None, "messages", ("id",), ()),
        (("child_id",), None, "children", ("id",), ()),
        (("child_message_id",), None, "messages", ("id",), ()),
        (("conversation_id",), None, "conversations", ("id",), ()),
        (("diary_message_id",), None, "messages", ("id",), ()),
    ),
    "conversations": (
        (("child_id",), None, "children", ("id",), ()),
    ),
    "duck_archives": (
        (("duck_id",), None, "ducks", ("id",), ()),
    ),
    "duty_rosters": (
        (("child_id",), None, "children", ("id",), ()),
    ),
    "emotion_logs": (
        (("child_id",), None, "children", ("id",), ()),
        (("conversation_id",), None, "conversations", ("id",), ()),
    ),
    "feeding_logs": (
        (("child_id",), None, "children", ("id",), ()),
        (("conversation_id",), None, "conversations", ("id",), ()),
        (("duck_id",), None, "ducks", ("id",), ()),
    ),
    "insight_notes": (
        (("child_id",), None, "children", ("id",), ()),
        (("conversation_id",), None, "conversations", ("id",), ()),
    ),
    "messages": (
        (("conversation_id",), None, "conversations", ("id",), ()),
    ),
}

_SCHEMA_2_UNIQUES = {
    "analysis_jobs": (("uq_analysis_job_conversation", ("conversation_id",)),),
    "assessment_dimensions": ((None, ("key",)),),
    "assessment_scores": (
        ("uq_assessment_dimension", ("assessment_id", "dimension_id")),
    ),
    "assessments": (("uq_assessment_conversation", ("conversation_id",)),),
    "duty_rosters": (("uq_roster_date_child", ("date", "child_id")),),
    "emotion_logs": (("uq_emotion_conversation", ("conversation_id",)),),
    "insight_notes": (("uq_insight_conversation", ("conversation_id",)),),
}

_SCHEMA_2_INDEXES = {
    "analysis_jobs": (
        ("ix_analysis_jobs_available_at", False, ("available_at",), None),
        ("ix_analysis_jobs_lease_expires_at", False, ("lease_expires_at",), None),
        ("ix_analysis_jobs_status", False, ("status",), None),
    ),
    "chat_requests": (
        ("ix_chat_requests_available_at", False, ("available_at",), None),
        ("ix_chat_requests_lease_expires_at", False, ("lease_expires_at",), None),
        ("ix_chat_requests_status", False, ("status",), None),
    ),
    "conversations": (
        (
            "uq_conversations_child_active",
            True,
            ("child_id",),
            "status = 'active'",
        ),
    ),
    "roster_requests": (
        ("ix_roster_requests_operation", False, ("operation",), None),
        ("ix_roster_requests_status", False, ("status",), None),
    ),
    "teacher_sessions": (
        ("ix_teacher_sessions_token_hash", True, ("token_hash",), None),
    ),
}

_AVATAR_MEDIA_COLUMNS = (
    ("id", "VARCHAR(36)", False, None, 1),
    ("file_name", "VARCHAR(255)", False, None, 0),
    ("mime_type", "VARCHAR(32)", False, None, 0),
    ("width", "INTEGER", False, None, 0),
    ("height", "INTEGER", False, None, 0),
    ("size_bytes", "INTEGER", False, None, 0),
    ("sha256", "VARCHAR(64)", False, None, 0),
    ("created_at", "DATETIME", False, None, 0),
)
_AVATAR_MEDIA_CHECKS = (
    ("ck_avatar_media_height_positive", "height > 0"),
    ("ck_avatar_media_sha256_length", "length(sha256) = 64"),
    ("ck_avatar_media_size_positive", "size_bytes > 0"),
    ("ck_avatar_media_webp", "mime_type = 'image/webp'"),
    ("ck_avatar_media_width_positive", "width > 0"),
)

_SCHEMA_3_COLUMNS = {**_SCHEMA_2_COLUMNS, "avatar_media": _AVATAR_MEDIA_COLUMNS}
_SCHEMA_3_UNIQUES = {
    **_SCHEMA_2_UNIQUES,
    "avatar_media": (("uq_avatar_media_file_name", ("file_name",)),),
}
_SCHEMA_3_INDEXES = {
    **_SCHEMA_2_INDEXES,
    "analysis_jobs": (
        *_SCHEMA_2_INDEXES["analysis_jobs"],
        (
            "ix_analysis_jobs_status_conversation_id",
            False,
            ("status", "conversation_id"),
            None,
        ),
    ),
    "assessments": (
        (
            "ix_assessments_status_conversation_id",
            False,
            ("status", "conversation_id"),
            None,
        ),
    ),
    "conversations": (
        (
            "ix_conversations_child_status_date_ended_id",
            False,
            ("child_id", "status", "date", "ended_at", "id"),
            None,
        ),
        (
            "ix_conversations_status_date_ended_id",
            False,
            ("status", "date", "ended_at", "id"),
            None,
        ),
        *_SCHEMA_2_INDEXES["conversations"],
    ),
    "messages": (
        (
            "ix_messages_conversation_id_id",
            False,
            ("conversation_id", "id"),
            None,
        ),
    ),
}
_SCHEMA_3_CHECKS = {"avatar_media": _AVATAR_MEDIA_CHECKS}
_ALEMBIC_VERSION_SIGNATURE = (
    (("version_num", "VARCHAR(32)", False, None, 1),),
    (),
    (),
    (),
    (),
)


class SchemaMigrationError(RuntimeError):
    """Base class for fail-closed database startup errors."""


class SchemaFingerprintError(SchemaMigrationError):
    """A database does not match the physical schema for its revision."""


class UnsupportedDatabaseRevisionError(SchemaMigrationError):
    """A version table contains an unknown, malformed, or newer revision."""


def _alembic_config(connection) -> Config:
    config = Config(str(ALEMBIC_CONFIG_PATH))
    config.set_main_option("script_location", str(MIGRATIONS_PATH))
    config.attributes["connection"] = connection
    return config


def _normalized_sql(value: object) -> object:
    """Canonicalize SQL structure without changing quoted token contents."""

    if not isinstance(value, str):
        return value

    normalized: list[str] = []
    quote: str | None = None
    pending_space = False
    position = 0
    while position < len(value):
        character = value[position]
        if quote is not None:
            normalized.append(character)
            if character == quote:
                if position + 1 < len(value) and value[position + 1] == quote:
                    normalized.append(value[position + 1])
                    position += 2
                    continue
                quote = None
            position += 1
            continue
        if character in {"'", '"'}:
            if pending_space and normalized:
                normalized.append(" ")
            pending_space = False
            normalized.append(character)
            quote = character
            position += 1
            continue
        if character.isspace():
            pending_space = True
            position += 1
            continue
        if pending_space and normalized:
            normalized.append(" ")
        pending_space = False
        normalized.append(character.lower())
        position += 1
    if quote is not None:
        raise ValueError("unterminated quoted SQL literal")
    return "".join(normalized)


def _sorted_tuple(values) -> tuple:
    return tuple(sorted(values, key=repr))


def _table_signature(inspector, table: str) -> tuple:
    columns = tuple(
        (
            column["name"],
            str(column["type"]).upper(),
            bool(column["nullable"]),
            _normalized_sql(column.get("default")),
            int(column.get("primary_key") or 0),
        )
        for column in inspector.get_columns(table)
    )
    foreign_keys = _sorted_tuple(
        (
            tuple(foreign_key["constrained_columns"]),
            foreign_key.get("referred_schema"),
            foreign_key["referred_table"],
            tuple(foreign_key["referred_columns"]),
            _sorted_tuple(foreign_key.get("options", {}).items()),
        )
        for foreign_key in inspector.get_foreign_keys(table)
    )
    unique_constraints = _sorted_tuple(
        (
            constraint.get("name"),
            tuple(constraint["column_names"]),
        )
        for constraint in inspector.get_unique_constraints(table)
    )
    indexes = _sorted_tuple(
        (
            index["name"],
            bool(index["unique"]),
            tuple(index["column_names"]),
            _normalized_sql(
                str(index.get("dialect_options", {}).get("sqlite_where"))
            )
            if index.get("dialect_options", {}).get("sqlite_where") is not None
            else None,
        )
        for index in inspector.get_indexes(table)
    )
    checks = _sorted_tuple(
        (
            constraint.get("name"),
            _normalized_sql(constraint["sqltext"]),
        )
        for constraint in inspector.get_check_constraints(table)
    )
    return columns, foreign_keys, unique_constraints, indexes, checks


def _expected_table_signature(
    table: str,
    *,
    columns,
    foreign_keys,
    uniques,
    indexes,
    checks,
) -> tuple:
    return (
        columns[table],
        _sorted_tuple(foreign_keys.get(table, ())),
        _sorted_tuple(uniques.get(table, ())),
        _sorted_tuple(indexes.get(table, ())),
        _sorted_tuple(checks.get(table, ())),
    )


def _require_schema_fingerprint(
    connection,
    *,
    revision_label: str,
    columns,
    foreign_keys,
    uniques,
    indexes,
    checks,
    versioned: bool,
) -> None:
    message = f"database does not match the required {revision_label} fingerprint"
    try:
        inspector = inspect(connection)
        expected_tables = set(columns)
        if versioned:
            expected_tables.add("alembic_version")
        if (
            set(inspector.get_table_names()) != expected_tables
            or inspector.get_view_names()
        ):
            raise SchemaFingerprintError(message)
        triggers = connection.execute(
            text(
                "SELECT name FROM sqlite_schema "
                "WHERE type = 'trigger' AND name NOT LIKE 'sqlite_%'"
            )
        ).scalars().all()
        if triggers:
            raise SchemaFingerprintError(message)
        for table in columns:
            if _table_signature(inspector, table) != _expected_table_signature(
                table,
                columns=columns,
                foreign_keys=foreign_keys,
                uniques=uniques,
                indexes=indexes,
                checks=checks,
            ):
                raise SchemaFingerprintError(message)
    except SchemaFingerprintError:
        raise
    except (KeyError, SQLAlchemyError, TypeError, ValueError):
        raise SchemaFingerprintError(message) from None


def _require_schema_2_fingerprint(connection, *, versioned: bool = False) -> None:
    _require_schema_fingerprint(
        connection,
        revision_label="schema-2",
        columns=_SCHEMA_2_COLUMNS,
        foreign_keys=_SCHEMA_2_FOREIGN_KEYS,
        uniques=_SCHEMA_2_UNIQUES,
        indexes=_SCHEMA_2_INDEXES,
        checks={},
        versioned=versioned,
    )


def _require_schema_3_fingerprint(connection) -> None:
    _require_schema_fingerprint(
        connection,
        revision_label="schema-3",
        columns=_SCHEMA_3_COLUMNS,
        foreign_keys=_SCHEMA_2_FOREIGN_KEYS,
        uniques=_SCHEMA_3_UNIQUES,
        indexes=_SCHEMA_3_INDEXES,
        checks=_SCHEMA_3_CHECKS,
        versioned=True,
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
            version_signature = _table_signature(inspector, "alembic_version")
            revisions = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalars().all()
        except SQLAlchemyError:
            raise UnsupportedDatabaseRevisionError(
                "unsupported database revision"
            ) from None
        if version_signature != _ALEMBIC_VERSION_SIGNATURE or len(revisions) != 1:
            raise UnsupportedDatabaseRevisionError(
                "unsupported database revision"
            )
        revision = revisions[0]
        if revision == SCHEMA_3_REVISION:
            _require_schema_3_fingerprint(connection)
            return "current"
        if revision == SCHEMA_2_REVISION:
            _require_schema_2_fingerprint(connection, versioned=True)
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
    if _database_action(engine) != "current":
        raise SchemaFingerprintError(
            "database does not match the required schema-3 fingerprint"
        )
