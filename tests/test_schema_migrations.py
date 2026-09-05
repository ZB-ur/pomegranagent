"""Guarded schema-2 to schema-3 Alembic migration contracts."""
from __future__ import annotations

import asyncio
from pathlib import Path
import sqlite3
import subprocess
import sys
import textwrap

from alembic import command
from alembic.config import Config
from fastapi import FastAPI
import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session

from app.backend import models
from app.backend.schema_migrations import (
    SCHEMA_2_REVISION,
    SCHEMA_3_REVISION,
    SchemaFingerprintError,
    UnsupportedDatabaseRevisionError,
    _normalized_sql,
    ensure_database_schema,
)
from app.backend.versioning import load_runtime_version


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_2_FIXTURE = ROOT / "tests" / "fixtures" / "schema_2.sql"
SCHEMA_2_TABLES = {
    "analysis_jobs",
    "assessment_dimensions",
    "assessment_scores",
    "assessments",
    "chat_requests",
    "children",
    "conversations",
    "duck_archives",
    "ducks",
    "duty_rosters",
    "emotion_logs",
    "feeding_logs",
    "insight_notes",
    "messages",
    "roster_requests",
    "teacher_credentials",
    "teacher_sessions",
}
SCHEMA_3_INDEXES = {
    "ix_conversations_status_date_ended_id": (
        "status",
        "date",
        "ended_at",
        "id",
    ),
    "ix_conversations_child_status_date_ended_id": (
        "child_id",
        "status",
        "date",
        "ended_at",
        "id",
    ),
    "ix_messages_conversation_id_id": ("conversation_id", "id"),
    "ix_analysis_jobs_status_conversation_id": ("status", "conversation_id"),
    "ix_assessments_status_conversation_id": ("status", "conversation_id"),
}
AVATAR_MEDIA_COLUMNS = (
    ("id", "VARCHAR(36)", False, None, 1),
    ("file_name", "VARCHAR(255)", False, None, 0),
    ("mime_type", "VARCHAR(32)", False, None, 0),
    ("width", "INTEGER", False, None, 0),
    ("height", "INTEGER", False, None, 0),
    ("size_bytes", "INTEGER", False, None, 0),
    ("sha256", "VARCHAR(64)", False, None, 0),
    ("created_at", "DATETIME", False, None, 0),
)
AVATAR_MEDIA_CHECKS = (
    ("ck_avatar_media_height_positive", "height > 0"),
    ("ck_avatar_media_sha256_length", "length(sha256) = 64"),
    ("ck_avatar_media_size_positive", "size_bytes > 0"),
    ("ck_avatar_media_webp", "mime_type = 'image/webp'"),
    ("ck_avatar_media_width_positive", "width > 0"),
)
PIN_THROTTLE_COLUMNS = (
    ("id", "INTEGER", False, None, 1),
    ("failure_timestamps", "TEXT", False, None, 0),
)
PIN_THROTTLE_CHECKS = (
    ("ck_teacher_pin_throttle_singleton", "id = 1"),
)


def engine_for(database: Path):
    return create_engine(
        f"sqlite:///{database}",
        connect_args={"check_same_thread": False},
    )


def load_schema_2_fixture(database: Path) -> Path:
    database.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database) as connection:
        connection.executescript(SCHEMA_2_FIXTURE.read_text(encoding="utf-8"))
    return database


def run_alembic(database: Path, operation: str, revision: str) -> None:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    getattr(command, operation)(config, revision)


def create_version_table(
    database: Path,
    revisions: tuple[str, ...],
    *,
    primary_key: bool = True,
) -> None:
    primary_key_sql = " PRIMARY KEY" if primary_key else ""
    with sqlite3.connect(database) as connection:
        connection.execute(
            f"""
            CREATE TABLE alembic_version (
                version_num VARCHAR(32) NOT NULL{primary_key_sql}
            )
            """
        )
        connection.executemany(
            "INSERT INTO alembic_version (version_num) VALUES (?)",
            ((revision,) for revision in revisions),
        )


def stamp_database(database: Path, revision: str) -> None:
    create_version_table(database, (revision,))


