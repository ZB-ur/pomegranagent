"""Guarded schema-2 to schema-3 Alembic migration contracts."""
from __future__ import annotations

import asyncio
from pathlib import Path
import sqlite3
import subprocess
import sys
import textwrap

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
    ensure_database_schema,
)


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


def assert_schema_three_shape(database: Path) -> None:
    engine = engine_for(database)
    try:
        inspector = inspect(engine)
        assert set(inspector.get_table_names()) == {
            *SCHEMA_2_TABLES,
            "alembic_version",
            "avatar_media",
        }
        assert [column["name"] for column in inspector.get_columns("avatar_media")] == [
            "id",
            "file_name",
            "mime_type",
            "width",
            "height",
            "size_bytes",
            "sha256",
            "created_at",
        ]
    finally:
        engine.dispose()
    for name, columns in SCHEMA_3_INDEXES.items():
        assert index_columns(database, name) == columns


def test_blank_database_upgrades_from_baseline_to_schema_three(tmp_path: Path):
    database = tmp_path / "blank.db"
    engine = engine_for(database)
    try:
        ensure_database_schema(engine, db_mode="app")
    finally:
        engine.dispose()

    assert scalar(database, "SELECT version_num FROM alembic_version") == (
        SCHEMA_3_REVISION
    )
    assert_schema_three_shape(database)


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


def test_schema_2_database_is_stamped_then_upgraded_without_data_loss(tmp_path: Path):
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
    assert_schema_three_shape(database)


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
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"
        )
        connection.execute(
            "INSERT INTO alembic_version (version_num) VALUES (?)",
            (revision,),
        )
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


def test_app_lifespan_migrates_before_seed_and_worker_start(monkeypatch):
    from app.backend import main as main_module

    events: list[str] = []

    class Worker:
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
    monkeypatch.setattr(
        main_module,
        "_seed_demo_data",
        lambda: events.append("seed_demo"),
    )

    async def exercise_lifespan():
        async with main_module.lifespan(test_app):
            events.append("serving")

    asyncio.run(exercise_lifespan())

    assert events == [
        "migrate",
        "seed_dimensions",
        "seed_demo",
        "worker_start",
        "serving",
        "worker_stop",
    ]


def test_test_lifespan_keeps_explicit_metadata_create_all(monkeypatch):
    from app.backend import main as main_module

    events: list[str] = []

    class Worker:
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
        "worker_start",
        "serving",
        "worker_stop",
    ]
