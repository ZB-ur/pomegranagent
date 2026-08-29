"""Bounded, teacher-only conversation history contract."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import nan

import pytest
from sqlalchemy import event, select

from app.backend import models, schemas
from app.backend.api_errors import APIError
from app.backend.routes.conversations import router as conversations_router
from app.backend.services.history import list_conversation_history


NOW = datetime(2026, 8, 23, 9, 0, tzinfo=timezone.utc)


def _unlock(client) -> None:
    response = client.post("/api/auth/setup", json={"pin": "1234"})
    assert response.status_code == 200


def _error(response, status: int, code: str) -> dict:
    assert response.status_code == status
    body = response.json()
    assert body["error"]["code"] == code
    return body["error"]


def _seed_history(
    db_session,
    *,
    job_status: str = "succeeded",
    review_status: str = "pending",
    child_active: bool = True,
    minutes: int = 0,
    with_projection: bool | None = None,
):
    if with_projection is None:
        with_projection = job_status == "succeeded"
    child = models.Child(
        name=f"历史幼儿-{minutes}-{job_status}",
        nickname="小史",
        avatar="history.png",
        active=child_active,
    )
    db_session.add(child)
    db_session.flush()
    ended_at = NOW - timedelta(minutes=minutes)
    conversation = models.Conversation(
        child_id=child.id,
        date="2026-08-23",
        status="ended",
        end_reason="max_rounds",
        started_at=ended_at - timedelta(minutes=5),
        ended_at=ended_at,
        revision=minutes,
    )
    db_session.add(conversation)
    db_session.flush()
    messages = [
        models.Message(
            conversation_id=conversation.id,
            role="child" if index % 2 == 0 else "diary",
            text=f"冻结消息 {index + 1}",
        )
        for index in range(4)
    ]
    db_session.add_all(messages)
    db_session.flush()
    conversation.frozen_last_message_id = messages[-1].id
    db_session.add(models.Message(
        conversation_id=conversation.id,
        role="diary",
        text="冻结边界之后的消息",
    ))
    job = models.AnalysisJob(
        conversation_id=conversation.id,
        frozen_last_message_id=messages[-1].id,
        status=job_status,
        attempt_count=1,
        max_attempts=3,
        available_at=ended_at,
        created_at=ended_at,
        updated_at=ended_at,
    )
    db_session.add(job)
    assessment = None
    if with_projection:
        db_session.add_all([
            models.FeedingLog(
                conversation_id=conversation.id,
                child_id=child.id,
                category="喂食",
                content="喂了青菜",
            ),
            models.EmotionLog(
                conversation_id=conversation.id,
                child_id=child.id,
                emotion="开心",
                intensity=4,
                note="愿意分享",
            ),
            models.InsightNote(
                conversation_id=conversation.id,
                child_id=child.id,
                content="会主动观察小鸭。",
            ),
        ])
        assessment = models.Assessment(
            conversation_id=conversation.id,
            child_id=child.id,
            status=review_status,
            overall=4.0,
        )
        db_session.add(assessment)
        db_session.flush()
        dimensions = db_session.scalars(
            select(models.AssessmentDimension).order_by(models.AssessmentDimension.id)
        ).all()
        db_session.add_all([
            models.AssessmentScore(
                assessment_id=assessment.id,
                dimension_id=dimension.id,
                score=4,
                reason=f"{dimension.name}理由",
            )
            for dimension in dimensions
        ])
    db_session.commit()
    return child, conversation, job, assessment


def test_history_static_route_precedes_dynamic_detail_and_requires_teacher(client, db_session):
    _seed_history(db_session)
    paths = [route.path for route in conversations_router.routes]
    assert paths.index("/api/conversations/history") < paths.index(
        "/api/conversations/{conversation_id}"
    )

    error = _error(client.get("/api/conversations/history?unknown=1"), 401, "TEACHER_AUTH_REQUIRED")
    assert error["field_errors"] == {}


@pytest.mark.parametrize(
    "query",
    [
        "?limit=0",
        "?limit=51",
        "?limit=text",
        "?child_id=0",
        "?before_id=-1",
        "?queue=pending",
        "?limit=1&limit=2",
        "?child_id=1&child_id=2",
        "?before_id=1&before_id=2",
    ],
)
def test_history_rejects_unknown_duplicate_or_out_of_bounds_query(client, query):
    _unlock(client)
    _error(client.get(f"/api/conversations/history{query}"), 422, "VALIDATION_ERROR")


def test_history_projects_all_states_inactive_children_and_strict_shape(client, db_session):
    pending_child, pending, *_ = _seed_history(
        db_session, review_status="pending", child_active=False, minutes=4
    )
    _seed_history(db_session, review_status="draft", minutes=3)
    _seed_history(db_session, review_status="confirmed", minutes=2)
    _seed_history(db_session, job_status="processing", minutes=1)
    newest_child, newest, *_ = _seed_history(db_session, job_status="failed", minutes=0)
    _unlock(client)

    response = client.get("/api/conversations/history")

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body["items"]] == sorted(
        [item["id"] for item in body["items"]], reverse=True
    )
    assert {item["analysis_status"] for item in body["items"]} == {
        "succeeded", "processing", "failed"
    }
    assert {item["review_status"] for item in body["items"]} == {
        "pending", "draft", "confirmed", "unavailable"
    }
    by_id = {item["id"]: item for item in body["items"]}
    assert by_id[pending.id]["child"]["id"] == pending_child.id
    assert by_id[newest.id] == {
        "id": newest.id,
        "child": {
            "id": newest_child.id,
            "name": newest_child.name,
            "nickname": "小史",
            "avatar": "history.png",
        },
        "date": "2026-08-23",
        "completed_at": "2026-08-23T09:00:00Z",
        "status": "ended",
        "end_reason": "max_rounds",
        "message_count": 4,
        "round": 2,
        "analysis_status": "failed",
        "review_status": "unavailable",
        "revision": 0,
    }
    assert body["next_before_id"] is None
    schemas.ConversationHistoryPage.model_validate(body)


def test_history_child_filter_and_declared_keyset_cursor(client, db_session):
    first_child, first, *_ = _seed_history(db_session, minutes=2)
    _seed_history(db_session, minutes=1)
    _seed_history(db_session, minutes=0)
    _unlock(client)

    first_page = client.get("/api/conversations/history?limit=2").json()
    assert len(first_page["items"]) == 2
    assert first_page["next_before_id"] == first_page["items"][-1]["id"]
    second_page = client.get(
        f"/api/conversations/history?limit=2&before_id={first_page['next_before_id']}"
    ).json()
    assert [item["id"] for item in second_page["items"]] == [first.id]
    assert second_page["next_before_id"] is None

    filtered = client.get(
        f"/api/conversations/history?child_id={first_child.id}"
    ).json()
    assert [item["id"] for item in filtered["items"]] == [first.id]


def test_history_accepts_reader_valid_partial_score_draft(client, db_session):
    _child, conversation, _job, assessment = _seed_history(
        db_session, review_status="draft"
    )
    scores = db_session.scalars(select(models.AssessmentScore).where(
        models.AssessmentScore.assessment_id == assessment.id
    ).order_by(models.AssessmentScore.id)).all()
    assert len(scores) > 1
    db_session.delete(scores[-1])
    db_session.commit()
    _unlock(client)

    response = client.get("/api/conversations/history")

    assert response.status_code == 200
    assert response.json()["items"][0]["id"] == conversation.id
    detail = client.get(f"/api/conversations/{conversation.id}")
    assert detail.status_code == 200
    assert detail.json()["review_status"] == "draft"
    assert len(detail.json()["review"]["scores"]) == len(scores) - 1


def test_history_never_lists_active_or_incomplete_conversation(client, db_session):
    child = models.Child(name="仍在对话")
    db_session.add(child)
    db_session.flush()
    db_session.add(models.Conversation(child_id=child.id, date="2026-08-23", status="active"))
    db_session.commit()
    _unlock(client)
    assert client.get("/api/conversations/history").json() == {
        "items": [], "next_before_id": None
    }


@pytest.mark.parametrize(
    "corrupt",
    [
        "job_boundary",
        "job_status",
        "job_attempt_count",
        "job_max_attempts",
        "end_reason",
        "message_role",
        "assessment_missing",
        "assessment_status",
        "assessment_child",
        "assessment_overall",
        "feeding_category",
        "emotion_missing",
        "emotion_intensity",
        "insight_blank",
        "score_value",
        "dimension_blank",
    ],
)
def test_history_fails_whole_page_for_unreadable_selected_item(
    client, db_session, corrupt
):
    _seed_history(db_session, minutes=1)
    _child, conversation, job, assessment = _seed_history(db_session, minutes=0)
    assert assessment is not None
    if corrupt == "job_boundary":
        job.frozen_last_message_id -= 1
    elif corrupt == "job_status":
        job.status = "mystery"
    elif corrupt == "job_attempt_count":
        job.attempt_count = -1
    elif corrupt == "job_max_attempts":
        job.max_attempts = 0
    elif corrupt == "end_reason":
        conversation.end_reason = "mystery"
    elif corrupt == "message_role":
        db_session.scalar(select(models.Message).where(
            models.Message.conversation_id == conversation.id
        ).order_by(models.Message.id)).role = "mystery"
    elif corrupt == "assessment_missing":
        db_session.delete(assessment)
    elif corrupt == "assessment_status":
        assessment.status = "mystery"
    elif corrupt == "assessment_child":
        assessment.child_id += 999
    elif corrupt == "assessment_overall":
        assessment.overall = nan
    elif corrupt == "feeding_category":
        db_session.scalar(select(models.FeedingLog).where(
            models.FeedingLog.conversation_id == conversation.id
        )).category = "mystery"
    elif corrupt == "emotion_missing":
        db_session.delete(db_session.scalar(select(models.EmotionLog).where(
            models.EmotionLog.conversation_id == conversation.id
        )))
    elif corrupt == "emotion_intensity":
        db_session.scalar(select(models.EmotionLog).where(
            models.EmotionLog.conversation_id == conversation.id
        )).intensity = 99
    elif corrupt == "insight_blank":
        db_session.scalar(select(models.InsightNote).where(
            models.InsightNote.conversation_id == conversation.id
        )).content = "  "
    elif corrupt == "score_value":
        db_session.scalar(select(models.AssessmentScore).where(
            models.AssessmentScore.assessment_id == assessment.id
        )).score = 9
    elif corrupt == "dimension_blank":
        score = db_session.scalar(select(models.AssessmentScore).where(
            models.AssessmentScore.assessment_id == assessment.id
        ))
        db_session.get(models.AssessmentDimension, score.dimension_id).name = "  "
    db_session.commit()
    _unlock(client)

    response = client.get("/api/conversations/history")

    _error(response, 500, "INTERNAL_ERROR")
    assert "items" not in response.text


def test_history_statement_budget_is_constant_for_one_or_twenty_rows(db_session):
    for index in range(20):
        _seed_history(db_session, job_status="failed", minutes=index)
    engine = db_session.get_bind()

    def count_for(limit: int) -> int:
        statements = []
        def record(_conn, _cursor, statement, _parameters, _context, _executemany):
            if not statement.lstrip().upper().startswith(("BEGIN", "ROLLBACK")):
                statements.append(statement)
        event.listen(engine, "before_cursor_execute", record)
        try:
            list_conversation_history(db_session, limit=limit, child_id=None, before_id=None)
        finally:
            event.remove(engine, "before_cursor_execute", record)
        return len(statements)

    one = count_for(1)
    twenty = count_for(20)
    assert one == twenty
    assert one <= 8


def test_history_response_models_reject_extra_and_invalid_nested_data():
    with pytest.raises(Exception):
        schemas.ConversationHistoryPage.model_validate({
            "items": [], "next_before_id": None, "extra": True
        })
    with pytest.raises(Exception):
        schemas.ConversationHistoryItem.model_validate({
            "id": 1,
            "child": {"id": 1, "name": "幼儿", "nickname": None, "avatar": None},
            "date": "2026-08-23",
            "completed_at": NOW,
            "status": "active",
            "end_reason": "complete",
            "message_count": 1,
            "round": 1,
            "analysis_status": "failed",
            "review_status": "unavailable",
            "revision": 0,
        })
