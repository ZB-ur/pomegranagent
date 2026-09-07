import asyncio
from concurrent.futures import ThreadPoolExecutor
import importlib.util
from io import BytesIO
import os
from pathlib import Path
import re
import sqlite3
import subprocess
from types import SimpleNamespace

import pytest
from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
BROWSER_ENTRY = ROOT / "app/frontend/child/browser.mjs"
CHILD_SERVER = ROOT / "tests/browser/child_server.py"
BROWSER_CONFTEST = ROOT / "tests/browser/conftest.py"
VIEWPORTS = [{"width": 1024, "height": 576}, {"width": 1280, "height": 720}]
VIEWPORT_IDS = ["1024x576", "1280x720"]
READY_GEOMETRY = {
    (1024, 576): {
        "header": {"x": 40, "y": 20, "width": 944, "height": 64},
        "content": {"x": 40, "y": 96, "width": 944, "height": 460},
        "state": {"x": 80, "y": 128, "width": 864, "height": 404},
        "panel": {"x": 80, "y": 224, "width": 608, "height": 308},
        "orb": {"x": 712, "y": 224, "width": 232, "height": 308},
    },
    (1280, 720): {
        "header": {"x": 40, "y": 20, "width": 1200, "height": 64},
        "content": {"x": 40, "y": 96, "width": 1200, "height": 604},
        "state": {"x": 80, "y": 128, "width": 1120, "height": 540},
        "panel": {"x": 116, "y": 240, "width": 760, "height": 396},
        "orb": {"x": 900, "y": 240, "width": 264, "height": 396},
    },
}


def browser_source() -> str:
    return BROWSER_ENTRY.read_text(encoding="utf-8")


