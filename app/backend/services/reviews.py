"""Teacher queue, detail, and atomic full-document review operations."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from .. import models, schemas
from ..api_errors import APIError
from .avatar_media import project_avatar_url_for_read


_INTERNAL_MESSAGE = "服务暂时不可用，请稍后重试"
_NOT_FOUND_MESSAGE = "会话不存在"
_VALIDATION_MESSAGE = "审阅内容校验失败"
_REVISION_MESSAGE = "审阅内容已经变化，请先恢复最新内容"


@dataclass(frozen=True)
class _ValidatedReview:
    assessment_id: int
    retained_feeding_ids: frozenset[int]


@dataclass(frozen=True)
class _ReviewReferenceRows:
    existing_feeding_by_id: dict[int, models.FeedingLog]
    ducks_by_id: dict[int, models.Duck]
    dimensions_by_id: dict[int, models.AssessmentDimension]
    enabled_dimension_ids: frozenset[int]


def _utc_datetime(value: datetime) -> datetime:
    """Expose SQLite's naive UTC values as timezone-aware API datetimes."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _database_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _internal_error() -> APIError:
    return APIError(500, "INTERNAL_ERROR", _INTERNAL_MESSAGE, retryable=True)


def _not_found_error() -> APIError:
    return APIError(404, "CONVERSATION_NOT_FOUND", _NOT_FOUND_MESSAGE)


def _review_validation_error(field_errors: dict[str, list[str]]) -> APIError:
    return APIError(
        422,
        "REVIEW_VALIDATION_FAILED",
        _VALIDATION_MESSAGE,
        field_errors,
    )


def _review_revision_error(actual_revision: int) -> APIError:
    return APIError(
        409,
        "REVIEW_REVISION_CONFLICT",
        _REVISION_MESSAGE,
        {"revision": [f"当前版本为 {actual_revision}"]},
    )


def _queue_statement(
    queue: Literal["pending", "processing", "failed"],
):
    message_count = (
        select(func.count(models.Message.id))
        .where(
            models.Message.conversation_id == models.Conversation.id,
            models.Message.id <= models.Conversation.frozen_last_message_id,
        )
        .correlate(models.Conversation)
        .scalar_subquery()
    )
    child_round = (
        select(func.count(models.Message.id))
        .where(
            models.Message.conversation_id == models.Conversation.id,
            models.Message.id <= models.Conversation.frozen_last_message_id,
            models.Message.role == "child",
        )
        .correlate(models.Conversation)
        .scalar_subquery()
    )
    statement = (
        select(
            models.Conversation,
            models.Child,
            models.AnalysisJob,
            models.Assessment,
            message_count.label("message_count"),
            child_round.label("child_round"),
        )
        .join(models.Child, models.Child.id == models.Conversation.child_id)
        .join(
            models.AnalysisJob,
            (
                (models.AnalysisJob.conversation_id == models.Conversation.id)
                & (models.AnalysisJob.frozen_last_message_id == models.Conversation.frozen_last_message_id)
            ),
        )
        .outerjoin(
            models.Assessment,
            models.Assessment.conversation_id == models.Conversation.id,
        )
        .where(
            models.Conversation.status == "ended",
            models.Conversation.ended_at.is_not(None),
            models.Conversation.frozen_last_message_id.is_not(None),
        )
        .order_by(models.Conversation.ended_at.desc(), models.Conversation.id.desc())
    )
    not_confirmed = or_(
        models.Assessment.status.is_(None),
        models.Assessment.status != "confirmed",
    )
    if queue == "pending":
        return statement.where(
            models.AnalysisJob.status == "succeeded",
            models.Assessment.status.in_(("pending", "draft")),
        )
    if queue == "processing":
        return statement.where(
            models.AnalysisJob.status.in_(("pending", "processing")),
            not_confirmed,
        )
    return statement.where(
        models.AnalysisJob.status == "failed",
        not_confirmed,
    )


