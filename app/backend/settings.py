from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_APP_DB_PATH = (DATA_DIR / "duck_diary.db").resolve()
DEFAULT_MEDIA_ROOT = (DATA_DIR / "media").resolve()
DEFAULT_LOG_PATH = (PROJECT_ROOT / "logs" / "app.log").resolve()
DEFAULT_TTS_CACHE_PATH = (DATA_DIR / "tts_cache").resolve()
DEFAULT_BUSINESS_TIMEZONE = "Asia/Shanghai"
DBMode = Literal["app", "test"]


class UnsafeTestRuntimePathError(RuntimeError):
    pass


class UnsafeTestDatabaseError(UnsafeTestRuntimePathError):
    pass


def _resolve_from_project(value: str | Path) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    return candidate.resolve()


def assert_safe_test_database_path(
    candidate: Path,
    *,
    app_path: Path = DEFAULT_APP_DB_PATH,
    data_dir: Path = DATA_DIR,
    log_path: Path = DEFAULT_LOG_PATH,
) -> Path:
    resolved = candidate.expanduser().resolve()
    formal_app = app_path.expanduser().resolve()
    formal_data = data_dir.expanduser().resolve()
    formal_log_root = log_path.expanduser().resolve().parent
    if (
        resolved == formal_app
        or resolved.is_relative_to(formal_data)
        or resolved.is_relative_to(formal_log_root)
    ):
        raise UnsafeTestDatabaseError(f"unsafe test database path: {resolved}")
    return resolved


def assert_safe_test_runtime_path(candidate: Path, *, resource: str) -> Path:
    """Reject test resources that could mutate retained application state."""

    resolved = candidate.expanduser().resolve()
    protected_roots = (
        DEFAULT_APP_DB_PATH,
        DATA_DIR.resolve(),
        DEFAULT_MEDIA_ROOT,
        DEFAULT_LOG_PATH.parent,
        DEFAULT_TTS_CACHE_PATH,
    )
    if any(
        resolved == protected or resolved.is_relative_to(protected)
        for protected in protected_roots
    ):
        raise UnsafeTestRuntimePathError(f"unsafe test runtime path for {resource}")
    return resolved


@dataclass(frozen=True)
class RuntimeSettings:
    db_path: Path
    db_mode: DBMode
    business_timezone: str
    media_root: Path
    log_path: Path
    tts_cache_path: Path

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "RuntimeSettings":
        source = os.environ if environ is None else environ
        raw_mode = source.get("APP_DB_MODE", "app")
        if raw_mode not in {"app", "test"}:
            raise RuntimeError("APP_DB_MODE must be 'app' or 'test'")
        path = _resolve_from_project(source.get("APP_DB_PATH", str(DEFAULT_APP_DB_PATH)))
        if raw_mode == "test":
            path = assert_safe_test_database_path(path)

        business_timezone = source.get(
            "APP_BUSINESS_TIMEZONE",
            DEFAULT_BUSINESS_TIMEZONE,
        )
        try:
            ZoneInfo(business_timezone)
        except (TypeError, ValueError, ZoneInfoNotFoundError):
            raise RuntimeError(
                "APP_BUSINESS_TIMEZONE must be a valid IANA timezone"
            ) from None

        if raw_mode == "test":
            runtime_root = path.parent
            media_default = runtime_root / "media"
            log_default = runtime_root / "app.log"
            tts_cache_default = runtime_root / "tts-cache"
        else:
            media_default = DEFAULT_MEDIA_ROOT
            log_default = DEFAULT_LOG_PATH
            tts_cache_default = DEFAULT_TTS_CACHE_PATH

        media_root = _resolve_from_project(
            source.get("APP_MEDIA_ROOT", str(media_default))
        )
        log_path = _resolve_from_project(source.get("APP_LOG_PATH", str(log_default)))
        tts_cache_path = _resolve_from_project(
            source.get("APP_TTS_CACHE_PATH", str(tts_cache_default))
        )
        if raw_mode == "test":
            media_root = assert_safe_test_runtime_path(
                media_root,
                resource="media",
            )
            log_path = assert_safe_test_runtime_path(log_path, resource="log")
            tts_cache_path = assert_safe_test_runtime_path(
                tts_cache_path,
                resource="TTS cache",
            )

        return cls(
            db_path=path,
            db_mode=raw_mode,
            business_timezone=business_timezone,
            media_root=media_root,
            log_path=log_path,
            tts_cache_path=tts_cache_path,
        )
