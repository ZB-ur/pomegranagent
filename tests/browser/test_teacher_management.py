import json
from pathlib import Path
import re
from urllib.parse import parse_qs, urlsplit

import pytest

from tests.browser.conftest import is_exact_fixture_url


PIN = "1234"
VIEWPORTS = [{"width": 1024, "height": 576}, {"width": 1280, "height": 720}]
VIEWPORT_IDS = ["1024x576", "1280x720"]
ROOT = Path(__file__).resolve().parents[2]
OLD_AVATAR = "/api/media/avatars/a30a6409-58b8-48f0-96f0-8ff679bebed7"
NEW_AVATAR_ID = "b30a6409-58b8-48f0-96f0-8ff679bebed7"
NEW_AVATAR = f"/api/media/avatars/{NEW_AVATAR_ID}"


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


def test_children_page_owns_create_dialog_instead_of_a_persistent_form(teacher_browser):
    context = teacher_browser.new_context()
    page = context.new_page()
    page.set_default_timeout(5_000)
    page.set_viewport_size({"width": 1024, "height": 768})
    page.route(
        f"{teacher_browser.server.base_url}/api/children?include_inactive=true",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps([{
                "id": 7,
                "name": "小雨",
                "nickname": "雨雨",
                "avatar": None,
                "active": True,
                "deactivated_at": None,
                "future_roster_entries": 2,
                "has_active_conversation": False,
            }], ensure_ascii=False),
        ),
    )
    page.goto(
        f"{teacher_browser.server.base_url}/teacher.html#children",
        wait_until="domcontentloaded",
    )
    setup(page)
    page.get_by_role("heading", name="幼儿管理", exact=True).wait_for()

    launcher = page.get_by_role("button", name="添加幼儿", exact=True)
    observed = {
        "launcher_count": launcher.count(),
        "persistent_name_fields": page.get_by_label("幼儿姓名", exact=True).count(),
        "persistent_nickname_fields": page.get_by_label("小名", exact=True).count(),
    }
    launcher.click()
    observed["named_create_dialogs"] = page.get_by_role(
        "dialog", name="新增幼儿", exact=True
    ).count()

    assert observed == {
        "launcher_count": 1,
        "persistent_name_fields": 0,
        "persistent_nickname_fields": 0,
        "named_create_dialogs": 1,
    }
    dialog = page.get_by_role("dialog", name="新增幼儿", exact=True)
    assert dialog.evaluate("node => node.tagName === 'DIALOG'")
    page.keyboard.press("Escape")
    dialog.wait_for(state="detached")
    assert launcher.evaluate("button => document.activeElement === button")


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_children_management_is_labeled_strict_and_never_sends_delete(teacher_browser, viewport):
    calls = []
    rows = [{
        "id": 7, "name": "小雨", "nickname": "雨雨", "avatar": OLD_AVATAR,
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
    create_launcher = page.get_by_role("button", name="添加幼儿", exact=True)
    assert page.get_by_label("幼儿姓名", exact=True).count() == 0
    create_launcher.click()
    create_dialog = page.get_by_role("dialog", name="新增幼儿", exact=True)
    create_dialog.wait_for()
    create_dialog.get_by_text(re.compile(r"JPEG.*PNG.*WebP")).wait_for()
    assert create_dialog.get_by_label("头像图片", exact=True).count() == 1
    create_dialog.get_by_label("幼儿姓名", exact=True).fill("  新幼儿  ")
    create_dialog.get_by_label("小名", exact=True).fill("  小新  ")
    create_dialog.get_by_role(
        "button", name=re.compile(r"^(确认)?添加幼儿$")
    ).click()
    page.wait_for_function("() => document.querySelector('[role=status]')?.textContent.includes('已保存')")
    create_dialog.wait_for(state="detached")
    assert create_launcher.evaluate("button => document.activeElement === button")

    edit_launcher = page.get_by_role("button", name="编辑：雨雨", exact=True)
    edit_launcher.click()
    edit_dialog = page.get_by_role("dialog", name="修改幼儿：雨雨", exact=True)
    edit_dialog.wait_for()
    assert edit_dialog.get_by_label("幼儿姓名", exact=True).input_value() == "小雨"
    assert edit_dialog.get_by_label("小名", exact=True).input_value() == "雨雨"
    edit_dialog.get_by_text(re.compile(r"JPEG.*PNG.*WebP")).wait_for()
    assert edit_dialog.get_by_label("头像图片", exact=True).count() == 1
    edit_dialog.get_by_label("幼儿姓名", exact=True).fill("  小雨更新  ")
    edit_dialog.get_by_label("小名", exact=True).fill("")
    edit_dialog.get_by_role("button", name="保存幼儿", exact=True).click()
    page.wait_for_function("() => document.querySelector('[role=status]')?.textContent.includes('已保存')")
    edit_dialog.wait_for(state="detached")
    assert page.get_by_role("button", name="编辑：雨雨", exact=True).evaluate(
        "button => document.activeElement === button"
    )

    mutations = [call for call in calls if call[0] in {"POST", "PUT"}]
    assert len(mutations) == 2
    assert json.loads(mutations[0][2]) == {"name": "新幼儿", "nickname": "小新", "avatar": None}
    assert json.loads(mutations[1][2]) == {
        "name": "小雨更新",
        "nickname": None,
        "avatar": OLD_AVATAR,
    }
    assert "/api/children/7" in mutations[1][1]
    assert any(parse_qs(urlsplit(call[1]).query) == {"include_inactive": ["true"]} for call in calls)
    assert all(call[0] != "DELETE" for call in calls)
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_ducks_create_and_edit_use_page_owned_dialogs_and_preserve_dto(
    teacher_browser, viewport
):
    calls = []
    rows = [{
        "id": 9,
        "name": "小黄",
        "avatar": OLD_AVATAR,
        "status": "活泼",
        "note": "喜欢晒太阳",
        "active": True,
        "deactivated_at": None,
        "historical_feeding_log_count": 3,
    }]

    def ducks(route):
        assert is_exact_fixture_url(route.request.url, teacher_browser.server.port)
        calls.append((route.request.method, route.request.url, route.request.post_data))
        if route.request.method in {"POST", "PUT"}:
            body = json.loads(route.request.post_data)
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "id": 10 if route.request.method == "POST" else 9,
                    "name": body["name"],
                    "avatar": body["avatar"],
                    "status": body["status"],
                    "note": body["note"],
                }, ensure_ascii=False),
            )
            return
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(rows, ensure_ascii=False),
        )

    context = teacher_browser.new_context()
    page = context.new_page()
    page.set_default_timeout(5_000)
    page.set_viewport_size(viewport)
    page.route(f"{teacher_browser.server.base_url}/api/ducks**", ducks)
    page.goto(
        f"{teacher_browser.server.base_url}/teacher.html#ducks",
        wait_until="domcontentloaded",
    )
    setup(page)
    page.get_by_role("heading", name="小鸭管理", exact=True).wait_for()

    create_launcher = page.get_by_role("button", name="添加小鸭", exact=True)
    assert page.get_by_label("小鸭名字", exact=True).count() == 0
    create_launcher.click()
    create_dialog = page.get_by_role("dialog", name="新增小鸭", exact=True)
    create_dialog.wait_for()
    assert create_dialog.evaluate("node => node.tagName === 'DIALOG'")
    create_dialog.get_by_text(re.compile(r"JPEG.*PNG.*WebP")).wait_for()
    assert create_dialog.get_by_label("头像图片", exact=True).count() == 1
    page.keyboard.press("Escape")
    create_dialog.wait_for(state="detached")
    assert create_launcher.evaluate("button => document.activeElement === button")

    create_launcher.click()
    create_dialog = page.get_by_role("dialog", name="新增小鸭", exact=True)
    create_dialog.get_by_label("小鸭名字", exact=True).fill("  新小鸭  ")
    create_dialog.get_by_label("状态", exact=True).fill("  健康  ")
    create_dialog.get_by_label("备注", exact=True).fill("  第一次记录  ")
    create_dialog.get_by_role(
        "button", name=re.compile(r"^(确认)?添加小鸭$")
    ).click()
    create_dialog.wait_for(state="detached")
    assert create_launcher.evaluate("button => document.activeElement === button")

    edit_launcher = page.get_by_role("button", name="编辑：小黄", exact=True)
    edit_launcher.click()
    edit_dialog = page.get_by_role("dialog", name="修改小鸭：小黄", exact=True)
    edit_dialog.wait_for()
    assert edit_dialog.get_by_label("小鸭名字", exact=True).input_value() == "小黄"
    assert edit_dialog.get_by_label("状态", exact=True).input_value() == "活泼"
    assert edit_dialog.get_by_label("备注", exact=True).input_value() == "喜欢晒太阳"
    assert edit_dialog.get_by_label("头像图片", exact=True).count() == 1
    edit_dialog.get_by_label("状态", exact=True).fill("  休息中  ")
    edit_dialog.get_by_label("备注", exact=True).fill("")
    edit_dialog.get_by_role("button", name="保存小鸭", exact=True).click()
    edit_dialog.wait_for(state="detached")
    assert page.get_by_role("button", name="编辑：小黄", exact=True).evaluate(
        "button => document.activeElement === button"
    )

    mutations = [call for call in calls if call[0] in {"POST", "PUT"}]
    assert len(mutations) == 2
    assert json.loads(mutations[0][2]) == {
        "name": "新小鸭",
        "avatar": None,
        "status": "健康",
        "note": "第一次记录",
    }
    assert json.loads(mutations[1][2]) == {
        "name": "小黄",
        "avatar": OLD_AVATAR,
        "status": "休息中",
        "note": None,
    }
    assert "/api/ducks/9" in mutations[1][1]
    assert any(
        parse_qs(urlsplit(call[1]).query) == {"include_inactive": ["true"]}
        for call in calls
    )
    assert all(call[0] != "DELETE" for call in calls)
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=VIEWPORT_IDS)
def test_avatar_preview_upload_retry_save_and_remove_are_ordered_and_retained(
    teacher_browser,
    viewport,
):
    row = {
        "id": 7,
        "name": "小雨",
        "nickname": "雨雨",
        "avatar": OLD_AVATAR,
        "active": True,
        "deactivated_at": None,
        "future_roster_entries": 2,
        "has_active_conversation": False,
    }
    calls = []
    upload_request_ids = []
    resource_attempts = 0

    def children(route):
        nonlocal resource_attempts
        if route.request.method == "PUT":
            body = json.loads(route.request.post_data)
            calls.append(("resource", body, route.request.headers["x-request-id"]))
            resource_attempts += 1
            if resource_attempts == 1:
                route.fulfill(
                    status=503,
                    content_type="application/json",
                    body=json.dumps({"error": {
                        "code": "RESOURCE_WRITE_UNAVAILABLE",
                        "message": "private resource detail",
                        "field_errors": {},
                        "retryable": True,
                        "request_id": "server-resource-request",
                    }}),
                )
                return
            row.update({
                "name": body["name"],
                "nickname": body["nickname"],
                "avatar": body["avatar"],
            })
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "id": 7,
                    "name": row["name"],
                    "nickname": row["nickname"],
                    "avatar": row["avatar"],
                    "active": True,
                }, ensure_ascii=False),
            )
            return
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps([row], ensure_ascii=False),
        )

    def upload(route):
        calls.append(("upload", route.request.headers.get("content-type"), None))
        upload_request_ids.append(route.request.headers["x-request-id"])
        assert route.request.post_data_buffer is not None
        assert b"avatar.png" in route.request.post_data_buffer
        if len(upload_request_ids) == 1:
            route.fulfill(
                status=503,
                content_type="application/json",
                body=json.dumps({"error": {
                    "code": "AVATAR_STORAGE_UNAVAILABLE",
                    "message": "private storage detail",
                    "field_errors": {},
                    "retryable": True,
                    "request_id": "server-request",
                }}),
            )
            return
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "id": NEW_AVATAR_ID,
                "url": NEW_AVATAR,
                "mime_type": "image/webp",
                "width": 128,
                "height": 128,
                "size_bytes": 4096,
                "sha256": "ab" * 32,
            }),
        )

    context = teacher_browser.new_context()
    page = context.new_page()
    page.set_default_timeout(5_000)
    page.set_viewport_size(viewport)
    page.add_init_script("""
      (() => {
        const create = URL.createObjectURL.bind(URL);
        const revoke = URL.revokeObjectURL.bind(URL);
        window.__avatarObjectURLs = { created: [], revoked: [] };
        URL.createObjectURL = value => {
          const url = create(value);
          window.__avatarObjectURLs.created.push(url);
          return url;
        };
        URL.revokeObjectURL = url => {
          window.__avatarObjectURLs.revoked.push(url);
          return revoke(url);
        };
      })();
    """)
    page.route(f"{teacher_browser.server.base_url}/api/children**", children)
    page.route(f"{teacher_browser.server.base_url}/api/media/avatars", upload)
    page.goto(
        f"{teacher_browser.server.base_url}/teacher.html#children",
        wait_until="domcontentloaded",
    )
    setup(page)

    launcher = page.get_by_role("button", name="编辑：雨雨", exact=True)
    launcher.click()
    dialog = page.get_by_role("dialog", name="修改幼儿：雨雨", exact=True)
    name = dialog.get_by_label("幼儿姓名", exact=True)
    file_input = dialog.get_by_label("头像图片", exact=True)
    name.fill("  小雨更新  ")
    file_input.set_input_files({
        "name": "avatar.png",
        "mimeType": "image/png",
        "buffer": (ROOT / "app/frontend/assets/duck-front-128.png").read_bytes(),
    })
    preview = dialog.locator("[data-avatar-preview] img")
    preview.wait_for()
    assert preview.get_attribute("alt") == ""
    assert preview.get_attribute("src").startswith("blob:")
    geometry = dialog.evaluate("""
      node => {
        const preview = node.querySelector('[data-avatar-preview]').getBoundingClientRect();
        const controls = node.querySelector('.management-avatar-controls').getBoundingClientRect();
        const bounds = node.getBoundingClientRect();
        return {
          overlap: !(preview.right <= controls.left || controls.right <= preview.left ||
            preview.bottom <= controls.top || controls.bottom <= preview.top),
          top: bounds.top,
          bottom: bounds.bottom,
          viewport: innerHeight,
        };
      }
    """)
    assert geometry["overlap"] is False
    assert geometry["top"] >= 0
    assert geometry["bottom"] <= geometry["viewport"]

    save = dialog.get_by_role("button", name="保存幼儿", exact=True)
    save.click()
    dialog.get_by_text("头像上传失败，表单内容已保留，请重试。", exact=True).wait_for()
    assert name.input_value() == "  小雨更新  "
    assert file_input.input_value().endswith("avatar.png")
    assert [call[0] for call in calls] == ["upload"]
    assert "private storage detail" not in dialog.inner_text()

    save.click()
    dialog.get_by_text("保存失败，表单内容已保留，请重试。", exact=True).wait_for()
    assert name.input_value() == "  小雨更新  "
    assert file_input.input_value().endswith("avatar.png")
    assert row["avatar"] == OLD_AVATAR
    assert [call[0] for call in calls] == ["upload", "upload", "resource"]
    assert "private resource detail" not in dialog.inner_text()

    save.click()
    dialog.wait_for(state="detached")
    assert [call[0] for call in calls] == ["upload", "upload", "resource", "resource"]
    assert upload_request_ids[0] == upload_request_ids[1]
    assert all(call[2] == upload_request_ids[0] for call in calls if call[0] == "resource")
    assert calls[-1][1] == {
        "name": "小雨更新",
        "nickname": "雨雨",
        "avatar": NEW_AVATAR,
    }
    object_urls = page.evaluate("window.__avatarObjectURLs")
    assert len(object_urls["created"]) == 1
    assert object_urls["revoked"] == object_urls["created"]

    page.get_by_role("button", name="编辑：雨雨", exact=True).click()
    remove_dialog = page.get_by_role("dialog", name="修改幼儿：雨雨", exact=True)
    remove_dialog.get_by_role("button", name="移除头像", exact=True).click()
    assert remove_dialog.locator("[data-avatar-preview] img").count() == 0
    remove_dialog.get_by_role("button", name="保存幼儿", exact=True).click()
    remove_dialog.wait_for(state="detached")
    assert len(upload_request_ids) == 2
    assert calls[-1][0] == "resource"
    assert calls[-1][1]["avatar"] is None
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )


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
    requests = []
    page.on("request", lambda request: requests.append(request))
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
    page.get_by_text("暂无排班", exact=True).wait_for()
    batch = page.get_by_role("button", name="录入本月名单", exact=True)
    pending_copy = page.get_by_text(
        "按多日期录入本月名单待批量 API 开放后启用；当前可安排单日或自动生成连续工作日。",
        exact=True,
    )
    assert batch.is_disabled()
    assert pending_copy.count() == 1
    request_count = len(requests)
    batch.evaluate(
        "button => new Promise(resolve => { "
        "button.click(); requestAnimationFrame(() => resolve()); })"
    )
    assert len(requests) == request_count
    assert page.get_by_label("排班日期", exact=True).count() == 0

    daily_launcher = page.get_by_role("button", name="安排当日", exact=True)
    daily_launcher.click()
    daily_dialog = page.get_by_role("dialog", name="安排当日值日", exact=True)
    daily_dialog.wait_for()
    assert daily_dialog.evaluate("node => node.tagName === 'DIALOG'")
    daily_dialog.get_by_label("排班日期", exact=True).fill("2026-08-29")
    daily_dialog.get_by_label("手动排班周期", exact=True).fill("2026-W34")
    duty_selects = daily_dialog.locator("select")
    assert duty_selects.count() == 2
    duty_selects.nth(0).select_option("7")
    duty_selects.nth(1).select_option("8")
    daily_dialog.get_by_role("button", name="保存当日排班", exact=True).click()
    daily_dialog.wait_for(state="detached")
    page.get_by_text("排班已保存", exact=True).wait_for()
    assert daily_launcher.evaluate("button => document.activeElement === button")
    assert len(calls) == 1
    assert calls[0].method == "PUT"
    body = json.loads(calls[0].post_data)
    assert set(body) == {"request_id", "cycle", "child_ids"}
    assert calls[0].headers["x-request-id"] == body["request_id"]


