from __future__ import annotations

import json
from urllib.parse import urlsplit

import pytest

from tests.browser.conftest import is_exact_fixture_url


VIEWPORTS = [{"width": 1024, "height": 768}, {"width": 1440, "height": 900}]
VIEWPORT_IDS = ["1024x768", "1440x900"]
PIN = "2468"
QUEUE_PATH = "/api/conversations?queue=pending"
DETAIL_PATH = "/api/conversations/42"
CHILD = {"id": 7, "name": "小雨", "nickname": "雨雨", "avatar": "rain.png"}


def queue_row() -> dict:
    return {
        "id": 42,
        "child": CHILD,
        "date": "2026-08-23",
        "started_at": "2026-08-23T08:54:00Z",
        "completed_at": "2026-08-23T08:59:00Z",
        "message_count": 3,
        "round": 2,
        "status": "ended",
        "end_reason": "max_rounds",
        "analysis_status": "succeeded",
        "review_status": "draft",
        "revision": 2,
    }


def review_detail(overrides: dict | None = None) -> dict:
    body = {
        "id": 42,
        "child": CHILD,
        "date": "2026-08-23",
        "started_at": "2026-08-23T08:54:00Z",
        "completed_at": "2026-08-23T08:59:00Z",
        "status": "ended",
        "end_reason": "max_rounds",
        "message_count": 3,
        "round": 2,
        "last_message_id": 9,
        "revision": 2,
        "analysis": {
            "job_id": 19,
            "status": "succeeded",
            "attempt_count": 0,
            "max_attempts": 3,
            "error": None,
            "updated_at": "2026-08-23T09:01:00Z",
        },
        "review_status": "draft",
        "messages": [
            {"id": 5, "role": "child", "text": "我喂了小鸭。"},
            {"id": 7, "role": "diary", "text": "你观察得很仔细。"},
            {"id": 9, "role": "child", "text": "它很开心。"},
        ],
        "review": {
            "feeding_logs": [{"id": 11, "category": "喂食", "content": "喂了菜叶", "duck_id": 3}],
            "emotion": {"emotion": "开心", "intensity": 4, "note": None},
            "insight": "能够清楚表达照料过程。",
            "scores": [{"dimension_id": 2, "dimension_name": "表达能力", "score": 4, "reason": "能说明自己的观察。"}],
            "overall": 4.0,
        },
    }
    return {**body, **(overrides or {})}


def open_teacher(teacher_browser, viewport, fragment: str = "#review?conversation_id=42"):
    context = teacher_browser.new_context()
    page = context.new_page()
    page.set_default_timeout(5_000)
    page.set_viewport_size(viewport)
    page.goto(f"{teacher_browser.server.base_url}/teacher.html{fragment}", wait_until="domcontentloaded")
    return context, page


def unlock_review(page) -> None:
    page.get_by_label("设置教师 PIN", exact=True).fill(PIN)
    page.get_by_label("再次输入教师 PIN", exact=True).fill(PIN)
    page.get_by_role("button", name="设置并解锁", exact=True).click()
    page.get_by_role("heading", name="值日审阅", exact=True).wait_for()


def fulfill_json(route, body: object, status: int = 200) -> None:
    route.fulfill(status=status, content_type="application/json", body=json.dumps(body))


def local_paths(requests, base_url: str) -> list[str]:
    origin = urlsplit(base_url)
    paths = []
    for request in requests:
        parsed = urlsplit(request.url)
        if (parsed.scheme, parsed.netloc) == (origin.scheme, origin.netloc):
            paths.append(parsed.path + (f"?{parsed.query}" if parsed.query else ""))
    return paths


def install_review_reads(page, teacher_browser, *, queue_handler, detail_handler) -> None:
    def queue(route):
        assert is_exact_fixture_url(route.request.url, teacher_browser.server.port)
        queue_handler(route)

    def detail(route):
        assert is_exact_fixture_url(route.request.url, teacher_browser.server.port)
        detail_handler(route)

    page.route(f"{teacher_browser.server.base_url}{QUEUE_PATH}", queue)
    page.route(f"{teacher_browser.server.base_url}/api/conversations/*", detail)


