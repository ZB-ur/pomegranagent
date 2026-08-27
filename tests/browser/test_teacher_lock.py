from __future__ import annotations

import json
from urllib.parse import urlsplit

import pytest


VIEWPORTS = [{"width": 1024, "height": 768}, {"width": 1440, "height": 900}]
VIEWPORT_IDS = ["1024x768", "1440x900"]
PIN = "2468"


def application_paths(requests, base_url: str) -> list[str]:
    origin = urlsplit(base_url)
    paths = []
    for request in requests:
        parsed = urlsplit(request.url)
        if parsed.scheme == origin.scheme and parsed.netloc == origin.netloc:
            paths.append(parsed.path)
    return paths


def open_teacher_page(teacher_browser, viewport):
    context = teacher_browser.new_context()
    page = context.new_page()
    page.set_default_timeout(5_000)
    page.set_viewport_size(viewport)
    page.goto(f"{teacher_browser.server.base_url}/teacher.html", wait_until="domcontentloaded")
    return context, page


def setup_teacher(page, *, pin: str = PIN) -> None:
    page.get_by_label("设置教师 PIN", exact=True).fill(pin)
    page.get_by_role("button", name="设置并解锁", exact=True).click()
    page.get_by_role("heading", name="概览", exact=True).wait_for()
    assert page.locator("form").count() == 0
    assert page.locator("#teacher-pin").count() == 0


def lock_teacher(page) -> None:
    page.get_by_role("button", name="立即锁定", exact=True).click()
    page.get_by_label("教师 PIN", exact=True).wait_for()


