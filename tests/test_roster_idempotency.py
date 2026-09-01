"""Contract tests for public roster reads and idempotent teacher roster writes."""
from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
from threading import Barrier, Lock, Thread
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, OperationalError

from app.backend import models, schemas
from app.backend.api_errors import APIError
from app.backend.database import SessionLocal, engine
from app.backend.routes import roster as roster_routes
from app.backend.routes.roster import router as roster_router
from app.backend.services import roster as roster_service


NOW = datetime(2026, 8, 23, 9, 0, tzinfo=timezone.utc)


def _child(db_session, *, name: str, active: bool = True) -> models.Child:
    child = models.Child(name=name, nickname=f"{name}小名", active=active)
    db_session.add(child)
    db_session.commit()
    return child


def _roster(db_session, *, roster_date: str, child_id: int, cycle: str = "2026-W34") -> None:
    db_session.add(
        models.DutyRoster(cycle=cycle, date=roster_date, child_id=child_id)
    )
    db_session.commit()


def _unlock(client) -> None:
    response = client.post("/api/auth/setup", json={"pin": "1234"})
    assert response.status_code == 200


def _error(response, *, status: int, code: str) -> None:
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


def _daily_body(*, child_ids: list[int], request_id: str | None = None, cycle: str = "2026-W34") -> dict:
    return {
        "request_id": request_id or str(uuid4()),
        "cycle": cycle,
        "child_ids": child_ids,
    }


def _auto_body(
    *,
    request_id: str | None = None,
    start_date: str = "2026-08-24",
    days: int = 1,
    cycle: str = "2026-W34",
    replace_existing: bool = False,
) -> dict:
    return {
        "request_id": request_id or str(uuid4()),
        "start_date": start_date,
        "days": days,
        "cycle": cycle,
        "replace_existing": replace_existing,
    }


def _monthly_body(
    *,
    entries: list[dict[str, object]],
    request_id: str | None = None,
    month: str = "2026-08",
    cycle: str = "2026-W34",
    replace_existing: bool = False,
) -> dict[str, object]:
    return {
        "request_id": request_id or str(uuid4()),
        "month": month,
        "cycle": cycle,
        "entries": entries,
        "replace_existing": replace_existing,
    }


def _rows(db_session) -> list[tuple[str, str, int]]:
    db_session.expire_all()
    return [
        (row.date, row.cycle, row.child_id)
        for row in db_session.scalars(
            select(models.DutyRoster).order_by(models.DutyRoster.date, models.DutyRoster.id)
        )
    ]


