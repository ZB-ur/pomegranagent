"""Teacher-only advanced conversation search contracts."""
from __future__ import annotations

import base64
import asyncio
from datetime import date, datetime, timedelta, timezone
import json
import logging
import re
import sqlite3

import pytest
from sqlalchemy import event, select

from app.backend import models, schemas
from app.backend.api_errors import APIError
from app.backend.routes.conversations import router as conversations_router
from app.backend.services import history as history_service


UTC = timezone.utc
BASE_TIME = datetime(2026, 8, 23, 9, 0, tzinfo=UTC)


def _unlock(client) -> None:
    response = client.post("/api/auth/setup", json={"pin": "1234"})
    assert response.status_code == 200


def _error(response, status: int, code: str) -> dict:
    assert response.status_code == status, response.text
    body = response.json()
    assert body["error"]["code"] == code
    return body["error"]


def _seed_search(
    db_session,
    *,
    child: models.Child | None = None,
    child_name: str = "搜索幼儿",
    conversation_date: str = "2026-08-23",
    ended_at: datetime = BASE_TIME,
    job_status: str = "succeeded",
    review_status: str = "pending",
    end_reason: str = "complete",
    frozen_text: str = "普通冻结消息",
    post_frozen_text: str = "冻结边界之后的消息",
) -> tuple[models.Child, models.Conversation, models.AnalysisJob, models.Assessment | None]:
    if child is None:
        child = models.Child(name=child_name, nickname=None, avatar=None, active=True)
        db_session.add(child)
        db_session.flush()
    conversation = models.Conversation(
        child_id=child.id,
        date=conversation_date,
        status="ended",
        end_reason=end_reason,
        started_at=ended_at - timedelta(minutes=5),
        ended_at=ended_at,
        revision=0,
    )
    db_session.add(conversation)
    db_session.flush()
    messages = [
        models.Message(
            conversation_id=conversation.id,
            role="child" if index % 2 == 0 else "diary",
            text=frozen_text if index == 1 else f"冻结消息 {index + 1}",
            created_at=ended_at,
        )
        for index in range(4)
    ]
    db_session.add_all(messages)
    db_session.flush()
    conversation.frozen_last_message_id = messages[-1].id
    db_session.add(models.Message(
        conversation_id=conversation.id,
        role="diary",
        text=post_frozen_text,
        created_at=ended_at,
    ))
    job = models.AnalysisJob(
        conversation_id=conversation.id,
        frozen_last_message_id=conversation.frozen_last_message_id,
        status=job_status,
        attempt_count=1,
        max_attempts=3,
        available_at=ended_at,
        created_at=ended_at,
        updated_at=ended_at,
    )
    db_session.add(job)
    assessment = None
    if job_status == "succeeded":
        assessment = models.Assessment(
            conversation_id=conversation.id,
            child_id=child.id,
            status=review_status,
            overall=4.0,
        )
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
                note=None,
            ),
            models.InsightNote(
                conversation_id=conversation.id,
                child_id=child.id,
                content="会主动观察小鸭。",
            ),
            assessment,
        ])
        db_session.flush()
        dimensions = db_session.scalars(
            select(models.AssessmentDimension).order_by(models.AssessmentDimension.id)
        ).all()
        db_session.add_all([
            models.AssessmentScore(
                assessment_id=assessment.id,
                dimension_id=dimension.id,
                score=4,
                reason="搜索投影理由",
            )
            for dimension in dimensions
        ])
    db_session.commit()
    return child, conversation, job, assessment


def _request(**overrides) -> schemas.ConversationSearchRequest:
    return schemas.ConversationSearchRequest(**overrides)


def _decode_cursor(cursor: str) -> tuple[bytes, dict]:
    padding = "=" * ((4 - len(cursor) % 4) % 4)
    raw = base64.urlsafe_b64decode(cursor + padding)
    return raw, json.loads(raw.decode("utf-8"))