def load_child_server_module():
    spec = importlib.util.spec_from_file_location("task6b_child_server", CHILD_SERVER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_browser_conftest_module():
    spec = importlib.util.spec_from_file_location(
        "task6b_browser_conftest",
        BROWSER_CONFTEST,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def clean_provider_environment(monkeypatch):
    forbidden = ("DEEPSEEK", "OPENAI", "API_KEY", "PROVIDER", "PROXY")
    for name in tuple(os.environ):
        if any(token in name.upper() for token in forbidden):
            monkeypatch.delenv(name, raising=False)


SYNTHETIC_DRY_RUN = """
Chrome for Testing 151.0.7922.34 (playwright chromium v1234)
  Download url:        https://invalid.example/chromium.zip
  Download fallback 1: https://invalid.example/chromium-fallback.zip
  Install location:    {cft}

FFmpeg playwright build v1011
  Download url:        https://invalid.example/ffmpeg.zip
  Install location:    /ignore/ffmpeg-1011

Chrome Headless Shell 151.0.7922.34 (playwright chromium-headless-shell v1234)
  Download url:        https://invalid.example/headless.zip
  Install location:    {shell}
"""

RUNTIME_VERSION = {
    "release_id": "2026.08.23-stabilization.1",
    "api_version": "2",
    "schema_version": "2",
}
SYNTHETIC_CHILD = {"id": 1, "name": "测试幼儿", "nickname": "小芽", "avatar": None}
SYNTHETIC_ACTIVE = {
    "conversation": {
        "id": 17,
        "child_id": 1,
        "status": "active",
        "revision": 2,
        "round": 1,
        "last_message_id": 102,
        "messages": [
            {"id": 101, "role": "child", "text": "我给小鸭准备了清水。"},
            {"id": 102, "role": "diary", "text": "谢谢你认真照顾小鸭。"},
        ],
    }
}
NEAR_LIMIT_CHILD_TEXT = "起" + ("鸭" * 1988) + "终"


def prepare_child_page(harness, viewport, *, roster, active_by_child=None):
    page = harness.page
    page.set_viewport_size(viewport)
    requested = []
    page.on("request", lambda request: requested.append(request.url))
    harness.fulfill_json("**/api/roster/today", roster)
    for child in roster:
        active = (active_by_child or {}).get(child["id"], {"conversation": None})
        harness.fulfill_json(f"**/api/children/{child['id']}/active-conversation", active)
    harness.fulfill_bytes("**/api/tts?*", b"synthetic-audio", content_type="audio/mpeg")
    page.goto(f"{harness.server.base_url}/", wait_until="domcontentloaded")
    page.get_by_role("button", name="开始", exact=True).wait_for()
    page.get_by_role("button", name="开始", exact=True).click()
    return requested


def wait_for_active_ready(page):
    record = page.get_by_role("button", name="开始说话", exact=True)
    record.wait_for()
    return record


def test_browser_entry_named_machine_facade():
    source = browser_source()
    assert "import { bootstrapBrowserChildApp } from './app.mjs';" in source
    assert "import { bootstrapBrowserChildAPI } from './api.mjs';" in source
    assert "import { createChildView } from './view.mjs';" in source
    assert "import { createSessionStore, createDraft, mergeRecovery } from './session-store.mjs';" in source
    assert "import { createSpeechController } from './speech.mjs';" in source
    assert "import { createTTSController } from './tts.mjs';" in source
    assert re.search(
        r"import\s*\{\s*STATES,\s*assertSnapshot,\s*controlsFor,\s*"
        r"createInitialSnapshot,\s*transition,?\s*\}\s*from './machine\.mjs';",
        source,
    )
    assert "const machine = Object.freeze({" in source
    for name in ("STATES", "assertSnapshot", "controlsFor", "createInitialSnapshot", "transition"):
        assert re.search(rf"^\s{{2}}{name},?$", source, re.MULTILINE)
    assert "export " not in source


def test_browser_entry_keyboard_policy_intercepts_only_record_button_space_repeat():
    source = browser_source()
    assert "function isInteractiveTarget(target)" in source
    assert "target.closest('#record-button') !== null" in source
    assert "target.isContentEditable" in source
    assert source.index("target.closest('#record-button') !== null") < source.index("target.isContentEditable")
    assert "[role=\"dialog\"][aria-modal=\"true\"],dialog[open]" in source
    assert "function forwardGlobalKeydown(event)" in source
    forwarder = re.search(r"function forwardGlobalKeydown\(event\) \{(?P<body>.*?)\n\}", source, re.DOTALL)
    assert forwarder is not None
    body = forwarder.group("body")
    for token in (
        "event.code === 'Space'",
        "event.repeat === true",
        "event.target instanceof Element",
        "event.target.closest('#record-button') !== null",
        "event.preventDefault();",
        "app.handleGlobalKeydown(event)",
    ):
        assert token in body
    for forbidden in ("recordToggle", "speech"):
        assert forbidden not in body


def test_browser_entry_store_factory():
    source = browser_source()
    assert "createStore: () => createSessionStore(sessionStorage" in source
    assert "now: () => new Date().toISOString()" in source


def test_browser_entry_tts_factory():
    source = browser_source()
    for token in (
        "createTTS: api => createTTSController({",
        "loadEdgeBlob: (text, signal) => api.tts(text, signal)",
        "Audio: url => new globalThis.Audio(url)",
        "createObjectURL: URL.createObjectURL.bind(URL)",
        "revokeObjectURL: URL.revokeObjectURL.bind(URL)",
        "speechSynthesis: globalThis.speechSynthesis",
        "SpeechSynthesisUtterance: globalThis.SpeechSynthesisUtterance",
        "AbortController: globalThis.AbortController",
    ):
        assert token in source


def test_browser_entry_speech_factory():
    source = browser_source()
    assert "createSpeech: ({ onEvent }) => createSpeechController({" in source
    assert "Recognition: globalThis.SpeechRecognition ?? globalThis.webkitSpeechRecognition ?? null" in source
    assert "onEvent," in source
    assert source.count("setTimer: globalThis.setTimeout.bind(globalThis)") == 2
    assert source.count("clearTimer: globalThis.clearTimeout.bind(globalThis)") == 2


def test_browser_entry_view_dom_composition():
    source = browser_source()
    assert "const root = document.getElementById('child-app');" in source
    assert "createElement: tag => document.createElement(tag)" in source
    assert "createTextNode: text => document.createTextNode(text)" in source
    assert "queueMicrotask: callback => globalThis.queueMicrotask(callback)" in source
    assert "isFocused: element => document.activeElement === element" in source
    assert "createView: (viewRoot, actions, viewDom) => createChildView(viewRoot, actions, viewDom)" in source


def test_browser_entry_single_bootstrap():
    source = browser_source()
    assert source.count("bootstrapBrowserChildApp(") == 1
    assert "const dependencies = Object.freeze({" in source
    assert "app = await bootstrapBrowserChildApp(dependencies);" in source


def test_browser_entry_listener_requires_nonnull_app():
    source = browser_source()
    assert "if (app === null) return;" in source
    assert source.count("document.addEventListener('keydown', forwardGlobalKeydown)") == 1
    assert source.index("if (app === null) return;") < source.index("document.addEventListener('keydown', forwardGlobalKeydown)")


def test_browser_entry_fixed_maintenance_fallback():
    source = browser_source()
    assert "function renderChildMaintenance(_code)" in source
    assert "document.getElementById('runtime-maintenance')" in source
    assert "幼儿端暂不可用" in source
    assert "当前服务状态无法安全确认，请老师检查服务后刷新页面。" in source
    assert "innerHTML" not in source


def test_browser_entry_pagehide_cleanup_is_idempotent():
    source = browser_source()
    assert "let cleaned = false;" in source
    assert "if (cleaned || app === null) return;" in source
    assert "document.removeEventListener('keydown', forwardGlobalKeydown);" in source
    assert "app.destroy();" in source
    assert source.count("globalThis.addEventListener('pagehide'" ) == 1


def test_browser_entry_has_no_bare_api_globals():
    source = browser_source()
    assert re.search(r"\bbootstrapBrowserChildAPI\b", source)
    assert re.search(r"\bbootstrapBrowserChildAPI\(globalThis\)", source)
    assert not re.search(r"\b(?:DuckAPI|DuckAuth|fetch|acceptText)\b", source)
    assert "innerHTML" not in source


def test_chromium_gate_requires_cft_v1234(chromium_gate_parser, gate_one_validator, tmp_path):
    cft = tmp_path / "chromium-1234"
    shell = tmp_path / "chromium_headless_shell-1234"
    cft.mkdir()
    shell.mkdir()
    parsed = chromium_gate_parser(SYNTHETIC_DRY_RUN.format(cft=cft, shell=shell))
    assert parsed.cft.product == "151.0.7922.34"
    assert parsed.cft.revision == "1234"
    assert parsed.cft.install_dir == cft
    assert parsed.cft.install_dir.is_dir()
    assert parsed.cft.install_dir != Path("/ignore/ffmpeg-1011")
    stderr_only = SimpleNamespace(
        stdout="",
        stderr=SYNTHETIC_DRY_RUN.format(cft=cft, shell=shell),
    )
    combined = gate_one_validator(runner=lambda *_args, **_kwargs: stderr_only)
    assert combined.cft.install_dir == cft
    assert combined.shell.install_dir == shell


def test_chromium_gate_requires_headless_shell_v1234(chromium_gate_parser, tmp_path):
    cft = tmp_path / "chromium-1234"
    shell = tmp_path / "chromium_headless_shell-1234"
    cft.mkdir()
    shell.mkdir()
    parsed = chromium_gate_parser(SYNTHETIC_DRY_RUN.format(cft=cft, shell=shell))
    assert parsed.shell.product == "151.0.7922.34"
    assert parsed.shell.revision == "1234"
    assert parsed.shell.install_dir == shell
    assert parsed.shell.install_dir.is_dir()
    assert parsed.shell.install_dir != Path("/ignore/ffmpeg-1011")


def test_chromium_gate_validates_runtime_version_and_ua(runtime_browser_validator):
    events = []

    class FakePage:
        def evaluate(self, expression):
            assert expression == "navigator.userAgent"
            events.append("ua")
            return "Mozilla/5.0 HeadlessChrome/151.0.7922.34"

        def close(self):
            events.append("page.close")

    class FakeBrowser:
        version = "151.0.7922.34"

        def new_page(self):
            events.append("page.open")
            return FakePage()

        def close(self):
            events.append("browser.close")

    runtime_browser_validator(FakeBrowser())
    assert events == ["page.open", "ua", "page.close", "browser.close"]

    class BrokenClosePage(FakePage):
        def close(self):
            events.append("broken-page.close")
            raise RuntimeError("synthetic page close failure")

    class BrokenCloseBrowser(FakeBrowser):
        def new_page(self):
            events.append("broken-page.open")
            return BrokenClosePage()

        def close(self):
            events.append("broken-browser.close")

    with pytest.raises(RuntimeError, match="synthetic page close failure"):
        runtime_browser_validator(BrokenCloseBrowser())
    assert events[-2:] == ["broken-page.close", "broken-browser.close"]


def test_child_server_import_preflight_blocks_provider_env(monkeypatch, tmp_path):
    module = load_child_server_module()
    assert str(ROOT) == os.sys.path[0]
    events = []
    imported = []
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-test-value")
    with pytest.raises(AssertionError, match="provider environment is forbidden"):
        module.fresh_import_main(
            browser_log_dir=tmp_path / "logs",
            event_sink=events,
            importer=lambda name: imported.append(name),
        )
    assert events == ["dotenv_disabled"]
    assert imported == []


def test_main_import_filehandler_is_redirected_from_real_log(monkeypatch, tmp_path):
    module = load_child_server_module()
    clean_provider_environment(monkeypatch)
    import dotenv

    original_load_dotenv = dotenv.load_dotenv
    monkeypatch.setattr(dotenv, "load_dotenv", original_load_dotenv)
    browser_log_dir = tmp_path / "logs"
    result = module.fresh_import_main(browser_log_dir=browser_log_dir)
    try:
        assert result.events == (
            "dotenv_disabled",
            "provider_environment_absent_pre",
            "real_log_snapshotted",
            "filehandler_redirected",
            "main_imported",
            "filehandler_restored",
            "provider_environment_absent_post",
            "logging_configured",
        )
        assert result.handler_paths
        assert all(path == (browser_log_dir / "app.log").resolve() for path in result.handler_paths)
        assert result.real_log_before == result.real_log_after
        assert dotenv.load_dotenv is not original_load_dotenv
    finally:
        result.restore_logging()


def test_edge_tts_fake_stream_trips_before_network(monkeypatch, tmp_path):
    module = load_child_server_module()
    tripwire = tmp_path / "ai-tripwire.txt"
    monkeypatch.setenv("BROWSER_AI_TRIPWIRE_PATH", str(tripwire))

    async def consume():
        async for _chunk in module.FakeCommunicate("synthetic", "synthetic-voice").stream():
            raise AssertionError("fake stream yielded transport data")

    def consume_in_isolated_thread():
        asyncio.run(consume())

    with ThreadPoolExecutor(max_workers=1) as executor:
        with pytest.raises(AssertionError, match="external edge_tts disabled in browser tests"):
            executor.submit(consume_in_isolated_thread).result()
    assert tripwire.read_text(encoding="utf-8") == "edge_tts blocked\n"


def test_nonstarting_worker_has_no_start_side_effect():
    module = load_child_server_module()
    worker = module._NonStartingAnalysisWorker()
    assert worker.status() == "not_started"
    assert worker.start() is None
    assert worker.stop(timeout_seconds=0.01) is None
    assert worker.status() == "not_started"


def test_browser_subprocess_environment_is_minimal(tmp_path):
    module = load_child_server_module()
    parent = {
        "PATH": "/synthetic/bin",
        "LANG": "C.UTF-8",
        "HTTPS_PROXY": "https://forbidden.invalid",
        "OPENAI_API_KEY": "synthetic-test-value",
        "APP_DB_PATH": "/forbidden/app.db",
        "APP_DB_EXTRA": "forbidden",
        "PLAYWRIGHT_BROWSERS_PATH": "/forbidden/cache",
        "ARBITRARY": "forbidden",
    }
    env = module.build_browser_environment(parent, tmp_path.resolve(), port=43123)
    assert env == {
        "PATH": "/synthetic/bin",
        "LANG": "C.UTF-8",
        "APP_DB_MODE": "app",
        "APP_DB_PATH": str((tmp_path / "browser-app.db").resolve()),
        "APP_LOG_PATH": str((tmp_path / "logs/app.log").resolve()),
        "APP_MEDIA_ROOT": str((tmp_path / "media").resolve()),
        "APP_TTS_CACHE_PATH": str((tmp_path / "tts-cache").resolve()),
        "BROWSER_PORT": "43123",
        "BROWSER_LOG_DIR": str((tmp_path / "logs").resolve()),
        "BROWSER_TTS_CACHE_DIR": str((tmp_path / "tts-cache").resolve()),
        "BROWSER_AI_TRIPWIRE_PATH": str((tmp_path / "ai-tripwire.txt").resolve()),
        "BROWSER_NETWORK_TRIPWIRE_PATH": str((tmp_path / "network-tripwire.txt").resolve()),
        "BROWSER_CONTEXT_EGRESS_TRIPWIRE_PATH": str((tmp_path / "browser-egress-tripwire.txt").resolve()),
        "DISABLE_EXTERNAL_AI": "1",
        "PYTHONNOUSERSITE": "1",
    }


def test_real_resource_snapshots_are_read_only(tmp_path):
    module = load_child_server_module()
    database = tmp_path / "real.db"
    log = tmp_path / "app.log"
    cache = tmp_path / "tts-cache"
    media = tmp_path / "media"
    cache.mkdir()
    media.mkdir()
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        connection.execute("CREATE TABLE sample (value TEXT)")
        connection.execute("INSERT INTO sample VALUES ('synthetic')")
        connection.commit()
        log.write_bytes(b"synthetic-log")
        (cache / "synthetic.mp3").write_bytes(b"synthetic-audio")
        (media / "synthetic.webp").write_bytes(b"synthetic-avatar")
        wal = Path(f"{database}-wal")
        shm = Path(f"{database}-shm")
        assert wal.is_file()
        assert shm.is_file()
        before_bytes = (
            database.read_bytes(),
            wal.read_bytes(),
            shm.read_bytes(),
            log.read_bytes(),
            (cache / "synthetic.mp3").read_bytes(),
            (media / "synthetic.webp").read_bytes(),
        )
        calls = []

        def read_only_connect(database_uri, *, uri):
            calls.append((database_uri, uri))
            return sqlite3.connect(database_uri, uri=uri)

        first = module.capture_resource_snapshots(
            database,
            log,
            cache,
            media,
            connect=read_only_connect,
        )
        second = module.capture_resource_snapshots(
            database,
            log,
            cache,
            media,
            connect=read_only_connect,
        )
        assert module.ResourceSnapshots._fields == (
            "database",
            "database_wal",
            "database_shm",
            "database_logical",
            "log",
            "tts_cache",
            "media",
        )
        assert module.FileSnapshot._fields == (
            "kind",
            "mode",
            "device",
            "inode",
            "link_count",
            "size",
            "mtime_ns",
            "sha256",
            "symlink_target",
            "error",
        )
        assert first == second
        assert first.database == module.file_snapshot(database)
        assert first.database_wal == module.file_snapshot(wal)
        assert first.database_shm == module.file_snapshot(shm)
        assert first.database_logical == module.logical_sqlite_digest(database)
        assert first.log == module.file_snapshot(log)
        assert first.tts_cache == module.directory_snapshot(cache)
        assert first.media == module.directory_snapshot(media)
        assert calls and all(
            uri is True and "mode=ro" in database_uri
            for database_uri, uri in calls
        )
        assert before_bytes == (
            database.read_bytes(),
            wal.read_bytes(),
            shm.read_bytes(),
            log.read_bytes(),
            (cache / "synthetic.mp3").read_bytes(),
            (media / "synthetic.webp").read_bytes(),
        )


def test_real_resource_snapshots_keep_stable_missing_resources_typed(tmp_path):
    module = load_child_server_module()
    paths = tuple(tmp_path / name for name in ("app.db", "app.log", "tts", "media"))

    first = module.capture_resource_snapshots(*paths)
    second = module.capture_resource_snapshots(*paths)

    assert first == second
    assert first.database.kind is module.FileKind.MISSING
    assert first.database_wal.kind is module.FileKind.MISSING
    assert first.database_shm.kind is module.FileKind.MISSING
    assert first.database_logical is None
    assert first.log.kind is module.FileKind.MISSING
    assert first.tts_cache.root.kind is module.FileKind.MISSING
    assert first.media.root.kind is module.FileKind.MISSING


def _browser_resource_paths(module, tmp_path):
    database = tmp_path / "app.db"
    log = tmp_path / "app.log"
    tts = tmp_path / "tts"
    media = tmp_path / "media"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE sample (value TEXT)")
        connection.execute("INSERT INTO sample VALUES ('synthetic')")
    log.write_bytes(b"synthetic-log")
    media.mkdir()
    return database, log, tts, media


def test_browser_resource_guard_allows_stable_missing_optional_paths_and_keeps_them_equality_sensitive(
    tmp_path,
):
    module = load_child_server_module()
    database, log, tts, media = _browser_resource_paths(module, tmp_path)

    baseline = module.capture_resource_snapshots(database, log, tts, media)
    stable = module.capture_resource_snapshots(database, log, tts, media)

    assert baseline == stable
    assert baseline.database_wal.kind is module.FileKind.MISSING
    assert baseline.database_shm.kind is module.FileKind.MISSING
    assert baseline.tts_cache.root.kind is module.FileKind.MISSING
    module.assert_safe_resource_snapshots(baseline, phase="baseline")
    module.assert_safe_resource_snapshots(stable, phase="final")

    tts.mkdir()
    changed = module.capture_resource_snapshots(database, log, tts, media)
    module.assert_safe_resource_snapshots(changed, phase="final")
    assert changed != baseline


@pytest.mark.parametrize(
    ("missing_name", "expected_issue"),
    [
        ("database", "database has forbidden kind missing"),
        ("log", "log has forbidden kind missing"),
    ],
)
def test_browser_resource_guard_rejects_missing_required_primary_files(
    tmp_path,
    missing_name,
    expected_issue,
):
    module = load_child_server_module()
    database, log, tts, media = _browser_resource_paths(module, tmp_path)
    {"database": database, "log": log}[missing_name].unlink()

    snapshots = module.capture_resource_snapshots(database, log, tts, media)

    with pytest.raises(
        AssertionError,
        match=re.escape(
            f"browser baseline resource snapshot unsafe: {expected_issue}"
        ),
    ):
        module.assert_safe_resource_snapshots(snapshots, phase="baseline")


@pytest.mark.parametrize("phase", ["baseline", "final"])
@pytest.mark.parametrize(
    ("case", "expected_issue"),
    [
        ("root-symlink", "tts_cache root has forbidden kind symlink"),
        (
            "nested-symlink",
            "tts_cache entry nested-link has forbidden kind symlink",
        ),
        ("root-special", "tts_cache root has forbidden kind special"),
        ("nested-special", "tts_cache entry nested-fifo has forbidden kind special"),
        ("root-unreadable", "log has forbidden kind unreadable (PermissionError)"),
        (
            "nested-unreadable",
            "tts_cache entry blocked.bin has forbidden kind unreadable (PermissionError)",
        ),
        ("root-hardlink", "log has link_count 2, expected 1"),
        (
            "nested-hardlink",
            "tts_cache entry linked.bin has link_count 2, expected 1",
        ),
        ("scan-error", "tts_cache scan failed at . (PermissionError)"),
    ],
)
def test_browser_resource_guard_rejects_exact_unsafe_fixture_states(
    monkeypatch,
    tmp_path,
    phase,
    case,
    expected_issue,
):
    module = load_child_server_module()
    database, log, tts, media = _browser_resource_paths(module, tmp_path)
    target = tmp_path / "link-target"
    original_open = module.os.open
    original_scandir = module.os.scandir

    if case == "root-symlink":
        target.mkdir()
        tts.symlink_to(target, target_is_directory=True)
    elif case == "root-special":
        os.mkfifo(tts)
    else:
        tts.mkdir()
        if case == "nested-symlink":
            (tts / "nested-link").symlink_to("missing-target")
        elif case == "nested-special":
            os.mkfifo(tts / "nested-fifo")
        elif case == "root-unreadable":
            def deny_log(candidate, *args, **kwargs):
                if Path(candidate) == log:
                    raise PermissionError("synthetic root denial")
                return original_open(candidate, *args, **kwargs)

            monkeypatch.setattr(module.os, "open", deny_log)
        elif case == "nested-unreadable":
            (tts / "blocked.bin").write_bytes(b"blocked")

            def deny_nested(candidate, *args, **kwargs):
                if candidate == "blocked.bin" and kwargs.get("dir_fd") is not None:
                    raise PermissionError("synthetic nested denial")
                return original_open(candidate, *args, **kwargs)

            monkeypatch.setattr(module.os, "open", deny_nested)
        elif case == "root-hardlink":
            os.link(log, tmp_path / "outside-log-hardlink")
        elif case == "nested-hardlink":
            nested = tts / "linked.bin"
            nested.write_bytes(b"same-content")
            os.link(nested, tmp_path / "outside-nested-hardlink")
        elif case == "scan-error":
            tts_identity = (tts.stat().st_dev, tts.stat().st_ino)

            def deny_scan(candidate):
                if isinstance(candidate, int):
                    details = os.fstat(candidate)
                    if (details.st_dev, details.st_ino) == tts_identity:
                        raise PermissionError("synthetic scan denial")
                return original_scandir(candidate)

            monkeypatch.setattr(module.os, "scandir", deny_scan)

    snapshots = module.capture_resource_snapshots(database, log, tts, media)
    stable = module.capture_resource_snapshots(database, log, tts, media)

    assert stable == snapshots
    with pytest.raises(
        AssertionError,
        match=re.escape(
            f"browser {phase} resource snapshot unsafe: {expected_issue}"
        ),
    ):
        module.assert_safe_resource_snapshots(snapshots, phase=phase)


def test_real_resource_snapshots_detect_same_content_external_hardlink_mutation(tmp_path):
    module = load_child_server_module()
    database, log, tts, media = _browser_resource_paths(module, tmp_path)
    tts.mkdir()
    external_link = tmp_path / "outside-log-hardlink"

    before = module.capture_resource_snapshots(database, log, tts, media)
    os.link(log, external_link)
    after = module.capture_resource_snapshots(database, log, tts, media)

    assert before.log.sha256 == after.log.sha256
    assert before.log.inode == after.log.inode
    assert before.log.link_count == 1
    assert after.log.link_count == 2
    assert before != after
    with pytest.raises(
        AssertionError,
        match=re.escape(
            "browser final resource snapshot unsafe: log has link_count 2, expected 1"
        ),
    ):
        module.assert_safe_resource_snapshots(after, phase="final")


@pytest.mark.parametrize(
    ("unsafe_case", "expected_issue"),
    [
        ("missing-database", "database has forbidden kind missing"),
        ("missing-log", "log has forbidden kind missing"),
        ("root-symlink", "tts_cache root has forbidden kind symlink"),
    ],
)
def test_child_server_fixture_rejects_unsafe_baseline_before_process_launch(
    monkeypatch,
    tmp_path,
    unsafe_case,
    expected_issue,
):
    child_module = load_child_server_module()
    fixture_module = load_browser_conftest_module()
    protected = tmp_path / "protected"
    protected.mkdir()
    database = protected / "app.db"
    log = protected / "logs/app.log"
    tts = protected / "tts"
    media = protected / "media"
    log.parent.mkdir()
    if unsafe_case != "missing-database":
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE sample (value TEXT)")
    if unsafe_case != "missing-log":
        log.write_bytes(b"synthetic-log")
    if unsafe_case == "root-symlink":
        target = protected / "tts-target"
        target.mkdir()
        tts.symlink_to(target, target_is_directory=True)

    monkeypatch.setattr(child_module, "REAL_DATABASE_PATH", database)
    monkeypatch.setattr(child_module, "REAL_LOG_PATH", log)
    monkeypatch.setattr(child_module, "REAL_TTS_CACHE_PATH", tts)
    monkeypatch.setattr(child_module, "REAL_MEDIA_ROOT", media)
    monkeypatch.setattr(
        fixture_module,
        "_load_child_server_module",
        lambda: child_module,
    )
    launch_calls = []

    def launch_spy(*args, **kwargs):
        launch_calls.append((args, kwargs))
        raise AssertionError("process launch attempted")

    monkeypatch.setattr(fixture_module.subprocess, "Popen", launch_spy)
    fixture = fixture_module.child_server.__wrapped__(
        chromium_browser=object(),
        tmp_path=tmp_path,
        unused_tcp_port=43123,
    )

    with pytest.raises(
        AssertionError,
        match=re.escape(
            f"browser baseline resource snapshot unsafe: {expected_issue}"
        ),
    ):
        next(fixture)
    assert launch_calls == []


def test_real_resource_snapshots_detect_missing_to_dangling_symlink(tmp_path):
    module = load_child_server_module()
    database = tmp_path / "app.db"
    log = tmp_path / "app.log"
    tts = tmp_path / "tts"
    media = tmp_path / "media"

    before = module.capture_resource_snapshots(database, log, tts, media)
    log.symlink_to("missing-target.log")
    after = module.capture_resource_snapshots(database, log, tts, media)

    assert before != after
    assert before.log.kind is module.FileKind.MISSING
    assert after.log.kind is module.FileKind.SYMLINK
    assert after.log.symlink_target == "missing-target.log"
    assert after.log.sha256 is None


def test_real_resource_snapshots_detect_nested_empty_directory_addition(tmp_path):
    module = load_child_server_module()
    database = tmp_path / "app.db"
    log = tmp_path / "app.log"
    tts = tmp_path / "tts"
    media = tmp_path / "media"
    tts.mkdir()
    media.mkdir()

    before = module.capture_resource_snapshots(database, log, tts, media)
    (tts / "nested" / "empty").mkdir(parents=True)
    after = module.capture_resource_snapshots(database, log, tts, media)

    assert before != after
    assert tuple(entry.relative_path for entry in before.tts_cache.entries) == ()
    assert tuple(entry.relative_path for entry in after.tts_cache.entries) == (
        "nested",
        "nested/empty",
    )
    assert all(
        entry.snapshot.kind is module.FileKind.DIRECTORY
        for entry in after.tts_cache.entries
    )


def test_real_resource_snapshots_detect_mode_change(tmp_path):
    module = load_child_server_module()
    database = tmp_path / "app.db"
    log = tmp_path / "app.log"
    tts = tmp_path / "tts"
    media = tmp_path / "media"
    tts.mkdir()
    media.mkdir()
    log.write_bytes(b"stable")
    log.chmod(0o600)

    before = module.capture_resource_snapshots(database, log, tts, media)
    log.chmod(0o640)
    after = module.capture_resource_snapshots(database, log, tts, media)

    assert before != after
    assert before.log.mode == 0o600
    assert after.log.mode == 0o640
    assert before.log.sha256 == after.log.sha256


def test_real_resource_snapshots_detect_same_content_inode_replacement(tmp_path):
    module = load_child_server_module()
    database = tmp_path / "app.db"
    log = tmp_path / "app.log"
    replacement = tmp_path / "replacement.log"
    tts = tmp_path / "tts"
    media = tmp_path / "media"
    tts.mkdir()
    media.mkdir()
    log.write_bytes(b"same-content")

    before = module.capture_resource_snapshots(database, log, tts, media)
    replacement.write_bytes(b"same-content")
    replacement.replace(log)
    after = module.capture_resource_snapshots(database, log, tts, media)

    assert before != after
    assert before.log.sha256 == after.log.sha256
    assert before.log.inode != after.log.inode


def test_real_resource_snapshots_fail_closed_without_no_follow_support(
    monkeypatch,
    tmp_path,
):
    module = load_child_server_module()
    regular = tmp_path / "regular.log"
    directory = tmp_path / "tts"
    regular.write_bytes(b"must-not-be-read-without-no-follow")
    directory.mkdir()
    monkeypatch.delattr(module.os, "O_NOFOLLOW")

    file_state = module.file_snapshot(regular)
    directory_state = module.directory_snapshot(directory)

    assert file_state.kind is module.FileKind.UNREADABLE
    assert file_state.sha256 is None
    assert file_state.error == "O_NOFOLLOW_UNAVAILABLE"
    assert directory_state.root.kind is module.FileKind.DIRECTORY
    assert directory_state.entries == ()
    assert directory_state.scan_error == "O_NOFOLLOW_UNAVAILABLE"
    assert directory_state.scan_source == "."


def test_socket_guard_blocks_non_loopback(tmp_path):
    module = load_child_server_module()
    tripwire = tmp_path / "network-tripwire.txt"
    allowed = []

    def original_connect(sock, address):
        allowed.append((sock, address))
        return "connected"

    guarded = module.make_loopback_connect_guard(tripwire, original_connect)
    token = object()
    assert guarded(token, ("127.0.0.1", 8000)) == "connected"
    assert guarded(token, ("::1", 8000, 0, 0)) == "connected"
    with pytest.raises(PermissionError, match="non-loopback socket blocked"):
        guarded(token, ("example.invalid", 443))
    assert allowed == [(token, ("127.0.0.1", 8000)), (token, ("::1", 8000, 0, 0))]
    assert tripwire.read_text(encoding="utf-8") == "example.invalid:443\n"


def test_fixture_teardown_closes_before_process_assertions():
    module = load_child_server_module()
    events = []

    class Resource:
        def __init__(self, name):
            self.name = name

        def close(self):
            events.append(f"close:{self.name}")

    class Process:
        returncode = None

        def poll(self):
            return self.returncode

        def terminate(self):
            events.append("terminate")

        def wait(self, timeout):
            events.append(f"wait:{timeout:g}")
            if events.count("wait:5") == 1:
                raise subprocess.TimeoutExpired("synthetic", timeout)
            self.returncode = -9
            return self.returncode

        def kill(self):
            events.append("kill")

    module.close_and_verify(
        [Resource("page"), Resource("context"), Resource("browser")],
        Process(),
        verify=lambda: events.append("verify"),
    )
    assert events == [
        "close:page",
        "close:context",
        "close:browser",
        "terminate",
        "wait:5",
        "kill",
        "wait:5",
        "verify",
    ]


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://127.0.0.1:43123/", True),
        ("http://127.0.0.1:43123/api/health?x=1", True),
        ("https://127.0.0.1:43123/", False),
        ("http://localhost:43123/", False),
        ("http://[::1]:43123/", False),
        ("http://user:pass@127.0.0.1:43123/", False),
        ("http://127.0.0.1:43124/", False),
        ("http://127.0.0.1/", False),
        ("http://127.0.0.1:not-a-port/", False),
        ("http://example.invalid:43123/", False),
        ("data:text/plain,synthetic", False),
    ],
)
def test_context_loopback_policy_allows_only_exact_origin(
    exact_fixture_url,
    context_route_policy,
    tmp_path,
    url,
    expected,
):
    assert exact_fixture_url(url, 43123) is expected
    events = []
    tripwire = tmp_path / "browser-egress-tripwire.txt"

    class Request:
        def __init__(self, request_url):
            self.url = request_url

    class Route:
        def __init__(self, request_url):
            self.request = Request(request_url)

        def continue_(self):
            events.append("continue")

        def abort(self, reason):
            events.append(f"abort:{reason}")

    context_route_policy(port=43123, egress_tripwire=tripwire)(Route(url))
    if expected:
        assert events == ["continue"]
        assert not tripwire.exists()
    else:
        assert events == ["abort:blockedbyclient"]
        assert tripwire.read_text(encoding="utf-8") == f"{url}\n"


