"""Contract tests for idempotent, recoverable child chat submissions."""
from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from threading import Event, Thread
from time import monotonic, sleep
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import func, select, update

from app.backend import ai_engine, models, schemas
from app.backend.api_errors import APIError
from app.backend.database import SessionLocal
from app.backend.routes import conversations as conversation_routes
from app.backend.services import chat as chat_service
from app.backend.services.chat import (
    claim_chat_request,
    commit_chat_success,
    payload_hash,
    record_chat_failure,
)


class FakeChatAI:
    """Small controllable stand-in for the external chat provider."""

    def __init__(self) -> None:
        self.call_count = 0
        self.calls: list[dict] = []
        self.on_call = None
        self.result: object = {
            "reply": "真棒！还有呢？",
            "ended": False,
            "end_reason": None,
        }

    def __call__(self, **kwargs):
        self.call_count += 1
        self.calls.append(kwargs)
        if self.on_call is not None:
            self.on_call()
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.fixture
def fake_chat_ai(monkeypatch) -> FakeChatAI:
    fake = FakeChatAI()
    monkeypatch.setattr(ai_engine, "chat_reply", fake)
    return fake


@pytest.fixture
def child_factory(db_session):
    def create(*, name: str = "小雨", nickname: str | None = "雨雨", active: bool = True):
        child = models.Child(name=name, nickname=nickname, active=active)
        db_session.add(child)
        db_session.commit()
        return child

    return create


