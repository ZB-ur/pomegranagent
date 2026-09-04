#!/usr/bin/env python3
"""Retained, non-default live-provider UAT controller harness.

The module deliberately performs no filesystem, process, provider, or backend
work at import time.  The live orchestration entry point is implemented in
small testable boundaries so fake dependencies can exercise every safety rule.
"""
from __future__ import annotations

import argparse
import base64
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import http.client
import io
import json
import math
import os
from pathlib import Path
import re
import secrets
import select
import signal
import socket
import sqlite3
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
import zlib
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit


PROJECT_ROOT = Path(__file__).resolve().parents[1]
HEAD_PATTERN = re.compile(r"[0-9a-f]{40}")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
UUID4_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
)
SAFE_EXECUTION_ENV = ("PATH", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT")
DEEPSEEK_ALLOWLIST = (
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_MODEL",
    "DEEPSEEK_TIMEOUT",
    "DEEPSEEK_MAX_TOKENS",
)
FROZEN_RELEASE = {
    "release_id": "2026.09.02-server-capabilities.1",
    "api_version": "3",
    "schema_version": "3",
}
APPROVED_VIEWPORTS = {
    "child": ["1024x576", "1280x720"],
    "teacher": ["1024x768", "1440x900"],
}
REQUIRED_SCREENSHOT_STATES = {
    "child-avatar-selected": ("child", "child_duck_avatar_management"),
    "child-conversation-complete": ("child", "child_conversation_real_provider_tts"),
    "teacher-management": ("teacher", "child_duck_avatar_management"),
    "teacher-review-confirmed": ("teacher", "review_edit_confirm"),
    "teacher-search-deep-link": ("teacher", "advanced_search_pagination_deep_link"),
    "teacher-weekly-growth": ("teacher", "weekly_metrics_growth"),
}
TELEMETRY_KEYS = {
    "audio_bytes",
    "cache_relative_path",
    "cache_sha256",
    "correlation_id",
    "error_class",
    "latency_bucket",
    "model",
    "operation",
    "parse_valid",
    "provider",
    "response_bytes",
    "response_sha256",
    "status",
    "voice",
}
LATENCY_BUCKETS = {"<1s", "1-5s", "5-30s", "30-120s", ">=120s"}
REQUIRED_JOURNEY_STEPS = (
    "teacher_credential_setup_login",
    "child_duck_avatar_management",
    "invalid_avatar_rejection",
    "monthly_roster_conflict_retry",
    "child_conversation_real_provider_tts",
    "conversation_completion_analysis",
    "teacher_today_queues",
    "review_edit_confirm",
    "weekly_metrics_growth",
    "advanced_search_pagination_deep_link",
    "search_empty_state",
    "logout_login_retained_state",
)
_CONTROLLER_KEYS = {
    "human_uat_required",
    "issues",
    "journey",
    "protocol",
    "run_id",
    "screenshots",
    "source_head",
}
_PROVENANCE_KEYS = {
    "analysis_job_id",
    "assessment_id",
    "child_avatar_id",
    "chat_request_ids",
    "duck_avatar_id",
    "growth_after",
    "growth_before",
    "live_child_id",
    "live_duck_id",
    "live_conversation_id",
    "monthly_pairs",
    "monthly_roster_attempts",
    "search_cursor",
    "search_deep_link",
    "search_page_one_ids",
    "search_page_two_ids",
    "search_request",
    "search_result_conversation_id",
    "tts_evidence",
    "weekly_metrics_after",
    "weekly_metrics_before",
    "weekly_week_start",
}
_BASELINE_ID_COLUMNS = {
    "analysis_jobs": "id",
    "assessment_scores": "id",
    "assessments": "id",
    "avatar_media": "id",
    "chat_requests": "request_id",
    "children": "id",
    "conversations": "id",
    "ducks": "id",
    "duty_rosters": "id",
    "emotion_logs": "id",
    "feeding_logs": "id",
    "insight_notes": "id",
    "messages": "id",
    "roster_requests": "request_id",
}
_RUNTIME_DIRTY_PREFIXES = (
    "app/",
    "scripts/",
    "tests/",
)
_RUNTIME_DIRTY_FILES = {
    ".env",
    ".python-version",
    "package-lock.json",
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "uv.lock",
    "version.json",
}
_RUNTIME_DIRTY_SUFFIXES = {".css", ".html", ".js", ".mjs", ".py", ".sql"}


class HarnessError(RuntimeError):
    """Base class for controlled live-UAT failures."""


class HarnessSafetyError(HarnessError):
    """A fail-closed filesystem, process, credential, or evidence violation."""


@dataclass(frozen=True, slots=True)
class RunPlan:
    repository: Path
    repository_identity: tuple[int, int, int, int]
    source_head: str
    run_id: str
    root: Path
    root_identity: tuple[int, int, int, int]
    database: Path
    media: Path
    tts_cache: Path
    app_log: Path
    server_stderr: Path
    screenshots: Path
    controller_evidence: Path
    journey: Path
    issues: Path
    provider_summary: Path
    seed_baseline: Path
    resources_before: Path
    resources_after: Path
    manifest: Path
    checksums: Path
    invalid_avatar: Path


@dataclass(slots=True, repr=False)
class ControlState:
    _teacher_secret: str | None = None
    finalize_requested: bool = False

    @property
    def has_teacher_secret(self) -> bool:
        return self._teacher_secret is not None

    def secret_for_scan(self) -> str | None:
        return self._teacher_secret

    def __repr__(self) -> str:
        return (
            "ControlState(has_teacher_secret="
            f"{self.has_teacher_secret!r}, finalize_requested={self.finalize_requested!r})"
        )


@dataclass(frozen=True, slots=True)
class BoundLoopbackSocket:
    socket: object
    port: int


@dataclass(frozen=True, slots=True)
class OwnedProcess:
    process: object
    pid: int
    pgid: int
    sid: int | None = None


@dataclass(slots=True)
class LiveServerSession:
    port: int
    owned: OwnedProcess
    telemetry: object
    output: object
    finished: bool = False
    provider_events: tuple[Mapping[str, object], ...] = ()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Retain one isolated live-provider UAT evidence bundle.",
    )
    parser.add_argument("--retain", action="store_true")
    parser.add_argument("--print-runtime-json", action="store_true")
    parser.add_argument("--expected-head", required=True)
    parser.add_argument(
        "--allow-unrelated-dirty-path",
        action="append",
        default=[],
        metavar="REPO_RELATIVE_PATH",
    )
    parsed = parser.parse_args(argv)
    if not parsed.retain or not parsed.print_runtime_json:
        parser.error("--retain and --print-runtime-json are both required")
    if HEAD_PATTERN.fullmatch(parsed.expected_head) is None:
        parser.error("--expected-head must be one literal lowercase 40-hex commit")
    try:
        parsed.allow_unrelated_dirty_path = list(
            _validated_unrelated_dirty_paths(parsed.allow_unrelated_dirty_path)
        )
    except HarnessSafetyError as exc:
        parser.error(str(exc))
    return parsed


def _canonical_repository_relative_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise HarnessSafetyError("unrelated dirty path is invalid")
    candidate = Path(value)
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        raise HarnessSafetyError("unrelated dirty path is invalid")
    canonical = candidate.as_posix()
    basename = candidate.name
    if (
        canonical in _RUNTIME_DIRTY_FILES
        or basename in {"Dockerfile", "Makefile"}
        or basename.startswith(".env")
        or basename.startswith("requirements")
        or candidate.suffix.lower() in _RUNTIME_DIRTY_SUFFIXES
        or canonical == "docs/live-provider-uat-checklist.md"
        or canonical.startswith(_RUNTIME_DIRTY_PREFIXES)
        or canonical.startswith("artifacts/real-uat/")
    ):
        raise HarnessSafetyError("unrelated dirty path affects runtime or UAT")
    return canonical


def _validated_unrelated_dirty_paths(values: object) -> tuple[str, ...]:
    if not isinstance(values, (tuple, list)) or len(values) > 256:
        raise HarnessSafetyError("unrelated dirty path list is invalid")
    canonical = tuple(_canonical_repository_relative_path(value) for value in values)
    if len(set(canonical)) != len(canonical):
        raise HarnessSafetyError("unrelated dirty path list contains duplicates")
    return tuple(sorted(canonical))


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(Path(path).expanduser())))


def _safe_owned_directory(path: Path, *, label: str) -> None:
    try:
        entry = path.lstat()
    except OSError as exc:
        raise HarnessSafetyError(f"{label} is unavailable") from exc
    if (
        not stat.S_ISDIR(entry.st_mode)
        or stat.S_ISLNK(entry.st_mode)
        or entry.st_uid != os.geteuid()
        or entry.st_mode & 0o022
    ):
        raise HarnessSafetyError(f"{label} is not an owner-controlled directory")


def _directory_open_flags() -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    return flags


def _open_absolute_directory_nofollow(path: Path) -> int:
    absolute = _absolute(path)
    descriptor = os.open(os.path.sep, _directory_open_flags())
    try:
        for component in absolute.parts[1:]:
            next_descriptor = os.open(
                component,
                _directory_open_flags(),
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _owned_directory_identity(path: Path, *, label: str) -> tuple[int, int, int, int]:
    _safe_owned_directory(path, label=label)
    try:
        descriptor = _open_absolute_directory_nofollow(path)
    except OSError as exc:
        raise HarnessSafetyError(f"{label} is unavailable") from exc
    try:
        entry = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(entry.st_mode)
            or entry.st_uid != os.geteuid()
            or entry.st_mode & 0o022
            or entry.st_nlink < 1
        ):
            raise HarnessSafetyError(f"{label} is not an owner-controlled directory")
        return (
            entry.st_dev,
            entry.st_ino,
            stat.S_IMODE(entry.st_mode),
            entry.st_uid,
        )
    finally:
        os.close(descriptor)


def _open_plan_root(plan: RunPlan) -> int:
    try:
        descriptor = _open_absolute_directory_nofollow(plan.repository)
    except OSError as exc:
        raise HarnessSafetyError("run root identity is unavailable") from exc
    try:
        repository_entry = os.fstat(descriptor)
        if (
            (
                repository_entry.st_dev,
                repository_entry.st_ino,
                stat.S_IMODE(repository_entry.st_mode),
                repository_entry.st_uid,
            )
            != plan.repository_identity
            or repository_entry.st_uid != os.geteuid()
            or repository_entry.st_mode & 0o022
        ):
            raise HarnessSafetyError("run root identity changed")
        for component in ("artifacts", "real-uat", plan.run_id):
            next_descriptor = os.open(
                component,
                _directory_open_flags(),
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = next_descriptor
        root_entry = os.fstat(descriptor)
        if (
            (
                root_entry.st_dev,
                root_entry.st_ino,
                stat.S_IMODE(root_entry.st_mode),
                root_entry.st_uid,
            )
            != plan.root_identity
            or root_entry.st_uid != os.geteuid()
            or root_entry.st_mode & 0o022
            or root_entry.st_nlink < 1
        ):
            raise HarnessSafetyError("run root identity changed")
        return descriptor
    except HarnessSafetyError:
        os.close(descriptor)
        raise
    except (OSError, ValueError) as exc:
        os.close(descriptor)
        raise HarnessSafetyError("run root identity changed") from exc


def assert_run_plan_identity(plan: RunPlan) -> None:
    descriptor = _open_plan_root(plan)
    os.close(descriptor)


def _open_plan_parent(plan: RunPlan, target: Path) -> tuple[int, str]:
    destination = _absolute(target)
    try:
        relative = destination.relative_to(plan.root)
    except ValueError as exc:
        raise HarnessSafetyError("evidence target is outside the retained run") from exc
    if len(relative.parts) < 1 or any(part in {"", ".", ".."} for part in relative.parts):
        raise HarnessSafetyError("evidence target is outside the retained run")
    descriptor = _open_plan_root(plan)
    try:
        for component in relative.parts[:-1]:
            next_descriptor = os.open(
                component,
                _directory_open_flags(),
                dir_fd=descriptor,
            )
            entry = os.fstat(next_descriptor)
            if (
                not stat.S_ISDIR(entry.st_mode)
                or entry.st_uid != os.geteuid()
                or entry.st_mode & 0o022
                or entry.st_nlink < 1
            ):
                os.close(next_descriptor)
                raise HarnessSafetyError("evidence parent is unsafe")
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor, relative.name
    except BaseException:
        os.close(descriptor)
        raise


def _directory_descriptor_identity(entry: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        entry.st_dev,
        entry.st_ino,
        stat.S_IMODE(entry.st_mode),
        entry.st_nlink,
        entry.st_uid,
    )


def _regular_descriptor_identity(entry: os.stat_result) -> tuple[int, ...]:
    return (
        entry.st_dev,
        entry.st_ino,
        entry.st_mode,
        entry.st_nlink,
        entry.st_size,
        entry.st_mtime_ns,
        entry.st_uid,
    )


def _read_pinned_run_file(
    plan: RunPlan,
    target: Path,
    *,
    max_bytes: int,
    before_read: Callable[[], None] = lambda: None,
) -> bytes:
    """Read through a retained parent descriptor and re-pin its pathname chain."""

    if type(max_bytes) is not int or max_bytes < 1:
        raise HarnessSafetyError("retained file bound is invalid")
    parent_descriptor, name = _open_plan_parent(plan, target)
    descriptor = None
    try:
        parent_identity = _directory_descriptor_identity(os.fstat(parent_descriptor))
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(name, flags, dir_fd=parent_descriptor)
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or before.st_mode & 0o022
            or before.st_nlink != 1
            or before.st_size > max_bytes
        ):
            raise HarnessSafetyError("retained file identity is unsafe")
        before_identity = _regular_descriptor_identity(before)
        before_read()
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, max_bytes - total + 1))
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise HarnessSafetyError("retained file exceeds its bound")
            chunks.append(chunk)
        if _regular_descriptor_identity(os.fstat(descriptor)) != before_identity:
            raise HarnessSafetyError("retained file changed during read")
    except HarnessSafetyError:
        raise
    except OSError as exc:
        raise HarnessSafetyError("retained file is unavailable") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(parent_descriptor)
    current_parent, current_name = _open_plan_parent(plan, target)
    try:
        if _directory_descriptor_identity(os.fstat(current_parent)) != parent_identity:
            raise HarnessSafetyError("retained file ancestor identity changed")
        current = os.stat(
            current_name,
            dir_fd=current_parent,
            follow_symlinks=False,
        )
        if _regular_descriptor_identity(current) != before_identity:
            raise HarnessSafetyError("retained file identity changed")
    except HarnessSafetyError:
        raise
    except OSError as exc:
        raise HarnessSafetyError("retained file identity changed") from exc
    finally:
        os.close(current_parent)
    assert_run_plan_identity(plan)
    return b"".join(chunks)


def _ensure_artifact_directory(path: Path, *, label: str) -> None:
    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        pass
    except OSError as exc:
        raise HarnessSafetyError(f"{label} cannot be created safely") from exc
    _safe_owned_directory(path, label=label)


def _open_or_create_owned_child_directory(
    parent_descriptor: int,
    name: str,
    *,
    label: str,
) -> int:
    try:
        os.mkdir(name, 0o700, dir_fd=parent_descriptor)
    except FileExistsError:
        pass
    except OSError as exc:
        raise HarnessSafetyError(f"{label} cannot be created safely") from exc
    try:
        descriptor = os.open(name, _directory_open_flags(), dir_fd=parent_descriptor)
    except OSError as exc:
        raise HarnessSafetyError(f"{label} is unavailable") from exc
    entry = os.fstat(descriptor)
    if (
        not stat.S_ISDIR(entry.st_mode)
        or entry.st_uid != os.geteuid()
        or entry.st_mode & 0o022
        or entry.st_nlink < 1
    ):
        os.close(descriptor)
        raise HarnessSafetyError(f"{label} is not an owner-controlled directory")
    return descriptor


def _default_now() -> datetime:
    return datetime.now(timezone.utc)


def _default_nonce() -> str:
    return secrets.token_hex(6)


