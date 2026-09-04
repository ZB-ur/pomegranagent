from __future__ import annotations

import argparse
import errno
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEMO_SEED_DATE = date(2026, 8, 24)
UNREACHABLE_ERRNOS = {errno.ECONNREFUSED, errno.ENETUNREACH, errno.EHOSTUNREACH}


@dataclass(frozen=True)
class RebuildResult:
    database_path: Path
    media_root: Path
    log_path: Path
    archived_database: Path | None
    archive_directory: Path
    record_sha256: str
    media_sha256: str


def local_service_is_running() -> bool:
    try:
        urllib.request.urlopen("http://127.0.0.1:8000/api/health", timeout=1).close()
        return True
    except urllib.error.URLError as error:
        reason = error.reason
        return not (isinstance(reason, OSError) and reason.errno in UNREACHABLE_ERRNOS)
    except TimeoutError:
        return True


def rebuild_demo_database(
    *,
    db_path: Path,
    media_root: Path,
    archive_dir: Path,
    log_path: Path,
    anchor_date: date = DEMO_SEED_DATE,
    service_is_running: Callable[[], bool] = local_service_is_running,
) -> RebuildResult:
    """Rebuild through the same staged, verified full-demo installation path."""

    if service_is_running():
        raise RuntimeError("service is still running; stop it before rebuilding data")
    db_path = db_path.expanduser().absolute()
    media_root = media_root.expanduser().absolute()
    log_path = log_path.expanduser().absolute()
    archive_base = archive_dir.expanduser().absolute()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    target_archive = archive_base / stamp
    database_existed = db_path.exists() or db_path.is_symlink()

    from app.backend.services.demo_seed import seed_full_demo

    seeded = seed_full_demo(
        anchor_date=anchor_date,
        database_path=db_path,
        media_root=media_root,
        log_path=log_path,
        force=True,
        archive_directory=target_archive,
    )
    archived_database = (
        target_archive / "database" / db_path.name if database_existed else None
    )
    return RebuildResult(
        database_path=seeded.database_path,
        media_root=seeded.media_root,
        log_path=seeded.log_path,
        archived_database=archived_database,
        archive_directory=target_archive,
        record_sha256=seeded.record_sha256,
        media_sha256=seeded.media_sha256,
    )


def _anchor_date(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError("anchor date must be YYYY-MM-DD") from None
    if parsed.isoformat() != value:
        raise argparse.ArgumentTypeError("anchor date must be YYYY-MM-DD")
    return parsed


def parse_args() -> argparse.Namespace:
    from app.backend.settings import RuntimeSettings

    settings = RuntimeSettings.from_env()
    parser = argparse.ArgumentParser(
        description=(
            "Archive the current demo bundle and rebuild it with deterministic "
            "full-demo records and media."
        )
    )
    parser.add_argument("--database", type=Path, default=settings.db_path)
    parser.add_argument("--media-root", type=Path, default=settings.media_root)
    parser.add_argument("--log-path", type=Path, default=settings.log_path)
    parser.add_argument("--archive-dir", type=Path, default=Path("data/archive"))
    parser.add_argument("--anchor-date", type=_anchor_date, default=DEMO_SEED_DATE)
    parser.add_argument("--confirm-rebuild", action="store_true", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = rebuild_demo_database(
        db_path=args.database,
        media_root=args.media_root,
        archive_dir=args.archive_dir,
        log_path=args.log_path,
        anchor_date=args.anchor_date,
    )
    print(f"New database: {result.database_path}")
    print(f"New media root: {result.media_root}")
    print(f"New log: {result.log_path}")
    print(f"Archive directory: {result.archive_directory}")
    print(f"Record SHA-256: {result.record_sha256}")
    print(f"Media SHA-256: {result.media_sha256}")


if __name__ == "__main__":
    main()