def test_chat_writes_one_pair_after_ai_success(
    client,
    db_session,
    child_factory,
    fake_chat_ai,
):
    """Catches a handler that writes before AI success or omits replay metadata."""
    child = child_factory()
    active_duck = models.Duck(name="小黄", status="活泼", active=True)
    inactive_duck = models.Duck(name="小灰", status="已转园", active=False)
    db_session.add_all([active_duck, inactive_duck])
    db_session.commit()

    request_id = "0d8b9030-f5ec-47da-9418-28b33f26c0dc"
    response = client.post(
        "/api/chat",
        json={
            "request_id": request_id,
            "child_id": child.id,
            "text": "我喂了小黄",
            "conversation_id": None,
            "max_rounds": 3,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "request_id": request_id,
        "conversation_id": 1,
        "child_message_id": 1,
        "diary_message_id": 2,
        "reply": "真棒！还有呢？",
        "round": 1,
        "ended": False,
        "end_reason": None,
        "replayed": False,
    }
    db_session.expire_all()
    assert db_session.scalar(select(func.count(models.Message.id))) == 2
    assert fake_chat_ai.call_count == 1
    assert fake_chat_ai.calls[0]["history"] == [{"role": "user", "text": "我喂了小黄"}]
    assert fake_chat_ai.calls[0]["recent_summary"] == "我喂了小黄"
    assert "小黄：活泼" in fake_chat_ai.calls[0]["ducks_info"]
    assert "小灰" not in fake_chat_ai.calls[0]["ducks_info"]


def test_new_chat_uses_one_business_clock_sample_for_date_and_utc_timestamps(
    client,
    db_session,
    child_factory,
    fake_chat_ai,
    monkeypatch,
):
    """Catches UTC calendar dates or a second clock read within one chat request."""
    child = child_factory()
    business_now = datetime(2026, 9, 2, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

    class Clock:
        calls = 0

        @classmethod
        def business_now(cls) -> datetime:
            cls.calls += 1
            if cls.calls > 1:
                raise AssertionError("chat request read the business clock twice")
            return business_now

        @staticmethod
        def utc_now() -> datetime:
            return business_now.astimezone(timezone.utc)

    monkeypatch.setattr(conversation_routes, "BUSINESS_CLOCK", Clock)

    response = client.post("/api/chat", json=_chat_payload(child_id=child.id))

    assert response.status_code == 200
    db_session.expire_all()
    conversation = db_session.get(models.Conversation, response.json()["conversation_id"])
    record = db_session.get(models.ChatRequestRecord, response.json()["request_id"])
    messages = db_session.scalars(
        select(models.Message)
        .where(models.Message.conversation_id == response.json()["conversation_id"])
        .order_by(models.Message.id)
    ).all()
    assert conversation is not None
    assert record is not None
    assert conversation.date == "2026-09-02"
    assert conversation.started_at == datetime(2026, 9, 1, 16, 0)
    assert record.created_at == datetime(2026, 9, 1, 16, 0)
    assert record.updated_at == datetime(2026, 9, 1, 16, 0)
    assert [(message.role, message.created_at) for message in messages] == [
        ("child", datetime(2026, 9, 1, 16, 0)),
        ("diary", datetime(2026, 9, 1, 16, 0)),
    ]
    assert Clock.calls == 1


def _chat_payload(
    *,
    child_id: int,
    request_id: str | None = None,
    text: str = "我喂了小黄",
    conversation_id: int | None = None,
    max_rounds: int = 3,
) -> dict:
    return {
        "request_id": request_id or str(uuid4()),
        "child_id": child_id,
        "text": text,
        "conversation_id": conversation_id,
        "max_rounds": max_rounds,
    }


def _error(response, *, status: int, code: str, retryable: bool = False) -> None:
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert response.json()["error"]["retryable"] is retryable


def _active_conversation(db_session, child_id: int) -> models.Conversation:
    conversation = models.Conversation(
        child_id=child_id,
        date="2026-08-23",
        status="active",
    )
    db_session.add(conversation)
    db_session.commit()
    return conversation


def test_llm_retry_fence_can_stop_the_second_transport_attempt(monkeypatch):
    """Catches a lost chat lease still spending the automatic provider retry."""
    shared_llm_guard = ai_engine._llm
    spec = importlib.util.spec_from_file_location(
        "isolated_chat_retry_ai_engine",
        ai_engine.__file__,
    )
    assert spec is not None
    assert spec.loader is not None
    isolated_ai_engine = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(isolated_ai_engine)
    transport_calls = 0

    def unavailable_provider(*_args, **_kwargs):
        nonlocal transport_calls
        transport_calls += 1
        raise httpx.ConnectError("synthetic provider unavailable")

    monkeypatch.setattr(isolated_ai_engine.httpx, "post", unavailable_provider)

    with pytest.raises(httpx.ConnectError):
        isolated_ai_engine._llm(
            [{"role": "user", "content": "synthetic"}],
            retries=1,
            should_retry=lambda: False,
        )

    assert transport_calls == 1
    transport_calls = 0
    with pytest.raises(httpx.ConnectError):
        isolated_ai_engine._llm(
            [{"role": "user", "content": "synthetic"}],
            retries=1,
        )
    assert transport_calls == 2
    assert ai_engine._llm is shared_llm_guard


def test_chat_reply_forwards_retry_fence_to_llm(monkeypatch):
    """Catches chat_reply dropping the ownership fence before its internal retry loop."""
    spec = importlib.util.spec_from_file_location(
        "isolated_chat_reply_ai_engine",
        ai_engine.__file__,
    )
    assert spec is not None
    assert spec.loader is not None
    isolated_ai_engine = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(isolated_ai_engine)
    observed_fences = []

    def llm(_messages, *, json_mode, should_retry):
        assert json_mode is True
        observed_fences.append(should_retry)
        return '{"reply":"继续说吧","ended":false,"end_reason":null}'

    monkeypatch.setattr(isolated_ai_engine, "_llm", llm)

    def retry_fence() -> bool:
        return False

    response = isolated_ai_engine.chat_reply(
        child={"name": "小雨", "nickname": "雨雨"},
        recent_summary="今天喂了小鸭",
        ducks_info="小黄：活泼",
        history=[{"role": "user", "text": "今天喂了小鸭"}],
        round_num=1,
        max_rounds=3,
        should_retry=retry_fence,
    )

    assert response == {"reply": "继续说吧", "ended": False, "end_reason": None}
    assert observed_fences == [retry_fence]


def _message(db_session, conversation_id: int, role: str, text: str) -> models.Message:
    message = models.Message(conversation_id=conversation_id, role=role, text=text)
    db_session.add(message)
    db_session.commit()
    return message


def _wait_for_chat_lease_extension(request_id: str, *, beyond: datetime) -> datetime:
    deadline = monotonic() + 1
    while monotonic() < deadline:
        with SessionLocal() as session:
            lease_expires_at = session.scalar(
                select(models.ChatRequestRecord.lease_expires_at).where(
                    models.ChatRequestRecord.request_id == request_id
                )
            )
        if lease_expires_at is not None and lease_expires_at > beyond.replace(tzinfo=None):
            return lease_expires_at
        sleep(0.005)
    pytest.fail("chat lease heartbeat did not extend the durable lease")


def test_duplicate_request_replays_stored_pair_without_a_second_ai_call(
    client,
    db_session,
    child_factory,
    fake_chat_ai,
):
    """Catches duplicate POSTs that create another transcript pair or call AI again."""
    child = child_factory()
    body = _chat_payload(
        child_id=child.id,
        request_id="9b3c444f-c442-4f25-9642-0f2af8fdb2ef",
    )

    first = client.post("/api/chat", json=body)
    second = client.post("/api/chat", json=body)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == {**first.json(), "replayed": True}
    assert fake_chat_ai.call_count == 1
    db_session.expire_all()
    assert db_session.scalar(select(func.count(models.Message.id))) == 2
    record = db_session.get(models.ChatRequestRecord, body["request_id"])
    assert (record.child_message_id, record.diary_message_id) == (
        first.json()["child_message_id"],
        first.json()["diary_message_id"],
    )


def test_same_request_id_with_changed_normalized_payload_is_a_conflict(
    client,
    child_factory,
    fake_chat_ai,
):
    """Catches hashing raw/mutable input instead of the normalized idempotency payload."""
    child = child_factory()
    request_id = "998901d0-8d05-45df-bc37-5bf37a24c1f4"
    assert client.post("/api/chat", json=_chat_payload(child_id=child.id, request_id=request_id)).status_code == 200

    conflict = client.post(
        "/api/chat",
        json=_chat_payload(child_id=child.id, request_id=request_id, text="我给小黄换了水"),
    )

    _error(conflict, status=409, code="IDEMPOTENCY_CONFLICT")
    assert fake_chat_ai.call_count == 1


def test_live_lease_returns_retryable_request_in_progress(
    client,
    db_session,
    child_factory,
    fake_chat_ai,
):
    """Catches a duplicate that steals a current attempt before its lease expires."""
    child = child_factory()
    body = _chat_payload(
        child_id=child.id,
        request_id="0652ea54-e40a-4b4c-95d6-eed2e7cbe0e3",
    )
    payload = schemas.ChatRequest.model_validate(body)
    record = models.ChatRequestRecord(
        request_id=body["request_id"],
        child_id=child.id,
        payload_hash=payload_hash(payload),
        status="processing",
        attempt_count=1,
        lease_owner="a" * 64,
        lease_expires_at=datetime.utcnow() + timedelta(seconds=30),
    )
    db_session.add(record)
    db_session.commit()

    response = client.post("/api/chat", json=body)

    _error(response, status=409, code="REQUEST_IN_PROGRESS", retryable=True)
    assert fake_chat_ai.call_count == 0


def test_chat_lease_renewal_requires_exact_owner_and_attempt_fence(
    db_session,
    child_factory,
):
    """Catches a stale chat attempt extending the current owner's lease."""
    child = child_factory()
    conversation = _active_conversation(db_session, child.id)
    payload = schemas.ChatRequest.model_validate(
        _chat_payload(child_id=child.id, conversation_id=conversation.id)
    )
    clock = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
    claim = claim_chat_request(
        db_session,
        payload,
        now=clock.replace(tzinfo=None),
        business_date=clock.date(),
        lease_seconds=6,
    )
    db_session.rollback()

    wrong_owner = chat_service.ChatClaim(
        request_id=claim.request_id,
        conversation_id=claim.conversation_id,
        replay=None,
        lease_owner="wrong-owner",
        attempt_count=claim.attempt_count,
        lease_expires_at=claim.lease_expires_at,
    )
    wrong_attempt = chat_service.ChatClaim(
        request_id=claim.request_id,
        conversation_id=claim.conversation_id,
        replay=None,
        lease_owner=claim.lease_owner,
        attempt_count=claim.attempt_count + 1,
        lease_expires_at=claim.lease_expires_at,
    )
    assert chat_service.renew_chat_request_lease(
        SessionLocal,
        claim=wrong_owner,
        clock=lambda: clock + timedelta(seconds=2),
        lease_seconds=6,
    ) is None
    assert chat_service.renew_chat_request_lease(
        SessionLocal,
        claim=wrong_attempt,
        clock=lambda: clock + timedelta(seconds=2),
        lease_seconds=6,
    ) is None
    assert chat_service.renew_chat_request_lease(
        SessionLocal,
        claim=claim,
        clock=lambda: clock + timedelta(seconds=2),
        lease_seconds=6,
    ) == datetime(2026, 9, 5, 12, 0, 8)
    assert chat_service.renew_chat_request_lease(
        SessionLocal,
        claim=claim,
        clock=lambda: clock + timedelta(seconds=9),
        lease_seconds=6,
    ) is None

    db_session.expire_all()
    saved = db_session.get(models.ChatRequestRecord, claim.request_id)
    assert saved is not None
    assert saved.lease_expires_at == datetime(2026, 9, 5, 12, 0, 8)


def test_chat_lease_guard_publishes_expiry_loss_atomically_with_renewal():
    """Catches an expired retry fence racing a concurrent deadline publication."""
    expiry = datetime(2026, 9, 5, 12, 0, 6)
    guard = chat_service.ChatLeaseGuard(expiry)
    loss_started = Event()
    release_loss = Event()
    renewal_finished = Event()
    retry_results: list[bool] = []
    renewal_results: list[bool] = []

    class BlockingEvent:
        def __init__(self) -> None:
            self.inner = Event()

        def is_set(self) -> bool:
            return self.inner.is_set()

        def set(self) -> None:
            loss_started.set()
            assert release_loss.wait(2)
            self.inner.set()

    guard._lost = BlockingEvent()  # type: ignore[assignment]

    retry_thread = Thread(
        target=lambda: retry_results.append(guard.retry_allowed(lambda: expiry))
    )
    retry_thread.start()
    assert loss_started.wait(1)

    def publish_renewal() -> None:
        renewal_results.append(
            guard.record_renewal(
                now=expiry - timedelta(seconds=1),
                lease_seconds=6,
            )
        )
        renewal_finished.set()

    renewal_thread = Thread(target=publish_renewal)
    renewal_thread.start()
    try:
        assert not renewal_finished.wait(0.1)
    finally:
        release_loss.set()
        retry_thread.join(2)
        renewal_thread.join(2)

    assert not retry_thread.is_alive()
    assert not renewal_thread.is_alive()
    assert retry_results == [False]
    assert renewal_results == [False]


def test_terminal_chat_cas_checks_fresh_lease_time_without_changing_business_timestamps(
    db_session,
    child_factory,
):
    """Catches an expired owner committing because terminal CAS reused request-start time."""
    child = child_factory()
    conversation = _active_conversation(db_session, child.id)
    payload = schemas.ChatRequest.model_validate(
        _chat_payload(child_id=child.id, conversation_id=conversation.id)
    )
    business_now = datetime(2026, 9, 5, 12, 0)
    claim = claim_chat_request(
        db_session,
        payload,
        now=business_now,
        business_date=business_now.date(),
        lease_seconds=6,
    )

    with pytest.raises(APIError) as stale_success:
        commit_chat_success(
            db_session,
            claim=claim,
            payload=payload,
            reply="迟到的回复",
            ended=False,
            end_reason=None,
            now=business_now,
            lease_now=datetime(2026, 9, 5, 12, 0, 7, tzinfo=timezone.utc),
        )

    assert stale_success.value.code == "REQUEST_IN_PROGRESS"
    assert record_chat_failure(
        db_session,
        claim=claim,
        code="CHAT_UPSTREAM_FAILED",
        now=business_now,
        lease_now=datetime(2026, 9, 5, 12, 0, 7, tzinfo=timezone.utc),
    ) is False
    db_session.expire_all()
    saved = db_session.get(models.ChatRequestRecord, claim.request_id)
    assert saved is not None
    assert saved.status == "processing"
    assert saved.updated_at == business_now
    assert db_session.scalar(select(func.count(models.Message.id))) == 0


@pytest.mark.parametrize("terminal_kind", ("success", "failure"))
def test_terminal_chat_lease_clock_is_sampled_after_sqlite_writer_slot(
    db_session,
    child_factory,
    terminal_kind,
):
    """Catches a writer wait turning a pre-lock lease timestamp stale."""
    child = child_factory()
    conversation = _active_conversation(db_session, child.id)
    payload = schemas.ChatRequest.model_validate(
        _chat_payload(child_id=child.id, conversation_id=conversation.id)
    )
    business_now = datetime(2026, 9, 5, 12, 0)
    claim = claim_chat_request(
        db_session,
        payload,
        now=business_now,
        business_date=business_now.date(),
        lease_seconds=6,
    )
    db_session.rollback()

    worker_started = Event()
    clock_called = Event()
    results: list[object] = []
    failures: list[BaseException] = []

    def lease_clock() -> datetime:
        clock_called.set()
        return business_now.replace(tzinfo=timezone.utc) + timedelta(seconds=7)

    def persist_terminal_state() -> None:
        with SessionLocal() as worker_session:
            worker_started.set()
            try:
                if terminal_kind == "success":
                    results.append(
                        commit_chat_success(
                            worker_session,
                            claim=claim,
                            payload=payload,
                            reply="迟到的回复",
                            ended=False,
                            end_reason=None,
                            now=business_now,
                            lease_clock=lease_clock,
                        )
                    )
                else:
                    results.append(
                        record_chat_failure(
                            worker_session,
                            claim=claim,
                            code="CHAT_UPSTREAM_FAILED",
                            now=business_now,
                            lease_clock=lease_clock,
                        )
                    )
            except BaseException as exc:
                failures.append(exc)

    with SessionLocal() as writer:
        writer.connection().exec_driver_sql("BEGIN IMMEDIATE")
        thread = Thread(target=persist_terminal_state)
        thread.start()
        try:
            assert worker_started.wait(1)
            assert not clock_called.wait(0.1)
        finally:
            writer.rollback()
            thread.join(2)

    assert not thread.is_alive()
    assert clock_called.is_set()
    if terminal_kind == "success":
        assert len(failures) == 1
        assert isinstance(failures[0], APIError)
        assert failures[0].code == "REQUEST_IN_PROGRESS"
        assert results == []
    else:
        assert failures == []
        assert results == [False]
    db_session.expire_all()
    saved = db_session.get(models.ChatRequestRecord, claim.request_id)
    assert saved is not None
    assert saved.status == "processing"
    assert db_session.scalar(select(func.count(models.Message.id))) == 0


def test_fixed_max_round_route_uses_fresh_lease_time_before_terminal_write(
    db_session,
    child_factory,
    fake_chat_ai,
):
    """Catches the provider-free final turn committing with request-start time."""
    child = child_factory()
    conversation = _active_conversation(db_session, child.id)
    _message(db_session, conversation.id, "child", "我喂了小黄")
    _message(db_session, conversation.id, "diary", "真棒！")
    _message(db_session, conversation.id, "child", "我还换了水")
    _message(db_session, conversation.id, "diary", "你真细心！")
    payload = schemas.ChatRequest.model_validate(
        _chat_payload(
            child_id=child.id,
            conversation_id=conversation.id,
            max_rounds=3,
        )
    )
    clock_start = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)

    class ExpiredClock:
        @staticmethod
        def business_now() -> datetime:
            return clock_start.astimezone(ZoneInfo("Asia/Shanghai"))

        @staticmethod
        def utc_now() -> datetime:
            return clock_start + timedelta(seconds=7)

    with SessionLocal() as route_session:
        with pytest.raises(APIError) as failed:
            conversation_routes._chat_request(
                payload,
                route_session,
                session_factory=SessionLocal,
                clock=ExpiredClock,
                lease_seconds=6,
                heartbeat_interval_seconds=0.01,
            )

    assert failed.value.code == "REQUEST_IN_PROGRESS"
    assert failed.value.retryable is True
    assert fake_chat_ai.call_count == 0
    db_session.expire_all()
    saved = db_session.get(models.ChatRequestRecord, str(payload.request_id))
    assert saved is not None
    assert saved.status == "processing"
    assert db_session.scalar(select(func.count(models.Message.id))) == 4


@pytest.mark.parametrize("failure_kind", ("api", "internal"))
def test_pre_provider_failure_uses_fresh_lease_time_before_terminal_write(
    db_session,
    child_factory,
    fake_chat_ai,
    monkeypatch,
    failure_kind,
):
    """Catches context failures persisting after their original lease expired."""
    child = child_factory()
    conversation = _active_conversation(db_session, child.id)
    payload = schemas.ChatRequest.model_validate(
        _chat_payload(child_id=child.id, conversation_id=conversation.id)
    )
    clock_start = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)

    class ExpiredClock:
        @staticmethod
        def business_now() -> datetime:
            return clock_start.astimezone(ZoneInfo("Asia/Shanghai"))

        @staticmethod
        def utc_now() -> datetime:
            return clock_start + timedelta(seconds=7)

    def fail_context(*_args, **_kwargs):
        if failure_kind == "api":
            raise APIError(409, "CONVERSATION_CHANGED", "会话状态已变化")
        raise RuntimeError("synthetic context failure")

    monkeypatch.setattr(conversation_routes, "build_chat_context", fail_context)

    with SessionLocal() as route_session:
        with pytest.raises(APIError) as failed:
            conversation_routes._chat_request(
                payload,
                route_session,
                session_factory=SessionLocal,
                clock=ExpiredClock,
                lease_seconds=6,
                heartbeat_interval_seconds=0.01,
            )

    assert failed.value.code == "REQUEST_IN_PROGRESS"
    assert failed.value.retryable is True
    assert fake_chat_ai.call_count == 0
    db_session.expire_all()
    saved = db_session.get(models.ChatRequestRecord, str(payload.request_id))
    assert saved is not None
    assert saved.status == "processing"
    assert db_session.scalar(select(func.count(models.Message.id))) == 0


