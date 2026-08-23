"""Contract tests for atomic, replayable conversation completion."""
from __future__ import annotations

from datetime import datetime, timezone
from threading import Event, Thread
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.dml import Update

from app.backend import models, schemas
from app.backend.api_errors import APIError
from app.backend.database import SessionLocal
from app.backend.routes import conversations as conversation_routes
from app.backend.services import chat as chat_service
from app.backend.services import completion as completion_service
from app.backend.services.chat import claim_chat_request, commit_chat_success


@pytest.fixture
def conversation_with_messages(db_session):
    def create(*, child_turns: int = 2, pending_end_reason: str | None = None):
        child = models.Child(name="小雨", nickname="雨雨", active=True)
        db_session.add(child)
        db_session.commit()

        conversation = models.Conversation(
            child_id=child.id,
            date="2026-08-23",
            status="active",
            pending_end_reason=pending_end_reason,
        )
        db_session.add(conversation)
        db_session.commit()

        for turn in range(child_turns):
            db_session.add_all(
                [
                    models.Message(
                        conversation_id=conversation.id,
                        role="child",
                        text=f"我观察到第 {turn + 1} 件事",
                    ),
                    models.Message(
                        conversation_id=conversation.id,
                        role="diary",
                        text=f"谢谢你的第 {turn + 1} 次分享",
                    ),
                ]
            )
        db_session.commit()
        messages = db_session.scalars(
            select(models.Message)
            .where(models.Message.conversation_id == conversation.id)
            .order_by(models.Message.id)
        ).all()
        return conversation, messages

    return create


def _error(response, *, status: int, code: str) -> None:
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert response.json()["error"]["retryable"] is False


def _job_count(db_session, conversation_id: int) -> int:
    return db_session.scalar(
        select(func.count(models.AnalysisJob.id)).where(
            models.AnalysisJob.conversation_id == conversation_id
        )
    )


def test_complete_freezes_messages_and_creates_one_pending_job(
    client,
    db_session,
    conversation_with_messages,
    monkeypatch,
):
    """Catches ending without a frozen boundary, durable job, or frozen DTO."""
    conversation, messages = conversation_with_messages(
        child_turns=2,
        pending_end_reason="complete",
    )
    completed_at = datetime(2026, 8, 23, 8, 35, 10, tzinfo=timezone.utc)

    class Clock:
        calls = 0

        @classmethod
        def now(cls, tz):
            assert tz is timezone.utc
            cls.calls += 1
            return completed_at

    monkeypatch.setattr(conversation_routes, "datetime", Clock)

    response = client.post(
        f"/api/conversations/{conversation.id}/complete",
        json={"expected_last_message_id": messages[-1].id},
    )

    assert response.status_code == 200
    assert response.json() == {
        "conversation_id": conversation.id,
        "conversation_saved": True,
        "status": "completed",
        "completed_at": "2026-08-23T08:35:10Z",
        "message_count": 4,
        "last_message_id": messages[-1].id,
        "analysis_job_id": 1,
        "analysis_status": "pending",
        "replayed": False,
    }
    assert Clock.calls == 1
    db_session.expire_all()
    saved = db_session.get(models.Conversation, conversation.id)
    job = db_session.scalar(
        select(models.AnalysisJob).where(
            models.AnalysisJob.conversation_id == conversation.id
        )
    )
    assert saved is not None
    assert saved.status == "ended"
    assert saved.end_reason == "complete"
    assert saved.ended_at == completed_at.replace(tzinfo=None)
    assert saved.frozen_last_message_id == messages[-1].id
    assert saved.revision == 1
    assert job is not None
    assert job.frozen_last_message_id == messages[-1].id
    assert job.status == "pending"


