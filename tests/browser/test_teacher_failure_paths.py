from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import pytest

from tests.browser.conftest import is_exact_fixture_url
from tests.browser.test_teacher_review_loading import queue_row, review_detail


PIN = "2468"
RAW_SECRET = "raw-task8-secret"
READ_CASES = [
    pytest.param(
        {
            "surface": "today_roster",
            "fault": "html-502",
            "viewport": {"width": 1024, "height": 768},
        },
        id="seed_today_roster_html_502_1024",
    ),
    pytest.param(
        {
            "surface": "today_roster",
            "fault": "offline",
            "viewport": {"width": 1024, "height": 768},
        },
        id="today_roster_offline_1024",
    ),
    pytest.param(
        {
            "surface": "review_pending",
            "fault": "html-502",
            "viewport": {"width": 1024, "height": 768},
        },
        id="review_pending_html_502_1024",
    ),
    pytest.param(
        {
            "surface": "review_pending",
            "fault": "offline",
            "viewport": {"width": 1024, "height": 768},
        },
        id="review_pending_offline_1024",
    ),
    pytest.param(
        {
            "surface": "today_roster",
            "fault": "html-502",
            "viewport": {"width": 1440, "height": 900},
        },
        id="today_roster_html_502_1440",
    ),
    pytest.param(
        {
            "surface": "today_roster",
            "fault": "offline",
            "viewport": {"width": 1440, "height": 900},
        },
        id="today_roster_offline_1440",
    ),
    pytest.param(
        {
            "surface": "review_pending",
            "fault": "html-502",
            "viewport": {"width": 1440, "height": 900},
        },
        id="review_pending_html_502_1440",
    ),
    pytest.param(
        {
            "surface": "review_pending",
            "fault": "offline",
            "viewport": {"width": 1440, "height": 900},
        },
        id="review_pending_offline_1440",
    ),
]
TIMEOUT_CASES = [
    pytest.param(
        {"viewport": {"width": 1024, "height": 768}},
        id="seed_review_timeout_1024",
    ),
    pytest.param(
        {"viewport": {"width": 1440, "height": 900}},
        id="review_timeout_1440",
    ),
]
STATE_SETTLED_CASES = [
    pytest.param(
        {
            "kind": "child",
            "action": "deactivate",
            "fault": "json-500",
            "viewport": {"width": 1024, "height": 768},
        },
        id="seed_child_deactivate_json_500_1024",
    ),
    pytest.param(
        {
            "kind": "child",
            "action": "reactivate",
            "fault": "json-500",
            "viewport": {"width": 1024, "height": 768},
        },
        id="child_reactivate_json_500_1024",
    ),
    pytest.param(
        {
            "kind": "duck",
            "action": "deactivate",
            "fault": "json-500",
            "viewport": {"width": 1024, "height": 768},
        },
        id="duck_deactivate_json_500_1024",
    ),
    pytest.param(
        {
            "kind": "duck",
            "action": "reactivate",
            "fault": "json-500",
            "viewport": {"width": 1024, "height": 768},
        },
        id="duck_reactivate_json_500_1024",
    ),
    *[
        pytest.param(
            {
                "kind": kind,
                "action": action,
                "fault": fault,
                "viewport": {"width": 1024, "height": 768},
            },
            id=f"{kind}_{action}_{fault.replace('-', '_')}_1024",
        )
        for fault in ("html-502", "offline")
        for kind in ("child", "duck")
        for action in ("deactivate", "reactivate")
    ],
    *[
        pytest.param(
            {
                "kind": kind,
                "action": action,
                "fault": fault,
                "viewport": {"width": 1440, "height": 900},
            },
            id=f"{kind}_{action}_{fault.replace('-', '_')}_1440",
        )
        for fault in ("json-500", "html-502", "offline")
        for kind in ("child", "duck")
        for action in ("deactivate", "reactivate")
    ],
]
STATE_DELAY_CASES = [
    pytest.param(
        {
            "kind": "child",
            "action": "deactivate",
            "viewport": {"width": 1024, "height": 768},
        },
        id="seed_child_deactivate_1024",
    ),
    pytest.param(
        {
            "kind": "child",
            "action": "reactivate",
            "viewport": {"width": 1024, "height": 768},
        },
        id="child_reactivate_1024",
    ),
    pytest.param(
        {
            "kind": "duck",
            "action": "deactivate",
            "viewport": {"width": 1024, "height": 768},
        },
        id="duck_deactivate_1024",
    ),
    pytest.param(
        {
            "kind": "duck",
            "action": "reactivate",
            "viewport": {"width": 1024, "height": 768},
        },
        id="duck_reactivate_1024",
    ),
    *[
        pytest.param(
            {
                "kind": kind,
                "action": action,
                "viewport": {"width": 1440, "height": 900},
            },
            id=f"{kind}_{action}_1440",
        )
        for kind in ("child", "duck")
        for action in ("deactivate", "reactivate")
    ],
]
ROSTER_SETTLED_CASES = [
    pytest.param(
        {
            "kind": "daily",
            "fault": "json-500",
            "viewport": {"width": 1024, "height": 768},
        },
        id="seed_daily_json_500_1024",
    ),
    pytest.param(
        {
            "kind": "auto",
            "fault": "json-500",
            "viewport": {"width": 1024, "height": 768},
        },
        id="auto_json_500_1024",
    ),
    *[
        pytest.param(
            {
                "kind": kind,
                "fault": fault,
                "viewport": {"width": 1024, "height": 768},
            },
            id=f"{kind}_{fault.replace('-', '_')}_1024",
        )
        for fault in ("html-502", "offline")
        for kind in ("daily", "auto")
    ],
    *[
        pytest.param(
            {
                "kind": kind,
                "fault": fault,
                "viewport": {"width": 1440, "height": 900},
            },
            id=f"{kind}_{fault.replace('-', '_')}_1440",
        )
        for fault in ("json-500", "html-502", "offline")
        for kind in ("daily", "auto")
    ],
]
ROSTER_DELAY_CASES = [
    pytest.param(
        {
            "kind": "daily",
            "viewport": {"width": 1024, "height": 768},
        },
        id="seed_daily_1024",
    ),
    pytest.param(
        {
            "kind": "auto",
            "viewport": {"width": 1024, "height": 768},
        },
        id="auto_1024",
    ),
    *[
        pytest.param(
            {
                "kind": kind,
                "viewport": {"width": 1440, "height": 900},
            },
            id=f"{kind}_1440",
        )
        for kind in ("daily", "auto")
    ],
]