def test_chat_heartbeat_recovers_after_one_transient_database_error(
    db_session,
    child_factory,
    monkeypatch,
):
    """Catches one short SQLite conflict disabling renewal for the whole call."""
    child = child_factory()
    conversation = _active_conversation(db_session, child.id)
    payload = schemas.ChatRequest.model_validate(
        _chat_payload(child_id=child.id, conversation_id=conversation.id)
    )
    clock = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
    claim = claim_chat_request(
        db_session,
        payload,
        now=clock.replace(tzinfo=None),
        business_date=clock.date(),
        lease_seconds=6,
    )
    db_session.rollback()
    first_failed = Event()
    later_succeeded = Event()
    calls = 0
    original_renew = chat_service.renew_chat_request_lease

    def fail_once_then_renew(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            first_failed.set()
            raise RuntimeError("transient sqlite writer conflict")
        renewed = original_renew(*args, **kwargs)
        if renewed:
            later_succeeded.set()
        return renewed

    monkeypatch.setattr(chat_service, "renew_chat_request_lease", fail_once_then_renew)

    with chat_service.chat_lease_heartbeat(
        SessionLocal,
        claim=claim,
        clock=lambda: clock + timedelta(seconds=2),
        lease_seconds=6,
        heartbeat_interval_seconds=0.01,
    ) as lease_lost:
        assert first_failed.wait(1)
        assert later_succeeded.wait(1)
        assert not lease_lost.is_set()

    assert calls >= 2
    db_session.expire_all()
    saved = db_session.get(models.ChatRequestRecord, claim.request_id)
    assert saved is not None
    assert saved.lease_expires_at == datetime(2026, 9, 5, 12, 0, 8)


def test_chat_heartbeat_marks_lease_lost_when_database_errors_outlive_expiry(
    db_session,
    child_factory,
    monkeypatch,
):
    """Catches repeated renewal errors leaving provider retries live past expiry."""
    child = child_factory()
    conversation = _active_conversation(db_session, child.id)
    payload = schemas.ChatRequest.model_validate(
        _chat_payload(child_id=child.id, conversation_id=conversation.id)
    )
    clock = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
    claim = claim_chat_request(
        db_session,
        payload,
        now=clock.replace(tzinfo=None),
        business_date=clock.date(),
        lease_seconds=6,
    )
    db_session.rollback()
    attempts = 0
    observed_expiry = Event()
    clock_samples = iter((2, 2, 7))

    def unavailable_database(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        raise RuntimeError("persistent sqlite writer failure")

    def heartbeat_clock():
        offset = next(clock_samples)
        if offset >= 6:
            observed_expiry.set()
        return clock + timedelta(seconds=offset)

    monkeypatch.setattr(
        chat_service,
        "renew_chat_request_lease",
        unavailable_database,
    )

    with chat_service.chat_lease_heartbeat(
        SessionLocal,
        claim=claim,
        clock=heartbeat_clock,
        lease_seconds=6,
        heartbeat_interval_seconds=0.01,
    ) as lease_lost:
        assert observed_expiry.wait(1)
        deadline = monotonic() + 1
        while not lease_lost.is_set() and monotonic() < deadline:
            sleep(0.005)
        assert lease_lost.is_set()

    assert attempts == 1


def test_chat_heartbeat_fences_one_failed_renewal_that_returns_after_lease_expiry(
    db_session,
    child_factory,
    monkeypatch,
):
    """Catches a blocked renewal trusting only its pre-I/O clock sample."""
    child = child_factory()
    conversation = _active_conversation(db_session, child.id)
    payload = schemas.ChatRequest.model_validate(
        _chat_payload(child_id=child.id, conversation_id=conversation.id)
    )
    clock_start = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
    clock_now = [clock_start + timedelta(seconds=2)]
    claim = claim_chat_request(
        db_session,
        payload,
        now=clock_start.replace(tzinfo=None),
        business_date=clock_start.date(),
        lease_seconds=6,
    )
    db_session.rollback()
    renewal_finished = Event()
    calls = 0

    def delayed_renewal(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        clock_now[0] = clock_start + timedelta(seconds=7)
        renewal_finished.set()
        raise RuntimeError("sqlite wait crossed the lease boundary")

    monkeypatch.setattr(chat_service, "renew_chat_request_lease", delayed_renewal)

    with chat_service.chat_lease_heartbeat(
        SessionLocal,
        claim=claim,
        clock=lambda: clock_now[0],
        lease_seconds=6,
        heartbeat_interval_seconds=0.01,
    ) as lease_lost:
        assert renewal_finished.wait(1)
        deadline = monotonic() + 1
        while not lease_lost.is_set() and monotonic() < deadline:
            sleep(0.005)
        assert lease_lost.is_set()

    assert calls == 1


def test_chat_heartbeat_marks_lost_before_any_post_miss_clock_work(
    db_session,
    child_factory,
    monkeypatch,
):
    """Catches a CAS miss leaving the real one-shot provider retry fence open."""
    child = child_factory()
    conversation = _active_conversation(db_session, child.id)
    payload = schemas.ChatRequest.model_validate(
        _chat_payload(child_id=child.id, conversation_id=conversation.id)
    )
    clock_start = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
    claim = claim_chat_request(
        db_session,
        payload,
        now=clock_start.replace(tzinfo=None),
        business_date=clock_start.date(),
        lease_seconds=6,
    )
    db_session.rollback()
    renewal_rejected = Event()
    post_miss_clock_entered = Event()
    release_post_miss_clock = Event()
    clock_calls = 0

    def reject_renewal(*_args, **_kwargs):
        renewal_rejected.set()
        return None

    def heartbeat_clock() -> datetime:
        nonlocal clock_calls
        clock_calls += 1
        if clock_calls > 1:
            post_miss_clock_entered.set()
            assert release_post_miss_clock.wait(2)
        return clock_start + timedelta(seconds=2)

    monkeypatch.setattr(chat_service, "renew_chat_request_lease", reject_renewal)
    stop_event = Event()
    guard = chat_service.ChatLeaseGuard(claim.lease_expires_at)
    thread = Thread(
        target=chat_service._run_chat_lease_heartbeat,
        kwargs={
            "session_factory": SessionLocal,
            "claim": claim,
            "clock": heartbeat_clock,
            "lease_seconds": 6,
            "interval_seconds": 0.01,
            "stop_event": stop_event,
            "lease_guard": guard,
        },
    )
    thread.start()
    try:
        assert renewal_rejected.wait(1)
        deadline = monotonic() + 1
        while (
            not guard.is_set()
            and not post_miss_clock_entered.is_set()
            and monotonic() < deadline
        ):
            sleep(0.005)
        assert guard.is_set()
    finally:
        release_post_miss_clock.set()
        stop_event.set()
        thread.join(2)

    assert not thread.is_alive()
    assert clock_calls == 1


def test_chat_heartbeat_publishes_durable_renewal_before_retry_fence_rechecks(
    db_session,
    child_factory,
    monkeypatch,
):
    """Catches a valid durable renewal being lost before its guard publication."""
    child = child_factory()
    conversation = _active_conversation(db_session, child.id)
    payload = schemas.ChatRequest.model_validate(
        _chat_payload(child_id=child.id, conversation_id=conversation.id)
    )
    clock_start = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
    claim = claim_chat_request(
        db_session,
        payload,
        now=clock_start.replace(tzinfo=None),
        business_date=clock_start.date(),
        lease_seconds=6,
    )
    db_session.rollback()
    renewed_until = clock_start.replace(tzinfo=None) + timedelta(seconds=8)
    post_renewal_clock_entered = Event()
    release_post_renewal_clock = Event()
    retry_finished = Event()
    retry_results: list[bool] = []
    clock_calls = 0

    def durable_renewal(*_args, **_kwargs):
        return renewed_until

    def heartbeat_clock() -> datetime:
        nonlocal clock_calls
        clock_calls += 1
        if clock_calls > 1:
            post_renewal_clock_entered.set()
            assert release_post_renewal_clock.wait(2)
        return clock_start + timedelta(seconds=2)

    monkeypatch.setattr(chat_service, "renew_chat_request_lease", durable_renewal)
    stop_event = Event()
    guard = chat_service.ChatLeaseGuard(claim.lease_expires_at)
    heartbeat = Thread(
        target=chat_service._run_chat_lease_heartbeat,
        kwargs={
            "session_factory": SessionLocal,
            "claim": claim,
            "clock": heartbeat_clock,
            "lease_seconds": 6,
            "interval_seconds": 0.01,
            "stop_event": stop_event,
            "lease_guard": guard,
        },
    )
    heartbeat.start()
    assert post_renewal_clock_entered.wait(1)

    def check_retry_fence() -> None:
        retry_results.append(
            guard.retry_allowed(
                lambda: clock_start + timedelta(seconds=7)
            )
        )
        retry_finished.set()

    retry = Thread(target=check_retry_fence)
    retry.start()
    try:
        assert not retry_finished.wait(0.1)
    finally:
        release_post_renewal_clock.set()
        retry.join(2)
        stop_event.set()
        heartbeat.join(2)

    assert not retry.is_alive()
    assert not heartbeat.is_alive()
    assert retry_results == [True]
    assert not guard.is_set()
    assert guard.expires_at() == renewed_until


def test_slow_chat_success_stays_owned_and_duplicate_cannot_reclaim_after_original_expiry(
    db_session,
    child_factory,
    fake_chat_ai,
):
    """Catches a slow valid provider call being reclaimed and executed twice."""
    child = child_factory()
    conversation = _active_conversation(db_session, child.id)
    payload = schemas.ChatRequest.model_validate(
        _chat_payload(child_id=child.id, conversation_id=conversation.id)
    )
    db_session.rollback()
    clock_now = [datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)]
    provider_entered = Event()
    release_provider = Event()
    failures: list[BaseException] = []
    responses: list[schemas.ChatResponse] = []

    class Clock:
        @staticmethod
        def business_now() -> datetime:
            return clock_now[0].astimezone(ZoneInfo("Asia/Shanghai"))

        @staticmethod
        def utc_now() -> datetime:
            return clock_now[0]

    route_session = SessionLocal()

    def hold_provider() -> None:
        assert not route_session.in_transaction()
        clock_now[0] += timedelta(seconds=4)
        provider_entered.set()
        assert release_provider.wait(2)

    fake_chat_ai.on_call = hold_provider

    def run_request() -> None:
        try:
            responses.append(
                conversation_routes._chat_request(
                    payload,
                    route_session,
                    session_factory=SessionLocal,
                    clock=Clock,
                    lease_seconds=6,
                    heartbeat_interval_seconds=0.01,
                )
            )
        except BaseException as exc:
            failures.append(exc)
        finally:
            route_session.close()

    thread = Thread(target=run_request)
    thread.start()
    try:
        assert provider_entered.wait(1)
        extended_to = _wait_for_chat_lease_extension(
            str(payload.request_id),
            beyond=clock_now[0] + timedelta(seconds=2),
        )
        clock_now[0] += timedelta(seconds=3)
        with SessionLocal() as duplicate_session:
            with pytest.raises(APIError) as duplicate:
                conversation_routes._chat_request(
                    payload,
                    duplicate_session,
                    session_factory=SessionLocal,
                    clock=Clock,
                    lease_seconds=6,
                    heartbeat_interval_seconds=0.01,
                )
        assert duplicate.value.code == "REQUEST_IN_PROGRESS"
        assert fake_chat_ai.call_count == 1
    finally:
        release_provider.set()
        thread.join(2)

    assert extended_to == datetime(2026, 9, 5, 12, 0, 10)
    assert not thread.is_alive()
    assert failures == []
    assert len(responses) == 1
    assert responses[0].reply == "真棒！还有呢？"
    db_session.expire_all()
    saved = db_session.get(models.ChatRequestRecord, str(payload.request_id))
    assert saved is not None
    assert saved.status == "succeeded"
    assert saved.attempt_count == 1
    assert db_session.scalar(select(func.count(models.Message.id))) == 2


def test_lost_chat_lease_discards_result_and_fences_provider_retry(
    db_session,
    child_factory,
    monkeypatch,
):
    """Catches a fenced-out attempt retrying upstream or writing its late result."""
    child = child_factory()
    conversation = _active_conversation(db_session, child.id)
    payload = schemas.ChatRequest.model_validate(
        _chat_payload(child_id=child.id, conversation_id=conversation.id)
    )
    db_session.rollback()
    clock_now = [datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)]
    renewal_rejected = Event()
    retry_fences = []
    transport_calls = 0

    class Clock:
        @staticmethod
        def business_now() -> datetime:
            return clock_now[0].astimezone(ZoneInfo("Asia/Shanghai"))

        @staticmethod
        def utc_now() -> datetime:
            return clock_now[0]

    def steal_lease(_session_factory, *, claim, **_kwargs):
        with SessionLocal() as thief:
            stolen = thief.execute(
                update(models.ChatRequestRecord)
                .where(
                    models.ChatRequestRecord.request_id == claim.request_id,
                    models.ChatRequestRecord.lease_owner == claim.lease_owner,
                    models.ChatRequestRecord.attempt_count == claim.attempt_count,
                )
                .values(
                    lease_owner="replacement-owner",
                    attempt_count=claim.attempt_count + 1,
                    lease_expires_at=clock_now[0].replace(tzinfo=None)
                    + timedelta(seconds=30),
                )
            )
            assert stolen.rowcount == 1
            thief.commit()
        renewal_rejected.set()
        return None

    def failing_transport_with_optional_retry(**kwargs):
        nonlocal transport_calls
        transport_calls += 1
        retry_fence = kwargs.get("should_retry")
        retry_fences.append(retry_fence)
        assert renewal_rejected.wait(1)
        if callable(retry_fence):
            deadline = monotonic() + 1
            while retry_fence() and monotonic() < deadline:
                sleep(0.005)
            if retry_fence():
                transport_calls += 1
        raise httpx.ConnectError("synthetic provider unavailable")

    monkeypatch.setattr(chat_service, "renew_chat_request_lease", steal_lease)
    monkeypatch.setattr(ai_engine, "chat_reply", failing_transport_with_optional_retry)

    with SessionLocal() as route_session:
        with pytest.raises(APIError) as failed:
            conversation_routes._chat_request(
                payload,
                route_session,
                session_factory=SessionLocal,
                clock=Clock,
                lease_seconds=6,
                heartbeat_interval_seconds=0.01,
            )

    assert failed.value.code == "REQUEST_IN_PROGRESS"
    assert failed.value.retryable is True
    assert len(retry_fences) == 1
    assert callable(retry_fences[0])
    assert transport_calls == 1
    db_session.expire_all()
    saved = db_session.get(models.ChatRequestRecord, str(payload.request_id))
    assert saved is not None
    assert saved.status == "processing"
    assert saved.lease_owner == "replacement-owner"
    assert saved.attempt_count == 2
    assert db_session.scalar(select(func.count(models.Message.id))) == 0


def test_slow_chat_failure_is_recorded_by_original_owner_after_lease_extension(
    db_session,
    child_factory,
    fake_chat_ai,
):
    """Catches a slow provider failure leaving its original request processing forever."""
    child = child_factory()
    conversation = _active_conversation(db_session, child.id)
    payload = schemas.ChatRequest.model_validate(
        _chat_payload(child_id=child.id, conversation_id=conversation.id)
    )
    db_session.rollback()
    clock_now = [datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)]
    provider_entered = Event()
    release_provider = Event()
    failures: list[BaseException] = []

    class Clock:
        @staticmethod
        def business_now() -> datetime:
            return clock_now[0].astimezone(ZoneInfo("Asia/Shanghai"))

        @staticmethod
        def utc_now() -> datetime:
            return clock_now[0]

    def hold_provider() -> None:
        clock_now[0] += timedelta(seconds=4)
        provider_entered.set()
        assert release_provider.wait(2)

    fake_chat_ai.on_call = hold_provider
    fake_chat_ai.result = httpx.ConnectError("synthetic provider unavailable")

    def run_request() -> None:
        with SessionLocal() as route_session:
            try:
                conversation_routes._chat_request(
                    payload,
                    route_session,
                    session_factory=SessionLocal,
                    clock=Clock,
                    lease_seconds=6,
                    heartbeat_interval_seconds=0.01,
                )
            except BaseException as exc:
                failures.append(exc)

    thread = Thread(target=run_request)
    thread.start()
    try:
        assert provider_entered.wait(1)
        _wait_for_chat_lease_extension(
            str(payload.request_id),
            beyond=clock_now[0] + timedelta(seconds=2),
        )
        clock_now[0] += timedelta(seconds=3)
    finally:
        release_provider.set()
        thread.join(2)

    assert not thread.is_alive()
    assert len(failures) == 1
    assert isinstance(failures[0], APIError)
    assert failures[0].code == "CHAT_UPSTREAM_FAILED"
    assert fake_chat_ai.call_count == 1
    db_session.expire_all()
    saved = db_session.get(models.ChatRequestRecord, str(payload.request_id))
    assert saved is not None
    assert saved.status == "failed"
    assert saved.attempt_count == 1
    assert saved.lease_owner is None
    assert saved.last_error_code == "CHAT_UPSTREAM_FAILED"
    assert db_session.scalar(select(func.count(models.Message.id))) == 0


