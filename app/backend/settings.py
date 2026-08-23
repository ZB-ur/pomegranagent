from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_APP_DB_PATH = (DATA_DIR / "duck_diary.db").resolve()
DBMode = Literal["app", "test"]


class UnsafeTestDatabaseError(RuntimeError):
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
) -> Path:
    resolved = candidate.expanduser().resolve()
    formal_app = app_path.expanduser().resolve()
    formal_data = data_dir.expanduser().resolve()
    if resolved == formal_app or resolved.is_relative_to(formal_data):
        raise UnsafeTestDatabaseError(f"unsafe test database path: {resolved}")
    return resolved


@dataclass(frozen=True)
class RuntimeSettings:
    db_path: Path
    db_mode: DBMode

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "RuntimeSettings":
        source = os.environ if environ is None else environ
        raw_mode = source.get("APP_DB_MODE", "app")
        if raw_mode not in {"app", "test"}:
            raise RuntimeError("APP_DB_MODE must be 'app' or 'test'")
        path = _resolve_from_project(source.get("APP_DB_PATH", str(DEFAULT_APP_DB_PATH)))
        if raw_mode == "test":
            path = assert_safe_test_database_path(path)
        return cls(db_path=path, db_mode=raw_mode)