def test_loopback_server_uses_disposable_resources(child_server):
    assert child_server.base_url == f"http://127.0.0.1:{child_server.port}"
    assert Path(child_server.environment["APP_DB_PATH"]).parent == child_server.runtime_dir
    assert Path(child_server.environment["BROWSER_LOG_DIR"]).is_relative_to(child_server.runtime_dir)
    assert Path(child_server.environment["BROWSER_TTS_CACHE_DIR"]).is_relative_to(child_server.runtime_dir)
    assert Path(child_server.environment["APP_LOG_PATH"]).is_relative_to(child_server.runtime_dir)
    assert Path(child_server.environment["APP_MEDIA_ROOT"]).is_relative_to(child_server.runtime_dir)
    assert Path(child_server.environment["APP_TTS_CACHE_PATH"]).is_relative_to(child_server.runtime_dir)
    assert child_server.process.poll() is None


def test_child_page_registers_fail_closed_business_routes_before_navigation(
    business_route_installer,
):
    routes = []

    class Page:
        def route(self, pattern, handler):
            routes.append((pattern, handler))

    page = Page()
    business_route_installer(page, port=43123)
    assert [pattern for pattern, _handler in routes] == [
        "**/api/roster/today",
        "**/api/children/*/active-conversation",
        "**/api/chat",
        "**/api/conversations/*/complete",
        "**/api/tts*",
        "**/api/runtime/context",
        "**/api/media/avatars*",
        "**/api/roster/month",
        "**/api/reports/weekly*",
        "**/api/conversations/search*",
    ]
    for pattern, handler in routes:
        outcomes = []

        class Request:
            url = "http://127.0.0.1:43123/api/chat"

        class Route:
            request = Request()

            def fulfill(self, **kwargs):
                outcomes.append(kwargs)

        handler(Route())
        assert outcomes == [{
            "status": 503,
            "content_type": "application/json",
            "body": '{"error":{"code":"UNEXPECTED_BROWSER_REQUEST","message":"fixture route required"}}',
        }], pattern
    fixture_source = (ROOT / "tests/browser/conftest.py").read_text(encoding="utf-8")
    context_install = "install_fail_closed_business_routes(context, port=child_server.port)"
    assert context_install in fixture_source
    assert fixture_source.index(context_install) < fixture_source.index("page = context.new_page()")
    assert "install_fail_closed_business_routes(page, port=child_server.port)" not in fixture_source