def test_chat_failure_reclaimed_after_heartbeat_join_returns_in_progress(
    db_session,
    child_factory,
    fake_chat_ai,
    monkeypatch,
):
    """Catches a failure response misreporting ownership after its final CAS loses."""
    child = child_factory()
    conversation = _active_conversation(db_session, child.id)
    payload = schemas.ChatRequest.model_validate(
        _chat_payload(child_id=child.id, conversation_id=conversation.id)
    )
    fake_chat_ai.result = httpx.ConnectError("synthetic provider unavailable")
    original_record_failure = chat_service.record_chat_failure

    def reclaim_then_record(db, *, claim, code, now, lease_clock):
        with SessionLocal() as thief:
            stolen = thief.execute(
                update(models.ChatRequestRecord)
                .where(
                    models.ChatRequestRecord.request_id == claim.request_id,
                    models.ChatRequestRecord.lease_owner == claim.lease_owner,
                    models.ChatRequestRecord.attempt_count == claim.attempt_count,
                )
                .values(
                    lease_owner="replacement-owner",
                    attempt_count=claim.attempt_count + 1,
                    lease_expires_at=now + timedelta(seconds=30),
                )
            )
            assert stolen.rowcount == 1
            thief.commit()
        return original_record_failure(
            db,
            claim=claim,
            code=code,
            now=now,
            lease_clock=lease_clock,
        )

    monkeypatch.setattr(conversation_routes, "record_chat_failure", reclaim_then_record)

    with SessionLocal() as route_session:
        with pytest.raises(APIError) as failed:
            conversation_routes._chat_request(
                payload,
                route_session,
                session_factory=SessionLocal,
                clock=conversation_routes.BUSINESS_CLOCK,
                heartbeat_interval_seconds=0.01,
            )

    assert failed.value.code == "REQUEST_IN_PROGRESS"
    assert failed.value.retryable is True
    assert fake_chat_ai.call_count == 1
    db_session.expire_all()
    saved = db_session.get(models.ChatRequestRecord, str(payload.request_id))
    assert saved is not None
    assert saved.status == "processing"
    assert saved.lease_owner == "replacement-owner"
    assert saved.attempt_count == 2
    assert db_session.scalar(select(func.count(models.Message.id))) == 0


