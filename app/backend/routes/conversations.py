"""Public child conversation recovery and idempotent chat routes."""
from __future__ import annotations

import logging
from datetime import timezone
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from .. import ai_engine, models, schemas
from ..api_errors import APIError
from ..auth import require_teacher_session
from ..business_time import BusinessClock
from ..database import SETTINGS, get_db
from ..services.analysis import retry_analysis
from ..services.chat import (
    FIXED_MAX_ROUNDS_REPLY,
    build_chat_context,
    claim_chat_request,
    commit_chat_success,
    record_chat_failure,
)
from ..services.completion import complete_conversation
from ..services.history import list_conversation_history, search_conversations
from ..services.reviews import get_review_detail, list_review_queue, save_review


logger = logging.getLogger("duck_diary.chat")
router = APIRouter()
BUSINESS_CLOCK = BusinessClock(SETTINGS.business_timezone)


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
    now = BUSINESS_CLOCK.utc_now()
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
        now=BUSINESS_CLOCK.utc_now(),
    )


@router.get(
    "/api/conversations",
    response_model=list[schemas.ConversationQueueItem],
)
def review_queue(
    queue: Literal["pending", "processing", "failed"],
    db: Session = Depends(get_db),
    _teacher: models.TeacherSession = Depends(require_teacher_session),
) -> list[schemas.ConversationQueueItem]:
    return list_review_queue(db, queue=queue)


def _history_query(request: Request) -> tuple[int, int | None, int | None]:
    allowed = {"limit", "child_id", "before_id"}
    pairs = request.query_params.multi_items()
    keys = [key for key, _value in pairs]
    invalid = sorted({key for key in keys if key not in allowed})
    duplicates = sorted({key for key in allowed if keys.count(key) > 1})
    if invalid or duplicates:
        fields = {
            f"query.{key}": ["不支持或重复的查询参数"]
            for key in [*invalid, *duplicates]
        }
        raise APIError(422, "VALIDATION_ERROR", "请求字段校验失败", fields)

    values = dict(pairs)

    def positive(name: str, default: int | None = None) -> int | None:
        raw = values.get(name)
        if raw is None:
            return default
        try:
            parsed = int(raw)
        except (TypeError, ValueError):
            parsed = 0
        maximum = 50 if name == "limit" else None
        if parsed < 1 or (maximum is not None and parsed > maximum):
            raise APIError(
                422,
                "VALIDATION_ERROR",
                "请求字段校验失败",
                {f"query.{name}": ["参数超出允许范围"]},
            )
        return parsed

    return positive("limit", 20), positive("child_id"), positive("before_id")


@router.get(
    "/api/conversations/history",
    response_model=schemas.ConversationHistoryPage,
)
def conversation_history(
    request: Request,
    db: Session = Depends(get_db),
    _teacher: models.TeacherSession = Depends(require_teacher_session),
) -> schemas.ConversationHistoryPage:
    limit, child_id, before_id = _history_query(request)
    return list_conversation_history(
        db,
        limit=limit,
        child_id=child_id,
        before_id=before_id,
    )


@router.post(
    "/api/conversations/search",
    response_model=schemas.ConversationSearchPage,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": schemas.ConversationSearchRequest.model_json_schema()
                }
            },
        }
    },
)
async def conversation_search(
    request: Request,
    db: Session = Depends(get_db),
    _teacher: models.TeacherSession = Depends(require_teacher_session),
) -> schemas.ConversationSearchPage:
    if request.scope.get("query_string", b""):
        raise APIError(
            422,
            "VALIDATION_ERROR",
            "请求字段校验失败",
            {"query": ["此接口不接受查询参数"]},
        )
    try:
        raw_payload = await request.json()
    except (TypeError, ValueError):
        raise APIError(
            422,
            "VALIDATION_ERROR",
            "请求字段校验失败",
            {"body": ["请求体必须是有效 JSON"]},
        ) from None
    try:
        payload = schemas.ConversationSearchRequest.model_validate(raw_payload)
    except ValidationError as exc:
        fields: dict[str, list[str]] = {}
        for item in exc.errors():
            location = ".".join(str(part) for part in item["loc"])
            key = f"body.{location}" if location else "body"
            fields.setdefault(key, []).append(item["msg"])
        raise APIError(
            422,
            "VALIDATION_ERROR",
            "请求字段校验失败",
            fields,
        ) from None
    return await run_in_threadpool(search_conversations, db, payload)


@router.get(
    "/api/conversations/{conversation_id}",
    response_model=schemas.ConversationDetail,
)
def review_detail(
    conversation_id: int,
    db: Session = Depends(get_db),
    _teacher: models.TeacherSession = Depends(require_teacher_session),
) -> schemas.ConversationDetail:
    return get_review_detail(db, conversation_id=conversation_id)


@router.put(
    "/api/conversations/{conversation_id}/review",
    response_model=schemas.ReviewResponse,
)
def put_review(
    conversation_id: int,
    payload: schemas.ReviewRequest,
    db: Session = Depends(get_db),
    _teacher: models.TeacherSession = Depends(require_teacher_session),
) -> schemas.ReviewResponse:
    return save_review(
        db,
        conversation_id=conversation_id,
        payload=payload,
        now=BUSINESS_CLOCK.utc_now(),
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
    business_now = BUSINESS_CLOCK.business_now()
    now = business_now.astimezone(timezone.utc).replace(tzinfo=None)
    claim = claim_chat_request(
        db,
        payload,
        now=now,
        business_date=business_now.date(),
    )
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
                now=now,
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
                now=now,
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
            now=now,
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
            now=now,
        )
        raise APIError(
            500,
            "INTERNAL_ERROR",
            "服务暂时不可用，请稍后重试",
            retryable=True,
        )
