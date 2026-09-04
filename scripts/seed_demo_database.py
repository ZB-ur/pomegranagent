"""Explicit CLI for installing the deterministic full-demo bundle."""
from __future__ import annotations

import argparse
from datetime import date
import json
import os
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _anchor_date(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError("anchor date must be YYYY-MM-DD") from None
    if parsed.isoformat() != value:
        raise argparse.ArgumentTypeError("anchor date must be YYYY-MM-DD")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Install an offline deterministic demo data bundle.",
    )
    commands = parser.add_subparsers(dest="seed_name", required=True)
    full_demo = commands.add_parser(
        "full-demo",
        help="seed the complete child, roster, history, analysis, and review graph",
    )
    full_demo.add_argument("--anchor-date", required=True, type=_anchor_date)
    full_demo.add_argument("--database", required=True, type=Path)
    full_demo.add_argument("--media-root", required=True, type=Path)
    full_demo.add_argument("--log-path", required=True, type=Path)
    full_demo.add_argument("--force", action="store_true")
    full_demo.add_argument("--archive-dir", type=Path)
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    # Bind import-time backend settings to the caller-authorized bundle. The seed
    # service itself uses a dedicated migrated engine and never starts the app.
    os.environ["APP_DB_MODE"] = "app"
    os.environ["APP_DB_PATH"] = str(args.database)
    os.environ["APP_MEDIA_ROOT"] = str(args.media_root)
    os.environ["APP_LOG_PATH"] = str(args.log_path)

    from app.backend.services.demo_seed import DemoSeedError, seed_full_demo

    try:
        result = seed_full_demo(
            anchor_date=args.anchor_date,
            database_path=args.database,
            media_root=args.media_root,
            log_path=args.log_path,
            force=args.force,
            archive_directory=args.archive_dir,
        )
    except DemoSeedError as exc:
        print(f"full-demo seed refused: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(
        {
            "database_path": str(result.database_path),
            "media_root": str(result.media_root),
            "log_path": str(result.log_path),
            "archive_directory": (
                str(result.archive_directory)
                if result.archive_directory is not None
                else None
            ),
            "record_sha256": result.record_sha256,
            "media_sha256": result.media_sha256,
        },
        ensure_ascii=False,
        sort_keys=True,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
