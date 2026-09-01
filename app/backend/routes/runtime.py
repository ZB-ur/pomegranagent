"""Public, non-secret runtime calendar context."""
from __future__ import annotations

from fastapi import APIRouter, Request

from .. import schemas
from ..api_errors import APIError
from ..business_time import BusinessClock
from ..database import SETTINGS


router = APIRouter()
BUSINESS_CLOCK = BusinessClock(SETTINGS.business_timezone)


@router.get("/api/runtime/context", response_model=schemas.RuntimeContextResponse)
def runtime_context(request: Request) -> schemas.RuntimeContextResponse:
    if request.scope.get("query_string", b""):
        raise APIError(
            422,
            "VALIDATION_ERROR",
            "请求字段校验失败",
            {"query": ["运行时上下文不接受查询参数"]},
        )
    business_date = BUSINESS_CLOCK.business_today()
    week_start, week_end_exclusive = BUSINESS_CLOCK.week_window(
        anchor=business_date,
    )
    return schemas.RuntimeContextResponse(
        timezone=BUSINESS_CLOCK.timezone_name,
        business_date=business_date,
        week_start=week_start,
        week_end_exclusive=week_end_exclusive,
    )
