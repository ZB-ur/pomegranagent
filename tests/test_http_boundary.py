"""Loopback same-origin boundary integration tests."""
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.backend.http_boundary import install_same_origin_boundary
from app.backend.main import app


def assert_cross_origin_rejection(response):
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CROSS_ORIGIN_FORBIDDEN"
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]
    assert "access-control-allow-origin" not in response.headers


def assert_host_rejection(response):
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "HOST_FORBIDDEN"
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]


def test_foreign_origin_is_rejected_with_standard_error_envelope(client):
    response = client.get(
        "/api/health",
        headers={"Origin": "https://attacker.example", "X-Request-ID": "foreign-123"},
    )

    assert_cross_origin_rejection(response)
    assert response.headers["x-request-id"] == "foreign-123"


def test_matching_attacker_host_and_origin_are_rejected_against_scope_server(client):
    response = client.get(
        "/api/health",
        headers={
            "Host": "attacker.example",
            "Origin": "http://attacker.example",
            "X-Request-ID": "dns-rebind-123",
        },
    )

    assert_cross_origin_rejection(response)
    assert response.headers["x-request-id"] == "dns-rebind-123"


def test_duplicate_raw_origin_headers_are_rejected(client):
    request = client.build_request(
        "GET",
        "/api/health",
        headers=[
            ("Origin", "http://testserver"),
            ("Origin", "https://attacker.example"),
            ("X-Request-ID", "duplicate-origin-123"),
        ],
    )
    origin_headers = [
        value for name, value in request.headers.raw if name.lower() == b"origin"
    ]
    assert origin_headers == [b"http://testserver", b"https://attacker.example"]

    response = client.send(request)

    assert_cross_origin_rejection(response)
    assert response.headers["x-request-id"] == "duplicate-origin-123"


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


def test_static_request_with_host_different_from_scope_server_is_rejected(client):
    response = client.get(
        "/index.html",
        headers={"Host": "attacker.example", "X-Request-ID": "static-host-123"},
    )

    assert_host_rejection(response)
    assert response.headers["x-request-id"] == "static-host-123"


@pytest.mark.parametrize("host", ["attacker.example", "localhost", "0.0.0.0"])
def test_app_mode_rejects_non_loopback_scope_even_when_host_matches(host):
    local_app = FastAPI()
    install_same_origin_boundary(local_app, db_mode="app")

    @local_app.get("/probe")
    def probe():
        return {"ok": True}

    with TestClient(local_app, base_url=f"http://{host}:8123") as local_client:
        response = local_client.get("/probe")

    assert_host_rejection(response)


def test_app_mode_allows_exact_loopback_scope_host_and_port():
    local_app = FastAPI()
    install_same_origin_boundary(local_app, db_mode="app")

    @local_app.get("/probe")
    def probe():
        return {"ok": True}

    with TestClient(local_app, base_url="http://127.0.0.1:8123") as local_client:
        response = local_client.get(
            "/probe",
            headers={"Origin": "http://127.0.0.1:8123"},
        )

    assert response.status_code == 200
    assert response.json() == {"ok": True}


@pytest.mark.parametrize("host", ["testserver", "testserver:8124"])
def test_host_header_must_include_the_exact_nondefault_scope_port(host):
    with TestClient(app, base_url="http://testserver:8123") as local_client:
        response = local_client.get("/api/health", headers={"Host": host})

    assert_host_rejection(response)


def test_duplicate_raw_host_headers_are_rejected(client):
    request = client.build_request(
        "GET",
        "/api/health",
        headers=[("Host", "testserver"), ("Host", "testserver")],
    )
    assert [
        value for name, value in request.headers.raw if name.lower() == b"host"
    ] == [b"testserver", b"testserver"]

    assert_host_rejection(client.send(request))


def test_launchers_bind_only_loopback_without_proxy_headers():
    root = Path(__file__).resolve().parents[1]
    run_sh = (root / "run.sh").read_text(encoding="utf-8")
    run_bat = (root / "run.bat").read_text(encoding="utf-8")
    assert "--host 127.0.0.1" in run_sh
    assert "--host 127.0.0.1" in run_bat
    assert "--no-proxy-headers" in run_sh
    assert "--no-proxy-headers" in run_bat
    assert "0.0.0.0" not in run_sh
    assert "0.0.0.0" not in run_bat


def test_documented_direct_uvicorn_commands_disable_proxy_headers():
    root = Path(__file__).resolve().parents[1]
    direct_commands = [
        line for line in (root / "README.md").read_text(encoding="utf-8").splitlines()
        if "uvicorn app.backend.main:app" in line
    ]

    assert len(direct_commands) == 2
    assert all("--host 127.0.0.1" in command for command in direct_commands)
    assert all("--no-proxy-headers" in command for command in direct_commands)
