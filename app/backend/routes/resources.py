"""Teacher-only child and duck administration with reversible state routes."""
from __future__ import annotations

from datetime import timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from .. import models, schemas
from ..api_errors import APIError
from ..auth import require_teacher_session
from ..business_time import BusinessClock
from ..database import SETTINGS, get_db
from ..services.deactivation import (
    list_teacher_children,
    list_teacher_ducks,
    set_child_active,
    set_duck_active,
)
from ..services.avatar_media import validate_avatar_reference
from ..services.resource_create import create_child as create_child_resource
from ..services.resource_create import create_duck as create_duck_resource
from .teacher_json import json_body_openapi, teacher_json_body


router = APIRouter()
BUSINESS_CLOCK = BusinessClock(SETTINGS.business_timezone)
CHILD_MUTATION_BODY = teacher_json_body(schemas.ChildMutationRequest)
DUCK_MUTATION_BODY = teacher_json_body(schemas.DuckMutationRequest)


def _incoming_request_id(request: Request) -> str | None:
    values = [
        value
        for name, value in request.scope.get("headers", [])
        if name.lower() == b"x-request-id"
    ]
    if not values:
        return None
    try:
        raw = values[0].decode("ascii")
        parsed = UUID(raw)
    except (AttributeError, UnicodeDecodeError, ValueError):
        parsed = None
        raw = ""
    if len(values) != 1 or parsed is None or parsed.version != 4 or str(parsed) != raw:
        raise APIError(
            422,
            "VALIDATION_ERROR",
            "请求字段校验失败",
            {"header.x-request-id": ["X-Request-ID 必须是单个 canonical UUIDv4"]},
        )
    return raw


@router.get("/api/children", response_model=list[schemas.TeacherChildOut])
def list_children(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    _teacher: models.TeacherSession = Depends(require_teacher_session),
) -> list[schemas.TeacherChildOut]:
    return list_teacher_children(
        db,
        include_inactive=include_inactive,
        today=BUSINESS_CLOCK.business_today(),
    )


@router.post(
    "/api/children",
    response_model=schemas.ChildOut,
    openapi_extra=json_body_openapi(schemas.ChildMutationRequest),
)
def create_child(
    request: Request,
    _teacher: models.TeacherSession = Depends(require_teacher_session),
    payload: schemas.ChildMutationRequest = Depends(CHILD_MUTATION_BODY),
    db: Session = Depends(get_db),
) -> schemas.ChildOut:
    return create_child_resource(
        db,
        payload,
        request_id=_incoming_request_id(request),
        media_root=SETTINGS.media_root,
        now=BUSINESS_CLOCK.utc_now(),
    )


@router.put(
    "/api/children/{child_id}",
    response_model=schemas.ChildOut,
    openapi_extra=json_body_openapi(schemas.ChildMutationRequest),
)
def update_child(
    child_id: int,
    _teacher: models.TeacherSession = Depends(require_teacher_session),
    payload: schemas.ChildMutationRequest = Depends(CHILD_MUTATION_BODY),
    db: Session = Depends(get_db),
) -> models.Child:
    validate_avatar_reference(db, payload.avatar, media_root=SETTINGS.media_root)
    child = db.get(models.Child, child_id)
    if child is None:
        raise APIError(404, "CHILD_NOT_FOUND", "幼儿不存在")
    for field, value in payload.model_dump().items():
        setattr(child, field, value)
    db.commit()
    db.refresh(child)
    return child


@router.post(
    "/api/children/{child_id}/deactivate",
    response_model=schemas.DeactivationResponse,
)
def deactivate_child(
    child_id: int,
    db: Session = Depends(get_db),
    _teacher: models.TeacherSession = Depends(require_teacher_session),
) -> schemas.DeactivationResponse:
    business_now = BUSINESS_CLOCK.business_now()
    return set_child_active(
        db,
        child_id=child_id,
        active=False,
        today=business_now.date(),
        now=business_now.astimezone(timezone.utc),
    )


