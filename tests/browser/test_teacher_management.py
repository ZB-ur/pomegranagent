import json
from urllib.parse import parse_qs, urlsplit

import pytest

from tests.browser.conftest import is_exact_fixture_url


PIN = "1234"
VIEWPORTS = [{"width": 1024, "height": 768}, {"width": 1440, "height": 900}]
VIEWPORT_IDS = ["1024x768", "1440x900"]


def open_teacher(teacher_browser, viewport, fragment):
    context = teacher_browser.new_context()
    page = context.new_page()
    page.set_default_timeout(5_000)
    page.set_viewport_size(viewport)
    requests = []
    page.on("request", lambda request: requests.append(request))
    page.goto(f"{teacher_browser.server.base_url}/teacher.html{fragment}", wait_until="domcontentloaded")
    page.get_by_label("设置教师 PIN", exact=True).fill(PIN)
    page.get_by_label("再次输入教师 PIN", exact=True).fill(PIN)
    page.get_by_role("button", name="设置并解锁", exact=True).click()
    return context, page, requests


def setup(page):
    page.get_by_label("设置教师 PIN", exact=True).fill(PIN)
    page.get_by_label("再次输入教师 PIN", exact=True).fill(PIN)
    page.get_by_role("button", name="设置并解锁", exact=True).click()


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_children_management_is_labeled_strict_and_never_sends_delete(teacher_browser, viewport):
    calls = []
    rows = [{
        "id": 7, "name": "小雨", "nickname": "雨雨", "avatar": None,
        "active": True, "deactivated_at": None, "future_roster_entries": 2,
        "has_active_conversation": False,
    }]

    def children(route):
        assert is_exact_fixture_url(route.request.url, teacher_browser.server.port)
        calls.append((route.request.method, route.request.url, route.request.post_data))
        if route.request.method in {"POST", "PUT"}:
            body = json.loads(route.request.post_data)
            route.fulfill(status=200, content_type="application/json", body=json.dumps({
                "id": 8 if route.request.method == "POST" else 7,
                "name": body["name"], "nickname": body["nickname"],
                "avatar": body["avatar"], "active": True,
            }, ensure_ascii=False))
            return
        route.fulfill(status=200, content_type="application/json", body=json.dumps(rows, ensure_ascii=False))

    page_context = teacher_browser.new_context()
    page = page_context.new_page()
    page.set_default_timeout(5_000)
    page.set_viewport_size(viewport)
    page.route(f"{teacher_browser.server.base_url}/api/children**", children)
    page.goto(f"{teacher_browser.server.base_url}/teacher.html#children", wait_until="domcontentloaded")
    page.get_by_label("设置教师 PIN", exact=True).fill(PIN)
    page.get_by_label("再次输入教师 PIN", exact=True).fill(PIN)
    page.get_by_role("button", name="设置并解锁", exact=True).click()

    page.get_by_role("heading", name="幼儿管理", exact=True).wait_for()
    page.get_by_label("幼儿姓名", exact=True).fill("  新幼儿  ")
    page.get_by_label("小名", exact=True).fill("  小新  ")
    page.get_by_role("button", name="添加幼儿", exact=True).click()
    page.wait_for_function("() => document.querySelector('[role=status]')?.textContent.includes('已保存')")

    page.get_by_role("button", name="编辑：雨雨", exact=True).click()
    page.get_by_label("幼儿姓名", exact=True).fill("  小雨更新  ")
    page.get_by_label("小名", exact=True).fill("")
    page.get_by_role("button", name="保存幼儿", exact=True).click()
    page.wait_for_function("() => document.querySelector('[role=status]')?.textContent.includes('已保存')")

    mutations = [call for call in calls if call[0] in {"POST", "PUT"}]
    assert len(mutations) == 2
    assert json.loads(mutations[0][2]) == {"name": "新幼儿", "nickname": "小新", "avatar": None}
    assert json.loads(mutations[1][2]) == {"name": "小雨更新", "nickname": None, "avatar": None}
    assert "/api/children/7" in mutations[1][1]
    assert any(parse_qs(urlsplit(call[1]).query) == {"include_inactive": ["true"]} for call in calls)
    assert all(call[0] != "DELETE" for call in calls)
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_child_deactivation_uses_named_dialog_and_real_undo(teacher_browser, viewport):
    state_calls = []
    rows = [{
        "id": 7, "name": "小雨", "nickname": "雨雨", "avatar": None,
        "active": True, "deactivated_at": None, "future_roster_entries": 2,
        "has_active_conversation": False,
    }]

    def child_list(route):
        route.fulfill(status=200, content_type="application/json", body=json.dumps(rows, ensure_ascii=False))

    def state(route):
        active = route.request.url.endswith("/reactivate")
        state_calls.append(route.request.url)
        route.fulfill(status=200, content_type="application/json", body=json.dumps({
            "id": 7, "kind": "child", "name": "小雨", "active": active,
            "deactivated_at": None if active else "2026-08-29T01:00:00Z",
            "affected_future_roster_entries": 2, "changed": True,
        }, ensure_ascii=False))

    context = teacher_browser.new_context()
    page = context.new_page()
    page.set_default_timeout(5_000)
    page.set_viewport_size(viewport)
    page.route(f"{teacher_browser.server.base_url}/api/children?include_inactive=true", child_list)
    page.route(f"{teacher_browser.server.base_url}/api/children/7/deactivate", state)
    page.route(f"{teacher_browser.server.base_url}/api/children/7/reactivate", state)
    page.goto(f"{teacher_browser.server.base_url}/teacher.html#children", wait_until="domcontentloaded")
    page.get_by_label("设置教师 PIN", exact=True).fill(PIN)
    page.get_by_label("再次输入教师 PIN", exact=True).fill(PIN)
    page.get_by_role("button", name="设置并解锁", exact=True).click()

    launcher = page.get_by_role("button", name="停用：雨雨", exact=True)
    launcher.click()
    dialog = page.get_by_role("dialog", name="停用雨雨", exact=True)
    dialog.get_by_text("2", exact=False).wait_for()
    dialog.get_by_role("button", name="取消", exact=True).click()
    assert launcher.evaluate("button => document.activeElement === button")
    assert state_calls == []
    launcher.click()
    dialog = page.get_by_role("dialog", name="停用雨雨", exact=True)
    dialog.get_by_role("button", name="确认停用", exact=True).click()
    undo = page.get_by_role("button", name="撤销停用：雨雨", exact=True)
    undo.wait_for()
    undo.click()
    page.wait_for_function("() => !document.querySelector('[data-undo-toast]')")
    assert state_calls == [
        f"{teacher_browser.server.base_url}/api/children/7/deactivate",
        f"{teacher_browser.server.base_url}/api/children/7/reactivate",
    ]


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_child_deactivation_409_reloads_enriched_list(teacher_browser, viewport):
    context = teacher_browser.new_context()
    page = context.new_page()
    page.set_default_timeout(5_000)
    page.set_viewport_size(viewport)
    list_calls = []

    def child_list(route):
        list_calls.append(route.request.url)
        blocked = len(list_calls) > 1
        route.fulfill(status=200, content_type="application/json", body=json.dumps([{
            "id": 7, "name": "小雨", "nickname": "雨雨", "avatar": None,
            "active": True, "deactivated_at": None, "future_roster_entries": 2,
            "has_active_conversation": blocked,
        }], ensure_ascii=False))

    page.route(f"{teacher_browser.server.base_url}/api/children?include_inactive=true", child_list)
    page.route(
        f"{teacher_browser.server.base_url}/api/children/7/deactivate",
        lambda route: route.fulfill(
            status=409,
            content_type="application/json",
            body=json.dumps({"error": {
                "code": "ACTIVE_CONVERSATION_EXISTS",
                "message": "raw server secret",
                "field_errors": {},
                "retryable": False,
            }}),
        ),
    )
    page.goto(f"{teacher_browser.server.base_url}/teacher.html#children", wait_until="domcontentloaded")
    setup(page)
    page.get_by_role("button", name="停用：雨雨", exact=True).click()
    page.get_by_role("dialog", name="停用雨雨", exact=True).get_by_role(
        "button", name="确认停用", exact=True
    ).click()

    page.get_by_text("当前有进行中的会话，暂不能停用。", exact=True).wait_for()
    expect_button = page.get_by_role("button", name="停用：雨雨", exact=True)
    assert expect_button.is_disabled()
    assert len(list_calls) == 2
    assert "raw server secret" not in page.locator("#main").inner_text()


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_only_latest_deactivation_undo_toast_remains_live(teacher_browser, viewport):
    context = teacher_browser.new_context()
    page = context.new_page()
    page.set_default_timeout(5_000)
    page.set_viewport_size(viewport)
    rows = [
        {"id": 7, "name": "小雨", "nickname": "雨雨", "avatar": None, "active": True, "deactivated_at": None, "future_roster_entries": 2, "has_active_conversation": False},
        {"id": 8, "name": "乐乐", "nickname": None, "avatar": None, "active": True, "deactivated_at": None, "future_roster_entries": 0, "has_active_conversation": False},
    ]
    page.route(
        f"{teacher_browser.server.base_url}/api/children?include_inactive=true",
        lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(rows, ensure_ascii=False)),
    )

    def state(route):
        identifier = int(urlsplit(route.request.url).path.split('/')[-2])
        item = next(row for row in rows if row["id"] == identifier)
        route.fulfill(status=200, content_type="application/json", body=json.dumps({
            "id": identifier, "kind": "child", "name": item["name"], "active": False,
            "deactivated_at": "2026-08-29T01:00:00Z",
            "affected_future_roster_entries": item["future_roster_entries"], "changed": True,
        }, ensure_ascii=False))

    page.route(f"{teacher_browser.server.base_url}/api/children/*/deactivate", state)
    page.goto(f"{teacher_browser.server.base_url}/teacher.html#children", wait_until="domcontentloaded")
    setup(page)
    for display in ["雨雨", "乐乐"]:
        page.get_by_role("button", name=f"停用：{display}", exact=True).click()
        page.get_by_role("dialog", name=f"停用{display}", exact=True).get_by_role(
            "button", name="确认停用", exact=True
        ).click()
        page.get_by_role("button", name=f"撤销停用：{display}", exact=True).wait_for()

    assert page.locator("[data-undo-toast]").count() == 1
    assert page.get_by_role("button", name="撤销停用：雨雨", exact=True).count() == 0
    assert page.get_by_role("button", name="撤销停用：乐乐", exact=True).count() == 1


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_duck_archive_summary_is_text_and_roster_uses_frozen_idempotent_routes(teacher_browser, viewport):
    context = teacher_browser.new_context()
    page = context.new_page()
    page.set_default_timeout(5_000)
    page.set_viewport_size(viewport)
    calls = []
    archive_calls = []
    children = [
        {"id": 7, "name": "甲", "nickname": None, "avatar": None, "active": True, "deactivated_at": None, "future_roster_entries": 0, "has_active_conversation": False},
        {"id": 8, "name": "乙", "nickname": None, "avatar": None, "active": True, "deactivated_at": None, "future_roster_entries": 0, "has_active_conversation": False},
    ]
    ducks = [{"id": 9, "name": "小黄", "avatar": None, "status": None, "note": None, "active": True, "deactivated_at": None, "historical_feeding_log_count": 0}]
    page.route(f"{teacher_browser.server.base_url}/api/children?include_inactive=true", lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(children, ensure_ascii=False)))
    page.route(f"{teacher_browser.server.base_url}/api/ducks?include_inactive=true", lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(ducks, ensure_ascii=False)))
    page.route(f"{teacher_browser.server.base_url}/api/roster", lambda route: route.fulfill(status=200, content_type="application/json", body="[]"))
    def archive(route):
        archive_calls.append(route.request.url)
        route.fulfill(status=200, content_type="application/json", body='{"duck_id":9,"summary":"<img src=x onerror=secret>"}')
    def summarize(route):
        archive_calls.append(route.request.url)
        route.fulfill(status=200, content_type="application/json", body='{"duck_id":9,"summary":"新档案"}')
    page.route(f"{teacher_browser.server.base_url}/api/ducks/9/archive", archive)
    page.route(f"{teacher_browser.server.base_url}/api/ducks/9/summarize", summarize)

    def daily(route):
        calls.append(route.request)
        body = json.loads(route.request.post_data)
        route.fulfill(status=200, content_type="application/json", body=json.dumps({
            "request_id": body["request_id"], "date": "2026-08-29", "cycle": body["cycle"],
            "child_ids": sorted(body["child_ids"]), "replayed": False,
        }))
    page.route(f"{teacher_browser.server.base_url}/api/roster/2026-08-29", daily)

    page.goto(f"{teacher_browser.server.base_url}/teacher.html#ducks", wait_until="domcontentloaded")
    page.get_by_label("设置教师 PIN", exact=True).fill(PIN)
    page.get_by_label("再次输入教师 PIN", exact=True).fill(PIN)
    page.get_by_role("button", name="设置并解锁", exact=True).click()
    page.get_by_role("button", name="查看档案：小黄", exact=True).evaluate(
        "button => { button.click(); button.click(); }"
    )
    page.get_by_text("<img src=x onerror=secret>", exact=True).wait_for()
    assert len(archive_calls) == 1
    assert page.locator("#main img").count() == 0
    page.get_by_role("button", name="生成档案：小黄", exact=True).evaluate(
        "button => { button.click(); button.click(); }"
    )
    page.get_by_text("新档案", exact=True).wait_for()
    assert len(archive_calls) == 2

    page.get_by_role("button", name="值日排班", exact=True).click()
    page.get_by_role("heading", name="值日排班", exact=True).wait_for()
    page.get_by_label("排班日期", exact=True).fill("2026-08-29")
    page.get_by_label("手动排班周期", exact=True).fill("2026-W34")
    page.get_by_label("选择甲", exact=True).check()
    page.get_by_label("选择乙", exact=True).check()
    page.get_by_role("button", name="保存当日排班", exact=True).click()
    page.get_by_text("排班已保存", exact=True).wait_for()
    assert len(calls) == 1
    assert calls[0].method == "PUT"
    body = json.loads(calls[0].post_data)
    assert set(body) == {"request_id", "cycle", "child_ids"}
    assert calls[0].headers["x-request-id"] == body["request_id"]


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_roster_duplicate_child_mapping_fails_closed(teacher_browser, viewport):
    context = teacher_browser.new_context()
    page = context.new_page()
    page.set_default_timeout(5_000)
    page.set_viewport_size(viewport)
    duplicate_children = [
        {"id": 7, "name": "甲", "nickname": None, "avatar": None, "active": True, "deactivated_at": None, "future_roster_entries": 0, "has_active_conversation": False},
        {"id": 7, "name": "重复甲", "nickname": None, "avatar": None, "active": True, "deactivated_at": None, "future_roster_entries": 0, "has_active_conversation": False},
    ]
    page.route(
        f"{teacher_browser.server.base_url}/api/children?include_inactive=true",
        lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(duplicate_children, ensure_ascii=False)),
    )
    page.route(
        f"{teacher_browser.server.base_url}/api/roster",
        lambda route: route.fulfill(status=200, content_type="application/json", body='[{"id":1,"cycle":"2026-W35","date":"2026-08-31","child_id":7}]'),
    )
    page.goto(f"{teacher_browser.server.base_url}/teacher.html#roster", wait_until="domcontentloaded")
    setup(page)

    page.get_by_text("排班加载失败，请重试。", exact=True).wait_for()
    assert page.get_by_label("选择甲", exact=True).count() == 0
    assert "2026-W35" not in page.locator("#main").inner_text()


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_auto_roster_lock_retry_uuid_and_exact_ack(teacher_browser, viewport):
    context = teacher_browser.new_context()
    page = context.new_page()
    page.set_default_timeout(5_000)
    page.set_viewport_size(viewport)
    children = [
        {"id": 7, "name": "甲", "nickname": None, "avatar": None, "active": True, "deactivated_at": None, "future_roster_entries": 0, "has_active_conversation": False},
        {"id": 8, "name": "乙", "nickname": None, "avatar": None, "active": True, "deactivated_at": None, "future_roster_entries": 0, "has_active_conversation": False},
    ]
    calls = []
    page.route(
        f"{teacher_browser.server.base_url}/api/children?include_inactive=true",
        lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(children, ensure_ascii=False)),
    )
    page.route(
        f"{teacher_browser.server.base_url}/api/roster",
        lambda route: route.fulfill(status=200, content_type="application/json", body="[]"),
    )

    def auto(route):
        body = json.loads(route.request.post_data)
        calls.append((body, route.request.headers["x-request-id"]))
        schedule = [{"date": "2026-08-31", "child_ids": [7, 8]}]
        if len(calls) == 3:
            schedule.append({"date": "2026-09-01", "child_ids": [7, 8]})
        route.fulfill(status=200, content_type="application/json", body=json.dumps({
            "request_id": body["request_id"], "schedule": schedule,
            "replayed": len(calls) == 3,
        }))

    page.route(f"{teacher_browser.server.base_url}/api/roster/auto", auto)
    page.goto(f"{teacher_browser.server.base_url}/teacher.html#roster", wait_until="domcontentloaded")
    setup(page)
    page.get_by_label("自动排班开始日期", exact=True).fill("2026-08-31")
    page.get_by_label("自动排班天数", exact=True).fill("2")
    page.get_by_label("自动排班周期", exact=True).fill("2026-W35")

    page.evaluate("""
      const form = [...document.querySelectorAll('#main form')][1];
      form.dispatchEvent(new Event('submit', {bubbles: true, cancelable: true}));
      form.dispatchEvent(new Event('submit', {bubbles: true, cancelable: true}));
    """)
    page.get_by_text("排班保存失败，请使用相同内容重试。", exact=True).wait_for()
    assert len(calls) == 1

    page.get_by_label("自动排班周期", exact=True).fill("2026-W35-new")
    page.get_by_role("button", name="生成排班", exact=True).click()
    page.get_by_text("排班保存失败，请使用相同内容重试。", exact=True).wait_for()
    page.get_by_role("button", name="生成排班", exact=True).click()
    page.get_by_text("排班已保存", exact=True).wait_for()

    assert len(calls) == 3
    first_id, second_id, third_id = [body["request_id"] for body, _header in calls]
    assert first_id != second_id
    assert second_id == third_id
    assert all(body["request_id"] == header for body, header in calls)
    assert calls[-1][0] == {
        "request_id": third_id,
        "start_date": "2026-08-31",
        "days": 2,
        "cycle": "2026-W35-new",
        "replace_existing": False,
    }


