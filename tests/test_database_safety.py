import sys
from pathlib import Path

import pytest

# Ensure the project package is importable when pytest prepends tests/ to sys.path.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.backend.settings import (
    DATA_DIR,
    DEFAULT_APP_DB_PATH,
    RuntimeSettings,
    UnsafeTestDatabaseError,
    assert_safe_test_database_path,
)


def test_relative_app_db_path_resolves_from_project_root(monkeypatch):
    monkeypatch.setenv("APP_DB_MODE", "app")
    monkeypatch.setenv("APP_DB_PATH", "var/local-demo.db")
    settings = RuntimeSettings.from_env()
    assert settings.db_path.is_absolute()
    assert settings.db_path.name == "local-demo.db"


@pytest.mark.parametrize("candidate", [DEFAULT_APP_DB_PATH, DATA_DIR / "pytest.db"])
def test_test_mode_rejects_application_data_paths(candidate: Path):
    with pytest.raises(UnsafeTestDatabaseError, match="unsafe test database"):
        assert_safe_test_database_path(candidate)


def test_test_mode_accepts_a_pytest_temp_path(tmp_path: Path):
    candidate = tmp_path / "test.db"
    assert assert_safe_test_database_path(candidate) == candidate.resolve()


def test_importing_database_does_not_create_tables(tmp_path: Path):
    import os
    import subprocess
    import sys

    db_path = tmp_path / "import-only.db"
    env = os.environ | {"APP_DB_MODE": "test", "APP_DB_PATH": str(db_path)}
    result = subprocess.run(
        [sys.executable, "-c", "import app.backend.database"],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert not db_path.exists()
