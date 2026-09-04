"""Bounded teacher history reads with page-wide integrity validation."""
from __future__ import annotations

import base64
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import logging
import math
import re

from pydantic import ValidationError
from sqlalchemy import and_, case, func, literal, or_, select
from sqlalchemy.orm import Session, aliased

from .. import models, schemas
from ..api_errors import APIError


_INTERNAL_MESSAGE = "服务暂时不可用，请稍后重试"
_JOB_STATUSES = {"pending", "processing", "succeeded", "failed"}
_REVIEW_STATUSES = {"pending", "draft", "confirmed"}
_CURSOR_KEYS = {
    "ended_at",
    "fingerprint",
    "id",
    "snapshot_max_id",
    "sort",
    "version",
}
_CURSOR_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
_FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_CURSOR_TIME_PATTERN = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$"
)
logger = logging.getLogger("duck_diary.history")


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _fail(db: Session) -> None:
    db.rollback()
    raise APIError(500, "INTERNAL_ERROR", _INTERNAL_MESSAGE, retryable=True)


def _history_candidate_statement(
    *,
    limit: int,
    child_id: int | None,
    before_id: int | None,
):
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


def _project_history_items(
    db: Session,
    visible: list[tuple[object, ...]],
) -> list[schemas.ConversationHistoryItem]:
    """Validate and materialize a complete candidate page in bounded queries."""
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

    return items


def list_conversation_history(
    db: Session,
    *,
    limit: int,
    child_id: int | None,
    before_id: int | None,
) -> schemas.ConversationHistoryPage:
    """Return one strict legacy keyset page without per-item database reads."""
    rows = db.execute(
        _history_candidate_statement(
            limit=limit,
            child_id=child_id,
            before_id=before_id,
        )
    ).all()
    items = _project_history_items(db, rows[:limit])
    page = schemas.ConversationHistoryPage(
        items=items,
        next_before_id=items[-1].id if len(rows) > limit and items else None,
    )
    db.rollback()
    return page


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _search_fingerprint(payload: schemas.ConversationSearchRequest) -> str:
    value = {
        "analysis_status": sorted(payload.analysis_status),
        "child_id": payload.child_id,
        "date_from": payload.date_from.isoformat() if payload.date_from else None,
        "date_to": payload.date_to.isoformat() if payload.date_to else None,
        "end_reason": sorted(payload.end_reason),
        "keyword": payload.keyword,
        "review_status": sorted(payload.review_status),
        "sort": payload.sort,
    }
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _canonical_cursor_time(value: datetime) -> str:
    return _utc(value).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _cursor_error() -> None:
    raise APIError(
        422,
        "VALIDATION_ERROR",
        "请求字段校验失败",
        {"body.cursor": ["游标无效或与筛选条件不匹配"]},
    )


def _encode_search_cursor(
    *,
    ended_at: datetime,
    conversation_id: int,
    sort: str,
    fingerprint: str,
    snapshot_max_id: int,
) -> str:
    raw = _canonical_json({
        "ended_at": _canonical_cursor_time(ended_at),
        "fingerprint": fingerprint,
        "id": conversation_id,
        "snapshot_max_id": snapshot_max_id,
        "sort": sort,
        "version": 1,
    })
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_search_cursor(
    cursor: str,
    *,
    expected_sort: str,
    expected_fingerprint: str,
) -> tuple[datetime, int, int]:
    try:
        if not _CURSOR_PATTERN.fullmatch(cursor):
            _cursor_error()
        padding = "=" * ((4 - len(cursor) % 4) % 4)
        raw = base64.b64decode(
            (cursor + padding).encode("ascii"),
            altchars=b"-_",
            validate=True,
        )
        if base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=") != cursor:
            _cursor_error()
        value = json.loads(
            raw.decode("utf-8"),
            parse_constant=lambda _constant: (_ for _ in ()).throw(ValueError()),
        )
        if not isinstance(value, dict) or set(value) != _CURSOR_KEYS:
            _cursor_error()
        if raw != _canonical_json(value):
            _cursor_error()
        if type(value["version"]) is not int or value["version"] != 1:
            _cursor_error()
        if type(value["id"]) is not int or value["id"] < 1:
            _cursor_error()
        if (
            type(value["snapshot_max_id"]) is not int
            or value["snapshot_max_id"] < 1
            or value["id"] > value["snapshot_max_id"]
        ):
            _cursor_error()
        if value["sort"] not in {"completed_desc", "completed_asc"}:
            _cursor_error()
        if value["sort"] != expected_sort:
            _cursor_error()
        fingerprint = value["fingerprint"]
        if (
            not isinstance(fingerprint, str)
            or not _FINGERPRINT_PATTERN.fullmatch(fingerprint)
            or fingerprint != expected_fingerprint
        ):
            _cursor_error()
        ended_at_text = value["ended_at"]
        if (
            not isinstance(ended_at_text, str)
            or not _CURSOR_TIME_PATTERN.fullmatch(ended_at_text)
        ):
            _cursor_error()
        ended_at = datetime.strptime(
            ended_at_text,
            "%Y-%m-%dT%H:%M:%S.%fZ",
        ).replace(tzinfo=timezone.utc)
        if _canonical_cursor_time(ended_at) != ended_at_text:
            _cursor_error()
        return (
            ended_at.replace(tzinfo=None),
            value["id"],
            value["snapshot_max_id"],
        )
    except APIError:
        raise
    except (KeyError, TypeError, ValueError, UnicodeDecodeError):
        _cursor_error()
    raise AssertionError("unreachable cursor parser state")


