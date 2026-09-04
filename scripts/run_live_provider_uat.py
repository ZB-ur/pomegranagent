#!/usr/bin/env python3
"""Retained, non-default live-provider UAT controller harness.

The module deliberately performs no filesystem, process, provider, or backend
work at import time.  The live orchestration entry point is implemented in
small testable boundaries so fake dependencies can exercise every safety rule.
"""
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import secrets
import select
import signal
import socket
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import time
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit


PROJECT_ROOT = Path(__file__).resolve().parents[1]
HEAD_PATTERN = re.compile(r"[0-9a-f]{40}")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
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
TELEMETRY_KEYS = {
    "audio_bytes",
    "error_class",
    "latency_bucket",
    "model",
    "operation",
    "provider",
    "response_bytes",
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
    "duck_avatar_id",
    "live_child_id",
    "live_duck_id",
    "live_conversation_id",
    "monthly_pairs",
    "search_page_one_ids",
    "search_page_two_ids",
    "search_result_conversation_id",
    "weekly_week_start",
}


class HarnessError(RuntimeError):
    """Base class for controlled live-UAT failures."""


class HarnessSafetyError(HarnessError):
    """A fail-closed filesystem, process, credential, or evidence violation."""


@dataclass(frozen=True, slots=True)
class RunPlan:
    repository: Path
    source_head: str
    run_id: str
    root: Path
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
    parsed = parser.parse_args(argv)
    if not parsed.retain or not parsed.print_runtime_json:
        parser.error("--retain and --print-runtime-json are both required")
    return parsed


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


def _ensure_artifact_directory(path: Path, *, label: str) -> None:
    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        pass
    except OSError as exc:
        raise HarnessSafetyError(f"{label} cannot be created safely") from exc
    _safe_owned_directory(path, label=label)


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
    _safe_owned_directory(root, label="repository root")
    if not (root / ".git").exists():
        raise HarnessSafetyError("repository root has no Git metadata")
    if HEAD_PATTERN.fullmatch(source_head) is None:
        raise HarnessSafetyError("source head is not a literal 40-hex commit")

    artifacts = root / "artifacts"
    if artifacts.is_symlink():
        raise HarnessSafetyError("artifact ancestry contains a symlink")
    _ensure_artifact_directory(artifacts, label="artifact ancestry")
    real_uat = artifacts / "real-uat"
    if real_uat.is_symlink():
        raise HarnessSafetyError("artifact ancestry contains a symlink")
    _ensure_artifact_directory(real_uat, label="artifact ancestry")

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
    for attempt in range(100):
        collision = "" if attempt == 0 else f"-{attempt:02d}"
        run_id = f"{stem}{collision}-{source_head[:12]}"
        candidate = real_uat / run_id
        try:
            os.mkdir(candidate, 0o700)
        except FileExistsError:
            continue
        except OSError as exc:
            raise HarnessSafetyError("run directory cannot be created safely") from exc
        run_root = candidate
        break
    if run_root is None:
        raise HarnessSafetyError("run identifier collision limit reached")
    _safe_owned_directory(run_root, label="run directory")

    return RunPlan(
        repository=root,
        source_head=source_head,
        run_id=run_id,
        root=run_root,
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
        owned = OwnedProcess(process=process, pid=process.pid, pgid=process.pid)
        _owned_identity(owned, getpgid=getpgid)
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
        identity_valid = (
            provider == "deepseek"
            and isinstance(model, str)
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", model) is not None
            and voice is None
        )
    elif operation == "tts":
        identity_valid = (
            provider == "edge-tts"
            and model is None
            and isinstance(voice, str)
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}", voice) is not None
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


def _owned_identity(owned: OwnedProcess, *, getpgid: Callable[[int], int]) -> None:
    if (
        type(owned.pid) is not int
        or owned.pid <= 1
        or owned.pgid != owned.pid
        or getattr(owned.process, "pid", None) != owned.pid
    ):
        raise HarnessSafetyError("process-group ownership is invalid")
    try:
        observed = getpgid(owned.pid)
    except (OSError, ValueError) as exc:
        raise HarnessSafetyError("process-group ownership is invalid") from exc
    if observed != owned.pgid:
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
    owned = OwnedProcess(process=process, pid=process.pid, pgid=process.pid)
    _owned_identity(owned, getpgid=getpgid)
    return owned


def require_owned_process_alive(
    owned: OwnedProcess,
    *,
    getpgid: Callable[[int], int] = os.getpgid,
) -> None:
    _owned_identity(owned, getpgid=getpgid)
    if owned.process.poll() is not None:
        raise HarnessSafetyError("live server exited before readiness")


def stop_owned_process_group(
    owned: OwnedProcess,
    *,
    getpgid: Callable[[int], int] = os.getpgid,
    killpg: Callable[[int, int], None] = os.killpg,
) -> None:
    """Idempotently stop only the verified direct child's process group."""

    if owned.process.poll() is not None:
        return
    _owned_identity(owned, getpgid=getpgid)
    try:
        killpg(owned.pgid, signal.SIGTERM)
        owned.process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        _owned_identity(owned, getpgid=getpgid)
        killpg(owned.pgid, signal.SIGKILL)
        try:
            owned.process.wait(timeout=5)
        except subprocess.TimeoutExpired as exc:
            raise HarnessSafetyError("owned process group could not be reaped") from exc
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
        output_fd = os.open(plan.server_stderr, flags, 0o600)
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
    else:
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
) -> None:
    """Write one canonical 0600 JSON artifact and durably replace its target."""

    destination = _absolute(target)
    parent = destination.parent
    _safe_owned_directory(parent, label="evidence parent")
    try:
        existing = destination.lstat()
    except FileNotFoundError:
        existing = None
    except OSError as exc:
        raise HarnessSafetyError("atomic evidence write failed") from exc
    if existing is not None and (
        not stat.S_ISREG(existing.st_mode) or existing.st_nlink != 1
    ):
        raise HarnessSafetyError("atomic evidence write target is unsafe")
    token = nonce()
    if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", token) is None:
        raise HarnessSafetyError("atomic evidence write nonce is invalid")
    temporary = parent / f".{destination.name}.{token}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = None
    try:
        descriptor = os.open(temporary, flags, 0o600)
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
        replace(temporary, destination)
        directory_flags = os.O_RDONLY
        if hasattr(os, "O_DIRECTORY"):
            directory_flags |= os.O_DIRECTORY
        directory_fd = os.open(parent, directory_flags)
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
            temporary.unlink()
        except OSError:
            pass
        raise HarnessSafetyError("atomic evidence write failed") from exc


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
    atomic_write_json(plan.manifest, payload)


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
        raw_path = record[3:]
        index += 1
        if b"R" in status_code or b"C" in status_code:
            if index >= len(records):
                raise HarnessSafetyError("protected Git porcelain is invalid")
            raw_path = records[index]
            index += 1
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


