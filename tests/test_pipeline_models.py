"""Durable reliability schema and request/response DTO contract tests."""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from app.backend import models, schemas


def _child(db_session: object) -> models.Child:
    child = models.Child(name="小雨", nickname="雨雨")
    db_session.add(child)
    db_session.commit()
    return child


def _conversation(
    db_session: object,
    child_id: int,
    *,
    status: str = "ended",
) -> models.Conversation:
    conversation = models.Conversation(
        child_id=child_id,
        date="2026-08-23",
        status=status,
    )
    db_session.add(conversation)
    db_session.commit()
    return conversation


def _message(db_session: object, conversation_id: int) -> models.Message:
    message = models.Message(
        conversation_id=conversation_id,
        role="child",
        text="我给小黄添了菜叶",
    )
    db_session.add(message)
    db_session.commit()
    return message


def test_chat_request_id_is_the_primary_key_and_session_recovers_after_conflict(db_session):
    child = _child(db_session)
    request_id = str(uuid4())
    db_session.add(
        models.ChatRequestRecord(
            request_id=request_id,
            child_id=child.id,
            payload_hash="a" * 64,
        )
    )
    db_session.commit()

    db_session.add(
        models.ChatRequestRecord(
            request_id=request_id,
            child_id=child.id,
            payload_hash="b" * 64,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()

    assert db_session.scalar(select(models.ChatRequestRecord.request_id)) == request_id


def test_roster_request_id_is_the_primary_key_and_session_recovers_after_conflict(
    db_session,
):
    request_id = str(uuid4())
    db_session.add(
        models.RosterRequest(
            request_id=request_id,
            operation="daily",
            payload_hash="a" * 64,
        )
    )
    db_session.commit()

    db_session.add(
        models.RosterRequest(
            request_id=request_id,
            operation="daily",
            payload_hash="b" * 64,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()

    assert db_session.scalar(select(models.RosterRequest.request_id)) == request_id


def test_only_one_active_conversation_is_allowed_per_child(db_session):
    child = _child(db_session)
    _conversation(db_session, child.id, status="active")

    db_session.add(
        models.Conversation(child_id=child.id, date="2026-08-24", status="active")
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()

    assert db_session.scalar(select(models.Conversation.id)) is not None


def test_one_analysis_job_is_allowed_per_conversation(db_session):
    child = _child(db_session)
    conversation = _conversation(db_session, child.id)
    message = _message(db_session, conversation.id)
    db_session.add(
        models.AnalysisJob(
            conversation_id=conversation.id,
            frozen_last_message_id=message.id,
        )
    )
    db_session.commit()

    db_session.add(
        models.AnalysisJob(
            conversation_id=conversation.id,
            frozen_last_message_id=message.id,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()

    assert db_session.scalar(select(models.AnalysisJob.conversation_id)) == conversation.id


def test_roster_child_can_only_appear_once_per_date(db_session):
    child = _child(db_session)
    db_session.add(
        models.DutyRoster(cycle="2026-W34", date="2026-08-24", child_id=child.id)
    )
    db_session.commit()

    db_session.add(
        models.DutyRoster(cycle="2026-W34", date="2026-08-24", child_id=child.id)
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()

    assert db_session.scalar(select(models.DutyRoster.id)) is not None


@pytest.mark.parametrize(
    ("model_class", "values"),
    [
        (
            models.EmotionLog,
            {"emotion": "开心", "intensity": 4, "note": "愿意继续分享"},
        ),
        (models.InsightNote, {"content": "会主动观察小鸭的食量。"}),
        (models.Assessment, {"status": "pending", "overall": 4.0}),
    ],
)
def test_each_projection_has_only_one_row_per_conversation(
    db_session,
    model_class,
    values,
):
    child = _child(db_session)
    conversation = _conversation(db_session, child.id)
    db_session.add(
        model_class(conversation_id=conversation.id, child_id=child.id, **values)
    )
    db_session.commit()

    db_session.add(
        model_class(conversation_id=conversation.id, child_id=child.id, **values)
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()

    assert db_session.scalar(select(model_class.id)) is not None


def test_assessment_can_only_score_each_dimension_once(db_session):
    child = _child(db_session)
    conversation = _conversation(db_session, child.id)
    dimension = models.AssessmentDimension(
        key=f"test-dimension-{uuid4()}",
        name="语言表达能力",
    )
    assessment = models.Assessment(
        conversation_id=conversation.id,
        child_id=child.id,
        status="pending",
    )
    db_session.add_all([dimension, assessment])
    db_session.commit()
    db_session.add(
        models.AssessmentScore(
            assessment_id=assessment.id,
            dimension_id=dimension.id,
            score=4,
            reason="能按顺序说明喂食过程。",
        )
    )
    db_session.commit()

    db_session.add(
        models.AssessmentScore(
            assessment_id=assessment.id,
            dimension_id=dimension.id,
            score=5,
            reason="重复维度。",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()

    assert db_session.scalar(select(models.AssessmentScore.id)) is not None


def test_chat_claim_boundary_defaults_to_null_and_ledger_defaults_are_durable(db_session):
    child = _child(db_session)
    request = models.ChatRequestRecord(
        request_id=str(uuid4()),
        child_id=child.id,
        payload_hash="a" * 64,
    )
    db_session.add(request)
    db_session.commit()
    db_session.refresh(request)

    assert request.base_last_message_id is None
    assert request.conversation_id is None
    assert request.child_message_id is None
    assert request.diary_message_id is None
    assert request.response_json is None
    assert request.status == "processing"
    assert request.attempt_count == 0
    assert request.available_at <= datetime.utcnow()


def test_chat_request_trims_text_and_forbids_unknown_fields():
    request_id = uuid4()
    payload = schemas.ChatRequest.model_validate(
        {
            "request_id": str(request_id),
            "child_id": 7,
            "text": "  我给小黄添了菜叶  ",
            "conversation_id": 42,
        }
    )

    assert payload.request_id == request_id
    assert payload.text == "我给小黄添了菜叶"
    assert payload.max_rounds == 3
    with pytest.raises(ValidationError):
        schemas.ChatRequest.model_validate(
            {
                "request_id": str(uuid4()),
                "child_id": 7,
                "text": "   ",
                "unexpected": True,
            }
        )


def test_roster_requests_require_two_distinct_children_and_trim_cycle():
    payload = schemas.DailyRosterRequest.model_validate(
        {
            "request_id": str(uuid4()),
            "cycle": " 2026-W34 ",
            "child_ids": [7, 8],
        }
    )

    assert payload.cycle == "2026-W34"
    with pytest.raises(ValidationError):
        schemas.DailyRosterRequest.model_validate(
            {
                "request_id": str(uuid4()),
                "cycle": "2026-W34",
                "child_ids": [7, 7],
            }
        )


def test_review_request_normalizes_editable_text_but_leaves_blank_draft_reason_for_service():
    payload = schemas.ReviewRequest.model_validate(
        {
            "revision": 2,
            "feeding_logs": [
                {
                    "id": None,
                    "category": "观察",
                    "content": " 小黄今天食欲很好 ",
                    "duck_id": 2,
                }
            ],
            "emotion": {"emotion": " 开心 ", "intensity": 4, "note": " 愿意继续分享 "},
            "insight": " 会主动观察小鸭的食量。 ",
            "scores": [{"dimension_id": 1, "score": 4, "reason": "   "}],
            "action": "save_draft",
        }
    )

    assert payload.feeding_logs[0].content == "小黄今天食欲很好"
    assert payload.emotion.emotion == "开心"
    assert payload.insight == "会主动观察小鸭的食量。"
    assert payload.scores[0].reason == ""
    assert payload.action == "save_draft"


@pytest.mark.parametrize("action", ["save_draft", "confirm"])
def test_review_request_rejects_duplicate_score_dimensions_for_every_action(action):
    with pytest.raises(ValidationError):
        schemas.ReviewRequest.model_validate(
            {
                "revision": 2,
                "feeding_logs": [],
                "emotion": {"emotion": "开心", "intensity": 4, "note": None},
                "insight": "会主动观察小鸭的食量。",
                "scores": [
                    {"dimension_id": 1, "score": 4, "reason": "表达清晰。"},
                    {"dimension_id": 1, "score": 5, "reason": "主动分享。"},
                ],
                "action": action,
            }
        )


def test_pipeline_response_dtos_forbid_top_level_and_nested_extra_fields():
    with pytest.raises(ValidationError):
        schemas.ChatResponse.model_validate(
            {
                "request_id": str(uuid4()),
                "conversation_id": 42,
                "child_message_id": 105,
                "diary_message_id": 106,
                "reply": "小黄一定很开心。",
                "round": 3,
                "ended": True,
                "end_reason": "max_rounds",
                "replayed": False,
                "unexpected": True,
            }
        )

    with pytest.raises(ValidationError):
        schemas.ActiveConversationResponse.model_validate(
            {
                "conversation": {
                    "id": 42,
                    "child_id": 7,
                    "status": "active",
                    "revision": 0,
                    "round": 1,
                    "last_message_id": 101,
                    "messages": [
                        {
                            "id": 101,
                            "role": "child",
                            "text": "我喂了小黄",
                            "unexpected": True,
                        }
                    ],
                }
            }
        )


def test_required_reliability_schema_names_are_visible_on_the_test_engine(db_session):
    inspector = inspect(db_session.get_bind())
    active_index = next(
        index
        for index in inspector.get_indexes("conversations")
        if index["name"] == "uq_conversations_child_active"
    )

    assert active_index["unique"] == 1
    assert str(active_index["dialect_options"]["sqlite_where"]) == "status = 'active'"

    expected_constraints = {
        "duty_rosters": "uq_roster_date_child",
        "analysis_jobs": "uq_analysis_job_conversation",
        "emotion_logs": "uq_emotion_conversation",
        "insight_notes": "uq_insight_conversation",
        "assessments": "uq_assessment_conversation",
        "assessment_scores": "uq_assessment_dimension",
    }
    for table, name in expected_constraints.items():
        names = {constraint["name"] for constraint in inspector.get_unique_constraints(table)}
        assert name in names


def test_failed_analysis_error_is_limited_to_the_sanitized_frozen_error():
    error = schemas.AnalysisError.model_validate(
        {"code": "ANALYSIS_UPSTREAM_FAILED", "message": "分析服务暂时不可用"}
    )

    assert error.code == "ANALYSIS_UPSTREAM_FAILED"
    assert error.message == "分析服务暂时不可用"
    with pytest.raises(ValidationError):
        schemas.AnalysisError.model_validate(
            {"code": "INTERNAL_TRACEBACK", "message": "secret endpoint"}
        )
