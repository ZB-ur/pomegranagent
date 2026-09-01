"""Teacher-only child and duck administration with reversible state routes."""
from __future__ import annotations

from datetime import timezone

from fastapi import APIRouter, Depends
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


router = APIRouter()
BUSINESS_CLOCK = BusinessClock(SETTINGS.business_timezone)


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


@router.post("/api/children", response_model=schemas.ChildOut)
def create_child(
    payload: schemas.ChildMutationRequest,
    db: Session = Depends(get_db),
    _teacher: models.TeacherSession = Depends(require_teacher_session),
) -> models.Child:
    validate_avatar_reference(db, payload.avatar, media_root=SETTINGS.media_root)
    child = models.Child(**payload.model_dump(), active=True, deactivated_at=None)
    db.add(child)
    db.commit()
    db.refresh(child)
    return child


@router.put("/api/children/{child_id}", response_model=schemas.ChildOut)
def update_child(
    child_id: int,
    payload: schemas.ChildMutationRequest,
    db: Session = Depends(get_db),
    _teacher: models.TeacherSession = Depends(require_teacher_session),
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


@router.post("/api/ducks", response_model=schemas.DuckOut)
def create_duck(
    payload: schemas.DuckMutationRequest,
    db: Session = Depends(get_db),
    _teacher: models.TeacherSession = Depends(require_teacher_session),
) -> models.Duck:
    validate_avatar_reference(db, payload.avatar, media_root=SETTINGS.media_root)
    duck = models.Duck(**payload.model_dump(), active=True, deactivated_at=None)
    db.add(duck)
    db.commit()
    db.refresh(duck)
    return duck


@router.put("/api/ducks/{duck_id}", response_model=schemas.DuckOut)
def update_duck(
    duck_id: int,
    payload: schemas.DuckMutationRequest,
    db: Session = Depends(get_db),
    _teacher: models.TeacherSession = Depends(require_teacher_session),
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