def scan_retained_artifacts(root: Path, *, actual_secrets: tuple[str, ...]) -> None:
    base = _absolute(root)
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
            continue
        if not stat.S_ISREG(entry.st_mode) or entry.st_nlink != 1:
            raise HarnessSafetyError("secret scan failed: unsafe artifact")
        total += entry.st_size
        if total > 2_000_000_000:
            raise HarnessSafetyError("secret scan failed: artifact bound")
        try:
            payload = path.read_bytes()
        except OSError as exc:
            raise HarnessSafetyError("secret scan failed: unreadable artifact") from exc
        if any(secret in payload for secret in encoded_secrets) or any(
            pattern.search(payload) is not None for pattern in _SECRET_PATTERNS
        ):
            role = path.relative_to(base).as_posix()
            raise HarnessSafetyError(f"secret scan failed: {role}")


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


def _stable_file_identity(entry: os.stat_result) -> tuple[int, ...]:
    return (
        entry.st_dev,
        entry.st_ino,
        entry.st_mode,
        entry.st_nlink,
        entry.st_size,
        entry.st_mtime_ns,
    )


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
        "viewport",
        "visible_assertions",
    }
    if set(item) != expected_keys:
        raise HarnessSafetyError("controller evidence screenshot shape is invalid")
    semantic = item["semantic_name"]
    viewport = item["viewport"]
    relative = item["relative_path"]
    if (
        not isinstance(semantic, str)
        or re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", semantic) is None
        or relative != f"screenshots/{semantic}.png"
        or viewport not in {value for values in APPROVED_VIEWPORTS.values() for value in values}
        or item["journey_step"] not in REQUIRED_JOURNEY_STEPS
        or not _safe_assertions(item["visible_assertions"])
    ):
        raise HarnessSafetyError("controller evidence screenshot is invalid")
    path = plan.root / str(relative)
    if path.parent != plan.screenshots or not path.is_relative_to(plan.root):
        raise HarnessSafetyError("controller evidence screenshot path is invalid")
    try:
        before = path.lstat()
    except OSError as exc:
        raise HarnessSafetyError("screenshot is unavailable") from exc
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise HarnessSafetyError("screenshot is not one regular file")
    try:
        from PIL import Image

        with Image.open(path) as image:
            image.load()
            decoded_format = image.format
            decoded_size = image.size
    except Exception as exc:
        raise HarnessSafetyError("screenshot cannot be decoded") from exc
    width, height = (int(part) for part in str(viewport).split("x"))
    if decoded_format != "PNG" or decoded_size != (width, height):
        raise HarnessSafetyError("screenshot dimensions do not match viewport")
    after_decode(path)
    try:
        after = path.lstat()
    except OSError as exc:
        raise HarnessSafetyError("screenshot changed after validation") from exc
    if _stable_file_identity(before) != _stable_file_identity(after):
        raise HarnessSafetyError("screenshot changed after validation")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if _stable_file_identity(opened) != _stable_file_identity(after):
            raise HarnessSafetyError("screenshot changed before hashing")
        chunks = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        final = os.fstat(descriptor)
        if _stable_file_identity(final) != _stable_file_identity(opened):
            raise HarnessSafetyError("screenshot changed during hashing")
    finally:
        os.close(descriptor)
    payload = b"".join(chunks)
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
    try:
        entry = plan.controller_evidence.lstat()
        payload = plan.controller_evidence.read_bytes()
        text = payload.decode("utf-8", errors="strict")
        value = json.loads(text)
    except (OSError, UnicodeError, ValueError) as exc:
        raise HarnessSafetyError("controller evidence is unavailable or invalid") from exc
    if (
        not stat.S_ISREG(entry.st_mode)
        or entry.st_nlink != 1
        or not isinstance(value, dict)
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
    paths = [item["relative_path"] for item in validated_screenshots]
    if len(set(semantic_names)) != len(semantic_names) or len(set(paths)) != len(paths):
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
    if not isinstance(human, list) or len(human) > 1:
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
    return {
        **value,
        "screenshots": validated_screenshots,
    }


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
        or Path(filename).name != filename
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


def validate_database_provenance(
    plan: RunPlan,
    entity_ids: Mapping[str, object],
) -> dict[str, object]:
    if set(entity_ids) != _PROVENANCE_KEYS:
        raise HarnessSafetyError("database provenance identifiers are incomplete")
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
            for avatar_id in (entity_ids["child_avatar_id"], entity_ids["duck_avatar_id"]):
                if not isinstance(avatar_id, str) or re.fullmatch(
                    r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
                    avatar_id,
                ) is None:
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
            if not isinstance(monthly, dict) or not monthly:
                raise HarnessSafetyError("database provenance monthly roster is invalid")
            for roster_date, expected_children in monthly.items():
                if (
                    not isinstance(roster_date, str)
                    or not isinstance(expected_children, list)
                    or len(expected_children) != 2
                    or len(set(expected_children)) != 2
                    or any(type(value) is not int or value <= 0 for value in expected_children)
                ):
                    raise HarnessSafetyError("database provenance monthly roster is invalid")
                date.fromisoformat(roster_date)
                actual = [
                    row[0]
                    for row in connection.execute(
                        "SELECT child_id FROM duty_rosters WHERE date = ? ORDER BY child_id",
                        (roster_date,),
                    ).fetchall()
                ]
                if actual != sorted(expected_children):
                    raise HarnessSafetyError("database provenance monthly roster mismatch")
            conversation = connection.execute(
                "SELECT child_id, date, status, end_reason, frozen_last_message_id "
                "FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
            if (
                conversation is None
                or conversation[0] != child_id
                or conversation[2] != "ended"
                or conversation[3] not in {"complete", "manual", "max_rounds"}
                or type(conversation[4]) is not int
            ):
                raise HarnessSafetyError("database provenance conversation mismatch")
            messages = connection.execute(
                "SELECT id, role FROM messages WHERE conversation_id = ? AND id <= ? ORDER BY id",
                (conversation_id, conversation[4]),
            ).fetchall()
            if (
                len(messages) < 2
                or messages[-1][0] != conversation[4]
                or {row[1] for row in messages} != {"child", "diary"}
            ):
                raise HarnessSafetyError("database provenance frozen messages mismatch")
            job = connection.execute(
                "SELECT id, frozen_last_message_id, status FROM analysis_jobs "
                "WHERE conversation_id = ? ORDER BY id DESC LIMIT 1",
                (conversation_id,),
            ).fetchone()
            if job != (job_id, conversation[4], "succeeded"):
                raise HarnessSafetyError("database provenance analysis mismatch")
            assessment = connection.execute(
                "SELECT conversation_id, child_id, status FROM assessments WHERE id = ?",
                (assessment_id,),
            ).fetchone()
            if assessment != (conversation_id, child_id, "confirmed"):
                raise HarnessSafetyError("database provenance review mismatch")
            scores = connection.execute(
                "SELECT dimension_id, score, reason FROM assessment_scores "
                "WHERE assessment_id = ? ORDER BY dimension_id",
                (assessment_id,),
            ).fetchall()
            if (
                len(scores) != 3
                or len({row[0] for row in scores}) != 3
                or any(type(row[1]) is not int or not 1 <= row[1] <= 5 or not row[2] for row in scores)
            ):
                raise HarnessSafetyError("database provenance score mismatch")
            try:
                week_start = date.fromisoformat(entity_ids["weekly_week_start"])
                conversation_date = date.fromisoformat(conversation[1])
            except (TypeError, ValueError) as exc:
                raise HarnessSafetyError("database provenance week mismatch") from exc
            if week_start.weekday() != 0 or not week_start <= conversation_date < week_start.fromordinal(week_start.toordinal() + 7):
                raise HarnessSafetyError("database provenance week mismatch")
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
                f"SELECT id, status FROM conversations WHERE id IN ({placeholders})",
                tuple(page_one + page_two),
            ).fetchall()
            if len(search_rows) != len(set(page_one + page_two)) or any(row[1] != "ended" for row in search_rows):
                raise HarnessSafetyError("database provenance search rows mismatch")
    except HarnessSafetyError:
        raise
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        raise HarnessSafetyError("database provenance validation failed") from exc
    after = _database_evidence(plan.database)
    if before != after:
        raise HarnessSafetyError("database provenance validation changed retained database")
    return {
        "analysis_job_id": entity_ids["analysis_job_id"],
        "assessment_id": entity_ids["assessment_id"],
        "conversation_id": entity_ids["live_conversation_id"],
        "score_count": 3,
        "search_result_id": entity_ids["search_result_conversation_id"],
        "status": "PROVEN",
    }


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


def _ensure_run_directory(path: Path, *, label: str) -> None:
    if path.exists():
        _safe_owned_directory(path, label=label)
        return
    try:
        os.mkdir(path, 0o700)
    except OSError as exc:
        raise HarnessSafetyError(f"{label} cannot be created safely") from exc
    _safe_owned_directory(path, label=label)


def _write_owned_bytes(path: Path, payload: bytes) -> None:
    if not isinstance(payload, bytes):
        raise HarnessSafetyError("evidence payload is invalid")
    destination = _absolute(path)
    _safe_owned_directory(destination.parent, label="evidence parent")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = None
    try:
        descriptor = os.open(destination, flags, 0o600)
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
) -> dict[str, object]:
    summary = summarize_provider_events(events)
    successful = {
        event["operation"]
        for event in summary["events"]
        if event["status"] == "ok"
        and (
            event["audio_bytes"] > 0
            if event["operation"] == "tts"
            else event["response_bytes"] > 0
        )
    }
    required = {"chat_reply", "extract_info", "assess_conversation", "tts"}
    if not required.issubset(successful):
        raise HarnessSafetyError("provider telemetry is incomplete")
    return summary


