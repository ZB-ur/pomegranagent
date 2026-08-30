from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import logging
import os
import shutil
import socket
import sys
import tempfile
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TEST_RUNTIME_DIR = Path(tempfile.mkdtemp(prefix="duck-diary-pytest-")).resolve()
TEST_DATABASE_PATH = TEST_RUNTIME_DIR / "pytest.db"
TEST_APPLICATION_LOG_PATH = (TEST_RUNTIME_DIR / "pytest-app.log").resolve()
TEST_TTS_CACHE_PATH = (TEST_RUNTIME_DIR / "tts-cache").resolve()
REAL_APPLICATION_DATABASE_PATH = (ROOT / "data" / "duck_diary.db").resolve()
REAL_APPLICATION_LOG_PATH = (ROOT / "logs" / "app.log").resolve()
REAL_TTS_CACHE_PATH = (ROOT / "data" / "tts_cache").resolve()
os.environ["APP_DB_MODE"] = "test"
os.environ["APP_DB_PATH"] = str(TEST_DATABASE_PATH)
os.environ["PYTHON_DOTENV_DISABLED"] = "1"

sys.path.insert(0, str(ROOT))

from scripts.run_interaction_acceptance import (  # noqa: E402
    DatabaseSnapshot,
    DirectorySnapshot,
    FileKind,
    FileSnapshot,
    _task9_register_breaker,
    _task9_tripwire_error,
    database_snapshot,
    directory_snapshot,
    file_snapshot,
)


def _tripwire_error(event_id: str) -> AssertionError:
    return _task9_tripwire_error(event_id)


@dataclass(frozen=True, slots=True)
class ApplicationResourceSnapshot:
    database: DatabaseSnapshot
    log: FileSnapshot
    tts: DirectorySnapshot
    unsafe_reasons: tuple[str, ...]


def capture_application_resources(
    database_path: Path = REAL_APPLICATION_DATABASE_PATH,
    log_path: Path = REAL_APPLICATION_LOG_PATH,
    tts_path: Path = REAL_TTS_CACHE_PATH,
) -> ApplicationResourceSnapshot:
    """Capture logical and physical application resources without following links."""

    database = database_snapshot(Path(database_path))
    log = file_snapshot(Path(log_path))
    tts = directory_snapshot(Path(tts_path))
    reasons = list(database.unsafe_reasons)
    if log.kind is not FileKind.REGULAR:
        reasons.append("APPLICATION_LOG_NOT_REGULAR")
    reasons.extend(tts.unsafe_reasons)
    return ApplicationResourceSnapshot(
        database=database,
        log=log,
        tts=tts,
        unsafe_reasons=tuple(dict.fromkeys(reasons)),
    )


def application_resource_violations(
    before: ApplicationResourceSnapshot,
    after: ApplicationResourceSnapshot,
) -> tuple[str, ...]:
    """Return precise fail-closed drift reasons for every protected resource."""

    violations = []
    if before.unsafe_reasons or after.unsafe_reasons:
        violations.append("RESOURCE_SNAPSHOT_UNSAFE")
    if before.database.logical_digest != after.database.logical_digest:
        violations.append("DATABASE_LOGICAL_CHANGED")
    if before.database.database != after.database.database:
        violations.append("DATABASE_FILE_CHANGED")
    if before.database.wal != after.database.wal:
        violations.append("DATABASE_WAL_CHANGED")
    if before.database.shm != after.database.shm:
        violations.append("DATABASE_SHM_CHANGED")
    if before.log != after.log:
        violations.append("APPLICATION_LOG_CHANGED")
    if before.tts.root != after.tts.root:
        violations.append("TTS_ROOT_CHANGED")
    if (
        before.tts.entries != after.tts.entries
        or before.tts.digest != after.tts.digest
    ):
        violations.append("TTS_TREE_CHANGED")
    return tuple(violations)


APPLICATION_RESOURCE_BASELINE = capture_application_resources()
assert APPLICATION_RESOURCE_BASELINE.unsafe_reasons == (), (
    "pytest could not establish a safe application-resource baseline: "
    f"{APPLICATION_RESOURCE_BASELINE.unsafe_reasons!r}"
)


def _local_socket_destination(candidate: socket.socket, address) -> bool:
    if candidate.family == socket.AF_UNIX:
        return True
    if not isinstance(address, tuple) or not address:
        return False
    host = str(address[0]).strip().lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


_original_socket_connect = socket.socket.connect
_original_socket_connect_ex = socket.socket.connect_ex
BLOCKED_NETWORK_ATTEMPTS: list[dict[str, int | str]] = []


@_task9_register_breaker("external_network")
def _guarded_socket_connect(candidate: socket.socket, address):
    if not _local_socket_destination(candidate, address):
        BLOCKED_NETWORK_ATTEMPTS.append(
            {"family": int(candidate.family), "operation": "connect"}
        )
        raise _tripwire_error("external_network")
    return _original_socket_connect(candidate, address)


@_task9_register_breaker("external_network")
def _guarded_socket_connect_ex(candidate: socket.socket, address):
    if not _local_socket_destination(candidate, address):
        BLOCKED_NETWORK_ATTEMPTS.append(
            {"family": int(candidate.family), "operation": "connect_ex"}
        )
        raise _tripwire_error("external_network")
    return _original_socket_connect_ex(candidate, address)


socket.socket.connect = _guarded_socket_connect
socket.socket.connect_ex = _guarded_socket_connect_ex
EXTERNAL_NETWORK_TRIPWIRE_INSTALLED = True


class _BlockedEdgeTTSCommunicate:
    @_task9_register_breaker("edge_tts")
    def __init__(self, *_args, **_kwargs):
        raise _tripwire_error("edge_tts")


_edge_tts_breaker = types.ModuleType("edge_tts")
_edge_tts_breaker.Communicate = _BlockedEdgeTTSCommunicate
sys.modules["edge_tts"] = _edge_tts_breaker
TTS_PROVIDER_TRIPWIRE_INSTALLED = True

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.backend import ai_engine  # noqa: E402
from app.backend.database import Base, SessionLocal, engine  # noqa: E402
from app.backend.settings import DEFAULT_APP_DB_PATH  # noqa: E402


@_task9_register_breaker("external_ai")
def _blocked_external_ai(*_args, **_kwargs):
    raise _tripwire_error("external_ai")


ai_engine._llm = _blocked_external_ai


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
    from app.backend import main as main_module  # noqa: E402

    _seed_dimensions = main_module._seed_dimensions
    app = main_module.app
    main_module.TTS_CACHE_DIR = TEST_TTS_CACHE_PATH
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

_import_resource_violations = application_resource_violations(
    APPLICATION_RESOURCE_BASELINE,
    capture_application_resources(),
)
assert _import_resource_violations == (), (
    "pytest application imports changed protected resources: "
    f"{_import_resource_violations!r}"
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
    monkeypatch.setattr(ai_engine, "_llm", _blocked_external_ai)


@pytest.fixture(scope="session", autouse=True)
def application_resource_checksum_guard():
    yield
    after = capture_application_resources()
    violations = application_resource_violations(
        APPLICATION_RESOURCE_BASELINE,
        after,
    )
    shutil.rmtree(TEST_RUNTIME_DIR, ignore_errors=True)
    assert not violations, "pytest changed protected application resources: " + ";".join(
        violations
    )


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