def partial_index_predicate(index_sql: str) -> str:
    """Extract WHERE without normalizing any quoted or unquoted SQL text."""

    quote: str | None = None
    position = 0
    while position < len(index_sql):
        character = index_sql[position]
        if quote is not None:
            if character == quote:
                if (
                    position + 1 < len(index_sql)
                    and index_sql[position + 1] == quote
                ):
                    position += 2
                    continue
                quote = None
            position += 1
            continue
        if character in {"'", '"'}:
            quote = character
            position += 1
            continue
        if index_sql[position : position + 5].upper() == "WHERE":
            before = index_sql[position - 1] if position else " "
            after_position = position + 5
            after = (
                index_sql[after_position]
                if after_position < len(index_sql)
                else " "
            )
            if not (before.isalnum() or before == "_") and not (
                after.isalnum() or after == "_"
            ):
                return index_sql[after_position:].strip()
        position += 1
    raise AssertionError(f"partial index has no WHERE clause: {index_sql}")


def physical_schema_signature(
    database: Path,
    *,
    excluded_tables: set[str] | None = None,
    excluded_indexes: set[str] | None = None,
) -> dict[str, dict[str, tuple[object, ...]]]:
    """Inspect persisted SQLite structure without importing migration code."""

    excluded_tables = excluded_tables or set()
    excluded_indexes = excluded_indexes or set()
    signature: dict[str, dict[str, tuple[object, ...]]] = {}
    with sqlite3.connect(database) as connection:
        table_names = [
            row[0]
            for row in connection.execute(
                """
                SELECT name
                FROM sqlite_schema
                WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                ORDER BY name
                """
            ).fetchall()
            if row[0] not in excluded_tables
        ]
        for table in table_names:
            columns = tuple(
                (
                    row[1],
                    row[2].upper(),
                    not bool(row[3]),
                    row[4],
                    row[5],
                )
                for row in connection.execute(
                    f'PRAGMA table_info("{table}")'
                ).fetchall()
            )
            foreign_keys = tuple(sorted(
                (
                    row[3],
                    row[2],
                    row[4],
                    row[5].lower(),
                    row[6].lower(),
                    row[7].lower(),
                )
                for row in connection.execute(
                    f'PRAGMA foreign_key_list("{table}")'
                ).fetchall()
            ))
            unique_constraints: list[tuple[str, ...]] = []
            indexes: list[tuple[object, ...]] = []
            for index_row in connection.execute(
                f'PRAGMA index_list("{table}")'
            ).fetchall():
                _, name, unique, origin, partial = index_row[:5]
                index_columns = tuple(
                    row[2]
                    for row in connection.execute(
                        f'PRAGMA index_info("{name}")'
                    ).fetchall()
                )
                if origin == "u":
                    unique_constraints.append(index_columns)
                    continue
                if origin == "pk" or name in excluded_indexes:
                    continue
                index_sql_row = connection.execute(
                    "SELECT sql FROM sqlite_schema WHERE type = 'index' AND name = ?",
                    (name,),
                ).fetchone()
                predicate = None
                if partial and index_sql_row and isinstance(index_sql_row[0], str):
                    predicate = partial_index_predicate(index_sql_row[0])
                indexes.append(
                    (name, bool(unique), index_columns, bool(partial), predicate)
                )
            signature[table] = {
                "columns": columns,
                "foreign_keys": foreign_keys,
                "unique_constraints": tuple(sorted(unique_constraints)),
                "indexes": tuple(sorted(indexes)),
            }

    engine = engine_for(database)
    try:
        inspector = inspect(engine)
        for table in signature:
            signature[table]["checks"] = tuple(sorted(
                (
                    constraint["name"],
                    constraint["sqltext"].strip(),
                )
                for constraint in inspector.get_check_constraints(table)
            ))
    finally:
        engine.dispose()
    return signature


@pytest.fixture
def schema_two_signature(tmp_path: Path):
    reference = load_schema_2_fixture(tmp_path / "frozen-schema-2.db")
    return physical_schema_signature(reference)


def scalar(database: Path, statement: str):
    with sqlite3.connect(database) as connection:
        row = connection.execute(statement).fetchone()
    return None if row is None else row[0]


def schema_snapshot(database: Path) -> list[tuple[object, ...]]:
    with sqlite3.connect(database) as connection:
        return connection.execute(
            """
            SELECT type, name, tbl_name, sql
            FROM sqlite_schema
            WHERE name NOT LIKE 'sqlite_%'
            ORDER BY type, name
            """
        ).fetchall()


