"""Contracts for reversible child and duck resource deactivation."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone
import re
from threading import Event, Thread, current_thread
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError, OperationalError

from app.backend import models, schemas
from app.backend.api_errors import APIError
from app.backend.database import SessionLocal, engine
from app.backend.routes import resources as resource_routes
from app.backend.services.chat import build_chat_context, claim_chat_request
from app.backend.services.deactivation import set_child_active
from app.backend.services.reviews import get_review_detail


CHILD_AVATAR = "/api/media/avatars/00000000-0000-4000-8000-000000000001"
DUCK_AVATAR = "/api/media/avatars/00000000-0000-4000-8000-000000000002"
UPDATED_AVATAR = "/api/media/avatars/00000000-0000-4000-8000-000000000003"


def _unlock(client) -> None:
    response = client.post("/api/auth/setup", json={"pin": "1234"})
    assert response.status_code == 200


def _error(response, *, status: int, code: str) -> dict:
    assert response.status_code == status
    body = response.json()
    assert body["error"]["code"] == code
    return body["error"]


def _child(db_session, *, name: str = "小雨", active: bool = True) -> models.Child:
    child = models.Child(
        name=name,
        nickname=f"{name}小名",
        avatar=CHILD_AVATAR,
        active=active,
    )
    db_session.add(child)
    db_session.flush()
    return child


def _duck(db_session, *, name: str = "小黄", active: bool = True) -> models.Duck:
    duck = models.Duck(
        name=name,
        avatar=DUCK_AVATAR,
        status="健康",
        note="喜欢菜叶",
        active=active,
    )
    db_session.add(duck)
    db_session.flush()
    return duck


def _seed_child_history(db_session) -> tuple[models.Child, dict[str, list[int]]]:
    """Seed retained business history without calling application services."""
    child = _child(db_session)
    duck = _duck(db_session)
    today = date.today()
    db_session.add_all([
        models.DutyRoster(cycle="past", date=(today - timedelta(days=1)).isoformat(), child_id=child.id),
        models.DutyRoster(cycle="today", date=today.isoformat(), child_id=child.id),
        models.DutyRoster(cycle="future", date=(today + timedelta(days=1)).isoformat(), child_id=child.id),
    ])
    conversation = models.Conversation(
        child_id=child.id,
        date=(today - timedelta(days=1)).isoformat(),
        status="ended",
        end_reason="complete",
        started_at=datetime(2026, 8, 23, 8, 0),
        ended_at=datetime(2026, 8, 23, 8, 5),
    )
    db_session.add(conversation)
    db_session.flush()
    messages = [
        models.Message(conversation_id=conversation.id, role="child", text="我喂了小黄"),
        models.Message(conversation_id=conversation.id, role="diary", text="观察得真仔细"),
    ]
    db_session.add_all(messages)
    db_session.flush()
    conversation.frozen_last_message_id = messages[-1].id
    job = models.AnalysisJob(
        conversation_id=conversation.id,
        frozen_last_message_id=messages[-1].id,
        status="succeeded",
        attempt_count=1,
        max_attempts=3,
        available_at=datetime(2026, 8, 23, 8, 5),
        created_at=datetime(2026, 8, 23, 8, 5),
        updated_at=datetime(2026, 8, 23, 8, 5),
    )
    db_session.add(job)
    db_session.add(models.ChatRequestRecord(
        request_id=str(uuid4()),
        child_id=child.id,
        conversation_id=conversation.id,
        payload_hash="a" * 64,
        status="succeeded",
        attempt_count=1,
        available_at=datetime(2026, 8, 23, 8, 0),
        response_json="{}",
    ))
    db_session.add_all([
        models.FeedingLog(
            conversation_id=conversation.id,
            child_id=child.id,
            duck_id=duck.id,
            category="喂食",
            content="添加菜叶",
        ),
        models.EmotionLog(
            conversation_id=conversation.id,
            child_id=child.id,
            emotion="开心",
            intensity=4,
        ),
        models.InsightNote(
            conversation_id=conversation.id,
            child_id=child.id,
            content="愿意分享观察。",
        ),
    ])
    assessment = models.Assessment(
        conversation_id=conversation.id,
        child_id=child.id,
        status="pending",
        overall=4.0,
    )
    db_session.add(assessment)
    db_session.flush()
    dimension = db_session.scalar(
        select(models.AssessmentDimension).order_by(models.AssessmentDimension.id)
    )
    assert dimension is not None
    db_session.add(models.AssessmentScore(
        assessment_id=assessment.id,
        dimension_id=dimension.id,
        score=4,
        reason="完整保留",
    ))
    db_session.commit()
    tracked = {
        "roster": list(db_session.scalars(select(models.DutyRoster.id).order_by(models.DutyRoster.id))),
        "conversation": [conversation.id],
        "message": [message.id for message in messages],
        "chat_request": list(db_session.scalars(select(models.ChatRequestRecord.request_id))),
        "job": [job.id],
        "feeding": list(db_session.scalars(select(models.FeedingLog.id))),
        "emotion": list(db_session.scalars(select(models.EmotionLog.id))),
        "insight": list(db_session.scalars(select(models.InsightNote.id))),
        "assessment": [assessment.id],
        "score": list(db_session.scalars(select(models.AssessmentScore.id))),
    }
    return child, tracked


def _history_snapshot(db_session) -> dict[str, list[int | str]]:
    return {
        "roster": list(db_session.scalars(select(models.DutyRoster.id).order_by(models.DutyRoster.id))),
        "conversation": list(db_session.scalars(select(models.Conversation.id).order_by(models.Conversation.id))),
        "message": list(db_session.scalars(select(models.Message.id).order_by(models.Message.id))),
        "chat_request": list(db_session.scalars(select(models.ChatRequestRecord.request_id))),
        "job": list(db_session.scalars(select(models.AnalysisJob.id).order_by(models.AnalysisJob.id))),
        "feeding": list(db_session.scalars(select(models.FeedingLog.id).order_by(models.FeedingLog.id))),
        "emotion": list(db_session.scalars(select(models.EmotionLog.id).order_by(models.EmotionLog.id))),
        "insight": list(db_session.scalars(select(models.InsightNote.id).order_by(models.InsightNote.id))),
        "assessment": list(db_session.scalars(select(models.Assessment.id).order_by(models.Assessment.id))),
        "score": list(db_session.scalars(select(models.AssessmentScore.id).order_by(models.AssessmentScore.id))),
    }


def _resource_snapshot(db_session) -> dict[str, list[tuple | int | str]]:
    """Record every retained resource/history identity touched by state errors."""
    return {
        "children": [
            (row.id, row.active, row.deactivated_at)
            for row in db_session.scalars(select(models.Child).order_by(models.Child.id))
        ],
        "rosters": list(db_session.scalars(select(models.DutyRoster.id).order_by(models.DutyRoster.id))),
        "conversations": list(db_session.scalars(select(models.Conversation.id).order_by(models.Conversation.id))),
        "messages": list(db_session.scalars(select(models.Message.id).order_by(models.Message.id))),
        "chat_requests": list(db_session.scalars(select(models.ChatRequestRecord.request_id).order_by(models.ChatRequestRecord.request_id))),
        "jobs": list(db_session.scalars(select(models.AnalysisJob.id).order_by(models.AnalysisJob.id))),
        "feeding": list(db_session.scalars(select(models.FeedingLog.id).order_by(models.FeedingLog.id))),
        "emotions": list(db_session.scalars(select(models.EmotionLog.id).order_by(models.EmotionLog.id))),
        "insights": list(db_session.scalars(select(models.InsightNote.id).order_by(models.InsightNote.id))),
        "assessments": list(db_session.scalars(select(models.Assessment.id).order_by(models.Assessment.id))),
        "scores": list(db_session.scalars(select(models.AssessmentScore.id).order_by(models.AssessmentScore.id))),
    }


def _complete_snapshot(db_session) -> dict[str, dict[object, tuple[object, ...]]]:
    """Capture every race-relevant row from a fresh session for exact comparison."""
    return {
        "children": {
            row.id: (row.name, row.nickname, row.avatar, row.active, row.deactivated_at)
            for row in db_session.scalars(select(models.Child).order_by(models.Child.id))
        },
        "ducks": {
            row.id: (row.name, row.avatar, row.status, row.note, row.active, row.deactivated_at)
            for row in db_session.scalars(select(models.Duck).order_by(models.Duck.id))
        },
        "rosters": {
            row.id: (row.cycle, row.date, row.child_id)
            for row in db_session.scalars(select(models.DutyRoster).order_by(models.DutyRoster.id))
        },
        "conversations": {
            row.id: (
                row.child_id,
                row.date,
                row.started_at,
                row.ended_at,
                row.status,
                row.end_reason,
                row.revision,
                row.pending_end_reason,
                row.frozen_last_message_id,
            )
            for row in db_session.scalars(select(models.Conversation).order_by(models.Conversation.id))
        },
        "messages": {
            row.id: (row.conversation_id, row.role, row.text, row.created_at)
            for row in db_session.scalars(select(models.Message).order_by(models.Message.id))
        },
        "chat_requests": {
            row.request_id: (
                row.child_id,
                row.conversation_id,
                row.base_last_message_id,
                row.child_message_id,
                row.diary_message_id,
                row.payload_hash,
                row.status,
                row.attempt_count,
                row.available_at,
                row.lease_owner,
                row.lease_expires_at,
                row.last_error_code,
                row.last_error_message,
                row.response_json,
                row.started_at,
                row.finished_at,
                row.created_at,
                row.updated_at,
            )
            for row in db_session.scalars(
                select(models.ChatRequestRecord).order_by(models.ChatRequestRecord.request_id)
            )
        },
        "analysis_jobs": {
            row.id: (
                row.conversation_id,
                row.frozen_last_message_id,
                row.status,
                row.attempt_count,
                row.max_attempts,
                row.available_at,
                row.lease_owner,
                row.lease_expires_at,
                row.last_error_code,
                row.last_error_message,
                row.started_at,
                row.finished_at,
                row.created_at,
                row.updated_at,
            )
            for row in db_session.scalars(select(models.AnalysisJob).order_by(models.AnalysisJob.id))
        },
        "roster_requests": {
            row.request_id: (
                row.operation,
                row.payload_hash,
                row.status,
                row.response_json,
                row.last_error_code,
                row.last_error_message,
                row.created_at,
                row.updated_at,
            )
            for row in db_session.scalars(select(models.RosterRequest).order_by(models.RosterRequest.request_id))
        },
        "feeding_logs": {
            row.id: (row.conversation_id, row.child_id, row.duck_id, row.category, row.content, row.occurred_at)
            for row in db_session.scalars(select(models.FeedingLog).order_by(models.FeedingLog.id))
        },
        "emotion_logs": {
            row.id: (row.conversation_id, row.child_id, row.emotion, row.intensity, row.note, row.occurred_at)
            for row in db_session.scalars(select(models.EmotionLog).order_by(models.EmotionLog.id))
        },
        "insight_notes": {
            row.id: (row.conversation_id, row.child_id, row.content, row.created_at)
            for row in db_session.scalars(select(models.InsightNote).order_by(models.InsightNote.id))
        },
        "assessment_dimensions": {
            row.id: (row.key, row.name, row.enabled, row.weight, row.description)
            for row in db_session.scalars(
                select(models.AssessmentDimension).order_by(models.AssessmentDimension.id)
            )
        },
        "assessments": {
            row.id: (row.conversation_id, row.child_id, row.status, row.overall)
            for row in db_session.scalars(select(models.Assessment).order_by(models.Assessment.id))
        },
        "assessment_scores": {
            row.id: (row.assessment_id, row.dimension_id, row.score, row.reason)
            for row in db_session.scalars(select(models.AssessmentScore).order_by(models.AssessmentScore.id))
        },
        "duck_archives": {
            row.id: (row.duck_id, row.summary, row.updated_at)
            for row in db_session.scalars(select(models.DuckArchive).order_by(models.DuckArchive.id))
        },
        "teacher_credentials": {
            row.id: (row.pin_salt, row.pin_hash, row.created_at, row.updated_at)
            for row in db_session.scalars(
                select(models.TeacherCredential).order_by(models.TeacherCredential.id)
            )
        },
        "teacher_sessions": {
            row.id: (row.token_hash, row.created_at)
            for row in db_session.scalars(select(models.TeacherSession).order_by(models.TeacherSession.id))
        },
    }


def _assert_seeded_history_unchanged(
    before: dict[str, dict[object, tuple[object, ...]]],
    after: dict[str, dict[object, tuple[object, ...]]],
) -> None:
    """Every pre-race row is immutable; races may add only their winner rows."""
    for table, before_rows in before.items():
        if table == "children":
            continue
        retained = {key: after[table][key] for key in before_rows}
        assert retained == before_rows, table


_PATH_PARAMETER = re.compile(r"\{[^}]+\}")


def _normalized_path(path: str) -> str:
    return _PATH_PARAMETER.sub("{}", path)


def _effective_routes(routes) -> list[object]:
    """Flatten direct FastAPI routes and lazy `_IncludedRouter` wrappers."""
    effective: list[object] = []
    for route in routes:
        original_router = getattr(route, "original_router", None)
        if original_router is not None:
            effective.extend(_effective_routes(original_router.routes))
        elif getattr(route, "methods", None):
            effective.append(route)
    return effective


def _route_method_path_counts(routes) -> Counter[tuple[str, str]]:
    return Counter(
        (method, _normalized_path(route.path))
        for route in routes
        for method in route.methods
    )


def test_child_deactivation_preserves_history_and_reactivation_restores_today_visibility(
    client,
    db_session,
):
    """Catches a state change that deletes history, hides roster rows permanently, or lacks impact data."""
    child, before = _seed_child_history(db_session)
    _unlock(client)

    listed = client.get("/api/children", params={"include_inactive": "true"})

    assert listed.status_code == 200
    assert listed.json() == [{
        "id": child.id,
        "name": "小雨",
        "nickname": "小雨小名",
        "avatar": CHILD_AVATAR,
        "active": True,
        "deactivated_at": None,
        "future_roster_entries": 2,
        "has_active_conversation": False,
    }]
    assert client.get("/api/roster/today").json() == [{
        "id": child.id,
        "name": "小雨",
        "nickname": "小雨小名",
        "avatar": CHILD_AVATAR,
    }]

    deactivated = client.post(f"/api/children/{child.id}/deactivate")
    assert deactivated.status_code == 200
    body = deactivated.json()
    assert body == {
        "id": child.id,
        "kind": "child",
        "name": "小雨",
        "active": False,
        "deactivated_at": body["deactivated_at"],
        "affected_future_roster_entries": 2,
        "changed": True,
    }
    assert body["deactivated_at"].endswith("Z")
    assert _history_snapshot(db_session) == before
    assert client.get("/api/children").json() == []
    assert client.get("/api/roster/today").json() == []
    inactive = client.get("/api/children", params={"include_inactive": "true"})
    assert inactive.json()[0]["future_roster_entries"] == 2
    assert inactive.json()[0]["has_active_conversation"] is False

    repeated_deactivate = client.post(f"/api/children/{child.id}/deactivate")
    assert repeated_deactivate.json() == {**body, "changed": False}
    reactivated = client.post(f"/api/children/{child.id}/reactivate")
    assert reactivated.json() == {
        "id": child.id,
        "kind": "child",
        "name": "小雨",
        "active": True,
        "deactivated_at": None,
        "affected_future_roster_entries": 2,
        "changed": True,
    }
    assert client.get("/api/roster/today").json()[0]["id"] == child.id
    assert client.post(f"/api/children/{child.id}/reactivate").json() == {
        **reactivated.json(),
        "changed": False,
    }


def test_child_deactivation_uses_one_business_clock_sample_for_future_impact(
    client,
    db_session,
    monkeypatch,
):
    """Catches a UTC/host date dropping a Shanghai-local roster entry."""
    child = models.Child(name="跨午夜幼儿", nickname=None, avatar=None, active=True)
    db_session.add(child)
    db_session.flush()
    db_session.add_all([
        models.DutyRoster(cycle="boundary", date=day, child_id=child.id)
        for day in ("2026-09-01", "2026-09-02", "2026-09-03")
    ])
    db_session.commit()
    business_now = datetime(
        2026,
        9,
        1,
        23,
        59,
        tzinfo=ZoneInfo("Asia/Shanghai"),
    )

    class Clock:
        calls = 0

        @classmethod
        def business_now(cls) -> datetime:
            cls.calls += 1
            if cls.calls > 1:
                raise AssertionError("deactivation read the business clock twice")
            return business_now

    monkeypatch.setattr(resource_routes, "BUSINESS_CLOCK", Clock)
    _unlock(client)

    response = client.post(f"/api/children/{child.id}/deactivate")

    assert response.status_code == 200
    assert response.json()["affected_future_roster_entries"] == 3
    assert response.json()["deactivated_at"] == "2026-09-01T15:59:00Z"
    assert Clock.calls == 1


def test_duck_deactivation_filters_default_list_and_retains_feeding_history(client, db_session):
    """Catches a duck state change that hard-deletes its feeding/archive history or leaks it into default lists."""
    child = _child(db_session)
    duck = _duck(db_session)
    conversation = models.Conversation(
        child_id=child.id,
        date=date.today().isoformat(),
        status="ended",
        end_reason="complete",
        ended_at=datetime(2026, 8, 23, 8, 5),
    )
    db_session.add(conversation)
    db_session.flush()
    db_session.add_all([
        models.FeedingLog(
            conversation_id=conversation.id,
            child_id=child.id,
            duck_id=duck.id,
            category="喂食",
            content="第一条",
        ),
        models.FeedingLog(
            conversation_id=conversation.id,
            child_id=child.id,
            duck_id=duck.id,
            category="观察",
            content="第二条",
        ),
        models.DuckArchive(duck_id=duck.id, summary="历史档案"),
    ])
    db_session.commit()
    archive_id = db_session.scalar(select(models.DuckArchive.id))
    log_ids = list(db_session.scalars(select(models.FeedingLog.id).order_by(models.FeedingLog.id)))
    _unlock(client)

    response = client.post(f"/api/ducks/{duck.id}/deactivate")

    assert response.status_code == 200
    assert response.json()["affected_future_roster_entries"] == 0
    assert response.json()["active"] is False
    assert response.json()["deactivated_at"].endswith("Z")
    assert client.get("/api/ducks").json() == []
    included = client.get("/api/ducks", params={"include_inactive": "true"})
    assert included.json() == [{
        "id": duck.id,
        "name": "小黄",
        "avatar": DUCK_AVATAR,
        "status": "健康",
        "note": "喜欢菜叶",
        "active": False,
        "deactivated_at": response.json()["deactivated_at"],
        "historical_feeding_log_count": 2,
    }]
    assert list(db_session.scalars(select(models.FeedingLog.id).order_by(models.FeedingLog.id))) == log_ids
    assert db_session.scalar(select(models.DuckArchive.id)) == archive_id
    repeated_deactivate = client.post(f"/api/ducks/{duck.id}/deactivate")
    assert repeated_deactivate.json() == {
        **response.json(),
        "changed": False,
    }
    assert repeated_deactivate.json()["deactivated_at"] == response.json()["deactivated_at"]
    reactivated = client.post(f"/api/ducks/{duck.id}/reactivate")
    assert reactivated.json()["id"] == duck.id
    assert reactivated.json()["active"] is True
    assert reactivated.json()["deactivated_at"] is None
    assert client.post(f"/api/ducks/{duck.id}/reactivate").json() == {
        **reactivated.json(),
        "changed": False,
    }


def test_resource_state_routes_are_locked_and_hard_delete_is_an_auth_first_tombstone(client, db_session):
    """Catches public resource state mutation or a legacy DELETE that reads or deletes rows."""
    child = _child(db_session)
    duck = _duck(db_session)
    db_session.commit()
    counts = {
        "children": db_session.scalar(select(func.count(models.Child.id))),
        "ducks": db_session.scalar(select(func.count(models.Duck.id))),
    }

    for method, path in [
        ("get", "/api/children"),
        ("post", f"/api/children/{child.id}/deactivate"),
        ("post", f"/api/children/{child.id}/reactivate"),
        ("delete", f"/api/children/{child.id}"),
        ("get", "/api/ducks"),
        ("post", f"/api/ducks/{duck.id}/deactivate"),
        ("post", f"/api/ducks/{duck.id}/reactivate"),
        ("delete", f"/api/ducks/{duck.id}"),
    ]:
        _error(getattr(client, method)(path), status=401, code="TEACHER_AUTH_REQUIRED")

    _unlock(client)
    for path in [f"/api/children/{child.id}", "/api/children/99999", f"/api/ducks/{duck.id}", "/api/ducks/99999"]:
        _error(client.delete(path), status=410, code="HARD_DELETE_DISABLED")
    assert db_session.scalar(select(func.count(models.Child.id))) == counts["children"]
    assert db_session.scalar(select(func.count(models.Duck.id))) == counts["ducks"]


def test_child_with_an_active_conversation_cannot_be_deactivated_and_history_is_unchanged(
    client,
    db_session,
):
    """Catches deactivation that strands an active transcript behind an inactive child."""
    child = _child(db_session)
    conversation = models.Conversation(
        child_id=child.id,
        date=date.today().isoformat(),
        status="active",
    )
    db_session.add(conversation)
    db_session.commit()
    before = _resource_snapshot(db_session)
    _unlock(client)

    response = client.post(f"/api/children/{child.id}/deactivate")

    _error(response, status=409, code="ACTIVE_CONVERSATION_EXISTS")
    db_session.expire_all()
    assert db_session.get(models.Child, child.id).active is True
    assert _resource_snapshot(db_session) == before


@pytest.mark.parametrize("winner", ["chat", "deactivate"])
def test_race_first_conversation_and_deactivation_settle_without_partial_work_or_a_stale_inactive_conversation(
    db_session,
    winner,
):
    """Catches a race that mutates retained history or leaves first-turn work partially durable."""
    child, _ = _seed_child_history(db_session)
    with SessionLocal() as fresh:
        before = _complete_snapshot(fresh)
    now = datetime(2026, 8, 23, 9, 0, tzinfo=timezone.utc)
    payload = schemas.ChatRequest.model_validate({
        "request_id": str(uuid4()),
        "child_id": child.id,
        "text": "我给小黄添了菜叶",
        "conversation_id": None,
        "max_rounds": 3,
    })
    reached = Event()
    release = Event()
    deactivate_started = Event()
    outcomes: dict[str, object] = {}
    paused = False

    def pause_serialization_point(
        _connection,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        nonlocal paused
        normalized = statement.lower()
        if paused or current_thread().name != f"race-chat-{winner}":
            return
        should_pause = (
            winner == "chat" and "insert into conversations" in normalized
        ) or (
            winner == "deactivate"
            and "from conversations" in normalized
            and "conversations.status" in normalized
        )
        if should_pause:
            paused = True
            reached.set()
            assert release.wait(timeout=5)

    def claim_in_own_session() -> None:
        with SessionLocal() as session:
            try:
                outcomes["chat"] = claim_chat_request(
                    session,
                    payload,
                    now=now,
                    business_date=date(2026, 8, 23),
                )
            except BaseException as exc:  # inspected below to reject leaked database errors
                outcomes["chat"] = exc

    def deactivate_in_own_session() -> None:
        deactivate_started.set()
        with SessionLocal() as session:
            try:
                outcomes["deactivate"] = set_child_active(
                    session,
                    child_id=child.id,
                    active=False,
                    today=date.today(),
                    now=now,
                )
            except BaseException as exc:  # inspected below to reject leaked database errors
                outcomes["deactivate"] = exc

    event.listen(engine, "after_cursor_execute", pause_serialization_point)
    try:
        chat_thread = Thread(target=claim_in_own_session, name=f"race-chat-{winner}")
        chat_thread.start()
        assert reached.wait(timeout=5)
        deactivate_thread = Thread(target=deactivate_in_own_session, name=f"race-deactivate-{winner}")
        deactivate_thread.start()
        assert deactivate_started.wait(timeout=5)
        if winner == "deactivate":
            deactivate_thread.join(timeout=5)
            assert not deactivate_thread.is_alive()
        release.set()
        chat_thread.join(timeout=5)
        deactivate_thread.join(timeout=5)
    finally:
        event.remove(engine, "after_cursor_execute", pause_serialization_point)

    assert not chat_thread.is_alive()
    assert not deactivate_thread.is_alive()
    assert paused
    assert not any(isinstance(outcome, OperationalError) for outcome in outcomes.values())
    with SessionLocal() as fresh:
        after = _complete_snapshot(fresh)
    _assert_seeded_history_unchanged(before, after)
    assert not (
        after["children"][child.id][3] is False
        and any(
            row[0] == child.id and row[4] == "active"
            for row in after["conversations"].values()
        )
    )
    added_rows = {
        table: set(after[table]) - set(before[table])
        for table in before
    }
    assert all(
        after[table] == before[table]
        for table in before
        if table not in {"children", "conversations", "chat_requests"}
    )
    if winner == "chat":
        assert not isinstance(outcomes["chat"], BaseException)
        assert isinstance(outcomes["deactivate"], APIError)
        assert outcomes["deactivate"].code == "ACTIVE_CONVERSATION_EXISTS"
        assert after["children"] == before["children"]
        assert len(added_rows["conversations"]) == 1
        assert added_rows["chat_requests"] == {str(payload.request_id)}
        assert all(
            not added_rows[table]
            for table in before
            if table not in {"conversations", "chat_requests"}
        )
        new_conversation_id = added_rows["conversations"].pop()
        assert after["conversations"][new_conversation_id][0] == child.id
        assert after["conversations"][new_conversation_id][4] == "active"
        new_request = after["chat_requests"][str(payload.request_id)]
        assert new_request[1] == new_conversation_id
        assert new_request[6] == "processing"
    else:
        assert isinstance(outcomes["chat"], APIError)
        assert outcomes["chat"].code == "CHILD_NOT_FOUND"
        assert not isinstance(outcomes["deactivate"], BaseException)
        assert after["children"][child.id][:3] == before["children"][child.id][:3]
        assert after["children"][child.id][3:] == (False, after["children"][child.id][4])
        assert after["children"][child.id][4] is not None
        assert not added_rows["children"]
        assert all(
            not added_rows[table]
            for table in before
            if table != "children"
        )


def test_hard_delete_tombstones_have_stable_missing_codes_and_no_target_lookup_or_write(
    client,
    db_session,
):
    """Catches unstable missing-resource errors or a DELETE tombstone that touches its target table."""
    child = _child(db_session)
    duck = _duck(db_session)
    db_session.commit()
    child_id = child.id
    duck_id = duck.id
    _unlock(client)
    _error(client.post("/api/children/99999/deactivate"), status=404, code="CHILD_NOT_FOUND")
    _error(client.post("/api/children/99999/reactivate"), status=404, code="CHILD_NOT_FOUND")
    _error(client.post("/api/ducks/99999/deactivate"), status=404, code="DUCK_NOT_FOUND")
    _error(client.post("/api/ducks/99999/reactivate"), status=404, code="DUCK_NOT_FOUND")
    statements: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany) -> None:
        statements.append(statement.lower())

    event.listen(engine, "before_cursor_execute", capture)
    try:
        for path in [
            f"/api/children/{child_id}",
            "/api/children/99999",
            f"/api/ducks/{duck_id}",
            "/api/ducks/99999",
        ]:
            _error(client.delete(path), status=410, code="HARD_DELETE_DISABLED")
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    assert len(statements) == 4
    assert all("teacher_sessions" in statement for statement in statements)
    assert not any("from children" in statement or "from ducks" in statement for statement in statements)
    assert db_session.scalar(select(func.count(models.Child.id))) == 1
    assert db_session.scalar(select(func.count(models.Duck.id))) == 1


def test_resource_route_inventory_flattens_direct_and_included_routes_and_rejects_legacy_parameter_aliases():
    """Catches a legacy direct `/{id}` handler that escapes a non-normalized route inventory."""
    from app.backend.auth import require_teacher_session
    from app.backend.database import get_db
    from app.backend.main import app

    canonical = {
        ("GET", "/api/children"),
        ("POST", "/api/children"),
        ("PUT", "/api/children/{}"),
        ("DELETE", "/api/children/{}"),
        ("POST", "/api/children/{}/deactivate"),
        ("POST", "/api/children/{}/reactivate"),
        ("GET", "/api/ducks"),
        ("POST", "/api/ducks"),
        ("PUT", "/api/ducks/{}"),
        ("DELETE", "/api/ducks/{}"),
        ("POST", "/api/ducks/{}/deactivate"),
        ("POST", "/api/ducks/{}/reactivate"),
    }
    effective_routes = _effective_routes(app.routes)
    counts = _route_method_path_counts(effective_routes)

    assert {pair for pair in counts if pair in canonical} == canonical
    assert all(counts[pair] == 1 for pair in canonical)
    for method, normalized_path in canonical:
        matching = [
            route
            for route in effective_routes
            if method in route.methods and _normalized_path(route.path) == normalized_path
        ]
        assert len(matching) == 1
        direct_calls = [dependency.call for dependency in matching[0].dependant.dependencies]
        assert any(
            dependency.call is require_teacher_session
            for dependency in matching[0].dependant.dependencies
        ), (method, normalized_path)
        if method == "DELETE":
            assert direct_calls == [require_teacher_session]
            assert get_db not in direct_calls

    child_delete = next(
        route
        for route in effective_routes
        if route.path == "/api/children/{child_id}" and "DELETE" in route.methods
    )
    with_legacy_alias = _route_method_path_counts([
        child_delete,
        SimpleNamespace(path="/api/children/{id}", methods={"DELETE"}),
    ])
    assert with_legacy_alias[("DELETE", "/api/children/{}")] == 2
    assert any(route.path == "/api/roster/today" for route in effective_routes)


def test_query_count_resource_lists_are_ordered_and_use_one_composed_query_after_teacher_auth(client, db_session):
    """Catches list impact lookups that grow one count/existence statement per resource."""
    first = _child(db_session, name="甲")
    inactive = _child(db_session, name="乙", active=False)
    last = _child(db_session, name="丙")
    first_duck = _duck(db_session, name="黄")
    inactive_duck = _duck(db_session, name="灰", active=False)
    db_session.add_all([
        models.DutyRoster(cycle="impact", date=date.today().isoformat(), child_id=first.id),
        models.DutyRoster(cycle="impact", date=(date.today() + timedelta(days=1)).isoformat(), child_id=inactive.id),
        models.Conversation(child_id=last.id, date=date.today().isoformat(), status="active"),
    ])
    db_session.flush()
    conversation = db_session.scalar(select(models.Conversation).where(models.Conversation.child_id == last.id))
    assert conversation is not None
    db_session.add_all([
        models.FeedingLog(
            conversation_id=conversation.id,
            child_id=last.id,
            duck_id=first_duck.id,
            category="喂食",
            content="保留",
        ),
        models.FeedingLog(
            conversation_id=conversation.id,
            child_id=last.id,
            duck_id=inactive_duck.id,
            category="观察",
            content="保留",
        ),
    ])
    db_session.commit()
    _unlock(client)
    statements: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany) -> None:
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        children = client.get("/api/children", params={"include_inactive": "true"})
        child_query_count = len(statements)
        ducks = client.get("/api/ducks", params={"include_inactive": "true"})
        duck_query_count = len(statements) - child_query_count
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    assert children.status_code == 200
    assert [row["id"] for row in children.json()] == [first.id, inactive.id, last.id]
    assert children.json()[1]["future_roster_entries"] == 1
    assert children.json()[2]["has_active_conversation"] is True
    assert ducks.status_code == 200
    assert [row["id"] for row in ducks.json()] == [first_duck.id, inactive_duck.id]
    assert [row["historical_feeding_log_count"] for row in ducks.json()] == [1, 1]
    assert child_query_count == 2  # one teacher-session lookup + one resource list statement
    assert duck_query_count == 2


def test_resource_crud_forces_creation_active_and_cannot_bypass_state_routes(client, db_session):
    """Catches legacy ChildCreate.active being able to deactivate resources outside state routes."""
    _unlock(client)
    created = client.post("/api/children", json={
        "name": "新同学",
        "nickname": "新",
        "avatar": CHILD_AVATAR,
        "active": False,
    })
    assert created.status_code == 200
    child = created.json()
    assert child["active"] is True
    updated = client.put(f"/api/children/{child['id']}", json={
        "name": "改名",
        "nickname": "改",
        "avatar": UPDATED_AVATAR,
        "active": False,
    })
    assert updated.status_code == 200
    assert updated.json() == {
        "id": child["id"],
        "name": "改名",
        "nickname": "改",
        "avatar": UPDATED_AVATAR,
        "active": True,
    }
    db_session.expire_all()
    persisted = db_session.get(models.Child, child["id"])
    assert persisted is not None
    assert persisted.active is True
    assert persisted.deactivated_at is None
    _error(client.put("/api/children/99999", json={"name": "缺失"}), status=404, code="CHILD_NOT_FOUND")
    _error(client.put("/api/ducks/99999", json={"name": "缺失"}), status=404, code="DUCK_NOT_FOUND")
    _error(client.post("/api/children", json={"name": "错误", "active": "not-a-bool"}), status=422, code="VALIDATION_ERROR")


def test_inactive_duck_is_excluded_from_new_chat_context_but_retained_in_historical_review(
    client,
    db_session,
):
    """Catches deactivation erasing historical duck IDs or leaving the duck in new chat context."""
    child = _child(db_session)
    duck = _duck(db_session)
    conversation = models.Conversation(
        child_id=child.id,
        date=date.today().isoformat(),
        status="ended",
        end_reason="complete",
        started_at=datetime(2026, 8, 23, 8, 0),
        ended_at=datetime(2026, 8, 23, 8, 5),
    )
    db_session.add(conversation)
    db_session.flush()
    message = models.Message(conversation_id=conversation.id, role="child", text="历史内容")
    db_session.add(message)
    db_session.flush()
    conversation.frozen_last_message_id = message.id
    db_session.add_all([
        models.AnalysisJob(
            conversation_id=conversation.id,
            frozen_last_message_id=message.id,
            status="succeeded",
            attempt_count=1,
            max_attempts=3,
            available_at=datetime(2026, 8, 23, 8, 5),
            created_at=datetime(2026, 8, 23, 8, 5),
            updated_at=datetime(2026, 8, 23, 8, 5),
        ),
        models.FeedingLog(
            conversation_id=conversation.id,
            child_id=child.id,
            duck_id=duck.id,
            category="喂食",
            content="历史喂食",
        ),
        models.EmotionLog(conversation_id=conversation.id, child_id=child.id, emotion="开心", intensity=4),
        models.InsightNote(conversation_id=conversation.id, child_id=child.id, content="历史洞察"),
    ])
    assessment = models.Assessment(
        conversation_id=conversation.id,
        child_id=child.id,
        status="pending",
        overall=4.0,
    )
    db_session.add(assessment)
    db_session.flush()
    dimension = db_session.scalar(select(models.AssessmentDimension).order_by(models.AssessmentDimension.id))
    assert dimension is not None
    db_session.add(models.AssessmentScore(
        assessment_id=assessment.id,
        dimension_id=dimension.id,
        score=4,
        reason="历史理由",
    ))
    db_session.commit()
    _unlock(client)
    assert client.post(f"/api/ducks/{duck.id}/deactivate").status_code == 200

    with SessionLocal() as historical:
        detail = get_review_detail(historical, conversation_id=conversation.id)
    assert detail.review is not None
    assert detail.review.feeding_logs[0].duck_id == duck.id
    payload = schemas.ChatRequest.model_validate({
        "request_id": str(uuid4()),
        "child_id": child.id,
        "text": "新的问题",
        "conversation_id": None,
        "max_rounds": 3,
    })
    with SessionLocal() as chat_db:
        claim = claim_chat_request(
            chat_db,
            payload,
            now=datetime(2026, 8, 23, 9, 0),
            business_date=date(2026, 8, 23),
        )
        context = build_chat_context(chat_db, claim, payload)
        chat_db.rollback()
    assert duck.name not in context.ducks_info


@pytest.mark.parametrize("failure", ["flush", "commit"])
def test_rollback_state_write_failures_preserve_child_state_from_a_fresh_session(db_session, monkeypatch, failure):
    """Catches a failed state change that leaves active/deactivated_at half-persisted."""
    child = _child(db_session)
    db_session.commit()
    before = (child.active, child.deactivated_at)
    if failure == "flush":
        def fail_flush(*_args, **_kwargs):
            raise RuntimeError("forced state flush failure")

        monkeypatch.setattr(db_session, "flush", fail_flush)
    else:
        def fail_commit(*_args, **_kwargs):
            raise RuntimeError("forced state commit failure")

        monkeypatch.setattr(db_session, "commit", fail_commit)

    with pytest.raises(RuntimeError, match=rf"forced state {failure} failure"):
        set_child_active(
            db_session,
            child_id=child.id,
            active=False,
            today=date.today(),
            now=datetime(2026, 8, 23, 9, 0, tzinfo=timezone.utc),
        )
    with SessionLocal() as fresh:
        current = fresh.get(models.Child, child.id)
        assert current is not None
        assert (current.active, current.deactivated_at) == before


def test_unrelated_state_integrity_error_is_not_mislabeled(db_session, monkeypatch):
    """Catches broad IntegrityError handling that hides a non-state database failure."""
    child = _child(db_session)
    db_session.commit()
    expected = IntegrityError("UPDATE unrelated", {}, Exception("unrelated constraint"))

    def fail_flush(*_args, **_kwargs):
        raise expected

    monkeypatch.setattr(db_session, "flush", fail_flush)
    with pytest.raises(IntegrityError) as raised:
        set_child_active(
            db_session,
            child_id=child.id,
            active=False,
            today=date.today(),
            now=datetime(2026, 8, 23, 9, 0, tzinfo=timezone.utc),
        )
    assert raised.value is expected
    with SessionLocal() as fresh:
        current = fresh.get(models.Child, child.id)
        assert current is not None
        assert current.active is True
