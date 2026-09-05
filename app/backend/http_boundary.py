"""Reject browser API traffic that did not originate from this server."""
from __future__ import annotations

from urllib.parse import urlsplit
from typing import Literal

from fastapi import FastAPI, Request

from .api_errors import APIError, error_response
from .database import DB_MODE

_DEFAULT_PORTS = {"http": 80, "https": 443}


def _effective_port(scheme: str, port: int | None) -> int | None:
    return port if port is not None else _DEFAULT_PORTS.get(scheme)


def _origin_parts(origin: str) -> tuple[str, str, int] | None:
    """Return a canonical origin only for a valid serialized HTTP(S) Origin."""
    if not origin or origin != origin.strip():
        return None

    try:
        parsed = urlsplit(origin)
        scheme = parsed.scheme.lower()
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        return None

    if (
        scheme not in _DEFAULT_PORTS
        or not parsed.netloc
        or not host
        or "@" in parsed.netloc
        or parsed.netloc.endswith(":")
    ):
        return None

    authority_and_rest = origin[len(parsed.scheme) + 3:]
    if any(character in authority_and_rest for character in "/?#"):
        return None

    effective_port = _effective_port(scheme, port)
    if effective_port is None:
        return None
    return scheme, host.lower(), effective_port


def _host_parts(authority: str, scheme: str) -> tuple[str, int] | None:
    """Parse one HTTP Host header into its canonical host and effective port."""
    if not authority or authority != authority.strip():
        return None
    try:
        parsed = urlsplit(f"{scheme}://{authority}")
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        return None
    if (
        scheme not in _DEFAULT_PORTS
        or not host
        or "@" in authority
        or any(character in authority for character in "/?#")
        or authority.endswith(":")
    ):
        return None
    effective_port = _effective_port(scheme, port)
    if effective_port is None:
        return None
    return host.lower(), effective_port


def _trusted_server_parts(request: Request) -> tuple[str, str, int] | None:
    scheme = str(request.scope.get("scheme", "")).lower()
    server = request.scope.get("server")
    if (
        scheme not in _DEFAULT_PORTS
        or not isinstance(server, (list, tuple))
        or len(server) != 2
    ):
        return None
    host, port = server
    if not isinstance(host, str) or not host or not isinstance(port, int):
        return None
    if not 1 <= port <= 65535:
        return None
    return scheme, host.lower(), port


def _origin_matches_request(origin: str, request: Request) -> bool:
    return _origin_parts(origin) == _trusted_server_parts(request)


def _host_matches_server(
    request: Request,
    db_mode: Literal["app", "test"],
) -> bool:
    trusted = _trusted_server_parts(request)
    hosts = request.headers.getlist("host")
    if trusted is None or len(hosts) != 1:
        return False
    scheme, host, port = trusted
    if db_mode == "app" and host != "127.0.0.1":
        return False
    return _host_parts(hosts[0], scheme) == (host, port)


def install_same_origin_boundary(
    app: FastAPI,
    *,
    db_mode: Literal["app", "test"] = DB_MODE,
) -> None:
    @app.middleware("http")
    async def reject_cross_origin_api(request: Request, call_next):
        origins = request.headers.getlist("origin")
        if request.url.path.startswith("/api/") and origins and (
            len(origins) != 1 or not _origin_matches_request(origins[0], request)
        ):
            return error_response(
                request,
                APIError(403, "CROSS_ORIGIN_FORBIDDEN", "不接受跨来源业务请求"),
            )
        if not _host_matches_server(request, db_mode):
            return error_response(
                request,
                APIError(403, "HOST_FORBIDDEN", "请求主机与本机服务不匹配"),
            )
        return await call_next(request)