ROSTER_CHILDREN = [
    {
        "id": 7,
        "name": "甲",
        "nickname": None,
        "avatar": None,
        "active": True,
        "deactivated_at": None,
        "future_roster_entries": 0,
        "has_active_conversation": False,
    },
    {
        "id": 8,
        "name": "乙",
        "nickname": None,
        "avatar": None,
        "active": True,
        "deactivated_at": None,
        "future_roster_entries": 0,
        "has_active_conversation": False,
    },
]


def _fulfill_json(route, body: object, *, status: int = 200) -> None:
    route.fulfill(
        status=status,
        content_type="application/json",
        body=json.dumps(body, ensure_ascii=False),
    )


def _assert_fixture_request(route, teacher_browser, *, method: str, path: str, query=None):
    request = route.request
    assert is_exact_fixture_url(request.url, teacher_browser.server.port)
    parsed = urlsplit(request.url)
    assert request.method == method
    assert parsed.path == path
    assert parse_qs(parsed.query, keep_blank_values=True) == (query or {})
    return request


def _settle_fault(route, fault: str) -> None:
    if fault == "json-500":
        route.fulfill(
            status=500,
            content_type="application/json",
            body=(
                '{"error":{"code":"INTERNAL_ERROR",'
                f'"message":"{RAW_SECRET}","field_errors":{{}},"retryable":true}}'
            ),
        )
        return
    if fault == "html-502":
        route.fulfill(
            status=502,
            content_type="text/html",
            body=f"<h1>{RAW_SECRET}</h1>",
        )
        return
    if fault == "offline":
        route.abort("internetdisconnected")
        return
    raise AssertionError(f"unknown Task 8 fault: {fault}")


def _open_teacher(teacher_browser, viewport, fragment: str = "#today"):
    context = teacher_browser.new_context()
    page = context.new_page()
    page.set_default_timeout(5_000)
    page.set_viewport_size(viewport)
    page.goto(
        f"{teacher_browser.server.base_url}/teacher.html{fragment}",
        wait_until="domcontentloaded",
    )
    return context, page


def _unlock_teacher(page, heading: str) -> None:
    page.get_by_label("设置教师 PIN", exact=True).fill(PIN)
    page.get_by_label("再次输入教师 PIN", exact=True).fill(PIN)
    page.get_by_role("button", name="设置并解锁", exact=True).click()
    page.get_by_role("heading", name=heading, exact=True).wait_for()


def _assert_raw_secret_absent(page) -> None:
    assert RAW_SECRET not in page.locator("body").inner_text()
    assert RAW_SECRET not in page.evaluate("document.documentElement.outerHTML")


def _assert_visible_outline(locator) -> None:
    style = locator.evaluate(
        """node => {
          const value = getComputedStyle(node);
          return {
            focused: document.activeElement === node,
            style: value.outlineStyle,
            width: parseFloat(value.outlineWidth),
            color: value.outlineColor,
            active: document.activeElement ? {
              tag: document.activeElement.tagName,
              id: document.activeElement.id,
              className: document.activeElement.className,
              text: document.activeElement.textContent,
            } : null,
          };
        }"""
    )
    assert style["focused"] is True, style
    assert style["style"] != "none"
    assert style["width"] > 0
    assert style["color"] not in {"transparent", "rgba(0, 0, 0, 0)"}


def _resource_spec(kind: str, active: bool) -> dict:
    if kind == "child":
        return {
            "fragment": "#children",
            "heading": "幼儿管理",
            "collection_path": "/api/children",
            "id": 7,
            "name": "小雨",
            "display": "雨雨",
            "row": {
                "id": 7,
                "name": "小雨",
                "nickname": "雨雨",
                "avatar": None,
                "active": active,
                "deactivated_at": None if active else "2026-08-28T01:00:00Z",
                "future_roster_entries": 2,
                "has_active_conversation": False,
            },
        }
    if kind == "duck":
        return {
            "fragment": "#ducks",
            "heading": "小鸭管理",
            "collection_path": "/api/ducks",
            "id": 9,
            "name": "团团",
            "display": "团团",
            "row": {
                "id": 9,
                "name": "团团",
                "avatar": None,
                "status": "健康",
                "note": None,
                "active": active,
                "deactivated_at": None if active else "2026-08-28T01:00:00Z",
                "historical_feeding_log_count": 3,
            },
        }
    raise AssertionError(f"unknown resource kind: {kind}")


def _activate_resource_action(page, spec: dict, action: str):
    label = (
        f"停用：{spec['display']}"
        if action == "deactivate"
        else f"恢复：{spec['display']}"
    )
    launcher = page.get_by_role("button", name=label, exact=True)
    launcher.wait_for()
    launcher.evaluate("node => { window.__task8StateLauncher = node; }")
    launcher.focus()
    page.keyboard.press("Enter")
    if action == "deactivate":
        dialog = page.get_by_role(
            "dialog", name=f"停用{spec['display']}", exact=True
        )
        dialog.wait_for()
        confirm = dialog.get_by_role("button", name="确认停用", exact=True)
        confirm.focus()
        page.keyboard.press("Enter")
    return launcher


def _open_roster_dialog(page, kind: str):
    launcher_name = "安排当日" if kind == "daily" else "自动生成"
    dialog_name = "安排当日值日" if kind == "daily" else "自动生成排班"
    other_dialog_name = "自动生成排班" if kind == "daily" else "安排当日值日"
    first_field = "排班日期" if kind == "daily" else "自动排班开始日期"
    launcher = page.get_by_role("button", name=launcher_name, exact=True)
    launcher.wait_for()
    launcher.evaluate("node => { window.__task8RosterLauncher = node; }")
    launcher.focus()
    page.keyboard.press("Enter")
    dialog = page.get_by_role("dialog", name=dialog_name, exact=True)
    dialog.wait_for()
    assert page.get_by_role(
        "dialog", name=other_dialog_name, exact=True
    ).count() == 0
    _assert_visible_outline(dialog.get_by_label(first_field, exact=True))
    return launcher, dialog