@pytest.mark.parametrize("provider_fails", [False, True], ids=["success", "failure"])
def test_chat_joins_inflight_heartbeat_before_terminal_database_write(
    db_session,
    child_factory,
    fake_chat_ai,
    monkeypatch,
    provider_fails,
):
    """Catches success or failure persistence racing the heartbeat SQLite writer."""
    child = child_factory()
    conversation = _active_conversation(db_session, child.id)
    payload = schemas.ChatRequest.model_validate(
        _chat_payload(child_id=child.id, conversation_id=conversation.id)
    )
    db_session.rollback()
    clock = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
    heartbeat_committed = Event()
    release_heartbeat = Event()
    provider_returned = Event()
    terminal_started = Event()
    failures: list[BaseException] = []
    original_renew = chat_service.renew_chat_request_lease
    original_commit = conversation_routes.commit_chat_success
    original_failure = conversation_routes.record_chat_failure

    class Clock:
        @staticmethod
        def business_now() -> datetime:
            return clock.astimezone(ZoneInfo("Asia/Shanghai"))

        @staticmethod
        def utc_now() -> datetime:
            return clock

    def hold_heartbeat(*args, **kwargs):
        renewed = original_renew(*args, **kwargs)
        heartbeat_committed.set()
        assert release_heartbeat.wait(2)
        return renewed

    def observe_commit(*args, **kwargs):
        terminal_started.set()
        return original_commit(*args, **kwargs)

    def observe_failure(*args, **kwargs):
        terminal_started.set()
        return original_failure(*args, **kwargs)

    def provider_call() -> None:
        assert heartbeat_committed.wait(1)
        provider_returned.set()

    monkeypatch.setattr(chat_service, "renew_chat_request_lease", hold_heartbeat)
    monkeypatch.setattr(conversation_routes, "commit_chat_success", observe_commit)
    monkeypatch.setattr(conversation_routes, "record_chat_failure", observe_failure)
    fake_chat_ai.on_call = provider_call
    if provider_fails:
        fake_chat_ai.result = httpx.ConnectError("synthetic provider unavailable")

    def run_request() -> None:
        with SessionLocal() as route_session:
            try:
                conversation_routes._chat_request(
                    payload,
                    route_session,
                    session_factory=SessionLocal,
                    clock=Clock,
                    lease_seconds=6,
                    heartbeat_interval_seconds=0.01,
                )
            except BaseException as exc:
                failures.append(exc)

    thread = Thread(target=run_request)
    thread.start()
    try:
        assert heartbeat_committed.wait(1)
        assert provider_returned.wait(1)
        assert not terminal_started.wait(0.1)
    finally:
        release_heartbeat.set()
        thread.join(2)

    assert not thread.is_alive()
    assert terminal_started.is_set()
    if provider_fails:
        assert len(failures) == 1
        assert isinstance(failures[0], APIError)
        assert failures[0].code == "CHAT_UPSTREAM_FAILED"
    else:
        assert failures == []
    db_session.expire_all()
    saved = db_session.get(models.ChatRequestRecord, str(payload.request_id))
    assert saved is not None
    assert saved.status == ("failed" if provider_fails else "succeeded")


