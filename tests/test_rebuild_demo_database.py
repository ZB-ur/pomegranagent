import errno
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

import pytest

from scripts.rebuild_demo_database import (
    local_service_is_running,
    parse_args,
    rebuild_demo_database,
)


def test_local_service_treats_http_error_as_running(monkeypatch: pytest.MonkeyPatch):
    error = urllib.error.HTTPError(
        "http://127.0.0.1:8000/api/health", 503, "Unavailable", None, None
    )
    monkeypatch.setattr(urllib.request, "urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(error))

    assert local_service_is_running() is True


def test_local_service_treats_timeout_as_running(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutError()),
    )

    assert local_service_is_running() is True


def test_local_service_treats_ambiguous_url_error_as_running(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(urllib.error.URLError("network changed")),
    )

    assert local_service_is_running() is True


def test_local_service_accepts_clear_connection_refusal(monkeypatch: pytest.MonkeyPatch):
    error = urllib.error.URLError(ConnectionRefusedError(errno.ECONNREFUSED, "Connection refused"))
    monkeypatch.setattr(urllib.request, "urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(error))

    assert local_service_is_running() is False


def test_rebuild_archives_existing_database_before_replacing_it(tmp_path: Path):
    db_path = tmp_path / "duck_diary.db"
    db_path.write_bytes(b"old-demo-database")
    result = rebuild_demo_database(
        db_path=db_path,
        archive_dir=tmp_path / "archive",
        log_path=tmp_path / "app.log",
        service_is_running=lambda: False,
    )
    assert result.database_path == db_path.resolve()
    assert result.archived_database.read_bytes() == b"old-demo-database"
    assert db_path.exists()


def test_rebuild_refuses_while_service_is_reachable(tmp_path: Path):
    with pytest.raises(RuntimeError, match="service is still running"):
        rebuild_demo_database(
            db_path=tmp_path / "duck_diary.db",
            archive_dir=tmp_path / "archive",
            log_path=tmp_path / "app.log",
            service_is_running=lambda: True,
        )


def test_rebuild_creates_frozen_deterministic_demo_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from sqlalchemy import create_engine, text
    from app.backend import main as backend_main

    class UnfrozenDate(date):
        @classmethod
        def today(cls) -> "UnfrozenDate":
            return cls(2030, 1, 1)

    monkeypatch.setattr(backend_main, "date", UnfrozenDate)

    db_path = tmp_path / "rebuilt.db"
    rebuild_demo_database(
        db_path=db_path,
        archive_dir=tmp_path / "archive",
        log_path=tmp_path / "missing.log",
        service_is_running=lambda: False,
    )
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.connect() as connection:
        assert connection.scalar(text("select count(*) from children")) == 5
        assert connection.scalar(text("select count(*) from ducks")) == 3
        assert connection.scalar(text("select count(*) from assessment_dimensions")) == 3
        assert connection.scalar(text("select count(*) from duty_rosters")) == 14
        assert connection.scalars(text("select distinct cycle from duty_rosters")).all() == ["示例-35周"]
        assert connection.scalars(
            text("select distinct date from duty_rosters order by date")
        ).all() == [
            "2026-08-24",
            "2026-08-25",
            "2026-08-26",
            "2026-08-27",
            "2026-08-28",
            "2026-08-31",
            "2026-09-01",
        ]


def test_parse_args_uses_runtime_configured_database(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    configured_db = tmp_path / "configured.db"
    monkeypatch.setenv("APP_DB_PATH", str(configured_db))
    monkeypatch.setattr(sys, "argv", ["rebuild_demo_database.py", "--confirm-rebuild"])

    assert parse_args().database == configured_db.resolve()


def test_parse_args_preserves_explicit_database_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    configured_db = tmp_path / "configured.db"
    overridden_db = tmp_path / "override.db"
    monkeypatch.setenv("APP_DB_PATH", str(configured_db))
    monkeypatch.setattr(
        sys,
        "argv",
        ["rebuild_demo_database.py", "--confirm-rebuild", "--database", str(overridden_db)],
    )

    assert parse_args().database == overridden_db