def _fill_roster_dialog(dialog, kind: str) -> dict:
    if kind == "daily":
        dialog.get_by_label("排班日期", exact=True).fill("2026-08-29")
        dialog.get_by_label("手动排班周期", exact=True).fill("  2026-W35  ")
        dialog.get_by_label("值日幼儿 1", exact=True).select_option("7")
        dialog.get_by_label("值日幼儿 2", exact=True).select_option("8")
    else:
        dialog.get_by_label("自动排班开始日期", exact=True).fill("2026-08-31")
        dialog.get_by_label("自动排班天数", exact=True).fill("2")
        dialog.get_by_label("自动排班周期", exact=True).fill("  2026-W36  ")
        dialog.get_by_label("替换已有排班", exact=True).check()
    return _roster_dialog_values(dialog, kind)


def _roster_dialog_values(dialog, kind: str) -> dict:
    if kind == "daily":
        return {
            "date": dialog.get_by_label("排班日期", exact=True).input_value(),
            "cycle": dialog.get_by_label(
                "手动排班周期", exact=True
            ).input_value(),
            "child_1": dialog.get_by_label(
                "值日幼儿 1", exact=True
            ).input_value(),
            "child_2": dialog.get_by_label(
                "值日幼儿 2", exact=True
            ).input_value(),
        }
    return {
        "start": dialog.get_by_label(
            "自动排班开始日期", exact=True
        ).input_value(),
        "days": dialog.get_by_label("自动排班天数", exact=True).input_value(),
        "cycle": dialog.get_by_label("自动排班周期", exact=True).input_value(),
        "replace": dialog.get_by_label("替换已有排班", exact=True).is_checked(),
    }


def _assert_valid_request_id(value: str | None) -> None:
    assert value is not None
    parsed = UUID(value)
    assert str(parsed) == value


@pytest.mark.parametrize("case", READ_CASES)
def test_teacher_representative_read_validators_cover_missing_transport_faults(
    teacher_browser, case
):
    surface = case["surface"]
    fault = case["fault"]
    calls = {
        "today_roster": 0,
        "today_pending": 0,
        "today_processing": 0,
        "today_failed": 0,
    }
    fragment = "#today" if surface == "today_roster" else "#review"
    _context, page = _open_teacher(teacher_browser, case["viewport"], fragment)
    page_errors: list[str] = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))

    def roster_handler(route):
        _assert_fixture_request(
            route,
            teacher_browser,
            method="GET",
            path="/api/roster/today",
        )
        calls["today_roster"] += 1
        if surface == "today_roster" and calls["today_roster"] == 1:
            _settle_fault(route, fault)
        else:
            _fulfill_json(route, [])

    def queue_handler(key, queue):
        def handler(route):
            _assert_fixture_request(
                route,
                teacher_browser,
                method="GET",
                path="/api/conversations",
                query={"queue": [queue]},
            )
            calls[key] += 1
            _fulfill_json(route, [])

        return handler

    def review_queue_handler(route):
        _assert_fixture_request(
            route,
            teacher_browser,
            method="GET",
            path="/api/conversations",
            query={"queue": ["pending"]},
        )
        calls["review_pending"] = calls.get("review_pending", 0) + 1
        if calls["review_pending"] == 1:
            _settle_fault(route, fault)
        else:
            _fulfill_json(route, [])

    if surface == "today_roster":
        page.route(
            f"{teacher_browser.server.base_url}/api/roster/today",
            roster_handler,
        )
        for key, queue in (
            ("today_pending", "pending"),
            ("today_processing", "processing"),
            ("today_failed", "failed"),
        ):
            page.route(
                f"{teacher_browser.server.base_url}/api/conversations?queue={queue}",
                queue_handler(key, queue),
            )
        _unlock_teacher(page, "今日任务")
        roster_panel = page.locator('[data-today-panel="roster"]')
        roster_panel.get_by_text("加载失败，请重试。", exact=True).wait_for()
        assert roster_panel.get_by_text("今天还未排班", exact=True).count() == 0
        assert roster_panel.get_by_text("已加载", exact=False).count() == 0
        assert calls == {
            "today_roster": 1,
            "today_pending": 1,
            "today_processing": 1,
            "today_failed": 1,
        }
        _assert_raw_secret_absent(page)
        roster_panel.get_by_role(
            "button", name="重新加载今日值日生", exact=True
        ).click()
        roster_panel.get_by_text("今天还未排班", exact=True).wait_for()
        assert calls == {
            "today_roster": 2,
            "today_pending": 1,
            "today_processing": 1,
            "today_failed": 1,
        }
    else:
        page.route(
            f"{teacher_browser.server.base_url}/api/conversations?queue=pending",
            review_queue_handler,
        )
        _unlock_teacher(page, "日记审阅")
        queue_panel = page.locator('[data-review-panel="queue"]')
        detail_panel = page.locator('[data-review-panel="detail"]')
        queue_panel.get_by_text("加载失败，请重试。", exact=True).wait_for()
        assert queue_panel.get_by_text("暂无待审阅会话", exact=True).count() == 0
        assert detail_panel.get_by_text(
            "请从左侧待审阅队列选择一条会话。", exact=True
        ).count() == 1
        assert calls["review_pending"] == 1
        _assert_raw_secret_absent(page)
        queue_panel.get_by_role(
            "button", name="重新加载队列", exact=True
        ).click()
        queue_panel.get_by_text("暂无待审阅会话", exact=True).wait_for()
        assert calls["review_pending"] == 2
    _assert_raw_secret_absent(page)
    assert page_errors == []