def list_review_queue(
    db: Session,
    *,
    queue: Literal["pending", "processing", "failed"],
) -> list[schemas.ConversationQueueItem]:
    """Return a teacher queue in one joined query without child/job N+1 reads."""
    rows = db.execute(_queue_statement(queue)).all()
    response: list[schemas.ConversationQueueItem] = []
    for conversation, child, job, assessment, message_count, child_round in rows:
        if (
            conversation.started_at is None
            or conversation.ended_at is None
            or conversation.end_reason is None
            or job.status not in {"pending", "processing", "succeeded", "failed"}
        ):
            db.rollback()
            raise _internal_error()
        review_status = (
            assessment.status if job.status == "succeeded" and assessment is not None else "unavailable"
        )
        if review_status not in {"pending", "draft", "confirmed", "unavailable"}:
            db.rollback()
            raise _internal_error()
        response.append(schemas.ConversationQueueItem(
            id=conversation.id,
            child=schemas.ChildIdentity(
                id=child.id,
                name=child.name,
                nickname=child.nickname,
                avatar=project_avatar_url_for_read(child.avatar),
            ),
            date=conversation.date,
            started_at=_utc_datetime(conversation.started_at),
            completed_at=_utc_datetime(conversation.ended_at),
            message_count=message_count or 0,
            round=child_round or 0,
            status="ended",
            end_reason=conversation.end_reason,
            analysis_status=job.status,
            review_status=review_status,
            revision=conversation.revision,
        ))
    db.rollback()
    return response


def _review_document(
    db: Session,
    *,
    conversation_id: int,
    assessment: models.Assessment,
) -> schemas.ReviewDocument:
    feeding_rows = db.scalars(
        select(models.FeedingLog)
        .where(models.FeedingLog.conversation_id == conversation_id)
        .order_by(models.FeedingLog.id)
    ).all()
    emotions = db.scalars(
        select(models.EmotionLog).where(models.EmotionLog.conversation_id == conversation_id)
    ).all()
    insights = db.scalars(
        select(models.InsightNote).where(models.InsightNote.conversation_id == conversation_id)
    ).all()
    score_rows = db.execute(
        select(models.AssessmentScore, models.AssessmentDimension)
        .join(
            models.AssessmentDimension,
            models.AssessmentDimension.id == models.AssessmentScore.dimension_id,
        )
        .where(models.AssessmentScore.assessment_id == assessment.id)
        .order_by(models.AssessmentScore.dimension_id)
    ).all()
    score_count = db.scalar(
        select(func.count(models.AssessmentScore.id)).where(
            models.AssessmentScore.assessment_id == assessment.id
        )
    ) or 0
    if (
        len(emotions) != 1
        or len(insights) != 1
        or not insights[0].content or not insights[0].content.strip()
        or len(score_rows) != score_count
        or assessment.overall is None
    ):
        raise _internal_error()
    emotion = emotions[0]
    return schemas.ReviewDocument(
        feeding_logs=[
            schemas.ReviewFeedingLog(
                id=row.id,
                category=row.category,
                content=row.content,
                duck_id=row.duck_id,
            )
            for row in feeding_rows
        ],
        emotion=schemas.ReviewEmotion(
            emotion=emotion.emotion,
            intensity=emotion.intensity,
            note=emotion.note,
        ),
        insight=insights[0].content,
        scores=[
            schemas.ReviewScore(
                dimension_id=score.dimension_id,
                dimension_name=dimension.name,
                score=score.score,
                reason=score.reason or "",
            )
            for score, dimension in score_rows
        ],
        overall=assessment.overall,
    )


def _ensure_sqlite_read_transaction(db: Session) -> bool:
    """Start a SQLite DBAPI snapshot and report whether this call owns it."""
    caller_owns_session_transaction = db.in_transaction()
    try:
        connection = db.connection()
        if connection.dialect.name != "sqlite":
            return False
        sqlite_connection = connection.connection.driver_connection
        if not sqlite_connection.in_transaction:
            connection.exec_driver_sql("BEGIN")
            return not caller_owns_session_transaction
        return False
    except BaseException:
        # ``db.connection()`` itself creates SQLAlchemy's logical transaction.
        # If our raw BEGIN then fails, unwind only that helper-created wrapper;
        # a caller-owned logical transaction (including unflushed ORM state)
        # must remain untouched.
        if not caller_owns_session_transaction and db.in_transaction():
            db.rollback()
        raise


