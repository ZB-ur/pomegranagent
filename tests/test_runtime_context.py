"""Public runtime context and import-time resource isolation contracts."""
from __future__ import annotations

from datetime import date
import json
import os
import subprocess
import sys

from sqlalchemy import select

import conftest as test_runtime
from app.backend import main as main_module, models
from app.backend.database import SETTINGS, SessionLocal


class _FrozenContextClock:
    timezone_name = "Asia/Shanghai"

    def __init__(self) -> None:
        self.today_calls = 0
        self.week_anchors: list[date | None] = []

    def business_today(self) -> date:
        self.today_calls += 1
        return date(2026, 9, 2)

    def week_window(self, anchor: date | None = None) -> tuple[date, date]:
        self.week_anchors.append(anchor)
        if anchor is None:
            raise AssertionError("runtime context must reuse its captured business date")
        return date(2026, 8, 31), date(2026, 9, 7)


def test_runtime_context_is_public_static_exact_and_reads_date_once(client, monkeypatch) -> None:
    from app.backend.routes import runtime as runtime_routes

    clock = _FrozenContextClock()
    monkeypatch.setattr(runtime_routes, "BUSINESS_CLOCK", clock)

    response = client.get("/api/runtime/context")

    assert response.status_code == 200
    assert response.json() == {
        "timezone": "Asia/Shanghai",
        "business_date": "2026-09-02",
        "week_start": "2026-08-31",
        "week_end_exclusive": "2026-09-07",
    }
    assert clock.today_calls == 1
    assert clock.week_anchors == [date(2026, 9, 2)]
    serialized = json.dumps(response.json(), ensure_ascii=False)
    assert str(test_runtime.ROOT) not in serialized
    assert str(test_runtime.TEST_RUNTIME_DIR) not in serialized


def test_runtime_context_rejects_every_query_shape_before_reading_the_clock(
    client,
    monkeypatch,
) -> None:
    from app.backend.routes import runtime as runtime_routes

    class UnreadableClock:
        timezone_name = "Asia/Shanghai"

        def business_today(self) -> date:
            raise AssertionError("invalid query must be rejected before reading time")

    monkeypatch.setattr(runtime_routes, "BUSINESS_CLOCK", UnreadableClock())

    for query in ("unknown=1", "unknown=1&unknown=2", "=blank", "empty="):
        response = client.get(f"/api/runtime/context?{query}")
        assert response.status_code == 422, query
        assert response.json()["error"]["code"] == "VALIDATION_ERROR", query


def test_pytest_runtime_paths_are_set_before_application_import() -> None:
    expected_media = (test_runtime.TEST_RUNTIME_DIR / "media").resolve()

    assert os.environ.get("APP_BUSINESS_TIMEZONE") == "Asia/Shanghai"
    assert os.environ.get("APP_MEDIA_ROOT") == str(expected_media)
    assert os.environ.get("APP_LOG_PATH") == str(test_runtime.TEST_APPLICATION_LOG_PATH)
    assert os.environ.get("APP_TTS_CACHE_PATH") == str(test_runtime.TEST_TTS_CACHE_PATH)
    assert SETTINGS.media_root == expected_media
    assert SETTINGS.log_path == test_runtime.TEST_APPLICATION_LOG_PATH
    assert SETTINGS.tts_cache_path == test_runtime.TEST_TTS_CACHE_PATH
    assert main_module.MEDIA_ROOT == expected_media
    assert main_module.TTS_CACHE_DIR == test_runtime.TEST_TTS_CACHE_PATH


def test_fresh_main_import_injects_log_tts_and_media_paths(tmp_path) -> None:
    database = (tmp_path / "runtime.db").resolve()
    log_path = (tmp_path / "logs" / "runtime.log").resolve()
    media_root = (tmp_path / "media").resolve()
    tts_root = (tmp_path / "tts").resolve()
    redirected_log = (tmp_path / "captured.log").resolve()
    script = """
import json
import logging
from pathlib import Path

requested = []
original = logging.FileHandler
redirected = Path(__import__('os').environ['TEST_REDIRECTED_LOG'])

def safe_file_handler(filename, *args, **kwargs):
    requested.append(str(Path(filename).resolve()))
    return original(redirected, *args, **kwargs)

logging.FileHandler = safe_file_handler
from app.backend import main
logging.FileHandler = original
print(json.dumps({
    'requested_logs': requested,
    'settings': {
        'log': str(main.SETTINGS.log_path),
        'media': str(main.SETTINGS.media_root),
        'tts': str(main.SETTINGS.tts_cache_path),
    },
    'main': {
        'media': str(main.MEDIA_ROOT),
        'tts': str(main.TTS_CACHE_DIR),
    },
}))
"""
    environment = {
        **os.environ,
        "APP_DB_MODE": "test",
        "APP_DB_PATH": str(database),
        "APP_BUSINESS_TIMEZONE": "Asia/Shanghai",
        "APP_LOG_PATH": str(log_path),
        "APP_MEDIA_ROOT": str(media_root),
        "APP_TTS_CACHE_PATH": str(tts_root),
        "PYTHON_DOTENV_DISABLED": "1",
        "TEST_REDIRECTED_LOG": str(redirected_log),
    }

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=test_runtime.ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    assert payload == {
        "requested_logs": [str(log_path)],
        "settings": {
            "log": str(log_path),
            "media": str(media_root),
            "tts": str(tts_root),
        },
        "main": {"media": str(media_root), "tts": str(tts_root)},
    }


def test_ordinary_lifespan_leaves_people_and_demo_graph_empty(client) -> None:
    del client
    with SessionLocal() as db:
        assert db.scalars(select(models.AssessmentDimension)).all()
        assert db.scalars(select(models.Child)).all() == []
        assert db.scalars(select(models.Duck)).all() == []
        assert db.scalars(select(models.DutyRoster)).all() == []
        assert db.scalars(select(models.Conversation)).all() == []
