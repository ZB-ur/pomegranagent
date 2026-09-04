#!/usr/bin/env python3
"""Isolated app-mode Uvicorn wrapper for retained live-provider UAT."""
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
import functools
import hashlib
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
    "cache_relative_path",
    "cache_sha256",
    "correlation_id",
    "error_class",
    "latency_bucket",
    "model",
    "operation",
    "parse_valid",
    "provider",
    "response_bytes",
    "response_sha256",
    "status",
    "voice",
}


class ServerSafetyError(RuntimeError):
    """The child refuses to import or serve from an unsafe runtime."""


class ProviderPayloadInvalid(ValueError):
    """A provider returned bytes that are not a parse-valid JSON object."""


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    root: Path
    database: Path
    media: Path
    tts_cache: Path
    app_log: Path
    identities: tuple[tuple[str, int, int, int, int, int], ...]


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
        and not entry.st_mode & 0o022
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


def _resource_identity(path: Path, *, directory: bool) -> tuple[str, int, int, int, int, int]:
    directory_flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        directory_flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        directory_flags |= os.O_NOFOLLOW
    absolute = Path(os.path.abspath(os.fspath(path)))
    descriptor = os.open(os.path.sep, directory_flags)
    try:
        for index, component in enumerate(absolute.parts[1:]):
            is_leaf = index == len(absolute.parts[1:]) - 1
            flags = os.O_RDONLY
            if not is_leaf or directory:
                flags |= getattr(os, "O_DIRECTORY", 0)
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
    except OSError as exc:
        os.close(descriptor)
        raise ServerSafetyError("live server runtime identity is unavailable") from exc
    try:
        entry = os.fstat(descriptor)
        kind_valid = stat.S_ISDIR(entry.st_mode) if directory else stat.S_ISREG(entry.st_mode)
        if (
            not kind_valid
            or entry.st_uid != os.geteuid()
            or entry.st_mode & 0o022
            or (not directory and entry.st_nlink != 1)
            or (directory and entry.st_nlink < 1)
        ):
            raise ServerSafetyError("live server runtime identity is unsafe")
        return (
            str(path),
            entry.st_dev,
            entry.st_ino,
            stat.S_IMODE(entry.st_mode),
            entry.st_nlink,
            entry.st_uid,
        )
    finally:
        os.close(descriptor)


def assert_runtime_paths_pinned(paths: RuntimePaths) -> None:
    expected_paths = (
        (paths.root, True),
        (paths.database, False),
        (paths.media, True),
        (paths.tts_cache, True),
        (paths.app_log.parent, True),
        (paths.app_log, False),
    )
    observed = tuple(
        _resource_identity(path, directory=directory)
        for path, directory in expected_paths
    )
    if observed != paths.identities:
        raise ServerSafetyError("live server runtime identity changed")


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
    media = paths["APP_MEDIA_ROOT"]
    tts_cache = paths["APP_TTS_CACHE_PATH"]
    app_log = paths["APP_LOG_PATH"]
    if (
        database.name != "duck-diary-uat.db"
        or media != root / "media"
        or tts_cache != root / "tts-cache"
        or app_log != root / "logs/app.log"
        or not _directory_owned(root)
        or not _directory_owned(media)
        or not _directory_owned(tts_cache)
        or not _directory_owned(app_log.parent)
        or not _regular_owned(database)
        or not _regular_owned(app_log)
    ):
        raise ServerSafetyError("live server environment resources are invalid")
    identities = tuple(
        _resource_identity(path, directory=directory)
        for path, directory in (
            (root, True),
            (database, False),
            (media, True),
            (tts_cache, True),
            (app_log.parent, True),
            (app_log, False),
        )
    )
    runtime = RuntimePaths(
        root=root,
        database=database,
        media=media,
        tts_cache=tts_cache,
        app_log=app_log,
        identities=identities,
    )
    assert_runtime_paths_pinned(runtime)
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
    correlation_id: str,
    parse_valid: bool | None,
    response_sha256: str | None,
    cache_relative_path: str | None = None,
    cache_sha256: str | None = None,
    error: BaseException | None,
) -> dict[str, object]:
    return {
        "audio_bytes": audio_bytes,
        "cache_relative_path": cache_relative_path,
        "cache_sha256": cache_sha256,
        "correlation_id": correlation_id,
        "error_class": None if error is None else _error_class(error),
        "latency_bucket": _latency_bucket(max(0.0, elapsed)),
        "model": model,
        "operation": operation,
        "parse_valid": parse_valid,
        "provider": "edge-tts" if operation == "tts" else "deepseek",
        "response_bytes": response_bytes,
        "response_sha256": response_sha256,
        "status": "ok" if error is None else "error",
        "voice": voice,
    }