def test_failed_request_id_retries_without_messages_from_the_failed_attempt(
    client,
    db_session,
    child_factory,
    fake_chat_ai,
):
    """Catches upstream failures that are disguised as a normal reply or permanently poison retries."""
    child = child_factory()
    body = _chat_payload(
        child_id=child.id,
        request_id="3b8b5ec9-d6b4-4f87-a171-e7726595296f",
    )
    fake_chat_ai.result = httpx.ConnectError("fake provider unavailable")

    failed = client.post("/api/chat", json=body)

    _error(failed, status=503, code="CHAT_UPSTREAM_FAILED", retryable=True)
    db_session.expire_all()
    assert db_session.scalar(select(func.count(models.Message.id))) == 0
    record = db_session.get(models.ChatRequestRecord, body["request_id"])
    assert record.status == "failed"
    conversation_id = record.conversation_id

    fake_chat_ai.result = {"reply": "恢复后继续说吧。", "ended": False, "end_reason": None}
    retried = client.post("/api/chat", json=body)

    assert retried.status_code == 200
    assert retried.json()["conversation_id"] == conversation_id
    assert retried.json()["reply"] == "恢复后继续说吧。"
    assert fake_chat_ai.call_count == 2
    db_session.expire_all()
    assert db_session.scalar(select(func.count(models.Message.id))) == 2
    assert db_session.get(models.ChatRequestRecord, body["request_id"]).attempt_count == 2


def test_expired_processing_request_is_reclaimed_by_the_same_request_id(
    client,
    db_session,
    child_factory,
    fake_chat_ai,
):
    """Catches abandoned processing rows that cannot be safely reclaimed after a crash."""
    child = child_factory()
    conversation = _active_conversation(db_session, child.id)
    body = _chat_payload(
        child_id=child.id,
        conversation_id=conversation.id,
        request_id="aa9bb1e2-ba88-4c33-8d30-3f0c0763452c",
    )
    payload = schemas.ChatRequest.model_validate(body)
    db_session.add(
        models.ChatRequestRecord(
            request_id=body["request_id"],
            child_id=child.id,
            conversation_id=conversation.id,
            payload_hash=payload_hash(payload),
            status="processing",
            attempt_count=1,
            lease_owner="b" * 64,
            lease_expires_at=datetime.utcnow() - timedelta(seconds=1),
        )
    )
    db_session.commit()

    response = client.post("/api/chat", json=body)

    assert response.status_code == 200
    db_session.expire_all()
    record = db_session.get(models.ChatRequestRecord, body["request_id"])
    assert record.status == "succeeded"
    assert record.attempt_count == 2
    assert record.lease_owner is None
    assert fake_chat_ai.call_count == 1