def table_rows(database: Path, tables: set[str]) -> dict[str, list[tuple[object, ...]]]:
    with sqlite3.connect(database) as connection:
        return {
            table: connection.execute(f'SELECT * FROM "{table}" ORDER BY 1').fetchall()
            for table in sorted(tables)
        }


def index_columns(database: Path, index_name: str) -> tuple[str, ...]:
    with sqlite3.connect(database) as connection:
        rows = connection.execute(f'PRAGMA index_info("{index_name}")').fetchall()
    return tuple(row[2] for row in rows)


def remove_ducks_note(database: Path) -> None:
    with sqlite3.connect(database) as connection:
        connection.execute("ALTER TABLE ducks DROP COLUMN note")


def add_ducks_column(database: Path) -> None:
    with sqlite3.connect(database) as connection:
        connection.execute("ALTER TABLE ducks ADD COLUMN unexpected_note TEXT")


def add_unexpected_table(database: Path) -> None:
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE unexpected_extension (id INTEGER PRIMARY KEY)")


def replace_partial_index(database: Path) -> None:
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            DROP INDEX uq_conversations_child_active;
            CREATE UNIQUE INDEX uq_conversations_child_active
                ON conversations (child_id) WHERE status = 'ended';
            """
        )


def replace_partial_index_literal_case(database: Path) -> None:
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            DROP INDEX uq_conversations_child_active;
            CREATE UNIQUE INDEX uq_conversations_child_active
                ON conversations (child_id) WHERE status = 'ACTIVE';
            """
        )


def remove_duck_archive_foreign_key(database: Path) -> None:
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            PRAGMA foreign_keys = OFF;
            ALTER TABLE duck_archives RENAME TO old_duck_archives;
            CREATE TABLE duck_archives (
                id INTEGER NOT NULL,
                duck_id INTEGER NOT NULL,
                summary TEXT,
                updated_at DATETIME NOT NULL,
                PRIMARY KEY (id)
            );
            INSERT INTO duck_archives SELECT * FROM old_duck_archives;
            DROP TABLE old_duck_archives;
            """
        )


def remove_roster_unique_constraint(database: Path) -> None:
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            PRAGMA foreign_keys = OFF;
            ALTER TABLE duty_rosters RENAME TO old_duty_rosters;
            CREATE TABLE duty_rosters (
                id INTEGER NOT NULL,
                cycle VARCHAR(64) NOT NULL,
                date VARCHAR(16) NOT NULL,
                child_id INTEGER NOT NULL,
                PRIMARY KEY (id),
                FOREIGN KEY(child_id) REFERENCES children (id)
            );
            INSERT INTO duty_rosters SELECT * FROM old_duty_rosters;
            DROP TABLE old_duty_rosters;
            """
        )


def replace_schema_three_index(database: Path) -> None:
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            DROP INDEX ix_messages_conversation_id_id;
            CREATE INDEX ix_messages_conversation_id_id
                ON messages (conversation_id);
            """
        )


def remove_avatar_constraints(database: Path) -> None:
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            ALTER TABLE avatar_media RENAME TO old_avatar_media;
            CREATE TABLE avatar_media (
                id VARCHAR(36) NOT NULL,
                file_name VARCHAR(255) NOT NULL,
                mime_type VARCHAR(32) NOT NULL,
                width INTEGER NOT NULL,
                height INTEGER NOT NULL,
                size_bytes INTEGER NOT NULL,
                sha256 VARCHAR(64) NOT NULL,
                created_at DATETIME NOT NULL,
                PRIMARY KEY (id)
            );
            INSERT INTO avatar_media SELECT * FROM old_avatar_media;
            DROP TABLE old_avatar_media;
            """
        )