def _checksum_lines(plan: RunPlan, manifest_payload: bytes) -> bytes:
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
            continue
        if not stat.S_ISREG(entry.st_mode) or entry.st_nlink != 1:
            raise HarnessSafetyError("checksum inventory contains an unsafe artifact")
        payload = candidate.read_bytes()
        if _file_evidence(candidate).get("sha256") != _hash_bytes(payload):
            raise HarnessSafetyError("checksum artifact changed during hashing")
        entries.append((_hash_bytes(payload), relative))
    entries.append((_hash_bytes(manifest_payload), plan.manifest.name))
    entries.sort(key=lambda item: item[1])
    return "".join(f"{digest}  {relative}\n" for digest, relative in entries).encode(
        "utf-8"
    )


def _complete_manifest(
    plan: RunPlan,
    *,
    seed_result: Mapping[str, object],
    controller: Mapping[str, object],
    provider_summary: Mapping[str, object],
    provenance: Mapping[str, object],
) -> dict[str, object]:
    return {
        "database_provenance": dict(provenance),
        "human_uat_required": controller["human_uat_required"],
        "issues_count": len(controller["issues"]),
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
    provenance_validator: Callable[[RunPlan, Mapping[str, object]], Mapping[str, object]] = validate_database_provenance,
) -> RunPlan:
    """Execute one retained run through injectable, fake-safe orchestration seams."""

    plan = None
    session = None
    session_finished = False
    try:
        before_first = capture_resources(repository)
        before_second = capture_resources(repository)
        assert_protected_resources_equal(before_first, before_second)
        source_head = before_second.get("git_head")
        if not isinstance(source_head, str) or HEAD_PATTERN.fullmatch(source_head) is None:
            raise HarnessSafetyError("protected source head is invalid")
        plan = create_run_plan(
            repository,
            source_head,
            now=now,
            nonce=nonce,
        )
        atomic_write_json(plan.resources_before, before_second)

        provider = select_provider_settings(environ, dotenv_values)
        seed_argv = build_seed_argv(
            plan,
            python_executable=python_executable,
            business_today=business_today,
        )
        seed_result = seed_runner(
            plan,
            argv=seed_argv,
            environment=build_seed_environment(environ),
        )
        seed_result = parse_seed_result(
            canonical_json_line(dict(seed_result)).encode("utf-8"),
            plan,
        )
        _safe_owned_directory(plan.app_log.parent, label="run log directory")
        _ensure_run_directory(plan.tts_cache, label="run TTS directory")
        _ensure_run_directory(plan.screenshots, label="run screenshot directory")
        _write_owned_bytes(
            plan.invalid_avatar,
            b"pomegranagent invalid avatar fixture; deliberately not an image\n",
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
        provider_summary = _validate_provider_completion(tuple(provider_events))
        entity_ids = _collect_entity_ids(controller)
        provenance = provenance_validator(plan, entity_ids)
        atomic_write_json(
            plan.journey,
            {
                "journey": controller["journey"],
                "protocol": "pomegranagent-live-uat-journey/v1",
                "run_id": plan.run_id,
            },
        )
        atomic_write_json(
            plan.issues,
            {
                "issues": controller["issues"],
                "protocol": "pomegranagent-live-uat-issues/v1",
                "run_id": plan.run_id,
            },
        )
        atomic_write_json(plan.provider_summary, provider_summary)

        after = capture_resources(repository)
        atomic_write_json(plan.resources_after, after)
        assert_protected_resources_equal(before_second, after)
        actual_secrets = (provider["DEEPSEEK_API_KEY"], control.secret_for_scan())
        scan_retained_artifacts(
            plan.root,
            actual_secrets=tuple(
                secret for secret in actual_secrets if isinstance(secret, str)
            ),
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
        _write_owned_bytes(plan.checksums, _checksum_lines(plan, manifest_payload))
        scan_retained_artifacts(
            plan.root,
            actual_secrets=tuple(
                secret for secret in actual_secrets if isinstance(secret, str)
            ),
        )
        atomic_write_json(plan.manifest, manifest)
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
            atomic_write_json(plan.resources_after, after)
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
    parse_args(argv)
    selected_environment = dict(os.environ if environ is None else environ)
    selected_output = sys.stdout if output_stream is None else output_stream
    with _SignalTermination() as termination:
        selected_input = input_stream
        if selected_input is None:
            selected_input = SignalAwareControlStream(sys.stdin.fileno(), termination.event)
        execute(
            repository=PROJECT_ROOT,
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
