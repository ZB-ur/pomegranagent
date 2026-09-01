from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urlsplit

import pytest

from tests.browser.conftest import is_exact_fixture_url
from tests.browser.test_teacher_review_loading import queue_row, review_detail


PIN = "2468"
KEYBOARD_CASES = [
    pytest.param(
        {"viewport": {"width": 1024, "height": 768}},
        id="seed_keyboard_review_1024",
    ),
    pytest.param(
        {"viewport": {"width": 1440, "height": 900}},
        id="keyboard_review_1440",
    ),
]
DIRTY_DIALOG_CASES = [
    pytest.param(
        {"viewport": {"width": 1024, "height": 768}},
        id="seed_dirty_dialog_1024",
    ),
    pytest.param(
        {"viewport": {"width": 1440, "height": 900}},
        id="dirty_dialog_1440",
    ),
]
A11Y_ROUTE_CASES = [
    pytest.param(
        {
            "fragment": "today",
            "navigation": "今日任务",
            "heading": "今日任务",
            "settled": "暂无分析失败会话",
            "viewport": {"width": 1024, "height": 768},
        },
        id="seed_a11y_today_1024",
    ),
    pytest.param(
        {
            "fragment": "children",
            "navigation": "幼儿管理",
            "heading": "幼儿管理",
            "settled": "暂无幼儿",
            "viewport": {"width": 1024, "height": 768},
        },
        id="a11y_children_1024",
    ),
    pytest.param(
        {
            "fragment": "ducks",
            "navigation": "小鸭管理",
            "heading": "小鸭管理",
            "settled": "暂无小鸭",
            "viewport": {"width": 1024, "height": 768},
        },
        id="a11y_ducks_1024",
    ),
    pytest.param(
        {
            "fragment": "roster",
            "navigation": "值日排班",
            "heading": "值日排班",
            "settled": "暂无排班",
            "viewport": {"width": 1024, "height": 768},
        },
        id="a11y_roster_1024",
    ),
    pytest.param(
        {
            "fragment": "review",
            "navigation": "值日审阅",
            "heading": "值日审阅",
            "settled": "暂无待审阅会话",
            "viewport": {"width": 1024, "height": 768},
        },
        id="a11y_review_1024",
    ),
    pytest.param(
        {
            "fragment": "growth",
            "navigation": "能力成长曲线",
            "heading": "能力成长曲线",
            "settled": "请选择一名幼儿查看成长曲线。",
            "viewport": {"width": 1024, "height": 768},
        },
        id="a11y_growth_1024",
    ),
    pytest.param(
        {
            "fragment": "search",
            "navigation": "明细检索",
            "heading": "明细检索",
            "settled": "暂无历史记录",
            "viewport": {"width": 1024, "height": 768},
        },
        id="a11y_search_1024",
    ),
    *[
        pytest.param(
            {
                "fragment": fragment,
                "navigation": navigation,
                "heading": heading,
                "settled": settled,
                "viewport": {"width": 1440, "height": 900},
            },
            id=f"a11y_{fragment}_1440",
        )
        for fragment, navigation, heading, settled in (
            ("today", "今日任务", "今日任务", "暂无分析失败会话"),
            ("children", "幼儿管理", "幼儿管理", "暂无幼儿"),
            ("ducks", "小鸭管理", "小鸭管理", "暂无小鸭"),
            ("roster", "值日排班", "值日排班", "暂无排班"),
            ("review", "值日审阅", "值日审阅", "暂无待审阅会话"),
            (
                "growth",
                "能力成长曲线",
                "能力成长曲线",
                "请选择一名幼儿查看成长曲线。",
            ),
            ("search", "明细检索", "明细检索", "暂无历史记录"),
        )
    ],
]
MANAGEMENT_DIALOG_CASES = [
    pytest.param(
        {
            "fragment": "children",
            "heading": "幼儿管理",
            "settled": "暂无幼儿",
            "launcher": "添加幼儿",
            "dialog": "新增幼儿",
            "viewport": viewport,
        },
        id=f"management_children_dialog_{viewport['width']}",
    )
    for viewport in (
        {"width": 1024, "height": 768},
        {"width": 1440, "height": 900},
    )
] + [
    pytest.param(
        {
            "fragment": fragment,
            "heading": heading,
            "settled": settled,
            "launcher": launcher,
            "dialog": dialog,
            "viewport": viewport,
        },
        id=f"management_{fragment}_{launcher}_{viewport['width']}",
    )
    for fragment, heading, settled, launcher, dialog in (
        ("ducks", "小鸭管理", "暂无小鸭", "添加小鸭", "新增小鸭"),
        ("roster", "值日排班", "暂无排班", "安排当日", "安排当日值日"),
        ("roster", "值日排班", "暂无排班", "自动生成", "自动生成排班"),
    )
    for viewport in (
        {"width": 1024, "height": 768},
        {"width": 1440, "height": 900},
    )
]
PIN_STATE_CASES = [
    pytest.param(
        {
            "state": "initial",
            "heading": "首次设置教师 PIN",
            "pin_label": "设置教师 PIN",
            "submit": "设置并解锁",
            "viewport": {"width": 1024, "height": 768},
        },
        id="seed_pin_initial_1024",
    ),
    pytest.param(
        {
            "state": "locked",
            "heading": "教师端已锁定",
            "pin_label": "教师 PIN",
            "submit": "解锁",
            "viewport": {"width": 1024, "height": 768},
        },
        id="pin_locked_1024",
    ),
    pytest.param(
        {
            "state": "initial",
            "heading": "首次设置教师 PIN",
            "pin_label": "设置教师 PIN",
            "submit": "设置并解锁",
            "viewport": {"width": 1440, "height": 900},
        },
        id="pin_initial_1440",
    ),
    pytest.param(
        {
            "state": "locked",
            "heading": "教师端已锁定",
            "pin_label": "教师 PIN",
            "submit": "解锁",
            "viewport": {"width": 1440, "height": 900},
        },
        id="pin_locked_1440",
    ),
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


def _assert_active_outline(locator) -> None:
    state = locator.evaluate(
        """node => {
          const style = getComputedStyle(node);
          return {
            focused: document.activeElement === node,
            outlineStyle: style.outlineStyle,
            outlineWidth: parseFloat(style.outlineWidth),
            outlineColor: style.outlineColor,
          };
        }"""
    )
    assert state["focused"] is True, state
    assert state["outlineStyle"] != "none", state
    assert state["outlineWidth"] > 0, state
    assert state["outlineColor"] not in {
        "transparent",
        "rgba(0, 0, 0, 0)",
    }, state


def _active_descriptor(page) -> dict:
    return page.evaluate(
        """() => {
          const node = document.activeElement;
          if (!node) return {tag: null, name: null, interactive: false};
          const style = getComputedStyle(node);
          const interactive = node.matches(
            'button, a[href], input, select, textarea, [role="button"], [role="link"]'
          );
          return {
            tag: node.tagName.toLowerCase(),
            id: node.id || null,
            name: node.getAttribute('aria-label') || node.textContent?.trim() || node.value || null,
            interactive,
            disabled: Boolean(node.disabled),
            outlineStyle: style.outlineStyle,
            outlineWidth: parseFloat(style.outlineWidth),
            outlineColor: style.outlineColor,
          };
        }"""
    )


def _walk_keyboard_to(page, target, *, key: str = "Tab", limit: int = 80) -> list[dict]:
    assert target.count() == 1
    sequence = []
    for _ in range(limit + 1):
        if target.evaluate("node => document.activeElement === node"):
            return sequence
        page.keyboard.press(key)
        active = _active_descriptor(page)
        sequence.append(active)
        if active["interactive"] and not active["disabled"]:
            assert active["outlineStyle"] != "none", sequence
            assert active["outlineWidth"] > 0, sequence
            assert active["outlineColor"] not in {
                "transparent",
                "rgba(0, 0, 0, 0)",
            }, sequence
    raise AssertionError(
        f"keyboard target not reached in {limit} presses; sequence={sequence}"
    )


def _install_keyboard_routes(page, teacher_browser) -> dict:
    calls = {
        "today_roster": 0,
        "pending": 0,
        "processing": 0,
        "failed": 0,
        "detail": 0,
        "save": 0,
    }

    def today_roster(route):
        _assert_fixture_request(
            route,
            teacher_browser,
            method="GET",
            path="/api/roster/today",
        )
        calls["today_roster"] += 1
        _fulfill_json(route, [])

    def pending(route):
        _assert_fixture_request(
            route,
            teacher_browser,
            method="GET",
            path="/api/conversations",
            query={"queue": ["pending"]},
        )
        calls["pending"] += 1
        fragment = urlsplit(page.url).fragment
        if fragment.startswith("today"):
            _fulfill_json(route, [])
            return
        row = queue_row()
        if calls["save"]:
            row = {**row, "review_status": "draft", "revision": 3}
        _fulfill_json(route, [row])

    def queue_handler(key: str, queue: str):
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

    def detail(route):
        _assert_fixture_request(
            route,
            teacher_browser,
            method="GET",
            path="/api/conversations/42",
        )
        calls["detail"] += 1
        _fulfill_json(route, review_detail())

    def save(route):
        request = _assert_fixture_request(
            route,
            teacher_browser,
            method="PUT",
            path="/api/conversations/42/review",
        )
        calls["save"] += 1
        payload = json.loads(request.post_data)
        assert payload == {
            "revision": 2,
            "feeding_logs": [
                {
                    "id": 11,
                    "category": "喂食",
                    "content": "喂了菜叶",
                    "duck_id": 3,
                }
            ],
            "emotion": {"emotion": "开心", "intensity": 4, "note": None},
            "insight": "能够清楚表达照料过程。",
            "scores": [
                {
                    "dimension_id": 2,
                    "score": 5,
                    "reason": "键盘保留理由",
                }
            ],
            "action": "save_draft",
        }
        saved_review = review_detail()["review"]
        saved_review = {
            **saved_review,
            "scores": [
                {
                    "dimension_id": 2,
                    "dimension_name": "表达能力",
                    "score": 5,
                    "reason": "键盘保留理由",
                }
            ],
            "overall": 5.0,
        }
        _fulfill_json(
            route,
            {
                "saved": True,
                "conversation_id": 42,
                "review_status": "draft",
                "revision": 3,
                "saved_at": "2026-08-29T09:03:00Z",
                "review": saved_review,
            },
        )

    base = teacher_browser.server.base_url
    page.route(f"{base}/api/roster/today", today_roster)
    page.route(f"{base}/api/conversations?queue=pending", pending)
    page.route(
        f"{base}/api/conversations?queue=processing",
        queue_handler("processing", "processing"),
    )
    page.route(
        f"{base}/api/conversations?queue=failed",
        queue_handler("failed", "failed"),
    )
    page.route(f"{base}/api/conversations/42", detail)
    page.route(f"{base}/api/conversations/42/review", save)
    return calls


def _install_static_routes(page, teacher_browser) -> dict:
    calls: dict[str, int] = {}

    def handler(key: str, *, path: str, body: object, query=None):
        def route_handler(route):
            _assert_fixture_request(
                route,
                teacher_browser,
                method="GET",
                path=path,
                query=query,
            )
            calls[key] = calls.get(key, 0) + 1
            _fulfill_json(route, body)

        return route_handler

    base = teacher_browser.server.base_url
    routes = [
        (
            "/api/roster/today",
            handler("today_roster", path="/api/roster/today", body=[]),
        ),
        (
            "/api/conversations?queue=pending",
            handler(
                "pending",
                path="/api/conversations",
                query={"queue": ["pending"]},
                body=[],
            ),
        ),
        (
            "/api/conversations?queue=processing",
            handler(
                "processing",
                path="/api/conversations",
                query={"queue": ["processing"]},
                body=[],
            ),
        ),
        (
            "/api/conversations?queue=failed",
            handler(
                "failed",
                path="/api/conversations",
                query={"queue": ["failed"]},
                body=[],
            ),
        ),
        (
            "/api/children?include_inactive=true",
            handler(
                "children",
                path="/api/children",
                query={"include_inactive": ["true"]},
                body=[],
            ),
        ),
        (
            "/api/ducks?include_inactive=true",
            handler(
                "ducks",
                path="/api/ducks",
                query={"include_inactive": ["true"]},
                body=[],
            ),
        ),
        (
            "/api/roster",
            handler("roster", path="/api/roster", body=[]),
        ),
        (
            "/api/conversations/history?limit=20",
            handler(
                "history",
                path="/api/conversations/history",
                query={"limit": ["20"]},
                body={"items": [], "next_before_id": None},
            ),
        ),
    ]
    for suffix, route_handler in routes:
        page.route(f"{base}{suffix}", route_handler)
    return calls


def _assert_computed_accessible_names(locator) -> None:
    for index in range(locator.count()):
        node = locator.nth(index)
        snapshot = node.aria_snapshot().strip()
        first_line = snapshot.splitlines()[0] if snapshot else ""
        assert re.match(r'^-\s+[^\s]+\s+".+"(?::|\s|$)', first_line), {
            "snapshot": snapshot,
            "html": node.evaluate("item => item.outerHTML"),
        }


def _assert_reduced_motion_contract(page) -> None:
    contract = page.evaluate(
        """() => {
          const media = [];
          for (const sheet of document.styleSheets) {
            for (const rule of sheet.cssRules) {
              if (rule.type === CSSRule.MEDIA_RULE &&
                  rule.conditionText.includes('prefers-reduced-motion')) {
                media.push(rule.cssText);
              }
            }
          }
          const text = media.join(String.fromCharCode(10));
          return {
            count: media.length,
            animation: text.includes('animation-duration: 0.01ms'),
            iteration: text.includes('animation-iteration-count: 1'),
            scrolling: text.includes('scroll-behavior: auto'),
            transition: text.includes('transition-duration: 0.01ms'),
          };
        }"""
    )
    assert contract == {
        "count": 1,
        "animation": True,
        "iteration": True,
        "scrolling": True,
        "transition": True,
    }


@pytest.mark.parametrize("case", KEYBOARD_CASES)
def test_teacher_complete_review_flow_is_page_keyboard_only(teacher_browser, case):
    context = teacher_browser.new_context()
    page = context.new_page()
    page.set_default_timeout(5_000)
    page.set_viewport_size(case["viewport"])
    page_errors: list[str] = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    calls = _install_keyboard_routes(page, teacher_browser)
    observer_installed = False
    try:
        page.goto(
            f"{teacher_browser.server.base_url}/teacher.html#today",
            wait_until="domcontentloaded",
        )
        pin = page.locator("#teacher-pin")
        pin.wait_for()
        assert pin.evaluate("node => document.activeElement === node")
        page.keyboard.type(PIN)
        page.keyboard.press("Tab")
        confirmation = page.locator("#teacher-pin-confirmation")
        assert confirmation.evaluate("node => document.activeElement === node")
        page.keyboard.type(PIN)
        page.keyboard.press("Tab")
        unlock = page.get_by_role("button", name="设置并解锁", exact=True)
        _assert_active_outline(unlock)
        page.keyboard.press("Enter")

        today_heading = page.locator("main#main h1", has_text="今日任务")
        today_heading.wait_for()
        _assert_active_outline(today_heading)
        review_navigation = page.locator('#nav button[data-v="review"]')
        _walk_keyboard_to(page, review_navigation, key="Shift+Tab")
        assert review_navigation.get_attribute("aria-current") is None
        page.keyboard.press("Enter")

        review_heading = page.locator("main#main h1", has_text="值日审阅")
        review_heading.wait_for()
        _assert_active_outline(review_heading)
        assert page.locator('#nav button[aria-current="page"]').count() == 1
        assert review_navigation.get_attribute("aria-current") == "page"
        queue_link = page.get_by_role(
            "link", name="审阅雨雨的会话 #42", exact=True
        )
        queue_link.wait_for()
        _walk_keyboard_to(page, queue_link)
        page.keyboard.press("Enter")

        form = page.locator("[data-review-form]")
        form.wait_for()
        review_heading.wait_for()
        _assert_active_outline(review_heading)
        reason = page.get_by_label("表达能力评分理由", exact=True)
        _walk_keyboard_to(page, reason)
        page.keyboard.press("ControlOrMeta+A")
        page.keyboard.type("键盘保留理由")
        assert reason.input_value() == "键盘保留理由"

        score_four = page.get_by_role("radio", name="表达能力 4 分", exact=True)
        _walk_keyboard_to(page, score_four, key="Shift+Tab")
        assert score_four.is_checked()
        page.keyboard.press("ArrowRight")
        score_five = page.get_by_role("radio", name="表达能力 5 分", exact=True)
        assert score_five.is_checked()
        assert reason.input_value() == "键盘保留理由"

        draft = page.get_by_role("button", name="保存草稿", exact=True)
        _walk_keyboard_to(page, draft)
        status = page.locator(
            '.review-save-status[role="status"][aria-live="polite"]'
        )
        assert status.count() == 1
        status.evaluate(
            """node => {
              const records = [];
              const writes = [];
              const nativeReplaceChildren = node.replaceChildren;
              Object.defineProperty(node, 'replaceChildren', {
                configurable: true,
                value(...children) {
                  const text = children.map(value => value instanceof Node
                    ? value.textContent
                    : String(value)).join('').trim();
                  if (text) writes.push({text, connected: node.isConnected});
                  return nativeReplaceChildren.apply(node, children);
                },
              });
              const observer = new MutationObserver(() => {
                const text = node.textContent.trim();
                if (text && records.at(-1)?.text !== text) {
                  records.push({text, connected: node.isConnected});
                }
              });
              observer.observe(node, {childList: true, subtree: true, characterData: true});
              window.__task8SaveStatus = {node, records, writes, observer};
            }"""
        )
        observer_installed = True
        page.keyboard.press("Enter")
        page.get_by_text("全部修改已保存", exact=True).wait_for()
        status_state = page.evaluate(
            """() => ({
              same: document.querySelector('.review-save-status') === window.__task8SaveStatus.node,
              connected: window.__task8SaveStatus.node.isConnected,
              records: window.__task8SaveStatus.records,
              writes: window.__task8SaveStatus.writes,
            })"""
        )
        assert status_state == {
            "same": True,
            "connected": True,
            "records": [
                {"text": "正在保存…", "connected": True},
                {"text": "全部修改已保存", "connected": True},
            ],
            "writes": [
                {"text": "正在保存…", "connected": True},
                {"text": "全部修改已保存", "connected": True},
            ],
        }
        refreshed_draft = page.get_by_role("button", name="保存草稿", exact=True)
        _assert_active_outline(refreshed_draft)
        assert calls["save"] == 1
        assert calls["detail"] == 1

        lock = page.get_by_role("button", name="立即锁定", exact=True)
        _walk_keyboard_to(page, lock)
        page.keyboard.press("Space")
        page.get_by_role("heading", name="教师端已锁定", exact=True).wait_for()
        assert page.locator("main#main h1").count() == 0
        assert page.locator("#nav button").evaluate_all(
            "nodes => nodes.every(node => node.disabled)"
        )
        exposure = page.evaluate(
            """() => ({
              text: document.body.innerText,
              html: document.documentElement.outerHTML,
              url: location.href,
              local: JSON.stringify(Object.fromEntries(Object.entries(localStorage))),
              session: JSON.stringify(Object.fromEntries(Object.entries(sessionStorage))),
            })"""
        )
        for secret in (PIN, "键盘保留理由"):
            assert all(secret not in value for value in exposure.values())
        assert page_errors == []
    finally:
        if observer_installed:
            page.evaluate(
                """() => {
                  window.__task8SaveStatus?.observer?.disconnect();
                  if (window.__task8SaveStatus?.node) {
                    delete window.__task8SaveStatus.node.replaceChildren;
                  }
                  delete window.__task8SaveStatus;
                }"""
            )


@pytest.mark.parametrize("case", DIRTY_DIALOG_CASES)
def test_teacher_dirty_review_dialog_is_named_keyboard_operable_and_restores_focus(
    teacher_browser, case
):
    context = teacher_browser.new_context()
    page = context.new_page()
    page.set_default_timeout(5_000)
    page.set_viewport_size(case["viewport"])
    page_errors: list[str] = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    _install_keyboard_routes(page, teacher_browser)

    page.goto(
        f"{teacher_browser.server.base_url}/teacher.html#review?conversation_id=42",
        wait_until="domcontentloaded",
    )
    pin = page.locator("#teacher-pin")
    pin.wait_for()
    assert pin.evaluate("node => document.activeElement === node")
    page.keyboard.type(PIN)
    page.keyboard.press("Tab")
    confirmation = page.locator("#teacher-pin-confirmation")
    assert confirmation.evaluate("node => document.activeElement === node")
    page.keyboard.type(PIN)
    page.keyboard.press("Tab")
    unlock = page.get_by_role("button", name="设置并解锁", exact=True)
    _assert_active_outline(unlock)
    page.keyboard.press("Enter")

    review_heading = page.locator("main#main h1", has_text="值日审阅")
    review_heading.wait_for()
    _assert_active_outline(review_heading)
    form = page.locator("[data-review-form]")
    form.wait_for()
    reason = page.get_by_label("表达能力评分理由", exact=True)
    _walk_keyboard_to(page, reason)
    page.keyboard.press("ControlOrMeta+A")
    page.keyboard.type("键盘未保存理由")
    assert reason.input_value() == "键盘未保存理由"

    target = page.locator('#nav button[data-v="today"]')
    target.evaluate("node => { window.__task8DirtyTrigger = node; }")
    _walk_keyboard_to(page, target, key="Shift+Tab")
    page.keyboard.press("Enter")
    dialog = page.get_by_role("dialog", name="有未保存的修改", exact=True)
    dialog.wait_for()
    assert dialog.count() == 1
    continue_button = dialog.get_by_role(
        "button", name="继续编辑", exact=True
    )
    _assert_active_outline(continue_button)

    page.keyboard.press("Escape")
    dialog.wait_for(state="detached")
    assert urlsplit(page.url).fragment == "review?conversation_id=42"
    assert reason.input_value() == "键盘未保存理由"
    assert target.evaluate(
        "node => node === window.__task8DirtyTrigger && document.activeElement === node"
    )
    _assert_active_outline(target)

    page.keyboard.press("Enter")
    dialog = page.get_by_role("dialog", name="有未保存的修改", exact=True)
    dialog.wait_for()
    assert dialog.count() == 1
    continue_button = dialog.get_by_role(
        "button", name="继续编辑", exact=True
    )
    _assert_active_outline(continue_button)
    page.keyboard.press("Tab")
    discard = dialog.get_by_role("button", name="放弃修改", exact=True)
    _assert_active_outline(discard)
    page.keyboard.press("Space")

    today_heading = page.locator("main#main h1", has_text="今日任务")
    today_heading.wait_for()
    assert urlsplit(page.url).fragment == "today"
    assert page.locator("[data-review-form]").count() == 0
    _assert_active_outline(today_heading)
    assert page_errors == []


@pytest.mark.parametrize("case", A11Y_ROUTE_CASES)
def test_teacher_authenticated_routes_have_frozen_accessibility_structure(
    teacher_browser, case
):
    context = teacher_browser.new_context()
    page = context.new_page()
    page.set_default_timeout(5_000)
    page.set_viewport_size(case["viewport"])
    page_errors: list[str] = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    calls = _install_static_routes(page, teacher_browser)
    page.goto(
        f"{teacher_browser.server.base_url}/teacher.html#{case['fragment']}",
        wait_until="domcontentloaded",
    )
    pin = page.locator("#teacher-pin")
    pin.wait_for()
    assert pin.evaluate("node => document.activeElement === node")
    page.keyboard.type(PIN)
    page.keyboard.press("Tab")
    confirmation = page.locator("#teacher-pin-confirmation")
    assert confirmation.evaluate("node => document.activeElement === node")
    page.keyboard.type(PIN)
    page.keyboard.press("Tab")
    page.keyboard.press("Enter")
    heading = page.locator("main#main h1", has_text=case["heading"])
    heading.wait_for()
    page.get_by_text(case["settled"], exact=True).wait_for()

    assert page.locator("main#main").count() == 1
    assert page.locator("main#main h1:visible").count() == 1
    assert heading.count() == 1
    _assert_active_outline(heading)

    form_controls = page.locator(
        "input:visible:not(:disabled), select:visible:not(:disabled), textarea:visible:not(:disabled)"
    )
    actions = page.locator(
        "button:visible:not(:disabled), a[href]:visible"
    )
    _assert_computed_accessible_names(form_controls)
    _assert_computed_accessible_names(actions)

    nested = page.evaluate(
        """() => {
          const selector = 'button, a[href], input, select, textarea, summary, [role="button"], [role="link"]';
          return [...document.querySelectorAll(selector)]
            .filter(node => node.querySelector(selector))
            .map(node => node.outerHTML);
        }"""
    )
    assert nested == []
    assert page.evaluate(
        """() => [...document.querySelectorAll('[tabindex]')]
          .filter(node => Number(node.getAttribute('tabindex')) > 0)
          .map(node => node.outerHTML)"""
    ) == []

    current = page.locator('#nav button[aria-current="page"]')
    assert current.count() == 1
    assert current.inner_text() == case["navigation"]
    assert page.locator("#nav button").evaluate_all(
        "nodes => nodes.filter(node => node.hasAttribute('aria-current')).length === 1"
    )

    sized_actions = page.locator(
        "button:visible, a[href]:visible:not(.skip-link)"
    )
    for index in range(sized_actions.count()):
        box = sized_actions.nth(index).bounding_box()
        assert box is not None
        assert box["width"] >= 44, {
            "box": box,
            "html": sized_actions.nth(index).evaluate("node => node.outerHTML"),
        }
        assert box["height"] >= 44, {
            "box": box,
            "html": sized_actions.nth(index).evaluate("node => node.outerHTML"),
        }

    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )
    for index in range(actions.count()):
        action = actions.nth(index)
        action.focus()
        _assert_active_outline(action)
    for index in range(form_controls.count()):
        control = form_controls.nth(index)
        control.focus()
        _assert_active_outline(control)
    _assert_reduced_motion_contract(page)
    assert calls != {}
    assert page_errors == []


