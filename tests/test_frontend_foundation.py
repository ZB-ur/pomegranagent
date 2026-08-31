from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
CHILD_SVG_ASSETS = (
    "assets/notebook-mark.svg",
    "assets/diary-mark.svg",
    "assets/decor-sage.svg",
    "assets/decor-ochre.svg",
)


def test_child_shell_loads_foundation_before_the_single_browser_entry():
    html = (ROOT / "app/frontend/index.html").read_text(encoding="utf-8")
    assert '<link rel="stylesheet" href="/child/styles.css">' in html
    assert '<main id="child-app" aria-busy="true" aria-labelledby="child-shell-title">' in html
    assert html.index('/shared/api.js') < html.index('/shared/auth.js') < html.index('/child/browser.mjs')
    assert '<script type="module" src="/child/browser.mjs"></script>' in html
    assert '/child/app.mjs' not in html
    assert not re.search(r'<script(?![^>]*\bsrc=)[^>]*>', html)


def test_child_shell_has_no_legacy_or_direct_browser_behavior():
    html = (ROOT / "app/frontend/index.html").read_text(encoding="utf-8")
    forbidden = ('<style', 'fetch(', 'DuckAPI', 'DuckAuth', 'SpeechRecognition',
                 'speechSynthesis', 'sessionStorage', '<input', '<textarea',
                 'onclick=', 'id="stage"', 'id="root"', 'id="ptt"')
    assert all(token not in html for token in forbidden)


def test_child_design_assets_are_local_safe_single_root_svgs():
    for filename in CHILD_SVG_ASSETS:
        source = (ROOT / "app" / "frontend" / filename).read_text(encoding="utf-8")
        assert len(re.findall(r"<svg\b", source, flags=re.IGNORECASE)) == 1
        assert len(re.findall(r"</svg\s*>", source, flags=re.IGNORECASE)) == 1
        assert re.search(r"\A\s*(?:<\?xml[^>]*>\s*)?<svg\b", source, flags=re.IGNORECASE)
        assert re.search(r"</svg\s*>\s*\Z", source, flags=re.IGNORECASE)
        assert not re.search(r"<script\b", source, flags=re.IGNORECASE)
        assert not re.search(r"\son[a-z][a-z0-9_-]*\s*=", source, flags=re.IGNORECASE)
        references = re.sub(
            r"\sxmlns(?::[a-z][a-z0-9_-]*)?\s*=\s*[\"'][^\"']+[\"']",
            "",
            source,
            flags=re.IGNORECASE,
        )
        assert not re.search(r"(?:https?:)?//", references, flags=re.IGNORECASE)
        assert not re.search(r"(?:href|xlink:href|src)\s*=\s*[\"'](?!#)", references, flags=re.IGNORECASE)
        assert not re.search(r"url\(\s*[\"']?(?!#)", source, flags=re.IGNORECASE)
        assert not re.search(r"data:image/", source, flags=re.IGNORECASE)


def test_teacher_shell_loads_only_foundation_and_one_module_entry():
    html = (ROOT / "app/frontend/teacher.html").read_text(encoding="utf-8")
    assert '<link rel="stylesheet" href="/teacher/styles.css">' in html
    script_sources = re.findall(r'<script[^>]+src="([^"]+)"[^>]*></script>', html)
    assert script_sources == [
        "/shared/api.js",
        "/shared/auth.js",
        "/teacher/app.js",
    ]
    assert html.count("<script") == 3
    assert '<script type="module" src="/teacher/app.js"></script>' in html
    assert not re.search(r'<script(?![^>]*\bsrc=)[^>]*>', html)
    assert "<style" not in html
    assert "style=" not in html


def test_teacher_assets_hold_runtime_auth_and_no_direct_fetch_contract():
    html = (ROOT / "app/frontend/teacher.html").read_text(encoding="utf-8")
    app = (ROOT / "app/frontend/teacher/app.js").read_text(encoding="utf-8")
    css = (ROOT / "app/frontend/teacher/styles.css").read_text(encoding="utf-8")
    router = (ROOT / "app/frontend/teacher/router.mjs").read_text(encoding="utf-8")
    management = (ROOT / "app/frontend/teacher/views/management.mjs").read_text(encoding="utf-8")
    reports = (ROOT / "app/frontend/teacher/views/reports.mjs").read_text(encoding="utf-8")
    assert "fetch(" not in html + app + router + management + reports
    assert "window.DuckAPI.ready()" in app
    assert "window.DuckAuth.status()" in app
    assert "window.DuckAuth.setup(" in app
    assert "window.DuckAuth.unlock(" in app
    assert "window.DuckAuth.lock()" in app
    assert "bootstrapVersionGate" not in app
    assert app.index("await window.DuckAPI.ready()") < app.index("window.DuckAuth.status()")
    assert ":focus-visible" in css
    assert "min-height: 44px" in css or "min-block-size: 44px" in css
    assert "prefers-reduced-motion: reduce" in css


