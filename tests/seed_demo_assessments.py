"""Compatibility entry point for the explicit deterministic full-demo seed.

This helper no longer opens the configured application database or appends rows.
Every target and the anchor date must be supplied explicitly; the canonical CLI
then builds a complete schema-3 bundle offline in one transaction.
"""
from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.seed_demo_database import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main(["full-demo", *sys.argv[1:]]))
