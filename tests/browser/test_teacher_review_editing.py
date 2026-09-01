from __future__ import annotations

import json

import pytest

from tests.browser.test_teacher_review_loading import (
    VIEWPORTS,
    VIEWPORT_IDS,
    fulfill_json,
    install_review_reads,
    open_teacher,
    queue_row,
    review_detail,
    unlock_review,
)


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_teacher_review_editor_saves_the_complete_normalized_draft_and_refreshes_only_queue(teacher_browser, viewport):
    _context, page = open_teacher(teacher_browser, viewport)
    queue_calls = 0
    saves = []

    def queue(route):
        nonlocal queue_calls
        queue_calls += 1
        refreshed_row = {**queue_row(), "review_status": "draft", "revision": 3}
        fulfill_json(route, [queue_row()] if queue_calls == 1 else [refreshed_row])

    def detail(route):
        fulfill_json(route, review_detail())

    def save(route):
        payload = json.loads(route.request.post_data)
        saves.append(payload)
        assert set(payload) == {"revision", "feeding_logs", "emotion", "insight", "scores", "action"}
        assert payload["revision"] == 2
        assert payload["action"] == "save_draft"
        assert payload["feeding_logs"] == [{"id": 11, "category": "观察", "content": "观察了小黄吃菜叶", "duck_id": 3}]
        assert payload["emotion"] == {"emotion": "开心", "intensity": 5, "note": None}
        assert payload["insight"] == "会主动记录小鸭进食。"
        assert payload["scores"] == [{"dimension_id": 2, "score": 5, "reason": ""}]
        acknowledgement = {
            "saved": True,
            "conversation_id": 42,
            "review_status": "draft",
            "revision": 3,
            "saved_at": "2026-08-23T09:03:00Z",
            "review": {
                "feeding_logs": [{"id": 11, "category": "观察", "content": "观察了小黄吃菜叶", "duck_id": 3}],
                "emotion": {"emotion": "开心", "intensity": 5, "note": None},
                "insight": "会主动记录小鸭进食。",
                "scores": [{"dimension_id": 2, "dimension_name": "表达能力", "score": 5, "reason": ""}],
                "overall": 5.0,
            },
        }
        fulfill_json(route, acknowledgement)

    install_review_reads(page, teacher_browser, queue_handler=queue, detail_handler=detail)
    page.route(f"{teacher_browser.server.base_url}/api/conversations/42/review", save)
    unlock_review(page)
    form = page.locator("[data-review-form]")
    form.wait_for()
    status = form.locator(
        '.review-save-status[role="status"][aria-live="polite"]'
    )
    assert status.inner_text() == "全部修改已保存"
    status.evaluate("node => { window.__p4ReviewSaveStatus = node; }")
    reason_error_id = page.get_by_label("表达能力评分理由", exact=True).get_attribute("aria-describedby")
    assert reason_error_id
    assert page.locator(f"#{reason_error_id}").count() == 1
    action_bar = form.locator(".review-actions")
    assert action_bar.locator(".review-save-status").count() == 1
    assert action_bar.evaluate("node => getComputedStyle(node).position") == "sticky"
    assert page.get_by_role("button", name="保存草稿", exact=True).bounding_box()["height"] >= 44
    assert page.get_by_role("button", name="保存并确认", exact=True).bounding_box()["height"] >= 44
    page.get_by_label("饲养记录 1 分类", exact=True).select_option("观察")
    page.get_by_label("饲养记录 1 内容", exact=True).fill("  观察了小黄吃菜叶  ")
    page.get_by_label("情绪", exact=True).fill("  开心  ")
    page.get_by_label("情绪强度", exact=True).fill("5")
    page.get_by_label("情绪备注", exact=True).fill("  ")
    page.get_by_label("教育洞察", exact=True).fill("  会主动记录小鸭进食。  ")
    page.get_by_role("radio", name="表达能力 5 分", exact=True).check()
    page.get_by_label("表达能力评分理由", exact=True).fill("  ")
    page.wait_for_function(
        "() => document.querySelector('.review-save-status')?.textContent === '有未保存的修改'"
    )
    assert page.evaluate(
        "document.querySelector('.review-save-status') === window.__p4ReviewSaveStatus"
    )
    page.get_by_role("button", name="保存草稿", exact=True).click()
    page.get_by_role("status").get_by_text("全部修改已保存", exact=True).wait_for()

    assert len(saves) == 1
    assert queue_calls == 2
    assert page.get_by_text("草稿 · 第 3 版", exact=True).count() == 1
    assert "revision" not in page.locator("[data-review-panel='detail']").inner_text().lower()
    assert page.evaluate(
        "document.querySelector('.review-save-status') === window.__p4ReviewSaveStatus"
    )
    assert page.get_by_label("饲养记录 1 内容", exact=True).input_value() == "观察了小黄吃菜叶"
    assert page.get_by_role("radio", name="表达能力 5 分", exact=True).is_checked()
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_teacher_review_complete_confirm_uses_confirm_action_and_removes_the_pending_row(teacher_browser, viewport):
    _context, page = open_teacher(teacher_browser, viewport)
    queue_calls = 0
    saves = []

    def queue(route):
        nonlocal queue_calls
        queue_calls += 1
        fulfill_json(route, [queue_row()] if queue_calls == 1 else [])

    def save(route):
        payload = json.loads(route.request.post_data)
        saves.append(payload)
        assert payload["revision"] == 2
        assert payload["action"] == "confirm"
        assert payload["scores"] == [{"dimension_id": 2, "score": 4, "reason": "能说明自己的观察。"}]
        fulfilment = {
            "saved": True,
            "conversation_id": 42,
            "review_status": "confirmed",
            "revision": 3,
            "saved_at": "2026-08-23T09:03:00Z",
            "review": review_detail()["review"],
        }
        fulfill_json(route, fulfilment)

    install_review_reads(
        page,
        teacher_browser,
        queue_handler=queue,
        detail_handler=lambda route: fulfill_json(route, review_detail()),
    )
    page.route(f"{teacher_browser.server.base_url}/api/conversations/42/review", save)
    unlock_review(page)
    page.locator("[data-review-form]").wait_for()
    page.get_by_role("button", name="保存并确认", exact=True).click()
    page.get_by_role("status").get_by_text("审阅已确认", exact=True).wait_for()

    assert len(saves) == 1
    assert queue_calls == 2
    assert page.get_by_text("暂无待审阅会话", exact=True).count() == 1
    assert page.get_by_text("已确认 · 第 3 版", exact=True).count() == 1
    assert "revision" not in page.locator("[data-review-panel='detail']").inner_text().lower()


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_teacher_review_invalid_confirm_and_revision_conflict_preserve_dirty_typed_values(teacher_browser, viewport):
    _context, page = open_teacher(teacher_browser, viewport)
    save_calls = 0

    def save(route):
        nonlocal save_calls
        save_calls += 1
        route.fulfill(
            status=409,
            content_type="application/json",
            body=json.dumps({"error": {
                "code": "REVIEW_REVISION_CONFLICT",
                "message": "server detail must stay hidden",
                "field_errors": {"revision": ["server detail must stay hidden"]},
            }}),
        )

    install_review_reads(
        page,
        teacher_browser,
        queue_handler=lambda route: fulfill_json(route, [queue_row()]),
        detail_handler=lambda route: fulfill_json(route, review_detail()),
    )
    page.route(f"{teacher_browser.server.base_url}/api/conversations/42/review", save)
    unlock_review(page)
    page.locator("[data-review-form]").wait_for()
    reason = page.get_by_label("表达能力评分理由", exact=True)
    reason.fill("  ")
    page.get_by_role("button", name="保存并确认", exact=True).click()
    page.get_by_text("请填写评分理由。", exact=True).wait_for()
    assert save_calls == 0

    reason.fill("  能描述自己的观察。  ")
    page.get_by_role("button", name="保存并确认", exact=True).click()
    conflict = "该审阅已在别处更新，请复制当前修改后重新加载。"
    page.get_by_text(conflict, exact=True).wait_for()
    assert save_calls == 1
    assert reason.input_value() == "  能描述自己的观察。  "
    assert page.get_by_role("button", name="保存草稿", exact=True).is_enabled()
    assert page.get_by_role("button", name="保存并确认", exact=True).is_enabled()
    assert "server detail must stay hidden" not in page.locator("body").inner_text()


