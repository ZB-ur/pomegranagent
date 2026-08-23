from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

TEST_RUNTIME_DIR = Path(tempfile.mkdtemp(prefix="duck-diary-pytest-")).resolve()
TEST_DATABASE_PATH = TEST_RUNTIME_DIR / "pytest.db"
os.environ["APP_DB_MODE"] = "test"
os.environ["APP_DB_PATH"] = str(TEST_DATABASE_PATH)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.backend import ai_engine  # noqa: E402
from app.backend.database import Base, SessionLocal, engine  # noqa: E402
from app.backend.main import _seed_dimensions, app  # noqa: E402
from app.backend.settings import DEFAULT_APP_DB_PATH  # noqa: E402


class _NonStartingAnalysisWorker:
    """Test lifespan seam: deterministic tests must claim jobs themselves."""

    def start(self) -> None:
        pass

    def stop(self, timeout_seconds: float = 5.0) -> None:
        pass

    def status(self) -> str:
        return "not_started"


app.state.analysis_worker_factory = _NonStartingAnalysisWorker


@pytest.fixture(autouse=True)
def disable_external_ai(monkeypatch):
    """Fail closed before tests can enter the shared LLM transport."""
    def blocked(*_args, **_kwargs):
        raise AssertionError("external AI disabled in tests")

    monkeypatch.setattr(ai_engine, "_llm", blocked)


def _logical_sqlite_hash(path: Path) -> str | None:
    """Hash the read-only SQLite view, including pages currently visible from WAL."""
    if not path.exists():
        return None
    with sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True) as connection:
        snapshot = "\n".join(connection.iterdump()).encode("utf-8")
    return hashlib.sha256(snapshot).hexdigest()


@pytest.fixture(scope="session", autouse=True)
def application_database_checksum_guard():
    before = _logical_sqlite_hash(DEFAULT_APP_DB_PATH)
    yield
    after = _logical_sqlite_hash(DEFAULT_APP_DB_PATH)
    assert after == before, "pytest changed the application database"
    shutil.rmtree(TEST_RUNTIME_DIR, ignore_errors=True)


@pytest.fixture(autouse=True)
def reset_test_database():
    engine.dispose()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    _seed_dimensions()
    yield


@pytest.fixture
def test_db_path() -> Path:
    return TEST_DATABASE_PATH


@pytest.fixture
def db_session() -> Session:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
