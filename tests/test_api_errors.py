"""API error-envelope and request-correlation integration tests."""
import re

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.backend.main import app


def assert_error(response, *, status: int, code: str):
    assert response.status_code == status
    assert set(response.json()) == {"error"}
    error = response.json()["error"]
    assert error["code"] == code
    assert isinstance(error["message"], str) and error["message"]
    assert isinstance(error["field_errors"], dict)
    assert isinstance(error["retryable"], bool)
    assert error["request_id"] == response.headers["x-request-id"]


def unlock_teacher(client):
    response = client.post("/api/auth/setup", json={"pin": "1234"})
    assert response.status_code == 200


def test_missing_teacher_detail_uses_the_frozen_conversation_code(client):
    unlock_teacher(client)
    assert_error(client.get("/api/conversations/99999"), status=404, code="CONVERSATION_NOT_FOUND")


def test_validation_error_has_stable_field_paths(client):
    unlock_teacher(client)
    response = client.post("/api/children", json={"name": 7})

    assert_error(response, status=422, code="VALIDATION_ERROR")
    assert "body.name" in response.json()["error"]["field_errors"]


def test_valid_incoming_request_id_is_echoed(client):
    response = client.get("/api/health", headers={"X-Request-ID": "acceptance-123"})

    assert response.headers["x-request-id"] == "acceptance-123"


def test_same_origin_options_echoes_valid_request_id_without_cors_header(client):
    response = client.options(
        "/api/health",
        headers={
            "Origin": "http://testserver",
            "Access-Control-Request-Method": "GET",
            "X-Request-ID": "preflight-123",
        },
    )

    assert response.headers["x-request-id"] == "preflight-123"
    assert "access-control-allow-origin" not in response.headers


def test_invalid_incoming_request_id_is_replaced_with_valid_generated_id(client):
    response = client.get("/api/health", headers={"X-Request-ID": "invalid request id"})

    request_id = response.headers["x-request-id"]
    assert request_id != "invalid request id"
    assert re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", request_id)


def test_successful_api_response_has_request_id(client):
    response = client.get("/api/health")

    assert re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", response.headers["x-request-id"])


def test_api_error_uses_standard_envelope_for_business_failures():
    from app.backend.api_errors import APIError, install_api_error_handling

    local_app = FastAPI()
    install_api_error_handling(local_app)

    @local_app.get("/business-error")
    def business_error():
        raise APIError(409, "BUSINESS_RULE", "不能重复提交", {"body.name": ["已存在"]})

    with TestClient(local_app) as local_client:
        response = local_client.get("/business-error")

    assert_error(response, status=409, code="BUSINESS_RULE")
    assert response.json()["error"]["field_errors"] == {"body.name": ["已存在"]}


def test_unhandled_error_hides_internal_exception_detail():
    from app.backend.api_errors import install_api_error_handling

    local_app = FastAPI()
    install_api_error_handling(local_app)

    @local_app.get("/explode")
    def explode():
        raise RuntimeError("secret database detail")

    with TestClient(local_app, raise_server_exceptions=False) as local_client:
        response = local_client.get("/explode")

    assert_error(response, status=500, code="INTERNAL_ERROR")
    assert response.json()["error"]["retryable"] is True
    assert "secret database detail" not in response.text
