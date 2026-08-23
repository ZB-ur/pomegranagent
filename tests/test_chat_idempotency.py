"""Contract tests for idempotent, recoverable child chat submissions."""
from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select, update

from app.backend import ai_engine, models, schemas
from app.backend.api_errors import APIError
from app.backend.database import SessionLocal
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
        self.result: object = {
            "reply": "真棒！还有呢？",
            "ended": False,
            "end_reason": None,
        }

    def __call__(self, **kwargs):
        self.call_count += 1
        self.calls.append(kwargs)
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


def _message(db_session, conversation_id: int, role: str, text: str) -> models.Message:
    message = models.Message(conversation_id=conversation_id, role=role, text=text)
    db_session.add(message)
    db_session.commit()
    return message


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
    first_claim = claim_chat_request(db_session, first_payload, now=clock)

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
    first_claim = claim_chat_request(db_session, first_payload, now=clock)
    with SessionLocal() as concurrent_session:
        second_claim = claim_chat_request(concurrent_session, second_payload, now=clock)

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