def _encode_cursor(value: dict, *, canonical: bool = True) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=canonical,
        separators=(",", ":") if canonical else (", ", ": "),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _equivalent_noncanonical_base64(cursor: str) -> str:
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    raw, _payload = _decode_cursor(cursor)
    remainder = len(raw) % 3
    assert remainder in {1, 2}
    unused_bits = 4 if remainder == 1 else 2
    index = alphabet.index(cursor[-1])
    replacement = (index & ~((1 << unused_bits) - 1)) | 1
    assert replacement != index
    mutated = cursor[:-1] + alphabet[replacement]
    assert _decode_cursor(mutated)[0] == raw
    return mutated


def test_search_static_route_authenticates_before_body_or_query_validation(client):
    paths = [route.path for route in conversations_router.routes]
    assert paths.index("/api/conversations/search") < paths.index(
        "/api/conversations/{conversation_id}"
    )

    malformed = client.post(
        "/api/conversations/search?unknown=secret",
        content=b"{not-json",
        headers={"content-type": "application/json"},
    )

    error = _error(malformed, 401, "TEACHER_AUTH_REQUIRED")
    assert error["field_errors"] == {}


def test_search_unauthenticated_asgi_request_reads_zero_body_bytes(client):
    receive_calls = 0
    messages = []

    async def exercise() -> None:
        async def receive():
            nonlocal receive_calls
            receive_calls += 1
            return {
                "type": "http.request",
                "body": b"{not-json-and-private-body",
                "more_body": False,
            }

        async def send(message):
            messages.append(message)

        await client.app({
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/conversations/search",
            "raw_path": b"/api/conversations/search",
            "query_string": b"unknown=private",
            "root_path": "",
            "headers": [(b"content-type", b"application/json")],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "state": {},
        }, receive, send)

    asyncio.run(exercise())
    start = next(message for message in messages if message["type"] == "http.response.start")
    body = b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    )
    assert start["status"] == 401
    assert b"TEACHER_AUTH_REQUIRED" in body
    assert receive_calls == 0


@pytest.mark.parametrize(
    "payload",
    [
        {"unknown": True},
        {"keyword": "   "},
        {"keyword": "x" * 101},
        {"date_from": "2026-09-02", "date_to": "2026-09-01"},
        {"date_from": "2025-09-01", "date_to": "2026-09-02"},
        {"analysis_status": ["failed", "failed"]},
        {"review_status": ["pending", "pending"]},
        {"end_reason": ["manual", "manual"]},
        {"cursor": "x" * 1025},
    ],
)
def test_search_rejects_invalid_body_and_every_query_parameter(client, payload):
    _unlock(client)
    error = _error(
        client.post("/api/conversations/search", json=payload),
        422,
        "VALIDATION_ERROR",
    )
    assert error["field_errors"]
    _error(
        client.post("/api/conversations/search?limit=20", json={}),
        422,
        "VALIDATION_ERROR",
    )


def test_search_filter_families_are_and_while_each_status_array_is_or(client, db_session):
    child = models.Child(name="组合筛选幼儿", avatar=None, active=True)
    other = models.Child(name="其他幼儿", avatar=None, active=True)
    db_session.add_all([child, other])
    db_session.flush()
    wanted = _seed_search(
        db_session,
        child=child,
        conversation_date="2026-08-20",
        ended_at=BASE_TIME,
        job_status="succeeded",
        review_status="confirmed",
        end_reason="complete",
        frozen_text="组合命中词",
    )[1]
    unavailable = _seed_search(
        db_session,
        child=child,
        conversation_date="2026-08-21",
        ended_at=BASE_TIME + timedelta(minutes=1),
        job_status="failed",
        end_reason="manual",
        frozen_text="组合命中词",
    )[1]
    _seed_search(
        db_session,
        child=other,
        conversation_date="2026-08-20",
        ended_at=BASE_TIME + timedelta(minutes=2),
        job_status="succeeded",
        review_status="confirmed",
        end_reason="complete",
        frozen_text="组合命中词",
    )
    _unlock(client)

    response = client.post("/api/conversations/search", json={
        "child_id": child.id,
        "date_from": "2026-08-20",
        "date_to": "2026-08-21",
        "analysis_status": ["succeeded", "failed"],
        "review_status": ["confirmed", "unavailable"],
        "end_reason": ["complete", "manual"],
        "keyword": "组合命中词",
        "sort": "completed_asc",
        "limit": 20,
    })

    assert response.status_code == 200, response.text
    assert [item["id"] for item in response.json()["items"]] == [
        wanted.id,
        unavailable.id,
    ]
    assert [item["review_status"] for item in response.json()["items"]] == [
        "confirmed",
        "unavailable",
    ]