def test_teacher_composes_safe_management_and_reports_without_legacy_routes():
    app = (ROOT / "app/frontend/teacher/app.js").read_text(encoding="utf-8")
    html = (ROOT / "app/frontend/teacher.html").read_text(encoding="utf-8")
    router = (ROOT / "app/frontend/teacher/router.mjs").read_text(encoding="utf-8")
    management = (ROOT / "app/frontend/teacher/views/management.mjs").read_text(encoding="utf-8")
    reports = (ROOT / "app/frontend/teacher/views/reports.mjs").read_text(encoding="utf-8")
    expected_routes = {"today", "children", "ducks", "roster", "review", "growth", "search"}

    assert "import { createTeacherRouter } from './router.mjs';" in app
    assert "import { createManagementRoutes } from './views/management.mjs';" in app
    assert "import { createReportRoutes } from './views/reports.mjs';" in app
    assert "import { createTodayRoute } from './views/today.mjs';" in app
    assert "import { createReviewRoute } from './views/review.mjs';" in app
    assert "import { createDirtyGuard } from './dirty-guard.mjs';" in app
    assert "const reviewDirtyGuard = createDirtyGuard({ window, document });" in app
    assert "dirtyGuard: reviewDirtyGuard" in app
    assert "confirmLeave: () => reviewDirtyGuard.confirmLeave()" in app
    assert "defaultRoute: 'today'" in app
    assert 'data-v="today"' in html
    assert '>今日任务</button>' in html
    assert "teacherRouter.start()" in app
    assert "teacherRouter.stop()" in app
    assert "const views = {}" not in app
    assert "function show(" not in app
    assert "function buildView(" not in app
    assert "function routeFromHash(" not in app
    assert "bootstrapVersionGate" not in app
    assert "/api/" not in app
    assert "DuckAPI" not in router + management + reports
    assert "DuckAuth" not in router + management + reports
    assert set(re.findall(r"route: '([a-z]+)'", app)) == expected_routes
    assert not (ROOT / "app/frontend/teacher/legacy-routes.mjs").exists()
    assert "/api/analysis/overview" not in app + reports
    assert "method: 'DELETE'" not in management + reports
    assert "alert(" not in management + reports
    assert "error.message" not in app + router + management + reports
    assert "innerHTML" not in management + reports
    assert "globalThis" not in management + reports
    assert "createRequestId: () => window.crypto.randomUUID()" in app


def test_auth_adapter_loads_immediately_after_api_client_on_both_pages():
    child_html = (ROOT / "app/frontend/index.html").read_text(encoding="utf-8")
    assert child_html.index('/shared/api.js') < child_html.index('/shared/auth.js') < child_html.index('/child/browser.mjs')

    teacher_html = (ROOT / "app/frontend/teacher.html").read_text(encoding="utf-8")
    assert teacher_html.index('/shared/api.js') < teacher_html.index('/shared/auth.js') < teacher_html.index('/teacher/app.js')

    source = (ROOT / "app" / "frontend" / "shared" / "auth.js").read_text(encoding="utf-8")
    for method, path in {
        "status": "/api/auth/status",
        "setup": "/api/auth/setup",
        "unlock": "/api/auth/unlock",
        "lock": "/api/auth/lock",
    }.items():
        assert method in source
        assert path in source


def test_child_empty_roster_copy_is_owned_by_the_semantic_view():
    html = (ROOT / "app/frontend/index.html").read_text(encoding="utf-8")
    view = (ROOT / "app/frontend/child/view.mjs").read_text(encoding="utf-8")
    assert "今天还未排班，请老师帮忙" in view
    assert "/api/children" not in html


def test_pages_do_not_call_fetch_directly():
    for filename in ("index.html", "teacher.html", "teacher/app.js", "teacher/router.mjs", "teacher/views/management.mjs", "teacher/views/reports.mjs"):
        html = (ROOT / "app" / "frontend" / filename).read_text(encoding="utf-8")
        assert "fetch(" not in html


def test_shared_client_exports_frozen_contract():
    source = (ROOT / "app" / "frontend" / "shared" / "api.js").read_text(encoding="utf-8")
    for name in ("request", "bootstrapVersionGate", "ready", "APIError"):
        assert name in source


def test_teacher_navigation_is_blocked_until_runtime_ready():
    html = (ROOT / "app" / "frontend" / "teacher.html").read_text(encoding="utf-8")
    app = (ROOT / "app" / "frontend" / "teacher" / "app.js").read_text(encoding="utf-8")
    assert '<nav class="nav" id="nav" aria-busy="true">' in html
    assert html.count(" disabled>") == 7
    assert "let runtimeReady = false;" in app
    assert "if (!runtimeReady || !teacherAuthenticated) return;" in app
    assert "nav.setAttribute('aria-busy', 'true');" in app
    assert "nav.querySelectorAll('button').forEach(button => { button.disabled = true; });" in app
    assert "runtimeReady = true;" in app
    assert "nav.removeAttribute('aria-busy');" in app
    assert "nav.querySelectorAll('button').forEach(button => { button.disabled = false; });" in app


def test_teacher_navigation_requires_both_runtime_and_authentication_and_can_relock():
    app = (ROOT / "app" / "frontend" / "teacher" / "app.js").read_text(encoding="utf-8")
    assert "let teacherAuthenticated = false;" in app
    assert "if (!runtimeReady || !teacherAuthenticated) return;" in app
    assert "unlockTeacherPage" in app
    assert "window.DuckAuth.lock()" in app
    assert "教师端已锁定，重新输入 PIN 后可继续。" in app
    assert "teacherRouter.stop()" in app
    assert "teacherRouter = null" in app
