from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest

from tests.browser.conftest import is_exact_fixture_url


VIEWPORTS = [{"width": 1024, "height": 768}, {"width": 1440, "height": 900}]
VIEWPORT_IDS = ["1024x768", "1440x900"]
PIN = "2468"
FAILURE_COPY = "加载失败，请重新进入此页面。"


def open_teacher(teacher_browser, viewport, fragment: str = ""):
    context = teacher_browser.new_context()
    page = context.new_page()
    page.set_default_timeout(5_000)
    page.set_viewport_size(viewport)
    page.goto(f"{teacher_browser.server.base_url}/teacher.html{fragment}", wait_until="domcontentloaded")
    return context, page


def setup_teacher(page, heading: str = "今日任务") -> None:
    page.get_by_label("设置教师 PIN", exact=True).fill(PIN)
    page.get_by_role("button", name="设置并解锁", exact=True).click()
    page.get_by_role("heading", name=heading, exact=True).wait_for()
    assert page.locator("form").count() == 0


def active_route(page) -> str:
    active = page.locator("#nav button.active")
    assert active.count() == 1
    assert active.get_attribute("aria-current") == "page"
    return active.inner_text()


def assert_focused_heading(page, label: str) -> None:
    heading = page.get_by_role("heading", name=label, exact=True)
    heading.wait_for()
    assert heading.get_attribute("tabindex") == "-1"
    assert page.evaluate("node => document.activeElement === node", heading.element_handle())