def test_daily_roster_normalizes_reverse_selected_child_ids_before_validating_ack(
    teacher_browser,
):
    context = teacher_browser.new_context()
    page = context.new_page()
    page.set_default_timeout(5_000)
    page.set_viewport_size({"width": 1024, "height": 768})
    children = [
        {
            "id": 4,
            "name": "小号幼儿",
            "nickname": None,
            "avatar": None,
            "active": True,
            "deactivated_at": None,
            "future_roster_entries": 0,
            "has_active_conversation": False,
        },
        {
            "id": 9,
            "name": "大号幼儿",
            "nickname": None,
            "avatar": None,
            "active": True,
            "deactivated_at": None,
            "future_roster_entries": 0,
            "has_active_conversation": False,
        },
    ]
    calls = []
    page.route(
        f"{teacher_browser.server.base_url}/api/children?include_inactive=true",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(children, ensure_ascii=False),
        ),
    )
    page.route(
        f"{teacher_browser.server.base_url}/api/roster",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body="[]",
        ),
    )

    def daily(route):
        body = json.loads(route.request.post_data)
        calls.append({"body": body, "headers": route.request.headers})
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "request_id": body["request_id"],
                "date": "2026-09-02",
                "cycle": "2026-W36",
                "child_ids": [4, 9],
                "replayed": False,
            }),
        )

    page.route(f"{teacher_browser.server.base_url}/api/roster/2026-09-02", daily)
    page.goto(
        f"{teacher_browser.server.base_url}/teacher.html#roster",
        wait_until="domcontentloaded",
    )
    setup(page)
    launcher = page.get_by_role("button", name="安排当日", exact=True)
    launcher.click()
    dialog = page.get_by_role("dialog", name="安排当日值日", exact=True)
    dialog.get_by_label("排班日期", exact=True).fill("2026-09-02")
    dialog.get_by_label("手动排班周期", exact=True).fill("2026-W36")
    dialog.get_by_label("值日幼儿 1", exact=True).select_option("9")
    dialog.get_by_label("值日幼儿 2", exact=True).select_option("4")
    dialog.get_by_role("button", name="保存当日排班", exact=True).click()

    dialog.wait_for(state="detached")
    page.get_by_text("排班已保存", exact=True).wait_for()
    assert page.get_by_text(
        "排班保存失败，请使用相同内容重试。", exact=True
    ).count() == 0
    assert launcher.evaluate("button => document.activeElement === button")
    assert len(calls) == 1
    assert calls[0]["body"]["child_ids"] == [4, 9]
    assert calls[0]["headers"]["x-request-id"] == calls[0]["body"]["request_id"]


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
    assert page.get_by_label("自动排班开始日期", exact=True).count() == 0
    auto_launcher = page.get_by_role("button", name="自动生成", exact=True)
    auto_launcher.click()
    auto_dialog = page.get_by_role("dialog", name="自动生成排班", exact=True)
    auto_dialog.wait_for()
    assert auto_dialog.evaluate("node => node.tagName === 'DIALOG'")
    page.keyboard.press("Escape")
    auto_dialog.wait_for(state="detached")
    assert auto_launcher.evaluate("button => document.activeElement === button")

    auto_launcher.click()
    auto_dialog = page.get_by_role("dialog", name="自动生成排班", exact=True)
    auto_dialog.get_by_label("自动排班开始日期", exact=True).fill("2026-08-31")
    auto_dialog.get_by_label("自动排班天数", exact=True).fill("2")
    auto_dialog.get_by_label("自动排班周期", exact=True).fill("2026-W35")

    auto_dialog.locator("form").evaluate("""form => {
      form.dispatchEvent(new Event('submit', {bubbles: true, cancelable: true}));
      form.dispatchEvent(new Event('submit', {bubbles: true, cancelable: true}));
    }""")
    page.get_by_text("排班保存失败，请使用相同内容重试。", exact=True).wait_for()
    assert len(calls) == 1

    auto_dialog.get_by_label("自动排班周期", exact=True).fill("2026-W35-new")
    generate = auto_dialog.get_by_role("button", name="生成排班", exact=True)
    generate.click()
    generate_handle = generate.element_handle()
    assert generate_handle is not None
    page.wait_for_function("button => !button.disabled", arg=generate_handle)
    assert len(calls) == 2
    generate.click()
    auto_dialog.wait_for(state="detached")
    page.get_by_text("排班已保存", exact=True).wait_for()
    assert auto_launcher.evaluate("button => document.activeElement === button")

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
