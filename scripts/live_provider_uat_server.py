#!/usr/bin/env python3
"""Isolated app-mode Uvicorn wrapper for retained live-provider UAT."""
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from dataclasses import dataclass
import functools
import importlib
import json
import logging
import os
from pathlib import Path
import re
import socket
import stat
import sys
import threading
import time


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if sys.path[0] != str(PROJECT_ROOT):
    sys.path.insert(0, str(PROJECT_ROOT))


DEEPSEEK_KEYS = {
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_MAX_TOKENS",
    "DEEPSEEK_MODEL",
    "DEEPSEEK_TIMEOUT",
}
APP_KEYS = {
    "APP_BUSINESS_TIMEZONE",
    "APP_DB_MODE",
    "APP_DB_PATH",
    "APP_LOG_PATH",
    "APP_MEDIA_ROOT",
    "APP_TTS_CACHE_PATH",
}
NEUTRAL_KEYS = {
    "LANG",
    "LC_ALL",
    "PATH",
    "PYTHONNOUSERSITE",
    "PYTHON_DOTENV_DISABLED",
    "SYSTEMROOT",
    "TMPDIR",
    "TZ",
}
ALLOWED_ENVIRONMENT = APP_KEYS | DEEPSEEK_KEYS | NEUTRAL_KEYS
TELEMETRY_KEYS = {
    "audio_bytes",
    "error_class",
    "latency_bucket",
    "model",
    "operation",
    "provider",
    "response_bytes",
    "status",
    "voice",
}


class ServerSafetyError(RuntimeError):
    """The child refuses to import or serve from an unsafe runtime."""


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    root: Path
    database: Path
    media: Path
    tts_cache: Path
    app_log: Path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve one retained live UAT runtime.")
    parser.add_argument("--listen-fd", type=int, required=True)
    parser.add_argument("--telemetry-fd", type=int, required=True)
    parsed = parser.parse_args(argv)
    if (
        parsed.listen_fd < 0
        or parsed.telemetry_fd < 0
        or parsed.listen_fd == parsed.telemetry_fd
    ):
        raise ServerSafetyError(
            "inherited descriptor contract is invalid"
        )
    return parsed


def _regular_owned(path: Path) -> bool:
    try:
        entry = path.lstat()
    except OSError:
        return False
    return (
        stat.S_ISREG(entry.st_mode)
        and not stat.S_ISLNK(entry.st_mode)
        and entry.st_nlink == 1
        and entry.st_uid == os.geteuid()
    )


def _directory_owned(path: Path) -> bool:
    try:
        entry = path.lstat()
    except OSError:
        return False
    return (
        stat.S_ISDIR(entry.st_mode)
        and not stat.S_ISLNK(entry.st_mode)
        and entry.st_uid == os.geteuid()
        and not entry.st_mode & 0o022
    )


def validate_child_environment(
    environment: Mapping[str, str] | None = None,
) -> RuntimePaths:
    """Freeze the exact child environment before any backend import."""

    source = os.environ if environment is None else environment
    if (
        not isinstance(source, Mapping)
        or not APP_KEYS.issubset(source)
        or not DEEPSEEK_KEYS.issubset(source)
        or any(name not in ALLOWED_ENVIRONMENT for name in source)
        or any(not isinstance(value, str) for value in source.values())
        or source.get("APP_DB_MODE") != "app"
        or source.get("APP_BUSINESS_TIMEZONE") != "Asia/Shanghai"
        or source.get("PYTHON_DOTENV_DISABLED") != "1"
        or source.get("PYTHONNOUSERSITE") != "1"
        or source.get("TZ") != "Asia/Shanghai"
        or not source.get("DEEPSEEK_API_KEY")
    ):
        raise ServerSafetyError("live server environment is invalid")

    paths = {
        key: Path(source[key])
        for key in (
            "APP_DB_PATH",
            "APP_LOG_PATH",
            "APP_MEDIA_ROOT",
            "APP_TTS_CACHE_PATH",
        )
    }
    if any(
        not path.is_absolute()
        or path != Path(os.path.abspath(os.fspath(path)))
        or path.resolve() != path
        for path in paths.values()
    ):
        raise ServerSafetyError("live server environment path is invalid")
    database = paths["APP_DB_PATH"]
    root = database.parent
    runtime = RuntimePaths(
        root=root,
        database=database,
        media=paths["APP_MEDIA_ROOT"],
        tts_cache=paths["APP_TTS_CACHE_PATH"],
        app_log=paths["APP_LOG_PATH"],
    )
    if (
        database.name != "duck-diary-uat.db"
        or runtime.media != root / "media"
        or runtime.tts_cache != root / "tts-cache"
        or runtime.app_log != root / "logs/app.log"
        or not _directory_owned(root)
        or not _directory_owned(runtime.media)
        or not _directory_owned(runtime.tts_cache)
        or not _directory_owned(runtime.app_log.parent)
        or not _regular_owned(runtime.database)
        or not _regular_owned(runtime.app_log)
    ):
        raise ServerSafetyError("live server environment resources are invalid")
    return runtime


