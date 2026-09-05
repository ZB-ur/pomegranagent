"""Idempotent child-chat claim, context, and commit operations."""
from __future__ import annotations

import hashlib
import json
import logging
import math
import secrets
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Iterator, Literal

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models, schemas
from ..api_errors import APIError


FIXED_MAX_ROUNDS_REPLY = "谢谢你今天的分享，鸭鸭日记本都记好啦！我们下次再见～"
logger = logging.getLogger("duck_diary.chat")

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
    lease_expires_at: datetime | None


@dataclass(frozen=True)
class ChatContext:
    """Immutable provider input built before ending the read transaction."""

    child: dict[str, str | None]
    conversation_id: int
    history: tuple[dict[str, str], ...]
    recent_summary: str
    ducks_info: str
    round: int


class ChatLeaseGuard:
    """Thread-safe lease deadline and provider retry fence for one chat attempt."""

    def __init__(self, lease_expires_at: datetime) -> None:
        self._lease_expires_at = _database_utc(lease_expires_at)
        self._lost = threading.Event()
        self._lock = threading.RLock()

    def is_set(self) -> bool:
        return self._lost.is_set()

    def mark_lost(self) -> None:
        with self._lock:
            self._lost.set()

    def expires_at(self) -> datetime:
        with self._lock:
            return self._lease_expires_at

    def record_renewal(self, *, now: datetime, lease_seconds: float) -> bool:
        with self._lock:
            if self._lost.is_set():
                return False
            self._lease_expires_at = _database_utc(now) + timedelta(
                seconds=lease_seconds
            )
            return True

    @contextmanager
    def renewal_fence(self) -> Iterator[None]:
        """Serialize a durable renewal and its in-memory publication with retries."""
        with self._lock:
            yield

    def retry_allowed(self, clock: Callable[[], datetime]) -> bool:
        with self._lock:
            if self._lost.is_set():
                return False
            try:
                now = _database_utc(clock())
            except Exception:
                self._lost.set()
                return False
            if now >= self._lease_expires_at:
                self._lost.set()
                return False
            return True


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


