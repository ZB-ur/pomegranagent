from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_both_pages_load_shared_api_before_inline_application_code():
    for filename in ("index.html", "teacher.html"):
        html = (ROOT / "app" / "frontend" / filename).read_text(encoding="utf-8")
        assert '<script src="/shared/api.js"></script>' in html
        assert html.index('/shared/api.js') < html.rindex("<script>")
        assert "DuckAPI.ready()" in html


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
    assert "if (!runtimeReady) return;" in html
    assert "nav.setAttribute('aria-busy', 'true');" in html
    assert "nav.querySelectorAll('button').forEach(button => { button.disabled = true; });" in html
    assert "runtimeReady = true;" in html
    assert "nav.removeAttribute('aria-busy');" in html
    assert "nav.querySelectorAll('button').forEach(button => { button.disabled = false; });" in html
