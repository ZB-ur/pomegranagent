"""Loopback same-origin boundary integration tests."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.backend.main import app


def assert_cross_origin_rejection(response):
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CROSS_ORIGIN_FORBIDDEN"
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]
    assert "access-control-allow-origin" not in response.headers


def test_foreign_origin_is_rejected_with_standard_error_envelope(client):
    response = client.get(
        "/api/health",
        headers={"Origin": "https://attacker.example", "X-Request-ID": "foreign-123"},
    )

    assert_cross_origin_rejection(response)
    assert response.headers["x-request-id"] == "foreign-123"


def test_same_origin_is_allowed_without_cors_header(client):
    response = client.get("/api/health", headers={"Origin": "http://testserver"})

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_protocol_mismatch_is_rejected(client):
    response = client.get("/api/health", headers={"Origin": "https://testserver"})

    assert_cross_origin_rejection(response)


def test_port_mismatch_is_rejected():
    with TestClient(app, base_url="http://testserver:8123") as local_client:
        response = local_client.get("/api/health", headers={"Origin": "http://testserver:8124"})

    assert_cross_origin_rejection(response)


@pytest.mark.parametrize(
    ("base_url", "origin"),
    [
        ("http://testserver", "http://testserver:80"),
        ("https://testserver", "https://testserver:443"),
    ],
)
def test_default_port_origin_is_canonical_same_origin(base_url, origin):
    with TestClient(app, base_url=base_url) as local_client:
        response = local_client.get("/api/health", headers={"Origin": origin})

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.parametrize(
    "origin",
    [
        "",
        "null",
        "https://",
        "https://testserver/path",
        "https://user@testserver",
        "http://testserver:invalid",
    ],
)
def test_malformed_or_null_origin_is_rejected(client, origin):
    response = client.get("/api/health", headers={"Origin": origin})

    assert_cross_origin_rejection(response)


def test_foreign_preflight_is_rejected(client):
    response = client.options(
        "/api/health",
        headers={
            "Origin": "https://attacker.example",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert_cross_origin_rejection(response)


def test_request_without_origin_remains_allowed(client):
    response = client.get("/api/health")

    assert response.status_code == 200


def test_launchers_bind_only_loopback():
    root = Path(__file__).resolve().parents[1]
    assert "--host 127.0.0.1" in (root / "run.sh").read_text(encoding="utf-8")
    assert "--host 127.0.0.1" in (root / "run.bat").read_text(encoding="utf-8")
    assert "0.0.0.0" not in (root / "run.sh").read_text(encoding="utf-8")
    assert "0.0.0.0" not in (root / "run.bat").read_text(encoding="utf-8")
