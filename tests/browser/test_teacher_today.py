from __future__ import annotations

from urllib.parse import urlsplit

import pytest

from tests.browser.conftest import is_exact_fixture_url


VIEWPORTS = [{"width": 1024, "height": 768}, {"width": 1440, "height": 900}]
VIEWPORT_IDS = ["1024x768", "1440x900"]
PIN = "2468"
TODAY_REQUESTS = [
    "/api/roster/today",
    "/api/conversations?queue=pending",
    "/api/conversations?queue=processing",
    "/api/conversations?queue=failed",
]
PANEL_PATHS = {
    "roster": "/api/roster/today",
    "pending": "/api/conversations?queue=pending",
    "processing": "/api/conversations?queue=processing",
    "failed": "/api/conversations?queue=failed",
}
LOADING_COPY = {
    "roster": "正在加载今日排班…",
    "pending": "正在加载待审阅会话…",
    "processing": "正在加载分析中会话…",
    "failed": "正在加载分析失败会话…",
}
EMPTY_COPY = {
    "roster": "今天还未排班",
    "pending": "暂无待审阅会话",
    "processing": "暂无分析中的会话",
    "failed": "暂无分析失败会话",
}
RELOAD_COPY = {
    "roster": "重新加载今日值日生",
    "pending": "重新加载待审阅",
    "processing": "重新加载分析中",
    "failed": "重新加载分析失败",
}
ROSTER_ROW = {"id": 7, "name": "小雨", "nickname": "雨雨", "avatar": "rain.png"}


def queue_row(queue: str) -> dict:
    return {
        "id": 42,
        "child": ROSTER_ROW,
        "date": "2026-08-23",
        "started_at": "2026-08-23T08:54:00Z",
        "completed_at": "2026-08-23T08:59:00Z",
        "message_count": 4,
        "round": 2,
        "status": "ended",
        "end_reason": "max_rounds",
        "analysis_status": "succeeded" if queue == "pending" else "processing" if queue == "processing" else "failed",
        "review_status": "draft" if queue == "pending" else "unavailable",
        "revision": 2,
    }


def open_teacher(teacher_browser, viewport, fragment: str = ""):
    context = teacher_browser.new_context()
    page = context.new_page()
    page.set_default_timeout(5_000)
    page.set_viewport_size(viewport)
    page.goto(f"{teacher_browser.server.base_url}/teacher.html{fragment}", wait_until="domcontentloaded")
    return context, page


def setup_teacher(page) -> None:
    page.get_by_label("设置教师 PIN", exact=True).fill(PIN)
    page.get_by_role("button", name="设置并解锁", exact=True).click()
    page.get_by_role("heading", name="今日任务", exact=True).wait_for()


def application_request_paths(requests, base_url: str) -> list[str]:
    origin = urlsplit(base_url)
    result = []
    for request in requests:
        parsed = urlsplit(request.url)
        if (parsed.scheme, parsed.netloc) != (origin.scheme, origin.netloc):
            continue
        result.append(parsed.path + (f"?{parsed.query}" if parsed.query else ""))
    return result


def panel(page, key: str):
    return page.locator(f'[data-today-panel="{key}"]')


def install_panel_routes(page, teacher_browser, handlers) -> None:
    for key, path in PANEL_PATHS.items():
        def make_handler(panel_key):
            def handler(route):
                assert is_exact_fixture_url(route.request.url, teacher_browser.server.port)
                handlers[panel_key](route)
            return handler
        page.route(f"{teacher_browser.server.base_url}{path}", make_handler(key))


def fulfill_json(route, body, status: int = 200) -> None:
    route.fulfill(status=status, content_type="application/json", body=__import__("json").dumps(body))


