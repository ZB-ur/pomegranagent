from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from pathlib import Path

import pytest

from tests.browser.test_teacher_accessibility import (
    PIN,
    _assert_fixture_request,
    _fulfill_json,
    _install_static_routes,
)


TEACHER_VIEWPORTS = [
    pytest.param({"width": 1024, "height": 768}, id="1024x768"),
    pytest.param({"width": 1440, "height": 900}, id="1440x900"),
]


def _rgb(color: str) -> tuple[float, float, float]:
    channels = re.findall(r"[0-9.]+", color)
    assert len(channels) >= 3, color
    return tuple(float(channel) / 255 for channel in channels[:3])


def _luminance(color: str) -> float:
    linear = [
        channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
        for channel in _rgb(color)
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(first: str, second: str) -> float:
    lighter, darker = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def _hex_color(color: str) -> str:
    return "#" + "".join(f"{round(channel * 255):02x}" for channel in _rgb(color))


def _focus_diagnostics(locator) -> dict:
    state = locator.evaluate(
        r"""node => {
          const style = getComputedStyle(node);
          const alpha = color => {
            if (!color || color === 'transparent') return 0;
            const match = color.match(/^rgba\([^,]+,[^,]+,[^,]+,\s*([0-9.]+)\)$/);
            return match ? Number(match[1]) : 1;
          };
          const nearest = start => {
            let current = start;
            while (current) {
              const color = getComputedStyle(current).backgroundColor;
              if (alpha(color) > 0) {
                return {color, source: current.tagName.toLowerCase()};
              }
              current = current.parentElement;
            }
            return null;
          };
          const rect = node.getBoundingClientRect();
          return {
            focused: document.activeElement === node,
            tag: node.tagName.toLowerCase(),
            tabIndex: node.getAttribute('tabindex'),
            outlineColor: style.outlineColor,
            outlineStyle: style.outlineStyle,
            outlineWidth: parseFloat(style.outlineWidth) || 0,
            outlineOffset: parseFloat(style.outlineOffset) || 0,
            boxShadow: style.boxShadow,
            elementBackground: nearest(node),
            surroundingBackground: nearest(node.parentElement),
            rect: {x: rect.x, y: rect.y, width: rect.width, height: rect.height},
            viewport: {width: innerWidth, height: innerHeight},
          };
        }"""
    )
    shadow_colors = re.findall(r"rgba?\([^)]*\)", state["boxShadow"])
    ring_colors = tuple(dict.fromkeys((state["outlineColor"], *shadow_colors)))
    assert state["elementBackground"] is not None, state
    assert state["surroundingBackground"] is not None, state
    adjacent = (
        state["elementBackground"]["color"],
        state["surroundingBackground"]["color"],
    )
    shadow_without_colors = re.sub(r"rgba?\([^)]*\)", "", state["boxShadow"])
    shadow_lengths = tuple(
        float(value) for value in re.findall(r"(-?[0-9.]+)px", shadow_without_colors)
    )
    shadow_spread = abs(shadow_lengths[3]) if len(shadow_lengths) >= 4 else 0.0
    shadow_blur = abs(shadow_lengths[2]) if len(shadow_lengths) >= 3 else 0.0
    shadow_is_inset = bool(re.search(r"\binset\b", shadow_without_colors))
    outline_extent = max(0.0, state["outlineWidth"] + state["outlineOffset"])
    shadow_extent = 0.0 if shadow_is_inset else max(0.0, shadow_blur + shadow_spread)
    extent = max(outline_extent, shadow_extent)
    state["ringColors"] = tuple(_hex_color(color) for color in ring_colors)
    state["adjacentColors"] = tuple(_hex_color(color) for color in adjacent)
    state["ringThicknesses"] = (state["outlineWidth"], shadow_spread)
    state["bestRatios"] = tuple(
        round(max(_contrast(ring, background) for ring in ring_colors), 3)
        for background in adjacent
    )
    state["focusBounds"] = {
        "left": state["rect"]["x"] - extent,
        "top": state["rect"]["y"] - extent,
        "right": state["rect"]["x"] + state["rect"]["width"] + extent,
        "bottom": state["rect"]["y"] + state["rect"]["height"] + extent,
    }
    return state


def _keyboard_focus(page, target, *, limit: int = 80) -> None:
    for _index in range(limit):
        page.keyboard.press("Tab")
        if target.evaluate("node => document.activeElement === node"):
            return
    raise AssertionError(
        f"target was not reached through {limit} page-keyboard Tab actions: "
        f"{target.evaluate('node => node.outerHTML')}"
    )


@pytest.mark.parametrize("viewport", TEACHER_VIEWPORTS)
def test_release_focus_indicator_meets_three_to_one(
    teacher_browser, viewport, record_property
):
    context = teacher_browser.new_context()
    page = context.new_page()
    page.set_default_timeout(5_000)
    page.set_viewport_size(viewport)
    _install_static_routes(page, teacher_browser)

    child = {
        "id": 701,
        "name": "焦点证据幼儿",
        "nickname": "焦点证据",
        "avatar": None,
        "active": True,
        "deactivated_at": None,
        "future_roster_entries": 0,
        "has_active_conversation": False,
    }

    def children(route):
        _assert_fixture_request(
            route,
            teacher_browser,
            method="GET",
            path="/api/children",
            query={"include_inactive": ["true"]},
        )
        _fulfill_json(route, [child])

    page.route(
        f"{teacher_browser.server.base_url}/api/children?include_inactive=true",
        children,
    )
    page.goto(
        f"{teacher_browser.server.base_url}/teacher.html#today",
        wait_until="domcontentloaded",
    )

    diagnostics = []

    def measure(label: str, target) -> None:
        assert target.count() == 1, label
        assert target.is_visible(), label
        diagnostics.append({"label": label, **_focus_diagnostics(target)})

    pin = page.locator("#teacher-pin")
    _keyboard_focus(page, pin)
    measure("input", pin)
    pin.fill(PIN)
    confirmation = page.locator("#teacher-pin-confirmation")
    _keyboard_focus(page, confirmation)
    measure("confirmation-input", confirmation)
    confirmation.fill(PIN)
    unlock = page.get_by_role("button", name="设置并解锁", exact=True)
    _keyboard_focus(page, unlock)
    measure("native-button", unlock)
    page.keyboard.press("Enter")
    page.get_by_role("heading", name="今日任务", exact=True).wait_for()
    page.get_by_text("暂无分析失败会话", exact=True).wait_for()

    today_heading = page.get_by_role("heading", name="今日任务", exact=True)
    assert today_heading.get_attribute("tabindex") == "-1"
    measure("route-h1", today_heading)

    current_nav = page.locator('#nav button[aria-current="page"]')
    _keyboard_focus(page, current_nav)
    measure("nav-button", current_nav)
    start_link = page.get_by_role("link", name="开始幼儿对话", exact=True)
    _keyboard_focus(page, start_link)
    measure("link", start_link)

    children_nav = page.locator('#nav button[data-v="children"]')
    _keyboard_focus(page, children_nav)
    page.keyboard.press("Enter")
    page.get_by_role("heading", name="幼儿管理", exact=True).wait_for()
    child_heading = page.get_by_role("heading", name="幼儿列表", exact=True)
    child_heading.evaluate(
        "node => { node.setAttribute('tabindex', '-1'); node.focus(); }"
    )
    measure("route-h2", child_heading)

    primary = page.get_by_role("button", name="添加幼儿", exact=True)
    _keyboard_focus(page, primary)
    measure("primary-blue-button", primary)
    page.keyboard.press("Enter")
    create_dialog = page.get_by_role("dialog", name="新增幼儿", exact=True)
    create_dialog.wait_for()
    white_panel = create_dialog.get_by_label("幼儿姓名", exact=True)
    if not white_panel.evaluate("node => document.activeElement === node"):
        _keyboard_focus(page, white_panel)
    measure("white-panel-control", white_panel)
    create_cancel = create_dialog.get_by_role("button", name="取消", exact=True)
    if not create_cancel.evaluate("node => document.activeElement === node"):
        _keyboard_focus(page, create_cancel)
    measure("create-dialog-target", create_cancel)
    page.keyboard.press("Escape")
    create_dialog.wait_for(state="detached")
    measure("create-dialog-return", primary)

    launcher = page.get_by_role("button", name="停用：焦点证据", exact=True)
    _keyboard_focus(page, launcher)
    measure("gray-button", launcher)
    page.keyboard.press("Enter")
    dialog_target = page.get_by_role("button", name="取消", exact=True)
    if not dialog_target.evaluate("node => document.activeElement === node"):
        _keyboard_focus(page, dialog_target)
    measure("dialog-target", dialog_target)
    page.keyboard.press("Escape")
    assert page.get_by_role("dialog", name="停用焦点证据", exact=True).count() == 0
    measure("dialog-return", launcher)

    ducks_nav = page.locator('#nav button[data-v="ducks"]')
    _keyboard_focus(page, ducks_nav)
    page.keyboard.press("Enter")
    page.get_by_role("heading", name="小鸭管理", exact=True).wait_for()
    duck_primary = page.get_by_role("button", name="添加小鸭", exact=True)
    _keyboard_focus(page, duck_primary)
    measure("duck-primary-button", duck_primary)
    page.keyboard.press("Enter")
    duck_dialog = page.get_by_role("dialog", name="新增小鸭", exact=True)
    duck_dialog.wait_for()
    note = duck_dialog.get_by_label("备注", exact=True)
    _keyboard_focus(page, note)
    measure("textarea", note)
    page.keyboard.press("Escape")
    duck_dialog.wait_for(state="detached")
    measure("duck-dialog-return", duck_primary)

    growth_nav = page.locator('#nav button[data-v="growth"]')
    _keyboard_focus(page, growth_nav)
    page.keyboard.press("Enter")
    page.get_by_role("heading", name="能力成长曲线", exact=True).wait_for()
    child_select = page.get_by_label("选择幼儿", exact=True)
    _keyboard_focus(page, child_select)
    measure("select", child_select)

    assert all(item["focused"] for item in diagnostics), diagnostics
    assert all(item["outlineStyle"] != "none" for item in diagnostics), diagnostics
    assert all(item["rect"]["width"] > 0 and item["rect"]["height"] > 0 for item in diagnostics), diagnostics
    assert {item["label"] for item in diagnostics} == {
        "route-h1",
        "route-h2",
        "dialog-target",
        "dialog-return",
        "create-dialog-target",
        "create-dialog-return",
            "native-button",
            "link",
            "input",
            "confirmation-input",
            "select",
        "textarea",
        "nav-button",
        "primary-blue-button",
        "duck-primary-button",
        "duck-dialog-return",
        "gray-button",
        "white-panel-control",
    }
    measured = [
        {
            "label": item["label"],
            "ringColors": item["ringColors"],
            "ringThicknesses": item["ringThicknesses"],
            "adjacentColors": item["adjacentColors"],
            "bestRatios": item["bestRatios"],
            "rect": item["rect"],
            "focusBounds": item["focusBounds"],
        }
        for item in diagnostics
    ]
    assert all(
        len(item["ringColors"]) >= 2
        and len(set(item["ringColors"])) >= 2
        and all(thickness >= 3 for thickness in item["ringThicknesses"])
        and all(ratio >= 3 for ratio in item["bestRatios"])
        for item in diagnostics
    ), measured
    assert all(
        0 <= item["focusBounds"]["left"]
        and 0 <= item["focusBounds"]["top"]
        and item["focusBounds"]["right"] <= viewport["width"]
        and item["focusBounds"]["bottom"] <= viewport["height"]
        for item in diagnostics
    ), measured
    record_property(
        "task9.focus_measurement",
        json.dumps(
            {
                "measurements": measured,
                "viewport": viewport,
                "viewport_id": f'{viewport["width"]}x{viewport["height"]}',
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ),
    )


@pytest.mark.parametrize("viewport", TEACHER_VIEWPORTS)
def test_release_roster_max_length_cjk_content_stays_in_bounds_without_overlap(
    teacher_browser, viewport
):
    context = teacher_browser.new_context()
    page = context.new_page()
    page.set_default_timeout(5_000)
    page.set_viewport_size(viewport)
    _install_static_routes(page, teacher_browser)
    long_child_name = "幼" * 64
    long_cycle = "月" * 64
    assert len(long_child_name) == 64
    assert len(long_cycle) == 64
    children = [
        {
            "id": 701,
            "name": long_child_name,
            "nickname": None,
            "avatar": None,
            "active": True,
            "deactivated_at": None,
            "future_roster_entries": 0,
            "has_active_conversation": False,
        },
        {
            "id": 702,
            "name": "搭档",
            "nickname": None,
            "avatar": None,
            "active": True,
            "deactivated_at": None,
            "future_roster_entries": 0,
            "has_active_conversation": False,
        },
    ]
    roster = [
        {"id": 1, "cycle": long_cycle, "date": "2026-09-01", "child_id": 701},
        {"id": 2, "cycle": long_cycle, "date": "2026-09-01", "child_id": 702},
    ]

    def children_route(route):
        _assert_fixture_request(
            route,
            teacher_browser,
            method="GET",
            path="/api/children",
            query={"include_inactive": ["true"]},
        )
        _fulfill_json(route, children)

    def roster_route(route):
        _assert_fixture_request(
            route,
            teacher_browser,
            method="GET",
            path="/api/roster",
        )
        _fulfill_json(route, roster)

    page.route(
        f"{teacher_browser.server.base_url}/api/children?include_inactive=true",
        children_route,
    )
    page.route(
        f"{teacher_browser.server.base_url}/api/roster",
        roster_route,
    )
    page.goto(
        f"{teacher_browser.server.base_url}/teacher.html#roster",
        wait_until="domcontentloaded",
    )
    page.get_by_label("设置教师 PIN", exact=True).fill(PIN)
    page.get_by_label("再次输入教师 PIN", exact=True).fill(PIN)
    page.get_by_role("button", name="设置并解锁", exact=True).click()
    page.get_by_role("heading", name="值日排班", exact=True).wait_for()

    projection_value = f"2026-09-01 · {long_cycle} · {long_child_name}、搭档"
    preview = page.locator(".roster-preview")
    row = page.locator(".roster-row")
    row.wait_for()
    assert row.count() == 1
    pill = row.locator(".roster-person").filter(has_text=long_child_name)
    badge = row.locator(".roster-footer .management-badge")
    projection = row.locator(".roster-footer .management-row-copy")
    people = row.locator(".roster-people")
    footer = row.locator(".roster-footer")
    assert pill.count() == 1
    assert badge.inner_text() == long_cycle
    assert projection.inner_text() == projection_value
    assert row.get_attribute("aria-label") == projection_value

    def geometry(locator):
        return locator.evaluate(
            """node => {
              const rect = node.getBoundingClientRect();
              return {
                left: rect.left,
                top: rect.top,
                right: rect.right,
                bottom: rect.bottom,
                width: rect.width,
                height: rect.height,
                clientWidth: node.clientWidth,
                clientHeight: node.clientHeight,
                scrollWidth: node.scrollWidth,
                scrollHeight: node.scrollHeight,
              };
            }"""
        )

    def assert_inside(inner, outer):
        assert inner["left"] >= outer["left"] - 1, (inner, outer)
        assert inner["top"] >= outer["top"] - 1, (inner, outer)
        assert inner["right"] <= outer["right"] + 1, (inner, outer)
        assert inner["bottom"] <= outer["bottom"] + 1, (inner, outer)

    def overlaps(first, second):
        horizontal = min(first["right"], second["right"]) - max(
            first["left"], second["left"]
        )
        vertical = min(first["bottom"], second["bottom"]) - max(
            first["top"], second["top"]
        )
        return horizontal > 0.5 and vertical > 0.5

    boxes = {
        "preview": geometry(preview),
        "row": geometry(row),
        "people": geometry(people),
        "pill": geometry(pill),
        "footer": geometry(footer),
        "badge": geometry(badge),
        "projection": geometry(projection),
    }
    assert_inside(boxes["row"], boxes["preview"])
    assert_inside(boxes["people"], boxes["row"])
    assert_inside(boxes["footer"], boxes["row"])
    assert_inside(boxes["pill"], boxes["people"])
    assert_inside(boxes["badge"], boxes["footer"])
    assert_inside(boxes["projection"], boxes["footer"])
    for name in ("pill", "badge", "projection"):
        box = boxes[name]
        assert box["width"] > 0 and box["height"] > 0, boxes
        assert box["scrollWidth"] <= box["clientWidth"] + 1, boxes
        assert box["scrollHeight"] <= box["clientHeight"] + 1, boxes
    assert not overlaps(boxes["pill"], boxes["badge"]), boxes
    assert not overlaps(boxes["pill"], boxes["projection"]), boxes
    assert not overlaps(boxes["badge"], boxes["projection"]), boxes
    assert boxes["row"]["left"] >= 0
    assert boxes["row"]["right"] <= viewport["width"]
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )


def _named_child_rows(database: Path, name: str) -> list[tuple[str, str | None]]:
    with sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True) as connection:
        return connection.execute(
            "SELECT name, nickname FROM children WHERE name = ? ORDER BY id",
            (name,),
        ).fetchall()


