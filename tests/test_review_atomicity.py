"""Teacher review queue, detail, and whole-document save contracts."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
from threading import Barrier, Event, Thread

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backend import models, schemas
from app.backend.api_errors import APIError
from app.backend.database import SessionLocal
from app.backend.services import reviews


NOW = datetime(2026, 8, 23, 9, 0, tzinfo=timezone.utc)


def _unlock(client) -> None:
    response = client.post("/api/auth/setup", json={"pin": "1234"})
    assert response.status_code == 200


def _error(response, *, status: int, code: str) -> dict:
    assert response.status_code == status
    body = response.json()
    assert body["error"]["code"] == code
    return body["error"]


def _seed_reviewable_conversation(
    db_session,
    *,
    job_status: str = "succeeded",
    review_status: str = "pending",
    ended_at: datetime = NOW,
    child_active: bool = True,
    with_projection: bool | None = None,
    frozen_message_count: int = 4,
) -> tuple[models.Conversation, models.AnalysisJob, models.Assessment | None]:
    """Seed one ended conversation and its one durable job using only test SQLite."""
    if with_projection is None:
        with_projection = job_status == "succeeded"
    child = models.Child(
        name=f"小雨-{ended_at.minute}-{job_status}",
        nickname="雨雨",
        avatar="rain.png",
        active=child_active,
    )
    db_session.add(child)
    db_session.flush()
    conversation = models.Conversation(
        child_id=child.id,
        date="2026-08-23",
        status="ended",
        end_reason="max_rounds",
        started_at=ended_at - timedelta(minutes=5),
        ended_at=ended_at,
        revision=2,
    )
    db_session.add(conversation)
    db_session.flush()
    messages = [
        models.Message(
            conversation_id=conversation.id,
            role="child" if index % 2 == 0 else "diary",
            text=f"冻结消息 {index + 1}",
        )
        for index in range(frozen_message_count)
    ]
    db_session.add_all(messages)
    db_session.flush()
    conversation.frozen_last_message_id = messages[-1].id
    # This must not be included in frozen queue/detail counts.
    db_session.add(models.Message(
        conversation_id=conversation.id,
        role="diary",
        text="冻结之后不应显示",
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
        last_error_code="provider-secret-code" if job_status == "failed" else None,
        last_error_message="provider secret https://example.invalid/key" if job_status == "failed" else None,
    )
    db_session.add(job)
    assessment: models.Assessment | None = None
    if with_projection:
        db_session.add_all([
            models.FeedingLog(
                conversation_id=conversation.id,
                child_id=child.id,
                category="喂食",
                content="第一条喂食记录",
            ),
            models.FeedingLog(
                conversation_id=conversation.id,
                child_id=child.id,
                category="观察",
                content="第二条观察记录",
            ),
            models.EmotionLog(
                conversation_id=conversation.id,
                child_id=child.id,
                emotion="开心",
                intensity=4,
                note="愿意继续分享",
            ),
            models.InsightNote(
                conversation_id=conversation.id,
                child_id=child.id,
                content="会主动观察小鸭的食量。",
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
                score=3 + (index % 2),
                reason=f"{dimension.name}的原始理由",
            )
            for index, dimension in enumerate(dimensions)
        ])
    db_session.commit()
    return conversation, job, assessment


def _review_payload(conversation: models.Conversation, *, action: str = "save_draft") -> dict:
    return {
        "revision": conversation.revision,
        "feeding_logs": [],
        "emotion": {"emotion": "期待", "intensity": 5, "note": "继续记录"},
        "insight": "老师确认了新的观察。",
        "scores": [],
        "action": action,
    }


def _snapshot_review(db_session, conversation_id: int) -> dict:
    conversation = db_session.get(models.Conversation, conversation_id)
    assessment = db_session.scalar(select(models.Assessment).where(
        models.Assessment.conversation_id == conversation_id
    ))
    assert conversation is not None
    assert assessment is not None
    return {
        "revision": conversation.revision,
        "feeding": [
            (row.id, row.category, row.content, row.duck_id)
            for row in db_session.scalars(select(models.FeedingLog).where(
                models.FeedingLog.conversation_id == conversation_id
            ).order_by(models.FeedingLog.id))
        ],
        "emotion": [
            (row.id, row.emotion, row.intensity, row.note)
            for row in db_session.scalars(select(models.EmotionLog).where(
                models.EmotionLog.conversation_id == conversation_id
            ).order_by(models.EmotionLog.id))
        ],
        "insight": [
            (row.id, row.content)
            for row in db_session.scalars(select(models.InsightNote).where(
                models.InsightNote.conversation_id == conversation_id
            ).order_by(models.InsightNote.id))
        ],
        "assessment": (assessment.id, assessment.status, assessment.overall),
        "scores": [
            (row.id, row.dimension_id, row.score, row.reason)
            for row in db_session.scalars(select(models.AssessmentScore).where(
                models.AssessmentScore.assessment_id == assessment.id
            ).order_by(models.AssessmentScore.dimension_id))
        ],
    }


def test_teacher_review_routes_require_a_session_before_queue_detail_or_write(client, db_session):
    """Catches a teacher route that exposes review data or writes while locked."""
    conversation, _job, _assessment = _seed_reviewable_conversation(db_session)
    payload = _review_payload(conversation)

    for request in [
        lambda: client.get("/api/conversations", params={"queue": "pending"}),
        lambda: client.get(f"/api/conversations/{conversation.id}"),
        lambda: client.put(f"/api/conversations/{conversation.id}/review", json=payload),
        lambda: client.post(f"/api/conversations/{conversation.id}/analysis/retry"),
    ]:
        _error(request(), status=401, code="TEACHER_AUTH_REQUIRED")


def test_teacher_queue_uses_job_matrix_frozen_counts_sort_and_historical_child(client, db_session):
    """Catches queue state filtering, live-message leakage, or inactive history removal."""
    oldest, _old_job, _old_assessment = _seed_reviewable_conversation(
        db_session,
        ended_at=NOW - timedelta(minutes=3),
    )
    newest, _new_job, _new_assessment = _seed_reviewable_conversation(
        db_session,
        review_status="draft",
        ended_at=NOW - timedelta(minutes=1),
        child_active=False,
    )
    confirmed, _confirmed_job, _confirmed_assessment = _seed_reviewable_conversation(
        db_session,
        review_status="confirmed",
        ended_at=NOW,
    )
    processing, _processing_job, _ = _seed_reviewable_conversation(
        db_session,
        job_status="processing",
        with_projection=False,
        ended_at=NOW - timedelta(minutes=2),
    )
    analysis_pending, _pending_job, _ = _seed_reviewable_conversation(
        db_session,
        job_status="pending",
        with_projection=False,
        ended_at=NOW - timedelta(minutes=2, seconds=30),
    )
    failed, _failed_job, _ = _seed_reviewable_conversation(
        db_session,
        job_status="failed",
        with_projection=False,
        ended_at=NOW - timedelta(minutes=4),
    )
    _unlock(client)

    pending = client.get("/api/conversations", params={"queue": "pending"})
    assert pending.status_code == 200
    assert [item["id"] for item in pending.json()] == [newest.id, oldest.id]
    assert confirmed.id not in [item["id"] for item in pending.json()]
    assert pending.json()[0] == {
        "id": newest.id,
        "child": {
            "id": newest.child_id,
            "name": f"小雨-{(NOW - timedelta(minutes=1)).minute}-succeeded",
            "nickname": "雨雨",
            "avatar": "rain.png",
        },
        "date": "2026-08-23",
        "started_at": "2026-08-23T08:54:00Z",
        "completed_at": "2026-08-23T08:59:00Z",
        "message_count": 4,
        "round": 2,
        "status": "ended",
        "end_reason": "max_rounds",
        "analysis_status": "succeeded",
        "review_status": "draft",
        "revision": 2,
    }
    processing_response = client.get("/api/conversations", params={"queue": "processing"})
    assert processing_response.status_code == 200
    assert [item["id"] for item in processing_response.json()] == [processing.id, analysis_pending.id]
    failed_response = client.get("/api/conversations", params={"queue": "failed"})
    assert failed_response.status_code == 200
    assert [item["id"] for item in failed_response.json()] == [failed.id]


@pytest.mark.parametrize("job_status", ["pending", "processing", "failed"])
def test_non_succeeded_detail_is_unavailable_and_failure_is_sanitized(client, db_session, job_status):
    """Catches partial review data or provider details leaking before analysis succeeds."""
    conversation, _job, _assessment = _seed_reviewable_conversation(
        db_session,
        job_status=job_status,
        with_projection=False,
    )
    _unlock(client)

    response = client.get(f"/api/conversations/{conversation.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["review_status"] == "unavailable"
    assert body["review"] is None
    assert body["analysis"]["status"] == job_status
    if job_status == "failed":
        assert body["analysis"]["error"] == {
            "code": "ANALYSIS_UPSTREAM_FAILED",
            "message": "分析服务暂时不可用",
        }
        assert "provider secret" not in response.text
        assert "example.invalid" not in response.text
    else:
        assert body["analysis"]["error"] is None


def test_succeeded_detail_has_one_complete_ordered_document_or_a_stable_corruption_error(
    client,
    db_session,
):
    """Catches a succeeded detail that drops required projections or leaks a partial DTO."""
    complete, _complete_job, _complete_assessment = _seed_reviewable_conversation(
        db_session,
        child_active=False,
    )
    corrupt, _corrupt_job, _corrupt_assessment = _seed_reviewable_conversation(db_session)
    db_session.execute(
        models.InsightNote.__table__.delete().where(
            models.InsightNote.conversation_id == corrupt.id
        )
    )
    db_session.commit()
    _unlock(client)

    detail = client.get(f"/api/conversations/{complete.id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["child"]["id"] == complete.child_id
    assert body["child"]["name"].startswith("小雨-")
    assert body["started_at"] == "2026-08-23T08:55:00Z"
    assert body["completed_at"] == "2026-08-23T09:00:00Z"
    assert body["message_count"] == 4
    assert body["round"] == 2
    assert body["last_message_id"] == body["messages"][-1]["id"]
    assert [message["text"] for message in body["messages"]] == [
        "冻结消息 1", "冻结消息 2", "冻结消息 3", "冻结消息 4",
    ]
    assert [score["dimension_id"] for score in body["review"]["scores"]] == sorted(
        score["dimension_id"] for score in body["review"]["scores"]
    )
    assert body["review"]["overall"] == 4.0

    _error(
        client.get(f"/api/conversations/{corrupt.id}"),
        status=500,
        code="INTERNAL_ERROR",
    )
    _error(
        client.get("/api/conversations/99999"),
        status=404,
        code="CONVERSATION_NOT_FOUND",
    )


def test_detail_and_save_require_the_job_to_match_the_frozen_transcript(client, db_session):
    """Catches a review writer accepting a stale job from a different frozen boundary."""
    conversation, job, _assessment = _seed_reviewable_conversation(db_session)
    job.frozen_last_message_id += 1000
    db_session.commit()
    before = _snapshot_review(db_session, conversation.id)
    _unlock(client)

    _error(
        client.get(f"/api/conversations/{conversation.id}"),
        status=404,
        code="CONVERSATION_NOT_FOUND",
    )
    _error(
        client.put(
            f"/api/conversations/{conversation.id}/review",
            json=_review_payload(conversation),
        ),
        status=404,
        code="CONVERSATION_NOT_FOUND",
    )
    with SessionLocal() as fresh:
        assert _snapshot_review(fresh, conversation.id) == before


def test_draft_review_replaces_the_full_document_and_refetches_identically(client, db_session):
    """Catches partial save behavior that leaves omitted projection rows or stale revision data."""
    conversation, _job, assessment = _seed_reviewable_conversation(db_session)
    assert assessment is not None
    existing_logs = db_session.scalars(
        select(models.FeedingLog)
        .where(models.FeedingLog.conversation_id == conversation.id)
        .order_by(models.FeedingLog.id)
    ).all()
    retained_log_id, omitted_log_id = (row.id for row in existing_logs)
    dimensions = db_session.scalars(
        select(models.AssessmentDimension).order_by(models.AssessmentDimension.id)
    ).all()
    duck = models.Duck(name="小黄", active=True)
    db_session.add(duck)
    db_session.commit()
    payload = _review_payload(conversation)
    payload.update({
        "feeding_logs": [
            {
                "id": retained_log_id,
                "category": "清洁",
                "content": "保留并改写的清洁记录",
                "duck_id": None,
            },
            {
                "id": None,
                "category": "观察",
                "content": "新建的观察记录",
                "duck_id": duck.id,
            },
        ],
        "emotion": {"emotion": "平静", "intensity": 2, "note": "重新整理"},
        "insight": "重新梳理了观察重点。",
        "scores": [
            {
                "dimension_id": dimensions[1].id,
                "score": 5,
                "reason": "草稿允许只保留一个维度。",
            }
        ],
    })
    _unlock(client)

    response = client.put(f"/api/conversations/{conversation.id}/review", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["saved"] is True
    assert body["review_status"] == "draft"
    assert body["revision"] == 3
    assert body["saved_at"].endswith("Z")
    logs = body["review"]["feeding_logs"]
    assert [log["id"] for log in logs] == [retained_log_id, logs[1]["id"]]
    assert logs[1]["id"] != omitted_log_id
    assert [log["content"] for log in logs] == ["保留并改写的清洁记录", "新建的观察记录"]
    assert body["review"]["scores"] == [{
        "dimension_id": dimensions[1].id,
        "dimension_name": dimensions[1].name,
        "score": 5,
        "reason": "草稿允许只保留一个维度。",
    }]
    refetched = client.get(f"/api/conversations/{conversation.id}")
    assert refetched.status_code == 200
    assert refetched.json()["revision"] == body["revision"]
    assert refetched.json()["review_status"] == "draft"
    assert refetched.json()["review"] == body["review"]


def test_confirm_requires_complete_reasoned_scores_then_leaves_every_queue(client, db_session):
    """Catches a confirm action that accepts an incomplete document or remains queued."""
    conversation, _job, _assessment = _seed_reviewable_conversation(db_session)
    dimensions = db_session.scalars(
        select(models.AssessmentDimension).order_by(models.AssessmentDimension.id)
    ).all()
    incomplete = _review_payload(conversation, action="confirm")
    incomplete["scores"] = [{
        "dimension_id": dimensions[0].id,
        "score": 4,
        "reason": "",
    }]
    _unlock(client)

    error = _error(
        client.put(f"/api/conversations/{conversation.id}/review", json=incomplete),
        status=422,
        code="REVIEW_VALIDATION_FAILED",
    )
    assert set(error["field_errors"]) == {"scores.0.reason", "scores"}
    complete = _review_payload(conversation, action="confirm")
    complete["scores"] = [
        {"dimension_id": dimension.id, "score": index + 3, "reason": f"{dimension.name}理由"}
        for index, dimension in enumerate(dimensions)
    ]
    complete["scores"][-1]["score"] = 5

    confirmed = client.put(f"/api/conversations/{conversation.id}/review", json=complete)

    assert confirmed.status_code == 200
    assert confirmed.json()["review_status"] == "confirmed"
    assert confirmed.json()["review"]["overall"] == 4.0
    for queue in ("pending", "processing", "failed"):
        queued = client.get("/api/conversations", params={"queue": queue})
        assert queued.status_code == 200
        assert conversation.id not in [item["id"] for item in queued.json()]


@pytest.mark.parametrize(
    ("case", "expected_key"),
    [
        ("foreign_feeding", "feeding_logs.0.id"),
        ("duplicate_feeding", "feeding_logs.1.id"),
        ("missing_duck", "feeding_logs.0.duck_id"),
        ("inactive_duck", "feeding_logs.0.duck_id"),
        ("reassigned_inactive_duck", "feeding_logs.0.duck_id"),
        ("missing_dimension", "scores.0.dimension_id"),
        ("disabled_dimension", "scores.0.dimension_id"),
    ],
)
def test_semantic_review_validation_returns_one_service_error_and_rolls_back_every_projection(
    client,
    db_session,
    case,
    expected_key,
):
    """Catches semantic validation that changes any retained review projection before rejection."""
    conversation, _job, _assessment = _seed_reviewable_conversation(db_session)
    logs = db_session.scalars(select(models.FeedingLog).where(
        models.FeedingLog.conversation_id == conversation.id
    ).order_by(models.FeedingLog.id)).all()
    dimensions = db_session.scalars(
        select(models.AssessmentDimension).order_by(models.AssessmentDimension.id)
    ).all()
    active_duck = models.Duck(name="活跃小鸭", active=True)
    inactive_duck = models.Duck(name="停用小鸭", active=False)
    db_session.add_all([active_duck, inactive_duck])
    db_session.flush()
    logs[0].duck_id = active_duck.id
    if case == "disabled_dimension":
        dimensions[0].enabled = False
    db_session.commit()
    before = _snapshot_review(db_session, conversation.id)
    payload = _review_payload(conversation)
    retained = {
        "id": logs[0].id,
        "category": "喂食",
        "content": "新的内容不得落库",
        "duck_id": active_duck.id,
    }
    if case == "foreign_feeding":
        retained["id"] = 99999
        payload["feeding_logs"] = [retained]
    elif case == "duplicate_feeding":
        payload["feeding_logs"] = [retained, {**retained, "content": "重复 ID"}]
    elif case == "missing_duck":
        payload["feeding_logs"] = [{**retained, "duck_id": 99999}]
    elif case == "inactive_duck":
        payload["feeding_logs"] = [{
            "id": None,
            "category": "观察",
            "content": "新建记录不能使用停用小鸭",
            "duck_id": inactive_duck.id,
        }]
    elif case == "reassigned_inactive_duck":
        payload["feeding_logs"] = [{**retained, "duck_id": inactive_duck.id}]
    elif case == "missing_dimension":
        payload["scores"] = [{"dimension_id": 99999, "score": 4, "reason": "不存在"}]
    else:
        payload["scores"] = [{"dimension_id": dimensions[0].id, "score": 4, "reason": "已停用"}]
    _unlock(client)

    error = _error(
        client.put(f"/api/conversations/{conversation.id}/review", json=payload),
        status=422,
        code="REVIEW_VALIDATION_FAILED",
    )

    assert expected_key in error["field_errors"]
    with SessionLocal() as fresh:
        assert _snapshot_review(fresh, conversation.id) == before


def test_retained_historical_inactive_duck_is_valid_but_schema_duplicate_scores_stay_foundation_validation(
    client,
    db_session,
):
    """Catches conflating allowed historical retention with semantic duck and schema errors."""
    conversation, _job, _assessment = _seed_reviewable_conversation(db_session)
    log = db_session.scalar(select(models.FeedingLog).where(
        models.FeedingLog.conversation_id == conversation.id
    ))
    dimension = db_session.scalar(select(models.AssessmentDimension))
    assert log is not None and dimension is not None
    inactive_duck = models.Duck(name="历史停用小鸭", active=False)
    db_session.add(inactive_duck)
    db_session.flush()
    log.duck_id = inactive_duck.id
    db_session.commit()
    payload = _review_payload(conversation)
    payload["feeding_logs"] = [{
        "id": log.id,
        "category": log.category,
        "content": log.content,
        "duck_id": inactive_duck.id,
    }]
    _unlock(client)

    retained = client.put(f"/api/conversations/{conversation.id}/review", json=payload)

    assert retained.status_code == 200
    duplicate = _review_payload(db_session.get(models.Conversation, conversation.id))
    duplicate["scores"] = [
        {"dimension_id": dimension.id, "score": 3, "reason": "甲"},
        {"dimension_id": dimension.id, "score": 4, "reason": "乙"},
    ]
    _error(
        client.put(f"/api/conversations/{conversation.id}/review", json=duplicate),
        status=422,
        code="VALIDATION_ERROR",
    )
    assert retained.json()["review"]["overall"] == 0.0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("feeding_logs", [{"id": None, "category": "错误类别", "content": "不会写入", "duck_id": None}]),
        ("feeding_logs", [{"id": None, "category": "观察", "content": "   ", "duck_id": None}]),
        ("scores", [{"dimension_id": 1, "score": 6, "reason": "超出范围"}]),
    ],
)
def test_schema_review_validation_keeps_foundation_error_code_and_never_starts_a_write(
    client,
    db_session,
    field,
    value,
):
    """Catches route code that reclassifies DTO errors or starts a replacement transaction first."""
    conversation, _job, _assessment = _seed_reviewable_conversation(db_session)
    before = _snapshot_review(db_session, conversation.id)
    payload = _review_payload(conversation)
    payload[field] = value
    _unlock(client)

    _error(
        client.put(f"/api/conversations/{conversation.id}/review", json=payload),
        status=422,
        code="VALIDATION_ERROR",
    )

    with SessionLocal() as fresh:
        assert _snapshot_review(fresh, conversation.id) == before


def test_stale_review_revision_and_forced_flush_or_commit_leave_fresh_snapshot_unchanged(
    client,
    db_session,
    monkeypatch,
):
    """Catches a stale/failed write that advances revision or leaves a mixed replacement document."""
    conversation, _job, _assessment = _seed_reviewable_conversation(db_session)
    before = _snapshot_review(db_session, conversation.id)
    stale = _review_payload(conversation)
    stale["revision"] += 1
    _unlock(client)

    conflict = _error(
        client.put(f"/api/conversations/{conversation.id}/review", json=stale),
        status=409,
        code="REVIEW_REVISION_CONFLICT",
    )
    assert conflict["field_errors"] == {"revision": ["当前版本为 2"]}
    with SessionLocal() as fresh:
        assert _snapshot_review(fresh, conversation.id) == before

    original_flush = Session.flush

    def failing_flush(self, *args, **kwargs):
        raise RuntimeError("forced flush failure")

    monkeypatch.setattr(Session, "flush", failing_flush)
    with SessionLocal() as failing_session, pytest.raises(RuntimeError, match="forced flush failure"):
        reviews.save_review(
            failing_session,
            conversation_id=conversation.id,
            payload=schemas.ReviewRequest.model_validate(_review_payload(conversation)),
            now=NOW,
        )
    monkeypatch.setattr(Session, "flush", original_flush)
    with SessionLocal() as fresh:
        assert _snapshot_review(fresh, conversation.id) == before

    original_commit = Session.commit

    def failing_commit(self, *args, **kwargs):
        raise RuntimeError("forced commit failure")

    monkeypatch.setattr(Session, "commit", failing_commit)
    with SessionLocal() as failing_session, pytest.raises(RuntimeError, match="forced commit failure"):
        reviews.save_review(
            failing_session,
            conversation_id=conversation.id,
            payload=schemas.ReviewRequest.model_validate(_review_payload(conversation)),
            now=NOW,
        )
    monkeypatch.setattr(Session, "commit", original_commit)
    with SessionLocal() as fresh:
        assert _snapshot_review(fresh, conversation.id) == before


def test_two_validated_sessions_have_one_revision_winner_and_one_clean_conflict(db_session, monkeypatch):
    """Catches two same-revision writers merging documents or both reporting success."""
    conversation, _job, _assessment = _seed_reviewable_conversation(db_session)
    barrier = Barrier(2)
    payloads = [
        schemas.ReviewRequest.model_validate({
            **_review_payload(conversation),
            "emotion": {"emotion": "开心", "intensity": 3, "note": "甲"},
            "insight": "甲老师的最终文档。",
        }),
        schemas.ReviewRequest.model_validate({
            **_review_payload(conversation),
            "emotion": {"emotion": "期待", "intensity": 5, "note": "乙"},
            "insight": "乙老师的最终文档。",
        }),
    ]
    winners: list[schemas.ReviewResponse] = []
    errors: list[APIError] = []

    def wait_after_validation() -> None:
        barrier.wait(timeout=5)

    monkeypatch.setattr(reviews, "_after_review_validation_before_cas", wait_after_validation)

    def save_in_own_session(payload: schemas.ReviewRequest) -> None:
        with SessionLocal() as session:
            try:
                winners.append(reviews.save_review(
                    session,
                    conversation_id=conversation.id,
                    payload=payload,
                    now=NOW,
                ))
            except APIError as error:
                errors.append(error)

    threads = [Thread(target=save_in_own_session, args=(payload,)) for payload in payloads]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not any(thread.is_alive() for thread in threads)
    assert len(winners) == 1
    assert len(errors) == 1
    assert errors[0].code == "REVIEW_REVISION_CONFLICT"
    assert errors[0].field_errors == {"revision": ["当前版本为 3"]}
    with SessionLocal() as fresh:
        final = reviews.get_review_detail(fresh, conversation_id=conversation.id)
    assert final.revision == 3
    assert final.review is not None
    assert final.review.insight == winners[0].review.insight
    assert final.review.emotion.note == winners[0].review.emotion.note


def _save_after_validation_pause(
    conversation: models.Conversation,
    payload: schemas.ReviewRequest,
    *,
    monkeypatch,
) -> tuple[Event, Event, Thread, list[object]]:
    """Start one real service save and pause it after its read validation rolls back."""
    validated = Event()
    release = Event()
    outcomes: list[object] = []

    def pause_after_validation() -> None:
        validated.set()
        assert release.wait(timeout=5)

    def save_in_own_session() -> None:
        with SessionLocal() as session:
            try:
                outcomes.append(reviews.save_review(
                    session,
                    conversation_id=conversation.id,
                    payload=payload,
                    now=NOW,
                ))
            except BaseException as error:
                outcomes.append(error)

    monkeypatch.setattr(reviews, "_after_review_validation_before_cas", pause_after_validation)
    writer = Thread(target=save_in_own_session)
    writer.start()
    assert validated.wait(timeout=5)
    return validated, release, writer, outcomes


def test_post_cas_dimension_disable_revalidates_and_rolls_back_the_winning_revision(
    db_session,
    monkeypatch,
):
    """Catches a writer persisting a score after its initially enabled dimension is disabled."""
    conversation, _job, _assessment = _seed_reviewable_conversation(db_session)
    dimension = db_session.scalar(select(models.AssessmentDimension))
    assert dimension is not None
    payload = schemas.ReviewRequest.model_validate({
        **_review_payload(conversation),
        "scores": [{"dimension_id": dimension.id, "score": 4, "reason": "初始有效"}],
    })
    with SessionLocal() as fresh:
        before = _snapshot_review(fresh, conversation.id)
    _validated, release, writer, outcomes = _save_after_validation_pause(
        conversation,
        payload,
        monkeypatch=monkeypatch,
    )
    with SessionLocal() as mutator:
        current = mutator.get(models.AssessmentDimension, dimension.id)
        assert current is not None
        current.enabled = False
        mutator.commit()
    release.set()
    writer.join(timeout=10)

    assert not writer.is_alive()
    assert len(outcomes) == 1
    assert isinstance(outcomes[0], APIError)
    assert outcomes[0].code == "REVIEW_VALIDATION_FAILED"
    assert set(outcomes[0].field_errors) == {"scores.0.dimension_id"}
    with SessionLocal() as fresh:
        assert _snapshot_review(fresh, conversation.id) == before


@pytest.mark.parametrize("change", ["deactivate", "delete"])
def test_post_cas_new_duck_change_revalidates_and_rolls_back_the_winning_revision(
    db_session,
    monkeypatch,
    change,
):
    """Catches a writer retaining a new duck reference after it turns inactive or disappears."""
    conversation, _job, _assessment = _seed_reviewable_conversation(db_session)
    duck = models.Duck(name="CAS 小鸭", active=True)
    db_session.add(duck)
    db_session.commit()
    payload = schemas.ReviewRequest.model_validate({
        **_review_payload(conversation),
        "feeding_logs": [{
            "id": None,
            "category": "观察",
            "content": "初始有效的新流水",
            "duck_id": duck.id,
        }],
    })
    with SessionLocal() as fresh:
        before = _snapshot_review(fresh, conversation.id)
    _validated, release, writer, outcomes = _save_after_validation_pause(
        conversation,
        payload,
        monkeypatch=monkeypatch,
    )
    with SessionLocal() as mutator:
        current = mutator.get(models.Duck, duck.id)
        assert current is not None
        if change == "deactivate":
            current.active = False
        else:
            mutator.delete(current)
        mutator.commit()
    release.set()
    writer.join(timeout=10)

    assert not writer.is_alive()
    assert len(outcomes) == 1
    assert isinstance(outcomes[0], APIError)
    assert outcomes[0].code == "REVIEW_VALIDATION_FAILED"
    assert set(outcomes[0].field_errors) == {"feeding_logs.0.duck_id"}
    with SessionLocal() as fresh:
        assert _snapshot_review(fresh, conversation.id) == before


def test_post_cas_reference_changes_accumulate_indexed_errors_without_a_partial_replacement(
    db_session,
    monkeypatch,
):
    """Catches post-CAS validation stopping at one changed reference and committing the rest."""
    conversation, _job, _assessment = _seed_reviewable_conversation(db_session)
    dimension = db_session.scalar(select(models.AssessmentDimension))
    assert dimension is not None
    duck = models.Duck(name="CAS 累积错误小鸭", active=True)
    db_session.add(duck)
    db_session.commit()
    payload = schemas.ReviewRequest.model_validate({
        **_review_payload(conversation),
        "feeding_logs": [{
            "id": None,
            "category": "观察",
            "content": "两个引用在初始验证时都有效",
            "duck_id": duck.id,
        }],
        "scores": [{"dimension_id": dimension.id, "score": 4, "reason": "初始有效"}],
    })
    with SessionLocal() as fresh:
        before = _snapshot_review(fresh, conversation.id)
    _validated, release, writer, outcomes = _save_after_validation_pause(
        conversation,
        payload,
        monkeypatch=monkeypatch,
    )
    with SessionLocal() as mutator:
        current_dimension = mutator.get(models.AssessmentDimension, dimension.id)
        current_duck = mutator.get(models.Duck, duck.id)
        assert current_dimension is not None and current_duck is not None
        current_dimension.enabled = False
        current_duck.active = False
        mutator.commit()
    release.set()
    writer.join(timeout=10)

    assert not writer.is_alive()
    assert len(outcomes) == 1
    assert isinstance(outcomes[0], APIError)
    assert outcomes[0].code == "REVIEW_VALIDATION_FAILED"
    assert set(outcomes[0].field_errors) == {
        "feeding_logs.0.duck_id",
        "scores.0.dimension_id",
    }
    with SessionLocal() as fresh:
        assert _snapshot_review(fresh, conversation.id) == before


def _normalized_path(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{}", path)


def test_legacy_tombstones_authenticate_before_410_never_write_and_route_inventory_is_unique(
    client,
    db_session,
):
    """Catches a legacy bypass, body validation before its tombstone, or duplicate route registration."""
    from app.backend.main import app

    conversation, _job, assessment = _seed_reviewable_conversation(db_session)
    assert assessment is not None
    before = _snapshot_review(db_session, conversation.id)
    locked_calls = [
        ("patch", f"/api/conversations/{conversation.id}/logs"),
        ("post", f"/api/assessments/{assessment.id}/confirm"),
    ]
    for method, path in locked_calls:
        _error(client.request(
            method.upper(),
            path,
            content=b"{not-json",
            headers={"content-type": "application/json"},
        ), status=401, code="TEACHER_AUTH_REQUIRED")
    _unlock(client)
    for method, path in locked_calls:
        _error(client.request(
            method.upper(),
            path,
            content=b"{not-json",
            headers={"content-type": "application/json"},
        ), status=410, code="LEGACY_ENDPOINT_REMOVED")
    with SessionLocal() as fresh:
        assert _snapshot_review(fresh, conversation.id) == before

    direct_and_included_routes = [
        child
        for route in app.router.routes
        for child in (
            route.original_router.routes if hasattr(route, "original_router") else [route]
        )
    ]
    routes = [
        (method, _normalized_path(route.path), route)
        for route in direct_and_included_routes
        if hasattr(route, "methods")
        for method in route.methods
        if method in {"GET", "POST", "PUT", "PATCH"}
    ]
    expected = {
        ("GET", "/api/conversations"),
        ("GET", "/api/conversations/{}"),
        ("PUT", "/api/conversations/{}/review"),
        ("POST", "/api/conversations/{}/analysis/retry"),
    }
    for method, path in expected:
        matching = [route for current_method, current_path, route in routes if (current_method, current_path) == (method, path)]
        assert len(matching) == 1, (method, path)
        dependencies = [
            getattr(dependency.call, "__name__", None)
            for dependency in matching[0].dependant.dependencies
        ]
        assert "require_teacher_session" in dependencies
    documented = app.openapi()["paths"]
    assert set(documented["/api/conversations"]) == {"get"}
    assert set(documented["/api/conversations/{conversation_id}"]) == {"get"}
    assert set(documented["/api/conversations/{conversation_id}/review"]) == {"put"}
