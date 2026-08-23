"""Teacher-only child and duck administration with reversible state routes."""
from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import models, schemas
from ..api_errors import APIError
from ..auth import require_teacher_session
from ..database import get_db
from ..services.deactivation import (
    list_teacher_children,
    list_teacher_ducks,
    set_child_active,
    set_duck_active,
)


router = APIRouter()


@router.get("/api/children", response_model=list[schemas.TeacherChildOut])
def list_children(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    _teacher: models.TeacherSession = Depends(require_teacher_session),
) -> list[schemas.TeacherChildOut]:
    return list_teacher_children(
        db,
        include_inactive=include_inactive,
        today=date.today(),
    )


@router.post("/api/children", response_model=schemas.ChildOut)
def create_child(
    payload: schemas.ChildCreate,
    db: Session = Depends(get_db),
    _teacher: models.TeacherSession = Depends(require_teacher_session),
) -> models.Child:
    child = models.Child(
        name=payload.name,
        nickname=payload.nickname,
        avatar=payload.avatar,
        active=True,
        deactivated_at=None,
    )
    db.add(child)
    db.commit()
    db.refresh(child)
    return child


@router.put("/api/children/{child_id}", response_model=schemas.ChildOut)
def update_child(
    child_id: int,
    payload: schemas.ChildCreate,
    db: Session = Depends(get_db),
    _teacher: models.TeacherSession = Depends(require_teacher_session),
) -> models.Child:
    child = db.get(models.Child, child_id)
    if child is None:
        raise APIError(404, "CHILD_NOT_FOUND", "幼儿不存在")
    child.name = payload.name
    child.nickname = payload.nickname
    child.avatar = payload.avatar
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
    return set_child_active(
        db,
        child_id=child_id,
        active=False,
        today=date.today(),
        now=datetime.now(timezone.utc),
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
    return set_child_active(
        db,
        child_id=child_id,
        active=True,
        today=date.today(),
        now=datetime.now(timezone.utc),
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
    payload: schemas.DuckCreate,
    db: Session = Depends(get_db),
    _teacher: models.TeacherSession = Depends(require_teacher_session),
) -> models.Duck:
    duck = models.Duck(**payload.model_dump(), active=True, deactivated_at=None)
    db.add(duck)
    db.commit()
    db.refresh(duck)
    return duck


@router.put("/api/ducks/{duck_id}", response_model=schemas.DuckOut)
def update_duck(
    duck_id: int,
    payload: schemas.DuckCreate,
    db: Session = Depends(get_db),
    _teacher: models.TeacherSession = Depends(require_teacher_session),
) -> models.Duck:
    duck = db.get(models.Duck, duck_id)
    if duck is None:
        raise APIError(404, "DUCK_NOT_FOUND", "小鸭不存在")
    duck.name = payload.name
    duck.avatar = payload.avatar
    duck.status = payload.status
    duck.note = payload.note
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
        now=datetime.now(timezone.utc),
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
        now=datetime.now(timezone.utc),
    )


@router.delete("/api/ducks/{duck_id}")
def delete_duck(
    duck_id: int,
    _teacher: models.TeacherSession = Depends(require_teacher_session),
) -> None:
    del duck_id
    raise APIError(410, "HARD_DELETE_DISABLED", "已禁用永久删除")
