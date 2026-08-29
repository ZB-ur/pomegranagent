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
        "dimensions": [{"key": "language", "name": "<script>语言</script>", "points": [{"date": "2026-08-23", "score": 4}]}],
    }, ensure_ascii=False)))
    page.goto(f"{teacher_browser.server.base_url}/teacher.html#growth", wait_until="domcontentloaded")
    setup(page)
    page.get_by_role("heading", name="能力成长曲线", exact=True).wait_for()
    assert page_errors == []
    assert page.locator("#main label").count() == 1, page.locator("#main").inner_text()
    page.get_by_label("选择幼儿", exact=True).select_option("7")
    page.wait_for_url("**/teacher.html#growth?child_id=7")
    page.get_by_text("<script>语言</script>", exact=True).wait_for()
    assert page.locator("#main script").count() == 0
    assert page.locator("#main svg").count() == 1
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")


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
    assert "raw secret" not in page.locator("#main").inner_text()
    retry.click()
    page.get_by_text("成长数据已加载", exact=True).wait_for()
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