def replace_avatar_check_literal_case(database: Path) -> None:
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            ALTER TABLE avatar_media RENAME TO old_avatar_media;
            CREATE TABLE avatar_media (
                id VARCHAR(36) NOT NULL,
                file_name VARCHAR(255) NOT NULL,
                mime_type VARCHAR(32) NOT NULL,
                width INTEGER NOT NULL,
                height INTEGER NOT NULL,
                size_bytes INTEGER NOT NULL,
                sha256 VARCHAR(64) NOT NULL,
                created_at DATETIME NOT NULL,
                CONSTRAINT ck_avatar_media_height_positive CHECK (height > 0),
                CONSTRAINT ck_avatar_media_webp
                    CHECK (mime_type = 'IMAGE/WEBP'),
                CONSTRAINT ck_avatar_media_sha256_length
                    CHECK (length(sha256) = 64),
                CONSTRAINT ck_avatar_media_size_positive CHECK (size_bytes > 0),
                CONSTRAINT ck_avatar_media_width_positive CHECK (width > 0),
                PRIMARY KEY (id),
                CONSTRAINT uq_avatar_media_file_name UNIQUE (file_name)
            );
            INSERT INTO avatar_media SELECT * FROM old_avatar_media;
            DROP TABLE old_avatar_media;
            """
        )


def assert_schema_three_shape(
    database: Path,
    schema_two_signature: dict[str, dict[str, tuple[object, ...]]],
) -> None:
    historical_signature = physical_schema_signature(
        database,
        excluded_tables={
            "alembic_version",
            "avatar_media",
            "teacher_pin_throttle",
        },
        excluded_indexes=set(SCHEMA_3_INDEXES),
    )
    assert historical_signature == schema_two_signature

    engine = engine_for(database)
    try:
        inspector = inspect(engine)
        assert set(inspector.get_table_names()) == {
            *SCHEMA_2_TABLES,
            "alembic_version",
            "avatar_media",
            "teacher_pin_throttle",
        }
        compatibility_tables = physical_schema_signature(
            database,
            excluded_tables={*SCHEMA_2_TABLES, "alembic_version"},
        )
        assert compatibility_tables["avatar_media"] == {
            "columns": AVATAR_MEDIA_COLUMNS,
            "foreign_keys": (),
            "unique_constraints": (("file_name",),),
            "indexes": (),
            "checks": AVATAR_MEDIA_CHECKS,
        }
        assert compatibility_tables["teacher_pin_throttle"] == {
            "columns": PIN_THROTTLE_COLUMNS,
            "foreign_keys": (),
            "unique_constraints": (),
            "indexes": (),
            "checks": PIN_THROTTLE_CHECKS,
        }
    finally:
        engine.dispose()
    for name, columns in SCHEMA_3_INDEXES.items():
        assert index_columns(database, name) == columns


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        ("  STATUS  =  'AcTiVe'  ", "status = 'AcTiVe'"),
        (
            "note = 'O''Brien' AND label = \"MiX\"",
            "note = 'O''Brien' and label = \"MiX\"",
        ),
        ("note = 'two  spaces'", "note = 'two  spaces'"),
        ("label = \"A\"\"B\"", "label = \"A\"\"B\""),
    ],
)
def test_sql_normalizer_preserves_quoted_literal_content(
    sql: str,
    expected: str,
):
    assert _normalized_sql(sql) == expected


def test_blank_database_upgrades_from_baseline_to_schema_three(
    tmp_path: Path,
    schema_two_signature,
):
    database = tmp_path / "blank.db"
    engine = engine_for(database)
    try:
        ensure_database_schema(engine, db_mode="app")
    finally:
        engine.dispose()

    assert scalar(database, "SELECT version_num FROM alembic_version") == (
        SCHEMA_3_REVISION
    )
    assert_schema_three_shape(database, schema_two_signature)


def test_schema_three_head_initializes_singleton_teacher_pin_throttle(
    tmp_path: Path,
):
    database = tmp_path / "pin-throttle-head.db"
    engine = engine_for(database)
    try:
        ensure_database_schema(engine, db_mode="app")
    finally:
        engine.dispose()

    signature = physical_schema_signature(
        database,
        excluded_tables={
            table
            for table in SCHEMA_2_TABLES | {"alembic_version", "avatar_media"}
        },
    )
    assert signature["teacher_pin_throttle"] == {
        "columns": PIN_THROTTLE_COLUMNS,
        "foreign_keys": (),
        "unique_constraints": (),
        "indexes": (),
        "checks": PIN_THROTTLE_CHECKS,
    }
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT id, failure_timestamps FROM teacher_pin_throttle"
        ).fetchall() == [(1, "[]")]
    assert load_runtime_version().schema_version == "3"


def test_blank_baseline_matches_complete_frozen_schema_two_signature(
    tmp_path: Path,
    schema_two_signature,
):
    database = tmp_path / "blank-baseline.db"

    run_alembic(database, "upgrade", SCHEMA_2_REVISION)

    assert scalar(database, "SELECT version_num FROM alembic_version") == (
        SCHEMA_2_REVISION
    )
    assert physical_schema_signature(
        database,
        excluded_tables={"alembic_version"},
    ) == schema_two_signature


def test_baseline_upgrade_does_not_import_the_current_orm(tmp_path: Path):
    database = tmp_path / "self-contained.db"
    code = textwrap.dedent(
        """
        import sys
        from sqlalchemy import create_engine

        class RejectCurrentModels:
            def find_spec(self, fullname, path=None, target=None):
                if fullname == "app.backend.models":
                    raise RuntimeError("migration imported current ORM models")
                return None

        sys.meta_path.insert(0, RejectCurrentModels())
        from app.backend.schema_migrations import ensure_database_schema

        engine = create_engine(f"sqlite:///{sys.argv[1]}")
        try:
            ensure_database_schema(engine, db_mode="app")
        finally:
            engine.dispose()
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", code, str(database)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert scalar(database, "SELECT version_num FROM alembic_version") == (
        SCHEMA_3_REVISION
    )


