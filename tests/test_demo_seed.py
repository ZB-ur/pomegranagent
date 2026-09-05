"""Deterministic, explicit full-demo seed acceptance tests."""
from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys

from PIL import Image
import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import Session

import conftest as test_runtime
from app.backend import models, schemas
from app.backend.analysis_worker import AnalysisWorker
from app.backend.services.avatar_media import load_avatar
from app.backend.services.history import search_conversations
from app.backend.services.reports import weekly_report


ANCHOR = date(2026, 9, 2)


def _seed(root: Path, *, anchor_date: date = ANCHOR):
    from app.backend.services.demo_seed import seed_full_demo

    return seed_full_demo(
        anchor_date=anchor_date,
        database_path=root / "demo.db",
        media_root=root / "media",
        log_path=root / "logs" / "app.log",
    )


def _scalar(connection, statement: str):
    return connection.scalar(text(statement))


def test_fixed_anchor_seed_has_exact_graph_and_stable_logical_hashes(
    tmp_path: Path,
) -> None:
    blocked_network_before = list(test_runtime.BLOCKED_NETWORK_ATTEMPTS)

    first = _seed(tmp_path / "first")
    second = _seed(tmp_path / "second")
    shifted = _seed(tmp_path / "shifted", anchor_date=ANCHOR + timedelta(days=1))

    assert first.media_sha256 == (
        "313c1c00a376081da5da91a0c15c171569531c50a774efb1582e8267afa3a6a7"
    )
    assert first.record_sha256 == (
        "f8fffaf9790258a0317ca87d594d3b9b38f45fb82c22cc4fd3df65ea85855827"
    )
    assert first.record_sha256 == second.record_sha256
    assert first.media_sha256 == second.media_sha256
    assert shifted.record_sha256 != first.record_sha256
    assert shifted.media_sha256 == first.media_sha256
    assert len(first.record_sha256) == len(first.media_sha256) == 64
    assert first.database_path.read_bytes()
    assert first.log_path.read_bytes() == b""
    assert test_runtime.BLOCKED_NETWORK_ATTEMPTS == blocked_network_before

    engine = create_engine(f"sqlite:///{first.database_path}")
    try:
        with engine.connect() as connection:
            assert _scalar(connection, "select version_num from alembic_version") == (
                "20260905_0003"
            )
            assert _scalar(connection, "select count(*) from children") == 8
            assert _scalar(connection, "select count(*) from children where active = 1") == 7
            assert _scalar(connection, "select count(*) from ducks") == 3
            assert _scalar(connection, "select count(*) from ducks where active = 1") == 2
            assert _scalar(connection, "select count(*) from assessment_dimensions") == 3
            assert _scalar(connection, "select count(*) from avatar_media") == 9
            assert _scalar(connection, "select count(*) from children where avatar is null") == 1
            assert _scalar(connection, "select count(*) from ducks where avatar is null") == 1
            assert _scalar(connection, "select count(*) from duty_rosters") == 10
            assert connection.scalars(
                text("select distinct date from duty_rosters order by date")
            ).all() == [
                "2026-08-26",
                "2026-09-01",
                "2026-09-02",
                "2026-09-03",
                "2026-09-09",
            ]
            assert _scalar(
                connection,
                "select count(*) from duty_rosters r "
                "join children c on c.id = r.child_id where c.active = 0",
            ) == 0

            assert _scalar(
                connection,
                "select count(*) from conversations where status = 'ended'",
            ) == 28
            status_counts = Counter(
                dict(
                    connection.execute(
                        text(
                            "select status, count(*) from analysis_jobs "
                            "group by status"
                        )
                    ).all()
                )
            )
            assert status_counts == {
                "succeeded": 16,
                "pending": 4,
                "processing": 4,
                "failed": 4,
            }
            review_counts = dict(
                connection.execute(
                    text("select status, count(*) from assessments group by status")
                ).all()
            )
            assert review_counts == {"pending": 5, "draft": 4, "confirmed": 7}
            assert _scalar(connection, "select count(*) from feeding_logs") == 16
            assert _scalar(connection, "select count(*) from emotion_logs") == 16
            assert _scalar(connection, "select count(*) from insight_notes") == 16
            assert _scalar(connection, "select count(*) from assessments") == 16
            assert _scalar(connection, "select count(*) from assessment_scores") == 48
            assert _scalar(
                connection,
                "select count(*) from assessments a "
                "left join assessment_scores s on s.assessment_id = a.id "
                "group by a.id having count(s.id) != 3",
            ) is None
            assert _scalar(
                connection,
                "select count(*) from conversations c "
                "join analysis_jobs j on j.conversation_id = c.id "
                "where c.frozen_last_message_id != j.frozen_last_message_id",
            ) == 0
            assert _scalar(
                connection,
                "select count(*) from conversations c "
                "left join messages m on m.id = c.frozen_last_message_id "
                "and m.conversation_id = c.id where m.id is null",
            ) == 0
            assert _scalar(
                connection,
                "select max(shared) from (select count(*) shared from conversations "
                "group by ended_at)",
            ) >= 3
            assert _scalar(
                connection,
                "select count(*) from messages where text like '%星河纸船%'",
            ) == 1
            for literal in ("%", "_", "\\"):
                assert connection.scalar(
                    text("select count(*) from messages where instr(text, :literal) > 0"),
                    {"literal": literal},
                ) >= 1

            for empty_table in (
                "teacher_credentials",
                "teacher_sessions",
                "chat_requests",
                "roster_requests",
            ):
                assert _scalar(connection, f"select count(*) from {empty_table}") == 0
            assert connection.execute(
                text(
                    "select id, failure_timestamps from teacher_pin_throttle "
                    "order by id"
                )
            ).all() == [(1, "[]")]

        with Session(engine) as session:
            avatars = session.scalars(
                select(models.AvatarMedia).order_by(models.AvatarMedia.id)
            ).all()
            assert len(avatars) == 9
            owners = {}
            for owner_type, rows in (
                ("child", session.scalars(select(models.Child)).all()),
                ("duck", session.scalars(select(models.Duck)).all()),
            ):
                for row in rows:
                    if row.avatar is not None:
                        owners[row.avatar.removeprefix("/api/media/avatars/")] = (
                            owner_type,
                            row.id,
                        )
            logical_media = []
            for avatar in avatars:
                blob = load_avatar(session, avatar.id, media_root=first.media_root)
                with Image.open(BytesIO(blob.content)) as decoded:
                    rgba = decoded.convert("RGBA")
                    assert rgba.size == (32, 32)
                    owner_type, owner_id = owners[avatar.id]
                    logical_media.append({
                        "id": avatar.id,
                        "owner_type": owner_type,
                        "owner_id": owner_id,
                        "mime_type": avatar.mime_type,
                        "width": avatar.width,
                        "height": avatar.height,
                        "rgba_sha256": sha256(rgba.tobytes()).hexdigest(),
                    })
            expected_media_hash = sha256(json.dumps(
                logical_media,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")).hexdigest()
            assert first.media_sha256 == expected_media_hash
    finally:
        engine.dispose()


def test_business_timestamps_are_shanghai_local_times_persisted_as_utc(
    tmp_path: Path,
) -> None:
    result = _seed(tmp_path / "utc")
    engine = create_engine(f"sqlite:///{result.database_path}")
    try:
        with Session(engine) as session:
            assert session.get(
                models.AvatarMedia,
                "70000000-0000-4000-8000-000000000001",
            ).created_at == datetime(2026, 9, 1, 16, 0)
            assert session.get(models.Child, 8).deactivated_at == datetime(
                2026, 9, 1, 16, 0
            )
            assert session.get(models.Duck, 3).deactivated_at == datetime(
                2026, 9, 1, 16, 0
            )

            conversation = session.get(models.Conversation, 13)
            assert conversation.started_at == datetime(2026, 9, 2, 1, 40)
            assert conversation.ended_at == datetime(2026, 9, 2, 1, 55)
            assert session.get(models.Message, 131).created_at == datetime(
                2026, 9, 2, 1, 41
            )
            assert session.get(models.Message, 132).created_at == datetime(
                2026, 9, 2, 1, 42
            )

            job = session.get(models.AnalysisJob, 113)
            assert job.available_at == datetime(2026, 9, 2, 1, 55)
            assert job.started_at == datetime(2026, 9, 2, 1, 55, 1)
            assert job.finished_at == datetime(2026, 9, 2, 1, 55, 4)
            assert job.created_at == datetime(2026, 9, 2, 1, 55)
            assert job.updated_at == datetime(2026, 9, 2, 1, 55, 4)

            assert session.get(models.FeedingLog, 13).occurred_at == datetime(
                2026, 9, 2, 1, 53
            )
            assert session.get(models.EmotionLog, 13).occurred_at == datetime(
                2026, 9, 2, 1, 54
            )
            assert session.get(models.InsightNote, 13).created_at == datetime(
                2026, 9, 2, 1, 55, 2
            )
    finally:
        engine.dispose()


def test_seeded_reports_growth_search_and_worker_are_demo_ready(tmp_path: Path) -> None:
    result = _seed(tmp_path / "readable")
    engine = create_engine(f"sqlite:///{result.database_path}")
    provider_calls: list[str] = []

    class ProviderTripwire:
        def extract_info(self, _transcript: str):
            provider_calls.append("extract")
            raise AssertionError("seeded jobs must not call a provider")

        def assess_conversation(self, _transcript: str, _dimensions: list[dict]):
            provider_calls.append("assess")
            raise AssertionError("seeded jobs must not call a provider")

    try:
        with Session(engine) as session:
            report = weekly_report(session, date(2026, 8, 31), date(2026, 9, 7))
            assert report.completed_conversations == 13
            assert report.participating_children == 7
            assert report.confirmed_reviews == 4
            assert report.failed_analyses == 4
            assert report.pending_reviews_total == 9
            assert session.get(models.Conversation, 9).date == "2026-08-30"
            assert session.get(models.Conversation, 20).date == "2026-09-07"

            from app.backend.main import growth_analysis

            growth = growth_analysis(child_id=1, db=session, _teacher=None)
            series_by_key = {
                dimension["key"]: dimension["points"]
                for dimension in growth["dimensions"]
            }
            assert growth["child_id"] == 1
            assert series_by_key == {
                "language": [
                    {"date": "2026-08-12", "score": 2},
                    {"date": "2026-08-19", "score": 3},
                    {"date": "2026-08-26", "score": 4},
                    {"date": "2026-09-02", "score": 5},
                ],
                "empathy": [
                    {"date": "2026-08-12", "score": 2},
                    {"date": "2026-08-19", "score": 4},
                    {"date": "2026-08-26", "score": 4},
                    {"date": "2026-09-02", "score": 5},
                ],
                "diligence": [
                    {"date": "2026-08-12", "score": 2},
                    {"date": "2026-08-19", "score": 2},
                    {"date": "2026-08-26", "score": 4},
                    {"date": "2026-09-02", "score": 4},
                ],
            }

            ordinary = search_conversations(
                session,
                schemas.ConversationSearchRequest(keyword="星河纸船", limit=10),
            )
            assert len(ordinary.items) == 1
            tied_desc = search_conversations(
                session,
                schemas.ConversationSearchRequest(
                    date_from=date(2026, 8, 3),
                    date_to=date(2026, 8, 3),
                    sort="completed_desc",
                    limit=10,
                ),
            )
            tied_asc = search_conversations(
                session,
                schemas.ConversationSearchRequest(
                    date_from=date(2026, 8, 3),
                    date_to=date(2026, 8, 3),
                    sort="completed_asc",
                    limit=10,
                ),
            )
            assert [item.id for item in tied_desc.items] == [3, 2, 1]
            assert [item.id for item in tied_asc.items] == [1, 2, 3]
            for literal in ("%", "_", "\\"):
                literal_page = search_conversations(
                    session,
                    schemas.ConversationSearchRequest(keyword=literal, limit=10),
                )
                assert literal_page.items

        from app.backend.services.analysis import recover_expired_jobs

        with Session(engine) as recovery_session:
            assert recover_expired_jobs(
                recovery_session,
                now=datetime(2026, 9, 2, tzinfo=timezone.utc),
            ) == 0
        def session_factory():
            return Session(engine)

        worker = AnalysisWorker(
            session_factory=session_factory,
            analyzer=ProviderTripwire(),
            clock=lambda: datetime(2026, 9, 2, tzinfo=timezone.utc),
        )
        assert worker.run_once() is False
        assert provider_calls == []
    finally:
        engine.dispose()


@pytest.mark.parametrize("occupied", ["database", "wal", "shm", "media", "log"])
def test_seed_without_force_rejects_every_existing_resource_before_install(
    tmp_path: Path,
    occupied: str,
) -> None:
    from app.backend.services.demo_seed import DemoSeedSafetyError, seed_full_demo

    root = tmp_path / occupied
    database = root / "demo.db"
    media = root / "media"
    log = root / "logs" / "app.log"
    selected = {
        "database": database,
        "wal": Path(f"{database}-wal"),
        "shm": Path(f"{database}-shm"),
        "media": media,
        "log": log,
    }[occupied]
    selected.parent.mkdir(parents=True)
    if occupied == "media":
        selected.mkdir()
    else:
        selected.write_bytes(b"retained-resource")

    with pytest.raises(DemoSeedSafetyError, match="not empty"):
        seed_full_demo(
            anchor_date=ANCHOR,
            database_path=database,
            media_root=media,
            log_path=log,
        )

    if occupied == "media":
        assert selected.is_dir() and list(selected.iterdir()) == []
    else:
        assert selected.read_bytes() == b"retained-resource"
    if occupied != "database":
        assert not database.exists()


def test_seed_rejects_symlinks_hardlinks_nonregular_and_overlapping_roots(
    tmp_path: Path,
) -> None:
    from app.backend.services.demo_seed import DemoSeedSafetyError, seed_full_demo

    def invoke(root: Path, *, database: Path | None = None, media: Path | None = None):
        return seed_full_demo(
            anchor_date=ANCHOR,
            database_path=database or root / "demo.db",
            media_root=media or root / "media",
            log_path=root / "logs" / "app.log",
        )

    symlink_root = tmp_path / "symlink"
    symlink_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (symlink_root / "media").symlink_to(outside, target_is_directory=True)
    with pytest.raises(DemoSeedSafetyError, match="symlink"):
        invoke(symlink_root)

    hardlink_root = tmp_path / "hardlink"
    hardlink_root.mkdir()
    retained = hardlink_root / "retained.db"
    retained.write_bytes(b"retained")
    os.link(retained, hardlink_root / "demo.db")
    with pytest.raises(DemoSeedSafetyError, match="regular unlinked"):
        invoke(hardlink_root)

    fifo_root = tmp_path / "fifo"
    (fifo_root / "logs").mkdir(parents=True)
    os.mkfifo(fifo_root / "logs" / "app.log")
    with pytest.raises(DemoSeedSafetyError, match="regular unlinked"):
        invoke(fifo_root)

    overlap_root = tmp_path / "overlap"
    with pytest.raises(DemoSeedSafetyError, match="overlap"):
        invoke(
            overlap_root,
            database=overlap_root / "media" / "demo.db",
            media=overlap_root / "media",
        )

    with pytest.raises(DemoSeedSafetyError, match="too broad"):
        invoke(tmp_path / "broad", media=Path("/"))
    with pytest.raises(DemoSeedSafetyError, match="too broad"):
        invoke(tmp_path / "project-root", media=test_runtime.ROOT)


def test_force_and_archive_options_are_fail_closed(tmp_path: Path) -> None:
    from app.backend.services.demo_seed import DemoSeedSafetyError, seed_full_demo

    root = tmp_path / "force-options"
    arguments = {
        "anchor_date": ANCHOR,
        "database_path": root / "demo.db",
        "media_root": root / "media",
        "log_path": root / "logs" / "app.log",
    }
    with pytest.raises(DemoSeedSafetyError, match="requires an explicit archive"):
        seed_full_demo(**arguments, force=True)
    with pytest.raises(DemoSeedSafetyError, match="requires --force"):
        seed_full_demo(**arguments, archive_directory=tmp_path / "archive-only")
    with pytest.raises(DemoSeedSafetyError, match="overlaps"):
        seed_full_demo(
            **arguments,
            force=True,
            archive_directory=root / "media" / "archive",
        )


@pytest.mark.parametrize("collision", ["media", "log", "archive"])
def test_seed_rejects_the_implicit_lock_path_as_a_reserved_resource(
    tmp_path: Path,
    collision: str,
) -> None:
    from app.backend.services.demo_seed import DemoSeedSafetyError, seed_full_demo

    root = tmp_path / "reserved-lock"
    database = root / "demo.db"
    lock_path = database.with_name(f".{database.name}.full-demo.lock")
    arguments = {
        "anchor_date": ANCHOR,
        "database_path": database,
        "media_root": root / "media",
        "log_path": root / "logs" / "app.log",
        "force": True,
        "archive_directory": tmp_path / "archives" / "reserved-lock",
    }
    target_by_collision = {
        "media": "media_root",
        "log": "log_path",
        "archive": "archive_directory",
    }
    arguments[target_by_collision[collision]] = lock_path

    with pytest.raises(DemoSeedSafetyError, match="overlap"):
        seed_full_demo(**arguments)

    assert not database.exists()
    assert not lock_path.exists()
    assert not arguments["archive_directory"].exists()


def test_all_demo_rows_roll_back_when_a_late_insert_fails(tmp_path: Path) -> None:
    from app.backend.schema_migrations import ensure_database_schema
    from app.backend.services.demo_seed import (
        _load_fixture,
        _stage_avatars,
        populate_full_demo_database,
    )

    database = tmp_path / "transaction.db"
    media = tmp_path / "media"
    engine = create_engine(f"sqlite:///{database}")
    ensure_database_schema(engine, "app")
    avatars = _stage_avatars(media, _load_fixture())

    @event.listens_for(engine, "before_cursor_execute")
    def fail_message_insert(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("INSERT INTO MESSAGES"):
            raise RuntimeError("late deterministic insert failure")

    try:
        with pytest.raises(RuntimeError, match="late deterministic insert failure"):
            populate_full_demo_database(
                engine,
                anchor_date=ANCHOR,
                fixture=_load_fixture(),
                avatars=avatars,
            )
        with engine.connect() as connection:
            for table in (
                "assessment_dimensions",
                "avatar_media",
                "children",
                "ducks",
                "duty_rosters",
                "conversations",
                "messages",
                "analysis_jobs",
            ):
                assert _scalar(connection, f"select count(*) from {table}") == 0
    finally:
        event.remove(engine, "before_cursor_execute", fail_message_insert)
        engine.dispose()


def _old_bundle(root: Path) -> tuple[Path, Path, Path]:
    database = root / "demo.db"
    media = root / "media"
    log = root / "logs" / "app.log"
    database.parent.mkdir(parents=True)
    database.write_bytes(b"old-database")
    Path(f"{database}-wal").write_bytes(b"old-wal")
    Path(f"{database}-shm").write_bytes(b"old-shm")
    media.mkdir()
    (media / "old-avatar.webp").write_bytes(b"old-media")
    log.parent.mkdir()
    log.write_bytes(b"old-log")
    return database, media, log


def test_force_archives_complete_old_bundle_and_installs_valid_new_bundle(
    tmp_path: Path,
) -> None:
    from app.backend.services.demo_seed import seed_full_demo

    database, media, log = _old_bundle(tmp_path / "force")
    archive = tmp_path / "archives" / "full-demo-before"

    result = seed_full_demo(
        anchor_date=ANCHOR,
        database_path=database,
        media_root=media,
        log_path=log,
        force=True,
        archive_directory=archive,
    )

    assert result.archive_directory == archive.resolve()
    assert (archive / "database" / "demo.db").read_bytes() == b"old-database"
    assert (archive / "database" / "demo.db-wal").read_bytes() == b"old-wal"
    assert (archive / "database" / "demo.db-shm").read_bytes() == b"old-shm"
    assert (archive / "media" / "old-avatar.webp").read_bytes() == b"old-media"
    assert (archive / "log" / "app.log").read_bytes() == b"old-log"
    assert database.read_bytes() != b"old-database"
    assert not Path(f"{database}-wal").exists()
    assert not Path(f"{database}-shm").exists()
    assert len(list(media.glob("*.webp"))) == 9
    assert log.read_bytes() == b""


def test_force_stages_before_archive_and_restores_every_old_resource_on_install_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.backend.services import demo_seed

    database, media, log = _old_bundle(tmp_path / "restore")
    archive = tmp_path / "archives" / "restore-point"
    original_replace = demo_seed._replace_path
    failed = False

    def fail_once_when_installing_media(source: Path, target: Path) -> None:
        nonlocal failed
        if target == media.resolve() and not failed:
            failed = True
            raise OSError("injected media install failure")
        original_replace(source, target)

    monkeypatch.setattr(demo_seed, "_replace_path", fail_once_when_installing_media)

    with pytest.raises(demo_seed.DemoSeedInstallError, match="restored"):
        demo_seed.seed_full_demo(
            anchor_date=ANCHOR,
            database_path=database,
            media_root=media,
            log_path=log,
            force=True,
            archive_directory=archive,
        )

    assert database.read_bytes() == b"old-database"
    assert Path(f"{database}-wal").read_bytes() == b"old-wal"
    assert Path(f"{database}-shm").read_bytes() == b"old-shm"
    assert (media / "old-avatar.webp").read_bytes() == b"old-media"
    assert log.read_bytes() == b"old-log"
    assert not archive.exists()


def test_force_removes_fresh_archive_after_archive_failure_restores_old_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.backend.services import demo_seed

    database, media, log = _old_bundle(tmp_path / "archive-restore")
    archive = tmp_path / "archives" / "archive-failure"
    original_replace = demo_seed._replace_path
    failed = False

    def fail_once_when_archiving_media(source: Path, target: Path) -> None:
        nonlocal failed
        if source == media.resolve() and target == archive.resolve() / "media" and not failed:
            failed = True
            raise OSError("injected media archive failure")
        original_replace(source, target)

    monkeypatch.setattr(demo_seed, "_replace_path", fail_once_when_archiving_media)

    with pytest.raises(demo_seed.DemoSeedInstallError, match="restored"):
        demo_seed.seed_full_demo(
            anchor_date=ANCHOR,
            database_path=database,
            media_root=media,
            log_path=log,
            force=True,
            archive_directory=archive,
        )

    assert database.read_bytes() == b"old-database"
    assert Path(f"{database}-wal").read_bytes() == b"old-wal"
    assert Path(f"{database}-shm").read_bytes() == b"old-shm"
    assert (media / "old-avatar.webp").read_bytes() == b"old-media"
    assert log.read_bytes() == b"old-log"
    assert not archive.exists()


def test_force_does_not_archive_any_old_resource_when_staging_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.backend.services import demo_seed

    database, media, log = _old_bundle(tmp_path / "stage-first")
    archive = tmp_path / "archives" / "must-not-exist"

    def fail_staging(_media_root: Path, _fixture: dict):
        raise demo_seed.DemoSeedError("injected staging failure")

    monkeypatch.setattr(demo_seed, "_stage_avatars", fail_staging)
    with pytest.raises(demo_seed.DemoSeedError, match="staging failure"):
        demo_seed.seed_full_demo(
            anchor_date=ANCHOR,
            database_path=database,
            media_root=media,
            log_path=log,
            force=True,
            archive_directory=archive,
        )

    assert database.read_bytes() == b"old-database"
    assert Path(f"{database}-wal").read_bytes() == b"old-wal"
    assert Path(f"{database}-shm").read_bytes() == b"old-shm"
    assert (media / "old-avatar.webp").read_bytes() == b"old-media"
    assert log.read_bytes() == b"old-log"
    assert not archive.exists()


def test_concurrent_seed_attempts_have_exactly_one_success(tmp_path: Path) -> None:
    root = tmp_path / "concurrent"

    def attempt():
        try:
            return "success", _seed(root)
        except Exception as exc:  # Both attempts are observed and classified below.
            return "failure", exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _index: attempt(), range(2)))

    assert [status for status, _value in outcomes].count("success") == 1
    assert [status for status, _value in outcomes].count("failure") == 1
    failure = next(value for status, value in outcomes if status == "failure")
    from app.backend.services.demo_seed import DemoSeedSafetyError

    assert isinstance(failure, DemoSeedSafetyError)


def test_full_demo_cli_requires_explicit_targets_and_prints_hashes(tmp_path: Path) -> None:
    database = tmp_path / "cli" / "demo.db"
    media = tmp_path / "cli" / "media"
    log = tmp_path / "cli" / "logs" / "app.log"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/seed_demo_database.py",
            "full-demo",
            "--anchor-date",
            ANCHOR.isoformat(),
            "--database",
            str(database),
            "--media-root",
            str(media),
            "--log-path",
            str(log),
        ],
        cwd=test_runtime.ROOT,
        env={**os.environ, "PYTHON_DOTENV_DISABLED": "1"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["database_path"] == str(database.resolve())
    assert payload["media_root"] == str(media.resolve())
    assert payload["log_path"] == str(log.resolve())
    assert payload["archive_directory"] is None
    assert len(payload["record_sha256"]) == len(payload["media_sha256"]) == 64

    missing_targets = subprocess.run(
        [sys.executable, "scripts/seed_demo_database.py", "full-demo", "--anchor-date", ANCHOR.isoformat()],
        cwd=test_runtime.ROOT,
        env={**os.environ, "PYTHON_DOTENV_DISABLED": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing_targets.returncode == 2


def test_legacy_assessment_helper_delegates_only_with_explicit_bundle_targets(
    tmp_path: Path,
) -> None:
    database = tmp_path / "compat" / "demo.db"
    media = tmp_path / "compat" / "media"
    log = tmp_path / "compat" / "logs" / "app.log"
    completed = subprocess.run(
        [
            sys.executable,
            "tests/seed_demo_assessments.py",
            "--anchor-date",
            ANCHOR.isoformat(),
            "--database",
            str(database),
            "--media-root",
            str(media),
            "--log-path",
            str(log),
        ],
        cwd=test_runtime.ROOT,
        env={**os.environ, "PYTHON_DOTENV_DISABLED": "1"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["database_path"] == str(database.resolve())
    engine = create_engine(f"sqlite:///{database}")
    try:
        with engine.connect() as connection:
            assert _scalar(connection, "select count(*) from assessments") == 16
    finally:
        engine.dispose()
