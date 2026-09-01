"""Strict weekly teacher metrics and bounded-query integrity contracts."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
import importlib

import pytest
from fastapi.routing import APIRoute
from sqlalchemy import event, select

from app.backend import models, schemas
from app.backend.api_errors import APIError
from app.backend.auth import require_teacher_session
from app.backend.business_time import BusinessClock
from app.backend.database import engine
from app.backend.main import app


WEEK_START = date(2026, 8, 31)
WEEK_END = date(2026, 9, 7)
ENDED_AT = datetime(2026, 9, 2, 8, 30, tzinfo=UTC)


def _service():
    return importlib.import_module("app.backend.services.reports")


def _route_module():
    return importlib.import_module("app.backend.routes.reports")


def _unlock(client) -> None:
    response = client.post("/api/auth/setup", json={"pin": "1234"})
    assert response.status_code == 200


def _error(response, *, status: int, code: str) -> dict:
    assert response.status_code == status
    body = response.json()
    assert body["error"]["code"] == code
    return body["error"]


def _child(db_session, name: str, *, active: bool = True) -> models.Child:
    child = models.Child(name=name, active=active)
    db_session.add(child)
    db_session.flush()
    return child


def _ended(
    db_session,
    *,
    child: models.Child,
    conversation_date: str,
    job_status: str | None = "succeeded",
    assessment_status: str | None = None,
) -> tuple[models.Conversation, models.AnalysisJob | None, models.Assessment | None]:
    conversation = models.Conversation(
        child_id=child.id,
        date=conversation_date,
        started_at=ENDED_AT - timedelta(minutes=5),
        ended_at=ENDED_AT,
        status="ended",
        end_reason="complete",
    )
    db_session.add(conversation)
    db_session.flush()
    message = models.Message(
        conversation_id=conversation.id,
        role="child",
        text="冻结周报消息",
        created_at=ENDED_AT - timedelta(minutes=1),
    )
    db_session.add(message)
    db_session.flush()
    conversation.frozen_last_message_id = message.id
    job = None
    if job_status is not None:
        job = models.AnalysisJob(
            conversation_id=conversation.id,
            frozen_last_message_id=message.id,
            status=job_status,
            available_at=ENDED_AT,
            created_at=ENDED_AT,
            updated_at=ENDED_AT,
        )
        db_session.add(job)
    assessment = None
    if assessment_status is not None:
        assessment = models.Assessment(
            conversation_id=conversation.id,
            child_id=child.id,
            status=assessment_status,
            overall=4.0,
        )
        db_session.add(assessment)
    db_session.flush()
    return conversation, job, assessment


def test_weekly_service_uses_conversation_calendar_window_and_global_review_backlog(
    db_session,
):
    """Catches ended_at filtering, active-child filtering, non-distinct children, or a weekly backlog."""
    historical = _child(db_session, "历史幼儿", active=False)
    current = _child(db_session, "当前幼儿")
    third = _child(db_session, "第三幼儿")
    _ended(
        db_session,
        child=historical,
        conversation_date="2026-08-31",
        job_status="succeeded",
        assessment_status="confirmed",
    )
    _ended(
        db_session,
        child=historical,
        conversation_date="2026-09-02",
        job_status="failed",
        assessment_status="pending",
    )
    _ended(
        db_session,
        child=current,
        conversation_date="2026-09-06",
        job_status="succeeded",
        assessment_status="pending",
    )
    _ended(
        db_session,
        child=third,
        conversation_date="2026-09-03",
        job_status="processing",
        assessment_status="draft",
    )
    _ended(
        db_session,
        child=current,
        conversation_date="2026-09-04",
        job_status="succeeded",
        assessment_status=None,
    )
    _ended(
        db_session,
        child=third,
        conversation_date="2026-08-30",
        job_status="succeeded",
        assessment_status="draft",
    )
    _ended(
        db_session,
        child=third,
        conversation_date="2026-09-07",
        job_status="succeeded",
        assessment_status="confirmed",
    )
    db_session.commit()

    result = _service().weekly_report(
        db_session,
        week_start=WEEK_START,
        week_end_exclusive=WEEK_END,
    )

    assert result.model_dump() == {
        "timezone": "Asia/Shanghai",
        "week_start": WEEK_START,
        "week_end_exclusive": WEEK_END,
        "completed_conversations": 5,
        "participating_children": 3,
        "confirmed_reviews": 1,
        "failed_analyses": 1,
        "pending_reviews_total": 2,
    }


def test_weekly_service_returns_the_exact_zero_shape(db_session):
    """Catches nullable aggregate leakage or omission of the cumulative fifth metric."""
    result = _service().weekly_report(
        db_session,
        week_start=WEEK_START,
        week_end_exclusive=WEEK_END,
    )

    assert result == schemas.WeeklyReportResponse(
        timezone="Asia/Shanghai",
        week_start=WEEK_START,
        week_end_exclusive=WEEK_END,
        completed_conversations=0,
        participating_children=0,
        confirmed_reviews=0,
        failed_analyses=0,
        pending_reviews_total=0,
    )


@pytest.mark.parametrize(
    "corruption",
    [
        "conversation_status",
        "conversation_end_reason",
        "conversation_pending_end_reason",
        "ended_without_timestamp",
        "ended_without_boundary",
        "active_with_ended_boundary",
        "job_status",
        "job_boundary",
        "job_for_active_conversation",
        "assessment_status",
        "assessment_child",
        "confirmed_without_succeeded",
    ],
)
def test_weekly_service_fails_the_whole_response_for_global_integrity_corruption(
    db_session,
    corruption,
):
    """Catches integrity checks scoped only to the requested week or partial aggregate responses."""
    selected_child = _child(db_session, "周内有效幼儿")
    _ended(
        db_session,
        child=selected_child,
        conversation_date="2026-09-02",
        job_status="succeeded",
        assessment_status="pending",
    )
    corrupt_child = _child(db_session, "周外损坏幼儿")
    conversation, job, assessment = _ended(
        db_session,
        child=corrupt_child,
        conversation_date="2025-01-01",
        job_status="succeeded",
        assessment_status="confirmed",
    )
    assert job is not None and assessment is not None
    if corruption == "conversation_status":
        conversation.status = "mystery"
    elif corruption == "conversation_end_reason":
        conversation.end_reason = "mystery"
    elif corruption == "conversation_pending_end_reason":
        conversation.pending_end_reason = "mystery"
    elif corruption == "ended_without_timestamp":
        conversation.ended_at = None
    elif corruption == "ended_without_boundary":
        conversation.frozen_last_message_id = None
    elif corruption == "active_with_ended_boundary":
        conversation.status = "active"
        conversation.end_reason = None
    elif corruption == "job_status":
        job.status = "mystery"
    elif corruption == "job_boundary":
        extra = models.Message(
            conversation_id=conversation.id,
            role="diary",
            text="不匹配边界",
        )
        db_session.add(extra)
        db_session.flush()
        job.frozen_last_message_id = extra.id
    elif corruption == "job_for_active_conversation":
        conversation.status = "active"
        conversation.ended_at = None
        conversation.end_reason = None
        conversation.frozen_last_message_id = None
    elif corruption == "assessment_status":
        assessment.status = "mystery"
    elif corruption == "assessment_child":
        assessment.child_id = selected_child.id
    else:
        job.status = "processing"
    db_session.commit()

    transient_name = f"must-rollback-{corruption}"
    db_session.add(models.Child(name=transient_name))
    with pytest.raises(APIError) as raised:
        _service().weekly_report(
            db_session,
            week_start=WEEK_START,
            week_end_exclusive=WEEK_END,
        )

    assert raised.value.status_code == 500
    assert raised.value.code == "INTERNAL_ERROR"
    assert raised.value.message == "服务暂时不可用，请稍后重试"
    assert raised.value.retryable is True
    assert db_session.scalar(
        select(models.Child.id).where(models.Child.name == transient_name)
    ) is None


@pytest.mark.parametrize("row_count", [1, 100])
def test_weekly_service_uses_the_same_two_sql_statements_for_one_or_one_hundred_rows(
    db_session,
    row_count,
):
    """Catches per-row validation, N+1 joins, or aggregate query multiplication."""
    child = _child(db_session, f"查询上限幼儿-{row_count}")
    for index in range(row_count):
        _ended(
            db_session,
            child=child,
            conversation_date=f"2026-09-{index % 6 + 1:02d}",
            job_status="failed",
        )
    db_session.commit()
    statements: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        if not statement.lstrip().upper().startswith(("BEGIN", "ROLLBACK")):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        result = _service().weekly_report(
            db_session,
            week_start=WEEK_START,
            week_end_exclusive=WEEK_END,
        )
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    assert len(statements) == 2
    assert result.completed_conversations == row_count
    assert result.participating_children == 1
    assert result.failed_analyses == row_count


def test_weekly_route_authenticates_before_reading_even_an_invalid_raw_query(client):
    """Catches query validation or report reads before the teacher session boundary."""
    error = _error(
        client.get("/api/reports/weekly?unknown=secret&week_start="),
        status=401,
        code="TEACHER_AUTH_REQUIRED",
    )
    assert error["field_errors"] == {}


@pytest.mark.parametrize(
    "raw_query",
    [
        "unknown=2026-08-31",
        "week_start=2026-08-31&week_start=2026-08-31",
        "week_start=",
        "=2026-08-31",
        "week_start",
        "week%5Fstart=2026-08-31",
        "week_start=2026%2D08%2D31",
        "week_start=%FF",
        "week_start=2026-02-30",
        "week_start=2026-8-31",
        "week_start=2026-09-01",
    ],
)
def test_weekly_route_rejects_noncanonical_or_non_monday_raw_query_before_any_sql(
    client,
    raw_query,
):
    """Catches permissive Starlette decoding, duplicate collapse, or service work before validation."""
    app.dependency_overrides[require_teacher_session] = lambda: object()
    statements: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        response = client.get(f"/api/reports/weekly?{raw_query}")
    finally:
        event.remove(engine, "before_cursor_execute", capture)
        app.dependency_overrides.pop(require_teacher_session, None)

    error = _error(response, status=422, code="VALIDATION_ERROR")
    assert error["field_errors"]
    assert statements == []


def test_weekly_route_without_query_samples_the_business_clock_once(client, monkeypatch):
    """Catches host-calendar reads or separate now/week samples in the default route."""
    calls = 0

    def now() -> datetime:
        nonlocal calls
        calls += 1
        if calls > 1:
            raise AssertionError("weekly route sampled now more than once")
        return datetime(2026, 9, 2, 7, 0, tzinfo=UTC)

    module = _route_module()
    monkeypatch.setattr(module, "BUSINESS_CLOCK", BusinessClock("Asia/Shanghai", now=now))
    _unlock(client)

    response = client.get("/api/reports/weekly")

    assert response.status_code == 200
    assert response.json() == {
        "timezone": "Asia/Shanghai",
        "week_start": "2026-08-31",
        "week_end_exclusive": "2026-09-07",
        "completed_conversations": 0,
        "participating_children": 0,
        "confirmed_reviews": 0,
        "failed_analyses": 0,
        "pending_reviews_total": 0,
    }
    assert calls == 1


def test_weekly_route_explicit_monday_never_reads_the_now_provider(client, monkeypatch):
    """Catches explicit anchors accidentally routed through business_today()."""
    def unexpected_now() -> datetime:
        raise AssertionError("explicit week_start must not read now")

    module = _route_module()
    monkeypatch.setattr(
        module,
        "BUSINESS_CLOCK",
        BusinessClock("Asia/Shanghai", now=unexpected_now),
    )
    _unlock(client)

    response = client.get("/api/reports/weekly?week_start=2026-08-31")

    assert response.status_code == 200
    assert response.json()["week_start"] == "2026-08-31"
    assert response.json()["week_end_exclusive"] == "2026-09-07"


def test_weekly_api_route_is_registered_before_the_static_frontend_mount():
    """Catches a valid report handler shadowed by the catch-all static mount."""
    weekly_container_indexes = [
        index
        for index, route in enumerate(app.router.routes)
        if any(
            isinstance(child, APIRoute) and child.path == "/api/reports/weekly"
            for child in (
                route.original_router.routes
                if hasattr(route, "original_router")
                else [route]
            )
        )
    ]
    mount_index = next(
        index
        for index, route in enumerate(app.router.routes)
        if route.__class__.__name__ == "Mount"
    )
    assert len(weekly_container_indexes) == 1
    assert weekly_container_indexes[0] < mount_index
