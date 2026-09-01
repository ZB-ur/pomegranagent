import json
from urllib.parse import parse_qs, urlsplit

import pytest


PIN = "1234"
VIEWPORTS = [{"width": 1024, "height": 768}, {"width": 1440, "height": 900}]
VIEWPORT_IDS = ["1024x768", "1440x900"]

CHILDREN = [
    {"id": 7, "name": "小雨", "nickname": "雨雨", "avatar": None, "active": True, "deactivated_at": None, "future_roster_entries": 0, "has_active_conversation": False},
    {"id": 8, "name": "历史幼儿", "nickname": None, "avatar": None, "active": False, "deactivated_at": "2026-08-20T00:00:00Z", "future_roster_entries": 0, "has_active_conversation": False},
]


def setup(page):
    page.get_by_label("设置教师 PIN", exact=True).fill(PIN)
    page.get_by_label("再次输入教师 PIN", exact=True).fill(PIN)
    page.get_by_role("button", name="设置并解锁", exact=True).click()


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_growth_uses_canonical_hash_and_safe_svg_nodes(teacher_browser, viewport):
    context = teacher_browser.new_context()
    page = context.new_page()
    page_errors = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.set_default_timeout(5_000)
    page.set_viewport_size(viewport)
    page.route(f"{teacher_browser.server.base_url}/api/children?include_inactive=true", lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(CHILDREN, ensure_ascii=False)))
    page.route(f"{teacher_browser.server.base_url}/api/analysis/growth?child_id=7", lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps({
        "child_id": 7,
        "dimensions": [{"key": "language", "name": "<script>语言</script>", "points": [
            {"date": "2026-08-06", "score": 5},
            {"date": "2026-08-01", "score": 1},
            {"date": "2026-08-02", "score": 2},
            {"date": "2026-08-03", "score": 3},
            {"date": "2026-08-04", "score": 4},
            {"date": "2026-08-05", "score": 5},
        ]}],
    }, ensure_ascii=False)))
    page.goto(f"{teacher_browser.server.base_url}/teacher.html#growth", wait_until="domcontentloaded")
    setup(page)
    page.get_by_role("heading", name="能力成长曲线", exact=True).wait_for()
    assert page_errors == []
    assert page.locator("#main label").count() == 1, page.locator("#main").inner_text()
    assert page.get_by_text("看见变化，不替孩子下结论", exact=True).count() == 1
    page.get_by_label("选择幼儿", exact=True).select_option("7")
    page.wait_for_url("**/teacher.html#growth?child_id=7")
    page.get_by_text("<script>语言</script>", exact=True).wait_for()
    chronological = page.get_by_text("2026-08-06 5 分", exact=False)
    chronological.first.wait_for()
    assert chronological.count() >= 1
    assert page.get_by_text("最近 5 次均值", exact=True).count() == 1
    assert page.get_by_text("与最早记录差值", exact=True).count() == 1
    summary = page.locator(".growth-summary-stack")
    assert summary.get_by_text("最新评分", exact=True).count() == 1
    assert summary.get_by_text("2026-08-06", exact=True).count() == 1
    assert summary.get_by_text("5 分", exact=True).count() == 1
    assert summary.get_by_text("3.8 分", exact=True).count() == 1
    assert summary.get_by_text("+4", exact=True).count() == 1
    assert summary.get_by_text("仅表示数值差，不代表结论", exact=True).count() == 1
    assert page.locator(".report-chart [data-axis-score]").evaluate_all("nodes => nodes.map(node => node.textContent)") == ["5", "4", "3", "2", "1"]
    assert page.locator("#main script").count() == 0
    assert page.locator("#main svg").count() == 1
    assert page.locator(".growth-view").get_attribute("aria-busy") is None
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
    assert page.locator("#main button:visible, #main a:visible, #main select:visible").evaluate_all("nodes => nodes.every(node => { const r=node.getBoundingClientRect(); return r.width>=44 && r.height>=44; })")

    chart_box = page.locator(".report-chart").bounding_box()
    data_box = page.locator(".growth-data-panel").bounding_box()
    assert chart_box is not None and data_box is not None
    if viewport["width"] >= 1280:
        assert abs(chart_box["y"] - data_box["y"]) <= 1
        assert chart_box["x"] + chart_box["width"] <= data_box["x"] + 1
    else:
        assert chart_box["y"] + chart_box["height"] <= data_box["y"] + 1


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_growth_long_history_keeps_all_points_with_bounded_non_overlapping_date_ticks(teacher_browser, viewport):
    context = teacher_browser.new_context()
    page = context.new_page()
    page.set_default_timeout(5_000)
    page.set_viewport_size(viewport)
    points = [
        {"date": "2026-08-01", "score": 1}, {"date": "2026-08-02", "score": 2},
        {"date": "2026-08-03", "score": 3}, {"date": "2026-08-04", "score": 4},
        {"date": "2026-08-05", "score": 5}, {"date": "2026-08-06", "score": 1},
        {"date": "2026-08-07", "score": 2}, {"date": "2026-08-08", "score": 3},
        {"date": "2026-08-09", "score": 4}, {"date": "2026-08-10", "score": 5},
        {"date": "2026-08-11", "score": 1}, {"date": "2026-08-12", "score": 2},
        {"date": "2026-08-13", "score": 3}, {"date": "2026-08-14", "score": 4},
        {"date": "2026-08-15", "score": 5}, {"date": "2026-08-16", "score": 1},
        {"date": "2026-08-17", "score": 2}, {"date": "2026-08-18", "score": 3},
        {"date": "2026-08-19", "score": 4}, {"date": "2026-08-20", "score": 5},
        {"date": "2026-08-21", "score": 1}, {"date": "2026-08-22", "score": 2},
        {"date": "2026-08-23", "score": 3}, {"date": "2026-08-24", "score": 4},
    ]
    expected_chronology = (
        "2026-08-01 1 分；2026-08-02 2 分；2026-08-03 3 分；2026-08-04 4 分；"
        "2026-08-05 5 分；2026-08-06 1 分；2026-08-07 2 分；2026-08-08 3 分；"
        "2026-08-09 4 分；2026-08-10 5 分；2026-08-11 1 分；2026-08-12 2 分；"
        "2026-08-13 3 分；2026-08-14 4 分；2026-08-15 5 分；2026-08-16 1 分；"
        "2026-08-17 2 分；2026-08-18 3 分；2026-08-19 4 分；2026-08-20 5 分；"
        "2026-08-21 1 分；2026-08-22 2 分；2026-08-23 3 分；2026-08-24 4 分"
    )
    page.route(
        f"{teacher_browser.server.base_url}/api/children?include_inactive=true",
        lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(CHILDREN, ensure_ascii=False)),
    )
    page.route(
        f"{teacher_browser.server.base_url}/api/analysis/growth?child_id=7",
        lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps({
            "child_id": 7,
            "dimensions": [{"key": "language", "name": "语言表达能力", "points": points}],
        }, ensure_ascii=False)),
    )
    page.goto(f"{teacher_browser.server.base_url}/teacher.html#growth?child_id=7", wait_until="domcontentloaded")
    setup(page)
    chronology = page.locator(".growth-data-series p")
    chronology.wait_for()
    assert chronology.inner_text() == expected_chronology
    assert page.locator(".report-chart circle").count() == 24

    svg_box = page.locator(".report-chart svg").bounding_box()
    tick_boxes = page.locator(".report-chart-date").evaluate_all("""nodes => nodes.map(node => {
      const rect = node.getBoundingClientRect();
      return {left: rect.left, right: rect.right, text: node.textContent};
    })""")
    assert svg_box is not None
    assert len(tick_boxes) >= 2
    assert len(tick_boxes) < 24
    assert tick_boxes[0]["text"] == "2026-08-01"
    assert tick_boxes[-1]["text"] == "2026-08-24"
    svg_left = svg_box["x"]
    svg_right = svg_box["x"] + svg_box["width"]
    assert all(tick["left"] >= svg_left - 0.5 for tick in tick_boxes), tick_boxes
    assert all(tick["right"] <= svg_right + 0.5 for tick in tick_boxes), tick_boxes
    assert all(left["right"] <= right["left"] for left, right in zip(tick_boxes, tick_boxes[1:])), tick_boxes


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_growth_ten_date_history_avoids_rounded_middle_tick_collision(teacher_browser, viewport):
    context = teacher_browser.new_context()
    page = context.new_page()
    page.set_default_timeout(5_000)
    page.set_viewport_size(viewport)
    points = [
        {"date": "2026-08-01", "score": 1}, {"date": "2026-08-02", "score": 2},
        {"date": "2026-08-03", "score": 3}, {"date": "2026-08-04", "score": 4},
        {"date": "2026-08-05", "score": 5}, {"date": "2026-08-06", "score": 1},
        {"date": "2026-08-07", "score": 2}, {"date": "2026-08-08", "score": 3},
        {"date": "2026-08-09", "score": 4}, {"date": "2026-08-10", "score": 5},
    ]
    expected_chronology = (
        "2026-08-01 1 分；2026-08-02 2 分；2026-08-03 3 分；2026-08-04 4 分；"
        "2026-08-05 5 分；2026-08-06 1 分；2026-08-07 2 分；2026-08-08 3 分；"
        "2026-08-09 4 分；2026-08-10 5 分"
    )
    page.route(
        f"{teacher_browser.server.base_url}/api/children?include_inactive=true",
        lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(CHILDREN, ensure_ascii=False)),
    )
    page.route(
        f"{teacher_browser.server.base_url}/api/analysis/growth?child_id=7",
        lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps({
            "child_id": 7,
            "dimensions": [{"key": "language", "name": "语言表达能力", "points": points}],
        }, ensure_ascii=False)),
    )
    page.goto(f"{teacher_browser.server.base_url}/teacher.html#growth?child_id=7", wait_until="domcontentloaded")
    setup(page)
    chronology = page.locator(".growth-data-series p")
    chronology.wait_for()
    assert chronology.inner_text() == expected_chronology
    assert page.locator(".report-chart circle").count() == 10

    svg_box = page.locator(".report-chart svg").bounding_box()
    tick_boxes = page.locator(".report-chart-date").evaluate_all("""nodes => nodes.map(node => {
      const rect = node.getBoundingClientRect();
      return {left: rect.left, right: rect.right, text: node.textContent};
    })""")
    assert svg_box is not None
    assert tick_boxes[0]["text"] == "2026-08-01"
    assert tick_boxes[-1]["text"] == "2026-08-10"
    svg_left = svg_box["x"]
    svg_right = svg_box["x"] + svg_box["width"]
    assert all(tick["left"] >= svg_left - 0.5 for tick in tick_boxes), tick_boxes
    assert all(tick["right"] <= svg_right + 0.5 for tick in tick_boxes), tick_boxes
    assert all(left["right"] <= right["left"] for left, right in zip(tick_boxes, tick_boxes[1:])), tick_boxes


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_growth_unselected_is_visible_non_live_and_skips_growth_request(teacher_browser, viewport):
    context = teacher_browser.new_context()
    page = context.new_page()
    page.set_default_timeout(5_000)
    page.set_viewport_size(viewport)
    growth_calls = []
    page.route(
        f"{teacher_browser.server.base_url}/api/children?include_inactive=true",
        lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(CHILDREN, ensure_ascii=False)),
    )

    def growth(route):
        growth_calls.append(route.request.url)
        route.fulfill(status=200, content_type="application/json", body='{"child_id":7,"dimensions":[]}')

    page.route(f"{teacher_browser.server.base_url}/api/analysis/growth**", growth)
    page.goto(f"{teacher_browser.server.base_url}/teacher.html#growth", wait_until="domcontentloaded")
    setup(page)
    select = page.get_by_label("选择幼儿", exact=True)
    select.wait_for()
    status = page.locator(".growth-view .report-status")
    assert select.locator("option").first.inner_text() == "请选择幼儿"
    assert status.inner_text() == "请选择一名幼儿查看成长曲线。"
    assert status.get_attribute("role") is None
    assert status.get_attribute("aria-live") is None
    assert page.locator(".growth-view").get_attribute("aria-busy") is None
    assert page.locator("#main svg").count() == 0
    assert growth_calls == []


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_growth_invalid_child_alerts_focuses_selector_and_skips_growth_request(teacher_browser, viewport):
    context = teacher_browser.new_context()
    page = context.new_page()
    page.set_default_timeout(5_000)
    page.set_viewport_size(viewport)
    growth_calls = []
    page.route(
        f"{teacher_browser.server.base_url}/api/children?include_inactive=true",
        lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(CHILDREN, ensure_ascii=False)),
    )

    def growth(route):
        growth_calls.append(route.request.url)
        route.fulfill(status=200, content_type="application/json", body='{"child_id":7,"dimensions":[]}')

    page.route(f"{teacher_browser.server.base_url}/api/analysis/growth**", growth)
    page.goto(f"{teacher_browser.server.base_url}/teacher.html#growth?child_id=999", wait_until="domcontentloaded")
    setup(page)
    status = page.get_by_text("所选幼儿不存在，请重新选择。", exact=True)
    status.wait_for()
    select = page.get_by_label("选择幼儿", exact=True)
    assert status.get_attribute("role") == "alert"
    assert select.evaluate("node => document.activeElement === node")
    assert page.locator(".growth-view").get_attribute("aria-busy") is None
    assert growth_calls == []


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_growth_marks_both_loading_phases_busy_then_renders_polite_empty_state(teacher_browser, viewport):
    context = teacher_browser.new_context()
    page = context.new_page()
    page_errors = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.set_default_timeout(5_000)
    page.set_viewport_size(viewport)
    page.goto(f"{teacher_browser.server.base_url}/teacher.html#today", wait_until="domcontentloaded")
    setup(page)
    page.get_by_role("heading", name="今日任务", exact=True).wait_for()
    page.evaluate("""() => {
      const original = window.DuckAPI;
      window.DuckAPI = Object.freeze({
        ...original,
        request(path, options) {
          if (path === '/api/children?include_inactive=true') {
            return new Promise(resolve => { window.__growthChildrenResolve = resolve; });
          }
          if (path === '/api/analysis/growth?child_id=7') {
            return new Promise(resolve => { window.__growthDataResolve = resolve; });
          }
          return original.request(path, options);
        },
      });
    }""")
    page.evaluate("location.hash = '#growth?child_id=7'")
    page.wait_for_function("() => Boolean(window.__growthChildrenResolve)")
    view = page.locator(".growth-view")
    assert view.get_attribute("aria-busy") == "true"
    assert page.get_by_text("正在加载幼儿…", exact=True).get_attribute("role") == "status"

    page.evaluate("children => window.__growthChildrenResolve(children)", CHILDREN)
    page.wait_for_function("() => Boolean(window.__growthDataResolve)")
    assert view.get_attribute("aria-busy") == "true"
    assert page.get_by_text("正在加载成长数据…", exact=True).get_attribute("aria-live") == "polite"

    page.evaluate("() => window.__growthDataResolve({child_id: 7, dimensions: []})")
    empty = page.get_by_text("暂无已确认的成长数据", exact=True)
    empty.wait_for()
    assert empty.get_attribute("role") == "status"
    assert empty.get_attribute("aria-live") == "polite"
    assert view.get_attribute("aria-busy") is None
    assert page.locator("#main svg").count() == 0
    assert page_errors == []


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_history_filter_pagination_and_review_anchor_are_canonical(teacher_browser, viewport):
    context = teacher_browser.new_context()
    page = context.new_page()
    page_errors = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.set_default_timeout(5_000)
    page.set_viewport_size(viewport)
    history_urls = []
    page.route(f"{teacher_browser.server.base_url}/api/children?include_inactive=true", lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(CHILDREN, ensure_ascii=False)))

    def history(route):
        history_urls.append(route.request.url)
        query = parse_qs(urlsplit(route.request.url).query)
        identifier = 42 if "before_id" not in query else 41
        route.fulfill(status=200, content_type="application/json", body=json.dumps({
            "items": [{
                "id": identifier,
                "child": {"id": 8, "name": "历史幼儿", "nickname": None, "avatar": None},
                "date": "2026-08-23", "completed_at": "2026-08-23T09:00:00Z",
                "status": "ended", "end_reason": "complete", "message_count": 4, "round": 2,
                "analysis_status": "succeeded", "review_status": "confirmed", "revision": 3,
            }],
            "next_before_id": 42 if identifier == 42 else None,
        }, ensure_ascii=False))
    page.route(f"{teacher_browser.server.base_url}/api/conversations/history**", history)
    page.goto(f"{teacher_browser.server.base_url}/teacher.html#search", wait_until="domcontentloaded")
    setup(page)
    page.get_by_role("heading", name="明细检索", exact=True).wait_for()
    assert page_errors == []
    assert page.locator("#main label").count() == 1, page.locator("#main").inner_text()
    page.get_by_label("筛选幼儿", exact=True).select_option("8")
    page.wait_for_url("**/teacher.html#search?child_id=8")
    link = page.get_by_role("link", name="查看会话 #42", exact=True)
    assert link.get_attribute("href") == "#review?conversation_id=42"
    page.get_by_role("button", name="加载更多", exact=True).click()
    page.get_by_role("link", name="查看会话 #41", exact=True).wait_for()
    assert parse_qs(urlsplit(history_urls[-1]).query) == {
        "limit": ["20"], "child_id": ["8"], "before_id": ["42"]
    }


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_growth_initial_failure_has_accessible_retry(teacher_browser, viewport):
    context = teacher_browser.new_context()
    page = context.new_page()
    page.set_default_timeout(5_000)
    page.set_viewport_size(viewport)
    calls = []
    page.route(
        f"{teacher_browser.server.base_url}/api/children?include_inactive=true",
        lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(CHILDREN, ensure_ascii=False)),
    )

    def growth(route):
        calls.append(route.request.url)
        if len(calls) == 1:
            route.fulfill(status=500, content_type="application/json", body='{"error":{"code":"INTERNAL_ERROR","message":"raw secret","field_errors":{},"retryable":true}}')
            return
        route.fulfill(status=200, content_type="application/json", body=json.dumps({
            "child_id": 7,
            "dimensions": [{"key": "language", "name": "语言表达", "points": []}],
        }, ensure_ascii=False))

    page.route(f"{teacher_browser.server.base_url}/api/analysis/growth?child_id=7", growth)
    page.goto(f"{teacher_browser.server.base_url}/teacher.html#growth?child_id=7", wait_until="domcontentloaded")
    setup(page)
    retry = page.get_by_role("button", name="重试成长数据", exact=True)
    retry.wait_for()
    status = page.locator(".growth-view .report-status")
    assert status.get_attribute("role") == "alert"
    assert status.evaluate("node => node.firstChild?.textContent") == "成长数据加载失败，请重试。"
    assert "raw secret" not in page.locator("#main").inner_text()
    assert retry.evaluate("node => document.activeElement === node")
    retry.click()
    empty = page.get_by_text("暂无已确认的成长数据", exact=True)
    empty.wait_for()
    assert empty.get_attribute("role") == "status"
    assert page.locator("#main svg").count() == 0
    assert len(calls) == 2


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_history_initial_failure_has_accessible_retry(teacher_browser, viewport):
    context = teacher_browser.new_context()
    page = context.new_page()
    page.set_default_timeout(5_000)
    page.set_viewport_size(viewport)
    calls = []
    page.route(
        f"{teacher_browser.server.base_url}/api/children?include_inactive=true",
        lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(CHILDREN, ensure_ascii=False)),
    )

    def history(route):
        calls.append(route.request.url)
        if len(calls) == 1:
            route.fulfill(status=502, content_type="text/html", body="<h1>raw secret</h1>")
            return
        route.fulfill(status=200, content_type="application/json", body='{"items":[],"next_before_id":null}')

    page.route(f"{teacher_browser.server.base_url}/api/conversations/history**", history)
    page.goto(f"{teacher_browser.server.base_url}/teacher.html#search", wait_until="domcontentloaded")
    setup(page)
    retry = page.get_by_role("button", name="重试历史记录", exact=True)
    retry.wait_for()
    assert "raw secret" not in page.locator("#main").inner_text()
    retry.click()
    page.get_by_text("暂无历史记录", exact=True).wait_for()
    assert len(calls) == 2


