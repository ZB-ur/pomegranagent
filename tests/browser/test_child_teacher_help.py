from __future__ import annotations

import json

import pytest


VIEWPORTS = [{"width": 1024, "height": 576}, {"width": 1280, "height": 720}]
VIEWPORT_IDS = ["1024x576", "1280x720"]

SYNTHETIC_CHILD = {"id": 1, "name": "测试幼儿", "nickname": "小芽", "avatar": None}
SYNTHETIC_ACTIVE = {
    "conversation": {
        "id": 17,
        "child_id": 1,
        "status": "active",
        "revision": 2,
        "round": 1,
        "last_message_id": 102,
        "messages": [
            {"id": 101, "role": "child", "text": "我给小鸭准备了清水。"},
            {"id": 102, "role": "diary", "text": "谢谢你认真照顾小鸭。"},
        ],
    }
}


def route_child_api(harness, exact_fixture_url, state=None):
    state = state or {}
    state.setdefault("active", SYNTHETIC_ACTIVE)
    state.setdefault("chat_failures", 0)
    state.setdefault("chat_bodies", [])
    state.setdefault("complete_bodies", [])
    state.setdefault("active_reads", 0)
    port = harness.server.port

    def fulfill(route, payload, *, status=200):
        assert exact_fixture_url(route.request.url, port)
        route.fulfill(
            status=status,
            content_type="application/json",
            body=json.dumps(payload, ensure_ascii=False),
        )

    harness.page.route("**/api/roster/today", lambda route: fulfill(route, [SYNTHETIC_CHILD]))

    def active(route):
        state["active_reads"] += 1
        fulfill(route, state["active"])

    harness.page.route("**/api/children/1/active-conversation", active)

    def chat(route):
        body = route.request.post_data_json
        state["chat_bodies"].append(body)
        if state["chat_failures"] > 0:
            state["chat_failures"] -= 1
            fulfill(route, {
                "error": {
                    "code": "UPSTREAM_UNAVAILABLE",
                    "message": "synthetic retryable failure",
                    "retryable": True,
                }
            }, status=503)
            return
        fulfill(route, {
            "request_id": body["request_id"],
            "conversation_id": 17,
            "child_message_id": 103,
            "diary_message_id": 104,
            "reply": "这句话已经安全收到。",
            "round": 2,
            "ended": False,
            "end_reason": None,
            "replayed": False,
        })

    harness.page.route("**/api/chat", chat)

    def complete(route):
        body = route.request.post_data_json
        state["complete_bodies"].append(body)
        fulfill(route, {
            "conversation_id": 17,
            "conversation_saved": True,
            "status": "completed",
            "completed_at": "2026-08-23T00:01:00Z",
            "message_count": 2,
            "last_message_id": body["expected_last_message_id"],
            "analysis_job_id": 3,
            "analysis_status": "pending",
            "replayed": False,
        })

    harness.page.route("**/api/conversations/17/complete", complete)

    def tts(route):
        assert exact_fixture_url(route.request.url, port)
        route.fulfill(status=200, content_type="audio/mpeg", body=b"synthetic-audio")

    harness.page.route("**/api/tts?*", tts)
    return state


def route_teacher_auth(harness, exact_fixture_url, state=None):
    state = state or {"configured": False, "authenticated": False}
    state.setdefault("calls", [])
    state.setdefault("failure", None)
    port = harness.server.port

    def handler(route):
        assert exact_fixture_url(route.request.url, port)
        path = route.request.url.split("/api/auth/", 1)[1].split("?", 1)[0]
        body = route.request.post_data_json if route.request.post_data else None
        state["calls"].append({"path": path, "body": body})
        if path in {"setup", "unlock", "lock"} and state["failure"] is not None:
            code, raw_message = state["failure"]
            route.fulfill(
                status=401,
                content_type="application/json",
                body=json.dumps({"error": {"code": code, "message": raw_message, "retryable": False}}),
            )
            return
        if path == "setup":
            state.update(configured=True, authenticated=True)
        elif path == "unlock":
            state["authenticated"] = True
        elif path == "lock":
            state["authenticated"] = False
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "configured": bool(state["configured"]),
                "authenticated": bool(state["authenticated"]),
            }),
        )

    for name in ("status", "setup", "unlock", "lock"):
        harness.page.route(f"**/api/auth/{name}", handler)
    return state