def _get_review_detail_in_transaction(
    db: Session,
    *,
    conversation_id: int,
) -> schemas.ConversationDetail:
    """Load one detail document from the caller's active database snapshot."""
    row = db.execute(
        select(models.Conversation, models.Child, models.AnalysisJob)
        .join(models.Child, models.Child.id == models.Conversation.child_id)
        .join(
            models.AnalysisJob,
            models.AnalysisJob.conversation_id == models.Conversation.id,
        )
        .where(
            models.Conversation.id == conversation_id,
            models.Conversation.status == "ended",
            models.Conversation.started_at.is_not(None),
            models.Conversation.ended_at.is_not(None),
            models.Conversation.frozen_last_message_id.is_not(None),
            models.AnalysisJob.frozen_last_message_id == models.Conversation.frozen_last_message_id,
        )
    ).one_or_none()
    if row is None:
        raise _not_found_error()
    conversation, child, job = row
    messages = db.scalars(
        select(models.Message)
        .where(
            models.Message.conversation_id == conversation.id,
            models.Message.id <= conversation.frozen_last_message_id,
        )
        .order_by(models.Message.id)
    ).all()
    if (
        not messages
        or messages[-1].id != conversation.frozen_last_message_id
        or conversation.end_reason is None
        or job.updated_at is None
        or job.status not in {"pending", "processing", "succeeded", "failed"}
    ):
        raise _internal_error()
    analysis_error = (
        schemas.AnalysisError(
            code="ANALYSIS_UPSTREAM_FAILED",
            message="分析服务暂时不可用",
        )
        if job.status == "failed"
        else None
    )
    review_status: str = "unavailable"
    review: schemas.ReviewDocument | None = None
    if job.status == "succeeded":
        assessment = db.scalar(
            select(models.Assessment).where(
                models.Assessment.conversation_id == conversation.id
            )
        )
        if assessment is None or assessment.status not in {"pending", "draft", "confirmed"}:
            raise _internal_error()
        review_status = assessment.status
        review = _review_document(
            db,
            conversation_id=conversation.id,
            assessment=assessment,
        )
    response = schemas.ConversationDetail(
        id=conversation.id,
        child=schemas.ChildIdentity(
            id=child.id,
            name=child.name,
            nickname=child.nickname,
            avatar=project_avatar_url_for_read(child.avatar),
        ),
        date=conversation.date,
        started_at=_utc_datetime(conversation.started_at),
        completed_at=_utc_datetime(conversation.ended_at),
        status="ended",
        end_reason=conversation.end_reason,
        message_count=len(messages),
        round=sum(message.role == "child" for message in messages),
        last_message_id=conversation.frozen_last_message_id,
        revision=conversation.revision,
        analysis=schemas.ConversationAnalysis(
            job_id=job.id,
            status=job.status,
            attempt_count=job.attempt_count,
            max_attempts=job.max_attempts,
            error=analysis_error,
            updated_at=_utc_datetime(job.updated_at),
        ),
        review_status=review_status,
        messages=[
            schemas.ConversationMessage(id=message.id, role=message.role, text=message.text)
            for message in messages
        ],
        review=review,
    )
    return response


def get_review_detail(
    db: Session,
    *,
    conversation_id: int,
) -> schemas.ConversationDetail:
    """Load one revision-consistent detail without owning caller transactions."""

    owns_sqlite_snapshot = _ensure_sqlite_read_transaction(db)
    try:
        return _get_review_detail_in_transaction(
            db,
            conversation_id=conversation_id,
        )
    finally:
        if owns_sqlite_snapshot:
            db.rollback()


def _after_review_validation_before_cas() -> None:
    """Deterministic test seam; production deliberately performs no work here."""


def _load_review_reference_rows(
    db: Session,
    *,
    conversation_id: int,
    payload: schemas.ReviewRequest,
) -> _ReviewReferenceRows:
    """Load every mutable reference once for either pre- or post-CAS validation."""
    existing_feeding_by_id = {
        row.id: row
        for row in db.scalars(
            select(models.FeedingLog).where(
                models.FeedingLog.conversation_id == conversation_id
            )
        )
    }
    requested_duck_ids = {
        row.duck_id for row in payload.feeding_logs if row.duck_id is not None
    }
    ducks_by_id = {
        duck.id: duck
        for duck in db.scalars(
            select(models.Duck).where(models.Duck.id.in_(requested_duck_ids))
        )
    } if requested_duck_ids else {}
    requested_dimension_ids = {row.dimension_id for row in payload.scores}
    dimensions_by_id = {
        dimension.id: dimension
        for dimension in db.scalars(
            select(models.AssessmentDimension).where(
                models.AssessmentDimension.id.in_(requested_dimension_ids)
            )
        )
    } if requested_dimension_ids else {}
    enabled_dimension_ids = frozenset(db.scalars(
        select(models.AssessmentDimension.id).where(
            models.AssessmentDimension.enabled.is_(True)
        )
    ))
    return _ReviewReferenceRows(
        existing_feeding_by_id=existing_feeding_by_id,
        ducks_by_id=ducks_by_id,
        dimensions_by_id=dimensions_by_id,
        enabled_dimension_ids=enabled_dimension_ids,
    )