@pytest.mark.parametrize("outcome", ["resolve", "reject"])
def test_growth_ignores_abort_insensitive_late_a_after_b(teacher_browser, outcome):
    context = teacher_browser.new_context()
    page = context.new_page()
    page.set_default_timeout(5_000)
    page_errors = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.goto(f"{teacher_browser.server.base_url}/teacher.html#today", wait_until="domcontentloaded")
    setup(page)
    page.get_by_role("heading", name="今日任务", exact=True).wait_for()
    page.evaluate("""children => {
      const original = window.DuckAPI;
      window.DuckAPI = Object.freeze({
        ...original,
        request(path, options) {
          if (path === '/api/children?include_inactive=true') return Promise.resolve(children);
          if (path === '/api/analysis/growth?child_id=7') {
            return new Promise((resolve, reject) => {
              window.__lateGrowth = {resolve, reject, signal: options.signal};
            });
          }
          if (path === '/api/analysis/growth?child_id=8') return Promise.resolve({
            child_id: 8,
            dimensions: [{key: 'latest', name: '最新 B', points: [{date: '2026-08-23', score: 4}]}],
          });
          return original.request(path, options);
        },
      });
    }""", CHILDREN)
    page.evaluate("location.hash = '#growth?child_id=7'")
    page.wait_for_function("() => Boolean(window.__lateGrowth)")
    page.evaluate("location.hash = '#growth?child_id=8'")
    page.get_by_text("最新 B", exact=True).wait_for()
    page.evaluate("""outcome => {
      if (outcome === 'resolve') window.__lateGrowth.resolve({
        child_id: 7,
        dimensions: [{key: 'stale', name: '过期 A', points: []}],
      });
      else window.__lateGrowth.reject(new Error('raw secret'));
    }""", outcome)
    page.wait_for_timeout(50)

    assert page.get_by_text("最新 B", exact=True).count() == 1
    assert page.get_by_text("过期 A", exact=True).count() == 0
    assert "raw secret" not in page.locator("#main").inner_text()
    assert page_errors == []


