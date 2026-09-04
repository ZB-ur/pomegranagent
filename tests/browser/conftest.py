from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import NamedTuple
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import urlopen

import pytest

from tests.browser.child_fakes import install_controlled_child_fakes


ROOT = Path(__file__).resolve().parents[2]
CHILD_SERVER_SCRIPT = ROOT / "tests/browser/child_server.py"
EXPECTED_PLAYWRIGHT_VERSION = "1.62.0"
EXPECTED_BROWSER_VERSION = "151.0.7922.34"
EXPECTED_REVISION = "1234"
UA_PATTERN = re.compile(r"(?:HeadlessChrome|Chrome)/151\.0\.7922\.34\b")
CFT_HEADER = re.compile(
    r"^Chrome for Testing (?P<product>\S+) "
    r"\(playwright chromium v(?P<revision>\d+)\)$"
)
SHELL_HEADER = re.compile(
    r"^Chrome Headless Shell (?P<product>\S+) "
    r"\(playwright chromium-headless-shell v(?P<revision>\d+)\)$"
)
INSTALL_LOCATION = re.compile(r"^\s+Install location:\s+(?P<path>.+?)\s*$")
FAIL_CLOSED_BUSINESS_PATTERNS = (
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
)
FAIL_CLOSED_BUSINESS_BODY = (
    '{"error":{"code":"UNEXPECTED_BROWSER_REQUEST","message":"fixture route required"}}'
)


class BrowserTarget(NamedTuple):
    product: str
    revision: str
    install_dir: Path


class BrowserGate(NamedTuple):
    cft: BrowserTarget
    shell: BrowserTarget


class BrowserServer(NamedTuple):
    process: subprocess.Popen
    port: int
    base_url: str
    runtime_dir: Path
    environment: dict[str, str]
    real_snapshots: object


def _target_from_output(output: str, header_pattern: re.Pattern[str], label: str) -> BrowserTarget:
    lines = output.splitlines()
    header_index = None
    header_match = None
    for index, line in enumerate(lines):
        match = header_pattern.fullmatch(line.strip())
        if match is not None:
            header_index = index
            header_match = match
            break
    if header_index is None or header_match is None:
        raise AssertionError(f"browser NO-GO: missing {label} dry-run header")
    install_dir = None
    for line in lines[header_index + 1 :]:
        if line and not line[0].isspace():
            break
        match = INSTALL_LOCATION.fullmatch(line)
        if match is not None:
            install_dir = Path(match.group("path")).expanduser().resolve()
            break
    if install_dir is None:
        raise AssertionError(f"browser NO-GO: missing {label} install location")
    return BrowserTarget(
        header_match.group("product"),
        header_match.group("revision"),
        install_dir,
    )


def parse_chromium_dry_run(output: str) -> BrowserGate:
    return BrowserGate(
        _target_from_output(output, CFT_HEADER, "Chrome for Testing"),
        _target_from_output(output, SHELL_HEADER, "Chrome Headless Shell"),
    )


