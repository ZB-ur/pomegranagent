from __future__ import annotations

import hashlib
import logging
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TEST_RUNTIME_DIR = Path(tempfile.mkdtemp(prefix="duck-diary-pytest-")).resolve()
TEST_DATABASE_PATH = TEST_RUNTIME_DIR / "pytest.db"
TEST_APPLICATION_LOG_PATH = (TEST_RUNTIME_DIR / "pytest-app.log").resolve()
REAL_APPLICATION_LOG_PATH = (ROOT / "logs" / "app.log").resolve()
os.environ["APP_DB_MODE"] = "test"
os.environ["APP_DB_PATH"] = str(TEST_DATABASE_PATH)

sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.backend import ai_engine  # noqa: E402
from app.backend.database import Base, SessionLocal, engine  # noqa: E402
from app.backend.settings import DEFAULT_APP_DB_PATH  # noqa: E402


def root_file_handler_paths() -> set[Path]:
    """Return resolved root FileHandler targets while tolerating non-file handlers."""
    paths = set()
    for handler in logging.getLogger().handlers:
        base_filename = getattr(handler, "baseFilename", None)
        if base_filename is not None:
            paths.add(Path(base_filename).resolve())
    return paths


_original_file_handler = logging.FileHandler
_redirected_main_file_handlers: list[Path] = []


def _redirect_main_file_handler(filename, *args, **kwargs):
    try:
        requested_path = Path(filename).expanduser().resolve()
    except TypeError:
        return _original_file_handler(filename, *args, **kwargs)
    if requested_path == REAL_APPLICATION_LOG_PATH:
        _redirected_main_file_handlers.append(TEST_APPLICATION_LOG_PATH)
        return _original_file_handler(TEST_APPLICATION_LOG_PATH, *args, **kwargs)
    return _original_file_handler(filename, *args, **kwargs)


logging.FileHandler = _redirect_main_file_handler
try:
    from app.backend.main import _seed_dimensions, app  # noqa: E402
finally:
    logging.FileHandler = _original_file_handler

APPLICATION_FILE_HANDLER_INSTALLED = bool(_redirected_main_file_handlers)
_root_file_handler_paths = root_file_handler_paths()
assert REAL_APPLICATION_LOG_PATH not in _root_file_handler_paths, (
    "pytest configured a root FileHandler for the real application log"
)
if APPLICATION_FILE_HANDLER_INSTALLED:
    assert TEST_APPLICATION_LOG_PATH in _root_file_handler_paths, (
        "pytest application logging did not use the disposable runtime log"
    )


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


def _file_bytes(path: Path) -> bytes | None:
    return path.read_bytes() if path.exists() else None


@pytest.fixture(scope="session", autouse=True)
def application_resource_checksum_guard():
    before_database = _logical_sqlite_hash(DEFAULT_APP_DB_PATH)
    before_log = _file_bytes(REAL_APPLICATION_LOG_PATH)
    yield
    after_database = _logical_sqlite_hash(DEFAULT_APP_DB_PATH)
    after_log = _file_bytes(REAL_APPLICATION_LOG_PATH)
    violations = []
    if after_database != before_database:
        violations.append("pytest changed the application database")
    if after_log != before_log:
        violations.append("pytest changed the real application log")
    shutil.rmtree(TEST_RUNTIME_DIR, ignore_errors=True)
    assert not violations, "; ".join(violations)


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
