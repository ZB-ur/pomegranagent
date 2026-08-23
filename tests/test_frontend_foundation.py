from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_both_pages_load_shared_api_before_inline_application_code():
    for filename in ("index.html", "teacher.html"):
        html = (ROOT / "app" / "frontend" / filename).read_text(encoding="utf-8")
        assert '<script src="/shared/api.js"></script>' in html
        assert html.index('/shared/api.js') < html.rindex("<script>")
        assert "DuckAPI.ready()" in html


def test_auth_adapter_loads_immediately_after_api_client_on_both_pages():
    for filename in ("index.html", "teacher.html"):
        html = (ROOT / "app" / "frontend" / filename).read_text(encoding="utf-8")
        assert html.index('/shared/api.js') < html.index('/shared/auth.js') < html.rindex("<script>")

    source = (ROOT / "app" / "frontend" / "shared" / "auth.js").read_text(encoding="utf-8")
    for method, path in {
        "status": "/api/auth/status",
        "setup": "/api/auth/setup",
        "unlock": "/api/auth/unlock",
        "lock": "/api/auth/lock",
    }.items():
        assert method in source
        assert path in source


def test_child_page_uses_the_empty_roster_message_without_calling_protected_children_api():
    html = (ROOT / "app" / "frontend" / "index.html").read_text(encoding="utf-8")
    assert "今天还未排班，请老师帮忙" in html
    assert "DuckAPI.request('/api/children')" not in html


def test_pages_do_not_call_fetch_directly():
    for filename in ("index.html", "teacher.html"):
        html = (ROOT / "app" / "frontend" / filename).read_text(encoding="utf-8")
        assert "fetch(" not in html


def test_shared_client_exports_frozen_contract():
    source = (ROOT / "app" / "frontend" / "shared" / "api.js").read_text(encoding="utf-8")
    for name in ("request", "bootstrapVersionGate", "ready", "APIError"):
        assert name in source


def test_teacher_navigation_is_blocked_until_runtime_ready():
    html = (ROOT / "app" / "frontend" / "teacher.html").read_text(encoding="utf-8")
    assert '<nav class="nav" id="nav" aria-busy="true">' in html
    assert html.count(" disabled>") == 7
    assert "let runtimeReady = false;" in html
    assert "if (!runtimeReady || !teacherAuthenticated) return;" in html
    assert "nav.setAttribute('aria-busy', 'true');" in html
    assert "nav.querySelectorAll('button').forEach(button => { button.disabled = true; });" in html
    assert "runtimeReady = true;" in html
    assert "nav.removeAttribute('aria-busy');" in html
    assert "nav.querySelectorAll('button').forEach(button => { button.disabled = false; });" in html


def test_teacher_navigation_requires_both_runtime_and_authentication_and_can_relock():
    html = (ROOT / "app" / "frontend" / "teacher.html").read_text(encoding="utf-8")
    assert "let teacherAuthenticated = false;" in html
    assert "if (!runtimeReady || !teacherAuthenticated) return;" in html
    assert "unlockTeacherPage" in html
    assert "DuckAuth.lock()" in html
    assert "教师端已锁定，重新输入 PIN 后可继续。" in html
    assert "Object.values(views).forEach((view) => view.remove());" in html