def _daily_hash(*, roster_date: str, cycle: str, child_ids: list[int]) -> str:
    """Handwritten canonical fixture: changing canonical semantics must break this test."""
    canonical = json.dumps(
        {
            "operation": "daily_roster",
            "date": roster_date,
            "cycle": cycle,
            "child_ids": sorted(child_ids),
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _monthly_hash(
    *,
    month: str,
    cycle: str,
    entries: list[dict[str, object]],
    replace_existing: bool,
) -> str:
    """Independent literal oracle for the frozen monthly canonical request."""
    normalized_entries = [
        {
            "date": str(entry["date"]),
            "child_ids": sorted(int(child_id) for child_id in entry["child_ids"]),
        }
        for entry in sorted(entries, key=lambda entry: str(entry["date"]))
    ]
    canonical = json.dumps(
        {
            "operation": "monthly_roster",
            "month": month,
            "cycle": cycle,
            "entries": normalized_entries,
            "replace_existing": replace_existing,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_today_is_public_and_returns_active_ordered_deduplicated_identities(
    client,
    db_session,
):
    """Catches today reads that leak inactive or duplicate roster identities."""
    # A legacy/corrupt database can contain duplicate roster rows even though
    # new schemas protect them; the public projection must still be safe.
    db_session.execute(text("DROP TABLE duty_rosters"))
    db_session.execute(text("""
        CREATE TABLE duty_rosters (
            id INTEGER PRIMARY KEY,
            cycle VARCHAR(64) NOT NULL,
            date VARCHAR(16) NOT NULL,
            child_id INTEGER NOT NULL
        )
    """))
    db_session.commit()
    first = _child(db_session, name="小雨")
    inactive = _child(db_session, name="停用", active=False)
    second = _child(db_session, name="乐乐")
    today = date.today().isoformat()
    _roster(db_session, roster_date=today, child_id=second.id)
    _roster(db_session, roster_date=today, child_id=inactive.id)
    _roster(db_session, roster_date=today, child_id=first.id)
    _roster(db_session, roster_date=today, child_id=second.id)

    response = client.get("/api/roster/today")

    assert response.status_code == 200
    assert response.json() == [
        {"id": second.id, "name": "乐乐", "nickname": "乐乐小名", "avatar": None},
        {"id": first.id, "name": "小雨", "nickname": "小雨小名", "avatar": None},
    ]


def test_today_roster_uses_one_captured_business_date(client, db_session, monkeypatch):
    """Catches host-calendar reads or multiple samples around Shanghai midnight."""
    child = _child(db_session, name="跨午夜值日生")
    _roster(db_session, roster_date="2026-09-01", child_id=child.id)

    class Clock:
        calls = 0

        @classmethod
        def business_today(cls) -> date:
            cls.calls += 1
            if cls.calls > 1:
                raise AssertionError("today roster read the business clock twice")
            return date(2026, 9, 1)

    monkeypatch.setattr(roster_routes, "BUSINESS_CLOCK", Clock)

    response = client.get("/api/roster/today")

    assert response.status_code == 200
    assert response.json() == [{
        "id": child.id,
        "name": "跨午夜值日生",
        "nickname": "跨午夜值日生小名",
        "avatar": None,
    }]
    assert Clock.calls == 1


def test_today_is_public_empty_and_uses_one_join_query(client, db_session):
    """Catches an empty day that falls back to children or performs one lookup per roster row."""
    statements: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    from sqlalchemy import event

    event.listen(engine, "before_cursor_execute", capture)
    try:
        response = client.get("/api/roster/today")
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    assert response.status_code == 200
    assert response.json() == []
    assert len(statements) == 1


def test_teacher_roster_list_has_strict_response_model_and_rejects_query_aliases(
    client,
    db_session,
):
    child = _child(db_session, name="历史值日", active=False)
    _roster(db_session, roster_date="2026-08-24", child_id=child.id, cycle="2026-W34")
    _unlock(client)

    response = client.get("/api/roster")

    assert response.status_code == 200
    assert response.json() == [{
        "id": 1,
        "cycle": "2026-W34",
        "date": "2026-08-24",
        "child_id": child.id,
    }]
    route = next(route for route in roster_router.routes if route.path == "/api/roster")
    assert route.response_model == list[schemas.RosterListItem]
    _error(client.get("/api/roster?cycle=2026-W34"), status=422, code="VALIDATION_ERROR")


def test_teacher_roster_routes_lock_before_legacy_tombstone_and_tombstone_never_writes(
    client,
    db_session,
):
    """Catches unlocked legacy writers or tombstones that bypass teacher auth."""
    body = {
        "request_id": str(uuid4()),
        "cycle": "2026-W34",
        "child_ids": [1, 2],
    }
    auto = {
        "request_id": str(uuid4()),
        "start_date": "2026-08-24",
        "days": 1,
        "cycle": "2026-W34",
        "replace_existing": False,
    }
    monthly = {
        "request_id": str(uuid4()),
        "month": "not-a-month",
        "cycle": "",
        "entries": [],
        "replace_existing": False,
    }
    for method, path, payload in [
        ("get", "/api/roster", None),
        ("put", "/api/roster/2026-08-24", body),
        ("post", "/api/roster/auto", auto),
        ("post", "/api/roster/month", monthly),
        ("post", "/api/roster", {"cycle": "legacy", "date": "2026-08-24", "child_ids": [1, 2]}),
    ]:
        request = getattr(client, method)
        response = request(path, json=payload) if payload is not None else request(path)
        _error(response, status=401, code="TEACHER_AUTH_REQUIRED")

    _unlock(client)
    tombstone = client.post(
        "/api/roster",
        json={"cycle": "legacy", "date": "2026-08-24", "child_ids": [1, 2]},
    )

    _error(tombstone, status=410, code="LEGACY_ENDPOINT_REMOVED")
    assert db_session.scalars(select(models.DutyRoster)).all() == []


def test_daily_put_replaces_only_its_date_with_exactly_two_active_children(
    client,
    db_session,
):
    """Catches a manual writer that appends, alters other dates, or lacks the frozen PUT route."""
    first = _child(db_session, name="甲")
    second = _child(db_session, name="乙")
    old = _child(db_session, name="旧")
    other_date_child = _child(db_session, name="别日")
    _roster(db_session, roster_date="2026-08-24", child_id=old.id, cycle="old")
    _roster(db_session, roster_date="2026-08-25", child_id=other_date_child.id, cycle="other")
    _unlock(client)
    request_id = "c30a6409-58b8-48f0-96f0-8ff679bebed7"

    response = client.put(
        "/api/roster/2026-08-24",
        json={"request_id": request_id, "cycle": " 2026-W34 ", "child_ids": [second.id, first.id]},
    )

    assert response.status_code == 200
    assert response.json() == {
        "request_id": request_id,
        "date": "2026-08-24",
        "cycle": "2026-W34",
        "child_ids": [first.id, second.id],
        "replayed": False,
    }
    db_session.expire_all()
    assert [
        (row.date, row.cycle, row.child_id)
        for row in db_session.scalars(
            select(models.DutyRoster).order_by(models.DutyRoster.date, models.DutyRoster.child_id)
        )
    ] == [
        ("2026-08-24", "2026-W34", first.id),
        ("2026-08-24", "2026-W34", second.id),
        ("2026-08-25", "other", other_date_child.id),
    ]


def test_daily_replay_is_stable_after_child_state_changes_and_conflicts_on_changed_semantics(
    client,
    db_session,
):
    """Catches replays that rewrite rows or reuse one UUID for another semantic request."""
    first = _child(db_session, name="甲")
    second = _child(db_session, name="乙")
    third = _child(db_session, name="丙")
    _unlock(client)
    request_id = "71d88b2f-477d-458d-9522-71c426a11d93"
    body = _daily_body(child_ids=[second.id, first.id], request_id=request_id)

    first_response = client.put("/api/roster/2026-08-24", json=body)
    assert first_response.status_code == 200
    first_snapshot = first_response.json()
    assert _rows(db_session) == [
        ("2026-08-24", "2026-W34", first.id),
        ("2026-08-24", "2026-W34", second.id),
    ]
    first.active = False
    db_session.commit()

    reordered = client.put(
        "/api/roster/2026-08-24",
        json=_daily_body(child_ids=[first.id, second.id], request_id=request_id),
    )
    assert reordered.status_code == 200
    assert reordered.json() == {**first_snapshot, "replayed": True}
    assert _rows(db_session) == [
        ("2026-08-24", "2026-W34", first.id),
        ("2026-08-24", "2026-W34", second.id),
    ]

    for path, changed in [
        ("/api/roster/2026-08-25", body),
        ("/api/roster/2026-08-24", _daily_body(child_ids=[second.id, third.id], request_id=request_id)),
        ("/api/roster/2026-08-24", _daily_body(child_ids=[second.id, first.id], request_id=request_id, cycle="other")),
    ]:
        _error(client.put(path, json=changed), status=409, code="IDEMPOTENCY_CONFLICT")
    _error(
        client.post(
            "/api/roster/auto",
            json=_auto_body(request_id=request_id, days=1),
        ),
        status=409,
        code="IDEMPOTENCY_CONFLICT",
    )


def test_daily_missing_or_inactive_children_preserve_existing_rows_and_ledger(
    client,
    db_session,
):
    """Catches daily replacement deleting the old assignment before full child validation."""
    active = _child(db_session, name="有效")
    inactive = _child(db_session, name="停用", active=False)
    old = _child(db_session, name="旧值日")
    _roster(db_session, roster_date="2026-08-24", child_id=old.id, cycle="old")
    _unlock(client)

    missing_id = "d4082899-398d-4c33-a02d-ca16c2709600"
    _error(
        client.put(
            "/api/roster/2026-08-24",
            json=_daily_body(child_ids=[active.id, 9999], request_id=missing_id),
        ),
        status=404,
        code="CHILD_NOT_FOUND",
    )
    inactive_id = "0e8ca54c-9b53-49f0-a500-3fa232cb8f68"
    _error(
        client.put(
            "/api/roster/2026-08-24",
            json=_daily_body(child_ids=[active.id, inactive.id], request_id=inactive_id),
        ),
        status=404,
        code="CHILD_NOT_FOUND",
    )

    assert _rows(db_session) == [("2026-08-24", "old", old.id)]
    assert db_session.get(models.RosterRequest, missing_id) is None
    assert db_session.get(models.RosterRequest, inactive_id) is None


def test_auto_generates_five_rotating_weekday_pairs_and_replays_first_snapshot(
    client,
    db_session,
):
    """Catches calendar-day counting, non-deterministic rotation, or replay recomputation."""
    children = [_child(db_session, name=f"幼儿{index}") for index in range(1, 6)]
    _unlock(client)
    request_id = "962ebd53-0cb0-444f-8b83-dfe4eae99247"
    body = _auto_body(request_id=request_id, days=5)

    response = client.post("/api/roster/auto", json=body)

    assert response.status_code == 200
    assert response.json() == {
        "request_id": request_id,
        "schedule": [
            {"date": "2026-08-24", "child_ids": [children[0].id, children[1].id]},
            {"date": "2026-08-25", "child_ids": [children[2].id, children[3].id]},
            {"date": "2026-08-26", "child_ids": [children[4].id, children[0].id]},
            {"date": "2026-08-27", "child_ids": [children[1].id, children[2].id]},
            {"date": "2026-08-28", "child_ids": [children[3].id, children[4].id]},
        ],
        "replayed": False,
    }
    first_snapshot = response.json()
    assert len(_rows(db_session)) == 10
    replay = client.post("/api/roster/auto", json=body)
    assert replay.status_code == 200
    assert replay.json() == {**first_snapshot, "replayed": True}
    assert len(_rows(db_session)) == 10
    _error(
        client.post("/api/roster/auto", json={**body, "days": 4}),
        status=409,
        code="IDEMPOTENCY_CONFLICT",
    )


def test_auto_weekend_start_advances_to_monday_without_spending_a_day(client, db_session):
    """Catches schedules that count Saturday and Sunday toward the requested weekdays."""
    first = _child(db_session, name="甲")
    second = _child(db_session, name="乙")
    _unlock(client)

    response = client.post(
        "/api/roster/auto",
        json=_auto_body(start_date="2026-08-22", days=2),
    )

    assert response.status_code == 200
    assert response.json()["schedule"] == [
        {"date": "2026-08-24", "child_ids": [first.id, second.id]},
        {"date": "2026-08-25", "child_ids": [first.id, second.id]},
    ]


def test_auto_requires_two_active_children_and_rejects_an_occupied_batch_atomically(
    client,
    db_session,
):
    """Catches partial auto schedules when capacity or one target date is invalid."""
    only = _child(db_session, name="仅有")
    _unlock(client)
    _error(
        client.post("/api/roster/auto", json=_auto_body(days=1)),
        status=409,
        code="INSUFFICIENT_ACTIVE_CHILDREN",
    )
    assert db_session.scalars(select(models.RosterRequest)).all() == []

    second = _child(db_session, name="第二")
    _roster(db_session, roster_date="2026-08-25", child_id=only.id, cycle="old")
    request_id = "79d967c0-a2d3-4eb0-a20b-5a437ffba0a5"
    _error(
        client.post("/api/roster/auto", json=_auto_body(request_id=request_id, days=2)),
        status=409,
        code="ROSTER_DATE_CONFLICT",
    )
    assert _rows(db_session) == [("2026-08-25", "old", only.id)]
    assert db_session.get(models.RosterRequest, request_id) is None
    assert second.id > only.id


def test_auto_replacement_overwrites_every_target_date_in_one_schedule(client, db_session):
    """Catches replacement that leaves old target rows or replaces only the first date."""
    first = _child(db_session, name="甲")
    second = _child(db_session, name="乙")
    old = _child(db_session, name="旧")
    _roster(db_session, roster_date="2026-08-24", child_id=old.id, cycle="old")
    _roster(db_session, roster_date="2026-08-25", child_id=old.id, cycle="old")
    _unlock(client)

    response = client.post(
        "/api/roster/auto",
        json=_auto_body(days=2, replace_existing=True),
    )

    assert response.status_code == 200
    assert _rows(db_session) == [
        ("2026-08-24", "2026-W34", first.id),
        ("2026-08-24", "2026-W34", second.id),
        ("2026-08-25", "2026-W34", old.id),
        ("2026-08-25", "2026-W34", first.id),
    ]


@pytest.mark.parametrize("failure", ["flush", "commit"])
def test_auto_write_failures_roll_back_replacement_and_the_processing_ledger(
    db_session,
    monkeypatch,
    failure,
):
    """Catches failed replacement commits that leave either rows or a success ledger behind."""
    first = _child(db_session, name="甲")
    second = _child(db_session, name="乙")
    old = _child(db_session, name="旧")
    _roster(db_session, roster_date="2026-08-24", child_id=old.id, cycle="old")
    _roster(db_session, roster_date="2026-08-25", child_id=old.id, cycle="old")
    request_id = str(uuid4())
    payload = schemas.AutoRosterRequest.model_validate(
        _auto_body(request_id=request_id, days=2, replace_existing=True)
    )

    if failure == "flush":
        original_flush = db_session.flush
        flush_count = 0

        def fail_final_flush(*args, **kwargs):
            nonlocal flush_count
            flush_count += 1
            if flush_count == 2:
                raise RuntimeError("forced final flush failure")
            return original_flush(*args, **kwargs)

        monkeypatch.setattr(db_session, "flush", fail_final_flush)
    else:
        def fail_commit(*args, **kwargs):
            raise RuntimeError("forced commit failure")

        monkeypatch.setattr(db_session, "commit", fail_commit)

    with pytest.raises(RuntimeError, match=rf"forced .*{failure}"):
        roster_service.generate_roster(db_session, payload, now=NOW)

    with SessionLocal() as fresh:
        assert [
            (row.date, row.cycle, row.child_id)
            for row in fresh.scalars(
                select(models.DutyRoster).order_by(models.DutyRoster.date, models.DutyRoster.id)
            )
        ] == [
            ("2026-08-24", "old", old.id),
            ("2026-08-25", "old", old.id),
        ]
        assert fresh.get(models.RosterRequest, request_id) is None
    assert second.id > first.id


def test_unrelated_integrity_error_is_not_mislabeled_as_a_roster_date_conflict(
    db_session,
    monkeypatch,
):
    """Catches broad IntegrityError handling that hides unrelated database faults as occupancy."""
    _child(db_session, name="甲")
    _child(db_session, name="乙")
    payload = schemas.AutoRosterRequest.model_validate(_auto_body(days=1))
    original_flush = db_session.flush
    flush_count = 0

    def unrelated_final_flush(*args, **kwargs):
        nonlocal flush_count
        flush_count += 1
        if flush_count == 2:
            raise IntegrityError("INSERT INTO unrelated", {}, Exception("unrelated constraint"))
        return original_flush(*args, **kwargs)

    monkeypatch.setattr(db_session, "flush", unrelated_final_flush)

    with pytest.raises(IntegrityError, match="unrelated constraint"):
        roster_service.generate_roster(db_session, payload, now=NOW)
    with SessionLocal() as fresh:
        assert fresh.scalars(select(models.DutyRoster)).all() == []
        assert fresh.get(models.RosterRequest, str(payload.request_id)) is None


def test_unrelated_first_claim_integrity_error_is_reraised_without_a_ledger(
    db_session,
    monkeypatch,
):
    """Catches a claim collision handler that disguises an unrelated first flush failure as replay."""
    _child(db_session, name="甲")
    _child(db_session, name="乙")
    payload = schemas.AutoRosterRequest.model_validate(_auto_body(days=1))
    expected = IntegrityError(
        "INSERT INTO unrelated_claim",
        {},
        Exception("unrelated first claim constraint"),
    )

    def fail_first_claim_flush(*args, **kwargs):
        raise expected

    monkeypatch.setattr(db_session, "flush", fail_first_claim_flush)

    with pytest.raises(IntegrityError) as raised:
        roster_service.generate_roster(db_session, payload, now=NOW)

    assert raised.value is expected
    with SessionLocal() as fresh:
        assert fresh.get(models.RosterRequest, str(payload.request_id)) is None
        assert fresh.scalars(select(models.DutyRoster)).all() == []


def test_concurrent_daily_same_uuid_returns_one_snapshot_and_one_replay(db_session):
    """Catches concurrent daily retries that produce multiple commits instead of a stable replay."""
    first = _child(db_session, name="甲")
    second = _child(db_session, name="乙")
    payload = schemas.DailyRosterRequest.model_validate(
        _daily_body(
            child_ids=[second.id, first.id],
            request_id="293b175d-4fc1-4fe8-83de-7f445bd5e6ed",
        )
    )
    start = Barrier(2)
    lock = Lock()
    results: list[schemas.DailyRosterResponse] = []
    failures: list[BaseException] = []

    def write_daily() -> None:
        session = SessionLocal()
        try:
            start.wait(timeout=2)
            response = roster_service.set_daily_roster(
                session,
                payload,
                roster_date=date(2026, 8, 24),
                now=NOW,
            )
            with lock:
                results.append(response)
        except BaseException as error:
            with lock:
                failures.append(error)
        finally:
            session.close()

    threads = [Thread(target=write_daily), Thread(target=write_daily)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert not any(thread.is_alive() for thread in threads)
    assert failures == []
    assert sorted(response.replayed for response in results) == [False, True]
    assert {
        json.dumps(response.model_dump(mode="json", exclude={"replayed"}), sort_keys=True)
        for response in results
    } == {
        json.dumps(
            {
                "request_id": str(payload.request_id),
                "date": "2026-08-24",
                "cycle": "2026-W34",
                "child_ids": [first.id, second.id],
            },
            sort_keys=True,
        )
    }
    with SessionLocal() as fresh:
        record = fresh.get(models.RosterRequest, str(payload.request_id))
        assert record is not None
        assert record.status == "succeeded"
        assert schemas.DailyRosterResponse.model_validate_json(record.response_json).model_dump(mode="json") == {
            "request_id": str(payload.request_id),
            "date": "2026-08-24",
            "cycle": "2026-W34",
            "child_ids": [first.id, second.id],
            "replayed": False,
        }
        assert fresh.scalar(select(func.count(models.RosterRequest.request_id))) == 1
        assert fresh.scalar(select(func.count(models.DutyRoster.id))) == 2


def test_concurrent_auto_distinct_uuids_leave_one_schedule_and_one_date_conflict(db_session):
    """Catches colliding auto writers that strand a ledger or partially write a losing schedule."""
    first = _child(db_session, name="甲")
    second = _child(db_session, name="乙")
    payloads = [
        schemas.AutoRosterRequest.model_validate(
            _auto_body(request_id=request_id, days=1)
        )
        for request_id in (
            "1d4a2815-1798-490e-bbd2-2a0a94e66ec6",
            "bdf2651a-1992-4578-995e-7231fd11a24e",
        )
    ]
    start = Barrier(2)
    lock = Lock()
    successes: list[schemas.AutoRosterResponse] = []
    conflicts: list[APIError] = []
    failures: list[BaseException] = []

    def generate(payload: schemas.AutoRosterRequest) -> None:
        session = SessionLocal()
        try:
            start.wait(timeout=2)
            response = roster_service.generate_roster(session, payload, now=NOW)
            with lock:
                successes.append(response)
        except APIError as error:
            with lock:
                conflicts.append(error)
        except BaseException as error:
            with lock:
                failures.append(error)
        finally:
            session.close()

    threads = [Thread(target=generate, args=(payload,)) for payload in payloads]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert not any(thread.is_alive() for thread in threads)
    assert failures == []
    assert len(successes) == 1
    assert successes[0].replayed is False
    assert [error.code for error in conflicts] == ["ROSTER_DATE_CONFLICT"]
    with SessionLocal() as fresh:
        assert [
            (row.date, row.child_id)
            for row in fresh.scalars(
                select(models.DutyRoster).order_by(models.DutyRoster.id)
            )
        ] == [
            ("2026-08-24", first.id),
            ("2026-08-24", second.id),
        ]
        records = fresh.scalars(select(models.RosterRequest).order_by(models.RosterRequest.request_id)).all()
        assert len(records) == 1
        assert records[0].status == "succeeded"
        assert records[0].request_id in {str(payload.request_id) for payload in payloads}


def test_daily_final_flush_failure_rolls_back_replacement_and_ledger_from_a_fresh_session(
    db_session,
    monkeypatch,
):
    """Catches a daily final flush failure that leaves either replaced rows or a response snapshot durable."""
    first = _child(db_session, name="甲")
    second = _child(db_session, name="乙")
    old = _child(db_session, name="旧")
    _roster(db_session, roster_date="2026-08-24", child_id=old.id, cycle="old")
    request_id = str(uuid4())
    payload = schemas.DailyRosterRequest.model_validate(
        _daily_body(child_ids=[first.id, second.id], request_id=request_id)
    )
    original_flush = db_session.flush
    flush_count = 0

    def fail_daily_final_flush(*args, **kwargs):
        nonlocal flush_count
        flush_count += 1
        if flush_count == 2:
            raise RuntimeError("forced daily final flush failure")
        return original_flush(*args, **kwargs)

    monkeypatch.setattr(db_session, "flush", fail_daily_final_flush)

    with pytest.raises(RuntimeError, match="forced daily final flush failure"):
        roster_service.set_daily_roster(
            db_session,
            payload,
            roster_date=date(2026, 8, 24),
            now=NOW,
        )

    with SessionLocal() as fresh:
        assert [
            (row.date, row.cycle, row.child_id)
            for row in fresh.scalars(select(models.DutyRoster).order_by(models.DutyRoster.id))
        ] == [("2026-08-24", "old", old.id)]
        assert fresh.get(models.RosterRequest, request_id) is None


def test_processing_roster_request_is_retryable_and_never_mutates_rows(client, db_session):
    """Catches a duplicate UUID stealing a visible in-progress request or overwriting its rows."""
    first = _child(db_session, name="甲")
    second = _child(db_session, name="乙")
    _unlock(client)
    request_id = "0b331690-e8fe-488b-9a2b-47923db8f087"
    body = _daily_body(child_ids=[first.id, second.id], request_id=request_id)
    db_session.add(
        models.RosterRequest(
            request_id=request_id,
            operation="daily_roster",
            payload_hash=_daily_hash(
                roster_date="2026-08-24",
                cycle="2026-W34",
                child_ids=[first.id, second.id],
            ),
            status="processing",
        )
    )
    db_session.commit()

    response = client.put("/api/roster/2026-08-24", json=body)

    _error(response, status=409, code="REQUEST_IN_PROGRESS")
    assert response.json()["error"]["retryable"] is True
    assert _rows(db_session) == []


def test_daily_commit_failure_rolls_back_replacement_and_ledger_from_a_fresh_session(
    db_session,
    monkeypatch,
):
    """Catches manual replacement committing a snapshot separately from its two roster rows."""
    first = _child(db_session, name="甲")
    second = _child(db_session, name="乙")
    old = _child(db_session, name="旧")
    _roster(db_session, roster_date="2026-08-24", child_id=old.id, cycle="old")
    request_id = str(uuid4())
    payload = schemas.DailyRosterRequest.model_validate(
        _daily_body(child_ids=[first.id, second.id], request_id=request_id)
    )

    def fail_commit(*args, **kwargs):
        raise RuntimeError("forced daily commit failure")

    monkeypatch.setattr(db_session, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="forced daily commit failure"):
        roster_service.set_daily_roster(
            db_session,
            payload,
            roster_date=date(2026, 8, 24),
            now=NOW,
        )

    with SessionLocal() as fresh:
        assert [
            (row.date, row.cycle, row.child_id)
            for row in fresh.scalars(select(models.DutyRoster).order_by(models.DutyRoster.id))
        ] == [("2026-08-24", "old", old.id)]
        assert fresh.get(models.RosterRequest, request_id) is None


def test_teacher_list_is_unfiltered_deterministic_and_path_is_iso_date(client, db_session):
    """Catches ambiguous list filters or a dynamic route that accepts non-date paths."""
    first = _child(db_session, name="甲")
    second = _child(db_session, name="乙")
    _roster(db_session, roster_date="2026-08-25", child_id=first.id, cycle="A")
    _roster(db_session, roster_date="2026-08-24", child_id=second.id, cycle="B")
    _roster(db_session, roster_date="2026-08-24", child_id=first.id, cycle="A")
    _unlock(client)

    listed = client.get("/api/roster")
    filtered = client.get("/api/roster", params={"cycle": "A"})
    invalid_date = client.put(
        "/api/roster/not-an-iso-date",
        json=_daily_body(child_ids=[first.id, second.id]),
    )

    assert listed.status_code == 200
    assert [(row["date"], row["id"]) for row in listed.json()] == [
        ("2026-08-24", 2),
        ("2026-08-24", 3),
        ("2026-08-25", 1),
    ]
    _error(filtered, status=422, code="VALIDATION_ERROR")
    _error(invalid_date, status=422, code="VALIDATION_ERROR")
    assert db_session.scalars(select(models.RosterRequest)).all() == []


def test_real_concurrent_unique_row_failure_is_classified_as_a_roster_date_conflict(db_session):
    """Catches a missing final database guard or classification of its real unique failure as generic conflict."""
    child = _child(db_session, name="甲")
    child_id = child.id
    barrier = Barrier(2)
    outcomes: list[str] = []
    errors: list[IntegrityError] = []

    def insert_same_row() -> None:
        session = SessionLocal()
        try:
            session.add(
                models.DutyRoster(cycle="race", date="2026-08-24", child_id=child_id)
            )
            barrier.wait(timeout=2)
            session.commit()
            outcomes.append("committed")
        except IntegrityError as error:
            session.rollback()
            errors.append(error)
            outcomes.append("unique")
        except OperationalError as error:  # pragma: no cover - SQLite should serialize then recheck.
            session.rollback()
            outcomes.append(f"operational:{error}")
        finally:
            session.close()

    threads = [Thread(target=insert_same_row), Thread(target=insert_same_row)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert not any(thread.is_alive() for thread in threads)
    assert sorted(outcomes) == ["committed", "unique"]
    assert len(errors) == 1
    with SessionLocal() as fresh:
        assert fresh.scalar(
            select(func.count(models.DutyRoster.id)).where(
                models.DutyRoster.date == "2026-08-24",
                models.DutyRoster.child_id == child_id,
            )
        ) == 1
        with pytest.raises(APIError) as classified:
            roster_service._raise_after_write_error(fresh, errors[0])
    assert classified.value.code == "ROSTER_DATE_CONFLICT"


def test_monthly_route_canonicalizes_dates_pairs_and_uses_one_clock_sample(
    client,
    db_session,
    monkeypatch,
):
    """Catches request-order hashes, unsorted pairs, current-month limits, or clock resampling."""
    children = [_child(db_session, name=f"月排幼儿{index}") for index in range(4)]
    _unlock(client)

    class Clock:
        calls = 0

        @classmethod
        def utc_now(cls) -> datetime:
            cls.calls += 1
            if cls.calls > 1:
                raise AssertionError("monthly roster sampled the business clock twice")
            return NOW

    monkeypatch.setattr(roster_routes, "BUSINESS_CLOCK", Clock)
    request_id = "846885f8-2b41-4641-a159-8d408d1aae58"
    response = client.post(
        "/api/roster/month",
        json=_monthly_body(
            request_id=request_id,
            month="2027-02",
            cycle=" 2027-春季 ",
            entries=[
                {"date": "2027-02-07", "child_ids": [children[3].id, children[2].id]},
                {"date": "2027-02-01", "child_ids": [children[1].id, children[0].id]},
            ],
        ),
    )

    assert response.status_code == 200
    assert response.json() == {
        "request_id": request_id,
        "month": "2027-02",
        "schedule": [
            {
                "date": "2027-02-01",
                "cycle": "2027-春季",
                "child_ids": [children[0].id, children[1].id],
            },
            {
                "date": "2027-02-07",
                "cycle": "2027-春季",
                "child_ids": [children[2].id, children[3].id],
            },
        ],
        "replayed": False,
    }
    assert Clock.calls == 1
    assert _rows(db_session) == [
        ("2027-02-01", "2027-春季", children[0].id),
        ("2027-02-01", "2027-春季", children[1].id),
        ("2027-02-07", "2027-春季", children[2].id),
        ("2027-02-07", "2027-春季", children[3].id),
    ]


def test_monthly_accepts_31_calendar_dates_and_rejects_every_structural_boundary(
    client,
    db_session,
):
    """Catches weekend filtering or bypasses of the frozen 1-31/in-month/pair invariants."""
    first = _child(db_session, name="甲")
    second = _child(db_session, name="乙")
    _unlock(client)
    entries = [
        {"date": f"2027-01-{day:02d}", "child_ids": [first.id, second.id]}
        for day in range(1, 32)
    ]

    accepted = client.post(
        "/api/roster/month",
        json=_monthly_body(month="2027-01", entries=entries),
    )

    assert accepted.status_code == 200
    assert len(accepted.json()["schedule"]) == 31
    baseline = _rows(db_session)
    assert len(baseline) == 62
    invalid_entries = [
        [],
        entries + [entries[0]],
        [entries[0], entries[0]],
        [{"date": "2027-02-01", "child_ids": [first.id, second.id]}],
        [{"date": "2027-01-01", "child_ids": [first.id, first.id]}],
        [{"date": "2027-01-01", "child_ids": [0, second.id]}],
    ]
    for candidate in invalid_entries:
        response = client.post(
            "/api/roster/month",
            json=_monthly_body(month="2027-01", entries=candidate),
        )
        _error(response, status=422, code="VALIDATION_ERROR")

    assert _rows(db_session) == baseline
    assert db_session.scalar(select(func.count(models.RosterRequest.request_id))) == 1


def test_monthly_claim_precedes_one_child_query_and_one_occupancy_query(
    db_session,
):
    """Catches validation-before-lock, N+1 child checks, or per-date occupancy reads."""
    from sqlalchemy import event

    children = [_child(db_session, name=f"查询幼儿{index}") for index in range(4)]
    payload = schemas.MonthlyRosterRequest.model_validate(
        _monthly_body(
            entries=[
                {"date": "2026-08-24", "child_ids": [children[0].id, children[1].id]},
                {"date": "2026-08-25", "child_ids": [children[2].id, children[3].id]},
            ]
        )
    )
    statements: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(" ".join(statement.lower().split()))

    event.listen(engine, "before_cursor_execute", capture)
    try:
        response = roster_service.set_monthly_roster(db_session, payload, now=NOW)
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    claim_indexes = [
        index for index, statement in enumerate(statements)
        if statement.startswith("insert into roster_requests")
    ]
    child_queries = [
        index for index, statement in enumerate(statements)
        if statement.startswith("select") and " from children " in f" {statement} "
    ]
    occupancy_queries = [
        index for index, statement in enumerate(statements)
        if statement.startswith("select") and " from duty_rosters " in f" {statement} "
    ]
    assert response.replayed is False
    assert len(claim_indexes) == 1
    assert len(child_queries) == 1
    assert len(occupancy_queries) == 1
    assert claim_indexes[0] < child_queries[0] < occupancy_queries[0]


def test_monthly_validates_all_distinct_active_children_before_occupancy_or_writes(
    db_session,
):
    """Catches deletion or occupancy work before the complete active-child set is validated."""
    from sqlalchemy import event

    active = _child(db_session, name="有效")
    inactive = _child(db_session, name="停用", active=False)
    old = _child(db_session, name="原排班")
    _roster(db_session, roster_date="2026-08-24", child_id=old.id, cycle="old")
    request_id = "76d661ec-a990-4499-b24c-2eb1e3aaee9e"
    payload = schemas.MonthlyRosterRequest.model_validate(
        _monthly_body(
            request_id=request_id,
            replace_existing=True,
            entries=[
                {"date": "2026-08-24", "child_ids": [active.id, inactive.id]},
                {"date": "2026-08-25", "child_ids": [active.id, 99999]},
            ],
        )
    )
    statements: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(" ".join(statement.lower().split()))

    event.listen(engine, "before_cursor_execute", capture)
    try:
        with pytest.raises(APIError) as raised:
            roster_service.set_monthly_roster(db_session, payload, now=NOW)
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    assert raised.value.status_code == 404
    assert raised.value.code == "CHILD_NOT_FOUND"
    assert sum(
        statement.startswith("select") and " from children " in f" {statement} "
        for statement in statements
    ) == 1
    assert not any(
        statement.startswith("select") and " from duty_rosters " in f" {statement} "
        for statement in statements
    )
    assert not any(statement.startswith("delete from duty_rosters") for statement in statements)
    assert _rows(db_session) == [("2026-08-24", "old", old.id)]
    assert db_session.get(models.RosterRequest, request_id) is None


def test_monthly_any_occupied_date_conflicts_without_changing_the_batch_or_ledger(
    client,
    db_session,
):
    """Catches a non-replace batch that partially inserts dates before finding occupancy."""
    first = _child(db_session, name="甲")
    second = _child(db_session, name="乙")
    old = _child(db_session, name="旧")
    untouched = _child(db_session, name="别日")
    _roster(db_session, roster_date="2026-08-25", child_id=old.id, cycle="old")
    _roster(db_session, roster_date="2026-09-01", child_id=untouched.id, cycle="untouched")
    _unlock(client)
    request_id = "969d2b3b-3e2b-45a8-bdb8-35dc3a0d0f78"

    response = client.post(
        "/api/roster/month",
        json=_monthly_body(
            request_id=request_id,
            entries=[
                {"date": "2026-08-24", "child_ids": [first.id, second.id]},
                {"date": "2026-08-25", "child_ids": [first.id, second.id]},
            ],
        ),
    )

    _error(response, status=409, code="ROSTER_DATE_CONFLICT")
    assert _rows(db_session) == [
        ("2026-08-25", "old", old.id),
        ("2026-09-01", "untouched", untouched.id),
    ]
    assert db_session.get(models.RosterRequest, request_id) is None


def test_monthly_replace_rebuilds_only_submitted_dates_and_keeps_untouched_rows(
    client,
    db_session,
):
    """Catches month-wide deletion or stale rows surviving on submitted replacement dates."""
    children = [_child(db_session, name=f"幼儿{index}") for index in range(5)]
    _roster(db_session, roster_date="2026-08-24", child_id=children[4].id, cycle="old-a")
    _roster(db_session, roster_date="2026-08-26", child_id=children[4].id, cycle="old-b")
    _roster(db_session, roster_date="2026-08-31", child_id=children[4].id, cycle="untouched")
    _roster(db_session, roster_date="2026-09-01", child_id=children[4].id, cycle="outside")
    _unlock(client)

    response = client.post(
        "/api/roster/month",
        json=_monthly_body(
            cycle="new-cycle",
            replace_existing=True,
            entries=[
                {"date": "2026-08-26", "child_ids": [children[3].id, children[2].id]},
                {"date": "2026-08-24", "child_ids": [children[1].id, children[0].id]},
            ],
        ),
    )

    assert response.status_code == 200
    assert _rows(db_session) == [
        ("2026-08-24", "new-cycle", children[0].id),
        ("2026-08-24", "new-cycle", children[1].id),
        ("2026-08-26", "new-cycle", children[2].id),
        ("2026-08-26", "new-cycle", children[3].id),
        ("2026-08-31", "untouched", children[4].id),
        ("2026-09-01", "outside", children[4].id),
    ]


def test_monthly_replay_uses_the_original_snapshot_after_child_deactivation(
    client,
    db_session,
):
    """Catches replay recomputation or hash sensitivity to entry and pair ordering."""
    children = [_child(db_session, name=f"重放幼儿{index}") for index in range(4)]
    _unlock(client)
    request_id = "8b36ac27-8ec8-423a-b470-8a9a66d75349"
    original_entries = [
        {"date": "2026-08-25", "child_ids": [children[3].id, children[2].id]},
        {"date": "2026-08-24", "child_ids": [children[1].id, children[0].id]},
    ]
    first = client.post(
        "/api/roster/month",
        json=_monthly_body(request_id=request_id, entries=original_entries),
    )
    assert first.status_code == 200
    snapshot = first.json()
    children[0].active = False
    db_session.commit()

    replay = client.post(
        "/api/roster/month",
        json=_monthly_body(
            request_id=request_id,
            entries=[
                {"date": "2026-08-24", "child_ids": [children[0].id, children[1].id]},
                {"date": "2026-08-25", "child_ids": [children[2].id, children[3].id]},
            ],
        ),
    )

    assert replay.status_code == 200
    assert replay.json() == {**snapshot, "replayed": True}
    assert len(_rows(db_session)) == 4

    changed_requests = [
        _monthly_body(request_id=request_id, cycle="changed", entries=original_entries),
        _monthly_body(
            request_id=request_id,
            replace_existing=True,
            entries=original_entries,
        ),
        _monthly_body(
            request_id=request_id,
            month="2026-09",
            entries=[
                {"date": "2026-09-01", "child_ids": [children[0].id, children[1].id]}
            ],
        ),
        _monthly_body(
            request_id=request_id,
            entries=[
                {"date": "2026-08-24", "child_ids": [children[0].id, children[2].id]}
            ],
        ),
    ]
    for changed in changed_requests:
        _error(
            client.post("/api/roster/month", json=changed),
            status=409,
            code="IDEMPOTENCY_CONFLICT",
        )


@pytest.mark.parametrize(
    "operation",
    ["daily_roster", "auto_roster", "child_create", "duck_create"],
)
def test_monthly_request_id_conflicts_with_every_existing_ledger_operation(
    client,
    db_session,
    operation,
):
    """Catches cross-operation UUID reuse being mistaken for a monthly replay."""
    first = _child(db_session, name="甲")
    second = _child(db_session, name="乙")
    request_id = str(uuid4())
    db_session.add(
        models.RosterRequest(
            request_id=request_id,
            operation=operation,
            payload_hash="0" * 64,
            status="succeeded",
            response_json="{}",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    db_session.commit()
    _unlock(client)

    response = client.post(
        "/api/roster/month",
        json=_monthly_body(
            request_id=request_id,
            entries=[{"date": "2026-08-24", "child_ids": [first.id, second.id]}],
        ),
    )

    _error(response, status=409, code="IDEMPOTENCY_CONFLICT")
    assert _rows(db_session) == []


def test_monthly_processing_request_is_retryable_and_never_mutates_rows(
    client,
    db_session,
):
    """Catches a retry stealing an in-progress monthly claim."""
    first = _child(db_session, name="甲")
    second = _child(db_session, name="乙")
    request_id = "9842a82d-305f-4670-a574-50163f854c47"
    entries = [{"date": "2026-08-24", "child_ids": [second.id, first.id]}]
    db_session.add(
        models.RosterRequest(
            request_id=request_id,
            operation="monthly_roster",
            payload_hash=_monthly_hash(
                month="2026-08",
                cycle="2026-W34",
                entries=entries,
                replace_existing=False,
            ),
            status="processing",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    db_session.commit()
    _unlock(client)

    response = client.post(
        "/api/roster/month",
        json=_monthly_body(request_id=request_id, entries=entries),
    )

    _error(response, status=409, code="REQUEST_IN_PROGRESS")
    assert response.json()["error"]["retryable"] is True
    assert _rows(db_session) == []


@pytest.mark.parametrize("failure", ["flush", "commit", "integrity"])
def test_monthly_write_failures_roll_back_rows_and_processing_ledger(
    db_session,
    monkeypatch,
    failure,
):
    """Catches monthly rows or snapshots escaping a failed one-transaction commit."""
    first = _child(db_session, name="甲")
    second = _child(db_session, name="乙")
    old = _child(db_session, name="旧")
    untouched = _child(db_session, name="别日")
    _roster(db_session, roster_date="2026-08-24", child_id=old.id, cycle="old")
    _roster(db_session, roster_date="2026-08-31", child_id=untouched.id, cycle="untouched")
    request_id = str(uuid4())
    payload = schemas.MonthlyRosterRequest.model_validate(
        _monthly_body(
            request_id=request_id,
            replace_existing=True,
            entries=[{"date": "2026-08-24", "child_ids": [first.id, second.id]}],
        )
    )

    if failure in {"flush", "integrity"}:
        original_flush = db_session.flush
        flush_count = 0

        def fail_final_flush(*args, **kwargs):
            nonlocal flush_count
            flush_count += 1
            if flush_count == 2:
                if failure == "integrity":
                    raise IntegrityError(
                        "INSERT INTO unrelated_monthly",
                        {},
                        Exception("unrelated monthly constraint"),
                    )
                raise RuntimeError("forced monthly flush failure")
            return original_flush(*args, **kwargs)

        monkeypatch.setattr(db_session, "flush", fail_final_flush)
    else:
        def fail_commit(*args, **kwargs):
            raise RuntimeError("forced monthly commit failure")

        monkeypatch.setattr(db_session, "commit", fail_commit)

    expected = IntegrityError if failure == "integrity" else RuntimeError
    with pytest.raises(expected, match="monthly"):
        roster_service.set_monthly_roster(db_session, payload, now=NOW)

    with SessionLocal() as fresh:
        assert [
            (row.date, row.cycle, row.child_id)
            for row in fresh.scalars(
                select(models.DutyRoster).order_by(models.DutyRoster.date, models.DutyRoster.id)
            )
        ] == [
            ("2026-08-24", "old", old.id),
            ("2026-08-31", "untouched", untouched.id),
        ]
        assert fresh.get(models.RosterRequest, request_id) is None


def test_concurrent_monthly_distinct_uuids_same_date_leave_exactly_one_pair(
    db_session,
):
    """Catches two validated batches racing into a four-child duty date."""
    children = [_child(db_session, name=f"并发幼儿{index}") for index in range(4)]
    child_ids = [child.id for child in children]
    payloads = [
        schemas.MonthlyRosterRequest.model_validate(
            _monthly_body(
                request_id=request_id,
                entries=[{"date": "2026-08-24", "child_ids": pair}],
            )
        )
        for request_id, pair in [
            ("51c92cb1-0d52-4ea0-9932-7f3442414ef6", child_ids[:2]),
            ("b3991426-8a35-4374-90e4-d98b8ba239ed", child_ids[2:]),
        ]
    ]
    start = Barrier(2)
    lock = Lock()
    successes: list[schemas.MonthlyRosterResponse] = []
    conflicts: list[APIError] = []
    failures: list[BaseException] = []

    def write_month(payload: schemas.MonthlyRosterRequest) -> None:
        session = SessionLocal()
        try:
            start.wait(timeout=2)
            result = roster_service.set_monthly_roster(session, payload, now=NOW)
            with lock:
                successes.append(result)
        except APIError as error:
            with lock:
                conflicts.append(error)
        except BaseException as error:
            with lock:
                failures.append(error)
        finally:
            session.close()

    threads = [Thread(target=write_month, args=(payload,)) for payload in payloads]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert not any(thread.is_alive() for thread in threads)
    assert failures == []
    assert len(successes) == 1
    assert successes[0].replayed is False
    assert [error.code for error in conflicts] == ["ROSTER_DATE_CONFLICT"]
    with SessionLocal() as fresh:
        assigned = list(
            fresh.scalars(
                select(models.DutyRoster.child_id)
                .where(models.DutyRoster.date == "2026-08-24")
                .order_by(models.DutyRoster.child_id)
            )
        )
        assert assigned in [sorted(child_ids[:2]), sorted(child_ids[2:])]
        assert fresh.scalar(select(func.count(models.DutyRoster.id))) == 2
        records = fresh.scalars(select(models.RosterRequest)).all()
        assert len(records) == 1
        assert records[0].status == "succeeded"


def test_roster_openapi_inventory_has_one_new_handler_per_exact_path():
    """Catches duplicate legacy handlers or static routes shadowed by the date route."""
    from app.backend.main import app

    expected = {
        ("GET", "/api/roster/today"),
        ("GET", "/api/roster"),
        ("POST", "/api/roster"),
        ("POST", "/api/roster/auto"),
        ("POST", "/api/roster/month"),
        ("PUT", "/api/roster/{roster_date}"),
    }
    direct_and_included_routes = [
        child
        for route in app.router.routes
        for child in (
            route.original_router.routes
            if hasattr(route, "original_router")
            else [route]
        )
    ]
    routes = [
        (method, route.path, route)
        for route in direct_and_included_routes
        if hasattr(route, "methods")
        for method in route.methods
        if method in {"GET", "POST", "PUT"}
    ]
    for method, path in expected:
        matching = [route for current_method, current_path, route in routes if (current_method, current_path) == (method, path)]
        assert len(matching) == 1, (method, path)
        if path != "/api/roster/today":
            dependencies = [
                getattr(dependency.call, "__name__", None)
                for dependency in matching[0].dependant.dependencies
            ]
            assert "require_teacher_session" in dependencies, (method, path)

    documented = app.openapi()["paths"]
    assert set(path for _method, path in expected) <= documented.keys()
    assert set(documented["/api/roster/today"]) == {"get"}
    assert set(documented["/api/roster"]) == {"get", "post"}
    assert set(documented["/api/roster/auto"]) == {"post"}
    assert set(documented["/api/roster/month"]) == {"post"}
    assert set(documented["/api/roster/{roster_date}"]) == {"put"}
    paths = [route.path for route in roster_router.routes]
    assert paths.index("/api/roster/month") < paths.index("/api/roster/{roster_date}")
