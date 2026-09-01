"""Idempotent child/duck create contracts using the schema-3 roster ledger."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import json
from threading import Barrier, Lock, Thread

import pytest
from sqlalchemy import func, select

from app.backend import models, schemas
from app.backend.auth import COOKIE_NAME
from app.backend.database import SETTINGS, SessionLocal
from app.backend.main import app


NOW = datetime(2026, 9, 2, 6, 7, 8, tzinfo=UTC)


def _unlock(client) -> None:
    assert client.post("/api/auth/setup", json={"pin": "1234"}).status_code == 200


async def _raw_asgi_create(
    *,
    path: str,
    body: dict[str, object],
    cookie: str,
    request_id_headers: list[bytes],
) -> tuple[int, dict[str, str], dict[str, object]]:
    encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
    messages: list[dict] = []
    received = False

    async def receive() -> dict:
        nonlocal received
        if received:
            return {"type": "http.disconnect"}
        received = True
        return {"type": "http.request", "body": encoded, "more_body": False}

    async def send(message: dict) -> None:
        messages.append(message)

    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(encoded)).encode("ascii")),
        (b"cookie", f"{COOKIE_NAME}={cookie}".encode("ascii")),
    ]
    headers.extend((b"x-request-id", value) for value in request_id_headers)
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "state": {},
    }
    await app(scope, receive, send)
    start = next(message for message in messages if message["type"] == "http.response.start")
    response_headers = {
        key.decode("latin-1").lower(): value.decode("latin-1")
        for key, value in start["headers"]
    }
    response_body = b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    )
    return start["status"], response_headers, json.loads(response_body)


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


@pytest.mark.parametrize(
    ("path", "body", "model"),
    [
        pytest.param(
            "/api/children",
            {"name": "非法请求头幼儿", "nickname": None, "avatar": None},
            models.Child,
            id="child",
        ),
        pytest.param(
            "/api/ducks",
            {"name": "非法请求头小鸭", "avatar": None, "status": None, "note": None},
            models.Duck,
            id="duck",
        ),
    ],
)
@pytest.mark.parametrize(
    "request_id_headers",
    [
        pytest.param(
            [
                b"abcdefab-cdef-4abc-8def-abcdefabcdef",
                b"abcdefab-cdef-4abc-8def-abcdefabcdef",
            ],
            id="duplicate",
        ),
        pytest.param([b""], id="empty"),
        pytest.param([b"not-a-uuid"], id="not-uuid"),
        pytest.param([b"ABCDEFAB-CDEF-4ABC-8DEF-ABCDEFABCDEF"], id="uppercase"),
        pytest.param(
            [b"abcdefab-cdef-4abc-8def-abcdefabcdef-extra"],
            id="overlong",
        ),
        pytest.param(
            [b" abcdefab-cdef-4abc-8def-abcdefabcdef"],
            id="whitespace",
        ),
        pytest.param([b"abcdefab-cdef-1abc-8def-abcdefabcdef"], id="uuid-v1"),
        pytest.param([b"00000000-0000-0000-0000-000000000000"], id="uuid-nil"),
    ],
)
def test_present_noncanonical_request_id_is_422_before_resource_or_ledger_write(
    client,
    db_session,
    path,
    body,
    model,
    request_id_headers,
) -> None:
    _unlock(client)
    cookie = client.cookies.get(COOKIE_NAME)
    assert cookie is not None

    status, _headers, payload = asyncio.run(
        _raw_asgi_create(
            path=path,
            body=body,
            cookie=cookie,
            request_id_headers=request_id_headers,
        )
    )

    assert status == 422
    assert payload["error"]["code"] == "VALIDATION_ERROR"
    assert payload["error"]["field_errors"] == {
        "header.x-request-id": ["X-Request-ID 必须是单个 canonical UUIDv4"]
    }
    assert db_session.scalar(select(func.count(model.id))) == 0
    assert db_session.scalar(select(func.count(models.RosterRequest.request_id))) == 0


@pytest.mark.parametrize(
    ("ledger_status", "expected_status", "expected_code", "retryable"),
    [
        pytest.param("failed", 409, "REQUEST_FAILED", False, id="failed"),
        pytest.param("unexpected", 500, "INTERNAL_ERROR", True, id="unknown"),
    ],
)
def test_non_success_terminal_or_unknown_ledger_state_fails_closed_without_new_write(
    client,
    db_session,
    ledger_status,
    expected_status,
    expected_code,
    retryable,
) -> None:
    _unlock(client)
    request_id = "66666666-6666-4666-8666-666666666666"
    body = {"name": "一次幼儿", "nickname": None, "avatar": None}
    first = client.post(
        "/api/children",
        json=body,
        headers={"X-Request-ID": request_id},
    )
    assert first.status_code == 200
    record = db_session.get(models.RosterRequest, request_id)
    assert record is not None
    record.status = ledger_status
    record.response_json = None
    record.last_error_code = "PRIVATE_PROVIDER_FAILURE"
    record.last_error_message = "secret upstream detail"
    db_session.commit()

    replay = client.post(
        "/api/children",
        json=body,
        headers={"X-Request-ID": request_id},
    )

    assert replay.status_code == expected_status
    assert replay.json()["error"]["code"] == expected_code
    assert replay.json()["error"]["retryable"] is retryable
    assert "secret" not in replay.text
    assert "PRIVATE_PROVIDER_FAILURE" not in replay.text
    assert db_session.scalar(select(func.count(models.Child.id))) == 1


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
