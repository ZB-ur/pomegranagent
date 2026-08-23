"""Public child conversation recovery and idempotent chat routes."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import ai_engine, models, schemas
from ..api_errors import APIError
from ..auth import require_teacher_session
from ..database import get_db
from ..services.analysis import retry_analysis
from ..services.chat import (
    FIXED_MAX_ROUNDS_REPLY,
    build_chat_context,
    claim_chat_request,
    commit_chat_success,
    record_chat_failure,
)
from ..services.completion import complete_conversation


logger = logging.getLogger("duck_diary.chat")
router = APIRouter()


def _active_child_or_error(db: Session, child_id: int) -> models.Child:
    child = db.get(models.Child, child_id)
    if child is None or not child.active:
        raise APIError(404, "CHILD_NOT_FOUND", "幼儿不存在或已停用")
    return child


def _context_response(db: Session, child_id: int) -> schemas.ActiveConversationResponse:
    _active_child_or_error(db, child_id)
    conversation = db.scalar(
        select(models.Conversation).where(
            models.Conversation.child_id == child_id,
            models.Conversation.status == "active",
        )
    )
    if conversation is None:
        return schemas.ActiveConversationResponse(conversation=None)
    messages = db.scalars(
        select(models.Message)
        .where(models.Message.conversation_id == conversation.id)
        .order_by(models.Message.id)
    ).all()
    return schemas.ActiveConversationResponse(
        conversation=schemas.ActiveConversation(
            id=conversation.id,
            child_id=conversation.child_id,
            status="active",
            revision=conversation.revision,
            round=sum(message.role == "child" for message in messages),
            last_message_id=messages[-1].id if messages else None,
            messages=[
                schemas.ConversationMessage(
                    id=message.id,
                    role=message.role,
                    text=message.text,
                )
                for message in messages
            ],
        )
    )


@router.get(
    "/api/children/{child_id}/active-conversation",
    response_model=schemas.ActiveConversationResponse,
)
def get_active_conversation(
    child_id: int,
    db: Session = Depends(get_db),
) -> schemas.ActiveConversationResponse:
    return _context_response(db, child_id)


@router.post(
    "/api/conversations/{conversation_id}/complete",
    response_model=schemas.ConversationCompleteResponse,
)
def complete(
    conversation_id: int,
    payload: schemas.ConversationCompleteRequest,
    db: Session = Depends(get_db),
) -> schemas.ConversationCompleteResponse:
    now = datetime.now(timezone.utc)
    return complete_conversation(
        db,
        conversation_id=conversation_id,
        expected_last_message_id=payload.expected_last_message_id,
        now=now,
    )


@router.post(
    "/api/conversations/{conversation_id}/analysis/retry",
    response_model=schemas.AnalysisRetryResponse,
)
def retry_conversation_analysis(
    conversation_id: int,
    db: Session = Depends(get_db),
    _teacher: models.TeacherSession = Depends(require_teacher_session),
) -> schemas.AnalysisRetryResponse:
    return retry_analysis(
        db,
        conversation_id,
        now=datetime.now(timezone.utc),
    )


def _validated_ai_reply(result: object) -> tuple[str, bool, str | None]:
    if not isinstance(result, dict):
        raise ValueError("chat reply is not an object")
    reply = result.get("reply")
    ended = result.get("ended")
    end_reason = result.get("end_reason")
    if not isinstance(reply, str) or not reply.strip():
        raise ValueError("chat reply is blank")
    if type(ended) is not bool:
        raise ValueError("chat ended is not boolean")
    if ended and end_reason != "complete":
        raise ValueError("ended chat reply must use complete")
    if not ended and end_reason is not None:
        raise ValueError("continuing chat reply cannot have end reason")
    return reply.strip(), ended, end_reason


@router.post("/api/chat", response_model=schemas.ChatResponse)
def chat(
    payload: schemas.ChatRequest,
    db: Session = Depends(get_db),
) -> schemas.ChatResponse:
    now = datetime.utcnow()
    claim = claim_chat_request(db, payload, now=now)
    if claim.replay is not None:
        return claim.replay.model_copy(update={"replayed": True})

    try:
        try:
            context = build_chat_context(db, claim, payload)
        except APIError as exc:
            record_chat_failure(db, claim=claim, code=exc.code, now=now)
            raise

        # No transaction stays open while the external provider runs.
        db.rollback()
        if context.round >= payload.max_rounds:
            return commit_chat_success(
                db,
                claim=claim,
                payload=payload,
                reply=FIXED_MAX_ROUNDS_REPLY,
                ended=True,
                end_reason="max_rounds",
                now=datetime.utcnow(),
            )

        try:
            result = ai_engine.chat_reply(
                child=context.child,
                recent_summary=context.recent_summary,
                ducks_info=context.ducks_info,
                history=list(context.history),
                round_num=context.round,
                max_rounds=payload.max_rounds,
            )
            reply, ended, end_reason = _validated_ai_reply(result)
        except (httpx.HTTPError, TimeoutError, ConnectionError) as exc:
            logger.warning(
                "chat upstream failure request_id=%s error_type=%s",
                claim.request_id,
                type(exc).__name__,
            )
            record_chat_failure(
                db,
                claim=claim,
                code="CHAT_UPSTREAM_FAILED",
                now=datetime.utcnow(),
            )
            raise APIError(
                503,
                "CHAT_UPSTREAM_FAILED",
                "对话服务暂时不可用，请稍后重试",
                retryable=True,
            )

        return commit_chat_success(
            db,
            claim=claim,
            payload=payload,
            reply=reply,
            ended=ended,
            end_reason=end_reason,
            now=datetime.utcnow(),
        )
    except APIError:
        raise
    except Exception as exc:  # Exception messages can contain provider secrets; log only the type.
        db.rollback()
        logger.error(
            "chat programming failure request_id=%s error_type=%s",
            claim.request_id,
            type(exc).__name__,
        )
        record_chat_failure(
            db,
            claim=claim,
            code="CHAT_INTERNAL_FAILED",
            now=datetime.utcnow(),
        )
        raise APIError(
            500,
            "INTERNAL_ERROR",
            "服务暂时不可用，请稍后重试",
            retryable=True,
        )
