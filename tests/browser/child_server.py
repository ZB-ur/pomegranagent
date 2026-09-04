from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import hashlib
import importlib
import logging
import os
import socket
import sqlite3
import subprocess
import tempfile
import types
from collections.abc import Callable, Iterable, Mapping
from typing import NamedTuple


FORBIDDEN_ENV_TOKENS = ("DEEPSEEK", "OPENAI", "API_KEY", "PROVIDER", "PROXY")
SAFE_EXECUTION_ENV = ("PATH", "LANG", "LC_ALL", "TMPDIR", "TZ", "SYSTEMROOT")
REAL_DATABASE_PATH = ROOT / "data" / "duck_diary.db"
REAL_LOG_PATH = ROOT / "logs" / "app.log"
REAL_TTS_CACHE_PATH = ROOT / "data" / "tts_cache"
REAL_MEDIA_ROOT = ROOT / "data" / "media"


class ResourceSnapshots(NamedTuple):
    database: str | None
    database_wal: str | None
    database_shm: str | None
    database_logical: str | None
    log: str | None
    tts_cache: str | None
    media: str | None


class FreshMainImportResult:
    def __init__(
        self,
        *,
        module,
        events: Iterable[str],
        handler_paths: Iterable[Path],
        real_log_before: bytes | None,
        real_log_after: bytes | None,
        previous_handlers: Iterable[logging.Handler],
        previous_level: int,
        disposable_handler: logging.Handler,
    ) -> None:
        self.module = module
        self.events = tuple(events)
        self.handler_paths = tuple(handler_paths)
        self.real_log_before = real_log_before
        self.real_log_after = real_log_after
        self._previous_handlers = tuple(previous_handlers)
        self._previous_level = previous_level
        self._disposable_handler = disposable_handler
        self._logging_restored = False

    def restore_logging(self) -> None:
        if self._logging_restored:
            return
        self._logging_restored = True
        root_logger = logging.getLogger()
        for handler in tuple(root_logger.handlers):
            root_logger.removeHandler(handler)
            if handler is not self._disposable_handler:
                try:
                    handler.close()
                except Exception:
                    pass
        try:
            self._disposable_handler.close()
        except Exception:
            pass
        root_logger.setLevel(self._previous_level)
        for handler in self._previous_handlers:
            root_logger.addHandler(handler)


def _record(events: list[str], name: str) -> None:
    events.append(name)


def assert_no_provider_environment(environ: Mapping[str, str] | None = None) -> None:
    source = os.environ if environ is None else environ
    offenders = sorted(
        name for name in source if any(token in name.upper() for token in FORBIDDEN_ENV_TOKENS)
    )
    assert not offenders, f"provider environment is forbidden in browser tests: {', '.join(offenders)}"


def _byte_snapshot(path: Path) -> bytes | None:
    return path.read_bytes() if path.exists() else None