class ProviderTelemetryContext:
    """Thread-local operation/correlation scope for raw provider calls."""

    _CORRELATION = re.compile(r"(?:conversation|analysis-job):[1-9][0-9]*")

    def __init__(self) -> None:
        self._local = threading.local()

    def set_next_correlation(self, value: str) -> None:
        if self._CORRELATION.fullmatch(value) is None:
            raise ServerSafetyError("provider correlation is invalid")
        self._local.next_correlation = value

    def _take_next_correlation(self) -> str | None:
        value = getattr(self._local, "next_correlation", None)
        self._local.next_correlation = None
        return value

    @contextmanager
    def correlate(self, value: str):
        if self._CORRELATION.fullmatch(value) is None:
            raise ServerSafetyError("provider correlation is invalid")
        previous = getattr(self._local, "explicit_correlation", None)
        self._local.explicit_correlation = value
        try:
            yield
        finally:
            self._local.explicit_correlation = previous

    @contextmanager
    def operation(self, operation: str):
        previous_operation = getattr(self._local, "operation", None)
        previous_correlation = getattr(self._local, "active_correlation", None)
        correlation = getattr(self._local, "explicit_correlation", None)
        if correlation is None:
            correlation = self._take_next_correlation()
        self._local.operation = operation
        self._local.active_correlation = correlation
        try:
            yield
        finally:
            self._local.operation = previous_operation
            self._local.active_correlation = previous_correlation

    def active(self) -> tuple[str | None, str | None]:
        return (
            getattr(self._local, "operation", None),
            getattr(self._local, "active_correlation", None),
        )


def instrument_ai_engine(
    ai_engine,
    *,
    emit: Callable[[Mapping[str, object]], None],
    monotonic: Callable[[], float] = time.monotonic,
) -> ProviderTelemetryContext:
    """Measure the raw parse-valid boundary for required DeepSeek operations."""

    model = ai_engine.MODEL
    if not isinstance(model, str) or re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", model
    ) is None:
        raise ServerSafetyError("live provider model is invalid")

    original_llm = getattr(ai_engine, "_llm", None)
    parser = getattr(ai_engine, "_parse_json", None)
    if not callable(original_llm) or not callable(parser):
        raise ServerSafetyError("live raw provider instrumentation target is missing")
    context = ProviderTelemetryContext()

    def measured_llm(*args, **kwargs):
        operation, correlation = context.active()
        if operation is None:
            return original_llm(*args, **kwargs)
        if correlation is None:
            correlation = "conversation:0"
        started = monotonic()
        try:
            raw = original_llm(*args, **kwargs)
        except BaseException as error:
            emit(
                _provider_event(
                    operation=operation,
                    model=model,
                    voice=None,
                    elapsed=monotonic() - started,
                    response_bytes=0,
                    audio_bytes=0,
                    correlation_id=correlation,
                    parse_valid=False,
                    response_sha256=None,
                    error=error,
                )
            )
            raise
        encoded = raw.encode("utf-8") if isinstance(raw, str) else b""
        parse_error: BaseException | None = None
        try:
            parsed = parser(raw)
            if not isinstance(parsed, dict) or not encoded:
                raise ProviderPayloadInvalid()
        except BaseException:
            parse_error = ProviderPayloadInvalid()
        emit(
            _provider_event(
                operation=operation,
                model=model,
                voice=None,
                elapsed=monotonic() - started,
                response_bytes=min(len(encoded), 100_000_000),
                audio_bytes=0,
                correlation_id=correlation,
                parse_valid=parse_error is None,
                response_sha256=hashlib.sha256(encoded).hexdigest() if encoded else None,
                error=parse_error,
            )
        )
        return raw

    ai_engine._llm = measured_llm

    def wrap(operation: str, function):
        @functools.wraps(function)
        def measured(*args, **kwargs):
            with context.operation(operation):
                return function(*args, **kwargs)

        return measured

    for operation in ("chat_reply", "extract_info", "assess_conversation"):
        original = getattr(ai_engine, operation, None)
        if not callable(original):
            raise ServerSafetyError("live AI instrumentation target is missing")
        setattr(ai_engine, operation, wrap(operation, original))
    return context


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
            text = args[0] if args else kwargs.get("text")
            self._text = text if isinstance(text, str) else ""
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
            audio_hasher = hashlib.sha256()
            try:
                async for chunk in self._inner.stream():
                    if isinstance(chunk, Mapping) and chunk.get("type") == "audio":
                        data = chunk.get("data")
                        if isinstance(data, bytes):
                            audio_bytes = min(100_000_000, audio_bytes + len(data))
                            audio_hasher.update(data)
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
                        correlation_id="message-text:"
                        + hashlib.sha256(self._text.encode("utf-8")).hexdigest(),
                        parse_valid=None,
                        response_sha256=None,
                        cache_relative_path="tts-cache/"
                        + hashlib.md5(
                            self._text.encode("utf-8"),
                            usedforsecurity=False,
                        ).hexdigest()
                        + ".mp3",
                        cache_sha256=audio_hasher.hexdigest() if audio_bytes else None,
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
                    correlation_id="message-text:"
                    + hashlib.sha256(self._text.encode("utf-8")).hexdigest(),
                    parse_valid=None,
                    response_sha256=None,
                    cache_relative_path="tts-cache/"
                    + hashlib.md5(
                        self._text.encode("utf-8"),
                        usedforsecurity=False,
                    ).hexdigest()
                    + ".mp3",
                    cache_sha256=audio_hasher.hexdigest() if audio_bytes else None,
                    error=None,
                )
            )

    edge_tts_module.Communicate = MeasuredCommunicate