def empty_handlers():
    return {key: lambda route: fulfill_json(route, []) for key in PANEL_PATHS}


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_teacher_today_shell_migrates_overview_before_first_authenticated_load(teacher_browser, viewport):
    _context, page = open_teacher(teacher_browser, viewport, "#overview?source=legacy")
    requests = []
    held = []
    page.on("request", lambda request: requests.append(request))

    def hold_roster(route):
        assert is_exact_fixture_url(route.request.url, teacher_browser.server.port)
        held.append(route)

    page.route(f"{teacher_browser.server.base_url}/api/roster/today", hold_roster)
    page.get_by_label("设置教师 PIN", exact=True).wait_for()
    assert urlsplit(page.url).fragment == "overview?source=legacy"
    setup_teacher(page)
    page.wait_for_function("() => performance.getEntriesByType('resource').some(entry => entry.name.includes('/api/conversations?queue=failed'))")

    assert urlsplit(page.url).fragment == "today?source=legacy"
    active = page.locator("#nav button.active")
    assert active.count() == 1
    assert active.inner_text() == "今日任务"
    assert active.get_attribute("aria-current") == "page"
    heading = page.get_by_role("heading", name="今日任务", exact=True)
    assert heading.evaluate("node => document.activeElement === node")
    assert page.get_by_text("教师工作台", exact=True).count() == 1
    assert page.get_by_text("已解锁 · 仅本次浏览器会话", exact=True).count() == 1
    assert page.locator("#main").inner_text().find("今日值日生") < page.locator("#main").inner_text().find("开始幼儿对话")
    assert page.locator("#main").inner_text().find("开始幼儿对话") < page.locator("#main").inner_text().find("待审阅")
    assert page.locator("#main").inner_text().find("待审阅") < page.locator("#main").inner_text().find("分析中")
    assert page.locator("#main").inner_text().find("分析中") < page.locator("#main").inner_text().find("分析失败")
    assert page.locator("#main").inner_text().find("分析失败") < page.locator("#main").inner_text().find("辅助指标")
    assert page.get_by_text("本周指标暂不可用", exact=True).count() == 1
    assert page.get_by_text("正在加载今日排班…", exact=True).count() == 1
    action = page.get_by_role("link", name="开始幼儿对话", exact=True)
    assert action.get_attribute("href") == "/index.html"
    assert action.get_attribute("target") == "_blank"
    assert "noopener" in (action.get_attribute("rel") or "").split()
    assert held
    assert application_request_paths(requests, teacher_browser.server.base_url).index(TODAY_REQUESTS[0]) < application_request_paths(requests, teacher_browser.server.base_url).index(TODAY_REQUESTS[1])
    paths = application_request_paths(requests, teacher_browser.server.base_url)
    business = [path for path in paths if path in TODAY_REQUESTS]
    assert business[:4] == TODAY_REQUESTS
    assert "/api/analysis/overview" not in paths

    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
    assert action.bounding_box()["width"] >= 44
    assert action.bounding_box()["height"] >= 44
    heading.focus()
    page.keyboard.press("Tab")
    assert action.evaluate("node => document.activeElement === node")
    outline = action.evaluate("node => getComputedStyle(node).outlineStyle")
    assert outline != "none"


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
@pytest.mark.parametrize("fragment", ["", "#unknown?child_id=7"], ids=["empty", "unknown"])
def test_teacher_today_canonicalizes_empty_and_unknown_hash_after_authentication(teacher_browser, viewport, fragment):
    _context, page = open_teacher(teacher_browser, viewport, fragment)
    page.get_by_label("设置教师 PIN", exact=True).wait_for()
    assert urlsplit(page.url).fragment == fragment.removeprefix("#")
    setup_teacher(page)
    assert urlsplit(page.url).fragment == "today"
    assert page.locator("#nav button.active").inner_text() == "今日任务"


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_teacher_today_shows_all_panel_loading_states_before_any_response(teacher_browser, viewport):
    _context, page = open_teacher(teacher_browser, viewport)
    held = []
    install_panel_routes(page, teacher_browser, {
        key: (lambda route, key=key: held.append((key, route))) for key in PANEL_PATHS
    })
    setup_teacher(page)
    for key, copy in LOADING_COPY.items():
        assert panel(page, key).get_by_text(copy, exact=True).count() == 1
        assert panel(page, key).get_attribute("aria-busy") == "true"
    assert [key for key, _route in held] == ["roster", "pending", "processing", "failed"]


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
@pytest.mark.parametrize("key", list(PANEL_PATHS))
def test_teacher_today_each_panel_has_its_fixed_empty_state(teacher_browser, viewport, key):
    _context, page = open_teacher(teacher_browser, viewport)
    install_panel_routes(page, teacher_browser, empty_handlers())
    setup_teacher(page)
    target = panel(page, key)
    target.get_by_text(EMPTY_COPY[key], exact=True).wait_for()
    assert target.get_attribute("aria-busy") is None
    if key == "roster":
        roster_link = target.get_by_role("link", name="前往值日排班", exact=True)
        assert roster_link.get_attribute("href") == "#roster"


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
@pytest.mark.parametrize("key", list(PANEL_PATHS))
@pytest.mark.parametrize("failure", ["http-500", "non-json", "malformed-json"])
def test_teacher_today_panel_failures_are_safe_and_retry_only_that_panel(teacher_browser, viewport, key, failure):
    _context, page = open_teacher(teacher_browser, viewport)
    calls = {name: 0 for name in PANEL_PATHS}

    def target(route):
        calls[key] += 1
        if calls[key] > 1:
            fulfill_json(route, [])
            return
        if failure == "http-500":
            route.fulfill(status=500, content_type="application/json", body='{"error":{"message":"raw-panel-detail"}}')
        elif failure == "non-json":
            route.fulfill(status=200, content_type="text/plain", body="raw-panel-detail")
        else:
            fulfill_json(route, {"not": "an array"})

    handlers = empty_handlers()
    handlers[key] = target
    for name in PANEL_PATHS:
        if name == key:
            continue
        original = handlers[name]

        def counted(route, name=name, original=original):
            calls[name] += 1
            original(route)

        handlers[name] = counted
    install_panel_routes(page, teacher_browser, handlers)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    setup_teacher(page)
    target_panel = panel(page, key)
    target_panel.get_by_text("加载失败，请重试。", exact=True).wait_for()
    assert "raw-panel-detail" not in page.locator("body").inner_text()
    target_panel.get_by_role("button", name=RELOAD_COPY[key], exact=True).click()
    target_panel.get_by_text(EMPTY_COPY[key], exact=True).wait_for()
    assert calls[key] == 2
    assert all(calls[name] == 1 for name in PANEL_PATHS if name != key)
    assert errors == []


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_teacher_today_keeps_successful_siblings_when_one_panel_fails(teacher_browser, viewport):
    _context, page = open_teacher(teacher_browser, viewport)
    handlers = empty_handlers()
    handlers["roster"] = lambda route: fulfill_json(route, [ROSTER_ROW])
    handlers["pending"] = lambda route: fulfill_json(route, [queue_row("pending")])
    handlers["processing"] = lambda route: route.fulfill(status=500, content_type="application/json", body="raw-processing")
    install_panel_routes(page, teacher_browser, handlers)
    setup_teacher(page)
    panel(page, "roster").get_by_text("雨雨", exact=True).wait_for()
    panel(page, "pending").get_by_text("会话 #42", exact=True).wait_for()
    panel(page, "processing").get_by_text("加载失败，请重试。", exact=True).wait_for()
    panel(page, "failed").get_by_text("暂无分析失败会话", exact=True).wait_for()
    assert "raw-processing" not in page.locator("body").inner_text()


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
@pytest.mark.parametrize("key,bad_review", [("processing", "draft"), ("failed", "pending")])
def test_teacher_today_queue_combination_failure_stays_scoped(teacher_browser, viewport, key, bad_review):
    _context, page = open_teacher(teacher_browser, viewport)
    handlers = empty_handlers()
    handlers["roster"] = lambda route: fulfill_json(route, [ROSTER_ROW])
    malformed = queue_row(key)
    malformed["review_status"] = bad_review
    handlers[key] = lambda route: fulfill_json(route, [malformed])
    install_panel_routes(page, teacher_browser, handlers)
    setup_teacher(page)
    panel(page, key).get_by_text("加载失败，请重试。", exact=True).wait_for()
    panel(page, "roster").get_by_text("雨雨", exact=True).wait_for()
    for sibling in set(PANEL_PATHS) - {key, "roster"}:
        panel(page, sibling).get_by_text(EMPTY_COPY[sibling], exact=True).wait_for()


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_teacher_today_data_links_and_retry_controls_are_touch_sized_without_overflow(teacher_browser, viewport):
    _context, page = open_teacher(teacher_browser, viewport)
    handlers = empty_handlers()
    handlers["roster"] = lambda route: fulfill_json(route, [ROSTER_ROW])
    handlers["pending"] = lambda route: fulfill_json(route, [queue_row("pending")])
    handlers["processing"] = lambda route: route.fulfill(status=500, content_type="application/json", body="raw-processing")
    handlers["failed"] = lambda route: fulfill_json(route, [queue_row("failed")])
    install_panel_routes(page, teacher_browser, handlers)
    setup_teacher(page)
    panel(page, "failed").get_by_role("button", name="重试分析：雨雨", exact=True).wait_for()
    targets = [
        panel(page, "roster").get_by_role("link", name="雨雨", exact=True),
        panel(page, "pending").get_by_role("link", name="审阅雨雨的会话 #42", exact=True),
        panel(page, "processing").get_by_role("button", name="重新加载分析中", exact=True),
        panel(page, "failed").get_by_role("button", name="重试分析：雨雨", exact=True),
    ]
    for target in targets:
        box = target.bounding_box()
        assert box["width"] >= 44
        assert box["height"] >= 44
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
@pytest.mark.parametrize(
    "retry_body",
    [
        {"conversation_id": 42, "analysis_job_id": 19, "analysis_status": "pending", "attempt_count": 0, "retry_accepted": True, "replayed": False},
        {"conversation_id": 42, "analysis_job_id": 19, "analysis_status": "pending", "attempt_count": 2, "retry_accepted": False, "replayed": True},
    ],
    ids=["accepted", "replayed"],
)
def test_teacher_today_analysis_retry_is_single_flight_and_refreshes_three_queues_in_order(teacher_browser, viewport, retry_body):
    _context, page = open_teacher(teacher_browser, viewport)
    requests = []
    page.on("request", lambda request: requests.append(request))
    failed_reads = 0

    def failed(route):
        nonlocal failed_reads
        failed_reads += 1
        fulfill_json(route, [queue_row("failed")] if failed_reads == 1 else [])

    handlers = empty_handlers()
    handlers["failed"] = failed
    install_panel_routes(page, teacher_browser, handlers)
    posts = []

    def hold_retry(route):
        assert is_exact_fixture_url(route.request.url, teacher_browser.server.port)
        posts.append(route)

    page.route(f"{teacher_browser.server.base_url}/api/conversations/42/analysis/retry", hold_retry)
    setup_teacher(page)
    button = panel(page, "failed").get_by_role("button", name="重试分析：雨雨", exact=True)
    button.wait_for()
    button.dblclick()
    assert button.is_disabled()
    page.keyboard.press("Enter")
    assert len(posts) == 1
    fulfill_json(posts[0], retry_body)
    panel(page, "failed").get_by_text("暂无分析失败会话", exact=True).wait_for()
    paths = application_request_paths(requests, teacher_browser.server.base_url)
    queue_reads = [path for path in paths if path in PANEL_PATHS.values()]
    assert queue_reads[-3:] == [
        "/api/conversations?queue=failed",
        "/api/conversations?queue=processing",
        "/api/conversations?queue=pending",
    ]
    assert failed_reads == 2


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
@pytest.mark.parametrize("failure", ["mismatch", "malformed", "401", "404", "409", "500", "non-json", "offline"])
def test_teacher_today_analysis_retry_failures_restore_only_the_row_action_with_safe_copy(teacher_browser, viewport, failure):
    _context, page = open_teacher(teacher_browser, viewport)
    handlers = empty_handlers()
    handlers["failed"] = lambda route: fulfill_json(route, [queue_row("failed")])
    install_panel_routes(page, teacher_browser, handlers)

    def fail_retry(route):
        assert is_exact_fixture_url(route.request.url, teacher_browser.server.port)
        if failure == "mismatch":
            fulfill_json(route, {"conversation_id": 7, "analysis_job_id": 19, "analysis_status": "pending", "attempt_count": 0, "retry_accepted": True, "replayed": False})
        elif failure == "malformed":
            fulfill_json(route, {"conversation_id": 42})
        elif failure == "non-json":
            route.fulfill(status=200, content_type="text/plain", body="raw-retry-detail")
        elif failure == "offline":
            route.abort("failed")
        else:
            route.fulfill(status=int(failure), content_type="application/json", body='{"error":{"message":"raw-retry-detail"}}')

    page.route(f"{teacher_browser.server.base_url}/api/conversations/42/analysis/retry", fail_retry)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    setup_teacher(page)
    failed_panel = panel(page, "failed")
    button = failed_panel.get_by_role("button", name="重试分析：雨雨", exact=True)
    button.click()
    assert button.is_disabled()
    feedback = failed_panel.locator(".today-retry-feedback")
    feedback.get_by_text("暂时无法重试分析，请稍后再试。", exact=True).wait_for()
    assert button.is_enabled()
    assert failed_panel.get_by_text("会话 #42", exact=True).count() == 1
    assert "raw-retry-detail" not in page.locator("body").inner_text()
    assert errors == []


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_teacher_today_held_retry_cannot_mutate_after_navigation(teacher_browser, viewport):
    _context, page = open_teacher(teacher_browser, viewport)
    handlers = empty_handlers()
    handlers["failed"] = lambda route: fulfill_json(route, [queue_row("failed")])
    install_panel_routes(page, teacher_browser, handlers)
    posts = []
    failed_requests = []
    page.on("requestfailed", lambda request: failed_requests.append(request.url))

    def hold_retry(route):
        assert is_exact_fixture_url(route.request.url, teacher_browser.server.port)
        posts.append(route)

    page.route(f"{teacher_browser.server.base_url}/api/conversations/42/analysis/retry", hold_retry)
    setup_teacher(page)
    panel(page, "failed").get_by_role("button", name="重试分析：雨雨", exact=True).click()
    assert len(posts) == 1
    page.get_by_role("button", name="幼儿管理", exact=True).click()
    page.get_by_role("heading", name="幼儿管理", exact=True).wait_for()
    page.wait_for_timeout(100)
    assert f"{teacher_browser.server.base_url}/api/conversations/42/analysis/retry" in failed_requests
    assert "暂时无法重试分析，请稍后再试。" not in page.locator("#main").inner_text()
