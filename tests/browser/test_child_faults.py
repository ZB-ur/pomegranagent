import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest


ROOT = Path(__file__).resolve().parents[2]
VIEWPORTS = [{"width": 1024, "height": 576}, {"width": 1280, "height": 720}]
STAGE_GEOMETRY = {
    (1024, 576): {
        "panel": {"x": 80, "y": 224, "width": 608, "height": 308},
        "orb": {"x": 712, "y": 224, "width": 232, "height": 308},
    },
    (1280, 720): {
        "panel": {"x": 116, "y": 240, "width": 760, "height": 396},
        "orb": {"x": 900, "y": 240, "width": 264, "height": 396},
    },
}
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
NEAR_LIMIT_CHILD_TEXT = "起" + ("鸭" * 1988) + "终"


def _keyboard_focus(page, target, *, limit=80):
    assert target.count() == 1
    for _index in range(limit + 1):
        if target.evaluate("node => document.activeElement === node"):
            return
        page.keyboard.press("Tab")
    raise AssertionError(
        f"target was not reached through {limit} page-keyboard Tab actions: "
        f"{target.evaluate('node => node.outerHTML')}"
    )


def _start_held_chat(child_page, exact_fixture_url, viewport):
    page = child_page.page
    page.set_viewport_size(viewport)
    port = child_page.server.port
    held = []

    child_page.fulfill_json("**/api/roster/today", [SYNTHETIC_CHILD])
    child_page.fulfill_json("**/api/children/1/active-conversation", SYNTHETIC_ACTIVE)

    def chat(route):
        assert exact_fixture_url(route.request.url, port)
        held.append((route, route.request.post_data_json))

    page.route("**/api/chat", chat)
    page.goto(f"{child_page.server.base_url}/", wait_until="domcontentloaded")
    page.get_by_role("button", name="开始", exact=True).click()
    page.get_by_role("button", name="开始说话", exact=True).click()
    page.wait_for_function("window.__childTest.recognition.starts === 1")
    page.evaluate("window.__childTest.recognition.emitResult(0, '我给小鸭讲了一个故事。', true)")
    page.keyboard.press("Space")
    page.wait_for_function("window.__childTest.recognition.stops === 1")
    with page.expect_request(lambda request: request.url.endswith("/api/chat")) as requested:
        page.evaluate("window.__childTest.recognition.emitEnd()")
    assert exact_fixture_url(requested.value.url, port)
    page.evaluate("() => Promise.resolve()")
    assert len(held) == 1
    return page, held


def _chat_success_for(body):
    return {
        "request_id": body["request_id"],
        "conversation_id": 17,
        "child_message_id": 103,
        "diary_message_id": 104,
        "reply": "今天的小鸭很开心。",
        "round": 2,
        "ended": False,
        "end_reason": None,
        "replayed": False,
    }


def _install_ended_flow(child_page, exact_fixture_url, *, complete_ok=True):
    page = child_page.page
    port = child_page.server.port
    complete_requests = []
    child_page.fulfill_json("**/api/roster/today", [SYNTHETIC_CHILD])
    child_page.fulfill_json("**/api/children/1/active-conversation", SYNTHETIC_ACTIVE)

    def chat(route):
        assert exact_fixture_url(route.request.url, port)
        body = route.request.post_data_json
        payload = _chat_success_for(body)
        payload.update({"ended": True, "end_reason": "complete"})
        route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))

    def tts(route):
        assert exact_fixture_url(route.request.url, port)
        route.fulfill(status=200, content_type="audio/mpeg", body=b"synthetic-audio")

    def complete(route):
        assert exact_fixture_url(route.request.url, port)
        complete_requests.append(route.request.post_data_json)
        if not complete_ok:
            route.fulfill(
                status=500,
                content_type="application/json",
                body=json.dumps({
                    "error": {
                        "code": "UPSTREAM_UNAVAILABLE",
                        "message": "raw-completion-a11y-secret",
                        "retryable": True,
                    }
                }),
            )
            return
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "conversation_id": 17,
                "conversation_saved": True,
                "status": "completed",
                "completed_at": "2026-08-23T00:01:00.000Z",
                "message_count": 4,
                "last_message_id": 104,
                "analysis_job_id": 3,
                "analysis_status": "pending",
                "replayed": False,
            }),
        )

    page.route("**/api/chat", chat)
    page.route("**/api/tts?*", tts)
    page.route("**/api/conversations/17/complete", complete)
    return complete_requests


def _drive_ended_flow(child_page):
    page = child_page.page
    page.goto(f"{child_page.server.base_url}/", wait_until="domcontentloaded")
    page.get_by_role("button", name="开始", exact=True).click()
    page.get_by_role("button", name="开始说话", exact=True).click()
    page.wait_for_function("window.__childTest.recognition.starts === 1")
    page.evaluate("window.__childTest.recognition.emitResult(0, '我给小鸭讲了一个故事。', true)")
    page.keyboard.press("Space")
    page.wait_for_function("window.__childTest.recognition.stops === 1")
    page.evaluate("window.__childTest.recognition.emitEnd()")
    page.wait_for_function("window.__childTest.audio.instances.length === 1")
    page.evaluate("window.__childTest.audio.emitPlaying(0)")
    page.evaluate("window.__childTest.audio.emitEnded(0)")
    return page


def _assert_fault_projection_accessibility(page, *, expected_focus, expected_alert):
    main = page.get_by_role("main")
    assert main.count() == 1
    labelled_by = main.get_attribute("aria-labelledby")
    assert labelled_by == "app-title"
    assert page.locator(f"#{labelled_by}").get_attribute("role") is None
    assert page.locator(f"#{labelled_by}").evaluate(
        "element => /^H[1-6]$/.test(element.tagName)"
    )

    alert = page.get_by_role("alert")
    assert alert.count() == 1
    assert alert.locator(".child-message__text").inner_text() == expected_alert
    assert page.get_by_role("status").count() == 1
    page.locator(expected_focus).wait_for()
    page.wait_for_function(
        "selector => document.activeElement?.matches(selector) === true",
        arg=expected_focus,
    )

    projection = page.evaluate(
        """
        () => {
          const visible = (element) => {
            const style = getComputedStyle(element);
            const rect = element.getBoundingClientRect();
            return style.display !== 'none'
              && style.visibility !== 'hidden'
              && rect.width > 0
              && rect.height > 0;
          };
          const buttons = [...document.querySelectorAll('button')].filter(visible);
          const names = buttons.map((button) =>
            button.getAttribute('aria-label') || button.textContent.trim()
          );
          const focused = document.activeElement;
          const focusStyle = getComputedStyle(focused);
          const animated = [...document.querySelectorAll('#child-app, #child-app *')]
            .filter(visible)
            .map((element) => {
              const style = getComputedStyle(element);
              return {
                animationDuration: style.animationDuration,
                transitionDuration: style.transitionDuration,
              };
            });
          return {
            names,
            buttonRects: buttons.map((button) => {
              const rect = button.getBoundingClientRect();
              return {
                width: rect.width,
                height: rect.height,
                left: rect.left,
                right: rect.right,
              };
            }),
            focus: {
              id: focused?.id || null,
              outlineStyle: focusStyle.outlineStyle,
              outlineWidth: focusStyle.outlineWidth,
              outlineColor: focusStyle.outlineColor,
            },
            animated,
            scrollWidth: document.documentElement.scrollWidth,
            viewportWidth: window.innerWidth,
          };
        }
        """
    )
    assert projection["names"]
    assert all(projection["names"])
    assert len(projection["names"]) == len(set(projection["names"]))
    assert projection["focus"]["id"] == expected_focus.removeprefix("#")
    assert projection["focus"]["outlineStyle"] != "none"
    assert projection["focus"]["outlineWidth"] != "0px"
    assert projection["focus"]["outlineColor"] not in {
        "rgba(0, 0, 0, 0)",
        "transparent",
    }
    assert projection["scrollWidth"] <= projection["viewportWidth"]
    assert all(rect["width"] >= 44 and rect["height"] >= 44
               for rect in projection["buttonRects"])
    assert all(rect["left"] >= 0 and rect["right"] <= projection["viewportWidth"]
               for rect in projection["buttonRects"])
    assert all(
        item["animationDuration"] in {"0s", "0ms"}
        and item["transitionDuration"] in {"0s", "0ms"}
        for item in projection["animated"]
    )


def test_shared_unused_tcp_port_is_available_to_every_browser_module(unused_tcp_port):
    assert isinstance(unused_tcp_port, int)
    assert unused_tcp_port > 0
    browser_dir = ROOT / "tests/browser"
    conftest_source = (browser_dir / "conftest.py").read_text(encoding="utf-8")
    assert sum(line.startswith("def unused_tcp_port(")
               for line in conftest_source.splitlines()) == 1
    for test_path in (
        browser_dir / "test_child_shell.py",
        browser_dir / "test_child_teacher_help.py",
        browser_dir / "test_child_faults.py",
    ):
        assert not any(
            line.startswith("def unused_tcp_port(")
            for line in test_path.read_text(encoding="utf-8").splitlines()
        )