def _review_reference_errors(
    payload: schemas.ReviewRequest,
    *,
    references: _ReviewReferenceRows,
) -> tuple[frozenset[int], dict[str, list[str]]]:
    """Classify all reference semantics without mutating ORM state."""
    errors: dict[str, list[str]] = {}

    def add_error(key: str, message: str) -> None:
        errors.setdefault(key, []).append(message)

    retained_ids: set[int] = set()
    for index, feeding in enumerate(payload.feeding_logs):
        existing = None
        if feeding.id is not None:
            existing = references.existing_feeding_by_id.get(feeding.id)
            if feeding.id in retained_ids:
                add_error(f"feeding_logs.{index}.id", "流水记录重复")
            elif existing is None:
                add_error(f"feeding_logs.{index}.id", "流水记录不属于当前会话")
            else:
                retained_ids.add(feeding.id)
        if feeding.duck_id is not None:
            duck = references.ducks_by_id.get(feeding.duck_id)
            if duck is None:
                add_error(f"feeding_logs.{index}.duck_id", "小鸭不存在")
            elif not duck.active and not (
                existing is not None and existing.duck_id == feeding.duck_id
            ):
                add_error(f"feeding_logs.{index}.duck_id", "小鸭已停用")

    requested_score_ids = {score.dimension_id for score in payload.scores}
    for index, score in enumerate(payload.scores):
        dimension = references.dimensions_by_id.get(score.dimension_id)
        if dimension is None:
            add_error(f"scores.{index}.dimension_id", "评估维度不存在")
        elif not dimension.enabled:
            add_error(f"scores.{index}.dimension_id", "评估维度已停用")
        if payload.action == "confirm" and not score.reason.strip():
            add_error(f"scores.{index}.reason", "确认时需要填写评分理由")
    if payload.action == "confirm" and requested_score_ids != references.enabled_dimension_ids:
        add_error("scores", "确认时必须覆盖全部启用维度")
    return frozenset(retained_ids), errors


def _validate_review(
    db: Session,
    *,
    conversation_id: int,
    payload: schemas.ReviewRequest,
) -> _ValidatedReview:
    """Read and classify every semantic error without changing ORM state."""
    with db.no_autoflush:
        conversation = db.get(models.Conversation, conversation_id)
        if conversation is None or conversation.status != "ended":
            db.rollback()
            raise _not_found_error()
        job = db.scalar(select(models.AnalysisJob).where(
            models.AnalysisJob.conversation_id == conversation_id
        ))
        if (
            job is None
            or conversation.frozen_last_message_id is None
            or job.frozen_last_message_id != conversation.frozen_last_message_id
        ):
            db.rollback()
            raise _not_found_error()
        if job.status != "succeeded":
            db.rollback()
            raise _review_validation_error({"analysis": ["分析尚未完成"]})
        assessment = db.scalar(select(models.Assessment).where(
            models.Assessment.conversation_id == conversation_id
        ))
        if assessment is None:
            db.rollback()
            raise _internal_error()
        references = _load_review_reference_rows(
            db,
            conversation_id=conversation_id,
            payload=payload,
        )
        retained_ids, errors = _review_reference_errors(
            payload,
            references=references,
        )
        if errors:
            db.rollback()
            raise _review_validation_error(errors)

    validated = _ValidatedReview(
        assessment_id=assessment.id,
        retained_feeding_ids=retained_ids,
    )
    # Do not upgrade this snapshot's read transaction into the writer.
    db.rollback()
    return validated


def _fresh_revision_or_error(db: Session, conversation_id: int) -> APIError:
    current = db.get(models.Conversation, conversation_id)
    actual_revision = current.revision if current is not None else -1
    db.rollback()
    return _review_revision_error(actual_revision)


