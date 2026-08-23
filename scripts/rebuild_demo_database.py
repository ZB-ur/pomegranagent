from __future__ import annotations

import argparse
import shutil
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@dataclass(frozen=True)
class RebuildResult:
    database_path: Path
    archived_database: Path | None
    archive_directory: Path


def local_service_is_running() -> bool:
    try:
        urllib.request.urlopen("http://127.0.0.1:8000/api/health", timeout=1).close()
        return True
    except (urllib.error.URLError, TimeoutError):
        return False


def rebuild_demo_database(
    *,
    db_path: Path,
    archive_dir: Path,
    log_path: Path,
    service_is_running: Callable[[], bool] = local_service_is_running,
) -> RebuildResult:
    if service_is_running():
        raise RuntimeError("service is still running; stop it before rebuilding data")
    db_path = db_path.expanduser().resolve()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target_dir = archive_dir.expanduser().resolve() / stamp
    target_dir.mkdir(parents=True, exist_ok=False)
    archived_database = None
    for source in (db_path, Path(str(db_path) + "-wal"), Path(str(db_path) + "-shm"), log_path):
        if source.exists():
            destination = target_dir / source.name
            shutil.move(str(source), destination)
            if source == db_path:
                archived_database = destination
    db_path.parent.mkdir(parents=True, exist_ok=True)
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.backend import models
    from app.backend.database import Base
    from app.backend.main import _seed_demo_data, _seed_dimensions

    local_engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    local_sessions = sessionmaker(autocommit=False, autoflush=False, bind=local_engine)
    Base.metadata.create_all(bind=local_engine)
    _seed_dimensions(local_sessions)
    _seed_demo_data(local_sessions)
    local_engine.dispose()
    return RebuildResult(db_path, archived_database, target_dir)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Archive the current demo data and rebuild it with deterministic sample records."
    )
    parser.add_argument("--database", type=Path, default=Path("data/duck_diary.db"))
    parser.add_argument("--archive-dir", type=Path, default=Path("data/archive"))
    parser.add_argument("--confirm-rebuild", action="store_true", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = rebuild_demo_database(
        db_path=args.database,
        archive_dir=args.archive_dir,
        log_path=Path("logs/app.log"),
    )
    print(f"New database: {result.database_path}")
    print(f"Archive directory: {result.archive_directory}")


if __name__ == "__main__":
    main()