def test_page_specific_routes_cannot_widen_loopback_policy(child_page):
    child_page.fulfill_json("**/api/synthetic-fixture", {"ok": True})
    child_page.page.goto(f"{child_page.server.base_url}/", wait_until="domcontentloaded")
    payload = child_page.page.evaluate(
        "async () => (await fetch('/api/synthetic-fixture')).json()"
    )
    assert payload == {"ok": True}
    assert not Path(
        child_page.server.environment["BROWSER_CONTEXT_EGRESS_TRIPWIRE_PATH"]
    ).exists()


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_keyboard_modality_blocks_native_editable_and_modal_space(child_page, viewport):
    prepare_child_page(
        child_page,
        viewport,
        roster=[SYNTHETIC_CHILD],
        active_by_child={1: SYNTHETIC_ACTIVE},
    )
    page = child_page.page
    record = wait_for_active_ready(page)

    record.press("Space")
    page.wait_for_function("window.__childTest.recognition.starts === 1")
    assert page.evaluate("window.__childTest.recognition.starts") == 1

    page.evaluate(
        """
        () => {
          const host = document.querySelector('.child-view');
          const disabled = document.createElement('button');
          disabled.id = 'synthetic-disabled';
          disabled.disabled = true;
          const link = document.createElement('a');
          link.id = 'synthetic-link';
          link.href = '#synthetic';
          const editable = document.createElement('div');
          editable.id = 'synthetic-editable';
          editable.contentEditable = 'true';
          host.append(disabled, link, editable);
        }
        """
    )
    for selector in ("#synthetic-disabled", "#synthetic-link", "#synthetic-editable"):
        page.dispatch_event(selector, "keydown", {"code": "Space", "key": " "})
    assert page.evaluate("window.__childTest.recognition.starts") == 1

    page.evaluate(
        """
        () => {
          const dialog = document.createElement('div');
          dialog.id = 'synthetic-dialog';
          dialog.setAttribute('role', 'dialog');
          dialog.setAttribute('aria-modal', 'true');
          document.body.append(dialog);
          document.querySelector('#app-title').focus();
        }
        """
    )
    page.keyboard.press("Space")
    assert page.evaluate("window.__childTest.recognition.starts") == 1


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_empty_roster_is_honest_and_has_no_cards(child_page, viewport):
    requested = prepare_child_page(child_page, viewport, roster=[])
    page = child_page.page
    page.get_by_text("今天还未排班，请老师帮忙", exact=True).first.wait_for()
    help_button = page.get_by_role("button", name="请老师帮忙", exact=True)
    assert help_button.is_visible()
    assert help_button.is_enabled()
    help_button.focus()
    assert page.evaluate("document.activeElement?.id") == "teacher-help-button"
    assert page.locator(".child-card").count() == 0
    assert page.get_by_role("main").count() == 1
    assert page.get_by_role("heading", level=1).count() == 1
    assert page.get_by_role("heading", level=1).inner_text().strip()
    business_urls = "\n".join(requested)
    assert "/active-conversation" not in business_urls
    assert "/api/chat" not in business_urls
    assert "/api/tts" not in business_urls


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
@pytest.mark.parametrize("roster_mode", ["empty", "avatar_cards"])
def test_roster_panel_and_pet_orb_are_safe_visible_and_non_overlapping(
    child_page,
    viewport,
    roster_mode,
):
    canonical_avatar = "/api/media/avatars/a30a6409-58b8-48f0-96f0-8ff679bebed7"
    roster = [] if roster_mode == "empty" else [
        {"id": 1, "name": "测试幼儿", "nickname": "   ", "avatar": "javascript:alert(1)"},
        {
            "id": 2,
            "name": "小林",
            "nickname": "\ufe0f\u034f",
            "avatar": canonical_avatar,
        },
    ]
    if roster_mode != "empty":
        encoded = BytesIO()
        with Image.open(ROOT / "app/frontend/assets/duck-front-128.png") as source:
            source.convert("RGB").save(encoded, format="WEBP")
        child_page.fulfill_bytes(
            f"**{canonical_avatar}",
            encoded.getvalue(),
            content_type="image/webp",
        )
    prepare_child_page(child_page, viewport, roster=roster)
    page = child_page.page
    panel = page.locator(".child-roster-panel")
    orb = page.locator(".child-pet-orb")
    panel.wait_for()
    orb.wait_for()

    if roster_mode == "empty":
        assert panel.locator("#roster-empty").inner_text() == "今天还未排班，请老师帮忙"
        assert panel.locator(".child-card").count() == 0
    else:
        cards = panel.locator(".child-card")
        assert cards.count() == 2
        for index, expected_label in enumerate(("测试幼儿", "小林")):
            card = cards.nth(index)
            assert card.locator(".child-card__label").inner_text() == expected_label
            assert card.get_attribute("aria-label") is None
            assert page.get_by_role("button", name=expected_label, exact=True).count() == 1
        assert cards.nth(0).locator("img").count() == 0
        image = cards.nth(1).locator(".child-card__avatar img")
        image.wait_for()
        assert image.get_attribute("src") == canonical_avatar
        assert image.get_attribute("alt") == ""
        fallback = cards.nth(1).locator(".child-card__avatar .avatar-fallback")
        assert fallback.evaluate("element => element.hidden") is True
        assert fallback.is_visible() is False
        image.dispatch_event("error")
        assert cards.nth(1).locator("img").count() == 0
        assert fallback.is_visible() is True
        assert cards.locator(".child-card__avatar").all_inner_texts() == ["测", "小"]
        body = page.locator("body").inner_text()
        assert "javascript:alert(1)" not in body

    measured = page.evaluate(
        """
        () => {
          const rectFor = selector => {
            const rect = document.querySelector(selector).getBoundingClientRect();
            return { x: rect.x, y: rect.y, width: rect.width, height: rect.height };
          };
          const scrolling = document.scrollingElement;
          return {
            panel: rectFor('.child-roster-panel'),
            orb: rectFor('.child-pet-orb'),
            cards: [...document.querySelectorAll('.child-card')].map(element => {
              const rect = element.getBoundingClientRect();
              return { x: rect.x, y: rect.y, width: rect.width, height: rect.height };
            }),
            scrollX: window.scrollX,
            scrollY: window.scrollY,
            documentWidth: scrolling.scrollWidth,
            viewportWidth: window.innerWidth,
          };
        }
        """
    )
    assert measured["scrollX"] == 0
    assert measured["scrollY"] == 0
    assert measured["documentWidth"] <= measured["viewportWidth"]
    panel_rect = measured["panel"]
    orb_rect = measured["orb"]
    assert panel_rect["x"] + panel_rect["width"] <= orb_rect["x"]
    assert orb_rect["x"] - (panel_rect["x"] + panel_rect["width"]) == pytest.approx(24, abs=1)
    assert panel_rect["y"] == pytest.approx(orb_rect["y"], abs=1)
    assert panel_rect["height"] == pytest.approx(orb_rect["height"], abs=1)
    if roster_mode == "avatar_cards":
        first, second = measured["cards"]
        assert first["x"] + first["width"] <= second["x"]
        assert first["y"] == pytest.approx(second["y"], abs=1)


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_active_conversation_shell_is_semantic(child_page, viewport):
    prepare_child_page(
        child_page,
        viewport,
        roster=[SYNTHETIC_CHILD],
        active_by_child={1: SYNTHETIC_ACTIVE},
    )
    page = child_page.page
    wait_for_active_ready(page)
    assert page.get_by_role("main").count() == 1
    assert page.get_by_role("heading", name="鸭鸭日记本", level=1).count() == 1
    log = page.get_by_role("log", name="对话记录")
    assert log.is_visible()
    assert log.get_by_text("小芽", exact=True).count() == 1
    assert log.get_by_text("鸭鸭日记本", exact=True).count() == 1
    assert page.get_by_role("status").is_visible()
    assert page.get_by_role("button", name="开始说话", exact=True).is_visible()


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_listening_projects_a_loaded_local_poster(child_page, viewport):
    prepare_child_page(
        child_page,
        viewport,
        roster=[SYNTHETIC_CHILD],
        active_by_child={1: SYNTHETIC_ACTIVE},
    )
    page = child_page.page
    page.get_by_role("button", name="开始说话", exact=True).click()
    page.wait_for_function("document.querySelector('.child-view')?.dataset.state === 'listening'")
    poster = page.locator('.child-pet-orb__poster')
    assert poster.count() == 1
    assert poster.get_attribute("src") == "/assets/duck-listening.png"
    page.wait_for_function(
        """
        () => {
          const poster = document.querySelector('.child-pet-orb__poster');
          return poster?.complete === true && poster.naturalWidth > 0;
        }
        """
    )
    loaded = poster.evaluate(
        "poster => ({ complete: poster.complete, naturalWidth: poster.naturalWidth })"
    )
    assert loaded["complete"] is True
    assert loaded["naturalWidth"] > 0


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_space_is_single_action_for_native_and_global_paths(child_page, viewport):
    prepare_child_page(
        child_page,
        viewport,
        roster=[SYNTHETIC_CHILD],
        active_by_child={1: SYNTHETIC_ACTIVE},
    )
    page = child_page.page
    record = wait_for_active_ready(page)
    record.press("Space")
    page.wait_for_function("window.__childTest.recognition.starts === 1")
    assert page.evaluate("window.__childTest.recognition.starts") == 1
    page.locator("#record-button").press("Space")
    page.wait_for_function("window.__childTest.recognition.stops === 1")
    page.evaluate("window.__childTest.recognition.emitEnd()")
    page.get_by_role("button", name="开始说话", exact=True).wait_for()

    page.locator("#app-title").focus()
    page.keyboard.press("Space")
    page.wait_for_function("window.__childTest.recognition.starts === 2")
    page.keyboard.press("Space")
    page.wait_for_function("window.__childTest.recognition.stops === 2")
    page.evaluate("window.__childTest.recognition.emitEnd()")
    page.get_by_role("button", name="开始说话", exact=True).wait_for()
    assert page.evaluate(
        "({ starts: window.__childTest.recognition.starts, stops: window.__childTest.recognition.stops })"
    ) == {"starts": 2, "stops": 2}


