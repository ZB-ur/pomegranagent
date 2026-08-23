"""Teacher PIN session boundary integration tests."""

from app.backend import models


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
    from app.backend.main import app

    protected = {
        ("GET", "/api/children"),
        ("POST", "/api/children"),
        ("PUT", "/api/children/{child_id}"),
        ("DELETE", "/api/children/{child_id}"),
        ("GET", "/api/ducks"),
        ("POST", "/api/ducks"),
        ("PUT", "/api/ducks/{duck_id}"),
        ("DELETE", "/api/ducks/{duck_id}"),
        ("GET", "/api/ducks/{duck_id}/archive"),
        ("POST", "/api/ducks/{duck_id}/summarize"),
        ("PUT", "/api/ducks/{duck_id}/archive"),
        ("GET", "/api/roster"),
        ("POST", "/api/roster"),
        ("POST", "/api/roster/auto"),
        ("GET", "/api/dimensions"),
        ("POST", "/api/dimensions"),
        ("PUT", "/api/dimensions/{dim_id}"),
        ("GET", "/api/conversations"),
        ("GET", "/api/conversations/{conv_id}"),
        ("GET", "/api/assessments"),
        ("POST", "/api/assessments/{assessment_id}/confirm"),
        ("PATCH", "/api/conversations/{conv_id}/logs"),
        ("GET", "/api/analysis/growth"),
        ("GET", "/api/analysis/overview"),
    }
    routes = {
        (method, route.path): route
        for route in app.routes
        if hasattr(route, "methods")
        for method in route.methods
    }

    assert protected <= routes.keys()
    for key in protected:
        calls = [getattr(dependency.call, "__name__", None) for dependency in routes[key].dependant.dependencies]
        assert "require_teacher_session" in calls, key


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
    assert client.post("/api/chat", json={"child_id": 99999, "text": "你好"}).status_code == 404
    assert client.post("/api/conversations/99999/finalize").status_code == 404
    assert client.get("/api/tts", params={"text": ""}).status_code == 400