def test_schema_2_database_is_stamped_then_upgraded_without_data_loss(
    tmp_path: Path,
    schema_two_signature,
):
    database = load_schema_2_fixture(tmp_path / "schema2.db")
    before = table_rows(database, SCHEMA_2_TABLES)
    engine = engine_for(database)
    try:
        ensure_database_schema(engine, db_mode="app")
    finally:
        engine.dispose()

    assert scalar(database, "SELECT version_num FROM alembic_version") == (
        SCHEMA_3_REVISION
    )
    assert scalar(database, "SELECT name FROM children WHERE id = 1") == "合成幼儿"
    assert scalar(database, "SELECT text FROM messages WHERE id = 2") == (
        "你观察得很仔细"
    )
    assert table_rows(database, SCHEMA_2_TABLES) == before
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert_schema_three_shape(database, schema_two_signature)


def test_valid_stamped_schema_two_upgrades_to_schema_three(
    tmp_path: Path,
    schema_two_signature,
):
    database = load_schema_2_fixture(tmp_path / "stamped-schema2.db")
    before = table_rows(database, SCHEMA_2_TABLES)
    stamp_database(database, SCHEMA_2_REVISION)
    engine = engine_for(database)
    try:
        ensure_database_schema(engine, db_mode="app")
    finally:
        engine.dispose()

    assert scalar(database, "SELECT version_num FROM alembic_version") == (
        SCHEMA_3_REVISION
    )
    assert table_rows(database, SCHEMA_2_TABLES) == before
    assert_schema_three_shape(database, schema_two_signature)


@pytest.mark.parametrize(
    "corrupt_schema",
    [
        remove_ducks_note,
        add_ducks_column,
        add_unexpected_table,
        remove_duck_archive_foreign_key,
        remove_roster_unique_constraint,
        replace_partial_index,
        replace_partial_index_literal_case,
    ],
    ids=[
        "missing-column",
        "extra-column",
        "extra-table",
        "missing-foreign-key",
        "missing-unique",
        "wrong-partial-index",
        "case-only-partial-literal",
    ],
)
def test_stamped_schema_two_corruption_is_rejected_before_upgrade_ddl(
    corrupt_schema,
    tmp_path: Path,
):
    database = load_schema_2_fixture(tmp_path / "corrupt-stamped-schema2.db")
    stamp_database(database, SCHEMA_2_REVISION)
    corrupt_schema(database)
    before = schema_snapshot(database)
    engine = engine_for(database)
    try:
        with pytest.raises(SchemaFingerprintError, match="schema-2 fingerprint"):
            ensure_database_schema(engine, db_mode="app")
    finally:
        engine.dispose()

    assert schema_snapshot(database) == before
    assert scalar(database, "SELECT version_num FROM alembic_version") == (
        SCHEMA_2_REVISION
    )
    assert scalar(
        database,
        "SELECT COUNT(*) FROM sqlite_schema WHERE type='table' AND name='avatar_media'",
    ) == 0