def save_review(
    db: Session,
    *,
    conversation_id: int,
    payload: schemas.ReviewRequest,
    now: datetime,
) -> schemas.ReviewResponse:
    """Replace every editable review projection in one revision-CAS transaction."""
    validated = _validate_review(db, conversation_id=conversation_id, payload=payload)
    _after_review_validation_before_cas()
    db_now = _database_utc(now)
    try:
        cas = db.execute(
            update(models.Conversation)
            .where(
                models.Conversation.id == conversation_id,
                models.Conversation.revision == payload.revision,
                models.Conversation.status == "ended",
            )
            .values(revision=models.Conversation.revision + 1)
        )
        if cas.rowcount != 1:
            db.rollback()
            raise _fresh_revision_or_error(db, conversation_id)

        conversation = db.get(models.Conversation, conversation_id, populate_existing=True)
        job = db.scalar(select(models.AnalysisJob).where(
            models.AnalysisJob.conversation_id == conversation_id
        ))
        assessment = db.scalar(select(models.Assessment).where(
            models.Assessment.conversation_id == conversation_id
        ))
        if (
            conversation is None
            or conversation.status != "ended"
            or job is None
            or job.status != "succeeded"
            or job.frozen_last_message_id != conversation.frozen_last_message_id
            or assessment is None
            or assessment.id != validated.assessment_id
        ):
            raise _internal_error()
        with db.no_autoflush:
            references = _load_review_reference_rows(
                db,
                conversation_id=conversation_id,
                payload=payload,
            )
            retained_ids, errors = _review_reference_errors(
                payload,
                references=references,
            )
        if errors:
            raise _review_validation_error(errors)
        if retained_ids != validated.retained_feeding_ids:
            raise _review_validation_error({
                "feeding_logs": ["流水记录已经变化，请重新审阅"],
            })
        retained_by_id = {
            feeding_id: references.existing_feeding_by_id[feeding_id]
            for feeding_id in retained_ids
        }

        for feeding in payload.feeding_logs:
            if feeding.id is None:
                db.add(models.FeedingLog(
                    conversation_id=conversation.id,
                    child_id=conversation.child_id,
                    duck_id=feeding.duck_id,
                    category=feeding.category,
                    content=feeding.content,
                    occurred_at=db_now,
                ))
            else:
                row = retained_by_id[feeding.id]
                row.duck_id = feeding.duck_id
                row.category = feeding.category
                row.content = feeding.content
        for feeding_id, row in references.existing_feeding_by_id.items():
            if feeding_id not in retained_ids:
                db.delete(row)

        emotion = db.scalar(select(models.EmotionLog).where(
            models.EmotionLog.conversation_id == conversation_id
        ))
        if emotion is None:
            emotion = models.EmotionLog(
                conversation_id=conversation.id,
                child_id=conversation.child_id,
                emotion=payload.emotion.emotion,
                intensity=payload.emotion.intensity,
                note=payload.emotion.note,
                occurred_at=db_now,
            )
            db.add(emotion)
        else:
            emotion.emotion = payload.emotion.emotion
            emotion.intensity = payload.emotion.intensity
            emotion.note = payload.emotion.note
        insight = db.scalar(select(models.InsightNote).where(
            models.InsightNote.conversation_id == conversation_id
        ))
        if insight is None:
            db.add(models.InsightNote(
                conversation_id=conversation.id,
                child_id=conversation.child_id,
                content=payload.insight,
                created_at=db_now,
            ))
        else:
            insight.content = payload.insight

        db.execute(delete(models.AssessmentScore).where(
            models.AssessmentScore.assessment_id == assessment.id
        ))
        db.add_all([
            models.AssessmentScore(
                assessment_id=assessment.id,
                dimension_id=score.dimension_id,
                score=score.score,
                reason=score.reason,
            )
            for score in payload.scores
        ])
        assessment.overall = round(
            sum(score.score for score in payload.scores) / len(payload.scores),
            2,
        ) if payload.scores else 0.0
        assessment.status = "confirmed" if payload.action == "confirm" else "draft"
        db.flush()
        review = _review_document(
            db,
            conversation_id=conversation.id,
            assessment=assessment,
        )
        response = schemas.ReviewResponse(
            saved=True,
            conversation_id=conversation.id,
            review_status=assessment.status,
            revision=conversation.revision,
            saved_at=_utc_datetime(now),
            review=review,
        )
        db.commit()
        return response
    except APIError:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