CLIENT_INVALID_CASES = [
    ("feeding", "请填写饲养记录。"),
    ("emotion", "请填写情绪。"),
    ("intensity-missing", "请输入 1 至 5 的整数。"),
    ("intensity-out-of-range", "请输入 1 至 5 的整数。"),
    ("insight", "请填写教育洞察。"),
    ("score-missing", "请选择 1 至 5 分。"),
    ("score-out-of-range", "请选择 1 至 5 分。"),
]


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
@pytest.mark.parametrize("case, expected_copy", CLIENT_INVALID_CASES)
def test_teacher_review_client_invalid_matrix_focuses_first_error_and_sends_zero_puts(
    teacher_browser, viewport, case, expected_copy
):
    _context, page = open_teacher(teacher_browser, viewport)
    saves = []
    install_review_reads(
        page,
        teacher_browser,
        queue_handler=lambda route: fulfill_json(route, [queue_row()]),
        detail_handler=lambda route: fulfill_json(route, review_detail()),
    )
    page.route(f"{teacher_browser.server.base_url}/api/conversations/42/review", lambda route: saves.append(route))
    unlock_review(page)
    page.locator("[data-review-form]").wait_for()

    if case == "feeding":
        target = page.get_by_label("饲养记录 1 内容", exact=True)
        target.fill("  ")
    elif case == "emotion":
        target = page.get_by_label("情绪", exact=True)
        target.fill("  ")
    elif case == "intensity-missing":
        target = page.get_by_label("情绪强度", exact=True)
        target.fill("")
    elif case == "intensity-out-of-range":
        target = page.get_by_label("情绪强度", exact=True)
        target.fill("6")
    elif case == "insight":
        target = page.get_by_label("教育洞察", exact=True)
        target.fill("  ")
    elif case == "score-missing":
        selected = page.get_by_role("radio", name="表达能力 4 分", exact=True)
        selected.evaluate("node => { for (const radio of node.form.elements[node.name]) radio.checked = false; }")
        target = page.get_by_role("radio", name="表达能力 1 分", exact=True)
    else:
        selected = page.get_by_role("radio", name="表达能力 4 分", exact=True)
        selected.evaluate("node => { node.value = '6'; node.checked = true; }")
        target = page.get_by_role("radio", name="表达能力 1 分", exact=True)

    page.get_by_role("button", name="保存草稿", exact=True).click()
    page.get_by_text(expected_copy, exact=True).wait_for()
    assert saves == []
    assert target.evaluate("node => document.activeElement === node")
    assert target.get_attribute("aria-invalid") == "true"


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_teacher_review_dirty_detail_reload_requires_one_native_discard_dialog(teacher_browser, viewport):
    _context, page = open_teacher(teacher_browser, viewport)
    detail_calls = 0

    def detail(route):
        nonlocal detail_calls
        detail_calls += 1
        fulfill_json(route, review_detail())

    install_review_reads(
        page,
        teacher_browser,
        queue_handler=lambda route: fulfill_json(route, [queue_row()]),
        detail_handler=detail,
    )
    unlock_review(page)
    page.locator("[data-review-form]").wait_for()
    insight = page.get_by_label("教育洞察", exact=True)
    insight.fill("尚未保存的修改")
    reload_button = page.get_by_role("button", name="重新加载此会话", exact=True)
    reload_button.click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_role("heading", name="有未保存的修改", exact=True).wait_for()
    dialog.get_by_role("button", name="继续编辑", exact=True).click()
    assert insight.input_value() == "尚未保存的修改"
    assert detail_calls == 1

    reload_button.click()
    page.get_by_role("dialog").get_by_role("button", name="放弃修改", exact=True).click()
    page.locator("[data-review-form]").wait_for()
    assert detail_calls == 2
    assert page.get_by_label("教育洞察", exact=True).input_value() == "能够清楚表达照料过程。"


