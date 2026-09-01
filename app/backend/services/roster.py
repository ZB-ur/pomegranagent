"""Atomic, idempotent roster reads and writes."""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from typing import TypeVar

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models, schemas
from ..api_errors import APIError


_DAILY_OPERATION = "daily_roster"
_AUTO_OPERATION = "auto_roster"
_MONTHLY_OPERATION = "monthly_roster"
_Response = TypeVar(
    "_Response",
    schemas.DailyRosterResponse,
    schemas.AutoRosterResponse,
    schemas.MonthlyRosterResponse,
)

_ERROR_MESSAGES = {
    "CHILD_NOT_FOUND": "幼儿不存在或已停用",
    "IDEMPOTENCY_CONFLICT": "请求 ID 与已有提交不一致",
    "INSUFFICIENT_ACTIVE_CHILDREN": "至少需要两名在园幼儿",
    "REQUEST_IN_PROGRESS": "请求正在处理中",
    "ROSTER_DATE_CONFLICT": "目标日期已有排班",
}


def _error(status_code: int, code: str, *, retryable: bool = False) -> APIError:
    return APIError(
        status_code,
        code,
        _ERROR_MESSAGES.get(code, "请求处理失败"),
        retryable=retryable,
    )


def _canonical_hash(operation: str, body: dict[str, object]) -> str:
    canonical = json.dumps(
        {"operation": operation, **body},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _request_id(
    payload: (
        schemas.DailyRosterRequest
        | schemas.AutoRosterRequest
        | schemas.MonthlyRosterRequest
    ),
) -> str:
    return str(payload.request_id)


def _stored_replay(
    db: Session,
    *,
    request_id: str,
    operation: str,
    payload_hash: str,
    response_type: type[_Response],
    record: models.RosterRequest | None = None,
) -> _Response:
    if record is None:
        record = db.scalar(
            select(models.RosterRequest)
            .where(models.RosterRequest.request_id == request_id)
            .execution_options(populate_existing=True)
        )
    if record is None:
        db.rollback()
        raise APIError(500, "INTERNAL_ERROR", "服务暂时不可用，请稍后重试", retryable=True)
    if record.operation != operation or record.payload_hash != payload_hash:
        db.rollback()
        raise _error(409, "IDEMPOTENCY_CONFLICT")
    if record.status == "succeeded":
        if not record.response_json:
            raise APIError(500, "INTERNAL_ERROR", "服务暂时不可用，请稍后重试", retryable=True)
        replay = response_type.model_validate_json(record.response_json)
        db.rollback()
        return replay.model_copy(update={"replayed": True})
    db.rollback()
    raise _error(409, "REQUEST_IN_PROGRESS", retryable=True)


def _claim_request(
    db: Session,
    *,
    request_id: str,
    operation: str,
    payload_hash: str,
    now: datetime,
    response_type: type[_Response],
) -> tuple[models.RosterRequest | None, _Response | None]:
    record = models.RosterRequest(
        request_id=request_id,
        operation=operation,
        payload_hash=payload_hash,
        status="processing",
        created_at=now,
        updated_at=now,
    )
    db.add(record)
    try:
        db.flush()
    except IntegrityError as error:
        db.rollback()
        record = db.scalar(
            select(models.RosterRequest)
            .where(models.RosterRequest.request_id == request_id)
            .execution_options(populate_existing=True)
        )
        if record is None:
            db.rollback()
            raise error
        return None, _stored_replay(
            db,
            request_id=request_id,
            operation=operation,
            payload_hash=payload_hash,
            response_type=response_type,
            record=record,
        )
    return record, None


def _finish_request(
    record: models.RosterRequest,
    response: _Response,
    *,
    now: datetime,
) -> None:
    record.response_json = response.model_dump_json()
    record.status = "succeeded"
    record.updated_at = now


def _active_children_for_daily(
    db: Session,
    child_ids: list[int],
) -> list[models.Child]:
    children = db.scalars(
        select(models.Child)
        .where(
            models.Child.id.in_(child_ids),
            models.Child.active.is_(True),
        )
        .order_by(models.Child.id)
    ).all()
    if len(children) != len(child_ids):
        raise _error(404, "CHILD_NOT_FOUND")
    return children


def _is_roster_unique_error(error: IntegrityError) -> bool:
    detail = str(getattr(error, "orig", error)).lower()
    return (
        "uq_roster_date_child" in detail
        or "duty_rosters.date, duty_rosters.child_id" in detail
    )


def _raise_after_write_error(db: Session, error: IntegrityError) -> None:
    db.rollback()
    if _is_roster_unique_error(error):
        raise _error(409, "ROSTER_DATE_CONFLICT") from error
    raise error


def get_today_roster(
    db: Session,
    *,
    today: date,
) -> list[schemas.RosterTodayChild]:
    rows = db.execute(
        select(
            models.DutyRoster.id,
            models.Child.id,
            models.Child.name,
            models.Child.nickname,
            models.Child.avatar,
        )
        .join(models.Child, models.DutyRoster.child_id == models.Child.id)
        .where(
            models.DutyRoster.date == today.isoformat(),
            models.Child.active.is_(True),
        )
        .order_by(models.DutyRoster.id)
    ).all()
    seen_ids: set[int] = set()
    result: list[schemas.RosterTodayChild] = []
    for _roster_id, child_id, name, nickname, avatar in rows:
        if child_id in seen_ids:
            continue
        seen_ids.add(child_id)
        result.append(
            schemas.RosterTodayChild(
                id=child_id,
                name=name,
                nickname=nickname,
                avatar=avatar,
            )
        )
    return result


def set_daily_roster(
    db: Session,
    payload: schemas.DailyRosterRequest,
    *,
    roster_date: date,
    now: datetime,
) -> schemas.DailyRosterResponse:
    child_ids = sorted(payload.child_ids)
    request_hash = _canonical_hash(
        _DAILY_OPERATION,
        {
            "date": roster_date.isoformat(),
            "cycle": payload.cycle,
            "child_ids": child_ids,
        },
    )
    record, replay = _claim_request(
        db,
        request_id=_request_id(payload),
        operation=_DAILY_OPERATION,
        payload_hash=request_hash,
        now=now,
        response_type=schemas.DailyRosterResponse,
    )
    if replay is not None:
        return replay
    assert record is not None

    try:
        _active_children_for_daily(db, child_ids)
        db.execute(
            delete(models.DutyRoster).where(
                models.DutyRoster.date == roster_date.isoformat()
            )
        )
        db.add_all(
            [
                models.DutyRoster(
                    cycle=payload.cycle,
                    date=roster_date.isoformat(),
                    child_id=child_id,
                )
                for child_id in child_ids
            ]
        )
        response = schemas.DailyRosterResponse(
            request_id=payload.request_id,
            date=roster_date,
            cycle=payload.cycle,
            child_ids=child_ids,
            replayed=False,
        )
        _finish_request(record, response, now=now)
        db.flush()
        db.commit()
        return response
    except APIError:
        db.rollback()
        raise
    except IntegrityError as error:
        _raise_after_write_error(db, error)
    except Exception:
        db.rollback()
        raise


def _weekday_schedule(
    *,
    start_date: date,
    days: int,
    child_ids: list[int],
) -> list[tuple[date, list[int]]]:
    target = start_date
    schedule: list[tuple[date, list[int]]] = []
    for index in range(days):
        while target.weekday() >= 5:
            target += timedelta(days=1)
        offset = index * 2
        schedule.append(
            (
                target,
                [
                    child_ids[offset % len(child_ids)],
                    child_ids[(offset + 1) % len(child_ids)],
                ],
            )
        )
        target += timedelta(days=1)
    return schedule


def generate_roster(
    db: Session,
    payload: schemas.AutoRosterRequest,
    *,
    now: datetime,
) -> schemas.AutoRosterResponse:
    request_hash = _canonical_hash(
        _AUTO_OPERATION,
        {
            "start_date": payload.start_date.isoformat(),
            "days": payload.days,
            "cycle": payload.cycle,
            "replace_existing": payload.replace_existing,
        },
    )
    record, replay = _claim_request(
        db,
        request_id=_request_id(payload),
        operation=_AUTO_OPERATION,
        payload_hash=request_hash,
        now=now,
        response_type=schemas.AutoRosterResponse,
    )
    if replay is not None:
        return replay
    assert record is not None

    try:
        child_ids = list(
            db.scalars(
                select(models.Child.id)
                .where(models.Child.active.is_(True))
                .order_by(models.Child.id)
            )
        )
        if len(child_ids) < 2:
            raise _error(409, "INSUFFICIENT_ACTIVE_CHILDREN")
        schedule = _weekday_schedule(
            start_date=payload.start_date,
            days=payload.days,
            child_ids=child_ids,
        )
        target_dates = [target.isoformat() for target, _pair in schedule]
        occupied = db.scalar(
            select(models.DutyRoster.id)
            .where(models.DutyRoster.date.in_(target_dates))
            .limit(1)
        )
        if occupied is not None and not payload.replace_existing:
            raise _error(409, "ROSTER_DATE_CONFLICT")
        if payload.replace_existing:
            db.execute(
                delete(models.DutyRoster).where(
                    models.DutyRoster.date.in_(target_dates)
                )
            )
        db.add_all(
            [
                models.DutyRoster(
                    cycle=payload.cycle,
                    date=target.isoformat(),
                    child_id=child_id,
                )
                for target, pair in schedule
                for child_id in pair
            ]
        )
        response = schemas.AutoRosterResponse(
            request_id=payload.request_id,
            schedule=[
                schemas.AutoRosterScheduleItem(date=target, child_ids=pair)
                for target, pair in schedule
            ],
            replayed=False,
        )
        _finish_request(record, response, now=now)
        db.flush()
        db.commit()
        return response
    except APIError:
        db.rollback()
        raise
    except IntegrityError as error:
        _raise_after_write_error(db, error)
    except Exception:
        db.rollback()
        raise


def set_monthly_roster(
    db: Session,
    payload: schemas.MonthlyRosterRequest,
    *,
    now: datetime,
) -> schemas.MonthlyRosterResponse:
    """Atomically publish one canonical set of explicit monthly duty pairs."""

    entries = sorted(
        (
            entry.date,
            sorted(entry.child_ids),
        )
        for entry in payload.entries
    )
    request_hash = _canonical_hash(
        _MONTHLY_OPERATION,
        {
            "month": payload.month,
            "cycle": payload.cycle,
            "entries": [
                {
                    "date": roster_date.isoformat(),
                    "child_ids": child_ids,
                }
                for roster_date, child_ids in entries
            ],
            "replace_existing": payload.replace_existing,
        },
    )
    record, replay = _claim_request(
        db,
        request_id=_request_id(payload),
        operation=_MONTHLY_OPERATION,
        payload_hash=request_hash,
        now=now,
        response_type=schemas.MonthlyRosterResponse,
    )
    if replay is not None:
        return replay
    assert record is not None

    try:
        distinct_child_ids = sorted(
            {
                child_id
                for _roster_date, child_ids in entries
                for child_id in child_ids
            }
        )
        _active_children_for_daily(db, distinct_child_ids)
        target_dates = [roster_date.isoformat() for roster_date, _child_ids in entries]
        occupied = db.scalar(
            select(models.DutyRoster.id)
            .where(models.DutyRoster.date.in_(target_dates))
            .limit(1)
        )
        if occupied is not None and not payload.replace_existing:
            raise _error(409, "ROSTER_DATE_CONFLICT")
        if payload.replace_existing:
            db.execute(
                delete(models.DutyRoster).where(
                    models.DutyRoster.date.in_(target_dates)
                )
            )
        db.add_all(
            [
                models.DutyRoster(
                    cycle=payload.cycle,
                    date=roster_date.isoformat(),
                    child_id=child_id,
                )
                for roster_date, child_ids in entries
                for child_id in child_ids
            ]
        )
        response = schemas.MonthlyRosterResponse(
            request_id=payload.request_id,
            month=payload.month,
            schedule=[
                schemas.MonthlyRosterScheduleItem(
                    date=roster_date,
                    cycle=payload.cycle,
                    child_ids=child_ids,
                )
                for roster_date, child_ids in entries
            ],
            replayed=False,
        )
        _finish_request(record, response, now=now)
        db.flush()
        db.commit()
        return response
    except APIError:
        db.rollback()
        raise
    except IntegrityError as error:
        _raise_after_write_error(db, error)
    except Exception:
        db.rollback()
        raise