def unavailable_detail(status: str) -> dict:
    body = review_detail()
    body["analysis"] = {
        **body["analysis"],
        "status": status,
        "error": None if status in {"pending", "processing"} else {
            "code": "ANALYSIS_UPSTREAM_FAILED",
            "message": "分析服务暂时不可用",
        },
    }
    body["review_status"] = "unavailable"
    body["review"] = None
    return body


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_teacher_review_queue_and_detail_show_identity_time_id_and_status(
    teacher_browser, viewport
):
    _context, page = open_teacher(teacher_browser, viewport)
    install_review_reads(
        page,
        teacher_browser,
        queue_handler=lambda route: fulfill_json(route, [queue_row()]),
        detail_handler=lambda route: fulfill_json(route, review_detail()),
    )

    unlock_review(page)

    queue = page.locator("[data-review-panel='queue'] .review-queue-row")
    detail = page.locator("[data-review-panel='detail'] .review-detail-header")
    queue.get_by_role("link", name="审阅雨雨的会话 #42", exact=True).wait_for()
    detail.get_by_role("heading", name="雨雨", exact=True).wait_for()
    queue_text = queue.inner_text()
    detail_text = detail.inner_text()
    assert "雨雨" in queue_text
    assert "完成于 16:59" in queue_text
    assert "会话 #42" in queue_text
    assert "草稿" in queue_text
    assert "雨雨" in detail_text
    assert "完成于 16:59" in detail_text
    assert "会话 #42" in detail_text
    assert "分析已完成" in detail_text


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_teacher_review_deep_link_renders_split_read_only_shell_before_parallel_queue_and_detail_loads(teacher_browser, viewport):
    _context, page = open_teacher(teacher_browser, viewport)
    held_queue = []
    held_detail = []
    requests = []
    page.on("request", lambda request: requests.append(request))

    def hold_queue(route):
        assert is_exact_fixture_url(route.request.url, teacher_browser.server.port)
        held_queue.append(route)

    def hold_detail(route):
        assert is_exact_fixture_url(route.request.url, teacher_browser.server.port)
        held_detail.append(route)

    page.route(f"{teacher_browser.server.base_url}{QUEUE_PATH}", hold_queue)
    page.route(f"{teacher_browser.server.base_url}{DETAIL_PATH}", hold_detail)
    unlock_review(page)

    queue_panel = page.locator("[data-review-panel='queue']")
    detail_panel = page.locator("[data-review-panel='detail']")
    review_shell = page.locator("[data-review-shell]")
    assert review_shell.evaluate("node => getComputedStyle(node).gridTemplateColumns").startswith("300px")
    assert queue_panel.get_by_role("heading", name="待审阅队列", exact=True).count() == 1
    assert detail_panel.get_by_text("正在加载会话 #42…", exact=True).count() == 1
    reload_detail = detail_panel.get_by_role("button", name="重新加载此会话", exact=True)
    assert reload_detail.count() == 1
    assert reload_detail.bounding_box()["width"] >= 44
    assert reload_detail.bounding_box()["height"] >= 44
    assert queue_panel.get_attribute("aria-busy") == "true"
    assert detail_panel.get_attribute("aria-busy") == "true"
    assert held_queue and held_detail
    paths = local_paths(requests, teacher_browser.server.base_url)
    assert paths.index(QUEUE_PATH) < paths.index(DETAIL_PATH)

    fulfill_json(held_queue.pop(), [queue_row()])
    fulfill_json(held_detail.pop(), review_detail())
    queue_link = queue_panel.get_by_role("link", name="审阅雨雨的会话 #42", exact=True)
    queue_link.wait_for()
    detail_panel.get_by_role("heading", name="原始对话", exact=True).wait_for()
    assert detail_panel.get_by_text("雨雨", exact=True).count() >= 1
    assert detail_panel.get_by_text("会话 #42", exact=True).count() >= 1
    assert detail_panel.get_by_text("幼儿", exact=True).count() == 2
    assert detail_panel.get_by_text("日记本", exact=True).count() == 1
    assert detail_panel.get_by_role("heading", name="结构化结果", exact=True).count() == 1
    assert detail_panel.get_by_role("heading", name="能力评估", exact=True).count() == 1
    assert detail_panel.get_by_text("表达能力", exact=True).count() == 1
    assert detail_panel.locator("[data-review-form]").count() == 1
    assert detail_panel.get_by_label("饲养记录 1 分类", exact=True).count() == 1
    assert detail_panel.get_by_label("表达能力评分理由", exact=True).count() == 1
    assert detail_panel.get_by_role("button", name="保存草稿", exact=True).count() == 1
    assert detail_panel.get_by_role("button", name="保存并确认", exact=True).count() == 1
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
    queue_link.focus()
    assert queue_link.evaluate("node => document.activeElement === node")


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
@pytest.mark.parametrize("failure", ["500", "non-json", "malformed", "offline"])
def test_teacher_review_queue_failures_are_scoped_and_the_retry_does_not_reload_detail(teacher_browser, viewport, failure):
    _context, page = open_teacher(teacher_browser, viewport, "#review")
    queue_calls = 0
    detail_calls = []

    def queue(route):
        nonlocal queue_calls
        queue_calls += 1
        if queue_calls > 1:
            fulfill_json(route, [])
        elif failure == "500":
            route.fulfill(status=500, content_type="application/json", body='{"error":{"message":"raw-queue-detail"}}')
        elif failure == "non-json":
            route.fulfill(status=200, content_type="text/plain", body="raw-queue-detail")
        elif failure == "malformed":
            fulfill_json(route, {"not": "an array"})
        else:
            route.abort("failed")

    install_review_reads(page, teacher_browser, queue_handler=queue, detail_handler=lambda route: detail_calls.append(route))
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    unlock_review(page)
    queue_panel = page.locator("[data-review-panel='queue']")
    queue_panel.get_by_text("加载失败，请重试。", exact=True).wait_for()
    assert "raw-queue-detail" not in page.locator("body").inner_text()
    queue_panel.get_by_role("button", name="重新加载队列", exact=True).click()
    queue_panel.get_by_text("暂无待审阅会话", exact=True).wait_for()
    assert queue_calls == 2
    assert detail_calls == []
    assert errors == []


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
@pytest.mark.parametrize("failure", ["500", "non-json", "malformed", "offline"])
def test_teacher_review_detail_failures_keep_the_queue_and_persistent_reload_recovers(teacher_browser, viewport, failure):
    _context, page = open_teacher(teacher_browser, viewport)
    detail_calls = 0

    def detail(route):
        nonlocal detail_calls
        detail_calls += 1
        if detail_calls > 1:
            fulfill_json(route, review_detail())
        elif failure == "500":
            route.fulfill(status=500, content_type="application/json", body='{"error":{"message":"raw-detail-value"}}')
        elif failure == "non-json":
            route.fulfill(status=200, content_type="text/plain", body="raw-detail-value")
        elif failure == "malformed":
            fulfill_json(route, {"id": 42})
        else:
            route.abort("failed")

    install_review_reads(page, teacher_browser, queue_handler=lambda route: fulfill_json(route, [queue_row()]), detail_handler=detail)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    unlock_review(page)
    queue_panel = page.locator("[data-review-panel='queue']")
    detail_panel = page.locator("[data-review-panel='detail']")
    queue_panel.get_by_role("link", name="审阅雨雨的会话 #42", exact=True).wait_for()
    detail_panel.get_by_text("加载失败，请重试。", exact=True).wait_for()
    assert "raw-detail-value" not in page.locator("body").inner_text()
    detail_panel.get_by_role("button", name="重新加载此会话", exact=True).click()
    detail_panel.get_by_role("heading", name="原始对话", exact=True).wait_for()
    assert detail_calls == 2
    assert errors == []


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
@pytest.mark.parametrize("status", ["pending", "processing", "failed"])
def test_teacher_review_unavailable_analysis_keeps_transcript_but_never_renders_review_controls_or_server_error(teacher_browser, viewport, status):
    _context, page = open_teacher(teacher_browser, viewport)
    install_review_reads(
        page,
        teacher_browser,
        queue_handler=lambda route: fulfill_json(route, []),
        detail_handler=lambda route: fulfill_json(route, unavailable_detail(status)),
    )
    unlock_review(page)
    detail_panel = page.locator("[data-review-panel='detail']")
    detail_panel.get_by_role("heading", name="原始对话", exact=True).wait_for()
    detail_panel.get_by_text("我喂了小鸭。", exact=True).wait_for()
    detail_panel.get_by_text("结构化结果暂不可用", exact=True).wait_for()
    assert detail_panel.get_by_role("heading", name="能力评估", exact=True).count() == 0
    assert detail_panel.locator("input, textarea, select").count() == 0
    assert "分析服务暂时不可用" not in detail_panel.inner_text()
    if status == "failed":
        detail_panel.get_by_text("分析失败，请返回今日任务重试。", exact=True).wait_for()
        retry_today = detail_panel.get_by_role("link", name="返回今日任务", exact=True)
        assert retry_today.get_attribute("href") == "#today"


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_teacher_review_navigation_aborts_held_detail_and_only_fast_hash_b_renders(teacher_browser, viewport):
    _context, page = open_teacher(teacher_browser, viewport)
    held = []
    failed = []
    page.on("requestfailed", lambda request: failed.append(request.url))

    def detail(route):
        if route.request.url.endswith("/42"):
            held.append(route)
        else:
            body = review_detail({"id": 43, "child": {"id": 8, "name": "小风", "nickname": "风风", "avatar": None}})
            fulfill_json(route, body)

    install_review_reads(page, teacher_browser, queue_handler=lambda route: fulfill_json(route, []), detail_handler=detail)
    unlock_review(page)
    assert held
    page.evaluate("location.hash = '#review?conversation_id=43'")
    detail_panel = page.locator("[data-review-panel='detail']")
    detail_panel.get_by_text("风风", exact=True).wait_for()
    page.wait_for_timeout(100)
    assert f"{teacher_browser.server.base_url}/api/conversations/42" in failed
    assert "会话 #42" not in detail_panel.inner_text()


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_teacher_review_lock_aborts_both_held_reads_and_reunlock_starts_one_fresh_reader(teacher_browser, viewport):
    _context, page = open_teacher(teacher_browser, viewport)
    queue_calls = 0
    detail_calls = 0
    failed = []
    errors = []
    page.on("requestfailed", lambda request: failed.append(request.url))
    page.on("pageerror", lambda error: errors.append(str(error)))

    def queue(route):
        nonlocal queue_calls
        queue_calls += 1
        if queue_calls > 1:
            fulfill_json(route, [])

    def detail(route):
        nonlocal detail_calls
        detail_calls += 1
        if detail_calls > 1:
            fulfill_json(route, review_detail())

    install_review_reads(page, teacher_browser, queue_handler=queue, detail_handler=detail)
    unlock_review(page)
    assert queue_calls == 1 and detail_calls == 1
    page.get_by_role("button", name="立即锁定", exact=True).click()
    page.get_by_label("教师 PIN", exact=True).wait_for()
    page.wait_for_timeout(100)
    assert f"{teacher_browser.server.base_url}{QUEUE_PATH}" in failed
    assert f"{teacher_browser.server.base_url}{DETAIL_PATH}" in failed
    assert page.get_by_role("heading", name="值日审阅", exact=True).count() == 0

    page.get_by_label("教师 PIN", exact=True).fill(PIN)
    page.get_by_role("button", name="解锁", exact=True).click()
    page.get_by_role("heading", name="值日审阅", exact=True).wait_for()
    page.locator("[data-review-panel='detail']").get_by_role("heading", name="原始对话", exact=True).wait_for()
    assert queue_calls == 2 and detail_calls == 2
    assert errors == []


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
@pytest.mark.parametrize("order", ["queue-first", "detail-first"])
def test_teacher_review_cross_source_child_mismatch_replaces_the_detail_with_fixed_error(teacher_browser, viewport, order):
    _context, page = open_teacher(teacher_browser, viewport)
    held_queue = []
    held_detail = []
    mismatched_child = {"id": 7, "name": "小雨", "nickname": "另一个身份", "avatar": "rain.png"}

    install_review_reads(
        page,
        teacher_browser,
        queue_handler=lambda route: held_queue.append(route),
        detail_handler=lambda route: held_detail.append(route),
    )
    unlock_review(page)
    assert held_queue and held_detail
    if order == "queue-first":
        fulfill_json(held_queue.pop(), pending_queue := [dict(queue_row(), child=mismatched_child)])
        fulfill_json(held_detail.pop(), review_detail())
    else:
        fulfill_json(held_detail.pop(), review_detail())
        page.locator("[data-review-panel='detail']").get_by_role("heading", name="原始对话", exact=True).wait_for()
        fulfill_json(held_queue.pop(), pending_queue := [dict(queue_row(), child=mismatched_child)])
    detail_panel = page.locator("[data-review-panel='detail']")
    detail_panel.get_by_text("加载失败，请重试。", exact=True).wait_for()
    assert "另一个身份" not in detail_panel.inner_text()