class RedactingFilter(logging.Filter):
    """Render every record once and retain no credential/header/session text."""

    _patterns = (
        re.compile(r"authorization\s*:[^\r\n]*", re.IGNORECASE),
        re.compile(r"\bbearer\s+[^\s,;]+", re.IGNORECASE),
        re.compile(r"(?:set-)?cookie\s*[:=][^\r\n]*", re.IGNORECASE),
        re.compile(r"duck_teacher_session\s*[:=][^\s,;]+", re.IGNORECASE),
        re.compile(r"auth[-_]?token\s*[:=][^\s,;]+", re.IGNORECASE),
    )

    def __init__(self, secrets: tuple[str, ...]) -> None:
        super().__init__()
        self._secrets = tuple(
            secret for secret in secrets if isinstance(secret, str) and secret
        )

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            rendered = record.getMessage()
        except Exception:
            rendered = "unrenderable log record"
        for secret in self._secrets:
            rendered = rendered.replace(secret, "[REDACTED]")
        for pattern in self._patterns:
            rendered = pattern.sub("[REDACTED]", rendered)
        if record.exc_info is not None:
            error_type = getattr(record.exc_info[0], "__name__", "Exception")
            rendered = f"{rendered} error_type={error_type}"
        record.msg = rendered
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        return True


def configure_safe_logging(paths: RuntimePaths, *, secrets: tuple[str, ...]) -> None:
    root = logging.getLogger()
    for handler in tuple(root.handlers):
        root.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass
    redactor = RedactingFilter(secrets)
    formatter = logging.Formatter(
        "%(asctime)s %(name)s %(levelname)s %(message)s"
    )
    file_handler = logging.FileHandler(paths.app_log, encoding="utf-8")
    stream_handler = logging.StreamHandler(sys.stderr)
    for handler in (file_handler, stream_handler):
        handler.addFilter(redactor)
        handler.setFormatter(formatter)
        root.addHandler(handler)
    root.setLevel(logging.INFO)
    logging.captureWarnings(True)


def load_backend(*, importer=importlib.import_module):
    """Disable dotenv loading before the first application backend import."""

    dotenv_module = importer("dotenv")
    dotenv_module.load_dotenv = lambda *_args, **_kwargs: False
    return importer("app.backend.main")


def _latency_bucket(elapsed: float) -> str:
    if elapsed < 1:
        return "<1s"
    if elapsed < 5:
        return "1-5s"
    if elapsed < 30:
        return "5-30s"
    if elapsed < 120:
        return "30-120s"
    return ">=120s"


def _error_class(error: BaseException) -> str:
    candidate = type(error).__name__
    return (
        candidate
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_.]{0,127}", candidate)
        else "Exception"
    )


def _response_bytes(value: object) -> int:
    try:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError):
        return 0
    return min(len(payload), 100_000_000)


def _provider_event(
    *,
    operation: str,
    model: str | None,
    voice: str | None,
    elapsed: float,
    response_bytes: int,
    audio_bytes: int,
    error: BaseException | None,
) -> dict[str, object]:
    return {
        "audio_bytes": audio_bytes,
        "error_class": None if error is None else _error_class(error),
        "latency_bucket": _latency_bucket(max(0.0, elapsed)),
        "model": model,
        "operation": operation,
        "provider": "edge-tts" if operation == "tts" else "deepseek",
        "response_bytes": response_bytes,
        "status": "ok" if error is None else "error",
        "voice": voice,
    }


def instrument_ai_engine(
    ai_engine,
    *,
    emit: Callable[[Mapping[str, object]], None],
    monotonic: Callable[[], float] = time.monotonic,
) -> None:
    """Wrap only the three release-required DeepSeek operations."""

    model = ai_engine.MODEL
    if not isinstance(model, str) or re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", model
    ) is None:
        raise ServerSafetyError("live provider model is invalid")

    def wrap(operation: str, function):
        @functools.wraps(function)
        def measured(*args, **kwargs):
            started = monotonic()
            try:
                result = function(*args, **kwargs)
            except BaseException as error:
                emit(
                    _provider_event(
                        operation=operation,
                        model=model,
                        voice=None,
                        elapsed=monotonic() - started,
                        response_bytes=0,
                        audio_bytes=0,
                        error=error,
                    )
                )
                raise
            emit(
                _provider_event(
                    operation=operation,
                    model=model,
                    voice=None,
                    elapsed=monotonic() - started,
                    response_bytes=_response_bytes(result),
                    audio_bytes=0,
                    error=None,
                )
            )
            return result

        return measured

    for operation in ("chat_reply", "extract_info", "assess_conversation"):
        original = getattr(ai_engine, operation, None)
        if not callable(original):
            raise ServerSafetyError("live AI instrumentation target is missing")
        setattr(ai_engine, operation, wrap(operation, original))


