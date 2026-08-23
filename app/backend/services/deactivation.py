"""Transactional, reversible resource state changes for teacher administration."""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import exists, func, select, update
from sqlalchemy.orm import Session

from .. import models, schemas
from ..api_errors import APIError


_ERROR_MESSAGES = {
    "ACTIVE_CONVERSATION_EXISTS": "该幼儿已有进行中的会话",
    "CHILD_NOT_FOUND": "幼儿不存在",
    "DUCK_NOT_FOUND": "小鸭不存在",
}


def _error(status_code: int, code: str) -> APIError:
    return APIError(status_code, code, _ERROR_MESSAGES[code])


def _utc_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _database_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _child_future_roster_entries(db: Session, *, child_id: int, today: date) -> int:
    return db.scalar(
        select(func.count(models.DutyRoster.id)).where(
            models.DutyRoster.child_id == child_id,
            models.DutyRoster.date >= today.isoformat(),
        )
    ) or 0


def _child_has_active_conversation(db: Session, *, child_id: int) -> bool:
    return db.scalar(
        select(models.Conversation.id)
        .where(
            models.Conversation.child_id == child_id,
            models.Conversation.status == "active",
        )
        .limit(1)
    ) is not None


def _child_response(
    db: Session,
    *,
    child: models.Child,
    today: date,
    changed: bool,
) -> schemas.DeactivationResponse:
    return schemas.DeactivationResponse(
        id=child.id,
        kind="child",
        name=child.name,
        active=child.active,
        deactivated_at=_utc_datetime(child.deactivated_at),
        affected_future_roster_entries=_child_future_roster_entries(
            db,
            child_id=child.id,
            today=today,
        ),
        changed=changed,
    )


def _duck_response(
    db: Session,
    *,
    duck: models.Duck,
    changed: bool,
) -> schemas.DeactivationResponse:
    return schemas.DeactivationResponse(
        id=duck.id,
        kind="duck",
        name=duck.name,
        active=duck.active,
        deactivated_at=_utc_datetime(duck.deactivated_at),
        affected_future_roster_entries=0,
        changed=changed,
    )


def list_teacher_children(
    db: Session,
    *,
    include_inactive: bool,
    today: date,
) -> list[schemas.TeacherChildOut]:
    """Load every UI impact in one composed list query, not per child."""
    future_roster_entries = (
        select(func.count(models.DutyRoster.id))
        .where(
            models.DutyRoster.child_id == models.Child.id,
            models.DutyRoster.date >= today.isoformat(),
        )
        .correlate(models.Child)
        .scalar_subquery()
    )
    has_active_conversation = exists(
        select(models.Conversation.id).where(
            models.Conversation.child_id == models.Child.id,
            models.Conversation.status == "active",
        )
    )
    statement = select(
        models.Child,
        future_roster_entries.label("future_roster_entries"),
        has_active_conversation.label("has_active_conversation"),
    ).order_by(models.Child.id)
    if not include_inactive:
        statement = statement.where(models.Child.active.is_(True))
    rows = db.execute(statement).all()
    response = [
        schemas.TeacherChildOut(
            id=child.id,
            name=child.name,
            nickname=child.nickname,
            avatar=child.avatar,
            active=child.active,
            deactivated_at=_utc_datetime(child.deactivated_at),
            future_roster_entries=future_roster_entries or 0,
            has_active_conversation=bool(has_active_conversation),
        )
        for child, future_roster_entries, has_active_conversation in rows
    ]
    db.rollback()
    return response


def list_teacher_ducks(
    db: Session,
    *,
    include_inactive: bool,
) -> list[schemas.TeacherDuckOut]:
    """Load all duck history impact counts in one composed list query."""
    historical_feeding_log_count = (
        select(func.count(models.FeedingLog.id))
        .where(models.FeedingLog.duck_id == models.Duck.id)
        .correlate(models.Duck)
        .scalar_subquery()
    )
    statement = select(
        models.Duck,
        historical_feeding_log_count.label("historical_feeding_log_count"),
    ).order_by(models.Duck.id)
    if not include_inactive:
        statement = statement.where(models.Duck.active.is_(True))
    rows = db.execute(statement).all()
    response = [
        schemas.TeacherDuckOut(
            id=duck.id,
            name=duck.name,
            avatar=duck.avatar,
            status=duck.status,
            note=duck.note,
            active=duck.active,
            deactivated_at=_utc_datetime(duck.deactivated_at),
            historical_feeding_log_count=historical_feeding_log_count or 0,
        )
        for duck, historical_feeding_log_count in rows
    ]
    db.rollback()
    return response


def set_child_active(
    db: Session,
    *,
    child_id: int,
    active: bool,
    today: date,
    now: datetime,
) -> schemas.DeactivationResponse:
    """Conditionally switch child state without deleting history or racing new work."""
    desired_timestamp = None if active else _database_utc(now)
    active_conversation_exists = exists(
        select(models.Conversation.id).where(
            models.Conversation.child_id == child_id,
            models.Conversation.status == "active",
        )
    )
    while True:
        statement = (
            update(models.Child)
            .where(
                models.Child.id == child_id,
                models.Child.active.is_(not active),
            )
            .values(active=active, deactivated_at=desired_timestamp)
        )
        if not active:
            statement = statement.where(~active_conversation_exists)
        try:
            changed = db.execute(statement).rowcount == 1
            if changed:
                child = db.get(models.Child, child_id, populate_existing=True)
                assert child is not None
                response = _child_response(
                    db,
                    child=child,
                    today=today,
                    changed=True,
                )
                db.flush()
                db.commit()
                return response
        except Exception:
            db.rollback()
            raise

        # A conditional write that did not affect a row is never trusted as a
        # stale in-memory observation: classify it from a fresh transaction.
        db.rollback()
        child = db.get(models.Child, child_id, populate_existing=True)
        if child is None:
            db.rollback()
            raise _error(404, "CHILD_NOT_FOUND")
        if child.active is active:
            response = _child_response(
                db,
                child=child,
                today=today,
                changed=False,
            )
            db.rollback()
            return response
        if not active and _child_has_active_conversation(db, child_id=child_id):
            db.rollback()
            raise _error(409, "ACTIVE_CONVERSATION_EXISTS")
        # A competing writer changed state again between our predicate and
        # fresh read. Retry the same conditional transition from clean state.
        db.rollback()


def set_duck_active(
    db: Session,
    *,
    duck_id: int,
    active: bool,
    now: datetime,
) -> schemas.DeactivationResponse:
    """Conditionally switch duck state while retaining feeding/archive history."""
    desired_timestamp = None if active else _database_utc(now)
    while True:
        statement = (
            update(models.Duck)
            .where(
                models.Duck.id == duck_id,
                models.Duck.active.is_(not active),
            )
            .values(active=active, deactivated_at=desired_timestamp)
        )
        try:
            changed = db.execute(statement).rowcount == 1
            if changed:
                duck = db.get(models.Duck, duck_id, populate_existing=True)
                assert duck is not None
                response = _duck_response(db, duck=duck, changed=True)
                db.flush()
                db.commit()
                return response
        except Exception:
            db.rollback()
            raise

        db.rollback()
        duck = db.get(models.Duck, duck_id, populate_existing=True)
        if duck is None:
            db.rollback()
            raise _error(404, "DUCK_NOT_FOUND")
        if duck.active is active:
            response = _duck_response(db, duck=duck, changed=False)
            db.rollback()
            return response
        db.rollback()
