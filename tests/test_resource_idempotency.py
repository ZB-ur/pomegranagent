"""Idempotent child/duck create contracts using the schema-3 roster ledger."""
from __future__ import annotations

from datetime import UTC, datetime
from threading import Barrier, Lock, Thread

import pytest
from sqlalchemy import func, select

from app.backend import models, schemas
from app.backend.database import SETTINGS, SessionLocal


NOW = datetime(2026, 9, 2, 6, 7, 8, tzinfo=UTC)


def _unlock(client) -> None:
    assert client.post("/api/auth/setup", json={"pin": "1234"}).status_code == 200


@pytest.mark.parametrize(
    ("path", "request_id", "first_body", "replay_body", "changed_body", "model", "operation"),
    [
        pytest.param(
            "/api/children",
            "11111111-1111-4111-8111-111111111111",
            {"name": "  小雨  ", "nickname": "  雨雨  ", "avatar": None},
            {"name": "小雨", "nickname": "雨雨", "avatar": None},
            {"name": "小林", "nickname": "雨雨", "avatar": None},
            models.Child,
            "child_create",
            id="child",
        ),
        pytest.param(
            "/api/ducks",
            "22222222-2222-4222-8222-222222222222",
            {"name": "  小黄  ", "avatar": None, "status": "  健康  ", "note": None},
            {"name": "小黄", "avatar": None, "status": "健康", "note": None},
            {"name": "小白", "avatar": None, "status": "健康", "note": None},
            models.Duck,
            "duck_create",
            id="duck",
        ),
    ],
)
def test_create_retry_replays_exact_response_and_changed_payload_conflicts(
    client,
    db_session,
    path,
    request_id,
    first_body,
    replay_body,
    changed_body,
    model,
    operation,
) -> None:
    _unlock(client)
    headers = {"X-Request-ID": request_id}

    first = client.post(path, json=first_body, headers=headers)
    replay = client.post(path, json=replay_body, headers=headers)

    assert first.status_code == replay.status_code == 200
    assert replay.content == first.content
    assert first.headers["x-request-id"] == replay.headers["x-request-id"] == request_id
    assert db_session.scalar(select(func.count(model.id))) == 1
    record = db_session.get(models.RosterRequest, request_id)
    assert record is not None
    assert (record.operation, record.status) == (operation, "succeeded")
    assert record.response_json == first.text

    conflict = client.post(path, json=changed_body, headers=headers)
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert conflict.json()["error"]["retryable"] is False
    assert db_session.scalar(select(func.count(model.id))) == 1


def test_create_request_id_is_global_across_child_and_duck_operations(client, db_session) -> None:
    _unlock(client)
    request_id = "33333333-3333-4333-8333-333333333333"
    headers = {"X-Request-ID": request_id}
    child = client.post(
        "/api/children",
        json={"name": "小雨", "nickname": None, "avatar": None},
        headers=headers,
    )

    duck = client.post(
        "/api/ducks",
        json={"name": "小黄", "avatar": None, "status": None, "note": None},
        headers=headers,
    )

    assert child.status_code == 200
    assert duck.status_code == 409
    assert duck.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert db_session.scalar(select(func.count(models.Child.id))) == 1
    assert db_session.scalar(select(func.count(models.Duck.id))) == 0


def test_create_without_request_id_keeps_p5_non_idempotent_compatibility(client, db_session) -> None:
    _unlock(client)
    body = {"name": "同名幼儿", "nickname": None, "avatar": None}

    first = client.post("/api/children", json=body)
    second = client.post("/api/children", json=body)

    assert first.status_code == second.status_code == 200
    assert first.json()["id"] != second.json()["id"]
    assert db_session.scalar(select(func.count(models.Child.id))) == 2
    assert db_session.scalar(select(func.count(models.RosterRequest.request_id))) == 0


def test_service_concurrent_same_request_creates_one_child_and_two_exact_responses() -> None:
    from app.backend.services.resource_create import create_child

    payload = schemas.ChildMutationRequest.model_validate({
        "name": "并发幼儿",
        "nickname": "同一个",
        "avatar": None,
    })
    request_id = "44444444-4444-4444-8444-444444444444"
    start = Barrier(2)
    result_lock = Lock()
    results: list[schemas.ChildOut] = []
    errors: list[BaseException] = []

    def create() -> None:
        session = SessionLocal()
        try:
            start.wait(timeout=2)
            result = create_child(
                session,
                payload,
                request_id=request_id,
                media_root=SETTINGS.media_root,
                now=NOW,
            )
            with result_lock:
                results.append(result)
        except BaseException as error:
            with result_lock:
                errors.append(error)
        finally:
            session.close()

    threads = [Thread(target=create), Thread(target=create)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert not any(thread.is_alive() for thread in threads)
    assert errors == []
    assert len(results) == 2
    assert results[0].model_dump(mode="json") == results[1].model_dump(mode="json")
    with SessionLocal() as fresh:
        assert fresh.scalar(select(func.count(models.Child.id))) == 1
        record = fresh.get(models.RosterRequest, request_id)
        assert record is not None
        assert (record.operation, record.status) == ("child_create", "succeeded")
        assert schemas.ChildOut.model_validate_json(record.response_json) == results[0]


def test_service_commit_failure_rolls_back_resource_and_ledger(db_session, monkeypatch) -> None:
    from app.backend.services.resource_create import create_duck

    payload = schemas.DuckMutationRequest.model_validate({
        "name": "不能保存",
        "avatar": None,
        "status": None,
        "note": None,
    })

    def fail_commit() -> None:
        raise RuntimeError("synthetic resource commit failure")

    monkeypatch.setattr(db_session, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="synthetic resource commit failure"):
        create_duck(
            db_session,
            payload,
            request_id="55555555-5555-4555-8555-555555555555",
            media_root=SETTINGS.media_root,
            now=NOW,
        )

    with SessionLocal() as fresh:
        assert fresh.scalar(select(func.count(models.Duck.id))) == 0
        assert fresh.scalar(select(func.count(models.RosterRequest.request_id))) == 0