def create_run_plan(
    repository: Path,
    source_head: str,
    *,
    now: Callable[[], datetime] = _default_now,
    nonce: Callable[[], str] = _default_nonce,
) -> RunPlan:
    """Exclusively create one retained run root and pin every descendant path."""

    root = _absolute(repository)
    repository_identity = _owned_directory_identity(root, label="repository root")
    if HEAD_PATTERN.fullmatch(source_head) is None:
        raise HarnessSafetyError("source head is not a literal 40-hex commit")

    artifacts = root / "artifacts"
    real_uat = artifacts / "real-uat"
    repository_descriptor = _open_absolute_directory_nofollow(root)
    artifacts_descriptor = real_uat_descriptor = None
    try:
        repository_entry = os.fstat(repository_descriptor)
        if (
            repository_entry.st_dev,
            repository_entry.st_ino,
            stat.S_IMODE(repository_entry.st_mode),
            repository_entry.st_uid,
        ) != repository_identity:
            raise HarnessSafetyError("repository root identity changed")
        git_entry = os.stat(
            ".git",
            dir_fd=repository_descriptor,
            follow_symlinks=False,
        )
        if not (stat.S_ISDIR(git_entry.st_mode) or stat.S_ISREG(git_entry.st_mode)):
            raise HarnessSafetyError("repository root has no Git metadata")
        artifacts_descriptor = _open_or_create_owned_child_directory(
            repository_descriptor,
            "artifacts",
            label="artifact ancestry",
        )
        real_uat_descriptor = _open_or_create_owned_child_directory(
            artifacts_descriptor,
            "real-uat",
            label="artifact ancestry",
        )
    except FileNotFoundError as exc:
        raise HarnessSafetyError("repository root has no Git metadata") from exc
    finally:
        os.close(repository_descriptor)
        if artifacts_descriptor is not None:
            os.close(artifacts_descriptor)

    sampled = now()
    if sampled.tzinfo is None or sampled.utcoffset() is None:
        raise HarnessSafetyError("run clock must be timezone aware")
    timestamp = sampled.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    entropy = nonce()
    if re.fullmatch(r"[0-9a-f]{12}", entropy) is None:
        raise HarnessSafetyError("run nonce is invalid")
    stem = f"{timestamp}-{entropy}"
    run_root = None
    run_id = ""
    run_descriptor = None
    try:
        assert real_uat_descriptor is not None
        for attempt in range(100):
            collision = "" if attempt == 0 else f"-{attempt:02d}"
            run_id = f"{stem}{collision}-{source_head[:12]}"
            candidate = real_uat / run_id
            try:
                os.mkdir(run_id, 0o700, dir_fd=real_uat_descriptor)
            except FileExistsError:
                continue
            except OSError as exc:
                raise HarnessSafetyError("run directory cannot be created safely") from exc
            run_descriptor = os.open(
                run_id,
                _directory_open_flags(),
                dir_fd=real_uat_descriptor,
            )
            run_root = candidate
            break
        if run_descriptor is None or run_root is None:
            raise HarnessSafetyError("run identifier collision limit reached")
        run_entry = os.fstat(run_descriptor)
        if (
            not stat.S_ISDIR(run_entry.st_mode)
            or run_entry.st_uid != os.geteuid()
            or run_entry.st_mode & 0o022
            or run_entry.st_nlink < 1
        ):
            raise HarnessSafetyError("run directory is not owner-controlled")
        root_identity = (
            run_entry.st_dev,
            run_entry.st_ino,
            stat.S_IMODE(run_entry.st_mode),
            run_entry.st_uid,
        )
    finally:
        if run_descriptor is not None:
            os.close(run_descriptor)
        if real_uat_descriptor is not None:
            os.close(real_uat_descriptor)
    if run_root is None:
        raise HarnessSafetyError("run identifier collision limit reached")

    return RunPlan(
        repository=root,
        repository_identity=repository_identity,
        source_head=source_head,
        run_id=run_id,
        root=run_root,
        root_identity=root_identity,
        database=run_root / "duck-diary-uat.db",
        media=run_root / "media",
        tts_cache=run_root / "tts-cache",
        app_log=run_root / "logs" / "app.log",
        server_stderr=run_root / "logs" / "server.stderr.log",
        screenshots=run_root / "screenshots",
        controller_evidence=run_root / "controller-evidence.json",
        journey=run_root / "journey.json",
        issues=run_root / "issues.json",
        provider_summary=run_root / "provider-summary.json",
        seed_baseline=run_root / "seed-baseline.json",
        resources_before=run_root / "resources.before.json",
        resources_after=run_root / "resources.after.json",
        manifest=run_root / "manifest.json",
        checksums=run_root / "SHA256SUMS",
        invalid_avatar=run_root / "invalid-avatar.png",
    )


def build_seed_argv(
    plan: RunPlan,
    *,
    python_executable: str,
    business_today: Callable[[], date],
) -> tuple[str, ...]:
    anchor = business_today()
    if type(anchor) is not date:
        raise HarnessSafetyError("business date provider returned an invalid value")
    return (
        python_executable,
        str(plan.repository / "scripts" / "seed_demo_database.py"),
        "full-demo",
        "--anchor-date",
        anchor.isoformat(),
        "--database",
        str(plan.database),
        "--media-root",
        str(plan.media),
        "--log-path",
        str(plan.app_log),
    )


def build_seed_environment(parent: Mapping[str, str]) -> dict[str, str]:
    environment = {
        name: parent[name]
        for name in SAFE_EXECUTION_ENV
        if name in parent and isinstance(parent[name], str)
    }
    environment.update(
        {
            "DISABLE_EXTERNAL_AI": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTHON_DOTENV_DISABLED": "1",
            "TZ": "Asia/Shanghai",
        }
    )
    return dict(sorted(environment.items()))


def run_seed_process(
    plan: RunPlan,
    *,
    argv: tuple[str, ...],
    environment: Mapping[str, str],
    popen=subprocess.Popen,
    getpgid: Callable[[int], int] = os.getpgid,
    getsid: Callable[[int], int] = os.getsid,
) -> dict[str, object]:
    """Run the synthetic seed offline in one bounded, shell-free process group."""

    allowed = set(SAFE_EXECUTION_ENV) | {
        "DISABLE_EXTERNAL_AI",
        "PYTHONNOUSERSITE",
        "PYTHON_DOTENV_DISABLED",
        "TZ",
    }
    if (
        not isinstance(environment, Mapping)
        or any(name not in allowed for name in environment)
        or environment.get("DISABLE_EXTERNAL_AI") != "1"
        or environment.get("PYTHONNOUSERSITE") != "1"
        or environment.get("PYTHON_DOTENV_DISABLED") != "1"
        or environment.get("TZ") != "Asia/Shanghai"
        or any(name.startswith("DEEPSEEK_") for name in environment)
        or not isinstance(argv, tuple)
        or not argv
        or any(not isinstance(part, str) or not part for part in argv)
    ):
        raise HarnessSafetyError("offline seed process contract is invalid")

    with tempfile.TemporaryFile(mode="w+b") as stdout_file, tempfile.TemporaryFile(
        mode="w+b"
    ) as stderr_file:
        try:
            process = popen(
                argv,
                cwd=plan.repository,
                env=dict(environment),
                stdin=subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                shell=False,
                start_new_session=True,
                close_fds=True,
            )
        except (OSError, ValueError) as exc:
            raise HarnessSafetyError("offline seed process could not start") from exc
        owned = OwnedProcess(
            process=process,
            pid=process.pid,
            pgid=process.pid,
            sid=process.pid,
        )
        _owned_identity(owned, getpgid=getpgid, getsid=getsid)
        try:
            returncode = process.wait(timeout=120)
        except subprocess.TimeoutExpired as exc:
            stop_owned_process_group(owned, getpgid=getpgid)
            raise HarnessSafetyError("offline seed process timed out") from exc
        if returncode != 0:
            raise HarnessSafetyError("offline seed process failed")
        stdout_file.seek(0, os.SEEK_END)
        stderr_file.seek(0, os.SEEK_END)
        if stdout_file.tell() > 65_536 or stderr_file.tell() > 65_536:
            raise HarnessSafetyError("offline seed process output is too large")
        stdout_file.seek(0)
        return parse_seed_result(stdout_file.read(), plan)


def _provider_configuration_error() -> HarnessSafetyError:
    return HarnessSafetyError("provider configuration is unsafe or incomplete")


def _canonical_provider_values(values: Mapping[str, object]) -> dict[str, str]:
    if set(values) != set(DEEPSEEK_ALLOWLIST):
        raise _provider_configuration_error()
    if not all(isinstance(values[name], str) for name in DEEPSEEK_ALLOWLIST):
        raise _provider_configuration_error()
    selected = {name: str(values[name]) for name in DEEPSEEK_ALLOWLIST}
    api_key = selected["DEEPSEEK_API_KEY"]
    if (
        len(api_key) < 16
        or len(api_key) > 4096
        or not api_key.strip()
        or api_key.strip().lower() in {"placeholder", "changeme", "your-api-key"}
        or any(character in "\r\n\x00" for character in api_key)
    ):
        raise _provider_configuration_error()
    try:
        parsed = urlsplit(selected["DEEPSEEK_BASE_URL"])
        port = parsed.port
    except (TypeError, ValueError):
        raise _provider_configuration_error() from None
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or any(part == ".." for part in parsed.path.split("/"))
        or any(character.isspace() for character in selected["DEEPSEEK_BASE_URL"])
        or port is not None and not (1 <= port <= 65535)
    ):
        raise _provider_configuration_error()
    selected["DEEPSEEK_BASE_URL"] = selected["DEEPSEEK_BASE_URL"].rstrip("/")
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", selected["DEEPSEEK_MODEL"]) is None:
        raise _provider_configuration_error()
    if re.fullmatch(r"[1-9][0-9]{0,2}", selected["DEEPSEEK_TIMEOUT"]) is None:
        raise _provider_configuration_error()
    if not 1 <= int(selected["DEEPSEEK_TIMEOUT"]) <= 300:
        raise _provider_configuration_error()
    if re.fullmatch(r"[1-9][0-9]{0,5}", selected["DEEPSEEK_MAX_TOKENS"]) is None:
        raise _provider_configuration_error()
    if not 1 <= int(selected["DEEPSEEK_MAX_TOKENS"]) <= 65_536:
        raise _provider_configuration_error()
    return selected


def select_provider_settings(
    parent: Mapping[str, str],
    dotenv_values: Mapping[str, object],
) -> dict[str, str]:
    """Select and validate only the five backend-supported DeepSeek settings."""

    defaults = {
        "DEEPSEEK_BASE_URL": "https://api.deepseek.com/v1",
        "DEEPSEEK_MODEL": "deepseek-v4-pro",
        "DEEPSEEK_TIMEOUT": "120",
        "DEEPSEEK_MAX_TOKENS": "8192",
    }
    selected: dict[str, object] = {}
    for name in DEEPSEEK_ALLOWLIST:
        if name in parent and parent[name] != "":
            selected[name] = parent[name]
        elif name in dotenv_values and dotenv_values[name] not in {None, ""}:
            selected[name] = dotenv_values[name]
        elif name in defaults:
            selected[name] = defaults[name]
    return _canonical_provider_values(selected)


def build_backend_environment(
    parent: Mapping[str, str],
    plan: RunPlan,
    provider: Mapping[str, object],
) -> dict[str, str]:
    selected = _canonical_provider_values(provider)
    environment = {
        name: parent[name]
        for name in SAFE_EXECUTION_ENV
        if name in parent and isinstance(parent[name], str)
    }
    environment.update(
        {
            "APP_BUSINESS_TIMEZONE": "Asia/Shanghai",
            "APP_DB_MODE": "app",
            "APP_DB_PATH": str(plan.database),
            "APP_LOG_PATH": str(plan.app_log),
            "APP_MEDIA_ROOT": str(plan.media),
            "APP_TTS_CACHE_PATH": str(plan.tts_cache),
            "PYTHONNOUSERSITE": "1",
            "PYTHON_DOTENV_DISABLED": "1",
            "TZ": "Asia/Shanghai",
            **selected,
        }
    )
    return dict(sorted(environment.items()))


def validate_readiness(
    *,
    health: object,
    version: object,
    version_cache_control: object,
    auth: object,
) -> None:
    expected_health = {
        **FROZEN_RELEASE,
        "db_mode": "app",
        "analysis_worker_status": "running",
    }
    if (
        health != expected_health
        or version != FROZEN_RELEASE
        or version_cache_control != "no-store"
        or auth != {"configured": False, "authenticated": False}
    ):
        raise HarnessSafetyError("live server readiness contract failed")


def _strict_json_bytes(payload: bytes) -> object:
    if not isinstance(payload, bytes) or not 1 <= len(payload) <= 65_536:
        raise HarnessSafetyError("live server readiness response is invalid")

    def reject_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    try:
        return json.loads(
            payload.decode("utf-8", errors="strict"),
            object_pairs_hook=reject_duplicates,
        )
    except (UnicodeError, ValueError, TypeError) as exc:
        raise HarnessSafetyError("live server readiness response is invalid") from exc


def _fetch_loopback_json(port: int, path: str) -> tuple[object, str | None]:
    if (
        type(port) is not int
        or not 1 <= port <= 65_535
        or path not in {"/api/health", "/version.json", "/api/auth/status"}
    ):
        raise HarnessSafetyError("live server readiness request is invalid")
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    try:
        connection.request(
            "GET",
            path,
            body=None,
            headers={"Accept": "application/json", "Connection": "close"},
        )
        response = connection.getresponse()
        if response.status != 200:
            raise HarnessSafetyError("live server readiness response is invalid")
        content_type = response.getheader("Content-Type", "").split(";", 1)[0].strip()
        if content_type != "application/json":
            raise HarnessSafetyError("live server readiness response is invalid")
        payload = response.read(65_537)
        if len(payload) > 65_536:
            raise HarnessSafetyError("live server readiness response is invalid")
        return _strict_json_bytes(payload), response.getheader("Cache-Control")
    finally:
        connection.close()