@pytest.mark.parametrize("case", MANAGEMENT_DIALOG_CASES)
def test_teacher_management_dialogs_are_modal_keyboard_sized_and_restore_focus(
    teacher_browser, case
):
    context = teacher_browser.new_context()
    page = context.new_page()
    page.set_default_timeout(5_000)
    page.set_viewport_size(case["viewport"])
    page_errors: list[str] = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    _install_static_routes(page, teacher_browser)
    page.goto(
        f"{teacher_browser.server.base_url}/teacher.html#{case['fragment']}",
        wait_until="domcontentloaded",
    )
    page.get_by_label("设置教师 PIN", exact=True).fill(PIN)
    page.get_by_label("再次输入教师 PIN", exact=True).fill(PIN)
    page.get_by_role("button", name="设置并解锁", exact=True).click()
    page.get_by_role("heading", name=case["heading"], exact=True).wait_for()
    page.get_by_text(case["settled"], exact=True).wait_for()

    launcher = page.get_by_role("button", name=case["launcher"], exact=True)
    launcher.click()
    dialog = page.get_by_role("dialog", name=case["dialog"], exact=True)
    dialog.wait_for()
    assert dialog.count() == 1
    assert dialog.evaluate(
        "node => node.tagName === 'DIALOG' && node.open && node.contains(document.activeElement)"
    )

    controls = dialog.locator(
        "input:visible:not(:disabled), select:visible:not(:disabled), "
        "textarea:visible:not(:disabled), button:visible:not(:disabled)"
    )
    assert controls.count() > 0
    _assert_computed_accessible_names(controls)
    actions = dialog.locator("button:visible:not(:disabled)")
    assert actions.count() >= 2
    for index in range(actions.count()):
        box = actions.nth(index).bounding_box()
        assert box is not None
        assert box["width"] >= 44 and box["height"] >= 44, {
            "box": box,
            "html": actions.nth(index).evaluate("node => node.outerHTML"),
        }

    for _index in range(controls.count() + 2):
        page.keyboard.press("Tab")
        assert dialog.evaluate(
            "node => node.matches(':modal') && "
            "(node.contains(document.activeElement) || document.activeElement === document.body)"
        )
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )

    page.keyboard.press("Escape")
    dialog.wait_for(state="detached")
    assert launcher.evaluate("button => document.activeElement === button")
    _assert_active_outline(launcher)
    assert page_errors == []


