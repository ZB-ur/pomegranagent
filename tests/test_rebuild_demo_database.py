from pathlib import Path

import pytest

from scripts.rebuild_demo_database import rebuild_demo_database


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


def test_rebuild_creates_deterministic_demo_counts(tmp_path: Path):
    from sqlalchemy import create_engine, text

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