def assert_pin_absent(page, pin: str) -> None:
    assert pin not in page.locator("body").inner_text()
    assert pin not in page.url
    assert page.evaluate("JSON.stringify(sessionStorage)").find(pin) == -1
    assert page.evaluate("JSON.stringify(localStorage)").find(pin) == -1
    assert page.evaluate("document.documentElement.outerHTML").find(pin) == -1


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_teacher_shell_has_no_inline_runtime(teacher_browser, viewport):
    context = teacher_browser.new_context()
    page = context.new_page()
    page.set_viewport_size(viewport)
    page.goto(f"{teacher_browser.server.base_url}/teacher.html", wait_until="domcontentloaded")
    assert page.locator("style").count() == 0
    assert page.locator("[style]").count() == 0
    assert page.evaluate(
        "[...document.scripts].map(script => [new URL(script.src).pathname, script.type])"
    ) == [
        ["/shared/api.js", ""],
        ["/shared/auth.js", ""],
        ["/teacher/app.js", "module"],
    ]
    assert page.locator('link[href="/teacher/styles.css"]').count() == 1
    assert page.locator('script[type="module"][src="/teacher/app.js"]').count() == 1


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_teacher_locked_bootstrap_makes_only_runtime_and_auth_requests(teacher_browser, viewport):
    context = teacher_browser.new_context()
    page = context.new_page()
    page.set_viewport_size(viewport)
    requests = []
    page.on("request", lambda request: requests.append(request))
    page.goto(f"{teacher_browser.server.base_url}/teacher.html", wait_until="domcontentloaded")
    page.get_by_label("设置教师 PIN", exact=True).wait_for()
    paths = application_paths(requests, teacher_browser.server.base_url)
    assert {path for path in paths if path.startswith("/api/")} <= {
        "/api/health",
        "/api/auth/status",
    }
    assert "/version.json" in paths
    assert page.get_by_role("heading", name="概览", exact=True).count() == 0
    assert page.get_by_role("heading", name="幼儿管理", exact=True).count() == 0
    assert page.get_by_role("heading", name="值日审阅", exact=True).count() == 0
    assert all(button.is_disabled() for button in page.locator("#nav button").all())


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_teacher_first_setup_and_manual_lock_stay_in_the_same_document(teacher_browser, viewport):
    _context, page = open_teacher_page(teacher_browser, viewport)
    page.get_by_role("heading", name="首次设置教师 PIN", exact=True).wait_for()
    initial_url = page.url
    setup_teacher(page)
    assert page.url == initial_url
    assert not any(button.is_disabled() for button in page.locator("#nav button").all())
    lock_teacher(page)
    assert page.url == initial_url
    assert all(button.is_disabled() for button in page.locator("#nav button").all())
    assert page.get_by_role("heading", name="概览", exact=True).count() == 0
    assert page.get_by_role("heading", name="教师端已锁定", exact=True).count() == 1


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_teacher_wrong_pin_is_safe_focuses_input_and_never_persists_material(teacher_browser, viewport):
    _context, page = open_teacher_page(teacher_browser, viewport)
    setup_teacher(page)
    lock_teacher(page)
    input_box = page.get_by_label("教师 PIN", exact=True)
    input_box.fill("1111")
    page.get_by_role("button", name="解锁", exact=True).click()
    page.get_by_text("PIN 不正确", exact=True).wait_for()
    assert page.get_by_role("button", name="解锁", exact=True).is_enabled()
    assert page.evaluate("document.activeElement?.id") == "teacher-pin"
    assert input_box.input_value() == "1111"
    assert page.get_by_role("heading", name="概览", exact=True).count() == 0
    assert_pin_absent(page, "1111")


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_teacher_fresh_context_requires_unlock_without_cookie_seeding(teacher_browser, viewport):
    context_a, page_a = open_teacher_page(teacher_browser, viewport)
    setup_teacher(page_a)
    context_a.close()

    context_b = teacher_browser.new_context()
    page_b = context_b.new_page()
    page_b.set_viewport_size(viewport)
    page_b.goto(f"{teacher_browser.server.base_url}/teacher.html", wait_until="domcontentloaded")
    page_b.get_by_label("教师 PIN", exact=True).wait_for()
    assert page_b.get_by_role("heading", name="概览", exact=True).count() == 0
    assert all(button.is_disabled() for button in page_b.locator("#nav button").all())


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_teacher_lock_failure_preserves_authenticated_view_and_announces_error(teacher_browser, viewport):
    _context, page = open_teacher_page(teacher_browser, viewport)
    setup_teacher(page)
    lock_requests = []

    def fail_lock(route):
        lock_requests.append(route.request.url)
        route.fulfill(
            status=500,
            content_type="application/json",
            body=json.dumps({"error": {"code": "LOCK_FAILED", "message": "raw-lock-detail-2468"}}),
        )

    page.route(f"{teacher_browser.server.base_url}/api/auth/lock", fail_lock)
    page.get_by_role("button", name="立即锁定", exact=True).click()
    page.locator("#teacher-lock-feedback").get_by_text("暂时无法锁定，请稍后重试。", exact=True).wait_for()
    assert len(lock_requests) == 1
    assert page.get_by_role("heading", name="概览", exact=True).count() == 1
    assert not any(button.is_disabled() for button in page.locator("#nav button").all())
    assert page.get_by_role("button", name="立即锁定", exact=True).is_enabled()
    assert "raw-lock-detail-2468" not in page.locator("body").inner_text()


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_teacher_runtime_failure_keeps_maintenance_and_makes_zero_auth_or_business_requests(teacher_browser, viewport):
    context = teacher_browser.new_context()
    page = context.new_page()
    page.set_viewport_size(viewport)
    requests = []
    page.on("request", lambda request: requests.append(request))

    def incompatible_health(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "release_id": "incompatible",
                "api_version": "2",
                "schema_version": "2",
                "db_mode": "app",
            }),
        )

    page.route(f"{teacher_browser.server.base_url}/api/health", incompatible_health)
    page.goto(f"{teacher_browser.server.base_url}/teacher.html", wait_until="domcontentloaded")
    page.locator("#runtime-maintenance").wait_for()
    paths = application_paths(requests, teacher_browser.server.base_url)
    assert not any(path.startswith("/api/auth/") for path in paths)
    assert {path for path in paths if path.startswith("/api/")} == {"/api/health"}
    assert page.locator("#nav").count() == 0
    assert page.get_by_role("heading", name="概览", exact=True).count() == 0


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_teacher_auth_status_failure_is_safe_and_makes_zero_business_requests(teacher_browser, viewport):
    context = teacher_browser.new_context()
    page = context.new_page()
    page.set_default_timeout(5_000)
    page.set_viewport_size(viewport)
    requests = []
    page.on("request", lambda request: requests.append(request))

    def fail_status(route):
        route.fulfill(
            status=500,
            content_type="application/json",
            body=json.dumps({
                "error": {
                    "code": "AUTH_STATUS_UNAVAILABLE",
                    "message": "raw-auth-status-detail-2468",
                }
            }),
        )

    page.route(f"{teacher_browser.server.base_url}/api/auth/status", fail_status)
    page.goto(f"{teacher_browser.server.base_url}/teacher.html", wait_until="domcontentloaded")
    page.get_by_text("教师端暂不可用，请稍后重试。", exact=True).wait_for()
    paths = application_paths(requests, teacher_browser.server.base_url)
    assert "raw-auth-status-detail-2468" not in page.locator("body").inner_text()
    assert {path for path in paths if path.startswith("/api/")} == {
        "/api/health",
        "/api/auth/status",
    }
    assert all(button.is_disabled() for button in page.locator("#nav button").all())
    assert page.get_by_role("heading", name="概览", exact=True).count() == 0
    assert page.get_by_role("heading", name="幼儿管理", exact=True).count() == 0
    assert page.get_by_role("heading", name="值日审阅", exact=True).count() == 0


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_teacher_pagehide_clears_pin_and_success_paths_leave_no_pin_material(teacher_browser, viewport):
    _context, page = open_teacher_page(teacher_browser, viewport)
    auth_requests = []
    page.on(
        "request",
        lambda request: auth_requests.append(urlsplit(request.url).path)
        if "/api/auth/" in request.url
        else None,
    )
    setup_teacher(page)
    assert_pin_absent(page, PIN)
    lock_teacher(page)
    assert page.get_by_label("教师 PIN", exact=True).input_value() == ""
    page.get_by_label("教师 PIN", exact=True).fill(PIN)
    page.get_by_role("button", name="解锁", exact=True).click()
    page.get_by_role("heading", name="概览", exact=True).wait_for()
    assert page.locator("form").count() == 0
    assert page.locator("#teacher-pin").count() == 0
    assert_pin_absent(page, PIN)
    lock_teacher(page)
    input_box = page.get_by_label("教师 PIN", exact=True)
    input_box.fill("1111")
    submit = page.get_by_role("button", name="解锁", exact=True)
    assert submit.is_enabled()
    submit.click()
    page.get_by_text("PIN 不正确", exact=True).wait_for()
    assert auth_requests[-1:] == ["/api/auth/unlock"], auth_requests
    page.evaluate("window.dispatchEvent(new PageTransitionEvent('pagehide'))")
    assert input_box.input_value() == ""
