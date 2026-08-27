from __future__ import annotations

import json

import pytest


VIEWPORTS = [{"width": 1024, "height": 576}, {"width": 1280, "height": 720}]

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


@pytest.fixture
def unused_tcp_port(free_tcp_port):
    return free_tcp_port


def install_teacher_help_fakes(page) -> None:
    page.add_init_script(
        """
        window.__teacherRecognition = { instances: [], starts: 0, stops: 0 };
        class TeacherRecognition {
          constructor() { window.__teacherRecognition.instances.push(this); }
          start() { window.__teacherRecognition.starts += 1; }
          stop() { window.__teacherRecognition.stops += 1; if (this.onend) this.onend(); }
          abort() { if (this.onend) this.onend(); }
        }
        window.SpeechRecognition = TeacherRecognition;
        window.webkitSpeechRecognition = TeacherRecognition;
        window.speechSynthesis = {
          speak(utterance) { queueMicrotask(() => utterance.onend && utterance.onend()); },
          cancel() {},
        };
        window.SpeechSynthesisUtterance = class { constructor(text) { this.text = text; } };
        """
    )


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
        if path in {"setup", "unlock"} and state["failure"] is not None:
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
    page.wait_for_function("window.__teacherRecognition.instances.length > 0")
    page.evaluate(
        """
        () => {
          const current = window.__teacherRecognition.instances.at(-1);
          current.onerror && current.onerror({ error: 'not-allowed' });
          current.onend && current.onend();
        }
        """
    )
    page.get_by_role("button", name="老师帮忙", exact=True).wait_for()


def open_teacher_dialog(page) -> None:
    page.locator("#teacher-help-button").click()
    page.locator("#teacher-help-dialog[open]").wait_for()


@pytest.mark.parametrize("viewport", VIEWPORTS)
def test_microphone_denial_focuses_visible_teacher_help_then_opens_dialog(
    child_page, exact_fixture_url, viewport
):
    install_teacher_help_fakes(child_page.page)
    route_child_api(child_page, exact_fixture_url)
    route_teacher_auth(child_page, exact_fixture_url)
    enter_ready_recovery(child_page, viewport)
    page = child_page.page
    page.wait_for_function("document.activeElement?.id === 'teacher-help-button'")
    assert page.locator("#child-status").inner_text() == "麦克风没有开启，请老师帮忙"
    open_teacher_dialog(page)
    assert page.locator("#teacher-help-dialog").get_attribute("aria-labelledby") == "teacher-help-title"
    assert page.locator("#teacher-pin").is_visible()


@pytest.mark.parametrize("viewport", VIEWPORTS)
def test_teacher_pin_setup_uses_adapter_auth_and_never_persists_or_renders_the_pin(
    child_page, exact_fixture_url, viewport
):
    install_teacher_help_fakes(child_page.page)
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


@pytest.mark.parametrize("viewport", VIEWPORTS)
def test_teacher_pin_failure_uses_fixed_copy_and_clears_input_without_raw_server_detail(
    child_page, exact_fixture_url, viewport
):
    install_teacher_help_fakes(child_page.page)
    route_child_api(child_page, exact_fixture_url)
    auth = route_teacher_auth(child_page, exact_fixture_url)
    enter_ready_recovery(child_page, viewport)
    page = child_page.page
    open_teacher_dialog(page)
    auth["failure"] = ("PIN_INVALID", "raw-secret-detail-4826")
    page.locator("#teacher-pin").fill("4826")
    page.locator("#teacher-unlock-button").click()
    page.get_by_text("PIN 不正确，请重新输入", exact=True).wait_for()
    assert page.locator("#teacher-pin").input_value() == ""
    assert "raw-secret-detail" not in page.locator("body").inner_text()


@pytest.mark.parametrize("viewport", VIEWPORTS)
def test_teacher_relock_calls_auth_lock_clears_dialog_fields_and_restores_help_focus(
    child_page, exact_fixture_url, viewport
):
    install_teacher_help_fakes(child_page.page)
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


@pytest.mark.parametrize("viewport", VIEWPORTS)
def test_teacher_text_failure_retains_text_and_retry_reuses_one_request_id(
    child_page, exact_fixture_url, viewport
):
    install_teacher_help_fakes(child_page.page)
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
    page.locator("#record-button").wait_for()
    assert len(api["chat_bodies"]) == 2
    assert api["chat_bodies"][0]["request_id"] == api["chat_bodies"][1]["request_id"]
    assert [body["text"] for body in api["chat_bodies"]] == [copy, copy]


@pytest.mark.parametrize("viewport", VIEWPORTS)
def test_teacher_recovery_actions_preserve_boundaries_and_complete_only_when_safe(
    child_page, exact_fixture_url, viewport
):
    install_teacher_help_fakes(child_page.page)
    api = route_child_api(child_page, exact_fixture_url)
    route_teacher_auth(child_page, exact_fixture_url, {
        "configured": True, "authenticated": True, "calls": [], "failure": None,
    })
    enter_ready_recovery(child_page, viewport)
    page = child_page.page
    open_teacher_dialog(page)
    page.locator("#teacher-actions").wait_for(state="visible")
    assert page.locator("#teacher-end-session").is_enabled()
    active_reads = api["active_reads"]
    page.locator("#teacher-retry-recovery").click()
    page.wait_for_timeout(300)
    assert api["active_reads"] > active_reads
    state = page.locator(".child-view").get_attribute("data-state")
    assert state == "recovery"
    assert page.locator("#teacher-actions").is_visible()
    assert page.locator("#teacher-retry-microphone").is_enabled()
    starts = page.evaluate("window.__teacherRecognition.starts")
    page.locator("#teacher-retry-microphone").click()
    page.wait_for_function(f"window.__teacherRecognition.starts > {starts}")
    page.evaluate("window.__teacherRecognition.instances.at(-1).onerror({error:'not-allowed'})")
    page.wait_for_function("document.querySelector('.child-view')?.dataset.state === 'recovery'")
    open_teacher_dialog(page)
    page.locator("#teacher-end-session").click()
    page.get_by_role("button", name="换下一位小朋友", exact=True).wait_for()
    assert api["complete_bodies"] == [{"expected_last_message_id": 102}]


@pytest.mark.parametrize("viewport", VIEWPORTS)
def test_teacher_dialog_traps_focus_blocks_global_space_and_restores_on_escape(
    child_page, exact_fixture_url, viewport
):
    install_teacher_help_fakes(child_page.page)
    route_child_api(child_page, exact_fixture_url)
    route_teacher_auth(child_page, exact_fixture_url, {
        "configured": True, "authenticated": True, "calls": [], "failure": None,
    })
    enter_ready_recovery(child_page, viewport)
    page = child_page.page
    open_teacher_dialog(page)
    starts = page.evaluate("window.__teacherRecognition.starts")
    page.locator("#teacher-text").focus()
    page.keyboard.press("Shift+Tab")
    assert page.evaluate("document.activeElement?.id") == "teacher-help-close"
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement?.id") == "teacher-text"
    page.locator("#teacher-help-title").focus()
    page.keyboard.press("Space")
    assert page.evaluate("window.__teacherRecognition.starts") == starts
    page.keyboard.press("Escape")
    assert page.evaluate("document.activeElement?.id") == "teacher-help-button"
