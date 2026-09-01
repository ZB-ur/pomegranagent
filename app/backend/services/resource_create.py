"""Atomic child and duck creation with optional request idempotency."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models, schemas
from ..api_errors import APIError
from .avatar_media import validate_avatar_reference


_CHILD_OPERATION = "child_create"
_DUCK_OPERATION = "duck_create"
_Response = TypeVar("_Response", schemas.ChildOut, schemas.DuckOut)


def _canonical_hash(operation: str, payload: BaseModel) -> str:
    canonical = json.dumps(
        {
            "operation": operation,
            "payload": payload.model_dump(mode="json"),
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _idempotency_error(code: str, *, retryable: bool = False) -> APIError:
    messages = {
        "IDEMPOTENCY_CONFLICT": "请求 ID 与已有提交不一致",
        "REQUEST_FAILED": "该请求先前处理失败，请使用新的请求 ID 重试",
        "REQUEST_IN_PROGRESS": "请求正在处理中",
    }
    return APIError(409, code, messages[code], retryable=retryable)


def _load_replay(
    db: Session,
    *,
    request_id: str,
    operation: str,
    payload_hash: str,
    response_type: type[_Response],
    record: models.RosterRequest | None = None,
) -> _Response:
    if record is None:
        record = db.scalar(
            select(models.RosterRequest)
            .where(models.RosterRequest.request_id == request_id)
            .execution_options(populate_existing=True)
        )
    if record is None:
        db.rollback()
        raise APIError(
            500,
            "INTERNAL_ERROR",
            "服务暂时不可用，请稍后重试",
            retryable=True,
        )
    if record.operation != operation or record.payload_hash != payload_hash:
        db.rollback()
        raise _idempotency_error("IDEMPOTENCY_CONFLICT")
    if record.status == "processing":
        db.rollback()
        raise _idempotency_error("REQUEST_IN_PROGRESS", retryable=True)
    if record.status == "failed":
        db.rollback()
        raise _idempotency_error("REQUEST_FAILED")
    if record.status != "succeeded":
        db.rollback()
        raise APIError(
            500,
            "INTERNAL_ERROR",
            "服务暂时不可用，请稍后重试",
            retryable=True,
        )
    if not record.response_json:
        db.rollback()
        raise APIError(
            500,
            "INTERNAL_ERROR",
            "服务暂时不可用，请稍后重试",
            retryable=True,
        )
    try:
        replay = response_type.model_validate_json(record.response_json)
    except Exception as error:
        db.rollback()
        raise APIError(
            500,
            "INTERNAL_ERROR",
            "服务暂时不可用，请稍后重试",
            retryable=True,
        ) from error
    db.rollback()
    return replay


def _claim_request(
    db: Session,
    *,
    request_id: str,
    operation: str,
    payload_hash: str,
    now: datetime,
    response_type: type[_Response],
) -> tuple[models.RosterRequest | None, _Response | None]:
    record = models.RosterRequest(
        request_id=request_id,
        operation=operation,
        payload_hash=payload_hash,
        status="processing",
        created_at=now,
        updated_at=now,
    )
    db.add(record)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(models.RosterRequest)
            .where(models.RosterRequest.request_id == request_id)
            .execution_options(populate_existing=True)
        )
        return None, _load_replay(
            db,
            request_id=request_id,
            operation=operation,
            payload_hash=payload_hash,
            response_type=response_type,
            record=existing,
        )
    return record, None


def _create_resource(
    db: Session,
    payload: BaseModel,
    *,
    request_id: str | None,
    media_root: Path,
    now: datetime,
    operation: str,
    model_type: type[models.Child] | type[models.Duck],
    response_type: type[_Response],
) -> _Response:
    record: models.RosterRequest | None = None
    if request_id is not None:
        payload_hash = _canonical_hash(operation, payload)
        record, replay = _claim_request(
            db,
            request_id=request_id,
            operation=operation,
            payload_hash=payload_hash,
            now=now,
            response_type=response_type,
        )
        if replay is not None:
            return replay

    try:
        avatar = getattr(payload, "avatar")
        validate_avatar_reference(db, avatar, media_root=media_root)
        resource = model_type(
            **payload.model_dump(),
            active=True,
            deactivated_at=None,
        )
        db.add(resource)
        db.flush()
        response = response_type.model_validate(resource)
        if record is not None:
            record.response_json = response.model_dump_json()
            record.status = "succeeded"
            record.updated_at = now
            db.flush()
        db.commit()
        return response
    except Exception:
        db.rollback()
        raise


def create_child(
    db: Session,
    payload: schemas.ChildMutationRequest,
    *,
    request_id: str | None,
    media_root: Path,
    now: datetime,
) -> schemas.ChildOut:
    return _create_resource(
        db,
        payload,
        request_id=request_id,
        media_root=media_root,
        now=now,
        operation=_CHILD_OPERATION,
        model_type=models.Child,
        response_type=schemas.ChildOut,
    )


def create_duck(
    db: Session,
    payload: schemas.DuckMutationRequest,
    *,
    request_id: str | None,
    media_root: Path,
    now: datetime,
) -> schemas.DuckOut:
    return _create_resource(
        db,
        payload,
        request_id=request_id,
        media_root=media_root,
        now=now,
        operation=_DUCK_OPERATION,
        model_type=models.Duck,
        response_type=schemas.DuckOut,
    )