def test_held_global_space_does_not_stop_after_listening_focus_transition(child_page):
    prepare_child_page(
        child_page,
        VIEWPORTS[0],
        roster=[SYNTHETIC_CHILD],
        active_by_child={1: SYNTHETIC_ACTIVE},
    )
    page = child_page.page
    record = wait_for_active_ready(page)
    record.focus()
    assert page.evaluate("document.activeElement?.id") == "record-button"
    page.evaluate(
        """
        () => {
          window.__recordSpaceKeydowns = [];
          document.addEventListener('keydown', event => {
            if (event.code !== 'Space') return;
            window.__recordSpaceKeydowns.push({
              defaultPrevented: event.defaultPrevented,
              repeat: event.repeat,
              targetId: event.target?.id ?? null,
            });
          });
        }
        """
    )

    page.keyboard.down("Space")
    page.wait_for_function("window.__childTest.recognition.starts === 1")
    page.keyboard.down("Space")
    page.keyboard.up("Space")

    assert page.evaluate(
        "({ starts: window.__childTest.recognition.starts, stops: window.__childTest.recognition.stops })"
    ) == {"starts": 1, "stops": 0}
    assert page.evaluate("window.__recordSpaceKeydowns") == [
        {"defaultPrevented": True, "repeat": False, "targetId": "record-button"},
        {"defaultPrevented": False, "repeat": True, "targetId": "child-status"},
    ]
    assert page.locator(".child-view").get_attribute("data-state") == "listening"

    page.evaluate("window.__recordSpaceKeydowns = []")
    page.keyboard.down("Space")
    page.wait_for_function("window.__childTest.recognition.stops === 1")
    page.evaluate("window.__childTest.recognition.emitEnd()")
    page.get_by_role("button", name="开始说话", exact=True).wait_for()
    page.wait_for_function("document.activeElement?.id === 'record-button'")
    page.keyboard.down("Space")
    page.keyboard.up("Space")

    assert page.evaluate(
        "({ starts: window.__childTest.recognition.starts, stops: window.__childTest.recognition.stops })"
    ) == {"starts": 1, "stops": 1}
    assert page.evaluate("window.__recordSpaceKeydowns") == [
        {"defaultPrevented": True, "repeat": False, "targetId": "child-status"},
        {"defaultPrevented": True, "repeat": True, "targetId": "record-button"},
    ]
    assert page.locator(".child-view").get_attribute("data-state") == "ready"


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_keyboard_focus_visible_uses_start_to_ready_flow(child_page, viewport):
    page = child_page.page
    page.set_viewport_size(viewport)
    child_page.fulfill_json("**/api/roster/today", [SYNTHETIC_CHILD])
    child_page.fulfill_json("**/api/children/1/active-conversation", SYNTHETIC_ACTIVE)
    child_page.fulfill_bytes("**/api/tts?*", b"synthetic-audio", content_type="audio/mpeg")
    page.goto(f"{child_page.server.base_url}/", wait_until="domcontentloaded")
    page.wait_for_function("document.activeElement?.id === 'start-button'")
    page.keyboard.press("Space")
    wait_for_active_ready(page)
    page.wait_for_function("document.activeElement?.id === 'record-button'")
    style = page.locator("#record-button").evaluate(
        """
        element => {
          const value = getComputedStyle(element);
          return {
            focusVisible: element.matches(':focus-visible'),
            color: value.outlineColor,
            style: value.outlineStyle,
            width: parseFloat(value.outlineWidth),
          };
        }
        """
    )
    assert style["focusVisible"] is True
    assert style["style"] != "none"
    assert style["width"] > 0
    assert style["color"] not in {"rgba(0, 0, 0, 0)", "transparent"}


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_ready_stage_matches_exact_panel_and_pet_orb_geometry_without_scroll(child_page, viewport):
    prepare_child_page(
        child_page,
        viewport,
        roster=[SYNTHETIC_CHILD],
        active_by_child={1: SYNTHETIC_ACTIVE},
    )
    page = child_page.page
    wait_for_active_ready(page)
    measured = page.evaluate(
        """
        () => {
          const rectFor = selector => {
            const element = document.querySelector(selector);
            if (element === null) return null;
            const rect = element.getBoundingClientRect();
            return { x: rect.x, y: rect.y, width: rect.width, height: rect.height };
          };
          const scrolling = document.scrollingElement;
          return {
            rects: {
              header: rectFor('.child-shell__header'),
              content: rectFor('.child-shell__content'),
              state: rectFor('.child-state'),
              panel: rectFor('.child-conversation-panel'),
              orb: rectFor('.child-pet-orb'),
            },
            scrollX: window.scrollX,
            scrollY: window.scrollY,
            documentWidth: scrolling.scrollWidth,
            documentHeight: scrolling.scrollHeight,
            viewportWidth: window.innerWidth,
            viewportHeight: window.innerHeight,
          };
        }
        """
    )
    expected = READY_GEOMETRY[(viewport["width"], viewport["height"])]
    assert measured["scrollX"] == 0
    assert measured["scrollY"] == 0
    assert measured["documentWidth"] <= measured["viewportWidth"]
    assert measured["documentHeight"] <= measured["viewportHeight"]
    for name, expected_rect in expected.items():
        actual = measured["rects"][name]
        assert actual is not None, name
        for field, expected_value in expected_rect.items():
            assert actual[field] == pytest.approx(expected_value, abs=1), (name, field, actual)
        assert actual["x"] >= 0
        assert actual["y"] >= 0
        assert actual["x"] + actual["width"] <= viewport["width"] + 1
        assert actual["y"] + actual["height"] <= viewport["height"] + 1

    panel = measured["rects"]["panel"]
    orb = measured["rects"]["orb"]
    assert panel["x"] + panel["width"] <= orb["x"]
    assert orb["x"] - (panel["x"] + panel["width"]) == pytest.approx(24, abs=1)
    assert panel["y"] == pytest.approx(orb["y"], abs=1)
    assert panel["height"] == pytest.approx(orb["height"], abs=1)


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_near_limit_transcript_scrolls_inside_its_fixed_row_without_overlap(
    child_page,
    viewport,
):
    active = {
        "conversation": {
            **SYNTHETIC_ACTIVE["conversation"],
            "messages": [
                {"id": 101, "role": "child", "text": NEAR_LIMIT_CHILD_TEXT},
                {"id": 102, "role": "diary", "text": "相邻的短消息仍然清楚可见。"},
            ],
        }
    }
    prepare_child_page(
        child_page,
        viewport,
        roster=[SYNTHETIC_CHILD],
        active_by_child={1: active},
    )
    page = child_page.page
    record = wait_for_active_ready(page)
    log = page.get_by_role("log", name="对话记录")
    rows = log.locator(".child-message")
    long_body = rows.nth(0).locator(".child-message__text")
    short_body = rows.nth(1).locator(".child-message__text")

    assert log.count() == 1
    assert rows.count() == 2
    assert long_body.text_content() == NEAR_LIMIT_CHILD_TEXT
    assert short_body.text_content() == "相邻的短消息仍然清楚可见。"

    measured = page.evaluate(
        """
        () => {
          const box = element => {
            const rect = element.getBoundingClientRect();
            return {
              x: rect.x,
              y: rect.y,
              width: rect.width,
              height: rect.height,
              top: rect.top,
              right: rect.right,
              bottom: rect.bottom,
              left: rect.left,
            };
          };
          const rectFor = selector => box(document.querySelector(selector));
          const rows = document.querySelectorAll(
            '.child-conversation-panel__messages .child-message'
          );
          const longRow = rows[0];
          const adjacentRow = rows[1];
          const longBody = longRow.querySelector('.child-message__text');
          const shortBody = adjacentRow.querySelector('.child-message__text');
          const speaker = longRow.querySelector('.child-message__speaker');
          const textNode = longBody.firstChild;
          longBody.scrollTop = longBody.scrollHeight;
          const lastCharacter = document.createRange();
          lastCharacter.setStart(textNode, textNode.length - 1);
          lastCharacter.setEnd(textNode, textNode.length);
          const scrolling = document.scrollingElement;
          return {
            row: box(longRow),
            adjacentRow: box(adjacentRow),
            body: box(longBody),
            speaker: box(speaker),
            lastCharacter: box(lastCharacter),
            bodyClientHeight: longBody.clientHeight,
            bodyScrollHeight: longBody.scrollHeight,
            bodyScrollTop: longBody.scrollTop,
            bodyOverflowY: getComputedStyle(longBody).overflowY,
            bodyText: longBody.textContent,
            shortClientHeight: shortBody.clientHeight,
            shortScrollHeight: shortBody.scrollHeight,
            outer: {
              header: rectFor('.child-shell__header'),
              content: rectFor('.child-shell__content'),
              state: rectFor('.child-state'),
              panel: rectFor('.child-conversation-panel'),
              orb: rectFor('.child-pet-orb'),
            },
            scrollX: window.scrollX,
            scrollY: window.scrollY,
            documentWidth: scrolling.scrollWidth,
            documentHeight: scrolling.scrollHeight,
            viewportWidth: window.innerWidth,
            viewportHeight: window.innerHeight,
          };
        }
        """
    )
    assert measured["bodyText"] == NEAR_LIMIT_CHILD_TEXT
    assert measured["row"]["height"] == pytest.approx(116, abs=0.5)
    assert measured["adjacentRow"]["height"] == pytest.approx(116, abs=0.5)
    assert measured["row"]["bottom"] <= measured["adjacentRow"]["top"]
    assert measured["speaker"]["top"] >= measured["row"]["top"]
    assert measured["speaker"]["bottom"] <= measured["body"]["top"]
    assert measured["body"]["top"] >= measured["row"]["top"]
    assert measured["body"]["bottom"] <= measured["row"]["bottom"]
    assert measured["bodyOverflowY"] == "auto"
    assert measured["bodyScrollHeight"] > measured["bodyClientHeight"]
    assert measured["bodyScrollTop"] == pytest.approx(
        measured["bodyScrollHeight"] - measured["bodyClientHeight"],
        abs=1,
    )
    assert measured["lastCharacter"]["top"] >= measured["body"]["top"] - 1
    assert measured["lastCharacter"]["bottom"] <= measured["body"]["bottom"] + 1
    assert measured["shortScrollHeight"] <= measured["shortClientHeight"]
    assert measured["scrollX"] == 0
    assert measured["scrollY"] == 0
    assert measured["documentWidth"] <= measured["viewportWidth"]
    assert measured["documentHeight"] <= measured["viewportHeight"]

    expected = READY_GEOMETRY[(viewport["width"], viewport["height"])]
    for name, expected_rect in expected.items():
        actual = measured["outer"][name]
        for field, expected_value in expected_rect.items():
            assert actual[field] == pytest.approx(expected_value, abs=1), (
                name,
                field,
                actual,
            )

    record.focus()
    page.keyboard.press("Shift+Tab")
    assert long_body.evaluate("node => document.activeElement === node") is True
    assert page.evaluate("window.scrollX === 0 && window.scrollY === 0") is True


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
@pytest.mark.parametrize("transcript_mode", ["empty", "populated"])
def test_recovery_stage_keeps_exact_panel_and_pet_orb_geometry_without_scroll(
    child_page,
    viewport,
    transcript_mode,
):
    prepare_child_page(
        child_page,
        viewport,
        roster=[SYNTHETIC_CHILD],
        active_by_child={1: SYNTHETIC_ACTIVE} if transcript_mode == "populated" else None,
    )
    page = child_page.page
    if transcript_mode == "empty":
        page.get_by_role("button", name="小芽", exact=True).click()
        page.wait_for_function(
            "window.__childTest.audio.instances.length === 1 "
            "&& window.__childTest.audio.instances[0].playCalls === 1"
        )
        page.evaluate("window.__childTest.audio.emitPlaying(0)")
        page.evaluate("window.__childTest.audio.emitEnded(0)")
    record = wait_for_active_ready(page)
    record.click()
    page.wait_for_function("window.__childTest.recognition.instances.length > 0")
    page.evaluate("window.__childTest.recognition.emitError('not-allowed')")
    page.evaluate("window.__childTest.recognition.emitEnd()")
    page.wait_for_function(
        "document.querySelector('.child-view')?.dataset.state === 'recovery'"
    )

    panel = page.locator(".child-conversation-panel")
    log = page.get_by_role("log", name="对话记录")
    alert = page.get_by_role("alert")
    assert panel.count() == 1
    assert log.count() == 1
    assert alert.count() == 1
    assert panel.locator('[role="log"]').count() == 1
    assert log.locator('[role="alert"]').count() == 1
    assert page.locator(".child-stage > [role=alert]").count() == 0
    assert page.locator(".child-stage > *").count() == 2
    assert page.locator(".child-view__error").count() == 0
    assert alert.locator(".child-message__text").inner_text() == "麦克风没有开启，请老师帮忙"
    transcript_rows = log.locator(".child-message--child, .child-message--diary")
    assert transcript_rows.count() == (0 if transcript_mode == "empty" else 2)

    measured = page.evaluate(
        """
        () => {
          const rectFor = selector => {
            const rect = document.querySelector(selector).getBoundingClientRect();
            return { x: rect.x, y: rect.y, width: rect.width, height: rect.height };
          };
          const scrolling = document.scrollingElement;
          return {
            panel: rectFor('.child-conversation-panel'),
            orb: rectFor('.child-pet-orb'),
            scrollX: window.scrollX,
            scrollY: window.scrollY,
            documentWidth: scrolling.scrollWidth,
            documentHeight: scrolling.scrollHeight,
            viewportWidth: window.innerWidth,
            viewportHeight: window.innerHeight,
          };
        }
        """
    )
    expected = READY_GEOMETRY[(viewport["width"], viewport["height"])]
    assert measured["scrollX"] == 0
    assert measured["scrollY"] == 0
    assert measured["documentWidth"] <= measured["viewportWidth"]
    assert measured["documentHeight"] <= measured["viewportHeight"]
    for name in ("panel", "orb"):
        for field, expected_value in expected[name].items():
            assert measured[name][field] == pytest.approx(expected_value, abs=1), (
                transcript_mode,
                name,
                field,
                measured[name],
            )

    panel_rect = measured["panel"]
    orb_rect = measured["orb"]
    assert panel_rect["x"] + panel_rect["width"] <= orb_rect["x"]
    assert orb_rect["x"] - (panel_rect["x"] + panel_rect["width"]) == pytest.approx(24, abs=1)
    assert panel_rect["y"] == pytest.approx(orb_rect["y"], abs=1)
    assert panel_rect["height"] == pytest.approx(orb_rect["height"], abs=1)


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_projection_is_reachable_without_horizontal_or_control_clipping(child_page, viewport):
    prepare_child_page(
        child_page,
        viewport,
        roster=[SYNTHETIC_CHILD],
        active_by_child={1: SYNTHETIC_ACTIVE},
    )
    page = child_page.page
    wait_for_active_ready(page)
    geometry = page.evaluate(
        """
        () => {
          const scrolling = document.scrollingElement;
          const main = document.querySelector('main');
          const view = document.querySelector('.child-view');
          return {
            bodyOverflowY: getComputedStyle(document.body).overflowY,
            documentFits: scrolling.scrollWidth <= scrolling.clientWidth,
            mainFits: main.scrollWidth <= main.clientWidth,
            viewFits: view.scrollWidth <= view.clientWidth,
            controls: [...document.querySelectorAll('button:not([hidden]),input:not([hidden]),textarea:not([hidden])')]
              .map(element => {
                const rect = element.getBoundingClientRect();
                return { id: element.id, width: rect.width, height: rect.height };
              }),
          };
        }
        """
    )
    assert geometry["bodyOverflowY"] not in {"hidden", "clip"}
    assert geometry["documentFits"] and geometry["mainFits"] and geometry["viewFits"]
    assert geometry["controls"]
    assert all(item["width"] >= 44 and item["height"] >= 44 for item in geometry["controls"])
    assert page.evaluate("({ x: window.scrollX, y: window.scrollY })") == {"x": 0, "y": 0}
    for locator in (
        page.get_by_role("heading", level=1),
        page.get_by_role("log", name="对话记录"),
        page.locator(".child-pet-orb"),
        page.get_by_role("button", name="开始说话", exact=True),
        page.get_by_role("button", name="请老师帮忙", exact=True),
        page.get_by_role("status"),
    ):
        box = locator.bounding_box()
        assert box is not None
        assert 0 <= box["x"] <= viewport["width"]
        assert 0 <= box["y"] <= viewport["height"]
        assert box["x"] + box["width"] <= viewport["width"]
        assert box["y"] + box["height"] <= viewport["height"]


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_child_health_validation_fallback_preserves_foundation_maintenance(child_page, viewport):
    page = child_page.page
    page.set_viewport_size(viewport)
    child_health = {**RUNTIME_VERSION, "db_mode": "app"}
    child_page.fulfill_json("**/api/health", child_health)
    child_page.fulfill_json("**/version.json*", RUNTIME_VERSION)
    page.goto(f"{child_page.server.base_url}/", wait_until="domcontentloaded")
    child_fallback = page.locator("#child-maintenance")
    child_fallback.wait_for()
    assert child_fallback.get_by_role("heading", name="幼儿端暂不可用").count() == 1
    assert page.locator("#runtime-maintenance").count() == 0
    assert "analysis_worker_status" not in page.locator("body").inner_text()

    page = child_page.context.new_page()
    child_page.page = page
    page.set_viewport_size(viewport)
    child_page.fulfill_json("**/api/health", {
        **RUNTIME_VERSION,
        "db_mode": "app",
        "analysis_worker_status": "not_started",
    })
    child_page.fulfill_json("**/version.json*", {**RUNTIME_VERSION, "release_id": "mismatch"})
    page.goto(f"{child_page.server.base_url}/", wait_until="domcontentloaded")
    foundation = page.locator("#runtime-maintenance")
    foundation.wait_for()
    assert foundation.get_by_role("heading", name="应用暂不可用").count() == 1
    assert page.locator("#child-maintenance").count() == 0
    assert "mismatch" not in page.locator("body").inner_text()
