"""Public daily roster read and teacher-only idempotent roster routes."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, schemas
from ..api_errors import APIError
from ..auth import require_teacher_session
from ..business_time import BusinessClock
from ..database import SETTINGS, get_db
from ..services.roster import (
    generate_roster,
    get_today_roster,
    set_daily_roster,
    set_monthly_roster,
)


router = APIRouter()
BUSINESS_CLOCK = BusinessClock(SETTINGS.business_timezone)


@router.get("/api/roster/today", response_model=list[schemas.RosterTodayChild])
def today_roster(db: Session = Depends(get_db)) -> list[schemas.RosterTodayChild]:
    return get_today_roster(db, today=BUSINESS_CLOCK.business_today())


@router.get("/api/roster", response_model=list[schemas.RosterListItem])
def list_roster(
    request: Request,
    db: Session = Depends(get_db),
    _teacher: models.TeacherSession = Depends(require_teacher_session),
) -> list[schemas.RosterListItem]:
    if request.query_params:
        raise APIError(
            422,
            "VALIDATION_ERROR",
            "请求字段校验失败",
            {"query": ["排班列表不接受查询参数"]},
        )
    query = select(models.DutyRoster)
    rows = db.scalars(query.order_by(models.DutyRoster.date, models.DutyRoster.id)).all()
    return [
        schemas.RosterListItem(
            id=row.id,
            cycle=row.cycle.strip(),
            date=row.date,
            child_id=row.child_id,
        )
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
    return generate_roster(db, payload, now=BUSINESS_CLOCK.utc_now())


@router.post("/api/roster/month", response_model=schemas.MonthlyRosterResponse)
def monthly_roster(
    payload: schemas.MonthlyRosterRequest,
    db: Session = Depends(get_db),
    _teacher: models.TeacherSession = Depends(require_teacher_session),
) -> schemas.MonthlyRosterResponse:
    return set_monthly_roster(db, payload, now=BUSINESS_CLOCK.utc_now())


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
        now=BUSINESS_CLOCK.utc_now(),
    )