@pytest.mark.parametrize("case", TIMEOUT_CASES)
def test_teacher_review_put_timeout_preserves_dirty_values_and_restores_focus(
    teacher_browser, case
):
    context = teacher_browser.new_context()
    page = context.new_page()
    page.set_default_timeout(5_000)
    page.set_viewport_size(case["viewport"])
    page.clock.install(time=1_700_000_000)
    page.add_init_script(
        """
        (() => {
          Object.defineProperty(window, 'DuckAPI', {
            configurable: true,
            get() { return undefined; },
            set(value) {
              const originalRequest = value.request;
              const wrappedRequest = async function(path, options) {
                if (path === '/api/conversations/42/review') {
                  window.__task8ReviewRequest = {
                    timeoutMs: options.timeoutMs,
                    sequenceKey: options.sequenceKey,
                  };
                }
                try {
                  return await originalRequest.call(value, path, options);
                } catch (error) {
                  if (path === '/api/conversations/42/review') {
                    const table = Object.getOwnPropertyDescriptors(error);
                    const ownData = {};
                    for (const key of Reflect.ownKeys(table)) {
                      const entry = table[key];
                      if (typeof key === 'string' && entry && 'value' in entry) {
                        ownData[key] = entry.value;
                      }
                    }
                    window.__task8ReviewRejection = ownData;
                  }
                  throw error;
                }
              };
              Object.defineProperty(window, 'DuckAPI', {
                configurable: true,
                value: Object.freeze({...value, request: wrappedRequest}),
              });
            },
          });
        })();
        """
    )
    queue_calls = 0
    detail_calls = 0
    held_routes = []
    captured_requests = []
    page_errors: list[str] = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))

    def queue_handler(route):
        nonlocal queue_calls
        _assert_fixture_request(
            route,
            teacher_browser,
            method="GET",
            path="/api/conversations",
            query={"queue": ["pending"]},
        )
        queue_calls += 1
        _fulfill_json(route, [queue_row()])

    def detail_handler(route):
        nonlocal detail_calls
        _assert_fixture_request(
            route,
            teacher_browser,
            method="GET",
            path="/api/conversations/42",
        )
        detail_calls += 1
        _fulfill_json(route, review_detail())

    save_url = f"{teacher_browser.server.base_url}/api/conversations/42/review"

    def save_handler(route):
        request = _assert_fixture_request(
            route,
            teacher_browser,
            method="PUT",
            path="/api/conversations/42/review",
        )
        captured_requests.append(
            {
                "body": request.post_data,
                "headers": dict(request.headers),
            }
        )
        held_routes.append(route)

    page.route(
        f"{teacher_browser.server.base_url}/api/conversations?queue=pending",
        queue_handler,
    )
    page.route(
        f"{teacher_browser.server.base_url}/api/conversations/42",
        detail_handler,
    )
    page.route(save_url, save_handler)
    try:
        page.goto(
            f"{teacher_browser.server.base_url}/teacher.html#review?conversation_id=42",
            wait_until="domcontentloaded",
        )
        _unlock_teacher(page, "日记审阅")
        form = page.locator("[data-review-form]")
        form.wait_for()
        insight = page.get_by_label("教育洞察", exact=True)
        typed = "  Task8 超时保留值  "
        insight.fill(typed)
        draft = page.get_by_role("button", name="保存草稿", exact=True)
        draft.evaluate("node => { window.__task8OriginalDraft = node; }")
        draft.focus()
        page.keyboard.press("Enter")
        page.wait_for_function("() => document.querySelector('.review-save-status')?.textContent === '正在保存…'")
        page.wait_for_timeout(0)
        assert len(held_routes) == 1
        assert len(captured_requests) == 1
        payload = json.loads(captured_requests[0]["body"])
        assert payload["revision"] == 2
        assert payload["action"] == "save_draft"
        assert payload["insight"] == typed.strip()
        assert page.evaluate("window.__task8ReviewRequest") == {
            "timeoutMs": 15_000,
            "sequenceKey": "teacher-review-mutation",
        }
        assert queue_calls == 1
        assert detail_calls == 1

        page.clock.fast_forward(15_001)
        page.get_by_text("保存失败，请稍后重试。", exact=True).wait_for()
        rejection = page.evaluate(
            """() => ({
              code: window.__task8ReviewRejection?.code,
              hasErrorField: Object.prototype.hasOwnProperty.call(
                window.__task8ReviewRejection || {}, 'error'),
              hasExportedRethrow: '__task8ReviewRethrown' in window,
            })"""
        )
        assert rejection == {
            "code": "REQUEST_TIMEOUT",
            "hasErrorField": False,
            "hasExportedRethrow": False,
        }
        assert insight.input_value() == typed
        status = page.locator(".review-save-status")
        assert status.inner_text() == "保存失败，修改仍未保存"
        assert status.get_attribute("data-save-state") == "failure"
        assert form.locator("input, textarea, select, button").evaluate_all(
            "nodes => nodes.every(node => !node.disabled)"
        )
        assert draft.evaluate("node => node === window.__task8OriginalDraft")
        _assert_visible_outline(draft)
        assert page.get_by_text("全部修改已保存", exact=True).count() == 0
        assert page.get_by_text("审阅已确认", exact=True).count() == 0
        assert queue_calls == 1
        assert detail_calls == 1
        assert page.evaluate(
            """() => {
              const event = new Event('beforeunload', {cancelable: true});
              window.dispatchEvent(event);
              return event.defaultPrevented;
            }"""
        )
        assert page_errors == []
    finally:
        for held in tuple(held_routes):
            try:
                held.abort("failed")
            except Exception:
                pass
        page.unroute(save_url, save_handler)
        held_routes.clear()


@pytest.mark.parametrize("case", STATE_SETTLED_CASES)
def test_teacher_resource_state_settled_faults_never_claim_success(
    teacher_browser, case
):
    kind = case["kind"]
    action = case["action"]
    starts_active = action == "deactivate"
    spec = _resource_spec(kind, starts_active)
    context = teacher_browser.new_context()
    page = context.new_page()
    page.set_default_timeout(5_000)
    page.set_viewport_size(case["viewport"])
    page_errors: list[str] = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    collection_calls = 0
    mutation_records = []

    def collection_handler(route):
        nonlocal collection_calls
        _assert_fixture_request(
            route,
            teacher_browser,
            method="GET",
            path=spec["collection_path"],
            query={"include_inactive": ["true"]},
        )
        collection_calls += 1
        _fulfill_json(route, [spec["row"]])

    mutation_path = f"{spec['collection_path']}/{spec['id']}/{action}"

    def mutation_handler(route):
        request = _assert_fixture_request(
            route,
            teacher_browser,
            method="POST",
            path=mutation_path,
        )
        mutation_records.append(
            {
                "method": request.method,
                "path": urlsplit(request.url).path,
                "query": parse_qs(urlsplit(request.url).query),
                "body": request.post_data,
                "request_id": request.headers.get("x-request-id"),
            }
        )
        _settle_fault(route, case["fault"])

    page.route(
        f"{teacher_browser.server.base_url}{spec['collection_path']}?include_inactive=true",
        collection_handler,
    )
    page.route(
        f"{teacher_browser.server.base_url}{mutation_path}",
        mutation_handler,
    )
    page.goto(
        f"{teacher_browser.server.base_url}/teacher.html{spec['fragment']}",
        wait_until="domcontentloaded",
    )
    _unlock_teacher(page, spec["heading"])
    launcher = _activate_resource_action(page, spec, action)
    expected_copy = (
        "暂时无法停用该幼儿，请刷新后重试。"
        if kind == "child" and action == "deactivate"
        else "操作失败，请稍后重试。"
    )
    page.get_by_text(expected_copy, exact=True).wait_for()

    assert mutation_records == [
        {
            "method": "POST",
            "path": mutation_path,
            "query": {},
            "body": None,
            "request_id": None,
        }
    ]
    assert collection_calls == 1
    assert page.get_by_text("启用中" if starts_active else "已停用", exact=True).count() == 1
    assert page.locator("[data-undo-toast]").count() == 0
    assert page.get_by_text("已停用，可在 10 秒内撤销。", exact=True).count() == 0
    assert launcher.evaluate("node => node === window.__task8StateLauncher")
    assert launcher.is_enabled()
    _assert_visible_outline(launcher)
    _assert_raw_secret_absent(page)
    assert page_errors == []