@pytest.mark.parametrize(
    "corrupt_schema",
    [
        remove_ducks_note,
        add_unexpected_table,
        replace_schema_three_index,
        remove_avatar_constraints,
        replace_avatar_check_literal_case,
    ],
    ids=[
        "missing-historical-column",
        "extra-table",
        "wrong-schema-three-index",
        "missing-avatar-constraints",
        "case-only-check-literal",
    ],
)
def test_stamped_schema_three_corruption_is_rejected(
    corrupt_schema,
    tmp_path: Path,
):
    database = tmp_path / "corrupt-schema3.db"
    engine = engine_for(database)
    try:
        ensure_database_schema(engine, db_mode="app")
    finally:
        engine.dispose()
    corrupt_schema(database)
    before = schema_snapshot(database)

    engine = engine_for(database)
    try:
        with pytest.raises(SchemaFingerprintError, match="schema-3 fingerprint"):
            ensure_database_schema(engine, db_mode="app")
    finally:
        engine.dispose()

    assert schema_snapshot(database) == before
    assert scalar(database, "SELECT version_num FROM alembic_version") == (
        SCHEMA_3_REVISION
    )


def test_missing_schema_2_column_is_rejected_before_any_migration_ddl(tmp_path: Path):
    database = load_schema_2_fixture(tmp_path / "missing-column.db")
    with sqlite3.connect(database) as connection:
        connection.execute("ALTER TABLE ducks DROP COLUMN note")
    before = schema_snapshot(database)
    engine = engine_for(database)
    try:
        with pytest.raises(SchemaFingerprintError, match="schema-2 fingerprint"):
            ensure_database_schema(engine, db_mode="app")
    finally:
        engine.dispose()

    assert schema_snapshot(database) == before
    assert "alembic_version" not in {row[1] for row in before}


def test_unexpected_unversioned_table_is_rejected_before_any_migration_ddl(
    tmp_path: Path,
):
    database = load_schema_2_fixture(tmp_path / "unexpected-table.db")
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE unexpected_extension (id INTEGER PRIMARY KEY)")
    before = schema_snapshot(database)
    engine = engine_for(database)
    try:
        with pytest.raises(SchemaFingerprintError, match="schema-2 fingerprint"):
            ensure_database_schema(engine, db_mode="app")
    finally:
        engine.dispose()

    assert schema_snapshot(database) == before


@pytest.mark.parametrize("revision", ["unknown_revision", "99999999_9999"])
def test_unknown_or_newer_revision_is_rejected_before_any_ddl(
    revision: str,
    tmp_path: Path,
):
    database = load_schema_2_fixture(tmp_path / f"{revision}.db")
    stamp_database(database, revision)
    before = schema_snapshot(database)
    engine = engine_for(database)
    try:
        with pytest.raises(
            UnsupportedDatabaseRevisionError,
            match="unsupported database revision",
        ):
            ensure_database_schema(engine, db_mode="app")
    finally:
        engine.dispose()

    assert schema_snapshot(database) == before
    assert scalar(database, "SELECT version_num FROM alembic_version") == revision


@pytest.mark.parametrize(
    ("primary_key", "revisions"),
    [
        (False, (SCHEMA_2_REVISION,)),
        (True, ()),
        (True, (SCHEMA_2_REVISION, SCHEMA_3_REVISION)),
    ],
    ids=["malformed-shape", "zero-rows", "multiple-rows"],
)
def test_malformed_alembic_version_state_is_rejected_before_any_ddl(
    primary_key: bool,
    revisions: tuple[str, ...],
    tmp_path: Path,
):
    database = load_schema_2_fixture(tmp_path / "malformed-version.db")
    create_version_table(database, revisions, primary_key=primary_key)
    before = schema_snapshot(database)
    engine = engine_for(database)
    try:
        with pytest.raises(
            UnsupportedDatabaseRevisionError,
            match="unsupported database revision",
        ):
            ensure_database_schema(engine, db_mode="app")
    finally:
        engine.dispose()

    assert schema_snapshot(database) == before
    with sqlite3.connect(database) as connection:
        stored_revisions = tuple(
            row[0]
            for row in connection.execute(
                "SELECT version_num FROM alembic_version ORDER BY version_num"
            ).fetchall()
        )
    assert stored_revisions == tuple(sorted(revisions))


def test_schema_three_upgrade_is_idempotent(tmp_path: Path):
    database = tmp_path / "idempotent.db"
    engine = engine_for(database)
    try:
        ensure_database_schema(engine, db_mode="app")
        before = schema_snapshot(database)
        ensure_database_schema(engine, db_mode="app")
    finally:
        engine.dispose()

    assert schema_snapshot(database) == before