def probe_live_readiness(
    session,
    *,
    fetch_json: Callable[[int, str], tuple[object, str | None]] = _fetch_loopback_json,
    require_alive: Callable[[OwnedProcess], None] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[object, object, object, object]:
    """Wait only for the owned loopback child, then enforce the exact release."""

    port = getattr(session, "port", None)
    owned = getattr(session, "owned", None)
    if type(port) is not int or not 1 <= port <= 65_535 or owned is None:
        raise HarnessSafetyError("live server session is invalid")
    if require_alive is None:
        require_alive = require_owned_process_alive
    deadline = monotonic() + 30.0
    while True:
        require_alive(owned)
        try:
            health, _health_cache = fetch_json(port, "/api/health")
            version, version_cache = fetch_json(port, "/version.json")
            auth, _auth_cache = fetch_json(port, "/api/auth/status")
        except (ConnectionError, TimeoutError, OSError, http.client.HTTPException):
            if monotonic() >= deadline:
                raise HarnessSafetyError("live server readiness timed out") from None
            sleep(0.1)
            continue
        validate_readiness(
            health=health,
            version=version,
            version_cache_control=version_cache,
            auth=auth,
        )
        return health, version, version_cache, auth


def build_runtime_object(plan: RunPlan, *, port: int) -> dict[str, object]:
    if type(port) is not int or not 1 <= port <= 65535:
        raise HarnessSafetyError("runtime loopback port is invalid")
    base_url = f"http://127.0.0.1:{port}"
    return {
        "artifact_root": str(plan.root),
        "base_url": base_url,
        "child_url": f"{base_url}/",
        "controller_evidence_path": str(plan.controller_evidence),
        "fixtures": {
            "child_avatar": str(
                plan.repository / "tests/fixtures/live_provider/avatars/child.png"
            ),
            "duck_avatar": str(
                plan.repository / "tests/fixtures/live_provider/avatars/duck.jpg"
            ),
            "invalid_avatar": str(plan.invalid_avatar),
        },
        "protocol": "pomegranagent-live-uat/v1",
        "release": dict(FROZEN_RELEASE),
        "run_id": plan.run_id,
        "screenshots_dir": str(plan.screenshots),
        "source_head": plan.source_head,
        "teacher_url": f"{base_url}/teacher.html",
        "viewports": {name: list(values) for name, values in APPROVED_VIEWPORTS.items()},
    }


def canonical_json_line(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n"


class RuntimeEmitter:
    def __init__(self, output) -> None:
        self._output = output
        self._emitted = False

    def emit(self, runtime: Mapping[str, object]) -> None:
        if self._emitted:
            raise HarnessSafetyError("safe runtime object was already emitted")
        self._output.write(canonical_json_line(runtime))
        self._output.flush()
        self._emitted = True


def _strict_control_frame(line: str) -> dict[str, object]:
    if not line.endswith("\n") or line.endswith("\r\n") or len(line.encode("utf-8")) > 1024:
        raise HarnessSafetyError("canonical control frame is invalid")
    payload = line[:-1]
    try:
        value = json.loads(payload)
    except (TypeError, ValueError) as exc:
        raise HarnessSafetyError("canonical control frame is invalid") from exc
    if not isinstance(value, dict) or canonical_json_line(value) != line:
        raise HarnessSafetyError("canonical control frame is invalid")
    return value


def consume_control_stream(stream, plan: RunPlan, *, output=None) -> ControlState:
    """Consume one-way controller NDJSON without acknowledgements or echo."""

    del output
    state = ControlState()
    for line in stream:
        value = _strict_control_frame(line)
        frame_type = value.get("type")
        if frame_type == "register_secret" and set(value) == {"kind", "type", "value"}:
            secret = value.get("value")
            if (
                value.get("kind") != "teacher_credential"
                or not isinstance(secret, str)
                or re.fullmatch(r"[0-9]{4,6}", secret) is None
                or state.has_teacher_secret
            ):
                raise HarnessSafetyError("canonical control frame is invalid")
            state._teacher_secret = secret
            continue
        if frame_type == "finalize" and set(value) == {"type"}:
            try:
                evidence_entry = plan.controller_evidence.lstat()
            except OSError as exc:
                raise HarnessSafetyError("finalize requires controller evidence") from exc
            if not stat.S_ISREG(evidence_entry.st_mode) or evidence_entry.st_nlink != 1:
                raise HarnessSafetyError("finalize requires controller evidence")
            state.finalize_requested = True
            break
        raise HarnessSafetyError("canonical control frame is invalid")
    return state


def parse_telemetry_line(payload: bytes) -> dict[str, object]:
    if not isinstance(payload, bytes) or not 1 <= len(payload) <= 4096:
        raise HarnessSafetyError("provider telemetry is invalid")
    try:
        text = payload.decode("utf-8", errors="strict")
        value = json.loads(text)
    except (UnicodeError, ValueError, TypeError) as exc:
        raise HarnessSafetyError("provider telemetry is invalid") from exc
    if (
        not isinstance(value, dict)
        or set(value) != TELEMETRY_KEYS
        or canonical_json_line(value) != text
    ):
        raise HarnessSafetyError("provider telemetry is invalid")
    operation = value["operation"]
    provider = value["provider"]
    model = value["model"]
    voice = value["voice"]
    if operation in {"chat_reply", "extract_info", "assess_conversation"}:
        expected_correlation = (
            r"conversation:[1-9][0-9]*"
            if operation == "chat_reply"
            else r"analysis-job:[1-9][0-9]*"
        )
        identity_valid = (
            provider == "deepseek"
            and isinstance(model, str)
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", model) is not None
            and voice is None
            and isinstance(value["correlation_id"], str)
            and re.fullmatch(expected_correlation, value["correlation_id"]) is not None
            and type(value["parse_valid"]) is bool
            and value["audio_bytes"] == 0
            and value["cache_relative_path"] is None
            and value["cache_sha256"] is None
        )
    elif operation == "tts":
        identity_valid = (
            provider == "edge-tts"
            and model is None
            and isinstance(voice, str)
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}", voice) is not None
            and isinstance(value["correlation_id"], str)
            and re.fullmatch(r"message-text:[0-9a-f]{64}", value["correlation_id"])
            is not None
            and value["parse_valid"] is None
            and value["response_bytes"] == 0
            and value["response_sha256"] is None
            and isinstance(value["cache_relative_path"], str)
            and re.fullmatch(
                r"tts-cache/[0-9a-f]{32}\.mp3",
                value["cache_relative_path"],
            )
            is not None
        )
    else:
        identity_valid = False
    status_value = value["status"]
    error_class = value["error_class"]
    status_valid = (
        status_value == "ok" and error_class is None
    ) or (
        status_value == "error"
        and isinstance(error_class, str)
        and re.fullmatch(r"[A-Za-z][A-Za-z0-9_.]{0,127}", error_class) is not None
    )
    count_values = (value["response_bytes"], value["audio_bytes"])
    if (
        not identity_valid
        or not status_valid
        or value["latency_bucket"] not in LATENCY_BUCKETS
        or any(type(count) is not int or not 0 <= count <= 100_000_000 for count in count_values)
    ):
        raise HarnessSafetyError("provider telemetry is invalid")
    if operation == "tts":
        if (
            value["status"] == "ok"
            and (
                value["audio_bytes"] <= 0
                or not isinstance(value["cache_sha256"], str)
                or SHA256_PATTERN.fullmatch(value["cache_sha256"]) is None
            )
        ):
            raise HarnessSafetyError("provider telemetry is invalid")
    elif (
        value["status"] == "ok"
        and (
            value["parse_valid"] is not True
            or value["response_bytes"] <= 0
            or not isinstance(value["response_sha256"], str)
            or SHA256_PATTERN.fullmatch(value["response_sha256"]) is None
        )
    ) or (
        value["response_bytes"] == 0 and value["response_sha256"] is not None
    ) or (
        value["response_bytes"] > 0
        and (
            not isinstance(value["response_sha256"], str)
            or SHA256_PATTERN.fullmatch(value["response_sha256"]) is None
        )
    ):
        raise HarnessSafetyError("provider telemetry is invalid")
    return value


def summarize_provider_events(events: tuple[Mapping[str, object], ...]) -> dict[str, object]:
    safe_events = []
    if len(events) > 10_000:
        raise HarnessSafetyError("provider telemetry is invalid")
    for event in events:
        validated = parse_telemetry_line(canonical_json_line(dict(event)).encode("utf-8"))
        safe_events.append(validated)
    return {
        "protocol": "pomegranagent-live-uat-provider-summary/v1",
        "events": safe_events,
    }


class TelemetryCollector:
    """Drain one dedicated pipe while retaining only validated bounded events."""

    def __init__(self, descriptor: int) -> None:
        if type(descriptor) is not int or descriptor < 0:
            raise HarnessSafetyError("provider telemetry descriptor is invalid")
        try:
            mode = os.fstat(descriptor).st_mode
        except OSError as exc:
            raise HarnessSafetyError("provider telemetry descriptor is invalid") from exc
        if not stat.S_ISFIFO(mode):
            raise HarnessSafetyError("provider telemetry descriptor is invalid")
        self._descriptor = descriptor
        self._thread: threading.Thread | None = None
        self._events: list[dict[str, object]] = []
        self._error: HarnessSafetyError | None = None

    def start(self) -> None:
        if self._thread is not None:
            raise HarnessSafetyError("provider telemetry collector already started")
        self._thread = threading.Thread(
            target=self._drain,
            name="live-uat-telemetry",
            daemon=True,
        )
        self._thread.start()

    def _drain(self) -> None:
        buffered = b""
        total = 0
        try:
            with os.fdopen(self._descriptor, "rb", buffering=0) as stream:
                while True:
                    chunk = stream.read(16_384)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > 40_960_000:
                        raise HarnessSafetyError("provider telemetry is invalid")
                    buffered += chunk
                    while b"\n" in buffered:
                        raw, buffered = buffered.split(b"\n", 1)
                        line = raw + b"\n"
                        if len(line) > 4096 or len(self._events) >= 10_000:
                            raise HarnessSafetyError("provider telemetry is invalid")
                        self._events.append(parse_telemetry_line(line))
                    if len(buffered) > 4096:
                        raise HarnessSafetyError("provider telemetry is invalid")
            if buffered:
                raise HarnessSafetyError("provider telemetry is truncated")
        except HarnessSafetyError as exc:
            self._error = exc
        except (OSError, ValueError) as exc:
            self._error = HarnessSafetyError("provider telemetry could not be read")
            self._error.__cause__ = exc

    def finish(self, *, timeout: float = 10.0) -> tuple[Mapping[str, object], ...]:
        thread = self._thread
        if thread is None:
            raise HarnessSafetyError("provider telemetry collector was not started")
        thread.join(timeout=timeout)
        if thread.is_alive():
            raise HarnessSafetyError("provider telemetry collector did not finish")
        if self._error is not None:
            raise self._error
        return tuple(self._events)


def prebind_loopback_socket(*, socket_factory=socket.socket) -> BoundLoopbackSocket:
    """Bind and listen on one kernel-selected loopback port without a race."""

    candidate = socket_factory(socket.AF_INET, socket.SOCK_STREAM)
    try:
        candidate.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        candidate.bind(("127.0.0.1", 0))
        candidate.listen(128)
        address = candidate.getsockname()
        if (
            not isinstance(address, tuple)
            or len(address) < 2
            or address[0] != "127.0.0.1"
            or type(address[1]) is not int
            or not 1 <= address[1] <= 65535
        ):
            raise HarnessSafetyError("prebound loopback socket is invalid")
        return BoundLoopbackSocket(candidate, address[1])
    except Exception as exc:
        try:
            candidate.close()
        except Exception:
            pass
        if isinstance(exc, HarnessSafetyError):
            raise
        raise HarnessSafetyError("prebound loopback socket failed") from exc


def _owned_identity(
    owned: OwnedProcess,
    *,
    getpgid: Callable[[int], int],
    getsid: Callable[[int], int] | None = None,
) -> None:
    expected_sid = owned.pid if owned.sid is None else owned.sid
    if (
        type(owned.pid) is not int
        or owned.pid <= 1
        or owned.pgid != owned.pid
        or expected_sid != owned.pid
        or getattr(owned.process, "pid", None) != owned.pid
    ):
        raise HarnessSafetyError("process-group ownership is invalid")
    try:
        observed = getpgid(owned.pid)
    except (OSError, ValueError) as exc:
        raise HarnessSafetyError("process-group ownership is invalid") from exc
    if observed != owned.pgid:
        raise HarnessSafetyError("process-group ownership is invalid")
    if getsid is not None:
        try:
            observed_sid = getsid(owned.pid)
        except (OSError, ValueError) as exc:
            raise HarnessSafetyError("process-group ownership is invalid") from exc
        if observed_sid != expected_sid:
            raise HarnessSafetyError("process-group ownership is invalid")


def launch_server_process(
    plan: RunPlan,
    *,
    environment: Mapping[str, str],
    bound_socket,
    telemetry_fd: int,
    output,
    python_executable: str,
    popen=subprocess.Popen,
    getpgid=os.getpgid,
    getsid=os.getsid,
) -> OwnedProcess:
    listen_fd = bound_socket.fileno()
    if (
        type(listen_fd) is not int
        or listen_fd < 0
        or type(telemetry_fd) is not int
        or telemetry_fd < 0
        or listen_fd == telemetry_fd
    ):
        raise HarnessSafetyError("inherited server descriptors are invalid")
    argv = (
        python_executable,
        str(plan.repository / "scripts" / "live_provider_uat_server.py"),
        "--listen-fd",
        str(listen_fd),
        "--telemetry-fd",
        str(telemetry_fd),
    )
    try:
        process = popen(
            argv,
            cwd=plan.repository,
            env=dict(environment),
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=output,
            shell=False,
            start_new_session=True,
            close_fds=True,
            pass_fds=(listen_fd, telemetry_fd),
        )
    except (OSError, ValueError) as exc:
        raise HarnessSafetyError("live server process could not start") from exc
    owned = OwnedProcess(
        process=process,
        pid=process.pid,
        pgid=process.pid,
        sid=process.pid,
    )
    _owned_identity(owned, getpgid=getpgid, getsid=getsid)
    return owned


def require_owned_process_alive(
    owned: OwnedProcess,
    *,
    getpgid: Callable[[int], int] = os.getpgid,
    getsid: Callable[[int], int] = os.getsid,
) -> None:
    _owned_identity(owned, getpgid=getpgid, getsid=getsid)
    if owned.process.poll() is not None:
        raise HarnessSafetyError("live server exited before readiness")


def _process_group_members(
    pgid: int,
    *,
    runner=subprocess.run,
) -> tuple[tuple[int, int], ...]:
    try:
        completed = runner(
            ("ps", "-axo", "pid=,pgid="),
            capture_output=True,
            check=False,
        )
    except (OSError, ValueError) as exc:
        raise HarnessSafetyError("process-group ownership is invalid") from exc
    payload = completed.stdout
    if completed.returncode != 0 or not isinstance(payload, bytes) or len(payload) > 8_000_000:
        raise HarnessSafetyError("process-group ownership is invalid")
    members: list[tuple[int, int]] = []
    try:
        for line in payload.decode("ascii", errors="strict").splitlines():
            fields = line.split()
            if len(fields) != 2:
                raise ValueError
            pid, observed_pgid = (int(field) for field in fields)
            if observed_pgid == pgid:
                try:
                    sid = os.getsid(pid)
                except ProcessLookupError:
                    continue
                members.append((pid, sid))
    except (OSError, UnicodeError, ValueError) as exc:
        raise HarnessSafetyError("process-group ownership is invalid") from exc
    return tuple(sorted(members))


def _verified_group_members(
    owned: OwnedProcess,
    members: tuple[tuple[int, int], ...],
) -> tuple[tuple[int, int], ...]:
    expected_sid = owned.pid if owned.sid is None else owned.sid
    if any(
        type(pid) is not int
        or pid <= 1
        or type(sid) is not int
        or sid != expected_sid
        for pid, sid in members
    ) or (
        owned.process.poll() is not None
        and any(pid == owned.pid for pid, _sid in members)
    ):
        raise HarnessSafetyError("process-group ownership is invalid")
    return members


def _wait_owned_group_absent(
    owned: OwnedProcess,
    *,
    group_members: Callable[[int], tuple[tuple[int, int], ...]],
    timeout: float,
    monotonic: Callable[[], float],
    sleep: Callable[[float], None],
) -> bool:
    deadline = monotonic() + timeout
    while True:
        members = _verified_group_members(owned, tuple(group_members(owned.pgid)))
        if not members:
            return True
        if monotonic() >= deadline:
            return False
        sleep(0.05)


def stop_owned_process_group(
    owned: OwnedProcess,
    *,
    getpgid: Callable[[int], int] = os.getpgid,
    getsid: Callable[[int], int] = os.getsid,
    group_members: Callable[[int], tuple[tuple[int, int], ...]] = _process_group_members,
    killpg: Callable[[int, int], None] = os.killpg,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Stop the retained session and prove every owned PGID member is absent."""

    leader_alive = owned.process.poll() is None
    if leader_alive:
        _owned_identity(owned, getpgid=getpgid, getsid=getsid)
    elif (
        type(owned.pid) is not int
        or owned.pid <= 1
        or owned.pgid != owned.pid
        or (owned.sid is not None and owned.sid != owned.pid)
    ):
        raise HarnessSafetyError("process-group ownership is invalid")
    members = _verified_group_members(owned, tuple(group_members(owned.pgid)))
    if not members:
        if leader_alive:
            raise HarnessSafetyError("process-group ownership is invalid")
        return
    try:
        killpg(owned.pgid, signal.SIGTERM)
        if leader_alive:
            try:
                owned.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                pass
        if not _wait_owned_group_absent(
            owned,
            group_members=group_members,
            timeout=2,
            monotonic=monotonic,
            sleep=sleep,
        ):
            _verified_group_members(owned, tuple(group_members(owned.pgid)))
            killpg(owned.pgid, signal.SIGKILL)
            if owned.process.poll() is None:
                try:
                    owned.process.wait(timeout=5)
                except subprocess.TimeoutExpired as exc:
                    raise HarnessSafetyError("owned process group could not be reaped") from exc
            if not _wait_owned_group_absent(
                owned,
                group_members=group_members,
                timeout=5,
                monotonic=monotonic,
                sleep=sleep,
            ):
                raise HarnessSafetyError("owned process group could not be reaped")
        elif owned.process.poll() is None:
            owned.process.wait(timeout=5)
    except (OSError, ValueError) as exc:
        raise HarnessSafetyError("owned process group could not be stopped") from exc
    if owned.process.poll() is None:
        raise HarnessSafetyError("owned process group could not be reaped")


def start_live_server(
    plan: RunPlan,
    *,
    environment: Mapping[str, str],
    python_executable: str,
    prebind: Callable[[], BoundLoopbackSocket] = prebind_loopback_socket,
    collector_factory: Callable[[int], object] = TelemetryCollector,
    launcher: Callable[..., OwnedProcess] = launch_server_process,
) -> LiveServerSession:
    """Launch the sole live child and close every parent-side inherited handle."""

    assert_run_plan_identity(plan)
    _safe_owned_directory(plan.app_log.parent, label="run log directory")
    bound = prebind()
    read_fd = write_fd = None
    output = None
    collector = None
    try:
        read_fd, write_fd = os.pipe()
        collector = collector_factory(read_fd)
        collector.start()
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        output_parent, output_name = _open_plan_parent(plan, plan.server_stderr)
        try:
            output_fd = os.open(
                output_name,
                flags,
                0o600,
                dir_fd=output_parent,
            )
        finally:
            os.close(output_parent)
        output = os.fdopen(output_fd, "wb", buffering=0)
        owned = launcher(
            plan,
            environment=environment,
            bound_socket=bound.socket,
            telemetry_fd=write_fd,
            output=output,
            python_executable=python_executable,
        )
    except BaseException:
        try:
            bound.socket.close()
        except BaseException:
            pass
        for descriptor in (write_fd, read_fd):
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
        if output is not None:
            try:
                output.close()
            except BaseException:
                pass
        raise
    bound.socket.close()
    os.close(write_fd)
    assert_run_plan_identity(plan)
    return LiveServerSession(
        port=bound.port,
        owned=owned,
        telemetry=collector,
        output=output,
    )


def finish_live_server(
    session: LiveServerSession,
    *,
    stopper: Callable[[OwnedProcess], None] = stop_owned_process_group,
) -> tuple[Mapping[str, object], ...]:
    """Stop, reap, flush, and drain the one session exactly once."""

    if not isinstance(session, LiveServerSession):
        raise HarnessSafetyError("live server session is invalid")
    if session.finished:
        return session.provider_events
    error: BaseException | None = None
    if session.owned.process.poll() is not None:
        error = HarnessSafetyError("live server exited unexpectedly")
    try:
        stopper(session.owned)
    except BaseException as exc:
        error = exc
    try:
        session.output.flush()
        os.fsync(session.output.fileno())
    except BaseException as exc:
        if error is None:
            error = exc
    finally:
        try:
            session.output.close()
        except BaseException as exc:
            if error is None:
                error = exc
    try:
        events = tuple(session.telemetry.finish())
    except BaseException as exc:
        events = ()
        if error is None:
            error = exc
    session.provider_events = events
    session.finished = True
    if error is not None:
        if isinstance(error, HarnessSafetyError):
            raise error
        raise HarnessSafetyError("live server cleanup failed") from error
    return events


def atomic_write_json(
    target: Path,
    value: object,
    *,
    replace: Callable[[Path, Path], None] = os.replace,
    nonce: Callable[[], str] = lambda: secrets.token_hex(8),
    pinned_plan: RunPlan | None = None,
) -> None:
    """Write one canonical 0600 JSON artifact and durably replace its target."""

    destination = _absolute(target)
    parent = destination.parent
    parent_descriptor = None
    destination_name = destination.name
    if pinned_plan is None:
        _safe_owned_directory(parent, label="evidence parent")
        try:
            existing = destination.lstat()
        except FileNotFoundError:
            existing = None
        except OSError as exc:
            raise HarnessSafetyError("atomic evidence write failed") from exc
    else:
        parent_descriptor, destination_name = _open_plan_parent(pinned_plan, destination)
        try:
            existing = os.stat(
                destination_name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            existing = None
        except OSError as exc:
            os.close(parent_descriptor)
            raise HarnessSafetyError("atomic evidence write failed") from exc
    if existing is not None and (
        not stat.S_ISREG(existing.st_mode) or existing.st_nlink != 1
    ):
        if parent_descriptor is not None:
            os.close(parent_descriptor)
        raise HarnessSafetyError("atomic evidence write target is unsafe")
    token = nonce()
    if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", token) is None:
        if parent_descriptor is not None:
            os.close(parent_descriptor)
        raise HarnessSafetyError("atomic evidence write nonce is invalid")
    temporary = parent / f".{destination.name}.{token}.tmp"
    temporary_name = temporary.name
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = None
    try:
        descriptor = os.open(
            temporary_name if parent_descriptor is not None else temporary,
            flags,
            0o600,
            dir_fd=parent_descriptor,
        )
        payload = canonical_json_line(value).encode("utf-8")
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise OSError("short write")
            offset += written
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        if parent_descriptor is not None and replace is os.replace:
            os.replace(
                temporary_name,
                destination_name,
                src_dir_fd=parent_descriptor,
                dst_dir_fd=parent_descriptor,
            )
        else:
            replace(temporary, destination)
        if parent_descriptor is not None:
            os.fsync(parent_descriptor)
        else:
            directory_fd = os.open(parent, _directory_open_flags())
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    except OSError as exc:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        try:
            if parent_descriptor is not None:
                os.unlink(temporary_name, dir_fd=parent_descriptor)
            else:
                temporary.unlink()
        except OSError:
            pass
        raise HarnessSafetyError("atomic evidence write failed") from exc
    finally:
        if parent_descriptor is not None:
            os.close(parent_descriptor)
    if pinned_plan is not None:
        assert_run_plan_identity(pinned_plan)


def finalize_failed_run(plan: RunPlan, *, reason_code: str) -> None:
    if re.fullmatch(r"[A-Z][A-Z0-9_]{2,63}", reason_code) is None:
        raise HarnessSafetyError("failed-run reason code is invalid")
    payload = {
        "protocol": "pomegranagent-live-uat-manifest/v1",
        "reason_code": reason_code,
        "run_id": plan.run_id,
        "source_head": plan.source_head,
        "status": "FAILED",
    }
    if plan.manifest.exists():
        try:
            existing = json.loads(plan.manifest.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise HarnessSafetyError("existing retained manifest is invalid") from exc
        if existing == payload:
            return
        raise HarnessSafetyError("existing retained manifest cannot be replaced")
    atomic_write_json(plan.manifest, payload, pinned_plan=plan)


def _hash_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _file_evidence(path: Path) -> dict[str, object]:
    try:
        entry = path.lstat()
    except FileNotFoundError:
        return {"kind": "missing"}
    except OSError as exc:
        raise HarnessSafetyError("protected resource snapshot failed") from exc
    common = {
        "device": entry.st_dev,
        "inode": entry.st_ino,
        "mode": stat.S_IMODE(entry.st_mode),
        "mtime_ns": entry.st_mtime_ns,
        "nlink": entry.st_nlink,
        "size": entry.st_size,
    }
    if stat.S_ISREG(entry.st_mode) and entry.st_nlink == 1:
        try:
            payload = path.read_bytes()
        except OSError as exc:
            raise HarnessSafetyError("protected resource snapshot failed") from exc
        after = path.lstat()
        if (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_nlink,
            after.st_size,
            after.st_mtime_ns,
        ) != (
            entry.st_dev,
            entry.st_ino,
            entry.st_mode,
            entry.st_nlink,
            entry.st_size,
            entry.st_mtime_ns,
        ):
            raise HarnessSafetyError("protected resource changed during snapshot")
        return {"kind": "regular", **common, "sha256": _hash_bytes(payload)}
    if stat.S_ISDIR(entry.st_mode) and not stat.S_ISLNK(entry.st_mode):
        return {"kind": "directory", **common}
    if stat.S_ISLNK(entry.st_mode):
        return {"kind": "symlink", **common}
    return {"kind": "special", **common}


def _directory_evidence(path: Path) -> dict[str, object]:
    root = _file_evidence(path)
    if root["kind"] == "missing":
        return {"root": root, "entries": [], "digest": _hash_bytes(b"[]")}
    if root["kind"] != "directory":
        raise HarnessSafetyError("protected resource tree is unsafe")
    entries = []
    try:
        candidates = sorted(path.rglob("*"), key=lambda item: item.relative_to(path).as_posix())
    except OSError as exc:
        raise HarnessSafetyError("protected resource tree scan failed") from exc
    for candidate in candidates:
        relative = candidate.relative_to(path).as_posix()
        if any(part in {"", ".", ".."} for part in relative.split("/")):
            raise HarnessSafetyError("protected resource tree is unsafe")
        evidence = _file_evidence(candidate)
        if evidence["kind"] not in {"regular", "directory"}:
            raise HarnessSafetyError("protected resource tree is unsafe")
        entries.append({"relative_path": relative, "snapshot": evidence})
    digest_payload = json.dumps(
        entries, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    root_after = _file_evidence(path)
    if root_after != root:
        raise HarnessSafetyError("protected resource changed during snapshot")
    return {"root": root, "entries": entries, "digest": _hash_bytes(digest_payload)}


@contextmanager
def _sqlite_shadow(path: Path):
    """Copy DB/WAL/SHM stably so read-only inspection cannot touch live sidecars."""

    with tempfile.TemporaryDirectory(prefix="pomegranagent-sqlite-proof-") as temporary:
        shadow = Path(temporary) / path.name
        for suffix in ("", "-wal", "-shm"):
            source = Path(f"{path}{suffix}")
            before = _file_evidence(source)
            if before["kind"] == "missing":
                if suffix == "":
                    raise HarnessSafetyError("protected database is unavailable")
                continue
            if before["kind"] != "regular":
                raise HarnessSafetyError("protected database snapshot failed")
            try:
                payload = source.read_bytes()
            except OSError as exc:
                raise HarnessSafetyError("protected database snapshot failed") from exc
            if _file_evidence(source) != before:
                raise HarnessSafetyError("protected database changed during snapshot")
            try:
                Path(f"{shadow}{suffix}").write_bytes(payload)
            except OSError as exc:
                raise HarnessSafetyError("protected database shadow failed") from exc
        yield shadow


def _database_logical_digest(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        with _sqlite_shadow(path) as shadow:
            uri = f"{shadow.as_uri()}?mode=ro"
            with sqlite3.connect(uri, uri=True) as connection:
                connection.execute("PRAGMA query_only=ON")
                if connection.execute("PRAGMA query_only").fetchone() != (1,):
                    raise HarnessSafetyError("protected database is not query-only")
                rows = "\n".join(connection.iterdump()).encode("utf-8")
    except HarnessSafetyError:
        raise
    except sqlite3.Error as exc:
        raise HarnessSafetyError("protected database snapshot failed") from exc
    return _hash_bytes(rows)


def _database_evidence(path: Path) -> dict[str, object]:
    return {
        "logical_digest": _database_logical_digest(path),
        "database": _file_evidence(path),
        "wal": _file_evidence(Path(f"{path}-wal")),
        "shm": _file_evidence(Path(f"{path}-shm")),
    }


def _git_capture(root: Path, runner, argv: tuple[str, ...]) -> bytes:
    try:
        completed = runner(argv, cwd=root, capture_output=True, check=False)
    except (OSError, ValueError) as exc:
        raise HarnessSafetyError("protected Git snapshot failed") from exc
    if completed.returncode != 0 or not isinstance(completed.stdout, bytes):
        raise HarnessSafetyError("protected Git snapshot failed")
    return completed.stdout


def _dirty_path_names(status: bytes) -> tuple[str, ...]:
    if not status:
        return ()
    if not status.endswith(b"\0"):
        raise HarnessSafetyError("protected Git porcelain is invalid")
    records = list(status[:-1].split(b"\0"))
    paths: list[str] = []
    index = 0
    while index < len(records):
        record = records[index]
        if len(record) < 4 or record[2:3] != b" ":
            raise HarnessSafetyError("protected Git porcelain is invalid")
        status_code = record[:2]
        raw_paths = [record[3:]]
        index += 1
        if b"R" in status_code or b"C" in status_code:
            if index >= len(records):
                raise HarnessSafetyError("protected Git porcelain is invalid")
            raw_paths.append(records[index])
            index += 1
        for raw_path in raw_paths:
            try:
                relative = raw_path.decode("utf-8", errors="strict")
            except UnicodeError as exc:
                raise HarnessSafetyError("protected Git porcelain is invalid") from exc
            candidate = Path(relative)
            if (
                not relative
                or candidate.is_absolute()
                or "\\" in relative
                or any(part in {"", ".", ".."} for part in candidate.parts)
            ):
                raise HarnessSafetyError("protected Git porcelain is invalid")
            paths.append(candidate.as_posix())
    return tuple(sorted(set(paths)))


def _dirty_path_evidence(root: Path, relative: str) -> dict[str, object]:
    path = root.joinpath(*relative.split("/"))
    file_state = _file_evidence(path)
    directory = _directory_evidence(path) if file_state["kind"] == "directory" else None
    if file_state["kind"] not in {"regular", "directory"}:
        raise HarnessSafetyError("pre-existing dirty path is unsafe")
    return {
        "relative_path": relative,
        "file": file_state,
        "directory": directory,
    }


def capture_protected_resources(
    repository: Path,
    *,
    runner=subprocess.run,
) -> dict[str, object]:
    root = _absolute(repository)
    _safe_owned_directory(root, label="repository root")
    head_payload = _git_capture(root, runner, ("git", "rev-parse", "HEAD"))
    try:
        head = head_payload.decode("ascii", errors="strict").strip()
    except UnicodeError as exc:
        raise HarnessSafetyError("protected Git head is invalid") from exc
    if HEAD_PATTERN.fullmatch(head) is None:
        raise HarnessSafetyError("protected Git head is invalid")
    porcelain = _git_capture(
        root,
        runner,
        ("git", "status", "--porcelain=v1", "-z", "--untracked-files=all"),
    )
    dirty_names = _dirty_path_names(porcelain)
    return {
        "database": _database_evidence(root / "data" / "duck_diary.db"),
        "log": _file_evidence(root / "logs" / "app.log"),
        "tts": _directory_evidence(root / "data" / "tts_cache"),
        "media": _directory_evidence(root / "data" / "media"),
        "git_head": head,
        "git_porcelain": {"sha256": _hash_bytes(porcelain), "size": len(porcelain)},
        "dirty_paths": [
            _dirty_path_evidence(root, relative) for relative in dirty_names
        ],
    }


def validate_reviewed_checkout(
    snapshot: Mapping[str, object],
    *,
    expected_head: str,
    allowed_unrelated_dirty_paths: tuple[str, ...],
) -> None:
    """Require the exact reviewed commit and only explicit non-runtime dirt."""

    try:
        allowed = _validated_unrelated_dirty_paths(allowed_unrelated_dirty_paths)
    except HarnessSafetyError as exc:
        raise HarnessSafetyError("reviewed checkout dirty-path classification is invalid") from exc
    dirty = snapshot.get("dirty_paths")
    if (
        HEAD_PATTERN.fullmatch(expected_head) is None
        or snapshot.get("git_head") != expected_head
        or not isinstance(dirty, list)
    ):
        raise HarnessSafetyError("reviewed checkout identity is invalid")
    observed: list[str] = []
    for item in dirty:
        if not isinstance(item, Mapping):
            raise HarnessSafetyError("reviewed checkout dirty state is invalid")
        relative = item.get("relative_path")
        try:
            canonical = _canonical_repository_relative_path(relative)
        except HarnessSafetyError as exc:
            raise HarnessSafetyError("reviewed checkout contains runtime or UAT dirt") from exc
        observed.append(canonical)
    if len(set(observed)) != len(observed) or tuple(sorted(observed)) != allowed:
        raise HarnessSafetyError("reviewed checkout dirty paths are not explicitly classified")


def assert_protected_resources_equal(before: object, after: object) -> None:
    if not isinstance(before, Mapping) or not isinstance(after, Mapping):
        raise HarnessSafetyError("protected resource drift: SNAPSHOT")
    labels = (
        ("database", "DATABASE"),
        ("log", "LOG"),
        ("tts", "TTS"),
        ("media", "MEDIA"),
        ("git_head", "HEAD"),
        ("git_porcelain", "PORCELAIN"),
        ("dirty_paths", "DIRTY"),
    )
    changed = [label for key, label in labels if before.get(key) != after.get(key)]
    if changed:
        raise HarnessSafetyError("protected resource drift: " + ",".join(changed))


_SECRET_PATTERNS = (
    re.compile(rb"authorization\s*:", re.IGNORECASE),
    re.compile(rb"\bbearer\s+", re.IGNORECASE),
    re.compile(rb"duck_teacher_session", re.IGNORECASE),
    re.compile(rb"set-cookie\s*:", re.IGNORECASE),
    re.compile(rb"(?:^|[^a-z])cookie\s*[:=]", re.IGNORECASE),
    re.compile(rb"auth[-_]?token\s*[:=]", re.IGNORECASE),
)


def scan_retained_artifacts(
    root: Path,
    *,
    actual_secrets: tuple[str, ...],
    pinned_plan: RunPlan | None = None,
) -> None:
    base = _absolute(root)
    if pinned_plan is not None:
        if base != pinned_plan.root:
            raise HarnessSafetyError("secret scan failed: retained root identity")
        assert_run_plan_identity(pinned_plan)
    _safe_owned_directory(base, label="retained artifact root")
    encoded_secrets = tuple(
        secret.encode("utf-8")
        for secret in actual_secrets
        if isinstance(secret, str) and secret
    )
    try:
        candidates = sorted(base.rglob("*"), key=lambda item: item.relative_to(base).as_posix())
    except OSError as exc:
        raise HarnessSafetyError("secret scan failed: artifact tree") from exc
    total = 0
    for path in candidates:
        entry = path.lstat()
        if stat.S_ISDIR(entry.st_mode) and not stat.S_ISLNK(entry.st_mode):
            if entry.st_uid != os.geteuid() or entry.st_mode & 0o022 or entry.st_nlink < 1:
                raise HarnessSafetyError("secret scan failed: unsafe artifact")
            continue
        if not stat.S_ISREG(entry.st_mode) or entry.st_nlink != 1:
            raise HarnessSafetyError("secret scan failed: unsafe artifact")
        try:
            if pinned_plan is not None:
                payload = _read_pinned_run_file(
                    pinned_plan,
                    path,
                    max_bytes=2_000_000_000,
                )
            else:
                before = _file_evidence(path)
                payload = path.read_bytes()
                after = _file_evidence(path)
                if before != after or before.get("sha256") != _hash_bytes(payload):
                    raise HarnessSafetyError("secret scan failed: changed artifact")
        except (HarnessSafetyError, OSError) as exc:
            raise HarnessSafetyError("secret scan failed: unreadable artifact") from exc
        total += len(payload)
        if total > 2_000_000_000:
            raise HarnessSafetyError("secret scan failed: artifact bound")
        if any(secret in payload for secret in encoded_secrets) or any(
            pattern.search(payload) is not None for pattern in _SECRET_PATTERNS
        ):
            role = path.relative_to(base).as_posix()
            raise HarnessSafetyError(f"secret scan failed: {role}")
        if payload.startswith(b"\x89PNG\r\n\x1a\n"):
            try:
                _validate_png_container(payload)
            except HarnessSafetyError as exc:
                raise HarnessSafetyError("secret scan failed: PNG metadata") from exc
    if pinned_plan is not None:
        assert_run_plan_identity(pinned_plan)


def _safe_assertions(value: object) -> bool:
    return bool(
        isinstance(value, list)
        and 1 <= len(value) <= 32
        and all(
            isinstance(item, str)
            and 1 <= len(item) <= 300
            and not any(character in "\r\n\x00" for character in item)
            for item in value
        )
    )


def _safe_entity_value(value: object, *, depth: int = 0) -> bool:
    if depth > 4:
        return False
    if value is None or type(value) in {bool, int}:
        return True
    if isinstance(value, str):
        return 1 <= len(value) <= 256 and not any(character in "\r\n\x00" for character in value)
    if isinstance(value, list):
        return len(value) <= 64 and all(_safe_entity_value(item, depth=depth + 1) for item in value)
    if isinstance(value, dict):
        return len(value) <= 64 and all(
            isinstance(key, str)
            and (
                re.fullmatch(r"[a-z][a-z0-9_]{0,63}", key) is not None
                or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", key) is not None
            )
            and _safe_entity_value(item, depth=depth + 1)
            for key, item in value.items()
        )
    return False


def _validate_png_container(payload: bytes) -> None:
    if not isinstance(payload, bytes) or not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise HarnessSafetyError("screenshot PNG container is invalid")
    allowed_chunks = {b"IHDR", b"PLTE", b"IDAT", b"IEND", b"cHRM", b"gAMA", b"pHYs", b"sRGB"}
    offset = 8
    chunks: list[bytes] = []
    while offset < len(payload):
        if len(chunks) >= 10_000 or offset + 12 > len(payload):
            raise HarnessSafetyError("screenshot PNG container is invalid")
        length = struct.unpack(">I", payload[offset : offset + 4])[0]
        chunk_type = payload[offset + 4 : offset + 8]
        end = offset + 12 + length
        if length > 100_000_000 or end > len(payload):
            raise HarnessSafetyError("screenshot PNG container is invalid")
        chunk_payload = payload[offset + 8 : offset + 8 + length]
        expected_crc = struct.unpack(">I", payload[offset + 8 + length : end])[0]
        if (
            re.fullmatch(rb"[A-Za-z]{4}", chunk_type) is None
            or zlib.crc32(chunk_type + chunk_payload) & 0xFFFFFFFF != expected_crc
        ):
            raise HarnessSafetyError("screenshot PNG container is invalid")
        if chunk_type not in allowed_chunks:
            raise HarnessSafetyError("screenshot PNG metadata is forbidden")
        chunks.append(chunk_type)
        offset = end
    if (
        offset != len(payload)
        or not chunks
        or chunks[0] != b"IHDR"
        or chunks[-1] != b"IEND"
        or chunks.count(b"IHDR") != 1
        or chunks.count(b"IEND") != 1
        or b"IDAT" not in chunks
    ):
        raise HarnessSafetyError("screenshot PNG container is invalid")


def _validated_screenshot(
    plan: RunPlan,
    item: Mapping[str, object],
    *,
    after_decode: Callable[[Path], None],
) -> dict[str, object]:
    expected_keys = {
        "journey_step",
        "relative_path",
        "semantic_name",
        "state_id",
        "surface",
        "viewport",
        "visible_assertions",
    }
    if set(item) != expected_keys:
        raise HarnessSafetyError("controller evidence screenshot shape is invalid")
    semantic = item["semantic_name"]
    state_id = item["state_id"]
    surface = item["surface"]
    viewport = item["viewport"]
    relative = item["relative_path"]
    if (
        not isinstance(semantic, str)
        or re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", semantic) is None
        or relative != f"screenshots/{semantic}.png"
        or not isinstance(state_id, str)
        or state_id not in REQUIRED_SCREENSHOT_STATES
        or semantic != state_id
        or not isinstance(surface, str)
        or (surface, item["journey_step"]) != REQUIRED_SCREENSHOT_STATES[state_id]
        or viewport not in APPROVED_VIEWPORTS[surface]
        or not _safe_assertions(item["visible_assertions"])
    ):
        raise HarnessSafetyError("controller evidence screenshot is invalid")
    path = plan.root / str(relative)
    assert_run_plan_identity(plan)
    if path.parent != plan.screenshots or not path.is_relative_to(plan.root):
        raise HarnessSafetyError("controller evidence screenshot path is invalid")
    try:
        initial_payload = _read_pinned_run_file(
            plan,
            path,
            max_bytes=100_000_000,
        )
    except HarnessSafetyError as exc:
        raise HarnessSafetyError("screenshot is unavailable or unsafe") from exc
    _validate_png_container(initial_payload)
    try:
        from PIL import Image

        with Image.open(io.BytesIO(initial_payload)) as image:
            image.load()
            decoded_format = image.format
            decoded_size = image.size
            extrema = image.convert("RGB").getextrema()
    except Exception as exc:
        raise HarnessSafetyError("screenshot cannot be decoded") from exc
    width, height = (int(part) for part in str(viewport).split("x"))
    if decoded_format != "PNG" or decoded_size != (width, height):
        raise HarnessSafetyError("screenshot dimensions do not match viewport")
    if all(low == high for low, high in extrema):
        raise HarnessSafetyError("screenshot is blank")
    after_decode(path)
    try:
        payload = _read_pinned_run_file(
            plan,
            path,
            max_bytes=100_000_000,
        )
    except HarnessSafetyError as exc:
        raise HarnessSafetyError("screenshot changed during validation") from exc
    if payload != initial_payload:
        raise HarnessSafetyError("screenshot changed during validation")
    assert_run_plan_identity(plan)
    return {
        **dict(item),
        "byte_size": len(payload),
        "sha256": _hash_bytes(payload),
        "source_run_id": plan.run_id,
    }


def validate_controller_evidence(
    plan: RunPlan,
    *,
    after_decode: Callable[[Path], None] = lambda _path: None,
) -> dict[str, object]:
    assert_run_plan_identity(plan)
    try:
        payload = _read_pinned_run_file(
            plan,
            plan.controller_evidence,
            max_bytes=10_000_000,
        )
        text = payload.decode("utf-8", errors="strict")
        value = json.loads(text)
    except (HarnessSafetyError, UnicodeError, ValueError) as exc:
        raise HarnessSafetyError("controller evidence is unavailable or invalid") from exc
    if (
        not isinstance(value, dict)
        or set(value) != _CONTROLLER_KEYS
        or canonical_json_line(value) != text
        or value["protocol"] != "pomegranagent-live-uat-controller/v1"
        or value["run_id"] != plan.run_id
        or value["source_head"] != plan.source_head
    ):
        raise HarnessSafetyError("controller evidence has an invalid top-level contract")
    journey = value["journey"]
    if not isinstance(journey, list):
        raise HarnessSafetyError("controller evidence journey is invalid")
    seen_steps = []
    for item in journey:
        if (
            not isinstance(item, dict)
            or set(item) != {"entity_ids", "status", "step_id", "visible_assertions"}
            or item["status"] != "PASS"
            or item["step_id"] not in REQUIRED_JOURNEY_STEPS
            or not _safe_assertions(item["visible_assertions"])
            or not isinstance(item["entity_ids"], dict)
            or not _safe_entity_value(item["entity_ids"])
        ):
            raise HarnessSafetyError("controller evidence journey is invalid")
        seen_steps.append(item["step_id"])
    if tuple(seen_steps) != REQUIRED_JOURNEY_STEPS:
        raise HarnessSafetyError("controller evidence journey is incomplete")
    screenshots = value["screenshots"]
    if not isinstance(screenshots, list) or not screenshots:
        raise HarnessSafetyError("controller evidence screenshots are invalid")
    validated_screenshots = [
        _validated_screenshot(plan, item, after_decode=after_decode)
        for item in screenshots
        if isinstance(item, Mapping)
    ]
    if len(validated_screenshots) != len(screenshots):
        raise HarnessSafetyError("controller evidence screenshots are invalid")
    semantic_names = [item["semantic_name"] for item in validated_screenshots]
    state_ids = [item["state_id"] for item in validated_screenshots]
    paths = [item["relative_path"] for item in validated_screenshots]
    if (
        len(set(semantic_names)) != len(semantic_names)
        or len(set(paths)) != len(paths)
        or len(set(state_ids)) != len(state_ids)
        or set(state_ids) != set(REQUIRED_SCREENSHOT_STATES)
    ):
        raise HarnessSafetyError("controller evidence screenshots contain duplicates")
    required_viewports = {value for values in APPROVED_VIEWPORTS.values() for value in values}
    if {item["viewport"] for item in validated_screenshots} != required_viewports:
        raise HarnessSafetyError("controller evidence screenshots omit an approved viewport")
    issues = value["issues"]
    if not isinstance(issues, list):
        raise HarnessSafetyError("controller evidence issues are invalid")
    for issue in issues:
        if (
            not isinstance(issue, dict)
            or set(issue) != {"safe_summary", "severity", "step_id"}
            or issue["severity"] not in {"low", "medium", "high", "blocker"}
            or issue["step_id"] not in REQUIRED_JOURNEY_STEPS
            or not isinstance(issue["safe_summary"], str)
            or not 1 <= len(issue["safe_summary"]) <= 300
        ):
            raise HarnessSafetyError("controller evidence issues are invalid")
    human = value["human_uat_required"]
    if not isinstance(human, list) or len(human) != 1:
        raise HarnessSafetyError("controller evidence human gate is invalid")
    for gate in human:
        if (
            not isinstance(gate, dict)
            or set(gate) != {"gate_id", "safe_summary", "status"}
            or gate["gate_id"] != "physical_microphone_acoustic_recognition"
            or gate["status"] != "HUMAN_UAT_REQUIRED"
            or not isinstance(gate["safe_summary"], str)
            or not 1 <= len(gate["safe_summary"]) <= 300
        ):
            raise HarnessSafetyError("controller evidence human gate is invalid")
    result = {
        **value,
        "screenshots": validated_screenshots,
    }
    assert_run_plan_identity(plan)
    return result


def _query_rows(
    connection: sqlite3.Connection,
    statement: str,
    parameters: tuple[object, ...] = (),
) -> list[list[object]]:
    rows = connection.execute(statement, parameters).fetchall()
    if len(rows) > 100_000:
        raise HarnessSafetyError("database provenance baseline is too large")
    return [list(row) for row in rows]


def capture_post_seed_baseline(plan: RunPlan) -> dict[str, object]:
    """Capture the canonical seed-only identity and reporting boundary."""

    assert_run_plan_identity(plan)
    before = _database_evidence(plan.database)
    try:
        with _sqlite_shadow(plan.database) as shadow, sqlite3.connect(
            f"{shadow.as_uri()}?mode=ro", uri=True
        ) as connection:
            connection.execute("PRAGMA query_only=ON")
            table_ids = {
                table: [
                    row[0]
                    for row in _query_rows(
                        connection,
                        f"SELECT {column} FROM {table} ORDER BY {column}",
                    )
                ]
                for table, column in _BASELINE_ID_COLUMNS.items()
            }
            dimensions = [
                {
                    "enabled": bool(row[3]),
                    "id": row[0],
                    "key": row[1],
                    "name": row[2],
                }
                for row in _query_rows(
                    connection,
                    "SELECT id, key, name, enabled FROM assessment_dimensions ORDER BY id",
                )
            ]
            reporting_source = {
                "analysis_jobs": _query_rows(
                    connection,
                    "SELECT id, conversation_id, frozen_last_message_id, status "
                    "FROM analysis_jobs ORDER BY id",
                ),
                "assessments": _query_rows(
                    connection,
                    "SELECT id, conversation_id, child_id, status, overall "
                    "FROM assessments ORDER BY id",
                ),
                "conversations": _query_rows(
                    connection,
                    "SELECT id, child_id, date, ended_at, status, frozen_last_message_id "
                    "FROM conversations ORDER BY id",
                ),
            }
    except HarnessSafetyError:
        raise
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        raise HarnessSafetyError("database provenance baseline failed") from exc
    after = _database_evidence(plan.database)
    if before != after:
        raise HarnessSafetyError("database provenance baseline changed retained database")
    result = {
        "dimensions": dimensions,
        "media_snapshot": _directory_evidence(plan.media),
        "protocol": "pomegranagent-live-uat-seed-baseline/v1",
        "reporting_source": reporting_source,
        "run_id": plan.run_id,
        "source_head": plan.source_head,
        "table_ids": table_ids,
        "tts_snapshot": _directory_evidence(plan.tts_cache),
    }
    assert_run_plan_identity(plan)
    return result


def _validated_seed_baseline(
    plan: RunPlan,
    baseline: Mapping[str, object],
) -> tuple[
    dict[str, set[object]],
    list[dict[str, object]],
    Mapping[str, object],
    set[str],
    set[str],
]:
    if (
        not isinstance(baseline, Mapping)
        or set(baseline)
        != {
            "dimensions",
            "media_snapshot",
            "protocol",
            "reporting_source",
            "run_id",
            "source_head",
            "table_ids",
            "tts_snapshot",
        }
        or baseline.get("protocol") != "pomegranagent-live-uat-seed-baseline/v1"
        or baseline.get("run_id") != plan.run_id
        or baseline.get("source_head") != plan.source_head
    ):
        raise HarnessSafetyError("database provenance baseline is invalid")
    raw_ids = baseline.get("table_ids")
    dimensions = baseline.get("dimensions")
    reporting = baseline.get("reporting_source")
    media_snapshot = baseline.get("media_snapshot")
    tts_snapshot = baseline.get("tts_snapshot")
    if (
        not isinstance(raw_ids, Mapping)
        or set(raw_ids) != set(_BASELINE_ID_COLUMNS)
        or not isinstance(dimensions, list)
        or not dimensions
        or not isinstance(reporting, Mapping)
        or set(reporting) != {"analysis_jobs", "assessments", "conversations"}
        or not isinstance(media_snapshot, Mapping)
        or not isinstance(tts_snapshot, Mapping)
    ):
        raise HarnessSafetyError("database provenance baseline is invalid")
    ids: dict[str, set[object]] = {}
    for table, values in raw_ids.items():
        if not isinstance(values, list) or len(values) != len(set(values)):
            raise HarnessSafetyError("database provenance baseline is invalid")
        ids[str(table)] = set(values)
    expected_dimension_keys = {"enabled", "id", "key", "name"}
    if any(
        not isinstance(item, dict)
        or set(item) != expected_dimension_keys
        or type(item["id"]) is not int
        or item["id"] <= 0
        or not isinstance(item["key"], str)
        or not item["key"]
        or not isinstance(item["name"], str)
        or not item["name"]
        or type(item["enabled"]) is not bool
        for item in dimensions
    ):
        raise HarnessSafetyError("database provenance baseline is invalid")
    def regular_names(snapshot: Mapping[str, object]) -> set[str]:
        entries = snapshot.get("entries")
        if not isinstance(entries, list):
            raise HarnessSafetyError("database provenance baseline is invalid")
        regular = [
            item
            for item in entries
            if isinstance(item, Mapping)
            and isinstance(item.get("snapshot"), Mapping)
            and item["snapshot"].get("kind") == "regular"
        ]
        names = {
            item.get("relative_path")
            for item in regular
            if isinstance(item.get("relative_path"), str)
        }
        if len(names) != len(regular):
            raise HarnessSafetyError("database provenance baseline is invalid")
        return {str(name) for name in names}

    return (
        ids,
        dimensions,
        reporting,
        regular_names(media_snapshot),
        regular_names(tts_snapshot),
    )


def _avatar_provenance(
    connection: sqlite3.Connection,
    plan: RunPlan,
    *,
    owner_table: str,
    owner_id: int,
    avatar_id: str,
) -> None:
    owner = connection.execute(
        f"SELECT avatar FROM {owner_table} WHERE id = ?", (owner_id,)
    ).fetchone()
    if owner != (f"/api/media/avatars/{avatar_id}",):
        raise HarnessSafetyError("database provenance avatar owner mismatch")
    row = connection.execute(
        "SELECT file_name, mime_type, width, height, size_bytes, sha256 "
        "FROM avatar_media WHERE id = ?",
        (avatar_id,),
    ).fetchone()
    if row is None or row[1] != "image/webp":
        raise HarnessSafetyError("database provenance avatar row mismatch")
    filename, _mime, width, height, size_bytes, expected_sha = row
    if (
        not isinstance(filename, str)
        or filename != f"{avatar_id}.webp"
        or not isinstance(width, int)
        or not isinstance(height, int)
        or width <= 0
        or height <= 0
    ):
        raise HarnessSafetyError("database provenance avatar metadata mismatch")
    path = plan.media / filename
    evidence = _file_evidence(path)
    if (
        evidence.get("kind") != "regular"
        or evidence.get("size") != size_bytes
        or evidence.get("sha256") != expected_sha
    ):
        raise HarnessSafetyError("database provenance avatar file mismatch")
    try:
        from PIL import Image

        with Image.open(path) as image:
            image.load()
            decoded = (image.format, image.size)
    except Exception as exc:
        raise HarnessSafetyError("database provenance avatar decode failed") from exc
    if decoded != ("WEBP", (width, height)):
        raise HarnessSafetyError("database provenance avatar decode mismatch")


def _weekly_metrics_from_source(
    *,
    conversations: list[list[object]],
    assessments: list[list[object]],
    analysis_jobs: list[list[object]],
    week_start: date,
) -> dict[str, object]:
    week_end = date.fromordinal(week_start.toordinal() + 7)
    weekly = {
        row[0]: row
        for row in conversations
        if (
            len(row) == 6
            and row[4] == "ended"
            and row[3] is not None
            and type(row[5]) is int
            and week_start.isoformat() <= row[2] < week_end.isoformat()
        )
    }
    assessments_by_conversation = {
        row[1]: row for row in assessments if len(row) == 5
    }
    jobs_by_conversation = {row[1]: row for row in analysis_jobs if len(row) == 4}
    pending_total = 0
    for assessment in assessments:
        if len(assessment) != 5 or assessment[3] not in {"pending", "draft"}:
            continue
        conversation = next((row for row in conversations if row[0] == assessment[1]), None)
        job = jobs_by_conversation.get(assessment[1])
        if (
            conversation is not None
            and len(conversation) == 6
            and conversation[4] == "ended"
            and type(conversation[5]) is int
            and job is not None
            and job[2] == conversation[5]
            and job[3] == "succeeded"
        ):
            pending_total += 1
    return {
        "completed_conversations": len(weekly),
        "confirmed_reviews": sum(
            assessments_by_conversation.get(conversation_id, [None] * 4)[3] == "confirmed"
            for conversation_id in weekly
        ),
        "failed_analyses": sum(
            jobs_by_conversation.get(conversation_id, [None] * 4)[2] == row[5]
            and jobs_by_conversation.get(conversation_id, [None] * 4)[3] == "failed"
            for conversation_id, row in weekly.items()
        ),
        "participating_children": len({row[1] for row in weekly.values()}),
        "pending_reviews_total": pending_total,
        "timezone": "Asia/Shanghai",
        "week_end_exclusive": week_end.isoformat(),
        "week_start": week_start.isoformat(),
    }


def _database_reporting_source(connection: sqlite3.Connection) -> dict[str, list[list[object]]]:
    return {
        "analysis_jobs": _query_rows(
            connection,
            "SELECT id, conversation_id, frozen_last_message_id, status FROM analysis_jobs ORDER BY id",
        ),
        "assessments": _query_rows(
            connection,
            "SELECT id, conversation_id, child_id, status, overall FROM assessments ORDER BY id",
        ),
        "conversations": _query_rows(
            connection,
            "SELECT id, child_id, date, ended_at, status, frozen_last_message_id FROM conversations ORDER BY id",
        ),
    }


def _growth_projection(
    connection: sqlite3.Connection,
    *,
    child_id: int,
    enabled_dimensions: list[dict[str, object]],
) -> dict[str, list[dict[str, object]]]:
    projection = {str(item["key"]): [] for item in enabled_dimensions}
    names_by_id = {int(item["id"]): str(item["key"]) for item in enabled_dimensions}
    rows = connection.execute(
        "SELECT a.id, c.date, s.dimension_id, s.score "
        "FROM assessments a JOIN conversations c ON c.id = a.conversation_id "
        "JOIN assessment_scores s ON s.assessment_id = a.id "
        "WHERE a.child_id = ? AND a.status = 'confirmed' ORDER BY a.id, s.dimension_id",
        (child_id,),
    ).fetchall()
    for _assessment_id, conversation_date, dimension_id, score in rows:
        key = names_by_id.get(dimension_id)
        if key is not None:
            projection[key].append({"date": conversation_date, "score": score})
    return projection


def _decode_search_cursor(
    cursor: object,
    *,
    search_request: Mapping[str, object],
) -> dict[str, object]:
    try:
        if not isinstance(cursor, str) or not 1 <= len(cursor) <= 2048 or re.fullmatch(r"[A-Za-z0-9_-]+", cursor) is None:
            raise ValueError
        padded = cursor + "=" * ((4 - len(cursor) % 4) % 4)
        raw = base64.b64decode(padded.encode("ascii"), altchars=b"-_", validate=True)
        if base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=") != cursor:
            raise ValueError
        value = json.loads(raw.decode("utf-8", errors="strict"))
        if (
            not isinstance(value, dict)
            or set(value) != {"ended_at", "fingerprint", "id", "snapshot_max_id", "sort", "version"}
            or canonical_json_line(value).encode("utf-8")[:-1] != raw
            or value["version"] != 1
            or type(value["id"]) is not int
            or type(value["snapshot_max_id"]) is not int
            or value["id"] <= 0
            or value["snapshot_max_id"] < value["id"]
            or value["sort"] != search_request.get("sort")
        ):
            raise ValueError
        fingerprint_source = {
            "analysis_status": sorted(search_request["analysis_status"]),
            "child_id": search_request["child_id"],
            "date_from": search_request["date_from"],
            "date_to": search_request["date_to"],
            "end_reason": sorted(search_request["end_reason"]),
            "keyword": search_request["keyword"],
            "review_status": sorted(search_request["review_status"]),
            "sort": search_request["sort"],
        }
        expected_fingerprint = _hash_bytes(
            json.dumps(
                fingerprint_source,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        if value["fingerprint"] != expected_fingerprint:
            raise ValueError
        datetime.strptime(value["ended_at"], "%Y-%m-%dT%H:%M:%S.%fZ")
        return value
    except (KeyError, TypeError, ValueError, UnicodeError):
        raise HarnessSafetyError("database provenance search cursor mismatch") from None


def validate_database_provenance(
    plan: RunPlan,
    entity_ids: Mapping[str, object],
    baseline: Mapping[str, object],
) -> dict[str, object]:
    assert_run_plan_identity(plan)
    if set(entity_ids) != _PROVENANCE_KEYS:
        raise HarnessSafetyError("database provenance identifiers are incomplete")
    (
        baseline_ids,
        baseline_dimensions,
        baseline_reporting,
        baseline_media_files,
        baseline_tts_files,
    ) = _validated_seed_baseline(plan, baseline)
    before = _database_evidence(plan.database)
    try:
        with _sqlite_shadow(plan.database) as shadow, sqlite3.connect(
            f"{shadow.as_uri()}?mode=ro", uri=True
        ) as connection:
            connection.execute("PRAGMA query_only=ON")
            if connection.execute("PRAGMA query_only").fetchone() != (1,):
                raise HarnessSafetyError("database provenance connection is not read-only")
            child_id = entity_ids["live_child_id"]
            duck_id = entity_ids["live_duck_id"]
            conversation_id = entity_ids["live_conversation_id"]
            job_id = entity_ids["analysis_job_id"]
            assessment_id = entity_ids["assessment_id"]
            if any(type(value) is not int or value <= 0 for value in (child_id, duck_id, conversation_id, job_id, assessment_id)):
                raise HarnessSafetyError("database provenance identifiers are invalid")
            new_numeric_ids = (
                ("children", child_id),
                ("ducks", duck_id),
                ("conversations", conversation_id),
                ("analysis_jobs", job_id),
                ("assessments", assessment_id),
            )
            if any(value in baseline_ids[table] for table, value in new_numeric_ids):
                raise HarnessSafetyError("database provenance reused a seed entity")
            for avatar_id in (entity_ids["child_avatar_id"], entity_ids["duck_avatar_id"]):
                if (
                    not isinstance(avatar_id, str)
                    or UUID4_PATTERN.fullmatch(avatar_id) is None
                    or avatar_id in baseline_ids["avatar_media"]
                    or f"{avatar_id}.webp" in baseline_media_files
                ):
                    raise HarnessSafetyError("database provenance avatar id is invalid")
            _avatar_provenance(
                connection,
                plan,
                owner_table="children",
                owner_id=child_id,
                avatar_id=entity_ids["child_avatar_id"],
            )
            _avatar_provenance(
                connection,
                plan,
                owner_table="ducks",
                owner_id=duck_id,
                avatar_id=entity_ids["duck_avatar_id"],
            )
            monthly = entity_ids["monthly_pairs"]
            if not isinstance(monthly, dict) or len(monthly) < 2:
                raise HarnessSafetyError("database provenance monthly roster is invalid")
            for roster_date, expected_children in monthly.items():
                if (
                    not isinstance(roster_date, str)
                    or not isinstance(expected_children, list)
                    or len(expected_children) != 2
                    or len(set(expected_children)) != 2
                    or child_id not in expected_children
                    or any(type(value) is not int or value <= 0 for value in expected_children)
                ):
                    raise HarnessSafetyError("database provenance monthly roster is invalid")
                date.fromisoformat(roster_date)
                actual_rows = connection.execute(
                    "SELECT id, child_id FROM duty_rosters WHERE date = ? ORDER BY child_id",
                    (roster_date,),
                ).fetchall()
                actual = [
                    row[1]
                    for row in actual_rows
                ]
                if any(
                    row[0] in baseline_ids["duty_rosters"]
                    for row in actual_rows
                ):
                    raise HarnessSafetyError("database provenance reused a seed roster row")
                if actual != sorted(expected_children):
                    raise HarnessSafetyError("database provenance monthly roster mismatch")
            attempts = entity_ids["monthly_roster_attempts"]
            if (
                not isinstance(attempts, list)
                or len(attempts) != 2
                or attempts[0]
                != {
                    "http_status": 409,
                    "outcome": "ROSTER_DATE_CONFLICT",
                    "request_id": attempts[0].get("request_id") if isinstance(attempts[0], dict) else None,
                }
                or attempts[1]
                != {
                    "http_status": 200,
                    "outcome": "SUCCEEDED",
                    "request_id": attempts[1].get("request_id") if isinstance(attempts[1], dict) else None,
                }
            ):
                raise HarnessSafetyError("database provenance roster retry evidence is invalid")
            conflict_request_id = attempts[0]["request_id"]
            retry_request_id = attempts[1]["request_id"]
            if (
                not isinstance(conflict_request_id, str)
                or not isinstance(retry_request_id, str)
                or UUID4_PATTERN.fullmatch(conflict_request_id) is None
                or UUID4_PATTERN.fullmatch(retry_request_id) is None
                or conflict_request_id == retry_request_id
                or conflict_request_id in baseline_ids["roster_requests"]
                or retry_request_id in baseline_ids["roster_requests"]
                or connection.execute(
                    "SELECT 1 FROM roster_requests WHERE request_id = ?",
                    (conflict_request_id,),
                ).fetchone()
                is not None
            ):
                raise HarnessSafetyError("database provenance roster retry identity mismatch")
            retry_row = connection.execute(
                "SELECT operation, status, response_json, last_error_code, last_error_message "
                "FROM roster_requests WHERE request_id = ?",
                (retry_request_id,),
            ).fetchone()
            try:
                retry_response = json.loads(retry_row[2]) if retry_row is not None else None
            except (TypeError, ValueError):
                retry_response = None
            schedule = retry_response.get("schedule") if isinstance(retry_response, dict) else None
            cycles = {
                item.get("cycle")
                for item in schedule
                if isinstance(schedule, list) and isinstance(item, dict)
            } if isinstance(schedule, list) else set()
            expected_schedule = [
                {
                    "child_ids": sorted(expected_children),
                    "cycle": next(iter(cycles)) if len(cycles) == 1 else None,
                    "date": roster_date,
                }
                for roster_date, expected_children in sorted(monthly.items())
            ]
            if (
                retry_row is None
                or retry_row[:2] != ("monthly_roster", "succeeded")
                or retry_row[3:] != (None, None)
                or not isinstance(retry_response, dict)
                or retry_response.get("request_id") != retry_request_id
                or retry_response.get("replayed") is not False
                or len(cycles) != 1
                or not isinstance(next(iter(cycles)), str)
                or not next(iter(cycles))
                or retry_response.get("schedule") != expected_schedule
            ):
                raise HarnessSafetyError("database provenance roster retry mismatch")
            conversation = connection.execute(
                "SELECT child_id, date, ended_at, status, end_reason, frozen_last_message_id "
                "FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
            if (
                conversation is None
                or conversation[0] != child_id
                or conversation[2] is None
                or conversation[3] != "ended"
                or conversation[4] not in {"complete", "manual", "max_rounds"}
                or type(conversation[5]) is not int
            ):
                raise HarnessSafetyError("database provenance conversation mismatch")
            messages = connection.execute(
                "SELECT id, role, text FROM messages WHERE conversation_id = ? ORDER BY id",
                (conversation_id,),
            ).fetchall()
            if (
                len(messages) < 6
                or len(messages) % 2
                or messages[-1][0] != conversation[5]
                or any(row[0] in baseline_ids["messages"] for row in messages)
                or [row[1] for row in messages] != ["child", "diary"] * (len(messages) // 2)
                or any(not isinstance(row[2], str) or not row[2].strip() for row in messages)
            ):
                raise HarnessSafetyError("database provenance frozen messages mismatch")
            tts_evidence = entity_ids["tts_evidence"]
            if (
                not isinstance(tts_evidence, Mapping)
                or set(tts_evidence)
                != {
                    "audio_sha256",
                    "cache_relative_path",
                    "source_message_id",
                    "text_sha256",
                }
                or tts_evidence["source_message_id"] != messages[-1][0]
                or tts_evidence["text_sha256"]
                != _hash_bytes(messages[-1][2].encode("utf-8"))
                or not isinstance(tts_evidence["audio_sha256"], str)
                or SHA256_PATTERN.fullmatch(tts_evidence["audio_sha256"]) is None
                or tts_evidence["cache_relative_path"]
                != "tts-cache/"
                + hashlib.md5(messages[-1][2].encode("utf-8"), usedforsecurity=False).hexdigest()
                + ".mp3"
                or str(tts_evidence["cache_relative_path"]).removeprefix("tts-cache/")
                in baseline_tts_files
            ):
                raise HarnessSafetyError("database provenance TTS source mismatch")
            chat_request_ids = entity_ids["chat_request_ids"]
            if (
                not isinstance(chat_request_ids, list)
                or len(chat_request_ids) != len(messages) // 2
                or len(set(chat_request_ids)) != len(chat_request_ids)
                or any(
                    not isinstance(value, str)
                    or UUID4_PATTERN.fullmatch(value) is None
                    or value in baseline_ids["chat_requests"]
                    for value in chat_request_ids
                )
            ):
                raise HarnessSafetyError("database provenance chat request identities are invalid")
            for index, request_id in enumerate(chat_request_ids):
                child_message = messages[index * 2]
                diary_message = messages[index * 2 + 1]
                request = connection.execute(
                    "SELECT child_id, conversation_id, base_last_message_id, child_message_id, "
                    "diary_message_id, status, attempt_count, response_json FROM chat_requests "
                    "WHERE request_id = ?",
                    (request_id,),
                ).fetchone()
                expected_base = None if index == 0 else messages[index * 2 - 1][0]
                if (
                    request is None
                    or request[:6]
                    != (
                        child_id,
                        conversation_id,
                        expected_base,
                        child_message[0],
                        diary_message[0],
                        "succeeded",
                    )
                    or type(request[6]) is not int
                    or request[6] < 1
                ):
                    raise HarnessSafetyError("database provenance chat request mismatch")
                try:
                    response = json.loads(request[7])
                except (TypeError, ValueError) as exc:
                    raise HarnessSafetyError("database provenance chat response mismatch") from exc
                if (
                    not isinstance(response, dict)
                    or response.get("conversation_id") != conversation_id
                    or response.get("diary_message_id") != diary_message[0]
                    or response.get("reply") != diary_message[2]
                ):
                    raise HarnessSafetyError("database provenance chat response mismatch")
            jobs = connection.execute(
                "SELECT id, frozen_last_message_id, status, attempt_count FROM analysis_jobs "
                "WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchall()
            job = jobs[0] if len(jobs) == 1 else None
            if (
                job is None
                or job[:3] != (job_id, conversation[5], "succeeded")
                or type(job[3]) is not int
                or job[3] < 1
            ):
                raise HarnessSafetyError("database provenance analysis mismatch")
            assessment = connection.execute(
                "SELECT conversation_id, child_id, status, overall FROM assessments WHERE id = ?",
                (assessment_id,),
            ).fetchone()
            if (
                assessment is None
                or assessment[:3] != (conversation_id, child_id, "confirmed")
                or not isinstance(assessment[3], (int, float))
                or not math.isfinite(assessment[3])
            ):
                raise HarnessSafetyError("database provenance review mismatch")
            feeding = connection.execute(
                "SELECT id, child_id, duck_id, category, content FROM feeding_logs WHERE conversation_id = ? ORDER BY id",
                (conversation_id,),
            ).fetchall()
            emotion = connection.execute(
                "SELECT id, child_id, emotion, intensity, note FROM emotion_logs WHERE conversation_id = ? ORDER BY id",
                (conversation_id,),
            ).fetchall()
            insight = connection.execute(
                "SELECT id, child_id, content FROM insight_notes WHERE conversation_id = ? ORDER BY id",
                (conversation_id,),
            ).fetchall()
            if (
                not feeding
                or not any(row[2] == duck_id for row in feeding)
                or any(
                    row[0] in baseline_ids["feeding_logs"]
                    or row[1] != child_id
                    or row[3] not in {"喂食", "清洁", "观察", "其它"}
                    or not isinstance(row[4], str)
                    or not row[4].strip()
                    for row in feeding
                )
                or len(emotion) != 1
                or emotion[0][0] in baseline_ids["emotion_logs"]
                or emotion[0][1] != child_id
                or not isinstance(emotion[0][2], str)
                or not emotion[0][2].strip()
                or type(emotion[0][3]) is not int
                or not 1 <= emotion[0][3] <= 5
                or len(insight) != 1
                or insight[0][0] in baseline_ids["insight_notes"]
                or insight[0][1] != child_id
                or not isinstance(insight[0][2], str)
                or not insight[0][2].strip()
            ):
                raise HarnessSafetyError("database provenance analysis projection mismatch")
            current_dimensions = [
                {"enabled": bool(row[3]), "id": row[0], "key": row[1], "name": row[2]}
                for row in connection.execute(
                    "SELECT id, key, name, enabled FROM assessment_dimensions ORDER BY id"
                ).fetchall()
            ]
            if current_dimensions != baseline_dimensions:
                raise HarnessSafetyError("database provenance dimension boundary changed")
            enabled_dimensions = [item for item in baseline_dimensions if item["enabled"]]
            scores = connection.execute(
                "SELECT id, dimension_id, score, reason FROM assessment_scores "
                "WHERE assessment_id = ? ORDER BY dimension_id",
                (assessment_id,),
            ).fetchall()
            if (
                not enabled_dimensions
                or {row[1] for row in scores} != {item["id"] for item in enabled_dimensions}
                or any(
                    row[0] in baseline_ids["assessment_scores"]
                    or type(row[2]) is not int
                    or not 1 <= row[2] <= 5
                    or not row[3]
                    for row in scores
                )
                or not math.isclose(
                    float(assessment[3]),
                    sum(row[2] for row in scores) / len(scores),
                    rel_tol=1e-9,
                    abs_tol=1e-9,
                )
            ):
                raise HarnessSafetyError("database provenance score mismatch")
            try:
                week_start = date.fromisoformat(entity_ids["weekly_week_start"])
                conversation_date = date.fromisoformat(conversation[1])
            except (TypeError, ValueError) as exc:
                raise HarnessSafetyError("database provenance week mismatch") from exc
            if week_start.weekday() != 0 or not week_start <= conversation_date < date.fromordinal(week_start.toordinal() + 7):
                raise HarnessSafetyError("database provenance week mismatch")
            baseline_metrics = _weekly_metrics_from_source(
                conversations=baseline_reporting["conversations"],
                assessments=baseline_reporting["assessments"],
                analysis_jobs=baseline_reporting["analysis_jobs"],
                week_start=week_start,
            )
            final_source = _database_reporting_source(connection)
            final_metrics = _weekly_metrics_from_source(
                conversations=final_source["conversations"],
                assessments=final_source["assessments"],
                analysis_jobs=final_source["analysis_jobs"],
                week_start=week_start,
            )
            if (
                entity_ids["weekly_metrics_before"] != baseline_metrics
                or entity_ids["weekly_metrics_after"] != final_metrics
                or final_metrics["completed_conversations"] != baseline_metrics["completed_conversations"] + 1
                or final_metrics["confirmed_reviews"] != baseline_metrics["confirmed_reviews"] + 1
                or final_metrics["participating_children"] != baseline_metrics["participating_children"] + 1
                or final_metrics["failed_analyses"] != baseline_metrics["failed_analyses"]
            ):
                raise HarnessSafetyError("database provenance weekly contribution mismatch")
            expected_growth_before = {str(item["key"]): [] for item in enabled_dimensions}
            expected_growth_after = _growth_projection(
                connection,
                child_id=child_id,
                enabled_dimensions=enabled_dimensions,
            )
            if (
                entity_ids["growth_before"] != expected_growth_before
                or entity_ids["growth_after"] != expected_growth_after
                or any(len(points) != 1 for points in expected_growth_after.values())
            ):
                raise HarnessSafetyError("database provenance growth contribution mismatch")
            page_one = entity_ids["search_page_one_ids"]
            page_two = entity_ids["search_page_two_ids"]
            result_id = entity_ids["search_result_conversation_id"]
            if (
                not isinstance(page_one, list)
                or not isinstance(page_two, list)
                or not page_one
                or not page_two
                or any(type(value) is not int or value <= 0 for value in page_one + page_two)
                or set(page_one) & set(page_two)
                or result_id != conversation_id
                or result_id not in set(page_one + page_two)
            ):
                raise HarnessSafetyError("database provenance search mismatch")
            placeholders = ",".join("?" for _ in page_one + page_two)
            search_rows = connection.execute(
                f"SELECT id, child_id, date, ended_at, status, end_reason, frozen_last_message_id "
                f"FROM conversations WHERE id IN ({placeholders})",
                tuple(page_one + page_two),
            ).fetchall()
            if len(search_rows) != len(set(page_one + page_two)) or any(row[4] != "ended" for row in search_rows):
                raise HarnessSafetyError("database provenance search rows mismatch")
            search_request = entity_ids["search_request"]
            if (
                not isinstance(search_request, Mapping)
                or set(search_request)
                != {"analysis_status", "child_id", "date_from", "date_to", "end_reason", "keyword", "review_status", "sort"}
                or search_request["analysis_status"] != ["succeeded"]
                or search_request["review_status"] != ["confirmed"]
                or search_request["end_reason"] != [conversation[4]]
                or search_request["sort"] not in {"completed_asc", "completed_desc"}
                or search_request["child_id"] not in {None, child_id}
                or not isinstance(search_request["keyword"], str)
                or not search_request["keyword"].strip()
                or not search_request["date_from"] <= conversation[1] <= search_request["date_to"]
            ):
                raise HarnessSafetyError("database provenance search request mismatch")
            keyword_hit = connection.execute(
                "SELECT 1 FROM messages WHERE conversation_id = ? AND instr(text, ?) > 0 LIMIT 1",
                (conversation_id, search_request["keyword"]),
            ).fetchone()
            cursor = _decode_search_cursor(
                entity_ids["search_cursor"],
                search_request=search_request,
            )
            search_by_id = {row[0]: row for row in search_rows}
            for search_id in page_one + page_two:
                row = search_by_id[search_id]
                job_status = connection.execute(
                    "SELECT status FROM analysis_jobs WHERE conversation_id = ? "
                    "AND frozen_last_message_id = ?",
                    (search_id, row[6]),
                ).fetchone()
                review_status = connection.execute(
                    "SELECT status FROM assessments WHERE conversation_id = ?",
                    (search_id,),
                ).fetchone()
                row_keyword = connection.execute(
                    "SELECT 1 FROM messages WHERE conversation_id = ? AND instr(text, ?) > 0 LIMIT 1",
                    (search_id, search_request["keyword"]),
                ).fetchone()
                if (
                    row[5] not in search_request["end_reason"]
                    or search_request["child_id"] not in {None, row[1]}
                    or not search_request["date_from"] <= row[2] <= search_request["date_to"]
                    or job_status is None
                    or job_status[0] not in search_request["analysis_status"]
                    or review_status is None
                    or review_status[0] not in search_request["review_status"]
                    or row_keyword is None
                ):
                    raise HarnessSafetyError("database provenance search result mismatch")
            expected_cursor_time = str(search_by_id[page_one[-1]][3]) + "Z"
            flattened = page_one + page_two
            expected_order = sorted(
                flattened,
                key=lambda value: (search_by_id[value][3], value),
                reverse=search_request["sort"] == "completed_desc",
            )
            if (
                keyword_hit is None
                or cursor["id"] != page_one[-1]
                or cursor["ended_at"] != expected_cursor_time
                or cursor["snapshot_max_id"] != max(flattened)
                or flattened != expected_order
                or entity_ids["search_deep_link"] != f"#review?conversation_id={conversation_id}"
            ):
                raise HarnessSafetyError("database provenance frozen search mismatch")
    except HarnessSafetyError:
        raise
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        raise HarnessSafetyError("database provenance validation failed") from exc
    after = _database_evidence(plan.database)
    if before != after:
        raise HarnessSafetyError("database provenance validation changed retained database")
    result = {
        "analysis_job_id": entity_ids["analysis_job_id"],
        "assessment_id": entity_ids["assessment_id"],
        "conversation_id": entity_ids["live_conversation_id"],
        "score_count": len([item for item in baseline_dimensions if item["enabled"]]),
        "search_result_id": entity_ids["search_result_conversation_id"],
        "status": "PROVEN",
    }
    assert_run_plan_identity(plan)
    return result


def parse_seed_result(payload: bytes, plan: RunPlan) -> dict[str, object]:
    try:
        text = payload.decode("utf-8", errors="strict")
        lines = text.splitlines()
        if len(lines) != 1 or not lines[0]:
            raise ValueError
        value = json.loads(lines[0])
    except (UnicodeError, ValueError, TypeError) as exc:
        raise HarnessSafetyError("seed result is not one strict JSON object") from exc
    expected_keys = {
        "archive_directory",
        "database_path",
        "log_path",
        "media_root",
        "media_sha256",
        "record_sha256",
    }
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise HarnessSafetyError("seed result has an unsupported shape")
    if (
        value["archive_directory"] is not None
        or value["database_path"] != str(plan.database)
        or value["media_root"] != str(plan.media)
        or value["log_path"] != str(plan.app_log)
        or not isinstance(value["record_sha256"], str)
        or SHA256_PATTERN.fullmatch(value["record_sha256"]) is None
        or not isinstance(value["media_sha256"], str)
        or SHA256_PATTERN.fullmatch(value["media_sha256"]) is None
    ):
        raise HarnessSafetyError("seed result does not match the authorized run")
    return value


def _ensure_run_directory(
    path: Path,
    *,
    label: str,
    pinned_plan: RunPlan,
) -> None:
    parent_descriptor, name = _open_plan_parent(pinned_plan, path)
    try:
        descriptor = _open_or_create_owned_child_directory(
            parent_descriptor,
            name,
            label=label,
        )
        os.close(descriptor)
    finally:
        os.close(parent_descriptor)
    assert_run_plan_identity(pinned_plan)


def _write_owned_bytes(
    path: Path,
    payload: bytes,
    *,
    pinned_plan: RunPlan,
) -> None:
    if not isinstance(payload, bytes):
        raise HarnessSafetyError("evidence payload is invalid")
    destination = _absolute(path)
    parent_descriptor, destination_name = _open_plan_parent(pinned_plan, destination)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = None
    try:
        descriptor = os.open(
            destination_name,
            flags,
            0o600,
            dir_fd=parent_descriptor,
        )
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise OSError("short write")
            offset += written
        os.fsync(descriptor)
    except OSError as exc:
        raise HarnessSafetyError("evidence file could not be created safely") from exc
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        os.close(parent_descriptor)
    assert_run_plan_identity(pinned_plan)


def _collect_entity_ids(controller: Mapping[str, object]) -> dict[str, object]:
    combined: dict[str, object] = {}
    journey = controller.get("journey")
    if not isinstance(journey, list):
        raise HarnessSafetyError("controller entity identifiers are incomplete")
    for step in journey:
        if not isinstance(step, Mapping) or not isinstance(step.get("entity_ids"), Mapping):
            raise HarnessSafetyError("controller entity identifiers are incomplete")
        for key, value in step["entity_ids"].items():
            if key in combined:
                raise HarnessSafetyError("controller entity identifiers contain duplicates")
            combined[key] = value
    if set(combined) != _PROVENANCE_KEYS:
        raise HarnessSafetyError("controller entity identifiers are incomplete")
    return combined


def _validate_provider_completion(
    events: tuple[Mapping[str, object], ...],
    *,
    plan: RunPlan,
    provider: Mapping[str, object],
    entity_ids: Mapping[str, object],
) -> dict[str, object]:
    summary = summarize_provider_events(events)
    selected = _canonical_provider_values(provider)
    conversation_id = entity_ids.get("live_conversation_id")
    analysis_job_id = entity_ids.get("analysis_job_id")
    chat_request_ids = entity_ids.get("chat_request_ids")
    tts_evidence = entity_ids.get("tts_evidence")
    if (
        type(conversation_id) is not int
        or conversation_id <= 0
        or type(analysis_job_id) is not int
        or analysis_job_id <= 0
        or not isinstance(chat_request_ids, list)
        or not chat_request_ids
        or not isinstance(tts_evidence, Mapping)
    ):
        raise HarnessSafetyError("provider telemetry is incomplete")
    expected_correlations = {
        "chat_reply": f"conversation:{conversation_id}",
        "extract_info": f"analysis-job:{analysis_job_id}",
        "assess_conversation": f"analysis-job:{analysis_job_id}",
        "tts": f"message-text:{tts_evidence.get('text_sha256')}",
    }
    counts = {operation: 0 for operation in expected_correlations}
    for event in summary["events"]:
        operation = event["operation"]
        if (
            event["status"] != "ok"
            or event["correlation_id"] != expected_correlations[operation]
        ):
            raise HarnessSafetyError("provider telemetry is incomplete or unrelated")
        if operation == "tts":
            if (
                event["voice"] != "zh-CN-XiaoxiaoNeural"
                or event["cache_relative_path"] != tts_evidence.get("cache_relative_path")
                or event["cache_sha256"] != tts_evidence.get("audio_sha256")
            ):
                raise HarnessSafetyError("provider telemetry TTS evidence mismatch")
        elif event["model"] != selected["DEEPSEEK_MODEL"] or event["parse_valid"] is not True:
            raise HarnessSafetyError("provider telemetry model or parse boundary mismatch")
        counts[operation] += 1
    if counts != {
        "chat_reply": len(chat_request_ids),
        "extract_info": 1,
        "assess_conversation": 1,
        "tts": 1,
    }:
        raise HarnessSafetyError("provider telemetry is incomplete")
    cache_relative = tts_evidence.get("cache_relative_path")
    if not isinstance(cache_relative, str):
        raise HarnessSafetyError("provider telemetry TTS evidence mismatch")
    cache_path = plan.root / cache_relative
    if cache_path.parent != plan.tts_cache:
        raise HarnessSafetyError("provider telemetry TTS evidence mismatch")
    cache = _file_evidence(cache_path)
    tts_event = next(event for event in summary["events"] if event["operation"] == "tts")
    if (
        cache.get("kind") != "regular"
        or cache.get("size") != tts_event["audio_bytes"]
        or cache.get("sha256") != tts_event["cache_sha256"]
    ):
        raise HarnessSafetyError("provider telemetry TTS cache mismatch")
    return summary


def _checksum_lines(plan: RunPlan, manifest_payload: bytes) -> bytes:
    assert_run_plan_identity(plan)
    entries: list[tuple[str, str]] = []
    try:
        candidates = sorted(
            plan.root.rglob("*"),
            key=lambda item: item.relative_to(plan.root).as_posix(),
        )
    except OSError as exc:
        raise HarnessSafetyError("checksum inventory failed") from exc
    for candidate in candidates:
        relative = candidate.relative_to(plan.root).as_posix()
        if candidate in {plan.checksums, plan.manifest}:
            continue
        try:
            entry = candidate.lstat()
        except OSError as exc:
            raise HarnessSafetyError("checksum inventory failed") from exc
        if stat.S_ISDIR(entry.st_mode) and not stat.S_ISLNK(entry.st_mode):
            if entry.st_uid != os.geteuid() or entry.st_mode & 0o022 or entry.st_nlink < 1:
                raise HarnessSafetyError("checksum inventory contains an unsafe artifact")
            continue
        if not stat.S_ISREG(entry.st_mode) or entry.st_nlink != 1:
            raise HarnessSafetyError("checksum inventory contains an unsafe artifact")
        try:
            payload = _read_pinned_run_file(
                plan,
                candidate,
                max_bytes=2_000_000_000,
            )
        except HarnessSafetyError as exc:
            raise HarnessSafetyError("checksum artifact changed during hashing") from exc
        entries.append((_hash_bytes(payload), relative))
    entries.append((_hash_bytes(manifest_payload), plan.manifest.name))
    entries.sort(key=lambda item: item[1])
    result = "".join(f"{digest}  {relative}\n" for digest, relative in entries).encode(
        "utf-8"
    )
    assert_run_plan_identity(plan)
    return result


def _complete_manifest(
    plan: RunPlan,
    *,
    seed_result: Mapping[str, object],
    controller: Mapping[str, object],
    provider_summary: Mapping[str, object],
    provenance: Mapping[str, object],
) -> dict[str, object]:
    issues = controller.get("issues")
    if not isinstance(issues, list) or any(
        isinstance(issue, Mapping) and issue.get("severity") == "blocker"
        for issue in issues
    ):
        raise HarnessSafetyError("complete manifest cannot contain a blocker issue")
    return {
        "database_provenance": dict(provenance),
        "human_uat_required": controller["human_uat_required"],
        "issues_count": len(issues),
        "protocol": "pomegranagent-live-uat-manifest/v1",
        "provider_event_count": len(provider_summary["events"]),
        "release": dict(FROZEN_RELEASE),
        "run_id": plan.run_id,
        "screenshots": controller["screenshots"],
        "seed": {
            "media_sha256": seed_result["media_sha256"],
            "record_sha256": seed_result["record_sha256"],
        },
        "source_head": plan.source_head,
        "status": "COMPLETE",
    }


def execute_retained_uat(
    *,
    repository: Path,
    expected_head: str,
    allowed_unrelated_dirty_paths: tuple[str, ...] = (),
    environ: Mapping[str, str],
    dotenv_values: Mapping[str, object],
    input_stream,
    output_stream,
    python_executable: str,
    now: Callable[[], datetime] = _default_now,
    nonce: Callable[[], str] = _default_nonce,
    business_today: Callable[[], date],
    capture_resources: Callable[[Path], Mapping[str, object]] = capture_protected_resources,
    seed_runner: Callable[..., Mapping[str, object]],
    server_starter: Callable[..., object],
    readiness_probe: Callable[[object], tuple[object, object, object, object]],
    server_finisher: Callable[[object], tuple[Mapping[str, object], ...]],
    controller_validator: Callable[[RunPlan], Mapping[str, object]] = validate_controller_evidence,
    provenance_validator: Callable[
        [RunPlan, Mapping[str, object], Mapping[str, object]],
        Mapping[str, object],
    ] = validate_database_provenance,
) -> RunPlan:
    """Execute one retained run through injectable, fake-safe orchestration seams."""

    plan = None
    session = None
    session_finished = False
    try:
        before_first = capture_resources(repository)
        before_second = capture_resources(repository)
        assert_protected_resources_equal(before_first, before_second)
        validate_reviewed_checkout(
            before_second,
            expected_head=expected_head,
            allowed_unrelated_dirty_paths=allowed_unrelated_dirty_paths,
        )
        source_head = expected_head
        plan = create_run_plan(
            repository,
            source_head,
            now=now,
            nonce=nonce,
        )
        atomic_write_json(plan.resources_before, before_second, pinned_plan=plan)

        provider = select_provider_settings(environ, dotenv_values)
        seed_argv = build_seed_argv(
            plan,
            python_executable=python_executable,
            business_today=business_today,
        )
        assert_run_plan_identity(plan)
        seed_result = seed_runner(
            plan,
            argv=seed_argv,
            environment=build_seed_environment(environ),
        )
        assert_run_plan_identity(plan)
        seed_result = parse_seed_result(
            canonical_json_line(dict(seed_result)).encode("utf-8"),
            plan,
        )
        seed_baseline = capture_post_seed_baseline(plan)
        atomic_write_json(plan.seed_baseline, seed_baseline, pinned_plan=plan)
        _safe_owned_directory(plan.app_log.parent, label="run log directory")
        _ensure_run_directory(
            plan.tts_cache,
            label="run TTS directory",
            pinned_plan=plan,
        )
        _ensure_run_directory(
            plan.screenshots,
            label="run screenshot directory",
            pinned_plan=plan,
        )
        _write_owned_bytes(
            plan.invalid_avatar,
            b"pomegranagent invalid avatar fixture; deliberately not an image\n",
            pinned_plan=plan,
        )

        backend_environment = build_backend_environment(environ, plan, provider)
        session = server_starter(
            plan,
            environment=backend_environment,
            python_executable=python_executable,
        )
        health, version, cache_control, auth = readiness_probe(session)
        validate_readiness(
            health=health,
            version=version,
            version_cache_control=cache_control,
            auth=auth,
        )
        RuntimeEmitter(output_stream).emit(
            build_runtime_object(plan, port=getattr(session, "port", None))
        )
        control = consume_control_stream(input_stream, plan)
        if not control.finalize_requested:
            raise HarnessSafetyError("controller finalize was not requested")
        if not control.has_teacher_secret:
            raise HarnessSafetyError("controller teacher credential was not registered")
        provider_events = server_finisher(session)
        session_finished = True

        controller = controller_validator(plan)
        if any(
            isinstance(issue, Mapping) and issue.get("severity") == "blocker"
            for issue in controller["issues"]
        ):
            raise HarnessSafetyError("controller evidence contains a blocker")
        entity_ids = _collect_entity_ids(controller)
        provenance = provenance_validator(plan, entity_ids, seed_baseline)
        provider_summary = _validate_provider_completion(
            tuple(provider_events),
            plan=plan,
            provider=provider,
            entity_ids=entity_ids,
        )
        atomic_write_json(
            plan.journey,
            {
                "journey": controller["journey"],
                "protocol": "pomegranagent-live-uat-journey/v1",
                "run_id": plan.run_id,
            },
            pinned_plan=plan,
        )
        atomic_write_json(
            plan.issues,
            {
                "issues": controller["issues"],
                "protocol": "pomegranagent-live-uat-issues/v1",
                "run_id": plan.run_id,
            },
            pinned_plan=plan,
        )
        atomic_write_json(plan.provider_summary, provider_summary, pinned_plan=plan)

        after = capture_resources(repository)
        validate_reviewed_checkout(
            after,
            expected_head=expected_head,
            allowed_unrelated_dirty_paths=allowed_unrelated_dirty_paths,
        )
        atomic_write_json(plan.resources_after, after, pinned_plan=plan)
        assert_protected_resources_equal(before_second, after)
        actual_secrets = (provider["DEEPSEEK_API_KEY"], control.secret_for_scan())
        scan_retained_artifacts(
            plan.root,
            actual_secrets=tuple(
                secret for secret in actual_secrets if isinstance(secret, str)
            ),
            pinned_plan=plan,
        )
        manifest = _complete_manifest(
            plan,
            seed_result=seed_result,
            controller=controller,
            provider_summary=provider_summary,
            provenance=provenance,
        )
        manifest_payload = canonical_json_line(manifest).encode("utf-8")
        if any(secret.encode("utf-8") in manifest_payload for secret in actual_secrets):
            raise HarnessSafetyError("complete manifest contains a registered secret")
        _write_owned_bytes(
            plan.checksums,
            _checksum_lines(plan, manifest_payload),
            pinned_plan=plan,
        )
        scan_retained_artifacts(
            plan.root,
            actual_secrets=tuple(
                secret for secret in actual_secrets if isinstance(secret, str)
            ),
            pinned_plan=plan,
        )
        atomic_write_json(plan.manifest, manifest, pinned_plan=plan)
        return plan
    except KeyboardInterrupt as exc:
        error: BaseException = HarnessSafetyError("controller interrupted the retained run")
        error.__cause__ = exc
    except BaseException as exc:
        error = exc

    if session is not None and not session_finished:
        try:
            server_finisher(session)
        except BaseException:
            error = HarnessSafetyError("owned server cleanup failed")
    if plan is not None:
        reason = (
            "CONTROLLER_EVIDENCE_MISSING"
            if isinstance(error, HarnessSafetyError) and "controller" in str(error).lower()
            else "SAFETY_FAILURE"
        )
        try:
            after = capture_resources(repository)
            validate_reviewed_checkout(
                after,
                expected_head=expected_head,
                allowed_unrelated_dirty_paths=allowed_unrelated_dirty_paths,
            )
            atomic_write_json(plan.resources_after, after, pinned_plan=plan)
            assert_protected_resources_equal(before_second, after)
        except BaseException:
            reason = "SAFETY_FAILURE"
        finalize_failed_run(plan, reason_code=reason)
    if isinstance(error, HarnessSafetyError):
        raise error
    raise HarnessSafetyError("retained live UAT failed safely") from error


class SignalAwareControlStream:
    """Yield stdin lines while signal handlers only set a termination latch."""

    def __init__(self, descriptor: int, termination: threading.Event) -> None:
        if type(descriptor) is not int or descriptor < 0:
            raise HarnessSafetyError("controller input descriptor is invalid")
        self._descriptor = descriptor
        self._termination = termination

    def __iter__(self):
        buffered = b""
        while not self._termination.is_set():
            try:
                readable, _, _ = select.select([self._descriptor], [], [], 0.25)
            except (OSError, ValueError) as exc:
                raise HarnessSafetyError("controller input failed") from exc
            if not readable:
                continue
            try:
                chunk = os.read(self._descriptor, 4096)
            except OSError as exc:
                raise HarnessSafetyError("controller input failed") from exc
            if not chunk:
                if buffered:
                    raise HarnessSafetyError("canonical control frame is invalid")
                return
            buffered += chunk
            while b"\n" in buffered:
                raw, buffered = buffered.split(b"\n", 1)
                try:
                    yield (raw + b"\n").decode("utf-8", errors="strict")
                except UnicodeError as exc:
                    raise HarnessSafetyError("canonical control frame is invalid") from exc
            if len(buffered) > 1024:
                raise HarnessSafetyError("canonical control frame is invalid")


class _SignalTermination:
    def __init__(self) -> None:
        self.event = threading.Event()
        self._previous: dict[int, object] = {}

    def __enter__(self):
        for signum in (signal.SIGINT, signal.SIGTERM):
            self._previous[signum] = signal.getsignal(signum)
            signal.signal(signum, self._mark)
        return self

    def _mark(self, _signum, _frame) -> None:
        self.event.set()

    def __exit__(self, _error_type, _error, _traceback) -> None:
        for signum, previous in self._previous.items():
            signal.signal(signum, previous)


def read_dotenv_values(
    repository: Path,
    *,
    loader: Callable[..., Mapping[str, object]] | None = None,
) -> dict[str, object]:
    """Read the repository dotenv file without updating the process environment."""

    path = _absolute(repository) / ".env"
    try:
        entry = path.lstat()
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise HarnessSafetyError("provider configuration file is unavailable") from exc
    if (
        not stat.S_ISREG(entry.st_mode)
        or stat.S_ISLNK(entry.st_mode)
        or entry.st_nlink != 1
        or entry.st_uid != os.geteuid()
        or entry.st_size > 1_048_576
    ):
        raise HarnessSafetyError("provider configuration file is unsafe")
    if loader is None:
        from dotenv import dotenv_values as loader

    try:
        values = loader(
            dotenv_path=path,
            encoding="utf-8",
            interpolate=False,
            verbose=False,
        )
    except BaseException as exc:
        raise HarnessSafetyError("provider configuration file could not be read") from exc
    if not isinstance(values, Mapping):
        raise HarnessSafetyError("provider configuration file is invalid")
    return dict(values)


def _business_today() -> date:
    return datetime.now(ZoneInfo("Asia/Shanghai")).date()


def main(
    argv: list[str] | None = None,
    *,
    execute: Callable[..., RunPlan] = execute_retained_uat,
    dotenv_reader: Callable[[Path], Mapping[str, object]] = read_dotenv_values,
    environ: Mapping[str, str] | None = None,
    input_stream=None,
    output_stream=None,
    python_executable: str | None = None,
    business_today: Callable[[], date] = _business_today,
) -> int:
    parsed = parse_args(argv)
    selected_environment = dict(os.environ if environ is None else environ)
    selected_output = sys.stdout if output_stream is None else output_stream
    with _SignalTermination() as termination:
        selected_input = input_stream
        if selected_input is None:
            selected_input = SignalAwareControlStream(sys.stdin.fileno(), termination.event)
        execute(
            repository=PROJECT_ROOT,
            expected_head=parsed.expected_head,
            allowed_unrelated_dirty_paths=tuple(parsed.allow_unrelated_dirty_path),
            environ=selected_environment,
            dotenv_values=dotenv_reader(PROJECT_ROOT),
            input_stream=selected_input,
            output_stream=selected_output,
            python_executable=sys.executable if python_executable is None else python_executable,
            business_today=business_today,
            seed_runner=run_seed_process,
            server_starter=start_live_server,
            readiness_probe=probe_live_readiness,
            server_finisher=finish_live_server,
        )
    return 0


def _entrypoint() -> int:
    try:
        return main()
    except SystemExit:
        raise
    except BaseException as error:
        name = type(error).__name__
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_.]{0,127}", name) is None:
            name = "Exception"
        print(f"retained live UAT failed error_type={name}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(_entrypoint())
