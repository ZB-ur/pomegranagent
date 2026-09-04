#!/usr/bin/env python3
"""Fail-closed interaction acceptance runner.

Importing this module is intentionally effect free. Runtime filesystem and
process access is confined to explicit public functions and the CLI entrypoint.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, fields, is_dataclass, replace
from collections.abc import Mapping
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import subprocess
import tempfile
import time
import types
from typing import NoReturn
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

import pytest


CLEAN_ENV_ARGV = (
    "/usr/bin/env",
    "-i",
    "PATH=/Users/lddmay/AiCoding/pomegranagent/.venv/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
    "HOME=/Users/lddmay",
    "LANG=C.UTF-8",
    "LC_ALL=C.UTF-8",
    "TMPDIR=/tmp",
    "TZ=Asia/Shanghai",
    "DISABLE_EXTERNAL_AI=1",
    "PYTHONNOUSERSITE=1",
    "PYTHON_DOTENV_DISABLED=1",
)
PYTHON = "/Users/lddmay/AiCoding/pomegranagent/.venv/bin/python"
NODE = "/opt/homebrew/bin/node"
FROZEN_START_HEAD = "89b3459973bb7cd6e8be43b1251ac6cdb5dfa292"
FROZEN_RUNTIME_VERSION = {
    "release_id": "2026.09.02-server-capabilities.1",
    "api_version": "3",
    "schema_version": "3",
}
REPORT_SCHEMA_VERSION = 2
FROZEN_LIMITATIONS = (
    "The runner cannot authorize release GO.",
    "Historical incidents still require release-owner disposition.",
    "Lovable completion or an explicit scope waiver is external to the runner.",
    (
        "Completed-report filesystem integrity assumes a cooperative local "
        "filesystem after no-follow path and identity checks; it does not claim "
        "resistance to a privileged concurrent filesystem adversary."
    ),
    (
        "Command duration_seconds is non-authoritative runner telemetry; only "
        "its finite nonnegative shape is checked, and no gate or decision trusts it."
    ),
    (
        "Pytest-command stdout is descriptor-hashed non-authoritative diagnostic "
        "data; JUnit plus authenticated stderr remains authoritative, while Node "
        "TAP stdout is parsed as authoritative suite evidence."
    ),
)

COMMAND_TIMEOUTS = {
    "runner": 300,
    "lovable": 120,
    "backend": 900,
    "browser": 1800,
    "shared_node": 300,
    "child_node": 600,
    "teacher_node": 300,
    "release_focus_1024": 120,
    "release_focus_all": 180,
    "teacher_accessibility_full": 300,
    "release_db_action_1024": 120,
    "release_db_action_all": 180,
    "review_identity_1024": 120,
    "review_identity_all": 180,
    "child_chat_timeout_1024": 120,
    "child_chat_timeout_all": 180,
    "child_completion_delay_1024": 120,
    "child_completion_delay_all": 180,
    "child_keyboard_core_1024": 180,
    "child_keyboard_core_all": 240,
    "today_three_status_1024": 120,
    "today_three_status_all": 180,
}

NEUTRAL_PARENT_ENV = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "TZ", "SYSTEMROOT")
FORCED_BREAKERS = {
    "DISABLE_EXTERNAL_AI": "1",
    "PYTHONNOUSERSITE": "1",
    "PYTHON_DOTENV_DISABLED": "1",
}
TEST_TRIPWIRE_PREFIX = "TEST_TRIPWIRE:"
_TRIPWIRE_EVENT_SIGNATURES = {
    "external_ai": (
        ("AssertionError", "tests/conftest.py:_blocked_external_ai", "TEST_TRIPWIRE:external_ai", True),
    ),
    "edge_tts": (
        ("AssertionError", "tests/conftest.py:__init__", "TEST_TRIPWIRE:edge_tts", True),
    ),
    "external_network": (
        ("AssertionError", "tests/conftest.py:_guarded_socket_connect", "TEST_TRIPWIRE:external_network", True),
        ("AssertionError", "tests/conftest.py:_guarded_socket_connect_ex", "TEST_TRIPWIRE:external_network", True),
    ),
    "browser_edge_tts": (
        ("AssertionError", "tests/browser/child_server.py:stream", "external edge_tts disabled in browser tests", True),
    ),
    "browser_ai": (
        ("AssertionError", "tests/browser/child_server.py:blocked_llm", "external AI disabled in browser tests", True),
    ),
    "browser_network": (
        ("PermissionError", "tests/browser/child_server.py:guarded", "non-loopback socket blocked:", False),
    ),
    "browser_file": (
        ("AssertionError", "tests/browser/conftest.py:_verify_server_safety", "browser tripwire fired:", False),
    ),
}
TRIPWIRE_EVENT_IDS = tuple(_TRIPWIRE_EVENT_SIGNATURES)
_TRIPWIRE_AUTH_KEY_PREFIX = b"TASK9_AUTH_V1:KEY:"
_TRIPWIRE_AUTH_EVENT_PREFIX = b"TASK9_AUTH_V1:EVENT:"
_TRIPWIRE_PHASES = ("import", "collection", "setup", "call", "teardown")


class ConftestMode(str, Enum):
    PURE = "noconftest"
    PROJECT = "project"


class EvidenceFormat(str, Enum):
    JUNIT = "junit"
    TAP = "tap"


class FileKind(str, Enum):
    MISSING = "missing"
    REGULAR = "regular"
    DIRECTORY = "directory"
    SYMLINK = "symlink"
    SPECIAL = "special"
    UNREADABLE = "unreadable"


@dataclass(frozen=True, slots=True)
class FileSnapshot:
    kind: FileKind
    mode: int | None = None
    size: int | None = None
    mtime_ns: int | None = None
    sha256: str | None = None
    symlink_target: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class DatabaseSnapshot:
    logical_digest: str | None
    database: FileSnapshot
    wal: FileSnapshot
    shm: FileSnapshot
    unsafe_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DirectoryEntrySnapshot:
    relative_path: str
    snapshot: FileSnapshot


@dataclass(frozen=True, slots=True)
class DirectorySnapshot:
    root: FileSnapshot
    entries: tuple[DirectoryEntrySnapshot, ...]
    digest: str | None
    unsafe_reasons: tuple[str, ...]
    scan_error: str | None = None
    scan_source: str | None = None


@dataclass(frozen=True, slots=True)
class ProtectedPathSnapshot:
    relative_path: str
    file: FileSnapshot
    directory: DirectorySnapshot | None
    unsafe_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ResourceSnapshot:
    database: DatabaseSnapshot
    log: FileSnapshot
    tts: DirectorySnapshot
    media: DirectorySnapshot
    user_paths: tuple[ProtectedPathSnapshot, ...]
    git_head: str | None
    git_porcelain: bytes | None
    unsafe_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CanonicalBytesSnapshot:
    sha256: str
    size: int


@dataclass(frozen=True, slots=True)
class CanonicalResourceSnapshot:
    database: DatabaseSnapshot
    log: FileSnapshot
    tts: DirectorySnapshot
    media: DirectorySnapshot
    user_paths: tuple[ProtectedPathSnapshot, ...]
    git_head: str | None
    git_porcelain: CanonicalBytesSnapshot | None
    unsafe_reasons: tuple[str, ...]


class ResourceCaptureError(RuntimeError):
    pass


class Termination(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    EXITED = "EXITED"
    TIMED_OUT = "TIMED_OUT"
    SIGNALED = "SIGNALED"
    SPAWN_FAILED = "SPAWN_FAILED"


class ClassifiedOutcome(str, Enum):
    SUCCESS = "SUCCESS"
    CHILD_NONZERO = "CHILD_NONZERO"
    TECHNICAL_FAILURE = "TECHNICAL_FAILURE"
    SAFETY_FAILURE = "SAFETY_FAILURE"
    CLI_MISUSE = "CLI_MISUSE"


class CleanupFailure(str, Enum):
    PIPE_DRAIN_TIMEOUT = "PIPE_DRAIN_TIMEOUT"
    LEADER_UNREAPED = "LEADER_UNREAPED"
    GROUP_SURVIVED = "GROUP_SURVIVED"


class GateStatus(str, Enum):
    BLOCKED = "BLOCKED"
    PASS = "PASS"


class DecisionOutcome(str, Enum):
    SAFETY_NO_GO = "SAFETY_NO_GO"
    TECHNICAL_NO_GO = "TECHNICAL_NO_GO"
    TECHNICAL_PASS_HUMAN_DECISION_PENDING = (
        "TECHNICAL_PASS_HUMAN_DECISION_PENDING"
    )


_SUITE_COUNT_FIELDS = (
    "total",
    "passed",
    "failures",
    "errors",
    "skipped",
    "xfailed",
    "xpassed",
    "todo",
    "cancelled",
)
_STRUCTURED_PROPERTY_NAMES = frozenset(
    {
        "task7.today_metrics_geometry",
        "task8.search_geometry",
        "task9.focus_measurement",
        "task9.db_action_evidence",
        "task9.timeout_evidence",
    }
)


@dataclass(frozen=True, slots=True)
class EvidenceProperty:
    node_id: str
    name: str
    value: str

    def __post_init__(self) -> None:
        try:
            decoded = json.loads(self.value)
            canonical = json.dumps(
                decoded,
                ensure_ascii=True,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("invalid structured evidence property") from error
        if (
            not isinstance(self.node_id, str)
            or not self.node_id
            or self.name not in _STRUCTURED_PROPERTY_NAMES
            or not isinstance(self.value, str)
            or self.value != canonical
        ):
            raise ValueError("invalid structured evidence property")


@dataclass(frozen=True, slots=True)
class TripwireEventEvidence:
    node_id: str
    event_id: str
    exception_type: str
    frame: str

    def __post_init__(self) -> None:
        signatures = _TRIPWIRE_EVENT_SIGNATURES.get(self.event_id, ())
        if (
            not isinstance(self.node_id, str)
            or not self.node_id
            or not any(
                self.exception_type == expected_type and self.frame == expected_frame
                for expected_type, expected_frame, _message, _exact in signatures
            )
        ):
            raise ValueError("invalid tripwire event evidence")


@dataclass(frozen=True, slots=True)
class AuthenticatedTripwireRecord:
    command_id: str
    node_id: str
    phase: str
    sequence: int
    event: TripwireEventEvidence

    def __post_init__(self) -> None:
        if (
            not isinstance(self.command_id, str)
            or not self.command_id
            or not isinstance(self.node_id, str)
            or not self.node_id
            or self.phase not in _TRIPWIRE_PHASES
            or type(self.sequence) is not int
            or self.sequence <= 0
            or not isinstance(self.event, TripwireEventEvidence)
            or self.event.node_id != self.node_id
        ):
            raise ValueError("invalid authenticated tripwire record")


@dataclass(frozen=True, slots=True)
class TripwireSidecarEvidence:
    records: tuple[AuthenticatedTripwireRecord, ...]
    integrity_valid: bool
    reason: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.records, tuple)
            or any(not isinstance(item, AuthenticatedTripwireRecord) for item in self.records)
            or type(self.integrity_valid) is not bool
            or not isinstance(self.reason, str)
            or not self.reason
            or (self.integrity_valid and self.reason != "PASS")
            or (not self.integrity_valid and self.reason == "PASS")
        ):
            raise ValueError("invalid tripwire sidecar evidence")


def _tripwire_canonical_json_bytes(value: Mapping[str, object]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _signed_tripwire_sidecar_for_offline_tests(
    command_id: str,
    records: tuple[Mapping[str, object], ...],
    *,
    extra_lines: tuple[bytes, ...] = (),
) -> bytes:
    """Create independent parser vectors without exposing live producer state."""

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
    )

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    header = _tripwire_canonical_json_bytes(
        {
            "command_id": command_id,
            "public_key": base64.b64encode(public_key).decode("ascii"),
            "version": 1,
        }
    )
    lines = [_TRIPWIRE_AUTH_KEY_PREFIX + base64.b64encode(header)]
    for record in records:
        payload = _tripwire_canonical_json_bytes(record)
        lines.append(
            _TRIPWIRE_AUTH_EVENT_PREFIX
            + base64.b64encode(payload)
            + b":"
            + base64.b64encode(private_key.sign(payload))
        )
    lines.extend(extra_lines)
    return b"\n".join(lines) + b"\n"


def _canonical_b64_json(payload: bytes) -> Mapping[str, object]:
    try:
        decoded_bytes = base64.b64decode(payload, validate=True)
        decoded = json.loads(decoded_bytes.decode("ascii", errors="strict"))
    except (
        binascii.Error,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
    ) as error:
        raise ValueError("invalid authenticated sidecar JSON") from error
    if (
        not isinstance(decoded, Mapping)
        or _tripwire_canonical_json_bytes(decoded) != decoded_bytes
    ):
        raise ValueError("noncanonical authenticated sidecar JSON")
    return decoded


def parse_tripwire_sidecar(
    payload: bytes, *, command_id: str
) -> TripwireSidecarEvidence:
    """Verify the command-local signed event stream without trusting raw prose."""

    if not isinstance(payload, bytes) or not isinstance(command_id, str) or not command_id:
        return TripwireSidecarEvidence((), False, "TRIPWIRE_AUTH_INVALID")
    key_payloads = [
        line[len(_TRIPWIRE_AUTH_KEY_PREFIX) :]
        for line in payload.splitlines()
        if line.startswith(_TRIPWIRE_AUTH_KEY_PREFIX)
    ]
    integrity_valid = True
    public_key = None
    canonical_header = None
    for encoded in key_payloads:
        try:
            header = _canonical_b64_json(encoded)
            if set(header) != {"command_id", "public_key", "version"}:
                raise ValueError("invalid authenticated sidecar header")
            if header["command_id"] != command_id or header["version"] != 1:
                raise ValueError("authenticated sidecar command mismatch")
            key_bytes = base64.b64decode(
                str(header["public_key"]).encode("ascii"), validate=True
            )
            if len(key_bytes) != 32:
                raise ValueError("invalid authenticated sidecar key")
            from cryptography.hazmat.primitives.asymmetric.ed25519 import (
                Ed25519PublicKey,
            )

            candidate_key = Ed25519PublicKey.from_public_bytes(key_bytes)
            candidate_header = _tripwire_canonical_json_bytes(header)
            if canonical_header is None:
                canonical_header = candidate_header
                public_key = candidate_key
            elif canonical_header != candidate_header:
                raise ValueError("conflicting authenticated sidecar key")
        except (binascii.Error, UnicodeEncodeError, TypeError, ValueError):
            integrity_valid = False
    if public_key is None or not key_payloads:
        integrity_valid = False

    accepted: list[AuthenticatedTripwireRecord] = []
    accepted_by_sequence: dict[int, tuple[bytes, bytes]] = {}
    max_sequence = 0
    for line in payload.splitlines():
        if not line.startswith(_TRIPWIRE_AUTH_EVENT_PREFIX):
            continue
        encoded = line[len(_TRIPWIRE_AUTH_EVENT_PREFIX) :]
        try:
            encoded_record, encoded_signature = encoded.split(b":", 1)
            record_bytes = base64.b64decode(encoded_record, validate=True)
            signature = base64.b64decode(encoded_signature, validate=True)
            decoded = json.loads(record_bytes.decode("ascii", errors="strict"))
            if (
                public_key is None
                or not isinstance(decoded, Mapping)
                or _tripwire_canonical_json_bytes(decoded) != record_bytes
                or set(decoded)
                != {"command_id", "event", "node_id", "phase", "sequence"}
                or decoded["command_id"] != command_id
                or not isinstance(decoded["event"], Mapping)
                or set(decoded["event"])
                != {"event_id", "exception_type", "frame"}
            ):
                raise ValueError("invalid authenticated event envelope")
            public_key.verify(signature, record_bytes)
            event = TripwireEventEvidence(
                node_id=decoded["node_id"], **decoded["event"]
            )
            record = AuthenticatedTripwireRecord(
                command_id=decoded["command_id"],
                node_id=decoded["node_id"],
                phase=decoded["phase"],
                sequence=decoded["sequence"],
                event=event,
            )
            prior = accepted_by_sequence.get(record.sequence)
            signed_record = (record_bytes, signature)
            if prior is not None:
                if prior != signed_record:
                    raise ValueError("conflicting authenticated event sequence")
                continue
            if record.sequence <= max_sequence:
                raise ValueError("nonmonotonic authenticated event sequence")
            accepted_by_sequence[record.sequence] = signed_record
            accepted.append(record)
            max_sequence = record.sequence
        except (
            binascii.Error,
            UnicodeDecodeError,
            json.JSONDecodeError,
            TypeError,
            ValueError,
        ):
            integrity_valid = False
        except Exception as error:
            if error.__class__.__name__ != "InvalidSignature":
                raise
            integrity_valid = False
    return TripwireSidecarEvidence(
        tuple(accepted),
        integrity_valid,
        "PASS" if integrity_valid else "TRIPWIRE_AUTH_INVALID",
    )


def _suite_evidence_state_is_valid(evidence: object) -> bool:
    try:
        valid = evidence.valid
        counts = tuple(getattr(evidence, name) for name in _SUITE_COUNT_FIELDS)
        node_ids = evidence.node_ids
        reason = evidence.reason
        properties = evidence.properties
        tripwire_events = evidence.tripwire_events
    except (AttributeError, TypeError):
        return False
    if (
        type(valid) is not bool
        or any(type(value) is not int or value < 0 for value in counts)
        or not isinstance(node_ids, tuple)
        or any(not isinstance(node_id, str) or not node_id for node_id in node_ids)
        or not isinstance(reason, str)
        or not reason
        or not isinstance(properties, tuple)
        or any(not isinstance(item, EvidenceProperty) for item in properties)
        or not isinstance(tripwire_events, tuple)
        or any(
            not isinstance(item, TripwireEventEvidence)
            for item in tripwire_events
        )
    ):
        return False
    total, passed, *nonpass_counts = counts
    if total != passed + sum(nonpass_counts) or len(node_ids) != total:
        return False
    property_keys = tuple((item.node_id, item.name) for item in properties)
    event_keys = tuple(
        (item.node_id, item.event_id, item.exception_type, item.frame)
        for item in tripwire_events
    )
    if (
        len(set(property_keys)) != len(property_keys)
        or any(item.node_id not in node_ids for item in properties)
        or len(set(event_keys)) != len(event_keys)
        or any(
            item.node_id not in node_ids
            and bool(node_ids)
            and not (item.node_id.startswith("<") and item.node_id.endswith(">"))
            for item in tripwire_events
        )
    ):
        return False
    clean_pass = (
        total > 0
        and passed == total
        and not any(nonpass_counts)
        and len(set(node_ids)) == total
    )
    if valid:
        return clean_pass and reason == "PASS" and not tripwire_events
    return reason != "PASS"


@dataclass(frozen=True, slots=True)
class SuiteEvidence:
    valid: bool
    total: int
    passed: int
    failures: int
    errors: int
    skipped: int
    xfailed: int
    xpassed: int
    todo: int
    cancelled: int
    node_ids: tuple[str, ...]
    reason: str
    properties: tuple[EvidenceProperty, ...] = ()
    tripwire_events: tuple[TripwireEventEvidence, ...] = ()

    def __post_init__(self) -> None:
        if not _suite_evidence_state_is_valid(self):
            raise ValueError("invalid suite evidence state")


@dataclass(frozen=True, slots=True)
class SelectorRequirement:
    command_id: str
    node_pattern: str
    expected_count: int
    gates: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class InternalEvidenceRequirement:
    source: str
    evidence_id: str
    expected_count: int
    gates: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class InternalEvidence:
    source: str
    evidence_id: str
    passed: bool
    fresh: bool
    valid: bool


@dataclass(frozen=True, slots=True)
class EvidenceMap:
    suites: Mapping[str, SuiteEvidence]
    internal: tuple[InternalEvidence, ...]


@dataclass(frozen=True, slots=True)
class RunOneResult:
    exit_code: int
    command_result: CommandResult
    evidence: SuiteEvidence | None


@dataclass(frozen=True, slots=True)
class GateResult:
    gate: int
    title: str
    status: GateStatus
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DecisionInputs:
    command_results: tuple[CommandResult, ...]
    gate_results: tuple[GateResult, ...]
    resources_unchanged: bool
    tripwires_clean: bool
    contrast_passed: bool
    incident_decisions: Mapping[str, str] | None
    lovable_complete_or_waived: bool


@dataclass(frozen=True, slots=True)
class DecisionResult:
    outcome: DecisionOutcome
    exit_code: int
    reasons: tuple[str, ...]
    final_go: bool = False


@dataclass(frozen=True, slots=True)
class AcceptanceRunResult:
    exit_code: int
    run_id: str
    artifact_root: Path
    decision: DecisionResult
    command_results: tuple[CommandResult, ...]
    report_record: Mapping[str, object] | None


@dataclass(frozen=True, slots=True)
class ExternalDecisionArtifact:
    label: str
    sha256: str
    authority_verified: bool
    author: str
    claimed_role: str
    timestamp: str
    incident_decisions: Mapping[str, str]
    rationales: Mapping[str, str]


class CliMisuseError(ValueError):
    exit_code = 64


INCIDENT_IDS = (
    "PIPELINE_T8_PROVIDER_20260823",
    "CHILD_T9_REAL_LOG_20260827",
    "TEACHER_T5_REAL_LOG_20260829",
)

INCIDENT_LEDGER = (
    {
        "incident_id": "PIPELINE_T8_PROVIDER_20260823",
        "facts": [
            "Two real DeepSeek HTTP 200 calls occurred at 2026-08-23 22:59:31 and 22:59:44 +08.",
            "Only a synthetic transcript and disposable SQLite were involved.",
        ],
        "corrective_controls": [
            "Corrected high-level fakes.",
            "Installed the permanent lowest-level _llm breaker.",
            "Sanitized subprocess environments and reran breaker-free suites.",
        ],
    },
    {
        "incident_id": "CHILD_T9_REAL_LOG_20260827",
        "facts": [
            "Pending-route teardown appended to the real application log at 2026-08-27 19:33:50 +08.",
            "An inherited parent pytest FileHandler was the root cause; incident bytes were preserved.",
        ],
        "corrective_controls": [
            "Added the parent logging guard and byte comparison.",
            "Later Child browser gates kept the real log byte-identical.",
        ],
    },
    {
        "incident_id": "TEACHER_T5_REAL_LOG_20260829",
        "facts": [
            "A non-browser review pytest ran concurrently with two browser suites at 2026-08-29 01:59 +08.",
            "A shared TestClient FileHandler wrote the real log; incident bytes were preserved.",
        ],
        "corrective_controls": [
            "Task 5A isolated pytest logging.",
            "All later acceptance gates ran strictly serially.",
        ],
    },
)


def _incident_report_rows() -> list[dict[str, object]]:
    return [
        {
            "incident_id": incident["incident_id"],
            "facts": list(incident["facts"]),
            "corrective_controls": list(incident["corrective_controls"]),
            "release_owner_acknowledgement": "ABSENT",
            "status": "HUMAN_DECISION_REQUIRED",
            "technical_review_status": "PENDING_INDEPENDENT_EVIDENCE_REVIEW",
        }
        for incident in INCIDENT_LEDGER
    ]


def parse_external_decision_json(payload: bytes) -> ExternalDecisionArtifact:
    """Validate and label a supplied disposition without claiming its authority."""

    try:
        document = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CliMisuseError("malformed external decision JSON") from error
    if not isinstance(document, dict) or set(document) != {
        "author",
        "claimed_role",
        "timestamp",
        "incidents",
    }:
        raise CliMisuseError("external decision has the wrong top-level shape")
    author = document["author"]
    claimed_role = document["claimed_role"]
    timestamp = document["timestamp"]
    incidents = document["incidents"]
    if not isinstance(author, str) or not author.strip():
        raise CliMisuseError("external decision author is required")
    if claimed_role not in {"user", "release_owner"}:
        raise CliMisuseError("external decision role is not eligible")
    if not isinstance(timestamp, str):
        raise CliMisuseError("external decision timestamp is required")
    try:
        parsed_timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as error:
        raise CliMisuseError("external decision timestamp is not RFC3339") from error
    if parsed_timestamp.tzinfo is None:
        raise CliMisuseError("external decision timestamp needs an offset")
    if not isinstance(incidents, list) or len(incidents) != len(INCIDENT_IDS):
        raise CliMisuseError("external decision must cover every incident once")

    decisions: dict[str, str] = {}
    rationales: dict[str, str] = {}
    for incident in incidents:
        if not isinstance(incident, dict) or set(incident) != {
            "incident_id",
            "decision",
            "rationale",
        }:
            raise CliMisuseError("external incident disposition has the wrong shape")
        incident_id = incident["incident_id"]
        decision = incident["decision"]
        rationale = incident["rationale"]
        if incident_id not in INCIDENT_IDS or incident_id in decisions:
            raise CliMisuseError("external incident IDs must be exact and unique")
        if decision not in {"ACCEPT", "REJECT"}:
            raise CliMisuseError("external incident decision must be ACCEPT or REJECT")
        if not isinstance(rationale, str) or not rationale.strip():
            raise CliMisuseError("external incident rationale is required")
        decisions[incident_id] = decision
        rationales[incident_id] = rationale
    if set(decisions) != set(INCIDENT_IDS):
        raise CliMisuseError("external decision omitted an incident")
    return ExternalDecisionArtifact(
        label="UNVERIFIED_SUPPLIED_ARTIFACT",
        sha256=hashlib.sha256(payload).hexdigest(),
        authority_verified=False,
        author=author,
        claimed_role=claimed_role,
        timestamp=timestamp,
        incident_decisions=decisions,
        rationales=rationales,
    )


def decide_release(inputs: DecisionInputs) -> DecisionResult:
    """Return one of the three runner-owned non-GO outcomes."""

    safety_reasons = []
    if not inputs.resources_unchanged:
        safety_reasons.append("RESOURCE_DRIFT")
    if not inputs.tripwires_clean:
        safety_reasons.append("TRIPWIRE_FAILURE")
    if any(
        result.classified_outcome is ClassifiedOutcome.SAFETY_FAILURE
        for result in inputs.command_results
    ):
        safety_reasons.append("COMMAND_SAFETY_FAILURE")
    if safety_reasons:
        return DecisionResult(
            DecisionOutcome.SAFETY_NO_GO,
            3,
            tuple(safety_reasons),
        )

    technical_reasons = []
    if not inputs.command_results or any(
        result.classified_outcome is not ClassifiedOutcome.SUCCESS
        for result in inputs.command_results
    ):
        technical_reasons.append("COMMAND_FAILURE")
    if (
        len(inputs.gate_results) != len(GATE_TITLES)
        or tuple(result.gate for result in inputs.gate_results)
        != tuple(GATE_TITLES)
        or any(result.status is not GateStatus.PASS for result in inputs.gate_results)
    ):
        technical_reasons.append("GATE_FAILURE")
    if not inputs.contrast_passed:
        technical_reasons.append("CONTRAST_FAILURE")
    if inputs.incident_decisions is not None:
        if set(inputs.incident_decisions) != set(INCIDENT_IDS):
            technical_reasons.append("INCIDENT_DECISION_INCOMPLETE")
        elif any(value == "REJECT" for value in inputs.incident_decisions.values()):
            technical_reasons.append("INCIDENT_REJECTED")
        elif any(value != "ACCEPT" for value in inputs.incident_decisions.values()):
            technical_reasons.append("INCIDENT_DECISION_INVALID")
    if not inputs.lovable_complete_or_waived:
        technical_reasons.append("LOVABLE_DELIVERABLE_MISSING")
    if technical_reasons:
        return DecisionResult(
            DecisionOutcome.TECHNICAL_NO_GO,
            1,
            tuple(technical_reasons),
        )
    return DecisionResult(
        DecisionOutcome.TECHNICAL_PASS_HUMAN_DECISION_PENDING,
        2,
        ("HUMAN_AUTHORITY_REQUIRED",),
    )


def _canonical_value(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, bytes):
        return {
            "sha256": hashlib.sha256(value).hexdigest(),
            "size": len(value),
        }
    if isinstance(value, Path):
        return value.as_posix()
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _canonical_value(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, Mapping):
        return {str(key): _canonical_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_canonical_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"value is not canonically serializable: {type(value).__name__}")


def _command_runner_exit(result: CommandResult) -> int:
    if result.classified_outcome is ClassifiedOutcome.SAFETY_FAILURE:
        return 3
    if (
        result.termination is Termination.EXITED
        and result.classified_outcome is ClassifiedOutcome.CHILD_NONZERO
        and result.child_exit is not None
        and result.child_exit > 0
    ):
        return result.child_exit
    if result.classified_outcome is ClassifiedOutcome.SUCCESS:
        return 0
    return 1


def _stream_record(order: int, command_id: str, stream: str, payload: bytes) -> dict:
    return {
        "path": f"commands/{order:02d}-{command_id}.{stream}.log",
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size": len(payload),
    }


def _binary_artifact_record(path: str, payload: bytes) -> dict[str, object]:
    return {
        "path": path,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size": len(payload),
    }


def _suite_counts(evidence: SuiteEvidence | None) -> dict[str, int | None]:
    return {
        name: None if evidence is None else getattr(evidence, name)
        for name in _SUITE_COUNT_FIELDS
    }


def _parsed_evidence_sha256(evidence: SuiteEvidence | None) -> str | None:
    if evidence is None:
        return None
    payload = json.dumps(
        _canonical_value(evidence),
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _structured_suite_values(
    suites: Mapping[str, SuiteEvidence], command_id: str, property_name: str
) -> list[object]:
    evidence = suites.get(command_id)
    if evidence is None:
        return []
    return [
        json.loads(item.value)
        for item in evidence.properties
        if item.name == property_name
    ]


def _gate_report_rows(
    gate_results: tuple[GateResult, ...],
    suites: Mapping[str, SuiteEvidence],
    internal: tuple[InternalEvidence, ...],
) -> list[dict[str, object]]:
    internal_by_key: dict[tuple[str, str], list[InternalEvidence]] = {}
    for item in internal:
        internal_by_key.setdefault((item.source, item.evidence_id), []).append(item)
    rows = []
    for gate in gate_results:
        selector_rows = []
        for requirement in SELECTOR_MANIFEST:
            if gate.gate not in requirement.gates:
                continue
            evidence = suites.get(requirement.command_id)
            actual = 0
            if evidence is not None:
                actual = sum(
                    1
                    for node_id in evidence.node_ids
                    if re.fullmatch(requirement.node_pattern, node_id)
                )
            selector_rows.append(
                {
                    "actual_count": actual,
                    "command_id": requirement.command_id,
                    "expected_count": requirement.expected_count,
                    "node_pattern": requirement.node_pattern,
                }
            )
        internal_rows = []
        for requirement in INTERNAL_EVIDENCE_REQUIREMENTS:
            if gate.gate not in requirement.gates:
                continue
            matches = internal_by_key.get(
                (requirement.source, requirement.evidence_id), []
            )
            internal_rows.append(
                {
                    "actual_count": len(matches),
                    "evidence_id": requirement.evidence_id,
                    "expected_count": requirement.expected_count,
                    "source": requirement.source,
                    "states": [_canonical_value(item) for item in matches],
                }
            )
        rows.append(
            {
                "gate": gate.gate,
                "internal_evidence": internal_rows,
                "reasons": list(gate.reasons),
                "selectors": selector_rows,
                "status": gate.status.value,
                "title": gate.title,
            }
        )
    return rows


def build_report_record(
    *,
    run_id: str,
    generated_at: str,
    tested_head: str,
    decision: DecisionResult,
    command_results: tuple[CommandResult, ...],
    command_specs: tuple[CommandSpec, ...],
    gate_results: tuple[GateResult, ...],
    lovable_status: str,
    external_decision: ExternalDecisionArtifact | None,
    baseline_snapshot: object,
    final_snapshot: object,
    junit_payloads: Mapping[str, bytes] | None = None,
    suite_evidence: Mapping[str, SuiteEvidence] | None = None,
    internal_evidence: tuple[InternalEvidence, ...] | None = None,
    resource_artifacts: Mapping[str, Mapping[str, object]] | None = None,
) -> dict[str, object]:
    """Build the sole in-memory authority record used by JSON and Markdown."""

    suites = {} if suite_evidence is None else dict(suite_evidence)
    internal = () if internal_evidence is None else internal_evidence
    specs_by_id = {spec.command_id: spec for spec in command_specs}
    if len(specs_by_id) != len(command_specs):
        raise ValueError("report command specs must be unique")
    commands = []
    for order, result in enumerate(command_results, start=1):
        spec = specs_by_id.get(result.subcommand)
        if spec is None:
            raise ValueError(f"missing report CommandSpec: {result.subcommand}")
        evidence = suites.get(result.subcommand)
        junit_payload = None if junit_payloads is None else junit_payloads.get(
            result.subcommand
        )
        commands.append(
            {
                "after_snapshot": _canonical_value(result.after_snapshot),
                "argv": list(spec.argv),
                "before_snapshot": _canonical_value(result.before_snapshot),
                "child_exit": result.child_exit,
                "child_started": result.child_started,
                "classified_outcome": result.classified_outcome.value,
                "cleanup_failures": [item.value for item in result.cleanup_failures],
                "conftest_mode": spec.conftest_mode.value,
                "counts": _suite_counts(evidence),
                "duration_seconds": result.duration_seconds,
                "evidence_reason": "MISSING" if evidence is None else evidence.reason,
                "evidence_sha256": _parsed_evidence_sha256(evidence),
                "evidence_valid": False if evidence is None else evidence.valid,
                "junit": (
                    None
                    if junit_payload is None
                    else _binary_artifact_record(
                        f"commands/{order:02d}-{result.subcommand}.junit.xml",
                        junit_payload,
                    )
                ),
                "order": order,
                "output_complete": result.output_complete,
                "reason": result.reason,
                "residual_group_observed": result.residual_group_observed,
                "runner_process_exit": _command_runner_exit(result),
                "stderr": _stream_record(
                    order, result.subcommand, "stderr", result.stderr
                ),
                "stdout": _stream_record(
                    order, result.subcommand, "stdout", result.stdout
                ),
                "subcommand": result.subcommand,
                "termination": result.termination.value,
                "timeout_seconds": spec.timeout_seconds,
                "tripwire_events": list(_tripwire_events_for_evidence(evidence)),
            }
        )
    tripwire_status = _tripwire_status(_tripwire_event_ids(suites), suites.get("browser"))
    record: dict[str, object] = {
        "commands": commands,
        "database_action_evidence": _structured_suite_values(
            suites, "release_db_action_all", "task9.db_action_evidence"
        ),
        "decision": {
            "final_go": False,
            "outcome": decision.outcome.value,
            "reasons": list(decision.reasons),
            "runner_process_exit": decision.exit_code,
        },
        "external_decision": _canonical_value(external_decision),
        "focus_measurements": _structured_suite_values(
            suites, "release_focus_all", "task9.focus_measurement"
        ),
        "gates": _gate_report_rows(gate_results, suites, internal),
        "generated_at": generated_at,
        "incidents": _incident_report_rows(),
        "internal_evidence": _canonical_value(internal),
        "limitations": list(FROZEN_LIMITATIONS),
        "lovable": {
            "completion_or_scope_waiver": lovable_status == "PROVIDED_OR_WAIVED",
            "connector_used": False,
            "project_status": lovable_status,
            "publish_performed": False,
            "source_uploaded": False,
            "status": lovable_status,
            "zero_credit_blocker": (
                None
                if lovable_status == "PROVIDED_OR_WAIVED"
                else "A blank or zero-credit project is not completion evidence."
            ),
        },
        "pending_status": "FINAL_GO_REQUIRES_HUMAN_RELEASE_DECISION",
        "report_roles": {
            "commit_a": "tested implementation",
            "commit_b": "evidence only",
        },
        "resources": {
            "after": _canonical_value(final_snapshot),
            "before": _canonical_value(baseline_snapshot),
        },
        "reviews": {
            "p0": None,
            "p1": None,
            "p2": None,
            "status": "PENDING_INDEPENDENT_EVIDENCE_REVIEW",
        },
        "run_id": run_id,
        "runtime_versions": dict(FROZEN_RUNTIME_VERSION),
        "schema_version": REPORT_SCHEMA_VERSION,
        "suite_evidence": {
            command_id: _canonical_value(evidence)
            for command_id, evidence in sorted(suites.items())
        },
        "supersedes": "docs/acceptance-report.md",
        "tested_head": tested_head,
        "timeout_evidence": _structured_suite_values(
            suites, "child_chat_timeout_all", "task9.timeout_evidence"
        ),
        "tripwires": {
            "provider_tts_socket_context_worker": tripwire_status
        },
        "viewport_contracts": {
            "child": ["1024x576", "1280x720"],
            "teacher": ["1024x768", "1440x900"],
        },
    }
    if resource_artifacts is not None:
        record["resource_artifacts"] = _canonical_value(resource_artifacts)
    return record


def canonical_json_bytes(record: Mapping[str, object]) -> bytes:
    encoded = json.dumps(
        _canonical_value(record),
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return (encoded + "\n").encode("utf-8")


def _markdown_scalar(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


_REPORT_BASE_KEYS = frozenset(
    {
        "commands",
        "database_action_evidence",
        "decision",
        "external_decision",
        "focus_measurements",
        "gates",
        "generated_at",
        "incidents",
        "internal_evidence",
        "limitations",
        "lovable",
        "pending_status",
        "report_roles",
        "resources",
        "reviews",
        "run_id",
        "runtime_versions",
        "schema_version",
        "suite_evidence",
        "supersedes",
        "tested_head",
        "timeout_evidence",
        "tripwires",
        "viewport_contracts",
    }
)
_COMMAND_REPORT_KEYS = frozenset(
    {
        "after_snapshot",
        "argv",
        "before_snapshot",
        "child_exit",
        "child_started",
        "classified_outcome",
        "cleanup_failures",
        "conftest_mode",
        "counts",
        "duration_seconds",
        "evidence_reason",
        "evidence_sha256",
        "evidence_valid",
        "junit",
        "order",
        "output_complete",
        "reason",
        "residual_group_observed",
        "runner_process_exit",
        "stderr",
        "stdout",
        "subcommand",
        "termination",
        "timeout_seconds",
        "tripwire_events",
    }
)
_COUNT_REPORT_KEYS = frozenset(_SUITE_COUNT_FIELDS)
_SUITE_REPORT_KEYS = frozenset(SuiteEvidence.__dataclass_fields__)
_PROPERTY_REPORT_KEYS = frozenset(EvidenceProperty.__dataclass_fields__)
_TRIPWIRE_EVENT_REPORT_KEYS = frozenset(TripwireEventEvidence.__dataclass_fields__)
_INTERNAL_REPORT_KEYS = frozenset(InternalEvidence.__dataclass_fields__)
_FOCUS_EVIDENCE_LABELS = (
    "input",
    "native-button",
    "route-h1",
    "nav-button",
    "link",
    "route-h2",
    "white-panel-control",
    "primary-blue-button",
    "gray-button",
    "dialog-target",
    "dialog-return",
    "textarea",
    "select",
)


def _structured_node_id(kind: str, viewport_id: str) -> str:
    test_names = {
        "focus": "test_release_focus_indicator_meets_three_to_one",
        "db": "test_release_teacher_action_persists_to_disposable_sqlite",
        "timeout": "test_first_chat_timeout_retains_draft_and_reuses_request_id_once",
        "search": "test_release_search_filters_results_and_focus_stay_in_bounds",
        "today": "test_release_today_weekly_metrics_retry_and_grid_stay_in_bounds",
    }
    return f"{test_names[kind]}[{viewport_id}]"


def _structured_property_expectations() -> dict[str, dict[str, tuple[str, ...]]]:
    focus_all = tuple(
        _structured_node_id("focus", viewport)
        for viewport in ("1024x768", "1440x900")
    )
    db_all = tuple(
        _structured_node_id("db", viewport)
        for viewport in ("1024x768", "1440x900")
    )
    timeout_all = tuple(
        _structured_node_id("timeout", viewport)
        for viewport in ("1024x576", "1280x720")
    )
    search_all = tuple(
        _structured_node_id("search", viewport)
        for viewport in ("1024x768", "1440x900")
    )
    today_all = tuple(
        _structured_node_id("today", viewport)
        for viewport in ("1024x768", "1440x900")
    )
    return {
        "browser": {
            "task7.today_metrics_geometry": today_all,
            "task8.search_geometry": search_all,
            "task9.focus_measurement": focus_all,
            "task9.db_action_evidence": db_all,
            "task9.timeout_evidence": timeout_all,
        },
        "release_focus_1024": {
            "task9.focus_measurement": focus_all[:1],
        },
        "release_focus_all": {
            "task9.focus_measurement": focus_all,
        },
        "release_db_action_1024": {
            "task9.db_action_evidence": db_all[:1],
        },
        "release_db_action_all": {
            "task9.db_action_evidence": db_all,
        },
        "child_chat_timeout_1024": {
            "task9.timeout_evidence": timeout_all[:1],
        },
        "child_chat_timeout_all": {
            "task9.timeout_evidence": timeout_all,
        },
    }


_STRUCTURED_PROPERTY_EXPECTATIONS = _structured_property_expectations()


def _report_suite_evidence(value: object) -> SuiteEvidence:
    if not isinstance(value, Mapping) or set(value) != _SUITE_REPORT_KEYS:
        raise CliMisuseError("completed report suite evidence is invalid")
    raw_properties = value.get("properties")
    raw_tripwire_events = value.get("tripwire_events")
    if not isinstance(raw_properties, list) or not isinstance(raw_tripwire_events, list):
        raise CliMisuseError("completed report suite evidence is invalid")
    try:
        properties = tuple(
            EvidenceProperty(**property_value)
            for property_value in raw_properties
            if isinstance(property_value, Mapping)
            and set(property_value) == _PROPERTY_REPORT_KEYS
        )
        if len(properties) != len(raw_properties):
            raise ValueError("property shape")
        tripwire_events = tuple(
            TripwireEventEvidence(**event_value)
            for event_value in raw_tripwire_events
            if isinstance(event_value, Mapping)
            and set(event_value) == _TRIPWIRE_EVENT_REPORT_KEYS
        )
        if len(tripwire_events) != len(raw_tripwire_events):
            raise ValueError("tripwire event shape")
        node_ids = value.get("node_ids")
        if not isinstance(node_ids, list):
            raise ValueError("node IDs")
        return SuiteEvidence(
            valid=value.get("valid"),
            total=value.get("total"),
            passed=value.get("passed"),
            failures=value.get("failures"),
            errors=value.get("errors"),
            skipped=value.get("skipped"),
            xfailed=value.get("xfailed"),
            xpassed=value.get("xpassed"),
            todo=value.get("todo"),
            cancelled=value.get("cancelled"),
            node_ids=tuple(node_ids),
            reason=value.get("reason"),
            properties=properties,
            tripwire_events=tripwire_events,
        )
    except (TypeError, ValueError) as error:
        raise CliMisuseError("completed report suite evidence is invalid") from error


def _report_internal_evidence(value: object) -> InternalEvidence:
    if not isinstance(value, Mapping) or set(value) != _INTERNAL_REPORT_KEYS:
        raise CliMisuseError("completed report internal evidence is invalid")
    item = InternalEvidence(**value)
    if (
        not isinstance(item.source, str)
        or not item.source
        or not isinstance(item.evidence_id, str)
        or not item.evidence_id
        or any(type(state) is not bool for state in (item.passed, item.fresh, item.valid))
    ):
        raise CliMisuseError("completed report internal evidence is invalid")
    return item


_FILE_SNAPSHOT_KEYS = frozenset(FileSnapshot.__dataclass_fields__)
_DATABASE_SNAPSHOT_KEYS = frozenset(DatabaseSnapshot.__dataclass_fields__)
_DIRECTORY_ENTRY_KEYS = frozenset(DirectoryEntrySnapshot.__dataclass_fields__)
_DIRECTORY_SNAPSHOT_KEYS = frozenset(DirectorySnapshot.__dataclass_fields__)
_PROTECTED_PATH_KEYS = frozenset(ProtectedPathSnapshot.__dataclass_fields__)
_RESOURCE_SNAPSHOT_KEYS = frozenset(ResourceSnapshot.__dataclass_fields__)


def _report_resource_error() -> NoReturn:
    raise CliMisuseError("completed report resource snapshot is invalid")


def _report_reasons(value: object) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or any(not isinstance(item, str) or not item for item in value)
        or len(value) != len(set(value))
    ):
        _report_resource_error()
    return tuple(value)


def _report_file_snapshot(value: object) -> FileSnapshot:
    if not isinstance(value, Mapping) or set(value) != _FILE_SNAPSHOT_KEYS:
        _report_resource_error()
    try:
        kind = FileKind(value["kind"])
    except (TypeError, ValueError):
        _report_resource_error()
    mode = value["mode"]
    size = value["size"]
    mtime_ns = value["mtime_ns"]
    sha256 = value["sha256"]
    symlink_target = value["symlink_target"]
    error = value["error"]
    metadata = (mode, size, mtime_ns)
    metadata_present = all(type(item) is int and item >= 0 for item in metadata)
    metadata_absent = all(item is None for item in metadata)
    if not (
        (sha256 is None or _valid_sha256(sha256))
        and (symlink_target is None or isinstance(symlink_target, str))
        and (error is None or isinstance(error, str))
    ):
        _report_resource_error()
    if kind is FileKind.MISSING:
        valid = metadata_absent and sha256 is None and symlink_target is None and error is None
    elif kind is FileKind.REGULAR:
        valid = metadata_present and _valid_sha256(sha256) and symlink_target is None and error is None
    elif kind in {FileKind.DIRECTORY, FileKind.SPECIAL}:
        valid = metadata_present and sha256 is None and symlink_target is None and error is None
    elif kind is FileKind.SYMLINK:
        valid = metadata_present and bool(symlink_target) and sha256 is None and error is None
    else:
        valid = (
            (metadata_present or metadata_absent)
            and sha256 is None
            and symlink_target is None
            and bool(error)
        )
    if not valid:
        _report_resource_error()
    return FileSnapshot(
        kind=kind,
        mode=mode,
        size=size,
        mtime_ns=mtime_ns,
        sha256=sha256,
        symlink_target=symlink_target,
        error=error,
    )


def _report_database_snapshot(value: object) -> DatabaseSnapshot:
    if not isinstance(value, Mapping) or set(value) != _DATABASE_SNAPSHOT_KEYS:
        _report_resource_error()
    logical_digest = value["logical_digest"]
    if logical_digest is not None and not _valid_sha256(logical_digest):
        _report_resource_error()
    database = _report_file_snapshot(value["database"])
    wal = _report_file_snapshot(value["wal"])
    shm = _report_file_snapshot(value["shm"])
    expected_reasons: list[str] = []
    if database.kind is FileKind.MISSING:
        expected_reasons.append("DATABASE_MISSING")
    elif database.kind is not FileKind.REGULAR:
        expected_reasons.append("DATABASE_NOT_REGULAR")
    if wal.kind not in {FileKind.MISSING, FileKind.REGULAR}:
        expected_reasons.append("WAL_NOT_REGULAR")
    if shm.kind not in {FileKind.MISSING, FileKind.REGULAR}:
        expected_reasons.append("SHM_NOT_REGULAR")
    if expected_reasons:
        if logical_digest is not None:
            _report_resource_error()
    elif logical_digest is None:
        expected_reasons.append("DATABASE_LOGICAL_UNREADABLE")
    supplied_reasons = _report_reasons(value["unsafe_reasons"])
    if supplied_reasons != tuple(expected_reasons):
        _report_resource_error()
    return DatabaseSnapshot(
        logical_digest=logical_digest,
        database=database,
        wal=wal,
        shm=shm,
        unsafe_reasons=supplied_reasons,
    )


def _report_relative_path(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.startswith("/")
        or "\\" in value
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        _report_resource_error()
    return value


def _report_directory_snapshot(
    value: object, *, allow_symlinks: bool
) -> DirectorySnapshot:
    if not isinstance(value, Mapping) or set(value) != _DIRECTORY_SNAPSHOT_KEYS:
        _report_resource_error()
    root = _report_file_snapshot(value["root"])
    raw_entries = value["entries"]
    if not isinstance(raw_entries, list):
        _report_resource_error()
    entries: list[DirectoryEntrySnapshot] = []
    for raw_entry in raw_entries:
        if not isinstance(raw_entry, Mapping) or set(raw_entry) != _DIRECTORY_ENTRY_KEYS:
            _report_resource_error()
        entries.append(
            DirectoryEntrySnapshot(
                relative_path=_report_relative_path(raw_entry["relative_path"]),
                snapshot=_report_file_snapshot(raw_entry["snapshot"]),
            )
        )
    paths = tuple(entry.relative_path for entry in entries)
    if paths != tuple(sorted(paths)) or len(paths) != len(set(paths)):
        _report_resource_error()
    supplied_reasons = _report_reasons(value["unsafe_reasons"])
    try:
        reconstructed = _make_directory_snapshot(
            root,
            tuple(entries),
            allow_symlinks=allow_symlinks,
            scan_error=value["scan_error"],
            scan_source=value["scan_source"],
        )
    except (TypeError, ValueError):
        _report_resource_error()
    if supplied_reasons != reconstructed.unsafe_reasons:
        _report_resource_error()
    if value["digest"] != reconstructed.digest:
        _report_resource_error()
    return reconstructed


def _report_protected_path_snapshot(value: object) -> ProtectedPathSnapshot:
    if not isinstance(value, Mapping) or set(value) != _PROTECTED_PATH_KEYS:
        _report_resource_error()
    file_state = _report_file_snapshot(value["file"])
    raw_directory = value["directory"]
    directory = (
        None
        if raw_directory is None
        else _report_directory_snapshot(raw_directory, allow_symlinks=True)
    )
    if (file_state.kind is FileKind.DIRECTORY) is not (directory is not None):
        _report_resource_error()
    expected_reasons: list[str] = []
    if file_state.kind is FileKind.MISSING:
        expected_reasons.append("PATH_MISSING")
    elif file_state.kind in {FileKind.UNREADABLE, FileKind.SPECIAL}:
        expected_reasons.append("PATH_UNSAFE")
    elif directory is not None:
        expected_reasons.extend(directory.unsafe_reasons)
        if directory.root != file_state:
            expected_reasons.append("PATH_FILE_DIRECTORY_MISMATCH")
    supplied_reasons = _report_reasons(value["unsafe_reasons"])
    if supplied_reasons != tuple(dict.fromkeys(expected_reasons)):
        _report_resource_error()
    return ProtectedPathSnapshot(
        relative_path=_report_relative_path(value["relative_path"]),
        file=file_state,
        directory=directory,
        unsafe_reasons=supplied_reasons,
    )


def _report_resource_snapshot(value: object) -> CanonicalResourceSnapshot:
    if not isinstance(value, Mapping) or set(value) != _RESOURCE_SNAPSHOT_KEYS:
        _report_resource_error()
    raw_user_paths = value["user_paths"]
    if not isinstance(raw_user_paths, list):
        _report_resource_error()
    user_paths = tuple(
        _report_protected_path_snapshot(item) for item in raw_user_paths
    )
    if tuple(item.relative_path for item in user_paths) != PROTECTED_USER_PATHS:
        _report_resource_error()
    git_head = value["git_head"]
    if git_head is not None and (
        not isinstance(git_head, str)
        or re.fullmatch(r"[0-9a-f]{40}", git_head) is None
    ):
        _report_resource_error()
    raw_porcelain = value["git_porcelain"]
    if raw_porcelain is None:
        git_porcelain = None
    elif (
        not isinstance(raw_porcelain, Mapping)
        or set(raw_porcelain) != {"sha256", "size"}
        or not _valid_sha256(raw_porcelain.get("sha256"))
        or type(raw_porcelain.get("size")) is not int
        or raw_porcelain["size"] < 0
    ):
        _report_resource_error()
    else:
        git_porcelain = CanonicalBytesSnapshot(
            sha256=raw_porcelain["sha256"], size=raw_porcelain["size"]
        )
    database = _report_database_snapshot(value["database"])
    log = _report_file_snapshot(value["log"])
    tts = _report_directory_snapshot(value["tts"], allow_symlinks=False)
    media = _report_directory_snapshot(value["media"], allow_symlinks=False)
    expected_reasons: list[str] = [
        f"DATABASE:{reason}" for reason in database.unsafe_reasons
    ]
    if log.kind is not FileKind.REGULAR:
        expected_reasons.append("LOG_NOT_REGULAR")
    expected_reasons.extend(f"TTS:{reason}" for reason in tts.unsafe_reasons)
    expected_reasons.extend(
        f"MEDIA:{reason}"
        for reason in media.unsafe_reasons
        if reason != "DIRECTORY_MISSING"
    )
    for protected in user_paths:
        expected_reasons.extend(
            f"USER_PATH:{protected.relative_path}:{reason}"
            for reason in protected.unsafe_reasons
            if reason != "PATH_MISSING"
        )
    if git_head is None:
        expected_reasons.append("GIT_HEAD_UNAVAILABLE")
    if git_porcelain is None:
        expected_reasons.append("GIT_STATUS_UNAVAILABLE")
    supplied_reasons = _report_reasons(value["unsafe_reasons"])
    if supplied_reasons != tuple(dict.fromkeys(expected_reasons)):
        _report_resource_error()
    return CanonicalResourceSnapshot(
        database=database,
        log=log,
        tts=tts,
        media=media,
        user_paths=user_paths,
        git_head=git_head,
        git_porcelain=git_porcelain,
        unsafe_reasons=supplied_reasons,
    )


def _report_optional_resource_snapshot(
    value: object,
) -> CanonicalResourceSnapshot | None:
    return None if value is None else _report_resource_snapshot(value)


def _report_command_result(command: Mapping[str, object]) -> CommandResult:
    try:
        return CommandResult(
            subcommand=command["subcommand"],
            child_started=command["child_started"],
            child_exit=command["child_exit"],
            termination=Termination(command["termination"]),
            output_complete=command["output_complete"],
            residual_group_observed=command["residual_group_observed"],
            cleanup_failures=tuple(
                CleanupFailure(value) for value in command["cleanup_failures"]
            ),
            classified_outcome=ClassifiedOutcome(command["classified_outcome"]),
            reason=command["reason"],
            before_snapshot=_report_optional_resource_snapshot(
                command["before_snapshot"]
            ),
            after_snapshot=_report_optional_resource_snapshot(
                command["after_snapshot"]
            ),
            duration_seconds=command["duration_seconds"],
        )
    except CliMisuseError:
        raise
    except (KeyError, TypeError, ValueError) as error:
        raise CliMisuseError("completed report command state is invalid") from error


def _exact_viewport(value: object, viewport_id: str) -> bool:
    width, height = (int(part) for part in viewport_id.split("x"))
    return value == {"height": height, "width": width}


def _finite_number(value: object) -> bool:
    return type(value) in {int, float} and math.isfinite(value)


def _exact_numeric_object(value: object, keys: set[str]) -> bool:
    return bool(
        isinstance(value, Mapping)
        and set(value) == keys
        and all(_finite_number(item) for item in value.values())
    )


def _validate_focus_property(value: object, viewport_id: str) -> bool:
    if (
        not isinstance(value, Mapping)
        or set(value) != {"measurements", "viewport", "viewport_id"}
        or value.get("viewport_id") != viewport_id
        or not _exact_viewport(value.get("viewport"), viewport_id)
        or not isinstance(value.get("measurements"), list)
    ):
        return False
    measurements = value["measurements"]
    if tuple(item.get("label") for item in measurements if isinstance(item, Mapping)) != _FOCUS_EVIDENCE_LABELS:
        return False
    width, height = (int(part) for part in viewport_id.split("x"))
    for item in measurements:
        if (
            not isinstance(item, Mapping)
            or set(item)
            != {
                "adjacentColors",
                "bestRatios",
                "focusBounds",
                "label",
                "rect",
                "ringColors",
                "ringThicknesses",
            }
            or not isinstance(item["ringColors"], list)
            or len(item["ringColors"]) < 2
            or len(set(item["ringColors"])) < 2
            or any(
                not isinstance(color, str)
                or re.fullmatch(r"#[0-9a-f]{6}", color) is None
                for color in item["ringColors"]
            )
            or not isinstance(item["adjacentColors"], list)
            or len(item["adjacentColors"]) != 2
            or any(
                not isinstance(color, str)
                or re.fullmatch(r"#[0-9a-f]{6}", color) is None
                for color in item["adjacentColors"]
            )
            or not isinstance(item["ringThicknesses"], list)
            or len(item["ringThicknesses"]) < 2
            or any(
                not _finite_number(thickness) or thickness < 3
                for thickness in item["ringThicknesses"]
            )
            or not isinstance(item["bestRatios"], list)
            or len(item["bestRatios"]) != 2
            or any(
                not _finite_number(ratio) or ratio < 3
                for ratio in item["bestRatios"]
            )
            or not _exact_numeric_object(
                item["rect"], {"height", "width", "x", "y"}
            )
            or not _exact_numeric_object(
                item["focusBounds"], {"bottom", "left", "right", "top"}
            )
            or item["rect"]["width"] <= 0
            or item["rect"]["height"] <= 0
            or item["focusBounds"]["left"] < 0
            or item["focusBounds"]["top"] < 0
            or item["focusBounds"]["right"] > width
            or item["focusBounds"]["bottom"] > height
        ):
            return False
    return True


def _validate_db_property(value: object, viewport_id: str) -> bool:
    return bool(
        isinstance(value, Mapping)
        and set(value)
        == {
            "after_count",
            "before_count",
            "business_name_sha256",
            "database_role",
            "outside_repository_data",
            "resolved_fixture_match",
            "viewport",
            "viewport_id",
        }
        and value.get("after_count") == 1
        and value.get("before_count") == 0
        and _valid_sha256(value.get("business_name_sha256"))
        and value.get("database_role") == "disposable-browser-app.db"
        and value.get("outside_repository_data") is True
        and value.get("resolved_fixture_match") is True
        and value.get("viewport_id") == viewport_id
        and _exact_viewport(value.get("viewport"), viewport_id)
    )


_TIMEOUT_PROPERTY_KEYS = {
    "activation_sequence",
    "body_reused_exactly",
    "chat_attempts",
    "completion_requests_at_9999",
    "completion_requests_during_failure_boundary",
    "durable_bytes_unchanged_at_9999",
    "failure_transitions_at_10000",
    "header_matches_body_request_id",
    "outstanding_chat_requests_at_9999",
    "request_id_sha256",
    "retry_controls_at_10000",
    "retry_controls_at_9999",
    "retry_requests",
    "state_at_10000",
    "state_at_9999",
    "success_copy_at_9999",
    "timeout_ms",
    "tts_requests_at_9999",
    "tts_requests_during_failure_boundary",
    "viewport",
    "viewport_id",
}


def _validate_timeout_property(value: object, viewport_id: str) -> bool:
    return bool(
        isinstance(value, Mapping)
        and set(value) == _TIMEOUT_PROPERTY_KEYS
        and value.get("activation_sequence") == ["Enter", "Space", "Enter"]
        and value.get("body_reused_exactly") is True
        and value.get("chat_attempts") == 2
        and value.get("completion_requests_at_9999") == 0
        and value.get("completion_requests_during_failure_boundary") == 0
        and value.get("durable_bytes_unchanged_at_9999") is True
        and value.get("failure_transitions_at_10000") == 1
        and value.get("header_matches_body_request_id") is True
        and value.get("outstanding_chat_requests_at_9999") == 1
        and _valid_sha256(value.get("request_id_sha256"))
        and value.get("retry_controls_at_10000") == 1
        and value.get("retry_controls_at_9999") == 0
        and value.get("retry_requests") == 1
        and value.get("state_at_10000") == "submission_failed"
        and value.get("state_at_9999") == "submitting"
        and value.get("success_copy_at_9999") is False
        and value.get("timeout_ms") == 10_000
        and value.get("tts_requests_at_9999") == 0
        and value.get("tts_requests_during_failure_boundary") == 0
        and value.get("viewport_id") == viewport_id
        and _exact_viewport(value.get("viewport"), viewport_id)
    )


def _validate_search_geometry_property(value: object, viewport_id: str) -> bool:
    if (
        not isinstance(value, Mapping)
        or set(value)
        != {
            "filter_height",
            "focus_ratios",
            "minimum_target_height",
            "viewport",
        }
        or not _exact_viewport(value.get("viewport"), viewport_id)
    ):
        return False
    _width, height = (int(part) for part in viewport_id.split("x"))
    return bool(
        _finite_number(value.get("filter_height"))
        and 0 < value["filter_height"] <= height
        and isinstance(value.get("focus_ratios"), list)
        and len(value["focus_ratios"]) == 2
        and all(
            _finite_number(ratio) and ratio >= 3
            for ratio in value["focus_ratios"]
        )
        and _finite_number(value.get("minimum_target_height"))
        and 44 <= value["minimum_target_height"] <= height
    )


def _validate_today_metrics_geometry_property(
    value: object, viewport_id: str
) -> bool:
    if (
        not isinstance(value, Mapping)
        or set(value)
        != {"metric_cards", "retry_height", "retry_width", "viewport"}
        or not _exact_viewport(value.get("viewport"), viewport_id)
    ):
        return False
    width, height = (int(part) for part in viewport_id.split("x"))
    return bool(
        type(value.get("metric_cards")) is int
        and value["metric_cards"] == 5
        and _finite_number(value.get("retry_height"))
        and 44 <= value["retry_height"] <= height
        and _finite_number(value.get("retry_width"))
        and 44 <= value["retry_width"] <= width
    )


def _validate_pending_structured_properties(
    suites: Mapping[str, SuiteEvidence],
) -> None:
    validators = {
        "task7.today_metrics_geometry": _validate_today_metrics_geometry_property,
        "task8.search_geometry": _validate_search_geometry_property,
        "task9.focus_measurement": _validate_focus_property,
        "task9.db_action_evidence": _validate_db_property,
        "task9.timeout_evidence": _validate_timeout_property,
    }
    for command_id, evidence in suites.items():
        expected_by_name = _STRUCTURED_PROPERTY_EXPECTATIONS.get(command_id, {})
        expected_keys = {
            (node_id, property_name)
            for property_name, node_ids in expected_by_name.items()
            for node_id in node_ids
        }
        actual_keys = {
            (item.node_id, item.name) for item in evidence.properties
        }
        if actual_keys != expected_keys or len(evidence.properties) != len(expected_keys):
            raise CliMisuseError("completed report structured evidence is invalid")
        for item in evidence.properties:
            viewport_match = re.search(r"\[([0-9]+x[0-9]+)\]$", item.node_id)
            if viewport_match is None:
                raise CliMisuseError("completed report structured evidence is invalid")
            value = json.loads(item.value)
            if not validators[item.name](value, viewport_match.group(1)):
                raise CliMisuseError("completed report structured evidence is invalid")


def _completed_report_execution_contract_is_valid(
    *,
    record: Mapping[str, object],
    commands: list[Mapping[str, object]],
    results: tuple[CommandResult, ...],
    suites: Mapping[str, SuiteEvidence],
    internal: tuple[InternalEvidence, ...],
    artifact_root: Path | None,
) -> bool:
    try:
        expected_ids = tuple(COMMAND_TIMEOUTS)
        command_ids = tuple(command["subcommand"] for command in commands)
        if (
            not commands
            or len(commands) > len(expected_ids)
            or command_ids != expected_ids[: len(commands)]
            or any(
                result.classified_outcome is not ClassifiedOutcome.SUCCESS
                for result in results[:-1]
            )
            or (
                len(commands) < len(expected_ids)
                and results[-1].classified_outcome is ClassifiedOutcome.SUCCESS
            )
        ):
            return False
        expected_artifact_root = (
            Path(artifact_root).resolve()
            if artifact_root is not None
            else Path("/__task9_in_memory_artifact_root__")
        )
        expected_specs = build_command_specs(
            Path(__file__).resolve().parents[1], expected_artifact_root
        )[: len(commands)]
        recorded_junit_parent: Path | None = None
        expected_suite_ids: set[str] = set()
        for order, (command, result, spec) in enumerate(
            zip(commands, results, expected_specs, strict=True), start=1
        ):
            expected_junit_path = f"commands/{order:02d}-{spec.command_id}.junit.xml"
            actual_argv = list(command["argv"])
            if artifact_root is None:
                normalized_argv = []
                for argument in actual_argv:
                    if not argument.startswith("--junitxml="):
                        normalized_argv.append(argument)
                        continue
                    recorded_junit = Path(
                        argument.removeprefix("--junitxml=")
                    )
                    if not recorded_junit.is_absolute():
                        return False
                    parent = recorded_junit.parent.resolve()
                    if recorded_junit_parent is None:
                        recorded_junit_parent = parent
                    elif parent != recorded_junit_parent:
                        return False
                    normalized_argv.append(
                        f"--junitxml={expected_artifact_root / recorded_junit.name}"
                    )
                actual_argv = normalized_argv
            if (
                actual_argv != list(spec.argv)
                or command["timeout_seconds"] != spec.timeout_seconds
                or command["conftest_mode"] != spec.conftest_mode.value
                or command["stdout"]["path"]
                != f"commands/{order:02d}-{spec.command_id}.stdout.log"
                or command["stderr"]["path"]
                != f"commands/{order:02d}-{spec.command_id}.stderr.log"
                or (
                    spec.evidence_format is EvidenceFormat.TAP
                    and command["junit"] is not None
                )
            ):
                return False
            evidence = suites.get(spec.command_id)
            if spec.evidence_format is EvidenceFormat.JUNIT:
                if command["junit"] is not None:
                    if command["junit"]["path"] != expected_junit_path:
                        return False
                    expected_suite_ids.add(spec.command_id)
                elif evidence is not None:
                    return False
            elif result.classified_outcome is not ClassifiedOutcome.SUCCESS:
                if evidence is not None:
                    return False
            else:
                expected_suite_ids.add(spec.command_id)
            if result.classified_outcome is ClassifiedOutcome.SUCCESS and (
                evidence is None
                or not evidence.valid
                or evidence.total <= 0
                or (
                    spec.evidence_format is EvidenceFormat.JUNIT
                    and command["junit"] is None
                )
            ):
                return False
        if set(suites) != expected_suite_ids:
            return False

        resources = record["resources"]
        baseline = _report_resource_snapshot(resources["before"])
        final_snapshot = _report_resource_snapshot(resources["after"])
        if (
            _snapshot_is_unsafe(baseline)
            or any(
                result.before_snapshot != baseline for result in results
            )
            or any(result.after_snapshot != baseline for result in results[:-1])
            or (
                not _snapshots_are_unchanged(baseline, final_snapshot)
                and results[-1].after_snapshot != final_snapshot
            )
        ):
            return False
        expected_internal = _run_internal_evidence(
            command_results=results,
            all_evidence=suites,
            baseline=baseline,
            final_snapshot=final_snapshot,
            version_exact=True,
        )
        if internal != expected_internal:
            return False
        _validate_pending_structured_properties(
            {
                result.subcommand: suites[result.subcommand]
                for result in results
                if result.classified_outcome is ClassifiedOutcome.SUCCESS
            }
        )
        return True
    except (CliMisuseError, IndexError, KeyError, TypeError, ValueError):
        return False


def _pending_report_contract_is_valid(
    *,
    record: Mapping[str, object],
    commands: list[Mapping[str, object]],
    results: tuple[CommandResult, ...],
    suites: Mapping[str, SuiteEvidence],
    internal: tuple[InternalEvidence, ...],
    recomputed_gates: tuple[GateResult, ...],
    artifact_root: Path | None,
) -> bool:
    try:
        lovable = record["lovable"]
        return bool(
            _completed_report_execution_contract_is_valid(
                record=record,
                commands=commands,
                results=results,
                suites=suites,
                internal=internal,
                artifact_root=artifact_root,
            )
            and len(commands) == len(COMMAND_TIMEOUTS)
            and all(
                result.classified_outcome is ClassifiedOutcome.SUCCESS
                for result in results
            )
            and all(gate.status is GateStatus.PASS for gate in recomputed_gates)
            and record["tripwires"]["provider_tts_socket_context_worker"]
            == "PASS"
            and lovable.get("completion_or_scope_waiver") is True
            and lovable.get("project_status") == "PROVIDED_OR_WAIVED"
            and lovable.get("status") == "PROVIDED_OR_WAIVED"
            and lovable.get("zero_credit_blocker") is None
        )
    except (CliMisuseError, IndexError, KeyError, TypeError, ValueError):
        return False


def _validate_report_cross_fields(
    record: Mapping[str, object],
    commands: list[Mapping[str, object]],
    *,
    artifact_root: Path | None,
) -> None:
    raw_suites = record["suite_evidence"]
    if (
        not isinstance(raw_suites, Mapping)
        or any(
            not isinstance(command_id, str) or command_id not in COMMAND_TIMEOUTS
            for command_id in raw_suites
        )
    ):
        raise CliMisuseError("completed report suite evidence is invalid")
    suites = {
        command_id: _report_suite_evidence(value)
        for command_id, value in raw_suites.items()
    }
    raw_internal = record["internal_evidence"]
    if not isinstance(raw_internal, list):
        raise CliMisuseError("completed report internal evidence is invalid")
    internal = tuple(_report_internal_evidence(value) for value in raw_internal)
    results = tuple(_report_command_result(command) for command in commands)
    tripwire_events = _tripwire_event_ids(suites)
    tripwire_status = _tripwire_status(tripwire_events, suites.get("browser"))
    if (
        record["tripwires"]["provider_tts_socket_context_worker"]
        != tripwire_status
    ):
        raise CliMisuseError("completed report tripwire state is invalid")
    tripwire_internal = tuple(
        item
        for item in internal
        if item.source == "tripwire"
        and item.evidence_id
        == "provider_tts_socket_context_and_worker_tripwires_clean"
    )
    if len(tripwire_internal) > 1 or (
        tripwire_internal
        and tripwire_internal[0] != _tripwire_internal_evidence(tripwire_status)
    ) or (not tripwire_internal and tripwire_status != "NOT_PROVEN"):
        raise CliMisuseError("completed report tripwire state is invalid")

    for command, result in zip(commands, results, strict=True):
        evidence = suites.get(result.subcommand)
        if (
            command["runner_process_exit"] != _command_runner_exit(result)
            or command["counts"] != _suite_counts(evidence)
            or command["evidence_valid"]
            is not (False if evidence is None else evidence.valid)
            or command["evidence_reason"]
            != ("MISSING" if evidence is None else evidence.reason)
            or command["evidence_sha256"] != _parsed_evidence_sha256(evidence)
            or tuple(command["tripwire_events"])
            != _tripwire_events_for_evidence(evidence)
        ):
            raise CliMisuseError("completed report command evidence is invalid")

    expected_top_level = {
        "focus_measurements": _structured_suite_values(
            suites, "release_focus_all", "task9.focus_measurement"
        ),
        "database_action_evidence": _structured_suite_values(
            suites, "release_db_action_all", "task9.db_action_evidence"
        ),
        "timeout_evidence": _structured_suite_values(
            suites, "child_chat_timeout_all", "task9.timeout_evidence"
        ),
    }
    if any(record[name] != value for name, value in expected_top_level.items()):
        raise CliMisuseError("completed report structured evidence is invalid")

    manifest_commands = {row.command_id for row in SELECTOR_MANIFEST}
    gate_suites = {
        command_id: evidence
        for command_id, evidence in suites.items()
        if command_id in manifest_commands
    }
    resources = record["resources"]
    baseline = _report_resource_snapshot(resources["before"])
    final_snapshot = _report_resource_snapshot(resources["after"])
    tested_head = record["tested_head"]
    head_snapshots = (baseline, final_snapshot) + tuple(
        snapshot
        for result in results
        for snapshot in (result.before_snapshot, result.after_snapshot)
    )
    if any(
        _snapshot_git_head(snapshot) != tested_head
        for snapshot in head_snapshots
    ):
        raise CliMisuseError("completed report tested HEAD is inconsistent")
    recomputed_gates = evaluate_gates(
        results,
        final_snapshot,
        EvidenceMap(suites=gate_suites, internal=internal),
    )
    if record["gates"] != _gate_report_rows(recomputed_gates, gate_suites, internal):
        raise CliMisuseError("completed report gates are not raw-evidence-derived")

    resources_unchanged = bool(
        _snapshots_are_unchanged(baseline, final_snapshot)
        and all(
            _snapshots_are_unchanged(
                result.before_snapshot, result.after_snapshot
            )
            for result in results
        )
    )
    lovable = record["lovable"]
    recomputed_decision = decide_release(
        DecisionInputs(
            command_results=results,
            gate_results=recomputed_gates,
            resources_unchanged=resources_unchanged,
            tripwires_clean=tripwire_status != "FAIL",
            contrast_passed=True,
            incident_decisions=None,
            lovable_complete_or_waived=(
                lovable.get("completion_or_scope_waiver") is True
                and lovable.get("project_status") == "PROVIDED_OR_WAIVED"
                and lovable.get("status") == "PROVIDED_OR_WAIVED"
                and lovable.get("zero_credit_blocker") is None
            ),
        )
    )
    pending_contract_valid = _pending_report_contract_is_valid(
        record=record,
        commands=commands,
        results=results,
        suites=suites,
        internal=internal,
        recomputed_gates=recomputed_gates,
        artifact_root=artifact_root,
    )
    if (
        recomputed_decision.outcome
        is DecisionOutcome.TECHNICAL_PASS_HUMAN_DECISION_PENDING
        and not pending_contract_valid
    ):
        recomputed_decision = DecisionResult(
            DecisionOutcome.TECHNICAL_NO_GO,
            1,
            ("REPORT_INTEGRITY_FAILURE",),
        )
    expected_decision = {
        "final_go": False,
        "outcome": recomputed_decision.outcome.value,
        "reasons": list(recomputed_decision.reasons),
        "runner_process_exit": recomputed_decision.exit_code,
    }
    if record["decision"] != expected_decision:
        raise CliMisuseError("completed report decision is not raw-evidence-derived")


def _valid_sha256(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _valid_artifact_record(value: object) -> bool:
    return bool(
        isinstance(value, Mapping)
        and set(value) == {"path", "sha256", "size"}
        and isinstance(value["path"], str)
        and value["path"]
        and _valid_sha256(value["sha256"])
        and type(value["size"]) is int
        and value["size"] >= 0
    )


def _completed_report_provenance_is_valid(
    run_id: object,
    generated_at: object,
    artifact_root: Path | None,
) -> bool:
    if (
        not isinstance(run_id, str)
        or re.fullmatch(r"[0-9]{8}T[0-9]{12}Z-task9", run_id) is None
        or not isinstance(generated_at, str)
        or re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z",
            generated_at,
        )
        is None
        or artifact_root is None
        or Path(artifact_root).name != run_id
    ):
        return False
    try:
        run_timestamp = datetime.strptime(
            run_id.removesuffix("-task9"), "%Y%m%dT%H%M%S%fZ"
        )
        generated_timestamp = datetime.strptime(
            generated_at, "%Y-%m-%dT%H:%M:%SZ"
        )
    except ValueError:
        return False
    return generated_timestamp == run_timestamp.replace(microsecond=0)


def _completed_missing_lovable_state_is_valid(value: object) -> bool:
    return bool(
        isinstance(value, Mapping)
        and set(value)
        == {
            "completion_or_scope_waiver",
            "connector_used",
            "project_status",
            "publish_performed",
            "source_uploaded",
            "status",
            "zero_credit_blocker",
        }
        and value.get("completion_or_scope_waiver") is False
        and value.get("connector_used") is False
        and value.get("project_status") == "MISSING"
        and value.get("publish_performed") is False
        and value.get("source_uploaded") is False
        and value.get("status") == "MISSING"
        and value.get("zero_credit_blocker")
        == "A blank or zero-credit project is not completion evidence."
    )


def _verified_lovable_reference_is_valid(artifact_root: Path | None) -> bool:
    if artifact_root is None:
        return False
    root = Path(artifact_root)
    if root.parent.name != "acceptance" or root.parent.parent.name != "artifacts":
        return False
    repo_root = root.parents[2]
    docs_root = repo_root / "docs"
    lovable_root = docs_root / "lovable"
    reference = lovable_root / "prototype-reference.md"
    try:
        if not stat.S_ISDIR(os.lstat(docs_root).st_mode):
            return False
        if not stat.S_ISDIR(os.lstat(lovable_root).st_mode):
            return False
        reference_stat = os.lstat(reference)
        if not stat.S_ISREG(reference_stat.st_mode) or reference_stat.st_size > 8192:
            return False
        payload = reference.read_bytes()
        text = payload.decode("utf-8", errors="strict")
    except (OSError, UnicodeDecodeError):
        return False
    lines = text.splitlines()
    if (
        not text.endswith("\n")
        or len(lines) != 9
        or lines[:5]
        != [
            "# Lovable teacher prototype reference",
            "",
            "视觉参考，不连接鸭鸭日记本后端",
            "",
            "- Review date: 2026-08-29",
        ]
        or not lines[5].startswith("- Share URL: ")
        or not lines[6].startswith("- Source commit: ")
        or not lines[7].startswith("- Checklist result: ")
        or not lines[8].startswith("- Open observations: ")
    ):
        return False
    share_url = lines[5].removeprefix("- Share URL: ")
    source_commit = lines[6].removeprefix("- Source commit: ")
    checklist_result = lines[7].removeprefix("- Checklist result: ")
    observations = lines[8].removeprefix("- Open observations: ")
    try:
        parsed_url = urlsplit(share_url)
        port = parsed_url.port
    except ValueError:
        return False
    hostname = parsed_url.hostname
    return bool(
        share_url
        and share_url.strip() == share_url
        and parsed_url.scheme == "https"
        and hostname is not None
        and (hostname == "lovable.app" or hostname.endswith(".lovable.app"))
        and parsed_url.username is None
        and parsed_url.password is None
        and port in {None, 443}
        and not parsed_url.query
        and not parsed_url.fragment
        and re.fullmatch(r"[0-9a-f]{40}", source_commit) is not None
        and checklist_result in {"GO", "GO with changes"}
        and observations
        and observations.strip() == observations
        and len(observations) <= 500
    )


def _completed_lovable_state_is_valid(
    value: object, artifact_root: Path | None
) -> bool:
    if _completed_missing_lovable_state_is_valid(value):
        return True
    return bool(
        isinstance(value, Mapping)
        and set(value)
        == {
            "completion_or_scope_waiver",
            "connector_used",
            "project_status",
            "publish_performed",
            "source_uploaded",
            "status",
            "zero_credit_blocker",
        }
        and value.get("completion_or_scope_waiver") is True
        and value.get("connector_used") is False
        and value.get("project_status") == "PROVIDED_OR_WAIVED"
        and value.get("publish_performed") is False
        and value.get("source_uploaded") is False
        and value.get("status") == "PROVIDED_OR_WAIVED"
        and value.get("zero_credit_blocker") is None
        and _verified_lovable_reference_is_valid(artifact_root)
    )


def _validate_report_record_shape(
    record: Mapping[str, object],
    *,
    completed: bool,
    artifact_root: Path | None = None,
    trusted_tested_head: str | None = None,
) -> None:
    if not isinstance(record, Mapping):
        raise CliMisuseError("completed report JSON has the wrong schema")
    optional = {"resource_artifacts", "report_markdown"}
    expected = set(_REPORT_BASE_KEYS)
    if completed:
        expected.update(optional)
    elif not set(record).issubset(expected | optional):
        raise CliMisuseError("completed report JSON has the wrong schema")
    if (completed and set(record) != expected) or not _REPORT_BASE_KEYS.issubset(record):
        raise CliMisuseError("completed report JSON has the wrong schema")
    if (
        record.get("schema_version") != REPORT_SCHEMA_VERSION
        or record.get("runtime_versions") != FROZEN_RUNTIME_VERSION
        or record.get("supersedes") != "docs/acceptance-report.md"
        or record.get("pending_status")
        != "FINAL_GO_REQUIRES_HUMAN_RELEASE_DECISION"
        or not isinstance(record.get("run_id"), str)
        or not isinstance(record.get("generated_at"), str)
        or not isinstance(record.get("tested_head"), str)
        or re.fullmatch(r"[0-9a-f]{40}", record["tested_head"]) is None
        or (
            completed
            and (
                trusted_tested_head is None
                or record.get("tested_head") != trusted_tested_head
            )
        )
        or (completed and record.get("external_decision") is not None)
        or (
            completed
            and not _completed_report_provenance_is_valid(
                record.get("run_id"),
                record.get("generated_at"),
                artifact_root,
            )
        )
    ):
        raise CliMisuseError("completed report JSON has the wrong schema")

    decision = record.get("decision")
    if (
        not isinstance(decision, Mapping)
        or set(decision)
        != {"final_go", "outcome", "reasons", "runner_process_exit"}
        or decision.get("final_go") is not False
        or decision.get("outcome") not in {item.value for item in DecisionOutcome}
        or type(decision.get("runner_process_exit")) is not int
        or not isinstance(decision.get("reasons"), list)
    ):
        raise CliMisuseError("completed report decision is invalid")

    commands = record.get("commands")
    if not isinstance(commands, list):
        raise CliMisuseError("completed report commands are invalid")
    for order, command in enumerate(commands, start=1):
        if not isinstance(command, Mapping) or set(command) != _COMMAND_REPORT_KEYS:
            raise CliMisuseError("completed report command is invalid")
        counts = command.get("counts")
        if (
            command.get("order") != order
            or not isinstance(command.get("subcommand"), str)
            or not isinstance(command.get("argv"), list)
            or not command["argv"]
            or any(not isinstance(item, str) or not item for item in command["argv"])
            or command.get("conftest_mode") not in {item.value for item in ConftestMode}
            or type(command.get("timeout_seconds")) is not int
            or command["timeout_seconds"] <= 0
            or type(command.get("duration_seconds")) not in {int, float}
            or not math.isfinite(command["duration_seconds"])
            or command["duration_seconds"] < 0
            or not isinstance(counts, Mapping)
            or set(counts) != _COUNT_REPORT_KEYS
            or any(value is not None and (type(value) is not int or value < 0) for value in counts.values())
            or not isinstance(command.get("evidence_reason"), str)
            or type(command.get("evidence_valid")) is not bool
            or (
                command.get("evidence_sha256") is not None
                and not _valid_sha256(command["evidence_sha256"])
            )
            or not _valid_artifact_record(command.get("stdout"))
            or not _valid_artifact_record(command.get("stderr"))
            or (
                command.get("junit") is not None
                and not _valid_artifact_record(command["junit"])
            )
            or not isinstance(command.get("tripwire_events"), list)
            or tuple(command["tripwire_events"])
            != tuple(
                event_id
                for event_id in TRIPWIRE_EVENT_IDS
                if event_id in command["tripwire_events"]
            )
        ):
            raise CliMisuseError("completed report command is invalid")

    gates = record.get("gates")
    if (
        not isinstance(gates, list)
        or [gate.get("gate") for gate in gates if isinstance(gate, Mapping)]
        != list(GATE_TITLES)
        or any(
            not isinstance(gate, Mapping)
            or set(gate)
            != {"gate", "internal_evidence", "reasons", "selectors", "status", "title"}
            or gate.get("title") != GATE_TITLES[gate["gate"]]
            or gate.get("status") not in {item.value for item in GateStatus}
            or not isinstance(gate.get("reasons"), list)
            or not isinstance(gate.get("selectors"), list)
            or not isinstance(gate.get("internal_evidence"), list)
            for gate in gates
        )
    ):
        raise CliMisuseError("completed report gates are invalid")

    incidents = record.get("incidents")
    if incidents != _incident_report_rows():
        raise CliMisuseError("completed report incidents are invalid")

    if (
        record.get("viewport_contracts")
        != {
            "child": ["1024x576", "1280x720"],
            "teacher": ["1024x768", "1440x900"],
        }
        or not isinstance(record.get("focus_measurements"), list)
        or not isinstance(record.get("database_action_evidence"), list)
        or not isinstance(record.get("timeout_evidence"), list)
        or not isinstance(record.get("resources"), Mapping)
        or set(record["resources"]) != {"after", "before"}
        or not isinstance(record.get("tripwires"), Mapping)
        or set(record["tripwires"])
        != {"provider_tts_socket_context_worker"}
        or record["tripwires"]["provider_tts_socket_context_worker"]
        not in {"PASS", "FAIL", "NOT_PROVEN"}
        or not isinstance(record.get("suite_evidence"), Mapping)
        or not isinstance(record.get("internal_evidence"), list)
        or record.get("limitations") != list(FROZEN_LIMITATIONS)
    ):
        raise CliMisuseError("completed report evidence is invalid")

    lovable = record.get("lovable")
    if (
        not isinstance(lovable, Mapping)
        or set(lovable)
        != {
            "completion_or_scope_waiver",
            "connector_used",
            "project_status",
            "publish_performed",
            "source_uploaded",
            "status",
            "zero_credit_blocker",
        }
        or any(
            lovable.get(name) is not False
            for name in ("connector_used", "publish_performed", "source_uploaded")
        )
        or (
            completed
            and not _completed_lovable_state_is_valid(lovable, artifact_root)
        )
    ):
        raise CliMisuseError("completed report Lovable state is invalid")
    reviews = record.get("reviews")
    if (
        not isinstance(reviews, Mapping)
        or set(reviews) != {"p0", "p1", "p2", "status"}
        or reviews.get("status") != "PENDING_INDEPENDENT_EVIDENCE_REVIEW"
        or (
            completed
            and any(reviews.get(name) is not None for name in ("p0", "p1", "p2"))
        )
    ):
        raise CliMisuseError("completed report review state is invalid")
    if record.get("report_roles") != {
        "commit_a": "tested implementation",
        "commit_b": "evidence only",
    }:
        raise CliMisuseError("completed report commit roles are invalid")
    if completed and artifact_root is None:
        raise CliMisuseError("completed report artifact root is invalid")
    _validate_report_cross_fields(
        record, commands, artifact_root=artifact_root
    )
    if completed:
        suites = {
            command_id: _report_suite_evidence(value)
            for command_id, value in record["suite_evidence"].items()
        }
        internal = tuple(
            _report_internal_evidence(value)
            for value in record["internal_evidence"]
        )
        results = tuple(_report_command_result(command) for command in commands)
        if not _completed_report_execution_contract_is_valid(
            record=record,
            commands=commands,
            results=results,
            suites=suites,
            internal=internal,
            artifact_root=artifact_root,
        ):
            raise CliMisuseError("completed report execution contract is invalid")
    if "resource_artifacts" in record:
        artifacts = record["resource_artifacts"]
        if (
            not isinstance(artifacts, Mapping)
            or set(artifacts) != {"after", "before"}
            or any(not _valid_artifact_record(item) for item in artifacts.values())
        ):
            raise CliMisuseError("completed report resource artifacts are invalid")
    if "report_markdown" in record and not _valid_artifact_record(
        record["report_markdown"]
    ):
        raise CliMisuseError("completed report Markdown artifact is invalid")


def _artifact_error() -> NoReturn:
    raise CliMisuseError("completed report artifact tree is invalid")


def _verified_artifact_bytes(
    artifact_root: Path,
    descriptor: Mapping[str, object],
    *,
    expected_path: str,
) -> bytes:
    if descriptor.get("path") != expected_path:
        _artifact_error()
    relative = Path(expected_path)
    if (
        relative.is_absolute()
        or relative.as_posix() != expected_path
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        _artifact_error()
    candidate = artifact_root / relative
    try:
        details = candidate.lstat()
        if not stat.S_ISREG(details.st_mode) or stat.S_ISLNK(details.st_mode):
            _artifact_error()
        payload = candidate.read_bytes()
    except OSError:
        _artifact_error()
    if (
        len(payload) != descriptor.get("size")
        or hashlib.sha256(payload).hexdigest() != descriptor.get("sha256")
    ):
        _artifact_error()
    return payload


def _verify_completed_artifact_tree(
    record: Mapping[str, object], source_path: Path
) -> None:
    source = Path(source_path)
    artifact_root = source.parent
    try:
        source_details = source.lstat()
        root_details = artifact_root.lstat()
        command_details = (artifact_root / "commands").lstat()
    except OSError:
        _artifact_error()
    if (
        source.name != "report.json"
        or not stat.S_ISREG(source_details.st_mode)
        or stat.S_ISLNK(source_details.st_mode)
        or not stat.S_ISDIR(root_details.st_mode)
        or stat.S_ISLNK(root_details.st_mode)
        or not stat.S_ISDIR(command_details.st_mode)
        or stat.S_ISLNK(command_details.st_mode)
    ):
        _artifact_error()

    try:
        recorded_suites = {
            command_id: _report_suite_evidence(value)
            for command_id, value in record["suite_evidence"].items()
        }
    except (AttributeError, CliMisuseError, TypeError, ValueError):
        _artifact_error()

    expected_command_names: set[str] = set()
    verified_suite_commands: set[str] = set()
    for order, command in enumerate(record["commands"], start=1):
        command_id = command["subcommand"]
        prefix = f"{order:02d}-{command_id}"
        stream_payloads: dict[str, bytes] = {}
        for field, suffix in (("stdout", "stdout.log"), ("stderr", "stderr.log")):
            expected = f"commands/{prefix}.{suffix}"
            stream_payloads[field] = _verified_artifact_bytes(
                artifact_root, command[field], expected_path=expected
            )
            expected_command_names.add(Path(expected).name)
        junit = command["junit"]
        artifact_tripwire_events: tuple[str, ...] = ()
        if junit is not None:
            expected = f"commands/{prefix}.junit.xml"
            junit_payload = _verified_artifact_bytes(
                artifact_root, junit, expected_path=expected
            )
            artifact_evidence = parse_pytest_junit_bytes(
                junit_payload,
                stderr_payload=stream_payloads["stderr"],
                command_id=command_id,
                require_tripwire_auth=(
                    command["conftest_mode"] == ConftestMode.PROJECT.value
                ),
            )
            if artifact_evidence != recorded_suites.get(command_id):
                _artifact_error()
            artifact_tripwire_events = _tripwire_events_for_evidence(
                artifact_evidence
            )
            verified_suite_commands.add(command_id)
            expected_command_names.add(Path(expected).name)
        elif command_id in recorded_suites:
            artifact_evidence = parse_node_tap(stream_payloads["stdout"])
            if artifact_evidence != recorded_suites[command_id]:
                _artifact_error()
            artifact_tripwire_events = _tripwire_events_for_evidence(
                artifact_evidence
            )
            verified_suite_commands.add(command_id)
        if tuple(command["tripwire_events"]) != artifact_tripwire_events:
            _artifact_error()

    if verified_suite_commands != set(recorded_suites):
        _artifact_error()

    resource_artifacts = record["resource_artifacts"]
    for name in ("before", "after"):
        expected = f"resources.{name}.json"
        payload = _verified_artifact_bytes(
            artifact_root, resource_artifacts[name], expected_path=expected
        )
        if payload != canonical_json_bytes(record["resources"][name]):
            _artifact_error()
    _verified_artifact_bytes(
        artifact_root, record["report_markdown"], expected_path="report.md"
    )

    try:
        root_names = {entry.name for entry in os.scandir(artifact_root)}
        command_names = {
            entry.name for entry in os.scandir(artifact_root / "commands")
        }
    except OSError:
        _artifact_error()
    if root_names != {
        "commands",
        "report.json",
        "report.md",
        "resources.before.json",
        "resources.after.json",
    } or command_names != expected_command_names:
        _artifact_error()


def _markdown_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def render_report_markdown(record: Mapping[str, object]) -> str:
    """Render Markdown from a completed canonical record without backflow."""

    _validate_report_record_shape(record, completed=False)
    decision = record["decision"]
    commands = record["commands"]
    gates = record["gates"]
    lovable = record["lovable"]
    lines = [
        "# Interaction Acceptance Report",
        "",
        f"This report supersedes `{record['supersedes']}`.",
        "",
        f"- Run ID: `{record['run_id']}`",
        f"- Generated: `{record['generated_at']}`",
        f"- Tested implementation HEAD A: `{record['tested_head']}`",
        f"- Runner schema: `{record['schema_version']}`",
        f"- Runtime versions: `{_markdown_json(record['runtime_versions'])}`",
        f"- Outcome: `{decision['outcome']}` (process exit `{decision['runner_process_exit']}`)",
        f"- Final GO: `{_markdown_scalar(decision['final_go'])}`",
        f"- Pending status: `{record['pending_status']}`",
        "- Commit B role: evidence only; it is not the tested HEAD.",
        "",
        "## Commands",
        "",
        "| Order | Command | Conftest | Timeout | Duration | Termination | Outcome | Child exit | Runner exit | Counts | Evidence |",
        "|---:|---|---|---:|---:|---|---|---:|---:|---|---|",
    ]
    for command in commands:
        cleanup = ", ".join(command["cleanup_failures"]) or "none"
        lines.append(
            f"| {command['order']} | `{command['subcommand']}` | "
            f"`{command['conftest_mode']}` | `{command['timeout_seconds']}` | "
            f"`{command['duration_seconds']}` | `{command['termination']}` | "
            f"`{command['classified_outcome']}` | "
            f"`{_markdown_scalar(command['child_exit'])}` | "
            f"`{command['runner_process_exit']}` | "
            f"`{_markdown_json(command['counts'])}` | "
            f"`{command['evidence_reason']}` |"
        )
        lines.extend(
            [
                f"  - argv: `{_markdown_json(command['argv'])}`",
                f"  - logs: stdout `{command['stdout']['sha256']}`, stderr `{command['stderr']['sha256']}`; parsed evidence `{_markdown_scalar(command['evidence_sha256'])}`; cleanup `{cleanup}`; output complete `{_markdown_scalar(command['output_complete'])}`; reason `{command['reason']}`.",
            ]
        )
    lines.extend(
        [
            "",
            "## Gates",
            "",
            "| Gate | Title | Status | Reasons |",
            "|---:|---|---|---|",
        ]
    )
    for gate in gates:
        lines.append(
            f"| {gate['gate']} | {gate['title']} | `{gate['status']}` | "
            f"`{_markdown_json(gate['reasons'])}` |"
        )
        lines.append(f"  - selectors: `{_markdown_json(gate['selectors'])}`")
        lines.append(
            f"  - internal evidence: `{_markdown_json(gate['internal_evidence'])}`"
        )
    lines.extend(
        [
            "",
            "## Resources and tripwires",
            "",
            f"- Global before/after detail: `{_markdown_json(record['resources'])}`",
            f"- Tripwires: `{_markdown_json(record['tripwires'])}`",
            "",
            "## Viewport and structured browser evidence",
            "",
            f"- Viewport contracts: `{_markdown_json(record['viewport_contracts'])}`",
            f"- Focus measurements: `{_markdown_json(record['focus_measurements'])}`",
            f"- Database action evidence: `{_markdown_json(record['database_action_evidence'])}`",
            f"- Timeout evidence: `{_markdown_json(record['timeout_evidence'])}`",
            "",
            "## Historical incidents",
            "",
        ]
    )
    for incident in record["incidents"]:
        lines.extend(
            [
                f"### {incident['incident_id']}",
                "",
                f"- Facts: `{_markdown_json(incident['facts'])}`",
                f"- Corrective controls: `{_markdown_json(incident['corrective_controls'])}`",
                f"- Technical review: `{incident['technical_review_status']}`",
                f"- Release-owner acknowledgement: `{incident['release_owner_acknowledgement']}`",
                "",
            ]
        )
    lines.extend(
        [
            "## Human authority boundary",
            "",
            "All three immutable incidents still require an explicit user or release-owner disposition. A supplied decision artifact is unverified and cannot create final GO.",
            "",
            "## Lovable delivery",
            "",
            f"Status: `{lovable['status']}`; zero-credit blocker: `{_markdown_scalar(lovable['zero_credit_blocker'])}`; completion/waiver: `{_markdown_scalar(lovable['completion_or_scope_waiver'])}`; connector/publish/source-upload: `false/false/false`.",
            "",
            "## Independent review and limitations",
            "",
            f"- Review: `{_markdown_json(record['reviews'])}`",
            f"- Limitations: `{_markdown_json(record['limitations'])}`",
            "- Final GO remains a human release decision.",
        ]
    )
    return "\n".join(lines) + "\n"


def render_canonical_json(record: Mapping[str, object]) -> bytes:
    return canonical_json_bytes(record)


def render_markdown(record: Mapping[str, object]) -> str:
    return render_report_markdown(record)


def evaluate_technical_decision(inputs: DecisionInputs) -> DecisionResult:
    return decide_release(inputs)


GATE_TITLES = {
    1: "application DB unchanged",
    2: "version match and mismatch lock",
    3: "duplicate prevention",
    4: "failed utterance retained, no fake reply",
    5: "refresh recovery",
    6: "microphone denial help",
    7: "saved child exit, tracked analysis",
    8: "complete review round-trip",
    9: "review identity/time/ID/status",
    10: "5-second TTS fallback",
    11: "roster replay",
    12: "undoable deactivation",
    13: "keyboard core flows",
    14: "real interaction/fault/DB assertions",
}

_SELECTOR_MANIFEST_TEXT = r"""backend | ^test_pytest_application_logging_uses_only_the_disposable_runtime_file$ | 1 | 1,14
backend | ^test_pytest_subprocess_does_not_change_application_db$ | 1 | 1
backend | ^test_review_atomic_pytest_subprocess_does_not_change_the_real_application_log$ | 1 | 1
backend | ^test_health_returns_frozen_runtime_versions$ | 1 | 2
backend | ^test_version_manifest_is_no_store$ | 1 | 2
backend | ^test_teacher_navigation_is_blocked_until_runtime_ready$ | 1 | 2
backend | ^test_teacher_navigation_requires_both_runtime_and_authentication_and_can_relock$ | 1 | 2
backend | ^test_chat_writes_one_pair_after_ai_success$ | 1 | 3
backend | ^test_duplicate_request_replays_stored_pair_without_a_second_ai_call$ | 1 | 3
backend | ^test_internal_chat_fault_marks_current_claim_failed_and_allows_retry\[(commit|context)\]$ | 2 | 3,4,14
backend | ^test_fixed_max_round_commit_fault_marks_current_claim_failed_and_allows_retry$ | 1 | 3,7,14
backend | ^test_complete_replays_the_frozen_snapshot_without_a_second_job$ | 1 | 3,7
backend | ^test_completion_write_failure_rolls_back_the_job_and_end_state\[(commit|flush)\]$ | 2 | 3,7,14
backend | ^test_process_builds_the_frozen_input_outside_a_database_session_and_projects_once$ | 1 | 7
backend | ^test_restart_recovers_only_expired_processing_jobs_and_preserves_attempts$ | 1 | 7
backend | ^test_failure_uses_bounded_backoff_then_a_sanitized_terminal_state\[(1-pending-1|2-pending-5|3-failed-0)\]$ | 3 | 7,14
backend | ^test_teacher_retry_requires_session_and_reuses_the_failed_job$ | 1 | 7
backend | ^test_teacher_retry_has_frozen_pending_and_terminal_state_contracts\[(pending-2-200-None|processing-1-409-ANALYSIS_IN_PROGRESS|succeeded-1-409-ANALYSIS_ALREADY_SUCCEEDED)\]$ | 3 | 7
backend | ^test_lifespan_uses_the_injected_single_worker_for_health_and_teardown$ | 1 | 7
backend | ^test_auto_generates_five_rotating_weekday_pairs_and_replays_first_snapshot$ | 1 | 3,11
backend | ^test_draft_review_replaces_the_full_document_and_refetches_identically$ | 1 | 3,8
backend | ^test_confirm_requires_complete_reasoned_scores_then_leaves_every_queue$ | 1 | 8
backend | ^test_reliable_end_to_end_flow$ | 1 | 7,8,14
backend | ^test_teacher_queue_uses_job_matrix_frozen_counts_sort_and_historical_child$ | 1 | 9
backend | ^test_succeeded_detail_has_one_complete_ordered_document_or_a_stable_corruption_error$ | 1 | 9
backend | ^test_child_deactivation_preserves_history_and_reactivation_restores_today_visibility$ | 1 | 12
backend | ^test_resource_state_routes_are_locked_and_hard_delete_is_an_auth_first_tombstone$ | 1 | 12
backend | ^test_hard_delete_tombstones_have_stable_missing_codes_and_no_target_lookup_or_write$ | 1 | 12
backend | ^test_resource_route_inventory_flattens_direct_and_included_routes_and_rejects_legacy_parameter_aliases$ | 1 | 12
backend | ^test_teacher_composes_safe_management_and_reports_without_legacy_routes$ | 1 | 12
shared_node | ^version mismatch enters maintenance before any business request$ | 1 | 2
shared_node | ^bootstrapVersionGate and ready share one pending successful gate promise$ | 1 | 2
shared_node | ^caller abort stays AbortError while timeout becomes REQUEST_TIMEOUT$ | 1 | 3,14
child_node | ^unbound and matching bound drafts become child-retryable without changing their request identity$ | 1 | 5
child_node | ^a COMPLETE_FAILED recovery reload returns to saving_conversation at the same remote boundary$ | 1 | 5,7
child_node | ^pending completion keeps the remote completion boundary and never reopens chat$ | 1 | 5,7
child_node | ^ended chat saved through the machine restores only the completion path$ | 1 | 5,7
child_node | ^uses the exact 1500 ms silence boundary and replaces one live timer on results and speech end$ | 1 | 10
child_node | ^a timeout before deferred loader invocation falls back safely and ignores its late blob$ | 1 | 10
teacher_node | ^Today validates every queue DTO shape, fixed labels, and queue-specific combinations$ | 1 | 7
browser | ^test_child_health_validation_fallback_preserves_foundation_maintenance\[(1024x576|1280x720)\]$ | 2 | 2
browser | ^test_teacher_locked_bootstrap_makes_only_runtime_and_auth_requests\[(1024x768|1440x900)\]$ | 2 | 2
browser | ^test_teacher_runtime_failure_keeps_maintenance_and_makes_zero_auth_or_business_requests\[(1024x768|1440x900)\]$ | 2 | 2
browser | ^test_teacher_auth_status_failure_is_safe_and_makes_zero_business_requests\[(1024x768|1440x900)\]$ | 2 | 2
browser | ^test_chat_retryable_fault_reuses_persisted_request_id_once\[(1024x576|1280x720)\]$ | 2 | 3
browser | ^test_first_chat_timeout_retains_draft_and_reuses_request_id_once\[(1024x576|1280x720)\]$ | 2 | 3,4,14
browser | ^test_chat_fault_matrix_retains_draft_without_success_copy\[(http_500|non_json|offline)-(1024x576|1280x720)\]$ | 6 | 3,4,14
browser | ^test_completion_delay_is_single_flight_and_saves_once\[(1024x576|1280x720)\]$ | 2 | 3,7,14
browser | ^test_teacher_review_put_timeout_preserves_dirty_values_and_restores_focus\[(seed_review_timeout_1024|review_timeout_1440)\]$ | 2 | 3,14
browser | ^test_teacher_review_delayed_save_is_single_flight_and_disables_every_editor_control\[(1024x768|1440x900)\]$ | 2 | 3,14
browser | ^test_teacher_resource_state_delay_is_single_flight\[(seed_child_deactivate_1024|child_reactivate_1024|duck_deactivate_1024|duck_reactivate_1024|(child|duck)_(deactivate|reactivate)_1440)\]$ | 8 | 3,12,14
browser | ^test_teacher_roster_delay_is_single_flight\[(seed_daily_1024|auto_1024|daily_1440|auto_1440)\]$ | 4 | 3,11,14
browser | ^test_teacher_roster_settled_faults_preserve_snapshot_and_request_id\[(seed_daily_json_500_1024|auto_json_500_1024|(daily|auto)_(html_502|offline)_1024|(daily|auto)_(json_500|html_502|offline)_1440)\]$ | 12 | 3,11,14
browser | ^test_reload_during_submit_restores_same_draft_and_ignores_old_response\[(1024x576|1280x720)\]$ | 2 | 5
browser | ^test_pagehide_destroy_makes_held_callback_inert\[(1024x576|1280x720)\]$ | 2 | 5,14
browser | ^test_microphone_denial_focuses_visible_teacher_help_then_opens_dialog\[(1024x576|1280x720)\]$ | 2 | 6
browser | ^test_completion_replay_reaches_completed_once_after_strict_save\[(1024x576|1280x720)\]$ | 2 | 3,7
browser | ^test_child_core_flow_is_page_keyboard_only_and_saves_once\[(1024x576|1280x720)\]$ | 2 | 7,13,14
browser | ^test_teacher_today_renders_pending_processing_and_failed_rows_with_retry_boundaries\[(1024x768|1440x900)\]$ | 2 | 7,14
browser | ^test_teacher_today_each_panel_has_its_fixed_empty_state\[(pending|processing|failed)-(1024x768|1440x900)\]$ | 6 | 7
browser | ^test_teacher_today_analysis_retry_is_single_flight_and_refreshes_three_queues_in_order\[(accepted|replayed)-(1024x768|1440x900)\]$ | 4 | 3,7,14
browser | ^test_teacher_today_analysis_retry_failures_restore_only_the_row_action_with_safe_copy\[(mismatch|malformed|401|404|409|500|non-json)-(1024x768|1440x900)\]$ | 14 | 7,14
browser | ^test_teacher_today_analysis_retry_offline_is_single_flight_until_transport_rejects\[(1024x768|1440x900)\]$ | 2 | 3,7,14
browser | ^test_teacher_review_editor_saves_the_complete_normalized_draft_and_refreshes_only_queue\[(1024x768|1440x900)\]$ | 2 | 8
browser | ^test_teacher_review_complete_confirm_uses_confirm_action_and_removes_the_pending_row\[(1024x768|1440x900)\]$ | 2 | 8
browser | ^test_teacher_review_queue_and_detail_show_identity_time_id_and_status\[(1024x768|1440x900)\]$ | 2 | 9
browser | ^test_tts_cold_start_uses_reachable_five_second_fallback\[(1024x576|1280x720)\]$ | 2 | 10,14
browser | ^test_tts_faults_settle_and_do_not_block_completion\[(edge_http_500|edge_non_json|edge_offline|play_rejected|audio_error|browser_speech_error)-(1024x576|1280x720)\]$ | 12 | 10,14
browser | ^test_child_deactivation_uses_named_dialog_and_real_undo\[(1024x768|1440x900)\]$ | 2 | 12
browser | ^test_children_management_is_labeled_strict_and_never_sends_delete\[(1024x768|1440x900)\]$ | 2 | 12
browser | ^test_teacher_management_exposes_reversible_state_without_delete\[(1024x768|1440x900)\]$ | 2 | 12
browser | ^test_teacher_resource_state_settled_faults_never_claim_success\[(seed_child_deactivate_json_500_1024|child_reactivate_json_500_1024|duck_deactivate_json_500_1024|duck_reactivate_json_500_1024|(child|duck)_(deactivate|reactivate)_(html_502|offline)_1024|(child|duck)_(deactivate|reactivate)_(json_500|html_502|offline)_1440)\]$ | 24 | 12,14
browser | ^test_manual_space_stop_requires_one_explicit_end\[(1024x576|1280x720)\]$ | 2 | 13
browser | ^test_space_is_single_action_for_native_and_global_paths\[(1024x576|1280x720)\]$ | 2 | 13
browser | ^test_keyboard_focus_visible_uses_start_to_ready_flow\[(1024x576|1280x720)\]$ | 2 | 13
browser | ^test_fault_recovery_preserves_accessibility_and_projection_constraints\[(chat_retryable|completion_failure)-(1024x576|1280x720)\]$ | 4 | 13,14
browser | ^test_teacher_complete_review_flow_is_page_keyboard_only\[(seed_keyboard_review_1024|keyboard_review_1440)\]$ | 2 | 13
browser | ^test_teacher_dirty_review_dialog_is_named_keyboard_operable_and_restores_focus\[(seed_dirty_dialog_1024|dirty_dialog_1440)\]$ | 2 | 13
browser | ^test_teacher_authenticated_routes_have_frozen_accessibility_structure\[(seed_a11y_today_1024|a11y_(children|ducks|roster|review|growth|search)_1024|a11y_(today|children|ducks|roster|review|growth|search)_1440)\]$ | 14 | 13
browser | ^test_release_focus_indicator_meets_three_to_one\[(1024x768|1440x900)\]$ | 2 | 13
browser | ^test_completion_fault_matrix_never_claims_saved_copy\[(http_500|non_json|offline|boundary_mismatch)-(1024x576|1280x720)\]$ | 8 | 3,14
browser | ^test_teacher_representative_read_validators_cover_missing_transport_faults\[(seed_today_roster_html_502_1024|today_roster_offline_1024|review_pending_html_502_1024|review_pending_offline_1024|today_roster_html_502_1440|today_roster_offline_1440|review_pending_html_502_1440|review_pending_offline_1440)\]$ | 8 | 14
browser | ^test_teacher_review_save_failures_keep_exact_values_dirty_and_never_refresh\[(server|non-json|offline)-\\u4fdd\\u5b58\\u5931\\u8d25\\uff0c\\u8bf7\\u7a0d\\u540e\\u91cd\\u8bd5\\u3002-(1024x768|1440x900)\]$ | 6 | 14
browser | ^test_child_server_import_preflight_blocks_provider_env$ | 1 | 14
browser | ^test_main_import_filehandler_is_redirected_from_real_log$ | 1 | 1,14
browser | ^test_edge_tts_fake_stream_trips_before_network$ | 1 | 14
browser | ^test_nonstarting_worker_has_no_start_side_effect$ | 1 | 14
browser | ^test_browser_subprocess_environment_is_minimal$ | 1 | 14
browser | ^test_real_resource_snapshots_are_read_only$ | 1 | 1,14
browser | ^test_socket_guard_blocks_non_loopback$ | 1 | 14
browser | ^test_fixture_teardown_closes_before_process_assertions$ | 1 | 14
browser | ^test_context_loopback_policy_allows_only_exact_origin\[(data:text/plain,synthetic-False|http://127\.0\.0\.1/-False|http://127\.0\.0\.1:43123/-True|http://127\.0\.0\.1:43123/api/health\?x=1-True|http://127\.0\.0\.1:43124/-False|http://127\.0\.0\.1:not-a-port/-False|http://\[::1\]:43123/-False|http://example\.invalid:43123/-False|http://localhost:43123/-False|http://user:pass@127\.0\.0\.1:43123/-False|https://127\.0\.0\.1:43123/-False)\]$ | 11 | 14
browser | ^test_loopback_server_uses_disposable_resources$ | 1 | 1,14
browser | ^test_child_page_registers_fail_closed_business_routes_before_navigation$ | 1 | 14
browser | ^test_page_specific_routes_cannot_widen_loopback_policy$ | 1 | 14
browser | ^test_browser_parent_logging_is_redirected_from_real_application_log$ | 1 | 1,14
browser | ^test_release_teacher_action_persists_to_disposable_sqlite\[(1024x768|1440x900)\]$ | 2 | 14
backend | ^test_runtime_context_is_public_static_exact_and_reads_date_once$ | 1 | 2,14
backend | ^test_runtime_context_rejects_every_query_shape_before_reading_the_clock$ | 1 | 2,14
backend | ^test_business_today_reads_the_provider_exactly_once$ | 1 | 2,14
backend | ^test_upload_authentication_precedes_multipart_parsing_content_length_and_writes$ | 1 | 3,14
backend | ^test_unauthenticated_asgi_request_reads_zero_body_bytes$ | 1 | 3,14
backend | ^test_authenticated_(chunked_multipart_total_budget_stops_before_oversize_epilogue|chunked_oversize_preamble_hits_total_budget_and_stops_receive|repeated_file_parts_stop_before_receiving_second_payload)$ | 3 | 3,14
backend | ^test_valid_uploads_have_exact_dto_uuid_metadata_and_static_webp\[(png|jpeg|webp)\]$ | 3 | 3,14
backend | ^test_(atomic_publish_never_overwrites_boundary_attacker_and_retries_uuid|concurrent_fixed_uuid_collision_never_overwrites_or_deletes_winner)$ | 2 | 3,14
backend | ^test_(store_holds_trusted_parent_fd_when_root_parent_is_swapped_to_symlink|load_holds_trusted_parent_fd_when_root_parent_is_swapped_to_symlink|reader_holds_root_lease_through_stored_content_validation|invalidating_waiter_never_closes_a_root_held_by_an_active_reader)$ | 4 | 1,14
backend | ^test_public_get_is_exact_webp_with_cache_nosniff_etag_and_no_auth$ | 1 | 14
backend | ^test_public_head_conditional_get_and_unsupported_range_have_explicit_contract$ | 1 | 14
backend | ^test_resource_avatar_reference_requires_safe_row_and_file_before_any_write$ | 1 | 3,12,14
backend | ^test_valid_reference_replacement_and_null_removal_never_delete_old_media$ | 1 | 3,12,14
backend | ^test_(child|duck)_mutation_normalizes_the_exact_client_owned_fields$ | 2 | 3,12,14
backend | ^test_create_retry_replays_exact_response_and_changed_payload_conflicts\[(child|duck)\]$ | 2 | 3,14
backend | ^test_service_concurrent_same_request_creates_one_child_and_two_exact_responses$ | 1 | 3,14
backend | ^test_monthly_route_canonicalizes_dates_pairs_and_uses_one_clock_sample$ | 1 | 3,11,14
backend | ^test_monthly_accepts_31_calendar_dates_and_rejects_every_structural_boundary$ | 1 | 11,14
backend | ^test_monthly_any_occupied_date_conflicts_without_changing_the_batch_or_ledger$ | 1 | 3,11,14
backend | ^test_monthly_replay_uses_the_original_snapshot_after_child_deactivation$ | 1 | 3,11,14
backend | ^test_concurrent_monthly_distinct_uuids_same_date_leave_exactly_one_pair$ | 1 | 3,11,14
backend | ^test_weekly_service_uses_conversation_calendar_window_and_global_review_backlog$ | 1 | 7,14
backend | ^test_weekly_service_returns_the_exact_zero_shape$ | 1 | 7,14
backend | ^test_weekly_service_fails_the_whole_response_for_global_integrity_corruption\[(conversation_status|conversation_end_reason|conversation_pending_end_reason|conversation_invalid_date|conversation_year_zero|ended_without_end_reason|ended_without_timestamp|ended_without_boundary|active_with_ended_boundary|job_status|job_boundary|job_for_active_conversation|assessment_status|assessment_child|confirmed_without_succeeded)\]$ | 15 | 7,14
backend | ^test_weekly_service_uses_the_same_two_sql_statements_for_one_or_one_hundred_rows\[(1|100)\]$ | 2 | 7,14
backend | ^test_weekly_route_authenticates_before_reading_even_an_invalid_raw_query$ | 1 | 7,14
backend | ^test_weekly_route_rejects_noncanonical_or_non_monday_raw_query_before_any_sql\[(unknown=2026-08-31|week_start=2026-08-31&week_start=2026-08-31|week_start=|=2026-08-31|week_start|week%5Fstart=2026-08-31|week_start=2026%2D08%2D31|week_start=%FF|week_start=2026-02-30|week_start=2026-8-31|week_start=2026-09-01|week_start=9999-12-27)\]$ | 12 | 7,14
backend | ^test_weekly_route_without_query_samples_the_business_clock_once$ | 1 | 7,14
backend | ^test_weekly_route_explicit_monday_never_reads_the_now_provider$ | 1 | 7,14
backend | ^test_search_static_route_authenticates_before_body_or_query_validation$ | 1 | 14
backend | ^test_search_keyword_is_literal_frozen_role_bounded_and_preserves_projection_counts$ | 1 | 8,9,14
backend | ^test_search_cursor_is_canonical_keyset_and_snapshot_excludes_new_inserts\[(completed_desc-descending|completed_asc-ascending)\]$ | 2 | 8,9,14
backend | ^test_search_cursor_fingerprint_ignores_limit_and_array_order_but_binds_filters$ | 1 | 8,9,14
backend | ^test_search_fails_whole_page_for_selected_projection_corruption$ | 1 | 8,9,14
backend | ^test_search_statement_budget_is_fixed_for_one_or_fifty_rows$ | 1 | 8,9,14
backend | ^test_fixed_anchor_seed_has_exact_graph_and_stable_logical_hashes$ | 1 | 1,14
backend | ^test_seeded_reports_growth_search_and_worker_are_demo_ready$ | 1 | 7,8,9,14
backend | ^test_seed_without_force_rejects_every_existing_resource_before_install\[(database|wal|shm|media|log)\]$ | 5 | 1,14
backend | ^test_all_demo_rows_roll_back_when_a_late_insert_fails$ | 1 | 1,14
backend | ^test_concurrent_seed_attempts_have_exactly_one_success$ | 1 | 1,14
backend | ^test_full_demo_cli_requires_explicit_targets_and_prints_hashes$ | 1 | 1,14
browser | ^test_avatar_preview_upload_retry_save_and_remove_are_ordered_and_retained\[(1024x576|1280x720)\]$ | 2 | 3,12,14
browser | ^test_monthly_roster_defaults_rows_and_retries_only_the_unchanged_snapshot\[(1024x768|1440x900)\]$ | 2 | 3,11,14
browser | ^test_monthly_conflict_requires_new_overwrite_id_then_reuses_it_on_failure\[(1024x768|1440x900)\]$ | 2 | 3,11,14
browser | ^test_teacher_today_renders_exact_week_range_and_five_weekly_metrics\[(1024x768|1440x900)\]$ | 2 | 7,14
browser | ^test_teacher_today_weekly_metrics_have_an_explicit_all_zero_state\[(1024x768|1440x900)\]$ | 2 | 7,14
browser | ^test_teacher_today_weekly_failure_retry_is_scoped_and_touch_sized\[(1024x768|1440x900)\]$ | 2 | 7,14
browser | ^test_search_filters_private_post_and_review_anchor_are_canonical\[(1024x768|1440x900)\]$ | 2 | 8,9,14
browser | ^test_search_append_failure_retains_rows_and_retries_frozen_body\[(http|parse)-(1024x768|1440x900)\]$ | 4 | 8,9,14
browser | ^test_search_new_search_supersedes_abort_insensitive_pending_append\[(resolve|reject)\]$ | 2 | 8,9,14
browser | ^test_search_held_first_page_exposes_busy_loading_then_polite_empty$ | 1 | 8,9,14
browser | ^test_roster_panel_and_pet_orb_are_safe_visible_and_non_overlapping\[avatar_cards-(1024x576|1280x720)\]$ | 2 | 14
browser | ^test_release_monthly_roster_dialog_keeps_fixed_actions_and_scrollable_rows\[(1024x768|1440x900)\]$ | 2 | 11,14
browser | ^test_release_search_filters_results_and_focus_stay_in_bounds\[(1024x768|1440x900)\]$ | 2 | 8,9,14
browser | ^test_release_today_weekly_metrics_retry_and_grid_stay_in_bounds\[(1024x768|1440x900)\]$ | 2 | 7,14
browser | ^test_release_avatar_upload_and_fallback_stay_in_bounds\[(1024x768|1440x900)\]$ | 2 | 12,14
"""


def _parse_selector_manifest(text: str) -> tuple[SelectorRequirement, ...]:
    requirements = []
    for line in text.splitlines():
        command_id, node_pattern, expected_count, gates = line.split(" | ")
        requirements.append(
            SelectorRequirement(
                command_id=command_id,
                node_pattern=node_pattern,
                expected_count=int(expected_count),
                gates=tuple(int(gate) for gate in gates.split(",")),
            )
        )
    return tuple(requirements)


SELECTOR_MANIFEST = _parse_selector_manifest(_SELECTOR_MANIFEST_TEXT)
SELECTOR_TO_GATES = {
    (row.command_id, row.node_pattern): row.gates for row in SELECTOR_MANIFEST
}
INTERNAL_EVIDENCE_REQUIREMENTS = (
    InternalEvidenceRequirement(
        "resource",
        "global_and_per_command_logical_and_physical_equality",
        1,
        (1, 14),
    ),
    InternalEvidenceRequirement(
        "resource", "inherited_user_paths_and_git_porcelain_equal", 1, (1, 14)
    ),
    InternalEvidenceRequirement(
        "runtime", "tested_head_api_schema_and_release_versions_exact", 1, (2, 14)
    ),
    InternalEvidenceRequirement(
        "tripwire",
        "provider_tts_socket_context_and_worker_tripwires_clean",
        1,
        (14,),
    ),
    InternalEvidenceRequirement(
        "browser_db",
        "exact_fixture_path_and_read_only_zero_to_one_business_row",
        1,
        (14,),
    ),
)


def evaluate_gates(
    results: tuple[CommandResult, ...] | tuple[()],
    resources: object | None,
    evidence_map: EvidenceMap,
) -> tuple[GateResult, ...]:
    """Fail closed unless every exact selector and internal fact is fresh and true."""

    del resources
    global_reasons: list[str] = []
    known_commands = {row.command_id for row in SELECTOR_MANIFEST}
    row_counts: dict[tuple[str, str], int] = {
        (row.command_id, row.node_pattern): 0 for row in SELECTOR_MANIFEST
    }

    for command_id, suite in evidence_map.suites.items():
        state_valid = _suite_evidence_state_is_valid(suite)
        if command_id not in known_commands or not state_valid or not suite.valid:
            global_reasons.append(f"INVALID_SUITE:{command_id}")
        node_ids = suite.node_ids if state_valid else ()
        if len(set(node_ids)) != len(node_ids):
            global_reasons.append(f"DUPLICATE_NODE:{command_id}")
        for node_id in node_ids:
            matches = tuple(
                row
                for row in SELECTOR_MANIFEST
                if row.command_id == command_id
                and re.fullmatch(row.node_pattern, node_id)
            )
            if not matches:
                continue
            if len(matches) != 1:
                global_reasons.append(f"AMBIGUOUS_OR_UNKNOWN:{command_id}:{node_id}")
                continue
            matched = matches[0]
            key = (matched.command_id, matched.node_pattern)
            row_counts[key] += 1

    if any(
        result.classified_outcome is not ClassifiedOutcome.SUCCESS for result in results
    ):
        global_reasons.append("COMMAND_RESULT_NOT_SUCCESS")

    internal_counts: dict[tuple[str, str], list[InternalEvidence]] = {}
    known_internal = {
        (item.source, item.evidence_id) for item in INTERNAL_EVIDENCE_REQUIREMENTS
    }
    for item in evidence_map.internal:
        key = (item.source, item.evidence_id)
        internal_counts.setdefault(key, []).append(item)
        if key not in known_internal:
            global_reasons.append(f"UNKNOWN_INTERNAL:{item.source}:{item.evidence_id}")

    gate_results = []
    for gate, title in GATE_TITLES.items():
        reasons = list(global_reasons)
        for row in SELECTOR_MANIFEST:
            if gate not in row.gates:
                continue
            actual_count = row_counts[(row.command_id, row.node_pattern)]
            if actual_count != row.expected_count:
                reasons.append(
                    f"SELECTOR_COUNT:{row.command_id}:{row.node_pattern}:{actual_count}"
                )
        for requirement in INTERNAL_EVIDENCE_REQUIREMENTS:
            if gate not in requirement.gates:
                continue
            matches = internal_counts.get(
                (requirement.source, requirement.evidence_id), []
            )
            if (
                len(matches) != requirement.expected_count
                or any(
                    not item.passed or not item.fresh or not item.valid
                    for item in matches
                )
            ):
                reasons.append(
                    f"INTERNAL:{requirement.source}:{requirement.evidence_id}"
                )
        gate_results.append(
            GateResult(
                gate=gate,
                title=title,
                status=GateStatus.PASS if not reasons else GateStatus.BLOCKED,
                reasons=tuple(dict.fromkeys(reasons)),
            )
        )
    return tuple(gate_results)


@dataclass(frozen=True, slots=True)
class CommandResult:
    subcommand: str
    child_started: bool
    child_exit: int | None
    termination: Termination
    output_complete: bool | None
    residual_group_observed: bool
    cleanup_failures: tuple[CleanupFailure, ...]
    classified_outcome: ClassifiedOutcome
    reason: str
    before_snapshot: object | None
    after_snapshot: object | None
    stdout: bytes = b""
    stderr: bytes = b""
    duration_seconds: float = 0.0

    def __post_init__(self) -> None:
        def invalid() -> None:
            raise ValueError("invalid command result state")

        if (
            not isinstance(self.subcommand, str)
            or not self.subcommand
            or type(self.child_started) is not bool
            or (
                self.child_exit is not None
                and (type(self.child_exit) is not int)
            )
            or not isinstance(self.termination, Termination)
            or (
                self.output_complete is not None
                and type(self.output_complete) is not bool
            )
            or type(self.residual_group_observed) is not bool
            or not isinstance(self.cleanup_failures, tuple)
            or any(
                not isinstance(item, CleanupFailure)
                for item in self.cleanup_failures
            )
            or not isinstance(self.classified_outcome, ClassifiedOutcome)
            or not isinstance(self.reason, str)
            or not self.reason
            or not isinstance(self.stdout, bytes)
            or not isinstance(self.stderr, bytes)
            or type(self.duration_seconds) not in {int, float}
            or not math.isfinite(self.duration_seconds)
            or self.duration_seconds < 0
        ):
            invalid()

        canonical_cleanup = tuple(
            item for item in CleanupFailure if item in self.cleanup_failures
        )
        if self.cleanup_failures != canonical_cleanup:
            invalid()

        before = self.before_snapshot
        after = self.after_snapshot
        resources_drifted = after is not None and not _snapshots_are_unchanged(
            before, after
        )

        if before is None:
            if after is not None:
                invalid()
            exact_no_baseline = (
                not self.child_started
                and self.child_exit is None
                and self.termination is Termination.NOT_STARTED
                and self.output_complete is None
                and not self.residual_group_observed
                and not self.cleanup_failures
            )
            if not exact_no_baseline:
                invalid()
            if (
                self.classified_outcome,
                self.reason,
            ) not in {
                (ClassifiedOutcome.CLI_MISUSE, "CLI_MISUSE"),
                (
                    ClassifiedOutcome.SAFETY_FAILURE,
                    "RESOURCE_BASELINE_UNAVAILABLE",
                ),
            }:
                invalid()
            return

        if not self.child_started:
            if (
                self.child_exit is not None
                or self.output_complete is not None
                or self.residual_group_observed
                or self.cleanup_failures
                or after is None
                or self.termination
                not in {Termination.NOT_STARTED, Termination.SPAWN_FAILED}
            ):
                invalid()
            if self.classified_outcome is ClassifiedOutcome.SAFETY_FAILURE:
                if self.reason != "RESOURCE_DRIFT" or not resources_drifted:
                    invalid()
            elif self.classified_outcome is ClassifiedOutcome.TECHNICAL_FAILURE:
                if resources_drifted:
                    invalid()
                if (
                    self.termination is Termination.SPAWN_FAILED
                    and self.reason != "SPAWN_FAILED"
                ):
                    invalid()
            else:
                invalid()
            return

        if self.termination in {Termination.NOT_STARTED, Termination.SPAWN_FAILED}:
            invalid()
        if self.output_complete is None:
            invalid()

        if not self.output_complete:
            if (
                after is not None
                or not self.cleanup_failures
                or self.classified_outcome is not ClassifiedOutcome.SAFETY_FAILURE
                or self.reason != "PROCESS_CLEANUP_INCOMPLETE"
            ):
                invalid()
            leader_unreaped = CleanupFailure.LEADER_UNREAPED in self.cleanup_failures
            if (self.child_exit is None) is not leader_unreaped:
                invalid()
            if self.termination is Termination.TIMED_OUT:
                if self.residual_group_observed:
                    invalid()
            elif self.termination is Termination.EXITED:
                if (
                    not self.residual_group_observed
                    or self.child_exit is None
                    or self.child_exit < 0
                ):
                    invalid()
            elif self.termination is Termination.SIGNALED:
                if (
                    not self.residual_group_observed
                    or self.child_exit is None
                    or self.child_exit >= 0
                ):
                    invalid()
            else:
                invalid()
            return

        if after is None or self.cleanup_failures or self.child_exit is None:
            invalid()

        if self.residual_group_observed:
            if (
                self.termination not in {Termination.EXITED, Termination.SIGNALED}
                or self.classified_outcome is not ClassifiedOutcome.SAFETY_FAILURE
            ):
                invalid()
            if (
                self.termination is Termination.EXITED
                and self.child_exit < 0
            ) or (
                self.termination is Termination.SIGNALED
                and self.child_exit >= 0
            ):
                invalid()
            expected_reason = (
                "RESOURCE_DRIFT"
                if resources_drifted
                else "RESIDUAL_PROCESS_GROUP"
            )
            if self.reason != expected_reason:
                invalid()
            return

        if self.termination is Termination.EXITED:
            if self.child_exit < 0:
                invalid()
            if self.classified_outcome is ClassifiedOutcome.SAFETY_FAILURE:
                expected_reason = (
                    "RESOURCE_DRIFT" if resources_drifted else "TRIPWIRE_FAILURE"
                )
                if self.reason != expected_reason:
                    invalid()
            elif self.child_exit == 0:
                if self.classified_outcome is ClassifiedOutcome.SUCCESS:
                    if self.reason != "SUCCESS" or resources_drifted:
                        invalid()
                elif self.classified_outcome is ClassifiedOutcome.TECHNICAL_FAILURE:
                    if resources_drifted or not (
                        self.reason.startswith("INVALID_EVIDENCE:")
                        or self.reason == "ARTIFACT_WRITE_FAILED"
                    ):
                        invalid()
                else:
                    invalid()
            elif self.classified_outcome is ClassifiedOutcome.CHILD_NONZERO:
                if self.reason != "CHILD_NONZERO" or resources_drifted:
                    invalid()
            elif self.classified_outcome is ClassifiedOutcome.TECHNICAL_FAILURE:
                if self.reason != "ARTIFACT_WRITE_FAILED" or resources_drifted:
                    invalid()
            else:
                invalid()
            return

        if self.termination is Termination.SIGNALED:
            if self.child_exit >= 0:
                invalid()
            if self.classified_outcome is ClassifiedOutcome.SAFETY_FAILURE:
                expected_reason = (
                    "RESOURCE_DRIFT" if resources_drifted else "TRIPWIRE_FAILURE"
                )
                if self.reason != expected_reason:
                    invalid()
            elif self.classified_outcome is ClassifiedOutcome.TECHNICAL_FAILURE:
                if resources_drifted or self.reason not in {
                    "CHILD_SIGNALED",
                    "ARTIFACT_WRITE_FAILED",
                }:
                    invalid()
            else:
                invalid()
            return

        if self.termination is Termination.TIMED_OUT:
            if self.classified_outcome is ClassifiedOutcome.SAFETY_FAILURE:
                expected_reason = (
                    "RESOURCE_DRIFT" if resources_drifted else "TRIPWIRE_FAILURE"
                )
                if self.reason != expected_reason:
                    invalid()
            elif self.classified_outcome is ClassifiedOutcome.TECHNICAL_FAILURE:
                if resources_drifted or self.reason not in {
                    "COMMAND_TIMEOUT",
                    "ARTIFACT_WRITE_FAILED",
                }:
                    invalid()
            else:
                invalid()
            return

        invalid()


def _empty_suite_evidence(reason: str) -> SuiteEvidence:
    return SuiteEvidence(
        valid=False,
        total=0,
        passed=0,
        failures=0,
        errors=0,
        skipped=0,
        xfailed=0,
        xpassed=0,
        todo=0,
        cancelled=0,
        node_ids=(),
        reason=reason,
    )


def _tripwire_property_value(node_id: str, value: str) -> TripwireEventEvidence:
    try:
        decoded = json.loads(value)
        canonical = json.dumps(
            decoded,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        if (
            not isinstance(decoded, Mapping)
            or set(decoded) != {"event_id", "exception_type", "frame"}
            or value != canonical
        ):
            raise ValueError("noncanonical tripwire event")
        event = TripwireEventEvidence(node_id=node_id, **decoded)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("invalid tripwire event property") from error
    return event


def _tripwire_property_evidence(
    case: ET.Element, node_id: str, value: str
) -> TripwireEventEvidence:
    event = _tripwire_property_value(node_id, value)

    outcome = case.find("failure")
    if outcome is None:
        outcome = case.find("error")
    if outcome is None:
        raise ValueError("tripwire event must be a failure or error")
    signature = next(
        (
            item
            for item in _TRIPWIRE_EVENT_SIGNATURES[event.event_id]
            if item[0] == event.exception_type and item[1] == event.frame
        ),
        None,
    )
    if signature is None:
        raise ValueError("tripwire event signature mismatch")
    _exception_type, frame, message, exact_message = signature
    observed_message = outcome.get("message", "")
    expected_message = f"{event.exception_type}: {message}"
    if outcome.tag == "failure":
        message_matches = (
            observed_message == expected_message
            if exact_message
            else observed_message.startswith(expected_message)
        )
    else:
        phase_prefixes = tuple(
            f'failed on {phase} with "{expected_message}'
            for phase in ("setup", "teardown")
        )
        message_matches = any(
            observed_message == f'{prefix}"'
            if exact_message
            else observed_message.startswith(prefix) and observed_message.endswith('"')
            for prefix in phase_prefixes
        )
    if not message_matches:
        raise ValueError("tripwire event exception mismatch")
    traceback_text = outcome.text or ""
    frame_path, function = frame.rsplit(":", 1)
    function_pattern = re.compile(
        rf"^\s*(?:async\s+)?def\s+{re.escape(function)}\(", re.MULTILINE
    )
    tail_pattern = re.compile(
        rf"(?:^|\n){re.escape(frame_path)}:[1-9][0-9]*: "
        rf"{re.escape(event.exception_type)}\s*$"
    )
    if (
        function_pattern.search(traceback_text) is None
        or tail_pattern.search(traceback_text) is None
    ):
        raise ValueError("tripwire event traceback mismatch")
    return event


def parse_pytest_junit_bytes(
    payload: bytes,
    *,
    stderr_payload: bytes | None = None,
    command_id: str | None = None,
    require_tripwire_auth: bool = False,
) -> SuiteEvidence:
    """Parse captured pytest evidence and authenticate private event records."""

    sidecar = None
    authenticated_records: tuple[AuthenticatedTripwireRecord, ...] = ()
    if require_tripwire_auth:
        sidecar = parse_tripwire_sidecar(
            stderr_payload if isinstance(stderr_payload, bytes) else b"",
            command_id=command_id if isinstance(command_id, str) else "",
        )
        authenticated_records = sidecar.records
    authenticated_events: list[TripwireEventEvidence] = []
    authenticated_event_keys: set[tuple[str, str, str, str]] = set()
    for record in authenticated_records:
        event = record.event
        key = (event.node_id, event.event_id, event.exception_type, event.frame)
        if key not in authenticated_event_keys:
            authenticated_event_keys.add(key)
            authenticated_events.append(event)
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        return SuiteEvidence(
            valid=False,
            total=0,
            passed=0,
            failures=0,
            errors=0,
            skipped=0,
            xfailed=0,
            xpassed=0,
            todo=0,
            cancelled=0,
            node_ids=(),
            reason="MALFORMED_XML",
            tripwire_events=tuple(authenticated_events),
        )

    testcases = tuple(root.iter("testcase"))
    node_ids = tuple(case.get("name", "") for case in testcases)
    if any(not node_id for node_id in node_ids):
        return _empty_suite_evidence("DUPLICATE_NODE_ID")
    duplicate_node_ids = len(set(node_ids)) != len(node_ids)
    if duplicate_node_ids and not require_tripwire_auth:
        return SuiteEvidence(
            valid=False,
            total=len(testcases),
            passed=len(testcases),
            failures=0,
            errors=0,
            skipped=0,
            xfailed=0,
            xpassed=0,
            todo=0,
            cancelled=0,
            node_ids=node_ids,
            reason="DUPLICATE_NODE_ID",
        )

    properties: list[EvidenceProperty] = []
    tripwire_events: list[TripwireEventEvidence] = []
    tripwire_property_keys: set[tuple[str, str, str, str]] = set()
    property_integrity_valid = True
    for case, node_id in zip(testcases, node_ids, strict=True):
        for property_node in case.findall("./properties/property"):
            name = property_node.get("name", "")
            value = property_node.get("value", "")
            try:
                if name == "task9.tripwire_event":
                    event = (
                        _tripwire_property_value(node_id, value)
                        if require_tripwire_auth
                        else _tripwire_property_evidence(case, node_id, value)
                    )
                    key = (
                        event.node_id,
                        event.event_id,
                        event.exception_type,
                        event.frame,
                    )
                    if require_tripwire_auth:
                        if key not in authenticated_event_keys:
                            property_integrity_valid = False
                        else:
                            tripwire_property_keys.add(key)
                    elif key not in tripwire_property_keys:
                        tripwire_property_keys.add(key)
                        tripwire_events.append(event)
                else:
                    properties.append(
                        EvidenceProperty(
                            node_id=node_id,
                            name=name,
                            value=value,
                        )
                    )
            except ValueError:
                property_integrity_valid = False

    if require_tripwire_auth:
        runtime_keys = {
            (
                record.event.node_id,
                record.event.event_id,
                record.event.exception_type,
                record.event.frame,
            )
            for record in authenticated_records
            if record.phase in {"setup", "call", "teardown"}
        }
        if not runtime_keys.issubset(tripwire_property_keys):
            property_integrity_valid = False
        tripwire_events = authenticated_events

    passed = failures = errors = skipped = xfailed = xpassed = 0
    for case in testcases:
        error = case.find("error")
        failure = case.find("failure")
        skipped_node = case.find("skipped")
        if error is not None:
            errors += 1
        elif skipped_node is not None:
            if skipped_node.get("type") == "pytest.xfail":
                xfailed += 1
            else:
                skipped += 1
        elif failure is not None:
            message = failure.get("message", "")
            if failure.get("type") == "pytest.xfail" or "XPASS" in message:
                xpassed += 1
            else:
                failures += 1
        else:
            passed += 1

    total = len(testcases)
    nonpass = failures + errors + skipped + xfailed + xpassed
    if require_tripwire_auth and (
        sidecar is None
        or not sidecar.integrity_valid
        or not property_integrity_valid
    ):
        reason = "TRIPWIRE_AUTH_INVALID"
    elif duplicate_node_ids:
        reason = "DUPLICATE_NODE_ID"
    else:
        reason = "PASS" if total and nonpass == 0 else (
            "ZERO_TESTS" if total == 0 else "NONPASS_TESTS"
        )
    if tripwire_events and reason == "PASS":
        reason = "TRIPWIRE_EVENT"
    return SuiteEvidence(
        valid=reason == "PASS" and not tripwire_events,
        total=total,
        passed=passed,
        failures=failures,
        errors=errors,
        skipped=skipped,
        xfailed=xfailed,
        xpassed=xpassed,
        todo=0,
        cancelled=0,
        node_ids=node_ids,
        reason=reason,
        properties=tuple(properties),
        tripwire_events=tuple(tripwire_events),
    )


def parse_pytest_junit(path: Path) -> SuiteEvidence:
    """Parse pytest JUnit evidence and reject every non-pass or ambiguity."""

    try:
        payload = Path(path).read_bytes()
    except OSError:
        return _empty_suite_evidence("MALFORMED_XML")
    return parse_pytest_junit_bytes(payload)


_TASK9_EXCEPTION_CAPABILITY = object()
_TASK9_ROOT_BREAKER_CODES: dict[str, set[types.CodeType]] = {
    event_id: set() for event_id in ("external_ai", "edge_tts", "external_network")
}


@dataclass(slots=True)
class _TripwireProducerState:
    command_id: str
    private_key: object
    sequence: int = 0


_TASK9_PRODUCER_STATE: _TripwireProducerState | None = None


def _task9_tripwire_error(event_id: str) -> AssertionError:
    if event_id not in _TASK9_ROOT_BREAKER_CODES:
        raise ValueError("unknown Task 9 breaker")
    error = AssertionError(f"{TEST_TRIPWIRE_PREFIX}{event_id}")
    error._task9_tripwire_event_id = event_id
    error._task9_tripwire_capability = _TASK9_EXCEPTION_CAPABILITY
    return error


def _task9_register_breaker(event_id: str):
    """Private cooperative-TCB decorator for exact root-breaker code objects."""

    if event_id not in _TASK9_ROOT_BREAKER_CODES:
        raise ValueError("unknown Task 9 breaker")

    def register(function):
        code = getattr(function, "__code__", None)
        if not isinstance(code, types.CodeType):
            raise TypeError("Task 9 breaker must be a Python function")
        try:
            relative = Path(code.co_filename).resolve().relative_to(
                Path(__file__).resolve().parents[1]
            ).as_posix()
        except (OSError, ValueError) as error:
            raise ValueError("Task 9 breaker must be repository-local") from error
        frame = f"{relative}:{code.co_name}"
        if not any(
            expected_frame == frame
            for _kind, expected_frame, _message, _exact
            in _TRIPWIRE_EVENT_SIGNATURES[event_id]
        ):
            raise ValueError("Task 9 breaker frame is not authorized")
        _TASK9_ROOT_BREAKER_CODES[event_id].add(code)
        return function

    return register


def _task9_command_id_from_args(args) -> str:
    arguments = tuple(str(item) for item in args)
    for index, argument in enumerate(arguments):
        if argument.startswith("--junitxml="):
            candidate = argument.split("=", 1)[1]
        elif argument == "--junitxml" and index + 1 < len(arguments):
            candidate = arguments[index + 1]
        else:
            continue
        name = Path(candidate).name
        if name.endswith(".junit.xml"):
            return name[: -len(".junit.xml")]
        if name.endswith(".xml"):
            return name[:-4]
    return "pytest"


def _task9_write_sidecar_line(payload: bytes) -> None:
    stream = getattr(os.sys, "__stderr__", None)
    if stream is None:
        return
    binary = getattr(stream, "buffer", None)
    if binary is not None:
        binary.write(payload + b"\n")
        binary.flush()
    else:
        stream.write((payload + b"\n").decode("ascii"))
        stream.flush()


def _task9_start_producer(args) -> None:
    global _TASK9_PRODUCER_STATE
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
    )

    command_id = _task9_command_id_from_args(args)
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    _TASK9_PRODUCER_STATE = _TripwireProducerState(command_id, private_key)
    header = _tripwire_canonical_json_bytes(
        {
            "command_id": command_id,
            "public_key": base64.b64encode(public_key).decode("ascii"),
            "version": 1,
        }
    )
    _task9_write_sidecar_line(
        _TRIPWIRE_AUTH_KEY_PREFIX + base64.b64encode(header)
    )


def _task9_frame_code(entry) -> types.CodeType | None:
    raw_frame = getattr(getattr(entry, "frame", None), "raw", None)
    code = getattr(raw_frame, "f_code", None)
    return code if isinstance(code, types.CodeType) else None


def _task9_frame_name(entry) -> str | None:
    try:
        relative = Path(str(entry.path)).resolve().relative_to(
            Path(__file__).resolve().parents[1]
        ).as_posix()
        function = str(entry.name)
    except (AttributeError, OSError, TypeError, ValueError):
        return None
    return f"{relative}:{function}"


def _task9_nested_codes(code: types.CodeType):
    yield code
    for constant in code.co_consts:
        if isinstance(constant, types.CodeType):
            yield from _task9_nested_codes(constant)


def _task9_namespace_codes(namespace: Mapping[str, object]) -> set[types.CodeType]:
    result: set[types.CodeType] = set()
    seen: set[int] = set()

    def visit(value) -> None:
        identity = id(value)
        if identity in seen:
            return
        seen.add(identity)
        if isinstance(value, types.FunctionType):
            result.update(_task9_nested_codes(value.__code__))
        elif isinstance(value, type):
            for member in vars(value).values():
                visit(member)

    for value in namespace.values():
        visit(value)
    return result


def _task9_browser_code_is_trusted(
    frame: str, code: types.CodeType, entry
) -> bool:
    frame_path, _function = frame.rsplit(":", 1)
    repo_root = Path(__file__).resolve().parents[1]
    raw_frame = getattr(getattr(entry, "frame", None), "raw", None)
    namespace = getattr(raw_frame, "f_globals", None)
    if not isinstance(namespace, Mapping):
        return False
    try:
        relative = Path(namespace["__file__"]).resolve().relative_to(
            repo_root
        ).as_posix()
        spec = namespace["__spec__"]
        origin = Path(spec.origin).resolve().relative_to(repo_root).as_posix()
    except (AttributeError, KeyError, OSError, TypeError, ValueError):
        return False
    return (
        relative == frame_path
        and origin == frame_path
        and code in _task9_namespace_codes(namespace)
    )


def _task9_authenticated_event(excinfo) -> dict[str, str] | None:
    traceback = getattr(excinfo, "traceback", None)
    if not traceback:
        return None
    error = getattr(excinfo, "value", None)
    final_entry = traceback[-1]
    frame = _task9_frame_name(final_entry)
    code = _task9_frame_code(final_entry)
    if frame is None or code is None:
        return None
    event_id = getattr(error, "_task9_tripwire_event_id", None)
    if (
        type(error) is AssertionError
        and event_id in _TASK9_ROOT_BREAKER_CODES
        and getattr(error, "_task9_tripwire_capability", None)
        is _TASK9_EXCEPTION_CAPABILITY
        and code in _TASK9_ROOT_BREAKER_CODES[event_id]
        and str(error) == f"{TEST_TRIPWIRE_PREFIX}{event_id}"
    ):
        return {
            "event_id": event_id,
            "exception_type": "AssertionError",
            "frame": frame,
        }
    for candidate_id, signatures in _TRIPWIRE_EVENT_SIGNATURES.items():
        if not candidate_id.startswith("browser_"):
            continue
        for exception_name, expected_frame, message, exact_message in signatures:
            if (
                type(error).__name__ == exception_name
                and frame == expected_frame
                and (
                    str(error) == message
                    if exact_message
                    else str(error).startswith(message)
                )
                and _task9_browser_code_is_trusted(frame, code, final_entry)
            ):
                return {
                    "event_id": candidate_id,
                    "exception_type": exception_name,
                    "frame": frame,
                }
    return None


def _task9_exception_phase(excinfo, *, default: str) -> str:
    traceback = getattr(excinfo, "traceback", ()) or ()
    names = tuple(str(getattr(entry, "name", "")) for entry in traceback)
    if "<module>" in names:
        return "import"
    if any("collect" in name.lower() for name in names):
        return "collection"
    return default


def _task9_emit_event(*, node_id: str, phase: str, event: Mapping[str, str]) -> None:
    state = _TASK9_PRODUCER_STATE
    if state is None or phase not in _TRIPWIRE_PHASES:
        return
    state.sequence += 1
    record = _tripwire_canonical_json_bytes(
        {
            "command_id": state.command_id,
            "event": dict(event),
            "node_id": node_id,
            "phase": phase,
            "sequence": state.sequence,
        }
    )
    signature = state.private_key.sign(record)
    _task9_write_sidecar_line(
        _TRIPWIRE_AUTH_EVENT_PREFIX
        + base64.b64encode(record)
        + b":"
        + base64.b64encode(signature)
    )


@pytest.hookimpl(tryfirst=True)
def pytest_load_initial_conftests(early_config, parser, args):
    del early_config, parser
    _task9_start_producer(args)


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    if _TASK9_PRODUCER_STATE is None:
        _task9_start_producer(getattr(config, "invocation_params", ()).args)


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_makereport(item, call):
    event = _task9_authenticated_event(getattr(call, "excinfo", None))
    if event is None:
        return None
    phase = str(getattr(call, "when", "call"))
    _task9_emit_event(node_id=str(item.name), phase=phase, event=event)
    item.user_properties.append(
        (
            "task9.tripwire_event",
            json.dumps(event, separators=(",", ":"), sort_keys=True),
        )
    )
    return None


@pytest.hookimpl(tryfirst=True)
def pytest_exception_interact(node, call, report):
    del report
    if str(getattr(call, "when", "")) != "collect":
        return
    event = _task9_authenticated_event(getattr(call, "excinfo", None))
    if event is not None:
        excinfo = getattr(call, "excinfo", None)
        phase = _task9_exception_phase(excinfo, default="collection")
        scope = f"<{phase}:{getattr(node, 'nodeid', getattr(node, 'name', 'unknown'))}>"
        _task9_emit_event(node_id=scope, phase=phase, event=event)


@pytest.hookimpl(tryfirst=True)
def pytest_internalerror(excrepr, excinfo):
    del excrepr
    event = _task9_authenticated_event(excinfo)
    if event is not None:
        phase = _task9_exception_phase(excinfo, default="import")
        _task9_emit_event(
            node_id=f"<{phase}:pytest-internal>", phase=phase, event=event
        )
    return None


_TAP_RESULT = re.compile(
    r"^(not ok|ok) ([1-9][0-9]*) - (.*?)(?: # (SKIP|TODO|cancelled)(?: .*)?)?$",
    re.IGNORECASE,
)
_TAP_PLAN = re.compile(r"^1\.\.([0-9]+)$")
_TAP_SUMMARY = re.compile(
    r"^# (tests|pass|fail|cancelled|skipped|todo) ([0-9]+)$"
)


def parse_node_tap(payload: bytes | str) -> SuiteEvidence:
    """Parse Node's top-level TAP13 subtest results without trusting summaries."""

    if isinstance(payload, bytes):
        try:
            text = payload.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return _empty_suite_evidence("INVALID_UTF8")
    else:
        text = payload
    lines = text.splitlines()
    if not lines or lines[0] != "TAP version 13":
        return _empty_suite_evidence("MALFORMED_TAP")

    matches: list[tuple[int, re.Match[str]]] = []
    plans: list[int] = []
    summaries: dict[str, int] = {}
    for line_number, line in enumerate(lines):
        result = _TAP_RESULT.fullmatch(line)
        if result is not None:
            matches.append((line_number, result))
            continue
        plan = _TAP_PLAN.fullmatch(line)
        if plan is not None:
            plans.append(int(plan.group(1)))
            continue
        summary = _TAP_SUMMARY.fullmatch(line)
        if summary is not None:
            key = summary.group(1)
            if key in summaries:
                return _empty_suite_evidence("MALFORMED_TAP")
            summaries[key] = int(summary.group(2))

    node_ids = tuple(match.group(3) for _line, match in matches)
    numbers = tuple(int(match.group(2)) for _line, match in matches)
    if any(not node_id for node_id in node_ids):
        return _empty_suite_evidence("DUPLICATE_NODE_ID")
    if len(set(node_ids)) != len(node_ids):
        return SuiteEvidence(
            valid=False,
            total=len(matches),
            passed=len(matches),
            failures=0,
            errors=0,
            skipped=0,
            xfailed=0,
            xpassed=0,
            todo=0,
            cancelled=0,
            node_ids=node_ids,
            reason="DUPLICATE_NODE_ID",
        )

    total = len(matches)
    if len(plans) != 1 or plans[0] != total or numbers != tuple(range(1, total + 1)):
        return _empty_suite_evidence("MALFORMED_TAP")
    if total == 0:
        return _empty_suite_evidence("ZERO_TESTS")

    passed = failures = skipped = todo = cancelled = 0
    for index, (line_number, match) in enumerate(matches):
        next_line = matches[index + 1][0] if index + 1 < total else len(lines)
        block = "\n".join(lines[line_number + 1 : next_line])
        directive = (match.group(4) or "").lower()
        status = match.group(1).lower()
        if directive == "skip":
            skipped += 1
        elif directive == "todo":
            todo += 1
        elif directive == "cancelled" or "cancelledByParent" in block:
            cancelled += 1
        elif status == "not ok":
            failures += 1
        else:
            passed += 1

    actual_summaries = {
        "tests": total,
        "pass": passed,
        "fail": failures,
        "cancelled": cancelled,
        "skipped": skipped,
        "todo": todo,
    }
    if any(actual_summaries[key] != value for key, value in summaries.items()):
        return _empty_suite_evidence("MALFORMED_TAP")

    nonpass = failures + skipped + todo + cancelled
    return SuiteEvidence(
        valid=nonpass == 0,
        total=total,
        passed=passed,
        failures=failures,
        errors=0,
        skipped=skipped,
        xfailed=0,
        xpassed=0,
        todo=todo,
        cancelled=cancelled,
        node_ids=node_ids,
        reason="PASS" if nonpass == 0 else "NONPASS_TESTS",
    )


@dataclass(frozen=True, slots=True)
class CommandSpec:
    command_id: str
    argv: tuple[str, ...]
    timeout_seconds: int
    conftest_mode: ConftestMode
    evidence_format: EvidenceFormat
    evidence_path: Path | None = None

    def __post_init__(self) -> None:
        if not self.command_id or not self.argv:
            raise ValueError("command spec requires a nonempty id and argv")
        if self.timeout_seconds <= 0:
            raise ValueError("command timeout must be positive")
        if self.evidence_format is EvidenceFormat.JUNIT and self.evidence_path is None:
            raise ValueError("pytest command requires a JUnit evidence path")
        if self.evidence_format is EvidenceFormat.TAP and self.evidence_path is not None:
            raise ValueError("TAP evidence is captured from stdout")


def _pytest_spec(
    command_id: str,
    artifact_root: Path,
    targets: tuple[str, ...],
    *,
    pure: bool = False,
) -> CommandSpec:
    evidence_path = artifact_root / f"{command_id}.junit.xml"
    plugin = ("-p", "scripts.run_interaction_acceptance", "--capture=sys")
    options = plugin + (
        ("--noconftest", "-q", "-o", "xfail_strict=true")
        if pure
        else ("-q", "-o", "xfail_strict=true")
    )
    argv = CLEAN_ENV_ARGV + (
        PYTHON,
        "-m",
        "pytest",
        *options,
        f"--junitxml={evidence_path}",
        *targets,
    )
    return CommandSpec(
        command_id=command_id,
        argv=argv,
        timeout_seconds=COMMAND_TIMEOUTS[command_id],
        conftest_mode=ConftestMode.PURE if pure else ConftestMode.PROJECT,
        evidence_format=EvidenceFormat.JUNIT,
        evidence_path=evidence_path,
    )


def _node_spec(command_id: str, targets: tuple[str, ...]) -> CommandSpec:
    return CommandSpec(
        command_id=command_id,
        argv=CLEAN_ENV_ARGV
        + (
            NODE,
            "--unhandled-rejections=strict",
            "--test",
            "--test-concurrency=1",
            "--test-reporter=tap",
            *targets,
        ),
        timeout_seconds=COMMAND_TIMEOUTS[command_id],
        conftest_mode=ConftestMode.PROJECT,
        evidence_format=EvidenceFormat.TAP,
    )


def build_command_specs(repo_root: Path, artifact_root: Path) -> tuple[CommandSpec, ...]:
    """Build the frozen 22-command inventory without shell expansion."""

    repo_root = Path(repo_root).resolve()
    artifact_root = Path(artifact_root).resolve()
    backend_targets = (
        "tests/test_database_safety.py",
        "tests/test_rebuild_demo_database.py",
        "tests/test_runtime_health.py",
        "tests/test_api_errors.py",
        "tests/test_http_boundary.py",
        "tests/test_teacher_auth.py",
        "tests/test_frontend_foundation.py",
        "tests/test_pipeline_models.py",
        "tests/test_chat_idempotency.py",
        "tests/test_conversation_completion.py",
        "tests/test_analysis_worker.py",
        "tests/test_roster_idempotency.py",
        "tests/test_review_atomicity.py",
        "tests/test_deactivation.py",
        "tests/test_conversation_history.py",
        "tests/test_api.py",
        "tests/test_server_capability_contracts.py",
        "tests/test_schema_migrations.py",
        "tests/test_business_time.py",
        "tests/test_runtime_context.py",
        "tests/test_resource_idempotency.py",
        "tests/test_avatar_media.py",
        "tests/test_weekly_reports.py",
        "tests/test_conversation_search.py",
        "tests/test_demo_seed.py",
        "tests/e2e.py",
    )

    def sorted_node_targets(directory: str) -> tuple[str, ...]:
        base = repo_root / directory
        return tuple(
            path.relative_to(repo_root).as_posix()
            for path in sorted(base.glob("*.test.mjs"), key=lambda item: item.name)
        )

    specs = (
        _pytest_spec(
            "runner",
            artifact_root,
            ("tests/test_interaction_acceptance_runner.py",),
            pure=True,
        ),
        _pytest_spec(
            "lovable",
            artifact_root,
            ("tests/test_lovable_artifacts.py",),
            pure=True,
        ),
        _pytest_spec("backend", artifact_root, backend_targets),
        _pytest_spec("browser", artifact_root, ("tests/browser",)),
        _node_spec("shared_node", ("tests/frontend/shared/api-client.test.mjs",)),
        _node_spec("child_node", sorted_node_targets("tests/frontend/child")),
        _node_spec("teacher_node", sorted_node_targets("tests/frontend/teacher")),
        _pytest_spec(
            "release_focus_1024",
            artifact_root,
            (
                "tests/browser/test_release_viewports.py::test_release_focus_indicator_meets_three_to_one[1024x768]",
            ),
        ),
        _pytest_spec(
            "release_focus_all",
            artifact_root,
            (
                "tests/browser/test_release_viewports.py::test_release_focus_indicator_meets_three_to_one",
            ),
        ),
        _pytest_spec(
            "teacher_accessibility_full",
            artifact_root,
            ("tests/browser/test_teacher_accessibility.py",),
        ),
        _pytest_spec(
            "release_db_action_1024",
            artifact_root,
            (
                "tests/browser/test_release_viewports.py::test_release_teacher_action_persists_to_disposable_sqlite[1024x768]",
            ),
        ),
        _pytest_spec(
            "release_db_action_all",
            artifact_root,
            (
                "tests/browser/test_release_viewports.py::test_release_teacher_action_persists_to_disposable_sqlite",
            ),
        ),
        _pytest_spec(
            "review_identity_1024",
            artifact_root,
            (
                "tests/browser/test_teacher_review_loading.py::test_teacher_review_queue_and_detail_show_identity_time_id_and_status[1024x768]",
            ),
        ),
        _pytest_spec(
            "review_identity_all",
            artifact_root,
            (
                "tests/browser/test_teacher_review_loading.py::test_teacher_review_queue_and_detail_show_identity_time_id_and_status",
            ),
        ),
        _pytest_spec(
            "child_chat_timeout_1024",
            artifact_root,
            (
                "tests/browser/test_child_faults.py::test_first_chat_timeout_retains_draft_and_reuses_request_id_once[1024x576]",
            ),
        ),
        _pytest_spec(
            "child_chat_timeout_all",
            artifact_root,
            (
                "tests/browser/test_child_faults.py::test_first_chat_timeout_retains_draft_and_reuses_request_id_once",
            ),
        ),
        _pytest_spec(
            "child_completion_delay_1024",
            artifact_root,
            (
                "tests/browser/test_child_faults.py::test_completion_delay_is_single_flight_and_saves_once[1024x576]",
            ),
        ),
        _pytest_spec(
            "child_completion_delay_all",
            artifact_root,
            (
                "tests/browser/test_child_faults.py::test_completion_delay_is_single_flight_and_saves_once",
            ),
        ),
        _pytest_spec(
            "child_keyboard_core_1024",
            artifact_root,
            (
                "tests/browser/test_child_faults.py::test_child_core_flow_is_page_keyboard_only_and_saves_once[1024x576]",
            ),
        ),
        _pytest_spec(
            "child_keyboard_core_all",
            artifact_root,
            (
                "tests/browser/test_child_faults.py::test_child_core_flow_is_page_keyboard_only_and_saves_once",
            ),
        ),
        _pytest_spec(
            "today_three_status_1024",
            artifact_root,
            (
                "tests/browser/test_teacher_today.py::test_teacher_today_renders_pending_processing_and_failed_rows_with_retry_boundaries[1024x768]",
            ),
        ),
        _pytest_spec(
            "today_three_status_all",
            artifact_root,
            (
                "tests/browser/test_teacher_today.py::test_teacher_today_renders_pending_processing_and_failed_rows_with_retry_boundaries",
            ),
        ),
    )
    ids = tuple(spec.command_id for spec in specs)
    if ids != tuple(COMMAND_TIMEOUTS) or len(set(ids)) != len(ids):
        raise RuntimeError("command inventory does not match the frozen authoritative IDs")
    return specs


def build_sanitized_env(
    parent_env: Mapping[str, str], *, browser: bool
) -> dict[str, str]:
    """Copy only neutral keys, never reading rejected values."""

    available_names = frozenset(iter(parent_env))
    allowed_names = tuple(
        name for name in NEUTRAL_PARENT_ENV if browser or name != "HOME"
    )
    sanitized = {
        name: parent_env[name] for name in allowed_names if name in available_names
    }
    sanitized.update(FORCED_BREAKERS)
    return sanitized


def logical_sqlite_digest(path: Path) -> str:
    """Hash the read-only logical SQLite view, including committed WAL rows."""

    resolved = Path(path).resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="task9-sqlite-snapshot-") as temp_dir:
        snapshot_path = Path(temp_dir) / resolved.name
        shutil.copyfile(resolved, snapshot_path)
        for suffix in ("-wal", "-shm"):
            sidecar = Path(f"{resolved}{suffix}")
            if sidecar.exists():
                shutil.copyfile(sidecar, Path(f"{snapshot_path}{suffix}"))
        with sqlite3.connect(
            f"{snapshot_path.as_uri()}?mode=ro", uri=True
        ) as connection:
            snapshot = "\n".join(connection.iterdump()).encode("utf-8")
    return hashlib.sha256(snapshot).hexdigest()


def file_snapshot(path: Path) -> FileSnapshot:
    """Capture strict lstat metadata and regular-file content without following links."""

    candidate = Path(path)
    try:
        details = candidate.lstat()
    except FileNotFoundError:
        return FileSnapshot(kind=FileKind.MISSING)
    except OSError as error:
        return FileSnapshot(kind=FileKind.UNREADABLE, error=type(error).__name__)
    common = {
        "mode": stat.S_IMODE(details.st_mode),
        "size": details.st_size,
        "mtime_ns": details.st_mtime_ns,
    }
    if stat.S_ISLNK(details.st_mode):
        try:
            target = os.readlink(candidate)
        except OSError as error:
            return FileSnapshot(
                kind=FileKind.UNREADABLE,
                error=type(error).__name__,
                **common,
            )
        return FileSnapshot(kind=FileKind.SYMLINK, symlink_target=target, **common)
    if stat.S_ISDIR(details.st_mode):
        return FileSnapshot(kind=FileKind.DIRECTORY, **common)
    if not stat.S_ISREG(details.st_mode):
        return FileSnapshot(kind=FileKind.SPECIAL, **common)
    try:
        digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
    except OSError as error:
        return FileSnapshot(
            kind=FileKind.UNREADABLE,
            error=type(error).__name__,
            **common,
        )
    return FileSnapshot(kind=FileKind.REGULAR, sha256=digest, **common)


def database_snapshot(path: Path) -> DatabaseSnapshot:
    """Capture logical SQLite content and strict physical database/sidecar state."""

    database_path = Path(path)
    database = file_snapshot(database_path)
    wal = file_snapshot(Path(f"{database_path}-wal"))
    shm = file_snapshot(Path(f"{database_path}-shm"))
    reasons: list[str] = []
    if database.kind is FileKind.MISSING:
        reasons.append("DATABASE_MISSING")
    elif database.kind is not FileKind.REGULAR:
        reasons.append("DATABASE_NOT_REGULAR")
    if wal.kind not in {FileKind.MISSING, FileKind.REGULAR}:
        reasons.append("WAL_NOT_REGULAR")
    if shm.kind not in {FileKind.MISSING, FileKind.REGULAR}:
        reasons.append("SHM_NOT_REGULAR")
    logical_digest = None
    if not reasons:
        try:
            logical_digest = logical_sqlite_digest(database_path)
        except (OSError, sqlite3.Error):
            reasons.append("DATABASE_LOGICAL_UNREADABLE")
    return DatabaseSnapshot(
        logical_digest=logical_digest,
        database=database,
        wal=wal,
        shm=shm,
        unsafe_reasons=tuple(reasons),
    )


def _file_snapshot_record(snapshot: FileSnapshot) -> dict[str, object]:
    return {
        "kind": snapshot.kind.value,
        "mode": snapshot.mode,
        "size": snapshot.size,
        "mtime_ns": snapshot.mtime_ns,
        "sha256": snapshot.sha256,
        "symlink_target": snapshot.symlink_target,
        "error": snapshot.error,
    }


def _make_directory_snapshot(
    root: FileSnapshot,
    entries: tuple[DirectoryEntrySnapshot, ...],
    *,
    allow_symlinks: bool,
    scan_error: str | None = None,
    scan_source: str | None = None,
) -> DirectorySnapshot:
    """Derive one canonical directory state for both capture and reconstruction."""

    paths = tuple(entry.relative_path for entry in entries)
    if paths != tuple(sorted(paths)) or len(paths) != len(set(paths)):
        raise ValueError("directory entries are not canonical")
    if (scan_error is None) is not (scan_source is None):
        raise ValueError("directory scan error and source must be paired")
    if scan_error is not None and (
        not isinstance(scan_error, str)
        or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", scan_error) is None
    ):
        raise ValueError("directory scan error is invalid")
    if scan_source is not None:
        valid_source = scan_source == "." or (
            isinstance(scan_source, str)
            and scan_source
            and not scan_source.startswith("/")
            and "\\" not in scan_source
            and all(part not in {"", ".", ".."} for part in scan_source.split("/"))
        )
        if not valid_source:
            raise ValueError("directory scan source is invalid")

    reasons: list[str] = []
    if root.kind is FileKind.MISSING:
        if entries or scan_error is not None:
            raise ValueError("missing directory cannot contain scan state")
        reasons.append("DIRECTORY_MISSING")
    elif root.kind is FileKind.UNREADABLE:
        if entries or scan_error is not None:
            raise ValueError("unreadable root cannot contain scan state")
        reasons.append("DIRECTORY_ROOT_UNREADABLE")
    elif root.kind is not FileKind.DIRECTORY:
        if entries or scan_error is not None:
            raise ValueError("non-directory root cannot contain scan state")
        reasons.append("DIRECTORY_NOT_DIRECTORY")
    else:
        entry_by_path = {entry.relative_path: entry for entry in entries}
        if scan_source not in {None, "."}:
            source_entry = entry_by_path.get(scan_source)
            if source_entry is None or source_entry.snapshot.kind is not FileKind.DIRECTORY:
                raise ValueError("directory scan source was not captured as a directory")
        for entry in entries:
            kind = entry.snapshot.kind
            if kind is FileKind.DIRECTORY:
                continue
            if kind is FileKind.UNREADABLE:
                reasons.append(f"ENTRY_UNREADABLE:{entry.relative_path}")
            elif kind is FileKind.SYMLINK and allow_symlinks:
                continue
            elif kind is not FileKind.REGULAR:
                reasons.append(f"ENTRY_NOT_REGULAR:{entry.relative_path}")
        if scan_error is not None:
            reasons.append(f"SCANDIR:{scan_source}:{scan_error}")

    canonical_reasons = tuple(dict.fromkeys(reasons))
    digest = None
    if not canonical_reasons:
        payload = {
            "root": _file_snapshot_record(root),
            "entries": [
                {
                    "relative_path": entry.relative_path,
                    "snapshot": _file_snapshot_record(entry.snapshot),
                }
                for entry in entries
            ],
            "scan_error": scan_error,
            "scan_source": scan_source,
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
    return DirectorySnapshot(
        root=root,
        entries=entries,
        digest=digest,
        unsafe_reasons=canonical_reasons,
        scan_error=scan_error,
        scan_source=scan_source,
    )


def directory_snapshot(path: Path, *, allow_symlinks: bool = False) -> DirectorySnapshot:
    """Capture a stable, non-following directory tree with strict metadata."""

    root_path = Path(path)
    root = file_snapshot(root_path)
    if root.kind is not FileKind.DIRECTORY:
        return _make_directory_snapshot(root, (), allow_symlinks=allow_symlinks)

    entries: list[DirectoryEntrySnapshot] = []
    pending = [root_path]
    scan_error: str | None = None
    scan_source: str | None = None
    while pending and scan_error is None:
        current = pending.pop()
        current_source = (
            "." if current == root_path else current.relative_to(root_path).as_posix()
        )
        children = []
        try:
            with os.scandir(current) as scan:
                iterator = iter(scan)
                while True:
                    try:
                        children.append(next(iterator))
                    except StopIteration:
                        break
                    except OSError as error:
                        scan_error = type(error).__name__
                        scan_source = current_source
                        break
        except OSError as error:
            if scan_error is None:
                scan_error = type(error).__name__
                scan_source = current_source
        for child in sorted(children, key=lambda item: item.name):
            child_path = Path(child.path)
            relative = child_path.relative_to(root_path).as_posix()
            snapshot = file_snapshot(child_path)
            entries.append(DirectoryEntrySnapshot(relative, snapshot))
            if snapshot.kind is FileKind.DIRECTORY and scan_error is None:
                pending.append(child_path)
    entries.sort(key=lambda item: item.relative_path)
    return _make_directory_snapshot(
        root,
        tuple(entries),
        allow_symlinks=allow_symlinks,
        scan_error=scan_error,
        scan_source=scan_source,
    )


def directory_digest(path: Path) -> str:
    snapshot = directory_snapshot(path)
    if snapshot.digest is None:
        raise ResourceCaptureError(";".join(snapshot.unsafe_reasons))
    return snapshot.digest


PROTECTED_USER_PATHS = (
    ".workbuddy/memory/2026-08-22.md",
    "docs/superpowers/specs/2026-08-23-interaction-stabilization-design.md",
    ".superpowers/brainstorm",
    "docs/superpowers/plans",
)


def _is_inherited_user_path(path: str) -> bool:
    return path in PROTECTED_USER_PATHS[:2] or any(
        path.startswith(f"{directory}/") for directory in PROTECTED_USER_PATHS[2:]
    )


def unit8_porcelain_is_allowed(payload: bytes) -> bool:
    """Require an empty index and allow worktree dirt only in inherited paths."""

    if not isinstance(payload, bytes):
        return False
    if not payload:
        return True
    if not payload.endswith(b"\0"):
        return False
    lines = payload[:-1].split(b"\0")
    if not lines or any(not line for line in lines):
        return False
    for line in lines:
        if len(line) < 4 or line[2:3] != b" ":
            return False
        status = line[:2]
        if status == b"??":
            pass
        elif status[:1] == b" " and status[1:2] in {b"M", b"D", b"T"}:
            pass
        else:
            return False
        try:
            path = line[3:].decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return False
        if not path or " -> " in path or not _is_inherited_user_path(path):
            return False
    return True


def _protected_path_snapshot(repo_root: Path, relative_path: str) -> ProtectedPathSnapshot:
    candidate = repo_root / relative_path
    root = file_snapshot(candidate)
    if root.kind is FileKind.MISSING:
        return ProtectedPathSnapshot(relative_path, root, None, ("PATH_MISSING",))
    if root.kind in {FileKind.UNREADABLE, FileKind.SPECIAL}:
        return ProtectedPathSnapshot(relative_path, root, None, ("PATH_UNSAFE",))
    if root.kind is FileKind.DIRECTORY:
        directory = directory_snapshot(candidate, allow_symlinks=True)
        reasons = list(directory.unsafe_reasons)
        if directory.root != root:
            reasons.append("PATH_FILE_DIRECTORY_MISMATCH")
        return ProtectedPathSnapshot(
            relative_path,
            root,
            directory,
            tuple(dict.fromkeys(reasons)),
        )
    return ProtectedPathSnapshot(relative_path, root, None, ())


def _git_capture(repo_root: Path, *arguments: str) -> tuple[int, bytes]:
    try:
        completed = subprocess.run(
            (*CLEAN_ENV_ARGV, "/opt/homebrew/bin/git", *arguments),
            cwd=repo_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError:
        return 127, b""
    return completed.returncode, completed.stdout


_GIT_METADATA_MAX_BYTES = 1024 * 1024
_GIT_SYMBOLIC_REF_LIMIT = 8
_GIT_HEAD_PATTERN = re.compile(r"[0-9a-f]{40}")


def _invalid_trusted_repository_head() -> NoReturn:
    raise CliMisuseError("completed report repository HEAD is invalid")


def _canonical_git_absolute_path(raw_path: object) -> Path:
    try:
        raw = os.fspath(raw_path)
    except TypeError:
        _invalid_trusted_repository_head()
    if (
        not isinstance(raw, str)
        or not raw
        or "\x00" in raw
        or not os.path.isabs(raw)
        or raw.startswith("//")
        or os.path.normpath(raw) != raw
    ):
        _invalid_trusted_repository_head()
    candidate = Path(raw)
    if str(candidate) != raw:
        _invalid_trusted_repository_head()
    return candidate


def _git_metadata_identity(details: os.stat_result) -> tuple[int, ...]:
    return (
        details.st_dev,
        details.st_ino,
        details.st_mode,
        details.st_size,
        details.st_mtime_ns,
    )


def _strict_git_path_details(
    raw_path: object, *, allow_missing: bool = False
) -> tuple[Path, os.stat_result] | None:
    candidate = _canonical_git_absolute_path(raw_path)
    for ancestor in reversed(candidate.parents):
        try:
            details = ancestor.lstat()
        except FileNotFoundError:
            if allow_missing:
                return None
            _invalid_trusted_repository_head()
        except OSError:
            _invalid_trusted_repository_head()
        if not stat.S_ISDIR(details.st_mode) or stat.S_ISLNK(details.st_mode):
            _invalid_trusted_repository_head()
    try:
        details = candidate.lstat()
    except FileNotFoundError:
        if allow_missing:
            return None
        _invalid_trusted_repository_head()
    except OSError:
        _invalid_trusted_repository_head()
    try:
        if candidate.resolve(strict=True) != candidate:
            _invalid_trusted_repository_head()
    except (OSError, RuntimeError):
        _invalid_trusted_repository_head()
    return candidate, details


def _strict_git_directory(raw_path: object) -> Path:
    checked = _strict_git_path_details(raw_path)
    if checked is None:
        _invalid_trusted_repository_head()
    candidate, details = checked
    if not stat.S_ISDIR(details.st_mode) or stat.S_ISLNK(details.st_mode):
        _invalid_trusted_repository_head()
    return candidate


def _read_strict_git_metadata_file(
    raw_path: object,
    *,
    allow_missing: bool = False,
    maximum_bytes: int = _GIT_METADATA_MAX_BYTES,
) -> bytes | None:
    checked = _strict_git_path_details(raw_path, allow_missing=allow_missing)
    if checked is None:
        return None
    candidate, before = checked
    if not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode):
        _invalid_trusted_repository_head()
    no_follow = getattr(os, "O_NOFOLLOW", None)
    if no_follow is None:
        _invalid_trusted_repository_head()
    descriptor = -1
    try:
        descriptor = os.open(
            candidate,
            os.O_RDONLY | os.O_CLOEXEC | no_follow,
        )
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or _git_metadata_identity(opened) != _git_metadata_identity(before)
        ):
            _invalid_trusted_repository_head()
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(65536, maximum_bytes + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > maximum_bytes:
                _invalid_trusted_repository_head()
        after = candidate.lstat()
        if (
            not stat.S_ISREG(after.st_mode)
            or stat.S_ISLNK(after.st_mode)
            or _git_metadata_identity(after) != _git_metadata_identity(opened)
        ):
            _invalid_trusted_repository_head()
        return b"".join(chunks)
    except CliMisuseError:
        raise
    except OSError:
        _invalid_trusted_repository_head()
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _single_git_metadata_line(payload: bytes) -> str:
    if not payload.endswith(b"\n") or payload.count(b"\n") != 1:
        _invalid_trusted_repository_head()
    try:
        line = payload[:-1].decode("ascii", errors="strict")
    except UnicodeDecodeError:
        _invalid_trusted_repository_head()
    if not line or "\r" in line:
        _invalid_trusted_repository_head()
    return line


def _declared_git_directory_path(
    base: Path,
    raw: str,
    *,
    allow_absolute: bool,
    allow_parent_components: bool,
) -> Path:
    if not raw or "\x00" in raw or "\\" in raw:
        _invalid_trusted_repository_head()
    if os.path.isabs(raw):
        if not allow_absolute:
            _invalid_trusted_repository_head()
        return _canonical_git_absolute_path(raw)
    if os.path.normpath(raw) != raw or raw in {".", ".."}:
        _invalid_trusted_repository_head()
    components = raw.split("/")
    if (
        any(component in {"", "."} for component in components)
        or (not allow_parent_components and ".." in components)
    ):
        _invalid_trusted_repository_head()
    joined = os.path.normpath(os.path.join(str(base), raw))
    return _canonical_git_absolute_path(joined)


def _valid_git_ref_name(ref_name: str) -> bool:
    if (
        not ref_name.startswith("refs/")
        or ref_name.endswith("/")
        or "//" in ref_name
        or ".." in ref_name
        or "@{" in ref_name
        or any(character in " ~^:?*[\\" for character in ref_name)
        or any(ord(character) < 32 or ord(character) == 127 for character in ref_name)
    ):
        return False
    components = ref_name.split("/")
    return all(
        component
        and component not in {".", ".."}
        and not component.startswith(".")
        and not component.endswith(".")
        and not component.endswith(".lock")
        for component in components
    )


def _parse_git_reference_line(payload: bytes) -> tuple[str, str]:
    line = _single_git_metadata_line(payload)
    if _GIT_HEAD_PATTERN.fullmatch(line) is not None:
        return "head", line
    if line.startswith("ref: "):
        ref_name = line[5:]
        if _valid_git_ref_name(ref_name):
            return "ref", ref_name
    _invalid_trusted_repository_head()


def _parse_packed_refs(payload: bytes | None) -> dict[str, str]:
    if payload is None:
        return {}
    if not payload or not payload.endswith(b"\n"):
        _invalid_trusted_repository_head()
    try:
        text = payload.decode("ascii", errors="strict")
    except UnicodeDecodeError:
        _invalid_trusted_repository_head()
    if any(
        (ord(character) < 32 and character != "\n")
        or ord(character) == 127
        for character in text
    ):
        _invalid_trusted_repository_head()
    parsed: dict[str, str] = {}
    previous_record = False
    for line in text[:-1].split("\n"):
        if not line:
            _invalid_trusted_repository_head()
        if line.startswith("#"):
            if not line.startswith("# ") or any(
                ord(character) < 32 or ord(character) == 127
                for character in line
            ):
                _invalid_trusted_repository_head()
            previous_record = False
            continue
        if line.startswith("^"):
            if (
                not previous_record
                or _GIT_HEAD_PATTERN.fullmatch(line[1:]) is None
            ):
                _invalid_trusted_repository_head()
            previous_record = False
            continue
        matched = re.fullmatch(r"([0-9a-f]{40}) ([^\x00-\x20\x7f]+)", line)
        if matched is None:
            _invalid_trusted_repository_head()
        head, ref_name = matched.groups()
        if not _valid_git_ref_name(ref_name) or ref_name in parsed:
            _invalid_trusted_repository_head()
        parsed[ref_name] = head
        previous_record = True
    return parsed


def _read_trusted_repository_head(repo_root: Path) -> str:
    try:
        root = _strict_git_directory(repo_root)
        git_entry_checked = _strict_git_path_details(root / ".git")
        if git_entry_checked is None:
            _invalid_trusted_repository_head()
        git_entry, git_entry_details = git_entry_checked
        git_file_layout = stat.S_ISREG(git_entry_details.st_mode)
        if stat.S_ISDIR(git_entry_details.st_mode) and not stat.S_ISLNK(
            git_entry_details.st_mode
        ):
            git_dir = _strict_git_directory(git_entry)
        elif git_file_layout and not stat.S_ISLNK(git_entry_details.st_mode):
            git_file_payload = _read_strict_git_metadata_file(
                git_entry, maximum_bytes=4096
            )
            if git_file_payload is None:
                _invalid_trusted_repository_head()
            git_file_line = _single_git_metadata_line(git_file_payload)
            if not git_file_line.startswith("gitdir: "):
                _invalid_trusted_repository_head()
            git_dir = _strict_git_directory(
                _declared_git_directory_path(
                    root,
                    git_file_line[8:],
                    allow_absolute=True,
                    allow_parent_components=False,
                )
            )
        else:
            _invalid_trusted_repository_head()

        commondir_payload = _read_strict_git_metadata_file(
            git_dir / "commondir", allow_missing=True, maximum_bytes=4096
        )
        if commondir_payload is None:
            common_dir = git_dir
        else:
            if not git_file_layout:
                _invalid_trusted_repository_head()
            common_line = _single_git_metadata_line(commondir_payload)
            common_dir = _strict_git_directory(
                _declared_git_directory_path(
                    git_dir,
                    common_line,
                    allow_absolute=False,
                    allow_parent_components=True,
                )
            )
            if (
                git_dir.parent.name != "worktrees"
                or git_dir.parent.parent != common_dir
                or not git_dir.name
            ):
                _invalid_trusted_repository_head()

        head_payload = _read_strict_git_metadata_file(
            git_dir / "HEAD", maximum_bytes=4096
        )
        if head_payload is None:
            _invalid_trusted_repository_head()
        kind, value = _parse_git_reference_line(head_payload)
        if kind == "head":
            return value

        loose_roots = (
            (git_dir, common_dir) if git_dir != common_dir else (common_dir,)
        )
        packed_refs: dict[str, str] | None = None
        seen: set[str] = set()
        ref_name = value
        for _hop in range(_GIT_SYMBOLIC_REF_LIMIT):
            if ref_name in seen or not _valid_git_ref_name(ref_name):
                _invalid_trusted_repository_head()
            seen.add(ref_name)
            loose_payloads = tuple(
                payload
                for loose_root in loose_roots
                if (
                    payload := _read_strict_git_metadata_file(
                        loose_root.joinpath(*ref_name.split("/")),
                        allow_missing=True,
                        maximum_bytes=4096,
                    )
                )
                is not None
            )
            if len(loose_payloads) > 1:
                _invalid_trusted_repository_head()
            if loose_payloads:
                kind, value = _parse_git_reference_line(loose_payloads[0])
                if kind == "head":
                    return value
                ref_name = value
                continue
            if packed_refs is None:
                packed_refs = _parse_packed_refs(
                    _read_strict_git_metadata_file(
                        common_dir / "packed-refs", allow_missing=True
                    )
                )
            packed_head = packed_refs.get(ref_name)
            if packed_head is None:
                _invalid_trusted_repository_head()
            return packed_head
        _invalid_trusted_repository_head()
    except CliMisuseError:
        raise
    except (OSError, RuntimeError, TypeError, ValueError):
        _invalid_trusted_repository_head()


def capture_resources(repo_root: Path) -> ResourceSnapshot:
    """Capture every protected repository resource without mutating it."""

    root = Path(repo_root).resolve()
    database = database_snapshot(root / "data" / "duck_diary.db")
    log = file_snapshot(root / "logs" / "app.log")
    tts = directory_snapshot(root / "data" / "tts_cache")
    media = directory_snapshot(root / "data" / "media")
    user_paths = tuple(
        _protected_path_snapshot(root, relative_path)
        for relative_path in PROTECTED_USER_PATHS
    )
    reasons: list[str] = [f"DATABASE:{reason}" for reason in database.unsafe_reasons]
    if log.kind is not FileKind.REGULAR:
        reasons.append("LOG_NOT_REGULAR")
    reasons.extend(f"TTS:{reason}" for reason in tts.unsafe_reasons)
    reasons.extend(
        f"MEDIA:{reason}"
        for reason in media.unsafe_reasons
        if reason != "DIRECTORY_MISSING"
    )
    for protected in user_paths:
        reasons.extend(
            f"USER_PATH:{protected.relative_path}:{reason}"
            for reason in protected.unsafe_reasons
            if reason != "PATH_MISSING"
        )

    head_returncode, head_bytes = _git_capture(root, "rev-parse", "HEAD")
    status_returncode, status_bytes = _git_capture(
        root, "status", "--porcelain=v1", "-z", "--untracked-files=all"
    )
    git_head = None
    if head_returncode == 0:
        try:
            candidate_head = head_bytes.strip().decode("ascii")
        except UnicodeDecodeError:
            candidate_head = ""
        if re.fullmatch(r"[0-9a-f]{40}", candidate_head) is not None:
            git_head = candidate_head
    if git_head is None:
        reasons.append("GIT_HEAD_UNAVAILABLE")
    git_porcelain = status_bytes if status_returncode == 0 else None
    if status_returncode != 0:
        reasons.append("GIT_STATUS_UNAVAILABLE")
    return ResourceSnapshot(
        database=database,
        log=log,
        tts=tts,
        media=media,
        user_paths=user_paths,
        git_head=git_head,
        git_porcelain=git_porcelain,
        unsafe_reasons=tuple(dict.fromkeys(reasons)),
    )


def _snapshot_is_unsafe(snapshot: object) -> bool:
    if isinstance(snapshot, Mapping):
        return bool(snapshot.get("unsafe_reasons", ()))
    return bool(getattr(snapshot, "unsafe_reasons", ()))


def _snapshot_git_head(snapshot: object) -> object:
    if isinstance(snapshot, Mapping):
        return snapshot.get("git_head")
    return getattr(snapshot, "git_head", None)


def _snapshots_are_unchanged(before: object, after: object) -> bool:
    return bool(
        before is not None
        and after is not None
        and not _snapshot_is_unsafe(before)
        and not _snapshot_is_unsafe(after)
        and before == after
    )


def _timeout_buffer(value: object) -> bytes:
    if value is None:
        return b""
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8", errors="replace")
    return bytes(value)


def _group_alive_state(executor, pgid: int) -> bool | None:
    try:
        return bool(executor.group_alive(pgid))
    except ProcessLookupError:
        return False
    except OSError:
        return None


def _signal_group(action, pgid: int) -> bool:
    try:
        action(pgid)
    except ProcessLookupError:
        return True
    except OSError:
        return False
    return True


def _wait_for_group_extinction(executor, pgid: int, deadline: float) -> bool:
    while _group_alive_state(executor, pgid) is not False:
        remaining = deadline - executor.monotonic()
        if remaining <= 0:
            return False
        executor.sleep(min(0.05, remaining))
    return True


def _apply_after_snapshot(
    *,
    before_snapshot: object,
    after_snapshot: object,
    outcome: ClassifiedOutcome,
    reason: str,
) -> tuple[ClassifiedOutcome, str]:
    if not _snapshots_are_unchanged(before_snapshot, after_snapshot):
        return ClassifiedOutcome.SAFETY_FAILURE, "RESOURCE_DRIFT"
    return outcome, reason


_CAPTURE_COMMAND_BASELINE = object()


def run_command(
    spec: CommandSpec,
    *,
    env: Mapping[str, str],
    executor,
    before_snapshot: object = _CAPTURE_COMMAND_BASELINE,
) -> CommandResult:
    """Run one spec synchronously and contain its entire process group."""

    if before_snapshot is _CAPTURE_COMMAND_BASELINE:
        try:
            before_snapshot = executor.capture_resources()
        except ResourceCaptureError:
            return CommandResult(
                subcommand=spec.command_id,
                child_started=False,
                child_exit=None,
                termination=Termination.NOT_STARTED,
                output_complete=None,
                residual_group_observed=False,
                cleanup_failures=(),
                classified_outcome=ClassifiedOutcome.SAFETY_FAILURE,
                reason="RESOURCE_BASELINE_UNAVAILABLE",
                before_snapshot=None,
                after_snapshot=None,
            )
    else:
        current_snapshot = executor.capture_resources()
        if (
            _snapshot_is_unsafe(current_snapshot)
            or current_snapshot != before_snapshot
        ):
            return CommandResult(
                subcommand=spec.command_id,
                child_started=False,
                child_exit=None,
                termination=Termination.NOT_STARTED,
                output_complete=None,
                residual_group_observed=False,
                cleanup_failures=(),
                classified_outcome=ClassifiedOutcome.SAFETY_FAILURE,
                reason="RESOURCE_DRIFT",
                before_snapshot=before_snapshot,
                after_snapshot=current_snapshot,
            )
    if _snapshot_is_unsafe(before_snapshot):
        return CommandResult(
            subcommand=spec.command_id,
            child_started=False,
            child_exit=None,
            termination=Termination.NOT_STARTED,
            output_complete=None,
            residual_group_observed=False,
            cleanup_failures=(),
            classified_outcome=ClassifiedOutcome.SAFETY_FAILURE,
            reason="RESOURCE_BASELINE_UNAVAILABLE",
            before_snapshot=None,
            after_snapshot=None,
        )

    command_started_at = executor.monotonic()
    try:
        process = executor.start(spec, env)
    except OSError:
        after_snapshot = executor.capture_resources()
        outcome, reason = _apply_after_snapshot(
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
            outcome=ClassifiedOutcome.TECHNICAL_FAILURE,
            reason="SPAWN_FAILED",
        )
        return CommandResult(
            subcommand=spec.command_id,
            child_started=False,
            child_exit=None,
            termination=Termination.SPAWN_FAILED,
            output_complete=None,
            residual_group_observed=False,
            cleanup_failures=(),
            classified_outcome=outcome,
            reason=reason,
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
            duration_seconds=max(0.0, executor.monotonic() - command_started_at),
        )

    pgid = process.pid

    stdout = b""
    stderr = b""
    child_exit: int | None = None
    termination = Termination.EXITED
    output_complete = True
    residual_observed = False
    cleanup_failures: tuple[CleanupFailure, ...] = ()
    after_snapshot = None
    outcome = ClassifiedOutcome.TECHNICAL_FAILURE
    reason = "COMMAND_FAILURE"

    try:
        stdout, stderr = executor.communicate(process, spec.timeout_seconds)
    except subprocess.TimeoutExpired as initial_timeout:
        termination = Termination.TIMED_OUT
        stdout = _timeout_buffer(initial_timeout.output)
        stderr = _timeout_buffer(initial_timeout.stderr)
        _signal_group(executor.terminate_group, pgid)
        term_complete = False
        try:
            stdout, stderr = executor.communicate(process, 5)
            term_complete = True
        except subprocess.TimeoutExpired as term_timeout:
            stdout = _timeout_buffer(term_timeout.output)
            stderr = _timeout_buffer(term_timeout.stderr)

        child_exit = executor.poll(process)
        term_group_extinct = (
            term_complete and _group_alive_state(executor, pgid) is False
        )
        if term_complete and term_group_extinct and child_exit is not None:
            after_snapshot = executor.capture_resources()
            outcome, reason = _apply_after_snapshot(
                before_snapshot=before_snapshot,
                after_snapshot=after_snapshot,
                outcome=ClassifiedOutcome.TECHNICAL_FAILURE,
                reason="COMMAND_TIMEOUT",
            )
        else:
            _signal_group(executor.kill_group, pgid)
            final_deadline = executor.monotonic() + 5
            final_complete = False
            remaining = max(0.0, final_deadline - executor.monotonic())
            try:
                stdout, stderr = executor.communicate(process, remaining)
                final_complete = True
            except subprocess.TimeoutExpired as final_timeout:
                stdout = _timeout_buffer(final_timeout.output)
                stderr = _timeout_buffer(final_timeout.stderr)
            child_exit = executor.poll(process)
            group_extinct = _wait_for_group_extinction(executor, pgid, final_deadline)
            failures: list[CleanupFailure] = []
            if not final_complete:
                failures.append(CleanupFailure.PIPE_DRAIN_TIMEOUT)
            if child_exit is None:
                failures.append(CleanupFailure.LEADER_UNREAPED)
            if not group_extinct:
                failures.append(CleanupFailure.GROUP_SURVIVED)
            cleanup_failures = tuple(failures)
            if cleanup_failures:
                output_complete = False
                outcome = ClassifiedOutcome.SAFETY_FAILURE
                reason = "PROCESS_CLEANUP_INCOMPLETE"
            else:
                after_snapshot = executor.capture_resources()
                outcome, reason = _apply_after_snapshot(
                    before_snapshot=before_snapshot,
                    after_snapshot=after_snapshot,
                    outcome=ClassifiedOutcome.TECHNICAL_FAILURE,
                    reason="COMMAND_TIMEOUT",
                )
    else:
        child_exit = executor.poll(process)
        if child_exit is None:
            output_complete = False
            cleanup_failures = (CleanupFailure.LEADER_UNREAPED,)
            outcome = ClassifiedOutcome.SAFETY_FAILURE
            reason = "PROCESS_CLEANUP_INCOMPLETE"
        else:
            termination = Termination.SIGNALED if child_exit < 0 else Termination.EXITED
            group_state = _group_alive_state(executor, pgid)
            if group_state is not False:
                residual_observed = True
                _signal_group(executor.terminate_group, pgid)
                extinct = _wait_for_group_extinction(
                    executor, pgid, executor.monotonic() + 5
                )
                if not extinct:
                    _signal_group(executor.kill_group, pgid)
                    extinct = _wait_for_group_extinction(
                        executor, pgid, executor.monotonic() + 5
                    )
                if not extinct:
                    output_complete = False
                    cleanup_failures = (CleanupFailure.GROUP_SURVIVED,)
                    outcome = ClassifiedOutcome.SAFETY_FAILURE
                    reason = "PROCESS_CLEANUP_INCOMPLETE"
                else:
                    after_snapshot = executor.capture_resources()
                    outcome, reason = _apply_after_snapshot(
                        before_snapshot=before_snapshot,
                        after_snapshot=after_snapshot,
                        outcome=ClassifiedOutcome.SAFETY_FAILURE,
                        reason="RESIDUAL_PROCESS_GROUP",
                    )
            else:
                after_snapshot = executor.capture_resources()
                if child_exit == 0:
                    outcome = ClassifiedOutcome.SUCCESS
                    reason = "SUCCESS"
                elif child_exit > 0:
                    outcome = ClassifiedOutcome.CHILD_NONZERO
                    reason = "CHILD_NONZERO"
                else:
                    outcome = ClassifiedOutcome.TECHNICAL_FAILURE
                    reason = "CHILD_SIGNALED"
                outcome, reason = _apply_after_snapshot(
                    before_snapshot=before_snapshot,
                    after_snapshot=after_snapshot,
                    outcome=outcome,
                    reason=reason,
                )

    try:
        executor.write_streams(spec.command_id, stdout, stderr)
    except OSError:
        if outcome is not ClassifiedOutcome.SAFETY_FAILURE:
            outcome = ClassifiedOutcome.TECHNICAL_FAILURE
            reason = "ARTIFACT_WRITE_FAILED"

    if output_complete:
        after_snapshot = executor.capture_resources()
        outcome, reason = _apply_after_snapshot(
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
            outcome=outcome,
            reason=reason,
        )
    return CommandResult(
        subcommand=spec.command_id,
        child_started=True,
        child_exit=child_exit,
        termination=termination,
        output_complete=output_complete,
        residual_group_observed=residual_observed,
        cleanup_failures=cleanup_failures,
        classified_outcome=outcome,
        reason=reason,
        before_snapshot=before_snapshot,
        after_snapshot=after_snapshot,
        stdout=stdout,
        stderr=stderr,
        duration_seconds=max(0.0, executor.monotonic() - command_started_at),
    )


def run_commands_serial(
    specs: tuple[CommandSpec, ...], *, env: Mapping[str, str], executor
) -> tuple[CommandResult, ...]:
    results: list[CommandResult] = []
    for spec in specs:
        result = run_command(spec, env=env, executor=executor)
        results.append(result)
        if result.classified_outcome is not ClassifiedOutcome.SUCCESS:
            break
    return tuple(results)


class PopenProcessExecutor:
    """Production shell-free process-group executor."""

    def __init__(self, repo_root: Path, command_artifact_root: Path):
        self.repo_root = Path(repo_root).resolve()
        self.command_artifact_root = Path(command_artifact_root).resolve()

    def capture_resources(self) -> ResourceSnapshot:
        return capture_resources(self.repo_root)

    def start(self, spec: CommandSpec, env: Mapping[str, str]):
        return subprocess.Popen(
            spec.argv,
            cwd=self.repo_root,
            env=dict(env),
            shell=False,
            start_new_session=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    @staticmethod
    def get_pgid(process) -> int:
        return os.getpgid(process.pid)

    @staticmethod
    def communicate(process, timeout: float):
        return process.communicate(timeout=timeout)

    @staticmethod
    def poll(process):
        return process.poll()

    @staticmethod
    def group_alive(pgid: int) -> bool:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return False
        return True

    @staticmethod
    def terminate_group(pgid: int) -> None:
        try:
            os.killpg(pgid, 15)
        except ProcessLookupError:
            pass

    @staticmethod
    def kill_group(pgid: int) -> None:
        try:
            os.killpg(pgid, 9)
        except ProcessLookupError:
            pass

    @staticmethod
    def monotonic() -> float:
        return time.monotonic()

    @staticmethod
    def sleep(seconds: float) -> None:
        time.sleep(seconds)

    def write_streams(self, command_id: str, stdout: bytes, stderr: bytes) -> None:
        command_dir = self.command_artifact_root / "commands"
        command_dir.mkdir(parents=True, exist_ok=True)
        try:
            order = tuple(COMMAND_TIMEOUTS).index(command_id) + 1
        except ValueError as error:
            raise OSError("unknown command artifact ID") from error
        prefix = f"{order:02d}-{command_id}"
        (command_dir / f"{prefix}.stdout.log").write_bytes(stdout)
        (command_dir / f"{prefix}.stderr.log").write_bytes(stderr)


BROWSER_COMMAND_IDS = frozenset(
    {
        "browser",
        "release_focus_1024",
        "release_focus_all",
        "teacher_accessibility_full",
        "release_db_action_1024",
        "release_db_action_all",
        "review_identity_1024",
        "review_identity_all",
        "child_chat_timeout_1024",
        "child_chat_timeout_all",
        "child_completion_delay_1024",
        "child_completion_delay_all",
        "child_keyboard_core_1024",
        "child_keyboard_core_all",
        "today_three_status_1024",
        "today_three_status_all",
    }
)


def validate_runtime_version(repo_root: Path) -> bool:
    try:
        payload = json.loads(
            (Path(repo_root) / "app" / "version.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return False
    return payload == FROZEN_RUNTIME_VERSION


def _not_started_result(
    command_id: str,
    *,
    outcome: ClassifiedOutcome,
    reason: str,
    before_snapshot: object | None,
    after_snapshot: object | None,
) -> CommandResult:
    return CommandResult(
        subcommand=command_id,
        child_started=False,
        child_exit=None,
        termination=Termination.NOT_STARTED,
        output_complete=None,
        residual_group_observed=False,
        cleanup_failures=(),
        classified_outcome=outcome,
        reason=reason,
        before_snapshot=before_snapshot,
        after_snapshot=after_snapshot,
    )


def run_one_command(
    command_id: str,
    *,
    repo_root: Path,
    artifact_root: Path,
    parent_env: Mapping[str, str],
    executor,
    expected_head: str = FROZEN_START_HEAD,
    version_validator=validate_runtime_version,
) -> RunOneResult:
    """Run exactly one frozen ID with baseline, preflight, and strict evidence."""

    root = Path(repo_root).resolve()
    artifacts = Path(artifact_root).resolve()
    specs = build_command_specs(root, artifacts)
    by_id = {spec.command_id: spec for spec in specs}
    if command_id not in by_id:
        result = _not_started_result(
            command_id,
            outcome=ClassifiedOutcome.CLI_MISUSE,
            reason="CLI_MISUSE",
            before_snapshot=None,
            after_snapshot=None,
        )
        return RunOneResult(64, result, None)

    try:
        baseline = executor.capture_resources()
    except ResourceCaptureError:
        baseline = None
    if baseline is None:
        result = _not_started_result(
            command_id,
            outcome=ClassifiedOutcome.SAFETY_FAILURE,
            reason="RESOURCE_BASELINE_UNAVAILABLE",
            before_snapshot=None,
            after_snapshot=None,
        )
        return RunOneResult(3, result, None)
    if _snapshot_is_unsafe(baseline):
        result = _not_started_result(
            command_id,
            outcome=ClassifiedOutcome.SAFETY_FAILURE,
            reason="RESOURCE_BASELINE_UNAVAILABLE",
            before_snapshot=None,
            after_snapshot=None,
        )
        return RunOneResult(3, result, None)

    if getattr(baseline, "git_head", None) != expected_head or not version_validator(
        root
    ):
        after_snapshot = executor.capture_resources()
        outcome, reason = _apply_after_snapshot(
            before_snapshot=baseline,
            after_snapshot=after_snapshot,
            outcome=ClassifiedOutcome.TECHNICAL_FAILURE,
            reason="WRONG_HEAD_OR_VERSION",
        )
        result = _not_started_result(
            command_id,
            outcome=outcome,
            reason=reason,
            before_snapshot=baseline,
            after_snapshot=after_snapshot,
        )
        return RunOneResult(_command_runner_exit(result), result, None)

    spec = by_id[command_id]
    sanitized_env = build_sanitized_env(
        parent_env, browser=command_id in BROWSER_COMMAND_IDS
    )
    result = run_command(
        spec,
        env=sanitized_env,
        executor=executor,
        before_snapshot=baseline,
    )
    evidence = None
    if spec.evidence_format is EvidenceFormat.JUNIT:
        try:
            junit_payload = spec.evidence_path.read_bytes()
        except OSError:
            junit_payload = b""
        evidence = parse_pytest_junit_bytes(
            junit_payload,
            stderr_payload=result.stderr,
            command_id=spec.command_id,
            require_tripwire_auth=(
                spec.conftest_mode is ConftestMode.PROJECT
            ),
        )
    elif result.classified_outcome is ClassifiedOutcome.SUCCESS:
        if spec.evidence_format is EvidenceFormat.TAP:
            evidence = parse_node_tap(result.stdout)
    if (
        evidence is not None
        and evidence.tripwire_events
        and result.classified_outcome is not ClassifiedOutcome.SAFETY_FAILURE
    ):
        result = replace(
            result,
            classified_outcome=ClassifiedOutcome.SAFETY_FAILURE,
            reason="TRIPWIRE_FAILURE",
        )
    elif result.classified_outcome is ClassifiedOutcome.SUCCESS:
        if evidence is None or not evidence.valid:
            evidence_reason = "MISSING" if evidence is None else evidence.reason
            result = replace(
                result,
                classified_outcome=ClassifiedOutcome.TECHNICAL_FAILURE,
                reason=f"INVALID_EVIDENCE:{evidence_reason}",
            )
    return RunOneResult(_command_runner_exit(result), result, evidence)


def _resource_artifact_bytes(snapshot: object) -> bytes:
    canonical = _canonical_value(snapshot)
    if not isinstance(canonical, Mapping):
        raise TypeError("resource snapshot must serialize as an object")
    return canonical_json_bytes(canonical)


def _run_internal_evidence(
    *,
    command_results: tuple[CommandResult, ...],
    all_evidence: Mapping[str, SuiteEvidence],
    baseline: object,
    final_snapshot: object,
    version_exact: bool,
) -> tuple[InternalEvidence, ...]:
    resources_equal = (
        not _snapshot_is_unsafe(final_snapshot)
        and final_snapshot == baseline
        and all(
            result.before_snapshot is not None
            and result.after_snapshot is not None
            and not _snapshot_is_unsafe(result.after_snapshot)
            and result.before_snapshot == baseline
            and result.after_snapshot == baseline
            for result in command_results
        )
    )
    browser = all_evidence.get("browser")
    browser_db = all_evidence.get("release_db_action_all")
    tripwire = _tripwire_internal_evidence(
        _tripwire_status(_tripwire_event_ids(all_evidence), browser)
    )
    return (
        InternalEvidence(
            "resource",
            "global_and_per_command_logical_and_physical_equality",
            resources_equal,
            True,
            resources_equal,
        ),
        InternalEvidence(
            "resource",
            "inherited_user_paths_and_git_porcelain_equal",
            resources_equal,
            True,
            resources_equal,
        ),
        InternalEvidence(
            "runtime",
            "tested_head_api_schema_and_release_versions_exact",
            version_exact,
            True,
            version_exact,
        ),
        tripwire,
        InternalEvidence(
            "browser_db",
            "exact_fixture_path_and_read_only_zero_to_one_business_row",
            browser_db is not None and browser_db.valid,
            browser_db is not None,
            browser_db is not None and browser_db.valid,
        ),
    )


def _tripwire_events_for_evidence(
    evidence: SuiteEvidence | None,
) -> tuple[str, ...]:
    if evidence is None:
        return ()
    observed = {item.event_id for item in evidence.tripwire_events}
    return tuple(event_id for event_id in TRIPWIRE_EVENT_IDS if event_id in observed)


def _tripwire_event_ids(
    suites: Mapping[str, SuiteEvidence],
) -> tuple[str, ...]:
    observed = {
        event_id
        for evidence in suites.values()
        for event_id in _tripwire_events_for_evidence(evidence)
    }
    return tuple(event_id for event_id in TRIPWIRE_EVENT_IDS if event_id in observed)


def _tripwire_status(
    events: tuple[str, ...], browser_evidence: SuiteEvidence | None
) -> str:
    if events:
        return "FAIL"
    if browser_evidence is not None and browser_evidence.valid:
        return "PASS"
    return "NOT_PROVEN"


def _tripwire_internal_evidence(status: str) -> InternalEvidence:
    proven = status != "NOT_PROVEN"
    return InternalEvidence(
        "tripwire",
        "provider_tts_socket_context_and_worker_tripwires_clean",
        status == "PASS",
        proven,
        proven,
    )


def _tripwire_was_observed(suites: Mapping[str, SuiteEvidence]) -> bool:
    return bool(_tripwire_event_ids(suites))


def _acceptance_decision(
    *,
    command_results: tuple[CommandResult, ...],
    all_evidence: Mapping[str, SuiteEvidence],
    baseline: object,
    final_snapshot: object,
    version_exact: bool,
    lovable_complete_or_waived: bool,
    inventory_exact: bool,
) -> tuple[DecisionResult, tuple[GateResult, ...], tuple[InternalEvidence, ...]]:
    internal = _run_internal_evidence(
        command_results=command_results,
        all_evidence=all_evidence,
        baseline=baseline,
        final_snapshot=final_snapshot,
        version_exact=version_exact,
    )
    manifest_commands = {row.command_id for row in SELECTOR_MANIFEST}
    evidence_map = EvidenceMap(
        suites={
            command_id: evidence
            for command_id, evidence in all_evidence.items()
            if command_id in manifest_commands
        },
        internal=internal,
    )
    gates = evaluate_gates(command_results, final_snapshot, evidence_map)
    resources_unchanged = (
        _snapshots_are_unchanged(baseline, final_snapshot)
        and all(
            _snapshots_are_unchanged(
                result.before_snapshot, result.after_snapshot
            )
            for result in command_results
        )
    )
    decision = decide_release(
        DecisionInputs(
            command_results=command_results,
            gate_results=gates,
            resources_unchanged=resources_unchanged,
            tripwires_clean=not _tripwire_was_observed(all_evidence),
            contrast_passed=True,
            incident_decisions=None,
            lovable_complete_or_waived=lovable_complete_or_waived,
        )
    )
    record_integrity = (
        inventory_exact
        and tuple(result.subcommand for result in command_results)
        == tuple(COMMAND_TIMEOUTS)
        and set(all_evidence) == set(COMMAND_TIMEOUTS)
        and all(
            evidence.valid and evidence.total > 0
            for evidence in all_evidence.values()
        )
    )
    if record_integrity:
        try:
            _validate_pending_structured_properties(all_evidence)
        except CliMisuseError:
            record_integrity = False
    if (
        decision.outcome
        is DecisionOutcome.TECHNICAL_PASS_HUMAN_DECISION_PENDING
        and not record_integrity
    ):
        decision = DecisionResult(
            DecisionOutcome.TECHNICAL_NO_GO,
            1,
            ("REPORT_INTEGRITY_FAILURE",),
        )
    return decision, gates, internal


def _write_completed_run_artifacts(
    *,
    artifact_root: Path,
    record: dict[str, object],
    before_bytes: bytes,
    after_bytes: bytes,
) -> dict[str, object]:
    before_path = artifact_root / "resources.before.json"
    after_path = artifact_root / "resources.after.json"
    before_path.write_bytes(before_bytes)
    after_path.write_bytes(after_bytes)
    record["resource_artifacts"] = {
        "after": _binary_artifact_record("resources.after.json", after_bytes),
        "before": _binary_artifact_record("resources.before.json", before_bytes),
    }
    markdown_bytes = render_report_markdown(record).encode("utf-8")
    record["report_markdown"] = _binary_artifact_record(
        "report.md", markdown_bytes
    )
    if render_report_markdown(record).encode("utf-8") != markdown_bytes:
        raise RuntimeError("report metadata changed one-way Markdown rendering")
    (artifact_root / "report.md").write_bytes(markdown_bytes)
    (artifact_root / "report.json").write_bytes(canonical_json_bytes(record))
    return record


def _discard_incomplete_report_artifacts(artifact_root: Path) -> bool:
    """Remove only untrusted completed-report outputs after a failed write."""

    removed = True
    for name in ("report.json", "report.md"):
        try:
            (artifact_root / name).unlink(missing_ok=True)
        except OSError:
            removed = False
    return removed


def _merge_completed_artifact_failure(
    decision: DecisionResult,
    error: BaseException,
    *,
    resources_drifted: bool,
    artifact_cleanup_complete: bool,
) -> DecisionResult:
    """Keep an established safety outcome monotonic across report failures."""

    artifact_reason = (
        "ARTIFACT_WRITE_FAILED"
        if isinstance(error, OSError)
        else "REPORT_INTEGRITY_FAILURE"
    )
    if (
        decision.outcome is DecisionOutcome.SAFETY_NO_GO
        or resources_drifted
    ):
        reasons = list(decision.reasons)
        if resources_drifted and "RESOURCE_DRIFT" not in reasons:
            reasons.insert(0, "RESOURCE_DRIFT")
        if artifact_reason not in reasons:
            reasons.append(artifact_reason)
        if not artifact_cleanup_complete:
            reasons.append("ARTIFACT_CLEANUP_FAILED")
        return DecisionResult(
            DecisionOutcome.SAFETY_NO_GO,
            3,
            tuple(reasons),
        )
    reasons = [artifact_reason]
    if not artifact_cleanup_complete:
        reasons.append("ARTIFACT_CLEANUP_FAILED")
    return DecisionResult(
        DecisionOutcome.TECHNICAL_NO_GO,
        1,
        tuple(reasons),
    )


def run_acceptance(
    *,
    repo_root: Path,
    artifact_root: Path,
    run_id: str,
    generated_at: str,
    parent_env: Mapping[str, str],
    executor,
    expected_head: str,
    specs: tuple[CommandSpec, ...] | None = None,
    version_validator=validate_runtime_version,
    lovable_complete_or_waived: bool | None = None,
) -> AcceptanceRunResult:
    """Run a frozen inventory serially and persist only ignored evidence."""

    root = Path(repo_root).resolve()
    artifacts = Path(artifact_root).resolve()
    try:
        baseline = executor.capture_resources()
    except ResourceCaptureError:
        baseline = None
    if baseline is None or _snapshot_is_unsafe(baseline):
        decision = DecisionResult(
            DecisionOutcome.SAFETY_NO_GO,
            3,
            ("RESOURCE_BASELINE_UNAVAILABLE",),
        )
        return AcceptanceRunResult(3, run_id, artifacts, decision, (), None)

    tested_head = getattr(baseline, "git_head", None)
    head_version_exact = bool(
        isinstance(tested_head, str)
        and re.fullmatch(r"[0-9a-f]{40}", expected_head)
        and tested_head == expected_head
        and version_validator(root)
    )
    porcelain = getattr(baseline, "git_porcelain", None)
    implementation_tree_clean = unit8_porcelain_is_allowed(porcelain)
    if not head_version_exact or not implementation_tree_clean:
        after_snapshot = executor.capture_resources()
        resources_drifted = (
            _snapshot_is_unsafe(after_snapshot) or after_snapshot != baseline
        )
        technical_reason = (
            "WRONG_HEAD_OR_VERSION"
            if not head_version_exact
            else "DIRTY_IMPLEMENTATION_TREE"
        )
        decision = DecisionResult(
            (
                DecisionOutcome.SAFETY_NO_GO
                if resources_drifted
                else DecisionOutcome.TECHNICAL_NO_GO
            ),
            3 if resources_drifted else 1,
            ("RESOURCE_DRIFT" if resources_drifted else technical_reason,),
        )
        return AcceptanceRunResult(
            decision.exit_code, run_id, artifacts, decision, (), None
        )

    try:
        artifacts.mkdir(parents=True, exist_ok=False)
        (artifacts / "commands").mkdir()
    except OSError:
        after_snapshot = executor.capture_resources()
        resources_drifted = (
            _snapshot_is_unsafe(after_snapshot) or after_snapshot != baseline
        )
        decision = DecisionResult(
            (
                DecisionOutcome.SAFETY_NO_GO
                if resources_drifted
                else DecisionOutcome.TECHNICAL_NO_GO
            ),
            3 if resources_drifted else 1,
            ("RESOURCE_DRIFT" if resources_drifted else "ARTIFACT_WRITE_FAILED",),
        )
        return AcceptanceRunResult(
            decision.exit_code, run_id, artifacts, decision, (), None
        )

    before_bytes = _resource_artifact_bytes(baseline)
    try:
        (artifacts / "resources.before.json").write_bytes(before_bytes)
    except OSError:
        after_snapshot = executor.capture_resources()
        resources_drifted = (
            _snapshot_is_unsafe(after_snapshot) or after_snapshot != baseline
        )
        decision = DecisionResult(
            (
                DecisionOutcome.SAFETY_NO_GO
                if resources_drifted
                else DecisionOutcome.TECHNICAL_NO_GO
            ),
            3 if resources_drifted else 1,
            ("RESOURCE_DRIFT" if resources_drifted else "ARTIFACT_WRITE_FAILED",),
        )
        return AcceptanceRunResult(
            decision.exit_code, run_id, artifacts, decision, (), None
        )

    frozen_specs = specs if specs is not None else build_command_specs(root, artifacts)
    inventory_exact = frozen_specs == build_command_specs(root, artifacts)
    command_results: list[CommandResult] = []
    all_evidence: dict[str, SuiteEvidence] = {}
    junit_payloads: dict[str, bytes] = {}

    for order, spec in enumerate(frozen_specs, start=1):
        sanitized = build_sanitized_env(
            parent_env, browser=spec.command_id in BROWSER_COMMAND_IDS
        )
        result = run_command(
            spec,
            env=sanitized,
            executor=executor,
            before_snapshot=baseline,
        )
        if (
            result.output_complete is False
            or result.after_snapshot is None
            or result.cleanup_failures
        ):
            command_results.append(result)
            decision = DecisionResult(
                DecisionOutcome.SAFETY_NO_GO,
                3,
                ("COMMAND_SAFETY_FAILURE",),
            )
            return AcceptanceRunResult(
                3,
                run_id,
                artifacts,
                decision,
                tuple(command_results),
                None,
            )
        evidence = None
        if spec.evidence_format is EvidenceFormat.JUNIT:
            command_junit = (
                artifacts
                / "commands"
                / f"{order:02d}-{spec.command_id}.junit.xml"
            )
            source = spec.evidence_path
            try:
                if not command_junit.is_file() and source is not None and source.is_file():
                    command_junit.write_bytes(source.read_bytes())
                if command_junit.is_file():
                    junit_payloads[spec.command_id] = command_junit.read_bytes()
                if (
                    source is not None
                    and source != command_junit
                    and source.is_file()
                ):
                    source.unlink()
            except OSError:
                if result.classified_outcome is not ClassifiedOutcome.SAFETY_FAILURE:
                    result = replace(
                        result,
                        classified_outcome=ClassifiedOutcome.TECHNICAL_FAILURE,
                        reason="ARTIFACT_WRITE_FAILED",
                    )
            junit_payload = junit_payloads.get(spec.command_id)
            if junit_payload is not None:
                evidence = parse_pytest_junit_bytes(
                    junit_payload,
                    stderr_payload=result.stderr,
                    command_id=spec.command_id,
                    require_tripwire_auth=(
                        spec.conftest_mode is ConftestMode.PROJECT
                    ),
                )
                all_evidence[spec.command_id] = evidence
        elif result.classified_outcome is ClassifiedOutcome.SUCCESS:
            evidence = parse_node_tap(result.stdout)
            all_evidence[spec.command_id] = evidence

        if (
            evidence is not None
            and evidence.tripwire_events
            and result.classified_outcome is ClassifiedOutcome.SUCCESS
        ):
            result = replace(
                result,
                classified_outcome=ClassifiedOutcome.SAFETY_FAILURE,
                reason="TRIPWIRE_FAILURE",
            )
        elif (
            result.classified_outcome is ClassifiedOutcome.SUCCESS
            and (evidence is None or not evidence.valid)
        ):
            evidence_reason = "MISSING" if evidence is None else evidence.reason
            result = replace(
                result,
                classified_outcome=ClassifiedOutcome.TECHNICAL_FAILURE,
                reason=f"INVALID_EVIDENCE:{evidence_reason}",
            )

        command_results.append(result)
        if result.classified_outcome is not ClassifiedOutcome.SUCCESS:
            break

    results_tuple = tuple(command_results)
    final_snapshot = executor.capture_resources()
    if (
        (_snapshot_is_unsafe(final_snapshot) or final_snapshot != baseline)
        and results_tuple
        and results_tuple[-1].after_snapshot is not None
    ):
        results_tuple = results_tuple[:-1] + (
            replace(
                results_tuple[-1],
                classified_outcome=ClassifiedOutcome.SAFETY_FAILURE,
                reason="RESOURCE_DRIFT",
                after_snapshot=final_snapshot,
            ),
        )

    del lovable_complete_or_waived
    lovable_complete = _verified_lovable_reference_is_valid(artifacts)
    decision, gates, internal = _acceptance_decision(
        command_results=results_tuple,
        all_evidence=all_evidence,
        baseline=baseline,
        final_snapshot=final_snapshot,
        version_exact=head_version_exact,
        lovable_complete_or_waived=lovable_complete,
        inventory_exact=inventory_exact,
    )
    after_bytes = _resource_artifact_bytes(final_snapshot)
    record = build_report_record(
        run_id=run_id,
        generated_at=generated_at,
        tested_head=tested_head,
        decision=decision,
        command_results=results_tuple,
        command_specs=frozen_specs,
        gate_results=gates,
        lovable_status="PROVIDED_OR_WAIVED" if lovable_complete else "MISSING",
        external_decision=None,
        junit_payloads=junit_payloads,
        suite_evidence=all_evidence,
        internal_evidence=internal,
        baseline_snapshot=baseline,
        final_snapshot=final_snapshot,
    )
    try:
        record = _write_completed_run_artifacts(
            artifact_root=artifacts,
            record=record,
            before_bytes=before_bytes,
            after_bytes=after_bytes,
        )
    except (OSError, CliMisuseError, RuntimeError, TypeError) as error:
        post_failure_snapshot = executor.capture_resources()
        resources_drifted = (
            _snapshot_is_unsafe(post_failure_snapshot)
            or post_failure_snapshot != baseline
        )
        artifact_decision = _merge_completed_artifact_failure(
            decision,
            error,
            resources_drifted=resources_drifted,
            artifact_cleanup_complete=_discard_incomplete_report_artifacts(
                artifacts
            ),
        )
        return AcceptanceRunResult(
            artifact_decision.exit_code,
            run_id,
            artifacts,
            artifact_decision,
            results_tuple,
            None,
        )

    post_artifact_snapshot = executor.capture_resources()
    if (
        _snapshot_is_unsafe(post_artifact_snapshot)
        or post_artifact_snapshot != baseline
    ):
        if results_tuple and results_tuple[-1].after_snapshot is not None:
            results_tuple = results_tuple[:-1] + (
                replace(
                    results_tuple[-1],
                    classified_outcome=ClassifiedOutcome.SAFETY_FAILURE,
                    reason="RESOURCE_DRIFT",
                    after_snapshot=post_artifact_snapshot,
                ),
            )
        decision, gates, internal = _acceptance_decision(
            command_results=results_tuple,
            all_evidence=all_evidence,
            baseline=baseline,
            final_snapshot=post_artifact_snapshot,
            version_exact=head_version_exact,
            lovable_complete_or_waived=lovable_complete,
            inventory_exact=inventory_exact,
        )
        after_bytes = _resource_artifact_bytes(post_artifact_snapshot)
        record = build_report_record(
            run_id=run_id,
            generated_at=generated_at,
            tested_head=tested_head,
            decision=decision,
            command_results=results_tuple,
            command_specs=frozen_specs,
            gate_results=gates,
            lovable_status=(
                "PROVIDED_OR_WAIVED" if lovable_complete else "MISSING"
            ),
            external_decision=None,
            junit_payloads=junit_payloads,
            suite_evidence=all_evidence,
            internal_evidence=internal,
            baseline_snapshot=baseline,
            final_snapshot=post_artifact_snapshot,
        )
        try:
            record = _write_completed_run_artifacts(
                artifact_root=artifacts,
                record=record,
                before_bytes=before_bytes,
                after_bytes=after_bytes,
            )
        except (OSError, CliMisuseError, RuntimeError, TypeError) as error:
            artifact_decision = _merge_completed_artifact_failure(
                decision,
                error,
                resources_drifted=True,
                artifact_cleanup_complete=_discard_incomplete_report_artifacts(
                    artifacts
                ),
            )
            return AcceptanceRunResult(
                3,
                run_id,
                artifacts,
                artifact_decision,
                results_tuple,
                None,
            )
        return AcceptanceRunResult(
            3, run_id, artifacts, decision, results_tuple, record
        )

    return AcceptanceRunResult(
        decision.exit_code,
        run_id,
        artifacts,
        decision,
        results_tuple,
        record,
    )


def run_full_acceptance(
    repo_root: Path, parent_env: Mapping[str, str], expected_head: str
) -> AcceptanceRunResult:
    root = Path(repo_root).resolve()
    now = datetime.now(timezone.utc)
    run_id = now.strftime("%Y%m%dT%H%M%S%fZ-task9")
    generated_at = now.isoformat(timespec="seconds").replace("+00:00", "Z")
    artifact_root = root / "artifacts" / "acceptance" / run_id
    executor = PopenProcessExecutor(root, artifact_root)
    return run_acceptance(
        repo_root=root,
        artifact_root=artifact_root,
        run_id=run_id,
        generated_at=generated_at,
        parent_env=parent_env,
        executor=executor,
        expected_head=expected_head,
    )


def _strict_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CliMisuseError("completed report JSON has duplicate keys")
        result[key] = value
    return result


def _source_stat_identity(details: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        details.st_dev,
        details.st_ino,
        details.st_mode,
        details.st_size,
        details.st_mtime_ns,
    )


def _inode_stat_identity(details: os.stat_result) -> tuple[int, int, int]:
    return (details.st_dev, details.st_ino, stat.S_IFMT(details.st_mode))


def _read_strict_completed_source(source: Path) -> tuple[Path, Path, bytes]:
    """Validate the original spelling and read one canonical regular source."""

    raw_source = os.fspath(source)
    if not isinstance(raw_source, str):
        raise CliMisuseError("completed report source path is invalid")
    source_path = Path(raw_source)
    if (
        not source_path.is_absolute()
        or os.path.normpath(raw_source) != raw_source
        or source_path.as_posix() != raw_source
        or source_path.name != "report.json"
    ):
        raise CliMisuseError("completed report source path is invalid")

    try:
        if source_path.resolve(strict=True) != source_path:
            raise CliMisuseError("completed report source path is invalid")
        for ancestor in reversed(source_path.parents):
            details = ancestor.lstat()
            if not stat.S_ISDIR(details.st_mode) or stat.S_ISLNK(details.st_mode):
                raise CliMisuseError("completed report source path is invalid")
        before = source_path.lstat()
        if not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode):
            raise CliMisuseError("completed report source path is invalid")

        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(source_path, flags)
        try:
            opened = os.fstat(descriptor)
            if (
                not stat.S_ISREG(opened.st_mode)
                or _source_stat_identity(opened) != _source_stat_identity(before)
            ):
                raise CliMisuseError("completed report source path is invalid")
            chunks = []
            while chunk := os.read(descriptor, 1024 * 1024):
                chunks.append(chunk)
        finally:
            os.close(descriptor)

        after = source_path.lstat()
        if (
            _source_stat_identity(after) != _source_stat_identity(opened)
            or source_path.resolve(strict=True) != source_path
        ):
            raise CliMisuseError("completed report source path is invalid")
        for ancestor in reversed(source_path.parents):
            details = ancestor.lstat()
            if not stat.S_ISDIR(details.st_mode) or stat.S_ISLNK(details.st_mode):
                raise CliMisuseError("completed report source path is invalid")
    except CliMisuseError:
        raise
    except OSError as error:
        raise CliMisuseError("completed report source path is invalid") from error
    return source_path, source_path.parent, b"".join(chunks)


def _prepare_strict_completed_output(
    source_path: Path, output: Path
) -> tuple[
    Path,
    Path,
    tuple[int, int, int],
    tuple[int, int, int, int, int],
    tuple[int, int, int, int, int] | None,
]:
    raw_output = os.fspath(output)
    if not isinstance(raw_output, str):
        raise CliMisuseError("completed report output path is invalid")
    output_path = Path(raw_output)
    if (
        not output_path.is_absolute()
        or os.path.normpath(raw_output) != raw_output
        or output_path.as_posix() != raw_output
        or not output_path.name
        or output_path == source_path
    ):
        raise CliMisuseError("completed report output path is invalid")

    parent = output_path.parent
    try:
        if output_path.resolve(strict=False) != output_path:
            raise CliMisuseError("completed report output path is invalid")
        for ancestor in reversed(output_path.parents):
            details = ancestor.lstat()
            if not stat.S_ISDIR(details.st_mode) or stat.S_ISLNK(details.st_mode):
                raise CliMisuseError("completed report output path is invalid")
        parent_details = parent.lstat()
        source_details = source_path.lstat()
        if (
            not stat.S_ISDIR(parent_details.st_mode)
            or stat.S_ISLNK(parent_details.st_mode)
            or not stat.S_ISREG(source_details.st_mode)
            or stat.S_ISLNK(source_details.st_mode)
        ):
            raise CliMisuseError("completed report output path is invalid")
        try:
            output_details = output_path.lstat()
        except FileNotFoundError:
            output_identity = None
        else:
            if (
                not stat.S_ISREG(output_details.st_mode)
                or stat.S_ISLNK(output_details.st_mode)
                or _inode_stat_identity(output_details)
                == _inode_stat_identity(source_details)
            ):
                raise CliMisuseError("completed report output path is invalid")
            output_identity = _source_stat_identity(output_details)
    except CliMisuseError:
        raise
    except OSError as error:
        raise CliMisuseError("completed report output path is invalid") from error
    return (
        output_path,
        parent,
        _inode_stat_identity(parent_details),
        _source_stat_identity(source_details),
        output_identity,
    )


def _atomic_write_strict_completed_output(
    source_path: Path, output: Path, payload: bytes
) -> Path:
    (
        output_path,
        parent,
        parent_identity,
        source_identity,
        output_identity,
    ) = _prepare_strict_completed_output(source_path, output)
    parent_descriptor = -1
    temporary_descriptor = -1
    temporary_path: Path | None = None
    try:
        parent_flags = (
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        parent_descriptor = os.open(parent, parent_flags)
        if _inode_stat_identity(os.fstat(parent_descriptor)) != parent_identity:
            raise CliMisuseError("completed report output path is invalid")

        temporary_descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{output_path.name}.task9-",
            suffix=".tmp",
            dir=parent,
        )
        temporary_path = Path(temporary_name)
        opened_temporary = os.fstat(temporary_descriptor)
        if (
            temporary_path.parent != parent
            or not stat.S_ISREG(opened_temporary.st_mode)
            or stat.S_ISLNK(opened_temporary.st_mode)
            or opened_temporary.st_nlink != 1
        ):
            raise CliMisuseError("completed report output path is invalid")
        os.fchmod(temporary_descriptor, 0o644)
        view = memoryview(payload)
        while view:
            written = os.write(temporary_descriptor, view)
            if written <= 0:
                raise OSError("completed report output write made no progress")
            view = view[written:]
        os.fsync(temporary_descriptor)
        os.close(temporary_descriptor)
        temporary_descriptor = -1

        if (
            _inode_stat_identity(parent.lstat()) != parent_identity
            or source_path.resolve(strict=True) != source_path
            or _source_stat_identity(source_path.lstat()) != source_identity
        ):
            raise CliMisuseError("completed report output path is invalid")
        for ancestor in reversed(output_path.parents):
            details = ancestor.lstat()
            if not stat.S_ISDIR(details.st_mode) or stat.S_ISLNK(details.st_mode):
                raise CliMisuseError("completed report output path is invalid")
        if output_identity is None:
            try:
                output_path.lstat()
            except FileNotFoundError:
                pass
            else:
                raise CliMisuseError("completed report output path is invalid")
        else:
            current_output = output_path.lstat()
            if (
                not stat.S_ISREG(current_output.st_mode)
                or stat.S_ISLNK(current_output.st_mode)
                or _source_stat_identity(current_output) != output_identity
                or _inode_stat_identity(current_output)
                == _inode_stat_identity(source_path.lstat())
            ):
                raise CliMisuseError("completed report output path is invalid")
        current_temporary = temporary_path.lstat()
        if (
            not stat.S_ISREG(current_temporary.st_mode)
            or stat.S_ISLNK(current_temporary.st_mode)
            or _inode_stat_identity(current_temporary)
            != _inode_stat_identity(opened_temporary)
        ):
            raise CliMisuseError("completed report output path is invalid")

        os.replace(temporary_path, output_path)
        temporary_path = None
        os.fsync(parent_descriptor)
    except CliMisuseError:
        raise
    except OSError as error:
        raise CliMisuseError("completed report output path is invalid") from error
    finally:
        if temporary_descriptor >= 0:
            os.close(temporary_descriptor)
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass
        if parent_descriptor >= 0:
            os.close(parent_descriptor)
    return output_path


def render_completed_report(source: Path, output: Path) -> Path:
    """Render a tracked report only from one completed canonical JSON record."""

    source_path, trusted_artifact_root, payload = _read_strict_completed_source(
        source
    )
    trusted_tested_head = _read_trusted_repository_head(
        Path(__file__).resolve().parents[1]
    )
    try:
        record = json.loads(
            payload.decode("utf-8", errors="strict"),
            object_pairs_hook=_strict_json_object,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CliMisuseError("completed report JSON is unreadable") from error
    if not isinstance(record, dict) or canonical_json_bytes(record) != payload:
        raise CliMisuseError("completed report JSON is not canonical")
    _validate_report_record_shape(
        record,
        completed=True,
        artifact_root=trusted_artifact_root,
        trusted_tested_head=trusted_tested_head,
    )
    _verify_completed_artifact_tree(record, source_path)
    markdown_bytes = render_report_markdown(record).encode("utf-8")
    expected = _binary_artifact_record("report.md", markdown_bytes)
    if record.get("report_markdown") != expected:
        raise CliMisuseError("completed report Markdown hash is invalid")
    if _read_trusted_repository_head(
        Path(__file__).resolve().parents[1]
    ) != trusted_tested_head:
        raise CliMisuseError("completed report repository HEAD is invalid")
    return _atomic_write_strict_completed_output(
        source_path, output, markdown_bytes
    )


def render_report_from_cli(repo_root: Path, source_argument: str) -> int:
    root = Path(repo_root).resolve()
    candidate = Path(source_argument)
    if not candidate.is_absolute():
        return 64
    try:
        acceptance_root = (root / "artifacts" / "acceptance").resolve()
        if (
            not candidate.is_relative_to(acceptance_root)
            or candidate.name != "report.json"
        ):
            return 64
        render_completed_report(
            source_argument, root / "docs" / "interaction-acceptance-report.md"
        )
    except (CliMisuseError, OSError):
        return 1
    return 0


def main(argv: tuple[str, ...] | None = None) -> int:
    arguments = tuple(argv if argv is not None else os.sys.argv[1:])
    repo_root = Path(__file__).resolve().parents[1]

    valid_run = (
        len(arguments) == 2
        and arguments[0] == "run"
        and re.fullmatch(r"[0-9a-f]{40}", arguments[1]) is not None
    )
    valid_run_one = len(arguments) == 2 and arguments[0] == "run-one"
    valid_render = len(arguments) == 2 and arguments[0] == "render-report"
    if not (valid_run or valid_run_one or valid_render):
        return 64

    if valid_run:
        full_result = run_full_acceptance(repo_root, os.environ, arguments[1])
        summary = {
            "artifact_root": full_result.artifact_root,
            "decision": full_result.decision.outcome.value,
            "run_id": full_result.run_id,
            "runner_process_exit": full_result.exit_code,
        }
        os.sys.stdout.buffer.write(canonical_json_bytes(summary))
        return full_result.exit_code

    if valid_render:
        return render_report_from_cli(repo_root, arguments[1])

    command_id = arguments[1]
    artifact_root = repo_root / "artifacts" / "acceptance" / f"run-one-{command_id}"
    executor = PopenProcessExecutor(repo_root, artifact_root)
    result = run_one_command(
        command_id,
        repo_root=repo_root,
        artifact_root=artifact_root,
        parent_env=os.environ,
        executor=executor,
    )
    summary = {
        "child_exit": result.command_result.child_exit,
        "classified_outcome": result.command_result.classified_outcome.value,
        "command_id": result.command_result.subcommand,
        "evidence": None if result.evidence is None else result.evidence.reason,
        "reason": result.command_result.reason,
        "runner_process_exit": result.exit_code,
        "termination": result.command_result.termination.value,
    }
    os.sys.stdout.buffer.write(canonical_json_bytes(summary))
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
