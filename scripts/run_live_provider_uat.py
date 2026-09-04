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
from dataclasses import dataclass, replace
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
import tarfile
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
FROZEN_MAX_ROUNDS_REPLY = "谢谢你今天的分享，鸭鸭日记本都记好啦！我们下次再见～"
APPROVED_VIEWPORTS = {
    "child": ["1024x576", "1280x720"],
    "teacher": ["1024x768", "1440x900"],
}
REQUIRED_SCREENSHOT_STATES = {
    "child-avatar-selected": ("child", "child_duck_avatar_management", "1024x576"),
    "child-conversation-complete": (
        "child",
        "child_conversation_real_provider_tts",
        "1280x720",
    ),
    "teacher-management": ("teacher", "child_duck_avatar_management", "1024x768"),
    "teacher-review-confirmed": ("teacher", "review_edit_confirm", "1440x900"),
    "teacher-search-deep-link": (
        "teacher",
        "advanced_search_pagination_deep_link",
        "1440x900",
    ),
    "teacher-weekly-growth": ("teacher", "weekly_metrics_growth", "1024x768"),
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
ROSTER_TELEMETRY_KEYS = {
    "canonical_body_sha256",
    "error_code",
    "kind",
    "method",
    "order",
    "path",
    "replace_existing",
    "request_id",
    "status",
}
TTS_REQUEST_TELEMETRY_KEYS = {
    "audio_bytes",
    "cache_hit",
    "cache_relative_path",
    "cache_sha256",
    "effective_text_sha256",
    "kind",
    "method",
    "order",
    "path",
    "requested_text_sha256",
    "status",
    "truncated",
    "voice",
}
TTS_EVIDENCE_KEYS = {
    "audio_sha256",
    "cache_relative_path",
    "effective_text_sha256",
    "kind",
    "playback",
    "source_message_id",
    "text_sha256",
    "truncated",
}
PLAYBACK_EVIDENCE_KEYS = {
    "error",
    "events",
    "play_promise",
    "speech_synthesis_fallback",
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
STEP_PROVENANCE_KEYS = {
    "teacher_credential_setup_login": frozenset(),
    "child_duck_avatar_management": frozenset(
        {"child_avatar_id", "duck_avatar_id", "live_child_id", "live_duck_id"}
    ),
    "invalid_avatar_rejection": frozenset(),
    "monthly_roster_conflict_retry": frozenset(
        {"monthly_pairs", "monthly_roster_request_ids"}
    ),
    "child_conversation_real_provider_tts": frozenset(
        {
            "chat_request_ids",
            "live_conversation_id",
            "local_terminal_request_id",
            "provider_chat_request_ids",
            "tts_evidence",
        }
    ),
    "conversation_completion_analysis": frozenset({"analysis_job_id"}),
    "teacher_today_queues": frozenset(),
    "review_edit_confirm": frozenset({"assessment_id"}),
    "weekly_metrics_growth": frozenset(
        {
            "growth_after",
            "growth_before",
            "weekly_metrics_after",
            "weekly_metrics_before",
            "weekly_week_start",
        }
    ),
    "advanced_search_pagination_deep_link": frozenset(
        {
            "search_cursor",
            "search_deep_link",
            "search_page_one_ids",
            "search_page_two_ids",
            "search_request",
            "search_result_conversation_id",
        }
    ),
    "search_empty_state": frozenset(),
    "logout_login_retained_state": frozenset(),
}
_CONTROLLER_PROVENANCE_KEYS = frozenset().union(*STEP_PROVENANCE_KEYS.values())
_PROVENANCE_KEYS = _CONTROLLER_PROVENANCE_KEYS | {
    "monthly_roster_attempts",
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
_RUNTIME_DB_COLUMNS = {
    "alembic_version": ("version_num",),
    "analysis_jobs": (
        "id",
        "conversation_id",
        "frozen_last_message_id",
        "status",
        "attempt_count",
        "max_attempts",
        "available_at",
        "lease_owner",
        "lease_expires_at",
        "last_error_code",
        "last_error_message",
        "started_at",
        "finished_at",
        "created_at",
        "updated_at",
    ),
    "assessment_dimensions": (
        "id",
        "key",
        "name",
        "enabled",
        "weight",
        "description",
    ),
    "assessment_scores": ("id", "assessment_id", "dimension_id", "score", "reason"),
    "assessments": ("id", "conversation_id", "child_id", "status", "overall"),
    "avatar_media": (
        "id",
        "file_name",
        "mime_type",
        "width",
        "height",
        "size_bytes",
        "sha256",
        "created_at",
    ),
    "chat_requests": (
        "request_id",
        "child_id",
        "conversation_id",
        "base_last_message_id",
        "child_message_id",
        "diary_message_id",
        "payload_hash",
        "status",
        "attempt_count",
        "available_at",
        "lease_owner",
        "lease_expires_at",
        "last_error_code",
        "last_error_message",
        "response_json",
        "started_at",
        "finished_at",
        "created_at",
        "updated_at",
    ),
    "children": ("id", "name", "nickname", "avatar", "active", "deactivated_at"),
    "conversations": (
        "id",
        "child_id",
        "date",
        "started_at",
        "ended_at",
        "status",
        "end_reason",
        "revision",
        "pending_end_reason",
        "frozen_last_message_id",
    ),
    "duck_archives": ("id", "duck_id", "summary", "updated_at"),
    "ducks": ("id", "name", "avatar", "status", "note", "active", "deactivated_at"),
    "duty_rosters": ("id", "cycle", "date", "child_id"),
    "emotion_logs": (
        "id",
        "conversation_id",
        "child_id",
        "emotion",
        "intensity",
        "note",
        "occurred_at",
    ),
    "feeding_logs": (
        "id",
        "conversation_id",
        "child_id",
        "duck_id",
        "category",
        "content",
        "occurred_at",
    ),
    "insight_notes": ("id", "conversation_id", "child_id", "content", "created_at"),
    "messages": ("id", "conversation_id", "role", "text", "created_at"),
    "roster_requests": (
        "request_id",
        "operation",
        "payload_hash",
        "status",
        "response_json",
        "last_error_code",
        "last_error_message",
        "created_at",
        "updated_at",
    ),
    "teacher_credentials": ("id", "pin_salt", "pin_hash", "created_at", "updated_at"),
    "teacher_sessions": ("id", "token_hash", "created_at"),
}
_RUNTIME_DB_TEXT_COLUMNS = {
    "analysis_jobs": ("status", "last_error_code", "last_error_message"),
    "assessment_dimensions": ("key", "name", "description"),
    "assessment_scores": ("reason",),
    "assessments": ("status",),
    "avatar_media": ("mime_type",),
    "chat_requests": ("status", "last_error_code", "last_error_message"),
    "children": ("name", "nickname"),
    "conversations": ("status", "end_reason", "pending_end_reason"),
    "duck_archives": ("summary",),
    "ducks": ("name", "status", "note"),
    "emotion_logs": ("emotion", "note"),
    "feeding_logs": ("category", "content"),
    "insight_notes": ("content",),
    "messages": ("role", "text"),
    "roster_requests": (
        "operation",
        "status",
        "last_error_code",
        "last_error_message",
    ),
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
    source_root: Path
    source_root_identity: tuple[int, int, int, int] | None
    source_tree_oid: str | None
    source_inventory: tuple[tuple[str, str, int, int, str], ...]
    source_manifest: Path
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
        source_root=run_root / "reviewed-source",
        source_root_identity=None,
        source_tree_oid=None,
        source_inventory=(),
        source_manifest=run_root / "reviewed-source.json",
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


def _git_object_output(
    plan: RunPlan,
    argv: tuple[str, ...],
    *,
    max_bytes: int,
    runner=subprocess.run,
) -> bytes:
    if (
        not isinstance(argv, tuple)
        or not argv
        or argv[0] != "git"
        or type(max_bytes) is not int
        or max_bytes < 1
    ):
        raise HarnessSafetyError("reviewed source Git command is invalid")
    if (
        _owned_directory_identity(plan.repository, label="repository root")
        != plan.repository_identity
    ):
        raise HarnessSafetyError("reviewed source repository identity changed")
    try:
        git_environment = {
            name: os.environ[name]
            for name in SAFE_EXECUTION_ENV
            if name in os.environ and isinstance(os.environ[name], str)
        }
        git_environment.update(
            {
                "GIT_ATTR_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_SYSTEM": os.devnull,
                "GIT_NO_REPLACE_OBJECTS": "1",
            }
        )
        completed = runner(
            ("git", "--no-replace-objects", *argv[1:]),
            cwd=plan.repository,
            capture_output=True,
            check=False,
            env=dict(sorted(git_environment.items())),
        )
    except (OSError, ValueError) as exc:
        raise HarnessSafetyError("reviewed source Git object read failed") from exc
    payload = completed.stdout
    if (
        completed.returncode != 0
        or not isinstance(payload, bytes)
        or len(payload) > max_bytes
    ):
        raise HarnessSafetyError("reviewed source Git object read failed")
    if (
        _owned_directory_identity(plan.repository, label="repository root")
        != plan.repository_identity
    ):
        raise HarnessSafetyError("reviewed source repository identity changed")
    return payload


def _git_blob_oid(payload: bytes) -> str:
    return _git_object_oid("blob", payload)


def _git_object_oid(kind: str, payload: bytes) -> str:
    if kind not in {"blob", "commit", "tree"} or not isinstance(payload, bytes):
        raise HarnessSafetyError("reviewed source Git object is invalid")
    header = f"{kind} {len(payload)}\0".encode("ascii")
    return hashlib.sha1(header + payload, usedforsecurity=False).hexdigest()


def _source_manifest_value(plan: RunPlan) -> dict[str, object]:
    if plan.source_tree_oid is None:
        raise HarnessSafetyError("reviewed source is not materialized")
    return {
        "files": [
            {
                "blob_oid": blob_oid,
                "git_mode": git_mode,
                "path": relative,
                "sha256": digest,
                "size": size,
            }
            for relative, blob_oid, git_mode, size, digest in plan.source_inventory
        ],
        "object_format": "sha1",
        "protocol": "pomegranagent-reviewed-source/v1",
        "source_head": plan.source_head,
        "tree_oid": plan.source_tree_oid,
    }


def materialize_reviewed_source(
    plan: RunPlan,
    *,
    runner=subprocess.run,
) -> RunPlan:
    """Retain and pin the exact Git tree used by every executable UAT surface."""

    if plan.source_root_identity is not None or plan.source_inventory:
        raise HarnessSafetyError("reviewed source was already materialized")
    resolved = _git_object_output(
        plan,
        ("git", "rev-parse", f"{plan.source_head}^{{commit}}"),
        max_bytes=256,
        runner=runner,
    )
    tree = _git_object_output(
        plan,
        ("git", "rev-parse", f"{plan.source_head}^{{tree}}"),
        max_bytes=256,
        runner=runner,
    )
    object_format = _git_object_output(
        plan,
        ("git", "rev-parse", "--show-object-format"),
        max_bytes=64,
        runner=runner,
    )
    commit_kind = _git_object_output(
        plan,
        ("git", "cat-file", "-t", plan.source_head),
        max_bytes=64,
        runner=runner,
    )
    commit_payload = _git_object_output(
        plan,
        ("git", "cat-file", "commit", plan.source_head),
        max_bytes=16_000_000,
        runner=runner,
    )
    try:
        resolved_head = resolved.decode("ascii", errors="strict").strip()
        tree_oid = tree.decode("ascii", errors="strict").strip()
        object_name = object_format.decode("ascii", errors="strict").strip()
        commit_name = commit_kind.decode("ascii", errors="strict").strip()
        commit_tree_oid = commit_payload.split(b"\n", 1)[0].decode(
            "ascii", errors="strict"
        ).removeprefix("tree ")
    except UnicodeError as exc:
        raise HarnessSafetyError("reviewed source Git identity is invalid") from exc
    if (
        resolved_head != plan.source_head
        or HEAD_PATTERN.fullmatch(tree_oid) is None
        or object_name != "sha1"
        or commit_name != "commit"
        or _git_object_oid("commit", commit_payload) != plan.source_head
        or commit_tree_oid != tree_oid
    ):
        raise HarnessSafetyError("reviewed source Git identity is invalid")
    tree_kind = _git_object_output(
        plan,
        ("git", "cat-file", "-t", tree_oid),
        max_bytes=64,
        runner=runner,
    )
    tree_payload = _git_object_output(
        plan,
        ("git", "cat-file", "tree", tree_oid),
        max_bytes=64_000_000,
        runner=runner,
    )
    if tree_kind != b"tree\n" or _git_object_oid("tree", tree_payload) != tree_oid:
        raise HarnessSafetyError("reviewed source Git identity is invalid")

    listing = _git_object_output(
        plan,
        ("git", "ls-tree", "-r", "-z", "--full-tree", plan.source_head),
        max_bytes=64_000_000,
        runner=runner,
    )
    expected: dict[str, tuple[int, str]] = {}
    try:
        records = listing[:-1].split(b"\0") if listing.endswith(b"\0") else ()
        if not records:
            raise ValueError
        for record in records:
            metadata, raw_path = record.split(b"\t", 1)
            raw_mode, kind, raw_oid = metadata.split(b" ")
            relative = raw_path.decode("utf-8", errors="strict")
            path = Path(relative)
            mode_text = raw_mode.decode("ascii", errors="strict")
            oid = raw_oid.decode("ascii", errors="strict")
            if (
                kind != b"blob"
                or mode_text not in {"100644", "100755"}
                or HEAD_PATTERN.fullmatch(oid) is None
                or not relative
                or path.is_absolute()
                or "\\" in relative
                or any(part in {"", ".", ".."} for part in path.parts)
                or relative in expected
            ):
                raise ValueError
            expected[path.as_posix()] = (int(mode_text, 8), oid)
    except (UnicodeError, ValueError) as exc:
        raise HarnessSafetyError("reviewed source Git tree is invalid") from exc
    required = {
        "scripts/seed_demo_database.py",
        "scripts/live_provider_uat_server.py",
        "tests/fixtures/live_provider/avatars/child.png",
        "tests/fixtures/live_provider/avatars/duck.jpg",
        "app/version.json",
    }
    if (
        not required.issubset(expected)
        or not any(path.startswith("app/backend/") for path in expected)
        or not any(path.startswith("app/frontend/") for path in expected)
    ):
        raise HarnessSafetyError("reviewed source execution surface is incomplete")

    archive = _git_object_output(
        plan,
        ("git", "archive", "--format=tar", plan.source_head),
        max_bytes=1_000_000_000,
        runner=runner,
    )
    extracted: dict[str, tuple[int, bytes]] = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as bundle:
            for member in bundle.getmembers():
                relative = member.name.rstrip("/")
                candidate = Path(relative)
                if (
                    not relative
                    or candidate.is_absolute()
                    or "\\" in relative
                    or any(part in {"", ".", ".."} for part in candidate.parts)
                ):
                    raise ValueError
                if member.isdir():
                    continue
                if not member.isfile() or relative in extracted:
                    raise ValueError
                stream = bundle.extractfile(member)
                if stream is None:
                    raise ValueError
                payload = stream.read(1_000_000_001)
                if len(payload) > 1_000_000_000:
                    raise ValueError
                extracted[candidate.as_posix()] = (member.mode, payload)
    except (OSError, tarfile.TarError, ValueError) as exc:
        raise HarnessSafetyError("reviewed source archive is invalid") from exc
    if set(extracted) != set(expected):
        raise HarnessSafetyError("reviewed source archive does not match Git tree")

    inventory: list[tuple[str, str, int, int, str]] = []
    for relative in sorted(expected):
        expected_mode, blob_oid = expected[relative]
        archive_mode, payload = extracted[relative]
        if (
            bool(archive_mode & 0o111) != bool(expected_mode & 0o111)
            or _git_blob_oid(payload) != blob_oid
        ):
            raise HarnessSafetyError("reviewed source archive does not match Git objects")
        inventory.append(
            (relative, blob_oid, expected_mode, len(payload), _hash_bytes(payload))
        )

    _ensure_run_directory(
        plan.source_root,
        label="reviewed source root",
        pinned_plan=plan,
    )
    directories = sorted(
        {
            parent.as_posix()
            for relative in expected
            for parent in Path(relative).parents
            if parent.as_posix() != "."
        },
        key=lambda value: (value.count("/"), value),
    )
    for relative in directories:
        _ensure_run_directory(
            plan.source_root.joinpath(*relative.split("/")),
            label="reviewed source directory",
            pinned_plan=plan,
        )
    for relative, _blob_oid, git_mode, _size, _digest in inventory:
        destination = plan.source_root.joinpath(*relative.split("/"))
        _write_owned_bytes(destination, extracted[relative][1], pinned_plan=plan)
        os.chmod(destination, 0o500 if git_mode & 0o111 else 0o400)

    reviewed = replace(
        plan,
        source_tree_oid=tree_oid,
        source_inventory=tuple(inventory),
    )
    atomic_write_json(
        reviewed.source_manifest,
        _source_manifest_value(reviewed),
        pinned_plan=reviewed,
    )
    for relative in sorted(directories, key=lambda value: (-value.count("/"), value)):
        os.chmod(reviewed.source_root.joinpath(*relative.split("/")), 0o500)
    os.chmod(reviewed.source_root, 0o500)
    reviewed = replace(
        reviewed,
        source_root_identity=_owned_directory_identity(
            reviewed.source_root,
            label="reviewed source root",
        ),
    )
    assert_reviewed_source_pinned(reviewed)
    return reviewed


def assert_reviewed_source_pinned(plan: RunPlan) -> None:
    if (
        plan.source_root != plan.root / "reviewed-source"
        or plan.source_root_identity is None
        or plan.source_tree_oid is None
        or not plan.source_inventory
        or _owned_directory_identity(plan.source_root, label="reviewed source root")
        != plan.source_root_identity
    ):
        raise HarnessSafetyError("reviewed source identity changed")
    try:
        manifest_payload = _read_pinned_run_file(
            plan,
            plan.source_manifest,
            max_bytes=128_000_000,
        )
        if manifest_payload != canonical_json_line(_source_manifest_value(plan)).encode(
            "utf-8"
        ):
            raise HarnessSafetyError("reviewed source manifest changed")
        candidates = sorted(
            plan.source_root.rglob("*"),
            key=lambda item: item.relative_to(plan.source_root).as_posix(),
        )
    except (OSError, ValueError) as exc:
        raise HarnessSafetyError("reviewed source inventory is unavailable") from exc
    expected = {item[0]: item for item in plan.source_inventory}
    observed: set[str] = set()
    for candidate in candidates:
        relative = candidate.relative_to(plan.source_root).as_posix()
        try:
            entry = candidate.lstat()
        except OSError as exc:
            raise HarnessSafetyError("reviewed source inventory changed") from exc
        if stat.S_ISDIR(entry.st_mode) and not stat.S_ISLNK(entry.st_mode):
            if (
                stat.S_IMODE(entry.st_mode) != 0o500
                or entry.st_uid != os.geteuid()
                or entry.st_nlink < 1
            ):
                raise HarnessSafetyError("reviewed source directory changed")
            continue
        if relative not in expected:
            raise HarnessSafetyError("reviewed source inventory changed")
        _relative, blob_oid, git_mode, size, digest = expected[relative]
        payload = _read_pinned_run_file(plan, candidate, max_bytes=1_000_000_000)
        if (
            not stat.S_ISREG(entry.st_mode)
            or entry.st_uid != os.geteuid()
            or entry.st_nlink != 1
            or stat.S_IMODE(entry.st_mode)
            != (0o500 if git_mode & 0o111 else 0o400)
            or len(payload) != size
            or _hash_bytes(payload) != digest
            or _git_blob_oid(payload) != blob_oid
        ):
            raise HarnessSafetyError("reviewed source file changed")
        observed.add(relative)
    if observed != set(expected):
        raise HarnessSafetyError("reviewed source inventory changed")
    assert_run_plan_identity(plan)


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
        str(plan.source_root / "scripts" / "seed_demo_database.py"),
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


def _reap_child_after_validation_failure(process) -> None:
    """Boundedly terminate one just-started leader when ownership is not usable."""

    try:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        if process.poll() is None:
            raise HarnessSafetyError("started child cleanup did not reap the leader")
    except HarnessSafetyError:
        raise
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        raise HarnessSafetyError("started child cleanup failed") from exc


def run_seed_process(
    plan: RunPlan,
    *,
    argv: tuple[str, ...],
    environment: Mapping[str, str],
    popen=subprocess.Popen,
    getpgid: Callable[[int], int] = os.getpgid,
    getsid: Callable[[int], int] = os.getsid,
    group_members: Callable[[int], tuple[tuple[int, int], ...]] = lambda pgid: _process_group_members(pgid),
    killpg: Callable[[int, int], None] = os.killpg,
    peek_exit: Callable[[OwnedProcess], int | None] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    source_validator: Callable[[RunPlan], None] = assert_reviewed_source_pinned,
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
    source_validator(plan)

    with tempfile.TemporaryFile(mode="w+b") as stdout_file, tempfile.TemporaryFile(
        mode="w+b"
    ) as stderr_file:
        try:
            process = popen(
                argv,
                cwd=plan.source_root,
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
        try:
            _owned_identity(owned, getpgid=getpgid, getsid=getsid)
        except BaseException as validation_error:
            try:
                _reap_child_after_validation_failure(process)
            except BaseException as cleanup_error:
                raise cleanup_error from validation_error
            raise
        observe = _peek_owned_exit if peek_exit is None else peek_exit
        observed = _wait_owned_exit_unreaped(
            owned,
            timeout=120,
            peek_exit=observe,
            monotonic=monotonic,
            sleep=sleep,
        )
        if observed is None:
            stop_owned_process_group(
                owned,
                getpgid=getpgid,
                getsid=getsid,
                group_members=group_members,
                killpg=killpg,
                peek_exit=observe,
                monotonic=monotonic,
                sleep=sleep,
            )
            raise HarnessSafetyError("offline seed process timed out")
        returncode = stop_owned_process_group(
            owned,
            getpgid=getpgid,
            getsid=getsid,
            group_members=group_members,
            killpg=killpg,
            peek_exit=observe,
            monotonic=monotonic,
            sleep=sleep,
        )
        if returncode != 0:
            raise HarnessSafetyError("offline seed process failed")
        source_validator(plan)
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
            "APP_REVIEWED_SOURCE_HEAD": plan.source_head,
            "APP_REVIEWED_SOURCE_MANIFEST": str(plan.source_manifest),
            "APP_REVIEWED_SOURCE_ROOT": str(plan.source_root),
            "APP_REVIEWED_SOURCE_TREE_OID": str(plan.source_tree_oid),
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
                plan.source_root / "tests/fixtures/live_provider/avatars/child.png"
            ),
            "duck_avatar": str(
                plan.source_root / "tests/fixtures/live_provider/avatars/duck.jpg"
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
    if not isinstance(value, dict) or canonical_json_line(value) != text:
        raise HarnessSafetyError("provider telemetry is invalid")
    if set(value) == ROSTER_TELEMETRY_KEYS:
        if (
            value["kind"] != "roster_attempt"
            or value["method"] != "POST"
            or value["path"] != "/api/roster/month"
            or type(value["order"]) is not int
            or value["order"] <= 0
            or not isinstance(value["request_id"], str)
            or UUID4_PATTERN.fullmatch(value["request_id"]) is None
            or not isinstance(value["canonical_body_sha256"], str)
            or SHA256_PATTERN.fullmatch(value["canonical_body_sha256"]) is None
            or type(value["replace_existing"]) is not bool
            or type(value["status"]) is not int
            or not 100 <= value["status"] <= 599
            or not (
                value["status"] < 400 and value["error_code"] is None
                or value["status"] >= 400
                and isinstance(value["error_code"], str)
                and re.fullmatch(r"[A-Z][A-Z0-9_]{2,63}", value["error_code"])
                is not None
            )
        ):
            raise HarnessSafetyError("provider telemetry is invalid")
        return value
    if set(value) == TTS_REQUEST_TELEMETRY_KEYS:
        if (
            value["kind"] != "tts_request"
            or value["method"] != "GET"
            or value["path"] != "/api/tts"
            or type(value["order"]) is not int
            or value["order"] <= 0
            or value["status"] != 200
            or type(value["cache_hit"]) is not bool
            or type(value["truncated"]) is not bool
            or type(value["audio_bytes"]) is not int
            or not 1 <= value["audio_bytes"] <= 100_000_000
            or value["voice"] != "zh-CN-XiaoxiaoNeural"
            or not isinstance(value["cache_relative_path"], str)
            or re.fullmatch(
                r"tts-cache/[0-9a-f]{32}\.mp3",
                value["cache_relative_path"],
            )
            is None
            or any(
                not isinstance(value[key], str)
                or SHA256_PATTERN.fullmatch(value[key]) is None
                for key in (
                    "cache_sha256",
                    "effective_text_sha256",
                    "requested_text_sha256",
                )
            )
        ):
            raise HarnessSafetyError("provider telemetry is invalid")
        return value
    if set(value) != TELEMETRY_KEYS:
        raise HarnessSafetyError("provider telemetry is invalid")
    operation = value["operation"]
    provider = value["provider"]
    model = value["model"]
    voice = value["voice"]
    if operation in {"chat_reply", "extract_info", "assess_conversation"}:
        expected_correlation = (
            r"chat-request:[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
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
        "protocol": "pomegranagent-live-uat-telemetry-summary/v1",
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
    source_validator: Callable[[RunPlan], None] = assert_reviewed_source_pinned,
    validation_stopper: Callable[[OwnedProcess], object] | None = None,
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
    source_validator(plan)
    argv = (
        python_executable,
        str(plan.source_root / "scripts" / "live_provider_uat_server.py"),
        "--listen-fd",
        str(listen_fd),
        "--telemetry-fd",
        str(telemetry_fd),
    )
    try:
        process = popen(
            argv,
            cwd=plan.source_root,
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
    identity_validated = False
    try:
        _owned_identity(owned, getpgid=getpgid, getsid=getsid)
        identity_validated = True
        source_validator(plan)
    except BaseException as validation_error:
        try:
            if identity_validated:
                stopper = (
                    stop_owned_process_group
                    if validation_stopper is None
                    else validation_stopper
                )
                stopper(owned)
            else:
                _reap_child_after_validation_failure(process)
        except BaseException as cleanup_error:
            raise cleanup_error from validation_error
        raise
    return owned


def require_owned_process_alive(
    owned: OwnedProcess,
    *,
    getpgid: Callable[[int], int] = os.getpgid,
    getsid: Callable[[int], int] = os.getsid,
    peek_exit: Callable[[OwnedProcess], int | None] | None = None,
) -> None:
    _owned_identity(owned, getpgid=getpgid, getsid=getsid)
    observed_exit = _peek_owned_exit(owned) if peek_exit is None else peek_exit(owned)
    if observed_exit is not None:
        raise HarnessSafetyError("live server exited before readiness")


def _peek_owned_exit(
    owned: OwnedProcess,
    *,
    waitid: Callable[[int, int, int], object | None] = os.waitid,
) -> int | None:
    """Observe child exit while deliberately retaining its kernel PID/PGID identity."""

    if getattr(owned.process, "returncode", None) is not None:
        return owned.process.returncode
    required = ("P_PID", "WEXITED", "WNOHANG", "WNOWAIT")
    if any(not hasattr(os, name) for name in required):
        raise HarnessSafetyError("unreaped process observation is unavailable")
    try:
        result = waitid(
            os.P_PID,
            owned.pid,
            os.WEXITED | os.WNOHANG | os.WNOWAIT,
        )
    except (ChildProcessError, OSError, ValueError) as exc:
        raise HarnessSafetyError("owned child identity is unavailable") from exc
    if result is None:
        return None
    if getattr(result, "si_pid", None) != owned.pid:
        raise HarnessSafetyError("owned child identity is invalid")
    code = getattr(result, "si_code", None)
    status_value = getattr(result, "si_status", None)
    if type(status_value) is not int:
        raise HarnessSafetyError("owned child exit status is invalid")
    if code == getattr(os, "CLD_EXITED", 1):
        return status_value
    if code in {
        getattr(os, "CLD_KILLED", 2),
        getattr(os, "CLD_DUMPED", 3),
    }:
        return -status_value
    raise HarnessSafetyError("owned child exit status is invalid")


def _wait_owned_exit_unreaped(
    owned: OwnedProcess,
    *,
    timeout: float,
    peek_exit: Callable[[OwnedProcess], int | None],
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> int | None:
    deadline = monotonic() + timeout
    while True:
        observed = peek_exit(owned)
        if observed is not None:
            return observed
        if monotonic() >= deadline:
            return None
        sleep(0.05)


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
    ):
        raise HarnessSafetyError("process-group ownership is invalid")
    return members


def _wait_owned_group_quiescent(
    owned: OwnedProcess,
    *,
    group_members: Callable[[int], tuple[tuple[int, int], ...]],
    peek_exit: Callable[[OwnedProcess], int | None],
    timeout: float,
    monotonic: Callable[[], float],
    sleep: Callable[[float], None],
) -> bool:
    deadline = monotonic() + timeout
    while True:
        exit_status = peek_exit(owned)
        members = _verified_group_members(owned, tuple(group_members(owned.pgid)))
        remaining = [pid for pid, _sid in members if pid != owned.pid]
        if exit_status is not None and not remaining:
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
    peek_exit: Callable[[OwnedProcess], int | None] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Stop the retained session and prove every owned PGID member is absent."""

    observe = _peek_owned_exit if peek_exit is None else peek_exit
    if getattr(owned.process, "returncode", None) is not None:
        raise HarnessSafetyError("process-group leader was reaped before cleanup")
    _owned_identity(owned, getpgid=getpgid, getsid=getsid)
    exit_status = observe(owned)
    members = _verified_group_members(owned, tuple(group_members(owned.pgid)))
    if not any(pid == owned.pid for pid, _sid in members):
        raise HarnessSafetyError("process-group ownership is invalid")
    try:
        if exit_status is None or any(pid != owned.pid for pid, _sid in members):
            _owned_identity(owned, getpgid=getpgid, getsid=getsid)
            killpg(owned.pgid, signal.SIGTERM)
        if not _wait_owned_group_quiescent(
            owned,
            group_members=group_members,
            peek_exit=observe,
            timeout=2,
            monotonic=monotonic,
            sleep=sleep,
        ):
            _owned_identity(owned, getpgid=getpgid, getsid=getsid)
            _verified_group_members(owned, tuple(group_members(owned.pgid)))
            killpg(owned.pgid, signal.SIGKILL)
            if not _wait_owned_group_quiescent(
                owned,
                group_members=group_members,
                peek_exit=observe,
                timeout=5,
                monotonic=monotonic,
                sleep=sleep,
            ):
                raise HarnessSafetyError("owned process group could not be reaped")
        observed_status = observe(owned)
        if observed_status is None:
            raise HarnessSafetyError("owned process group leader did not exit")
        try:
            returncode = owned.process.wait(timeout=5)
        except subprocess.TimeoutExpired as exc:
            raise HarnessSafetyError("owned process group could not be reaped") from exc
    except (OSError, ValueError) as exc:
        raise HarnessSafetyError("owned process group could not be stopped") from exc
    if returncode != observed_status:
        raise HarnessSafetyError("owned process group exit status changed")
    if _verified_group_members(owned, tuple(group_members(owned.pgid))):
        raise HarnessSafetyError("owned process group could not be reaped")
    return returncode


def start_live_server(
    plan: RunPlan,
    *,
    environment: Mapping[str, str],
    python_executable: str,
    prebind: Callable[[], BoundLoopbackSocket] = prebind_loopback_socket,
    collector_factory: Callable[[int], object] = TelemetryCollector,
    launcher: Callable[..., OwnedProcess] = launch_server_process,
    startup_stopper: Callable[[OwnedProcess], object] = stop_owned_process_group,
) -> LiveServerSession:
    """Launch the sole live child and close every parent-side inherited handle."""

    assert_run_plan_identity(plan)
    _safe_owned_directory(plan.app_log.parent, label="run log directory")
    bound = prebind()
    read_fd = write_fd = None
    output = None
    collector = None
    collector_started = False
    owned = None
    try:
        read_fd, write_fd = os.pipe()
        collector = collector_factory(read_fd)
        collector.start()
        collector_started = True
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
        bound.socket.close()
        os.close(write_fd)
        write_fd = None
        assert_run_plan_identity(plan)
    except BaseException as startup_error:
        cleanup_error = None
        if owned is not None:
            try:
                startup_stopper(owned)
            except BaseException as exc:
                cleanup_error = exc
        try:
            bound.socket.close()
        except BaseException as exc:
            if cleanup_error is None:
                cleanup_error = exc
        if write_fd is not None:
            try:
                os.close(write_fd)
            except OSError as exc:
                if cleanup_error is None:
                    cleanup_error = exc
        if collector_started:
            try:
                collector.finish()
                read_fd = None
            except BaseException as exc:
                if cleanup_error is None:
                    cleanup_error = exc
        if read_fd is not None:
            try:
                os.close(read_fd)
            except OSError as exc:
                if cleanup_error is None:
                    cleanup_error = exc
        if output is not None:
            try:
                output.close()
            except BaseException as exc:
                if cleanup_error is None:
                    cleanup_error = exc
        if cleanup_error is not None:
            raise HarnessSafetyError("live server startup cleanup failed") from cleanup_error
        raise startup_error
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
    peek_exit: Callable[[OwnedProcess], int | None] | None = None,
) -> tuple[Mapping[str, object], ...]:
    """Stop, reap, flush, and drain the one session exactly once."""

    if not isinstance(session, LiveServerSession):
        raise HarnessSafetyError("live server session is invalid")
    if session.finished:
        return session.provider_events
    error: BaseException | None = None
    observe = _peek_owned_exit if peek_exit is None else peek_exit
    if observe(session.owned) is not None:
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
    terminal_commit: bool = False,
) -> None:
    """Write one canonical 0600 JSON artifact and durably replace its target."""

    destination = _absolute(target)
    if type(terminal_commit) is not bool or (
        terminal_commit
        and (pinned_plan is None or destination != pinned_plan.manifest)
    ):
        raise HarnessSafetyError("terminal evidence commit is invalid")
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
        if terminal_commit:
            assert_run_plan_identity(pinned_plan)
            if parent_descriptor is not None:
                os.fsync(parent_descriptor)
        if parent_descriptor is not None and replace is os.replace:
            os.replace(
                temporary_name,
                destination_name,
                src_dir_fd=parent_descriptor,
                dst_dir_fd=parent_descriptor,
            )
        else:
            replace(temporary, destination)
        if terminal_commit:
            pass
        elif parent_descriptor is not None:
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
            try:
                os.close(parent_descriptor)
            except OSError:
                if not terminal_commit:
                    raise
    if pinned_plan is not None and not terminal_commit:
        assert_run_plan_identity(pinned_plan)


def finalize_failed_run(
    plan: RunPlan,
    *,
    reason_code: str,
) -> None:
    if re.fullmatch(r"[A-Z][A-Z0-9_]{2,63}", reason_code) is None:
        raise HarnessSafetyError("failed-run reason code is invalid")
    payload = {
        "protocol": "pomegranagent-live-uat-manifest/v1",
        "reason_code": reason_code,
        "run_id": plan.run_id,
        "source_head": plan.source_head,
        "status": "FAILED",
    }
    state = _file_evidence(plan.manifest)
    if state["kind"] != "missing":
        if state["kind"] != "regular":
            raise HarnessSafetyError("existing retained manifest is invalid")
        try:
            existing_payload = _read_pinned_run_file(
                plan,
                plan.manifest,
                max_bytes=10_000_000,
            )
            existing_text = existing_payload.decode("utf-8", errors="strict")
            existing = json.loads(existing_text)
        except (HarnessSafetyError, UnicodeError, ValueError) as exc:
            raise HarnessSafetyError("existing retained manifest is invalid") from exc
        if existing == payload:
            return
        raise HarnessSafetyError("existing retained manifest cannot be replaced")
    atomic_write_json(plan.manifest, payload, pinned_plan=plan)


def _hash_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _entry_evidence(entry: os.stat_result) -> dict[str, object]:
    common = {
        "device": entry.st_dev,
        "inode": entry.st_ino,
        "mode": stat.S_IMODE(entry.st_mode),
        "mtime_ns": entry.st_mtime_ns,
        "nlink": entry.st_nlink,
        "size": entry.st_size,
    }
    if stat.S_ISREG(entry.st_mode):
        return {"kind": "regular", **common}
    if stat.S_ISDIR(entry.st_mode):
        return {"kind": "directory", **common}
    if stat.S_ISLNK(entry.st_mode):
        return {"kind": "symlink", **common}
    return {"kind": "special", **common}


def _read_absolute_regular_nofollow(
    path: Path,
    *,
    max_bytes: int = 2_000_000_000,
) -> tuple[bytes, dict[str, object]]:
    absolute = _absolute(path)
    parent_descriptor = None
    descriptor = None
    try:
        parent_descriptor = _open_absolute_directory_nofollow(absolute.parent)
    except FileNotFoundError:
        raise HarnessSafetyError("protected resource is unavailable") from None
    except OSError as exc:
        raise HarnessSafetyError("protected resource snapshot failed") from exc
    try:
        parent_identity = _directory_descriptor_identity(os.fstat(parent_descriptor))
        entry = os.stat(absolute.name, dir_fd=parent_descriptor, follow_symlinks=False)
        evidence = _entry_evidence(entry)
        if (
            evidence["kind"] != "regular"
            or entry.st_nlink != 1
            or entry.st_uid != os.geteuid()
            or entry.st_mode & 0o022
            or entry.st_size > max_bytes
        ):
            raise HarnessSafetyError("protected resource is not a safe regular file")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(absolute.name, flags, dir_fd=parent_descriptor)
        before_identity = _regular_descriptor_identity(os.fstat(descriptor))
        if before_identity != _regular_descriptor_identity(entry):
            raise HarnessSafetyError("protected resource identity changed")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, max_bytes - total + 1))
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise HarnessSafetyError("protected resource exceeds its bound")
            chunks.append(chunk)
        if _regular_descriptor_identity(os.fstat(descriptor)) != before_identity:
            raise HarnessSafetyError("protected resource changed during snapshot")
    except HarnessSafetyError:
        raise
    except (OSError, ValueError) as exc:
        raise HarnessSafetyError("protected resource snapshot failed") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if parent_descriptor is not None:
            os.close(parent_descriptor)
    current_parent = None
    try:
        current_parent = _open_absolute_directory_nofollow(absolute.parent)
        if _directory_descriptor_identity(os.fstat(current_parent)) != parent_identity:
            raise HarnessSafetyError("protected resource ancestor identity changed")
        current = os.stat(
            absolute.name,
            dir_fd=current_parent,
            follow_symlinks=False,
        )
        if _regular_descriptor_identity(current) != before_identity:
            raise HarnessSafetyError("protected resource identity changed")
    except HarnessSafetyError:
        raise
    except OSError as exc:
        raise HarnessSafetyError("protected resource identity changed") from exc
    finally:
        if current_parent is not None:
            os.close(current_parent)
    payload = b"".join(chunks)
    return payload, {**evidence, "sha256": _hash_bytes(payload)}


def _file_evidence(path: Path) -> dict[str, object]:
    absolute = _absolute(path)
    parent_descriptor = None
    try:
        parent_descriptor = _open_absolute_directory_nofollow(absolute.parent)
        parent_identity = _directory_descriptor_identity(os.fstat(parent_descriptor))
        entry = os.stat(absolute.name, dir_fd=parent_descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return {"kind": "missing"}
    except OSError as exc:
        raise HarnessSafetyError("protected resource snapshot failed") from exc
    finally:
        if parent_descriptor is not None:
            os.close(parent_descriptor)
    evidence = _entry_evidence(entry)
    if evidence["kind"] == "regular":
        _payload, regular = _read_absolute_regular_nofollow(absolute)
        if any(regular.get(key) != value for key, value in evidence.items()):
            raise HarnessSafetyError("protected resource changed during snapshot")
        return regular
    current_parent = None
    try:
        current_parent = _open_absolute_directory_nofollow(absolute.parent)
        if _directory_descriptor_identity(os.fstat(current_parent)) != parent_identity:
            raise HarnessSafetyError("protected resource ancestor identity changed")
        current = os.stat(
            absolute.name,
            dir_fd=current_parent,
            follow_symlinks=False,
        )
        if _entry_evidence(current) != evidence:
            raise HarnessSafetyError("protected resource changed during snapshot")
    except HarnessSafetyError:
        raise
    except OSError as exc:
        raise HarnessSafetyError("protected resource changed during snapshot") from exc
    finally:
        if current_parent is not None:
            os.close(current_parent)
    return evidence


def _directory_evidence(path: Path) -> dict[str, object]:
    absolute = _absolute(path)
    descriptor = None
    try:
        descriptor = _open_absolute_directory_nofollow(absolute)
    except FileNotFoundError:
        missing = {"kind": "missing"}
        return {"root": missing, "entries": [], "digest": _hash_bytes(b"[]")}
    except OSError as exc:
        raise HarnessSafetyError("protected resource tree scan failed") from exc
    entries: list[dict[str, object]] = []

    def snapshot_directory(parent_descriptor: int, prefix: str) -> None:
        try:
            names = sorted(os.listdir(parent_descriptor))
        except OSError as exc:
            raise HarnessSafetyError("protected resource tree scan failed") from exc
        for name in names:
            if not name or name in {".", ".."} or "/" in name or "\\" in name:
                raise HarnessSafetyError("protected resource tree is unsafe")
            relative = f"{prefix}/{name}" if prefix else name
            child_descriptor = None
            try:
                entry = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
                evidence = _entry_evidence(entry)
                if evidence["kind"] == "regular":
                    if entry.st_nlink != 1 or entry.st_uid != os.geteuid() or entry.st_mode & 0o022:
                        raise HarnessSafetyError("protected resource tree is unsafe")
                    child_descriptor = os.open(
                        name,
                        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                        dir_fd=parent_descriptor,
                    )
                    before_identity = _regular_descriptor_identity(
                        os.fstat(child_descriptor)
                    )
                    if before_identity != _regular_descriptor_identity(entry):
                        raise HarnessSafetyError("protected resource tree changed")
                    chunks = []
                    total = 0
                    while True:
                        chunk = os.read(child_descriptor, 1024 * 1024)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > 2_000_000_000:
                            raise HarnessSafetyError("protected resource tree is too large")
                        chunks.append(chunk)
                    if (
                        _regular_descriptor_identity(os.fstat(child_descriptor))
                        != before_identity
                        or _regular_descriptor_identity(
                            os.stat(
                                name,
                                dir_fd=parent_descriptor,
                                follow_symlinks=False,
                            )
                        )
                        != before_identity
                    ):
                        raise HarnessSafetyError("protected resource tree changed")
                    evidence = {**evidence, "sha256": _hash_bytes(b"".join(chunks))}
                    entries.append(
                        {"relative_path": relative, "snapshot": evidence}
                    )
                elif evidence["kind"] == "directory":
                    if entry.st_uid != os.geteuid() or entry.st_mode & 0o022 or entry.st_nlink < 1:
                        raise HarnessSafetyError("protected resource tree is unsafe")
                    child_descriptor = os.open(
                        name,
                        _directory_open_flags(),
                        dir_fd=parent_descriptor,
                    )
                    before_identity = _directory_descriptor_identity(
                        os.fstat(child_descriptor)
                    )
                    if before_identity != _directory_descriptor_identity(entry):
                        raise HarnessSafetyError("protected resource tree changed")
                    entries.append(
                        {"relative_path": relative, "snapshot": evidence}
                    )
                    snapshot_directory(child_descriptor, relative)
                    if (
                        _directory_descriptor_identity(os.fstat(child_descriptor))
                        != before_identity
                        or _directory_descriptor_identity(
                            os.stat(
                                name,
                                dir_fd=parent_descriptor,
                                follow_symlinks=False,
                            )
                        )
                        != before_identity
                    ):
                        raise HarnessSafetyError("protected resource tree changed")
                else:
                    raise HarnessSafetyError("protected resource tree is unsafe")
            except HarnessSafetyError:
                raise
            except (OSError, ValueError) as exc:
                raise HarnessSafetyError("protected resource tree scan failed") from exc
            finally:
                if child_descriptor is not None:
                    os.close(child_descriptor)

    try:
        root_entry = os.fstat(descriptor)
        root = _entry_evidence(root_entry)
        if (
            root["kind"] != "directory"
            or root_entry.st_uid != os.geteuid()
            or root_entry.st_mode & 0o022
            or root_entry.st_nlink < 1
        ):
            raise HarnessSafetyError("protected resource tree is unsafe")
        root_identity = _directory_descriptor_identity(root_entry)
        snapshot_directory(descriptor, "")
        if _directory_descriptor_identity(os.fstat(descriptor)) != root_identity:
            raise HarnessSafetyError("protected resource tree changed")
    finally:
        if descriptor is not None:
            os.close(descriptor)
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
                payload, pinned = _read_absolute_regular_nofollow(source)
            except HarnessSafetyError as exc:
                raise HarnessSafetyError("protected database snapshot failed") from exc
            if pinned != before or _file_evidence(source) != before:
                raise HarnessSafetyError("protected database changed during snapshot")
            try:
                Path(f"{shadow}{suffix}").write_bytes(payload)
            except OSError as exc:
                raise HarnessSafetyError("protected database shadow failed") from exc
        yield shadow


def _database_logical_digest(path: Path) -> str | None:
    evidence = _file_evidence(path)
    if evidence["kind"] == "missing":
        return None
    if evidence["kind"] != "regular":
        raise HarnessSafetyError("protected database snapshot failed")
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


def _dirty_path_records(
    status: bytes,
) -> tuple[tuple[str, str, str, int, str | None], ...]:
    if not status:
        return ()
    if not status.endswith(b"\0"):
        raise HarnessSafetyError("protected Git porcelain is invalid")
    records = list(status[:-1].split(b"\0"))
    paths: list[tuple[str, str, str, int, str | None]] = []
    index = 0
    porcelain_record = 0

    def decode_path(raw_path: bytes) -> str:
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
        return candidate.as_posix()

    while index < len(records):
        record = records[index]
        if len(record) < 4 or record[2:3] != b" ":
            raise HarnessSafetyError("protected Git porcelain is invalid")
        status_code = record[:2]
        try:
            decoded_status = status_code.decode("ascii", errors="strict")
        except UnicodeError as exc:
            raise HarnessSafetyError("protected Git porcelain is invalid") from exc
        if (
            re.fullmatch(r"[ MADRCUT?!]{2}", decoded_status) is None
            or decoded_status == "  "
        ):
            raise HarnessSafetyError("protected Git porcelain is invalid")
        raw_paths = [(record[3:], "path")]
        destination = None
        index += 1
        if b"R" in status_code or b"C" in status_code:
            if index >= len(records):
                raise HarnessSafetyError("protected Git porcelain is invalid")
            raw_paths = [(record[3:], "current"), (records[index], "original")]
            destination = decode_path(record[3:])
            index += 1
        for raw_path, role in raw_paths:
            paths.append(
                (
                    decode_path(raw_path),
                    decoded_status,
                    role,
                    porcelain_record,
                    destination,
                )
            )
        porcelain_record += 1
    result = tuple(sorted(paths))
    if len({(item[3], item[2]) for item in result}) != len(result):
        raise HarnessSafetyError("protected Git porcelain contains duplicate records")
    return result


def _dirty_path_names(status: bytes) -> tuple[str, ...]:
    return tuple(
        relative
        for relative, _status, _role, _record, _destination in _dirty_path_records(
            status
        )
    )


def _dirty_path_evidence(
    root: Path,
    relative: str,
    porcelain_status: str,
    porcelain_role: str,
    porcelain_record: int,
    porcelain_destination: str | None,
) -> dict[str, object]:
    path = root.joinpath(*relative.split("/"))
    file_state = _file_evidence(path)
    directory = _directory_evidence(path) if file_state["kind"] == "directory" else None
    if file_state["kind"] not in {"missing", "regular", "directory"}:
        raise HarnessSafetyError("pre-existing dirty path is unsafe")
    return {
        "relative_path": relative,
        "porcelain_status": porcelain_status,
        "porcelain_role": porcelain_role,
        "porcelain_record": porcelain_record,
        "porcelain_destination": porcelain_destination,
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
    dirty_records = _dirty_path_records(porcelain)
    return {
        "database": _database_evidence(root / "data" / "duck_diary.db"),
        "log": _file_evidence(root / "logs" / "app.log"),
        "tts": _directory_evidence(root / "data" / "tts_cache"),
        "media": _directory_evidence(root / "data" / "media"),
        "git_head": head,
        "git_porcelain": {"sha256": _hash_bytes(porcelain), "size": len(porcelain)},
        "dirty_paths": [
            _dirty_path_evidence(
                root,
                relative,
                porcelain_status,
                porcelain_role,
                porcelain_record,
                porcelain_destination,
            )
            for (
                relative,
                porcelain_status,
                porcelain_role,
                porcelain_record,
                porcelain_destination,
            ) in dirty_records
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
        if (
            not isinstance(item, Mapping)
            or set(item)
            != {
                "directory",
                "file",
                "porcelain_destination",
                "porcelain_record",
                "porcelain_role",
                "porcelain_status",
                "relative_path",
            }
            or not isinstance(item.get("file"), Mapping)
            or item["file"].get("kind") not in {"missing", "regular", "directory"}
            or (
                item["file"].get("kind") == "directory"
                and not isinstance(item.get("directory"), Mapping)
            )
            or (
                item["file"].get("kind") != "directory"
                and item.get("directory") is not None
            )
            or not isinstance(item.get("porcelain_status"), str)
            or re.fullmatch(r"[ MADRCUT?!]{2}", item["porcelain_status"]) is None
            or not isinstance(item.get("porcelain_role"), str)
            or type(item.get("porcelain_record")) is not int
            or item["porcelain_record"] < 0
        ):
            raise HarnessSafetyError("reviewed checkout dirty state is invalid")
        rename_or_copy = "R" in item["porcelain_status"] or "C" in item["porcelain_status"]
        if (
            rename_or_copy
            and item["porcelain_role"] not in {"current", "original"}
        ) or (not rename_or_copy and item["porcelain_role"] != "path"):
            raise HarnessSafetyError("reviewed checkout dirty state is invalid")
        destination = item.get("porcelain_destination")
        if rename_or_copy:
            try:
                canonical_destination = _canonical_repository_relative_path(destination)
            except HarnessSafetyError as exc:
                raise HarnessSafetyError("reviewed checkout dirty state is invalid") from exc
            if (
                item["porcelain_role"] == "current"
                and item.get("relative_path") != canonical_destination
            ):
                raise HarnessSafetyError("reviewed checkout dirty state is invalid")
        elif destination is not None:
            raise HarnessSafetyError("reviewed checkout dirty state is invalid")
        relative = item.get("relative_path")
        try:
            canonical = _canonical_repository_relative_path(relative)
        except HarnessSafetyError as exc:
            raise HarnessSafetyError("reviewed checkout contains runtime or UAT dirt") from exc
        observed.append(canonical)
    if tuple(sorted(set(observed))) != allowed:
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


def _assert_secret_free_payload(
    payload: bytes,
    *,
    actual_secrets: tuple[str, ...],
    role: str,
    apply_patterns: bool = True,
) -> None:
    if (
        not isinstance(payload, bytes)
        or not isinstance(role, str)
        or re.fullmatch(r"[A-Za-z0-9._/-]{1,500}", role) is None
        or any(not isinstance(secret, str) for secret in actual_secrets)
    ):
        raise HarnessSafetyError("secret scan failed: invalid scanner input")
    encoded_secrets = tuple(secret.encode("utf-8") for secret in actual_secrets if secret)
    if any(secret in payload for secret in encoded_secrets) or (
        apply_patterns
        and any(pattern.search(payload) is not None for pattern in _SECRET_PATTERNS)
    ):
        raise HarnessSafetyError(f"secret scan failed: {role}")


def _canonical_secret_scan_object(payload: bytes, *, role: str) -> Mapping[str, object]:
    try:
        text = payload.decode("utf-8", errors="strict")
        value = json.loads(text)
    except (UnicodeError, ValueError, TypeError) as exc:
        raise HarnessSafetyError(f"secret scan failed: {role}") from exc
    if (
        not isinstance(value, Mapping)
        or canonical_json_line(dict(value)) != text
    ):
        raise HarnessSafetyError(f"secret scan failed: {role}")
    return value


def _runtime_summary_texts(
    payload: bytes,
    *,
    role: str,
) -> tuple[str, ...]:
    value = _canonical_secret_scan_object(payload, role=role)
    texts: list[str] = []

    def assertions(items: object, *, keys: set[str]) -> None:
        if not isinstance(items, list):
            raise HarnessSafetyError(f"secret scan failed: {role}")
        for item in items:
            if not isinstance(item, Mapping) or set(item) != keys:
                raise HarnessSafetyError(f"secret scan failed: {role}")
            visible = item.get("visible_assertions")
            if not isinstance(visible, list) or any(
                not isinstance(entry, str) for entry in visible
            ):
                raise HarnessSafetyError(f"secret scan failed: {role}")
            texts.extend(visible)

    def summaries(items: object, *, keys: set[str]) -> None:
        if not isinstance(items, list):
            raise HarnessSafetyError(f"secret scan failed: {role}")
        for item in items:
            if (
                not isinstance(item, Mapping)
                or set(item) != keys
                or not isinstance(item.get("safe_summary"), str)
            ):
                raise HarnessSafetyError(f"secret scan failed: {role}")
            texts.append(str(item["safe_summary"]))

    if role == "controller-evidence.json":
        if set(value) != _CONTROLLER_KEYS:
            raise HarnessSafetyError(f"secret scan failed: {role}")
        assertions(
            value.get("journey"),
            keys={"entity_ids", "status", "step_id", "visible_assertions"},
        )
        assertions(
            value.get("screenshots"),
            keys={
                "journey_step",
                "relative_path",
                "semantic_name",
                "state_id",
                "surface",
                "viewport",
                "visible_assertions",
            },
        )
        summaries(
            value.get("issues"),
            keys={"safe_summary", "severity", "step_id"},
        )
        summaries(
            value.get("human_uat_required"),
            keys={"gate_id", "safe_summary", "status"},
        )
    elif role == "journey.json":
        if set(value) != {"journey", "protocol", "run_id"}:
            raise HarnessSafetyError(f"secret scan failed: {role}")
        assertions(
            value.get("journey"),
            keys={"entity_ids", "status", "step_id", "visible_assertions"},
        )
    elif role == "issues.json":
        if set(value) != {"issues", "protocol", "run_id"}:
            raise HarnessSafetyError(f"secret scan failed: {role}")
        summaries(
            value.get("issues"),
            keys={"safe_summary", "severity", "step_id"},
        )
    elif role == "provider-summary.json":
        events = value.get("events")
        if not isinstance(events, list):
            raise HarnessSafetyError(f"secret scan failed: {role}")
        try:
            validated = summarize_provider_events(tuple(events))
        except HarnessSafetyError as exc:
            raise HarnessSafetyError(f"secret scan failed: {role}") from exc
        if value != validated:
            raise HarnessSafetyError(f"secret scan failed: {role}")
        for event in events:
            assert isinstance(event, Mapping)
            for key in ("error_class", "model", "operation", "provider", "voice"):
                candidate = event.get(key)
                if isinstance(candidate, str):
                    texts.append(candidate)
    elif role == "manifest.json":
        if set(value) != {
            "database_provenance",
            "human_uat_required",
            "issues_count",
            "protocol",
            "provider_event_count",
            "release",
            "run_id",
            "screenshots",
            "secret_scan",
            "seed",
            "source_head",
            "status",
        }:
            raise HarnessSafetyError(f"secret scan failed: {role}")
        assertions(
            value.get("screenshots"),
            keys={
                "byte_size",
                "journey_step",
                "relative_path",
                "semantic_name",
                "sha256",
                "source_run_id",
                "state_id",
                "surface",
                "viewport",
                "visible_assertions",
            },
        )
        summaries(
            value.get("human_uat_required"),
            keys={"gate_id", "safe_summary", "status"},
        )
    else:
        raise HarnessSafetyError(f"secret scan failed: {role}")
    return tuple(texts)


_RUNTIME_LOG_LINE = re.compile(
    r"(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) "
    r"(?P<logger>(?:duck_diary(?:\.[a-z_]+)*|uvicorn(?:\.[a-z_]+)*|"
    r"py\.warnings|asyncio|httpx)) "
    r"(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL) "
    r"(?P<message>[^\r\n]*)\n"
)


def _runtime_log_messages(
    payload: bytes,
    *,
    role: str,
    plan: RunPlan | None,
) -> tuple[str, ...]:
    if plan is None:
        raise HarnessSafetyError(f"secret scan failed: {role}")
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise HarnessSafetyError(f"secret scan failed: {role}") from exc
    messages: list[str] = []
    runtime_database = (
        "runtime database: db_mode=app path=" + str(plan.database)
    )
    offset = 0
    while offset < len(text):
        match = _RUNTIME_LOG_LINE.match(text, offset)
        if match is None:
            raise HarnessSafetyError(f"secret scan failed: {role}")
        try:
            datetime.strptime(match.group("timestamp"), "%Y-%m-%d %H:%M:%S,%f")
        except ValueError as exc:
            raise HarnessSafetyError(f"secret scan failed: {role}") from exc
        message = match.group("message")
        if message.startswith("runtime database:"):
            if message != runtime_database:
                raise HarnessSafetyError(f"secret scan failed: {role}")
            message = "runtime database: db_mode=app path=[PINNED_RUNTIME_DB]"
        messages.append(message)
        offset = match.end()
    return tuple(messages)


_STAT_EVIDENCE_KEYS = {
    "device",
    "inode",
    "kind",
    "mode",
    "mtime_ns",
    "nlink",
    "size",
}


def _valid_stat_evidence(value: object, *, hashed: bool | None = None) -> bool:
    if not isinstance(value, Mapping):
        return False
    if value == {"kind": "missing"}:
        return hashed is not True
    kind = value.get("kind")
    expected = _STAT_EVIDENCE_KEYS | ({"sha256"} if kind == "regular" else set())
    if (
        set(value) != expected
        or kind not in {"regular", "directory", "symlink", "special"}
        or any(
            type(value.get(key)) is not int or int(value[key]) < 0
            for key in ("device", "inode", "mode", "mtime_ns", "nlink", "size")
        )
        or value["nlink"] < 1
        or value["mode"] > 0o7777
        or (
            kind == "regular"
            and (
                not isinstance(value.get("sha256"), str)
                or SHA256_PATTERN.fullmatch(str(value["sha256"])) is None
            )
        )
        or (hashed is True and kind != "regular")
        or (hashed is False and kind == "regular")
    ):
        return False
    return True


def _valid_directory_evidence(value: object) -> bool:
    if (
        not isinstance(value, Mapping)
        or set(value) != {"digest", "entries", "root"}
        or not isinstance(value.get("digest"), str)
        or SHA256_PATTERN.fullmatch(str(value["digest"])) is None
        or not isinstance(value.get("entries"), list)
    ):
        return False
    root = value.get("root")
    entries = value["entries"]
    if root == {"kind": "missing"}:
        return entries == [] and value["digest"] == _hash_bytes(b"[]")
    if not _valid_stat_evidence(root, hashed=False) or root.get("kind") != "directory":
        return False
    observed_paths: list[str] = []
    for item in entries:
        if (
            not isinstance(item, Mapping)
            or set(item) != {"relative_path", "snapshot"}
            or not isinstance(item.get("relative_path"), str)
        ):
            return False
        try:
            relative = _canonical_repository_relative_path(item["relative_path"])
        except HarnessSafetyError:
            return False
        snapshot = item.get("snapshot")
        if not _valid_stat_evidence(snapshot):
            return False
        if snapshot.get("kind") not in {"regular", "directory"}:
            return False
        observed_paths.append(relative)
    if observed_paths != sorted(set(observed_paths)):
        return False
    digest_payload = json.dumps(
        entries,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return value["digest"] == _hash_bytes(digest_payload)


def _validate_resource_secret_index(
    value: Mapping[str, object],
    *,
    plan: RunPlan | None,
    role: str,
) -> None:
    failed = HarnessSafetyError(f"secret scan failed: {role}")
    if plan is None or set(value) != {
        "database",
        "dirty_paths",
        "git_head",
        "git_porcelain",
        "log",
        "media",
        "tts",
    }:
        raise failed
    database = value.get("database")
    porcelain = value.get("git_porcelain")
    if (
        not isinstance(database, Mapping)
        or set(database) != {"database", "logical_digest", "shm", "wal"}
        or not _valid_stat_evidence(database.get("database"))
        or not _valid_stat_evidence(database.get("wal"))
        or not _valid_stat_evidence(database.get("shm"))
        or (
            database.get("logical_digest") is not None
            and (
                not isinstance(database.get("logical_digest"), str)
                or SHA256_PATTERN.fullmatch(str(database["logical_digest"])) is None
            )
        )
        or not _valid_stat_evidence(value.get("log"))
        or not _valid_directory_evidence(value.get("media"))
        or not _valid_directory_evidence(value.get("tts"))
        or value.get("git_head") != plan.source_head
        or not isinstance(porcelain, Mapping)
        or set(porcelain) != {"sha256", "size"}
        or not isinstance(porcelain.get("sha256"), str)
        or SHA256_PATTERN.fullmatch(str(porcelain["sha256"])) is None
        or type(porcelain.get("size")) is not int
        or porcelain["size"] < 0
        or not isinstance(value.get("dirty_paths"), list)
    ):
        raise failed
    database_kind = database["database"].get("kind")
    if (
        (database_kind == "missing" and database.get("logical_digest") is not None)
        or (database_kind != "missing" and database.get("logical_digest") is None)
    ):
        raise failed
    for item in value["dirty_paths"]:
        if (
            not isinstance(item, Mapping)
            or set(item)
            != {
                "directory",
                "file",
                "porcelain_destination",
                "porcelain_record",
                "porcelain_role",
                "porcelain_status",
                "relative_path",
            }
            or not _valid_stat_evidence(item.get("file"))
            or (
                item["file"].get("kind") == "directory"
                and not _valid_directory_evidence(item.get("directory"))
            )
            or (
                item["file"].get("kind") != "directory"
                and item.get("directory") is not None
            )
        ):
            raise failed
    dirty_names = tuple(
        sorted(
            {
                item.get("relative_path")
                for item in value["dirty_paths"]
                if isinstance(item, Mapping)
                and isinstance(item.get("relative_path"), str)
            }
        )
    )
    try:
        validate_reviewed_checkout(
            value,
            expected_head=plan.source_head,
            allowed_unrelated_dirty_paths=dirty_names,
        )
    except HarnessSafetyError as exc:
        raise failed from exc


def _valid_database_timestamp(value: object) -> bool:
    if not isinstance(value, str) or re.fullmatch(
        r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d{6})?",
        value,
    ) is None:
        return False
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return False
    return True


def _valid_database_date(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _seed_baseline_texts(
    value: Mapping[str, object],
    *,
    plan: RunPlan | None,
    role: str,
) -> tuple[str, ...]:
    failed = HarnessSafetyError(f"secret scan failed: {role}")
    if plan is None:
        raise failed
    try:
        _validated_seed_baseline(plan, value)
    except HarnessSafetyError as exc:
        raise failed from exc
    table_ids = value.get("table_ids")
    dimensions = value.get("dimensions")
    reporting = value.get("reporting_source")
    if (
        not isinstance(table_ids, Mapping)
        or not isinstance(dimensions, list)
        or not isinstance(reporting, Mapping)
        or not _valid_directory_evidence(value.get("media_snapshot"))
        or not _valid_directory_evidence(value.get("tts_snapshot"))
    ):
        raise failed
    uuid_tables = {"avatar_media", "chat_requests", "roster_requests"}
    for table, identifiers in table_ids.items():
        if not isinstance(identifiers, list):
            raise failed
        if table in uuid_tables:
            if any(
                not isinstance(identifier, str)
                or UUID4_PATTERN.fullmatch(identifier) is None
                for identifier in identifiers
            ):
                raise failed
        elif any(type(identifier) is not int or identifier <= 0 for identifier in identifiers):
            raise failed
    texts = [
        str(item[key])
        for item in dimensions
        if isinstance(item, Mapping)
        for key in ("key", "name")
    ]
    if len(texts) != len(dimensions) * 2:
        raise failed

    analysis_jobs = reporting.get("analysis_jobs")
    assessments = reporting.get("assessments")
    conversations = reporting.get("conversations")
    if (
        not isinstance(analysis_jobs, list)
        or any(
            not isinstance(row, list)
            or len(row) != 4
            or any(type(row[index]) is not int or row[index] <= 0 for index in range(3))
            or row[3] not in {"pending", "processing", "succeeded", "failed"}
            for row in analysis_jobs
        )
        or not isinstance(assessments, list)
        or any(
            not isinstance(row, list)
            or len(row) != 5
            or any(type(row[index]) is not int or row[index] <= 0 for index in range(3))
            or row[3] not in {"pending", "draft", "confirmed"}
            or (row[4] is not None and type(row[4]) not in {int, float})
            for row in assessments
        )
        or not isinstance(conversations, list)
        or any(
            not isinstance(row, list)
            or len(row) != 6
            or type(row[0]) is not int
            or row[0] <= 0
            or type(row[1]) is not int
            or row[1] <= 0
            or not _valid_database_date(row[2])
            or (
                row[3] is not None
                and (
                    not isinstance(row[3], str)
                    or re.fullmatch(
                        r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d{6})?",
                        row[3],
                    )
                    is None
                )
            )
            or row[4] not in {"active", "ended"}
            or (row[5] is not None and (type(row[5]) is not int or row[5] <= 0))
            for row in conversations
        )
    ):
        raise failed
    texts.extend(str(row[3]) for row in analysis_jobs)
    texts.extend(str(row[3]) for row in assessments)
    texts.extend(str(row[4]) for row in conversations)
    return tuple(texts)


def _database_response_texts(
    *,
    table: str,
    operation: str | None,
    payload: object,
    failed: HarnessSafetyError,
) -> tuple[str, ...]:
    roster_operations = {
        "auto_roster",
        "child_create",
        "daily_roster",
        "duck_create",
        "monthly_roster",
    }
    if table == "roster_requests" and operation not in roster_operations:
        raise failed
    if payload is None:
        if table == "roster_requests":
            raise failed
        return ()
    if not isinstance(payload, str) or not payload:
        raise failed
    try:
        value = json.loads(payload)
    except (TypeError, ValueError) as exc:
        raise failed from exc
    if not isinstance(value, Mapping):
        raise failed

    def request_id(candidate: object) -> bool:
        return isinstance(candidate, str) and UUID4_PATTERN.fullmatch(candidate) is not None

    def child_ids(candidate: object) -> bool:
        return (
            isinstance(candidate, list)
            and candidate
            and all(type(item) is int and item > 0 for item in candidate)
            and len(candidate) == len(set(candidate))
        )

    def avatar(candidate: object) -> bool:
        if candidate is None:
            return True
        prefix = "/api/media/avatars/"
        return (
            isinstance(candidate, str)
            and candidate.startswith(prefix)
            and UUID4_PATTERN.fullmatch(candidate[len(prefix) :]) is not None
        )

    def text_field(candidate: object, *, maximum: int, optional: bool = False) -> bool:
        if optional and candidate is None:
            return True
        return (
            isinstance(candidate, str)
            and candidate == candidate.strip()
            and 1 <= len(candidate) <= maximum
            and not any(character in "\r\n\x00" for character in candidate)
        )

    if table == "chat_requests":
        if (
            set(value)
            != {
                "child_message_id",
                "conversation_id",
                "diary_message_id",
                "end_reason",
                "ended",
                "replayed",
                "reply",
                "request_id",
                "round",
            }
            or not request_id(value.get("request_id"))
            or any(
                type(value.get(key)) is not int or value[key] <= 0
                for key in (
                    "child_message_id",
                    "conversation_id",
                    "diary_message_id",
                    "round",
                )
            )
            or type(value.get("ended")) is not bool
            or type(value.get("replayed")) is not bool
            or value.get("end_reason") not in {None, "complete", "manual", "max_rounds"}
            or not isinstance(value.get("reply"), str)
        ):
            raise failed
        return (str(value["reply"]),)
    if table != "roster_requests" or operation is None:
        raise failed
    if operation == "child_create":
        if (
            set(value) != {"active", "avatar", "id", "name", "nickname"}
            or type(value.get("id")) is not int
            or value["id"] <= 0
            or type(value.get("active")) is not bool
            or not avatar(value.get("avatar"))
            or not text_field(value.get("name"), maximum=64)
            or not text_field(value.get("nickname"), maximum=64, optional=True)
        ):
            raise failed
        return tuple(
            candidate
            for candidate in (value["name"], value["nickname"])
            if isinstance(candidate, str)
        )
    if operation == "duck_create":
        if (
            set(value) != {"avatar", "id", "name", "note", "status"}
            or type(value.get("id")) is not int
            or value["id"] <= 0
            or not avatar(value.get("avatar"))
            or not text_field(value.get("name"), maximum=64)
            or not text_field(value.get("status"), maximum=255, optional=True)
            or not text_field(value.get("note"), maximum=2000, optional=True)
        ):
            raise failed
        return tuple(
            candidate
            for candidate in (value["name"], value["status"], value["note"])
            if isinstance(candidate, str)
        )
    if (
        not request_id(value.get("request_id"))
        or value.get("replayed") is not False
    ):
        raise failed
    keys = set(value)
    if operation == "daily_roster":
        if (
            keys != {"child_ids", "cycle", "date", "replayed", "request_id"}
            or not child_ids(value.get("child_ids"))
            or not isinstance(value.get("cycle"), str)
            or not 1 <= len(value["cycle"]) <= 64
            or not _valid_database_date(value.get("date"))
        ):
            raise failed
        return ()
    expected_keys = (
        {"month", "replayed", "request_id", "schedule"}
        if operation == "monthly_roster"
        else {"replayed", "request_id", "schedule"}
    )
    if operation not in {"auto_roster", "monthly_roster"} or keys != expected_keys:
        raise failed
    schedule = value.get("schedule")
    if not isinstance(schedule, list):
        raise failed
    monthly = operation == "monthly_roster"
    if monthly and (
        not isinstance(value.get("month"), str)
        or re.fullmatch(r"\d{4}-(?:0[1-9]|1[0-2])", value["month"]) is None
    ):
        raise failed
    for item in schedule:
        expected = {"child_ids", "cycle", "date"} if monthly else {"child_ids", "date"}
        if (
            not isinstance(item, Mapping)
            or set(item) != expected
            or not child_ids(item.get("child_ids"))
            or not _valid_database_date(item.get("date"))
            or (
                monthly
                and (
                    not isinstance(item.get("cycle"), str)
                    or not 1 <= len(item["cycle"]) <= 64
                )
            )
        ):
            raise failed
    return ()


def _runtime_database_texts(
    *,
    plan: RunPlan | None,
    role: str,
) -> tuple[str, ...]:
    failed = HarnessSafetyError(f"secret scan failed: {role}")
    if plan is None:
        raise failed
    try:
        with _sqlite_shadow(plan.database) as shadow, sqlite3.connect(
            f"{shadow.as_uri()}?mode=ro",
            uri=True,
        ) as connection:
            connection.execute("PRAGMA query_only=ON")
            if connection.execute("PRAGMA query_only").fetchone() != (1,):
                raise failed
            schema_objects = connection.execute(
                "SELECT type, name FROM sqlite_schema "
                "WHERE name NOT LIKE 'sqlite_%' AND type IN ('table', 'view', 'trigger') "
                "ORDER BY type, name"
            ).fetchall()
            tables = {name for kind, name in schema_objects if kind == "table"}
            if (
                any(kind != "table" for kind, _name in schema_objects)
                or tables != set(_RUNTIME_DB_COLUMNS)
            ):
                raise failed
            for table, expected_columns in _RUNTIME_DB_COLUMNS.items():
                columns = tuple(
                    row[1]
                    for row in connection.execute(
                        f'PRAGMA table_info("{table}")'
                    ).fetchall()
                )
                if columns != expected_columns:
                    raise failed

            credential_rows = connection.execute(
                "SELECT id, pin_salt, pin_hash, created_at, updated_at "
                "FROM teacher_credentials ORDER BY id"
            ).fetchall()
            if (
                len(credential_rows) != 1
                or credential_rows[0][0] != 1
                or not isinstance(credential_rows[0][1], str)
                or re.fullmatch(r"[0-9a-f]{32}", credential_rows[0][1]) is None
                or not isinstance(credential_rows[0][2], str)
                or re.fullmatch(r"[0-9a-f]{128}", credential_rows[0][2]) is None
                or not _valid_database_timestamp(credential_rows[0][3])
                or not _valid_database_timestamp(credential_rows[0][4])
            ):
                raise failed
            session_rows = connection.execute(
                "SELECT id, token_hash, created_at FROM teacher_sessions ORDER BY id"
            ).fetchall()
            if (
                not session_rows
                or len({row[1] for row in session_rows}) != len(session_rows)
                or any(
                    type(row[0]) is not int
                    or row[0] <= 0
                    or not isinstance(row[1], str)
                    or re.fullmatch(r"[0-9a-f]{64}", row[1]) is None
                    or not _valid_database_timestamp(row[2])
                    for row in session_rows
                )
            ):
                raise failed
            if connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchall() != [("20260902_0002",)]:
                raise failed

            texts: list[str] = []
            for table, columns in _RUNTIME_DB_TEXT_COLUMNS.items():
                selection = ", ".join(f'"{column}"' for column in columns)
                rows = connection.execute(
                    f'SELECT {selection} FROM "{table}" ORDER BY rowid'
                ).fetchall()
                for row in rows:
                    for value in row:
                        if value is None:
                            continue
                        if not isinstance(value, str):
                            raise failed
                        texts.append(value)
            for table in ("chat_requests", "roster_requests"):
                selection = (
                    "NULL, response_json"
                    if table == "chat_requests"
                    else "operation, response_json"
                )
                rows = connection.execute(
                    f'SELECT {selection} FROM "{table}" ORDER BY rowid'
                ).fetchall()
                for operation, response_json in rows:
                    texts.extend(
                        _database_response_texts(
                            table=table,
                            operation=operation,
                            payload=response_json,
                            failed=failed,
                        )
                    )
    except HarnessSafetyError:
        raise
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        raise failed from exc
    return tuple(texts)


def _validate_checksum_secret_index(
    payload: bytes,
    *,
    plan: RunPlan | None,
) -> None:
    inventory = _checksum_inventory(payload)
    if plan is None:
        return
    observed: dict[str, str] = {}
    try:
        candidates = sorted(
            plan.root.rglob("*"),
            key=lambda item: item.relative_to(plan.root).as_posix(),
        )
    except OSError as exc:
        raise HarnessSafetyError("secret scan failed: SHA256SUMS") from exc
    for candidate in candidates:
        if candidate == plan.checksums:
            continue
        entry = candidate.lstat()
        if stat.S_ISDIR(entry.st_mode) and not stat.S_ISLNK(entry.st_mode):
            continue
        if not stat.S_ISREG(entry.st_mode) or entry.st_nlink != 1:
            raise HarnessSafetyError("secret scan failed: SHA256SUMS")
        relative = candidate.relative_to(plan.root).as_posix()
        observed[relative] = _file_evidence(candidate)["sha256"]
    if plan.manifest.name not in observed:
        observed[plan.manifest.name] = str(inventory.get(plan.manifest.name, ""))
    if inventory != observed:
        raise HarnessSafetyError("secret scan failed: SHA256SUMS")


def _assert_runtime_secrets_free_payload(
    payload: bytes,
    *,
    runtime_secrets: tuple[str, ...],
    role: str,
    pinned_plan: RunPlan | None,
) -> None:
    if role.startswith("reviewed-source/"):
        return
    if role == "reviewed-source.json":
        if pinned_plan is None or payload != canonical_json_line(
            _source_manifest_value(pinned_plan)
        ).encode("utf-8"):
            raise HarnessSafetyError("secret scan failed: reviewed-source.json")
        return
    if role == "SHA256SUMS":
        _validate_checksum_secret_index(payload, plan=pinned_plan)
        return
    if role == "seed-baseline.json":
        baseline = _canonical_secret_scan_object(payload, role=role)
        texts = _seed_baseline_texts(
            baseline,
            plan=pinned_plan,
            role=role,
        )
        _assert_secret_free_payload(
            canonical_json_line(list(texts)).encode("utf-8"),
            actual_secrets=runtime_secrets,
            role=role,
            apply_patterns=False,
        )
        return
    if role in {
        "controller-evidence.json",
        "issues.json",
        "journey.json",
        "manifest.json",
        "provider-summary.json",
    }:
        texts = _runtime_summary_texts(payload, role=role)
        _assert_secret_free_payload(
            canonical_json_line(list(texts)).encode("utf-8"),
            actual_secrets=runtime_secrets,
            role=role,
            apply_patterns=False,
        )
        return
    if role in {
        "duck-diary-uat.db",
        "duck-diary-uat.db-shm",
        "duck-diary-uat.db-wal",
    }:
        texts = _runtime_database_texts(plan=pinned_plan, role=role)
        _assert_secret_free_payload(
            canonical_json_line(list(texts)).encode("utf-8"),
            actual_secrets=runtime_secrets,
            role=role,
            apply_patterns=False,
        )
        return
    if role in {"logs/app.log", "logs/server.stderr.log"}:
        messages = _runtime_log_messages(
            payload,
            role=role,
            plan=pinned_plan,
        )
        _assert_secret_free_payload(
            canonical_json_line(list(messages)).encode("utf-8"),
            actual_secrets=runtime_secrets,
            role=role,
            apply_patterns=False,
        )
        return
    if role in {"resources.before.json", "resources.after.json"}:
        value = _canonical_secret_scan_object(payload, role=role)
        _validate_resource_secret_index(value, plan=pinned_plan, role=role)
        return
    _assert_secret_free_payload(
        payload,
        actual_secrets=runtime_secrets,
        role=role,
        apply_patterns=False,
    )


def scan_retained_artifacts(
    root: Path,
    *,
    provider_secrets: tuple[str, ...],
    runtime_secrets: tuple[str, ...],
    pinned_plan: RunPlan | None = None,
) -> None:
    base = _absolute(root)
    if pinned_plan is not None:
        if base != pinned_plan.root:
            raise HarnessSafetyError("secret scan failed: retained root identity")
        assert_run_plan_identity(pinned_plan)
    _safe_owned_directory(base, label="retained artifact root")
    if any(
        not isinstance(secret, str)
        for secret in (*provider_secrets, *runtime_secrets)
    ):
        raise HarnessSafetyError("secret scan failed: invalid scanner input")
    try:
        candidates = sorted(base.rglob("*"), key=lambda item: item.relative_to(base).as_posix())
    except OSError as exc:
        raise HarnessSafetyError("secret scan failed: artifact tree") from exc
    total = 0
    protected_indexes: dict[str, bytes] = {}
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
        role = path.relative_to(base).as_posix()
        if role in {"resources.before.json", "resources.after.json"}:
            protected_indexes[role] = payload
        reviewed_source = role.startswith("reviewed-source/")
        _assert_secret_free_payload(
            payload,
            actual_secrets=provider_secrets,
            role=role,
            # The retained source tree is already pinned byte-for-byte to the
            # reviewed Git objects and necessarily contains the scanner's own
            # detector literals.  Registered live secrets remain forbidden.
            apply_patterns=not reviewed_source,
        )
        _assert_runtime_secrets_free_payload(
            payload,
            runtime_secrets=runtime_secrets,
            role=role,
            pinned_plan=pinned_plan,
        )
        if payload.startswith(b"\x89PNG\r\n\x1a\n"):
            try:
                _validate_png_container(payload)
            except HarnessSafetyError as exc:
                raise HarnessSafetyError("secret scan failed: PNG metadata") from exc
    if protected_indexes and (
        set(protected_indexes) != {"resources.before.json", "resources.after.json"}
        or protected_indexes["resources.before.json"]
        != protected_indexes["resources.after.json"]
    ):
        raise HarnessSafetyError("secret scan failed: protected resource indexes")
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
    if depth > 5:
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
        or (surface, item["journey_step"], viewport)
        != REQUIRED_SCREENSHOT_STATES[state_id]
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
        if set(item["entity_ids"]) != STEP_PROVENANCE_KEYS[item["step_id"]]:
            raise HarnessSafetyError("controller evidence journey provenance is invalid")
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
    try:
        payload = _read_pinned_run_file(
            plan,
            path,
            max_bytes=100_000_000,
        )
    except HarnessSafetyError as exc:
        raise HarnessSafetyError("database provenance avatar file mismatch") from exc
    if (
        len(payload) != size_bytes
        or _hash_bytes(payload) != expected_sha
    ):
        raise HarnessSafetyError("database provenance avatar file mismatch")
    try:
        from PIL import Image

        with Image.open(io.BytesIO(payload)) as image:
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


def _valid_native_audio_playback(value: object) -> bool:
    return (
        isinstance(value, Mapping)
        and set(value) == PLAYBACK_EVIDENCE_KEYS
        and value["play_promise"] == "fulfilled"
        and value["events"] == ["playing", "ended"]
        and value["error"] is None
        and value["speech_synthesis_fallback"] is False
    )


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
            roster_request_ids = entity_ids["monthly_roster_request_ids"]
            if (
                not isinstance(attempts, list)
                or len(attempts) != 2
                or any(
                    not isinstance(attempt, Mapping)
                    or set(attempt) != ROSTER_TELEMETRY_KEYS
                    for attempt in attempts
                )
                or roster_request_ids
                != [attempt.get("request_id") for attempt in attempts]
                or [attempt["kind"] for attempt in attempts]
                != ["roster_attempt", "roster_attempt"]
                or [attempt["method"] for attempt in attempts] != ["POST", "POST"]
                or [attempt["path"] for attempt in attempts]
                != ["/api/roster/month", "/api/roster/month"]
                or [attempt["order"] for attempt in attempts] != [1, 2]
                or [attempt["status"] for attempt in attempts] != [409, 200]
                or [attempt["error_code"] for attempt in attempts]
                != ["ROSTER_DATE_CONFLICT", None]
                or [attempt["replace_existing"] for attempt in attempts]
                != [False, True]
                or attempts[0]["canonical_body_sha256"]
                != attempts[1]["canonical_body_sha256"]
                or not isinstance(attempts[0]["canonical_body_sha256"], str)
                or SHA256_PATTERN.fullmatch(attempts[0]["canonical_body_sha256"])
                is None
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
                "SELECT operation, status, response_json, last_error_code, last_error_message, payload_hash "
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
            expected_body = {
                "cycle": next(iter(cycles)) if len(cycles) == 1 else None,
                "entries": [
                    {"child_ids": item["child_ids"], "date": item["date"]}
                    for item in expected_schedule
                ],
                "month": retry_response.get("month")
                if isinstance(retry_response, dict)
                else None,
            }
            expected_body_sha = _hash_bytes(
                json.dumps(
                    expected_body,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            )
            expected_retry_hash = _hash_bytes(
                json.dumps(
                    {
                        **expected_body,
                        "operation": "monthly_roster",
                        "replace_existing": True,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            )
            if (
                retry_row is None
                or retry_row[:2] != ("monthly_roster", "succeeded")
                or retry_row[3:5] != (None, None)
                or not isinstance(retry_response, dict)
                or retry_response.get("request_id") != retry_request_id
                or retry_response.get("replayed") is not False
                or len(cycles) != 1
                or not isinstance(next(iter(cycles)), str)
                or not next(iter(cycles))
                or retry_response.get("schedule") != expected_schedule
                or attempts[0]["canonical_body_sha256"] != expected_body_sha
                or retry_row[5] != expected_retry_hash
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
                or conversation[4] not in {"complete", "max_rounds"}
                or type(conversation[5]) is not int
            ):
                raise HarnessSafetyError("database provenance conversation mismatch")
            messages = connection.execute(
                "SELECT id, role, text FROM messages WHERE conversation_id = ? ORDER BY id",
                (conversation_id,),
            ).fetchall()
            if (
                len(messages) not in {2, 4, 6}
                or messages[-1][0] != conversation[5]
                or conversation[4]
                != ("max_rounds" if len(messages) == 6 else "complete")
                or any(row[0] in baseline_ids["messages"] for row in messages)
                or [row[1] for row in messages] != ["child", "diary"] * (len(messages) // 2)
                or any(not isinstance(row[2], str) or not row[2].strip() for row in messages)
                or any("我" not in row[2] for row in messages[::2])
            ):
                raise HarnessSafetyError("database provenance frozen messages mismatch")
            tts_evidence = entity_ids["tts_evidence"]
            child_name_row = connection.execute(
                "SELECT name, nickname FROM children WHERE id = ?", (child_id,)
            ).fetchone()
            if (
                child_name_row is None
                or not isinstance(child_name_row[0], str)
                or not child_name_row[0]
                or (
                    child_name_row[1] is not None
                    and not isinstance(child_name_row[1], str)
                )
            ):
                raise HarnessSafetyError("database provenance TTS source mismatch")
            child_display_name = child_name_row[1] or child_name_row[0]
            greeting = (
                f"你好呀，{child_display_name}！我是鸭鸭日记本，今天想听你讲讲照顾小鸭的事～"
            )
            expected_tts = [
                ("opening_greeting", None, greeting),
                *[
                    ("diary_reply", message[0], message[2])
                    for message in messages[1::2]
                ],
            ]
            if not isinstance(tts_evidence, list) or len(tts_evidence) != len(expected_tts):
                raise HarnessSafetyError("database provenance TTS source mismatch")
            for evidence, (kind, source_message_id, text) in zip(
                tts_evidence, expected_tts, strict=True
            ):
                stripped_text = text.strip()
                effective_text = stripped_text[:500]
                expected_cache = (
                    "tts-cache/"
                    + hashlib.md5(
                        effective_text.encode("utf-8"), usedforsecurity=False
                    ).hexdigest()
                    + ".mp3"
                )
                if (
                    not isinstance(evidence, Mapping)
                    or set(evidence) != TTS_EVIDENCE_KEYS
                    or evidence["kind"] != kind
                    or not _valid_native_audio_playback(evidence["playback"])
                    or evidence["source_message_id"] != source_message_id
                    or evidence["text_sha256"] != _hash_bytes(text.encode("utf-8"))
                    or evidence["effective_text_sha256"]
                    != _hash_bytes(effective_text.encode("utf-8"))
                    or evidence["truncated"] is not (len(stripped_text) > 500)
                    or not isinstance(evidence["audio_sha256"], str)
                    or SHA256_PATTERN.fullmatch(evidence["audio_sha256"]) is None
                    or evidence["cache_relative_path"] != expected_cache
                    or expected_cache.removeprefix("tts-cache/") in baseline_tts_files
                    or _file_evidence(plan.root / expected_cache).get("sha256")
                    != evidence["audio_sha256"]
                ):
                    raise HarnessSafetyError("database provenance TTS source mismatch")
            chat_request_ids = entity_ids["chat_request_ids"]
            request_count = len(messages) // 2
            if (
                not isinstance(chat_request_ids, list)
                or len(chat_request_ids) != request_count
                or len(set(chat_request_ids)) != len(chat_request_ids)
                or any(
                    not isinstance(value, str)
                    or UUID4_PATTERN.fullmatch(value) is None
                    or value in baseline_ids["chat_requests"]
                    for value in chat_request_ids
                )
            ):
                raise HarnessSafetyError("database provenance chat request identities are invalid")
            provider_request_ids = (
                chat_request_ids[:2]
                if request_count == 3
                else chat_request_ids
            )
            local_terminal_request_id = (
                chat_request_ids[2] if request_count == 3 else None
            )
            if (
                entity_ids["provider_chat_request_ids"] != provider_request_ids
                or entity_ids["local_terminal_request_id"]
                != local_terminal_request_id
            ):
                raise HarnessSafetyError("database provenance chat provider boundary mismatch")
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
                    or set(response)
                    != {
                        "child_message_id",
                        "conversation_id",
                        "diary_message_id",
                        "end_reason",
                        "ended",
                        "replayed",
                        "reply",
                        "request_id",
                        "round",
                    }
                    or response.get("request_id") != request_id
                    or response.get("conversation_id") != conversation_id
                    or response.get("child_message_id") != child_message[0]
                    or response.get("diary_message_id") != diary_message[0]
                    or response.get("reply") != diary_message[2]
                    or response.get("round") != index + 1
                    or response.get("replayed") is not False
                    or response.get("ended") is not (index == request_count - 1)
                    or response.get("end_reason")
                    != (
                        conversation[4]
                        if index == request_count - 1
                        else None
                    )
                    or (
                        conversation[4] == "max_rounds"
                        and index == request_count - 1
                        and response.get("reply") != FROZEN_MAX_ROUNDS_REPLY
                    )
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
            search_request = entity_ids["search_request"]
            if (
                not isinstance(page_one, list)
                or not isinstance(page_two, list)
                or len(page_one) != 5
                or not page_two
                or any(type(value) is not int or value <= 0 for value in page_one + page_two)
                or len(set(page_one)) != len(page_one)
                or len(set(page_two)) != len(page_two)
                or set(page_one) & set(page_two)
                or result_id != conversation_id
                or result_id not in set(page_one + page_two)
            ):
                raise HarnessSafetyError("database provenance search mismatch")
            if (
                not isinstance(search_request, Mapping)
                or set(search_request)
                != {
                    "analysis_status",
                    "child_id",
                    "date_from",
                    "date_to",
                    "end_reason",
                    "keyword",
                    "limit",
                    "review_status",
                    "sort",
                }
                or search_request["analysis_status"] != ["succeeded"]
                or search_request["review_status"] != ["confirmed"]
                or search_request["end_reason"] != ["max_rounds", "complete"]
                or conversation[4] not in search_request["end_reason"]
                or search_request["sort"] != "completed_desc"
                or search_request["child_id"] is not None
                or search_request["keyword"] != "我"
                or search_request["limit"] != 5
            ):
                raise HarnessSafetyError("database provenance search request mismatch")
            snapshot_row = connection.execute(
                "SELECT MAX(id) FROM conversations"
            ).fetchone()
            if snapshot_row is None or type(snapshot_row[0]) is not int:
                raise HarnessSafetyError("database provenance search rows mismatch")
            snapshot_max_id = snapshot_row[0]
            search_rows = connection.execute(
                "SELECT c.id, c.child_id, c.date, c.ended_at, c.status, "
                "c.end_reason, c.frozen_last_message_id "
                "FROM conversations c "
                "JOIN analysis_jobs j ON j.conversation_id = c.id "
                "WHERE c.status = 'ended' AND c.ended_at IS NOT NULL "
                "AND c.frozen_last_message_id IS NOT NULL AND c.id <= ? "
                "AND c.end_reason IN ('max_rounds', 'complete') "
                "AND j.status = 'succeeded' "
                "AND EXISTS (SELECT 1 FROM assessments a "
                "WHERE a.conversation_id = c.id AND a.status = 'confirmed') "
                "AND EXISTS (SELECT 1 FROM messages m "
                "WHERE m.conversation_id = c.id "
                "AND m.id <= c.frozen_last_message_id "
                "AND m.role IN ('child', 'diary') AND instr(m.text, ?) > 0) "
                "ORDER BY c.ended_at DESC, c.id DESC",
                (snapshot_max_id, search_request["keyword"]),
            ).fetchall()
            if (
                len(search_rows) <= 5
                or len({row[0] for row in search_rows}) != len(search_rows)
            ):
                raise HarnessSafetyError("database provenance search rows mismatch")
            expected_date_from = min(str(row[2]) for row in search_rows)
            expected_date_to = max(str(row[2]) for row in search_rows)
            try:
                canonical_date_from = date.fromisoformat(
                    str(search_request["date_from"])
                ).isoformat()
                canonical_date_to = date.fromisoformat(
                    str(search_request["date_to"])
                ).isoformat()
            except ValueError:
                raise HarnessSafetyError(
                    "database provenance search request mismatch"
                ) from None
            if (
                canonical_date_from != search_request["date_from"]
                or canonical_date_to != search_request["date_to"]
                or canonical_date_from != expected_date_from
                or canonical_date_to != expected_date_to
                or not canonical_date_from <= conversation[1] <= canonical_date_to
            ):
                raise HarnessSafetyError("database provenance search request mismatch")
            expected_ids = [row[0] for row in search_rows]
            if page_one != expected_ids[:5] or page_two != expected_ids[5:10]:
                raise HarnessSafetyError("database provenance search result mismatch")
            cursor = _decode_search_cursor(
                entity_ids["search_cursor"],
                search_request=search_request,
            )
            search_by_id = {row[0]: row for row in search_rows}
            expected_cursor_time = datetime.fromisoformat(
                str(search_by_id[page_one[-1]][3])
            ).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            if (
                cursor["id"] != page_one[-1]
                or cursor["ended_at"] != expected_cursor_time
                or cursor["snapshot_max_id"] != snapshot_max_id
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
    if set(combined) != _CONTROLLER_PROVENANCE_KEYS:
        raise HarnessSafetyError("controller entity identifiers are incomplete")
    return combined


def _inject_private_roster_provenance(
    events: tuple[Mapping[str, object], ...],
    controller_entity_ids: Mapping[str, object],
) -> dict[str, object]:
    """Add server-only roster telemetry after binding its visible request ids."""

    if set(controller_entity_ids) != _CONTROLLER_PROVENANCE_KEYS:
        raise HarnessSafetyError("controller entity identifiers are incomplete")
    request_ids = controller_entity_ids.get("monthly_roster_request_ids")
    summary = summarize_provider_events(events)
    roster_events = [
        event for event in summary["events"] if event.get("kind") == "roster_attempt"
    ]
    if (
        not isinstance(request_ids, list)
        or len(request_ids) != 2
        or len(set(request_ids)) != 2
        or any(
            not isinstance(request_id, str)
            or UUID4_PATTERN.fullmatch(request_id) is None
            for request_id in request_ids
        )
        or summary["events"][:2] != roster_events
        or len(roster_events) != 2
        or [event.get("request_id") for event in roster_events] != request_ids
        or [event.get("order") for event in roster_events] != [1, 2]
        or [event.get("method") for event in roster_events] != ["POST", "POST"]
        or [event.get("path") for event in roster_events]
        != ["/api/roster/month", "/api/roster/month"]
        or [event.get("status") for event in roster_events] != [409, 200]
        or [event.get("error_code") for event in roster_events]
        != ["ROSTER_DATE_CONFLICT", None]
        or [event.get("replace_existing") for event in roster_events]
        != [False, True]
        or roster_events[0].get("canonical_body_sha256")
        != roster_events[1].get("canonical_body_sha256")
    ):
        raise HarnessSafetyError("provider telemetry roster evidence mismatch")
    return {
        **dict(controller_entity_ids),
        "monthly_roster_attempts": roster_events,
    }


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
    provider_chat_request_ids = entity_ids.get("provider_chat_request_ids")
    local_terminal_request_id = entity_ids.get("local_terminal_request_id")
    roster_attempts = entity_ids.get("monthly_roster_attempts")
    roster_request_ids = entity_ids.get("monthly_roster_request_ids")
    tts_evidence = entity_ids.get("tts_evidence")
    if (
        type(conversation_id) is not int
        or conversation_id <= 0
        or type(analysis_job_id) is not int
        or analysis_job_id <= 0
        or not isinstance(chat_request_ids, list)
        or not 1 <= len(chat_request_ids) <= 3
        or len(set(chat_request_ids)) != len(chat_request_ids)
        or any(
            not isinstance(request_id, str)
            or UUID4_PATTERN.fullmatch(request_id) is None
            for request_id in chat_request_ids
        )
        or provider_chat_request_ids
        != (chat_request_ids[:2] if len(chat_request_ids) == 3 else chat_request_ids)
        or local_terminal_request_id
        != (chat_request_ids[2] if len(chat_request_ids) == 3 else None)
        or not isinstance(roster_attempts, list)
        or len(roster_attempts) != 2
        or roster_request_ids
        != [attempt.get("request_id") for attempt in roster_attempts]
        or not isinstance(tts_evidence, list)
        or len(tts_evidence) != len(chat_request_ids) + 1
    ):
        raise HarnessSafetyError("provider telemetry is incomplete")
    roster_events = [
        event for event in summary["events"] if event.get("kind") == "roster_attempt"
    ]
    if (
        summary["events"][:2] != roster_events
        or roster_events != roster_attempts
        or [event["order"] for event in roster_events] != [1, 2]
        or [event["method"] for event in roster_events] != ["POST", "POST"]
        or [event["path"] for event in roster_events]
        != ["/api/roster/month", "/api/roster/month"]
        or [event["status"] for event in roster_events] != [409, 200]
        or [event["error_code"] for event in roster_events]
        != ["ROSTER_DATE_CONFLICT", None]
        or [event["replace_existing"] for event in roster_events] != [False, True]
        or roster_events[0]["request_id"] == roster_events[1]["request_id"]
        or roster_events[0]["canonical_body_sha256"]
        != roster_events[1]["canonical_body_sha256"]
    ):
        raise HarnessSafetyError("provider telemetry roster evidence mismatch")
    validated_tts: list[Mapping[str, object]] = []
    for index, evidence in enumerate(tts_evidence):
        if (
            not isinstance(evidence, Mapping)
            or set(evidence) != TTS_EVIDENCE_KEYS
            or evidence["kind"]
            != ("opening_greeting" if index == 0 else "diary_reply")
            or not _valid_native_audio_playback(evidence["playback"])
            or (index == 0 and evidence["source_message_id"] is not None)
            or (
                index > 0
                and (
                    type(evidence["source_message_id"]) is not int
                    or evidence["source_message_id"] <= 0
                )
            )
            or not isinstance(evidence["text_sha256"], str)
            or SHA256_PATTERN.fullmatch(evidence["text_sha256"]) is None
            or not isinstance(evidence["effective_text_sha256"], str)
            or SHA256_PATTERN.fullmatch(evidence["effective_text_sha256"]) is None
            or type(evidence["truncated"]) is not bool
            or not isinstance(evidence["audio_sha256"], str)
            or SHA256_PATTERN.fullmatch(evidence["audio_sha256"]) is None
            or not isinstance(evidence["cache_relative_path"], str)
            or re.fullmatch(
                r"tts-cache/[0-9a-f]{32}\.mp3",
                evidence["cache_relative_path"],
            )
            is None
        ):
            raise HarnessSafetyError("provider telemetry TTS evidence mismatch")
        validated_tts.append(evidence)

    cache_sizes: list[int] = []
    for evidence in validated_tts:
        cache_path = plan.root / str(evidence["cache_relative_path"])
        if cache_path.parent != plan.tts_cache:
            raise HarnessSafetyError("provider telemetry TTS evidence mismatch")
        cache = _file_evidence(cache_path)
        if (
            cache.get("kind") != "regular"
            or cache.get("sha256") != evidence["audio_sha256"]
            or type(cache.get("size")) is not int
            or cache["size"] <= 0
        ):
            raise HarnessSafetyError("provider telemetry TTS cache mismatch")
        cache_sizes.append(cache["size"])

    expected: list[tuple[str, object, object]] = []
    seen_cache_paths: set[str] = set()

    def append_tts(index: int) -> None:
        evidence = validated_tts[index]
        cache_path = str(evidence["cache_relative_path"])
        cache_hit = cache_path in seen_cache_paths
        if not cache_hit:
            expected.append(("tts_provider", evidence, cache_sizes[index]))
        expected.append(
            (
                "tts_request",
                evidence,
                {"cache_hit": cache_hit, "order": index + 1, "size": cache_sizes[index]},
            )
        )
        seen_cache_paths.add(cache_path)

    append_tts(0)
    for index, request_id in enumerate(chat_request_ids):
        if request_id in provider_chat_request_ids:
            expected.append(("deepseek", "chat_reply", f"chat-request:{request_id}"))
        append_tts(index + 1)
    expected.extend(
        (
            ("deepseek", "extract_info", f"analysis-job:{analysis_job_id}"),
            ("deepseek", "assess_conversation", f"analysis-job:{analysis_job_id}"),
        )
    )
    activity_events = summary["events"][2:]
    if len(activity_events) != len(expected):
        raise HarnessSafetyError("provider telemetry is incomplete")
    for event, expected_event in zip(activity_events, expected, strict=True):
        event_kind, first, second = expected_event
        if event_kind == "tts_request":
            evidence = first
            endpoint = second
            assert isinstance(evidence, Mapping)
            assert isinstance(endpoint, Mapping)
            expected_endpoint = {
                "audio_bytes": endpoint["size"],
                "cache_hit": endpoint["cache_hit"],
                "cache_relative_path": evidence["cache_relative_path"],
                "cache_sha256": evidence["audio_sha256"],
                "effective_text_sha256": evidence["effective_text_sha256"],
                "kind": "tts_request",
                "method": "GET",
                "order": endpoint["order"],
                "path": "/api/tts",
                "requested_text_sha256": evidence["text_sha256"],
                "status": 200,
                "truncated": evidence["truncated"],
                "voice": "zh-CN-XiaoxiaoNeural",
            }
            if event != expected_endpoint:
                raise HarnessSafetyError("provider telemetry TTS evidence mismatch")
        elif event_kind == "tts_provider":
            evidence = first
            assert isinstance(evidence, Mapping)
            if (
                event.get("operation") != "tts"
                or event.get("status") != "ok"
                or event.get("correlation_id")
                != f"message-text:{evidence['effective_text_sha256']}"
                or event.get("voice") != "zh-CN-XiaoxiaoNeural"
                or event.get("cache_relative_path")
                != evidence["cache_relative_path"]
                or event.get("cache_sha256") != evidence["audio_sha256"]
                or event.get("audio_bytes") != second
            ):
                raise HarnessSafetyError("provider telemetry TTS evidence mismatch")
        else:
            if (
                event.get("operation") != first
                or event.get("status") != "ok"
                or event.get("correlation_id") != second
                or event.get("model") != selected["DEEPSEEK_MODEL"]
                or event.get("parse_valid") is not True
            ):
                raise HarnessSafetyError(
                    "provider telemetry model or parse boundary mismatch"
                )
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


def _checksum_inventory(payload: bytes) -> dict[str, str]:
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise HarnessSafetyError("terminal inventory is invalid") from exc
    if not text or not text.endswith("\n"):
        raise HarnessSafetyError("terminal inventory is invalid")
    inventory: dict[str, str] = {}
    observed_order: list[str] = []
    for line in text.splitlines():
        if len(line) < 67 or line[64:66] != "  ":
            raise HarnessSafetyError("terminal inventory is invalid")
        digest = line[:64]
        relative = line[66:]
        candidate = Path(relative)
        if (
            SHA256_PATTERN.fullmatch(digest) is None
            or not relative
            or candidate.is_absolute()
            or "\\" in relative
            or any(part in {"", ".", ".."} for part in candidate.parts)
            or relative in inventory
        ):
            raise HarnessSafetyError("terminal inventory is invalid")
        inventory[relative] = digest
        observed_order.append(relative)
    if observed_order != sorted(observed_order):
        raise HarnessSafetyError("terminal inventory is invalid")
    return inventory


def _verify_complete_precommit_state(
    plan: RunPlan,
    *,
    manifest_payload: bytes,
    checksums_payload: bytes,
    provider_summary: Mapping[str, object],
) -> None:
    """Bind all prepared bytes before COMPLETE becomes the last atomic commit."""

    try:
        retained_checksums = _read_pinned_run_file(
            plan,
            plan.checksums,
            max_bytes=100_000_000,
        )
        retained_provider = _read_pinned_run_file(
            plan,
            plan.provider_summary,
            max_bytes=100_000_000,
        )
    except HarnessSafetyError as exc:
        raise HarnessSafetyError("terminal inventory is unavailable") from exc
    expected_provider = canonical_json_line(dict(provider_summary)).encode("utf-8")
    if (
        retained_checksums != checksums_payload
        or retained_provider != expected_provider
        or _checksum_lines(plan, manifest_payload) != checksums_payload
    ):
        raise HarnessSafetyError("terminal inventory bytes are inconsistent")
    inventory = _checksum_inventory(checksums_payload)
    try:
        manifest = json.loads(manifest_payload.decode("utf-8", errors="strict"))
    except (UnicodeError, ValueError) as exc:
        raise HarnessSafetyError("terminal inventory manifest is invalid") from exc
    if not isinstance(manifest, Mapping):
        raise HarnessSafetyError("terminal inventory manifest is invalid")
    screenshots = manifest.get("screenshots")
    events = provider_summary.get("events")
    if not isinstance(screenshots, list) or not isinstance(events, list):
        raise HarnessSafetyError("terminal inventory evidence is invalid")
    for screenshot in screenshots:
        if (
            not isinstance(screenshot, Mapping)
            or not isinstance(screenshot.get("relative_path"), str)
            or not isinstance(screenshot.get("sha256"), str)
            or inventory.get(screenshot["relative_path"]) != screenshot["sha256"]
        ):
            raise HarnessSafetyError("terminal inventory screenshot mismatch")
    for event in events:
        if not isinstance(event, Mapping):
            raise HarnessSafetyError("terminal inventory provider evidence is invalid")
        relative = event.get("cache_relative_path")
        digest = event.get("cache_sha256")
        if relative is None and digest is None:
            continue
        if (
            not isinstance(relative, str)
            or not isinstance(digest, str)
            or inventory.get(relative) != digest
        ):
            raise HarnessSafetyError("terminal inventory provider cache mismatch")
    if inventory.get(plan.manifest.name) != _hash_bytes(manifest_payload):
        raise HarnessSafetyError("terminal inventory manifest checksum mismatch")
    assert_run_plan_identity(plan)


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
        "secret_scan": {
            "actual_values": "PASS",
            "forbidden_patterns": "PASS",
            "provider_key": "FULL_RETAINED_TREE_PASS",
            "reviewed_source_forbidden_patterns": "GIT_PINNED_EXEMPT",
            "status": "PASS",
            "teacher_pin": "RUNTIME_GENERATED_EVIDENCE_PASS",
        },
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
    source_materializer: Callable[[RunPlan], RunPlan] = materialize_reviewed_source,
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
        plan = source_materializer(plan)
        if plan.source_root_identity is not None:
            assert_reviewed_source_pinned(plan)

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
        if plan.source_root_identity is not None:
            assert_reviewed_source_pinned(plan)

        controller = controller_validator(plan)
        if any(
            isinstance(issue, Mapping) and issue.get("severity") == "blocker"
            for issue in controller["issues"]
        ):
            raise HarnessSafetyError("controller evidence contains a blocker")
        controller_entity_ids = _collect_entity_ids(controller)
        entity_ids = _inject_private_roster_provenance(
            tuple(provider_events),
            controller_entity_ids,
        )
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
        provider_secrets = (str(provider["DEEPSEEK_API_KEY"]),)
        runtime_secrets = tuple(
            secret
            for secret in (control.secret_for_scan(),)
            if isinstance(secret, str) and secret
        )
        scan_retained_artifacts(
            plan.root,
            provider_secrets=provider_secrets,
            runtime_secrets=runtime_secrets,
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
        _assert_secret_free_payload(
            manifest_payload,
            actual_secrets=provider_secrets,
            role="manifest.json",
        )
        _assert_runtime_secrets_free_payload(
            manifest_payload,
            runtime_secrets=runtime_secrets,
            role="manifest.json",
            pinned_plan=plan,
        )
        checksums_payload = _checksum_lines(plan, manifest_payload)
        _write_owned_bytes(
            plan.checksums,
            checksums_payload,
            pinned_plan=plan,
        )
        scan_retained_artifacts(
            plan.root,
            provider_secrets=provider_secrets,
            runtime_secrets=runtime_secrets,
            pinned_plan=plan,
        )
        _verify_complete_precommit_state(
            plan,
            manifest_payload=manifest_payload,
            checksums_payload=checksums_payload,
            provider_summary=provider_summary,
        )
        if plan.source_root_identity is not None:
            assert_reviewed_source_pinned(plan)
        atomic_write_json(
            plan.manifest,
            manifest,
            pinned_plan=plan,
            terminal_commit=True,
        )
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
        finalize_failed_run(
            plan,
            reason_code=reason,
        )
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
        evidence = _file_evidence(path)
        if evidence["kind"] == "missing":
            return {}
        if evidence["kind"] != "regular" or evidence.get("size", 0) > 1_048_576:
            raise HarnessSafetyError("provider configuration file is unsafe")
        payload, pinned = _read_absolute_regular_nofollow(
            path,
            max_bytes=1_048_576,
        )
        if pinned != evidence:
            raise HarnessSafetyError("provider configuration file changed")
        decoded = payload.decode("utf-8", errors="strict")
    except HarnessSafetyError as exc:
        raise HarnessSafetyError("provider configuration file is unsafe") from exc
    except UnicodeError as exc:
        raise HarnessSafetyError("provider configuration file is invalid") from exc
    if loader is None:
        from dotenv import dotenv_values as loader

    try:
        values = loader(
            stream=io.StringIO(decoded),
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
