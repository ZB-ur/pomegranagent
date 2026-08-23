"""Idempotent child-chat claim, context, and commit operations."""
from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models, schemas
from ..api_errors import APIError


FIXED_MAX_ROUNDS_REPLY = "谢谢你今天的分享，鸭鸭日记本都记好啦！我们下次再见～"

_ERROR_MESSAGES = {
    "ACTIVE_CONVERSATION_EXISTS": "该幼儿已有进行中的会话",
    "CHAT_UPSTREAM_FAILED": "对话服务暂时不可用，请稍后重试",
    "CHILD_NOT_FOUND": "幼儿不存在或已停用",
    "CONVERSATION_CHANGED": "会话内容已经变化，请先恢复最新内容",
    "CONVERSATION_CHILD_MISMATCH": "会话不属于该幼儿",
    "CONVERSATION_COMPLETION_REQUIRED": "本次对话已结束，请先完成保存",
    "CONVERSATION_NOT_FOUND": "活动会话不存在",
    "IDEMPOTENCY_CONFLICT": "请求 ID 与已有提交不一致",
    "REQUEST_IN_PROGRESS": "请求正在处理中",
}


@dataclass(frozen=True)
class ChatClaim:
    """One owner-bound attempt to turn a durable request into a message pair."""

    request_id: str
    conversation_id: int
    replay: schemas.ChatResponse | None
    lease_owner: str | None
    attempt_count: int


@dataclass(frozen=True)
class ChatContext:
    """Immutable provider input built before ending the read transaction."""

    child: dict[str, str | None]
    conversation_id: int
    history: tuple[dict[str, str], ...]
    recent_summary: str
    ducks_info: str
    round: int