class TelemetryWriter:
    def __init__(self, descriptor: int) -> None:
        if type(descriptor) is not int or descriptor < 0:
            raise ServerSafetyError("telemetry descriptor is invalid")
        try:
            mode = os.fstat(descriptor).st_mode
        except OSError as exc:
            raise ServerSafetyError("telemetry descriptor is invalid") from exc
        if not stat.S_ISFIFO(mode):
            raise ServerSafetyError("telemetry descriptor is not a pipe")
        self._descriptor = descriptor
        self._lock = threading.Lock()

    def emit(self, event: Mapping[str, object]) -> None:
        if set(event) != TELEMETRY_KEYS:
            raise ServerSafetyError("telemetry event shape is invalid")
        payload = (
            json.dumps(
                dict(event),
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        if not 1 <= len(payload) <= 4096:
            raise ServerSafetyError("telemetry event is too large")
        with self._lock:
            offset = 0
            while offset < len(payload):
                written = os.write(self._descriptor, payload[offset:])
                if written <= 0:
                    raise ServerSafetyError("telemetry pipe write failed")
                offset += written


def instrument_edge_tts(
    edge_tts_module,
    *,
    emit: Callable[[Mapping[str, object]], None],
    monotonic: Callable[[], float] = time.monotonic,
) -> None:
    original = edge_tts_module.Communicate

    class MeasuredCommunicate:
        def __init__(self, *args, **kwargs) -> None:
            self._inner = original(*args, **kwargs)
            candidate = args[1] if len(args) > 1 else kwargs.get("voice")
            self._voice = (
                candidate
                if isinstance(candidate, str)
                and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}", candidate)
                else "unknown"
            )

        async def stream(self):
            started = monotonic()
            audio_bytes = 0
            try:
                async for chunk in self._inner.stream():
                    if isinstance(chunk, Mapping) and chunk.get("type") == "audio":
                        data = chunk.get("data")
                        if isinstance(data, bytes):
                            audio_bytes = min(100_000_000, audio_bytes + len(data))
                    yield chunk
            except BaseException as error:
                emit(
                    _provider_event(
                        operation="tts",
                        model=None,
                        voice=self._voice,
                        elapsed=monotonic() - started,
                        response_bytes=0,
                        audio_bytes=audio_bytes,
                        error=error,
                    )
                )
                raise
            emit(
                _provider_event(
                    operation="tts",
                    model=None,
                    voice=self._voice,
                    elapsed=monotonic() - started,
                    response_bytes=0,
                    audio_bytes=audio_bytes,
                    error=None,
                )
            )

    edge_tts_module.Communicate = MeasuredCommunicate


def install_live_worker_projection(backend) -> None:
    original = backend.AnalysisWorker

    class LiveWorker:
        def __init__(self) -> None:
            self._inner = original(
                session_factory=backend.SessionLocal,
                analyzer=backend.ai_engine,
            )

        def start(self) -> None:
            self._inner.start()

        def stop(self, timeout_seconds: float = 5.0) -> None:
            self._inner.stop(timeout_seconds=timeout_seconds)

        def status(self) -> str:
            observed = self._inner.status()
            return (
                "running"
                if observed in {"starting", "idle", "processing"}
                else observed
            )

    backend.app.state.analysis_worker_factory = LiveWorker


def _validated_listen_socket(descriptor: int) -> socket.socket:
    try:
        candidate = socket.socket(fileno=descriptor)
        address = candidate.getsockname()
    except OSError as exc:
        raise ServerSafetyError("listen descriptor is invalid") from exc
    if (
        candidate.family != socket.AF_INET
        or not isinstance(address, tuple)
        or len(address) < 2
        or address[0] != "127.0.0.1"
        or type(address[1]) is not int
        or not 1 <= address[1] <= 65535
    ):
        candidate.close()
        raise ServerSafetyError("listen descriptor is not bound loopback")
    return candidate


def main(argv: list[str] | None = None) -> int:
    parsed = parse_args(argv)
    paths = validate_child_environment()
    configure_safe_logging(paths, secrets=(os.environ["DEEPSEEK_API_KEY"],))
    telemetry = TelemetryWriter(parsed.telemetry_fd)
    listen_socket = _validated_listen_socket(parsed.listen_fd)
    backend = load_backend()
    instrument_ai_engine(backend.ai_engine, emit=telemetry.emit)
    edge_tts = importlib.import_module("edge_tts")
    instrument_edge_tts(edge_tts, emit=telemetry.emit)
    install_live_worker_projection(backend)

    import uvicorn

    config = uvicorn.Config(
        backend.app,
        access_log=False,
        log_config=None,
        proxy_headers=False,
        workers=1,
    )
    server = uvicorn.Server(config)
    server.run(sockets=[listen_socket])
    return 0


def _entrypoint() -> int:
    try:
        return main()
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as error:
        name = type(error).__name__
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_.]{0,127}", name) is None:
            name = "Exception"
        print(f"live server failed error_type={name}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(_entrypoint())