@pytest.mark.parametrize("viewport", TEACHER_VIEWPORTS)
def test_release_teacher_action_persists_to_disposable_sqlite(
    teacher_browser, viewport, record_property
):
    database = Path(teacher_browser.server.environment["APP_DB_PATH"]).resolve()
    expected_database = (teacher_browser.server.runtime_dir / "browser-app.db").resolve()
    repository_data = (Path(__file__).resolve().parents[2] / "data").resolve()
    real_database = (repository_data / "duck_diary.db").resolve()
    assert database == expected_database
    assert database != real_database
    assert not database.is_relative_to(repository_data)
    name_token = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"task9-db-action:{database.as_posix()}:{viewport['width']}x{viewport['height']}",
    ).hex
    evidence_name = f"真实证据幼儿-{name_token[:20]}"
    before_rows = _named_child_rows(database, evidence_name)
    assert before_rows == []

    context = teacher_browser.new_context()
    page = context.new_page()
    page.set_default_timeout(5_000)
    page.set_viewport_size(viewport)
    page.goto(
        f"{teacher_browser.server.base_url}/teacher.html#children",
        wait_until="domcontentloaded",
    )
    page.get_by_label("设置教师 PIN", exact=True).fill(PIN)
    page.get_by_label("再次输入教师 PIN", exact=True).fill(PIN)
    page.get_by_role("button", name="设置并解锁", exact=True).click()
    page.get_by_role("heading", name="幼儿管理", exact=True).wait_for()

    action = page.get_by_role("button", name="添加幼儿", exact=True)
    assert action.is_visible()
    action.click()
    dialog = page.get_by_role("dialog", name="新增幼儿", exact=True)
    dialog.wait_for()
    dialog.get_by_label("幼儿姓名", exact=True).fill(f"  {evidence_name}  ")
    dialog.get_by_label("小名", exact=True).fill("  证据  ")
    dialog.get_by_role(
        "button", name=re.compile(r"^(确认)?添加幼儿$")
    ).click()
    dialog.wait_for(state="detached")
    page.get_by_text("已保存", exact=True).wait_for()

    after_rows = _named_child_rows(database, evidence_name)
    assert after_rows == [(evidence_name, "证据")]
    record_property(
        "task9.db_action_evidence",
        json.dumps(
            {
                "after_count": len(after_rows),
                "before_count": len(before_rows),
                "business_name_sha256": hashlib.sha256(
                    evidence_name.encode("utf-8")
                ).hexdigest(),
                "database_role": "disposable-browser-app.db",
                "outside_repository_data": not database.is_relative_to(repository_data),
                "resolved_fixture_match": database == expected_database,
                "viewport": viewport,
                "viewport_id": f'{viewport["width"]}x{viewport["height"]}',
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ),
    )