def test_search_review_status_semantics_cover_all_succeeded_and_unavailable_states(
    client,
    db_session,
):
    rows = {}
    minute = 0
    for review_status in ("pending", "draft", "confirmed"):
        rows[f"review_{review_status}"] = _seed_search(
            db_session,
            ended_at=BASE_TIME + timedelta(minutes=minute),
            review_status=review_status,
        )[1]
        minute += 1
    for analysis_status in ("pending", "processing", "failed"):
        rows[f"analysis_{analysis_status}"] = _seed_search(
            db_session,
            ended_at=BASE_TIME + timedelta(minutes=minute),
            job_status=analysis_status,
        )[1]
        minute += 1
    _unlock(client)

    available = client.post("/api/conversations/search", json={
        "review_status": ["pending", "confirmed"],
        "sort": "completed_asc",
    }).json()
    unavailable = client.post("/api/conversations/search", json={
        "review_status": ["unavailable"],
        "sort": "completed_asc",
    }).json()

    assert [item["id"] for item in available["items"]] == [
        rows["review_pending"].id,
        rows["review_confirmed"].id,
    ]
    assert [item["id"] for item in unavailable["items"]] == [
        rows["analysis_pending"].id,
        rows["analysis_processing"].id,
        rows["analysis_failed"].id,
    ]
    assert all(item["review_status"] == "unavailable" for item in unavailable["items"])


def test_search_keyword_is_literal_frozen_role_bounded_and_preserves_projection_counts(
    client,
    db_session,
):
    literal = r"50%_\ 完成"
    wanted = _seed_search(db_session, frozen_text=f"前缀 {literal} 后缀")[1]
    _seed_search(db_session, frozen_text=r"50XQ\ 完成")
    _seed_search(
        db_session,
        frozen_text="冻结区无关键词",
        post_frozen_text=f"仅边界后出现 {literal}",
    )
    _unlock(client)

    response = client.post("/api/conversations/search", json={"keyword": literal})

    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["id"] for item in body["items"]] == [wanted.id]
    assert body["items"][0]["message_count"] == 4
    assert body["items"][0]["round"] == 2
    assert body["next_cursor"] is None