@router.post(
    "/api/children/{child_id}/reactivate",
    response_model=schemas.DeactivationResponse,
)
def reactivate_child(
    child_id: int,
    db: Session = Depends(get_db),
    _teacher: models.TeacherSession = Depends(require_teacher_session),
) -> schemas.DeactivationResponse:
    business_now = BUSINESS_CLOCK.business_now()
    return set_child_active(
        db,
        child_id=child_id,
        active=True,
        today=business_now.date(),
        now=business_now.astimezone(timezone.utc),
    )


@router.delete("/api/children/{child_id}")
def delete_child(
    child_id: int,
    _teacher: models.TeacherSession = Depends(require_teacher_session),
) -> None:
    del child_id
    raise APIError(410, "HARD_DELETE_DISABLED", "已禁用永久删除")


@router.get("/api/ducks", response_model=list[schemas.TeacherDuckOut])
def list_ducks(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    _teacher: models.TeacherSession = Depends(require_teacher_session),
) -> list[schemas.TeacherDuckOut]:
    return list_teacher_ducks(db, include_inactive=include_inactive)


@router.post(
    "/api/ducks",
    response_model=schemas.DuckOut,
    openapi_extra=json_body_openapi(schemas.DuckMutationRequest),
)
def create_duck(
    request: Request,
    _teacher: models.TeacherSession = Depends(require_teacher_session),
    payload: schemas.DuckMutationRequest = Depends(DUCK_MUTATION_BODY),
    db: Session = Depends(get_db),
) -> schemas.DuckOut:
    return create_duck_resource(
        db,
        payload,
        request_id=_incoming_request_id(request),
        media_root=SETTINGS.media_root,
        now=BUSINESS_CLOCK.utc_now(),
    )


@router.put(
    "/api/ducks/{duck_id}",
    response_model=schemas.DuckOut,
    openapi_extra=json_body_openapi(schemas.DuckMutationRequest),
)
def update_duck(
    duck_id: int,
    _teacher: models.TeacherSession = Depends(require_teacher_session),
    payload: schemas.DuckMutationRequest = Depends(DUCK_MUTATION_BODY),
    db: Session = Depends(get_db),
) -> models.Duck:
    validate_avatar_reference(db, payload.avatar, media_root=SETTINGS.media_root)
    duck = db.get(models.Duck, duck_id)
    if duck is None:
        raise APIError(404, "DUCK_NOT_FOUND", "小鸭不存在")
    for field, value in payload.model_dump().items():
        setattr(duck, field, value)
    db.commit()
    db.refresh(duck)
    return duck


@router.post(
    "/api/ducks/{duck_id}/deactivate",
    response_model=schemas.DeactivationResponse,
)
def deactivate_duck(
    duck_id: int,
    db: Session = Depends(get_db),
    _teacher: models.TeacherSession = Depends(require_teacher_session),
) -> schemas.DeactivationResponse:
    return set_duck_active(
        db,
        duck_id=duck_id,
        active=False,
        now=BUSINESS_CLOCK.utc_now(),
    )


@router.post(
    "/api/ducks/{duck_id}/reactivate",
    response_model=schemas.DeactivationResponse,
)
def reactivate_duck(
    duck_id: int,
    db: Session = Depends(get_db),
    _teacher: models.TeacherSession = Depends(require_teacher_session),
) -> schemas.DeactivationResponse:
    return set_duck_active(
        db,
        duck_id=duck_id,
        active=True,
        now=BUSINESS_CLOCK.utc_now(),
    )


@router.delete("/api/ducks/{duck_id}")
def delete_duck(
    duck_id: int,
    _teacher: models.TeacherSession = Depends(require_teacher_session),
) -> None:
    del duck_id
    raise APIError(410, "HARD_DELETE_DISABLED", "已禁用永久删除")
