"""Atomic conversation freeze and durable analysis-job creation."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
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
        completed_at=conversation.ended_at,
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
        raise _api_error(409, "CONVERSATION_CHANGED")
    job = db.scalar(
        select(models.AnalysisJob).where(
            models.AnalysisJob.conversation_id == conversation.id
        )
    )
    if job is None or job.frozen_last_message_id != conversation.frozen_last_message_id:
        raise _api_error(500, "INTERNAL_ERROR")
    return _completion_response(
        db,
        conversation=conversation,
        job=job,
        replayed=True,
    )


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
        return _ended_replay_or_error(
            db,
            conversation=conversation,
            expected_last_message_id=expected_last_message_id,
        )
    if conversation.status != "active":
        raise _api_error(409, "CONVERSATION_CHANGED")

    last_message_id = _last_message_id(db, conversation.id)
    if last_message_id is None:
        raise _api_error(409, "CONVERSATION_EMPTY")
    if last_message_id != expected_last_message_id:
        raise _api_error(409, "CONVERSATION_CHANGED")

    try:
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
    except IntegrityError:
        # A concurrent finisher may have committed the unique job first.  Once
        # rolled back, reread its durable result and apply normal replay rules.
        db.rollback()
        current = db.get(models.Conversation, conversation_id)
        if current is None:
            raise _api_error(404, "CONVERSATION_NOT_FOUND")
        if current.status == "ended":
            return _ended_replay_or_error(
                db,
                conversation=current,
                expected_last_message_id=expected_last_message_id,
            )
        raise _api_error(409, "CONVERSATION_CHANGED")
    except Exception:
        db.rollback()
        raise