def payload_hash(payload: schemas.ChatRequest) -> str:
    """Hash only the normalized semantic request payload, never its request ID."""
    canonical = json.dumps(
        {
            "child_id": payload.child_id,
            "conversation_id": payload.conversation_id,
            "max_rounds": payload.max_rounds,
            "text": payload.text,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _api_error(status_code: int, code: str, *, retryable: bool = False) -> APIError:
    return APIError(
        status_code,
        code,
        _ERROR_MESSAGES.get(code, "请求处理失败"),
        retryable=retryable,
    )


def _request_record(db: Session, request_id: str) -> models.ChatRequestRecord | None:
    return db.scalar(
        select(models.ChatRequestRecord)
        .where(models.ChatRequestRecord.request_id == request_id)
        .execution_options(populate_existing=True)
    )


def _last_message_id(db: Session, conversation_id: int) -> int | None:
    return db.scalar(
        select(models.Message.id)
        .where(models.Message.conversation_id == conversation_id)
        .order_by(models.Message.id.desc())
        .limit(1)
    )


def _lease_owner() -> str:
    return secrets.token_hex(32)


def _claim_from_existing(
    db: Session,
    record: models.ChatRequestRecord,
    *,
    expected_hash: str,
    now: datetime,
    lease_seconds: int,
) -> ChatClaim:
    if record.payload_hash != expected_hash:
        raise _api_error(409, "IDEMPOTENCY_CONFLICT")
    if record.status == "succeeded":
        if not record.response_json:
            raise _api_error(500, "INTERNAL_ERROR", retryable=True)
        return ChatClaim(
            request_id=record.request_id,
            conversation_id=record.conversation_id or 0,
            replay=schemas.ChatResponse.model_validate_json(record.response_json),
            lease_owner=None,
            attempt_count=record.attempt_count,
        )
    if record.status == "processing" and (
        record.lease_expires_at is None or record.lease_expires_at > now
    ):
        raise _api_error(409, "REQUEST_IN_PROGRESS", retryable=True)
    if record.status not in {"failed", "processing"}:
        raise _api_error(500, "INTERNAL_ERROR", retryable=True)

    observed_attempt_count = record.attempt_count
    owner = _lease_owner()
    reclaimed = db.execute(
        update(models.ChatRequestRecord)
        .where(
            models.ChatRequestRecord.request_id == record.request_id,
            models.ChatRequestRecord.payload_hash == expected_hash,
            models.ChatRequestRecord.attempt_count == observed_attempt_count,
            or_(
                models.ChatRequestRecord.status == "failed",
                and_(
                    models.ChatRequestRecord.status == "processing",
                    models.ChatRequestRecord.lease_expires_at <= now,
                ),
            ),
        )
        .values(
            status="processing",
            attempt_count=observed_attempt_count + 1,
            available_at=now,
            lease_owner=owner,
            lease_expires_at=now + timedelta(seconds=lease_seconds),
            last_error_code=None,
            last_error_message=None,
            finished_at=None,
            updated_at=now,
        )
    )
    if reclaimed.rowcount != 1:
        db.rollback()
        current = _request_record(db, record.request_id)
        if current is None:
            raise _api_error(500, "INTERNAL_ERROR", retryable=True)
        return _claim_from_existing(
            db,
            current,
            expected_hash=expected_hash,
            now=now,
            lease_seconds=lease_seconds,
        )
    db.commit()
    return ChatClaim(
        request_id=record.request_id,
        conversation_id=record.conversation_id or 0,
        replay=None,
        lease_owner=owner,
        attempt_count=observed_attempt_count + 1,
    )


def _active_child_or_error(db: Session, child_id: int) -> models.Child:
    child = db.get(models.Child, child_id)
    if child is None or not child.active:
        raise _api_error(404, "CHILD_NOT_FOUND")
    return child


def _conversation_for_new_claim(
    db: Session,
    payload: schemas.ChatRequest,
    *,
    now: datetime,
) -> models.Conversation:
    _active_child_or_error(db, payload.child_id)
    if payload.conversation_id is not None:
        conversation = db.get(models.Conversation, payload.conversation_id)
        if conversation is None or conversation.status != "active":
            raise _api_error(404, "CONVERSATION_NOT_FOUND")
        if conversation.child_id != payload.child_id:
            raise _api_error(409, "CONVERSATION_CHILD_MISMATCH")
        if conversation.pending_end_reason is not None:
            raise _api_error(409, "CONVERSATION_COMPLETION_REQUIRED")
        return conversation

    current = db.scalar(
        select(models.Conversation).where(
            models.Conversation.child_id == payload.child_id,
            models.Conversation.status == "active",
        )
    )
    if current is not None:
        if current.pending_end_reason is not None:
            raise _api_error(409, "CONVERSATION_COMPLETION_REQUIRED")
        raise _api_error(409, "ACTIVE_CONVERSATION_EXISTS")
    conversation = models.Conversation(
        child_id=payload.child_id,
        date=now.date().isoformat(),
        status="active",
    )
    db.add(conversation)
    db.flush()
    return conversation


def _active_race_error(db: Session, child_id: int) -> APIError:
    current = db.scalar(
        select(models.Conversation).where(
            models.Conversation.child_id == child_id,
            models.Conversation.status == "active",
        )
    )
    if current is not None and current.pending_end_reason is not None:
        return _api_error(409, "CONVERSATION_COMPLETION_REQUIRED")
    return _api_error(409, "ACTIVE_CONVERSATION_EXISTS")


def claim_chat_request(
    db: Session,
    payload: schemas.ChatRequest,
    *,
    now: datetime,
    lease_seconds: int = 45,
) -> ChatClaim:
    """Claim a request and, for first turns, create its active conversation atomically."""
    request_id = str(payload.request_id)
    expected_hash = payload_hash(payload)
    existing = _request_record(db, request_id)
    if existing is not None:
        return _claim_from_existing(
            db,
            existing,
            expected_hash=expected_hash,
            now=now,
            lease_seconds=lease_seconds,
        )

    try:
        conversation = _conversation_for_new_claim(db, payload, now=now)
        owner = _lease_owner()
        record = models.ChatRequestRecord(
            request_id=request_id,
            child_id=payload.child_id,
            conversation_id=conversation.id,
            base_last_message_id=_last_message_id(db, conversation.id),
            payload_hash=expected_hash,
            status="processing",
            attempt_count=1,
            available_at=now,
            lease_owner=owner,
            lease_expires_at=now + timedelta(seconds=lease_seconds),
            started_at=now,
            created_at=now,
            updated_at=now,
        )
        db.add(record)
        db.commit()
    except IntegrityError:
        # The active-conversation or request-ID unique guard won a concurrent race.
        db.rollback()
        existing = _request_record(db, request_id)
        if existing is not None:
            return _claim_from_existing(
                db,
                existing,
                expected_hash=expected_hash,
                now=now,
                lease_seconds=lease_seconds,
            )
        if payload.conversation_id is None:
            raise _active_race_error(db, payload.child_id)
        raise

    return ChatClaim(
        request_id=request_id,
        conversation_id=conversation.id,
        replay=None,
        lease_owner=owner,
        attempt_count=1,
    )


def _claim_update(
    db: Session,
    claim: ChatClaim,
    *,
    now: datetime,
    values: dict[str, object],
) -> bool:
    """Compare-and-set one exact processing attempt, never just its request ID."""
    result = db.execute(
        update(models.ChatRequestRecord)
        .where(
            models.ChatRequestRecord.request_id == claim.request_id,
            models.ChatRequestRecord.status == "processing",
            models.ChatRequestRecord.lease_owner == claim.lease_owner,
            models.ChatRequestRecord.attempt_count == claim.attempt_count,
            models.ChatRequestRecord.lease_expires_at.is_not(None),
            models.ChatRequestRecord.lease_expires_at > now,
        )
        .values(**values)
    )
    return result.rowcount == 1


def _mark_claim_failed(
    db: Session,
    claim: ChatClaim,
    *,
    code: str,
    now: datetime,
) -> bool:
    return _claim_update(
        db,
        claim,
        now=now,
        values={
            "status": "failed",
            "available_at": now,
            "lease_owner": None,
            "lease_expires_at": None,
            "last_error_code": code,
            "last_error_message": _ERROR_MESSAGES.get(code, "请求处理失败"),
            "finished_at": now,
            "updated_at": now,
        },
    )


def _fail_owned_claim_and_raise(
    db: Session,
    claim: ChatClaim,
    *,
    code: str,
    now: datetime,
    status_code: int,
    retryable: bool = False,
) -> None:
    if not _mark_claim_failed(db, claim, code=code, now=now):
        db.rollback()
        raise _api_error(409, "REQUEST_IN_PROGRESS", retryable=True)
    db.commit()
    raise _api_error(status_code, code, retryable=retryable)


def build_chat_context(
    db: Session,
    claim: ChatClaim,
    payload: schemas.ChatRequest,
) -> ChatContext:
    """Build provider input without inserting the pending child message."""
    record = _request_record(db, claim.request_id)
    if record is None:
        raise _api_error(409, "CONVERSATION_CHANGED")
    child = _active_child_or_error(db, record.child_id)
    conversation = db.get(models.Conversation, claim.conversation_id)
    if (
        conversation is None
        or conversation.status != "active"
        or conversation.child_id != child.id
    ):
        raise _api_error(409, "CONVERSATION_CHANGED")
    if conversation.pending_end_reason is not None:
        raise _api_error(409, "CONVERSATION_COMPLETION_REQUIRED")
    if _last_message_id(db, conversation.id) != record.base_last_message_id:
        raise _api_error(409, "CONVERSATION_CHANGED")

    messages = db.scalars(
        select(models.Message)
        .where(models.Message.conversation_id == conversation.id)
        .order_by(models.Message.id)
    ).all()
    history = tuple(
        {
            "role": "user" if message.role == "child" else "assistant",
            "text": message.text,
        }
        for message in [*messages, models.Message(role="child", text=payload.text)]
    )
    recent_summary = " / ".join(item["text"] for item in history[-6:])
    ducks = db.scalars(
        select(models.Duck).where(models.Duck.active.is_(True)).order_by(models.Duck.id)
    ).all()
    duck_parts: list[str] = []
    for duck in ducks:
        archive = db.scalar(
            select(models.DuckArchive).where(models.DuckArchive.duck_id == duck.id)
        )
        summary = archive.summary if archive and archive.summary else None
        duck_parts.append(
            f"{duck.name}：{duck.status or '暂无状态'}"
            + (f"；档案：{summary}" if summary else "")
        )
    return ChatContext(
        child={"name": child.name, "nickname": child.nickname},
        conversation_id=conversation.id,
        history=history,
        recent_summary=recent_summary,
        ducks_info="；".join(duck_parts),
        round=sum(message.role == "child" for message in messages) + 1,
    )


def commit_chat_success(
    db: Session,
    *,
    claim: ChatClaim,
    payload: schemas.ChatRequest,
    reply: str,
    ended: bool,
    end_reason: Literal["max_rounds", "complete"] | None,
    now: datetime,
) -> schemas.ChatResponse:
    """Commit exactly one message pair only if this lease still owns the base state."""
    # This no-op state update is deliberately the first write.  It is the lease
    # compare-and-set and, on SQLite, serializes later transcript validation and
    # the paired-message write against another committing claimant.
    if not _claim_update(db, claim, now=now, values={"updated_at": now}):
        db.rollback()
        raise _api_error(409, "REQUEST_IN_PROGRESS", retryable=True)
    record = _request_record(db, claim.request_id)
    assert record is not None

    child = db.get(models.Child, record.child_id)
    if child is None or not child.active:
        _fail_owned_claim_and_raise(
            db,
            claim,
            code="CHILD_NOT_FOUND",
            now=now,
            status_code=404,
        )
    conversation = db.get(models.Conversation, claim.conversation_id)
    if (
        conversation is None
        or conversation.status != "active"
        or conversation.child_id != record.child_id
        or _last_message_id(db, claim.conversation_id) != record.base_last_message_id
    ):
        _fail_owned_claim_and_raise(
            db,
            claim,
            code="CONVERSATION_CHANGED",
            now=now,
            status_code=409,
        )
    if conversation.pending_end_reason is not None:
        _fail_owned_claim_and_raise(
            db,
            claim,
            code="CONVERSATION_COMPLETION_REQUIRED",
            now=now,
            status_code=409,
        )
    if (ended and end_reason not in {"max_rounds", "complete"}) or (
        not ended and end_reason is not None
    ):
        raise ValueError("invalid chat end semantics")

    round_number = db.scalar(
        select(func.count(models.Message.id)).where(
            models.Message.conversation_id == conversation.id,
            models.Message.role == "child",
        )
    ) + 1
    child_message = models.Message(
        conversation_id=conversation.id,
        role="child",
        text=payload.text,
    )
    diary_message = models.Message(
        conversation_id=conversation.id,
        role="diary",
        text=reply,
    )
    db.add_all([child_message, diary_message])
    db.flush()
    if ended:
        conversation.pending_end_reason = end_reason
    response = schemas.ChatResponse(
        request_id=payload.request_id,
        conversation_id=conversation.id,
        child_message_id=child_message.id,
        diary_message_id=diary_message.id,
        reply=reply,
        round=round_number,
        ended=ended,
        end_reason=end_reason,
        replayed=False,
    )
    if not _claim_update(
        db,
        claim,
        now=now,
        values={
            "child_message_id": child_message.id,
            "diary_message_id": diary_message.id,
            "status": "succeeded",
            "lease_owner": None,
            "lease_expires_at": None,
            "last_error_code": None,
            "last_error_message": None,
            "response_json": json.dumps(
                response.model_dump(mode="json"),
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
            "finished_at": now,
            "updated_at": now,
        },
    ):
        db.rollback()
        raise _api_error(409, "REQUEST_IN_PROGRESS", retryable=True)
    db.commit()
    return response


def record_chat_failure(
    db: Session,
    *,
    claim: ChatClaim,
    code: str,
    now: datetime,
) -> None:
    """Persist a sanitized failure only while this exact lease still owns the request."""
    if not _mark_claim_failed(db, claim, code=code, now=now):
        db.rollback()
        return
    db.commit()