def _database_utc(value: datetime) -> datetime:
    """Use naive UTC for SQLite while accepting aware clocks at boundaries."""
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _terminal_lease_time(
    db: Session,
    *,
    now: datetime,
    lease_now: datetime | None = None,
    lease_clock: Callable[[], datetime] | None = None,
) -> datetime:
    """Sample a terminal lease clock only after owning SQLite's writer slot."""
    if lease_now is not None and lease_clock is not None:
        raise ValueError("lease_now and lease_clock are mutually exclusive")
    if lease_clock is None:
        return _database_utc(lease_now or now)

    try:
        connection = db.connection()
        if connection.dialect.name != "sqlite":
            raise RuntimeError("chat terminal lease checks require SQLite")
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        return _database_utc(lease_clock())
    except Exception:
        db.rollback()
        raise


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
            lease_expires_at=None,
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
        lease_expires_at=now + timedelta(seconds=lease_seconds),
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
    business_date: date,
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

    # End the stale observation transaction before the first write.  This
    # conditional no-op is the shared SQLite serialization point with child
    # deactivation: either this claimant holds the active child while it
    # creates its conversation/request, or deactivation has already made the
    # child unavailable and no partial first-turn records are written.
    db.rollback()
    active_child_lock = db.execute(
        update(models.Child)
        .where(
            models.Child.id == payload.child_id,
            models.Child.active.is_(True),
        )
        .values(active=models.Child.active)
    )
    if active_child_lock.rowcount != 1:
        db.rollback()
        _active_child_or_error(db, payload.child_id)
        raise _api_error(404, "CHILD_NOT_FOUND")
    conversation = models.Conversation(
        child_id=payload.child_id,
        date=business_date.isoformat(),
        status="active",
        started_at=now,
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
    business_date: date,
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
        conversation = _conversation_for_new_claim(
            db,
            payload,
            now=now,
            business_date=business_date,
        )
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
        lease_expires_at=now + timedelta(seconds=lease_seconds),
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


def renew_chat_request_lease(
    session_factory: Callable[[], Session],
    *,
    claim: ChatClaim,
    clock: Callable[[], datetime],
    lease_seconds: float,
) -> datetime | None:
    """Extend one exact live lease and return its new naive-UTC expiry."""
    if claim.lease_owner is None:
        return None
    db = session_factory()
    try:
        connection = db.connection()
        if connection.dialect.name != "sqlite":
            raise RuntimeError("chat lease renewal requires SQLite")
        # Acquire the single SQLite writer slot before sampling time so a busy
        # wait cannot turn a pre-expiry timestamp into a stale renewal.
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        db_now = _database_utc(clock())
        renewed_until = db_now + timedelta(seconds=lease_seconds)
        renewed = db.execute(
            update(models.ChatRequestRecord)
            .where(
                models.ChatRequestRecord.request_id == claim.request_id,
                models.ChatRequestRecord.status == "processing",
                models.ChatRequestRecord.lease_owner == claim.lease_owner,
                models.ChatRequestRecord.attempt_count == claim.attempt_count,
                models.ChatRequestRecord.lease_expires_at.is_not(None),
                models.ChatRequestRecord.lease_expires_at > db_now,
            )
            .values(
                lease_expires_at=renewed_until,
                updated_at=db_now,
            )
        )
        if renewed.rowcount == 1:
            db.commit()
            return renewed_until
        db.rollback()
        return None
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _run_chat_lease_heartbeat(
    session_factory: Callable[[], Session],
    *,
    claim: ChatClaim,
    clock: Callable[[], datetime],
    lease_seconds: float,
    interval_seconds: float,
    stop_event: threading.Event,
    lease_guard: ChatLeaseGuard,
) -> None:
    def mark_lost(message: str) -> None:
        lease_guard.mark_lost()
        logger.warning(
            "%s request_id=%s attempt_count=%s",
            message,
            claim.request_id,
            claim.attempt_count,
        )

    while not stop_event.wait(interval_seconds):
        try:
            heartbeat_now = _database_utc(clock())
        except Exception as exc:
            logger.warning(
                "chat lease heartbeat clock failure request_id=%s attempt_count=%s error_type=%s",
                claim.request_id,
                claim.attempt_count,
                type(exc).__name__,
            )
            mark_lost("chat lease clock unavailable during provider call")
            return
        lease_expires_at = lease_guard.expires_at()
        if heartbeat_now >= lease_expires_at:
            mark_lost("chat lease expired before heartbeat renewal")
            return
        with lease_guard.renewal_fence():
            try:
                renewed_until = renew_chat_request_lease(
                    session_factory,
                    claim=claim,
                    clock=clock,
                    lease_seconds=lease_seconds,
                )
            except Exception as exc:
                logger.warning(
                    "chat lease heartbeat failure request_id=%s attempt_count=%s error_type=%s",
                    claim.request_id,
                    claim.attempt_count,
                    type(exc).__name__,
                )
                try:
                    heartbeat_finished_at = _database_utc(clock())
                except Exception as clock_exc:
                    logger.warning(
                        "chat lease heartbeat clock failure request_id=%s attempt_count=%s error_type=%s",
                        claim.request_id,
                        claim.attempt_count,
                        type(clock_exc).__name__,
                    )
                    mark_lost("chat lease clock unavailable after heartbeat failure")
                    return
                if heartbeat_finished_at >= lease_guard.expires_at():
                    mark_lost("chat lease expired while heartbeat unavailable")
                    return
                continue
            if renewed_until is None:
                mark_lost("chat lease lost during provider call")
                return
            try:
                heartbeat_finished_at = _database_utc(clock())
            except Exception as exc:
                logger.warning(
                    "chat lease heartbeat clock failure request_id=%s attempt_count=%s error_type=%s",
                    claim.request_id,
                    claim.attempt_count,
                    type(exc).__name__,
                )
                mark_lost("chat lease clock unavailable after heartbeat renewal")
                return
            if heartbeat_finished_at >= renewed_until:
                mark_lost("chat lease expired during heartbeat renewal")
                return
            if not lease_guard.record_renewal(
                now=renewed_until - timedelta(seconds=lease_seconds),
                lease_seconds=lease_seconds,
            ):
                return


@contextmanager
def chat_lease_heartbeat(
    session_factory: Callable[[], Session],
    *,
    claim: ChatClaim,
    clock: Callable[[], datetime],
    lease_seconds: float = 45,
    heartbeat_interval_seconds: float | None = None,
) -> Iterator[ChatLeaseGuard]:
    """Keep one provider attempt leased and join its writer before final persistence."""
    interval = (
        lease_seconds / 3
        if heartbeat_interval_seconds is None
        else heartbeat_interval_seconds
    )
    if (
        not math.isfinite(lease_seconds)
        or not math.isfinite(interval)
        or lease_seconds <= 0
        or interval <= 0
        or interval > lease_seconds / 3
    ):
        raise ValueError(
            "chat heartbeat interval must be finite, positive, and no more than lease/3"
        )
    if claim.lease_expires_at is None:
        raise ValueError("chat heartbeat requires an active lease expiry")
    stop_event = threading.Event()
    lease_guard = ChatLeaseGuard(claim.lease_expires_at)
    heartbeat = threading.Thread(
        target=_run_chat_lease_heartbeat,
        kwargs={
            "session_factory": session_factory,
            "claim": claim,
            "clock": clock,
            "lease_seconds": lease_seconds,
            "interval_seconds": interval,
            "stop_event": stop_event,
            "lease_guard": lease_guard,
        },
        name=f"chat-lease-heartbeat-{claim.request_id}",
        daemon=True,
    )
    heartbeat.start()
    try:
        yield lease_guard
    finally:
        stop_event.set()
        heartbeat.join()


def _mark_claim_failed(
    db: Session,
    claim: ChatClaim,
    *,
    code: str,
    now: datetime,
    lease_now: datetime | None = None,
    lease_clock: Callable[[], datetime] | None = None,
) -> bool:
    return _claim_update(
        db,
        claim,
        now=_terminal_lease_time(
            db,
            now=now,
            lease_now=lease_now,
            lease_clock=lease_clock,
        ),
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
    lease_now: datetime | None = None,
    status_code: int,
    retryable: bool = False,
) -> None:
    if not _mark_claim_failed(
        db,
        claim,
        code=code,
        now=now,
        lease_now=lease_now,
    ):
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
    lease_now: datetime | None = None,
    lease_clock: Callable[[], datetime] | None = None,
) -> schemas.ChatResponse:
    """Commit exactly one message pair only if this lease still owns the base state."""
    # This no-op state update is deliberately the first write.  It is the lease
    # compare-and-set and, on SQLite, serializes later transcript validation and
    # the paired-message write against another committing claimant.
    lease_check_at = _terminal_lease_time(
        db,
        now=now,
        lease_now=lease_now,
        lease_clock=lease_clock,
    )
    if not _claim_update(db, claim, now=lease_check_at, values={"updated_at": now}):
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
            lease_now=lease_check_at,
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
            lease_now=lease_check_at,
            status_code=409,
        )
    if conversation.pending_end_reason is not None:
        _fail_owned_claim_and_raise(
            db,
            claim,
            code="CONVERSATION_COMPLETION_REQUIRED",
            now=now,
            lease_now=lease_check_at,
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
        created_at=now,
    )
    diary_message = models.Message(
        conversation_id=conversation.id,
        role="diary",
        text=reply,
        created_at=now,
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
        now=lease_check_at,
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
    lease_now: datetime | None = None,
    lease_clock: Callable[[], datetime] | None = None,
) -> bool:
    """Persist a sanitized failure only while this exact lease still owns the request."""
    if not _mark_claim_failed(
        db,
        claim,
        code=code,
        now=now,
        lease_now=lease_now,
        lease_clock=lease_clock,
    ):
        db.rollback()
        return False
    db.commit()
    return True
