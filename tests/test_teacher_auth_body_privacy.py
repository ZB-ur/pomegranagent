"""Teacher JSON writes must authenticate before touching request bodies."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

import pytest
from fastapi.routing import APIRoute

from app.backend.auth import require_teacher_session
from app.backend.main import app


@dataclass(frozen=True, slots=True)
class ProtectedBodyRoute:
    method: str
    template: str
    concrete_path: str


PROTECTED_BODY_ROUTES = (
    ProtectedBodyRoute("POST", "/api/children", "/api/children"),
    ProtectedBodyRoute("PUT", "/api/children/{child_id}", "/api/children/1"),
    ProtectedBodyRoute("POST", "/api/ducks", "/api/ducks"),
    ProtectedBodyRoute("PUT", "/api/ducks/{duck_id}", "/api/ducks/1"),
    ProtectedBodyRoute("POST", "/api/roster/auto", "/api/roster/auto"),
    ProtectedBodyRoute("POST", "/api/roster/month", "/api/roster/month"),
    ProtectedBodyRoute(
        "PUT",
        "/api/roster/{roster_date}",
        "/api/roster/2026-09-05",
    ),
    ProtectedBodyRoute(
        "PUT",
        "/api/conversations/{conversation_id}/review",
        "/api/conversations/1/review",
    ),
    ProtectedBodyRoute("POST", "/api/dimensions", "/api/dimensions"),
    ProtectedBodyRoute("PUT", "/api/dimensions/{dim_id}", "/api/dimensions/1"),
    ProtectedBodyRoute(
        "PUT",
        "/api/ducks/{duck_id}/archive",
        "/api/ducks/1/archive",
    ),
)

_PRIVATE_JSON = b'{"confidential":"must-not-be-read-before-auth"}'


async def _raw_unauthenticated_request(
    application,
    route: ProtectedBodyRoute,
) -> tuple[int, dict[str, object], int]:
    messages: list[dict] = []
    receive_calls = 0

    async def receive() -> dict:
        nonlocal receive_calls
        receive_calls += 1
        if receive_calls > 1:
            return {"type": "http.disconnect"}
        return {
            "type": "http.request",
            "body": _PRIVATE_JSON,
            "more_body": False,
        }

    async def send(message: dict) -> None:
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": route.method,
        "scheme": "http",
        "path": route.concrete_path,
        "raw_path": route.concrete_path.encode("ascii"),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(_PRIVATE_JSON)).encode("ascii")),
        ],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "state": {},
    }
    await application(scope, receive, send)

    start = next(message for message in messages if message["type"] == "http.response.start")
    body = b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    )
    return start["status"], json.loads(body), receive_calls


def _uses_teacher_session(route: APIRoute) -> bool:
    pending = list(route.dependant.dependencies)
    while pending:
        dependency = pending.pop()
        if dependency.call is require_teacher_session:
            return True
        pending.extend(dependency.dependencies)
    return False


def _effective_api_routes(routes) -> list[APIRoute]:
    effective: list[APIRoute] = []
    for route in routes:
        included_router = getattr(route, "original_router", None)
        if included_router is not None:
            effective.extend(_effective_api_routes(included_router.routes))
        elif isinstance(route, APIRoute):
            effective.append(route)
    return effective


def _teacher_typed_body_write_inventory() -> set[tuple[str, str]]:
    writes = {"POST", "PUT", "PATCH", "DELETE"}
    return {
        (method, route.path)
        for route in _effective_api_routes(app.routes)
        if route.body_field is not None
        and _uses_teacher_session(route)
        for method in route.methods & writes
    }


def test_protected_teacher_json_write_inventory_uses_manual_body_dependencies() -> None:
    effective_routes = _effective_api_routes(app.routes)
    documented = app.openapi()["paths"]
    for protected in PROTECTED_BODY_ROUTES:
        matching = [
            route
            for route in effective_routes
            if protected.method in route.methods and route.path == protected.template
        ]
        assert len(matching) == 1, (protected.method, protected.template)
        assert _uses_teacher_session(matching[0])
        assert matching[0].body_field is None
        request_body = documented[protected.template][protected.method.lower()][
            "requestBody"
        ]
        assert request_body["required"] is True
        assert "schema" in request_body["content"]["application/json"]

    assert _teacher_typed_body_write_inventory() == set()


@pytest.mark.parametrize(
    "route",
    PROTECTED_BODY_ROUTES,
    ids=lambda route: f"{route.method.lower()}-{route.template}",
)
def test_unauthenticated_teacher_write_rejects_before_receiving_json_body(
    client,
    route: ProtectedBodyRoute,
) -> None:
    status, response_body, receive_calls = asyncio.run(
        _raw_unauthenticated_request(client.app, route)
    )

    assert receive_calls == 0
    assert status == 401
    assert response_body["error"]["code"] == "TEACHER_AUTH_REQUIRED"


def test_manual_body_dependency_preserves_strict_content_type_behavior(client) -> None:
    assert client.post("/api/auth/setup", json={"pin": "1234"}).status_code == 200

    response = client.post(
        "/api/children",
        content=b'{"name":"no-content-type"}',
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "body" in response.json()["error"]["field_errors"]
