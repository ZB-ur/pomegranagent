import asyncio
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import os
from pathlib import Path
import re
import sqlite3
import subprocess
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
BROWSER_ENTRY = ROOT / "app/frontend/child/browser.mjs"
CHILD_SERVER = ROOT / "tests/browser/child_server.py"
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


def test_browser_entry_keyboard_policy_is_forward_only():
    source = browser_source()
    assert "function isInteractiveTarget(target)" in source
    assert "target.isContentEditable" in source
    assert "[role=\"dialog\"][aria-modal=\"true\"],dialog[open]" in source
    assert "function forwardGlobalKeydown(event)" in source
    forwarder = re.search(r"function forwardGlobalKeydown\(event\) \{(?P<body>.*?)\n\}", source, re.DOTALL)
    assert forwarder is not None
    assert "app.handleGlobalKeydown(event)" in forwarder.group("body")
    for forbidden in ("preventDefault", "recordToggle", "speech"):
        assert forbidden not in forwarder.group("body")


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
    cache.mkdir()
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE sample (value TEXT)")
        connection.execute("INSERT INTO sample VALUES ('synthetic')")
    log.write_bytes(b"synthetic-log")
    (cache / "synthetic.mp3").write_bytes(b"synthetic-audio")
    before_bytes = database.read_bytes(), log.read_bytes(), (cache / "synthetic.mp3").read_bytes()
    calls = []

    def read_only_connect(database_uri, *, uri):
        calls.append((database_uri, uri))
        return sqlite3.connect(database_uri, uri=uri)

    first = module.capture_resource_snapshots(database, log, cache, connect=read_only_connect)
    second = module.capture_resource_snapshots(database, log, cache, connect=read_only_connect)
    assert first == second
    assert calls and all(uri is True and "mode=ro" in database_uri for database_uri, uri in calls)
    assert before_bytes == (database.read_bytes(), log.read_bytes(), (cache / "synthetic.mp3").read_bytes())


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
    for locator in (
        page.get_by_role("heading", level=1),
        page.get_by_role("log", name="对话记录"),
        page.get_by_role("button", name="开始说话", exact=True),
        page.get_by_role("button", name="请老师帮忙", exact=True),
        page.get_by_role("status"),
    ):
        locator.scroll_into_view_if_needed()
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
