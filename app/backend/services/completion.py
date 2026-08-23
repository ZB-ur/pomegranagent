"""Atomic conversation freeze and durable analysis-job creation."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models, schemas
from ..api_errors import APIError


_ERROR_MESSAGES = {
    "CONVERSATION_CHANGED": "会话内容已经变化，请先恢复最新内容",
    "CONVERSATION_EMPTY": "会话暂无内容，无法完成保存",
    "CONVERSATION_NOT_FOUND": "会话不存在",
    "INTERNAL_ERROR": "服务暂时不可用，请稍后重试",
}


def _api_error(status_code: int, code: str) -> APIError:
    return APIError(status_code, code, _ERROR_MESSAGES[code])


def _last_message_id(db: Session, conversation_id: int) -> int | None:
    return db.scalar(
        select(models.Message.id)
        .where(models.Message.conversation_id == conversation_id)
        .order_by(models.Message.id.desc())
        .limit(1)
    )


def _frozen_message_count(
    db: Session,
    *,
    conversation_id: int,
    frozen_last_message_id: int,
) -> int:
    return db.scalar(
        select(func.count(models.Message.id)).where(
            models.Message.conversation_id == conversation_id,
            models.Message.id <= frozen_last_message_id,
        )
    ) or 0


def _utc_datetime(value: datetime) -> datetime:
    """Expose SQLite's naive UTC timestamps as explicit UTC API values."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _completion_response(
    db: Session,
    *,
    conversation: models.Conversation,
    job: models.AnalysisJob,
    replayed: bool,
) -> schemas.ConversationCompleteResponse:
    if conversation.ended_at is None or conversation.frozen_last_message_id is None:
        raise _api_error(500, "INTERNAL_ERROR")
    return schemas.ConversationCompleteResponse(
        conversation_id=conversation.id,
        conversation_saved=True,
        status="completed",
        completed_at=_utc_datetime(conversation.ended_at),
        message_count=_frozen_message_count(
            db,
            conversation_id=conversation.id,
            frozen_last_message_id=conversation.frozen_last_message_id,
        ),
        last_message_id=conversation.frozen_last_message_id,
        analysis_job_id=job.id,
        analysis_status="pending",
        replayed=replayed,
    )


def _ended_replay_or_error(
    db: Session,
    *,
    conversation: models.Conversation,
    expected_last_message_id: int,
) -> schemas.ConversationCompleteResponse:
    if conversation.frozen_last_message_id != expected_last_message_id:
        db.rollback()
        raise _api_error(409, "CONVERSATION_CHANGED")
    job = db.scalar(
        select(models.AnalysisJob).where(
            models.AnalysisJob.conversation_id == conversation.id
        )
    )
    if (
        job is None
        or job.frozen_last_message_id != conversation.frozen_last_message_id
        or conversation.ended_at is None
    ):
        db.rollback()
        raise _api_error(500, "INTERNAL_ERROR")
    response = _completion_response(
        db,
        conversation=conversation,
        job=job,
        replayed=True,
    )
    db.rollback()
    return response


def complete_conversation(
    db: Session,
    *,
    conversation_id: int,
    expected_last_message_id: int,
    now: datetime,
) -> schemas.ConversationCompleteResponse:
    """Freeze one active transcript and enqueue its sole analysis job atomically."""
    conversation = db.get(models.Conversation, conversation_id)
    if conversation is None:
        raise _api_error(404, "CONVERSATION_NOT_FOUND")

    # This check deliberately precedes active-state validation so a lost HTTP
    # response can retry safely after the transcript has already been frozen.
    if conversation.status == "ended":
        # End the initial read transaction before starting the replay read.
        db.rollback()
        current = db.get(models.Conversation, conversation_id)
        assert current is not None
        return _ended_replay_or_error(
            db,
            conversation=current,
            expected_last_message_id=expected_last_message_id,
        )
    if conversation.status != "active":
        raise _api_error(409, "CONVERSATION_CHANGED")

    observed_revision = conversation.revision
    # Do not upgrade the observation transaction into a writer.  A fresh
    # conditional UPDATE is SQLite's serialization boundary with chat's first
    # lease CAS write.
    db.rollback()

    try:
        lock = db.execute(
            update(models.Conversation)
            .where(
                models.Conversation.id == conversation_id,
                models.Conversation.status == "active",
                models.Conversation.revision == observed_revision,
            )
            .values(revision=models.Conversation.revision)
        )
        if lock.rowcount != 1:
            db.rollback()
            current = db.get(models.Conversation, conversation_id)
            if current is not None and current.status == "ended":
                return _ended_replay_or_error(
                    db,
                    conversation=current,
                    expected_last_message_id=expected_last_message_id,
                )
            raise _api_error(409, "CONVERSATION_CHANGED")

        conversation = db.get(
            models.Conversation,
            conversation_id,
            populate_existing=True,
        )
        if conversation is None or conversation.status != "active":
            raise _api_error(409, "CONVERSATION_CHANGED")
        last_message_id = _last_message_id(db, conversation.id)
        if last_message_id is None:
            raise _api_error(409, "CONVERSATION_EMPTY")
        if last_message_id != expected_last_message_id:
            raise _api_error(409, "CONVERSATION_CHANGED")

        conversation.status = "ended"
        conversation.end_reason = conversation.pending_end_reason or "manual"
        conversation.ended_at = now
        conversation.frozen_last_message_id = last_message_id
        conversation.revision += 1
        job = models.AnalysisJob(
            conversation_id=conversation.id,
            frozen_last_message_id=last_message_id,
            status="pending",
            available_at=now,
            created_at=now,
            updated_at=now,
        )
        db.add(job)
        db.flush()
        response = _completion_response(
            db,
            conversation=conversation,
            job=job,
            replayed=False,
        )
        db.commit()
        return response
    except APIError:
        db.rollback()
        raise
    except IntegrityError:
        # A concurrent finisher may have committed the unique job first.  Once
        # rolled back, reread its durable result and apply normal replay rules.
        db.rollback()
        current = db.get(models.Conversation, conversation_id)
        if current is not None and current.status == "ended":
            if current.frozen_last_message_id != expected_last_message_id:
                db.rollback()
                raise _api_error(409, "CONVERSATION_CHANGED")
            job = db.scalar(
                select(models.AnalysisJob).where(
                    models.AnalysisJob.conversation_id == current.id
                )
            )
            if (
                job is not None
                and job.frozen_last_message_id == expected_last_message_id
                and current.ended_at is not None
            ):
                response = _completion_response(
                    db,
                    conversation=current,
                    job=job,
                    replayed=True,
                )
                db.rollback()
                return response
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