@pytest.mark.parametrize("outcome", ["resolve", "reject"])
def test_late_deactivation_after_navigation_cannot_write_to_new_route(teacher_browser, outcome):
    context = teacher_browser.new_context()
    page = context.new_page()
    page.set_default_timeout(5_000)
    page_errors = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.goto(f"{teacher_browser.server.base_url}/teacher.html#today", wait_until="domcontentloaded")
    setup(page)
    page.get_by_role("heading", name="今日任务", exact=True).wait_for()
    child = {
        "id": 7, "name": "小雨", "nickname": "雨雨", "avatar": None,
        "active": True, "deactivated_at": None, "future_roster_entries": 2,
        "has_active_conversation": False,
    }
    page.evaluate("""child => {
      const original = window.DuckAPI;
      window.DuckAPI = Object.freeze({
        ...original,
        request(path, options) {
          if (path === '/api/children?include_inactive=true') return Promise.resolve([child]);
          if (path === '/api/ducks?include_inactive=true') return Promise.resolve([]);
          if (path === '/api/children/7/deactivate') {
            return new Promise((resolve, reject) => {
              window.__lateState = {resolve, reject, signal: options.signal};
            });
          }
          return original.request(path, options);
        },
      });
    }""", child)
    page.evaluate("location.hash = '#children'")
    page.get_by_role("button", name="停用：雨雨", exact=True).click()
    page.get_by_role("dialog", name="停用雨雨", exact=True).get_by_role(
        "button", name="确认停用", exact=True
    ).click()
    page.wait_for_function("() => Boolean(window.__lateState)")
    page.evaluate("location.hash = '#ducks'")
    page.get_by_role("heading", name="小鸭管理", exact=True).wait_for()
    page.evaluate("""outcome => {
      if (outcome === 'resolve') window.__lateState.resolve({
        id: 7, kind: 'child', name: '小雨', active: false,
        deactivated_at: '2026-08-29T01:00:00Z',
        affected_future_roster_entries: 2, changed: true,
      });
      else window.__lateState.reject(new Error('raw secret'));
    }""", outcome)
    page.wait_for_timeout(50)

    assert page.get_by_role("heading", name="小鸭管理", exact=True).count() == 1
    assert page.locator("[data-undo-toast]").count() == 0
    assert "raw secret" not in page.locator("#main").inner_text()
    assert page_errors == []