@pytest.mark.parametrize("case", STATE_DELAY_CASES)
def test_teacher_resource_state_delay_is_single_flight(teacher_browser, case):
    kind = case["kind"]
    action = case["action"]
    current_active = action == "deactivate"
    spec = _resource_spec(kind, current_active)
    context = teacher_browser.new_context()
    page = context.new_page()
    page.set_default_timeout(5_000)
    page.set_viewport_size(case["viewport"])
    page_errors: list[str] = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    collection_calls = 0
    mutation_records = []
    held_routes = []

    def collection_handler(route):
        nonlocal collection_calls
        _assert_fixture_request(
            route,
            teacher_browser,
            method="GET",
            path=spec["collection_path"],
            query={"include_inactive": ["true"]},
        )
        collection_calls += 1
        _fulfill_json(route, [_resource_spec(kind, current_active)["row"]])

    mutation_path = f"{spec['collection_path']}/{spec['id']}/{action}"

    def mutation_handler(route):
        request = _assert_fixture_request(
            route,
            teacher_browser,
            method="POST",
            path=mutation_path,
        )
        mutation_records.append(
            {
                "method": request.method,
                "path": urlsplit(request.url).path,
                "query": parse_qs(urlsplit(request.url).query),
                "body": request.post_data,
                "request_id": request.headers.get("x-request-id"),
            }
        )
        held_routes.append(route)

    mutation_url = f"{teacher_browser.server.base_url}{mutation_path}"
    page.route(
        f"{teacher_browser.server.base_url}{spec['collection_path']}?include_inactive=true",
        collection_handler,
    )
    page.route(mutation_url, mutation_handler)
    try:
        page.goto(
            f"{teacher_browser.server.base_url}/teacher.html{spec['fragment']}",
            wait_until="domcontentloaded",
        )
        _unlock_teacher(page, spec["heading"])
        launcher = _activate_resource_action(page, spec, action)
        page.wait_for_timeout(0)
        assert len(held_routes) == 1
        assert len(mutation_records) == 1
        assert launcher.is_disabled()

        page.keyboard.press("Enter")
        page.keyboard.press("Space")
        launcher.evaluate("node => { node.click(); node.click(); }")
        page.wait_for_timeout(0)
        assert len(held_routes) == 1
        assert len(mutation_records) == 1
        assert collection_calls == 1
        assert page.get_by_text(
            "启用中" if current_active else "已停用", exact=True
        ).count() == 1
        assert page.locator("[data-undo-toast]").count() == 0
        assert page.get_by_text("操作失败，请稍后重试。", exact=True).count() == 0
        assert page.get_by_text(
            "暂时无法停用该幼儿，请刷新后重试。", exact=True
        ).count() == 0

        current_active = action == "reactivate"
        acknowledgement = {
            "id": spec["id"],
            "kind": kind,
            "name": spec["name"],
            "active": current_active,
            "deactivated_at": None if current_active else "2026-08-29T01:00:00Z",
            "affected_future_roster_entries": (
                spec["row"].get("future_roster_entries", 0)
            ),
            "changed": True,
        }
        held = held_routes.pop()
        _fulfill_json(held, acknowledgement)
        next_label = (
            f"停用：{spec['display']}"
            if current_active
            else f"恢复：{spec['display']}"
        )
        page.get_by_role("button", name=next_label, exact=True).wait_for()
        assert collection_calls == 2
        assert len(mutation_records) == 1
        if action == "deactivate":
            page.get_by_role(
                "button", name=f"撤销停用：{spec['display']}", exact=True
            ).wait_for()
        assert page_errors == []
    finally:
        for held in tuple(held_routes):
            try:
                held.abort("failed")
            except Exception:
                pass
        page.unroute(mutation_url, mutation_handler)
        held_routes.clear()


