from __future__ import annotations

from time import monotonic
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import expect

from tests.browser.conftest import is_exact_fixture_url


VIEWPORTS = [{"width": 1024, "height": 768}, {"width": 1440, "height": 900}]
VIEWPORT_IDS = ["1024x768", "1440x900"]
PIN = "2468"
TODAY_REQUESTS = [
    "/api/roster/today",
    "/api/conversations?queue=pending",
    "/api/conversations?queue=processing",
    "/api/conversations?queue=failed",
    "/api/reports/weekly",
    "/api/runtime/context",
]
METRICS_PATH = "/api/reports/weekly"
RUNTIME_PATH = "/api/runtime/context"
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


def weekly_response(**overrides) -> dict:
    body = {
        "timezone": "Asia/Shanghai",
        "week_start": "2026-08-31",
        "week_end_exclusive": "2026-09-07",
        "completed_conversations": 5,
        "participating_children": 3,
        "confirmed_reviews": 2,
        "failed_analyses": 1,
        "pending_reviews_total": 4,
    }
    body.update(overrides)
    return body


def runtime_response(**overrides) -> dict:
    body = {
        "timezone": "Asia/Shanghai",
        "business_date": "2026-09-02",
        "week_start": "2026-08-31",
        "week_end_exclusive": "2026-09-07",
    }
    body.update(overrides)
    return body


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
    page.get_by_label("再次输入教师 PIN", exact=True).fill(PIN)
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


def install_panel_routes(
    page,
    teacher_browser,
    handlers,
    metrics_handler=None,
    runtime_handler=None,
) -> None:
    for key, path in PANEL_PATHS.items():
        def make_handler(panel_key):
            def handler(route):
                assert is_exact_fixture_url(route.request.url, teacher_browser.server.port)
                handlers[panel_key](route)
            return handler
        page.route(f"{teacher_browser.server.base_url}{path}", make_handler(key))

    def weekly(route):
        assert is_exact_fixture_url(route.request.url, teacher_browser.server.port)
        if metrics_handler is None:
            fulfill_json(route, weekly_response())
        else:
            metrics_handler(route)

    page.route(f"{teacher_browser.server.base_url}{METRICS_PATH}", weekly)

    def runtime(route):
        assert is_exact_fixture_url(route.request.url, teacher_browser.server.port)
        if runtime_handler is None:
            fulfill_json(route, runtime_response())
        else:
            runtime_handler(route)

    page.route(f"{teacher_browser.server.base_url}{RUNTIME_PATH}", runtime)


def fulfill_json(route, body, status: int = 200) -> None:
    route.fulfill(status=status, content_type="application/json", body=__import__("json").dumps(body))


def empty_handlers():
    return {key: lambda route: fulfill_json(route, []) for key in PANEL_PATHS}


def wait_for_condition(page, condition, description: str, timeout_ms: int = 5_000):
    deadline = monotonic() + timeout_ms / 1_000
    while True:
        result = condition()
        if result:
            return result
        if page.is_closed():
            raise AssertionError(f"page closed while waiting for {description}")
        if monotonic() >= deadline:
            raise AssertionError(f"timed out waiting for {description}")
        page.wait_for_timeout(10)  # Event-pump poll interval, not a fixed-state delay.


