"""Contract tests for atomic, replayable conversation completion."""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import func, select

from app.backend import models
from app.backend.database import SessionLocal
from app.backend.routes import conversations as conversation_routes


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
    completed_at = datetime(2026, 8, 23, 8, 35, 10)

    class Clock:
        calls = 0

        @classmethod
        def utcnow(cls):
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
        "completed_at": completed_at.isoformat(),
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
    assert saved.ended_at == completed_at
    assert saved.frozen_last_message_id == messages[-1].id
    assert saved.revision == 1
    assert job is not None
    assert job.frozen_last_message_id == messages[-1].id
    assert job.status == "pending"


def test_complete_replays_the_frozen_snapshot_without_a_second_job(
    client,
    db_session,
    conversation_with_messages,
):
    """Catches a lost response retry that increments revision or enqueues twice."""
    conversation, messages = conversation_with_messages()
    payload = {"expected_last_message_id": messages[-1].id}

    first = client.post(f"/api/conversations/{conversation.id}/complete", json=payload)
    second = client.post(f"/api/conversations/{conversation.id}/complete", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
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
