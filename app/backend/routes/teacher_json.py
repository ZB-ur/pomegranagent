"""Authenticate teacher JSON writes before reading and validating their bodies."""

from __future__ import annotations

from email.message import Message
import json
from typing import Any, Callable

from fastapi import Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, TypeAdapter, ValidationError

from .. import models
from ..auth import require_teacher_session


BodyValidator = type[BaseModel] | TypeAdapter[Any]
BodyDependency = Callable[..., Any]

_JSON_OBJECT = TypeAdapter(dict[str, Any])


def _accepts_json(content_type: str | None) -> bool:
    if not content_type:
        return False
    message = Message()
    message["content-type"] = content_type
    if message.get_content_maintype() != "application":
        return False
    subtype = message.get_content_subtype()
    return subtype == "json" or subtype.endswith("+json")


async def _request_body_value(request: Request) -> Any:
    body_bytes = await request.body()
    if not body_bytes:
        return None
    if not _accepts_json(request.headers.get("content-type")):
        return body_bytes
    try:
        return await request.json()
    except json.JSONDecodeError as exc:
        raise RequestValidationError(
            [
                {
                    "type": "json_invalid",
                    "loc": ("body", exc.pos),
                    "msg": "JSON decode error",
                    "input": {},
                    "ctx": {"error": exc.msg},
                }
            ],
            body=exc.doc,
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail="There was an error parsing the body",
        ) from exc


def _validate_body(payload: Any, validator: BodyValidator) -> Any:
    try:
        if isinstance(validator, TypeAdapter):
            return validator.validate_python(payload)
        return validator.model_validate(payload)
    except ValidationError as exc:
        errors = [
            {**error, "loc": ("body", *error.get("loc", ()))}
            for error in exc.errors()
        ]
        raise RequestValidationError(errors, body=payload) from exc


def teacher_json_body(validator: BodyValidator) -> BodyDependency:
    async def dependency(
        request: Request,
        _teacher: models.TeacherSession = Depends(require_teacher_session),
    ) -> Any:
        del _teacher
        return _validate_body(await _request_body_value(request), validator)

    dependency.__name__ = f"teacher_json_{getattr(validator, '__name__', 'object')}"
    return dependency


def json_body_openapi(validator: BodyValidator) -> dict[str, object]:
    schema = (
        validator.json_schema()
        if isinstance(validator, TypeAdapter)
        else validator.model_json_schema()
    )
    return {
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": schema}},
        }
    }


teacher_json_object_body = teacher_json_body(_JSON_OBJECT)
teacher_json_object_openapi = json_body_openapi(_JSON_OBJECT)
