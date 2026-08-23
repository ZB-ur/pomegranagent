from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
logger = logging.getLogger("duck_diary")


@dataclass
class APIError(Exception):
    status_code: int
    code: str
    message: str
    field_errors: dict[str, list[str]] = field(default_factory=dict)
    retryable: bool = False

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        field_errors: dict[str, list[str]] | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.field_errors = field_errors or {}
        self.retryable = retryable


def request_id_for(request: Request) -> str:
    current = getattr(request.state, "request_id", None)
    if current:
        return current
    incoming = request.headers.get("X-Request-ID", "")
    request.state.request_id = incoming if REQUEST_ID_PATTERN.fullmatch(incoming) else str(uuid.uuid4())
    return request.state.request_id


def error_response(request: Request, error: APIError) -> JSONResponse:
    request_id = request_id_for(request)
    return JSONResponse(
        status_code=error.status_code,
        content={"error": {
            "code": error.code,
            "message": error.message,
            "field_errors": error.field_errors,
            "retryable": error.retryable,
            "request_id": request_id,
        }},
        headers={"X-Request-ID": request_id},
    )


def install_api_error_handling(app: FastAPI) -> None:
    @app.middleware("http")
    async def add_request_id(request: Request, call_next):
        request_id = request_id_for(request)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    @app.exception_handler(APIError)
    async def handle_api_error(request: Request, exc: APIError):
        return error_response(request, exc)

    @app.exception_handler(HTTPException)
    async def handle_http_error(request: Request, exc: HTTPException):
        code = {400: "BAD_REQUEST", 401: "UNAUTHORIZED", 403: "FORBIDDEN", 404: "NOT_FOUND", 409: "CONFLICT", 429: "RATE_LIMITED"}.get(exc.status_code, "HTTP_ERROR")
        return error_response(request, APIError(exc.status_code, code, str(exc.detail), retryable=exc.status_code >= 500))

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError):
        fields: dict[str, list[str]] = {}
        for item in exc.errors():
            key = ".".join(str(part) for part in item["loc"])
            fields.setdefault(key, []).append(item["msg"])
        return error_response(request, APIError(422, "VALIDATION_ERROR", "请求字段校验失败", fields))

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception):
        logger.exception("unhandled request error request_id=%s", request_id_for(request), exc_info=exc)
        return error_response(request, APIError(500, "INTERNAL_ERROR", "服务暂时不可用，请稍后重试", retryable=True))
