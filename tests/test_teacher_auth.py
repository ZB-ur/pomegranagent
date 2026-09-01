"""Teacher PIN session boundary integration tests."""

from collections import Counter
import re
from uuid import uuid4

from sqlalchemy import select

from app.backend import models


def _normalized_path(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{}", path)


def _effective_routes(routes) -> list[object]:
    return [
        child
        for route in routes
        for child in (route.original_router.routes if hasattr(route, "original_router") else [route])
    ]


def _route_method_path_counts(routes) -> Counter[tuple[str, str]]:
    return Counter(
        (method, _normalized_path(route.path))
        for route in routes
        if hasattr(route, "methods")
        for method in route.methods
        if route.path.startswith("/api/") or route.path == "/version.json"
    )


def test_first_setup_unlocks_with_a_nonpersistent_strict_session_cookie(client):
    assert client.get("/api/auth/status").json() == {
        "configured": False,
        "authenticated": False,
    }

    response = client.post("/api/auth/setup", json={"pin": "1234"})

    assert response.status_code == 200
    assert response.json() == {"configured": True, "authenticated": True}
    cookie = response.headers["set-cookie"]
    assert "duck_teacher_session=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie
    assert "Path=/" in cookie
    assert "Secure" not in cookie
    assert "Max-Age" not in cookie
    assert "Expires" not in cookie


def test_setup_is_one_time_and_wrong_pin_does_not_unlock(client):
    assert client.post("/api/auth/setup", json={"pin": "1234"}).status_code == 200
    assert client.post("/api/auth/lock").status_code == 200

    duplicate = client.post("/api/auth/setup", json={"pin": "5678"})
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "PIN_ALREADY_CONFIGURED"

    wrong = client.post("/api/auth/unlock", json={"pin": "9999"})
    assert wrong.status_code == 401
    assert wrong.json()["error"]["code"] == "PIN_INVALID"

    correct = client.post("/api/auth/unlock", json={"pin": "1234"})
    assert correct.status_code == 200
    assert correct.json() == {"configured": True, "authenticated": True}


def test_setup_race_returns_conflict_and_keeps_database_sessions_usable(
    client,
    db_session,
    monkeypatch,
):
    from app.backend import auth
    from app.backend.database import SessionLocal

    original_commit = auth.Session.commit
    inserted_competing_credential = False

    def commit_with_competing_credential(session):
        nonlocal inserted_competing_credential
        if not inserted_competing_credential and any(
            isinstance(row, models.TeacherCredential) for row in session.new
        ):
            inserted_competing_credential = True
            competing_session = SessionLocal()
            try:
                competing_session.add(
                    models.TeacherCredential(
                        id=1,
                        pin_salt="00" * 16,
                        pin_hash="competing-pin-hash",
                    )
                )
                original_commit(competing_session)
            finally:
                competing_session.close()
        return original_commit(session)

    monkeypatch.setattr(auth.Session, "commit", commit_with_competing_credential)

    response = client.post("/api/auth/setup", json={"pin": "1234"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PIN_ALREADY_CONFIGURED"
    assert db_session.scalar(select(models.TeacherCredential.pin_hash)) == "competing-pin-hash"
    assert client.get("/api/auth/status").json() == {
        "configured": True,
        "authenticated": False,
    }
    wrong_pin = client.post("/api/auth/unlock", json={"pin": "1234"})
    assert wrong_pin.status_code == 401
    assert wrong_pin.json()["error"]["code"] == "PIN_INVALID"


def test_lock_revokes_server_session_and_rejects_a_stale_cookie(client):
    response = client.post("/api/auth/setup", json={"pin": "1234"})
    token = response.cookies.get("duck_teacher_session")
    assert token
    assert client.get("/api/auth/status").json()["authenticated"] is True

    lock = client.post("/api/auth/lock")
    assert lock.status_code == 200
    assert lock.json() == {"configured": True, "authenticated": False}
    assert "duck_teacher_session=\"\"" in lock.headers["set-cookie"]
    assert client.get("/api/auth/status").json()["authenticated"] is False

    stale = client.get("/api/auth/status", headers={"Cookie": f"duck_teacher_session={token}"})
    assert stale.status_code == 200
    assert stale.json() == {"configured": True, "authenticated": False}


def test_pin_hash_never_equals_plain_pin_and_session_token_is_not_stored(client, db_session):
    response = client.post("/api/auth/setup", json={"pin": "1234"})
    token = response.cookies.get("duck_teacher_session")

    credential = db_session.query(models.TeacherCredential).one()
    session = db_session.query(models.TeacherSession).one()
    assert credential.pin_hash != "1234"
    assert credential.pin_salt
    assert session.token_hash != token
    assert len(session.token_hash) == 64


def test_pin_must_be_four_to_six_ascii_digits(client):
    for pin in ("123", "1234567", "abcd", "１２３４"):
        response = client.post("/api/auth/setup", json={"pin": pin})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_unlock_requires_prior_setup(client):
    response = client.post("/api/auth/unlock", json={"pin": "1234"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PIN_NOT_CONFIGURED"


def test_teacher_route_inventory_has_the_session_dependency():
    from app.backend.auth import require_teacher_session
    from app.backend.main import app

    protected = {
        ("GET", "/api/children"),
        ("POST", "/api/children"),
        ("PUT", "/api/children/{}"),
        ("POST", "/api/children/{}/deactivate"),
        ("POST", "/api/children/{}/reactivate"),
        ("DELETE", "/api/children/{}"),
        ("GET", "/api/ducks"),
        ("POST", "/api/ducks"),
        ("PUT", "/api/ducks/{}"),
        ("POST", "/api/ducks/{}/deactivate"),
        ("POST", "/api/ducks/{}/reactivate"),
        ("DELETE", "/api/ducks/{}"),
        ("GET", "/api/ducks/{}/archive"),
        ("POST", "/api/ducks/{}/summarize"),
        ("PUT", "/api/ducks/{}/archive"),
        ("GET", "/api/roster"),
        ("POST", "/api/roster"),
        ("POST", "/api/roster/auto"),
        ("PUT", "/api/roster/{}"),
        ("GET", "/api/dimensions"),
        ("POST", "/api/dimensions"),
        ("PUT", "/api/dimensions/{}"),
        ("GET", "/api/conversations"),
        ("GET", "/api/conversations/history"),
        ("GET", "/api/conversations/{}"),
        ("PUT", "/api/conversations/{}/review"),
        ("POST", "/api/conversations/{}/analysis/retry"),
        ("GET", "/api/assessments"),
        ("POST", "/api/assessments/{}/confirm"),
        ("PATCH", "/api/conversations/{}/logs"),
        ("GET", "/api/analysis/growth"),
        ("GET", "/api/analysis/overview"),
        ("POST", "/api/media/avatars"),
    }
    expected_methods = {
        "/api/auth/status": {"GET"},
        "/api/auth/setup": {"POST"},
        "/api/auth/unlock": {"POST"},
        "/api/auth/lock": {"POST"},
        "/api/children/{}/active-conversation": {"GET"},
        "/api/conversations/{}/complete": {"POST"},
        "/api/conversations/{}/analysis/retry": {"POST"},
        "/api/conversations": {"GET"},
        "/api/conversations/history": {"GET"},
        "/api/conversations/{}": {"GET"},
        "/api/conversations/{}/review": {"PUT"},
        "/api/chat": {"POST"},
        "/api/children": {"GET", "POST"},
        "/api/children/{}": {"PUT", "DELETE"},
        "/api/children/{}/deactivate": {"POST"},
        "/api/children/{}/reactivate": {"POST"},
        "/api/ducks": {"GET", "POST"},
        "/api/ducks/{}": {"PUT", "DELETE"},
        "/api/ducks/{}/deactivate": {"POST"},
        "/api/ducks/{}/reactivate": {"POST"},
        "/api/roster/today": {"GET"},
        "/api/roster": {"GET", "POST"},
        "/api/roster/auto": {"POST"},
        "/api/roster/{}": {"PUT"},
        "/api/health": {"GET"},
        "/version.json": {"GET"},
        "/api/dimensions": {"GET", "POST"},
        "/api/dimensions/{}": {"PUT"},
        "/api/conversations/{}/finalize": {"POST"},
        "/api/assessments": {"GET"},
        "/api/assessments/{}/confirm": {"POST"},
        "/api/conversations/{}/logs": {"PATCH"},
        "/api/ducks/{}/archive": {"GET", "PUT"},
        "/api/ducks/{}/summarize": {"POST"},
        "/api/tts": {"GET"},
        "/api/analysis/growth": {"GET"},
        "/api/analysis/overview": {"GET"},
        "/api/runtime/context": {"GET"},
        "/api/media/avatars": {"POST"},
        "/api/media/avatars/{}": {"GET", "HEAD"},
    }

    effective_routes = _effective_routes(app.router.routes)
    counts = _route_method_path_counts(effective_routes)
    expected_counts = Counter(
        (method, path)
        for path, methods in expected_methods.items()
        for method in methods
    )
    assert counts == expected_counts
    for key in protected:
        matching = [
            route
            for route in effective_routes
            if hasattr(route, "methods") and key[0] in route.methods and _normalized_path(route.path) == key[1]
        ]
        assert len(matching) == 1, key
        assert require_teacher_session in [dependency.call for dependency in matching[0].dependant.dependencies], key

    for key in {
        ("GET", "/api/children/{}/active-conversation"),
        ("POST", "/api/conversations/{}/complete"),
        ("POST", "/api/chat"),
        ("POST", "/api/conversations/{}/finalize"),
        ("GET", "/api/runtime/context"),
        ("GET", "/api/media/avatars/{}"),
        ("HEAD", "/api/media/avatars/{}"),
    }:
        route = next(
            route
            for route in effective_routes
            if hasattr(route, "methods") and key[0] in route.methods and _normalized_path(route.path) == key[1]
        )
        assert require_teacher_session not in [dependency.call for dependency in route.dependant.dependencies], key

    documented = app.openapi()["paths"]
    documented_methods = {
        _normalized_path(path): {method.upper() for method in methods}
        for path, methods in documented.items()
        if path.startswith("/api/") or path == "/version.json"
    }
    assert documented_methods == expected_methods


def test_teacher_routes_require_session_and_child_surface_remains_public(client):
    protected = [
        ("get", "/api/children", None),
        ("get", "/api/roster", None),
        ("get", "/api/conversations", None),
        ("get", "/api/analysis/overview", None),
        ("post", "/api/roster/auto", {"start_date": "2026-08-24", "days": 1, "cycle": "test"}),
    ]
    for method, path, body in protected:
        request = getattr(client, method)
        response = request(path, json=body) if body is not None else request(path)
        assert response.status_code == 401
        error = response.json()["error"]
        assert error["code"] == "TEACHER_AUTH_REQUIRED"
        assert error["request_id"]

    assert client.get("/api/health").status_code == 200
    assert client.get("/version.json").status_code == 200
    assert client.get("/api/roster/today").status_code == 200
    missing_avatar = client.get(
        "/api/media/avatars/11111111-1111-4111-8111-111111111111"
    )
    assert missing_avatar.status_code == 404
    assert missing_avatar.json()["error"]["code"] == "AVATAR_NOT_FOUND"
    unknown_chat = client.post("/api/chat", json={"request_id": str(uuid4()), "child_id": 99999, "text": "你好"})
    assert unknown_chat.status_code == 404
    assert unknown_chat.json()["error"]["code"] == "CHILD_NOT_FOUND"
    finalize = client.post("/api/conversations/99999/finalize", content=b"{not-json", headers={"content-type": "application/json"})
    assert finalize.status_code == 410
    assert finalize.json()["error"]["code"] == "LEGACY_ENDPOINT_REMOVED"
    assert client.get("/api/tts", params={"text": ""}).status_code == 400


def test_avatar_upload_authentication_precedes_multipart_validation(client):
    response = client.post(
        "/api/media/avatars",
        content=b"not multipart",
        headers={
            "Content-Type": "multipart/form-data; boundary=broken",
            "Content-Length": str(6 * 1024 * 1024),
            "X-Request-ID": "avatar-auth-first",
        },
    )

    assert response.status_code == 401
    assert response.headers["x-request-id"] == "avatar-auth-first"
    assert response.json()["error"] == {
        "code": "TEACHER_AUTH_REQUIRED",
        "message": "请先输入教师 PIN 解锁",
        "field_errors": {},
        "retryable": False,
        "request_id": "avatar-auth-first",
    }