def test_blank_head_downgrades_to_complete_schema_two_signature(
    tmp_path: Path,
    schema_two_signature,
):
    database = tmp_path / "downgrade.db"
    run_alembic(database, "upgrade", "head")

    run_alembic(database, "downgrade", SCHEMA_2_REVISION)

    assert scalar(database, "SELECT version_num FROM alembic_version") == (
        SCHEMA_2_REVISION
    )
    assert physical_schema_signature(
        database,
        excluded_tables={"alembic_version"},
    ) == schema_two_signature


def test_test_mode_migrator_leaves_blank_database_untouched(tmp_path: Path):
    database = tmp_path / "test-mode.db"
    engine = engine_for(database)
    try:
        ensure_database_schema(engine, db_mode="test")
    finally:
        engine.dispose()

    assert not database.exists()


def test_avatar_media_orm_is_compatible_with_migrated_schema(tmp_path: Path):
    database = tmp_path / "avatar-model.db"
    engine = engine_for(database)
    try:
        ensure_database_schema(engine, db_mode="app")
        with Session(engine) as session:
            session.add(models.AvatarMedia(
                id="6d8b0000-0000-4000-8000-000000000001",
                file_name="6d8b0000-0000-4000-8000-000000000001.webp",
                mime_type="image/webp",
                width=768,
                height=512,
                size_bytes=84231,
                sha256="a" * 64,
            ))
            session.commit()
            stored = session.scalar(select(models.AvatarMedia))
            assert stored is not None
            assert stored.file_name == (
                "6d8b0000-0000-4000-8000-000000000001.webp"
            )
            assert stored.mime_type == "image/webp"
    finally:
        engine.dispose()


def test_app_lifespan_migrates_and_seeds_only_dimensions_before_worker_start(monkeypatch):
    from app.backend import main as main_module

    events: list[str] = []

    class Worker:
        def __init__(self):
            events.append("worker_construct")

        def start(self):
            events.append("worker_start")

        def status(self):
            return "running"

        def stop(self, *, timeout_seconds: float):
            assert timeout_seconds == 5.0
            events.append("worker_stop")

    test_app = FastAPI(lifespan=main_module.lifespan)
    test_app.state.analysis_worker_factory = Worker
    monkeypatch.setattr(main_module, "DB_MODE", "app")
    monkeypatch.setattr(
        main_module,
        "ensure_database_schema",
        lambda migration_engine, db_mode: events.append("migrate"),
    )
    monkeypatch.setattr(
        main_module.Base.metadata,
        "create_all",
        lambda **kwargs: events.append("create_all"),
    )
    monkeypatch.setattr(
        main_module,
        "_seed_dimensions",
        lambda: events.append("seed_dimensions"),
    )
    async def exercise_lifespan():
        async with main_module.lifespan(test_app):
            events.append("serving")

    asyncio.run(exercise_lifespan())

    assert events == [
        "migrate",
        "seed_dimensions",
        "worker_construct",
        "worker_start",
        "serving",
        "worker_stop",
    ]


def test_test_lifespan_keeps_explicit_metadata_create_all(monkeypatch):
    from app.backend import main as main_module

    events: list[str] = []

    class Worker:
        def __init__(self):
            events.append("worker_construct")

        def start(self):
            events.append("worker_start")

        def status(self):
            return "running"

        def stop(self, *, timeout_seconds: float):
            assert timeout_seconds == 5.0
            events.append("worker_stop")

    test_app = FastAPI(lifespan=main_module.lifespan)
    test_app.state.analysis_worker_factory = Worker
    monkeypatch.setattr(main_module, "DB_MODE", "test")
    monkeypatch.setattr(
        main_module,
        "ensure_database_schema",
        lambda migration_engine, db_mode: events.append("migrate"),
    )
    monkeypatch.setattr(
        main_module.Base.metadata,
        "create_all",
        lambda **kwargs: events.append("create_all"),
    )
    monkeypatch.setattr(
        main_module,
        "_seed_dimensions",
        lambda: events.append("seed_dimensions"),
    )

    async def exercise_lifespan():
        async with main_module.lifespan(test_app):
            events.append("serving")

    asyncio.run(exercise_lifespan())

    assert events == [
        "create_all",
        "seed_dimensions",
        "worker_construct",
        "worker_start",
        "serving",
        "worker_stop",
    ]