def enter_ready_recovery(harness, viewport, *, active=True) -> None:
    page = harness.page
    page.set_viewport_size(viewport)
    page.goto(f"{harness.server.base_url}/", wait_until="domcontentloaded")
    page.get_by_role("button", name="开始", exact=True).click()
    if not active:
        page.get_by_role("button", name="小芽", exact=True).click()
    record = page.get_by_role("button", name="开始说话", exact=True)
    record.wait_for()
    record.click()
    page.wait_for_function("window.__childTest.recognition.instances.length > 0")
    page.evaluate("window.__childTest.recognition.emitError('not-allowed')")
    page.evaluate("window.__childTest.recognition.emitEnd()")
    page.get_by_role("button", name="请老师帮忙", exact=True).wait_for()


def open_teacher_dialog(page) -> None:
    page.locator("#teacher-help-button").click()
    page.locator("#teacher-help-dialog[open]").wait_for()


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_microphone_denial_focuses_visible_teacher_help_then_opens_dialog(
    child_page, exact_fixture_url, viewport
):
    route_child_api(child_page, exact_fixture_url)
    route_teacher_auth(child_page, exact_fixture_url)
    enter_ready_recovery(child_page, viewport)
    page = child_page.page
    page.wait_for_function("document.activeElement?.id === 'teacher-help-button'")
    assert page.locator("#child-status").inner_text() == "麦克风没有开启，请老师帮忙"
    open_teacher_dialog(page)
    assert page.locator("#teacher-help-dialog").get_attribute("aria-labelledby") == "teacher-help-title"
    assert page.locator("#teacher-pin").is_visible()


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_unlocked_teacher_dialog_uses_bounded_non_overlapping_child_visual_groups(
    child_page, exact_fixture_url, viewport
):
    route_child_api(child_page, exact_fixture_url)
    route_teacher_auth(child_page, exact_fixture_url, {
        "configured": True, "authenticated": True, "calls": [], "failure": None,
    })
    enter_ready_recovery(child_page, viewport)
    page = child_page.page
    open_teacher_dialog(page)
    page.locator("#teacher-actions").wait_for(state="visible")

    dialog = page.locator("#teacher-help-dialog")
    header = dialog.locator(".teacher-help-dialog__header")
    unlocked = dialog.locator(".teacher-help-dialog__section--unlocked")
    footer = dialog.locator(".teacher-help-dialog__footer")
    error = dialog.locator("#teacher-help-error")
    assert header.count() == 1
    assert header.locator("#teacher-help-title").count() == 1
    assert header.locator("#teacher-help-description").count() == 1
    assert unlocked.count() == 1
    assert unlocked.get_attribute("id") == "teacher-actions"
    assert footer.count() == 1
    assert footer.locator("#teacher-help-close").count() == 1
    assert error.inner_text() == ""
    assert error.is_visible() is False

    measured = dialog.evaluate(
        """
        dialog => {
          const rectFor = element => {
            const rect = element.getBoundingClientRect();
            return { x: rect.x, y: rect.y, width: rect.width, height: rect.height };
          };
          const groups = [
            dialog.querySelector('.teacher-help-dialog__header'),
            dialog.querySelector('#teacher-help-error'),
            dialog.querySelector('.teacher-help-dialog__section--unlocked'),
            dialog.querySelector('.teacher-help-dialog__footer'),
          ];
          const style = getComputedStyle(dialog);
          return {
            dialog: rectFor(dialog),
            groups: groups.filter(element => element.getClientRects().length > 0).map(rectFor),
            overflowY: style.overflowY,
            clientHeight: dialog.clientHeight,
            scrollHeight: dialog.scrollHeight,
            controls: [...dialog.querySelectorAll('button:not([hidden]),input:not([hidden]),textarea:not([hidden])')]
              .filter(element => element.getClientRects().length > 0)
              .map(element => ({ id: element.id, ...rectFor(element) })),
          };
        }
        """
    )
    dialog_rect = measured["dialog"]
    assert dialog_rect["x"] >= 0
    assert dialog_rect["y"] >= 0
    assert dialog_rect["x"] + dialog_rect["width"] <= viewport["width"] + 1
    assert dialog_rect["y"] + dialog_rect["height"] <= viewport["height"] + 1
    assert measured["overflowY"] in {"auto", "scroll"}
    assert measured["scrollHeight"] >= measured["clientHeight"]
    for earlier, later in zip(measured["groups"], measured["groups"][1:]):
        assert earlier["y"] + earlier["height"] <= later["y"]
    assert measured["controls"]
    undersized = [
        control for control in measured["controls"]
        if control["width"] < 44 or control["height"] < 44
    ]
    assert undersized == []


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_teacher_pin_setup_uses_adapter_auth_and_never_persists_or_renders_the_pin(
    child_page, exact_fixture_url, viewport
):
    route_child_api(child_page, exact_fixture_url)
    auth = route_teacher_auth(child_page, exact_fixture_url)
    enter_ready_recovery(child_page, viewport)
    page = child_page.page
    open_teacher_dialog(page)
    sentinel = "4826"
    page.locator("#teacher-pin").fill(sentinel)
    page.locator("#teacher-unlock-button").click()
    page.locator("#teacher-actions").wait_for(state="visible")
    assert [call["path"] for call in auth["calls"]] == ["status", "status", "setup"]
    assert page.locator("#teacher-pin").input_value() == ""
    assert sentinel not in page.locator("body").inner_text()
    assert sentinel not in page.evaluate("JSON.stringify(sessionStorage)")


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_teacher_pin_failure_uses_fixed_copy_and_clears_input_without_raw_server_detail(
    child_page, exact_fixture_url, viewport
):
    route_child_api(child_page, exact_fixture_url)
    auth = route_teacher_auth(child_page, exact_fixture_url)
    enter_ready_recovery(child_page, viewport)
    page = child_page.page
    open_teacher_dialog(page)
    auth["failure"] = ("PIN_INVALID", "raw-secret-detail-4826")
    page.locator("#teacher-pin").fill("4826")
    page.locator("#teacher-unlock-button").click()
    page.get_by_text("PIN 不正确，请重新输入", exact=True).wait_for()
    assert page.locator("#teacher-help-error").is_visible()
    assert page.locator("#teacher-pin").input_value() == ""
    assert "raw-secret-detail" not in page.locator("body").inner_text()


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_teacher_relock_calls_auth_lock_clears_dialog_fields_and_restores_help_focus(
    child_page, exact_fixture_url, viewport
):
    route_child_api(child_page, exact_fixture_url)
    auth = route_teacher_auth(child_page, exact_fixture_url, {
        "configured": True, "authenticated": True, "calls": [], "failure": None,
    })
    enter_ready_recovery(child_page, viewport)
    page = child_page.page
    open_teacher_dialog(page)
    page.locator("#teacher-text").fill("机密补录-4826")
    page.locator("#teacher-lock-button").click()
    page.wait_for_function("!document.querySelector('#teacher-help-dialog')?.open")
    assert [call["path"] for call in auth["calls"]] == ["status", "lock"]
    assert page.locator("#teacher-text").input_value() == ""
    assert page.evaluate("document.activeElement?.id") == "teacher-help-button"
    assert "机密补录-4826" not in page.evaluate("JSON.stringify(sessionStorage)")


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_unlocked_teacher_close_waits_for_auth_lock_before_dismissing(
    child_page, exact_fixture_url, viewport
):
    route_child_api(child_page, exact_fixture_url)
    auth = route_teacher_auth(child_page, exact_fixture_url, {
        "configured": True, "authenticated": True, "calls": [], "failure": None,
    })
    enter_ready_recovery(child_page, viewport)
    page = child_page.page
    open_teacher_dialog(page)
    page.locator("#teacher-text").fill("机密补录-4826")
    page.locator("#teacher-help-close").click()
    page.wait_for_function("!document.querySelector('#teacher-help-dialog')?.open")
    assert [call["path"] for call in auth["calls"]] == ["status", "lock"]
    assert page.locator("#teacher-text").input_value() == ""
    assert page.evaluate("document.activeElement?.id") == "teacher-help-button"


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_failed_teacher_close_relock_keeps_dialog_text_and_retry_controls(
    child_page, exact_fixture_url, viewport
):
    route_child_api(child_page, exact_fixture_url)
    auth = route_teacher_auth(child_page, exact_fixture_url, {
        "configured": True, "authenticated": True, "calls": [], "failure": None,
    })
    enter_ready_recovery(child_page, viewport)
    page = child_page.page
    open_teacher_dialog(page)
    copy = "机密补录-4826"
    page.locator("#teacher-text").fill(copy)
    auth["failure"] = ("LOCK_FAILED", "raw-private-lock-detail-4826")
    page.locator("#teacher-help-close").click()
    assert page.locator("#teacher-help-dialog").evaluate("dialog => dialog.open") is True
    page.get_by_text("老师帮助暂时不可用，请稍后重试", exact=True).wait_for()
    assert [call["path"] for call in auth["calls"]] == ["status", "lock"]
    assert page.locator("#teacher-text").input_value() == copy
    assert page.locator("#teacher-help-close").is_enabled()
    assert page.locator("#teacher-text").is_enabled()
    assert "raw-private-lock-detail" not in page.locator("body").inner_text()


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_teacher_text_failure_retains_text_and_retry_reuses_one_request_id(
    child_page, exact_fixture_url, viewport
):
    api = route_child_api(child_page, exact_fixture_url, {"chat_failures": 1})
    route_teacher_auth(child_page, exact_fixture_url, {
        "configured": True, "authenticated": True, "calls": [], "failure": None,
    })
    enter_ready_recovery(child_page, viewport)
    page = child_page.page
    open_teacher_dialog(page)
    copy = "我刚才给小鸭添了清水"
    page.locator("#teacher-text").fill(copy)
    page.locator("#teacher-submit-text").click()
    page.get_by_role("button", name="重新发送这句话", exact=True).wait_for()
    assert page.locator("#teacher-text").input_value() == copy
    page.locator("#teacher-submit-text").click()
    page.wait_for_function("window.__childTest.audio.instances.length === 1")
    page.evaluate("window.__childTest.audio.emitPlaying(0)")
    page.evaluate("window.__childTest.audio.emitEnded(0)")
    page.locator("#record-button").wait_for()
    assert len(api["chat_bodies"]) == 2
    assert api["chat_bodies"][0]["request_id"] == api["chat_bodies"][1]["request_id"]
    assert [body["text"] for body in api["chat_bodies"]] == [copy, copy]


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_teacher_recovery_actions_preserve_boundaries_and_complete_only_when_safe(
    child_page, exact_fixture_url, viewport
):
    api = route_child_api(child_page, exact_fixture_url)
    auth = route_teacher_auth(child_page, exact_fixture_url, {
        "configured": True, "authenticated": True, "calls": [], "failure": None,
    })
    enter_ready_recovery(child_page, viewport)
    page = child_page.page
    open_teacher_dialog(page)
    page.locator("#teacher-actions").wait_for(state="visible")
    assert page.locator("#teacher-end-session").is_enabled()
    active_reads = api["active_reads"]
    with page.expect_request_finished(
        lambda request: "/api/children/1/active-conversation" in request.url
    ) as finished:
        page.locator("#teacher-retry-recovery").click()
    assert exact_fixture_url(finished.value.url, child_page.server.port)
    assert api["active_reads"] > active_reads
    state = page.locator(".child-view").get_attribute("data-state")
    assert state == "recovery"
    assert page.locator("#teacher-actions").is_visible()
    assert page.locator("#teacher-retry-microphone").is_enabled()
    starts = page.evaluate("window.__childTest.recognition.starts")
    page.locator("#teacher-retry-microphone").click()
    page.wait_for_function(f"window.__childTest.recognition.starts > {starts}")
    page.evaluate("window.__childTest.recognition.emitError('not-allowed')")
    page.wait_for_function("document.querySelector('.child-view')?.dataset.state === 'recovery'")
    open_teacher_dialog(page)
    assert page.locator("#teacher-pin").is_visible()
    page.locator("#teacher-pin").fill("4826")
    page.locator("#teacher-unlock-button").click()
    page.locator("#teacher-actions").wait_for(state="visible")
    page.locator("#teacher-end-session").click()
    page.get_by_role("button", name="换下一位小朋友", exact=True).wait_for()
    assert api["complete_bodies"] == [{"expected_last_message_id": 102}]
    assert [call["path"] for call in auth["calls"]] == [
        "status", "lock", "status", "status", "unlock", "lock",
    ]


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_teacher_dialog_traps_focus_blocks_global_space_and_restores_on_escape(
    child_page, exact_fixture_url, viewport
):
    route_child_api(child_page, exact_fixture_url)
    auth = route_teacher_auth(child_page, exact_fixture_url, {
        "configured": True, "authenticated": True, "calls": [], "failure": None,
    })
    enter_ready_recovery(child_page, viewport)
    page = child_page.page
    open_teacher_dialog(page)
    starts = page.evaluate("window.__childTest.recognition.starts")
    page.locator("#teacher-text").focus()
    page.keyboard.press("Shift+Tab")
    assert page.evaluate("document.activeElement?.id") == "teacher-help-close"
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement?.id") == "teacher-text"
    page.locator("#teacher-help-title").focus()
    page.keyboard.press("Space")
    assert page.evaluate("window.__childTest.recognition.starts") == starts
    page.keyboard.press("Escape")
    page.wait_for_function("!document.querySelector('#teacher-help-dialog')?.open")
    assert [call["path"] for call in auth["calls"]] == ["status", "lock"]
    assert page.evaluate("document.activeElement?.id") == "teacher-help-button"