def require_gate_one(*, runner=subprocess.run) -> BrowserGate:
    installed_version = importlib.metadata.version("playwright")
    if installed_version != EXPECTED_PLAYWRIGHT_VERSION:
        raise AssertionError(
            f"browser NO-GO: playwright {installed_version}, expected {EXPECTED_PLAYWRIGHT_VERSION}"
        )
    completed = runner(
        [sys.executable, "-m", "playwright", "install", "--dry-run", "chromium"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    complete_output = "\n".join(
        part for part in (completed.stdout, completed.stderr) if isinstance(part, str) and part
    )
    gate = parse_chromium_dry_run(complete_output)
    failures = []
    for label, target, expected_name in (
        ("Chrome for Testing", gate.cft, "chromium-1234"),
        ("Chrome Headless Shell", gate.shell, "chromium_headless_shell-1234"),
    ):
        if target.product != EXPECTED_BROWSER_VERSION or target.revision != EXPECTED_REVISION:
            failures.append(
                f"{label} reported {target.product} v{target.revision}; "
                f"expected {EXPECTED_BROWSER_VERSION} v{EXPECTED_REVISION}"
            )
        if target.install_dir.name != expected_name or not target.install_dir.is_dir():
            failures.append(f"{label} missing expected directory {target.install_dir}")
    if failures:
        expected_paths = f"{gate.cft.install_dir}, {gate.shell.install_dir}"
        raise AssertionError(
            "browser provisioning: NO-GO; "
            + "; ".join(failures)
            + f"; expected paths: {expected_paths}; human-authorized follow-up only: "
            + f"{sys.executable} -m playwright install chromium"
        )
    return gate


def validate_runtime_browser(browser) -> None:
    page = None
    try:
        if browser.version != EXPECTED_BROWSER_VERSION:
            raise AssertionError(
                f"browser NO-GO: runtime {browser.version}, expected {EXPECTED_BROWSER_VERSION}"
            )
        page = browser.new_page()
        user_agent = page.evaluate("navigator.userAgent")
        if UA_PATTERN.search(user_agent) is None:
            raise AssertionError(f"browser NO-GO: unexpected user agent {user_agent!r}")
    finally:
        try:
            if page is not None:
                page.close()
        finally:
            browser.close()


def is_exact_fixture_url(url: str, port: int) -> bool:
    try:
        parsed = urlsplit(url)
        parsed_port = parsed.port
    except (TypeError, ValueError):
        return False
    return (
        parsed.scheme == "http"
        and parsed.hostname == "127.0.0.1"
        and parsed_port == port
        and parsed.username is None
        and parsed.password is None
    )


def make_context_route_policy(*, port: int, egress_tripwire: Path):
    def context_policy(route):
        attempted = route.request.url
        if is_exact_fixture_url(attempted, port):
            route.continue_()
            return
        egress_tripwire.write_text(f"{attempted}\n", encoding="utf-8")
        route.abort("blockedbyclient")

    return context_policy


def install_fail_closed_business_routes(page, *, port: int) -> None:
    def fail_closed(route):
        assert is_exact_fixture_url(route.request.url, port)
        route.fulfill(
            status=503,
            content_type="application/json",
            body=FAIL_CLOSED_BUSINESS_BODY,
        )

    for pattern in FAIL_CLOSED_BUSINESS_PATTERNS:
        page.route(pattern, fail_closed)


def _load_child_server_module():
    spec = importlib.util.spec_from_file_location("task6b_child_server_fixture", CHILD_SERVER_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def chromium_gate_parser():
    return parse_chromium_dry_run


@pytest.fixture
def gate_one_validator():
    return require_gate_one


@pytest.fixture
def runtime_browser_validator():
    return validate_runtime_browser


@pytest.fixture
def exact_fixture_url():
    return is_exact_fixture_url


@pytest.fixture
def context_route_policy():
    return make_context_route_policy


@pytest.fixture
def business_route_installer():
    return install_fail_closed_business_routes


@pytest.fixture
def unused_tcp_port(free_tcp_port):
    return free_tcp_port


@pytest.fixture(scope="session", autouse=True)
def browser_parent_logging_guard(tmp_path_factory):
    real_log = (ROOT / "logs" / "app.log").resolve()
    if not real_log.parent.is_dir():
        pytest.fail(
            f"browser preflight NO-GO: missing real log directory {real_log.parent}",
            pytrace=False,
        )
    before = real_log.read_bytes() if real_log.exists() else None
    root_logger = logging.getLogger()
    removed_real_handlers = []
    for handler in tuple(root_logger.handlers):
        base_filename = getattr(handler, "baseFilename", None)
        if base_filename is not None and Path(base_filename).resolve() == real_log:
            root_logger.removeHandler(handler)
            removed_real_handlers.append(handler)

    disposable_log = tmp_path_factory.mktemp("browser-parent-logs") / "pytest.log"
    disposable_handler = logging.FileHandler(disposable_log, encoding="utf-8")
    root_logger.addHandler(disposable_handler)
    try:
        yield disposable_log
    finally:
        after = real_log.read_bytes() if real_log.exists() else None
        root_logger.removeHandler(disposable_handler)
        disposable_handler.close()
        for handler in removed_real_handlers:
            root_logger.addHandler(handler)
        assert after == before, "browser parent process changed the real application log"


@pytest.fixture(scope="session")
def chromium_browser(browser_parent_logging_guard):
    del browser_parent_logging_guard
    gate_error = None
    try:
        require_gate_one()
    except AssertionError as error:
        gate_error = str(error)
    if gate_error is not None:
        pytest.fail(gate_error, pytrace=False)

    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        probe = playwright.chromium.launch(headless=True)
        validate_runtime_browser(probe)
        yield lambda: playwright.chromium.launch(headless=True)


def _verify_server_safety(module, server: BrowserServer) -> None:
    after = module.capture_resource_snapshots(
        module.REAL_DATABASE_PATH,
        module.REAL_LOG_PATH,
        module.REAL_TTS_CACHE_PATH,
        module.REAL_MEDIA_ROOT,
    )
    assert after == server.real_snapshots, "browser fixture changed a real application resource"
    for name in (
        "BROWSER_AI_TRIPWIRE_PATH",
        "BROWSER_NETWORK_TRIPWIRE_PATH",
        "BROWSER_CONTEXT_EGRESS_TRIPWIRE_PATH",
    ):
        assert not Path(server.environment[name]).exists(), f"browser tripwire fired: {name}"


@pytest.fixture
def child_server(chromium_browser, tmp_path, unused_tcp_port):
    del chromium_browser
    module = _load_child_server_module()
    if not module.REAL_LOG_PATH.parent.is_dir():
        pytest.fail(
            f"browser preflight NO-GO: missing real log directory {module.REAL_LOG_PATH.parent}",
            pytrace=False,
        )
    runtime_dir = (tmp_path / "browser-runtime").resolve()
    runtime_dir.mkdir()
    (runtime_dir / "logs").mkdir()
    (runtime_dir / "tts-cache").mkdir()
    environment = module.build_browser_environment(os.environ, runtime_dir, port=unused_tcp_port)
    snapshots = module.capture_resource_snapshots(
        module.REAL_DATABASE_PATH,
        module.REAL_LOG_PATH,
        module.REAL_TTS_CACHE_PATH,
        module.REAL_MEDIA_ROOT,
    )
    process = subprocess.Popen(
        [sys.executable, str(CHILD_SERVER_SCRIPT)],
        cwd=ROOT,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    server = BrowserServer(
        process,
        unused_tcp_port,
        f"http://127.0.0.1:{unused_tcp_port}",
        runtime_dir,
        environment,
        snapshots,
    )
    deadline = time.monotonic() + 5
    health = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            break
        try:
            with urlopen(f"{server.base_url}/api/health", timeout=0.25) as response:
                health = json.load(response)
            break
        except (OSError, URLError):
            time.sleep(0.05)
    if health is None or health.get("db_mode") != "app":
        module.close_and_verify([], process, verify=lambda: _verify_server_safety(module, server))
        pytest.fail(
            f"loopback child server failed; inspect {runtime_dir / 'logs/app.log'}",
            pytrace=False,
        )
    try:
        yield server
    finally:
        module.close_and_verify([], process, verify=lambda: _verify_server_safety(module, server))


class ChildPageHarness:
    def __init__(self, *, page, context, browser, server: BrowserServer) -> None:
        self.page = page
        self.context = context
        self.browser = browser
        self.server = server

    def fulfill_json(self, pattern: str, payload, *, status: int = 200) -> None:
        port = self.server.port

        def handler(route):
            assert is_exact_fixture_url(route.request.url, port)
            route.fulfill(
                status=status,
                content_type="application/json",
                body=json.dumps(payload, ensure_ascii=False),
            )

        self.page.route(pattern, handler)

    def fulfill_bytes(self, pattern: str, payload: bytes, *, content_type: str) -> None:
        port = self.server.port

        def handler(route):
            assert is_exact_fixture_url(route.request.url, port)
            route.fulfill(status=200, content_type=content_type, body=payload)

        self.page.route(pattern, handler)


@pytest.fixture
def child_page(chromium_browser, child_server):
    browser = chromium_browser()
    context = browser.new_context(service_workers="block")
    egress_tripwire = Path(child_server.environment["BROWSER_CONTEXT_EGRESS_TRIPWIRE_PATH"])

    context.route(
        "**/*",
        make_context_route_policy(port=child_server.port, egress_tripwire=egress_tripwire),
    )
    install_fail_closed_business_routes(context, port=child_server.port)
    page = context.new_page()
    install_controlled_child_fakes(page)
    harness = ChildPageHarness(page=page, context=context, browser=browser, server=child_server)
    try:
        yield harness
    finally:
        for resource in (page, context, browser):
            try:
                resource.close()
            except Exception:
                pass


class TeacherBrowserHarness:
    """Fresh, exact-origin teacher contexts backed by the disposable app server."""

    def __init__(self, *, browser, server: BrowserServer) -> None:
        self.browser = browser
        self.server = server
        self._contexts = []

    def new_context(self):
        context = self.browser.new_context(service_workers="block")
        egress_tripwire = Path(self.server.environment["BROWSER_CONTEXT_EGRESS_TRIPWIRE_PATH"])
        context.route(
            "**/*",
            make_context_route_policy(port=self.server.port, egress_tripwire=egress_tripwire),
        )
        self._contexts.append(context)
        return context

    def close(self) -> None:
        for context in reversed(self._contexts):
            for page in reversed(context.pages):
                try:
                    page.close()
                except Exception:
                    pass
            try:
                context.close()
            except Exception:
                pass
        self._contexts.clear()
        self.browser.close()


@pytest.fixture
def teacher_browser(chromium_browser, child_server):
    browser = chromium_browser()
    harness = TeacherBrowserHarness(browser=browser, server=child_server)
    try:
        yield harness
    finally:
        harness.close()