@pytest.mark.parametrize("case", PIN_STATE_CASES)
def test_teacher_pin_and_locked_states_use_the_separate_h2_contract(
    teacher_browser, case
):
    context = teacher_browser.new_context()
    page = context.new_page()
    page.set_default_timeout(5_000)
    page.set_viewport_size(case["viewport"])
    page_errors: list[str] = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    _install_static_routes(page, teacher_browser)
    page.goto(
        f"{teacher_browser.server.base_url}/teacher.html#today",
        wait_until="domcontentloaded",
    )

    pin = page.locator("#teacher-pin")
    pin.wait_for()
    if case["state"] == "locked":
        assert pin.evaluate("node => document.activeElement === node")
        page.keyboard.type(PIN)
        page.keyboard.press("Tab")
        confirmation = page.locator("#teacher-pin-confirmation")
        assert confirmation.evaluate("node => document.activeElement === node")
        page.keyboard.type(PIN)
        page.keyboard.press("Tab")
        page.keyboard.press("Enter")
        today_heading = page.locator("main#main h1", has_text="今日任务")
        today_heading.wait_for()
        lock = page.get_by_role("button", name="立即锁定", exact=True)
        _walk_keyboard_to(page, lock, key="Shift+Tab")
        page.keyboard.press("Space")
        pin = page.locator("#teacher-pin")
        pin.wait_for()

    assert page.locator("main#main").count() == 1
    heading = page.locator("main#main h2:visible", has_text=case["heading"])
    assert heading.count() == 1
    assert page.locator("main#main h2:visible").count() == 1
    assert page.locator("main#main h1").count() == 0
    assert page.get_by_label(case["pin_label"], exact=True).count() == 1
    expected_confirmation_count = 1 if case["state"] == "initial" else 0
    assert page.get_by_label("再次输入教师 PIN", exact=True).count() == expected_confirmation_count
    assert page.get_by_role(
        "button", name=case["submit"], exact=True
    ).count() == 1
    assert page.locator("#nav button").evaluate_all(
        "nodes => nodes.length === 7 && nodes.every(node => node.disabled)"
    )
    assert page.locator("#nav").get_attribute("aria-busy") == "true"
    assert page.locator('#nav button[aria-current="page"]').count() == 0
    assert page.evaluate(
        """() => [...document.querySelectorAll('[tabindex]')]
          .filter(node => Number(node.getAttribute('tabindex')) > 0)
          .map(node => node.outerHTML)"""
    ) == []
    visible_controls = page.locator(
        "main#main input:visible:not(:disabled), main#main button:visible:not(:disabled), main#main select:visible:not(:disabled), main#main textarea:visible:not(:disabled)"
    )
    _assert_computed_accessible_names(visible_controls)
    assert pin.evaluate("node => document.activeElement === node")
    _assert_active_outline(pin)
    assert PIN not in page.locator("body").inner_text()
    assert PIN not in page.evaluate("document.documentElement.outerHTML")
    assert page_errors == []
