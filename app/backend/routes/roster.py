"""Public daily roster read and teacher-only idempotent roster routes."""
from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, schemas
from ..api_errors import APIError
from ..auth import require_teacher_session
from ..database import get_db
from ..services.roster import generate_roster, get_today_roster, set_daily_roster


router = APIRouter()


@router.get("/api/roster/today", response_model=list[schemas.RosterTodayChild])
def today_roster(db: Session = Depends(get_db)) -> list[schemas.RosterTodayChild]:
    return get_today_roster(db, today=date.today())


@router.get("/api/roster")
def list_roster(
    cycle: str | None = None,
    db: Session = Depends(get_db),
    _teacher: models.TeacherSession = Depends(require_teacher_session),
):
    query = select(models.DutyRoster)
    if cycle is not None:
        query = query.where(models.DutyRoster.cycle == cycle)
    rows = db.scalars(query.order_by(models.DutyRoster.date, models.DutyRoster.id)).all()
    return [
        {"id": row.id, "cycle": row.cycle, "date": row.date, "child_id": row.child_id}
        for row in rows
    ]


@router.post("/api/roster")
def legacy_roster_tombstone(
    _teacher: models.TeacherSession = Depends(require_teacher_session),
):
    raise APIError(410, "LEGACY_ENDPOINT_REMOVED", "旧排班接口已下线")


@router.post("/api/roster/auto", response_model=schemas.AutoRosterResponse)
def auto_roster(
    payload: schemas.AutoRosterRequest,
    db: Session = Depends(get_db),
    _teacher: models.TeacherSession = Depends(require_teacher_session),
) -> schemas.AutoRosterResponse:
    return generate_roster(db, payload, now=datetime.now(timezone.utc))


@router.put("/api/roster/{roster_date}", response_model=schemas.DailyRosterResponse)
def put_daily_roster(
    roster_date: date,
    payload: schemas.DailyRosterRequest,
    db: Session = Depends(get_db),
    _teacher: models.TeacherSession = Depends(require_teacher_session),
) -> schemas.DailyRosterResponse:
    return set_daily_roster(
        db,
        payload,
        roster_date=roster_date,
        now=datetime.now(timezone.utc),
    )