def test_stale_attempt_cannot_commit_or_fail_after_its_lease_is_reclaimed(
    db_session,
    child_factory,
):
    """Catches a late AI result/failure mutating a newer lease holder's attempt."""
    child = child_factory()
    conversation = _active_conversation(db_session, child.id)
    first_payload = schemas.ChatRequest.model_validate(
        _chat_payload(child_id=child.id, conversation_id=conversation.id)
    )
    clock = datetime.utcnow()
    first_claim = claim_chat_request(
        db_session,
        first_payload,
        now=clock,
        business_date=clock.date(),
    )

    with SessionLocal() as reclaimer:
        reclaimer.execute(
            update(models.ChatRequestRecord)
            .where(models.ChatRequestRecord.request_id == first_claim.request_id)
            .values(lease_expires_at=clock - timedelta(seconds=1))
        )
        reclaimer.commit()
        second_claim = claim_chat_request(
            reclaimer,
            first_payload,
            now=clock + timedelta(seconds=1),
            business_date=clock.date(),
        )

    with pytest.raises(APIError) as stale_result:
        commit_chat_success(
            db_session,
            claim=first_claim,
            payload=first_payload,
            reply="迟到的回复",
            ended=False,
            end_reason=None,
            now=clock + timedelta(seconds=1),
        )
    assert stale_result.value.code == "REQUEST_IN_PROGRESS"
    record_chat_failure(
        db_session,
        claim=first_claim,
        code="CHAT_UPSTREAM_FAILED",
        now=clock + timedelta(seconds=1),
    )
    db_session.expire_all()
    current = db_session.get(models.ChatRequestRecord, first_claim.request_id)
    assert current.status == "processing"
    assert current.lease_owner == second_claim.lease_owner
    assert db_session.scalar(select(func.count(models.Message.id))) == 0

    committed = commit_chat_success(
        db_session,
        claim=second_claim,
        payload=first_payload,
        reply="当前尝试的回复",
        ended=False,
        end_reason=None,
        now=clock + timedelta(seconds=1),
    )
    assert committed.reply == "当前尝试的回复"
    assert db_session.scalar(select(func.count(models.Message.id))) == 2


def test_conversation_must_belong_to_the_request_child(
    client,
    db_session,
    child_factory,
    fake_chat_ai,
):
    """Catches cross-child transcript writes through a guessed conversation ID."""
    child = child_factory(name="小雨")
    other_child = child_factory(name="乐乐")
    other_conversation = _active_conversation(db_session, other_child.id)

    response = client.post(
        "/api/chat",
        json=_chat_payload(child_id=child.id, conversation_id=other_conversation.id),
    )

    _error(response, status=409, code="CONVERSATION_CHILD_MISMATCH")
    assert fake_chat_ai.call_count == 0
    assert db_session.scalar(select(func.count(models.ChatRequestRecord.request_id))) == 0


def test_missing_or_inactive_conversation_is_not_claimed_or_sent_to_ai(
    client,
    db_session,
    child_factory,
    fake_chat_ai,
):
    """Catches writes to absent/ended conversations instead of the active transcript only."""
    child = child_factory()
    ended = models.Conversation(child_id=child.id, date="2026-08-23", status="ended")
    db_session.add(ended)
    db_session.commit()

    missing = client.post(
        "/api/chat",
        json=_chat_payload(child_id=child.id, conversation_id=99999),
    )
    inactive = client.post(
        "/api/chat",
        json=_chat_payload(child_id=child.id, conversation_id=ended.id),
    )

    _error(missing, status=404, code="CONVERSATION_NOT_FOUND")
    _error(inactive, status=404, code="CONVERSATION_NOT_FOUND")
    assert fake_chat_ai.call_count == 0
    assert db_session.scalar(select(func.count(models.ChatRequestRecord.request_id))) == 0


@pytest.mark.parametrize("active", [False, None])
def test_missing_or_inactive_child_is_not_claimed_or_sent_to_ai(
    client,
    db_session,
    child_factory,
    fake_chat_ai,
    active,
):
    """Catches ledger rows or provider calls for missing/deactivated children."""
    child_id = child_factory(active=False).id if active is False else 99999

    response = client.post("/api/chat", json=_chat_payload(child_id=child_id))

    _error(response, status=404, code="CHILD_NOT_FOUND")
    assert fake_chat_ai.call_count == 0
    assert db_session.scalar(select(func.count(models.ChatRequestRecord.request_id))) == 0


def test_new_first_turn_is_rejected_when_the_child_already_has_an_active_conversation(
    client,
    db_session,
    child_factory,
    fake_chat_ai,
):
    """Catches first-turn races that leave an orphaned ledger beside an existing conversation."""
    child = child_factory()
    first = client.post("/api/chat", json=_chat_payload(child_id=child.id))
    assert first.status_code == 200

    rejected = client.post("/api/chat", json=_chat_payload(child_id=child.id))

    _error(rejected, status=409, code="ACTIVE_CONVERSATION_EXISTS")
    assert fake_chat_ai.call_count == 1
    assert db_session.scalar(select(func.count(models.ChatRequestRecord.request_id))) == 1


def test_max_round_close_writes_pair_and_pending_reason_without_ai(
    client,
    db_session,
    child_factory,
    fake_chat_ai,
):
    """Catches the fixed final turn calling AI or ending the conversation before completion."""
    child = child_factory()
    conversation = _active_conversation(db_session, child.id)
    _message(db_session, conversation.id, "child", "我喂了小黄")
    _message(db_session, conversation.id, "diary", "真棒！")
    _message(db_session, conversation.id, "child", "我还换了水")
    _message(db_session, conversation.id, "diary", "你真细心！")

    response = client.post(
        "/api/chat",
        json=_chat_payload(child_id=child.id, conversation_id=conversation.id, max_rounds=3),
    )

    assert response.status_code == 200
    assert response.json()["reply"] == "谢谢你今天的分享，鸭鸭日记本都记好啦！我们下次再见～"
    assert response.json()["ended"] is True
    assert response.json()["end_reason"] == "max_rounds"
    assert fake_chat_ai.call_count == 0
    db_session.expire_all()
    saved = db_session.get(models.Conversation, conversation.id)
    assert saved.status == "active"
    assert saved.pending_end_reason == "max_rounds"
    assert db_session.scalar(select(func.count(models.Message.id))) == 6


def test_pending_end_blocks_new_chat_but_still_replays_the_original_request(
    client,
    db_session,
    child_factory,
    fake_chat_ai,
):
    """Catches a new turn appended after a completed-looking chat awaits /complete."""
    child = child_factory()
    body = _chat_payload(child_id=child.id)
    fake_chat_ai.result = {"reply": "今天先说到这里吧。", "ended": True, "end_reason": "complete"}

    first = client.post("/api/chat", json=body)
    replay = client.post("/api/chat", json=body)
    blocked = client.post(
        "/api/chat",
        json=_chat_payload(
            child_id=child.id,
            conversation_id=first.json()["conversation_id"],
            text="我还想补充一点",
        ),
    )

    assert first.status_code == 200
    assert replay.json() == {**first.json(), "replayed": True}
    _error(blocked, status=409, code="CONVERSATION_COMPLETION_REQUIRED")
    db_session.expire_all()
    assert db_session.scalar(select(func.count(models.Message.id))) == 2
    assert fake_chat_ai.call_count == 1


def test_two_requests_from_the_same_base_allow_only_one_message_pair(
    db_session,
    child_factory,
):
    """Catches two distinct request IDs both committing after AI raced from one transcript boundary."""
    child = child_factory()
    conversation = _active_conversation(db_session, child.id)
    base_child = _message(db_session, conversation.id, "child", "我喂了小黄")
    _message(db_session, conversation.id, "diary", "它吃得怎么样？")
    first_payload = schemas.ChatRequest.model_validate(
        _chat_payload(child_id=child.id, conversation_id=conversation.id, text="它吃了菜叶")
    )
    second_payload = schemas.ChatRequest.model_validate(
        _chat_payload(child_id=child.id, conversation_id=conversation.id, text="我还换了水")
    )
    clock = datetime.utcnow()
    first_claim = claim_chat_request(
        db_session,
        first_payload,
        now=clock,
        business_date=clock.date(),
    )
    with SessionLocal() as concurrent_session:
        second_claim = claim_chat_request(
            concurrent_session,
            second_payload,
            now=clock,
            business_date=clock.date(),
        )

    committed = commit_chat_success(
        db_session,
        claim=first_claim,
        payload=first_payload,
        reply="记下来了。",
        ended=False,
        end_reason=None,
        now=clock,
    )
    with SessionLocal() as stale_session:
        with pytest.raises(APIError) as stale_result:
            commit_chat_success(
                stale_session,
                claim=second_claim,
                payload=second_payload,
                reply="不应写入。",
                ended=False,
                end_reason=None,
                now=clock,
            )
        assert stale_result.value.code == "CONVERSATION_CHANGED"

    db_session.expire_all()
    assert committed.child_message_id > base_child.id
    assert db_session.scalar(select(func.count(models.Message.id))) == 4
    assert db_session.get(models.ChatRequestRecord, second_claim.request_id).status == "failed"