def install_chat_correlation(backend, context: ProviderTelemetryContext) -> None:
    conversations = importlib.import_module("app.backend.routes.conversations")
    original = conversations.build_chat_context

    @functools.wraps(original)
    def correlated(*args, **kwargs):
        result = original(*args, **kwargs)
        conversation_id = getattr(result, "conversation_id", None)
        if type(conversation_id) is not int or conversation_id <= 0:
            raise ServerSafetyError("chat provider correlation is unavailable")
        context.set_next_correlation(f"conversation:{conversation_id}")
        return result

    conversations.build_chat_context = correlated
    if getattr(backend, "ai_engine", None) is not conversations.ai_engine:
        raise ServerSafetyError("chat provider instrumentation identity mismatch")


def install_live_worker_projection(
    backend,
    context: ProviderTelemetryContext,
) -> None:
    original = backend.AnalysisWorker

    class CorrelatedAnalyzer:
        def __init__(self, worker) -> None:
            self._worker = worker

        def _job_id(self) -> int:
            job_id = getattr(self._worker, "_active_job_id", None)
            if type(job_id) is not int or job_id <= 0:
                raise ServerSafetyError("analysis provider correlation is unavailable")
            return job_id

        def extract_info(self, transcript):
            with context.correlate(f"analysis-job:{self._job_id()}"):
                return backend.ai_engine.extract_info(transcript)

        def assess_conversation(self, transcript, dimensions):
            with context.correlate(f"analysis-job:{self._job_id()}"):
                return backend.ai_engine.assess_conversation(transcript, dimensions)

    class LiveWorker:
        def __init__(self) -> None:
            self._inner = original(
                session_factory=backend.SessionLocal,
                analyzer=backend.ai_engine,
            )
            self._inner._analyzer = CorrelatedAnalyzer(self._inner)

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
    assert_runtime_paths_pinned(paths)
    configure_safe_logging(paths, secrets=(os.environ["DEEPSEEK_API_KEY"],))
    assert_runtime_paths_pinned(paths)
    telemetry = TelemetryWriter(parsed.telemetry_fd)
    listen_socket = _validated_listen_socket(parsed.listen_fd)
    backend = load_backend()
    assert_runtime_paths_pinned(paths)
    provider_context = instrument_ai_engine(backend.ai_engine, emit=telemetry.emit)
    install_chat_correlation(backend, provider_context)
    edge_tts = importlib.import_module("edge_tts")
    instrument_edge_tts(edge_tts, emit=telemetry.emit)
    install_live_worker_projection(backend, provider_context)
    assert_runtime_paths_pinned(paths)

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
    assert_runtime_paths_pinned(paths)
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