def cleanup_held_retry_routes(
    page,
    *,
    retry_url,
    handler,
    held_routes,
    request_started,
    listeners,
):
    cleanup_error = None
    if request_started() and not held_routes and not page.is_closed():
        try:
            wait_for_condition(
                page,
                lambda: held_routes[0] if held_routes else None,
                "late retry route capture during cleanup",
            )
        except AssertionError as error:
            cleanup_error = error
    for held_route in tuple(held_routes):
        try:
            held_route.abort("failed")
        except PlaywrightError:
            pass
    try:
        page.unroute(retry_url, handler)
    finally:
        for event, listener in listeners:
            page.remove_listener(event, listener)
    if cleanup_error is not None:
        raise cleanup_error


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
    page.route(
        f"{teacher_browser.server.base_url}{METRICS_PATH}",
        lambda route: fulfill_json(route, weekly_response()),
    )
    page.route(
        f"{teacher_browser.server.base_url}{RUNTIME_PATH}",
        lambda route: fulfill_json(route, runtime_response()),
    )
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
    assert page.locator("#main").inner_text().find("分析失败") < page.locator("#main").inner_text().find("本周概览")
    assert page.get_by_text("本周指标暂不可用", exact=True).count() == 0
    assert page.get_by_text("正在加载今日排班…", exact=True).count() == 1
    action = page.get_by_role("link", name="开始幼儿对话", exact=True)
    assert action.get_attribute("href") == "/index.html"
    assert action.get_attribute("target") == "_blank"
    assert "noopener" in (action.get_attribute("rel") or "").split()
    assert held
    assert application_request_paths(requests, teacher_browser.server.base_url).index(TODAY_REQUESTS[0]) < application_request_paths(requests, teacher_browser.server.base_url).index(TODAY_REQUESTS[1])
    paths = application_request_paths(requests, teacher_browser.server.base_url)
    business = [path for path in paths if path in TODAY_REQUESTS]
    assert business[:6] == TODAY_REQUESTS
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
    }, metrics_handler=lambda route: held.append(("metrics", route)),
        runtime_handler=lambda route: held.append(("runtime", route)))
    setup_teacher(page)
    for key, copy in LOADING_COPY.items():
        assert panel(page, key).get_by_text(copy, exact=True).count() == 1
        assert panel(page, key).get_attribute("aria-busy") == "true"
    metrics = page.locator('[data-today-metrics="weekly"]')
    assert metrics.get_by_text("正在加载本周指标…", exact=True).count() == 1
    assert metrics.get_attribute("aria-busy") == "true"
    assert [key for key, _route in held] == [
        "roster", "pending", "processing", "failed", "metrics", "runtime",
    ]


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_teacher_today_uses_the_approved_hero_and_two_column_panel_grid(
    teacher_browser, viewport
):
    _context, page = open_teacher(teacher_browser, viewport)
    install_panel_routes(page, teacher_browser, empty_handlers())
    setup_teacher(page)
    panel(page, "failed").get_by_text("暂无分析失败会话", exact=True).wait_for()

    topbar = page.locator(".teacher-topbar")
    assert topbar.count() == 1
    assert topbar.get_by_text("今日任务", exact=True).count() == 1
    assert topbar.get_by_role("button", name="立即锁定", exact=True).count() == 1

    hero = page.locator(".today-hero")
    grid = page.locator(".today-panel-grid")
    assert hero.count() == 1
    assert hero.get_by_text("今天的工作，一眼看清", exact=True).count() == 1
    assert grid.count() == 1
    assert grid.locator(":scope > [data-today-panel]").count() == 4
    assert grid.evaluate(
        "node => getComputedStyle(node).gridTemplateColumns.split(' ').length === 2"
    )

    tones = {
        "roster": "success",
        "pending": "warning",
        "processing": "info",
        "failed": "danger",
    }
    for key, tone in tones.items():
        target = panel(page, key)
        assert target.get_attribute("data-tone") == tone
        assert target.locator(".today-status-badge").count() == 1

    hero_box = hero.bounding_box()
    grid_box = grid.bounding_box()
    metrics_box = page.locator(".today-metrics-strip").bounding_box()
    assert hero_box is not None and grid_box is not None and metrics_box is not None
    assert hero_box["y"] + hero_box["height"] <= grid_box["y"]
    assert grid_box["width"] >= hero_box["width"] * 0.95
    assert grid_box["y"] + grid_box["height"] <= metrics_box["y"]
    assert metrics_box["height"] >= 120
    assert page.locator(".today-metrics-grid > [data-metric]").count() == 5
    assert page.get_by_text("本周指标暂不可用", exact=True).count() == 0
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_teacher_today_renders_exact_week_range_and_five_weekly_metrics(
    teacher_browser, viewport
):
    _context, page = open_teacher(teacher_browser, viewport)
    runtime_calls = []

    def runtime_handler(route):
        runtime_calls.append(route.request.url)
        fulfill_json(route, runtime_response(timezone="Factory"))

    install_panel_routes(
        page,
        teacher_browser,
        empty_handlers(),
        metrics_handler=lambda route: fulfill_json(
            route,
            weekly_response(timezone="Factory"),
        ),
        runtime_handler=runtime_handler,
    )
    setup_teacher(page)
    metrics = page.locator('[data-today-metrics="weekly"]')
    metrics.get_by_text("周指标已更新", exact=True).wait_for()

    assert metrics.get_attribute("data-state") == "loaded"
    assert metrics.get_attribute("aria-busy") is None
    assert metrics.get_by_text("2026年8月31日–9月6日", exact=True).count() == 1
    expected = {
        "completed": ("本周完成对话", "5"),
        "children": ("参与幼儿", "3"),
        "confirmed": ("已确认审阅", "2"),
        "failed": ("分析失败", "1"),
        "pending": ("当前待审阅", "4"),
    }
    for key, (label, value) in expected.items():
        card = metrics.locator(f'[data-metric="{key}"]')
        assert card.get_by_text(label, exact=True).count() == 1
        assert card.get_by_text(value, exact=True).count() == 1
    assert page.get_by_text("本周指标暂不可用", exact=True).count() == 0
    assert runtime_calls == [f"{teacher_browser.server.base_url}{RUNTIME_PATH}"]


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_teacher_today_weekly_metrics_have_an_explicit_all_zero_state(
    teacher_browser, viewport
):
    _context, page = open_teacher(teacher_browser, viewport)
    install_panel_routes(
        page,
        teacher_browser,
        empty_handlers(),
        metrics_handler=lambda route: fulfill_json(
            route,
            weekly_response(
                completed_conversations=0,
                participating_children=0,
                confirmed_reviews=0,
                failed_analyses=0,
                pending_reviews_total=0,
            ),
        ),
    )
    setup_teacher(page)
    metrics = page.locator('[data-today-metrics="weekly"]')
    metrics.get_by_text(
        "本周暂无完成数据，当前也没有待审阅。", exact=True
    ).wait_for()
    assert metrics.locator(".today-metric-value").all_inner_texts() == ["0"] * 5


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_teacher_today_weekly_failure_retry_is_scoped_and_touch_sized(
    teacher_browser, viewport
):
    _context, page = open_teacher(teacher_browser, viewport)
    calls = {key: 0 for key in PANEL_PATHS}
    calls["metrics"] = 0
    calls["runtime"] = 0

    def panel_handler(key):
        def handler(route):
            calls[key] += 1
            fulfill_json(route, [])

        return handler

    def metrics_handler(route):
        calls["metrics"] += 1
        if calls["metrics"] == 1:
            route.fulfill(
                status=500,
                content_type="application/json",
                body='{"error":{"message":"raw-weekly-detail"}}',
            )
        else:
            fulfill_json(route, weekly_response())

    def runtime_handler(route):
        calls["runtime"] += 1
        fulfill_json(route, runtime_response())

    install_panel_routes(
        page,
        teacher_browser,
        {key: panel_handler(key) for key in PANEL_PATHS},
        metrics_handler=metrics_handler,
        runtime_handler=runtime_handler,
    )
    setup_teacher(page)
    metrics = page.locator('[data-today-metrics="weekly"]')
    metrics.get_by_text("本周指标加载失败，请重试。", exact=True).wait_for()
    assert all(panel(page, key).get_attribute("data-state") == "empty" for key in PANEL_PATHS)
    retry = metrics.get_by_role("button", name="重新加载本周指标", exact=True)
    box = retry.bounding_box()
    assert box["width"] >= 44 and box["height"] >= 44
    retry.click()
    metrics.get_by_text("周指标已更新", exact=True).wait_for()
    assert calls == {
        "roster": 1,
        "pending": 1,
        "processing": 1,
        "failed": 1,
        "metrics": 2,
        "runtime": 2,
    }
    assert "raw-weekly-detail" not in page.locator("body").inner_text()
    assert all(panel(page, key).get_attribute("data-state") == "empty" for key in PANEL_PATHS)


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
    assert target_panel.get_attribute("data-state") == "error"
    assert target_panel.locator(".today-status-badge").evaluate(
        "node => getComputedStyle(node).backgroundColor"
    ) == "rgb(248, 226, 222)"
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
def test_teacher_today_renders_pending_processing_and_failed_rows_with_retry_boundaries(
    teacher_browser, viewport
):
    _context, page = open_teacher(teacher_browser, viewport)
    requests = []

    def record_request(request):
        requests.append(request)

    page.on("request", record_request)

    def distinct_row(queue, conversation_id, child, completed_at):
        row = queue_row(queue)
        row.update({
            "id": conversation_id,
            "child": child,
            "completed_at": completed_at,
        })
        return row

    pending_row = distinct_row(
        "pending",
        42,
        {"id": 7, "name": "小雨", "nickname": "雨雨", "avatar": "rain.png"},
        "2026-08-23T08:59:00Z",
    )
    processing_row = distinct_row(
        "processing",
        43,
        {"id": 8, "name": "小云", "nickname": "云云", "avatar": "cloud.png"},
        "2026-08-23T09:05:00Z",
    )
    failed_row = distinct_row(
        "failed",
        44,
        {"id": 9, "name": "小星", "nickname": "星星", "avatar": "star.png"},
        "2026-08-23T09:11:00Z",
    )
    retried_processing_row = dict(failed_row)
    retried_processing_row["analysis_status"] = "pending"

    reads = {key: 0 for key in PANEL_PATHS}

    def roster(route):
        reads["roster"] += 1
        fulfill_json(route, [ROSTER_ROW])

    def pending(route):
        reads["pending"] += 1
        fulfill_json(route, [pending_row])

    def processing(route):
        reads["processing"] += 1
        rows = [processing_row]
        if reads["processing"] > 1:
            rows.append(retried_processing_row)
        fulfill_json(route, rows)

    def failed(route):
        reads["failed"] += 1
        fulfill_json(route, [failed_row] if reads["failed"] == 1 else [])

    install_panel_routes(page, teacher_browser, {
        "roster": roster,
        "pending": pending,
        "processing": processing,
        "failed": failed,
    })
    retry_posts = []
    retry_url = f"{teacher_browser.server.base_url}/api/conversations/44/analysis/retry"
    handler_closing = False

    def hold_retry(route):
        nonlocal handler_closing
        assert is_exact_fixture_url(route.request.url, teacher_browser.server.port)
        retry_posts.append(route)
        if handler_closing:
            try:
                route.abort("failed")
            except PlaywrightError:
                pass

    page.route(retry_url, hold_retry)
    try:
        setup_teacher(page)

        expected = {
            "pending": ("雨雨", "16:59", 42, "待审阅"),
            "processing": ("云云", "17:05", 43, "分析中"),
            "failed": ("星星", "17:11", 44, "分析失败"),
        }
        for key, (name, completed_time, conversation_id, status) in expected.items():
            target = panel(page, key)
            target.get_by_text(name, exact=True).wait_for()
            details = " ".join(
                target.locator(".today-row-details").inner_text().split()
            )
            assert details == (
                f"完成于 {completed_time} · 会话 #{conversation_id} · 2 轮 · {status}"
            )
            for other_name in {"雨雨", "云云", "星星"} - {name}:
                assert target.get_by_text(other_name, exact=True).count() == 0

        assert panel(page, "pending").locator(".today-analysis-retry").count() == 0
        assert panel(page, "processing").locator(".today-analysis-retry").count() == 0
        retry = panel(page, "failed").get_by_role(
            "button", name="重试分析：星星", exact=True
        )
        assert retry.count() == 1
        assert page.locator(".today-analysis-retry").count() == 1

        retry.dblclick()
        held_retry = wait_for_condition(
            page,
            lambda: retry_posts[0] if retry_posts else None,
            "retry route capture before row-boundary pending assertions",
        )
        assert retry.is_disabled()
        page.keyboard.press("Enter")
        assert len(retry_posts) == 1
        fulfill_json(held_retry, {
            "conversation_id": 44,
            "analysis_job_id": 29,
            "analysis_status": "pending",
            "attempt_count": 0,
            "retry_accepted": True,
            "replayed": False,
        })

        panel(page, "failed").get_by_text("暂无分析失败会话", exact=True).wait_for()
        moved = panel(page, "processing")
        moved.get_by_text("星星", exact=True).wait_for()
        moved_row = moved.locator(".today-queue-row").filter(has_text="星星")
        assert moved_row.count() == 1
        assert " ".join(moved_row.locator(".today-row-details").inner_text().split()) == (
            "完成于 17:11 · 会话 #44 · 2 轮 · 分析中"
        )
        assert moved.get_by_text("云云", exact=True).count() == 1
        assert panel(page, "pending").get_by_text("雨雨", exact=True).count() == 1
        assert page.locator(".today-analysis-retry").count() == 0
        assert len(retry_posts) == 1
        assert reads == {"roster": 1, "pending": 2, "processing": 2, "failed": 2}

        paths = application_request_paths(requests, teacher_browser.server.base_url)
        queue_reads = [path for path in paths if path in PANEL_PATHS.values()]
        assert queue_reads[-3:] == [
            "/api/conversations?queue=failed",
            "/api/conversations?queue=processing",
            "/api/conversations?queue=pending",
        ]
    finally:
        handler_closing = True
        cleanup_held_retry_routes(
            page,
            retry_url=retry_url,
            handler=hold_retry,
            held_routes=retry_posts,
            request_started=lambda: any(
                request.url == retry_url and request.method == "POST"
                for request in requests
            ),
            listeners=(("request", record_request),),
        )


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

    def record_request(request):
        requests.append(request)

    page.on("request", record_request)
    failed_reads = 0

    def failed(route):
        nonlocal failed_reads
        failed_reads += 1
        fulfill_json(route, [queue_row("failed")] if failed_reads == 1 else [])

    handlers = empty_handlers()
    handlers["failed"] = failed
    install_panel_routes(page, teacher_browser, handlers)
    posts = []
    retry_url = f"{teacher_browser.server.base_url}/api/conversations/42/analysis/retry"
    handler_closing = False

    def hold_retry(route):
        nonlocal handler_closing
        assert is_exact_fixture_url(route.request.url, teacher_browser.server.port)
        posts.append(route)
        if handler_closing:
            try:
                route.abort("failed")
            except PlaywrightError:
                pass

    page.route(retry_url, hold_retry)
    try:
        setup_teacher(page)
        button = panel(page, "failed").get_by_role("button", name="重试分析：雨雨", exact=True)
        button.wait_for()
        button.dblclick()
        held_post = wait_for_condition(
            page,
            lambda: posts[0] if posts else None,
            "retry route capture before success pending assertions",
        )
        assert button.is_disabled()
        page.keyboard.press("Enter")
        assert len(posts) == 1
        fulfill_json(held_post, retry_body)
        panel(page, "failed").get_by_text("暂无分析失败会话", exact=True).wait_for()
        paths = application_request_paths(requests, teacher_browser.server.base_url)
        queue_reads = [path for path in paths if path in PANEL_PATHS.values()]
        assert queue_reads[-3:] == [
            "/api/conversations?queue=failed",
            "/api/conversations?queue=processing",
            "/api/conversations?queue=pending",
        ]
        assert failed_reads == 2
    finally:
        handler_closing = True
        cleanup_held_retry_routes(
            page,
            retry_url=retry_url,
            handler=hold_retry,
            held_routes=posts,
            request_started=lambda: any(
                request.url == retry_url and request.method == "POST"
                for request in requests
            ),
            listeners=(("request", record_request),),
        )


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
@pytest.mark.parametrize("failure", ["mismatch", "malformed", "401", "404", "409", "500", "non-json"])
def test_teacher_today_analysis_retry_failures_restore_only_the_row_action_with_safe_copy(teacher_browser, viewport, failure):
    _context, page = open_teacher(teacher_browser, viewport)
    requests = []
    page.on("request", lambda request: requests.append(request))
    reads = {key: 0 for key in PANEL_PATHS}

    def panel_handler(key):
        def handler(route):
            reads[key] += 1
            fulfill_json(route, [queue_row("failed")] if key == "failed" else [])

        return handler

    handlers = {key: panel_handler(key) for key in PANEL_PATHS}
    install_panel_routes(page, teacher_browser, handlers)
    retry_posts = []
    retry_path = "/api/conversations/42/analysis/retry"

    def fail_retry(route):
        assert is_exact_fixture_url(route.request.url, teacher_browser.server.port)
        retry_posts.append(route.request.url)
        if failure == "mismatch":
            fulfill_json(route, {"conversation_id": 7, "analysis_job_id": 19, "analysis_status": "pending", "attempt_count": 0, "retry_accepted": True, "replayed": False})
        elif failure == "malformed":
            fulfill_json(route, {"conversation_id": 42})
        elif failure == "non-json":
            route.fulfill(status=200, content_type="text/plain", body="raw-retry-detail")
        else:
            route.fulfill(status=int(failure), content_type="application/json", body='{"error":{"message":"raw-retry-detail"}}')

    page.route(f"{teacher_browser.server.base_url}{retry_path}", fail_retry)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    setup_teacher(page)
    failed_panel = panel(page, "failed")
    button = failed_panel.get_by_role("button", name="重试分析：雨雨", exact=True)
    button.click()
    feedback = failed_panel.locator(".today-retry-feedback")
    feedback.get_by_text("暂时无法重试分析，请稍后再试。", exact=True).wait_for()
    assert button.is_enabled()
    assert failed_panel.get_by_text("会话 #42", exact=True).count() == 1
    assert failed_panel.get_by_text("雨雨", exact=True).count() == 1
    assert failed_panel.get_by_text(EMPTY_COPY["failed"], exact=True).count() == 0
    assert failed_panel.locator(".today-queue-row").count() == 1
    assert failed_panel.locator(".today-analysis-retry").count() == 1
    assert page.locator(".today-analysis-retry").count() == 1
    assert panel(page, "roster").get_by_text(EMPTY_COPY["roster"], exact=True).count() == 1
    assert panel(page, "roster").get_by_role("link", name="前往值日排班", exact=True).count() == 1
    assert panel(page, "pending").get_by_text(EMPTY_COPY["pending"], exact=True).count() == 1
    assert panel(page, "processing").get_by_text(EMPTY_COPY["processing"], exact=True).count() == 1
    assert panel(page, "pending").get_by_text("雨雨", exact=True).count() == 0
    assert panel(page, "processing").get_by_text("雨雨", exact=True).count() == 0
    assert page.get_by_role("link", name="开始幼儿对话", exact=True).count() == 1

    application_paths = application_request_paths(requests, teacher_browser.server.base_url)
    assert [path for path in application_paths if path in TODAY_REQUESTS] == TODAY_REQUESTS
    retry_requests = [
        request
        for request in requests
        if request.url == f"{teacher_browser.server.base_url}{retry_path}"
    ]
    assert len(retry_requests) == 1
    assert retry_requests[0].method == "POST"
    assert retry_posts == [f"{teacher_browser.server.base_url}{retry_path}"]
    assert reads == {"roster": 1, "pending": 1, "processing": 1, "failed": 1}
    assert "raw-retry-detail" not in page.locator("body").inner_text()
    assert errors == []


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_teacher_today_analysis_retry_offline_is_single_flight_until_transport_rejects(
    teacher_browser, viewport
):
    _context, page = open_teacher(teacher_browser, viewport)
    handlers = empty_handlers()
    handlers["failed"] = lambda route: fulfill_json(route, [queue_row("failed")])
    install_panel_routes(page, teacher_browser, handlers)
    held_routes = []
    retry_requests = []
    event_order = []
    handler_closing = False

    retry_url = f"{teacher_browser.server.base_url}/api/conversations/42/analysis/retry"

    def record_retry_request(request):
        if request.url == retry_url and request.method == "POST":
            retry_requests.append(request)
            event_order.append("request")

    def hold_retry(route):
        nonlocal handler_closing
        assert is_exact_fixture_url(route.request.url, teacher_browser.server.port)
        held_routes.append(route)
        event_order.append("route")
        if handler_closing:
            try:
                route.abort("failed")
            except PlaywrightError:
                pass

    page.on("request", record_retry_request)
    page.route(retry_url, hold_retry)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    setup_teacher(page)
    failed_panel = panel(page, "failed")
    button = failed_panel.get_by_role("button", name="重试分析：雨雨", exact=True)
    try:
        button.dblclick()
        held_route = wait_for_condition(
            page,
            lambda: held_routes[0] if held_routes else None,
            "retry route capture",
        )
        assert len(retry_requests) == 1
        assert len(held_routes) == 1
        assert event_order == ["request", "route"]
        expect(button).to_be_disabled()
        page.keyboard.press("Enter")
        assert len(held_routes) == 1

        held_route.abort("failed")
        feedback = failed_panel.locator(".today-retry-feedback")
        feedback.get_by_text("暂时无法重试分析，请稍后再试。", exact=True).wait_for()
        expect(button).to_be_enabled()
        assert len(held_routes) == 1
        assert failed_panel.get_by_text("会话 #42", exact=True).count() == 1
        assert failed_panel.get_by_text("暂无分析失败会话", exact=True).count() == 0
        assert failed_panel.locator(".today-analysis-retry").count() == 1
        assert panel(page, "pending").get_by_text("暂无待审阅会话", exact=True).count() == 1
        assert panel(page, "processing").get_by_text("暂无分析中的会话", exact=True).count() == 1
        assert "raw-retry-detail" not in page.locator("body").inner_text()
        assert errors == []
    finally:
        handler_closing = True
        cleanup_error = None
        if retry_requests and not held_routes and not page.is_closed():
            try:
                wait_for_condition(
                    page,
                    lambda: held_routes[0] if held_routes else None,
                    "late retry route capture during cleanup",
                )
            except AssertionError as error:
                cleanup_error = error
        for held_route in tuple(held_routes):
            try:
                held_route.abort("failed")
            except PlaywrightError:
                pass
        try:
            page.unroute(retry_url, hold_retry)
        finally:
            page.remove_listener("request", record_retry_request)
        if cleanup_error is not None:
            raise cleanup_error


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_teacher_today_held_retry_cannot_mutate_after_navigation(teacher_browser, viewport):
    _context, page = open_teacher(teacher_browser, viewport)
    handlers = empty_handlers()
    handlers["failed"] = lambda route: fulfill_json(route, [queue_row("failed")])
    install_panel_routes(page, teacher_browser, handlers)
    posts = []
    retry_requests = []
    failed_requests = []
    retry_url = f"{teacher_browser.server.base_url}/api/conversations/42/analysis/retry"
    handler_closing = False

    def record_retry_request(request):
        if request.url == retry_url and request.method == "POST":
            retry_requests.append(request)

    def record_failed_request(request):
        failed_requests.append(request.url)

    page.on("request", record_retry_request)
    page.on("requestfailed", record_failed_request)

    def hold_retry(route):
        nonlocal handler_closing
        assert is_exact_fixture_url(route.request.url, teacher_browser.server.port)
        posts.append(route)
        if handler_closing:
            try:
                route.abort("failed")
            except PlaywrightError:
                pass

    page.route(retry_url, hold_retry)
    try:
        setup_teacher(page)
        panel(page, "failed").get_by_role(
            "button", name="重试分析：雨雨", exact=True
        ).click()
        wait_for_condition(
            page,
            lambda: posts[0] if posts else None,
            "retry route capture before navigation",
        )
        assert len(retry_requests) == 1
        assert len(posts) == 1
        page.get_by_role("button", name="幼儿管理", exact=True).click()
        page.get_by_role("heading", name="幼儿管理", exact=True).wait_for()
        wait_for_condition(
            page,
            lambda: retry_url if retry_url in failed_requests else None,
            "exact retry request failure after navigation",
        )
        assert failed_requests.count(retry_url) == 1
        assert "暂时无法重试分析，请稍后再试。" not in page.locator("#main").inner_text()
    finally:
        handler_closing = True
        cleanup_held_retry_routes(
            page,
            retry_url=retry_url,
            handler=hold_retry,
            held_routes=posts,
            request_started=lambda: bool(retry_requests),
            listeners=(
                ("request", record_retry_request),
                ("requestfailed", record_failed_request),
            ),
        )