def test_complete_replays_the_frozen_snapshot_without_a_second_job(
    client,
    db_session,
    conversation_with_messages,
    monkeypatch,
):
    """Catches a lost response retry that increments revision or enqueues twice."""
    conversation, messages = conversation_with_messages()
    payload = {"expected_last_message_id": messages[-1].id}
    completed_at = datetime(2026, 8, 23, 8, 35, 10, tzinfo=timezone.utc)

    class Clock:
        @classmethod
        def now(cls, tz):
            assert tz is timezone.utc
            return completed_at

    monkeypatch.setattr(conversation_routes, "datetime", Clock)

    first = client.post(f"/api/conversations/{conversation.id}/complete", json=payload)
    second = client.post(f"/api/conversations/{conversation.id}/complete", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["completed_at"] == "2026-08-23T08:35:10Z"
    assert second.json() == {**first.json(), "replayed": True}
    db_session.expire_all()
    saved = db_session.get(models.Conversation, conversation.id)
    assert saved is not None
    assert saved.status == "ended"
    assert saved.end_reason == "manual"
    assert saved.revision == 1
    assert _job_count(db_session, conversation.id) == 1


def test_complete_rejects_a_stale_active_boundary_without_writing(
    client,
    db_session,
    conversation_with_messages,
):
    """Catches saving a changed active transcript or enqueuing analysis for it."""
    conversation, messages = conversation_with_messages()

    response = client.post(
        f"/api/conversations/{conversation.id}/complete",
        json={"expected_last_message_id": messages[-2].id},
    )

    _error(response, status=409, code="CONVERSATION_CHANGED")
    db_session.expire_all()
    saved = db_session.get(models.Conversation, conversation.id)
    assert saved is not None
    assert saved.status == "active"
    assert saved.end_reason is None
    assert saved.ended_at is None
    assert saved.frozen_last_message_id is None
    assert saved.revision == 0
    assert _job_count(db_session, conversation.id) == 0


def test_complete_rejects_a_different_boundary_after_the_conversation_ended(
    client,
    db_session,
    conversation_with_messages,
):
    """Catches replay validation that accepts a different frozen transcript ID."""
    conversation, messages = conversation_with_messages()
    completed = client.post(
        f"/api/conversations/{conversation.id}/complete",
        json={"expected_last_message_id": messages[-1].id},
    )
    assert completed.status_code == 200

    changed = client.post(
        f"/api/conversations/{conversation.id}/complete",
        json={"expected_last_message_id": messages[-2].id},
    )

    _error(changed, status=409, code="CONVERSATION_CHANGED")
    db_session.expire_all()
    saved = db_session.get(models.Conversation, conversation.id)
    assert saved is not None
    assert saved.revision == 1
    assert saved.frozen_last_message_id == messages[-1].id
    assert _job_count(db_session, conversation.id) == 1


def test_complete_rejects_an_empty_active_conversation_without_writing(
    client,
    db_session,
    conversation_with_messages,
):
    """Catches completion that creates an analysis job without any transcript."""
    conversation, _ = conversation_with_messages(child_turns=0)

    response = client.post(
        f"/api/conversations/{conversation.id}/complete",
        json={"expected_last_message_id": 1},
    )

    _error(response, status=409, code="CONVERSATION_EMPTY")
    db_session.expire_all()
    saved = db_session.get(models.Conversation, conversation.id)
    assert saved is not None
    assert saved.status == "active"
    assert saved.ended_at is None
    assert saved.frozen_last_message_id is None
    assert saved.revision == 0
    assert _job_count(db_session, conversation.id) == 0


def test_complete_reports_a_missing_conversation(client):
    """Catches treating an absent conversation as a changed or empty transcript."""
    response = client.post(
        "/api/conversations/99999/complete",
        json={"expected_last_message_id": 1},
    )

    _error(response, status=404, code="CONVERSATION_NOT_FOUND")


def test_complete_body_forbids_unknown_fields_without_writing(
    client,
    db_session,
    conversation_with_messages,
):
    """Catches accepting non-contract completion command fields."""
    conversation, messages = conversation_with_messages()

    response = client.post(
        f"/api/conversations/{conversation.id}/complete",
        json={
            "expected_last_message_id": messages[-1].id,
            "unexpected": "not part of the completion command",
        },
    )

    _error(response, status=422, code="VALIDATION_ERROR")
    db_session.expire_all()
    saved = db_session.get(models.Conversation, conversation.id)
    assert saved is not None
    assert saved.status == "active"
    assert _job_count(db_session, conversation.id) == 0


def test_completion_unique_job_conflict_replays_the_committed_snapshot(
    client,
    db_session,
    conversation_with_messages,
):
    """Catches a stale concurrent session surfacing a unique conflict as a second job."""
    conversation, messages = conversation_with_messages()
    payload = {"expected_last_message_id": messages[-1].id}

    with SessionLocal() as stale_session:
        stale_conversation = stale_session.get(models.Conversation, conversation.id)
        assert stale_conversation is not None
        assert stale_conversation.status == "active"

        committed = client.post(
            f"/api/conversations/{conversation.id}/complete",
            json=payload,
        )
        assert committed.status_code == 200

        from app.backend.services.completion import complete_conversation

        replay = complete_conversation(
            stale_session,
            conversation_id=conversation.id,
            expected_last_message_id=messages[-1].id,
            now=datetime(2026, 8, 23, 8, 36, 10),
        )

    assert replay.model_dump(mode="json") == {
        **committed.json(),
        "replayed": True,
    }
    db_session.expire_all()
    assert _job_count(db_session, conversation.id) == 1
    assert db_session.get(models.Conversation, conversation.id).revision == 1


def test_completion_write_lock_serializes_a_final_chat_commit(
    db_session,
    conversation_with_messages,
    monkeypatch,
):
    """Catches a chat pair appended after completion read but before it freezes."""
    conversation, messages = conversation_with_messages()
    expected_last_message_id = messages[-1].id
    payload = schemas.ChatRequest.model_validate(
        {
            "request_id": str(uuid4()),
            "child_id": conversation.child_id,
            "conversation_id": conversation.id,
            "text": "我还想补充最后一件事",
            "max_rounds": 3,
        }
    )
    clock = datetime(2026, 8, 23, 8, 38, 10)
    claim = claim_chat_request(db_session, payload, now=clock)

    completion_lock_acquired = Event()
    chat_attempted_write = Event()
    release_completion = Event()
    results: dict[str, object] = {}
    completion_session = SessionLocal()
    original_execute = completion_session.execute
    original_claim_update = chat_service._claim_update

    def pause_after_completion_lock(statement, *args, **kwargs):
        result = original_execute(statement, *args, **kwargs)
        if isinstance(statement, Update):
            completion_lock_acquired.set()
            assert release_completion.wait(timeout=5)
        return result

    def signal_chat_write_attempt(*args, **kwargs):
        chat_attempted_write.set()
        return original_claim_update(*args, **kwargs)

    monkeypatch.setattr(completion_session, "execute", pause_after_completion_lock)
    monkeypatch.setattr(chat_service, "_claim_update", signal_chat_write_attempt)

    def run_completion() -> None:
        try:
            results["completion"] = completion_service.complete_conversation(
                completion_session,
                conversation_id=conversation.id,
                expected_last_message_id=expected_last_message_id,
                now=clock,
            )
        except Exception as exc:  # pragma: no cover - asserted below
            results["completion_error"] = exc

    def run_chat() -> None:
        with SessionLocal() as chat_session:
            try:
                results["chat"] = commit_chat_success(
                    chat_session,
                    claim=claim,
                    payload=payload,
                    reply="这句不能在冻结后写入。",
                    ended=False,
                    end_reason=None,
                    now=clock,
                )
            except Exception as exc:  # pragma: no cover - asserted below
                results["chat_error"] = exc

    completion_thread = Thread(target=run_completion)
    chat_thread = Thread(target=run_chat)
    chat_started = False
    completion_thread.start()
    try:
        assert completion_lock_acquired.wait(timeout=2), (
            "completion must acquire its conditional write lock before reading messages"
        )
        chat_thread.start()
        chat_started = True
        assert chat_attempted_write.wait(timeout=2)
        release_completion.set()
        completion_thread.join(timeout=5)
        chat_thread.join(timeout=5)
        assert not completion_thread.is_alive()
        assert not chat_thread.is_alive()
    finally:
        release_completion.set()
        completion_thread.join(timeout=5)
        if chat_started:
            chat_thread.join(timeout=5)
        completion_session.close()

    assert "completion_error" not in results
    assert results["completion"].replayed is False
    assert "chat" not in results
    assert isinstance(results.get("chat_error"), APIError)
    assert results["chat_error"].code == "CONVERSATION_CHANGED"
    with SessionLocal() as fresh_session:
        saved = fresh_session.get(models.Conversation, conversation.id)
        actual_last_message_id = fresh_session.scalar(
            select(models.Message.id)
            .where(models.Message.conversation_id == conversation.id)
            .order_by(models.Message.id.desc())
            .limit(1)
        )
        assert saved is not None
        assert saved.status == "ended"
        assert saved.frozen_last_message_id == actual_last_message_id
        assert saved.frozen_last_message_id == expected_last_message_id
        assert _job_count(fresh_session, conversation.id) == 1


def test_completion_preserves_an_unrelated_integrity_error(
    db_session,
    conversation_with_messages,
    monkeypatch,
):
    """Catches an unrelated database integrity failure rewritten as transcript drift."""
    conversation, messages = conversation_with_messages()
    original_error = IntegrityError(
        "forced unrelated integrity failure",
        {},
        RuntimeError("unrelated constraint"),
    )

    def fail_flush(*args, **kwargs):
        raise original_error

    monkeypatch.setattr(db_session, "flush", fail_flush)

    with pytest.raises(IntegrityError) as raised:
        completion_service.complete_conversation(
            db_session,
            conversation_id=conversation.id,
            expected_last_message_id=messages[-1].id,
            now=datetime(2026, 8, 23, 8, 39, 10),
        )

    assert raised.value is original_error
    assert not db_session.in_transaction()
    with SessionLocal() as fresh_session:
        saved = fresh_session.get(models.Conversation, conversation.id)
        assert saved is not None
        assert saved.status == "active"
        assert saved.end_reason is None
        assert saved.ended_at is None
        assert saved.frozen_last_message_id is None
        assert saved.revision == 0
        assert _job_count(fresh_session, conversation.id) == 0


@pytest.mark.parametrize("operation", ["flush", "commit"])
def test_completion_write_failure_rolls_back_the_job_and_end_state(
    client,
    db_session,
    conversation_with_messages,
    monkeypatch,
    operation,
):
    """Catches a write error that persists either completion state or its job alone."""
    probe, probe_messages = conversation_with_messages()
    assert client.post(
        f"/api/conversations/{probe.id}/complete",
        json={"expected_last_message_id": probe_messages[-1].id},
    ).status_code == 200

    conversation, messages = conversation_with_messages()
    from app.backend.services.completion import complete_conversation

    def fail_write(*args, **kwargs):
        raise RuntimeError(f"forced {operation} failure")

    with monkeypatch.context() as patch:
        patch.setattr(db_session, operation, fail_write)
        with pytest.raises(RuntimeError, match=f"forced {operation} failure"):
            complete_conversation(
                db_session,
                conversation_id=conversation.id,
                expected_last_message_id=messages[-1].id,
                now=datetime(2026, 8, 23, 8, 37, 10),
            )

    with SessionLocal() as fresh_session:
        saved = fresh_session.get(models.Conversation, conversation.id)
        assert saved is not None
        assert saved.status == "active"
        assert saved.end_reason is None
        assert saved.ended_at is None
        assert saved.frozen_last_message_id is None
        assert saved.revision == 0
        assert _job_count(fresh_session, conversation.id) == 0