@pytest.mark.parametrize("outcome", ["resolve", "reject"])
def test_search_ignores_abort_insensitive_late_a_after_b(teacher_browser, outcome):
    context = teacher_browser.new_context()
    page = context.new_page()
    page.set_default_timeout(5_000)
    page_errors = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.goto(f"{teacher_browser.server.base_url}/teacher.html#today", wait_until="domcontentloaded")
    setup(page)
    page.get_by_role("heading", name="今日任务", exact=True).wait_for()
    page.evaluate("""children => {
      const original = window.DuckAPI;
      const item = (id, child) => ({
        id,
        child: {id: child.id, name: child.name, nickname: child.nickname, avatar: child.avatar},
        date: '2026-08-23', completed_at: '2026-08-23T09:00:00Z',
        status: 'ended', end_reason: 'complete', message_count: 4, round: 2,
        analysis_status: 'succeeded', review_status: 'confirmed', revision: 3,
      });
      window.__historyItem = item;
      window.DuckAPI = Object.freeze({
        ...original,
        request(path, options) {
          if (path === '/api/children?include_inactive=true') return Promise.resolve(children);
          if (path.includes('/api/conversations/history?') && path.includes('child_id=7')) {
            return new Promise((resolve, reject) => {
              window.__lateHistory = {resolve, reject, signal: options.signal};
            });
          }
          if (path.includes('/api/conversations/history?') && path.includes('child_id=8')) {
            return Promise.resolve({items: [item(88, children[1])], next_before_id: null});
          }
          return original.request(path, options);
        },
      });
    }""", CHILDREN)
    page.evaluate("location.hash = '#search?child_id=7'")
    page.wait_for_function("() => Boolean(window.__lateHistory)")
    page.evaluate("location.hash = '#search?child_id=8'")
    page.get_by_role("link", name="查看会话 #88", exact=True).wait_for()
    page.evaluate("""outcome => {
      if (outcome === 'resolve') window.__lateHistory.resolve({
        items: [window.__historyItem(77, {
          id: 7, name: '小雨', nickname: '雨雨', avatar: null,
        })],
        next_before_id: null,
      });
      else window.__lateHistory.reject(new Error('raw secret'));
    }""", outcome)
    page.wait_for_timeout(50)

    assert page.get_by_role("link", name="查看会话 #88", exact=True).count() == 1
    assert page.get_by_role("link", name="查看会话 #77", exact=True).count() == 0
    assert "raw secret" not in page.locator("#main").inner_text()
    assert page_errors == []