@pytest.mark.parametrize(
    "sort,expected",
    [
        ("completed_desc", "descending"),
        ("completed_asc", "ascending"),
    ],
)
def test_search_cursor_is_canonical_keyset_and_snapshot_excludes_new_inserts(
    client,
    db_session,
    sort,
    expected,
):
    conversations = [
        _seed_search(db_session, ended_at=BASE_TIME + timedelta(minutes=offset))[1]
        for offset in (0, 1, 1, 2, 3)
    ]
    _unlock(client)

    first_response = client.post("/api/conversations/search", json={
        "sort": sort,
        "limit": 2,
    })
    assert first_response.status_code == 200, first_response.text
    first = first_response.json()
    cursor = first["next_cursor"]
    assert cursor and "=" not in cursor and re.fullmatch(r"[A-Za-z0-9_-]+", cursor)
    raw, cursor_payload = _decode_cursor(cursor)
    assert raw == json.dumps(
        cursor_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert set(cursor_payload) == {
        "version", "ended_at", "id", "sort", "fingerprint", "snapshot_max_id",
    }
    assert cursor_payload["version"] == 1
    assert cursor_payload["sort"] == sort
    assert re.fullmatch(r"[0-9a-f]{64}", cursor_payload["fingerprint"])
    assert re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z", cursor_payload["ended_at"])
    assert cursor_payload["snapshot_max_id"] == max(row.id for row in conversations)

    inserted = _seed_search(
        db_session,
        ended_at=BASE_TIME + timedelta(days=1),
        frozen_text="分页后新插入",
    )[1]
    second = client.post("/api/conversations/search", json={
        "sort": sort,
        "limit": 1,
        "cursor": cursor,
    }).json()

    first_ids = [item["id"] for item in first["items"]]
    second_ids = [item["id"] for item in second["items"]]
    assert not set(first_ids) & set(second_ids)
    assert inserted.id not in second_ids
    all_expected = sorted(
        conversations,
        key=lambda row: (row.ended_at, row.id),
        reverse=expected == "descending",
    )
    assert first_ids + second_ids == [row.id for row in all_expected[:3]]


def test_search_cursor_fingerprint_ignores_limit_and_array_order_but_binds_filters(
    client,
    db_session,
):
    for minute in range(4):
        _seed_search(
            db_session,
            ended_at=BASE_TIME + timedelta(minutes=minute),
            job_status="failed",
            end_reason="manual",
        )
    _unlock(client)
    first = client.post("/api/conversations/search", json={
        "analysis_status": ["failed", "processing"],
        "end_reason": ["manual", "complete"],
        "limit": 1,
    }).json()
    assert first["next_cursor"]

    continued = client.post("/api/conversations/search", json={
        "analysis_status": ["processing", "failed"],
        "end_reason": ["complete", "manual"],
        "limit": 2,
        "cursor": first["next_cursor"],
    })
    assert continued.status_code == 200, continued.text

    for mutation in (
        {"analysis_status": ["failed"]},
        {"end_reason": ["manual"]},
        {"sort": "completed_asc"},
        {"keyword": "different"},
    ):
        body = {
            "analysis_status": ["failed", "processing"],
            "end_reason": ["manual", "complete"],
            "cursor": first["next_cursor"],
            **mutation,
        }
        error = _error(
            client.post("/api/conversations/search", json=body),
            422,
            "VALIDATION_ERROR",
        )
        assert "body.cursor" in error["field_errors"]


def test_search_rejects_noncanonical_or_malformed_cursor_variants(client, db_session):
    for minute in range(2):
        _seed_search(db_session, ended_at=BASE_TIME + timedelta(minutes=minute))
    _unlock(client)
    valid = client.post("/api/conversations/search", json={"limit": 1}).json()["next_cursor"]
    assert valid
    _raw, payload = _decode_cursor(valid)
    noncanonical_base64_source = _encode_cursor({
        **payload,
        "snapshot_max_id": payload["snapshot_max_id"] * 10,
    })
    variants = [
        _equivalent_noncanonical_base64(noncanonical_base64_source),
        _encode_cursor(payload, canonical=False),
        _encode_cursor({**payload, "extra": True}),
        _encode_cursor({key: value for key, value in payload.items() if key != "id"}),
        _encode_cursor({**payload, "id": True}),
        _encode_cursor({**payload, "snapshot_max_id": False}),
        _encode_cursor({**payload, "ended_at": "2026-08-23T09:00:00Z"}),
        _encode_cursor({**payload, "sort": "newest"}),
        _encode_cursor({**payload, "fingerprint": payload["fingerprint"].upper()}),
        _encode_cursor({**payload, "version": 2}),
        "_w",
    ]
    for cursor in variants:
        error = _error(
            client.post("/api/conversations/search", json={"limit": 1, "cursor": cursor}),
            422,
            "VALIDATION_ERROR",
        )
        assert "body.cursor" in error["field_errors"]
    _error(
        client.post("/api/conversations/search", json={"cursor": valid + "="}),
        422,
        "VALIDATION_ERROR",
    )


def test_search_fails_whole_page_for_selected_projection_corruption(client, db_session):
    _seed_search(db_session, ended_at=BASE_TIME)
    _child, corrupt, _job, assessment = _seed_search(
        db_session,
        ended_at=BASE_TIME + timedelta(minutes=1),
    )
    assert assessment is not None
    db_session.delete(assessment)
    db_session.commit()
    _unlock(client)

    response = client.post("/api/conversations/search", json={})

    _error(response, 500, "INTERNAL_ERROR")
    assert "items" not in response.text
    assert f'"id":{corrupt.id}' not in response.text


def test_search_fails_closed_when_review_status_drifts_during_projection(
    db_session,
    test_db_path,
):
    _child, _conversation, _job, assessment = _seed_search(
        db_session,
        review_status="pending",
    )
    assert assessment is not None
    assessment_id = assessment.id
    db_session.expunge_all()
    engine = db_session.get_bind()
    mutated = False

    def confirm_after_candidate(
        _connection,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ):
        nonlocal mutated
        normalized = " ".join(statement.lower().split())
        if mutated or " from messages " not in f" {normalized} ":
            return
        with sqlite3.connect(test_db_path, timeout=5) as writer:
            writer.execute(
                "UPDATE assessments SET status = ? WHERE id = ?",
                ("confirmed", assessment_id),
            )
            writer.commit()
        mutated = True

    event.listen(engine, "before_cursor_execute", confirm_after_candidate)
    try:
        with pytest.raises(APIError) as raised:
            history_service.search_conversations(
                db_session,
                _request(review_status=["pending"]),
            )
    finally:
        event.remove(engine, "before_cursor_execute", confirm_after_candidate)

    assert mutated is True
    assert raised.value.status_code == 500
    assert raised.value.code == "INTERNAL_ERROR"
    assert raised.value.retryable is True
    with sqlite3.connect(test_db_path) as reader:
        stored_status = reader.execute(
            "SELECT status FROM assessments WHERE id = ?",
            (assessment_id,),
        ).fetchone()[0]
    assert stored_status == "confirmed"


def test_search_projects_legacy_child_avatar_as_null_without_rewriting_storage(
    db_session,
):
    child = models.Child(
        name="历史头像幼儿",
        nickname="历史小名",
        avatar="uploads/legacy-child.png",
        active=True,
    )
    db_session.add(child)
    db_session.flush()
    child, conversation, _job, _assessment = _seed_search(
        db_session,
        child=child,
    )
    child_id = child.id
    conversation_id = conversation.id
    db_session.expunge_all()

    result = history_service.search_conversations(db_session, _request())

    item = next(entry for entry in result.items if entry.id == conversation_id)
    assert item.child.avatar is None
    assert db_session.get(models.Child, child_id).avatar == "uploads/legacy-child.png"


def test_search_db_exception_rolls_back_and_logs_only_error_type(
    db_session,
    caplog,
):
    _seed_search(db_session, job_status="failed")
    transient = models.Child(name="必须回滚的搜索写入", avatar=None)
    db_session.add(transient)
    engine = db_session.get_bind()

    def explode(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            raise RuntimeError("ultra-secret-keyword and bind")

    event.listen(engine, "before_cursor_execute", explode)
    caplog.set_level(logging.ERROR, logger="duck_diary.history")
    try:
        with pytest.raises(APIError) as raised:
            history_service.search_conversations(
                db_session,
                _request(keyword="ultra-secret-keyword"),
            )
    finally:
        event.remove(engine, "before_cursor_execute", explode)

    assert raised.value.status_code == 500
    assert raised.value.code == "INTERNAL_ERROR"
    assert raised.value.retryable is True
    assert "ultra-secret-keyword" not in caplog.text
    assert "bind" not in caplog.text
    assert "RuntimeError" in caplog.text
    assert db_session.scalar(select(models.Child).where(
        models.Child.name == "必须回滚的搜索写入"
    )) is None


def test_search_statement_budget_is_fixed_for_one_or_fifty_rows(db_session):
    for minute in range(50):
        _seed_search(
            db_session,
            ended_at=BASE_TIME + timedelta(minutes=minute),
            frozen_text="预算关键词",
        )
    engine = db_session.get_bind()

    def count_for(limit: int) -> int:
        statements = []

        def record(_connection, _cursor, statement, _parameters, _context, _executemany):
            if not statement.lstrip().upper().startswith(("BEGIN", "ROLLBACK")):
                statements.append(statement)

        event.listen(engine, "before_cursor_execute", record)
        try:
            result = history_service.search_conversations(
                db_session,
                _request(
                        keyword="预算关键词",
                        analysis_status=["succeeded"],
                        review_status=["pending"],
                    limit=limit,
                ),
            )
        finally:
            event.remove(engine, "before_cursor_execute", record)
        assert len(result.items) == limit
        return len(statements)

    one = count_for(1)
    fifty = count_for(50)
    assert one == fifty
    assert one <= 8


def test_search_response_model_is_strict():
    with pytest.raises(Exception):
        schemas.ConversationSearchPage.model_validate({
            "items": [],
            "next_cursor": None,
            "extra": True,
        })