@pytest.mark.parametrize("case", ROSTER_SETTLED_CASES)
def test_teacher_roster_settled_faults_preserve_snapshot_and_request_id(
    teacher_browser, case
):
    context = teacher_browser.new_context()
    page = context.new_page()
    page.set_default_timeout(5_000)
    page.set_viewport_size(case["viewport"])
    page_errors: list[str] = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    collection_calls = {"roster": 0, "children": 0}
    mutation_records = []

    def roster_handler(route):
        _assert_fixture_request(
            route, teacher_browser, method="GET", path="/api/roster"
        )
        collection_calls["roster"] += 1
        rows = []
        if collection_calls["roster"] > 1:
            dates = (
                [("2026-08-29", "2026-W35")]
                if case["kind"] == "daily"
                else [
                    ("2026-08-31", "2026-W36"),
                    ("2026-09-01", "2026-W36"),
                ]
            )
            rows = [
                {
                    "id": index,
                    "cycle": cycle,
                    "date": date,
                    "child_id": child_id,
                }
                for index, (date, cycle, child_id) in enumerate(
                    (
                        (date, cycle, child_id)
                        for date, cycle in dates
                        for child_id in (7, 8)
                    ),
                    start=1,
                )
            ]
        _fulfill_json(route, rows)

    def children_handler(route):
        _assert_fixture_request(
            route,
            teacher_browser,
            method="GET",
            path="/api/children",
            query={"include_inactive": ["true"]},
        )
        collection_calls["children"] += 1
        _fulfill_json(route, ROSTER_CHILDREN)

    mutation_path = (
        "/api/roster/2026-08-29"
        if case["kind"] == "daily"
        else "/api/roster/auto"
    )
    mutation_method = "PUT" if case["kind"] == "daily" else "POST"

    def mutation_handler(route):
        request = _assert_fixture_request(
            route,
            teacher_browser,
            method=mutation_method,
            path=mutation_path,
        )
        mutation_records.append(
            {
                "body": request.post_data,
                "request_id": request.headers.get("x-request-id"),
            }
        )
        if len(mutation_records) == 1:
            _settle_fault(route, case["fault"])
            return
        body = json.loads(request.post_data)
        acknowledgement = (
            {
                "request_id": body["request_id"],
                "date": "2026-08-29",
                "cycle": body["cycle"],
                "child_ids": body["child_ids"],
                "replayed": True,
            }
            if case["kind"] == "daily"
            else {
                "request_id": body["request_id"],
                "schedule": [
                    {"date": "2026-08-31", "child_ids": [7, 8]},
                    {"date": "2026-09-01", "child_ids": [7, 8]},
                ],
                "replayed": True,
            }
        )
        _fulfill_json(route, acknowledgement)

    page.route(f"{teacher_browser.server.base_url}/api/roster", roster_handler)
    page.route(
        f"{teacher_browser.server.base_url}/api/children?include_inactive=true",
        children_handler,
    )
    page.route(
        f"{teacher_browser.server.base_url}{mutation_path}", mutation_handler
    )
    page.goto(
        f"{teacher_browser.server.base_url}/teacher.html#roster",
        wait_until="domcontentloaded",
    )
    _unlock_teacher(page, "值日排班")
    page.get_by_text("暂无排班", exact=True).wait_for()
    launcher, dialog = _open_roster_dialog(page, case["kind"])
    original_values = _fill_roster_dialog(dialog, case["kind"])
    action_name = "保存当日排班" if case["kind"] == "daily" else "生成排班"
    action = dialog.get_by_role("button", name=action_name, exact=True)
    action.evaluate("node => { window.__task8RosterAction = node; }")
    action.focus()
    page.keyboard.press("Enter")
    dialog.get_by_text(
        "排班保存失败，请使用相同内容重试。", exact=True
    ).wait_for()

    assert len(mutation_records) == 1
    body = json.loads(mutation_records[0]["body"])
    expected_body = (
        {
            "request_id": mutation_records[0]["request_id"],
            "cycle": "2026-W35",
            "child_ids": [7, 8],
        }
        if case["kind"] == "daily"
        else {
            "request_id": mutation_records[0]["request_id"],
            "start_date": "2026-08-31",
            "days": 2,
            "cycle": "2026-W36",
            "replace_existing": True,
        }
    )
    assert body == expected_body
    _assert_valid_request_id(body["request_id"])
    assert _roster_dialog_values(dialog, case["kind"]) == original_values
    assert dialog.locator("input, textarea, select, button").evaluate_all(
        "nodes => nodes.length > 0 && nodes.every(node => !node.disabled)"
    )
    assert action.evaluate("node => node === window.__task8RosterAction")
    _assert_visible_outline(action)
    assert collection_calls == {"roster": 1, "children": 1}
    assert page.get_by_text("排班已保存", exact=True).count() == 0
    _assert_raw_secret_absent(page)
    assert page_errors == []

    page.keyboard.press("Enter")
    page.get_by_text("排班已保存", exact=True).wait_for()
    success_projection = (
        "2026-08-29 · 2026-W35 · 甲、乙"
        if case["kind"] == "daily"
        else "2026-08-31 · 2026-W36 · 甲、乙"
    )
    page.get_by_text(success_projection, exact=True).wait_for()
    dialog.wait_for(state="detached")
    assert len(mutation_records) == 2
    assert mutation_records[1]["body"] == mutation_records[0]["body"]
    assert mutation_records[1]["request_id"] == mutation_records[0]["request_id"]
    assert json.loads(mutation_records[1]["body"])["request_id"] == body[
        "request_id"
    ]
    assert collection_calls == {"roster": 2, "children": 2}
    assert launcher.evaluate("node => node === window.__task8RosterLauncher")
    _assert_visible_outline(launcher)
    _assert_raw_secret_absent(page)
    assert page_errors == []


