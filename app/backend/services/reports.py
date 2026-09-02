"""Bounded weekly teacher metrics with global integrity validation."""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import and_, false, func, literal, not_, or_, select
from sqlalchemy.orm import Session

from .. import models, schemas
from ..api_errors import APIError
from ..database import SETTINGS


_CONVERSATION_STATUSES = ("active", "ended")
_END_REASONS = ("max_rounds", "complete", "manual")
_PENDING_END_REASONS = ("max_rounds", "complete")
_JOB_STATUSES = ("pending", "processing", "succeeded", "failed")
_ASSESSMENT_STATUSES = ("pending", "draft", "confirmed")


def _internal_error() -> APIError:
    return APIError(
        500,
        "INTERNAL_ERROR",
        "服务暂时不可用，请稍后重试",
        retryable=True,
    )


def _fail(db: Session) -> None:
    db.rollback()
    raise _internal_error()


def _invalid_when_false_or_null(valid_expression):
    return not_(func.coalesce(valid_expression, false()))


def _conversation_is_valid():
    frozen_message_exists = (
        select(literal(1))
        .select_from(models.Message)
        .where(
            models.Message.id == models.Conversation.frozen_last_message_id,
            models.Message.conversation_id == models.Conversation.id,
        )
        .correlate(models.Conversation)
        .exists()
    )
    canonical_date = and_(
        func.length(models.Conversation.date) == 10,
        func.substr(models.Conversation.date, 1, 4) != "0000",
        func.date(models.Conversation.date, "+0 days")
        == models.Conversation.date,
    )
    pending_end_reason_is_valid = or_(
        models.Conversation.pending_end_reason.is_(None),
        models.Conversation.pending_end_reason.in_(_PENDING_END_REASONS),
    )
    active_is_valid = and_(
        models.Conversation.status == "active",
        models.Conversation.ended_at.is_(None),
        models.Conversation.end_reason.is_(None),
        models.Conversation.frozen_last_message_id.is_(None),
    )
    ended_is_valid = and_(
        models.Conversation.status == "ended",
        models.Conversation.ended_at.is_not(None),
        models.Conversation.end_reason.in_(_END_REASONS),
        models.Conversation.frozen_last_message_id.is_not(None),
        frozen_message_exists,
    )
    return and_(
        models.Conversation.status.in_(_CONVERSATION_STATUSES),
        canonical_date,
        pending_end_reason_is_valid,
        or_(active_is_valid, ended_is_valid),
    )


def _integrity_statement():
    invalid_conversation_exists = (
        select(literal(1))
        .select_from(models.Conversation)
        .where(_invalid_when_false_or_null(_conversation_is_valid()))
        .exists()
    )

    job_conversation = models.Conversation.__table__.alias("job_conversation")
    job_boundary_message = models.Message.__table__.alias("job_boundary_message")
    job_is_valid = and_(
        models.AnalysisJob.status.in_(_JOB_STATUSES),
        job_conversation.c.id.is_not(None),
        job_conversation.c.status == "ended",
        job_conversation.c.ended_at.is_not(None),
        job_conversation.c.frozen_last_message_id.is_not(None),
        models.AnalysisJob.frozen_last_message_id
        == job_conversation.c.frozen_last_message_id,
        job_boundary_message.c.id.is_not(None),
    )
    invalid_job_exists = (
        select(literal(1))
        .select_from(models.AnalysisJob)
        .outerjoin(
            job_conversation,
            job_conversation.c.id == models.AnalysisJob.conversation_id,
        )
        .outerjoin(
            job_boundary_message,
            and_(
                job_boundary_message.c.id
                == models.AnalysisJob.frozen_last_message_id,
                job_boundary_message.c.conversation_id
                == models.AnalysisJob.conversation_id,
            ),
        )
        .where(_invalid_when_false_or_null(job_is_valid))
        .exists()
    )

    assessment_conversation = models.Conversation.__table__.alias(
        "assessment_conversation"
    )
    assessment_job = models.AnalysisJob.__table__.alias("assessment_job")
    assessment_is_valid = and_(
        models.Assessment.status.in_(_ASSESSMENT_STATUSES),
        assessment_conversation.c.id.is_not(None),
        assessment_conversation.c.status == "ended",
        assessment_conversation.c.ended_at.is_not(None),
        assessment_conversation.c.frozen_last_message_id.is_not(None),
        models.Assessment.child_id == assessment_conversation.c.child_id,
        assessment_job.c.id.is_not(None),
        assessment_job.c.frozen_last_message_id
        == assessment_conversation.c.frozen_last_message_id,
        or_(
            models.Assessment.status != "confirmed",
            assessment_job.c.status == "succeeded",
        ),
    )
    invalid_assessment_exists = (
        select(literal(1))
        .select_from(models.Assessment)
        .outerjoin(
            assessment_conversation,
            assessment_conversation.c.id == models.Assessment.conversation_id,
        )
        .outerjoin(
            assessment_job,
            assessment_job.c.conversation_id
            == models.Assessment.conversation_id,
        )
        .where(_invalid_when_false_or_null(assessment_is_valid))
        .exists()
    )

    return select(
        or_(
            invalid_conversation_exists,
            invalid_job_exists,
            invalid_assessment_exists,
        )
    )


