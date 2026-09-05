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
from urllib.parse import parse_qs


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
    "APP_REVIEWED_SOURCE_HEAD",
    "APP_REVIEWED_SOURCE_MANIFEST",
    "APP_REVIEWED_SOURCE_ROOT",
    "APP_REVIEWED_SOURCE_TREE_OID",
    "APP_TTS_CACHE_PATH",
}
NEUTRAL_KEYS = {
    "__CF_USER_TEXT_ENCODING",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
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
ROSTER_TELEMETRY_KEYS = {
    "canonical_body_sha256",
    "error_code",
    "kind",
    "method",
    "order",
    "path",
    "replace_existing",
    "request_id",
    "status",
}
TTS_REQUEST_TELEMETRY_KEYS = {
    "audio_bytes",
    "cache_hit",
    "cache_relative_path",
    "cache_sha256",
    "effective_text_sha256",
    "kind",
    "method",
    "order",
    "path",
    "requested_text_sha256",
    "status",
    "truncated",
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
    source_root: Path
    source_manifest: Path
    source_head: str
    source_tree_oid: str
    source_inventory: tuple[tuple[str, int, int, str], ...]
    source_root_identity: tuple[str, int, int, int, int, int]
    source_manifest_identity: tuple[str, int, int, int, int, int]
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


def _read_regular_nofollow(path: Path, *, max_bytes: int) -> bytes:
    before = _resource_identity(path, directory=False)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        directory_flags |= os.O_NOFOLLOW
    absolute = Path(os.path.abspath(os.fspath(path)))
    parent = os.open(os.path.sep, directory_flags)
    descriptor = None
    try:
        for component in absolute.parts[1:-1]:
            next_parent = os.open(component, directory_flags, dir_fd=parent)
            os.close(parent)
            parent = next_parent
        descriptor = os.open(absolute.name, flags, dir_fd=parent)
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, max_bytes - total + 1))
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise ServerSafetyError("live server source file exceeds its bound")
            chunks.append(chunk)
        after = os.fstat(descriptor)
        if (
            str(path),
            after.st_dev,
            after.st_ino,
            stat.S_IMODE(after.st_mode),
            after.st_nlink,
            after.st_uid,
        ) != before:
            raise ServerSafetyError("live server source file changed")
    except ServerSafetyError:
        raise
    except OSError as exc:
        raise ServerSafetyError("live server source file is unavailable") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(parent)
    if _resource_identity(path, directory=False) != before:
        raise ServerSafetyError("live server source file identity changed")
    return b"".join(chunks)


