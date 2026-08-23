"""Lease-based durable conversation analysis operations."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Literal, Protocol

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from .. import models, schemas
from ..api_errors import APIError


logger = logging.getLogger("duck_diary.analysis")

ANALYSIS_ERROR_CODE = "ANALYSIS_UPSTREAM_FAILED"
ANALYSIS_ERROR_MESSAGE = "分析服务暂时不可用"
_FEEDING_CATEGORIES = {"喂食", "清洁", "观察", "其它"}


class AnalysisEngine(Protocol):
    def extract_info(self, transcript: str) -> dict: ...

    def assess_conversation(self, transcript: str, dimensions: list[dict]) -> dict: ...


@dataclass(frozen=True)
class AnalysisWorkerStatus:
    state: Literal["starting", "idle", "processing", "stopped", "failed"]
    active_job_id: int | None
    last_error_code: str | None


@dataclass(frozen=True)
class _FrozenAnalysisInput:
    job_id: int
    attempt_count: int
    conversation_id: int
    child_id: int
    transcript: str
    dimensions: tuple[dict, ...]
    dimension_ids_by_key: dict[str, int]
    duck_ids_by_name: dict[str, int]


@dataclass(frozen=True)
class _ValidatedProjection:
    feeding_logs: tuple[tuple[str, str, int | None], ...]
    emotion: tuple[str, int, str | None]
    insight: str
    scores: tuple[tuple[int, int, str], ...]
    overall: float


class _InvalidAnalysisOutput(ValueError):
    """Provider output or frozen inputs cannot safely be persisted."""


class _InvalidFrozenInput(_InvalidAnalysisOutput):
    def __init__(self, *, job_id: int, attempt_count: int) -> None:
        super().__init__("analysis job frozen input is invalid")
        self.job_id = job_id
        self.attempt_count = attempt_count


def _database_utc(value: datetime) -> datetime:
    """Use naive UTC for SQLite while accepting aware clocks at all boundaries."""
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def recover_expired_jobs(db: Session, *, now: datetime) -> int:
    """Make abandoned processing jobs eligible again without erasing attempts."""
    db_now = _database_utc(now)
    recovered = db.execute(
        update(models.AnalysisJob)
        .where(
            models.AnalysisJob.status == "processing",
            models.AnalysisJob.lease_expires_at.is_not(None),
            models.AnalysisJob.lease_expires_at <= db_now,
        )
        .values(
            status="pending",
            available_at=db_now,
            lease_owner=None,
            lease_expires_at=None,
            updated_at=db_now,
        )
    )
    db.commit()
    return recovered.rowcount


def claim_next_analysis_job(
    db: Session,
    *,
    worker_id: str,
    now: datetime,
    lease_seconds: int,
) -> int | None:
    """Claim the oldest due job using a conditional update, then commit ownership."""
    db_now = _database_utc(now)
    while True:
        candidate_id = db.scalar(
            select(models.AnalysisJob.id)
            .where(
                models.AnalysisJob.status == "pending",
                models.AnalysisJob.available_at <= db_now,
            )
            .order_by(models.AnalysisJob.available_at, models.AnalysisJob.id)
            .limit(1)
        )
        if candidate_id is None:
            db.rollback()
            return None
        claimed = db.execute(
            update(models.AnalysisJob)
            .where(
                models.AnalysisJob.id == candidate_id,
                models.AnalysisJob.status == "pending",
                models.AnalysisJob.available_at <= db_now,
            )
            .values(
                status="processing",
                attempt_count=models.AnalysisJob.attempt_count + 1,
                lease_owner=worker_id,
                lease_expires_at=db_now + timedelta(seconds=lease_seconds),
                started_at=db_now,
                finished_at=None,
                updated_at=db_now,
            )
        )
        if claimed.rowcount == 1:
            db.commit()
            return candidate_id
        db.rollback()


def _owned_processing_job(
    db: Session,
    *,
    job_id: int,
    worker_id: str,
    now: datetime,
) -> models.AnalysisJob | None:
    job = db.get(models.AnalysisJob, job_id)
    if job is None or job.status == "succeeded":
        return None
    if (
        job.status != "processing"
        or job.lease_owner != worker_id
        or job.lease_expires_at is None
        or job.lease_expires_at <= now
    ):
        return None
    return job


def _load_frozen_input(
    session_factory: Callable[[], Session],
    *,
    job_id: int,
    worker_id: str,
    now: datetime,
) -> _FrozenAnalysisInput | None:
    """Read all provider input, then close the database before external latency."""
    db = session_factory()
    try:
        job = _owned_processing_job(
            db,
            job_id=job_id,
            worker_id=worker_id,
            now=now,
        )
        if job is None:
            return None
        conversation = db.get(models.Conversation, job.conversation_id)
        if (
            conversation is None
            or conversation.status != "ended"
            or conversation.frozen_last_message_id != job.frozen_last_message_id
        ):
            raise _InvalidFrozenInput(job_id=job.id, attempt_count=job.attempt_count)
        messages = db.scalars(
            select(models.Message)
            .where(
                models.Message.conversation_id == conversation.id,
                models.Message.id <= job.frozen_last_message_id,
            )
            .order_by(models.Message.id)
        ).all()
        if not messages or messages[-1].id != job.frozen_last_message_id:
            raise _InvalidFrozenInput(job_id=job.id, attempt_count=job.attempt_count)
        dimensions = db.scalars(
            select(models.AssessmentDimension)
            .where(models.AssessmentDimension.enabled.is_(True))
            .order_by(models.AssessmentDimension.id)
        ).all()
        if not dimensions:
            raise _InvalidFrozenInput(job_id=job.id, attempt_count=job.attempt_count)
        duck_ids_by_name: dict[str, int] = {}
        for duck in db.scalars(
            select(models.Duck)
            .where(models.Duck.active.is_(True))
            .order_by(models.Duck.id)
        ):
            duck_ids_by_name.setdefault(duck.name, duck.id)
        return _FrozenAnalysisInput(
            job_id=job.id,
            attempt_count=job.attempt_count,
            conversation_id=conversation.id,
            child_id=conversation.child_id,
            transcript="\n".join(f"{message.role}: {message.text}" for message in messages),
            dimensions=tuple(
                {
                    "key": dimension.key,
                    "name": dimension.name,
                    "description": dimension.description,
                }
                for dimension in dimensions
            ),
            dimension_ids_by_key={dimension.key: dimension.id for dimension in dimensions},
            duck_ids_by_name=duck_ids_by_name,
        )
    finally:
        db.close()


def _text(value: object, *, maximum: int, required: bool = True) -> str | None:
    if not isinstance(value, str):
        raise _InvalidAnalysisOutput("provider text is not a string")
    normalized = value.strip()
    if len(normalized) > maximum or (required and not normalized):
        raise _InvalidAnalysisOutput("provider text is outside the allowed range")
    return normalized or None


def _score(value: object) -> int:
    if type(value) is not int or not 1 <= value <= 5:
        raise _InvalidAnalysisOutput("provider score is outside 1-5")
    return value


def _validate_projection(
    extraction: object,
    assessment: object,
    *,
    frozen_input: _FrozenAnalysisInput,
) -> _ValidatedProjection:
    if not isinstance(extraction, dict) or not isinstance(assessment, dict):
        raise _InvalidAnalysisOutput("provider results must be objects")
    raw_logs = extraction.get("feeding_logs")
    if not isinstance(raw_logs, list):
        raise _InvalidAnalysisOutput("feeding logs must be a list")
    feeding_logs: list[tuple[str, str, int | None]] = []
    for raw_log in raw_logs:
        if not isinstance(raw_log, dict):
            raise _InvalidAnalysisOutput("feeding log must be an object")
        category = raw_log.get("category")
        if category not in _FEEDING_CATEGORIES:
            raise _InvalidAnalysisOutput("feeding category is invalid")
        content = _text(raw_log.get("content"), maximum=500)
        assert content is not None
        duck_name = raw_log.get("duck_name")
        if duck_name is not None and not isinstance(duck_name, str):
            raise _InvalidAnalysisOutput("duck name is invalid")
        duck_id = frozen_input.duck_ids_by_name.get(duck_name.strip()) if duck_name else None
        feeding_logs.append((category, content, duck_id))

    raw_emotion = extraction.get("emotion")
    if not isinstance(raw_emotion, dict):
        raise _InvalidAnalysisOutput("emotion must be an object")
    emotion = _text(raw_emotion.get("emotion"), maximum=32)
    assert emotion is not None
    raw_note = raw_emotion.get("note")
    note = None if raw_note is None else _text(raw_note, maximum=500, required=False)
    insight = _text(extraction.get("insight"), maximum=2000, required=False) or ""

    raw_scores = assessment.get("scores")
    if not isinstance(raw_scores, list) or len(raw_scores) != len(frozen_input.dimensions):
        raise _InvalidAnalysisOutput("every enabled dimension must be scored once")
    seen_keys: set[str] = set()
    scores_by_key: dict[str, tuple[int, str]] = {}
    for raw_score in raw_scores:
        if not isinstance(raw_score, dict):
            raise _InvalidAnalysisOutput("score must be an object")
        key = raw_score.get("dimension_key")
        if (
            not isinstance(key, str)
            or key not in frozen_input.dimension_ids_by_key
            or key in seen_keys
        ):
            raise _InvalidAnalysisOutput("dimension key is invalid or duplicated")
        seen_keys.add(key)
        reason = _text(raw_score.get("reason"), maximum=500)
        assert reason is not None
        scores_by_key[key] = (_score(raw_score.get("score")), reason)
    if seen_keys != set(frozen_input.dimension_ids_by_key):
        raise _InvalidAnalysisOutput("every enabled dimension must be scored once")
    scores = tuple(
        (
            frozen_input.dimension_ids_by_key[dimension["key"]],
            *scores_by_key[dimension["key"]],
        )
        for dimension in frozen_input.dimensions
    )
    return _ValidatedProjection(
        feeding_logs=tuple(feeding_logs),
        emotion=(emotion, _score(raw_emotion.get("intensity")), note),
        insight=insight,
        scores=scores,
        overall=sum(score for _dimension_id, score, _reason in scores) / len(scores),
    )


def _owned_job_update(
    *,
    job_id: int,
    worker_id: str,
    attempt_count: int,
    now: datetime,
) -> tuple:
    return (
        models.AnalysisJob.id == job_id,
        models.AnalysisJob.status == "processing",
        models.AnalysisJob.lease_owner == worker_id,
        models.AnalysisJob.attempt_count == attempt_count,
        models.AnalysisJob.lease_expires_at.is_not(None),
        models.AnalysisJob.lease_expires_at > now,
    )


def _record_failure(
    session_factory: Callable[[], Session],
    *,
    job_id: int,
    worker_id: str,
    attempt_count: int,
    clock: Callable[[], datetime],
) -> None:
    db = session_factory()
    try:
        db_now = _database_utc(clock())
        job = db.get(models.AnalysisJob, job_id)
        if job is None:
            db.rollback()
            return
        terminal = attempt_count >= job.max_attempts
        failure = db.execute(
            update(models.AnalysisJob)
            .where(
                *_owned_job_update(
                    job_id=job_id,
                    worker_id=worker_id,
                    attempt_count=attempt_count,
                    now=db_now,
                )
            )
            .values(
                status="failed" if terminal else "pending",
                available_at=db_now if terminal else db_now + timedelta(seconds=1 if attempt_count == 1 else 5),
                lease_owner=None,
                lease_expires_at=None,
                last_error_code=ANALYSIS_ERROR_CODE,
                last_error_message=ANALYSIS_ERROR_MESSAGE,
                finished_at=db_now if terminal else None,
                updated_at=db_now,
            )
        )
        if failure.rowcount == 1:
            db.commit()
        else:
            db.rollback()
    finally:
        db.close()


def _replace_projection(
    session_factory: Callable[[], Session],
    *,
    frozen_input: _FrozenAnalysisInput,
    projection: _ValidatedProjection,
    worker_id: str,
    clock: Callable[[], datetime],
) -> bool:
    db = session_factory()
    try:
        db_now = _database_utc(clock())
        lock = db.execute(
            update(models.AnalysisJob)
            .where(
                *_owned_job_update(
                    job_id=frozen_input.job_id,
                    worker_id=worker_id,
                    attempt_count=frozen_input.attempt_count,
                    now=db_now,
                )
            )
            .values(updated_at=db_now)
        )
        if lock.rowcount != 1:
            db.rollback()
            return False

        assessment_ids = list(
            db.scalars(
                select(models.Assessment.id).where(
                    models.Assessment.conversation_id == frozen_input.conversation_id
                )
            )
        )
        if assessment_ids:
            db.execute(
                delete(models.AssessmentScore).where(
                    models.AssessmentScore.assessment_id.in_(assessment_ids)
                )
            )
        db.execute(delete(models.FeedingLog).where(
            models.FeedingLog.conversation_id == frozen_input.conversation_id
        ))
        db.execute(delete(models.EmotionLog).where(
            models.EmotionLog.conversation_id == frozen_input.conversation_id
        ))
        db.execute(delete(models.InsightNote).where(
            models.InsightNote.conversation_id == frozen_input.conversation_id
        ))
        db.execute(delete(models.Assessment).where(
            models.Assessment.conversation_id == frozen_input.conversation_id
        ))
        db.add_all([
            models.FeedingLog(
                conversation_id=frozen_input.conversation_id,
                child_id=frozen_input.child_id,
                duck_id=duck_id,
                category=category,
                content=content,
                occurred_at=db_now,
            )
            for category, content, duck_id in projection.feeding_logs
        ])
        emotion, intensity, note = projection.emotion
        db.add(models.EmotionLog(
            conversation_id=frozen_input.conversation_id,
            child_id=frozen_input.child_id,
            emotion=emotion,
            intensity=intensity,
            note=note,
            occurred_at=db_now,
        ))
        db.add(models.InsightNote(
            conversation_id=frozen_input.conversation_id,
            child_id=frozen_input.child_id,
            content=projection.insight,
            created_at=db_now,
        ))
        assessment = models.Assessment(
            conversation_id=frozen_input.conversation_id,
            child_id=frozen_input.child_id,
            status="pending",
            overall=projection.overall,
        )
        db.add(assessment)
        db.flush()
        db.add_all([
            models.AssessmentScore(
                assessment_id=assessment.id,
                dimension_id=dimension_id,
                score=score,
                reason=reason,
            )
            for dimension_id, score, reason in projection.scores
        ])
        db.execute(
            update(models.AnalysisJob)
            .where(models.AnalysisJob.id == frozen_input.job_id)
            .values(
                status="succeeded",
                available_at=db_now,
                lease_owner=None,
                lease_expires_at=None,
                last_error_code=None,
                last_error_message=None,
                finished_at=db_now,
                updated_at=db_now,
            )
        )
        db.execute(
            update(models.Conversation)
            .where(models.Conversation.id == frozen_input.conversation_id)
            .values(revision=models.Conversation.revision + 1)
        )
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def process_analysis_job(
    session_factory: Callable[[], Session],
    *,
    job_id: int,
    worker_id: str,
    analyzer: AnalysisEngine,
    clock: Callable[[], datetime],
) -> None:
    """Run a claimed job while keeping AI calls outside database sessions."""
    try:
        frozen_input = _load_frozen_input(
            session_factory,
            job_id=job_id,
            worker_id=worker_id,
            now=_database_utc(clock()),
        )
    except _InvalidFrozenInput as exc:
        logger.warning("analysis frozen input failure job_id=%s", exc.job_id)
        _record_failure(
            session_factory,
            job_id=exc.job_id,
            worker_id=worker_id,
            attempt_count=exc.attempt_count,
            clock=clock,
        )
        return
    if frozen_input is None:
        return

    try:
        extraction = analyzer.extract_info(frozen_input.transcript)
        assessment = analyzer.assess_conversation(
            frozen_input.transcript,
            list(frozen_input.dimensions),
        )
        projection = _validate_projection(
            extraction,
            assessment,
            frozen_input=frozen_input,
        )
        _replace_projection(
            session_factory,
            frozen_input=frozen_input,
            projection=projection,
            worker_id=worker_id,
            clock=clock,
        )
    except Exception as exc:  # Provider content is never persisted or exposed.
        logger.warning(
            "analysis provider or persistence failure job_id=%s error_type=%s",
            job_id,
            type(exc).__name__,
            exc_info=True,
        )
        _record_failure(
            session_factory,
            job_id=frozen_input.job_id,
            worker_id=worker_id,
            attempt_count=frozen_input.attempt_count,
            clock=clock,
        )


def retry_analysis(
    db: Session,
    conversation_id: int,
    *,
    now: datetime,
) -> schemas.AnalysisRetryResponse:
    """Teacher retry reuses the unique durable job; it never creates another one."""
    conversation = db.get(models.Conversation, conversation_id)
    job = (
        db.scalar(
            select(models.AnalysisJob).where(
                models.AnalysisJob.conversation_id == conversation_id
            )
        )
        if conversation is not None
        else None
    )
    if conversation is None or job is None:
        db.rollback()
        raise APIError(404, "CONVERSATION_NOT_FOUND", "会话不存在")
    if job.status == "pending":
        response = schemas.AnalysisRetryResponse(
            conversation_id=conversation_id,
            analysis_job_id=job.id,
            analysis_status="pending",
            attempt_count=job.attempt_count,
            retry_accepted=False,
            replayed=True,
        )
        db.rollback()
        return response
    if job.status == "processing":
        db.rollback()
        raise APIError(409, "ANALYSIS_IN_PROGRESS", "分析任务正在处理中")
    if job.status == "succeeded":
        db.rollback()
        raise APIError(409, "ANALYSIS_ALREADY_SUCCEEDED", "分析任务已经完成")

    db_now = _database_utc(now)
    reset = db.execute(
        update(models.AnalysisJob)
        .where(
            models.AnalysisJob.id == job.id,
            models.AnalysisJob.status == "failed",
        )
        .values(
            status="pending",
            attempt_count=0,
            available_at=db_now,
            lease_owner=None,
            lease_expires_at=None,
            last_error_code=None,
            last_error_message=None,
            started_at=None,
            finished_at=None,
            updated_at=db_now,
        )
    )
    if reset.rowcount == 1:
        db.commit()
        return schemas.AnalysisRetryResponse(
            conversation_id=conversation_id,
            analysis_job_id=job.id,
            analysis_status="pending",
            attempt_count=0,
            retry_accepted=True,
            replayed=False,
        )

    # Another retry or a worker won between our read and attempted reset.
    # Drop both stale ORM values and the failed CAS before classifying durable state.
    db.rollback()
    current = db.scalar(
        select(models.AnalysisJob)
        .where(models.AnalysisJob.conversation_id == conversation_id)
        .execution_options(populate_existing=True)
    )
    if current is None:
        db.rollback()
        raise APIError(404, "CONVERSATION_NOT_FOUND", "会话不存在")
    if current.status == "pending":
        response = schemas.AnalysisRetryResponse(
            conversation_id=conversation_id,
            analysis_job_id=current.id,
            analysis_status="pending",
            attempt_count=current.attempt_count,
            retry_accepted=False,
            replayed=True,
        )
        db.rollback()
        return response
    if current.status == "processing":
        db.rollback()
        raise APIError(409, "ANALYSIS_IN_PROGRESS", "分析任务正在处理中")
    if current.status == "succeeded":
        db.rollback()
        raise APIError(409, "ANALYSIS_ALREADY_SUCCEEDED", "分析任务已经完成")
    db.rollback()
    raise APIError(409, "ANALYSIS_IN_PROGRESS", "分析任务正在处理中")