def test_browser_parent_logging_is_redirected_from_real_application_log(
    browser_parent_logging_guard,
):
    import logging

    real_log = (ROOT / "logs" / "app.log").resolve()
    handler_paths = {
        Path(handler.baseFilename).resolve()
        for handler in logging.getLogger().handlers
        if getattr(handler, "baseFilename", None) is not None
    }
    assert browser_parent_logging_guard.resolve() in handler_paths
    assert real_log not in handler_paths


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=["1024x576", "1280x720"])
def test_natural_recognition_end_restarts_and_preserves_text_until_user_finish(
    child_page, exact_fixture_url, viewport
):
    page = child_page.page
    page.set_viewport_size(viewport)
    chat_requests = []
    port = child_page.server.port

    child_page.fulfill_json("**/api/roster/today", [SYNTHETIC_CHILD])
    child_page.fulfill_json("**/api/children/1/active-conversation", SYNTHETIC_ACTIVE)

    def chat(route):
        assert exact_fixture_url(route.request.url, port)
        chat_requests.append(route.request.post_data_json)
        route.fulfill(
            status=503,
            content_type="application/json",
            body=json.dumps({
                "error": {
                    "code": "UPSTREAM_UNAVAILABLE",
                    "message": "synthetic retryable failure",
                    "retryable": True,
                }
            }),
        )

    page.route("**/api/chat", chat)
    page.goto(f"{child_page.server.base_url}/", wait_until="domcontentloaded")
    page.get_by_role("button", name="开始", exact=True).click()
    record = page.get_by_role("button", name="开始说话", exact=True)
    record.wait_for()
    record.click()

    assert page.evaluate("window.__childTest.recognition.starts") == 1
    page.evaluate("window.__childTest.recognition.emitResult(0, '我给小鸭换了', true)")
    assert chat_requests == []

    page.evaluate("window.__childTest.recognition.emitEnd()")
    page.wait_for_function("window.__childTest.recognition.starts === 2")
    assert chat_requests == []
    assert page.locator(".child-view").get_attribute("data-state") == "listening"
    assert page.evaluate("window.__childTest.recognition.stops") == 0

    page.evaluate("window.__childTest.recognition.emitResult(0, '清水。', true)")
    assert chat_requests == []
    page.keyboard.press("Space")
    page.wait_for_function("window.__childTest.recognition.stops === 1")
    assert chat_requests == []

    with page.expect_request(lambda request: request.url.endswith("/api/chat")):
        page.evaluate("window.__childTest.recognition.emitEnd()")
    page.get_by_role("button", name="重新发送", exact=True).wait_for()
    assert len(chat_requests) == 1
    assert chat_requests[0]["text"] == "我给小鸭换了清水。"
    serialized = page.evaluate(
        "sessionStorage.getItem('duck-diary.child-session.v1')"
    )
    assert serialized is not None
    assert "我给小鸭换了清水。" in serialized

    page.evaluate("window.__childTest.recognition.emitResult(0, '重复结果', true)")
    page.evaluate("window.__childTest.recognition.emitEnd()")
    page.evaluate("() => Promise.resolve()")
    assert len(chat_requests) == 1


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=["1024x576", "1280x720"])
def test_manual_space_stop_requires_one_explicit_end(child_page, exact_fixture_url, viewport):
    page = child_page.page
    page.set_viewport_size(viewport)
    chat_requests = []
    port = child_page.server.port

    child_page.fulfill_json("**/api/roster/today", [SYNTHETIC_CHILD])
    child_page.fulfill_json("**/api/children/1/active-conversation", SYNTHETIC_ACTIVE)

    def chat(route):
        assert exact_fixture_url(route.request.url, port)
        chat_requests.append(route.request.post_data_json)
        route.fulfill(
            status=503,
            content_type="application/json",
            body=json.dumps({
                "error": {
                    "code": "UPSTREAM_UNAVAILABLE",
                    "message": "synthetic retryable failure",
                    "retryable": True,
                }
            }),
        )

    page.route("**/api/chat", chat)
    page.goto(f"{child_page.server.base_url}/", wait_until="domcontentloaded")
    page.get_by_role("button", name="开始", exact=True).click()
    page.get_by_role("button", name="开始说话", exact=True).wait_for()

    page.locator("#app-title").focus()
    page.keyboard.press("Space")
    page.wait_for_function("window.__childTest.recognition.starts === 1")
    page.evaluate("window.__childTest.recognition.emitResult(0, '我给小鸭加了水。', true)")
    assert chat_requests == []

    page.keyboard.press("Space")
    page.wait_for_function("window.__childTest.recognition.stops === 1")
    assert chat_requests == []

    page.evaluate("window.__childTest.recognition.emitEnd()")
    page.get_by_role("button", name="重新发送", exact=True).wait_for()
    assert len(chat_requests) == 1

    page.evaluate("window.__childTest.recognition.emitEnd()")
    page.evaluate("() => Promise.resolve()")
    assert len(chat_requests) == 1


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=["1024x576", "1280x720"])
def test_explicit_stop_without_end_recovers_once_at_5000ms_without_chat(
    child_page, exact_fixture_url, viewport
):
    page = child_page.page
    page.clock.install(time=1_700_000_000)
    page.set_viewport_size(viewport)
    chat_requests = []
    port = child_page.server.port

    child_page.fulfill_json("**/api/roster/today", [SYNTHETIC_CHILD])
    child_page.fulfill_json("**/api/children/1/active-conversation", SYNTHETIC_ACTIVE)

    def chat(route):
        assert exact_fixture_url(route.request.url, port)
        chat_requests.append(route.request.post_data_json)
        route.fulfill(status=503, content_type="application/json", body="{}")

    page.route("**/api/chat", chat)
    page.goto(f"{child_page.server.base_url}/", wait_until="domcontentloaded")
    page.get_by_role("button", name="开始", exact=True).click()
    page.get_by_role("button", name="开始说话", exact=True).click()
    page.wait_for_function("window.__childTest.recognition.starts === 1")
    page.evaluate("window.__childTest.recognition.emitResult(0, '这句话不能丢。', true)")
    page.clock.pause_at(page.evaluate("Date.now()") / 1000 + 1)

    page.keyboard.press("Space")
    page.wait_for_function("window.__childTest.recognition.stops === 1")
    assert page.locator(".child-view").get_attribute("data-state") == "listening"
    assert chat_requests == []

    page.clock.fast_forward(4_999)
    assert page.locator(".child-view").get_attribute("data-state") == "listening"
    assert chat_requests == []

    page.clock.fast_forward(1)
    page.wait_for_function(
        "document.querySelector('.child-view')?.dataset.state === 'recovery'"
    )
    assert chat_requests == []
    page.clock.fast_forward(5_000)
    assert page.locator(".child-view").get_attribute("data-state") == "recovery"
    assert chat_requests == []


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=["1024x576", "1280x720"])
def test_silence_clock_never_stops_or_submits_without_explicit_finish(
    child_page, exact_fixture_url, viewport
):
    page = child_page.page
    page.clock.install(time=1_700_000_000)
    page.set_viewport_size(viewport)
    chat_requests = []
    port = child_page.server.port

    child_page.fulfill_json("**/api/roster/today", [SYNTHETIC_CHILD])
    child_page.fulfill_json("**/api/children/1/active-conversation", SYNTHETIC_ACTIVE)

    def chat(route):
        assert exact_fixture_url(route.request.url, port)
        chat_requests.append(route.request.post_data_json)
        route.fulfill(status=503, content_type="application/json", body="{}")

    page.route("**/api/chat", chat)
    page.goto(f"{child_page.server.base_url}/", wait_until="domcontentloaded")
    page.get_by_role("button", name="开始", exact=True).click()
    record = page.get_by_role("button", name="开始说话", exact=True)
    record.wait_for()
    page.clock.pause_at(page.evaluate("Date.now()") / 1000 + 1)
    record.click()
    page.wait_for_function("window.__childTest.recognition.starts === 1")

    page.clock.fast_forward(1499)
    assert page.evaluate("window.__childTest.recognition.stops") == 0
    page.clock.fast_forward(1)
    assert page.evaluate("window.__childTest.recognition.stops") == 0
    assert page.locator(".child-view").get_attribute("data-state") == "listening"
    assert chat_requests == []

    page.keyboard.press("Space")
    page.wait_for_function("window.__childTest.recognition.stops === 1")

    page.evaluate("window.__childTest.recognition.emitEnd()")
    page.get_by_role("button", name="开始说话", exact=True).wait_for()
    assert chat_requests == []


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=["1024x576", "1280x720"])
def test_chat_retryable_fault_reuses_persisted_request_id_once(
    child_page, exact_fixture_url, viewport
):
    page = child_page.page
    page.set_viewport_size(viewport)
    chat_bodies = []
    tts_requests = []
    port = child_page.server.port

    child_page.fulfill_json("**/api/roster/today", [SYNTHETIC_CHILD])
    child_page.fulfill_json("**/api/children/1/active-conversation", SYNTHETIC_ACTIVE)

    def chat(route):
        assert exact_fixture_url(route.request.url, port)
        body = route.request.post_data_json
        chat_bodies.append(body)
        if len(chat_bodies) == 1:
            route.fulfill(
                status=503,
                content_type="application/json",
                body=json.dumps({
                    "error": {
                        "code": "UPSTREAM_UNAVAILABLE",
                        "message": "synthetic retryable failure",
                        "retryable": True,
                    }
                }),
            )
            return
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "request_id": body["request_id"],
                "conversation_id": 17,
                "child_message_id": 103,
                "diary_message_id": 104,
                "reply": "这句话已经安全收到。",
                "round": 2,
                "ended": False,
                "end_reason": None,
                "replayed": False,
            }),
        )

    def tts(route):
        assert exact_fixture_url(route.request.url, port)
        tts_requests.append(route.request.url)
        route.fulfill(status=200, content_type="audio/mpeg", body=b"synthetic-audio")

    page.route("**/api/chat", chat)
    page.route("**/api/tts?*", tts)
    page.goto(f"{child_page.server.base_url}/", wait_until="domcontentloaded")
    page.get_by_role("button", name="开始", exact=True).click()
    page.get_by_role("button", name="开始说话", exact=True).click()
    page.wait_for_function("window.__childTest.recognition.starts === 1")
    page.evaluate("window.__childTest.recognition.emitResult(0, '我给小鸭添了清水。', true)")
    page.keyboard.press("Space")
    page.wait_for_function("window.__childTest.recognition.stops === 1")
    page.evaluate("window.__childTest.recognition.emitEnd()")
    retry = page.get_by_role("button", name="重新发送", exact=True)
    retry.wait_for()
    panel = page.locator(".child-conversation-panel")
    log = panel.get_by_role("log", name="对话记录")
    preserved = page.locator("#pending-draft")
    assert panel.count() == 1
    assert preserved.count() == 1
    assert log.locator("#pending-draft").count() == 1
    assert page.locator(".child-stage > #pending-draft").count() == 0
    assert preserved.get_by_text("我给小鸭添了清水。", exact=True).count() == 1
    assert retry.count() == 1
    assert "synthetic retryable failure" not in page.locator("body").inner_text()

    stored = json.loads(page.evaluate("sessionStorage.getItem('duck-diary.child-session.v1')"))
    assert stored["draft"]["request_id"] == chat_bodies[0]["request_id"]
    retry.dblclick()
    page.wait_for_function("window.__childTest.audio.instances.length === 1")
    assert len(chat_bodies) == 2
    assert [body["request_id"] for body in chat_bodies] == [stored["draft"]["request_id"]] * 2
    assert [body["text"] for body in chat_bodies] == ["我给小鸭添了清水。"] * 2
    assert len(tts_requests) == 1

    page.evaluate("window.__childTest.audio.emitPlaying(0)")
    page.evaluate("window.__childTest.audio.emitEnded(0)")
    page.get_by_role("button", name="开始说话", exact=True).wait_for()
    assert page.get_by_role("log", name="对话记录").get_by_text(
        "我给小鸭添了清水。", exact=True
    ).count() == 1


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=["1024x576", "1280x720"])
def test_near_limit_preserved_draft_scrolls_inside_its_fixed_row_without_overlap(
    child_page,
    exact_fixture_url,
    viewport,
):
    page = child_page.page
    page.set_viewport_size(viewport)
    port = child_page.server.port
    chat_bodies = []

    child_page.fulfill_json("**/api/roster/today", [SYNTHETIC_CHILD])
    child_page.fulfill_json("**/api/children/1/active-conversation", SYNTHETIC_ACTIVE)

    def chat(route):
        assert exact_fixture_url(route.request.url, port)
        body = route.request.post_data_json
        chat_bodies.append(body)
        route.fulfill(
            status=503,
            content_type="application/json",
            body=json.dumps({
                "error": {
                    "code": "UPSTREAM_UNAVAILABLE",
                    "message": "raw near-limit draft secret",
                    "retryable": True,
                }
            }),
        )

    page.route("**/api/chat", chat)
    page.goto(f"{child_page.server.base_url}/", wait_until="domcontentloaded")
    page.get_by_role("button", name="开始", exact=True).click()
    page.get_by_role("button", name="开始说话", exact=True).click()
    page.wait_for_function("window.__childTest.recognition.starts === 1")
    page.evaluate(
        "text => window.__childTest.recognition.emitResult(0, text, true)",
        NEAR_LIMIT_CHILD_TEXT,
    )
    page.keyboard.press("Space")
    page.wait_for_function("window.__childTest.recognition.stops === 1")
    page.evaluate("window.__childTest.recognition.emitEnd()")

    retry = page.get_by_role("button", name="重新发送", exact=True)
    retry.wait_for()
    log = page.get_by_role("log", name="对话记录")
    preserved = log.locator("#pending-draft")
    draft_body = preserved.locator(".child-message__text")
    assert page.locator(".child-view").get_attribute("data-state") == "submission_failed"
    assert log.count() == 1
    assert preserved.count() == 1
    assert draft_body.text_content() == NEAR_LIMIT_CHILD_TEXT
    assert len(chat_bodies) == 1
    assert chat_bodies[0]["text"] == NEAR_LIMIT_CHILD_TEXT
    assert "raw near-limit draft secret" not in page.locator("body").inner_text()

    retry.focus()
    page.keyboard.press("Shift+Tab")
    assert draft_body.evaluate("node => document.activeElement === node") is True

    measured = page.evaluate(
        """
        () => {
          const box = element => {
            const rect = element.getBoundingClientRect();
            return {
              x: rect.x,
              y: rect.y,
              width: rect.width,
              height: rect.height,
              top: rect.top,
              right: rect.right,
              bottom: rect.bottom,
              left: rect.left,
            };
          };
          const draft = document.querySelector('#pending-draft');
          const previousRow = draft.previousElementSibling;
          const nextRow = draft.nextElementSibling;
          const body = draft.querySelector('.child-message__text');
          const speaker = draft.querySelector('.child-message__speaker');
          const previousBody = previousRow.querySelector('.child-message__text');
          const nextBody = nextRow.querySelector('.child-message__text');
          const textNode = body.firstChild;
          body.scrollTop = body.scrollHeight;
          const lastCharacter = document.createRange();
          lastCharacter.setStart(textNode, textNode.length - 1);
          lastCharacter.setEnd(textNode, textNode.length);
          const scrolling = document.scrollingElement;
          return {
            previousRow: box(previousRow),
            row: box(draft),
            nextRow: box(nextRow),
            body: box(body),
            speaker: box(speaker),
            lastCharacter: box(lastCharacter),
            bodyClientHeight: body.clientHeight,
            bodyScrollHeight: body.scrollHeight,
            bodyScrollTop: body.scrollTop,
            bodyOverflowY: getComputedStyle(body).overflowY,
            bodyText: body.textContent,
            previousClientHeight: previousBody.clientHeight,
            previousScrollHeight: previousBody.scrollHeight,
            nextClientHeight: nextBody.clientHeight,
            nextScrollHeight: nextBody.scrollHeight,
            panel: box(document.querySelector('.child-conversation-panel')),
            orb: box(document.querySelector('.child-pet-orb')),
            scrollX: window.scrollX,
            scrollY: window.scrollY,
            documentWidth: scrolling.scrollWidth,
            documentHeight: scrolling.scrollHeight,
            viewportWidth: window.innerWidth,
            viewportHeight: window.innerHeight,
          };
        }
        """
    )
    assert measured["bodyText"] == NEAR_LIMIT_CHILD_TEXT
    for name in ("previousRow", "row", "nextRow"):
        assert measured[name]["height"] == pytest.approx(116, abs=0.5)
    assert measured["previousRow"]["bottom"] <= measured["row"]["top"]
    assert measured["row"]["bottom"] <= measured["nextRow"]["top"]
    assert measured["speaker"]["top"] >= measured["row"]["top"]
    assert measured["speaker"]["bottom"] <= measured["body"]["top"]
    assert measured["body"]["top"] >= measured["row"]["top"]
    assert measured["body"]["bottom"] <= measured["row"]["bottom"]
    assert measured["bodyOverflowY"] == "auto"
    assert measured["bodyScrollHeight"] > measured["bodyClientHeight"]
    assert measured["bodyScrollTop"] == pytest.approx(
        measured["bodyScrollHeight"] - measured["bodyClientHeight"],
        abs=1,
    )
    assert measured["lastCharacter"]["top"] >= measured["body"]["top"] - 1
    assert measured["lastCharacter"]["bottom"] <= measured["body"]["bottom"] + 1
    assert measured["previousScrollHeight"] <= measured["previousClientHeight"]
    assert measured["nextScrollHeight"] <= measured["nextClientHeight"]
    assert measured["scrollX"] == 0
    assert measured["scrollY"] == 0
    assert measured["documentWidth"] <= measured["viewportWidth"]
    assert measured["documentHeight"] <= measured["viewportHeight"]

    expected = STAGE_GEOMETRY[(viewport["width"], viewport["height"])]
    for name in ("panel", "orb"):
        for field, expected_value in expected[name].items():
            assert measured[name][field] == pytest.approx(expected_value, abs=1), (
                name,
                field,
                measured[name],
            )


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=["1024x576", "1280x720"])
def test_chat_11000ms_response_uses_same_request_and_audio_path(
    child_page, exact_fixture_url, viewport
):
    page = child_page.page
    page.clock.install(time=1_700_000_000)
    page.set_viewport_size(viewport)
    port = child_page.server.port
    held = []
    chat_bodies = []
    chat_header_ids = []
    tts_requests = []

    child_page.fulfill_json("**/api/roster/today", [SYNTHETIC_CHILD])
    child_page.fulfill_json(
        "**/api/children/1/active-conversation", SYNTHETIC_ACTIVE
    )

    def chat(route):
        assert exact_fixture_url(route.request.url, port)
        chat_bodies.append(route.request.post_data_json)
        chat_header_ids.append(route.request.headers.get("x-request-id"))
        held.append(route)

    def tts(route):
        assert exact_fixture_url(route.request.url, port)
        tts_requests.append(route.request.url)
        route.fulfill(status=200, content_type="audio/mpeg", body=b"synthetic-audio")

    page.route("**/api/chat", chat)
    page.route("**/api/tts?*", tts)
    page.goto(f"{child_page.server.base_url}/", wait_until="domcontentloaded")
    page.get_by_role("button", name="开始", exact=True).click()
    page.get_by_role("button", name="开始说话", exact=True).click()
    page.wait_for_function("window.__childTest.recognition.starts === 1")
    page.evaluate(
        """() => {
          window.__p6ChatStates = [];
          window.__p6ChatState = document.querySelector('.child-view').dataset.state;
          window.__p6ChatObserver = new MutationObserver(() => {
            const state = document.querySelector('.child-view')?.dataset.state;
            if (state && state !== window.__p6ChatState) {
              window.__p6ChatStates.push(state);
              window.__p6ChatState = state;
            }
          });
          window.__p6ChatObserver.observe(document.body, {
            attributes: true,
            childList: true,
            subtree: true,
          });
        }"""
    )
    page.evaluate(
        "window.__childTest.recognition.emitResult(0, '我看见小鸭排队喝水。', true)"
    )
    page.keyboard.press("Space")
    page.wait_for_function("window.__childTest.recognition.stops === 1")
    with page.expect_request(lambda request: request.url.endswith("/api/chat")):
        page.evaluate("window.__childTest.recognition.emitEnd()")
    page.evaluate("() => Promise.resolve()")

    assert len(held) == 1
    assert len(chat_bodies) == 1
    request_id = chat_bodies[0]["request_id"]
    assert chat_header_ids == [request_id]
    assert page.locator(".child-view").get_attribute("data-state") == "submitting"

    page.clock.fast_forward(11_000)
    page.evaluate("() => Promise.resolve()")
    states_before_response = page.evaluate("window.__p6ChatStates")
    assert page.locator(".child-view").get_attribute("data-state") == "submitting"
    assert "submission_failed" not in states_before_response
    assert len(chat_bodies) == 1
    assert tts_requests == []

    held[0].fulfill(
        status=200,
        content_type="application/json",
        body=json.dumps(_chat_success_for(chat_bodies[0])),
    )
    page.wait_for_function(
        """() => document.querySelector('.child-view')?.dataset.state === 'speaking'
          && window.__childTest.audio.instances.length === 1"""
    )
    states_after_response = page.evaluate("window.__p6ChatStates")
    assert "submission_failed" not in states_after_response
    assert states_after_response[-1] == "speaking"
    assert len(chat_bodies) == 1
    assert chat_header_ids == [request_id]
    assert chat_bodies[0]["request_id"] == request_id
    assert len(tts_requests) == 1
    assert parse_qs(urlsplit(tts_requests[0]).query) == {
        "text": ["今天的小鸭很开心。"]
    }
    assert page.evaluate("window.__childTest.audio.instances[0].playCalls") == 1

    regular_message_texts = page.locator(
        ".child-conversation-panel .child-message:not(.child-message--pending):not(.child-message--failure) "
        ".child-message__text"
    ).all_inner_texts()
    assert regular_message_texts == [
        "我给小鸭准备了清水。",
        "谢谢你认真照顾小鸭。",
        "我看见小鸭排队喝水。",
        "今天的小鸭很开心。",
    ]
    assert page.locator("#pending-draft").count() == 0

    page.evaluate("window.__childTest.audio.emitPlaying(0)")
    page.evaluate("window.__childTest.audio.emitEnded(0)")
    page.get_by_role("button", name="开始说话", exact=True).wait_for()


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=["1024x576", "1280x720"])
def test_first_chat_thirty_second_timeout_retains_draft_and_reuses_request_id_once(
    child_page, exact_fixture_url, viewport, record_property
):
    page = child_page.page
    page.clock.install(time=1_700_000_000)
    page.set_viewport_size(viewport)
    port = child_page.server.port
    held = []
    chat_bodies = []
    chat_header_ids = []
    tts_requests = []
    completion_requests = []

    child_page.fulfill_json("**/api/roster/today", [SYNTHETIC_CHILD])
    child_page.fulfill_json(
        "**/api/children/1/active-conversation", SYNTHETIC_ACTIVE
    )

    def chat(route):
        assert exact_fixture_url(route.request.url, port)
        chat_bodies.append(route.request.post_data_json)
        chat_header_ids.append(route.request.headers.get("x-request-id"))
        held.append(route)

    def tts(route):
        assert exact_fixture_url(route.request.url, port)
        tts_requests.append(route.request.url)
        route.fulfill(status=200, content_type="audio/mpeg", body=b"synthetic-audio")

    def complete(route):
        assert exact_fixture_url(route.request.url, port)
        completion_requests.append(route.request.post_data_json)
        route.fulfill(status=200, content_type="application/json", body="{}")

    page.route("**/api/chat", chat)
    page.route("**/api/tts?*", tts)
    page.route("**/api/conversations/*/complete", complete)
    page.goto(f"{child_page.server.base_url}/", wait_until="domcontentloaded")
    page.get_by_role("button", name="开始", exact=True).click()
    page.get_by_role("button", name="开始说话", exact=True).click()
    page.wait_for_function("window.__childTest.recognition.starts === 1")
    page.evaluate(
        "window.__childTest.recognition.emitResult(0, '我给小鸭准备了超时证据。', true)"
    )
    page.clock.pause_at(page.evaluate("Date.now()") / 1000 + 1)
    page.keyboard.press("Space")
    page.wait_for_function("window.__childTest.recognition.stops === 1")
    with page.expect_request(lambda request: request.url.endswith("/api/chat")) as requested:
        page.evaluate("window.__childTest.recognition.emitEnd()")
    assert exact_fixture_url(requested.value.url, port)
    page.evaluate("() => Promise.resolve()")
    assert len(chat_bodies) == 1
    request_id = chat_bodies[0]["request_id"]
    assert chat_header_ids == [request_id]
    serialized_before = page.evaluate(
        "sessionStorage.getItem('duck-diary.child-session.v1')"
    )
    assert serialized_before is not None
    stored_before = json.loads(serialized_before)
    assert "我给小鸭准备了超时证据。" in serialized_before
    assert request_id in serialized_before
    page.evaluate(
        """() => {
          window.__task9TimeoutTransitions = [];
          window.__task9TimeoutLastState = document.querySelector('.child-view').dataset.state;
          window.__task9TimeoutObserver = new MutationObserver(() => {
            const state = document.querySelector('.child-view')?.dataset.state;
            if (state && state !== window.__task9TimeoutLastState) {
              window.__task9TimeoutTransitions.push(state);
              window.__task9TimeoutLastState = state;
            }
          });
          window.__task9TimeoutObserver.observe(document.body, {
            attributes: true,
            childList: true,
            subtree: true,
          });
        }"""
    )

    page.clock.fast_forward(29_999)
    page.evaluate("() => Promise.resolve()")
    state_at_29999 = page.locator(".child-view").get_attribute("data-state")
    durable_at_29999 = page.evaluate(
        "sessionStorage.getItem('duck-diary.child-session.v1')"
    )
    retry_controls_at_29999 = page.get_by_role(
        "button", name="重新发送", exact=True
    ).count()
    page_text_at_29999 = page.locator("body").inner_text()
    success_copy_at_29999 = any(
        copy in page_text_at_29999
        for copy in ("今天的小鸭很开心。", "今天的话已经安全记下来啦")
    )
    assert state_at_29999 == "submitting"
    assert durable_at_29999 == serialized_before
    assert len(held) == 1
    assert retry_controls_at_29999 == 0
    assert len(chat_bodies) == 1
    assert tts_requests == []
    assert completion_requests == []
    assert success_copy_at_29999 is False

    page.clock.fast_forward(1)
    retry = page.get_by_role("button", name="重新发送", exact=True)
    retry.wait_for()
    state_at_30000 = page.locator(".child-view").get_attribute("data-state")
    retry_controls_at_30000 = retry.count()
    timeout_transitions = page.evaluate("window.__task9TimeoutTransitions")
    failure_transitions_at_30000 = timeout_transitions.count("submission_failed")
    assert state_at_30000 == "submission_failed"
    assert retry_controls_at_30000 == 1
    assert failure_transitions_at_30000 == 1
    assert len(held) == 1
    assert len(chat_bodies) == 1
    assert tts_requests == []
    assert completion_requests == []
    serialized_after = page.evaluate(
        "sessionStorage.getItem('duck-diary.child-session.v1')"
    )
    stored_after = json.loads(serialized_after)
    assert stored_after["draft"] == stored_before["draft"]
    assert stored_after["draft"]["request_id"] == request_id
    assert stored_after["draft"]["text"] == "我给小鸭准备了超时证据。"
    page_text = page.locator("body").inner_text()
    assert "今天的小鸭很开心。" not in page_text
    assert "今天的话已经安全记下来啦" not in page_text
    assert tts_requests == []
    assert completion_requests == []
    page.clock.fast_forward(30_000)
    page.evaluate("() => Promise.resolve()")
    timeout_transitions = page.evaluate("window.__task9TimeoutTransitions")
    assert timeout_transitions.count("submission_failed") == 1
    assert retry.count() == 1
    assert len(chat_bodies) == 1
    assert len(held) == 1
    assert tts_requests == []
    assert completion_requests == []

    _keyboard_focus(page, retry)
    assert retry.evaluate("node => document.activeElement === node")
    with page.expect_request(lambda request: request.url.endswith("/api/chat")) as retried:
        page.keyboard.press("Enter")
        page.keyboard.press("Space")
        page.keyboard.press("Enter")
    assert exact_fixture_url(retried.value.url, port)
    page.evaluate("() => Promise.resolve()")
    assert len(chat_bodies) == 2
    assert chat_bodies[1] == chat_bodies[0]
    assert [body["request_id"] for body in chat_bodies] == [request_id, request_id]
    assert [body["text"] for body in chat_bodies] == ["我给小鸭准备了超时证据。"] * 2
    assert chat_header_ids == [request_id, request_id]
    assert len(held) == 2
    assert tts_requests == []
    assert completion_requests == []
    record_property(
        "task9.timeout_evidence",
        json.dumps(
            {
                "activation_sequence": ["Enter", "Space", "Enter"],
                "body_reused_exactly": chat_bodies[1] == chat_bodies[0],
                "chat_attempts": len(chat_bodies),
                "completion_requests_at_29999": 0,
                "completion_requests_during_failure_boundary": len(completion_requests),
                "durable_bytes_unchanged_at_29999": durable_at_29999
                == serialized_before,
                "failure_transitions_at_30000": failure_transitions_at_30000,
                "header_matches_body_request_id": chat_header_ids
                == [request_id, request_id],
                "outstanding_chat_requests_at_29999": 1,
                "request_id_sha256": hashlib.sha256(
                    request_id.encode("utf-8")
                ).hexdigest(),
                "retry_controls_at_30000": retry_controls_at_30000,
                "retry_controls_at_29999": retry_controls_at_29999,
                "retry_requests": len(chat_bodies) - 1,
                "state_at_30000": state_at_30000,
                "state_at_29999": state_at_29999,
                "success_copy_at_29999": success_copy_at_29999,
                "timeout_ms": 30_000,
                "tts_requests_at_29999": 0,
                "tts_requests_during_failure_boundary": len(tts_requests),
                "viewport": viewport,
                "viewport_id": f'{viewport["width"]}x{viewport["height"]}',
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ),
    )
    for pending_route in held:
        pending_route.abort("failed")
    page.evaluate("() => Promise.resolve()")


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=["1024x576", "1280x720"])
def test_completion_delay_is_single_flight_and_saves_once(
    child_page, exact_fixture_url, viewport
):
    page = child_page.page
    page.set_viewport_size(viewport)
    port = child_page.server.port
    complete_requests = []
    held_completions = []

    child_page.fulfill_json("**/api/roster/today", [SYNTHETIC_CHILD])
    child_page.fulfill_json(
        "**/api/children/1/active-conversation", SYNTHETIC_ACTIVE
    )

    def chat(route):
        assert exact_fixture_url(route.request.url, port)
        body = route.request.post_data_json
        payload = _chat_success_for(body)
        payload.update({"ended": True, "end_reason": "complete"})
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(payload),
        )

    def tts(route):
        assert exact_fixture_url(route.request.url, port)
        route.fulfill(status=200, content_type="audio/mpeg", body=b"synthetic-audio")

    def complete(route):
        assert exact_fixture_url(route.request.url, port)
        complete_requests.append(route.request.post_data_json)
        held_completions.append(route)

    page.route("**/api/chat", chat)
    page.route("**/api/tts?*", tts)
    page.route("**/api/conversations/17/complete", complete)
    page.goto(f"{child_page.server.base_url}/", wait_until="domcontentloaded")
    page.get_by_role("button", name="开始", exact=True).click()
    page.get_by_role("button", name="开始说话", exact=True).click()
    page.wait_for_function("window.__childTest.recognition.starts === 1")
    page.evaluate(
        "window.__childTest.recognition.emitResult(0, '我给小鸭讲了一个故事。', true)"
    )
    page.keyboard.press("Space")
    page.wait_for_function("window.__childTest.recognition.stops === 1")
    page.evaluate("window.__childTest.recognition.emitEnd()")
    page.wait_for_function("window.__childTest.audio.instances.length === 1")
    page.evaluate("window.__childTest.audio.emitPlaying(0)")
    with page.expect_request(
        lambda request: request.url.endswith("/api/conversations/17/complete")
    ) as requested:
        page.evaluate("window.__childTest.audio.emitEnded(0)")
    assert exact_fixture_url(requested.value.url, port)
    page.evaluate("() => Promise.resolve()")

    assert complete_requests == [{"expected_last_message_id": 104}]
    assert len(held_completions) == 1
    assert page.locator(".child-view").get_attribute("data-state") == "saving_conversation"
    stored = json.loads(
        page.evaluate("sessionStorage.getItem('duck-diary.child-session.v1')")
    )
    assert stored["state"] == "saving_conversation"
    assert stored["last_message_id"] == 104

    page.keyboard.press("Enter")
    page.keyboard.press("Space")
    page.locator(".child-view").click()
    page.keyboard.press("Enter")
    page.keyboard.press("Space")
    page.evaluate("() => Promise.resolve()")
    assert complete_requests == [{"expected_last_message_id": 104}]
    assert len(held_completions) == 1

    acknowledgement = {
        "conversation_id": 17,
        "conversation_saved": True,
        "status": "completed",
        "completed_at": "2026-08-23T00:01:00.000Z",
        "message_count": 4,
        "last_message_id": 104,
        "analysis_job_id": 3,
        "analysis_status": "pending",
        "replayed": False,
    }
    held_completions[0].fulfill(
        status=200,
        content_type="application/json",
        body=json.dumps(acknowledgement),
    )
    completed = page.get_by_role("button", name="换下一位小朋友", exact=True)
    completed.wait_for()

    assert complete_requests == [{"expected_last_message_id": 104}]
    assert acknowledgement["analysis_job_id"] == 3
    assert acknowledgement["analysis_status"] == "pending"
    assert completed.count() == 1
    assert page.locator(".child-view").get_attribute("data-state") == "completed"
    assert page.get_by_role("status").inner_text() == "今天的话已经安全记下来啦"


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=["1024x576", "1280x720"])
def test_child_core_flow_is_page_keyboard_only_and_saves_once(
    child_page, exact_fixture_url, viewport
):
    page = child_page.page
    page.clock.install(time=1_700_000_000)
    page.set_viewport_size(viewport)
    port = child_page.server.port
    chat_requests = []
    tts_requests = []
    complete_requests = []
    user_actions = []
    second_child = {
        "id": 2,
        "name": "键盘候选幼儿",
        "nickname": "小键",
        "avatar": None,
    }

    child_page.fulfill_json(
        "**/api/roster/today", [SYNTHETIC_CHILD, second_child]
    )
    child_page.fulfill_json(
        "**/api/children/1/active-conversation", {"conversation": None}
    )
    child_page.fulfill_json(
        "**/api/children/2/active-conversation", {"conversation": None}
    )

    def chat(route):
        assert exact_fixture_url(route.request.url, port)
        body = route.request.post_data_json
        chat_requests.append(body)
        round_index = len(chat_requests)
        assert round_index in {1, 2, 3}
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "request_id": body["request_id"],
                "conversation_id": 17,
                "child_message_id": (round_index * 2) - 1,
                "diary_message_id": round_index * 2,
                "reply": f"第{round_index}轮日记回复。",
                "round": round_index,
                "ended": round_index == 3,
                "end_reason": "max_rounds" if round_index == 3 else None,
                "replayed": False,
            }),
        )

    def tts(route):
        assert exact_fixture_url(route.request.url, port)
        tts_requests.append(route.request.url)
        route.fulfill(status=200, content_type="audio/mpeg", body=b"synthetic-audio")

    def complete(route):
        assert exact_fixture_url(route.request.url, port)
        body = route.request.post_data_json
        complete_requests.append(body)
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "conversation_id": 17,
                "conversation_saved": True,
                "status": "completed",
                "completed_at": "2026-08-23T00:01:00.000Z",
                "message_count": 6,
                "last_message_id": body["expected_last_message_id"],
                "analysis_job_id": 3,
                "analysis_status": "pending",
                "replayed": False,
            }),
        )

    def press(stage, key):
        user_actions.append((stage, "page.keyboard", key))
        page.keyboard.press(key)

    page.route("**/api/chat", chat)
    page.route("**/api/tts?*", tts)
    page.route("**/api/conversations/17/complete", complete)
    page.goto(f"{child_page.server.base_url}/", wait_until="domcontentloaded")

    assert page.locator(".child-view").get_attribute("data-state") == "welcome"
    page.wait_for_function("document.activeElement?.id === 'start-button'")
    press("welcome", "Enter")
    page.wait_for_function(
        "document.querySelector('.child-view')?.dataset.state === 'selecting_child'"
    )
    assert page.locator(".child-view").get_attribute("data-state") == "selecting_child"
    press("child-selection-focus", "Tab")
    page.wait_for_function("document.activeElement?.id === 'child-card-1'")
    press("child-selection", "Enter")
    page.wait_for_function("window.__childTest.audio.instances.length === 1")
    page.evaluate("window.__childTest.audio.emitPlaying(0)")
    page.evaluate("window.__childTest.audio.emitEnded(0)")
    page.wait_for_function("document.activeElement?.id === 'record-button'")
    assert page.locator(".child-view").get_attribute("data-state") == "ready"

    page.clock.pause_at(page.evaluate("Date.now()") / 1000 + 1)
    for round_index, child_text in enumerate(
        [
            "第一轮我给小鸭添了水。",
            "第二轮我给小鸭讲了故事。",
            "第三轮我和搭档一起照顾小鸭。",
        ]
    ):
        press(f"round-{round_index + 1}-record", "Space")
        page.wait_for_function(
            f"window.__childTest.recognition.starts === {round_index + 1}"
        )
        page.evaluate(
            "([index, text]) => window.__childTest.recognition.emitResult(index, text, true)",
            [round_index, child_text],
        )
        page.clock.fast_forward(1_499)
        assert page.evaluate("window.__childTest.recognition.stops") == round_index
        page.clock.fast_forward(1)
        assert page.evaluate("window.__childTest.recognition.stops") == round_index
        press(f"round-{round_index + 1}-finish", "Space")
        assert page.evaluate("window.__childTest.recognition.stops") == round_index + 1
        page.evaluate("window.__childTest.recognition.emitEnd()")
        audio_index = round_index + 1
        page.wait_for_function(
            f"window.__childTest.audio.instances.length === {audio_index + 1}"
        )
        page.evaluate(
            "index => window.__childTest.audio.emitPlaying(index)", audio_index
        )
        page.evaluate(
            "index => window.__childTest.audio.emitEnded(index)", audio_index
        )
        if round_index < 2:
            page.wait_for_function("document.activeElement?.id === 'record-button'")

    completed = page.get_by_role("button", name="换下一位小朋友", exact=True)
    completed.wait_for()
    page.wait_for_function("document.activeElement?.id === 'reset-button'")

    assert [body["text"] for body in chat_requests] == [
        "第一轮我给小鸭添了水。",
        "第二轮我给小鸭讲了故事。",
        "第三轮我和搭档一起照顾小鸭。",
    ]
    assert len({body["request_id"] for body in chat_requests}) == 3
    assert len(tts_requests) == 4
    assert complete_requests == [{"expected_last_message_id": 6}]
    assert page.locator(".child-view").get_attribute("data-state") == "completed"
    assert page.get_by_role("status").inner_text() == "今天的话已经安全记下来啦"
    log = page.get_by_role("log", name="对话记录")
    for text in [
        "第一轮我给小鸭添了水。",
        "第1轮日记回复。",
        "第二轮我给小鸭讲了故事。",
        "第2轮日记回复。",
        "第三轮我和搭档一起照顾小鸭。",
        "第3轮日记回复。",
    ]:
        assert log.get_by_text(text, exact=True).count() == 1

    press("completed-exit", "Enter")
    page.get_by_role("button", name="开始", exact=True).wait_for()
    assert page.locator(".child-view").get_attribute("data-state") == "welcome"
    assert complete_requests == [{"expected_last_message_id": 6}]
    assert user_actions == [
        ("welcome", "page.keyboard", "Enter"),
        ("child-selection-focus", "page.keyboard", "Tab"),
        ("child-selection", "page.keyboard", "Enter"),
        ("round-1-record", "page.keyboard", "Space"),
        ("round-1-finish", "page.keyboard", "Space"),
        ("round-2-record", "page.keyboard", "Space"),
        ("round-2-finish", "page.keyboard", "Space"),
        ("round-3-record", "page.keyboard", "Space"),
        ("round-3-finish", "page.keyboard", "Space"),
        ("completed-exit", "page.keyboard", "Enter"),
    ]


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=["1024x576", "1280x720"])
@pytest.mark.parametrize(
    "fault",
    ["http_500", "non_json", "offline"],
    ids=["http_500", "non_json", "offline"],
)
def test_chat_fault_matrix_retains_draft_without_success_copy(
    child_page, exact_fixture_url, viewport, fault
):
    page = child_page.page
    page.set_viewport_size(viewport)
    chat_requests = []
    tts_requests = []
    complete_requests = []
    port = child_page.server.port

    child_page.fulfill_json("**/api/roster/today", [SYNTHETIC_CHILD])
    child_page.fulfill_json("**/api/children/1/active-conversation", SYNTHETIC_ACTIVE)

    def chat(route):
        assert exact_fixture_url(route.request.url, port)
        chat_requests.append(route.request.post_data_json)
        if fault == "http_500":
            route.fulfill(
                status=500,
                content_type="application/json",
                body=json.dumps({
                    "error": {
                        "code": "UPSTREAM_UNAVAILABLE",
                        "message": "synthetic retryable failure",
                        "retryable": True,
                    }
                }),
            )
            return
        if fault == "offline":
            route.abort("internetdisconnected")
            return
        route.fulfill(status=502, content_type="text/plain", body="not-json-synthetic")

    def tts(route):
        assert exact_fixture_url(route.request.url, port)
        tts_requests.append(route.request.url)
        route.fulfill(status=503, content_type="application/json", body="{}")

    def complete(route):
        assert exact_fixture_url(route.request.url, port)
        complete_requests.append(route.request.post_data_json)
        route.fulfill(status=503, content_type="application/json", body="{}")

    page.route("**/api/chat", chat)
    page.route("**/api/tts?*", tts)
    page.route("**/api/conversations/17/complete", complete)
    page.goto(f"{child_page.server.base_url}/", wait_until="domcontentloaded")
    page.get_by_role("button", name="开始", exact=True).click()
    page.get_by_role("button", name="开始说话", exact=True).click()
    page.wait_for_function("window.__childTest.recognition.starts === 1")
    page.evaluate("window.__childTest.recognition.emitResult(0, '我给小鸭盖好了小房子。', true)")
    page.keyboard.press("Space")
    page.wait_for_function("window.__childTest.recognition.stops === 1")
    page.evaluate("window.__childTest.recognition.emitEnd()")

    page.get_by_role("button", name="重新发送", exact=True).wait_for()
    serialized = page.evaluate("sessionStorage.getItem('duck-diary.child-session.v1')")
    assert serialized is not None
    assert "我给小鸭盖好了小房子。" in serialized
    body = page.locator("body").inner_text()
    assert "这句话已经安全收到。" not in body
    assert "今天的话已经安全记下来啦" not in body
    assert len(chat_requests) == 1
    assert tts_requests == []
    assert complete_requests == []


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=["1024x576", "1280x720"])
def test_chat_replay_deduplicates_acknowledged_message_ids(
    child_page, exact_fixture_url, viewport
):
    page = child_page.page
    page.set_viewport_size(viewport)
    child_text = "我给小鸭换了干净的水。"
    diary_text = "谢谢你细心照顾小鸭。"
    active = {
        "conversation": {
            "id": 17,
            "child_id": 1,
            "status": "active",
            "revision": 3,
            "round": 2,
            "last_message_id": 104,
            "messages": [
                *SYNTHETIC_ACTIVE["conversation"]["messages"],
                {"id": 103, "role": "child", "text": child_text},
                {"id": 104, "role": "diary", "text": diary_text},
            ],
        }
    }
    chat_bodies = []
    tts_requests = []
    port = child_page.server.port

    child_page.fulfill_json("**/api/roster/today", [SYNTHETIC_CHILD])
    child_page.fulfill_json("**/api/children/1/active-conversation", active)

    def chat(route):
        assert exact_fixture_url(route.request.url, port)
        body = route.request.post_data_json
        chat_bodies.append(body)
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "request_id": body["request_id"],
                "conversation_id": 17,
                "child_message_id": 103,
                "diary_message_id": 104,
                "reply": diary_text,
                "round": 2,
                "ended": False,
                "end_reason": None,
                "replayed": True,
            }),
        )

    def tts(route):
        assert exact_fixture_url(route.request.url, port)
        tts_requests.append(route.request.url)
        route.fulfill(status=200, content_type="audio/mpeg", body=b"synthetic-audio")

    page.route("**/api/chat", chat)
    page.route("**/api/tts?*", tts)
    page.goto(f"{child_page.server.base_url}/", wait_until="domcontentloaded")
    page.get_by_role("button", name="开始", exact=True).click()
    page.get_by_role("button", name="开始说话", exact=True).click()
    page.wait_for_function("window.__childTest.recognition.starts === 1")
    page.evaluate(f"window.__childTest.recognition.emitResult(0, {json.dumps(child_text)}, true)")
    page.keyboard.press("Space")
    page.wait_for_function("window.__childTest.recognition.stops === 1")
    page.evaluate("window.__childTest.recognition.emitEnd()")
    page.wait_for_function("window.__childTest.audio.instances.length === 1")
    page.evaluate("window.__childTest.audio.emitPlaying(0)")
    page.evaluate("window.__childTest.audio.emitEnded(0)")
    page.get_by_role("button", name="开始说话", exact=True).wait_for()

    log = page.get_by_role("log", name="对话记录")
    assert log.get_by_text(child_text, exact=True).count() == 1
    assert log.get_by_text(diary_text, exact=True).count() == 1
    assert len(chat_bodies) == 1
    assert chat_bodies[0]["text"] == child_text
    assert len(tts_requests) == 1


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=["1024x576", "1280x720"])
def test_chat_conflicting_replay_enters_sanitized_recovery(
    child_page, exact_fixture_url, viewport
):
    page = child_page.page
    page.set_viewport_size(viewport)
    raw_route_secret = "raw-conflicting-route-secret"
    chat_requests = []
    tts_requests = []
    complete_requests = []
    port = child_page.server.port

    child_page.fulfill_json("**/api/roster/today", [SYNTHETIC_CHILD])
    child_page.fulfill_json("**/api/children/1/active-conversation", SYNTHETIC_ACTIVE)

    def chat(route):
        assert exact_fixture_url(route.request.url, port)
        body = route.request.post_data_json
        chat_requests.append(body)
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "request_id": body["request_id"],
                "conversation_id": 17,
                "child_message_id": 101,
                "diary_message_id": 104,
                "reply": raw_route_secret,
                "round": 2,
                "ended": False,
                "end_reason": None,
                "replayed": True,
            }),
        )

    def tts(route):
        assert exact_fixture_url(route.request.url, port)
        tts_requests.append(route.request.url)
        route.fulfill(status=503, content_type="application/json", body="{}")

    def complete(route):
        assert exact_fixture_url(route.request.url, port)
        complete_requests.append(route.request.post_data_json)
        route.fulfill(status=503, content_type="application/json", body="{}")

    page.route("**/api/chat", chat)
    page.route("**/api/tts?*", tts)
    page.route("**/api/conversations/17/complete", complete)
    page.goto(f"{child_page.server.base_url}/", wait_until="domcontentloaded")
    page.get_by_role("button", name="开始", exact=True).click()
    page.get_by_role("button", name="开始说话", exact=True).click()
    page.wait_for_function("window.__childTest.recognition.starts === 1")
    page.evaluate("window.__childTest.recognition.emitResult(0, '我给小鸭换了水。', true)")
    page.keyboard.press("Space")
    page.wait_for_function("window.__childTest.recognition.stops === 1")
    page.evaluate("window.__childTest.recognition.emitEnd()")

    page.get_by_role("alert").wait_for()
    assert page.locator(".child-view").get_attribute("data-state") == "recovery"
    assert page.get_by_text("这次对话需要老师检查后再继续", exact=True).count() == 1
    assert page.get_by_role("log", name="对话记录").get_by_text(
        "我给小鸭准备了清水。", exact=True
    ).count() == 1
    serialized = page.evaluate("sessionStorage.getItem('duck-diary.child-session.v1')")
    assert raw_route_secret not in page.locator("body").inner_text()
    assert serialized is not None and raw_route_secret not in serialized
    assert len(chat_requests) == 1
    assert tts_requests == []
    assert complete_requests == []


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=["1024x576", "1280x720"])
@pytest.mark.parametrize(
    "fault",
    [
        "edge_http_500",
        "edge_non_json",
        "edge_offline",
        "play_rejected",
        "audio_error",
        "browser_speech_error",
    ],
    ids=[
        "edge_http_500",
        "edge_non_json",
        "edge_offline",
        "play_rejected",
        "audio_error",
        "browser_speech_error",
    ],
)
def test_tts_faults_settle_and_do_not_block_completion(
    child_page, exact_fixture_url, viewport, fault
):
    page = child_page.page
    page.set_viewport_size(viewport)
    chat_requests = []
    tts_requests = []
    complete_requests = []
    port = child_page.server.port

    child_page.fulfill_json("**/api/roster/today", [SYNTHETIC_CHILD])
    child_page.fulfill_json("**/api/children/1/active-conversation", SYNTHETIC_ACTIVE)

    def chat(route):
        assert exact_fixture_url(route.request.url, port)
        body = route.request.post_data_json
        chat_requests.append(body)
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "request_id": body["request_id"],
                "conversation_id": 17,
                "child_message_id": 103,
                "diary_message_id": 104,
                "reply": "今天的小鸭很开心。",
                "round": 2,
                "ended": True,
                "end_reason": "complete",
                "replayed": False,
            }),
        )

    def tts(route):
        assert exact_fixture_url(route.request.url, port)
        tts_requests.append(route.request.url)
        if fault == "edge_non_json":
            route.fulfill(status=200, content_type="application/json", body="{}")
            return
        if fault == "edge_offline":
            route.abort("internetdisconnected")
            return
        if fault in {"play_rejected", "audio_error"}:
            route.fulfill(status=200, content_type="audio/mpeg", body=b"synthetic-audio")
            return
        route.fulfill(
            status=500,
            content_type="application/json",
            body=json.dumps({
                "error": {
                    "code": "UPSTREAM_UNAVAILABLE",
                    "message": "synthetic edge failure",
                    "retryable": True,
                }
            }),
        )

    def complete(route):
        assert exact_fixture_url(route.request.url, port)
        body = route.request.post_data_json
        complete_requests.append(body)
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "conversation_id": 17,
                "conversation_saved": True,
                "status": "completed",
                "completed_at": "2026-08-23T00:01:00Z",
                "message_count": 4,
                "last_message_id": body["expected_last_message_id"],
                "analysis_job_id": 3,
                "analysis_status": "pending",
                "replayed": False,
            }),
        )

    page.route("**/api/chat", chat)
    page.route("**/api/tts?*", tts)
    page.route("**/api/conversations/17/complete", complete)
    page.goto(f"{child_page.server.base_url}/", wait_until="domcontentloaded")
    page.get_by_role("button", name="开始", exact=True).click()
    page.get_by_role("button", name="开始说话", exact=True).click()
    page.wait_for_function("window.__childTest.recognition.starts === 1")
    page.evaluate("window.__childTest.recognition.emitResult(0, '我给小鸭讲了一个故事。', true)")
    if fault == "play_rejected":
        page.evaluate("window.__childTest.audio.rejectNextPlayOnce()")
    page.keyboard.press("Space")
    page.wait_for_function("window.__childTest.recognition.stops === 1")
    page.evaluate("window.__childTest.recognition.emitEnd()")
    if fault == "audio_error":
        page.wait_for_function("window.__childTest.audio.instances.length === 1")
        page.evaluate("window.__childTest.audio.emitError(0)")
    page.wait_for_function("window.__childTest.tts.utterances.length === 1")

    stored = json.loads(page.evaluate("sessionStorage.getItem('duck-diary.child-session.v1')"))
    assert stored["state"] == "speaking"
    assert stored["draft"] is None
    assert stored["last_message_id"] == 104
    assert len(chat_requests) == 1
    assert len(tts_requests) == 1
    assert complete_requests == []

    if fault == "browser_speech_error":
        page.evaluate("window.__childTest.tts.emitError(0)")
    else:
        page.evaluate("window.__childTest.tts.emitEnd(0)")
    page.get_by_role("button", name="换下一位小朋友", exact=True).wait_for()
    assert complete_requests == [{"expected_last_message_id": 104}]
    assert page.get_by_role("status").inner_text() == "今天的话已经安全记下来啦"


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=["1024x576", "1280x720"])
def test_tts_11000ms_cold_start_uses_same_request_audio_path(
    child_page, exact_fixture_url, viewport
):
    page = child_page.page
    page.clock.install(time=1_700_000_000)
    page.set_viewport_size(viewport)
    tts_requests = []
    held_tts_routes = []
    port = child_page.server.port

    child_page.fulfill_json("**/api/roster/today", [SYNTHETIC_CHILD])
    child_page.fulfill_json(
        "**/api/children/1/active-conversation", {"conversation": None}
    )

    def hold_tts(route):
        assert exact_fixture_url(route.request.url, port)
        tts_requests.append(route.request.url)
        held_tts_routes.append(route)

    page.route("**/api/tts?*", hold_tts)
    page.goto(f"{child_page.server.base_url}/", wait_until="domcontentloaded")
    page.get_by_role("button", name="开始", exact=True).click()
    child = page.get_by_role("button", name="小芽", exact=True)
    child.wait_for()
    page.clock.pause_at(page.evaluate("Date.now()") / 1000 + 1)
    with page.expect_request(lambda request: "/api/tts?" in request.url) as requested:
        child.click()
    assert exact_fixture_url(requested.value.url, port)
    assert parse_qs(urlsplit(requested.value.url).query) == {
        "text": ["你好呀，小芽！我是鸭鸭日记本，今天想听你讲讲照顾小鸭的事～"]
    }
    page.evaluate("() => Promise.resolve()")
    assert len(tts_requests) == 1
    assert len(held_tts_routes) == 1

    page.clock.fast_forward(11_000)
    assert page.evaluate("window.__childTest.audio.instances.length") == 0
    assert page.evaluate("window.__childTest.tts.utterances.length") == 0
    held_tts_routes[0].fulfill(
        status=200,
        content_type="audio/mpeg",
        body=b"synthetic-cold-start-audio",
    )
    page.wait_for_function("window.__childTest.audio.instances.length === 1")
    assert page.evaluate("window.__childTest.audio.instances[0].playCalls") == 1
    assert page.evaluate("window.__childTest.tts.utterances.length") == 0

    page.evaluate("window.__childTest.audio.emitPlaying(0)")
    page.evaluate("window.__childTest.audio.emitEnded(0)")
    page.get_by_role("button", name="开始说话", exact=True).wait_for()
    assert len(tts_requests) == 1
    assert page.evaluate("window.__childTest.audio.instances.length") == 1
    assert page.evaluate("window.__childTest.tts.utterances.length") == 0


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=["1024x576", "1280x720"])
def test_tts_cold_start_uses_reachable_fifteen_second_fallback(
    child_page, exact_fixture_url, viewport
):
    page = child_page.page
    page.clock.install(time=1_700_000_000)
    page.set_viewport_size(viewport)
    chat_requests = []
    held_tts_routes = []
    port = child_page.server.port

    child_page.fulfill_json("**/api/roster/today", [SYNTHETIC_CHILD])
    child_page.fulfill_json("**/api/children/1/active-conversation", SYNTHETIC_ACTIVE)

    def chat(route):
        assert exact_fixture_url(route.request.url, port)
        body = route.request.post_data_json
        chat_requests.append(body)
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "request_id": body["request_id"],
                "conversation_id": 17,
                "child_message_id": 103,
                "diary_message_id": 104,
                "reply": "今天的小鸭很开心。",
                "round": 2,
                "ended": False,
                "end_reason": None,
                "replayed": False,
            }),
        )

    def hold_tts(route):
        assert exact_fixture_url(route.request.url, port)
        held_tts_routes.append(route)

    page.route("**/api/chat", chat)
    page.route("**/api/tts?*", hold_tts)
    page.goto(f"{child_page.server.base_url}/", wait_until="domcontentloaded")
    page.get_by_role("button", name="开始", exact=True).click()
    record = page.get_by_role("button", name="开始说话", exact=True)
    record.wait_for()
    page.clock.pause_at(page.evaluate("Date.now()") / 1000 + 1)
    record.click()
    page.wait_for_function("window.__childTest.recognition.starts === 1")
    page.evaluate("window.__childTest.recognition.emitResult(0, '我给小鸭讲了一个故事。', true)")
    page.keyboard.press("Space")
    page.wait_for_function("window.__childTest.recognition.stops === 1")
    with page.expect_request(lambda request: "/api/tts?" in request.url) as requested:
        page.evaluate("window.__childTest.recognition.emitEnd()")
    assert exact_fixture_url(requested.value.url, port)
    assert len(chat_requests) == 1

    stored = json.loads(page.evaluate("sessionStorage.getItem('duck-diary.child-session.v1')"))
    assert stored["state"] == "speaking"
    page.clock.fast_forward(14_999)
    assert page.evaluate("window.__childTest.tts.utterances.length") == 0
    assert page.evaluate("window.__childTest.audio.instances.length") == 0
    with page.expect_event(
        "requestfailed", lambda request: "/api/tts?" in request.url
    ) as aborted:
        page.clock.fast_forward(1)
    page.clock.fast_forward(1)
    assert exact_fixture_url(aborted.value.url, port)
    assert len(held_tts_routes) == 1
    page.wait_for_function("window.__childTest.tts.utterances.length === 1")
    assert page.evaluate("window.__childTest.audio.instances.length") == 0
    page.evaluate("window.__childTest.tts.emitEnd(0)")
    page.get_by_role("button", name="开始说话", exact=True).wait_for()


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=["1024x576", "1280x720"])
@pytest.mark.parametrize(
    "fault",
    ["http_500", "non_json", "offline", "boundary_mismatch"],
    ids=["http_500", "non_json", "offline", "boundary_mismatch"],
)
def test_completion_fault_matrix_never_claims_saved_copy(
    child_page, exact_fixture_url, viewport, fault
):
    page = child_page.page
    page.set_viewport_size(viewport)
    complete_requests = []
    port = child_page.server.port

    child_page.fulfill_json("**/api/roster/today", [SYNTHETIC_CHILD])
    child_page.fulfill_json("**/api/children/1/active-conversation", SYNTHETIC_ACTIVE)

    def chat(route):
        assert exact_fixture_url(route.request.url, port)
        body = route.request.post_data_json
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "request_id": body["request_id"],
                "conversation_id": 17,
                "child_message_id": 103,
                "diary_message_id": 104,
                "reply": "今天的小鸭很开心。",
                "round": 2,
                "ended": True,
                "end_reason": "complete",
                "replayed": False,
            }),
        )

    def tts(route):
        assert exact_fixture_url(route.request.url, port)
        route.fulfill(status=200, content_type="audio/mpeg", body=b"synthetic-audio")

    def complete(route):
        assert exact_fixture_url(route.request.url, port)
        complete_requests.append(route.request.post_data_json)
        if fault == "non_json":
            route.fulfill(status=502, content_type="text/plain", body="not-json-synthetic")
            return
        if fault == "offline":
            route.abort("internetdisconnected")
            return
        if fault == "boundary_mismatch":
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "conversation_id": 17,
                    "conversation_saved": True,
                    "status": "completed",
                    "completed_at": "2026-08-23T00:01:00Z",
                    "message_count": 3,
                    "last_message_id": 104,
                    "analysis_job_id": 3,
                    "analysis_status": "pending",
                    "replayed": False,
                }),
            )
            return
        route.fulfill(
            status=500,
            content_type="application/json",
            body=json.dumps({
                "error": {
                    "code": "UPSTREAM_UNAVAILABLE",
                    "message": "raw-completion-route-secret",
                    "retryable": True,
                }
            }),
        )

    page.route("**/api/chat", chat)
    page.route("**/api/tts?*", tts)
    page.route("**/api/conversations/17/complete", complete)
    page.goto(f"{child_page.server.base_url}/", wait_until="domcontentloaded")
    page.get_by_role("button", name="开始", exact=True).click()
    page.get_by_role("button", name="开始说话", exact=True).click()
    page.wait_for_function("window.__childTest.recognition.starts === 1")
    page.evaluate("window.__childTest.recognition.emitResult(0, '我给小鸭讲了一个故事。', true)")
    page.keyboard.press("Space")
    page.wait_for_function("window.__childTest.recognition.stops === 1")
    page.evaluate("window.__childTest.recognition.emitEnd()")
    page.wait_for_function("window.__childTest.audio.instances.length === 1")
    page.evaluate("window.__childTest.audio.emitPlaying(0)")
    page.evaluate("window.__childTest.audio.emitEnded(0)")

    page.get_by_role("alert").wait_for()
    assert page.locator(".child-view").get_attribute("data-state") == "recovery"
    assert complete_requests == [{"expected_last_message_id": 104}]
    body = page.locator("body").inner_text()
    serialized = page.evaluate("sessionStorage.getItem('duck-diary.child-session.v1')")
    assert "今天的话已经安全记下来啦" not in body
    assert "raw-completion-route-secret" not in body
    assert serialized is not None and "raw-completion-route-secret" not in serialized
    if fault == "boundary_mismatch":
        assert json.loads(serialized)["failure"]["code"] == "COMPLETE_RESPONSE_INVALID"
    assert page.get_by_role("log", name="对话记录").get_by_text(
        "我给小鸭讲了一个故事。", exact=True
    ).count() == 1


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=["1024x576", "1280x720"])
def test_completion_replay_reaches_completed_once_after_strict_save(
    child_page, exact_fixture_url, viewport
):
    page = child_page.page
    page.set_viewport_size(viewport)
    complete_requests = []
    port = child_page.server.port

    child_page.fulfill_json("**/api/roster/today", [SYNTHETIC_CHILD])
    child_page.fulfill_json("**/api/children/1/active-conversation", SYNTHETIC_ACTIVE)

    def chat(route):
        assert exact_fixture_url(route.request.url, port)
        body = route.request.post_data_json
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "request_id": body["request_id"],
                "conversation_id": 17,
                "child_message_id": 103,
                "diary_message_id": 104,
                "reply": "今天的小鸭很开心。",
                "round": 2,
                "ended": True,
                "end_reason": "complete",
                "replayed": False,
            }),
        )

    def tts(route):
        assert exact_fixture_url(route.request.url, port)
        route.fulfill(status=200, content_type="audio/mpeg", body=b"synthetic-audio")

    def complete(route):
        assert exact_fixture_url(route.request.url, port)
        complete_requests.append(route.request.post_data_json)
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "conversation_id": 17,
                "conversation_saved": True,
                "status": "completed",
                "completed_at": "2026-08-23T00:01:00.000Z",
                "message_count": 4,
                "last_message_id": 104,
                "analysis_job_id": 3,
                "analysis_status": "pending",
                "replayed": True,
            }),
        )

    page.route("**/api/chat", chat)
    page.route("**/api/tts?*", tts)
    page.route("**/api/conversations/17/complete", complete)
    page.goto(f"{child_page.server.base_url}/", wait_until="domcontentloaded")
    page.get_by_role("button", name="开始", exact=True).click()
    page.get_by_role("button", name="开始说话", exact=True).click()
    page.wait_for_function("window.__childTest.recognition.starts === 1")
    page.evaluate("window.__childTest.recognition.emitResult(0, '我给小鸭讲了一个故事。', true)")
    page.keyboard.press("Space")
    page.wait_for_function("window.__childTest.recognition.stops === 1")
    page.evaluate("window.__childTest.recognition.emitEnd()")
    page.wait_for_function("window.__childTest.audio.instances.length === 1")
    page.evaluate("window.__childTest.audio.emitPlaying(0)")
    page.evaluate("window.__childTest.audio.emitEnded(0)")

    page.get_by_role("button", name="换下一位小朋友", exact=True).wait_for()
    assert complete_requests == [{"expected_last_message_id": 104}]
    assert page.locator(".child-view").get_attribute("data-state") == "completed"
    assert "今天的话已经安全记下来啦" in page.locator("body").inner_text()
    stored = json.loads(page.evaluate("sessionStorage.getItem('duck-diary.child-session.v1')"))
    assert stored["state"] == "completed"
    assert stored["last_message_id"] == 104
    assert len(stored["messages"]) == 4


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=["1024x576", "1280x720"])
def test_reload_during_submit_restores_same_draft_and_ignores_old_response(
    child_page, exact_fixture_url, viewport
):
    page, held = _start_held_chat(child_page, exact_fixture_url, viewport)
    route, body = held[0]
    before_reload = json.loads(
        page.evaluate("sessionStorage.getItem('duck-diary.child-session.v1')")
    )
    assert before_reload["state"] == "submitting"
    assert before_reload["draft"]["request_id"] == body["request_id"]
    assert before_reload["draft"]["text"] == body["text"]

    page.reload(wait_until="domcontentloaded")
    page.get_by_role("button", name="重新发送", exact=True).wait_for()
    restored_bytes = page.evaluate(
        "sessionStorage.getItem('duck-diary.child-session.v1')"
    )
    restored = json.loads(restored_bytes)
    assert restored["state"] == "submission_failed"
    assert restored["draft"]["request_id"] == body["request_id"]
    assert restored["draft"]["text"] == body["text"]

    route.fulfill(
        status=200,
        content_type="application/json",
        body=json.dumps(_chat_success_for(body)),
    )
    page.evaluate("() => Promise.resolve()")
    assert page.evaluate(
        "sessionStorage.getItem('duck-diary.child-session.v1')"
    ) == restored_bytes
    assert page.get_by_text("今天的小鸭很开心。", exact=True).count() == 0
    assert page.get_by_role("button", name="重新发送", exact=True).is_visible()


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=["1024x576", "1280x720"])
def test_pagehide_destroy_makes_held_callback_inert(
    child_page, exact_fixture_url, viewport
):
    page, held = _start_held_chat(child_page, exact_fixture_url, viewport)
    route, body = held[0]
    durable_bytes = page.evaluate(
        "sessionStorage.getItem('duck-diary.child-session.v1')"
    )
    assert json.loads(durable_bytes)["state"] == "submitting"

    page.dispatch_event("body", "pagehide")
    route.fulfill(
        status=200,
        content_type="application/json",
        body=json.dumps(_chat_success_for(body)),
    )
    page.evaluate("() => Promise.resolve()")

    assert page.evaluate(
        "sessionStorage.getItem('duck-diary.child-session.v1')"
    ) == durable_bytes
    body_copy = page.locator("body").inner_text()
    assert "今天的小鸭很开心。" not in body_copy
    assert "今天的话已经安全记下来啦" not in body_copy


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=["1024x576", "1280x720"])
def test_completed_reset_clears_only_isolated_durable_state(
    child_page, exact_fixture_url, viewport
):
    page = child_page.page
    page.set_viewport_size(viewport)
    complete_requests = _install_ended_flow(child_page, exact_fixture_url)
    _drive_ended_flow(child_page)

    reset = page.get_by_role("button", name="换下一位小朋友", exact=True)
    reset.wait_for()
    assert complete_requests == [{"expected_last_message_id": 104}]
    assert json.loads(
        page.evaluate("sessionStorage.getItem('duck-diary.child-session.v1')")
    )["state"] == "completed"

    reset.click()
    page.get_by_role("button", name="开始", exact=True).wait_for()
    assert page.evaluate(
        "sessionStorage.getItem('duck-diary.child-session.v1')"
    ) is None
    body = page.locator("body").inner_text()
    assert "我给小鸭讲了一个故事。" not in body
    assert "今天的小鸭很开心。" not in body
    assert page.locator(".child-view").get_attribute("data-state") == "welcome"
    assert complete_requests == [{"expected_last_message_id": 104}]


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=["1024x576", "1280x720"])
@pytest.mark.parametrize("fault", ["chat_retryable", "completion_failure"])
def test_fault_recovery_preserves_accessibility_and_projection_constraints(
    child_page, exact_fixture_url, viewport, fault
):
    page = child_page.page
    page.emulate_media(reduced_motion="reduce")

    if fault == "chat_retryable":
        page, held = _start_held_chat(child_page, exact_fixture_url, viewport)
        route, _body = held[0]
        route.fulfill(
            status=503,
            content_type="application/json",
            body=json.dumps({
                "error": {
                    "code": "UPSTREAM_UNAVAILABLE",
                    "message": "raw-chat-a11y-secret",
                    "retryable": True,
                }
            }),
        )
        page.get_by_role("button", name="重新发送", exact=True).wait_for()
        _assert_fault_projection_accessibility(
            page,
            expected_focus="#retry-button",
            expected_alert="暂时没有收到日记本的确认，原话已经保留",
        )
        assert "raw-chat-a11y-secret" not in page.locator("body").inner_text()
        return

    page.set_viewport_size(viewport)
    _install_ended_flow(child_page, exact_fixture_url, complete_ok=False)
    _drive_ended_flow(child_page)
    page.get_by_role("button", name="请老师帮忙", exact=True).wait_for()
    _assert_fault_projection_accessibility(
        page,
        expected_focus="#teacher-help-button",
        expected_alert="这次对话需要老师检查后再继续",
    )
    assert "raw-completion-a11y-secret" not in page.locator("body").inner_text()
