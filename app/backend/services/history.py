"""Bounded teacher history reads with page-wide integrity validation."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import math

from pydantic import ValidationError
from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from .. import models, schemas
from ..api_errors import APIError


_INTERNAL_MESSAGE = "服务暂时不可用，请稍后重试"
_JOB_STATUSES = {"pending", "processing", "succeeded", "failed"}
_REVIEW_STATUSES = {"pending", "draft", "confirmed"}


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _fail(db: Session) -> None:
    db.rollback()
    raise APIError(500, "INTERNAL_ERROR", _INTERNAL_MESSAGE, retryable=True)


def _candidate_statement(*, limit: int, child_id: int | None, before_id: int | None):
    statement = (
        select(
            models.Conversation,
            models.Child,
            models.AnalysisJob,
            func.count(models.Message.id),
            func.max(models.Message.id),
            func.sum(case((models.Message.role == "child", 1), else_=0)),
        )
        .join(models.Child, models.Child.id == models.Conversation.child_id)
        .outerjoin(
            models.AnalysisJob,
            models.AnalysisJob.conversation_id == models.Conversation.id,
        )
        .outerjoin(
            models.Message,
            and_(
                models.Message.conversation_id == models.Conversation.id,
                models.Message.id <= models.Conversation.frozen_last_message_id,
            ),
        )
        .where(
            models.Conversation.status == "ended",
            models.Conversation.started_at.is_not(None),
            models.Conversation.ended_at.is_not(None),
            models.Conversation.frozen_last_message_id.is_not(None),
        )
        .group_by(models.Conversation.id, models.Child.id, models.AnalysisJob.id)
        .order_by(models.Conversation.id.desc())
        .limit(limit + 1)
    )
    if child_id is not None:
        statement = statement.where(models.Conversation.child_id == child_id)
    if before_id is not None:
        statement = statement.where(models.Conversation.id < before_id)
    return statement


def _group(rows, attribute: str) -> dict[int, list[object]]:
    grouped: dict[int, list[object]] = defaultdict(list)
    for row in rows:
        grouped[getattr(row, attribute)].append(row)
    return grouped


def list_conversation_history(
    db: Session,
    *,
    limit: int,
    child_id: int | None,
    before_id: int | None,
) -> schemas.ConversationHistoryPage:
    """Return one strict keyset page without per-item database reads."""
    rows = db.execute(
        _candidate_statement(limit=limit, child_id=child_id, before_id=before_id)
    ).all()
    visible = rows[:limit]
    visible_ids = [conversation.id for conversation, *_rest in visible]
    message_rows = []
    if visible_ids:
        message_rows = db.scalars(
            select(models.Message)
            .where(models.Message.conversation_id.in_(visible_ids))
            .order_by(models.Message.conversation_id, models.Message.id)
        ).all()
    succeeded_ids = [
        conversation.id
        for conversation, _child, job, *_counts in visible
        if job is not None and job.status == "succeeded"
    ]

    assessments = []
    feeding_rows = []
    emotions = []
    insights = []
    scores = []
    dimensions = []
    if succeeded_ids:
        assessments = db.scalars(
            select(models.Assessment).where(
                models.Assessment.conversation_id.in_(succeeded_ids)
            )
        ).all()
        feeding_rows = db.scalars(
            select(models.FeedingLog).where(
                models.FeedingLog.conversation_id.in_(succeeded_ids)
            )
        ).all()
        emotions = db.scalars(
            select(models.EmotionLog).where(
                models.EmotionLog.conversation_id.in_(succeeded_ids)
            )
        ).all()
        insights = db.scalars(
            select(models.InsightNote).where(
                models.InsightNote.conversation_id.in_(succeeded_ids)
            )
        ).all()
        assessment_ids = [assessment.id for assessment in assessments]
        if assessment_ids:
            scores = db.scalars(
                select(models.AssessmentScore).where(
                    models.AssessmentScore.assessment_id.in_(assessment_ids)
                )
            ).all()
            dimensions = db.scalars(
                select(models.AssessmentDimension)
            ).all()

    assessments_by_conversation = _group(assessments, "conversation_id")
    feeding_by_conversation = _group(feeding_rows, "conversation_id")
    emotions_by_conversation = _group(emotions, "conversation_id")
    insights_by_conversation = _group(insights, "conversation_id")
    scores_by_assessment = _group(scores, "assessment_id")
    dimensions_by_id = {dimension.id: dimension for dimension in dimensions}
    messages_by_conversation = _group(message_rows, "conversation_id")

    items: list[schemas.ConversationHistoryItem] = []
    try:
        for conversation, child, job, message_count, max_message_id, child_round in visible:
            if (
                job is None
                or job.frozen_last_message_id != conversation.frozen_last_message_id
                or job.status not in _JOB_STATUSES
                or job.updated_at is None
                or conversation.end_reason not in {"max_rounds", "complete", "manual"}
                or not message_count
                or max_message_id != conversation.frozen_last_message_id
            ):
                _fail(db)

            frozen_messages = [
                message
                for message in messages_by_conversation.get(conversation.id, [])
                if message.id <= conversation.frozen_last_message_id
            ]
            if (
                len(frozen_messages) != message_count
                or not frozen_messages
                or frozen_messages[-1].id != conversation.frozen_last_message_id
                or sum(message.role == "child" for message in frozen_messages) != child_round
            ):
                _fail(db)
            for message in frozen_messages:
                schemas.ConversationMessage(
                    id=message.id,
                    role=message.role,
                    text=message.text,
                )
            schemas.ConversationAnalysis(
                job_id=job.id,
                status=job.status,
                attempt_count=job.attempt_count,
                max_attempts=job.max_attempts,
                error=(
                    schemas.AnalysisError(
                        code="ANALYSIS_UPSTREAM_FAILED",
                        message="分析服务暂时不可用",
                    )
                    if job.status == "failed"
                    else None
                ),
                updated_at=_utc(job.updated_at),
            )

            review_status = "unavailable"
            if job.status == "succeeded":
                candidates = assessments_by_conversation.get(conversation.id, [])
                if len(candidates) != 1:
                    _fail(db)
                assessment = candidates[0]
                if (
                    assessment.child_id != child.id
                    or assessment.status not in _REVIEW_STATUSES
                    or assessment.overall is None
                    or not math.isfinite(assessment.overall)
                ):
                    _fail(db)
                emotion_rows = emotions_by_conversation.get(conversation.id, [])
                insight_rows = insights_by_conversation.get(conversation.id, [])
                score_rows = scores_by_assessment.get(assessment.id, [])
                if len(emotion_rows) != 1 or len(insight_rows) != 1:
                    _fail(db)
                emotion = emotion_rows[0]
                insight = insight_rows[0]
                if (
                    emotion.child_id != child.id
                    or insight.child_id != child.id
                    or not insight.content
                    or not insight.content.strip()
                ):
                    _fail(db)
                feeding = feeding_by_conversation.get(conversation.id, [])
                if any(row.child_id != child.id for row in feeding):
                    _fail(db)
                if len({score.dimension_id for score in score_rows}) != len(score_rows):
                    _fail(db)
                if (
                    any(score.dimension_id not in dimensions_by_id for score in score_rows)
                ):
                    _fail(db)
                review = schemas.ReviewDocument(
                    feeding_logs=[
                        schemas.ReviewFeedingLog(
                            id=row.id,
                            category=row.category,
                            content=row.content,
                            duck_id=row.duck_id,
                        )
                        for row in sorted(feeding, key=lambda item: item.id)
                    ],
                    emotion=schemas.ReviewEmotion(
                        emotion=emotion.emotion,
                        intensity=emotion.intensity,
                        note=emotion.note,
                    ),
                    insight=insight.content,
                    scores=[
                        schemas.ReviewScore(
                            dimension_id=score.dimension_id,
                            dimension_name=dimensions_by_id[score.dimension_id].name,
                            score=score.score,
                            reason=score.reason or "",
                        )
                        for score in sorted(score_rows, key=lambda item: item.dimension_id)
                    ],
                    overall=assessment.overall,
                )
                if len(review.scores) != len(score_rows) or any(
                    not item.dimension_name.strip() for item in review.scores
                ):
                    _fail(db)
                review_status = assessment.status

            items.append(schemas.ConversationHistoryItem(
                id=conversation.id,
                child=schemas.ChildIdentity(
                    id=child.id,
                    name=child.name,
                    nickname=child.nickname,
                    avatar=child.avatar,
                ),
                date=conversation.date,
                completed_at=_utc(conversation.ended_at),
                status="ended",
                end_reason=conversation.end_reason,
                message_count=message_count,
                round=child_round or 0,
                analysis_status=job.status,
                review_status=review_status,
                revision=conversation.revision,
            ))
    except (ValidationError, TypeError, ValueError, OverflowError):
        _fail(db)

    page = schemas.ConversationHistoryPage(
        items=items,
        next_before_id=items[-1].id if len(rows) > limit and items else None,
    )
    db.rollback()
    return page