def _weekly_base(week_start: date, week_end_exclusive: date):
    return (
        models.Conversation.status == "ended",
        models.Conversation.ended_at.is_not(None),
        models.Conversation.frozen_last_message_id.is_not(None),
        models.Conversation.date >= week_start.isoformat(),
        models.Conversation.date < week_end_exclusive.isoformat(),
    )


def _window_is_valid(week_start: object, week_end_exclusive: object) -> bool:
    if type(week_start) is not date or type(week_end_exclusive) is not date:
        return False
    if week_start.weekday() != 0:
        return False
    try:
        return week_start + timedelta(days=7) == week_end_exclusive
    except OverflowError:
        return False


def _aggregate_statement(week_start: date, week_end_exclusive: date):
    weekly = _weekly_base(week_start, week_end_exclusive)
    completed = (
        select(func.count(models.Conversation.id))
        .where(*weekly)
        .scalar_subquery()
    )
    participating = (
        select(func.count(func.distinct(models.Conversation.child_id)))
        .where(*weekly)
        .scalar_subquery()
    )
    confirmed = (
        select(func.count(models.Assessment.id))
        .select_from(models.Assessment)
        .join(
            models.Conversation,
            models.Conversation.id == models.Assessment.conversation_id,
        )
        .where(*weekly, models.Assessment.status == "confirmed")
        .scalar_subquery()
    )
    failed = (
        select(func.count(models.AnalysisJob.id))
        .select_from(models.AnalysisJob)
        .join(
            models.Conversation,
            models.Conversation.id == models.AnalysisJob.conversation_id,
        )
        .where(
            *weekly,
            models.AnalysisJob.status == "failed",
            models.AnalysisJob.frozen_last_message_id
            == models.Conversation.frozen_last_message_id,
        )
        .scalar_subquery()
    )
    pending_total = (
        select(func.count(models.Assessment.id))
        .select_from(models.Assessment)
        .join(
            models.Conversation,
            models.Conversation.id == models.Assessment.conversation_id,
        )
        .join(
            models.AnalysisJob,
            and_(
                models.AnalysisJob.conversation_id == models.Conversation.id,
                models.AnalysisJob.frozen_last_message_id
                == models.Conversation.frozen_last_message_id,
            ),
        )
        .where(
            models.Conversation.status == "ended",
            models.Conversation.ended_at.is_not(None),
            models.Conversation.frozen_last_message_id.is_not(None),
            models.AnalysisJob.status == "succeeded",
            models.Assessment.status.in_(("pending", "draft")),
        )
        .scalar_subquery()
    )
    return select(
        completed.label("completed_conversations"),
        participating.label("participating_children"),
        confirmed.label("confirmed_reviews"),
        failed.label("failed_analyses"),
        pending_total.label("pending_reviews_total"),
    )


def weekly_report(
    db: Session,
    week_start: date,
    week_end_exclusive: date,
) -> schemas.WeeklyReportResponse:
    """Return one validated week plus the cumulative review backlog in two SQL reads."""
    try:
        if not _window_is_valid(week_start, week_end_exclusive):
            _fail(db)
        if db.scalar(_integrity_statement()):
            _fail(db)
        row = db.execute(
            _aggregate_statement(week_start, week_end_exclusive)
        ).one()
        response = schemas.WeeklyReportResponse(
            timezone=SETTINGS.business_timezone,
            week_start=week_start,
            week_end_exclusive=week_end_exclusive,
            completed_conversations=int(row.completed_conversations or 0),
            participating_children=int(row.participating_children or 0),
            confirmed_reviews=int(row.confirmed_reviews or 0),
            failed_analyses=int(row.failed_analyses or 0),
            pending_reviews_total=int(row.pending_reviews_total or 0),
        )
        db.rollback()
        return response
    except APIError:
        raise
    except Exception:
        db.rollback()
        raise
