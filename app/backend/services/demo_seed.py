"""Deterministic, offline construction of the explicit full-demo bundle."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
from typing import Iterator
from zoneinfo import ZoneInfo

from PIL import Image
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session

from .. import models
from ..database import Base
from ..schema_migrations import ensure_database_schema
from .avatar_media import close_pinned_media_roots, load_avatar


FULL_DEMO_PATH = Path(__file__).resolve().parents[1] / "demo_data" / "full_demo.json"
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_AVATAR_PREFIX = "/api/media/avatars/"
_RESOURCE_LABELS = ("database", "database-wal", "database-shm", "media", "log")
_BUSINESS_TIMEZONE = ZoneInfo("Asia/Shanghai")


class DemoSeedError(RuntimeError):
    """Base error for an explicit demo seed that did not install."""


class DemoSeedSafetyError(DemoSeedError):
    """The requested target bundle is unsafe or already populated."""


class DemoSeedInstallError(DemoSeedError):
    """A staged bundle could not be installed safely."""


@dataclass(frozen=True)
class DemoSeedResult:
    database_path: Path
    media_root: Path
    log_path: Path
    archive_directory: Path | None
    record_sha256: str
    media_sha256: str

    @property
    def record_hash(self) -> str:
        return self.record_sha256

    @property
    def media_hash(self) -> str:
        return self.media_sha256


@dataclass(frozen=True)
class _AvatarArtifact:
    media_id: str
    owner_type: str
    owner_id: int
    file_name: str
    width: int
    height: int
    content: bytes
    content_sha256: str
    rgba_sha256: str


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _load_fixture(path: Path = FULL_DEMO_PATH) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise DemoSeedError("full-demo fixture is unavailable or invalid") from exc
    if not isinstance(payload, dict) or set(payload) != {
        "format",
        "future_lease_at",
        "dimensions",
        "children",
        "ducks",
        "avatars",
        "rosters",
        "conversations",
    }:
        raise DemoSeedError("full-demo fixture has an unsupported shape")
    if payload["format"] != "pomegranagent-full-demo-v1":
        raise DemoSeedError("full-demo fixture has an unsupported format")
    if tuple(map(len, (
        payload["children"],
        payload["ducks"],
        payload["dimensions"],
        payload["avatars"],
        payload["rosters"],
        payload["conversations"],
    ))) != (8, 3, 3, 9, 10, 28):
        raise DemoSeedError("full-demo fixture violates the frozen entity graph")
    statuses = [item.get("analysis_status") for item in payload["conversations"]]
    if {name: statuses.count(name) for name in set(statuses)} != {
        "succeeded": 16,
        "pending": 4,
        "processing": 4,
        "failed": 4,
    }:
        raise DemoSeedError("full-demo fixture violates analysis status counts")
    reviews = [
        item.get("review_status")
        for item in payload["conversations"]
        if item.get("analysis_status") == "succeeded"
    ]
    if {name: reviews.count(name) for name in set(reviews)} != {
        "pending": 5,
        "draft": 4,
        "confirmed": 7,
    }:
        raise DemoSeedError("full-demo fixture violates review status counts")
    return payload


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(Path(path).expanduser())))


def _exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _reject_symlink_components(path: Path) -> None:
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current /= component
        try:
            entry = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(entry.st_mode):
            raise DemoSeedSafetyError(f"symlink path is not allowed: {current}")


def _ensure_parent(path: Path) -> None:
    _reject_symlink_components(path.parent)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    _reject_symlink_components(path.parent)
    parent_stat = path.parent.stat()
    if not stat.S_ISDIR(parent_stat.st_mode) or parent_stat.st_uid != os.geteuid():
        raise DemoSeedSafetyError(f"target parent is not owner controlled: {path.parent}")


def _overlaps(first: Path, second: Path) -> bool:
    return first == second or first in second.parents or second in first.parents


def _seed_lock_path(database_path: Path) -> Path:
    return database_path.with_name(f".{database_path.name}.full-demo.lock")


def _validate_target_paths(
    *,
    database_path: Path,
    media_root: Path,
    log_path: Path,
    archive_directory: Path | None,
    force: bool,
) -> None:
    if database_path.name in {"", ".", ".."} or log_path.name in {"", ".", ".."}:
        raise DemoSeedSafetyError("database and log targets must be files")
    broad_roots = {
        Path("/"),
        Path.home().resolve(),
        _PROJECT_ROOT,
        Path("/tmp").resolve(),
        Path("/private/tmp").resolve(),
        Path(tempfile.gettempdir()).resolve(),
    }
    for label, candidate in (
        ("media", media_root),
        ("archive", archive_directory),
    ):
        if candidate is None:
            continue
        if candidate in broad_roots or len(candidate.parts) < 3:
            raise DemoSeedSafetyError(f"{label} target is too broad")
    targets = [database_path, Path(f"{database_path}-wal"), Path(f"{database_path}-shm"), media_root, log_path]
    protected_targets = [*targets, _seed_lock_path(database_path)]
    if len(set(protected_targets)) != len(protected_targets):
        raise DemoSeedSafetyError("demo resource targets overlap")
    for index, first in enumerate(protected_targets):
        for second in protected_targets[index + 1:]:
            if _overlaps(first, second):
                raise DemoSeedSafetyError("demo resource targets overlap")
    if force and archive_directory is None:
        raise DemoSeedSafetyError("--force requires an explicit archive directory")
    if not force and archive_directory is not None:
        raise DemoSeedSafetyError("archive directory requires --force")
    if archive_directory is not None:
        if any(_overlaps(archive_directory, target) for target in protected_targets):
            raise DemoSeedSafetyError("archive directory overlaps demo resources")
        if _exists(archive_directory):
            raise DemoSeedSafetyError("archive directory must not already exist")
    for target in [*protected_targets, *([archive_directory] if archive_directory else [])]:
        _reject_symlink_components(target)


def _assert_regular_unlinked_file(path: Path) -> None:
    entry = path.lstat()
    if not stat.S_ISREG(entry.st_mode) or entry.st_nlink != 1:
        raise DemoSeedSafetyError(f"resource must be one regular unlinked file: {path}")


def _assert_safe_existing_resource(path: Path, *, directory: bool) -> None:
    if not _exists(path):
        return
    entry = path.lstat()
    if directory:
        if not stat.S_ISDIR(entry.st_mode):
            raise DemoSeedSafetyError(f"media target must be a directory: {path}")
        for child in path.rglob("*"):
            child_entry = child.lstat()
            if stat.S_ISDIR(child_entry.st_mode):
                continue
            if not stat.S_ISREG(child_entry.st_mode) or child_entry.st_nlink != 1:
                raise DemoSeedSafetyError(f"unsafe media entry: {child}")
    else:
        _assert_regular_unlinked_file(path)


def _resource_paths(database_path: Path, media_root: Path, log_path: Path) -> tuple[Path, ...]:
    return (
        database_path,
        Path(f"{database_path}-wal"),
        Path(f"{database_path}-shm"),
        media_root,
        log_path,
    )


def _resource_digest(path: Path) -> str:
    """Hash one already-validated file/tree without following links."""

    entry = path.lstat()
    if stat.S_ISREG(entry.st_mode):
        return sha256(path.read_bytes()).hexdigest()
    if not stat.S_ISDIR(entry.st_mode):
        raise DemoSeedSafetyError(f"resource cannot be hashed safely: {path}")
    rows: list[dict[str, object]] = []
    for child in sorted(path.rglob("*"), key=lambda item: item.relative_to(path).as_posix()):
        child_entry = child.lstat()
        relative = child.relative_to(path).as_posix()
        if stat.S_ISDIR(child_entry.st_mode):
            rows.append({"path": relative, "kind": "directory"})
        elif stat.S_ISREG(child_entry.st_mode) and child_entry.st_nlink == 1:
            rows.append({
                "path": relative,
                "kind": "file",
                "size": child_entry.st_size,
                "sha256": sha256(child.read_bytes()).hexdigest(),
            })
        else:
            raise DemoSeedSafetyError(f"resource cannot be hashed safely: {child}")
    return sha256(_canonical_json(rows)).hexdigest()


def _bundle_snapshot(
    database_path: Path,
    media_root: Path,
    log_path: Path,
) -> dict[str, str]:
    return {
        label: _resource_digest(resource)
        for label, resource in zip(
            _RESOURCE_LABELS,
            _resource_paths(database_path, media_root, log_path),
            strict=True,
        )
        if _exists(resource)
    }


def _validate_existing_bundle(
    database_path: Path,
    media_root: Path,
    log_path: Path,
    *,
    force: bool,
) -> None:
    resources = _resource_paths(database_path, media_root, log_path)
    for index, resource in enumerate(resources):
        _assert_safe_existing_resource(resource, directory=index == 3)
    if not force and any(_exists(resource) for resource in resources):
        raise DemoSeedSafetyError("demo target bundle is not empty; use --force with an archive")


def _replace_path(source: Path, target: Path) -> None:
    """Single filesystem rename boundary shared by install and tested recovery."""

    os.replace(source, target)


def _archive_destinations(
    *,
    archive_directory: Path,
    database_path: Path,
    media_root: Path,
    log_path: Path,
) -> tuple[Path, ...]:
    del media_root
    return (
        archive_directory / "database" / database_path.name,
        archive_directory / "database" / f"{database_path.name}-wal",
        archive_directory / "database" / f"{database_path.name}-shm",
        archive_directory / "media",
        archive_directory / "log" / log_path.name,
    )


def _restore_archived_resources(
    moved: list[tuple[str, Path, Path]],
    *,
    expected: dict[str, str],
) -> bool:
    restored = True
    for _label, original, archived in reversed(moved):
        try:
            _ensure_parent(original)
            _replace_path(archived, original)
        except Exception:
            restored = False
    if not restored:
        return False
    for label, original, _archived in moved:
        try:
            if _resource_digest(original) != expected[label]:
                return False
        except Exception:
            return False
    return True


def _remove_fresh_archive_directory(archive_directory: Path) -> bool:
    """Remove only the known-empty directories created for this invocation."""

    try:
        for child in (archive_directory / "database", archive_directory / "log"):
            try:
                child.rmdir()
            except FileNotFoundError:
                pass
        archive_directory.rmdir()
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return True


def _archive_existing_bundle(
    *,
    database_path: Path,
    media_root: Path,
    log_path: Path,
    archive_directory: Path,
    expected: dict[str, str],
) -> list[tuple[str, Path, Path]]:
    _ensure_parent(archive_directory)
    try:
        archive_directory.mkdir(mode=0o700)
        (archive_directory / "database").mkdir(mode=0o700)
        (archive_directory / "log").mkdir(mode=0o700)
    except OSError as exc:
        raise DemoSeedInstallError("could not create the explicit archive directory") from exc

    resources = _resource_paths(database_path, media_root, log_path)
    destinations = _archive_destinations(
        archive_directory=archive_directory,
        database_path=database_path,
        media_root=media_root,
        log_path=log_path,
    )
    moved: list[tuple[str, Path, Path]] = []
    try:
        for label, source, destination in zip(
            _RESOURCE_LABELS,
            resources,
            destinations,
            strict=True,
        ):
            if not _exists(source):
                continue
            _ensure_parent(destination)
            _replace_path(source, destination)
            moved.append((label, source, destination))
            if _resource_digest(destination) != expected[label]:
                raise DemoSeedInstallError("archived resource hash verification failed")
        return moved
    except Exception as exc:
        if not _restore_archived_resources(moved, expected=expected):
            raise DemoSeedInstallError(
                "archive failed and the old demo bundle could not be fully restored"
            ) from exc
        if not _remove_fresh_archive_directory(archive_directory):
            raise DemoSeedInstallError(
                "archive failed; the old demo bundle was restored but the fresh "
                "archive directory could not be removed"
            ) from exc
        raise DemoSeedInstallError(
            "archive failed; the old demo bundle was restored"
        ) from exc


@contextmanager
def _exclusive_seed_lock(database_path: Path) -> Iterator[None]:
    _ensure_parent(database_path)
    lock_path = _seed_lock_path(database_path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except FileExistsError:
        raise DemoSeedSafetyError("another full-demo seed is already running") from None
    identity: tuple[int, int] | None = None
    try:
        current = os.fstat(descriptor)
        identity = (current.st_dev, current.st_ino)
        os.write(descriptor, f"{os.getpid()}\n".encode("ascii"))
        os.fsync(descriptor)
        yield
    finally:
        os.close(descriptor)
        try:
            current = lock_path.lstat()
            if identity == (current.st_dev, current.st_ino) and stat.S_ISREG(current.st_mode):
                lock_path.unlink()
        except FileNotFoundError:
            pass


def _avatar_pixels(index: int, primary: list[int], accent: list[int]) -> bytes:
    if (
        len(primary) != 4
        or len(accent) != 4
        or any(type(channel) is not int or not 0 <= channel <= 255 for channel in [*primary, *accent])
    ):
        raise DemoSeedError("avatar palette is invalid")
    pixels = bytearray()
    for y in range(32):
        for x in range(32):
            use_accent = ((x // 4) + (y // 4) + index) % 3 == 0
            pixels.extend(accent if use_accent else primary)
    return bytes(pixels)


def _stage_avatars(media_root: Path, fixture: dict) -> tuple[_AvatarArtifact, ...]:
    media_root.mkdir(mode=0o700)
    artifacts: list[_AvatarArtifact] = []
    for index, spec in enumerate(fixture["avatars"]):
        pixels = _avatar_pixels(index, spec["primary"], spec["accent"])
        image = Image.frombytes("RGBA", (32, 32), pixels)
        encoded = BytesIO()
        image.save(
            encoded,
            format="WEBP",
            lossless=True,
            quality=100,
            method=6,
            exact=True,
            exif=b"",
            icc_profile=None,
            xmp=b"",
        )
        content = encoded.getvalue()
        file_name = f"{spec['id']}.webp"
        target = media_root / file_name
        target.write_bytes(content)
        target.chmod(0o600)
        artifacts.append(_AvatarArtifact(
            media_id=spec["id"],
            owner_type=spec["owner_type"],
            owner_id=spec["owner_id"],
            file_name=file_name,
            width=32,
            height=32,
            content=content,
            content_sha256=sha256(content).hexdigest(),
            rgba_sha256=sha256(pixels).hexdigest(),
        ))
    return tuple(artifacts)


def _at(anchor_date: date, day_offset: int, clock: str) -> datetime:
    local_time = datetime.combine(
        anchor_date + timedelta(days=day_offset),
        time.fromisoformat(clock),
        tzinfo=_BUSINESS_TIMEZONE,
    )
    return local_time.astimezone(timezone.utc).replace(tzinfo=None)


def _insert_full_demo_rows(
    db: Session,
    *,
    anchor_date: date,
    fixture: dict,
    avatars: tuple[_AvatarArtifact, ...],
) -> None:
    avatar_by_id = {avatar.media_id: avatar for avatar in avatars}
    anchor_midnight = _at(anchor_date, 0, time.min.isoformat())
    for dimension in fixture["dimensions"]:
        db.add(models.AssessmentDimension(
            id=dimension["id"],
            key=dimension["key"],
            name=dimension["name"],
            enabled=True,
            weight=1.0,
            description=dimension["description"],
        ))
    for avatar in avatars:
        db.add(models.AvatarMedia(
            id=avatar.media_id,
            file_name=avatar.file_name,
            mime_type="image/webp",
            width=avatar.width,
            height=avatar.height,
            size_bytes=len(avatar.content),
            sha256=avatar.content_sha256,
            created_at=anchor_midnight,
        ))
    for child in fixture["children"]:
        avatar_id = child["avatar_id"]
        if avatar_id is not None and avatar_id not in avatar_by_id:
            raise DemoSeedError("child avatar reference is invalid")
        db.add(models.Child(
            id=child["id"],
            name=child["name"],
            nickname=child["nickname"],
            avatar=f"{_AVATAR_PREFIX}{avatar_id}" if avatar_id else None,
            active=child["active"],
            deactivated_at=None if child["active"] else anchor_midnight,
        ))
    for duck in fixture["ducks"]:
        avatar_id = duck["avatar_id"]
        if avatar_id is not None and avatar_id not in avatar_by_id:
            raise DemoSeedError("duck avatar reference is invalid")
        db.add(models.Duck(
            id=duck["id"],
            name=duck["name"],
            avatar=f"{_AVATAR_PREFIX}{avatar_id}" if avatar_id else None,
            status=duck["status"],
            note=duck["note"],
            active=duck["active"],
            deactivated_at=None if duck["active"] else anchor_midnight,
        ))
    for roster in fixture["rosters"]:
        roster_date = anchor_date + timedelta(days=roster["day_offset"])
        db.add(models.DutyRoster(
            id=roster["id"],
            cycle=f"演示-{roster_date.isocalendar().year}-W{roster_date.isocalendar().week:02d}",
            date=roster_date.isoformat(),
            child_id=roster["child_id"],
        ))

    future_lease_at = datetime.fromisoformat(fixture["future_lease_at"])
    categories = ("喂食", "清洁", "观察", "其它")
    emotions = ("开心", "平静", "期待", "自豪")
    for conversation in fixture["conversations"]:
        conversation_id = conversation["id"]
        started_at = _at(
            anchor_date,
            conversation["day_offset"],
            conversation["started_at"],
        )
        ended_at = _at(
            anchor_date,
            conversation["day_offset"],
            conversation["ended_at"],
        )
        child_message_id = conversation_id * 10 + 1
        diary_message_id = conversation_id * 10 + 2
        review_status = conversation["review_status"]
        db.add(models.Conversation(
            id=conversation_id,
            child_id=conversation["child_id"],
            date=(anchor_date + timedelta(days=conversation["day_offset"])).isoformat(),
            started_at=started_at,
            ended_at=ended_at,
            status="ended",
            end_reason=conversation["end_reason"],
            revision=2 if review_status == "draft" else (1 if review_status == "confirmed" else 0),
            pending_end_reason=None,
            frozen_last_message_id=diary_message_id,
        ))
        db.add_all([
            models.Message(
                id=child_message_id,
                conversation_id=conversation_id,
                role="child",
                text=conversation["child_text"],
                created_at=started_at + timedelta(minutes=1),
            ),
            models.Message(
                id=diary_message_id,
                conversation_id=conversation_id,
                role="diary",
                text=conversation["diary_text"],
                created_at=started_at + timedelta(minutes=2),
            ),
        ])

        status_name = conversation["analysis_status"]
        is_pending = status_name == "pending"
        is_processing = status_name == "processing"
        is_succeeded = status_name == "succeeded"
        is_failed = status_name == "failed"
        db.add(models.AnalysisJob(
            id=100 + conversation_id,
            conversation_id=conversation_id,
            frozen_last_message_id=diary_message_id,
            status=status_name,
            attempt_count=0 if is_pending else (3 if is_failed else 1),
            max_attempts=3,
            available_at=future_lease_at if (is_pending or is_processing) else ended_at,
            lease_owner="full-demo-fixed-worker" if is_processing else None,
            lease_expires_at=future_lease_at if is_processing else None,
            last_error_code="ANALYSIS_UPSTREAM_FAILED" if is_failed else None,
            last_error_message="演示分析失败，可安全重试" if is_failed else None,
            started_at=None if is_pending else ended_at + timedelta(seconds=1),
            finished_at=ended_at + timedelta(seconds=4) if (is_succeeded or is_failed) else None,
            created_at=ended_at,
            updated_at=ended_at + timedelta(seconds=4),
        ))
        if not is_succeeded:
            continue

        duck_id = 1 + (conversation_id % 2)
        db.add(models.FeedingLog(
            id=conversation_id,
            conversation_id=conversation_id,
            child_id=conversation["child_id"],
            duck_id=duck_id,
            category=categories[(conversation_id - 1) % len(categories)],
            content=f"演示记录 {conversation_id}：完成照顾并观察小鸭",
            occurred_at=ended_at - timedelta(minutes=2),
        ))
        db.add(models.EmotionLog(
            id=conversation_id,
            conversation_id=conversation_id,
            child_id=conversation["child_id"],
            emotion=emotions[(conversation_id - 1) % len(emotions)],
            intensity=1 + (conversation_id % 5),
            note=f"演示情绪记录 {conversation_id}",
            occurred_at=ended_at - timedelta(minutes=1),
        ))
        db.add(models.InsightNote(
            id=conversation_id,
            conversation_id=conversation_id,
            child_id=conversation["child_id"],
            content=f"演示心得 {conversation_id}：能回顾照顾步骤并表达感受。",
            created_at=ended_at + timedelta(seconds=2),
        ))
        base_score = conversation["score_base"]
        score_values = (
            base_score,
            min(5, base_score + (conversation_id % 2)),
            max(1, base_score - (conversation_id % 2)),
        )
        assessment = models.Assessment(
            id=conversation_id,
            conversation_id=conversation_id,
            child_id=conversation["child_id"],
            status=review_status,
            overall=sum(score_values) / 3,
        )
        db.add(assessment)
        for dimension_id, score in enumerate(score_values, start=1):
            db.add(models.AssessmentScore(
                id=conversation_id * 10 + dimension_id,
                assessment_id=conversation_id,
                dimension_id=dimension_id,
                score=score,
                reason=f"演示维度 {dimension_id} 的可读评分理由",
            ))


def populate_full_demo_database(
    engine: Engine,
    *,
    anchor_date: date,
    fixture: dict,
    avatars: tuple[_AvatarArtifact, ...],
) -> None:
    """Insert the complete graph using exactly one SQLAlchemy transaction."""

    with Session(engine) as db:
        with db.begin():
            _insert_full_demo_rows(
                db,
                anchor_date=anchor_date,
                fixture=fixture,
                avatars=avatars,
            )


def _json_value(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat(timespec="microseconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    return value


def _record_sha256(engine: Engine, avatars: tuple[_AvatarArtifact, ...]) -> str:
    rgba_by_id = {avatar.media_id: avatar.rgba_sha256 for avatar in avatars}
    payload: dict[str, list[dict[str, object]]] = {}
    with engine.connect() as connection:
        for table in sorted(Base.metadata.sorted_tables, key=lambda item: item.name):
            primary = list(table.primary_key.columns)
            statement = select(table)
            if primary:
                statement = statement.order_by(*primary)
            rows = []
            for result in connection.execute(statement).mappings():
                row = {key: _json_value(value) for key, value in result.items()}
                if table.name == "avatar_media":
                    row.pop("size_bytes", None)
                    row.pop("sha256", None)
                    row["rgba_sha256"] = rgba_by_id[row["id"]]
                rows.append(row)
            payload[table.name] = rows
    return sha256(_canonical_json(payload)).hexdigest()


def _media_sha256(avatars: tuple[_AvatarArtifact, ...]) -> str:
    logical = [
        {
            "id": avatar.media_id,
            "owner_type": avatar.owner_type,
            "owner_id": avatar.owner_id,
            "mime_type": "image/webp",
            "width": avatar.width,
            "height": avatar.height,
            "rgba_sha256": avatar.rgba_sha256,
        }
        for avatar in sorted(avatars, key=lambda item: item.media_id)
    ]
    return sha256(_canonical_json(logical)).hexdigest()


def _validate_staged_bundle(
    engine: Engine,
    *,
    media_root: Path,
    avatars: tuple[_AvatarArtifact, ...],
) -> None:
    try:
        with Session(engine) as db:
            stored_ids = db.scalars(
                select(models.AvatarMedia.id).order_by(models.AvatarMedia.id)
            ).all()
            expected_ids = sorted(avatar.media_id for avatar in avatars)
            if stored_ids != expected_ids:
                raise DemoSeedError("staged avatar rows are incomplete")
            for media_id in stored_ids:
                load_avatar(db, media_id, media_root=media_root)
    finally:
        close_pinned_media_roots()


def _install_new_bundle(
    *,
    staged_database: Path,
    staged_media: Path,
    staged_log: Path,
    database_path: Path,
    media_root: Path,
    log_path: Path,
    archived: list[tuple[str, Path, Path]],
    archived_hashes: dict[str, str],
    archive_directory: Path | None,
) -> None:
    installed: list[tuple[Path, Path]] = []
    try:
        for source, target in (
            (staged_database, database_path),
            (staged_media, media_root),
            (staged_log, log_path),
        ):
            _ensure_parent(target)
            _replace_path(source, target)
            installed.append((source, target))
    except Exception as exc:
        staged_restored = True
        for source, target in reversed(installed):
            try:
                _replace_path(target, source)
            except Exception:
                staged_restored = False
        old_restored = _restore_archived_resources(
            archived,
            expected=archived_hashes,
        )
        if not staged_restored or not old_restored:
            raise DemoSeedInstallError(
                "full-demo install failed and the old bundle could not be fully restored"
            ) from exc
        if archive_directory is not None and not _remove_fresh_archive_directory(
            archive_directory
        ):
            raise DemoSeedInstallError(
                "full-demo install failed; the old bundle was restored but the fresh "
                "archive directory could not be removed"
            ) from exc
        raise DemoSeedInstallError(
            "full-demo install failed; the old bundle was restored"
        ) from exc


def seed_full_demo(
    *,
    anchor_date: date,
    database_path: Path,
    media_root: Path,
    log_path: Path,
    force: bool = False,
    archive_directory: Path | None = None,
) -> DemoSeedResult:
    """Build, validate, and install one explicit offline full-demo bundle."""

    if type(anchor_date) is not date:
        raise DemoSeedSafetyError("anchor date must be a date")
    database_path = _absolute(database_path)
    media_root = _absolute(media_root)
    log_path = _absolute(log_path)
    archive_directory = _absolute(archive_directory) if archive_directory is not None else None
    _validate_target_paths(
        database_path=database_path,
        media_root=media_root,
        log_path=log_path,
        archive_directory=archive_directory,
        force=force,
    )
    fixture = _load_fixture()
    with _exclusive_seed_lock(database_path):
        _validate_existing_bundle(database_path, media_root, log_path, force=force)
        original_hashes = (
            _bundle_snapshot(database_path, media_root, log_path) if force else {}
        )
        stage_root = Path(tempfile.mkdtemp(
            prefix=f".{database_path.stem}-full-demo-",
            dir=database_path.parent,
        ))
        stage_root.chmod(0o700)
        staged_database = stage_root / "database.sqlite3"
        staged_media = stage_root / "media"
        staged_log = stage_root / "app.log"
        engine: Engine | None = None
        try:
            avatars = _stage_avatars(staged_media, fixture)
            engine = create_engine(
                f"sqlite:///{staged_database}",
                connect_args={"check_same_thread": False},
            )
            ensure_database_schema(engine, "app")
            populate_full_demo_database(
                engine,
                anchor_date=anchor_date,
                fixture=fixture,
                avatars=avatars,
            )
            engine.dispose()
            engine = create_engine(
                f"sqlite:///{staged_database}",
                connect_args={"check_same_thread": False},
            )
            record_hash = _record_sha256(engine, avatars)
            media_hash = _media_sha256(avatars)
            _validate_staged_bundle(engine, media_root=staged_media, avatars=avatars)
            engine.dispose()
            engine = None
            staged_database.chmod(0o600)
            staged_log.touch(mode=0o600)
            _validate_existing_bundle(database_path, media_root, log_path, force=force)
            if force and _bundle_snapshot(database_path, media_root, log_path) != original_hashes:
                raise DemoSeedSafetyError("demo target bundle changed while the seed was staged")
            archived: list[tuple[str, Path, Path]] = []
            if force:
                assert archive_directory is not None
                archived = _archive_existing_bundle(
                    database_path=database_path,
                    media_root=media_root,
                    log_path=log_path,
                    archive_directory=archive_directory,
                    expected=original_hashes,
                )
            _install_new_bundle(
                staged_database=staged_database,
                staged_media=staged_media,
                staged_log=staged_log,
                database_path=database_path,
                media_root=media_root,
                log_path=log_path,
                archived=archived,
                archived_hashes=original_hashes,
                archive_directory=archive_directory,
            )
            return DemoSeedResult(
                database_path=database_path,
                media_root=media_root,
                log_path=log_path,
                archive_directory=archive_directory,
                record_sha256=record_hash,
                media_sha256=media_hash,
            )
        finally:
            if engine is not None:
                engine.dispose()
            close_pinned_media_roots()
            shutil.rmtree(stage_root, ignore_errors=True)