def _strict_source_manifest(
    payload: bytes,
    *,
    source_head: str,
    tree_oid: str,
) -> tuple[tuple[str, int, int, str], ...]:
    def reject_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError
            result[key] = value
        return result

    try:
        text = payload.decode("utf-8", errors="strict")
        value = json.loads(text, object_pairs_hook=reject_duplicates)
    except (UnicodeError, TypeError, ValueError) as exc:
        raise ServerSafetyError("live server reviewed source manifest is invalid") from exc
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "files",
            "object_format",
            "protocol",
            "source_head",
            "tree_oid",
        }
        or value["protocol"] != "pomegranagent-reviewed-source/v1"
        or value["object_format"] != "sha1"
        or value["source_head"] != source_head
        or value["tree_oid"] != tree_oid
        or not isinstance(value["files"], list)
        or not value["files"]
        or json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
        != text
    ):
        raise ServerSafetyError("live server reviewed source manifest is invalid")
    inventory: list[tuple[str, int, int, str]] = []
    for item in value["files"]:
        if (
            not isinstance(item, dict)
            or set(item) != {"blob_oid", "git_mode", "path", "sha256", "size"}
            or not isinstance(item["path"], str)
            or not item["path"]
            or Path(item["path"]).is_absolute()
            or "\\" in item["path"]
            or any(part in {"", ".", ".."} for part in Path(item["path"]).parts)
            or not isinstance(item["git_mode"], int)
            or item["git_mode"] not in {0o100644, 0o100755}
            or type(item["size"]) is not int
            or not 0 <= item["size"] <= 1_000_000_000
            or not isinstance(item["sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) is None
            or not isinstance(item["blob_oid"], str)
            or re.fullmatch(r"[0-9a-f]{40}", item["blob_oid"]) is None
        ):
            raise ServerSafetyError("live server reviewed source manifest is invalid")
        inventory.append(
            (item["path"], item["git_mode"], item["size"], item["sha256"])
        )
    if len({item[0] for item in inventory}) != len(inventory):
        raise ServerSafetyError("live server reviewed source manifest is invalid")
    return tuple(inventory)


def _assert_source_inventory(paths: RuntimePaths) -> None:
    try:
        candidates = sorted(
            paths.source_root.rglob("*"),
            key=lambda item: item.relative_to(paths.source_root).as_posix(),
        )
    except OSError as exc:
        raise ServerSafetyError("live server reviewed source inventory is unavailable") from exc
    expected = {item[0]: item for item in paths.source_inventory}
    observed: set[str] = set()
    for candidate in candidates:
        relative = candidate.relative_to(paths.source_root).as_posix()
        try:
            entry = candidate.lstat()
        except OSError as exc:
            raise ServerSafetyError("live server reviewed source inventory changed") from exc
        if stat.S_ISDIR(entry.st_mode) and not stat.S_ISLNK(entry.st_mode):
            if (
                stat.S_IMODE(entry.st_mode) != 0o500
                or entry.st_uid != os.geteuid()
                or entry.st_nlink < 1
            ):
                raise ServerSafetyError("live server reviewed source directory changed")
            continue
        item = expected.get(relative)
        if item is None:
            raise ServerSafetyError("live server reviewed source inventory changed")
        _path, git_mode, size, digest = item
        payload = _read_regular_nofollow(candidate, max_bytes=1_000_000_000)
        if (
            stat.S_IMODE(entry.st_mode) != (0o500 if git_mode & 0o111 else 0o400)
            or len(payload) != size
            or hashlib.sha256(payload).hexdigest() != digest
        ):
            raise ServerSafetyError("live server reviewed source file changed")
        observed.add(relative)
    if observed != set(expected):
        raise ServerSafetyError("live server reviewed source inventory changed")


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
    if _resource_identity(paths.source_root, directory=True) != paths.source_root_identity:
        raise ServerSafetyError("live server reviewed source identity changed")
    if (
        _resource_identity(paths.source_manifest, directory=False)
        != paths.source_manifest_identity
    ):
        raise ServerSafetyError("live server reviewed source manifest changed")
    manifest_payload = _read_regular_nofollow(
        paths.source_manifest,
        max_bytes=128_000_000,
    )
    if _strict_source_manifest(
        manifest_payload,
        source_head=paths.source_head,
        tree_oid=paths.source_tree_oid,
    ) != paths.source_inventory:
        raise ServerSafetyError("live server reviewed source manifest changed")
    _assert_source_inventory(paths)


def _valid_macos_text_encoding(source: Mapping[str, str]) -> bool:
    value = source.get("__CF_USER_TEXT_ENCODING")
    if value is None:
        return True
    canonical_hex = r"(?:0|[1-9A-F][0-9A-F]{0,7})"
    return (
        sys.platform == "darwin"
        and re.fullmatch(
            rf"0x{os.geteuid():X}:0x{canonical_hex}:0x{canonical_hex}",
            value,
        )
        is not None
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
        or source.get("LC_CTYPE") not in {None, "C.UTF-8", "UTF-8"}
        or not source.get("DEEPSEEK_API_KEY")
        or not _valid_macos_text_encoding(source)
    ):
        raise ServerSafetyError("live server environment is invalid")

    paths = {
        key: Path(source[key])
        for key in (
            "APP_DB_PATH",
            "APP_LOG_PATH",
            "APP_MEDIA_ROOT",
            "APP_REVIEWED_SOURCE_MANIFEST",
            "APP_REVIEWED_SOURCE_ROOT",
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
    source_root = paths["APP_REVIEWED_SOURCE_ROOT"]
    source_manifest = paths["APP_REVIEWED_SOURCE_MANIFEST"]
    source_head = source["APP_REVIEWED_SOURCE_HEAD"]
    source_tree_oid = source["APP_REVIEWED_SOURCE_TREE_OID"]
    if (
        database.name != "duck-diary-uat.db"
        or media != root / "media"
        or tts_cache != root / "tts-cache"
        or app_log != root / "logs/app.log"
        or source_root != root / "reviewed-source"
        or source_manifest != root / "reviewed-source.json"
        or re.fullmatch(r"[0-9a-f]{40}", source_head) is None
        or re.fullmatch(r"[0-9a-f]{40}", source_tree_oid) is None
        or not _directory_owned(root)
        or not _directory_owned(media)
        or not _directory_owned(tts_cache)
        or not _directory_owned(app_log.parent)
        or not _directory_owned(source_root)
        or not _regular_owned(database)
        or not _regular_owned(app_log)
        or not _regular_owned(source_manifest)
    ):
        raise ServerSafetyError("live server environment resources are invalid")
    source_manifest_identity = _resource_identity(source_manifest, directory=False)
    source_root_identity = _resource_identity(source_root, directory=True)
    source_inventory = _strict_source_manifest(
        _read_regular_nofollow(source_manifest, max_bytes=128_000_000),
        source_head=source_head,
        tree_oid=source_tree_oid,
    )
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
        source_root=source_root,
        source_manifest=source_manifest,
        source_head=source_head,
        source_tree_oid=source_tree_oid,
        source_inventory=source_inventory,
        source_root_identity=source_root_identity,
        source_manifest_identity=source_manifest_identity,
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

    _CORRELATION = re.compile(
        r"(?:analysis-job:[1-9][0-9]*|chat-request:"
        r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})"
    )

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
            raise ServerSafetyError("provider correlation is unavailable")
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
        if frozenset(event) not in {
            frozenset(TELEMETRY_KEYS),
            frozenset(ROSTER_TELEMETRY_KEYS),
            frozenset(TTS_REQUEST_TELEMETRY_KEYS),
        }:
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


def _roster_request_evidence(payload: bytes) -> dict[str, object]:
    def reject_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError
            result[key] = value
        return result

    try:
        value = json.loads(
            payload.decode("utf-8", errors="strict"),
            object_pairs_hook=reject_duplicates,
        )
        if (
            not isinstance(value, dict)
            or set(value)
            != {"cycle", "entries", "month", "replace_existing", "request_id"}
            or not isinstance(value["request_id"], str)
            or re.fullmatch(
                r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
                value["request_id"],
            )
            is None
            or not isinstance(value["month"], str)
            or re.fullmatch(r"[0-9]{4}-(?:0[1-9]|1[0-2])", value["month"]) is None
            or not isinstance(value["cycle"], str)
            or not value["cycle"].strip()
            or len(value["cycle"].strip()) > 64
            or type(value["replace_existing"]) is not bool
            or not isinstance(value["entries"], list)
            or not 1 <= len(value["entries"]) <= 31
        ):
            raise ValueError
        entries = []
        for item in value["entries"]:
            if (
                not isinstance(item, dict)
                or set(item) != {"child_ids", "date"}
                or not isinstance(item["date"], str)
                or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", item["date"]) is None
                or item["date"][:7] != value["month"]
                or not isinstance(item["child_ids"], list)
                or len(item["child_ids"]) != 2
                or any(type(child_id) is not int or child_id <= 0 for child_id in item["child_ids"])
                or len(set(item["child_ids"])) != 2
            ):
                raise ValueError
            entries.append(
                {
                    "child_ids": sorted(item["child_ids"]),
                    "date": item["date"],
                }
            )
        entries.sort(key=lambda item: item["date"])
        if len({item["date"] for item in entries}) != len(entries):
            raise ValueError
    except (KeyError, TypeError, UnicodeError, ValueError) as exc:
        raise ServerSafetyError("monthly roster telemetry request is invalid") from exc
    canonical = json.dumps(
        {
            "cycle": value["cycle"].strip(),
            "entries": entries,
            "month": value["month"],
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return {
        "canonical_body_sha256": hashlib.sha256(canonical).hexdigest(),
        "replace_existing": value["replace_existing"],
        "request_id": value["request_id"],
    }


def _response_error_code(payload: bytes, *, status: int) -> str | None:
    try:
        value = json.loads(payload.decode("utf-8", errors="strict"))
        if not isinstance(value, dict):
            raise ValueError
        if status < 400:
            return None
        code = value["error"]["code"]
    except (KeyError, TypeError, UnicodeError, ValueError) as exc:
        raise ServerSafetyError("monthly roster telemetry response is invalid") from exc
    if not isinstance(code, str) or re.fullmatch(r"[A-Z][A-Z0-9_]{2,63}", code) is None:
        raise ServerSafetyError("monthly roster telemetry response is invalid")
    return code


class RosterAttemptTelemetry:
    """ASGI boundary retaining only canonical monthly-attempt facts."""

    def __init__(self, app, *, emit: Callable[[Mapping[str, object]], None]) -> None:
        if not callable(app) or not callable(emit):
            raise ServerSafetyError("monthly roster telemetry target is invalid")
        self._app = app
        self._emit = emit
        self._order = 0
        self._lock = threading.Lock()

    async def __call__(self, scope, receive, send):
        if (
            not isinstance(scope, Mapping)
            or scope.get("type") != "http"
            or scope.get("method") != "POST"
            or scope.get("path") != "/api/roster/month"
        ):
            return await self._app(scope, receive, send)

        request_body = bytearray()
        request_complete = False
        request_valid = True

        async def measured_receive():
            nonlocal request_complete, request_valid
            message = await receive()
            if not isinstance(message, Mapping):
                request_valid = False
                return message
            if message.get("type") != "http.request":
                if not request_complete:
                    request_valid = False
                return message
            chunk = message.get("body", b"")
            if not isinstance(chunk, bytes):
                request_valid = False
            elif len(request_body) + len(chunk) > 1_000_000:
                request_valid = False
            elif request_valid:
                request_body.extend(chunk)
            more_body = message.get("more_body", False)
            if type(more_body) is not bool or request_complete:
                request_valid = False
            if more_body is False:
                request_complete = True
            return message

        response_status = None
        response_body = bytearray()
        response_complete = False
        response_valid = True

        async def measured_send(message):
            nonlocal response_status, response_complete, response_valid
            if not isinstance(message, Mapping):
                response_valid = False
                return await send(message)
            message_type = message.get("type")
            if message_type == "http.response.start":
                status = message.get("status")
                if (
                    type(status) is not int
                    or not 100 <= status <= 599
                    or response_status is not None
                ):
                    response_valid = False
                else:
                    response_status = status
            elif message_type == "http.response.body":
                chunk = message.get("body", b"")
                if not isinstance(chunk, bytes) or response_status is None:
                    response_valid = False
                elif len(response_body) + len(chunk) > 1_000_000:
                    response_valid = False
                elif response_valid:
                    response_body.extend(chunk)
                more_body = message.get("more_body", False)
                if type(more_body) is not bool or response_complete:
                    response_valid = False
                if more_body is False:
                    response_complete = True
            await send(message)

        result = await self._app(scope, measured_receive, measured_send)
        if response_status not in {200, 409}:
            return result
        if not request_valid or not request_complete:
            raise ServerSafetyError("monthly roster telemetry request is invalid")
        if not response_valid:
            raise ServerSafetyError("monthly roster telemetry response is invalid")
        if not response_complete:
            raise ServerSafetyError("monthly roster telemetry response is incomplete")
        evidence = _roster_request_evidence(bytes(request_body))
        error_code = _response_error_code(bytes(response_body), status=response_status)
        with self._lock:
            order = self._order + 1
            self._emit(
                {
                    **evidence,
                    "error_code": error_code,
                    "kind": "roster_attempt",
                    "method": "POST",
                    "order": order,
                    "path": "/api/roster/month",
                    "status": response_status,
                }
            )
            self._order = order
        return result


class TTSRequestTelemetry:
    """Retain safe request/cache facts for every UI TTS endpoint call."""

    def __init__(
        self,
        app,
        *,
        emit: Callable[[Mapping[str, object]], None],
        tts_cache: Path,
    ) -> None:
        if not callable(app) or not callable(emit) or not _directory_owned(tts_cache):
            raise ServerSafetyError("TTS request telemetry target is invalid")
        self._app = app
        self._emit = emit
        self._tts_cache = tts_cache
        self._order = 0
        self._lock = threading.Lock()

    async def __call__(self, scope, receive, send):
        if (
            not isinstance(scope, Mapping)
            or scope.get("type") != "http"
            or scope.get("method") != "GET"
            or scope.get("path") != "/api/tts"
        ):
            return await self._app(scope, receive, send)
        raw_query = scope.get("query_string")
        try:
            if not isinstance(raw_query, bytes) or len(raw_query) > 10_000:
                raise ValueError
            query = parse_qs(
                raw_query.decode("ascii", errors="strict"),
                keep_blank_values=True,
                strict_parsing=True,
                max_num_fields=1,
                encoding="utf-8",
                errors="strict",
            )
            if set(query) != {"text"} or len(query["text"]) != 1:
                raise ValueError
            requested_text = query["text"][0]
            stripped_text = requested_text.strip()
            effective_text = stripped_text[:500]
            if not effective_text:
                raise ValueError
        except (UnicodeError, ValueError) as exc:
            raise ServerSafetyError("TTS request telemetry query is invalid") from exc
        encoded_requested = requested_text.encode("utf-8")
        encoded_effective = effective_text.encode("utf-8")
        cache_name = (
            hashlib.md5(encoded_effective, usedforsecurity=False).hexdigest() + ".mp3"
        )
        cache_file = self._tts_cache / cache_name
        try:
            cache_file.lstat()
        except FileNotFoundError:
            cache_before = None
        except OSError as exc:
            raise ServerSafetyError("TTS request telemetry cache is unavailable") from exc
        else:
            cache_before = _read_regular_nofollow(cache_file, max_bytes=100_000_000)
        with self._lock:
            self._order += 1
            order = self._order

        response_status = None
        response_body = bytearray()
        response_complete = False

        async def measured_send(message):
            nonlocal response_status, response_complete
            if not isinstance(message, Mapping):
                raise ServerSafetyError("TTS request telemetry response is invalid")
            if message.get("type") == "http.response.start":
                status = message.get("status")
                if (
                    type(status) is not int
                    or not 100 <= status <= 599
                    or response_status is not None
                ):
                    raise ServerSafetyError("TTS request telemetry response is invalid")
                response_status = status
            elif message.get("type") == "http.response.body":
                chunk = message.get("body", b"")
                if not isinstance(chunk, bytes) or response_status is None:
                    raise ServerSafetyError("TTS request telemetry response is invalid")
                response_body.extend(chunk)
                if len(response_body) > 100_000_000:
                    raise ServerSafetyError("TTS request telemetry response is invalid")
                if not message.get("more_body", False):
                    response_complete = True
            await send(message)

        await self._app(scope, receive, measured_send)
        if response_status != 200 or not response_complete or not response_body:
            raise ServerSafetyError("TTS request telemetry response is invalid")
        cache_after = _read_regular_nofollow(cache_file, max_bytes=100_000_000)
        if bytes(response_body) != cache_after or (
            cache_before is not None and cache_before != cache_after
        ):
            raise ServerSafetyError("TTS request telemetry cache is inconsistent")
        self._emit(
            {
                "audio_bytes": len(cache_after),
                "cache_hit": cache_before is not None,
                "cache_relative_path": f"tts-cache/{cache_name}",
                "cache_sha256": hashlib.sha256(cache_after).hexdigest(),
                "effective_text_sha256": hashlib.sha256(encoded_effective).hexdigest(),
                "kind": "tts_request",
                "method": "GET",
                "order": order,
                "path": "/api/tts",
                "requested_text_sha256": hashlib.sha256(encoded_requested).hexdigest(),
                "status": response_status,
                "truncated": len(stripped_text) > 500,
                "voice": "zh-CN-XiaoxiaoNeural",
            }
        )


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
        claim = kwargs.get("claim") if "claim" in kwargs else (
            args[1] if len(args) > 1 else None
        )
        request_id = getattr(claim, "request_id", None)
        if (
            not isinstance(request_id, str)
            or re.fullmatch(
                r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
                request_id,
            )
            is None
        ):
            raise ServerSafetyError("chat provider correlation is unavailable")
        context.set_next_correlation(f"chat-request:{request_id}")
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
    if paths.source_root != PROJECT_ROOT:
        raise ServerSafetyError("live server is not executing from reviewed source")
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

    instrumented_app = RosterAttemptTelemetry(backend.app, emit=telemetry.emit)
    instrumented_app = TTSRequestTelemetry(
        instrumented_app,
        emit=telemetry.emit,
        tts_cache=paths.tts_cache,
    )
    config = uvicorn.Config(
        instrumented_app,
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