def fresh_import_main(
    *,
    browser_log_dir: Path,
    event_sink: list[str] | None = None,
    importer: Callable[[str], object] | None = None,
) -> FreshMainImportResult:
    """Fresh-import main behind the single dotenv/provider/log redirection guard."""
    import dotenv

    events = event_sink if event_sink is not None else []
    dotenv.load_dotenv = lambda *_args, **_kwargs: False
    _record(events, "dotenv_disabled")
    assert_no_provider_environment()
    _record(events, "provider_environment_absent_pre")

    real_log_dir = REAL_LOG_PATH.parent
    if not real_log_dir.is_dir():
        raise AssertionError(f"browser preflight requires existing real log directory: {real_log_dir}")
    real_log_before = _byte_snapshot(REAL_LOG_PATH)
    _record(events, "real_log_snapshotted")

    resolved_log_dir = browser_log_dir.resolve()
    resolved_log_dir.mkdir(parents=True, exist_ok=True)
    disposable_log = resolved_log_dir / "app.log"
    original_file_handler = logging.FileHandler
    prior_handlers = tuple(logging.getLogger().handlers)
    prior_level = logging.getLogger().level
    handler_paths: list[Path] = []
    redirected_handlers: list[logging.Handler] = []

    def redirected_file_handler(_filename, *args, **kwargs):
        handler = original_file_handler(disposable_log, *args, **kwargs)
        redirected_handlers.append(handler)
        handler_paths.append(Path(handler.baseFilename).resolve())
        return handler

    logging.FileHandler = redirected_file_handler
    _record(events, "filehandler_redirected")
    import_main = importlib.import_module if importer is None else importer
    previous_main = None
    if importer is None:
        previous_main = sys.modules.pop("app.backend.main", None)
    try:
        main_module = import_main("app.backend.main")
        _record(events, "main_imported")
    except Exception:
        if previous_main is not None:
            sys.modules["app.backend.main"] = previous_main
        raise
    finally:
        logging.FileHandler = original_file_handler
        _record(events, "filehandler_restored")

    assert_no_provider_environment()
    _record(events, "provider_environment_absent_post")
    disposable_handler = original_file_handler(disposable_log, encoding="utf-8")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        handlers=[disposable_handler],
        force=True,
    )
    _record(events, "logging_configured")
    for handler in redirected_handlers:
        if handler not in logging.getLogger().handlers:
            try:
                handler.close()
            except Exception:
                pass
    real_log_after = _byte_snapshot(REAL_LOG_PATH)
    if real_log_after != real_log_before:
        raise AssertionError("fresh main import changed the real application log")
    return FreshMainImportResult(
        module=main_module,
        events=events,
        handler_paths=handler_paths,
        real_log_before=real_log_before,
        real_log_after=real_log_after,
        previous_handlers=prior_handlers,
        previous_level=prior_level,
        disposable_handler=disposable_handler,
    )


def _tripwire_path(environment_name: str) -> Path:
    raw = os.environ.get(environment_name)
    if not raw:
        raise AssertionError(f"missing browser test tripwire: {environment_name}")
    path = Path(raw).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def write_ai_tripwire(message: str) -> None:
    _tripwire_path("BROWSER_AI_TRIPWIRE_PATH").write_text(f"{message}\n", encoding="utf-8")


class FakeCommunicate:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    async def stream(self):
        write_ai_tripwire("edge_tts blocked")
        raise AssertionError("external edge_tts disabled in browser tests")
        yield {"type": "audio", "data": b""}


class _NonStartingAnalysisWorker:
    def start(self) -> None:
        return None

    def stop(self, timeout_seconds: float = 5.0) -> None:
        del timeout_seconds
        return None

    def status(self) -> str:
        return "not_started"


def build_browser_environment(
    parent: Mapping[str, str],
    runtime_dir: Path,
    *,
    port: int,
) -> dict[str, str]:
    runtime = runtime_dir.resolve()
    database = (runtime / "browser-app.db").resolve()
    real_data = (ROOT / "data").resolve()
    if database == real_data or real_data in database.parents:
        raise AssertionError("browser database must not be under the real data directory")
    environment = {name: parent[name] for name in SAFE_EXECUTION_ENV if name in parent}
    environment.update(
        {
            "APP_DB_MODE": "app",
            "APP_DB_PATH": str(database),
            "APP_LOG_PATH": str((runtime / "logs/app.log").resolve()),
            "APP_MEDIA_ROOT": str((runtime / "media").resolve()),
            "APP_TTS_CACHE_PATH": str((runtime / "tts-cache").resolve()),
            "BROWSER_PORT": str(int(port)),
            "BROWSER_LOG_DIR": str((runtime / "logs").resolve()),
            "BROWSER_TTS_CACHE_DIR": str((runtime / "tts-cache").resolve()),
            "BROWSER_AI_TRIPWIRE_PATH": str((runtime / "ai-tripwire.txt").resolve()),
            "BROWSER_NETWORK_TRIPWIRE_PATH": str((runtime / "network-tripwire.txt").resolve()),
            "BROWSER_CONTEXT_EGRESS_TRIPWIRE_PATH": str(
                (runtime / "browser-egress-tripwire.txt").resolve()
            ),
            "DISABLE_EXTERNAL_AI": "1",
            "PYTHONNOUSERSITE": "1",
        }
    )
    assert_no_provider_environment(environment)
    return environment


