"""Read-side compatibility for schema-2 avatar strings retained in schema 3."""
from __future__ import annotations

from datetime import date
from pathlib import Path
import sqlite3

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.backend import schemas
from app.backend.schema_migrations import ensure_database_schema
from app.backend.services import deactivation, history, reviews, roster


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_2_FIXTURE = ROOT / "tests" / "fixtures" / "schema_2.sql"
ROSTER_DATE = date(2026, 9, 1)


def _upgrade_schema_two_with_avatars(
    database: Path,
    *,
    child_avatar: str,
    duck_avatar: str,
) -> Engine:
    with sqlite3.connect(database) as connection:
        connection.executescript(SCHEMA_2_FIXTURE.read_text(encoding="utf-8"))
        connection.execute(
            "UPDATE children SET avatar = ? WHERE id = 1",
            (child_avatar,),
        )
        connection.execute(
            "UPDATE ducks SET avatar = ? WHERE id = 1",
            (duck_avatar,),
        )
        connection.execute(
            "UPDATE assessments SET status = 'pending' WHERE id = 1"
        )

    engine = create_engine(
        f"sqlite:///{database}",
        connect_args={"check_same_thread": False},
    )
    ensure_database_schema(engine, db_mode="app")
    return engine


def _read_identity_avatars(db: Session) -> dict[str, str | None]:
    teacher_children = deactivation.list_teacher_children(
        db,
        include_inactive=True,
        today=ROSTER_DATE,
    )
    teacher_ducks = deactivation.list_teacher_ducks(
        db,
        include_inactive=True,
    )
    today_roster = roster.get_today_roster(db, today=ROSTER_DATE)
    review_queue = reviews.list_review_queue(db, queue="pending")
    review_detail = reviews.get_review_detail(db, conversation_id=1)
    history_page = history.list_conversation_history(
        db,
        limit=20,
        child_id=None,
        before_id=None,
    )
    search_page = history.search_conversations(
        db,
        schemas.ConversationSearchRequest(limit=20),
    )

    return {
        "teacher_children": teacher_children[0].avatar,
        "teacher_ducks": teacher_ducks[0].avatar,
        "today_roster": today_roster[0].avatar,
        "review_queue": review_queue[0].child.avatar,
        "review_detail": review_detail.child.avatar,
        "history": history_page.items[0].child.avatar,
        "search": search_page.items[0].child.avatar,
    }


def _stored_avatars(database: Path) -> tuple[str | None, str | None]:
    with sqlite3.connect(database) as connection:
        child_avatar = connection.execute(
            "SELECT avatar FROM children WHERE id = 1"
        ).fetchone()[0]
        duck_avatar = connection.execute(
            "SELECT avatar FROM ducks WHERE id = 1"
        ).fetchone()[0]
    return child_avatar, duck_avatar


def test_schema_two_legacy_avatars_remain_stored_but_every_identity_read_projects_null(
    tmp_path: Path,
):
    """Catches strict response validation leaking or rewriting retained legacy avatars."""
    child_avatar = "/api/media/avatars/not-a-canonical-uuid"
    duck_avatar = "legacy-duck.jpg"
    database = tmp_path / "legacy-avatars.db"
    engine = _upgrade_schema_two_with_avatars(
        database,
        child_avatar=child_avatar,
        duck_avatar=duck_avatar,
    )
    try:
        with Session(engine) as db:
            assert _read_identity_avatars(db) == {
                "teacher_children": None,
                "teacher_ducks": None,
                "today_roster": None,
                "review_queue": None,
                "review_detail": None,
                "history": None,
                "search": None,
            }
    finally:
        engine.dispose()

    assert _stored_avatars(database) == (child_avatar, duck_avatar)


def test_schema_two_canonical_avatar_urls_survive_upgrade_and_every_identity_read(
    tmp_path: Path,
):
    """Catches a legacy fallback that erases already-canonical avatar URLs."""
    child_avatar = (
        "/api/media/avatars/00000000-0000-4000-8000-000000000101"
    )
    duck_avatar = (
        "/api/media/avatars/00000000-0000-4000-8000-000000000102"
    )
    database = tmp_path / "canonical-avatars.db"
    engine = _upgrade_schema_two_with_avatars(
        database,
        child_avatar=child_avatar,
        duck_avatar=duck_avatar,
    )
    try:
        with Session(engine) as db:
            assert _read_identity_avatars(db) == {
                "teacher_children": child_avatar,
                "teacher_ducks": duck_avatar,
                "today_roster": child_avatar,
                "review_queue": child_avatar,
                "review_detail": child_avatar,
                "history": child_avatar,
                "search": child_avatar,
            }
    finally:
        engine.dispose()

    assert _stored_avatars(database) == (child_avatar, duck_avatar)