def test_active_conversation_recovery_is_child_scoped_and_orders_transcript(
    client,
    db_session,
    child_factory,
):
    """Catches recovery leaking inactive children/conversations or misreporting transcript boundaries."""
    child = child_factory(name="小雨")
    active = _active_conversation(db_session, child.id)
    first = _message(db_session, active.id, "child", "我喂了小黄")
    _message(db_session, active.id, "diary", "它吃得怎么样？")
    _message(db_session, active.id, "child", "吃了很多菜叶")
    last = _message(db_session, active.id, "diary", "你观察得真仔细！")
    empty_child = child_factory(name="空空")
    empty_active = _active_conversation(db_session, empty_child.id)
    no_active_child = child_factory(name="没有活动会话")
    ended_child = child_factory(name="已结束")
    ended = models.Conversation(child_id=ended_child.id, date="2026-08-23", status="ended")
    inactive_child = child_factory(name="已停用", active=False)
    db_session.add(ended)
    db_session.commit()

    recovered = client.get(f"/api/children/{child.id}/active-conversation")
    empty = client.get(f"/api/children/{empty_child.id}/active-conversation")
    absent = client.get(f"/api/children/{no_active_child.id}/active-conversation")
    ended_response = client.get(f"/api/children/{ended_child.id}/active-conversation")
    inactive = client.get(f"/api/children/{inactive_child.id}/active-conversation")
    missing = client.get("/api/children/99999/active-conversation")

    assert recovered.json() == {
        "conversation": {
            "id": active.id,
            "child_id": child.id,
            "status": "active",
            "revision": 0,
            "round": 2,
            "last_message_id": last.id,
            "messages": [
                {"id": first.id, "role": "child", "text": "我喂了小黄"},
                {"id": first.id + 1, "role": "diary", "text": "它吃得怎么样？"},
                {"id": first.id + 2, "role": "child", "text": "吃了很多菜叶"},
                {"id": last.id, "role": "diary", "text": "你观察得真仔细！"},
            ],
        }
    }
    assert empty.json() == {
        "conversation": {
            "id": empty_active.id,
            "child_id": empty_child.id,
            "status": "active",
            "revision": 0,
            "round": 0,
            "last_message_id": None,
            "messages": [],
        }
    }
    assert absent.json() == {"conversation": None}
    assert ended_response.json() == {"conversation": None}
    _error(inactive, status=404, code="CHILD_NOT_FOUND")
    _error(missing, status=404, code="CHILD_NOT_FOUND")


def test_interleaved_expired_reclaim_allows_only_one_new_lease_owner(
    db_session,
    child_factory,
):
    """Catches stale ORM observations overwriting another session's new lease."""
    child = child_factory()
    conversation = _active_conversation(db_session, child.id)
    payload = schemas.ChatRequest.model_validate(
        _chat_payload(child_id=child.id, conversation_id=conversation.id)
    )
    clock = datetime.utcnow()
    db_session.add(
        models.ChatRequestRecord(
            request_id=str(payload.request_id),
            child_id=child.id,
            conversation_id=conversation.id,
            payload_hash=payload_hash(payload),
            status="processing",
            attempt_count=1,
            lease_owner="c" * 64,
            lease_expires_at=clock - timedelta(seconds=1),
        )
    )
    db_session.commit()

    with SessionLocal() as first_session, SessionLocal() as second_session:
        first_observation = chat_service._request_record(first_session, str(payload.request_id))
        second_observation = chat_service._request_record(second_session, str(payload.request_id))
        assert first_observation is not None
        assert second_observation is not None

        winner = chat_service._claim_from_existing(
            first_session,
            first_observation,
            expected_hash=payload_hash(payload),
            now=clock,
            lease_seconds=45,
        )
        with pytest.raises(APIError) as loser:
            chat_service._claim_from_existing(
                second_session,
                second_observation,
                expected_hash=payload_hash(payload),
                now=clock,
                lease_seconds=45,
            )

    assert loser.value.code == "REQUEST_IN_PROGRESS"
    assert loser.value.retryable is True
    db_session.expire_all()
    current = db_session.get(models.ChatRequestRecord, str(payload.request_id))
    assert current.status == "processing"
    assert current.attempt_count == 2
    assert current.lease_owner == winner.lease_owner
    assert db_session.scalar(select(func.count(models.Message.id))) == 0


@pytest.mark.parametrize("fault_target", ["context", "commit"])
def test_internal_chat_fault_marks_current_claim_failed_and_allows_retry(
    client,
    db_session,
    child_factory,
    fake_chat_ai,
    monkeypatch,
    fault_target,
):
    """Catches internal context/commit faults that leave a request processing until lease expiry."""
    child = child_factory()
    body = _chat_payload(child_id=child.id)
    if fault_target == "context":
        original = conversation_routes.build_chat_context

        def fail_context(*args, **kwargs):
            raise ValueError("provider-secret-must-not-leak")

        monkeypatch.setattr(conversation_routes, "build_chat_context", fail_context)
    else:
        original = conversation_routes.commit_chat_success

        def fail_commit(*args, **kwargs):
            raise ValueError("provider-secret-must-not-leak")

        monkeypatch.setattr(conversation_routes, "commit_chat_success", fail_commit)

    failed = client.post("/api/chat", json=body)

    _error(failed, status=500, code="INTERNAL_ERROR", retryable=True)
    db_session.expire_all()
    record = db_session.get(models.ChatRequestRecord, body["request_id"])
    assert record.status == "failed"
    assert record.last_error_code == "CHAT_INTERNAL_FAILED"
    assert db_session.scalar(select(func.count(models.Message.id))) == 0

    if fault_target == "context":
        monkeypatch.setattr(conversation_routes, "build_chat_context", original)
    else:
        monkeypatch.setattr(conversation_routes, "commit_chat_success", original)
    retried = client.post("/api/chat", json=body)

    assert retried.status_code == 200
    assert retried.json()["replayed"] is False
    assert fake_chat_ai.call_count == (1 if fault_target == "context" else 2)
    db_session.expire_all()
    assert db_session.get(models.ChatRequestRecord, body["request_id"]).status == "succeeded"
    assert db_session.scalar(select(func.count(models.Message.id))) == 2


def test_fixed_max_round_commit_fault_marks_current_claim_failed_and_allows_retry(
    client,
    db_session,
    child_factory,
    fake_chat_ai,
    monkeypatch,
):
    """Catches a fixed-close commit failure leaving its no-AI request processing."""
    child = child_factory()
    conversation = _active_conversation(db_session, child.id)
    _message(db_session, conversation.id, "child", "我喂了小黄")
    _message(db_session, conversation.id, "diary", "真棒！")
    _message(db_session, conversation.id, "child", "我还换了水")
    _message(db_session, conversation.id, "diary", "你真细心！")
    body = _chat_payload(
        child_id=child.id,
        conversation_id=conversation.id,
        max_rounds=3,
    )
    original = conversation_routes.commit_chat_success

    def fail_commit(*args, **kwargs):
        raise ValueError("provider-secret-must-not-leak")

    monkeypatch.setattr(conversation_routes, "commit_chat_success", fail_commit)
    failed = client.post("/api/chat", json=body)

    _error(failed, status=500, code="INTERNAL_ERROR", retryable=True)
    db_session.expire_all()
    record = db_session.get(models.ChatRequestRecord, body["request_id"])
    assert record.status == "failed"
    assert record.last_error_code == "CHAT_INTERNAL_FAILED"
    assert db_session.scalar(select(func.count(models.Message.id))) == 4

    monkeypatch.setattr(conversation_routes, "commit_chat_success", original)
    retried = client.post("/api/chat", json=body)

    assert retried.status_code == 200
    assert retried.json()["ended"] is True
    assert retried.json()["end_reason"] == "max_rounds"
    assert fake_chat_ai.call_count == 0
    db_session.expire_all()
    assert db_session.get(models.ChatRequestRecord, body["request_id"]).status == "succeeded"
    assert db_session.scalar(select(func.count(models.Message.id))) == 6