def logical_sqlite_digest(
    path: Path,
    *,
    connect: Callable[..., sqlite3.Connection] = sqlite3.connect,
) -> str | None:
    resolved = path.resolve()
    if not resolved.exists():
        return None
    with tempfile.TemporaryDirectory(prefix="browser-sqlite-shadow-") as temporary:
        shadow = Path(temporary) / resolved.name
        shadow.write_bytes(resolved.read_bytes())
        for suffix in ("-wal", "-shm"):
            source = Path(f"{resolved}{suffix}")
            if source.exists():
                Path(f"{shadow}{suffix}").write_bytes(source.read_bytes())
        database_uri = f"{shadow.as_uri()}?mode=ro"
        with connect(database_uri, uri=True) as connection:
            snapshot = "\n".join(connection.iterdump()).encode("utf-8")
    return hashlib.sha256(snapshot).hexdigest()


def file_digest(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def directory_digest(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    for item in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        digest.update(item.relative_to(path).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(item.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def capture_resource_snapshots(
    database: Path,
    log: Path,
    tts_cache: Path,
    media: Path,
    *,
    connect: Callable[..., sqlite3.Connection] = sqlite3.connect,
) -> ResourceSnapshots:
    logical = logical_sqlite_digest(database, connect=connect)
    return ResourceSnapshots(
        file_digest(database),
        file_digest(Path(f"{database}-wal")),
        file_digest(Path(f"{database}-shm")),
        logical,
        file_digest(log),
        directory_digest(tts_cache),
        directory_digest(media),
    )


def make_loopback_connect_guard(tripwire: Path, original_connect: Callable):
    resolved_tripwire = tripwire.resolve()

    def guarded(sock, address):
        host = address[0] if isinstance(address, tuple) and address else None
        if host in {"127.0.0.1", "::1"}:
            return original_connect(sock, address)
        port = address[1] if isinstance(address, tuple) and len(address) > 1 else ""
        resolved_tripwire.parent.mkdir(parents=True, exist_ok=True)
        resolved_tripwire.write_text(f"{host}:{port}\n", encoding="utf-8")
        raise PermissionError(f"non-loopback socket blocked: {host}:{port}")

    return guarded


def close_and_verify(resources: Iterable[object], process, *, verify: Callable[[], None]) -> None:
    for resource in resources:
        try:
            resource.close()
        except Exception:
            pass
    if process is not None:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        if process.poll() is None:
            raise AssertionError("browser child server did not exit")
    verify()


def _install_external_tripwires(main_module) -> None:
    def blocked_llm(*_args, **_kwargs):
        write_ai_tripwire("llm blocked")
        raise AssertionError("external AI disabled in browser tests")

    main_module.ai_engine._llm = blocked_llm
    fake_edge_tts = types.ModuleType("edge_tts")
    fake_edge_tts.Communicate = FakeCommunicate
    sys.modules["edge_tts"] = fake_edge_tts
    socket.socket.connect = make_loopback_connect_guard(
        _tripwire_path("BROWSER_NETWORK_TRIPWIRE_PATH"),
        socket.socket.connect,
    )


def run_server() -> None:
    browser_log_dir = Path(os.environ["APP_LOG_PATH"]).resolve().parent
    assert browser_log_dir == Path(os.environ["BROWSER_LOG_DIR"]).resolve()
    browser_log_dir.mkdir(parents=True, exist_ok=True)
    tts_cache = Path(os.environ["APP_TTS_CACHE_PATH"]).resolve()
    assert tts_cache == Path(os.environ["BROWSER_TTS_CACHE_DIR"]).resolve()
    tts_cache.mkdir(parents=True, exist_ok=True)
    Path(os.environ["APP_MEDIA_ROOT"]).resolve().mkdir(parents=True, exist_ok=True)
    os.environ["APP_BUSINESS_TIMEZONE"] = "Asia/Shanghai"
    result = fresh_import_main(browser_log_dir=browser_log_dir)
    main_module = result.module
    _install_external_tripwires(main_module)
    main_module.app.state.analysis_worker_factory = _NonStartingAnalysisWorker

    import uvicorn

    uvicorn.run(
        main_module.app,
        host="127.0.0.1",
        port=int(os.environ["BROWSER_PORT"]),
        log_config=None,
        proxy_headers=False,
        access_log=False,
    )


if __name__ == "__main__":
    run_server()