def assert_same_document_with_today(page, teacher_browser) -> None:
    parsed = urlsplit(page.url)
    origin = urlsplit(teacher_browser.server.base_url)
    assert (parsed.scheme, parsed.netloc, parsed.path) == (origin.scheme, origin.netloc, "/teacher.html")
    assert parsed.fragment == "today"


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_teacher_hash_click_back_forward_active_and_focus(teacher_browser, viewport):
    _context, page = open_teacher(teacher_browser, viewport)
    setup_teacher(page)
    assert_same_document_with_today(page, teacher_browser)

    page.get_by_role("button", name="幼儿管理", exact=True).click()
    page.get_by_role("heading", name="幼儿管理", exact=True).wait_for()
    assert urlsplit(page.url).fragment == "children"
    assert active_route(page) == "幼儿管理"
    assert_focused_heading(page, "幼儿管理")

    page.get_by_role("button", name="小鸭管理", exact=True).click()
    page.get_by_role("heading", name="小鸭管理", exact=True).wait_for()
    assert urlsplit(page.url).fragment == "ducks"
    assert active_route(page) == "小鸭管理"
    assert_focused_heading(page, "小鸭管理")

    page.go_back()
    page.get_by_role("heading", name="幼儿管理", exact=True).wait_for()
    assert urlsplit(page.url).fragment == "children"
    assert active_route(page) == "幼儿管理"
    assert_focused_heading(page, "幼儿管理")

    page.go_forward()
    page.get_by_role("heading", name="小鸭管理", exact=True).wait_for()
    assert urlsplit(page.url).fragment == "ducks"
    assert active_route(page) == "小鸭管理"
    assert_focused_heading(page, "小鸭管理")


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
@pytest.mark.parametrize("fragment", ["", "#bogus"], ids=["empty", "unknown"])
def test_teacher_canonicalizes_empty_and_unknown_hash_only_after_authentication(teacher_browser, viewport, fragment):
    _context, page = open_teacher(teacher_browser, viewport, fragment)
    page.get_by_label("设置教师 PIN", exact=True).wait_for()
    assert urlsplit(page.url).fragment in ("", "bogus")
    setup_teacher(page)
    assert_same_document_with_today(page, teacher_browser)
    assert active_route(page) == "今日任务"


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_teacher_growth_fragment_query_is_preserved_and_requests_the_selected_child(teacher_browser, viewport):
    _context, page = open_teacher(teacher_browser, viewport, "#growth?child_id=7")
    growth_requests = []
    page.on("request", lambda request: growth_requests.append(request.url) if "/api/analysis/growth" in request.url else None)

    setup_teacher(page, "能力成长曲线")
    assert page.url == f"{teacher_browser.server.base_url}/teacher.html#growth?child_id=7"
    assert active_route(page) == "能力成长曲线"
    assert_focused_heading(page, "能力成长曲线")
    parsed_requests = [urlsplit(url) for url in growth_requests]
    assert any(parsed.path == "/api/analysis/growth" and parse_qs(parsed.query) == {"child_id": ["7"]} for parsed in parsed_requests)
    page.reload(wait_until="domcontentloaded")
    page.get_by_role("heading", name="能力成长曲线", exact=True).wait_for()
    assert page.locator("#teacher-pin").count() == 0
    assert page.url == f"{teacher_browser.server.base_url}/teacher.html#growth?child_id=7"


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_teacher_clicking_current_today_refetches_without_creating_history(teacher_browser, viewport):
    _context, page = open_teacher(teacher_browser, viewport)
    reads = []
    page.on("request", lambda request: reads.append(request.url) if urlsplit(request.url).path == "/api/roster/today" else None)
    setup_teacher(page)
    before_history = page.evaluate("history.length")
    with page.expect_request(f"{teacher_browser.server.base_url}/api/roster/today"):
        page.get_by_role("button", name="今日任务", exact=True).click()
    page.get_by_role("heading", name="今日任务", exact=True).wait_for()
    assert len(reads) >= 2
    assert page.evaluate("history.length") == before_history
    assert_same_document_with_today(page, teacher_browser)


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_teacher_navigation_aborts_held_today_without_late_dom_mutation(teacher_browser, viewport):
    _context, page = open_teacher(teacher_browser, viewport)
    held = []
    failures = []
    page.on("requestfailed", lambda request: failures.append(request.url))

    def hold_today(route):
        assert is_exact_fixture_url(route.request.url, teacher_browser.server.port)
        held.append(route)

    page.route(f"{teacher_browser.server.base_url}/api/roster/today", hold_today)
    setup_teacher(page)
    assert len(held) == 1
    page.get_by_role("button", name="幼儿管理", exact=True).click()
    page.get_by_role("heading", name="幼儿管理", exact=True).wait_for()
    page.wait_for_timeout(100)
    old_url = f"{teacher_browser.server.base_url}/api/roster/today"
    assert old_url in failures
    assert urlsplit(page.url).fragment == "children"
    assert active_route(page) == "幼儿管理"
    assert_focused_heading(page, "幼儿管理")
    assert "幼儿人数" not in page.locator("#main").inner_text()


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_teacher_rapid_navigation_keeps_only_the_newest_route_and_no_page_error(teacher_browser, viewport):
    _context, page = open_teacher(teacher_browser, viewport)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    setup_teacher(page)
    for label in ("幼儿管理", "小鸭管理", "值日排班"):
        page.get_by_role("button", name=label, exact=True).click()
    page.get_by_role("heading", name="值日排班", exact=True).wait_for()
    assert active_route(page) == "值日排班"
    assert_focused_heading(page, "值日排班")
    assert urlsplit(page.url).fragment == "roster"
    assert errors == []
    assert "AbortError" not in page.locator("body").inner_text()


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_teacher_manual_lock_aborts_route_and_unlock_starts_one_fresh_route_load(teacher_browser, viewport):
    _context, page = open_teacher(teacher_browser, viewport)
    today_routes = []
    failures = []
    page.on("requestfailed", lambda request: failures.append(request.url))

    def hold_first_today(route):
        assert is_exact_fixture_url(route.request.url, teacher_browser.server.port)
        today_routes.append(route)
        if len(today_routes) > 1:
            route.fulfill(status=200, content_type="application/json", body="[]")

    page.route(f"{teacher_browser.server.base_url}/api/roster/today", hold_first_today)
    setup_teacher(page)
    assert len(today_routes) == 1
    page.get_by_role("button", name="立即锁定", exact=True).click()
    page.get_by_label("教师 PIN", exact=True).wait_for()
    page.wait_for_timeout(100)
    assert f"{teacher_browser.server.base_url}/api/roster/today" in failures
    assert page.get_by_role("heading", name="今日任务", exact=True).count() == 0
    assert all(button.is_disabled() for button in page.locator("#nav button").all())

    page.get_by_label("教师 PIN", exact=True).fill(PIN)
    page.get_by_role("button", name="解锁", exact=True).click()
    page.get_by_role("heading", name="今日任务", exact=True).wait_for()
    assert len(today_routes) == 2
    assert active_route(page) == "今日任务"
    assert_same_document_with_today(page, teacher_browser)


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
@pytest.mark.parametrize("fragment, heading", [("#review", "值日审阅"), ("#search", "明细检索")])
def test_teacher_legacy_review_and_search_errors_are_fixed_and_navigable(teacher_browser, viewport, fragment, heading):
    _context, page = open_teacher(teacher_browser, viewport, fragment)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    setup_teacher(page, heading)
    alert = page.locator("#main [role='alert']")
    alert.get_by_text(FAILURE_COPY, exact=True).wait_for()
    assert alert.count() == 1
    body = page.locator("body").inner_text()
    assert "Field required" not in body
    assert "AbortError" not in body
    assert errors == []
    page.get_by_role("button", name="今日任务", exact=True).click()
    page.get_by_role("heading", name="今日任务", exact=True).wait_for()
    assert active_route(page) == "今日任务"


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_teacher_legacy_hard_delete_error_is_fixed_and_navigable(teacher_browser, viewport):
    _context, page = open_teacher(teacher_browser, viewport)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))

    def ducks(route):
        assert is_exact_fixture_url(route.request.url, teacher_browser.server.port)
        route.fulfill(
            status=200,
            content_type="application/json",
            body='[{"id":1,"name":"测试小鸭","avatar":null,"status":"健康","note":null,"active":true,"deactivated_at":null}]',
        )

    page.route(f"{teacher_browser.server.base_url}/api/ducks", ducks)
    setup_teacher(page)
    page.get_by_role("button", name="小鸭管理", exact=True).click()
    page.get_by_role("heading", name="小鸭管理", exact=True).wait_for()
    page.get_by_role("button", name="删除", exact=True).click()
    alert = page.locator("#main [role='alert']")
    alert.get_by_text(FAILURE_COPY, exact=True).wait_for()
    assert alert.count() == 1
    body = page.locator("body").inner_text()
    assert "已禁用永久删除" not in body
    assert "删除成功" not in body
    assert errors == []
    page.get_by_role("button", name="今日任务", exact=True).click()
    page.get_by_role("heading", name="今日任务", exact=True).wait_for()
    assert active_route(page) == "今日任务"
