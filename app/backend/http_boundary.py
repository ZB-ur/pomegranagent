"""Reject browser API traffic that did not originate from this server."""
from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import FastAPI, Request

from .api_errors import APIError, error_response

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


def _request_origin_parts(request: Request) -> tuple[str, str, int] | None:
    try:
        scheme = request.url.scheme.lower()
        host = request.url.hostname
        port = request.url.port
    except ValueError:
        return None

    if scheme not in _DEFAULT_PORTS or not host:
        return None

    effective_port = _effective_port(scheme, port)
    if effective_port is None:
        return None
    return scheme, host.lower(), effective_port


def _origin_matches_request(origin: str, request: Request) -> bool:
    return _origin_parts(origin) == _request_origin_parts(request)


def install_same_origin_boundary(app: FastAPI) -> None:
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
        return await call_next(request)