@pytest.mark.parametrize("case", ROSTER_DELAY_CASES)
def test_teacher_roster_delay_is_single_flight(teacher_browser, case):
    context = teacher_browser.new_context()
    page = context.new_page()
    page.set_default_timeout(5_000)
    page.set_viewport_size(case["viewport"])
    page_errors: list[str] = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    collection_calls = {"roster": 0, "children": 0}
    mutation_records = []
    held_routes = []

    def roster_handler(route):
        _assert_fixture_request(
            route, teacher_browser, method="GET", path="/api/roster"
        )
        collection_calls["roster"] += 1
        rows = []
        if collection_calls["roster"] > 1:
            dates = (
                [("2026-08-29", "2026-W35")]
                if case["kind"] == "daily"
                else [
                    ("2026-08-31", "2026-W36"),
                    ("2026-09-01", "2026-W36"),
                ]
            )
            rows = [
                {
                    "id": index,
                    "cycle": cycle,
                    "date": date,
                    "child_id": child_id,
                }
                for index, (date, cycle, child_id) in enumerate(
                    (
                        (date, cycle, child_id)
                        for date, cycle in dates
                        for child_id in (7, 8)
                    ),
                    start=1,
                )
            ]
        _fulfill_json(route, rows)

    def children_handler(route):
        _assert_fixture_request(
            route,
            teacher_browser,
            method="GET",
            path="/api/children",
            query={"include_inactive": ["true"]},
        )
        collection_calls["children"] += 1
        _fulfill_json(route, ROSTER_CHILDREN)

    mutation_path = (
        "/api/roster/2026-08-29"
        if case["kind"] == "daily"
        else "/api/roster/auto"
    )
    mutation_method = "PUT" if case["kind"] == "daily" else "POST"

    def mutation_handler(route):
        request = _assert_fixture_request(
            route,
            teacher_browser,
            method=mutation_method,
            path=mutation_path,
        )
        mutation_records.append(
            {
                "body": request.post_data,
                "request_id": request.headers.get("x-request-id"),
            }
        )
        held_routes.append(route)

    mutation_url = f"{teacher_browser.server.base_url}{mutation_path}"
    page.route(f"{teacher_browser.server.base_url}/api/roster", roster_handler)
    page.route(
        f"{teacher_browser.server.base_url}/api/children?include_inactive=true",
        children_handler,
    )
    page.route(mutation_url, mutation_handler)
    try:
        page.goto(
            f"{teacher_browser.server.base_url}/teacher.html#roster",
            wait_until="domcontentloaded",
        )
        _unlock_teacher(page, "值日排班")
        page.get_by_text("暂无排班", exact=True).wait_for()
        launcher, dialog = _open_roster_dialog(page, case["kind"])
        original_values = _fill_roster_dialog(dialog, case["kind"])
        action_name = "保存当日排班" if case["kind"] == "daily" else "生成排班"
        action = dialog.get_by_role("button", name=action_name, exact=True)
        action.focus()
        page.keyboard.press("Enter")
        page.wait_for_timeout(0)
        assert len(held_routes) == 1
        assert len(mutation_records) == 1
        original_body = mutation_records[0]["body"]
        original_request_id = mutation_records[0]["request_id"]
        body = json.loads(original_body)
        expected_body = (
            {
                "request_id": original_request_id,
                "cycle": "2026-W35",
                "child_ids": [7, 8],
            }
            if case["kind"] == "daily"
            else {
                "request_id": original_request_id,
                "start_date": "2026-08-31",
                "days": 2,
                "cycle": "2026-W36",
                "replace_existing": True,
            }
        )
        assert body == expected_body
        _assert_valid_request_id(original_request_id)
        assert dialog.locator("input, textarea, select, button").evaluate_all(
            "nodes => nodes.length > 0 && nodes.every(node => node.disabled)"
        )

        page.keyboard.press("Enter")
        page.keyboard.press("Space")
        dialog.locator("form").evaluate(
            "form => form.dispatchEvent(new Event('submit', {bubbles: true, cancelable: true}))"
        )
        page.wait_for_timeout(0)
        assert len(held_routes) == 1
        assert len(mutation_records) == 1
        assert mutation_records[0] == {
            "body": original_body,
            "request_id": original_request_id,
        }
        assert _roster_dialog_values(dialog, case["kind"]) == original_values
        assert collection_calls == {"roster": 1, "children": 1}
        assert page.get_by_text("排班已保存", exact=True).count() == 0
        assert page.get_by_text(
            "排班保存失败，请使用相同内容重试。", exact=True
        ).count() == 0

        held = held_routes.pop()
        acknowledgement = (
            {
                "request_id": body["request_id"],
                "date": "2026-08-29",
                "cycle": body["cycle"],
                "child_ids": body["child_ids"],
                "replayed": False,
            }
            if case["kind"] == "daily"
            else {
                "request_id": body["request_id"],
                "schedule": [
                    {"date": "2026-08-31", "child_ids": [7, 8]},
                    {"date": "2026-09-01", "child_ids": [7, 8]},
                ],
                "replayed": False,
            }
        )
        _fulfill_json(held, acknowledgement)
        page.get_by_text("排班已保存", exact=True).wait_for()
        success_projection = (
            "2026-08-29 · 2026-W35 · 甲、乙"
            if case["kind"] == "daily"
            else "2026-08-31 · 2026-W36 · 甲、乙"
        )
        page.get_by_text(success_projection, exact=True).wait_for()
        dialog.wait_for(state="detached")
        assert collection_calls == {"roster": 2, "children": 2}
        assert len(mutation_records) == 1
        assert held_routes == []
        assert launcher.evaluate("node => node === window.__task8RosterLauncher")
        _assert_visible_outline(launcher)
        assert page_errors == []
    finally:
        for held in tuple(held_routes):
            try:
                held.abort("failed")
            except Exception:
                pass
        page.unroute(mutation_url, mutation_handler)
        held_routes.clear()


@pytest.mark.parametrize(
    "viewport",
    [{"width": 1024, "height": 768}, {"width": 1440, "height": 900}],
    ids=["1024x768", "1440x900"],
)
def test_monthly_context_failure_disables_only_monthly_entry(
    teacher_browser,
    viewport,
):
    """A failed independent calendar capability must not take down roster fallbacks."""
    context = teacher_browser.new_context()
    page = context.new_page()
    page.set_default_timeout(5_000)
    page.set_viewport_size(viewport)
    runtime_calls = 0
    page_errors: list[str] = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))

    def runtime(route):
        nonlocal runtime_calls
        runtime_calls += 1
        route.fulfill(
            status=500,
            content_type="application/json",
            body=json.dumps({"error": {
                "code": "INTERNAL_ERROR",
                "message": RAW_SECRET,
                "field_errors": {},
                "retryable": True,
                "request_id": "runtime-failure",
            }}),
        )

    page.route(f"{teacher_browser.server.base_url}/api/runtime/context", runtime)
    page.route(
        f"{teacher_browser.server.base_url}/api/roster",
        lambda route: _fulfill_json(route, []),
    )
    page.route(
        f"{teacher_browser.server.base_url}/api/children?include_inactive=true",
        lambda route: _fulfill_json(route, ROSTER_CHILDREN),
    )
    page.goto(
        f"{teacher_browser.server.base_url}/teacher.html#roster",
        wait_until="domcontentloaded",
    )
    _unlock_teacher(page, "值日排班")
    page.get_by_text(
        "无法读取当前业务日期，本月录入暂不可用；单日安排和自动生成仍可使用。",
        exact=True,
    ).wait_for()

    monthly = page.get_by_role("button", name="录入本月名单", exact=True)
    manual = page.get_by_role("button", name="安排当日", exact=True)
    automatic = page.get_by_role("button", name="自动生成", exact=True)
    assert runtime_calls == 1
    assert monthly.is_disabled()
    assert not manual.is_disabled()
    assert not automatic.is_disabled()
    manual.click()
    manual_dialog = page.get_by_role("dialog", name="安排当日值日", exact=True)
    manual_dialog.wait_for()
    page.keyboard.press("Escape")
    manual_dialog.wait_for(state="detached")
    automatic.click()
    auto_dialog = page.get_by_role("dialog", name="自动生成排班", exact=True)
    auto_dialog.wait_for()
    page.keyboard.press("Escape")
    auto_dialog.wait_for(state="detached")
    _assert_raw_secret_absent(page)
    assert page_errors == []