def _search_candidate_statement(
    payload: schemas.ConversationSearchRequest,
    *,
    cursor_position: tuple[datetime, int] | None,
    snapshot_max_id: int | None,
):
    snapshot_conversation = aliased(models.Conversation)
    snapshot_expression = (
        literal(snapshot_max_id)
        if snapshot_max_id is not None
        else select(func.max(snapshot_conversation.id)).scalar_subquery()
    )
    statement = (
        select(
            models.Conversation,
            models.Child,
            models.AnalysisJob,
            func.count(models.Message.id),
            func.max(models.Message.id),
            func.sum(case((models.Message.role == "child", 1), else_=0)),
            snapshot_expression.label("snapshot_max_id"),
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
            models.Conversation.id <= snapshot_expression,
        )
        .group_by(models.Conversation.id, models.Child.id, models.AnalysisJob.id)
        .limit(payload.limit + 1)
    )

    if payload.child_id is not None:
        statement = statement.where(
            models.Conversation.child_id == payload.child_id
        )
    if payload.date_from is not None:
        statement = statement.where(
            models.Conversation.date >= payload.date_from.isoformat()
        )
    if payload.date_to is not None:
        statement = statement.where(
            models.Conversation.date <= payload.date_to.isoformat()
        )
    if payload.analysis_status:
        statement = statement.where(
            models.AnalysisJob.status.in_(payload.analysis_status)
        )
    if payload.end_reason:
        statement = statement.where(
            models.Conversation.end_reason.in_(payload.end_reason)
        )
    if payload.review_status:
        review_predicates = []
        available_statuses = [
            status for status in payload.review_status if status != "unavailable"
        ]
        if "unavailable" in payload.review_status:
            review_predicates.append(
                models.AnalysisJob.status.in_(("pending", "processing", "failed"))
            )
        if available_statuses:
            assessment = aliased(models.Assessment)
            assessment_exists = select(1).where(
                assessment.conversation_id == models.Conversation.id,
                assessment.status.in_(available_statuses),
            ).exists()
            review_predicates.append(and_(
                models.AnalysisJob.status == "succeeded",
                assessment_exists,
            ))
        statement = statement.where(or_(*review_predicates))
    if payload.keyword is not None:
        message = aliased(models.Message)
        escaped = (
            payload.keyword.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        keyword_exists = select(1).where(
            message.conversation_id == models.Conversation.id,
            message.id <= models.Conversation.frozen_last_message_id,
            message.role.in_(("child", "diary")),
            message.text.like(f"%{escaped}%", escape="\\"),
        ).exists()
        statement = statement.where(keyword_exists)

    descending = payload.sort == "completed_desc"
    if cursor_position is not None:
        cursor_time, cursor_id = cursor_position
        if descending:
            statement = statement.where(or_(
                models.Conversation.ended_at < cursor_time,
                and_(
                    models.Conversation.ended_at == cursor_time,
                    models.Conversation.id < cursor_id,
                ),
            ))
        else:
            statement = statement.where(or_(
                models.Conversation.ended_at > cursor_time,
                and_(
                    models.Conversation.ended_at == cursor_time,
                    models.Conversation.id > cursor_id,
                ),
            ))
    order = (
        (models.Conversation.ended_at.desc(), models.Conversation.id.desc())
        if descending
        else (models.Conversation.ended_at.asc(), models.Conversation.id.asc())
    )
    return statement.order_by(*order)


def search_conversations(
    db: Session,
    payload: schemas.ConversationSearchRequest,
) -> schemas.ConversationSearchPage:
    """Return one immutable-snapshot search page using strict history projection."""
    try:
        fingerprint = _search_fingerprint(payload)
        cursor_position = None
        snapshot_max_id = None
        if payload.cursor is not None:
            cursor_time, cursor_id, snapshot_max_id = _decode_search_cursor(
                payload.cursor,
                expected_sort=payload.sort,
                expected_fingerprint=fingerprint,
            )
            cursor_position = (cursor_time, cursor_id)

        candidate_rows = db.execute(_search_candidate_statement(
            payload,
            cursor_position=cursor_position,
            snapshot_max_id=snapshot_max_id,
        )).all()
        visible_rows = candidate_rows[:payload.limit]
        projection_rows = [tuple(row[:6]) for row in visible_rows]
        items = _project_history_items(db, projection_rows)

        next_cursor = None
        if len(candidate_rows) > payload.limit and items:
            effective_snapshot = candidate_rows[0][6]
            if type(effective_snapshot) is not int or effective_snapshot < 1:
                _fail(db)
            last_conversation = visible_rows[-1][0]
            next_cursor = _encode_search_cursor(
                ended_at=last_conversation.ended_at,
                conversation_id=last_conversation.id,
                sort=payload.sort,
                fingerprint=fingerprint,
                snapshot_max_id=effective_snapshot,
            )

        page = schemas.ConversationSearchPage(
            items=items,
            next_cursor=next_cursor,
        )
        db.rollback()
        return page
    except APIError:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.error(
            "conversation search failed error_type=%s",
            type(exc).__name__,
        )
        raise APIError(
            500,
            "INTERNAL_ERROR",
            _INTERNAL_MESSAGE,
            retryable=True,
        ) from None
