"""Teacher-only weekly report route with a strict raw query boundary."""
from __future__ import annotations

from datetime import date
import re

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from .. import models, schemas
from ..api_errors import APIError
from ..auth import require_teacher_session
from ..business_time import BusinessClock
from ..database import SETTINGS, get_db
from ..services.reports import weekly_report


router = APIRouter()
BUSINESS_CLOCK = BusinessClock(SETTINGS.business_timezone)
_EXPLICIT_WEEK = re.compile(rb"week_start=([0-9]{4}-[0-9]{2}-[0-9]{2})")


def _validation_error() -> APIError:
    return APIError(
        422,
        "VALIDATION_ERROR",
        "请求字段校验失败",
        {"query.week_start": ["必须是唯一、未编码的周一日期 YYYY-MM-DD"]},
    )


def _week_window(request: Request) -> tuple[date, date]:
    raw_query = request.scope.get("query_string", b"")
    if not raw_query:
        return BUSINESS_CLOCK.week_window()
    match = _EXPLICIT_WEEK.fullmatch(raw_query)
    if match is None:
        raise _validation_error()
    try:
        anchor = date.fromisoformat(match.group(1).decode("ascii"))
    except (UnicodeDecodeError, ValueError):
        raise _validation_error() from None
    if anchor.isoformat().encode("ascii") != match.group(1) or anchor.weekday() != 0:
        raise _validation_error()
    return BUSINESS_CLOCK.week_window(anchor=anchor)


@router.get("/api/reports/weekly", response_model=schemas.WeeklyReportResponse)
def get_weekly_report(
    request: Request,
    _teacher: models.TeacherSession = Depends(require_teacher_session),
    db: Session = Depends(get_db),
) -> schemas.WeeklyReportResponse:
    week_start, week_end_exclusive = _week_window(request)
    return weekly_report(db, week_start, week_end_exclusive)