@pytest.mark.parametrize(
    "viewport",
    [{"width": 1024, "height": 768}, {"width": 1440, "height": 900}],
    ids=["1024x768", "1440x900"],
)
def test_monthly_conflict_requires_new_overwrite_id_then_reuses_it_on_failure(
    teacher_browser,
    viewport,
):
    """Conflict acknowledgement must never turn the original UUID into overwrite semantics."""
    context = teacher_browser.new_context()
    page = context.new_page()
    page.set_default_timeout(5_000)
    page.set_viewport_size(viewport)
    page_errors: list[str] = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    calls: list[dict] = []
    final_body = None

    page.route(
        f"{teacher_browser.server.base_url}/api/runtime/context",
        lambda route: _fulfill_json(route, {
            "timezone": "Asia/Shanghai",
            "business_date": "2026-09-02",
            "week_start": "2026-08-31",
            "week_end_exclusive": "2026-09-07",
        }),
    )
    page.route(
        f"{teacher_browser.server.base_url}/api/children?include_inactive=true",
        lambda route: _fulfill_json(route, ROSTER_CHILDREN),
    )

    def roster(route):
        rows = []
        if final_body is not None:
            rows = [
                {
                    "id": index,
                    "cycle": final_body["cycle"],
                    "date": entry["date"],
                    "child_id": child_id,
                }
                for index, (entry, child_id) in enumerate(
                    (
                        (entry, child_id)
                        for entry in final_body["entries"]
                        for child_id in entry["child_ids"]
                    ),
                    start=1,
                )
            ]
        _fulfill_json(route, rows)

    def monthly(route):
        nonlocal final_body
        request = _assert_fixture_request(
            route,
            teacher_browser,
            method="POST",
            path="/api/roster/month",
        )
        body = json.loads(request.post_data)
        calls.append({
            "body": body,
            "request_id": request.headers.get("x-request-id"),
        })
        if len(calls) == 1:
            _fulfill_json(route, {"error": {
                "code": "ROSTER_DATE_CONFLICT",
                "message": RAW_SECRET,
                "field_errors": {},
                "retryable": False,
                "request_id": body["request_id"],
            }}, status=409)
            return
        if len(calls) == 2:
            _fulfill_json(route, {"error": {
                "code": "INTERNAL_ERROR",
                "message": RAW_SECRET,
                "field_errors": {},
                "retryable": True,
                "request_id": body["request_id"],
            }}, status=500)
            return
        final_body = body
        _fulfill_json(route, {
            "request_id": body["request_id"],
            "month": body["month"],
            "schedule": [
                {
                    "date": entry["date"],
                    "cycle": body["cycle"],
                    "child_ids": entry["child_ids"],
                }
                for entry in body["entries"]
            ],
            "replayed": True,
        })

    page.route(f"{teacher_browser.server.base_url}/api/roster", roster)
    page.route(f"{teacher_browser.server.base_url}/api/roster/month", monthly)
    page.goto(
        f"{teacher_browser.server.base_url}/teacher.html#roster",
        wait_until="domcontentloaded",
    )
    _unlock_teacher(page, "值日排班")
    launcher = page.get_by_role("button", name="录入本月名单", exact=True)
    page.wait_for_function("button => !button.disabled", arg=launcher.element_handle())
    launcher.click()
    dialog = page.get_by_role("dialog", name="录入本月搭档", exact=True)
    dialog.get_by_label("排班周期", exact=True).fill("2026-秋季")
    submit = dialog.get_by_role("button", name="保存本月排班", exact=True)
    submit.click()
    dialog.get_by_text(
        "目标日期已有排班，可确认覆盖这些日期。",
        exact=True,
    ).wait_for()
    overwrite = dialog.get_by_role("button", name="覆盖已有排班", exact=True)
    overwrite.click()
    dialog.get_by_text(
        "覆盖失败，请使用相同内容重试。",
        exact=True,
    ).wait_for()
    overwrite.click()
    dialog.wait_for(state="detached")

    assert len(calls) == 3
    first_id = calls[0]["body"]["request_id"]
    overwrite_id = calls[1]["body"]["request_id"]
    assert first_id != overwrite_id
    assert calls[2] == calls[1]
    assert calls[0]["body"]["replace_existing"] is False
    assert calls[1]["body"]["replace_existing"] is True
    assert all(call["request_id"] == call["body"]["request_id"] for call in calls)
    page.get_by_text("排班已保存", exact=True).wait_for()
    page.get_by_text("2026-09-01 · 2026-秋季 · 甲、乙", exact=True).wait_for()
    assert launcher.evaluate("button => document.activeElement === button")
    _assert_raw_secret_absent(page)
    assert page_errors == []


def test_late_monthly_context_after_navigation_cannot_pollute_the_next_route(
    teacher_browser,
):
    context = teacher_browser.new_context()
    page = context.new_page()
    page.set_default_timeout(5_000)
    page.set_viewport_size({"width": 1024, "height": 768})
    held = []
    page_errors: list[str] = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.route(
        f"{teacher_browser.server.base_url}/api/runtime/context",
        lambda route: held.append(route),
    )
    page.route(
        f"{teacher_browser.server.base_url}/api/roster",
        lambda route: _fulfill_json(route, []),
    )
    page.route(
        f"{teacher_browser.server.base_url}/api/children?include_inactive=true",
        lambda route: _fulfill_json(route, ROSTER_CHILDREN),
    )
    try:
        page.goto(
            f"{teacher_browser.server.base_url}/teacher.html#roster",
            wait_until="domcontentloaded",
        )
        _unlock_teacher(page, "值日排班")
        page.wait_for_function("() => window.location.hash === '#roster'")
        page.wait_for_function("() => document.querySelector('main') !== null")
        page.wait_for_timeout(0)
        assert len(held) == 1
        page.get_by_role("button", name="幼儿管理", exact=True).click()
        page.get_by_role("heading", name="幼儿管理", exact=True).wait_for()
        try:
            _fulfill_json(held.pop(), {
                "timezone": "Asia/Shanghai",
                "business_date": "2026-09-02",
                "week_start": "2026-08-31",
                "week_end_exclusive": "2026-09-07",
            })
        except Exception:
            pass
        page.wait_for_timeout(50)
        assert page.get_by_role("heading", name="幼儿管理", exact=True).count() == 1
        assert page.get_by_role("dialog", name="录入本月搭档", exact=True).count() == 0
        assert page.get_by_text(
            "可按选定月份批量录入搭档；单日安排和自动生成仍可独立使用。",
            exact=True,
        ).count() == 0
        assert page_errors == []
    finally:
        for route in held:
            try:
                route.abort("failed")
            except Exception:
                pass