SAVE_FAILURES = [
    ("validation", "部分内容未通过校验，请检查后重试。"),
    ("conflict", "该审阅已在别处更新，请复制当前修改后重新加载。"),
    ("auth", "教师会话已失效，请先重新解锁。"),
    ("missing", "该会话已不可审阅，请重新加载队列。"),
    ("server", "保存失败，请稍后重试。"),
    ("non-json", "保存失败，请稍后重试。"),
    ("offline", "保存失败，请稍后重试。"),
    ("wrong-conversation", "保存失败，请稍后重试。"),
    ("wrong-status", "保存失败，请稍后重试。"),
    ("stale-revision", "保存失败，请稍后重试。"),
    ("malformed-review", "保存失败，请稍后重试。"),
]


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
@pytest.mark.parametrize("failure, expected_copy", SAVE_FAILURES)
def test_teacher_review_save_failures_keep_exact_values_dirty_and_never_refresh(
    teacher_browser, viewport, failure, expected_copy
):
    _context, page = open_teacher(teacher_browser, viewport)
    queue_calls = 0

    def queue(route):
        nonlocal queue_calls
        queue_calls += 1
        fulfill_json(route, [queue_row()])

    def save(route):
        if failure == "validation":
            route.fulfill(status=422, content_type="application/json", body=json.dumps({"error": {
                "code": "REVIEW_VALIDATION_FAILED",
                "message": "raw validation detail",
                "field_errors": {"insight": ["raw insight detail"]},
            }}))
        elif failure == "conflict":
            route.fulfill(status=409, content_type="application/json", body=json.dumps({"error": {
                "code": "REVIEW_REVISION_CONFLICT", "message": "raw conflict detail",
                "field_errors": {"revision": ["raw revision detail"]},
            }}))
        elif failure == "auth":
            route.fulfill(status=401, content_type="application/json", body=json.dumps({"error": {
                "code": "TEACHER_AUTH_REQUIRED", "message": "raw auth detail", "field_errors": {},
            }}))
        elif failure == "missing":
            route.fulfill(status=404, content_type="application/json", body=json.dumps({"error": {
                "code": "CONVERSATION_NOT_FOUND", "message": "raw missing detail", "field_errors": {},
            }}))
        elif failure == "server":
            route.fulfill(status=500, content_type="application/json", body=json.dumps({"error": {
                "code": "INTERNAL_ERROR", "message": "raw server detail", "field_errors": {},
            }}))
        elif failure == "non-json":
            route.fulfill(status=502, content_type="text/html", body="raw html detail")
        elif failure == "offline":
            route.abort("failed")
        else:
            acknowledgement = {
                "saved": True,
                "conversation_id": 42,
                "review_status": "draft",
                "revision": 3,
                "saved_at": "2026-08-23T09:03:00Z",
                "review": review_detail()["review"],
            }
            if failure == "wrong-conversation":
                acknowledgement["conversation_id"] = 43
            elif failure == "wrong-status":
                acknowledgement["review_status"] = "confirmed"
            elif failure == "stale-revision":
                acknowledgement["revision"] = 2
            else:
                acknowledgement["review"] = {**acknowledgement["review"], "insight": " "}
            fulfill_json(route, acknowledgement)

    install_review_reads(
        page,
        teacher_browser,
        queue_handler=queue,
        detail_handler=lambda route: fulfill_json(route, review_detail()),
    )
    page.route(f"{teacher_browser.server.base_url}/api/conversations/42/review", save)
    unlock_review(page)
    page.locator("[data-review-form]").wait_for()
    insight = page.get_by_label("教育洞察", exact=True)
    typed = f"  保留输入-{failure}  "
    insight.fill(typed)
    page.get_by_role("button", name="保存草稿", exact=True).click()
    page.get_by_text(expected_copy, exact=True).wait_for()

    assert insight.input_value() == typed
    status = page.locator(".review-save-status")
    assert status.inner_text() == "保存失败，修改仍未保存"
    assert status.get_attribute("data-save-state") == "failure"
    assert page.get_by_role("button", name="保存草稿", exact=True).is_enabled()
    assert page.get_by_role("button", name="保存并确认", exact=True).is_enabled()
    assert queue_calls == 1
    body = page.locator("body").inner_text()
    assert "raw " not in body
    if failure == "validation":
        assert insight.get_attribute("aria-invalid") == "true"


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_teacher_review_direct_dom_edit_before_undefined_put_failure_stays_dirty_and_guarded(
    teacher_browser, viewport
):
    _context, page = open_teacher(teacher_browser, viewport)
    queue_calls = 0
    save_calls = 0
    page_errors = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))

    def queue(route):
        nonlocal queue_calls
        queue_calls += 1
        fulfill_json(route, [queue_row()])

    def save(route):
        nonlocal save_calls
        save_calls += 1
        fulfill_json(route, {"ignored": "Response.json is deliberately undefined"})

    install_review_reads(
        page,
        teacher_browser,
        queue_handler=queue,
        detail_handler=lambda route: fulfill_json(route, review_detail()),
    )
    page.route(f"{teacher_browser.server.base_url}/api/conversations/42/review", save)
    unlock_review(page)
    form = page.locator("[data-review-form]")
    form.wait_for()
    page.evaluate("""
        () => {
          const original = Response.prototype.json;
          Response.prototype.json = function () {
            if (this.url.endsWith('/api/conversations/42/review')) return Promise.resolve(undefined);
            return original.call(this);
          };
        }
    """)
    insight = page.get_by_label("教育洞察", exact=True)
    typed = "  未确认的原样输入  "
    insight.evaluate("(node, value) => { node.value = value; }", typed)
    assert page.locator(".review-save-status").inner_text() == "全部修改已保存"
    page.get_by_role("button", name="保存草稿", exact=True).click()
    page.get_by_text("保存失败，请稍后重试。", exact=True).wait_for(timeout=1_000)

    assert save_calls == 1
    assert queue_calls == 1
    assert insight.input_value() == typed
    assert form.locator("input, textarea, select, button").evaluate_all("nodes => nodes.every(node => !node.disabled)")
    status = page.locator(".review-save-status")
    assert status.inner_text() == "保存失败，修改仍未保存"
    assert status.get_attribute("data-save-state") == "failure"
    assert page.get_by_text("全部修改已保存", exact=True).count() == 0
    assert page.get_by_text("审阅已确认", exact=True).count() == 0
    assert page.evaluate("() => { const event = new Event('beforeunload', {cancelable: true}); window.dispatchEvent(event); return event.defaultPrevented; }")
    page.evaluate("location.hash = '#today'")
    dialog = page.get_by_role("dialog", name="有未保存的修改", exact=True)
    dialog.wait_for()
    dialog.get_by_role("button", name="继续编辑", exact=True).click()
    page.wait_for_timeout(50)
    assert page.evaluate("location.hash") == "#review?conversation_id=42"
    assert insight.input_value() == typed
    assert page_errors == []


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_teacher_review_delayed_save_is_single_flight_and_disables_every_editor_control(teacher_browser, viewport):
    _context, page = open_teacher(teacher_browser, viewport)
    held = []
    queue_calls = 0

    def queue(route):
        nonlocal queue_calls
        queue_calls += 1
        fulfill_json(route, [queue_row()])

    install_review_reads(
        page,
        teacher_browser,
        queue_handler=queue,
        detail_handler=lambda route: fulfill_json(route, review_detail()),
    )
    page.route(f"{teacher_browser.server.base_url}/api/conversations/42/review", lambda route: held.append(route))
    unlock_review(page)
    form = page.locator("[data-review-form]")
    form.wait_for()
    status = form.locator(".review-save-status")
    assert status.inner_text() == "全部修改已保存"
    status.evaluate("node => { window.__p4DelayedSaveStatus = node; }")
    draft = page.get_by_role("button", name="保存草稿", exact=True)
    confirm = page.get_by_role("button", name="保存并确认", exact=True)
    page.get_by_label("教育洞察", exact=True).fill("等待保存的修改")
    page.wait_for_function(
        "() => document.querySelector('.review-save-status')?.textContent === '有未保存的修改'"
    )
    draft.click()
    page.wait_for_function(
        "() => document.querySelector('.review-save-status')?.textContent === '正在保存…'"
    )
    assert page.evaluate(
        "document.querySelector('.review-save-status') === window.__p4DelayedSaveStatus"
    )
    confirm.evaluate("node => node.click()")
    draft.evaluate("node => node.click()")
    assert len(held) == 1
    assert form.locator("input, textarea, select, button").evaluate_all("nodes => nodes.every(node => node.disabled)")

    acknowledgement = {
        "saved": True,
        "conversation_id": 42,
        "review_status": "draft",
        "revision": 3,
        "saved_at": "2026-08-23T09:03:00Z",
        "review": review_detail()["review"],
    }
    fulfill_json(held.pop(), acknowledgement)
    page.get_by_text("全部修改已保存", exact=True).wait_for()
    assert page.evaluate(
        "document.querySelector('.review-save-status') === window.__p4DelayedSaveStatus"
    )
    assert queue_calls == 2


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_teacher_review_dirty_hash_navigation_continue_restores_review_and_discard_changes_route(teacher_browser, viewport):
    _context, page = open_teacher(teacher_browser, viewport)
    install_review_reads(
        page,
        teacher_browser,
        queue_handler=lambda route: fulfill_json(route, [queue_row()]),
        detail_handler=lambda route: fulfill_json(route, review_detail()),
    )
    unlock_review(page)
    page.locator("[data-review-form]").wait_for()
    insight = page.get_by_label("教育洞察", exact=True)
    insight.fill("尚未保存的跨页修改")
    assert page.evaluate("() => { const event = new Event('beforeunload', {cancelable: true}); window.dispatchEvent(event); return event.defaultPrevented; }")

    page.evaluate("location.hash = '#today'")
    dialog = page.get_by_role("dialog")
    dialog.get_by_role("button", name="继续编辑", exact=True).click()
    page.wait_for_timeout(50)
    assert page.evaluate("location.hash") == "#review?conversation_id=42"
    assert insight.input_value() == "尚未保存的跨页修改"

    page.evaluate("location.hash = '#today'")
    page.get_by_role("dialog").get_by_role("button", name="放弃修改", exact=True).click()
    page.get_by_role("heading", name="今日任务", exact=True).wait_for()
    assert page.evaluate("location.hash") == "#today"
    assert page.locator("[data-review-form]").count() == 0
