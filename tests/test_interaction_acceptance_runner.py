import ast
import importlib
import hashlib
import html
import json
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
from re import _constants as sre_constants
from re import _parser as sre_parse

import pytest
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, replace
from pathlib import Path

EXPECTED_TIMEOUTS = {
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
EXPECTED_FROZEN_LIMITATIONS = (
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


def _specs(tmp_path):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    repo_root = Path(__file__).resolve().parents[1]
    artifact_root = (tmp_path / "acceptance-artifacts").resolve()
    return module, repo_root, artifact_root, module.build_command_specs(repo_root, artifact_root)


def test_runner_module_import_is_effect_free():
    module = importlib.import_module("scripts.run_interaction_acceptance")

    assert module.__name__ == "scripts.run_interaction_acceptance"


def test_pure_runner_test_imports_only_stdlib_and_pytest():
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])

    assert roots <= set(sys.stdlib_module_names) | {"pytest"}


def test_command_inventory_has_exact_ids_timeouts_and_conftest_modes(tmp_path):
    module, _repo_root, _artifact_root, specs = _specs(tmp_path)

    assert tuple(spec.command_id for spec in specs) == tuple(EXPECTED_TIMEOUTS)
    assert {spec.command_id: spec.timeout_seconds for spec in specs} == EXPECTED_TIMEOUTS
    assert len({spec.command_id for spec in specs}) == 22
    pure_ids = {
        spec.command_id
        for spec in specs
        if spec.conftest_mode is module.ConftestMode.PURE
    }
    assert pure_ids == {"runner", "lovable"}
    assert all(spec.timeout_seconds > 0 for spec in specs)


def test_full_suite_argv_is_explicit_sorted_and_forbidden_targets_are_absent(tmp_path):
    _module, _repo_root, artifact_root, specs = _specs(tmp_path)
    by_id = {spec.command_id: spec for spec in specs}
    pytest_prefix = (
        PYTHON,
        "-m",
        "pytest",
        "-p",
        "scripts.run_interaction_acceptance",
        "--capture=sys",
    )
    node_prefix = (
        NODE,
        "--unhandled-rejections=strict",
        "--test",
        "--test-concurrency=1",
        "--test-reporter=tap",
    )
    backend_targets = (
        "tests/test_database_safety.py",
        "tests/test_rebuild_demo_database.py",
        "tests/test_runtime_health.py",
        "tests/test_api_errors.py",
        "tests/test_http_boundary.py",
        "tests/test_teacher_auth.py",
        "tests/test_teacher_auth_body_privacy.py",
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
        "tests/test_legacy_avatar_fallback.py",
        "tests/test_weekly_reports.py",
        "tests/test_conversation_search.py",
        "tests/test_demo_seed.py",
        "tests/test_live_provider_uat_harness.py",
        "tests/e2e.py",
    )
    child_targets = tuple(
        f"tests/frontend/child/{name}"
        for name in (
            "api.test.mjs",
            "app-effects.test.mjs",
            "machine.test.mjs",
            "session-store.test.mjs",
            "speech.test.mjs",
            "tts.test.mjs",
            "view.test.mjs",
        )
    )
    teacher_targets = tuple(
        f"tests/frontend/teacher/{name}"
        for name in (
            "dirty-guard.test.mjs",
            "management.test.mjs",
            "reports.test.mjs",
            "review.test.mjs",
            "router.test.mjs",
            "today.test.mjs",
        )
    )
    expected_tails = {
        "runner": pytest_prefix
        + (
            "--noconftest",
            "-q",
            "-o",
            "xfail_strict=true",
            f"--junitxml={artifact_root / 'runner.junit.xml'}",
            "tests/test_interaction_acceptance_runner.py",
        ),
        "lovable": pytest_prefix
        + (
            "--noconftest",
            "-q",
            "-o",
            "xfail_strict=true",
            f"--junitxml={artifact_root / 'lovable.junit.xml'}",
            "tests/test_lovable_artifacts.py",
        ),
        "backend": pytest_prefix
        + (
            "-q",
            "-o",
            "xfail_strict=true",
            f"--junitxml={artifact_root / 'backend.junit.xml'}",
            *backend_targets,
        ),
        "browser": pytest_prefix
        + (
            "-q",
            "-o",
            "xfail_strict=true",
            f"--junitxml={artifact_root / 'browser.junit.xml'}",
            "tests/browser",
        ),
        "shared_node": node_prefix + ("tests/frontend/shared/api-client.test.mjs",),
        "child_node": node_prefix + child_targets,
        "teacher_node": node_prefix + teacher_targets,
    }

    for command_id, tail in expected_tails.items():
        assert by_id[command_id].argv == CLEAN_ENV_ARGV + tail
    assert by_id["child_node"].argv[-len(child_targets) :] == tuple(sorted(child_targets))
    assert by_id["teacher_node"].argv[-len(teacher_targets) :] == tuple(sorted(teacher_targets))
    assert all("*" not in arg for spec in specs for arg in spec.argv)
    all_argv = "\n".join(arg for spec in specs for arg in spec.argv)
    for forbidden in (
        "tests/seed_demo_assessments.py",
        "tests/screenshot.py",
        "tests/process_ip_images.py",
        "scripts/rebuild_demo_database.py",
        "tests/test_runtime_foundation.py",
        "tests/test_conversation_pipeline.py",
    ):
        assert forbidden not in all_argv


def test_focused_browser_argv_selects_exact_function_and_parameter(tmp_path):
    _module, _repo_root, artifact_root, specs = _specs(tmp_path)
    by_id = {spec.command_id: spec for spec in specs}
    cases = {
        "release_focus_1024": (
            "tests/browser/test_release_viewports.py::test_release_focus_indicator_meets_three_to_one[1024x768]",
        ),
        "release_focus_all": (
            "tests/browser/test_release_viewports.py::test_release_focus_indicator_meets_three_to_one",
        ),
        "teacher_accessibility_full": ("tests/browser/test_teacher_accessibility.py",),
        "release_db_action_1024": (
            "tests/browser/test_release_viewports.py::test_release_teacher_action_persists_to_disposable_sqlite[1024x768]",
        ),
        "release_db_action_all": (
            "tests/browser/test_release_viewports.py::test_release_teacher_action_persists_to_disposable_sqlite",
        ),
        "review_identity_1024": (
            "tests/browser/test_teacher_review_loading.py::test_teacher_review_queue_and_detail_show_identity_time_id_and_status[1024x768]",
        ),
        "review_identity_all": (
            "tests/browser/test_teacher_review_loading.py::test_teacher_review_queue_and_detail_show_identity_time_id_and_status",
        ),
        "child_chat_timeout_1024": (
            "tests/browser/test_child_faults.py::test_first_chat_thirty_second_timeout_retains_draft_and_reuses_request_id_once[1024x576]",
        ),
        "child_chat_timeout_all": (
            "tests/browser/test_child_faults.py::test_first_chat_thirty_second_timeout_retains_draft_and_reuses_request_id_once",
        ),
        "child_completion_delay_1024": (
            "tests/browser/test_child_faults.py::test_completion_delay_is_single_flight_and_saves_once[1024x576]",
        ),
        "child_completion_delay_all": (
            "tests/browser/test_child_faults.py::test_completion_delay_is_single_flight_and_saves_once",
        ),
        "child_keyboard_core_1024": (
            "tests/browser/test_child_faults.py::test_child_core_flow_is_page_keyboard_only_and_saves_once[1024x576]",
        ),
        "child_keyboard_core_all": (
            "tests/browser/test_child_faults.py::test_child_core_flow_is_page_keyboard_only_and_saves_once",
        ),
        "today_three_status_1024": (
            "tests/browser/test_teacher_today.py::test_teacher_today_renders_pending_processing_and_failed_rows_with_retry_boundaries[1024x768]",
        ),
        "today_three_status_all": (
            "tests/browser/test_teacher_today.py::test_teacher_today_renders_pending_processing_and_failed_rows_with_retry_boundaries",
        ),
    }

    for command_id, targets in cases.items():
        expected = CLEAN_ENV_ARGV + (
            PYTHON,
            "-m",
            "pytest",
            "-p",
            "scripts.run_interaction_acceptance",
            "--capture=sys",
            "-q",
            "-o",
            "xfail_strict=true",
            f"--junitxml={artifact_root / f'{command_id}.junit.xml'}",
            *targets,
        )
        assert by_id[command_id].argv == expected


def test_every_pytest_spec_has_a_unique_junit_path_derived_from_its_id(tmp_path):
    module, _repo_root, artifact_root, specs = _specs(tmp_path)
    pytest_specs = [
        spec for spec in specs if spec.evidence_format is module.EvidenceFormat.JUNIT
    ]

    assert len(pytest_specs) == 19
    assert len({spec.evidence_path for spec in pytest_specs}) == len(pytest_specs)
    for spec in pytest_specs:
        assert spec.evidence_path == artifact_root / f"{spec.command_id}.junit.xml"
        assert f"--junitxml={spec.evidence_path}" in spec.argv


class HostileParentEnvironment(Mapping[str, str]):
    def __init__(self):
        self.safe = {
            "PATH": "/safe/bin",
            "HOME": "/safe/browser-home",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "TMPDIR": "/safe/tmp",
            "TZ": "UTC",
            "SYSTEMROOT": "C:/Windows",
        }
        self.hostile_names = (
            "OPENAI_API_KEY",
            "DEEPSEEK_PROVIDER_TOKEN",
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "NO_PROXY",
            "__CF_USER_TEXT_ENCODING",
            "DISABLE_EXTERNAL_AI",
            "PYTHONNOUSERSITE",
            "PYTHON_DOTENV_DISABLED",
        )

    def __iter__(self) -> Iterator[str]:
        return iter((*self.safe, *self.hostile_names))

    def __len__(self) -> int:
        return len(self.safe) + len(self.hostile_names)

    def __getitem__(self, key: str) -> str:
        if key in self.hostile_names:
            raise AssertionError(f"forbidden value access: {key}")
        return self.safe[key]


def test_sanitized_env_strips_hostile_names_without_reading_their_values():
    module = importlib.import_module("scripts.run_interaction_acceptance")
    parent = HostileParentEnvironment()

    sanitized = module.build_sanitized_env(parent, browser=False)

    assert sanitized == {
        "PATH": "/safe/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TMPDIR": "/safe/tmp",
        "TZ": "UTC",
        "SYSTEMROOT": "C:/Windows",
        "DISABLE_EXTERNAL_AI": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHON_DOTENV_DISABLED": "1",
    }


def test_browser_sanitized_env_retains_only_the_neutral_home():
    module = importlib.import_module("scripts.run_interaction_acceptance")
    parent = HostileParentEnvironment()

    sanitized = module.build_sanitized_env(parent, browser=True)

    assert sanitized["HOME"] == "/safe/browser-home"
    assert set(sanitized) == {
        "PATH",
        "HOME",
        "LANG",
        "LC_ALL",
        "TMPDIR",
        "TZ",
        "SYSTEMROOT",
        "DISABLE_EXTERNAL_AI",
        "PYTHONNOUSERSITE",
        "PYTHON_DOTENV_DISABLED",
    }


def _physical_sqlite_state(path: Path):
    state = {}
    for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        if not candidate.exists():
            state[candidate.name] = None
            continue
        details = candidate.lstat()
        state[candidate.name] = (
            stat.S_IMODE(details.st_mode),
            details.st_size,
            details.st_mtime_ns,
            candidate.read_bytes(),
        )
    return state


def test_logical_sqlite_digest_sees_wal_data_without_changing_physical_files(tmp_path):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    database = tmp_path / "wal-visible.db"
    with sqlite3.connect(database) as writer:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("CREATE TABLE evidence (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        writer.commit()
        writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        baseline_digest = module.logical_sqlite_digest(database)
        raw_database_sha = hashlib.sha256(database.read_bytes()).hexdigest()

        writer.execute("INSERT INTO evidence(value) VALUES ('wal-only-change')")
        writer.commit()
        assert hashlib.sha256(database.read_bytes()).hexdigest() == raw_database_sha
        physical_before_observation = _physical_sqlite_state(database)

        changed_digest = module.logical_sqlite_digest(database)

        physical_after_observation = _physical_sqlite_state(database)
        assert changed_digest != baseline_digest
        assert physical_after_observation == physical_before_observation


def test_file_snapshot_detects_missing_rewrite_chmod_symlink_and_unreadable(tmp_path):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    missing = tmp_path / "missing.log"
    assert module.file_snapshot(missing).kind is module.FileKind.MISSING

    log = tmp_path / "app.log"
    log.write_bytes(b"preserved-log")
    initial = module.file_snapshot(log)
    assert initial.kind is module.FileKind.REGULAR
    assert initial.sha256 == hashlib.sha256(b"preserved-log").hexdigest()

    original_mtime = initial.mtime_ns
    log.write_bytes(b"preserved-log")
    os.utime(log, ns=(original_mtime + 1_000_000, original_mtime + 1_000_000))
    rewritten = module.file_snapshot(log)
    assert rewritten.sha256 == initial.sha256
    assert rewritten.mtime_ns != initial.mtime_ns
    assert rewritten != initial

    log.chmod(0o400)
    chmodded = module.file_snapshot(log)
    assert chmodded.mode == 0o400
    assert chmodded != rewritten

    target = tmp_path / "target.log"
    target.write_bytes(b"target")
    link = tmp_path / "linked.log"
    link.symlink_to(target)
    linked = module.file_snapshot(link)
    assert linked.kind is module.FileKind.SYMLINK
    assert linked.symlink_target == str(target)
    assert linked.sha256 is None

    unreadable = tmp_path / "unreadable.log"
    unreadable.write_bytes(b"secret")
    unreadable.chmod(0)
    try:
        blocked = module.file_snapshot(unreadable)
        assert blocked.kind is module.FileKind.UNREADABLE
        assert blocked.sha256 is None
    finally:
        unreadable.chmod(0o600)


def test_file_snapshot_totalizes_lstat_and_readlink_permission_failures(
    tmp_path, monkeypatch
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    blocked = tmp_path / "blocked.bin"
    blocked.write_bytes(b"blocked")
    original_lstat = Path.lstat

    def guarded_lstat(path):
        if path == blocked:
            raise PermissionError("synthetic lstat denial")
        return original_lstat(path)

    monkeypatch.setattr(Path, "lstat", guarded_lstat)
    lstat_snapshot = module.file_snapshot(blocked)
    assert lstat_snapshot.kind is module.FileKind.UNREADABLE
    assert lstat_snapshot.error == "PermissionError"
    assert lstat_snapshot.sha256 is None

    monkeypatch.setattr(Path, "lstat", original_lstat)
    target = tmp_path / "target.bin"
    target.write_bytes(b"target")
    link = tmp_path / "link.bin"
    link.symlink_to(target)
    monkeypatch.setattr(
        module.os,
        "readlink",
        lambda _path: (_ for _ in ()).throw(PermissionError("synthetic readlink denial")),
    )
    readlink_snapshot = module.file_snapshot(link)
    assert readlink_snapshot.kind is module.FileKind.UNREADABLE
    assert readlink_snapshot.error == "PermissionError"
    assert readlink_snapshot.sha256 is None


def test_database_snapshot_tracks_wal_shm_and_fails_closed_on_unsafe_types(tmp_path):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    database = tmp_path / "resource.db"
    with sqlite3.connect(database) as writer:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("CREATE TABLE rows (value TEXT NOT NULL)")
        writer.execute("INSERT INTO rows(value) VALUES ('visible-in-wal')")
        writer.commit()

        snapshot = module.database_snapshot(database)
        assert snapshot.database.kind is module.FileKind.REGULAR
        assert snapshot.wal.kind is module.FileKind.REGULAR
        assert snapshot.shm.kind is module.FileKind.REGULAR
        assert snapshot.logical_digest == module.logical_sqlite_digest(database)
        assert snapshot.unsafe_reasons == ()

    missing = module.database_snapshot(tmp_path / "missing.db")
    assert missing.database.kind is module.FileKind.MISSING
    assert missing.logical_digest is None
    assert missing.unsafe_reasons == ("DATABASE_MISSING",)

    target = tmp_path / "sidecar-target"
    target.write_bytes(b"not-a-wal")
    wal = Path(f"{database}-wal")
    wal.unlink(missing_ok=True)
    wal.symlink_to(target)
    unsafe = module.database_snapshot(database)
    assert unsafe.wal.kind is module.FileKind.SYMLINK
    assert unsafe.logical_digest is None
    assert unsafe.unsafe_reasons == ("WAL_NOT_REGULAR",)


def test_directory_snapshot_is_sorted_and_detects_metadata_and_type_changes(tmp_path):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    root = tmp_path / "tts-cache"
    root.mkdir()
    (root / "z-last.bin").write_bytes(b"z")
    (root / "a-first.bin").write_bytes(b"same")
    nested = root / "nested"
    nested.mkdir()
    (nested / "voice.bin").write_bytes(b"voice")

    initial = module.directory_snapshot(root)
    assert tuple(entry.relative_path for entry in initial.entries) == (
        "a-first.bin",
        "nested",
        "nested/voice.bin",
        "z-last.bin",
    )
    assert initial.unsafe_reasons == ()
    assert module.directory_digest(root) == initial.digest

    first = root / "a-first.bin"
    first_mtime = first.lstat().st_mtime_ns
    first.write_bytes(b"same")
    os.utime(first, ns=(first_mtime + 1_000_000, first_mtime + 1_000_000))
    rewritten = module.directory_snapshot(root)
    assert rewritten.digest != initial.digest

    first.chmod(0o400)
    chmodded = module.directory_snapshot(root)
    assert chmodded.digest != rewritten.digest

    changing = root / "changes-type"
    changing.write_bytes(b"file")
    file_state = module.directory_snapshot(root)
    changing.unlink()
    changing.mkdir()
    directory_state = module.directory_snapshot(root)
    assert directory_state.digest != file_state.digest


def test_directory_snapshot_fails_closed_for_missing_symlink_and_unreadable_entries(tmp_path):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    missing = module.directory_snapshot(tmp_path / "missing-cache")
    assert missing.digest is None
    assert missing.unsafe_reasons == ("DIRECTORY_MISSING",)

    root = tmp_path / "tts-cache"
    root.mkdir()
    target = tmp_path / "target.bin"
    target.write_bytes(b"target")
    (root / "link.bin").symlink_to(target)
    linked = module.directory_snapshot(root)
    assert linked.digest is None
    assert linked.unsafe_reasons == ("ENTRY_NOT_REGULAR:link.bin",)
    with pytest.raises(module.ResourceCaptureError, match="ENTRY_NOT_REGULAR:link.bin"):
        module.directory_digest(root)

    (root / "link.bin").unlink()
    unreadable = root / "unreadable.bin"
    unreadable.write_bytes(b"blocked")
    unreadable.chmod(0)
    try:
        blocked = module.directory_snapshot(root)
        assert blocked.digest is None
        assert blocked.unsafe_reasons == ("ENTRY_UNREADABLE:unreadable.bin",)
    finally:
        unreadable.chmod(0o600)

    wrong_root = tmp_path / "not-a-directory"
    wrong_root.write_bytes(b"file")
    type_changed = module.directory_snapshot(wrong_root)
    assert type_changed.digest is None
    assert type_changed.unsafe_reasons == ("DIRECTORY_NOT_DIRECTORY",)


def test_directory_snapshot_round_trips_one_safe_tree_and_allowed_symlink(tmp_path):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    root = tmp_path / "tts-cache"
    root.mkdir()
    (root / "voice.bin").write_bytes(b"voice")
    target = tmp_path / "outside.bin"
    target.write_bytes(b"target")
    (root / "allowed-link.bin").symlink_to(target)

    captured = module.directory_snapshot(root, allow_symlinks=True)
    reconstructed = module._report_directory_snapshot(
        module._canonical_value(captured), allow_symlinks=True
    )

    assert captured.scan_error is None
    assert captured.scan_source is None
    assert captured.unsafe_reasons == ()
    assert captured.digest is not None
    assert reconstructed == captured


@pytest.mark.parametrize("root_kind", ("unreadable", "regular", "symlink"))
def test_directory_snapshot_distinguishes_root_capture_failure_from_non_directory(
    tmp_path, monkeypatch, root_kind
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    root = tmp_path / "root"
    root.mkdir()
    if root_kind == "unreadable":
        root_snapshot = module.FileSnapshot(
            kind=module.FileKind.UNREADABLE,
            error="PermissionError",
        )
        expected = ("DIRECTORY_ROOT_UNREADABLE",)
    elif root_kind == "regular":
        root_snapshot = module.FileSnapshot(
            kind=module.FileKind.REGULAR,
            mode=0o600,
            size=1,
            mtime_ns=1,
            sha256=hashlib.sha256(b"x").hexdigest(),
        )
        expected = ("DIRECTORY_NOT_DIRECTORY",)
    else:
        root_snapshot = module.FileSnapshot(
            kind=module.FileKind.SYMLINK,
            mode=0o777,
            size=1,
            mtime_ns=1,
            symlink_target="target",
        )
        expected = ("DIRECTORY_NOT_DIRECTORY",)
    monkeypatch.setattr(module, "file_snapshot", lambda _path: root_snapshot)

    captured = module.directory_snapshot(root)

    assert captured.root == root_snapshot
    assert captured.scan_error is None
    assert captured.scan_source is None
    assert captured.unsafe_reasons == expected


def test_directory_snapshot_distinguishes_zero_and_partial_scandir_failures(
    tmp_path, monkeypatch
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    root = tmp_path / "tts-cache"
    root.mkdir()
    (root / "visible.bin").write_bytes(b"visible")
    real_scandir = module.os.scandir

    def denied_scandir(_path):
        raise PermissionError("synthetic root scan denial")

    monkeypatch.setattr(module.os, "scandir", denied_scandir)
    zero = module.directory_snapshot(root)
    assert zero.root.kind is module.FileKind.DIRECTORY
    assert zero.entries == ()
    assert zero.scan_error == "PermissionError"
    assert zero.scan_source == "."
    assert zero.unsafe_reasons == ("SCANDIR:.:PermissionError",)

    with real_scandir(root) as scan:
        visible = next(scan)

    class PartialScan:
        def __init__(self):
            self._yielded = False

        def __enter__(self):
            return self

        def __exit__(self, _type, _value, _traceback):
            return False

        def __iter__(self):
            return self

        def __next__(self):
            if not self._yielded:
                self._yielded = True
                return visible
            raise BlockingIOError("synthetic partial scan denial")

    monkeypatch.setattr(module.os, "scandir", lambda _path: PartialScan())
    partial = module.directory_snapshot(root)
    assert tuple(entry.relative_path for entry in partial.entries) == ("visible.bin",)
    assert partial.root.kind is module.FileKind.DIRECTORY
    assert partial.scan_error == "BlockingIOError"
    assert partial.scan_source == "."
    assert partial.unsafe_reasons == ("SCANDIR:.:BlockingIOError",)
    assert zero != partial


def test_directory_snapshot_report_reconstruction_rejects_forged_scan_state(
    tmp_path, monkeypatch
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    root = tmp_path / "tts-cache"
    root.mkdir()
    real_scandir = os.scandir
    monkeypatch.setattr(
        module.os,
        "scandir",
        lambda _path: (_ for _ in ()).throw(PermissionError("synthetic denial")),
    )
    captured = module.directory_snapshot(root)
    canonical = module._canonical_value(captured)

    assert module._report_directory_snapshot(canonical, allow_symlinks=False) == captured

    forged_reason = json.loads(json.dumps(canonical))
    forged_reason["unsafe_reasons"] = ["DIRECTORY_ROOT_UNREADABLE"]
    with pytest.raises(module.CliMisuseError, match="resource"):
        module._report_directory_snapshot(forged_reason, allow_symlinks=False)

    forged_source = json.loads(json.dumps(canonical))
    forged_source["scan_source"] = "nested"
    with pytest.raises(module.CliMisuseError, match="resource"):
        module._report_directory_snapshot(forged_source, allow_symlinks=False)

    safe_root = tmp_path / "safe"
    safe_root.mkdir()
    monkeypatch.setattr(module.os, "scandir", real_scandir)
    safe = module._canonical_value(module.directory_snapshot(safe_root))
    safe["digest"] = "0" * 64
    with pytest.raises(module.CliMisuseError, match="resource"):
        module._report_directory_snapshot(safe, allow_symlinks=False)


def _run_clean_git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [*CLEAN_ENV_ARGV, "/opt/homebrew/bin/git", *args],
        cwd=repo,
        capture_output=True,
        check=True,
        text=True,
    )


def _make_resource_repository(root: Path) -> None:
    (root / "data" / "tts_cache").mkdir(parents=True)
    (root / "data" / "media").mkdir()
    (root / "logs").mkdir()
    (root / ".workbuddy" / "memory").mkdir(parents=True)
    (root / "docs" / "superpowers" / "specs").mkdir(parents=True)
    (root / ".superpowers" / "brainstorm").mkdir(parents=True)
    (root / "docs" / "superpowers" / "plans").mkdir(parents=True)
    with sqlite3.connect(root / "data" / "duck_diary.db") as connection:
        connection.execute("CREATE TABLE protected (value TEXT NOT NULL)")
        connection.execute("INSERT INTO protected(value) VALUES ('stable')")
    (root / "logs" / "app.log").write_bytes(b"stable-log")
    (root / "data" / "tts_cache" / "voice.bin").write_bytes(b"voice")
    (root / "data" / "media" / "avatar.webp").write_bytes(b"avatar")
    (root / ".workbuddy" / "memory" / "2026-08-22.md").write_text("memory\n")
    (
        root
        / "docs"
        / "superpowers"
        / "specs"
        / "2026-08-23-interaction-stabilization-design.md"
    ).write_text("spec\n")
    (root / ".superpowers" / "brainstorm" / "state.txt").write_text("state\n")
    (root / "docs" / "superpowers" / "plans" / "plan.md").write_text("plan\n")
    _run_clean_git(root, "init", "-q")
    _run_clean_git(root, "add", ".")
    _run_clean_git(
        root,
        "-c",
        "user.name=Task 9 Fixture",
        "-c",
        "user.email=task9@example.invalid",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-q",
        "-m",
        "fixture",
    )


def test_capture_resources_is_total_and_tracks_git_and_all_protected_paths(tmp_path):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    repo = tmp_path / "resource-repo"
    repo.mkdir()
    _make_resource_repository(repo)

    initial = module.capture_resources(repo)

    assert initial.unsafe_reasons == ()
    assert len(initial.git_head) == 40
    assert initial.git_porcelain == b""
    assert initial.media.root.kind is module.FileKind.DIRECTORY
    assert tuple(entry.relative_path for entry in initial.media.entries) == (
        "avatar.webp",
    )
    assert tuple(path.relative_path for path in initial.user_paths) == (
        ".workbuddy/memory/2026-08-22.md",
        "docs/superpowers/specs/2026-08-23-interaction-stabilization-design.md",
        ".superpowers/brainstorm",
        "docs/superpowers/plans",
    )

    log = repo / "logs" / "app.log"
    initial_mtime = log.lstat().st_mtime_ns
    log.write_bytes(b"stable-log")
    os.utime(log, ns=(initial_mtime + 1_000_000, initial_mtime + 1_000_000))
    rewritten = module.capture_resources(repo)
    assert rewritten != initial
    assert rewritten.log.sha256 == initial.log.sha256

    log.unlink()
    missing = module.capture_resources(repo)
    assert missing.log.kind is module.FileKind.MISSING
    assert "LOG_NOT_REGULAR" in missing.unsafe_reasons


def test_capture_resources_accepts_stably_missing_media_and_user_path(tmp_path):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    repo = tmp_path / "resource-repo"
    repo.mkdir()
    _make_resource_repository(repo)
    shutil.rmtree(repo / "data" / "media")
    shutil.rmtree(repo / ".superpowers" / "brainstorm")
    _run_clean_git(repo, "add", "-u")
    _run_clean_git(
        repo,
        "-c",
        "user.name=Task 10 Fixture",
        "-c",
        "user.email=task10@example.invalid",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-q",
        "-m",
        "remove optional protected roots",
    )

    missing = module.capture_resources(repo)

    assert missing.media.unsafe_reasons == ("DIRECTORY_MISSING",)
    assert next(
        path for path in missing.user_paths
        if path.relative_path == ".superpowers/brainstorm"
    ).unsafe_reasons == ("PATH_MISSING",)
    assert missing.git_porcelain == b""
    assert missing.unsafe_reasons == ()

    (repo / "data" / "media").mkdir()
    (repo / ".superpowers" / "brainstorm").mkdir(parents=True)
    appeared = module.capture_resources(repo)

    assert appeared.unsafe_reasons == ()
    assert appeared != missing
    assert module._snapshots_are_unchanged(missing, appeared) is False


@dataclass(frozen=True)
class FakeResources:
    token: str = "stable"
    unsafe_reasons: tuple[str, ...] = ()


@dataclass
class FakeProcess:
    communications: list[object]
    group_states: list[bool]
    term_returncode: object = "UNCHANGED"
    kill_returncode: object = "UNCHANGED"
    returncode: int | None = None
    pid: int = 4100
    pgid: int = 4100


class ScriptedProcessExecutor:
    def __init__(self, *processes: FakeProcess, snapshots=None):
        self.processes = list(processes)
        self.snapshots = list(snapshots or [FakeResources()] * (len(processes) * 3))
        self.events = []
        self.communicate_timeouts = []
        self.writes = []
        self.now = 0.0
        self.current = None

    def capture_resources(self):
        self.events.append("capture")
        return self.snapshots.pop(0)

    def start(self, spec, env):
        del env
        self.events.append(f"start:{spec.command_id}")
        process = self.processes.pop(0)
        self.current = process
        return process

    def get_pgid(self, process):
        self.events.append("pgid")
        return process.pgid

    def communicate(self, process, timeout):
        self.events.append("communicate")
        self.communicate_timeouts.append(timeout)
        outcome = process.communications.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        stdout, stderr, returncode = outcome
        process.returncode = returncode
        return stdout, stderr

    def poll(self, process):
        self.events.append("poll")
        return process.returncode

    def group_alive(self, pgid):
        del pgid
        self.events.append("alive")
        process = self.current
        if len(process.group_states) > 1:
            return process.group_states.pop(0)
        return process.group_states[0]

    def terminate_group(self, pgid):
        del pgid
        self.events.append("term")
        if self.current.term_returncode != "UNCHANGED":
            self.current.returncode = self.current.term_returncode

    def kill_group(self, pgid):
        del pgid
        self.events.append("kill")
        if self.current.kill_returncode != "UNCHANGED":
            self.current.returncode = self.current.kill_returncode

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.events.append("sleep")
        self.now += seconds

    def write_streams(self, command_id, stdout, stderr):
        self.events.append(f"write:{command_id}")
        self.writes.append((command_id, stdout, stderr))


class PermissionFaultExecutor(ScriptedProcessExecutor):
    def __init__(self, *processes, fault):
        super().__init__(*processes)
        self.fault = fault

    def group_alive(self, pgid):
        if self.fault == "probe":
            self.events.append("alive-permission-error")
            raise PermissionError("synthetic killpg(0) denial")
        return super().group_alive(pgid)

    def terminate_group(self, pgid):
        if self.fault == "term":
            self.events.append("term-permission-error")
            raise PermissionError("synthetic TERM denial")
        return super().terminate_group(pgid)

    def kill_group(self, pgid):
        if self.fault == "kill":
            self.events.append("kill-permission-error")
            raise PermissionError("synthetic KILL denial")
        return super().kill_group(pgid)


def _unit_process_spec(module, tmp_path, command_id="runner", timeout=3):
    return module.CommandSpec(
        command_id=command_id,
        argv=("/usr/bin/true",),
        timeout_seconds=timeout,
        conftest_mode=module.ConftestMode.PURE,
        evidence_format=module.EvidenceFormat.JUNIT,
        evidence_path=tmp_path / f"{command_id}.xml",
    )


def _timeout(output=b"partial", stderr=b"partial-error"):
    return subprocess.TimeoutExpired(
        cmd=("synthetic",),
        timeout=1,
        output=output,
        stderr=stderr,
    )


def test_process_group_clean_exit_and_spontaneous_signal_are_distinct(tmp_path):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    clean = FakeProcess([(b"ok", b"", 0)], [False])
    signaled = FakeProcess([(b"signal", b"", -9)], [False])

    clean_result = module.run_command(
        _unit_process_spec(module, tmp_path),
        env={},
        executor=ScriptedProcessExecutor(clean),
    )
    signal_result = module.run_command(
        _unit_process_spec(module, tmp_path),
        env={},
        executor=ScriptedProcessExecutor(signaled),
    )

    assert clean_result.termination is module.Termination.EXITED
    assert clean_result.child_exit == 0
    assert clean_result.classified_outcome is module.ClassifiedOutcome.SUCCESS
    assert signal_result.termination is module.Termination.SIGNALED
    assert signal_result.child_exit == -9
    assert signal_result.classified_outcome is module.ClassifiedOutcome.TECHNICAL_FAILURE


def test_process_group_uses_start_new_session_leader_pid_without_fallible_getpgid(
    tmp_path,
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    process = FakeProcess([(b"ok", b"", 0)], [False], pid=7331, pgid=7331)

    class GetPgidMustNotRun(ScriptedProcessExecutor):
        def get_pgid(self, _process):
            self.events.append("forbidden-getpgid")
            raise OSError("synthetic getpgid failure")

    executor = GetPgidMustNotRun(process)

    result = module.run_command(
        _unit_process_spec(module, tmp_path), env={}, executor=executor
    )

    assert result.child_started is True
    assert result.classified_outcome is module.ClassifiedOutcome.SUCCESS
    assert "forbidden-getpgid" not in executor.events


@pytest.mark.parametrize("leader_exit", [0, -15])
def test_process_group_residual_descendant_is_immutable_safety_evidence(tmp_path, leader_exit):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    process = FakeProcess([(b"complete", b"", leader_exit)], [True, False])
    executor = ScriptedProcessExecutor(process)

    result = module.run_command(
        _unit_process_spec(module, tmp_path), env={}, executor=executor
    )

    expected_termination = (
        module.Termination.EXITED if leader_exit == 0 else module.Termination.SIGNALED
    )
    assert result.termination is expected_termination
    assert result.residual_group_observed is True
    assert result.output_complete is True
    assert result.cleanup_failures == ()
    assert result.after_snapshot is not None
    assert result.classified_outcome is module.ClassifiedOutcome.SAFETY_FAILURE
    assert result.reason == "RESIDUAL_PROCESS_GROUP"
    assert "term" in executor.events
    assert "kill" not in executor.events


def test_process_group_timeout_term_cleanup_uses_complete_nonduplicated_output(tmp_path):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    process = FakeProcess(
        [_timeout(b"partial"), (b"complete-once", b"complete-error", -15)],
        [False],
        term_returncode=-15,
    )
    executor = ScriptedProcessExecutor(process)

    result = module.run_command(
        _unit_process_spec(module, tmp_path), env={}, executor=executor
    )

    assert result.termination is module.Termination.TIMED_OUT
    assert result.child_exit == -15
    assert result.stdout == b"complete-once"
    assert result.stderr == b"complete-error"
    assert result.output_complete is True
    assert result.classified_outcome is module.ClassifiedOutcome.TECHNICAL_FAILURE
    assert executor.events.count("term") == 1
    assert "kill" not in executor.events
    assert executor.writes == [("runner", b"complete-once", b"complete-error")]


def test_process_group_timeout_escalates_when_descendant_ignores_term(tmp_path):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    process = FakeProcess(
        [
            _timeout(b"initial"),
            (b"leader-reaped", b"", 0),
            (b"leader-reaped", b"", 0),
        ],
        [True, False],
        term_returncode=0,
        kill_returncode=0,
    )
    executor = ScriptedProcessExecutor(process)

    result = module.run_command(
        _unit_process_spec(module, tmp_path), env={}, executor=executor
    )

    assert result.termination is module.Termination.TIMED_OUT
    assert result.child_exit == 0
    assert result.output_complete is True
    assert result.cleanup_failures == ()
    assert result.classified_outcome is module.ClassifiedOutcome.TECHNICAL_FAILURE
    assert executor.events.count("term") == 1
    assert executor.events.count("kill") == 1


def test_process_group_timeout_kill_escalation_records_final_reap_integer(tmp_path):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    process = FakeProcess(
        [_timeout(b"initial"), _timeout(b"after-term"), (b"final", b"", -9)],
        [False],
        kill_returncode=-9,
    )
    executor = ScriptedProcessExecutor(process)

    result = module.run_command(
        _unit_process_spec(module, tmp_path), env={}, executor=executor
    )

    assert result.child_exit == -9
    assert result.termination is module.Termination.TIMED_OUT
    assert result.stdout == b"final"
    assert result.output_complete is True
    assert executor.events.count("kill") == 1


def test_process_group_incomplete_cleanup_canonicalizes_pipe_and_group_failures(tmp_path):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    process = FakeProcess(
        [
            _timeout(b"initial"),
            _timeout(b"term-partial"),
            _timeout(b"kill-partial", b"kill-error"),
        ],
        [True],
        kill_returncode=-9,
    )
    executor = ScriptedProcessExecutor(process)

    result = module.run_command(
        _unit_process_spec(module, tmp_path), env={}, executor=executor
    )

    assert result.cleanup_failures == (
        module.CleanupFailure.PIPE_DRAIN_TIMEOUT,
        module.CleanupFailure.GROUP_SURVIVED,
    )
    assert result.output_complete is False
    assert result.after_snapshot is None
    assert result.stdout == b"kill-partial"
    assert result.stderr == b"kill-error"
    assert result.classified_outcome is module.ClassifiedOutcome.SAFETY_FAILURE
    assert executor.writes == [("runner", b"kill-partial", b"kill-error")]


def test_process_group_incomplete_cleanup_reports_unreaped_leader(tmp_path):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    process = FakeProcess(
        [_timeout(), _timeout(), _timeout(b"latest")],
        [False],
        kill_returncode=None,
    )
    executor = ScriptedProcessExecutor(process)

    result = module.run_command(
        _unit_process_spec(module, tmp_path), env={}, executor=executor
    )

    assert result.child_exit is None
    assert result.cleanup_failures == (
        module.CleanupFailure.PIPE_DRAIN_TIMEOUT,
        module.CleanupFailure.LEADER_UNREAPED,
    )
    assert result.after_snapshot is None


def test_process_group_final_complete_output_with_live_group_keeps_complete_buffers(tmp_path):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    process = FakeProcess(
        [_timeout(), _timeout(), (b"newest-complete", b"newest-error", -9)],
        [True],
        kill_returncode=-9,
    )
    executor = ScriptedProcessExecutor(process)

    result = module.run_command(
        _unit_process_spec(module, tmp_path), env={}, executor=executor
    )

    assert result.cleanup_failures == (module.CleanupFailure.GROUP_SURVIVED,)
    assert result.output_complete is False
    assert result.stdout == b"newest-complete"
    assert result.stderr == b"newest-error"
    assert result.after_snapshot is None


def test_process_group_final_pipe_timeout_with_reaped_extinct_group_is_pipe_only(tmp_path):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    process = FakeProcess(
        [_timeout(), _timeout(), _timeout(b"latest-partial", b"latest-error")],
        [False],
        kill_returncode=-9,
    )
    executor = ScriptedProcessExecutor(process)

    result = module.run_command(
        _unit_process_spec(module, tmp_path), env={}, executor=executor
    )

    assert result.child_exit == -9
    assert result.cleanup_failures == (module.CleanupFailure.PIPE_DRAIN_TIMEOUT,)
    assert result.stdout == b"latest-partial"
    assert result.stderr == b"latest-error"
    assert result.after_snapshot is None
    assert sum(executor.communicate_timeouts[-1:]) <= 5
    assert executor.now <= 5


@pytest.mark.parametrize("path", ("timeout", "residual"))
@pytest.mark.parametrize("fault", ("probe", "term", "kill"))
def test_process_group_permission_errors_fail_closed_without_resource_snapshot(
    tmp_path, path, fault
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    if path == "timeout":
        process = FakeProcess(
            [_timeout(), _timeout(), (b"final", b"", -9)],
            [True],
            kill_returncode=-9,
        )
        expected_termination = module.Termination.TIMED_OUT
    else:
        process = FakeProcess([(b"complete", b"", 0)], [True])
        expected_termination = module.Termination.EXITED
    executor = PermissionFaultExecutor(process, fault=fault)

    result = module.run_command(
        _unit_process_spec(module, tmp_path), env={}, executor=executor
    )

    assert result.termination is expected_termination
    assert result.output_complete is False
    assert result.cleanup_failures == (module.CleanupFailure.GROUP_SURVIVED,)
    assert result.classified_outcome is module.ClassifiedOutcome.SAFETY_FAILURE
    assert result.reason == "PROCESS_CLEANUP_INCOMPLETE"
    assert result.after_snapshot is None
    assert module._command_runner_exit(result) == 3
    assert executor.events.count("capture") == 1
    assert executor.now <= 10


def test_permission_error_cleanup_stops_serial_execution_before_next_start(tmp_path):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    possible_residual = FakeProcess([(b"complete", b"", 0)], [True])
    never_started = FakeProcess([(b"must-not-run", b"", 0)], [False])
    executor = PermissionFaultExecutor(
        possible_residual, never_started, fault="probe"
    )
    specs = (
        _unit_process_spec(module, tmp_path, "one"),
        _unit_process_spec(module, tmp_path, "two"),
    )

    results = module.run_commands_serial(specs, env={}, executor=executor)

    assert len(results) == 1
    assert results[0].reason == "PROCESS_CLEANUP_INCOMPLETE"
    assert "start:two" not in executor.events


def test_process_group_serial_order_captures_after_before_next_start(tmp_path):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    first = FakeProcess([(b"one", b"", 0)], [False])
    second = FakeProcess([(b"two", b"", 0)], [False])
    executor = ScriptedProcessExecutor(first, second)
    specs = (
        _unit_process_spec(module, tmp_path, "one"),
        _unit_process_spec(module, tmp_path, "two"),
    )

    results = module.run_commands_serial(specs, env={}, executor=executor)

    assert len(results) == 2
    first_start = executor.events.index("start:one")
    second_start = executor.events.index("start:two")
    assert executor.events[first_start:second_start].count("capture") == 3
    assert all(result.classified_outcome is module.ClassifiedOutcome.SUCCESS for result in results)


def test_process_group_serial_stops_after_residual_safety_failure(tmp_path):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    residual = FakeProcess([(b"one", b"", 0)], [True, False])
    never_started = FakeProcess([(b"two", b"", 0)], [False])
    executor = ScriptedProcessExecutor(residual, never_started)
    specs = (
        _unit_process_spec(module, tmp_path, "one"),
        _unit_process_spec(module, tmp_path, "two"),
    )

    results = module.run_commands_serial(specs, env={}, executor=executor)

    assert len(results) == 1
    assert results[0].classified_outcome is module.ClassifiedOutcome.SAFETY_FAILURE
    assert "start:two" not in executor.events


def test_full_run_anchors_every_command_start_to_one_global_baseline(tmp_path):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    repo_root = Path(__file__).resolve().parents[1]
    artifact_root = tmp_path / "artifacts" / "acceptance" / "global-drift"
    baseline = FakeRunOneResources(token="global-a")
    drifted = FakeRunOneResources(token="next-command-b")
    specs = tuple(
        module.CommandSpec(
            command_id=command_id,
            argv=("/usr/bin/true",),
            timeout_seconds=3,
            conftest_mode=module.ConftestMode.PROJECT,
            evidence_format=module.EvidenceFormat.TAP,
        )
        for command_id in ("shared_node", "child_node")
    )
    processes = tuple(
        FakeProcess([(_unit7_passing_tap(f"synthetic-{index}"), b"", 0)], [False])
        for index in range(1, 3)
    )

    class DriftBeforeSecondCommandExecutor(ScriptedProcessExecutor):
        def __init__(self, *children):
            super().__init__(*children)
            self.capture_count = 0

        def capture_resources(self):
            self.events.append("capture")
            self.capture_count += 1
            return baseline if self.capture_count <= 4 else drifted

    executor = DriftBeforeSecondCommandExecutor(*processes)

    result = module.run_acceptance(
        repo_root=repo_root,
        artifact_root=artifact_root,
        run_id="20260830T030000Z-global-drift",
        generated_at="2026-08-30T03:00:00Z",
        parent_env={},
        executor=executor,
        expected_head=baseline.git_head,
        specs=specs,
        version_validator=lambda _root: True,
        lovable_complete_or_waived=False,
    )

    assert result.exit_code == 3
    assert len(result.command_results) == 2
    second = result.command_results[1]
    assert second.child_started is False
    assert second.termination is module.Termination.NOT_STARTED
    assert second.classified_outcome is module.ClassifiedOutcome.SAFETY_FAILURE
    assert second.reason == "RESOURCE_DRIFT"
    assert second.before_snapshot == baseline
    assert second.after_snapshot == drifted
    assert executor.events.count("start:child_node") == 0


@pytest.mark.parametrize(
    ("cleanup_path", "fault"),
    (
        ("timeout", "probe"),
        ("timeout", "term"),
        ("timeout", "kill"),
        ("residual", "probe"),
        ("residual", "term"),
        ("residual", "kill"),
    ),
)
def test_full_run_stops_at_uncontained_process_before_evidence_or_final_resources(
    tmp_path, monkeypatch, cleanup_path, fault
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    repo_root = Path(__file__).resolve().parents[1]
    artifact_root = tmp_path / "artifacts" / "acceptance" / f"{cleanup_path}-{fault}"
    stable = FakeRunOneResources()
    if cleanup_path == "timeout":
        first = FakeProcess(
            [_timeout(), _timeout(), _timeout()],
            [True],
        )
    else:
        first = FakeProcess([(b"leader-exited", b"", 0)], [True])
    never_started = FakeProcess([(b"must-not-run", b"", 0)], [False])
    class ProductionStreamPermissionExecutor(PermissionFaultExecutor):
        def write_streams(self, command_id, stdout, stderr):
            self.events.append(f"write:{command_id}")
            module.PopenProcessExecutor(repo_root, artifact_root).write_streams(
                command_id, stdout, stderr
            )

    executor = ProductionStreamPermissionExecutor(
        first, never_started, fault=fault
    )
    executor.snapshots = [stable] * 20
    specs = tuple(
        module.CommandSpec(
            command_id=command_id,
            argv=("/usr/bin/true",),
            timeout_seconds=3,
            conftest_mode=module.ConftestMode.PROJECT,
            evidence_format=module.EvidenceFormat.JUNIT,
            evidence_path=artifact_root / f"{command_id}.junit.xml",
        )
        for command_id in ("backend", "browser")
    )

    junit_operations = []
    original_is_file = Path.is_file
    original_read_bytes = Path.read_bytes
    original_write_bytes = Path.write_bytes
    original_unlink = Path.unlink

    def record_junit(operation, path):
        if path.name.endswith(".junit.xml"):
            junit_operations.append((operation, path.name))

    def spy_is_file(path):
        record_junit("stat", path)
        return original_is_file(path)

    def spy_read_bytes(path):
        record_junit("read", path)
        return original_read_bytes(path)

    def spy_write_bytes(path, payload):
        record_junit("write", path)
        return original_write_bytes(path, payload)

    def spy_unlink(path, *args, **kwargs):
        record_junit("unlink", path)
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "is_file", spy_is_file)
    monkeypatch.setattr(Path, "read_bytes", spy_read_bytes)
    monkeypatch.setattr(Path, "write_bytes", spy_write_bytes)
    monkeypatch.setattr(Path, "unlink", spy_unlink)

    result = module.run_acceptance(
        repo_root=repo_root,
        artifact_root=artifact_root,
        run_id=f"20260830T080000Z-{cleanup_path}-{fault}",
        generated_at="2026-08-30T08:00:00Z",
        parent_env={},
        executor=executor,
        expected_head=stable.git_head,
        specs=specs,
        version_validator=lambda _root: True,
        lovable_complete_or_waived=False,
    )

    assert result.exit_code == 3
    assert result.decision.outcome is module.DecisionOutcome.SAFETY_NO_GO
    assert result.report_record is None
    assert len(result.command_results) == 1
    command = result.command_results[0]
    assert command.output_complete is False
    assert command.after_snapshot is None
    assert command.cleanup_failures
    assert command.reason == "PROCESS_CLEANUP_INCOMPLETE"
    assert junit_operations == []
    prefix = f"{tuple(module.COMMAND_TIMEOUTS).index('backend') + 1:02d}-backend"
    command_dir = artifact_root / "commands"
    assert (command_dir / f"{prefix}.stdout.log").read_bytes() == command.stdout
    assert (command_dir / f"{prefix}.stderr.log").read_bytes() == command.stderr
    assert executor.events.count("capture") == 2
    assert "start:browser" not in executor.events
    assert not (artifact_root / "resources.after.json").exists()
    assert not (artifact_root / "report.json").exists()
    assert not (artifact_root / "report.md").exists()


def _run_synthetic_tripwire_command(
    module,
    tmp_path,
    *,
    command_id,
    stdout,
    stderr=b"",
    child_exit,
    junit_xml=None,
):
    stable = FakeRunOneResources()
    artifact_root = (
        tmp_path
        / "artifacts"
        / "acceptance"
        / f"tripwire-{command_id}-{abs(child_exit)}"
    )
    evidence_path = None
    evidence_format = module.EvidenceFormat.TAP
    if junit_xml is not None:
        evidence_path = tmp_path / f"tripwire-{command_id}.junit.xml"
        evidence_path.write_text(junit_xml, encoding="utf-8")
        evidence_format = module.EvidenceFormat.JUNIT
    spec = module.CommandSpec(
        command_id=command_id,
        argv=("/usr/bin/false",),
        timeout_seconds=3,
        conftest_mode=module.ConftestMode.PROJECT,
        evidence_format=evidence_format,
        evidence_path=evidence_path,
    )
    executor = ScriptedProcessExecutor(
        FakeProcess([(stdout, stderr, child_exit)], [False]),
        snapshots=[stable] * 10,
    )
    return module.run_acceptance(
        repo_root=Path(__file__).resolve().parents[1],
        artifact_root=artifact_root,
        run_id=f"20260830T100000Z-{command_id}-{abs(child_exit)}",
        generated_at="2026-08-30T10:00:00Z",
        parent_env={},
        executor=executor,
        expected_head=stable.git_head,
        specs=(spec,),
        version_validator=lambda _root: True,
        lovable_complete_or_waived=False,
    )


def _authenticated_tripwire_junit(event_id):
    signatures = {
        "external_ai": (
            "AssertionError",
            "tests/conftest.py:_blocked_external_ai",
            "TEST_TRIPWIRE:external_ai",
        ),
        "edge_tts": (
            "AssertionError",
            "tests/conftest.py:__init__",
            "TEST_TRIPWIRE:edge_tts",
        ),
        "external_network": (
            "AssertionError",
            "tests/conftest.py:_guarded_socket_connect",
            "TEST_TRIPWIRE:external_network",
        ),
        "browser_edge_tts": (
            "AssertionError",
            "tests/browser/child_server.py:stream",
            "external edge_tts disabled in browser tests",
        ),
        "browser_ai": (
            "AssertionError",
            "tests/browser/child_server.py:blocked_llm",
            "external AI disabled in browser tests",
        ),
        "browser_network": (
            "PermissionError",
            "tests/browser/child_server.py:guarded",
            "non-loopback socket blocked:",
        ),
        "browser_file": (
            "AssertionError",
            "tests/browser/conftest.py:_verify_server_safety",
            "browser tripwire fired:",
        ),
    }
    exception_type, frame, message = signatures[event_id]
    frame_path, function = frame.rsplit(":", 1)
    payload = json.dumps(
        {
            "event_id": event_id,
            "exception_type": exception_type,
            "frame": frame,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    function_prefix = "async " if function == "stream" else ""
    traceback = (
        f"    {function_prefix}def {function}():\n"
        f"E       {exception_type}: {message}\n\n"
        f"{frame_path}:999: {exception_type}"
    )
    return (
        '<testsuite tests="1" failures="1" errors="0" skipped="0">'
        '<testcase name="test_uncaught_breaker"><properties>'
        '<property name="task9.tripwire_event" '
        f'value="{html.escape(payload, quote=True)}"/>'
        "</properties>"
        f'<failure message="{html.escape(f"{exception_type}: {message}", quote=True)}">'
        f"{html.escape(traceback)}"
        "</failure></testcase></testsuite>"
    )


_TRIPWIRE_TEST_SIGNATURES = {
    event_id: (exception_type, frame)
    for event_id, (exception_type, frame, _message) in {
        "external_ai": (
            "AssertionError",
            "tests/conftest.py:_blocked_external_ai",
            "TEST_TRIPWIRE:external_ai",
        ),
        "edge_tts": (
            "AssertionError",
            "tests/conftest.py:__init__",
            "TEST_TRIPWIRE:edge_tts",
        ),
        "external_network": (
            "AssertionError",
            "tests/conftest.py:_guarded_socket_connect",
            "TEST_TRIPWIRE:external_network",
        ),
        "browser_edge_tts": (
            "AssertionError",
            "tests/browser/child_server.py:stream",
            "external edge_tts disabled in browser tests",
        ),
        "browser_ai": (
            "AssertionError",
            "tests/browser/child_server.py:blocked_llm",
            "external AI disabled in browser tests",
        ),
        "browser_network": (
            "PermissionError",
            "tests/browser/child_server.py:guarded",
            "non-loopback socket blocked:",
        ),
        "browser_file": (
            "AssertionError",
            "tests/browser/conftest.py:_verify_server_safety",
            "browser tripwire fired:",
        ),
    }.items()
}


def _signed_tripwire_sidecar(command_id, records, *, extra_lines=()):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    return module._signed_tripwire_sidecar_for_offline_tests(
        command_id,
        tuple(records),
        extra_lines=tuple(extra_lines),
    )


def _tripwire_record(event_id, *, command_id, node_id, phase, sequence):
    exception_type, frame = _TRIPWIRE_TEST_SIGNATURES[event_id]
    return {
        "command_id": command_id,
        "event": {
            "event_id": event_id,
            "exception_type": exception_type,
            "frame": frame,
        },
        "node_id": node_id,
        "phase": phase,
        "sequence": sequence,
    }


@pytest.mark.parametrize("event_id", tuple(_TRIPWIRE_TEST_SIGNATURES))
def test_authenticated_sidecar_is_required_for_each_tripwire_event(event_id):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    command_id = "backend" if not event_id.startswith("browser_") else "browser"
    record = _tripwire_record(
        event_id,
        command_id=command_id,
        node_id="test_uncaught_breaker",
        phase="call",
        sequence=1,
    )
    stderr = _signed_tripwire_sidecar(command_id, (record,))

    evidence = module.parse_pytest_junit_bytes(
        _authenticated_tripwire_junit(event_id).encode("utf-8"),
        stderr_payload=stderr,
        command_id=command_id,
        require_tripwire_auth=True,
    )

    assert tuple(item.event_id for item in evidence.tripwire_events) == (event_id,)


def test_authenticated_sidecar_union_is_monotonic_across_phases_and_bad_records():
    module = importlib.import_module("scripts.run_interaction_acceptance")
    first = _tripwire_record(
        "external_ai",
        command_id="backend",
        node_id="test_two_phase_breakers",
        phase="setup",
        sequence=1,
    )
    second = _tripwire_record(
        "external_network",
        command_id="backend",
        node_id="test_two_phase_breakers",
        phase="teardown",
        sequence=2,
    )
    stderr = _signed_tripwire_sidecar(
        "backend",
        (first, second, second),
        extra_lines=(b"TASK9_AUTH_V1:EVENT:not-base64:not-a-signature",),
    )
    first_property = re.search(
        r'<property name="task9.tripwire_event" [^>]+/>',
        _authenticated_tripwire_junit("external_ai"),
    ).group(0)
    second_property = re.search(
        r'<property name="task9.tripwire_event" [^>]+/>',
        _authenticated_tripwire_junit("external_network"),
    ).group(0)
    junit = (
        '<testsuite tests="1" failures="1" errors="0" skipped="0">'
        '<testcase name="test_two_phase_breakers"><properties>'
        f"{first_property}{second_property}"
        "</properties>"
        '<failure message="AssertionError: TEST_TRIPWIRE:external_ai">'
        "failure retained"
        "</failure></testcase></testsuite>"
    )

    evidence = module.parse_pytest_junit_bytes(
        junit.encode("utf-8"),
        stderr_payload=stderr,
        command_id="backend",
        require_tripwire_auth=True,
    )

    assert tuple(item.event_id for item in evidence.tripwire_events) == (
        "external_ai",
        "external_network",
    )
    assert evidence.valid is False
    assert evidence.reason == "TRIPWIRE_AUTH_INVALID"


def test_ordinary_property_compile_lookalike_and_wrong_capability_do_not_authenticate():
    module = importlib.import_module("scripts.run_interaction_acceptance")
    forged_junit = _authenticated_tripwire_junit("external_ai").replace(
        "tests/conftest.py:999: AssertionError",
        "tests/conftest.py:999: AssertionError\n# compiled lookalike",
    )
    wrong_command = _tripwire_record(
        "external_ai",
        command_id="other-command",
        node_id="test_uncaught_breaker",
        phase="call",
        sequence=1,
    )
    stderr = _signed_tripwire_sidecar("other-command", (wrong_command,))

    evidence = module.parse_pytest_junit_bytes(
        forged_junit.encode("utf-8"),
        stderr_payload=stderr,
        command_id="backend",
        require_tripwire_auth=True,
    )

    assert evidence.tripwire_events == ()
    assert evidence.valid is False
    assert evidence.reason == "TRIPWIRE_AUTH_INVALID"


@pytest.mark.parametrize("event_id", tuple(_TRIPWIRE_TEST_SIGNATURES))
@pytest.mark.parametrize("orchestrator", ("run-one", "full"))
def test_run_one_and_full_merge_authenticated_event_before_nonzero_decision(
    tmp_path, event_id, orchestrator
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    command_id = "backend" if not event_id.startswith("browser_") else "browser"
    record = _tripwire_record(
        event_id,
        command_id=command_id,
        node_id="test_uncaught_breaker",
        phase="call",
        sequence=1,
    )
    stderr = _signed_tripwire_sidecar(command_id, (record,))
    junit = _authenticated_tripwire_junit(event_id)

    if orchestrator == "run-one":
        artifact_root = tmp_path / "run-one-artifacts"
        artifact_root.mkdir()
        _write_junit(artifact_root, f"{command_id}.junit.xml", junit)
        stable = FakeRunOneResources()
        executor = ScriptedProcessExecutor(
            FakeProcess([(b"ordinary pytest failure\n", stderr, 1)], [False]),
            snapshots=[stable] * 10,
        )
        result = module.run_one_command(
            command_id,
            repo_root=Path(__file__).resolve().parents[1],
            artifact_root=artifact_root,
            parent_env={},
            executor=executor,
            expected_head=stable.git_head,
            version_validator=lambda _root: True,
        )
        decision_outcome = result.command_result.classified_outcome
        observed_events = tuple(
            item.event_id for item in result.evidence.tripwire_events
        )
        exit_code = result.exit_code
    else:
        result = _run_synthetic_tripwire_command(
            module,
            tmp_path,
            command_id=command_id,
            stdout=b"ordinary pytest failure\n",
            stderr=stderr,
            child_exit=1,
            junit_xml=junit,
        )
        decision_outcome = result.decision.outcome
        observed_events = tuple(
            result.report_record["commands"][0]["tripwire_events"]
        )
        exit_code = result.exit_code

    assert exit_code == 3
    assert decision_outcome in {
        module.ClassifiedOutcome.SAFETY_FAILURE,
        module.DecisionOutcome.SAFETY_NO_GO,
    }
    assert observed_events == (event_id,)


def test_full_run_rejects_property_without_authenticated_sidecar(tmp_path):
    module = importlib.import_module("scripts.run_interaction_acceptance")

    result = _run_synthetic_tripwire_command(
        module,
        tmp_path,
        command_id="backend",
        stdout=b"ordinary pytest failure\n",
        child_exit=1,
        junit_xml=_authenticated_tripwire_junit("external_ai"),
    )

    assert result.exit_code == 1
    assert result.decision.outcome is module.DecisionOutcome.TECHNICAL_NO_GO
    assert result.report_record["commands"][0]["tripwire_events"] == []


@pytest.mark.parametrize(
    ("command_id", "breaker_output", "expected_event"),
    (
        (
            "backend",
            b"AssertionError: TEST_TRIPWIRE:external_ai\n",
            "external_ai",
        ),
        (
            "browser",
            b"AssertionError: external edge_tts disabled in browser tests\n",
            "browser_edge_tts",
        ),
        (
            "browser",
            b"PermissionError: non-loopback socket blocked: redacted\n",
            "browser_network",
        ),
    ),
)
def test_full_run_does_not_trust_backend_or_browser_breaker_text_in_raw_logs(
    tmp_path, command_id, breaker_output, expected_event
):
    module = importlib.import_module("scripts.run_interaction_acceptance")

    result = _run_synthetic_tripwire_command(
        module,
        tmp_path,
        command_id=command_id,
        stdout=breaker_output,
        child_exit=7,
    )

    assert result.exit_code == 1
    assert result.decision.outcome is module.DecisionOutcome.TECHNICAL_NO_GO
    assert "TRIPWIRE_FAILURE" not in result.decision.reasons
    assert result.report_record is not None
    assert (
        result.report_record["tripwires"]["provider_tts_socket_context_worker"]
        == "NOT_PROVEN"
    )
    assert result.report_record["commands"][0]["tripwire_events"] == []


@pytest.mark.parametrize(
    ("command_id", "event_id"),
    (("backend", "external_ai"), ("browser", "browser_edge_tts")),
)
def test_full_run_escalates_authenticated_junit_breaker_event_to_safety(
    tmp_path, command_id, event_id
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    record = _tripwire_record(
        event_id,
        command_id=command_id,
        node_id="test_uncaught_breaker",
        phase="call",
        sequence=1,
    )

    result = _run_synthetic_tripwire_command(
        module,
        tmp_path,
        command_id=command_id,
        stdout=b"ordinary pytest failure\n",
        stderr=_signed_tripwire_sidecar(command_id, (record,)),
        child_exit=1,
        junit_xml=_authenticated_tripwire_junit(event_id),
    )

    assert result.exit_code == 3
    assert result.decision.outcome is module.DecisionOutcome.SAFETY_NO_GO
    assert result.decision.reasons == ("TRIPWIRE_FAILURE",)
    assert result.report_record is not None
    assert (
        result.report_record["tripwires"]["provider_tts_socket_context_worker"]
        == "FAIL"
    )
    assert result.report_record["commands"][0]["tripwire_events"] == [event_id]


def test_full_run_rejects_forged_tripwire_property_without_trusted_junit_frame(
    tmp_path,
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    forged = _authenticated_tripwire_junit("external_ai").replace(
        "tests/conftest.py:999: AssertionError",
        "tests/test_forgery.py:999: AssertionError",
    )

    result = _run_synthetic_tripwire_command(
        module,
        tmp_path,
        command_id="backend",
        stdout=b"ordinary pytest failure\n",
        child_exit=1,
        junit_xml=forged,
    )

    assert result.exit_code == 1
    assert result.decision.outcome is module.DecisionOutcome.TECHNICAL_NO_GO
    assert "TRIPWIRE_FAILURE" not in result.decision.reasons
    assert result.report_record is not None
    assert result.report_record["commands"][0]["tripwire_events"] == []
    assert (
        result.report_record["suite_evidence"]["backend"]["reason"]
        == "TRIPWIRE_AUTH_INVALID"
    )


@pytest.mark.parametrize("rehash_forgery", (False, True))
def test_completed_report_rejects_tampered_authenticated_tripwire_junit(
    tmp_path, rehash_forgery
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    event = _tripwire_record(
        "external_ai",
        command_id="backend",
        node_id="test_uncaught_breaker",
        phase="call",
        sequence=1,
    )
    artifact_root, report_record = _completed_suite_artifact_tree(
        module,
        tmp_path,
        command_id="backend",
        evidence_format=module.EvidenceFormat.JUNIT,
        evidence_payload=_authenticated_tripwire_junit("external_ai").encode(),
        stderr=_signed_tripwire_sidecar("backend", (event,)),
        project=True,
    )
    command = next(
        item for item in report_record["commands"] if item["subcommand"] == "backend"
    )
    junit_path = artifact_root / command["junit"]["path"]
    if rehash_forgery:
        tampered = re.sub(
            br"<properties>.*?</properties>", b"", junit_path.read_bytes()
        )
        junit_path.write_bytes(tampered)
        command["junit"].update(
            sha256=hashlib.sha256(tampered).hexdigest(),
            size=len(tampered),
        )
        _refresh_completed_report_files(module, artifact_root, report_record)
    else:
        junit_path.write_bytes(junit_path.read_bytes() + b"\n")

    with pytest.raises(module.CliMisuseError, match="artifact"):
        module.render_completed_report(
            artifact_root / "report.json", tmp_path / "must-not-render.md"
        )


def test_full_run_keeps_ordinary_tripwire_word_assertion_technical(tmp_path):
    module = importlib.import_module("scripts.run_interaction_acceptance")

    result = _run_synthetic_tripwire_command(
        module,
        tmp_path,
        command_id="backend",
        stdout=b"AssertionError: ordinary tripwire helper assertion\n",
        child_exit=7,
    )

    assert result.exit_code == 1
    assert result.decision.outcome is module.DecisionOutcome.TECHNICAL_NO_GO
    assert "TRIPWIRE_FAILURE" not in result.decision.reasons
    assert result.report_record is not None
    assert (
        result.report_record["tripwires"]["provider_tts_socket_context_worker"]
        == "NOT_PROVEN"
    )
    assert result.report_record["commands"][0]["tripwire_events"] == []


@pytest.mark.parametrize(
    "output",
    (
        b'tests/conftest.py:169: raise AssertionError(f"{TEST_TRIPWIRE_PREFIX}external_ai")\nAssertionError: unrelated failure\n',
        b"# caught TEST_TRIPWIRE:external_ai\nAssertionError: unrelated failure\n",
    ),
)
def test_full_run_ignores_source_or_caught_breaker_mentions_on_unrelated_failure(
    tmp_path, output
):
    module = importlib.import_module("scripts.run_interaction_acceptance")

    result = _run_synthetic_tripwire_command(
        module,
        tmp_path,
        command_id="backend",
        stdout=output,
        child_exit=7,
    )

    assert result.exit_code == 1
    assert result.decision.outcome is module.DecisionOutcome.TECHNICAL_NO_GO
    assert "TRIPWIRE_FAILURE" not in result.decision.reasons
    assert result.report_record is not None
    assert result.report_record["commands"][0]["tripwire_events"] == []
    assert (
        result.report_record["tripwires"]["provider_tts_socket_context_worker"]
        == "NOT_PROVEN"
    )


def test_full_run_does_not_treat_successfully_caught_breaker_self_test_as_a_hit(
    tmp_path,
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    stdout = _unit7_passing_tap("synthetic-caught-breaker").replace(
        b"TAP version 13\n",
        b"TAP version 13\n# caught TEST_TRIPWIRE:external_ai\n",
    )

    result = _run_synthetic_tripwire_command(
        module,
        tmp_path,
        command_id="backend",
        stdout=stdout,
        child_exit=0,
    )

    assert result.command_results[0].classified_outcome is module.ClassifiedOutcome.SUCCESS
    assert result.decision.outcome is module.DecisionOutcome.TECHNICAL_NO_GO
    assert "TRIPWIRE_FAILURE" not in result.decision.reasons
    assert result.report_record is not None
    assert (
        result.report_record["tripwires"]["provider_tts_socket_context_worker"]
        == "NOT_PROVEN"
    )
    assert result.report_record["commands"][0]["tripwire_events"] == []


def _write_junit(tmp_path: Path, name: str, xml: str) -> Path:
    path = tmp_path / name
    path.write_text(xml, encoding="utf-8")
    return path


def test_junit_parser_accepts_nonzero_all_pass_evidence(tmp_path):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    path = _write_junit(
        tmp_path,
        "pass.xml",
        '<testsuite tests="2" failures="0" errors="0" skipped="0">'
        '<testcase classname="tests.test_a" name="test_one"/>'
        '<testcase classname="tests.test_a" name="test_two[param]"/>'
        "</testsuite>",
    )

    evidence = module.parse_pytest_junit(path)

    assert evidence.valid is True
    assert evidence.total == 2
    assert evidence.passed == 2
    assert evidence.node_ids == ("test_one", "test_two[param]")
    assert evidence.reason == "PASS"


def test_junit_parser_captures_only_canonical_structured_testcase_properties(tmp_path):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    path = _write_junit(
        tmp_path,
        "properties.xml",
        '<testsuite tests="1" failures="0" errors="0" skipped="0">'
        '<testcase name="test_release_focus_indicator_meets_three_to_one[1024x768]">'
        "<properties>"
        '<property name="task9.focus_measurement" '
        "value='{&quot;targets&quot;:12,&quot;viewport&quot;:&quot;1024x768&quot;}'/>"
        "</properties>"
        "</testcase></testsuite>",
    )

    evidence = module.parse_pytest_junit(path)

    assert evidence.properties == (
        module.EvidenceProperty(
            "test_release_focus_indicator_meets_three_to_one[1024x768]",
            "task9.focus_measurement",
            '{"targets":12,"viewport":"1024x768"}',
        ),
    )


def test_authenticated_browser_junit_accepts_p6_geometry_properties():
    module = importlib.import_module("scripts.run_interaction_acceptance")
    properties = (
        (
            "test_release_search_filters_results_and_focus_stay_in_bounds[1024x768]",
            "task8.search_geometry",
            '{"filter_height":391,"focus_ratios":[17.74,17.74],'
            '"minimum_target_height":44,"viewport":{"height":768,"width":1024}}',
        ),
        (
            "test_release_today_weekly_metrics_retry_and_grid_stay_in_bounds[1024x768]",
            "task7.today_metrics_geometry",
            '{"metric_cards":5,"retry_height":44,"retry_width":142,'
            '"viewport":{"height":768,"width":1024}}',
        ),
    )
    testcases = "".join(
        '<testcase name="{}"><properties><property name="{}" value="{}"/>'
        "</properties></testcase>".format(
            node_id,
            name,
            html.escape(value, quote=True),
        )
        for node_id, name, value in properties
    )
    junit = (
        '<testsuite tests="2" failures="0" errors="0" skipped="0">'
        f"{testcases}</testsuite>"
    ).encode("utf-8")

    evidence = module.parse_pytest_junit_bytes(
        junit,
        stderr_payload=_signed_tripwire_sidecar("browser", ()),
        command_id="browser",
        require_tripwire_auth=True,
    )

    assert evidence.valid is True
    assert evidence.reason == "PASS"
    assert evidence.properties == tuple(
        module.EvidenceProperty(node_id, name, value)
        for node_id, name, value in properties
    )


def test_focus_evidence_label_oracle_covers_current_teacher_modal_journey():
    module = importlib.import_module("scripts.run_interaction_acceptance")

    assert module._FOCUS_EVIDENCE_LABELS == (
        "input",
        "confirmation-input",
        "native-button",
        "route-h1",
        "nav-button",
        "link",
        "route-h2",
        "primary-blue-button",
        "white-panel-control",
        "create-dialog-target",
        "create-dialog-return",
        "gray-button",
        "dialog-target",
        "dialog-return",
        "duck-primary-button",
        "textarea",
        "duck-dialog-return",
        "select",
    )

    viewport = {"height": 768, "width": 1024}
    assert (
        module._validate_focus_property(
            _structured_property_payload("focus", viewport), "1024x768"
        )
        is True
    )


def test_junit_parser_counts_failure_error_skip_xfail_and_xpass(tmp_path):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    path = _write_junit(
        tmp_path,
        "nonpass.xml",
        '<testsuite tests="6" failures="2" errors="1" skipped="2">'
        '<testcase name="pass"/>'
        '<testcase name="failure"><failure message="assertion"/></testcase>'
        '<testcase name="error"><error message="collection"/></testcase>'
        '<testcase name="skip"><skipped message="skip"/></testcase>'
        '<testcase name="xfail"><skipped type="pytest.xfail" message="expected failure"/></testcase>'
        '<testcase name="xpass"><failure message="[XPASS(strict)] synthetic ordinary XPASS"/></testcase>'
        "</testsuite>",
    )

    evidence = module.parse_pytest_junit(path)

    assert evidence.valid is False
    assert (
        evidence.total,
        evidence.passed,
        evidence.failures,
        evidence.errors,
        evidence.skipped,
        evidence.xfailed,
        evidence.xpassed,
    ) == (6, 1, 1, 1, 1, 1, 1)
    assert evidence.reason == "NONPASS_TESTS"


def _suite_state(module, **overrides):
    values = {
        "valid": True,
        "total": 1,
        "passed": 1,
        "failures": 0,
        "errors": 0,
        "skipped": 0,
        "xfailed": 0,
        "xpassed": 0,
        "todo": 0,
        "cancelled": 0,
        "node_ids": ("test_pass",),
        "reason": "PASS",
    }
    values.update(overrides)
    return module.SuiteEvidence(**values)


@pytest.mark.parametrize(
    "overrides",
    [
        {"valid": 1},
        {"total": -1},
        {"passed": 0},
        {"skipped": 1},
        {"total": 0, "passed": 0, "node_ids": ()},
        {"node_ids": ["test_pass"]},
        {"node_ids": ("",)},
        {"reason": "NONPASS_TESTS"},
        {"valid": False, "reason": "PASS"},
    ],
)
def test_suite_evidence_constructor_rejects_inconsistent_counter_states(overrides):
    module = importlib.import_module("scripts.run_interaction_acceptance")

    with pytest.raises(ValueError, match="invalid suite evidence state"):
        _suite_state(module, **overrides)


@pytest.mark.parametrize(
    ("name", "xml", "reason"),
    [
        (
            "zero.xml",
            '<testsuite tests="0" failures="0" errors="0" skipped="0"/>',
            "ZERO_TESTS",
        ),
        ("malformed.xml", "<testsuite><testcase>", "MALFORMED_XML"),
        (
            "duplicate.xml",
            '<testsuite tests="2" failures="0" errors="0" skipped="0">'
            '<testcase name="same"/><testcase name="same"/></testsuite>',
            "DUPLICATE_NODE_ID",
        ),
    ],
)
def test_junit_parser_rejects_zero_malformed_and_duplicate_evidence(
    tmp_path, name, xml, reason
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    evidence = module.parse_pytest_junit(_write_junit(tmp_path, name, xml))

    assert evidence.valid is False
    assert evidence.reason == reason


def test_tap_parser_accepts_nonzero_all_pass_evidence():
    module = importlib.import_module("scripts.run_interaction_acceptance")
    tap = b"""TAP version 13
# Subtest: first
ok 1 - first
# Subtest: second
ok 2 - second
1..2
# tests 2
# pass 2
# fail 0
# cancelled 0
# skipped 0
# todo 0
"""

    evidence = module.parse_node_tap(tap)

    assert evidence.valid is True
    assert evidence.total == 2
    assert evidence.passed == 2
    assert evidence.node_ids == ("first", "second")
    assert evidence.reason == "PASS"


@pytest.mark.parametrize(
    ("tap", "expected_counts"),
    [
        (
            b"TAP version 13\nnot ok 1 - failed\n1..1\n# tests 1\n# pass 0\n# fail 1\n# cancelled 0\n# skipped 0\n# todo 0\n",
            (1, 0, 1, 0, 0, 0),
        ),
        (
            b"TAP version 13\nok 1 - skipped # SKIP unavailable\n1..1\n# tests 1\n# pass 0\n# fail 0\n# cancelled 0\n# skipped 1\n# todo 0\n",
            (1, 0, 0, 1, 0, 0),
        ),
        (
            b"TAP version 13\nok 1 - later # TODO pending\n1..1\n# tests 1\n# pass 0\n# fail 0\n# cancelled 0\n# skipped 0\n# todo 1\n",
            (1, 0, 0, 0, 1, 0),
        ),
        (
            b"TAP version 13\nnot ok 1 - cancelled\n  ---\n  failureType: cancelledByParent\n  ...\n1..1\n# tests 1\n# pass 0\n# fail 0\n# cancelled 1\n# skipped 0\n# todo 0\n",
            (1, 0, 0, 0, 0, 1),
        ),
    ],
)
def test_tap_parser_counts_failure_skip_todo_and_cancel(tap, expected_counts):
    module = importlib.import_module("scripts.run_interaction_acceptance")

    evidence = module.parse_node_tap(tap)

    assert evidence.valid is False
    assert (
        evidence.total,
        evidence.passed,
        evidence.failures,
        evidence.skipped,
        evidence.todo,
        evidence.cancelled,
    ) == expected_counts
    assert evidence.reason == "NONPASS_TESTS"


@pytest.mark.parametrize(
    ("tap", "reason"),
    [
        (b"TAP version 13\n1..0\n# tests 0\n", "ZERO_TESTS"),
        (b"TAP version 13\nok 1 - one\n1..2\n", "MALFORMED_TAP"),
        (b"TAP version 13\n\xff\n", "INVALID_UTF8"),
        (
            b"TAP version 13\nok 1 - same\nok 2 - same\n1..2\n",
            "DUPLICATE_NODE_ID",
        ),
    ],
)
def test_tap_parser_rejects_zero_malformed_utf8_and_duplicate_subtests(tap, reason):
    module = importlib.import_module("scripts.run_interaction_acceptance")

    evidence = module.parse_node_tap(tap)

    assert evidence.valid is False
    assert evidence.reason == reason


EXPECTED_GATE_TITLES = {
    1: "application DB unchanged",
    2: "version match and mismatch lock",
    3: "duplicate prevention",
    4: "failed utterance retained, no fake reply",
    5: "refresh recovery",
    6: "microphone denial help",
    7: "saved child exit, tracked analysis",
    8: "complete review round-trip",
    9: "review identity/time/ID/status",
    10: "15-second bounded TTS fallback",
    11: "roster replay",
    12: "undoable deactivation",
    13: "keyboard core flows",
    14: "real interaction/fault/DB assertions",
}

EXPECTED_INTERNAL_EVIDENCE = (
    (
        "resource",
        "global_and_per_command_logical_and_physical_equality",
        1,
        (1, 14),
    ),
    ("resource", "inherited_user_paths_and_git_porcelain_equal", 1, (1, 14)),
    ("runtime", "tested_head_api_schema_and_release_versions_exact", 1, (2, 14)),
    (
        "tripwire",
        "provider_tts_socket_context_and_worker_tripwires_clean",
        1,
        (14,),
    ),
    (
        "browser_db",
        "exact_fixture_path_and_read_only_zero_to_one_business_row",
        1,
        (14,),
    ),
)

EXPECTED_TODAY_RETRY_SELECTOR_ROWS = (
    (
        "browser",
        r"^test_teacher_today_analysis_retry_failures_restore_only_the_row_action_with_safe_copy\[(mismatch|malformed|401|404|409|500|non-json)-(1024x768|1440x900)\]$",
        14,
        (7, 14),
    ),
    (
        "browser",
        r"^test_teacher_today_analysis_retry_offline_is_single_flight_until_transport_rejects\[(1024x768|1440x900)\]$",
        2,
        (3, 7, 14),
    ),
)


_P6_SELECTOR_ADDITIONS_TEXT = r"""backend | ^test_runtime_context_is_public_static_exact_and_reads_date_once$ | 1 | 2,14
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
browser | ^test_release_avatar_upload_and_fallback_stay_in_bounds\[(1024x768|1440x900)\]$ | 2 | 12,14"""


_P6_POST_REVIEW_SELECTOR_ADDITIONS_TEXT = r"""backend | ^test_schema_two_(legacy_avatars_remain_stored_but_every_identity_read_projects_null|canonical_avatar_urls_survive_upgrade_and_every_identity_read)$ | 2 | 1,9,12,14
backend | ^test_search_fails_closed_when_review_status_drifts_during_projection$ | 1 | 8,9,14
backend | ^test_protected_teacher_json_write_inventory_uses_manual_body_dependencies$ | 1 | 3,14
backend | ^test_unauthenticated_teacher_write_rejects_before_receiving_json_body\[(post-/api/children|put-/api/children/\{child_id\}|post-/api/ducks|put-/api/ducks/\{duck_id\}|post-/api/roster/auto|post-/api/roster/month|put-/api/roster/\{roster_date\}|put-/api/conversations/\{conversation_id\}/review|post-/api/dimensions|put-/api/dimensions/\{dim_id\}|put-/api/ducks/\{duck_id\}/archive)\]$ | 11 | 3,14
backend | ^test_manual_body_dependency_preserves_strict_content_type_behavior$ | 1 | 3,14"""


_P6_AUDIT_FIX_SELECTOR_ADDITIONS_TEXT = r"""backend | ^test_roster_telemetry_never_reads_or_reports_a_body_rejected_by_auth\[(valid-single-chunk|malformed-single-chunk|malformed-multiple-chunks)\]$ | 3 | 3,14
backend | ^test_provider_settings_normalize_official_deepseek_openai_base_urls\[(official-root|official-root-trailing-slash|compatible-v1|compatible-v1-trailing-slash)\]$ | 4 | 4,7,8,14
backend | ^test_provider_settings_default_to_the_compatible_deepseek_v1_path$ | 1 | 4,7,8,14
backend | ^test_provider_settings_reject_nonofficial_deepseek_origins_and_paths\[(insecure-scheme|attacker-origin|lookalike-suffix-origin|official-prefix-origin|userinfo-username|userinfo-password|nondefault-port|query|fragment|other-version-path|endpoint-path|nested-compatible-path)\]$ | 12 | 4,7,8,14
backend | ^test_(fake_harness_dry_run_has_one_stdout_owned_stop_redaction_and_retained_failure|execute_retained_uat_rejects_teacher_pin_not_matching_runtime_scrypt)$ | 2 | 14
backend | ^test_finish_live_server_retries_cleanup_after_stopper_fails_before_signal$ | 1 | 14
backend | ^test_finish_live_server_continues_cleanup_when_initial_observation_fails$ | 1 | 14
backend | ^test_run_seed_process_cleans_owned_group_after_observation_failure$ | 1 | 14
backend | ^test_launch_server_process_preserves_owner_when_both_cleanup_attempts_fail$ | 1 | 14
backend | ^test_finish_live_server_skips_io_for_preclosed_output_and_converges$ | 1 | 14
backend | ^test_finish_live_server_remembers_close_that_raised_after_closing$ | 1 | 14
backend | ^test_process_group_members_bounds_the_ps_subprocess$ | 1 | 14
backend | ^test_owned_process_group_does_not_rediscover_members_after_reaping_leader$ | 1 | 14
backend | ^test_launch_identity_failure_retries_direct_reap_without_group_signal$ | 1 | 14
backend | ^test_start_live_server_preserves_owner_when_cleanup_and_collector_stop_fail$ | 1 | 14
backend | ^test_execute_retained_uat_preserves_server_starter_owned_cleanup_error$ | 1 | 14
backend | ^test_execute_retained_uat_retries_finisher_and_preserves_readiness_error$ | 1 | 14
backend | ^test_finish_live_server_closes_output_after_flush_or_fsync_failure\[(flush-expected_output_calls0-expected_fsync_calls0|fsync-expected_output_calls1-expected_fsync_calls1)\]$ | 2 | 14
backend | ^test_start_live_server_preserves_launcher_owned_error_during_parent_cleanup$ | 1 | 14
backend | ^test_api_error_can_carry_a_controlled_retry_after_header$ | 1 | 3,14
backend | ^test_api_error_rejects_uncontrolled_or_noncanonical_headers\[(unsupported-name|negative-value|header-injection|non-string-value)\]$ | 4 | 3,14
backend | ^test_(matching_attacker_host_and_origin_are_rejected_against_scope_server|static_request_with_host_different_from_scope_server_is_rejected)$ | 2 | 3,14
backend | ^test_app_mode_rejects_non_loopback_scope_even_when_host_matches\[(attacker\.example|localhost|0\.0\.0\.0)\]$ | 3 | 3,14
backend | ^test_(app_mode_allows_exact_loopback_scope_host_and_port|duplicate_raw_host_headers_are_rejected)$ | 2 | 3,14
backend | ^test_host_header_must_include_the_exact_nondefault_scope_port\[(testserver|testserver:8124)\]$ | 2 | 3,14
backend | ^test_(launch_server_process_hands_validated_owner_to_outer_guardian|start_live_server_hands_pending_session_to_outer_finisher)$ | 2 | 14
backend | ^test_second_round_(unverified_launch_cleanup_retains_exact_process_and_errors|unverified_seed_cleanup_retains_exact_process_and_errors|start_attaches_pending_session_for_outer_takeover|execute_recovers_pending_session_from_failed_starter|entrypoint_guardian_retries_validated_owner_until_reaped|entrypoint_latches_sigterm_until_guardian_reaps_owner|early_sigterm_is_not_lost_before_main_execute|execute_rejects_preexisting_termination_before_resources|main_rejects_sigterm_latched_inside_execute|signal_aware_stream_does_not_yield_after_select_race|signal_after_terminal_linearization_is_not_latched|entrypoint_guardian_never_returns_with_pending_owner|entrypoint_guardian_reaps_exact_unverified_process_only|start_preserves_unverified_process_when_other_cleanup_fails|guardian_retries_pending_session_finalization_to_terminal|telemetry_invalid_payload_joins_once_and_rethrows_same_error|telemetry_unexpected_parser_error_fails_closed|session_converges_terminal_telemetry_error_without_redrain|execute_preserves_primary_cleanup_and_finalization_order|failed_manifest_does_not_replace_pending_validated_owner|write_fd_close_after_close_cannot_hit_reused_descriptor|read_fd_transfer_cannot_close_collector_reused_descriptor|collector_constructor_failure_closes_borrowed_read_fd|atomic_write_close_after_close_cannot_hit_reused_descriptor|terminal_commit_fsyncs_parent_after_replace|terminal_commit_rejects_signal_during_precommit|terminal_replace_failure_clears_completion_latch|terminal_replace_then_raise_is_verified_as_committed|terminal_replace_ambiguity_retries_transient_verification|directory_traversal_close_after_close_preserves_reused_fd\[(absolute|plan-root|plan-parent)\]|output_fd_is_closed_when_parent_descriptor_close_fails|seed_nonzero_primary_survives_cleanup_failure|reaped_status_mismatch_marks_process_resource_complete|entrypoint_finishes_generic_pending_session_resources|startup_complete_marker_resources_reach_entrypoint_guardian|startup_cleanup_success_retains_unfinished_telemetry|preowner_startup_failure_retains_collector_until_guardian|preoutput_startup_failure_retains_collector_until_guardian|fdopen_failure_closes_raw_output_before_retaining_collector)$ | 41 | 14
backend | ^test_review_detail_(uses_one_sqlite_snapshot_across_a_concurrent_atomic_save|reuses_an_existing_sqlite_transaction|success_preserves_a_callers_pending_sqlite_transaction|error_preserves_a_callers_pending_sqlite_transaction|preserves_a_callers_unflushed_orm_transaction|releases_its_owned_snapshot_after_an_unexpected_error|begin_failure_releases_helper_created_session_transaction|begin_failure_preserves_caller_owned_orm_transaction)$ | 8 | 8,9,14
backend | ^test_schema_three_head_initializes_singleton_teacher_pin_throttle$ | 1 | 1,14
backend | ^test_(five_failures_allow_no_sixth_attempt_even_with_the_correct_pin|pin_failures_use_a_rolling_fifteen_minute_window|success_atomically_clears_recent_failure_state|failure_state_survives_a_new_testclient_session|six_concurrent_wrong_pins_are_serialized_at_the_global_limit|duplicate_setup_repairs_a_missing_throttle_singleton)$ | 6 | 3,14
backend | ^test_(owned_process_group_reaps_real_short_lived_wnowait_child|exact_exited_leader_can_signal_only_prevalidated_same_session_descendants|exact_exited_leader_rejects_foreign_session_member_without_signal|live_server_accepts_only_canonical_macos_text_encoding)$ | 4 | 14"""

_P6_UAT_INCIDENT_SELECTOR_ADDITIONS_TEXT = r"""browser | ^test_tts_11000ms_cold_start_uses_same_request_audio_path\[(1024x576|1280x720)\]$ | 2 | 10,14
browser | ^test_chat_11000ms_response_uses_same_request_and_audio_path\[(1024x576|1280x720)\]$ | 2 | 3,4,10,14
backend | ^test_(llm_retry_fence_can_stop_the_second_transport_attempt|chat_reply_forwards_retry_fence_to_llm|chat_lease_renewal_requires_exact_owner_and_attempt_fence|chat_lease_guard_publishes_expiry_loss_atomically_with_renewal|terminal_chat_cas_checks_fresh_lease_time_without_changing_business_timestamps|terminal_chat_lease_clock_is_sampled_after_sqlite_writer_slot\[(success|failure)\]|fixed_max_round_route_uses_fresh_lease_time_before_terminal_write|pre_provider_failure_uses_fresh_lease_time_before_terminal_write\[(api|internal)\]|chat_heartbeat_recovers_after_one_transient_database_error|chat_heartbeat_marks_lease_lost_when_database_errors_outlive_expiry|chat_heartbeat_fences_one_failed_renewal_that_returns_after_lease_expiry|chat_heartbeat_marks_lost_before_any_post_miss_clock_work|chat_heartbeat_publishes_durable_renewal_before_retry_fence_rechecks|slow_chat_success_stays_owned_and_duplicate_cannot_reclaim_after_original_expiry|lost_chat_lease_discards_result_and_fences_provider_retry|slow_chat_failure_is_recorded_by_original_owner_after_lease_extension|chat_failure_reclaimed_after_heartbeat_join_returns_in_progress|chat_joins_inflight_heartbeat_before_terminal_database_write\[(success|failure)\])$ | 21 | 3,4,14"""

_P5_CHAT_TIMEOUT_SELECTOR_ROW = (
    "browser",
    r"^test_first_chat_timeout_retains_draft_and_reuses_request_id_once\[(1024x576|1280x720)\]$",
    2,
    (3, 4, 14),
)
_P6_CHAT_TIMEOUT_SELECTOR_ROW = (
    "browser",
    r"^test_first_chat_thirty_second_timeout_retains_draft_and_reuses_request_id_once\[(1024x576|1280x720)\]$",
    2,
    (3, 4, 14),
)

_P5_TTS_SELECTOR_ROW = (
    "browser",
    r"^test_tts_cold_start_uses_reachable_five_second_fallback\[(1024x576|1280x720)\]$",
    2,
    (10, 14),
)
_P6_TTS_SELECTOR_ROW = (
    "browser",
    r"^test_tts_cold_start_uses_reachable_fifteen_second_fallback\[(1024x576|1280x720)\]$",
    2,
    (10, 14),
)


_P5_SELECTOR_ORACLE = (
    Path(__file__).resolve().parent
    / "fixtures/interaction_acceptance/p5_selector_oracle.json"
)
_P5_SELECTOR_ORACLE_SHA256 = (
    "3c07aa2a66c32839f47b0e313aa796cf08bb5dc2cd6197eb14b0a22045c2f6a4"
)
_P6_SELECTOR_ADDITIONS_SHA256 = (
    "38ef5ceacb3b34e5a64e92f5d98b1a7deeeee5a9831281671c4ebac7241b9031"
)
_P6_POST_REVIEW_SELECTOR_ADDITIONS_SHA256 = (
    "ed7fe56d4422466c4f88b5e27a208fb89e0d57297bbbc2dccb724b2f7440f24b"
)
_P6_AUDIT_FIX_SELECTOR_ADDITIONS_SHA256 = (
    "1f5be2060f97659b11bb8b92d140538446f22bf737a6b40af407817654e2237b"
)
_P6_UAT_INCIDENT_SELECTOR_ADDITIONS_SHA256 = (
    "096f9af80d91445ca2d18f344690af57225d21631b6e742150cb47c049a39929"
)


def _selector_rows(text):
    rows = []
    for line in text.splitlines():
        command_id, pattern, count, gates = line.split(" | ")
        rows.append(
            (command_id, pattern, int(count), tuple(int(gate) for gate in gates.split(",")))
        )
    return tuple(rows)


def test_p5_selector_oracle_fixture_has_frozen_sha_and_literal_schema():
    oracle_bytes = _P5_SELECTOR_ORACLE.read_bytes()

    assert hashlib.sha256(oracle_bytes).hexdigest() == _P5_SELECTOR_ORACLE_SHA256
    oracle = json.loads(oracle_bytes.decode("utf-8", errors="strict"))
    assert type(oracle) is dict
    assert tuple(oracle) == ("schema_version", "release", "row_count", "rows")
    assert oracle["schema_version"] == 1
    assert oracle["release"] == "P5"
    assert oracle["row_count"] == 97
    assert type(oracle["rows"]) is list
    assert len(oracle["rows"]) == 97
    for row in oracle["rows"]:
        assert type(row) is dict
        assert tuple(row) == (
            "command_id",
            "node_pattern",
            "expected_count",
            "gates",
        )
        assert row["command_id"] in {
            "backend",
            "shared_node",
            "child_node",
            "teacher_node",
            "browser",
        }
        assert type(row["node_pattern"]) is str and row["node_pattern"]
        assert type(row["expected_count"]) is int and row["expected_count"] > 0
        assert type(row["gates"]) is list and row["gates"]
        assert all(type(gate) is int and 1 <= gate <= 14 for gate in row["gates"])
        assert row["gates"] == sorted(set(row["gates"]))


def _p5_frozen_manifest_rows():
    oracle_bytes = _P5_SELECTOR_ORACLE.read_bytes()
    assert hashlib.sha256(oracle_bytes).hexdigest() == _P5_SELECTOR_ORACLE_SHA256
    oracle = json.loads(oracle_bytes.decode("utf-8", errors="strict"))
    assert tuple(oracle) == ("schema_version", "release", "row_count", "rows")
    assert (oracle["schema_version"], oracle["release"], oracle["row_count"]) == (
        1,
        "P5",
        97,
    )
    assert len(oracle["rows"]) == 97
    return tuple(
        (
            row["command_id"],
            row["node_pattern"],
            row["expected_count"],
            tuple(row["gates"]),
        )
        for row in oracle["rows"]
    )


def _p6_frozen_manifest_rows():
    assert (
        hashlib.sha256(_P6_SELECTOR_ADDITIONS_TEXT.encode("utf-8")).hexdigest()
        == _P6_SELECTOR_ADDITIONS_SHA256
    )
    return _selector_rows(_P6_SELECTOR_ADDITIONS_TEXT)


def _p6_post_review_manifest_rows():
    assert (
        hashlib.sha256(
            _P6_POST_REVIEW_SELECTOR_ADDITIONS_TEXT.encode("utf-8")
        ).hexdigest()
        == _P6_POST_REVIEW_SELECTOR_ADDITIONS_SHA256
    )
    return _selector_rows(_P6_POST_REVIEW_SELECTOR_ADDITIONS_TEXT)


def _p6_audit_fix_manifest_rows():
    assert (
        hashlib.sha256(
            _P6_AUDIT_FIX_SELECTOR_ADDITIONS_TEXT.encode("utf-8")
        ).hexdigest()
        == _P6_AUDIT_FIX_SELECTOR_ADDITIONS_SHA256
    )
    return _selector_rows(_P6_AUDIT_FIX_SELECTOR_ADDITIONS_TEXT)


def _p6_uat_incident_manifest_rows():
    assert (
        hashlib.sha256(
            _P6_UAT_INCIDENT_SELECTOR_ADDITIONS_TEXT.encode("utf-8")
        ).hexdigest()
        == _P6_UAT_INCIDENT_SELECTOR_ADDITIONS_SHA256
    )
    return _selector_rows(_P6_UAT_INCIDENT_SELECTOR_ADDITIONS_TEXT)


def _current_p5_manifest_rows():
    """Keep immutable P5 evidence while versioning changed P6 timeout contracts."""
    rows = _p5_frozen_manifest_rows()
    assert rows.count(_P5_TTS_SELECTOR_ROW) == 1
    assert rows.count(_P5_CHAT_TIMEOUT_SELECTOR_ROW) == 1
    return tuple(
        _P6_TTS_SELECTOR_ROW
        if row == _P5_TTS_SELECTOR_ROW
        else _P6_CHAT_TIMEOUT_SELECTOR_ROW
        if row == _P5_CHAT_TIMEOUT_SELECTOR_ROW
        else row
        for row in rows
    )


def _frozen_manifest_rows():
    return (
        _current_p5_manifest_rows()
        + _p6_frozen_manifest_rows()
        + _p6_post_review_manifest_rows()
        + _p6_audit_fix_manifest_rows()
        + _p6_uat_incident_manifest_rows()
    )


def test_literal_p5_selector_oracle_has_explicit_p6_timeout_replacements():
    module = importlib.import_module("scripts.run_interaction_acceptance")
    p5_rows = _p5_frozen_manifest_rows()
    current_p5_rows = _current_p5_manifest_rows()
    p6_rows = _p6_frozen_manifest_rows()
    post_review_rows = _p6_post_review_manifest_rows()
    audit_fix_rows = _p6_audit_fix_manifest_rows()
    uat_incident_rows = _p6_uat_incident_manifest_rows()
    actual_rows = tuple(
        (row.command_id, row.node_pattern, row.expected_count, row.gates)
        for row in module.SELECTOR_MANIFEST
    )

    assert len(p5_rows) == 97
    assert len(p6_rows) == 56
    assert len(post_review_rows) == 5
    assert len(audit_fix_rows) == 31
    assert len(uat_incident_rows) == 3
    p6_end = len(p5_rows) + len(p6_rows)
    post_review_end = p6_end + len(post_review_rows)
    assert _P5_TTS_SELECTOR_ROW in p5_rows
    assert _P5_TTS_SELECTOR_ROW not in actual_rows
    assert _P6_TTS_SELECTOR_ROW in actual_rows
    assert _P5_CHAT_TIMEOUT_SELECTOR_ROW in p5_rows
    assert _P5_CHAT_TIMEOUT_SELECTOR_ROW not in actual_rows
    assert _P6_CHAT_TIMEOUT_SELECTOR_ROW in actual_rows
    assert actual_rows[: len(p5_rows)] == current_p5_rows
    assert actual_rows[len(p5_rows) : p6_end] == p6_rows
    assert actual_rows[p6_end:post_review_end] == post_review_rows
    audit_fix_end = post_review_end + len(audit_fix_rows)
    assert actual_rows[post_review_end:audit_fix_end] == audit_fix_rows
    assert actual_rows[audit_fix_end:] == uat_incident_rows
    assert _frozen_manifest_rows() == (
        current_p5_rows
        + p6_rows
        + post_review_rows
        + audit_fix_rows
        + uat_incident_rows
    )


def _concat_expansions(left, right):
    return tuple(prefix + suffix for prefix in left for suffix in right)


def _expand_finite_regex_tokens(tokens):
    expanded = ("",)
    for opcode, argument in tokens:
        if opcode is sre_constants.AT:
            fragment = ("",)
        elif opcode is sre_constants.LITERAL:
            fragment = (chr(argument),)
        elif opcode is sre_constants.SUBPATTERN:
            fragment = _expand_finite_regex_tokens(argument[-1])
        elif opcode is sre_constants.BRANCH:
            fragment = tuple(
                value
                for branch in argument[1]
                for value in _expand_finite_regex_tokens(branch)
            )
        elif opcode in {sre_constants.MAX_REPEAT, sre_constants.MIN_REPEAT}:
            minimum, maximum, repeated = argument
            assert minimum == maximum
            fragment = ("",)
            repeated_fragment = _expand_finite_regex_tokens(repeated)
            for _index in range(minimum):
                fragment = _concat_expansions(fragment, repeated_fragment)
        else:
            raise AssertionError(f"non-finite manifest regex opcode: {opcode!r}")
        expanded = _concat_expansions(expanded, fragment)
    return expanded


def _materialize_pattern(pattern):
    return _expand_finite_regex_tokens(sre_parse.parse(pattern))


def _suite_evidence(module, node_ids):
    node_ids = tuple(node_ids)
    return module.SuiteEvidence(
        valid=bool(node_ids),
        total=len(node_ids),
        passed=len(node_ids),
        failures=0,
        errors=0,
        skipped=0,
        xfailed=0,
        xpassed=0,
        todo=0,
        cancelled=0,
        node_ids=node_ids,
        reason="PASS" if node_ids else "ZERO_TESTS",
    )


def _complete_gate_evidence(module):
    by_command = {}
    for command_id, pattern, _count, _gates in _frozen_manifest_rows():
        by_command.setdefault(command_id, []).extend(_materialize_pattern(pattern))
    suites = {
        command_id: _suite_evidence(module, node_ids)
        for command_id, node_ids in by_command.items()
    }
    internal = tuple(
        module.InternalEvidence(source, evidence_id, passed=True, fresh=True, valid=True)
        for source, evidence_id, _count, _gates in EXPECTED_INTERNAL_EVIDENCE
    )
    return module.EvidenceMap(suites=suites, internal=internal)


def test_gate_manifest_has_all_frozen_rows_literal_parameters_and_reverse_index():
    module = importlib.import_module("scripts.run_interaction_acceptance")
    expected_rows = _frozen_manifest_rows()
    actual_rows = tuple(
        (row.command_id, row.node_pattern, row.expected_count, row.gates)
        for row in module.SELECTOR_MANIFEST
    )

    actual_today_retry_rows = tuple(
        row
        for row in actual_rows
        if "test_teacher_today_analysis_retry_failures_restore" in row[1]
        or "test_teacher_today_analysis_retry_offline_is_single_flight" in row[1]
    )

    assert actual_today_retry_rows == EXPECTED_TODAY_RETRY_SELECTOR_ROWS
    assert actual_rows == expected_rows
    assert len(actual_rows) == 192
    assert module.GATE_TITLES == EXPECTED_GATE_TITLES
    assert tuple(
        (item.source, item.evidence_id, item.expected_count, item.gates)
        for item in module.INTERNAL_EVIDENCE_REQUIREMENTS
    ) == EXPECTED_INTERNAL_EVIDENCE
    assert set(gate for row in actual_rows for gate in row[3]) == set(range(1, 15))

    materialized_count = 0
    for command_id, pattern, expected_count, _gates in expected_rows:
        compiled = re.compile(pattern)
        node_ids = _materialize_pattern(pattern)
        assert len(node_ids) == expected_count
        assert len(set(node_ids)) == expected_count
        assert all(compiled.fullmatch(node_id) for node_id in node_ids)
        assert not compiled.fullmatch(node_ids[0] + "__same_count_substitution")
        for node_id in node_ids:
            matches = [
                candidate
                for candidate in module.SELECTOR_MANIFEST
                if candidate.command_id == command_id
                and re.fullmatch(candidate.node_pattern, node_id)
            ]
            assert len(matches) == 1
        materialized_count += len(node_ids)
    assert materialized_count == 526

    assert module.SELECTOR_TO_GATES == {
        (row.command_id, row.node_pattern): row.gates for row in module.SELECTOR_MANIFEST
    }


def test_p6_runtime_version_is_additive_to_runner_schema_two():
    module = importlib.import_module("scripts.run_interaction_acceptance")

    assert module.FROZEN_RUNTIME_VERSION == {
        "release_id": "2026.09.02-server-capabilities.1",
        "api_version": "3",
        "schema_version": "3",
    }
    assert module.REPORT_SCHEMA_VERSION == 2


def test_resource_snapshot_shape_adds_main_media_without_dropping_p5_fields():
    module = importlib.import_module("scripts.run_interaction_acceptance")

    assert tuple(module.ResourceSnapshot.__dataclass_fields__) == (
        "database",
        "log",
        "tts",
        "media",
        "user_paths",
        "git_head",
        "git_porcelain",
        "unsafe_reasons",
    )
    assert tuple(module.CanonicalResourceSnapshot.__dataclass_fields__) == tuple(
        module.ResourceSnapshot.__dataclass_fields__
    )


def test_gate_manifest_allows_clean_ordinary_full_suite_nodes_outside_manifest():
    module = importlib.import_module("scripts.run_interaction_acceptance")
    complete = _complete_gate_evidence(module)
    suites = dict(complete.suites)
    backend = suites["backend"]
    suites["backend"] = _suite_evidence(
        module,
        (*backend.node_ids, "test_ordinary_full_suite_pass_outside_manifest"),
    )

    gates = module.evaluate_gates(
        (), None, module.EvidenceMap(suites=suites, internal=complete.internal)
    )

    assert all(gate.status is module.GateStatus.PASS for gate in gates)


def test_internal_resource_evidence_requires_every_command_to_equal_global_baseline():
    module = importlib.import_module("scripts.run_interaction_acceptance")
    complete = _complete_gate_evidence(module)
    internal_sources = {
        **complete.suites,
        "release_db_action_all": _suite_evidence(module, ("db-action-proof",)),
    }
    baseline = FakeResources(token="global-a")
    forged = FakeResources(token="forged-b")

    def success_with(snapshot):
        return module.CommandResult(
            subcommand="runner",
            child_started=True,
            child_exit=0,
            termination=module.Termination.EXITED,
            output_complete=True,
            residual_group_observed=False,
            cleanup_failures=(),
            classified_outcome=module.ClassifiedOutcome.SUCCESS,
            reason="SUCCESS",
            before_snapshot=snapshot,
            after_snapshot=snapshot,
        )

    forged_result = success_with(forged)
    forged_internal = module._run_internal_evidence(
        command_results=(forged_result,),
        all_evidence=internal_sources,
        baseline=baseline,
        final_snapshot=baseline,
        version_exact=True,
    )
    forged_gates = module.evaluate_gates(
        (forged_result,),
        None,
        module.EvidenceMap(suites=complete.suites, internal=forged_internal),
    )

    assert forged_internal[0].passed is False
    assert forged_internal[0].valid is False
    assert forged_gates[0].status is module.GateStatus.BLOCKED
    assert forged_gates[13].status is module.GateStatus.BLOCKED

    anchored_result = success_with(baseline)
    anchored_internal = module._run_internal_evidence(
        command_results=(anchored_result,),
        all_evidence=internal_sources,
        baseline=baseline,
        final_snapshot=baseline,
        version_exact=True,
    )
    anchored_gates = module.evaluate_gates(
        (anchored_result,),
        None,
        module.EvidenceMap(suites=complete.suites, internal=anchored_internal),
    )

    assert anchored_internal[0].passed is True
    assert anchored_internal[0].valid is True
    assert all(
        gate.status is module.GateStatus.PASS for gate in anchored_gates
    ), tuple(
        (gate.gate, gate.reasons)
        for gate in anchored_gates
        if gate.status is not module.GateStatus.PASS
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("total", 0),
        ("passed", 0),
        ("skipped", 1),
        ("xfailed", 1),
        ("xpassed", 1),
        ("todo", 1),
        ("cancelled", 1),
    ],
)
def test_gate_evaluator_revalidates_hostile_suite_counter_state(field, value):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    complete = _complete_gate_evidence(module)
    suites = dict(complete.suites)
    original = suites["backend"]
    hostile = object.__new__(module.SuiteEvidence)
    for state_field in original.__dataclass_fields__:
        object.__setattr__(hostile, state_field, getattr(original, state_field))
    object.__setattr__(hostile, field, value)
    suites["backend"] = hostile

    gates = module.evaluate_gates(
        (), None, module.EvidenceMap(suites=suites, internal=complete.internal)
    )

    assert all(gate.status is module.GateStatus.BLOCKED for gate in gates)
    assert all("INVALID_SUITE:backend" in gate.reasons for gate in gates)


@pytest.mark.parametrize("gate", range(1, 8))
def test_gate_one_through_seven_stays_blocked_after_each_required_deletion(gate):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    complete = _complete_gate_evidence(module)
    assert module.evaluate_gates((), None, complete)[gate - 1].status is module.GateStatus.PASS

    for row in (item for item in module.SELECTOR_MANIFEST if gate in item.gates):
        suites = dict(complete.suites)
        original = suites[row.command_id]
        removable = next(
            node_id
            for node_id in original.node_ids
            if re.fullmatch(row.node_pattern, node_id)
        )
        suites[row.command_id] = _suite_evidence(
            module, (node_id for node_id in original.node_ids if node_id != removable)
        )
        evidence = module.EvidenceMap(suites=suites, internal=complete.internal)
        assert module.evaluate_gates((), None, evidence)[gate - 1].status is module.GateStatus.BLOCKED

    for requirement in (
        item for item in module.INTERNAL_EVIDENCE_REQUIREMENTS if gate in item.gates
    ):
        internal = tuple(
            item
            for item in complete.internal
            if (item.source, item.evidence_id)
            != (requirement.source, requirement.evidence_id)
        )
        evidence = module.EvidenceMap(suites=complete.suites, internal=internal)
        assert module.evaluate_gates((), None, evidence)[gate - 1].status is module.GateStatus.BLOCKED


@pytest.mark.parametrize("gate", range(8, 15))
def test_gate_eight_through_fourteen_rejects_deletion_and_same_count_substitution(gate):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    complete = _complete_gate_evidence(module)
    assert module.evaluate_gates((), None, complete)[gate - 1].status is module.GateStatus.PASS

    for row in (item for item in module.SELECTOR_MANIFEST if gate in item.gates):
        suites = dict(complete.suites)
        original = suites[row.command_id]
        matched = [
            node_id
            for node_id in original.node_ids
            if re.fullmatch(row.node_pattern, node_id)
        ]
        replacement = matched[0] + "__same_count_substitution"
        suites[row.command_id] = _suite_evidence(
            module,
            (
                replacement if node_id == matched[0] else node_id
                for node_id in original.node_ids
            ),
        )
        evidence = module.EvidenceMap(suites=suites, internal=complete.internal)
        assert module.evaluate_gates((), None, evidence)[gate - 1].status is module.GateStatus.BLOCKED

    for requirement in (
        item for item in module.INTERNAL_EVIDENCE_REQUIREMENTS if gate in item.gates
    ):
        internal = tuple(
            item
            for item in complete.internal
            if (item.source, item.evidence_id)
            != (requirement.source, requirement.evidence_id)
        )
        evidence = module.EvidenceMap(suites=complete.suites, internal=internal)
        assert module.evaluate_gates((), None, evidence)[gate - 1].status is module.GateStatus.BLOCKED


def _decision_command(module, outcome=None):
    resources = FakeRunOneResources()
    outcome = outcome or module.ClassifiedOutcome.SUCCESS
    values = {
        module.ClassifiedOutcome.SUCCESS: (0, "SUCCESS", resources),
        module.ClassifiedOutcome.CHILD_NONZERO: (1, "CHILD_NONZERO", resources),
        module.ClassifiedOutcome.SAFETY_FAILURE: (
            0,
            "RESOURCE_DRIFT",
            FakeResources(token="drifted"),
        ),
    }
    child_exit, reason, after_snapshot = values[outcome]
    return module.CommandResult(
        subcommand="runner",
        child_started=True,
        child_exit=child_exit,
        termination=module.Termination.EXITED,
        output_complete=True,
        residual_group_observed=False,
        cleanup_failures=(),
        classified_outcome=outcome,
        reason=reason,
        before_snapshot=resources,
        after_snapshot=after_snapshot,
    )


def _passing_gate_results(module):
    return tuple(
        module.GateResult(
            gate=gate,
            title=title,
            status=module.GateStatus.PASS,
            reasons=(),
        )
        for gate, title in module.GATE_TITLES.items()
    )


def _decision_inputs(module, **changes):
    values = {
        "command_results": (_decision_command(module),),
        "gate_results": _passing_gate_results(module),
        "resources_unchanged": True,
        "tripwires_clean": True,
        "contrast_passed": True,
        "incident_decisions": None,
        "lovable_complete_or_waived": True,
    }
    values.update(changes)
    return module.DecisionInputs(**values)


@pytest.mark.parametrize(
    ("changes", "outcome", "exit_code"),
    [
        (
            {"command_results": None},
            "TECHNICAL_NO_GO",
            1,
        ),
        ({"resources_unchanged": False}, "SAFETY_NO_GO", 3),
        ({"tripwires_clean": False}, "SAFETY_NO_GO", 3),
        ({"contrast_passed": False}, "TECHNICAL_NO_GO", 1),
        ({"incident_decisions": None}, "TECHNICAL_PASS_HUMAN_DECISION_PENDING", 2),
        (
            {
                "incident_decisions": {
                    "PIPELINE_T8_PROVIDER_20260823": "ACCEPT",
                    "CHILD_T9_REAL_LOG_20260827": "REJECT",
                    "TEACHER_T5_REAL_LOG_20260829": "ACCEPT",
                }
            },
            "TECHNICAL_NO_GO",
            1,
        ),
        ({"lovable_complete_or_waived": False}, "TECHNICAL_NO_GO", 1),
    ],
)
def test_decision_model_fails_closed_for_commands_safety_gates_and_authority(
    changes, outcome, exit_code
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    if changes.get("command_results") is None and "command_results" in changes:
        changes = {
            **changes,
            "command_results": (
                _decision_command(module, module.ClassifiedOutcome.CHILD_NONZERO),
            ),
        }

    decision = module.decide_release(_decision_inputs(module, **changes))

    assert decision.outcome.value == outcome
    assert decision.exit_code == exit_code
    assert decision.outcome.value != "GO"


def test_decision_model_prioritizes_safety_and_emits_only_non_go_pending_on_pass():
    module = importlib.import_module("scripts.run_interaction_acceptance")
    safety_command = _decision_command(module, module.ClassifiedOutcome.SAFETY_FAILURE)
    safety = module.decide_release(
        _decision_inputs(
            module,
            command_results=(safety_command,),
            contrast_passed=False,
            lovable_complete_or_waived=False,
        )
    )
    accepted = {
        incident_id: "ACCEPT" for incident_id in module.INCIDENT_IDS
    }
    technical_pass = module.decide_release(
        _decision_inputs(module, incident_decisions=accepted)
    )

    assert (safety.outcome.value, safety.exit_code) == ("SAFETY_NO_GO", 3)
    assert (
        technical_pass.outcome.value,
        technical_pass.exit_code,
    ) == ("TECHNICAL_PASS_HUMAN_DECISION_PENDING", 2)
    assert technical_pass.final_go is False


def _valid_external_decision_document():
    return {
        "author": "Release Owner",
        "claimed_role": "release_owner",
        "timestamp": "2026-08-29T08:00:00+08:00",
        "incidents": [
            {
                "incident_id": incident_id,
                "decision": "ACCEPT",
                "rationale": "Risk reviewed against the preserved evidence.",
            }
            for incident_id in (
                "PIPELINE_T8_PROVIDER_20260823",
                "CHILD_T9_REAL_LOG_20260827",
                "TEACHER_T5_REAL_LOG_20260829",
            )
        ],
    }


@pytest.mark.parametrize(
    "mutate",
    [
        lambda document: document.update(extra=True),
        lambda document: document.update(claimed_role="reviewer"),
        lambda document: document.update(timestamp="yesterday"),
        lambda document: document["incidents"].pop(),
        lambda document: document["incidents"].append(dict(document["incidents"][0])),
        lambda document: document["incidents"][0].update(decision="MAYBE"),
        lambda document: document["incidents"][0].update(rationale=""),
        lambda document: document["incidents"][0].update(extra=True),
    ],
)
def test_external_decision_json_rejects_malformed_or_unverifiable_shape(mutate):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    document = _valid_external_decision_document()
    mutate(document)

    with pytest.raises(module.CliMisuseError) as caught:
        module.parse_external_decision_json(
            __import__("json").dumps(document).encode("utf-8")
        )

    assert caught.value.exit_code == 64


def test_external_decision_json_is_hashed_and_never_promoted_to_authority():
    module = importlib.import_module("scripts.run_interaction_acceptance")
    payload = __import__("json").dumps(
        _valid_external_decision_document(), sort_keys=True
    ).encode("utf-8")

    artifact = module.parse_external_decision_json(payload)

    assert artifact.label == "UNVERIFIED_SUPPLIED_ARTIFACT"
    assert artifact.sha256 == hashlib.sha256(payload).hexdigest()
    assert artifact.authority_verified is False
    assert artifact.incident_decisions == {
        incident_id: "ACCEPT" for incident_id in module.INCIDENT_IDS
    }


def _timeout_report_result(module, command_id, child_exit, stdout):
    resources = FakeRunOneResources()
    return module.CommandResult(
        subcommand=command_id,
        child_started=True,
        child_exit=child_exit,
        termination=module.Termination.TIMED_OUT,
        output_complete=True,
        residual_group_observed=False,
        cleanup_failures=(),
        classified_outcome=module.ClassifiedOutcome.TECHNICAL_FAILURE,
        reason="COMMAND_TIMEOUT",
        before_snapshot=resources,
        after_snapshot=resources,
        stdout=stdout,
        stderr=b"",
    )


_FOCUS_LABELS = (
    "input",
    "confirmation-input",
    "native-button",
    "route-h1",
    "nav-button",
    "link",
    "route-h2",
    "primary-blue-button",
    "white-panel-control",
    "create-dialog-target",
    "create-dialog-return",
    "gray-button",
    "dialog-target",
    "dialog-return",
    "duck-primary-button",
    "textarea",
    "duck-dialog-return",
    "select",
)


def _structured_property_payload(kind, viewport):
    viewport_id = f"{viewport['width']}x{viewport['height']}"
    if kind == "focus":
        measurements = [
            {
                "adjacentColors": ["#ffffff", "#666666"],
                "bestRatios": [4.5, 3.5],
                "focusBounds": {
                    "bottom": 40,
                    "left": 1,
                    "right": 101,
                    "top": 1,
                },
                "label": label,
                "rect": {"height": 30, "width": 90, "x": 6, "y": 6},
                "ringColors": ["#0057b8", "#ffffff"],
                "ringThicknesses": [3, 3],
            }
            for label in _FOCUS_LABELS
        ]
        return {
            "measurements": measurements,
            "viewport": viewport,
            "viewport_id": viewport_id,
        }
    if kind == "db":
        return {
            "after_count": 1,
            "before_count": 0,
            "business_name_sha256": "a" * 64,
            "database_role": "disposable-browser-app.db",
            "outside_repository_data": True,
            "resolved_fixture_match": True,
            "viewport": viewport,
            "viewport_id": viewport_id,
        }
    if kind == "timeout":
        return {
            "activation_sequence": ["Enter", "Space", "Enter"],
            "body_reused_exactly": True,
            "chat_attempts": 2,
            "completion_requests_at_29999": 0,
            "completion_requests_during_failure_boundary": 0,
            "durable_bytes_unchanged_at_29999": True,
            "failure_transitions_at_30000": 1,
            "header_matches_body_request_id": True,
            "outstanding_chat_requests_at_29999": 1,
            "request_id_sha256": "b" * 64,
            "retry_controls_at_30000": 1,
            "retry_controls_at_29999": 0,
            "retry_requests": 1,
            "state_at_30000": "submission_failed",
            "state_at_29999": "submitting",
            "success_copy_at_29999": False,
            "timeout_ms": 30_000,
            "tts_requests_at_29999": 0,
            "tts_requests_during_failure_boundary": 0,
            "viewport": viewport,
            "viewport_id": viewport_id,
        }
    if kind == "search":
        return {
            "filter_height": 391,
            "focus_ratios": [17.74, 17.74],
            "minimum_target_height": 44,
            "viewport": viewport,
        }
    if kind == "today":
        return {
            "metric_cards": 5,
            "retry_height": 44,
            "retry_width": 142,
            "viewport": viewport,
        }
    raise AssertionError(kind)


def _structured_node(kind, viewport_id):
    names = {
        "focus": "test_release_focus_indicator_meets_three_to_one",
        "db": "test_release_teacher_action_persists_to_disposable_sqlite",
        "timeout": "test_first_chat_thirty_second_timeout_retains_draft_and_reuses_request_id_once",
        "search": "test_release_search_filters_results_and_focus_stay_in_bounds",
        "today": "test_release_today_weekly_metrics_retry_and_grid_stay_in_bounds",
    }
    return f"{names[kind]}[{viewport_id}]"


def _suite_with_properties(module, suite, properties):
    return module.SuiteEvidence(
        valid=suite.valid,
        total=suite.total,
        passed=suite.passed,
        failures=suite.failures,
        errors=suite.errors,
        skipped=suite.skipped,
        xfailed=suite.xfailed,
        xpassed=suite.xpassed,
        todo=suite.todo,
        cancelled=suite.cancelled,
        node_ids=suite.node_ids,
        reason=suite.reason,
        properties=tuple(properties),
    )


def _structured_suite(module, kind, viewport_ids):
    property_names = {
        "focus": "task9.focus_measurement",
        "db": "task9.db_action_evidence",
        "timeout": "task9.timeout_evidence",
        "search": "task8.search_geometry",
        "today": "task7.today_metrics_geometry",
    }
    properties = []
    for viewport_id in viewport_ids:
        width, height = (int(part) for part in viewport_id.split("x"))
        node_id = _structured_node(kind, viewport_id)
        properties.append(
            module.EvidenceProperty(
                node_id=node_id,
                name=property_names[kind],
                value=__import__("json").dumps(
                    _structured_property_payload(
                        kind, {"width": width, "height": height}
                    ),
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            )
        )
    return _suite_with_properties(
        module,
        _suite_evidence(module, tuple(item.node_id for item in properties)),
        properties,
    )


def _valid_pending_report_record(module, tmp_path, *, tested_head=None):
    repo_root = Path(__file__).resolve().parents[1]
    artifact_root = (tmp_path / "acceptance-run").resolve()
    tested_head = tested_head or module.FROZEN_START_HEAD
    specs = module.build_command_specs(repo_root, artifact_root)
    complete = _complete_gate_evidence(module)
    suites = {}
    for spec in specs:
        suites[spec.command_id] = complete.suites.get(
            spec.command_id,
            _suite_evidence(module, (f"synthetic_{spec.command_id}_pass",)),
        )

    structured = {
        "focus": {
            "1024": _structured_suite(module, "focus", ("1024x768",)),
            "all": _structured_suite(
                module, "focus", ("1024x768", "1440x900")
            ),
        },
        "db": {
            "1024": _structured_suite(module, "db", ("1024x768",)),
            "all": _structured_suite(module, "db", ("1024x768", "1440x900")),
        },
        "timeout": {
            "1024": _structured_suite(module, "timeout", ("1024x576",)),
            "all": _structured_suite(
                module, "timeout", ("1024x576", "1280x720")
            ),
        },
        "search": {
            "all": _structured_suite(
                module, "search", ("1024x768", "1440x900")
            ),
        },
        "today": {
            "all": _structured_suite(
                module, "today", ("1024x768", "1440x900")
            ),
        },
    }
    suites.update(
        {
            "release_focus_1024": structured["focus"]["1024"],
            "release_focus_all": structured["focus"]["all"],
            "release_db_action_1024": structured["db"]["1024"],
            "release_db_action_all": structured["db"]["all"],
            "child_chat_timeout_1024": structured["timeout"]["1024"],
            "child_chat_timeout_all": structured["timeout"]["all"],
        }
    )
    browser_properties = tuple(
        property_item
        for kind in ("timeout", "focus", "db", "search", "today")
        for property_item in structured[kind]["all"].properties
    )
    suites["browser"] = _suite_with_properties(
        module, suites["browser"], browser_properties
    )

    baseline = FakeRunOneResources(
        git_head=tested_head, token="one-global-baseline"
    )
    results = tuple(
        module.CommandResult(
            subcommand=spec.command_id,
            child_started=True,
            child_exit=0,
            termination=module.Termination.EXITED,
            output_complete=True,
            residual_group_observed=False,
            cleanup_failures=(),
            classified_outcome=module.ClassifiedOutcome.SUCCESS,
            reason="SUCCESS",
            before_snapshot=baseline,
            after_snapshot=baseline,
            stdout=(
                _unit7_passing_tap(suites[spec.command_id].node_ids[0])
                if spec.evidence_format is module.EvidenceFormat.TAP
                else b"pytest passed"
            ),
            stderr=b"",
            duration_seconds=1.25,
        )
        for spec in specs
    )
    internal = tuple(
        module.InternalEvidence(
            requirement.source,
            requirement.evidence_id,
            passed=True,
            fresh=True,
            valid=True,
        )
        for requirement in module.INTERNAL_EVIDENCE_REQUIREMENTS
    )
    manifest_commands = {row.command_id for row in module.SELECTOR_MANIFEST}
    gates = module.evaluate_gates(
        results,
        baseline,
        module.EvidenceMap(
            suites={
                command_id: evidence
                for command_id, evidence in suites.items()
                if command_id in manifest_commands
            },
            internal=internal,
        ),
    )
    assert all(gate.status is module.GateStatus.PASS for gate in gates)
    decision = module.DecisionResult(
        module.DecisionOutcome.TECHNICAL_PASS_HUMAN_DECISION_PENDING,
        2,
        ("HUMAN_AUTHORITY_REQUIRED",),
    )
    junit_payloads = {
        spec.command_id: b"<testsuite tests='1'><testcase name='synthetic'/></testsuite>"
        for spec in specs
        if spec.evidence_format is module.EvidenceFormat.JUNIT
    }
    return module.build_report_record(
        run_id="20260830T040000Z-valid-pending",
        generated_at="2026-08-30T04:00:00Z",
        tested_head=tested_head,
        decision=decision,
        command_results=results,
        command_specs=specs,
        gate_results=gates,
        lovable_status="PROVIDED_OR_WAIVED",
        external_decision=None,
        junit_payloads=junit_payloads,
        suite_evidence=suites,
        internal_evidence=internal,
        baseline_snapshot=baseline,
        final_snapshot=baseline,
    )


def _json_clone_record(module, record):
    return __import__("json").loads(module.canonical_json_bytes(record))


def _all_report_resource_snapshots(record):
    snapshots = [record["resources"]["before"], record["resources"]["after"]]
    snapshots.extend(
        snapshot
        for command in record["commands"]
        for snapshot in (command["before_snapshot"], command["after_snapshot"])
        if snapshot is not None
    )
    return snapshots


def _safety_drift_report_record(module, termination):
    before = FakeRunOneResources(token="safety-a")
    after = FakeRunOneResources(token="safety-b")
    child_exit = {
        module.Termination.EXITED: 0,
        module.Termination.SIGNALED: -9,
        module.Termination.TIMED_OUT: -15,
    }[termination]
    command = module.CommandResult(
        subcommand="runner",
        child_started=True,
        child_exit=child_exit,
        termination=termination,
        output_complete=True,
        residual_group_observed=False,
        cleanup_failures=(),
        classified_outcome=module.ClassifiedOutcome.SAFETY_FAILURE,
        reason="RESOURCE_DRIFT",
        before_snapshot=before,
        after_snapshot=after,
        stdout=b"synthetic command output",
    )
    spec = module.CommandSpec(
        command_id="runner",
        argv=("/usr/bin/false",),
        timeout_seconds=3,
        conftest_mode=module.ConftestMode.PURE,
        evidence_format=module.EvidenceFormat.TAP,
    )
    gates = module.evaluate_gates(
        (command,),
        after,
        module.EvidenceMap(suites={}, internal=()),
    )
    decision = module.DecisionResult(
        module.DecisionOutcome.SAFETY_NO_GO,
        3,
        ("RESOURCE_DRIFT", "COMMAND_SAFETY_FAILURE"),
    )
    return module.build_report_record(
        run_id=f"20260830T090000Z-safety-{termination.value.lower()}",
        generated_at="2026-08-30T09:00:00Z",
        tested_head=module.FROZEN_START_HEAD,
        decision=decision,
        command_results=(command,),
        command_specs=(spec,),
        gate_results=gates,
        lovable_status="PROVIDED_OR_WAIVED",
        external_decision=None,
        baseline_snapshot=before,
        final_snapshot=after,
    )


def _technical_partial_report_record(module):
    resources = FakeRunOneResources(token="technical-stable")
    command = module.CommandResult(
        subcommand="runner",
        child_started=True,
        child_exit=7,
        termination=module.Termination.EXITED,
        output_complete=True,
        residual_group_observed=False,
        cleanup_failures=(),
        classified_outcome=module.ClassifiedOutcome.CHILD_NONZERO,
        reason="CHILD_NONZERO",
        before_snapshot=resources,
        after_snapshot=resources,
        stdout=b"ordinary failure",
    )
    spec = module.CommandSpec(
        command_id="runner",
        argv=("/usr/bin/false",),
        timeout_seconds=3,
        conftest_mode=module.ConftestMode.PURE,
        evidence_format=module.EvidenceFormat.TAP,
    )
    gates = module.evaluate_gates(
        (command,),
        resources,
        module.EvidenceMap(suites={}, internal=()),
    )
    decision = module.DecisionResult(
        module.DecisionOutcome.TECHNICAL_NO_GO,
        1,
        ("COMMAND_FAILURE", "GATE_FAILURE"),
    )
    return module.build_report_record(
        run_id="20260830T090100Z-technical-partial",
        generated_at="2026-08-30T09:01:00Z",
        tested_head=module.FROZEN_START_HEAD,
        decision=decision,
        command_results=(command,),
        command_specs=(spec,),
        gate_results=gates,
        lovable_status="PROVIDED_OR_WAIVED",
        external_decision=None,
        baseline_snapshot=resources,
        final_snapshot=resources,
    )


def test_snapshot_safety_is_identical_for_dataclass_and_canonical_mapping():
    module = importlib.import_module("scripts.run_interaction_acceptance")
    unsafe_mapping = {"token": "unsafe-a", "unsafe_reasons": ["LOG_UNREADABLE"]}

    assert module._snapshot_is_unsafe(
        FakeResources(unsafe_reasons=("LOG_UNREADABLE",))
    )
    assert module._snapshot_is_unsafe(unsafe_mapping)
    assert not module._snapshot_is_unsafe({"token": "safe", "unsafe_reasons": []})
    with pytest.raises(ValueError, match="invalid command result state"):
        module.CommandResult(
            subcommand="runner",
            child_started=True,
            child_exit=0,
            termination=module.Termination.EXITED,
            output_complete=True,
            residual_group_observed=False,
            cleanup_failures=(),
            classified_outcome=module.ClassifiedOutcome.TECHNICAL_FAILURE,
            reason="INVALID_EVIDENCE:ZERO_TESTS",
            before_snapshot=unsafe_mapping,
            after_snapshot=unsafe_mapping,
        )

    truthful = module.CommandResult(
        subcommand="runner",
        child_started=True,
        child_exit=0,
        termination=module.Termination.EXITED,
        output_complete=True,
        residual_group_observed=False,
        cleanup_failures=(),
        classified_outcome=module.ClassifiedOutcome.SAFETY_FAILURE,
        reason="RESOURCE_DRIFT",
        before_snapshot=unsafe_mapping,
        after_snapshot=unsafe_mapping,
    )
    assert truthful.classified_outcome is module.ClassifiedOutcome.SAFETY_FAILURE


@pytest.mark.parametrize(
    ("termination", "child_exit"),
    (("EXITED", 0), ("SIGNALED", -9)),
)
@pytest.mark.parametrize("representation", ("dataclass", "mapping"))
def test_residual_process_with_resource_drift_requires_resource_drift_precedence(
    termination, child_exit, representation
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    before = FakeRunOneResources(token="residual-a")
    after = FakeRunOneResources(token="residual-b")
    if representation == "mapping":
        before = module._canonical_value(before)
        after = module._canonical_value(after)

    with pytest.raises(ValueError, match="invalid command result state"):
        module.CommandResult(
            subcommand="runner",
            child_started=True,
            child_exit=child_exit,
            termination=module.Termination[termination],
            output_complete=True,
            residual_group_observed=True,
            cleanup_failures=(),
            classified_outcome=module.ClassifiedOutcome.SAFETY_FAILURE,
            reason="RESIDUAL_PROCESS_GROUP",
            before_snapshot=before,
            after_snapshot=after,
        )

    truthful = module.CommandResult(
        subcommand="runner",
        child_started=True,
        child_exit=child_exit,
        termination=module.Termination[termination],
        output_complete=True,
        residual_group_observed=True,
        cleanup_failures=(),
        classified_outcome=module.ClassifiedOutcome.SAFETY_FAILURE,
        reason="RESOURCE_DRIFT",
        before_snapshot=before,
        after_snapshot=after,
    )
    assert truthful.reason == "RESOURCE_DRIFT"


def test_residual_and_resource_drift_control_states_remain_distinct():
    module = importlib.import_module("scripts.run_interaction_acceptance")
    unchanged = FakeRunOneResources(token="unchanged")
    residual = module.CommandResult(
        subcommand="runner",
        child_started=True,
        child_exit=0,
        termination=module.Termination.EXITED,
        output_complete=True,
        residual_group_observed=True,
        cleanup_failures=(),
        classified_outcome=module.ClassifiedOutcome.SAFETY_FAILURE,
        reason="RESIDUAL_PROCESS_GROUP",
        before_snapshot=unchanged,
        after_snapshot=unchanged,
    )
    drift = module.CommandResult(
        subcommand="runner",
        child_started=True,
        child_exit=0,
        termination=module.Termination.EXITED,
        output_complete=True,
        residual_group_observed=False,
        cleanup_failures=(),
        classified_outcome=module.ClassifiedOutcome.SAFETY_FAILURE,
        reason="RESOURCE_DRIFT",
        before_snapshot=FakeRunOneResources(token="drift-a"),
        after_snapshot=FakeRunOneResources(token="drift-b"),
    )

    assert residual.reason == "RESIDUAL_PROCESS_GROUP"
    assert drift.reason == "RESOURCE_DRIFT"


@pytest.mark.parametrize(
    "termination",
    (
        pytest.param("EXITED", id="exit-zero-evidence-failure"),
        pytest.param("SIGNALED", id="signal"),
        pytest.param("TIMED_OUT", id="timeout"),
    ),
)
@pytest.mark.parametrize("mutation", ("forged_technical", "wrong_exit", "wrong_reasons"))
def test_schema_v2_recomputes_safety_decision_for_every_command_termination(
    termination, mutation
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    record = _json_clone_record(
        module,
        _safety_drift_report_record(module, module.Termination[termination]),
    )
    if mutation == "forged_technical":
        record["decision"] = {
            "final_go": False,
            "outcome": "TECHNICAL_NO_GO",
            "reasons": ["COMMAND_FAILURE", "GATE_FAILURE"],
            "runner_process_exit": 1,
        }
    elif mutation == "wrong_exit":
        record["decision"]["runner_process_exit"] = 1
    elif mutation == "wrong_reasons":
        record["decision"]["reasons"] = ["COMMAND_SAFETY_FAILURE"]
    else:
        raise AssertionError(mutation)

    with pytest.raises(module.CliMisuseError, match="decision"):
        module.render_report_markdown(record)


@pytest.mark.parametrize("mutation", ("forged_safety", "wrong_exit", "wrong_reasons"))
def test_schema_v2_recomputes_truthful_technical_partial_decision(mutation):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    truthful = _technical_partial_report_record(module)
    assert "TECHNICAL_NO_GO" in module.render_report_markdown(truthful)
    record = _json_clone_record(module, truthful)
    if mutation == "forged_safety":
        record["decision"] = {
            "final_go": False,
            "outcome": "SAFETY_NO_GO",
            "reasons": ["COMMAND_SAFETY_FAILURE"],
            "runner_process_exit": 3,
        }
    elif mutation == "wrong_exit":
        record["decision"]["runner_process_exit"] = 3
    elif mutation == "wrong_reasons":
        record["decision"]["reasons"] = ["GATE_FAILURE"]
    else:
        raise AssertionError(mutation)

    with pytest.raises(module.CliMisuseError, match="decision"):
        module.render_report_markdown(record)


@pytest.mark.parametrize(
    "mutation",
    ("minimal", "missing_nested", "extra_nested", "wrong_nested_type"),
)
def test_schema_v2_rejects_noncanonical_resource_snapshot_shapes(mutation):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    record = _json_clone_record(module, _technical_partial_report_record(module))
    snapshots = [record["resources"]["before"], record["resources"]["after"]]
    snapshots.extend(
        snapshot
        for command in record["commands"]
        for snapshot in (command["before_snapshot"], command["after_snapshot"])
    )
    if mutation == "minimal":
        replacement = {"token": "stable", "unsafe_reasons": []}
        record["resources"]["before"] = dict(replacement)
        record["resources"]["after"] = dict(replacement)
        for command in record["commands"]:
            command["before_snapshot"] = dict(replacement)
            command["after_snapshot"] = dict(replacement)
    elif mutation == "missing_nested":
        for snapshot in snapshots:
            snapshot.pop("database")
    elif mutation == "extra_nested":
        for snapshot in snapshots:
            snapshot["database"]["extra"] = True
    elif mutation == "wrong_nested_type":
        for snapshot in snapshots:
            snapshot["database"]["database"]["mode"] = "0644"
    else:
        raise AssertionError(mutation)

    with pytest.raises(module.CliMisuseError, match="resource"):
        module.render_report_markdown(record)


@pytest.mark.parametrize(
    "mutation",
    (
        "missing_db_empty_reasons",
        "nested_unsafe_top_safe",
        "log_reason_mismatch",
        "tts_reason_mismatch",
        "media_reason_mismatch",
        "user_reason_mismatch",
        "git_reason_mismatch",
        "wrong_directory_digest",
        "directory_scan_reason_forgery",
    ),
)
def test_schema_v2_rejects_resource_snapshot_semantic_forgery(mutation):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    record = _json_clone_record(module, _technical_partial_report_record(module))
    for snapshot in _all_report_resource_snapshots(record):
        if mutation == "missing_db_empty_reasons":
            snapshot["database"]["database"] = {
                "error": None,
                "kind": "missing",
                "mode": None,
                "mtime_ns": None,
                "sha256": None,
                "size": None,
                "symlink_target": None,
            }
            snapshot["database"]["logical_digest"] = None
            snapshot["database"]["unsafe_reasons"] = []
        elif mutation == "nested_unsafe_top_safe":
            snapshot["database"]["database"] = {
                "error": None,
                "kind": "symlink",
                "mode": 511,
                "mtime_ns": 1,
                "sha256": None,
                "size": 9,
                "symlink_target": "elsewhere",
            }
            snapshot["database"]["logical_digest"] = None
            snapshot["database"]["unsafe_reasons"] = ["DATABASE_NOT_REGULAR"]
            snapshot["unsafe_reasons"] = []
        elif mutation == "log_reason_mismatch":
            snapshot["log"] = {
                "error": None,
                "kind": "missing",
                "mode": None,
                "mtime_ns": None,
                "sha256": None,
                "size": None,
                "symlink_target": None,
            }
            snapshot["unsafe_reasons"] = []
        elif mutation == "tts_reason_mismatch":
            snapshot["tts"]["root"] = {
                "error": None,
                "kind": "missing",
                "mode": None,
                "mtime_ns": None,
                "sha256": None,
                "size": None,
                "symlink_target": None,
            }
            snapshot["tts"]["entries"] = []
            snapshot["tts"]["digest"] = None
            snapshot["tts"]["unsafe_reasons"] = ["DIRECTORY_MISSING"]
            snapshot["unsafe_reasons"] = []
        elif mutation == "media_reason_mismatch":
            snapshot["media"]["root"] = {
                "error": None,
                "kind": "missing",
                "mode": None,
                "mtime_ns": None,
                "sha256": None,
                "size": None,
                "symlink_target": None,
            }
            snapshot["media"]["entries"] = []
            snapshot["media"]["digest"] = None
            snapshot["media"]["unsafe_reasons"] = ["DIRECTORY_MISSING"]
            snapshot["unsafe_reasons"] = ["MEDIA:DIRECTORY_MISSING"]
        elif mutation == "user_reason_mismatch":
            protected = snapshot["user_paths"][0]
            protected["file"] = {
                "error": None,
                "kind": "missing",
                "mode": None,
                "mtime_ns": None,
                "sha256": None,
                "size": None,
                "symlink_target": None,
            }
            protected["directory"] = None
            protected["unsafe_reasons"] = ["PATH_MISSING"]
            snapshot["unsafe_reasons"] = [
                f"USER_PATH:{protected['relative_path']}:PATH_MISSING"
            ]
        elif mutation == "git_reason_mismatch":
            snapshot["git_porcelain"] = None
            snapshot["unsafe_reasons"] = []
        elif mutation == "wrong_directory_digest":
            snapshot["tts"]["digest"] = "0" * 64
        elif mutation == "directory_scan_reason_forgery":
            snapshot["tts"]["digest"] = None
            snapshot["tts"]["unsafe_reasons"] = ["DIRECTORY_UNREADABLE"]
            snapshot["unsafe_reasons"] = ["TTS:DIRECTORY_UNREADABLE"]
        else:
            raise AssertionError(mutation)

    with pytest.raises(module.CliMisuseError, match="resource"):
        module.render_report_markdown(record)


def test_schema_v2_accepts_one_semantically_reconstructed_safe_snapshot():
    module = importlib.import_module("scripts.run_interaction_acceptance")
    record = _technical_partial_report_record(module)

    markdown = module.render_report_markdown(record)

    assert "TECHNICAL_NO_GO" in markdown
    assert record["resources"]["before"]["unsafe_reasons"] == []


def test_schema_v2_accepts_truthful_nested_unsafe_snapshot_as_safety():
    module = importlib.import_module("scripts.run_interaction_acceptance")
    record = _json_clone_record(
        module,
        _safety_drift_report_record(module, module.Termination.EXITED),
    )
    for snapshot in _all_report_resource_snapshots(record):
        snapshot["log"] = {
            "error": None,
            "kind": "missing",
            "mode": None,
            "mtime_ns": None,
            "sha256": None,
            "size": None,
            "symlink_target": None,
        }
        snapshot["unsafe_reasons"] = ["LOG_NOT_REGULAR"]

    markdown = module.render_report_markdown(record)

    assert "SAFETY_NO_GO" in markdown
    assert "LOG_NOT_REGULAR" in markdown


def test_schema_v2_accepts_truthful_directory_scan_failure_as_safety(
    tmp_path, monkeypatch
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    root = tmp_path / "tts-cache"
    root.mkdir()
    monkeypatch.setattr(
        module.os,
        "scandir",
        lambda _path: (_ for _ in ()).throw(PermissionError("synthetic denial")),
    )
    unsafe_tts = module._canonical_value(module.directory_snapshot(root))
    assert unsafe_tts["scan_error"] == "PermissionError"
    assert unsafe_tts["scan_source"] == "."

    record = _json_clone_record(
        module,
        _safety_drift_report_record(module, module.Termination.EXITED),
    )
    for snapshot in _all_report_resource_snapshots(record):
        snapshot["tts"] = json.loads(json.dumps(unsafe_tts))
        snapshot["unsafe_reasons"] = ["TTS:SCANDIR:.:PermissionError"]

    markdown = module.render_report_markdown(record)

    assert "SAFETY_NO_GO" in markdown
    assert "TTS:SCANDIR:.:PermissionError" in markdown


def test_schema_v2_retains_exact_p6_browser_geometry_evidence(tmp_path):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    record = _valid_pending_report_record(module, tmp_path)

    properties = record["suite_evidence"]["browser"]["properties"]
    by_name = {
        name: tuple(
            item["node_id"] for item in properties if item["name"] == name
        )
        for name in ("task7.today_metrics_geometry", "task8.search_geometry")
    }

    assert by_name == {
        "task7.today_metrics_geometry": (
            "test_release_today_weekly_metrics_retry_and_grid_stay_in_bounds[1024x768]",
            "test_release_today_weekly_metrics_retry_and_grid_stay_in_bounds[1440x900]",
        ),
        "task8.search_geometry": (
            "test_release_search_filters_results_and_focus_stay_in_bounds[1024x768]",
            "test_release_search_filters_results_and_focus_stay_in_bounds[1440x900]",
        ),
    }
    assert "TECHNICAL_PASS_HUMAN_DECISION_PENDING" in module.render_report_markdown(
        record
    )


def test_p6_geometry_validators_reject_shape_viewport_nonfinite_and_fractional_count():
    module = importlib.import_module("scripts.run_interaction_acceptance")
    viewport = {"height": 768, "width": 1024}
    search = _structured_property_payload("search", viewport)
    today = _structured_property_payload("today", viewport)

    assert module._validate_search_geometry_property(search, "1024x768") is True
    assert (
        module._validate_today_metrics_geometry_property(today, "1024x768")
        is True
    )

    search_mutations = (
        {**search, "unknown": True},
        {**search, "viewport": {"height": 768, "width": 1025}},
        {**search, "filter_height": float("inf")},
        {**search, "focus_ratios": [17.74]},
    )
    today_mutations = (
        {**today, "unknown": True},
        {**today, "viewport": {"height": 768, "width": 1025}},
        {**today, "retry_height": float("inf")},
        {**today, "metric_cards": 5.0},
    )

    assert all(
        module._validate_search_geometry_property(item, "1024x768") is False
        for item in search_mutations
    )
    assert all(
        module._validate_today_metrics_geometry_property(item, "1024x768")
        is False
        for item in today_mutations
    )


@pytest.mark.parametrize(
    "property_name",
    ("task7.today_metrics_geometry", "task8.search_geometry"),
)
@pytest.mark.parametrize("mutation", ("missing", "duplicate"))
def test_schema_v2_rejects_p6_browser_geometry_multiplicity(
    tmp_path, property_name, mutation
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    record = _json_clone_record(
        module, _valid_pending_report_record(module, tmp_path)
    )
    properties = record["suite_evidence"]["browser"]["properties"]
    matching = [item for item in properties if item["name"] == property_name]
    assert len(matching) == 2
    if mutation == "missing":
        properties.remove(matching[-1])
    elif mutation == "duplicate":
        properties.append(dict(matching[-1]))
    else:
        raise AssertionError(mutation)

    with pytest.raises(module.CliMisuseError):
        module.render_report_markdown(record)


def test_schema_v2_accepts_one_truthful_full_technical_pending_record(tmp_path):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    del tmp_path
    record = _valid_pending_report_record(
        module, Path("/tmp/task9-schema-v2-golden")
    )

    markdown = module.render_report_markdown(record)
    json_bytes = module.canonical_json_bytes(record)

    assert "TECHNICAL_PASS_HUMAN_DECISION_PENDING" in markdown
    assert "Final GO: `false`" in markdown
    assert len(record["commands"]) == 22
    assert len(record["focus_measurements"]) == 2
    assert len(record["database_action_evidence"]) == 2
    assert len(record["timeout_evidence"]) == 2
    assert hashlib.sha256(json_bytes).hexdigest() == "40d5bb5bf2395afc3f823cd45cf51ccec7de21793769d9f237a374d61b1fd810"
    assert hashlib.sha256(markdown.encode()).hexdigest() == "987eb3a7672478199c12eaa7541dbe2c26cb74023fd37eec04fb7c85f4ebb373"


def test_schema_v2_accepts_pending_for_the_exact_post_commit_resource_head(tmp_path):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    post_commit_head = "a" * 40
    record = _valid_pending_report_record(
        module, tmp_path, tested_head=post_commit_head
    )

    markdown = module.render_report_markdown(record)

    assert record["tested_head"] == post_commit_head
    assert f"Tested implementation HEAD A: `{post_commit_head}`" in markdown


@pytest.mark.parametrize(
    "mutation",
    ("top_level", "global", "command", "runtime_version"),
)
def test_schema_v2_rejects_any_tested_head_or_version_mismatch(tmp_path, mutation):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    post_commit_head = "a" * 40
    record = _json_clone_record(
        module,
        _valid_pending_report_record(
            module, tmp_path, tested_head=post_commit_head
        ),
    )
    other_head = "b" * 40
    if mutation == "top_level":
        record["tested_head"] = other_head
    elif mutation == "global":
        record["resources"]["before"]["git_head"] = other_head
        record["resources"]["after"]["git_head"] = other_head
    elif mutation == "command":
        record["commands"][0]["before_snapshot"]["git_head"] = other_head
        record["commands"][0]["after_snapshot"]["git_head"] = other_head
    elif mutation == "runtime_version":
        record["runtime_versions"]["api_version"] = "forged"
    else:
        raise AssertionError(mutation)

    with pytest.raises(module.CliMisuseError):
        module.render_report_markdown(record)


@pytest.mark.parametrize(
    "outcome",
    ("pending", "technical", "safety"),
)
@pytest.mark.parametrize("mutation", ("top_level", "global", "command"))
def test_schema_v2_binds_tested_head_for_every_decision_outcome(
    tmp_path, outcome, mutation
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    if outcome == "pending":
        source = _valid_pending_report_record(module, tmp_path)
    elif outcome == "technical":
        source = _technical_partial_report_record(module)
    elif outcome == "safety":
        source = _safety_drift_report_record(module, module.Termination.EXITED)
    else:
        raise AssertionError(outcome)
    record = _json_clone_record(module, source)
    other_head = "b" * 40
    if mutation == "top_level":
        record["tested_head"] = other_head
    elif mutation == "global":
        record["resources"]["before"]["git_head"] = other_head
        record["resources"]["after"]["git_head"] = other_head
    elif mutation == "command":
        record["commands"][0]["before_snapshot"]["git_head"] = other_head
        record["commands"][0]["after_snapshot"]["git_head"] = other_head
    else:
        raise AssertionError(mutation)

    with pytest.raises(module.CliMisuseError, match="HEAD"):
        module.render_report_markdown(record)


@pytest.mark.parametrize("outcome", ("pending", "technical", "safety"))
def test_schema_v2_accepts_every_outcome_at_one_consistent_post_commit_head(
    tmp_path, outcome
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    if outcome == "pending":
        record = _json_clone_record(
            module,
            _valid_pending_report_record(
                module, tmp_path, tested_head="a" * 40
            ),
        )
    elif outcome == "technical":
        record = _json_clone_record(module, _technical_partial_report_record(module))
    elif outcome == "safety":
        record = _json_clone_record(
            module,
            _safety_drift_report_record(module, module.Termination.EXITED),
        )
    else:
        raise AssertionError(outcome)
    if outcome != "pending":
        record["tested_head"] = "a" * 40
        for snapshot in (
            record["resources"]["before"],
            record["resources"]["after"],
        ):
            snapshot["git_head"] = "a" * 40
        for command in record["commands"]:
            command["before_snapshot"]["git_head"] = "a" * 40
            command["after_snapshot"]["git_head"] = "a" * 40

    markdown = module.render_report_markdown(record)

    assert f"Tested implementation HEAD A: `{'a' * 40}`" in markdown
    assert record["decision"]["outcome"] in markdown


def test_render_report_cli_normalizes_completed_validation_failure(
    tmp_path, monkeypatch
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    source = tmp_path / "artifacts" / "acceptance" / "invalid" / "report.json"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"{}\n")

    def reject(_source, _output):
        raise module.CliMisuseError("synthetic invalid completed report")

    monkeypatch.setattr(module, "render_completed_report", reject)

    assert module.render_report_from_cli(tmp_path, str(source)) == 1


@pytest.mark.parametrize(
    "mutation",
    (
        "zero",
        "twenty_one",
        "duplicate",
        "substitute",
        "wrong_order",
        "wrong_argv",
        "wrong_timeout",
    ),
)
def test_schema_v2_rejects_nonexact_pending_command_inventory(tmp_path, mutation):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    record = _json_clone_record(
        module, _valid_pending_report_record(module, tmp_path)
    )
    commands = record["commands"]
    if mutation == "zero":
        commands.clear()
    elif mutation == "twenty_one":
        commands.pop()
    elif mutation == "duplicate":
        commands[-1] = dict(commands[0], order=22)
    elif mutation == "substitute":
        commands[-1]["subcommand"] = "substituted-command"
    elif mutation == "wrong_order":
        commands[0], commands[1] = commands[1], commands[0]
        commands[0]["order"] = 1
        commands[1]["order"] = 2
    elif mutation == "wrong_argv":
        commands[0]["argv"] = [*commands[0]["argv"], "--forged"]
    elif mutation == "wrong_timeout":
        commands[0]["timeout_seconds"] += 1
    else:
        raise AssertionError(mutation)

    with pytest.raises(module.CliMisuseError):
        module.render_report_markdown(record)


@pytest.mark.parametrize("mutation", ("child_nonzero", "zero_evidence"))
def test_schema_v2_rejects_pending_command_or_parser_failure(tmp_path, mutation):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    record = _json_clone_record(
        module, _valid_pending_report_record(module, tmp_path)
    )
    command = record["commands"][0]
    if mutation == "child_nonzero":
        command.update(
            child_exit=7,
            classified_outcome="CHILD_NONZERO",
            reason="CHILD_NONZERO",
            runner_process_exit=7,
        )
    else:
        suite = record["suite_evidence"]["runner"]
        suite.update(
            valid=False,
            total=0,
            passed=0,
            node_ids=[],
            reason="ZERO_TESTS",
            properties=[],
        )
        command["counts"] = {
            "cancelled": 0,
            "errors": 0,
            "failures": 0,
            "passed": 0,
            "skipped": 0,
            "todo": 0,
            "total": 0,
            "xfailed": 0,
            "xpassed": 0,
        }
        command["evidence_valid"] = False
        command["evidence_reason"] = "ZERO_TESTS"
        command["evidence_sha256"] = None

    with pytest.raises(module.CliMisuseError):
        module.render_report_markdown(record)


@pytest.mark.parametrize(
    ("kind", "command_id", "top_level"),
    (
        ("focus", "release_focus_all", "focus_measurements"),
        ("db", "release_db_action_all", "database_action_evidence"),
        ("timeout", "child_chat_timeout_all", "timeout_evidence"),
    ),
)
@pytest.mark.parametrize("mutation", ("empty", "missing", "duplicate", "substitute"))
def test_schema_v2_rejects_incomplete_or_substituted_structured_properties(
    tmp_path, kind, command_id, top_level, mutation
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    record = _json_clone_record(
        module, _valid_pending_report_record(module, tmp_path)
    )
    suite = record["suite_evidence"][command_id]
    if mutation == "empty":
        record[top_level] = []
    elif mutation == "missing":
        suite["properties"].pop()
    elif mutation == "duplicate":
        suite["properties"].append(dict(suite["properties"][0]))
    elif mutation == "substitute":
        old_node = suite["node_ids"][-1]
        new_node = old_node + "__substituted"
        suite["node_ids"][-1] = new_node
        suite["properties"][-1]["node_id"] = new_node
    else:
        raise AssertionError(mutation)

    with pytest.raises(module.CliMisuseError):
        module.render_report_markdown(record)


def test_schema_v2_recomputes_gates_instead_of_trusting_forged_pass_rows(tmp_path):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    record = _json_clone_record(
        module, _valid_pending_report_record(module, tmp_path)
    )
    browser = record["suite_evidence"]["browser"]
    removed = browser["node_ids"].pop(0)
    browser["total"] -= 1
    browser["passed"] -= 1
    browser["properties"] = [
        item for item in browser["properties"] if item["node_id"] != removed
    ]
    assert all(gate["status"] == "PASS" for gate in record["gates"])

    with pytest.raises(module.CliMisuseError):
        module.render_report_markdown(record)


@pytest.mark.parametrize(
    "mutation",
    ("command_baseline", "global_after", "tripwire", "lovable", "internal_duplicate"),
)
def test_schema_v2_pending_requires_one_baseline_tripwire_and_lovable(
    tmp_path, mutation
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    record = _json_clone_record(
        module, _valid_pending_report_record(module, tmp_path)
    )
    if mutation == "command_baseline":
        forged = {"token": "forged-b", "unsafe_reasons": []}
        record["commands"][0]["before_snapshot"] = forged
        record["commands"][0]["after_snapshot"] = forged
    elif mutation == "global_after":
        record["resources"]["after"]["token"] = "drifted-final"
    elif mutation == "tripwire":
        record["tripwires"]["provider_tts_socket_context_worker"] = "FAIL"
    elif mutation == "lovable":
        record["lovable"].update(
            completion_or_scope_waiver=False,
            project_status="MISSING",
            status="MISSING",
            zero_credit_blocker="still missing",
        )
    elif mutation == "internal_duplicate":
        record["internal_evidence"].append(dict(record["internal_evidence"][0]))
    else:
        raise AssertionError(mutation)

    with pytest.raises(module.CliMisuseError):
        module.render_report_markdown(record)


@pytest.mark.parametrize("mutation", ("top_level", "internal"))
def test_schema_v2_rejects_caller_rewrites_of_unified_tripwire_state(
    tmp_path, mutation
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    record = _json_clone_record(
        module, _valid_pending_report_record(module, tmp_path)
    )
    if mutation == "top_level":
        record["tripwires"]["provider_tts_socket_context_worker"] = "FAIL"
    elif mutation == "internal":
        tripwire = next(
            item
            for item in record["internal_evidence"]
            if item["source"] == "tripwire"
        )
        tripwire.update(passed=False, fresh=True, valid=True)
    else:
        raise AssertionError(mutation)

    with pytest.raises(module.CliMisuseError):
        module.render_report_markdown(record)


@pytest.mark.parametrize(
    "mutation",
    (
        "fact",
        "control",
        "acknowledgement",
        "status",
        "technical_status",
        "missing",
        "extra",
        "order",
        "extra_key",
        "non_mapping",
    ),
)
def test_schema_v2_rejects_every_incident_ledger_mutation_stably(mutation):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    record = _json_clone_record(module, _technical_partial_report_record(module))
    incidents = record["incidents"]
    if mutation == "fact":
        incidents[0]["facts"][0] = "forged fact"
    elif mutation == "control":
        incidents[0]["corrective_controls"][0] = "forged control"
    elif mutation == "acknowledgement":
        incidents[0]["release_owner_acknowledgement"] = "PRESENT"
    elif mutation == "status":
        incidents[0]["status"] = "CLOSED"
    elif mutation == "technical_status":
        incidents[0]["technical_review_status"] = "APPROVED"
    elif mutation == "missing":
        incidents.pop()
    elif mutation == "extra":
        incidents.append(dict(incidents[0]))
    elif mutation == "order":
        incidents.reverse()
    elif mutation == "extra_key":
        incidents[0]["caller_note"] = "forged"
    elif mutation == "non_mapping":
        incidents[0] = "not-an-incident"
    else:
        raise AssertionError(mutation)

    with pytest.raises(module.CliMisuseError, match="incidents"):
        module.render_report_markdown(record)


def test_schema_v2_accepts_the_exact_immutable_incident_ledger():
    module = importlib.import_module("scripts.run_interaction_acceptance")
    record = _technical_partial_report_record(module)

    markdown = module.render_report_markdown(record)

    assert tuple(item["incident_id"] for item in record["incidents"]) == (
        module.INCIDENT_IDS
    )
    assert "Historical incidents" in markdown


@pytest.mark.parametrize(
    ("command_id", "top_level"),
    (
        ("release_focus_all", "focus_measurements"),
        ("release_db_action_all", "database_action_evidence"),
        ("child_chat_timeout_all", "timeout_evidence"),
    ),
)
def test_schema_v2_rejects_unknown_structured_property_fields(
    tmp_path, command_id, top_level
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    record = _json_clone_record(
        module, _valid_pending_report_record(module, tmp_path)
    )
    property_item = record["suite_evidence"][command_id]["properties"][0]
    decoded = __import__("json").loads(property_item["value"])
    decoded["unknown"] = True
    property_item["value"] = __import__("json").dumps(
        decoded,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    record[top_level][0] = decoded

    with pytest.raises(module.CliMisuseError):
        module.render_report_markdown(record)


def test_report_record_has_strict_frozen_command_evidence_and_release_schema():
    module = importlib.import_module("scripts.run_interaction_acceptance")
    resources = FakeRunOneResources()
    command = _timeout_report_result(module, "release_focus_all", -15, b"focus")
    spec = module.CommandSpec(
        command_id="release_focus_all",
        argv=(PYTHON, "-m", "pytest", "tests/browser/test_release_viewports.py"),
        timeout_seconds=180,
        conftest_mode=module.ConftestMode.PROJECT,
        evidence_format=module.EvidenceFormat.JUNIT,
        evidence_path=Path("/tmp/release_focus_all.junit.xml"),
    )
    focus_node = "test_release_focus_indicator_meets_three_to_one[1024x768]"
    focus_value = (
        '{"targets":12,"viewport":{"height":768,"id":"1024x768","width":1024}}'
    )
    suite = module.SuiteEvidence(
        valid=True,
        total=1,
        passed=1,
        failures=0,
        errors=0,
        skipped=0,
        xfailed=0,
        xpassed=0,
        todo=0,
        cancelled=0,
        node_ids=(focus_node,),
        reason="PASS",
        properties=(
            module.EvidenceProperty(
                focus_node,
                "task9.focus_measurement",
                focus_value,
            ),
        ),
    )
    decision = module.DecisionResult(
        module.DecisionOutcome.TECHNICAL_NO_GO,
        1,
        ("COMMAND_FAILURE",),
    )

    record = module.build_report_record(
        run_id="20260830T020304Z-task9",
        generated_at="2026-08-30T02:03:04Z",
        tested_head="89b3459973bb7cd6e8be43b1251ac6cdb5dfa292",
        decision=decision,
        command_results=(command,),
        command_specs=(spec,),
        gate_results=_passing_gate_results(module),
        lovable_status="MISSING",
        external_decision=None,
        suite_evidence={"release_focus_all": suite},
        internal_evidence=(),
        baseline_snapshot=resources,
        final_snapshot=resources,
    )

    assert record["schema_version"] == 2
    assert record["runtime_versions"] == module.FROZEN_RUNTIME_VERSION
    assert record["pending_status"] == "FINAL_GO_REQUIRES_HUMAN_RELEASE_DECISION"
    assert record["viewport_contracts"] == {
        "child": ["1024x576", "1280x720"],
        "teacher": ["1024x768", "1440x900"],
    }
    command_record = record["commands"][0]
    assert command_record["argv"] == list(spec.argv)
    assert command_record["conftest_mode"] == "project"
    assert command_record["timeout_seconds"] == 180
    assert command_record["duration_seconds"] >= 0
    assert set(command_record["counts"]) == {
        "cancelled",
        "errors",
        "failures",
        "passed",
        "skipped",
        "todo",
        "total",
        "xfailed",
        "xpassed",
    }
    assert command_record["evidence_sha256"]
    assert all({"selectors", "internal_evidence", "reasons"} <= set(gate) for gate in record["gates"])
    assert record["resources"]["before"] == record["resources"]["after"]
    assert set(record["resources"]["before"]) == set(
        module.ResourceSnapshot.__dataclass_fields__
    )
    assert "token" not in record["resources"]["before"]
    assert record["focus_measurements"] == [__import__("json").loads(focus_value)]
    assert record["database_action_evidence"] == []
    assert record["tripwires"]["provider_tts_socket_context_worker"] == "NOT_PROVEN"
    assert len(record["incidents"]) == 3
    assert all(incident["facts"] and incident["corrective_controls"] for incident in record["incidents"])
    assert record["lovable"]["zero_credit_blocker"]
    assert record["lovable"]["connector_used"] is False
    assert set(record["reviews"]) == {"p0", "p1", "p2", "status"}
    assert record["reviews"]["status"] == "PENDING_INDEPENDENT_EVIDENCE_REVIEW"


def test_canonical_json_and_markdown_are_one_way_stable_goldens():
    module = importlib.import_module("scripts.run_interaction_acceptance")
    decision = module.DecisionResult(
        module.DecisionOutcome.TECHNICAL_NO_GO,
        1,
        ("COMMAND_FAILURE", "GATE_FAILURE"),
    )
    commands = (
        _timeout_report_result(module, "term-timeout", -15, b"term-output"),
        _timeout_report_result(module, "kill-timeout", -9, b"kill-output"),
    )
    specs = tuple(
        module.CommandSpec(
            command_id=command.subcommand,
            argv=("/usr/bin/false", command.subcommand),
            timeout_seconds=3,
            conftest_mode=module.ConftestMode.PURE,
            evidence_format=module.EvidenceFormat.TAP,
        )
        for command in commands
    )
    gates = module.evaluate_gates(
        commands,
        None,
        module.EvidenceMap(suites={}, internal=()),
    )
    resources = FakeRunOneResources()

    record = module.build_report_record(
        run_id="20260829T000000Z-task9-fixed",
        generated_at="2026-08-29T00:00:00Z",
        tested_head="89b3459973bb7cd6e8be43b1251ac6cdb5dfa292",
        decision=decision,
        command_results=commands,
        command_specs=specs,
        gate_results=gates,
        lovable_status="PROVIDED_OR_WAIVED",
        external_decision=None,
        baseline_snapshot=resources,
        final_snapshot=resources,
    )
    json_bytes = module.canonical_json_bytes(record)
    markdown = module.render_report_markdown(record)

    assert module.canonical_json_bytes(record) == json_bytes
    assert module.render_report_markdown(record) == markdown
    assert hashlib.sha256(json_bytes).hexdigest() == "a8a3d38199ca82e822b67cabab182d136227ebf4ef3b3a2e8c6adf6083a0370f"
    assert hashlib.sha256(markdown.encode()).hexdigest() == "03603939fa9074bde6d260af06accea0375719f6017692dd311c2a5dbe49bd9f"
    assert "Runner schema: `2`" in markdown
    assert "argv:" in markdown
    assert "Focus measurements:" in markdown
    assert "Final GO remains a human release decision." in markdown


def FakeRunOneResources(
    *,
    git_head="89b3459973bb7cd6e8be43b1251ac6cdb5dfa292",
    git_porcelain=b"",
    token="stable",
    unsafe_reasons=(),
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    regular = module.FileSnapshot(
        kind=module.FileKind.REGULAR,
        mode=0o644,
        size=len(token),
        mtime_ns=1_787_000_000_000_000_000,
        sha256=digest,
    )
    missing = module.FileSnapshot(kind=module.FileKind.MISSING)
    directory_root = module.FileSnapshot(
        kind=module.FileKind.DIRECTORY,
        mode=0o755,
        size=0,
        mtime_ns=1_787_000_000_000_000_000,
    )
    directory_payload = {
        "root": {
            "error": None,
            "kind": "directory",
            "mode": 0o755,
            "mtime_ns": 1_787_000_000_000_000_000,
            "sha256": None,
            "size": 0,
            "symlink_target": None,
        },
        "entries": [],
        "scan_error": None,
        "scan_source": None,
    }
    directory_digest = hashlib.sha256(
        __import__("json").dumps(
            directory_payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    empty_directory = module.DirectorySnapshot(
        root=directory_root,
        entries=(),
        digest=directory_digest,
        unsafe_reasons=(),
    )
    protected = tuple(
        module.ProtectedPathSnapshot(
            relative_path=relative_path,
            file=(directory_root if index >= 2 else regular),
            directory=(empty_directory if index >= 2 else None),
            unsafe_reasons=(),
        )
        for index, relative_path in enumerate(module.PROTECTED_USER_PATHS)
    )
    return module.ResourceSnapshot(
        database=module.DatabaseSnapshot(
            logical_digest=digest,
            database=regular,
            wal=missing,
            shm=missing,
            unsafe_reasons=(),
        ),
        log=regular,
        tts=empty_directory,
        media=empty_directory,
        user_paths=protected,
        git_head=git_head,
        git_porcelain=git_porcelain,
        unsafe_reasons=tuple(unsafe_reasons),
    )


def _run_one_executor(*processes, snapshots):
    return ScriptedProcessExecutor(*processes, snapshots=snapshots)


def test_run_one_success_uses_frozen_id_strict_evidence_and_sanitized_env(tmp_path):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    _write_junit(
        artifact_root,
        "runner.junit.xml",
        '<testsuite tests="1" failures="0" errors="0" skipped="0">'
        '<testcase name="test_pass"/></testsuite>',
    )
    process = FakeProcess([(b"pytest output", b"", 0)], [False])
    stable = FakeRunOneResources()
    executor = _run_one_executor(process, snapshots=[stable, stable, stable, stable])

    result = module.run_one_command(
        "runner",
        repo_root=Path(__file__).resolve().parents[1],
        artifact_root=artifact_root,
        parent_env=HostileParentEnvironment(),
        executor=executor,
        expected_head=stable.git_head,
        version_validator=lambda _root: True,
    )

    assert result.exit_code == 0
    assert result.command_result.classified_outcome is module.ClassifiedOutcome.SUCCESS
    assert result.evidence.valid is True
    assert executor.events.count("capture") == 4
    assert executor.events.count("start:runner") == 1


def test_run_one_detects_resource_drift_between_preflight_and_child_start(tmp_path):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    process = FakeProcess([(b"must not run", b"", 0)], [False])
    stable = FakeRunOneResources()
    drifted = FakeRunOneResources(token="drifted")
    executor = _run_one_executor(
        process,
        snapshots=[stable, drifted, drifted, drifted],
    )

    result = module.run_one_command(
        "runner",
        repo_root=Path(__file__).resolve().parents[1],
        artifact_root=artifact_root,
        parent_env={},
        executor=executor,
        expected_head=stable.git_head,
        version_validator=lambda _root: True,
    )

    assert result.exit_code == 3
    assert result.command_result.child_started is False
    assert result.command_result.before_snapshot == stable
    assert result.command_result.after_snapshot == drifted
    assert result.command_result.classified_outcome is module.ClassifiedOutcome.SAFETY_FAILURE
    assert result.command_result.reason == "RESOURCE_DRIFT"
    assert "start:runner" not in executor.events


def test_run_one_rejects_unknown_id_before_resource_io_or_child_start(tmp_path):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    executor = _run_one_executor(snapshots=[])

    result = module.run_one_command(
        "python -c arbitrary",
        repo_root=Path(__file__).resolve().parents[1],
        artifact_root=tmp_path,
        parent_env={},
        executor=executor,
        expected_head="89b3459973bb7cd6e8be43b1251ac6cdb5dfa292",
        version_validator=lambda _root: True,
    )

    assert result.exit_code == 64
    assert result.command_result.reason == "CLI_MISUSE"
    assert result.command_result.before_snapshot is None
    assert result.command_result.after_snapshot is None
    assert executor.events == []


def test_run_one_unsafe_baseline_and_wrong_head_start_no_child(tmp_path):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    unsafe = FakeRunOneResources(unsafe_reasons=("LOG_NOT_REGULAR",))
    unsafe_executor = _run_one_executor(snapshots=[unsafe])
    unsafe_result = module.run_one_command(
        "runner",
        repo_root=Path(__file__).resolve().parents[1],
        artifact_root=tmp_path / "unsafe",
        parent_env={},
        executor=unsafe_executor,
        expected_head=unsafe.git_head,
        version_validator=lambda _root: True,
    )

    wrong = FakeRunOneResources(git_head="0" * 40)
    wrong_executor = _run_one_executor(snapshots=[wrong, wrong])
    wrong_result = module.run_one_command(
        "runner",
        repo_root=Path(__file__).resolve().parents[1],
        artifact_root=tmp_path / "wrong",
        parent_env={},
        executor=wrong_executor,
        expected_head="89b3459973bb7cd6e8be43b1251ac6cdb5dfa292",
        version_validator=lambda _root: True,
    )

    assert (unsafe_result.exit_code, unsafe_result.command_result.reason) == (
        3,
        "RESOURCE_BASELINE_UNAVAILABLE",
    )
    assert unsafe_result.command_result.before_snapshot is None
    assert unsafe_result.command_result.after_snapshot is None
    assert (wrong_result.exit_code, wrong_result.command_result.reason) == (
        1,
        "WRONG_HEAD_OR_VERSION",
    )
    assert wrong_result.command_result.before_snapshot == wrong
    assert wrong_result.command_result.after_snapshot == wrong
    assert all(not event.startswith("start:") for event in unsafe_executor.events)
    assert all(not event.startswith("start:") for event in wrong_executor.events)


@pytest.mark.parametrize("child_exit", [1, 2, 3, 7, 64])
def test_run_one_passes_through_only_positive_exited_child_codes(tmp_path, child_exit):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    process = FakeProcess([(b"failed", b"", child_exit)], [False])
    stable = FakeRunOneResources()
    executor = _run_one_executor(process, snapshots=[stable, stable, stable, stable])

    result = module.run_one_command(
        "runner",
        repo_root=Path(__file__).resolve().parents[1],
        artifact_root=tmp_path,
        parent_env={},
        executor=executor,
        expected_head=stable.git_head,
        version_validator=lambda _root: True,
    )

    assert result.exit_code == child_exit
    assert result.command_result.termination is module.Termination.EXITED
    assert result.command_result.classified_outcome is module.ClassifiedOutcome.CHILD_NONZERO


def test_run_one_zero_exit_with_invalid_evidence_is_technical_failure(tmp_path):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    _write_junit(
        artifact_root,
        "runner.junit.xml",
        '<testsuite tests="0" failures="0" errors="0" skipped="0"/>',
    )
    process = FakeProcess([(b"", b"", 0)], [False])
    stable = FakeRunOneResources()
    executor = _run_one_executor(process, snapshots=[stable, stable, stable, stable])

    result = module.run_one_command(
        "runner",
        repo_root=Path(__file__).resolve().parents[1],
        artifact_root=artifact_root,
        parent_env={},
        executor=executor,
        expected_head=stable.git_head,
        version_validator=lambda _root: True,
    )

    assert result.exit_code == 1
    assert result.evidence.reason == "ZERO_TESTS"
    assert result.command_result.classified_outcome is module.ClassifiedOutcome.TECHNICAL_FAILURE
    assert result.command_result.reason == "INVALID_EVIDENCE:ZERO_TESTS"


def _assert_exact_not_started_result(
    module,
    result,
    *,
    outcome,
    reason,
    before,
    after,
):
    command = result.command_result
    assert command.child_started is False
    assert command.child_exit is None
    assert command.termination is module.Termination.NOT_STARTED
    assert command.output_complete is None
    assert command.residual_group_observed is False
    assert command.cleanup_failures == ()
    assert command.classified_outcome is outcome
    assert command.reason == reason
    assert command.before_snapshot is before
    assert command.after_snapshot is after


def test_unit7_cli_refusal_invalid_argv_never_constructs_an_executor(monkeypatch):
    module = importlib.import_module("scripts.run_interaction_acceptance")

    class ForbiddenExecutor:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("invalid CLI reached resource/executor setup")

    monkeypatch.setattr(module, "PopenProcessExecutor", ForbiddenExecutor)
    invalid_argv = (
        (),
        ("run",),
        ("run-one",),
        ("run-one", "runner", "extra"),
        ("unknown",),
        ("run", "extra"),
        ("render-report",),
        ("render-report", "one.json", "extra"),
    )

    assert [module.main(argv) for argv in invalid_argv] == [64] * len(invalid_argv)


def test_unit7_cli_refusal_unknown_id_is_exact_cli_misuse_without_resource_io(
    tmp_path,
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    executor = _run_one_executor(snapshots=[])

    result = module.run_one_command(
        "not-a-frozen-command",
        repo_root=Path(__file__).resolve().parents[1],
        artifact_root=tmp_path,
        parent_env={},
        executor=executor,
        version_validator=lambda _root: True,
    )

    assert result.exit_code == 64
    _assert_exact_not_started_result(
        module,
        result,
        outcome=module.ClassifiedOutcome.CLI_MISUSE,
        reason="CLI_MISUSE",
        before=None,
        after=None,
    )
    assert executor.events == []


@pytest.mark.parametrize("baseline_mode", ["missing", "unsafe"])
def test_unit7_cli_refusal_missing_or_unsafe_baseline_is_exact_safety_no_start(
    tmp_path, baseline_mode
):
    module = importlib.import_module("scripts.run_interaction_acceptance")

    if baseline_mode == "missing":
        class MissingBaselineExecutor:
            def __init__(self):
                self.events = []

            def capture_resources(self):
                self.events.append("capture")
                raise module.ResourceCaptureError("synthetic missing baseline")

            def start(self, _spec, _env):
                self.events.append("start")
                raise AssertionError("missing baseline started a child")

        executor = MissingBaselineExecutor()
    else:
        unsafe = FakeRunOneResources(unsafe_reasons=("DATABASE_MISSING",))
        executor = _run_one_executor(snapshots=[unsafe])

    result = module.run_one_command(
        "runner",
        repo_root=Path(__file__).resolve().parents[1],
        artifact_root=tmp_path,
        parent_env={},
        executor=executor,
        expected_head=FakeRunOneResources().git_head,
        version_validator=lambda _root: True,
    )

    assert result.exit_code == 3
    _assert_exact_not_started_result(
        module,
        result,
        outcome=module.ClassifiedOutcome.SAFETY_FAILURE,
        reason="RESOURCE_BASELINE_UNAVAILABLE",
        before=None,
        after=None,
    )
    assert not any(event.startswith("start") for event in executor.events)


@pytest.mark.parametrize("refusal", ["wrong-head", "wrong-version"])
def test_unit7_cli_refusal_after_baseline_is_exact_technical_no_start(
    tmp_path, refusal
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    stable = FakeRunOneResources(
        git_head="0" * 40 if refusal == "wrong-head" else FakeRunOneResources().git_head
    )
    executor = _run_one_executor(snapshots=[stable, stable])

    result = module.run_one_command(
        "runner",
        repo_root=Path(__file__).resolve().parents[1],
        artifact_root=tmp_path,
        parent_env={},
        executor=executor,
        expected_head=FakeRunOneResources().git_head,
        version_validator=lambda _root: refusal != "wrong-version",
    )

    assert result.exit_code == 1
    _assert_exact_not_started_result(
        module,
        result,
        outcome=module.ClassifiedOutcome.TECHNICAL_FAILURE,
        reason="WRONG_HEAD_OR_VERSION",
        before=stable,
        after=stable,
    )
    assert executor.events == ["capture", "capture"]


def test_unit7_process_result_spawn_and_normal_failure_contract(tmp_path):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    stable = FakeResources()

    class SpawnFailureExecutor(ScriptedProcessExecutor):
        def start(self, spec, env):
            del env
            self.events.append(f"start:{spec.command_id}")
            raise OSError("synthetic spawn refusal")

    spawn_executor = SpawnFailureExecutor(snapshots=[stable, stable])
    spawned = module.run_command(
        _unit_process_spec(module, tmp_path), env={}, executor=spawn_executor
    )
    failed = module.run_command(
        _unit_process_spec(module, tmp_path),
        env={},
        executor=ScriptedProcessExecutor(
            FakeProcess([(b"normal-failure", b"", 7)], [False]),
                snapshots=[stable, stable, stable],
        ),
    )

    assert (
        spawned.child_started,
        spawned.child_exit,
        spawned.termination,
        spawned.output_complete,
        spawned.classified_outcome,
        spawned.reason,
        spawned.before_snapshot,
        spawned.after_snapshot,
    ) == (
        False,
        None,
        module.Termination.SPAWN_FAILED,
        None,
        module.ClassifiedOutcome.TECHNICAL_FAILURE,
        "SPAWN_FAILED",
        stable,
        stable,
    )
    assert (
        failed.child_started,
        failed.child_exit,
        failed.termination,
        failed.output_complete,
        failed.classified_outcome,
        failed.reason,
    ) == (
        True,
        7,
        module.Termination.EXITED,
        True,
        module.ClassifiedOutcome.CHILD_NONZERO,
        "CHILD_NONZERO",
    )


def test_unit7_process_result_timeout_signal_residual_and_incomplete_contract(
    tmp_path,
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    timeout = module.run_command(
        _unit_process_spec(module, tmp_path),
        env={},
        executor=ScriptedProcessExecutor(
            FakeProcess(
                [_timeout(), (b"term-complete", b"", -15)],
                [False],
                term_returncode=-15,
            )
        ),
    )
    signaled = module.run_command(
        _unit_process_spec(module, tmp_path),
        env={},
        executor=ScriptedProcessExecutor(
            FakeProcess([(b"signal-complete", b"", -9)], [False])
        ),
    )
    residual = module.run_command(
        _unit_process_spec(module, tmp_path),
        env={},
        executor=ScriptedProcessExecutor(
            FakeProcess([(b"leader-complete", b"", 0)], [True, False])
        ),
    )
    incomplete = module.run_command(
        _unit_process_spec(module, tmp_path),
        env={},
        executor=ScriptedProcessExecutor(
            FakeProcess(
                [_timeout(), _timeout(), _timeout(b"latest")],
                [True],
                kill_returncode=-9,
            )
        ),
    )

    assert (
        timeout.child_exit,
        timeout.termination,
        timeout.output_complete,
        timeout.residual_group_observed,
        timeout.cleanup_failures,
        timeout.classified_outcome,
    ) == (
        -15,
        module.Termination.TIMED_OUT,
        True,
        False,
        (),
        module.ClassifiedOutcome.TECHNICAL_FAILURE,
    )
    assert (
        signaled.child_exit,
        signaled.termination,
        signaled.output_complete,
        signaled.classified_outcome,
    ) == (
        -9,
        module.Termination.SIGNALED,
        True,
        module.ClassifiedOutcome.TECHNICAL_FAILURE,
    )
    assert (
        residual.termination,
        residual.output_complete,
        residual.residual_group_observed,
        residual.cleanup_failures,
        residual.classified_outcome,
        residual.reason,
    ) == (
        module.Termination.EXITED,
        True,
        True,
        (),
        module.ClassifiedOutcome.SAFETY_FAILURE,
        "RESIDUAL_PROCESS_GROUP",
    )
    assert incomplete.output_complete is False
    assert incomplete.after_snapshot is None
    assert incomplete.cleanup_failures == (
        module.CleanupFailure.PIPE_DRAIN_TIMEOUT,
        module.CleanupFailure.GROUP_SURVIVED,
    )
    assert incomplete.classified_outcome is module.ClassifiedOutcome.SAFETY_FAILURE
    assert incomplete.reason == "PROCESS_CLEANUP_INCOMPLETE"


def test_unit7_process_result_artifact_write_failure_is_captured(tmp_path):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    stable = FakeResources()

    class ArtifactFailureExecutor(ScriptedProcessExecutor):
        def write_streams(self, command_id, stdout, stderr):
            self.events.append(f"write:{command_id}")
            raise OSError("synthetic artifact write failure")

    executor = ArtifactFailureExecutor(
        FakeProcess([(b"complete", b"", 0)], [False]),
        snapshots=[stable, stable, stable],
    )

    result = module.run_command(
        _unit_process_spec(module, tmp_path), env={}, executor=executor
    )

    assert result.child_started is True
    assert result.child_exit == 0
    assert result.termination is module.Termination.EXITED
    assert result.output_complete is True
    assert result.before_snapshot == stable
    assert result.after_snapshot == stable
    assert result.classified_outcome is module.ClassifiedOutcome.TECHNICAL_FAILURE
    assert result.reason == "ARTIFACT_WRITE_FAILED"


def test_unit7_drift_precedence_overrides_child_preflight_and_spawn_failures(
    tmp_path,
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    stable = FakeRunOneResources()
    drifted = FakeRunOneResources(token="drifted")

    child_executor = _run_one_executor(
        FakeProcess([(b"child-failure", b"", 64)], [False]),
        snapshots=[stable, stable, drifted, drifted],
    )
    child_result = module.run_one_command(
        "runner",
        repo_root=Path(__file__).resolve().parents[1],
        artifact_root=tmp_path / "child",
        parent_env={},
        executor=child_executor,
        expected_head=stable.git_head,
        version_validator=lambda _root: True,
    )

    wrong_head = FakeRunOneResources(git_head="0" * 40)
    wrong_head_drifted = FakeRunOneResources(git_head="0" * 40, token="drifted")
    preflight_executor = _run_one_executor(
        snapshots=[wrong_head, wrong_head_drifted]
    )
    preflight_result = module.run_one_command(
        "runner",
        repo_root=Path(__file__).resolve().parents[1],
        artifact_root=tmp_path / "preflight",
        parent_env={},
        executor=preflight_executor,
        expected_head=stable.git_head,
        version_validator=lambda _root: True,
    )

    class SpawnDriftExecutor(ScriptedProcessExecutor):
        def start(self, spec, env):
            del env
            self.events.append(f"start:{spec.command_id}")
            raise OSError("synthetic spawn failure")

    spawn_executor = SpawnDriftExecutor(
        snapshots=[stable, stable, drifted]
    )
    spawn_result = module.run_one_command(
        "runner",
        repo_root=Path(__file__).resolve().parents[1],
        artifact_root=tmp_path / "spawn",
        parent_env={},
        executor=spawn_executor,
        expected_head=stable.git_head,
        version_validator=lambda _root: True,
    )

    for result in (child_result, preflight_result, spawn_result):
        assert result.exit_code == 3
        assert result.command_result.classified_outcome is module.ClassifiedOutcome.SAFETY_FAILURE
        assert result.command_result.reason == "RESOURCE_DRIFT"
        assert result.command_result.before_snapshot is not None
        assert result.command_result.after_snapshot is not None
        assert result.command_result.before_snapshot != result.command_result.after_snapshot


def test_unit7_drift_precedence_incomplete_cleanup_has_null_after_and_safety_exit(
    tmp_path,
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    stable = FakeRunOneResources()
    process = FakeProcess(
        [_timeout(), _timeout(), _timeout(b"owned-output")],
        [True],
        kill_returncode=-9,
    )
    executor = _run_one_executor(process, snapshots=[stable, stable])

    result = module.run_one_command(
        "runner",
        repo_root=Path(__file__).resolve().parents[1],
        artifact_root=tmp_path,
        parent_env={},
        executor=executor,
        expected_head=stable.git_head,
        version_validator=lambda _root: True,
    )

    assert result.exit_code == 3
    assert result.command_result.classified_outcome is module.ClassifiedOutcome.SAFETY_FAILURE
    assert result.command_result.reason == "PROCESS_CLEANUP_INCOMPLETE"
    assert result.command_result.before_snapshot == stable
    assert result.command_result.after_snapshot is None
    assert result.command_result.output_complete is False
    assert result.command_result.cleanup_failures == (
        module.CleanupFailure.PIPE_DRAIN_TIMEOUT,
        module.CleanupFailure.GROUP_SURVIVED,
    )


def test_unit7_drift_precedence_rechecks_after_artifact_write_on_child_failure(
    tmp_path,
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    stable = FakeRunOneResources()
    drifted = FakeRunOneResources(token="artifact-write-drift")
    executor = _run_one_executor(
        FakeProcess([(b"child-failure", b"", 64)], [False]),
        snapshots=[stable, stable, stable, drifted],
    )

    result = module.run_one_command(
        "runner",
        repo_root=Path(__file__).resolve().parents[1],
        artifact_root=tmp_path,
        parent_env={},
        executor=executor,
        expected_head=stable.git_head,
        version_validator=lambda _root: True,
    )

    assert result.exit_code == 3
    assert result.command_result.child_exit == 64
    assert result.command_result.classified_outcome is module.ClassifiedOutcome.SAFETY_FAILURE
    assert result.command_result.reason == "RESOURCE_DRIFT"
    assert result.command_result.before_snapshot == stable
    assert result.command_result.after_snapshot == drifted
    assert executor.events.count("capture") == 4


def _unit7_command_result_values(module, **changes):
    stable = FakeResources()
    values = {
        "subcommand": "runner",
        "child_started": True,
        "child_exit": 0,
        "termination": module.Termination.EXITED,
        "output_complete": True,
        "residual_group_observed": False,
        "cleanup_failures": (),
        "classified_outcome": module.ClassifiedOutcome.SUCCESS,
        "reason": "SUCCESS",
        "before_snapshot": stable,
        "after_snapshot": stable,
        "stdout": b"",
        "stderr": b"",
    }
    values.update(changes)
    return values


def test_unit7_result_cross_product_accepts_every_frozen_valid_state():
    module = importlib.import_module("scripts.run_interaction_acceptance")
    drifted = FakeResources(token="drifted")
    valid_states = [
        (
            "cli-misuse",
            {
                "child_started": False,
                "child_exit": None,
                "termination": module.Termination.NOT_STARTED,
                "output_complete": None,
                "classified_outcome": module.ClassifiedOutcome.CLI_MISUSE,
                "reason": "CLI_MISUSE",
                "before_snapshot": None,
                "after_snapshot": None,
            },
        ),
        (
            "baseline-unavailable",
            {
                "child_started": False,
                "child_exit": None,
                "termination": module.Termination.NOT_STARTED,
                "output_complete": None,
                "classified_outcome": module.ClassifiedOutcome.SAFETY_FAILURE,
                "reason": "RESOURCE_BASELINE_UNAVAILABLE",
                "before_snapshot": None,
                "after_snapshot": None,
            },
        ),
        (
            "technical-preflight",
            {
                "child_started": False,
                "child_exit": None,
                "termination": module.Termination.NOT_STARTED,
                "output_complete": None,
                "classified_outcome": module.ClassifiedOutcome.TECHNICAL_FAILURE,
                "reason": "WRONG_HEAD_OR_VERSION",
            },
        ),
        (
            "technical-preflight-drift",
            {
                "child_started": False,
                "child_exit": None,
                "termination": module.Termination.NOT_STARTED,
                "output_complete": None,
                "classified_outcome": module.ClassifiedOutcome.SAFETY_FAILURE,
                "reason": "RESOURCE_DRIFT",
                "after_snapshot": drifted,
            },
        ),
        (
            "spawn-failure",
            {
                "child_started": False,
                "child_exit": None,
                "termination": module.Termination.SPAWN_FAILED,
                "output_complete": None,
                "classified_outcome": module.ClassifiedOutcome.TECHNICAL_FAILURE,
                "reason": "SPAWN_FAILED",
            },
        ),
        (
            "spawn-drift",
            {
                "child_started": False,
                "child_exit": None,
                "termination": module.Termination.SPAWN_FAILED,
                "output_complete": None,
                "classified_outcome": module.ClassifiedOutcome.SAFETY_FAILURE,
                "reason": "RESOURCE_DRIFT",
                "after_snapshot": drifted,
            },
        ),
        ("normal-success", {}),
        (
            "evidence-failure",
            {
                "classified_outcome": module.ClassifiedOutcome.TECHNICAL_FAILURE,
                "reason": "INVALID_EVIDENCE:ZERO_TESTS",
            },
        ),
        (
            "artifact-failure",
            {
                "classified_outcome": module.ClassifiedOutcome.TECHNICAL_FAILURE,
                "reason": "ARTIFACT_WRITE_FAILED",
            },
        ),
        (
            "normal-child-nonzero",
            {
                "child_exit": 7,
                "classified_outcome": module.ClassifiedOutcome.CHILD_NONZERO,
                "reason": "CHILD_NONZERO",
            },
        ),
        (
            "normal-drift",
            {
                "classified_outcome": module.ClassifiedOutcome.SAFETY_FAILURE,
                "reason": "RESOURCE_DRIFT",
                "after_snapshot": drifted,
            },
        ),
        (
            "spontaneous-signal",
            {
                "child_exit": -9,
                "termination": module.Termination.SIGNALED,
                "classified_outcome": module.ClassifiedOutcome.TECHNICAL_FAILURE,
                "reason": "CHILD_SIGNALED",
            },
        ),
        (
            "spontaneous-signal-drift",
            {
                "child_exit": -15,
                "termination": module.Termination.SIGNALED,
                "classified_outcome": module.ClassifiedOutcome.SAFETY_FAILURE,
                "reason": "RESOURCE_DRIFT",
                "after_snapshot": drifted,
            },
        ),
        (
            "contained-timeout-term-handler-zero",
            {
                "child_exit": 0,
                "termination": module.Termination.TIMED_OUT,
                "classified_outcome": module.ClassifiedOutcome.TECHNICAL_FAILURE,
                "reason": "COMMAND_TIMEOUT",
            },
        ),
        (
            "contained-timeout-term",
            {
                "child_exit": -15,
                "termination": module.Termination.TIMED_OUT,
                "classified_outcome": module.ClassifiedOutcome.TECHNICAL_FAILURE,
                "reason": "COMMAND_TIMEOUT",
            },
        ),
        (
            "contained-timeout-kill-drift",
            {
                "child_exit": -9,
                "termination": module.Termination.TIMED_OUT,
                "classified_outcome": module.ClassifiedOutcome.SAFETY_FAILURE,
                "reason": "RESOURCE_DRIFT",
                "after_snapshot": drifted,
            },
        ),
        (
            "cleaned-residual-exit",
            {
                "residual_group_observed": True,
                "classified_outcome": module.ClassifiedOutcome.SAFETY_FAILURE,
                "reason": "RESIDUAL_PROCESS_GROUP",
            },
        ),
        (
            "cleaned-residual-signal",
            {
                "child_exit": -15,
                "termination": module.Termination.SIGNALED,
                "residual_group_observed": True,
                "classified_outcome": module.ClassifiedOutcome.SAFETY_FAILURE,
                "reason": "RESIDUAL_PROCESS_GROUP",
            },
        ),
        (
            "incomplete-timeout-reaped",
            {
                "child_exit": -9,
                "termination": module.Termination.TIMED_OUT,
                "output_complete": False,
                "cleanup_failures": (
                    module.CleanupFailure.PIPE_DRAIN_TIMEOUT,
                    module.CleanupFailure.GROUP_SURVIVED,
                ),
                "classified_outcome": module.ClassifiedOutcome.SAFETY_FAILURE,
                "reason": "PROCESS_CLEANUP_INCOMPLETE",
                "after_snapshot": None,
            },
        ),
        (
            "incomplete-timeout-unreaped",
            {
                "child_exit": None,
                "termination": module.Termination.TIMED_OUT,
                "output_complete": False,
                "cleanup_failures": (
                    module.CleanupFailure.PIPE_DRAIN_TIMEOUT,
                    module.CleanupFailure.LEADER_UNREAPED,
                ),
                "classified_outcome": module.ClassifiedOutcome.SAFETY_FAILURE,
                "reason": "PROCESS_CLEANUP_INCOMPLETE",
                "after_snapshot": None,
            },
        ),
        (
            "incomplete-residual-exit",
            {
                "residual_group_observed": True,
                "output_complete": False,
                "cleanup_failures": (module.CleanupFailure.GROUP_SURVIVED,),
                "classified_outcome": module.ClassifiedOutcome.SAFETY_FAILURE,
                "reason": "PROCESS_CLEANUP_INCOMPLETE",
                "after_snapshot": None,
            },
        ),
    ]

    for label, changes in valid_states:
        result = module.CommandResult(
            **_unit7_command_result_values(module, **changes)
        )
        assert result.reason, label
        assert (result.before_snapshot is None) is (label in {
            "cli-misuse",
            "baseline-unavailable",
        })


def test_unit7_result_cross_product_rejects_every_invalid_state():
    module = importlib.import_module("scripts.run_interaction_acceptance")
    invalid_states = [
        (
            "not-started-child-exit",
            {
                "child_started": False,
                "termination": module.Termination.NOT_STARTED,
                "output_complete": None,
            },
        ),
        (
            "no-baseline-unapproved-reason",
            {
                "child_started": False,
                "child_exit": None,
                "termination": module.Termination.NOT_STARTED,
                "output_complete": None,
                "classified_outcome": module.ClassifiedOutcome.TECHNICAL_FAILURE,
                "reason": "WRONG_HEAD_OR_VERSION",
                "before_snapshot": None,
                "after_snapshot": None,
            },
        ),
        (
            "baseline-unavailable-with-snapshot",
            {
                "child_started": False,
                "child_exit": None,
                "termination": module.Termination.NOT_STARTED,
                "output_complete": None,
                "classified_outcome": module.ClassifiedOutcome.SAFETY_FAILURE,
                "reason": "RESOURCE_BASELINE_UNAVAILABLE",
            },
        ),
        ("started-without-before", {"before_snapshot": None, "after_snapshot": None}),
        ("complete-with-null-after", {"after_snapshot": None}),
        (
            "incomplete-without-cleanup",
            {
                "output_complete": False,
                "classified_outcome": module.ClassifiedOutcome.SAFETY_FAILURE,
                "reason": "PROCESS_CLEANUP_INCOMPLETE",
                "after_snapshot": None,
            },
        ),
        (
            "cleanup-with-complete-output",
            {"cleanup_failures": (module.CleanupFailure.GROUP_SURVIVED,)},
        ),
        (
            "cleanup-not-canonical",
            {
                "output_complete": False,
                "cleanup_failures": (
                    module.CleanupFailure.GROUP_SURVIVED,
                    module.CleanupFailure.PIPE_DRAIN_TIMEOUT,
                ),
                "classified_outcome": module.ClassifiedOutcome.SAFETY_FAILURE,
                "reason": "PROCESS_CLEANUP_INCOMPLETE",
                "after_snapshot": None,
            },
        ),
        (
            "unreaped-with-integer-exit",
            {
                "termination": module.Termination.TIMED_OUT,
                "output_complete": False,
                "cleanup_failures": (module.CleanupFailure.LEADER_UNREAPED,),
                "classified_outcome": module.ClassifiedOutcome.SAFETY_FAILURE,
                "reason": "PROCESS_CLEANUP_INCOMPLETE",
                "after_snapshot": None,
            },
        ),
        (
            "null-exit-without-unreaped",
            {
                "child_exit": None,
                "termination": module.Termination.TIMED_OUT,
                "output_complete": False,
                "cleanup_failures": (module.CleanupFailure.PIPE_DRAIN_TIMEOUT,),
                "classified_outcome": module.ClassifiedOutcome.SAFETY_FAILURE,
                "reason": "PROCESS_CLEANUP_INCOMPLETE",
                "after_snapshot": None,
            },
        ),
        (
            "timeout-residual-flag",
            {
                "child_exit": -9,
                "termination": module.Termination.TIMED_OUT,
                "residual_group_observed": True,
                "classified_outcome": module.ClassifiedOutcome.TECHNICAL_FAILURE,
                "reason": "COMMAND_TIMEOUT",
            },
        ),
        (
            "residual-not-safety",
            {"residual_group_observed": True},
        ),
        ("negative-exited", {"child_exit": -9}),
        (
            "nonnegative-signaled",
            {"termination": module.Termination.SIGNALED},
        ),
        (
            "positive-exited-technical",
            {
                "child_exit": 2,
                "classified_outcome": module.ClassifiedOutcome.TECHNICAL_FAILURE,
                "reason": "COMMAND_FAILURE",
            },
        ),
        (
            "zero-exited-child-nonzero",
            {
                "classified_outcome": module.ClassifiedOutcome.CHILD_NONZERO,
                "reason": "CHILD_NONZERO",
            },
        ),
        (
            "spawn-marked-started",
            {"termination": module.Termination.SPAWN_FAILED},
        ),
        ("blank-reason", {"reason": ""}),
        ("non-tuple-cleanup", {"cleanup_failures": []}),
        ("non-bytes-stdout", {"stdout": "text"}),
    ]

    for label, changes in invalid_states:
        with pytest.raises((TypeError, ValueError), match="command result"):
            module.CommandResult(
                **_unit7_command_result_values(module, **changes)
            )


def test_unit7_result_child_exit_2_3_64_stays_distinct_in_json_and_markdown():
    module = importlib.import_module("scripts.run_interaction_acceptance")
    resources = FakeRunOneResources()
    commands = tuple(
        module.CommandResult(
            **_unit7_command_result_values(
                module,
                subcommand=f"child-exit-{child_exit}",
                child_exit=child_exit,
                classified_outcome=module.ClassifiedOutcome.CHILD_NONZERO,
                reason="CHILD_NONZERO",
                before_snapshot=resources,
                after_snapshot=resources,
            )
        )
        for child_exit in (2, 3, 64)
    )
    decision = module.DecisionResult(
        module.DecisionOutcome.TECHNICAL_NO_GO,
        1,
        (
            "COMMAND_FAILURE",
            "GATE_FAILURE",
            "LOVABLE_DELIVERABLE_MISSING",
        ),
    )
    specs = tuple(
        module.CommandSpec(
            command_id=command.subcommand,
            argv=("/usr/bin/false", command.subcommand),
            timeout_seconds=3,
            conftest_mode=module.ConftestMode.PURE,
            evidence_format=module.EvidenceFormat.TAP,
        )
        for command in commands
    )
    gates = module.evaluate_gates(
        commands,
        resources,
        module.EvidenceMap(suites={}, internal=()),
    )
    record = module.build_report_record(
        run_id="20260829T010000Z-child-exits",
        generated_at="2026-08-29T01:00:00Z",
        tested_head=FakeRunOneResources().git_head,
        decision=decision,
        command_results=commands,
        command_specs=specs,
        gate_results=gates,
        lovable_status="MISSING",
        external_decision=None,
        baseline_snapshot=resources,
        final_snapshot=resources,
    )

    payload = __import__("json").loads(module.canonical_json_bytes(record))
    assert [row["child_exit"] for row in payload["commands"]] == [2, 3, 64]
    assert [row["runner_process_exit"] for row in payload["commands"]] == [2, 3, 64]
    assert {row["termination"] for row in payload["commands"]} == {"EXITED"}
    assert {row["classified_outcome"] for row in payload["commands"]} == {
        "CHILD_NONZERO"
    }

    markdown = module.render_report_markdown(record)
    for order, child_exit in enumerate((2, 3, 64), start=1):
        assert f"| {order} | `child-exit-{child_exit}` | `noconftest` | `3` |" in markdown
        assert f"`EXITED` | `CHILD_NONZERO` | `{child_exit}` | `{child_exit}` |" in markdown


def _unit7_passing_tap(node_id):
    return (
        "TAP version 13\n"
        f"ok 1 - {node_id}\n"
        "1..1\n"
        "# tests 1\n"
        "# pass 1\n"
        "# fail 0\n"
        "# cancelled 0\n"
        "# skipped 0\n"
        "# todo 0\n"
    ).encode()


def _unit7_passing_tap_nodes(node_ids):
    node_ids = tuple(node_ids)
    lines = ["TAP version 13"]
    lines.extend(
        f"ok {index} - {node_id}"
        for index, node_id in enumerate(node_ids, start=1)
    )
    lines.extend(
        (
            f"1..{len(node_ids)}",
            f"# tests {len(node_ids)}",
            f"# pass {len(node_ids)}",
            "# fail 0",
            "# cancelled 0",
            "# skipped 0",
            "# todo 0",
        )
    )
    return ("\n".join(lines) + "\n").encode()


@pytest.mark.parametrize(
    "porcelain",
    [
        b"M  scripts/run_interaction_acceptance.py\0",
        b" M scripts/run_interaction_acceptance.py\0",
        b"?? tests/new_implementation_test.py\0",
        b"M  .workbuddy/memory/2026-08-22.md\0",
    ],
)
def test_unit8_porcelain_policy_rejects_implementation_dirt_and_nonempty_index(
    porcelain,
):
    module = importlib.import_module("scripts.run_interaction_acceptance")

    assert module.unit8_porcelain_is_allowed(porcelain) is False


def test_unit8_porcelain_policy_allows_only_unstaged_inherited_user_categories():
    module = importlib.import_module("scripts.run_interaction_acceptance")
    inherited = (
        b" M .workbuddy/memory/2026-08-22.md\0"
        b" M docs/superpowers/specs/2026-08-23-interaction-stabilization-design.md\0"
        b"?? .superpowers/brainstorm/synthetic-state\0"
        b"?? docs/superpowers/plans/synthetic-plan.md\0"
    )

    assert module.unit8_porcelain_is_allowed(b"") is True
    assert module.unit8_porcelain_is_allowed(inherited) is True
    assert module.unit8_porcelain_is_allowed(b"not porcelain\0") is False


def test_full_run_requires_exact_designated_candidate_head_before_artifact_write(
    tmp_path,
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    artifact_root = tmp_path / "artifacts" / "acceptance" / "wrong-head"
    current = FakeRunOneResources(git_head="a" * 40)
    executor = ScriptedProcessExecutor(snapshots=[current, current])

    result = module.run_acceptance(
        repo_root=Path(__file__).resolve().parents[1],
        artifact_root=artifact_root,
        run_id="20260830T010203Z-task9",
        generated_at="2026-08-30T01:02:03Z",
        parent_env={},
        executor=executor,
        specs=(),
        expected_head="b" * 40,
        version_validator=lambda _root: True,
        lovable_complete_or_waived=False,
    )

    assert result.exit_code == 1
    assert result.decision.reasons == ("WRONG_HEAD_OR_VERSION",)
    assert not artifact_root.exists()


def test_full_run_rejects_dirty_implementation_tree_before_artifact_write(tmp_path):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    artifact_root = tmp_path / "artifacts" / "acceptance" / "dirty-tree"
    dirty = FakeRunOneResources(
        git_porcelain=b" M scripts/run_interaction_acceptance.py\0"
    )
    executor = ScriptedProcessExecutor(snapshots=[dirty, dirty])

    result = module.run_acceptance(
        repo_root=Path(__file__).resolve().parents[1],
        artifact_root=artifact_root,
        run_id="20260830T010204Z-task9",
        generated_at="2026-08-30T01:02:04Z",
        parent_env={},
        executor=executor,
        specs=(),
        expected_head=dirty.git_head,
        version_validator=lambda _root: True,
        lovable_complete_or_waived=False,
    )

    assert result.exit_code == 1
    assert result.decision.reasons == ("DIRTY_IMPLEMENTATION_TREE",)
    assert not artifact_root.exists()


def test_full_run_partial_custom_inventory_returns_controlled_technical_no_go(
    tmp_path,
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    repo_root = tmp_path / "controlled-repository"
    repo_root.mkdir()
    artifact_root = (
        repo_root / "artifacts" / "acceptance" / "partial-inventory"
    )
    stable = FakeRunOneResources()
    reference = repo_root / "docs" / "lovable" / "prototype-reference.md"
    reference.parent.mkdir(parents=True)
    reference.write_text(
        _valid_lovable_reference_text(stable.git_head), encoding="utf-8"
    )
    complete = _complete_gate_evidence(module)
    command_nodes = {
        **complete.suites,
        "release_focus_all": _suite_evidence(module, ("focus-proof",)),
        "release_db_action_all": _suite_evidence(module, ("db-proof",)),
    }
    specs = tuple(
        module.CommandSpec(
            command_id=command_id,
            argv=("/usr/bin/true",),
            timeout_seconds=3,
            conftest_mode=module.ConftestMode.PROJECT,
            evidence_format=module.EvidenceFormat.TAP,
        )
        for command_id in command_nodes
    )
    processes = tuple(
        FakeProcess(
            [(_unit7_passing_tap_nodes(evidence.node_ids), b"", 0)],
            [False],
        )
        for evidence in command_nodes.values()
    )
    executor = ScriptedProcessExecutor(
        *processes,
        snapshots=[stable] * (len(processes) * 3 + 6),
    )

    result = module.run_acceptance(
        repo_root=repo_root,
        artifact_root=artifact_root,
        run_id="20260830T050000Z-partial-inventory",
        generated_at="2026-08-30T05:00:00Z",
        parent_env={},
        executor=executor,
        expected_head=stable.git_head,
        specs=specs,
        version_validator=lambda _root: True,
        lovable_complete_or_waived=None,
    )

    assert result.exit_code == 1
    assert result.decision.outcome is module.DecisionOutcome.TECHNICAL_NO_GO
    assert "REPORT_INTEGRITY_FAILURE" in result.decision.reasons
    assert result.report_record is not None
    assert result.report_record["decision"]["outcome"] == "TECHNICAL_NO_GO"


def _valid_lovable_reference_text(tested_head):
    return (
        "# Lovable teacher prototype reference\n\n"
        "视觉参考，不连接鸭鸭日记本后端\n\n"
        "- Review date: 2026-08-29\n"
        "- Share URL: https://task9-evidence.lovable.app/\n"
        f"- Source commit: {tested_head}\n"
        "- Checklist result: GO\n"
        "- Open observations: Reviewed two-screen private visual prototype.\n"
    )


def _valid_figma_scope_waiver_text():
    return (
        "# Figma full-product interaction reference\n\n"
        "前向设计真源；历史 Lovable 原型交付已由用户豁免。\n\n"
        "- Review date: 2026-09-02\n"
        "- Verification date: 2026-09-05\n"
        "- Design version: full-product-reviewed-v1\n"
        "- File URL: https://www.figma.com/design/czJ3EIKcXyowhfzBuQt32S\n"
        "- File key: czJ3EIKcXyowhfzBuQt32S\n"
        "- Editor type: figma\n"
        "- Scope: child-and-teacher-full-product\n"
        "- Page count: required=16; auxiliary=2\n"
        "- Required pages: 0:1=00 Cover & Handoff | 1:2=01 Foundations | 1:3=02 Components | 1:4=10 Child · Core States | 1:5=11 Child · Recovery & Teacher Help | 1:6=12 Child · Prototype Flows | 1:7=20 Teacher · Shell & Auth | 1:8=21 Teacher · Today | 1:9=22 Teacher · Children | 1:10=23 Teacher · Ducks | 1:11=24 Teacher · Roster | 1:12=25 Teacher · Review | 1:13=26 Teacher · Growth | 1:14=27 Teacher · Search | 1:15=30 Cross-product Flows | 1:16=90 Code Mapping & Acceptance\n"
        "- Auxiliary pages: 641:2=99 Deprecated Components | 665:2=98 Internal Feature Sources\n"
        "- Viewports: child=1024x576,1280x720; teacher=1024x768,1440x900\n"
        "- Child prototype paths: 93:4->93:133=happy-path | 93:143->93:220=retry-send | 93:230->93:288=teacher-recovery | 93:298->93:386=completion\n"
        "- Teacher prototype paths: 192:4->192:60=auth-to-today | 259:197->192:349=review-save-confirm | 192:504->261:431=child-deactivate-restore | 262:317->262:683=duck-management | 263:450->263:955=roster-save-retry | 584:1199->584:2222=monthly-roster | 264:550->264:698=growth | 265:606->265:774=search\n"
        "- Foundations: 35:2=Foundation System / Approved B+A\n"
        "- Shared components: 70:46=Child/Shell | 533:435=Child/PetOrb | 553:686=Child/ConversationPanel | 104:121=Teacher/Shell | 126:115=Teacher/Dialog | 655:928=Teacher/AvatarUploader\n"
        "- Code mapping: 125:2=Screen Inventory + Node Map | 125:125=Code Mapping + Delta | 125:183=Motion Asset Handoff | 125:249=Acceptance + Release Gate | 147:2440=Exact Review DTO Field Map | 679:2=Future Feature Handoff\n"
        "- Data declaration: fictional-only\n"
        "- Open release items: real-provider-UAT; physical-microphone=HUMAN_UAT_REQUIRED; motion-assets=PLACEHOLDER_REPLACEMENT_AFTER_UAT\n"
        "- Lovable deliverable: WAIVED\n"
        "- Review result: ACCEPTED\n"
        "- Review authority: user-and-release-owner\n"
        "- Evidence plans: 2026-09-01-child-vertical-slice.md@1e200be7b6b3b6316e15252cc086b5ce13f65487c9e4a1a3cc23b18862d510a5, 2026-09-01-teacher-shell-today-vertical-slice.md@259636693a1de958dad481a744f579989123261a55fee5e8a2a68a878269661a, 2026-09-01-teacher-reports-vertical-slice.md@de7b9ebf16afc38c16ae4d523909268b07dc669aa3dc21d02e588e91c6bc2d1f\n"
    )


@pytest.mark.parametrize(
    ("reference_kind", "caller_value", "expected_status"),
    (
        pytest.param("missing", True, "MISSING", id="caller-true-missing"),
        pytest.param("malformed", True, "MISSING", id="caller-true-malformed"),
        pytest.param("symlink", None, "MISSING", id="is-file-symlink"),
        pytest.param("valid", False, "PROVIDED_OR_WAIVED", id="caller-false-valid"),
        pytest.param(
            "figma-valid",
            None,
            "PROVIDED_OR_WAIVED",
            id="verified-figma-scope-waiver",
        ),
        pytest.param(
            "figma-malformed",
            None,
            "MISSING",
            id="malformed-figma-scope-waiver",
        ),
        pytest.param(
            "figma-symlink",
            None,
            "MISSING",
            id="figma-reference-symlink",
        ),
        pytest.param(
            "figma-arbitrary-key",
            None,
            "MISSING",
            id="figma-arbitrary-key",
        ),
        pytest.param(
            "figma-control-url",
            None,
            "MISSING",
            id="figma-control-character-url",
        ),
        pytest.param(
            "figma-plan-missing",
            None,
            "MISSING",
            id="figma-plan-missing",
        ),
        pytest.param(
            "figma-plan-empty",
            None,
            "MISSING",
            id="figma-plan-empty",
        ),
        pytest.param(
            "figma-plan-tampered",
            None,
            "MISSING",
            id="figma-plan-tampered",
        ),
        pytest.param(
            "figma-plan-symlink",
            None,
            "MISSING",
            id="figma-plan-symlink",
        ),
        pytest.param(
            "figma-plans-dir-symlink",
            None,
            "MISSING",
            id="figma-plans-directory-symlink",
        ),
        pytest.param("missing", None, "MISSING", id="derived-missing-control"),
    ),
)
def test_run_acceptance_derives_lovable_state_from_strict_reference(
    tmp_path, reference_kind, caller_value, expected_status
):
    """Trusting the caller boolean or Path.is_file must fail this real-run test."""

    module = importlib.import_module("scripts.run_interaction_acceptance")
    repo_root = tmp_path / "controlled-repository"
    repo_root.mkdir()
    run_id = "20260830T170000000000Z-task9"
    artifact_root = repo_root / "artifacts" / "acceptance" / run_id
    stable = FakeRunOneResources()
    reference = repo_root / "docs" / "lovable" / "prototype-reference.md"
    figma_reference = repo_root / "docs" / "figma" / "prototype-reference.md"
    if reference_kind.startswith("figma-"):
        source_plans = (
            Path(__file__).resolve().parents[1]
            / "docs"
            / "superpowers"
            / "plans"
        )
        plans_parent = repo_root / "docs" / "superpowers"
        plans_parent.mkdir(parents=True)
        plans = plans_parent / "plans"
        if reference_kind == "figma-plans-dir-symlink":
            plan_destination = tmp_path / "external-figma-plans"
            plan_destination.mkdir()
            plans.symlink_to(plan_destination, target_is_directory=True)
        else:
            plans.mkdir()
            plan_destination = plans
        plan_names = (
            "2026-09-01-child-vertical-slice.md",
            "2026-09-01-teacher-shell-today-vertical-slice.md",
            "2026-09-01-teacher-reports-vertical-slice.md",
        )
        for name in plan_names:
            (plan_destination / name).write_bytes((source_plans / name).read_bytes())
        figma_reference.parent.mkdir(parents=True)
    if reference_kind in {"malformed", "symlink", "valid"}:
        reference.parent.mkdir(parents=True)
    if reference_kind == "malformed":
        reference.write_text("not the frozen nine-line reference\n", encoding="utf-8")
    elif reference_kind == "symlink":
        target = repo_root / "valid-reference-target.md"
        target.write_text(
            _valid_lovable_reference_text(stable.git_head), encoding="utf-8"
        )
        reference.symlink_to(target)
    elif reference_kind == "valid":
        reference.write_text(
            _valid_lovable_reference_text(stable.git_head), encoding="utf-8"
        )
    elif reference_kind.startswith("figma-"):
        figma_text = _valid_figma_scope_waiver_text()
        if reference_kind == "figma-malformed":
            figma_text = figma_text.replace(
                "- Lovable deliverable: WAIVED",
                "- Lovable deliverable: PENDING",
            )
        elif reference_kind == "figma-arbitrary-key":
            figma_text = figma_text.replace(
                "czJ3EIKcXyowhfzBuQt32S", "AAAAAAAAAAAAAAAAAAAAAA"
            )
        elif reference_kind == "figma-control-url":
            figma_text = figma_text.replace("www.figma.com", "www.fig\tma.com")
        figma_reference.write_text(figma_text, encoding="utf-8")
        if reference_kind == "figma-symlink":
            target = tmp_path / "valid-figma-reference-target.md"
            target.write_text(figma_text, encoding="utf-8")
            figma_reference.unlink()
            figma_reference.symlink_to(target)
        elif reference_kind == "figma-plan-missing":
            (plans / plan_names[0]).unlink()
        elif reference_kind == "figma-plan-empty":
            (plans / plan_names[0]).write_bytes(b"")
        elif reference_kind == "figma-plan-tampered":
            (plans / plan_names[0]).write_bytes(
                (plans / plan_names[0]).read_bytes() + b"\n# tampered\n"
            )
        elif reference_kind == "figma-plan-symlink":
            plan = plans / plan_names[0]
            target = tmp_path / "valid-figma-plan-target.md"
            target.write_bytes(plan.read_bytes())
            plan.unlink()
            plan.symlink_to(target)
    elif reference_kind != "missing":
        raise AssertionError(reference_kind)

    spec = module.CommandSpec(
        command_id="shared_node",
        argv=("/usr/bin/true",),
        timeout_seconds=3,
        conftest_mode=module.ConftestMode.PURE,
        evidence_format=module.EvidenceFormat.TAP,
    )
    executor = ScriptedProcessExecutor(
        FakeProcess([(_unit7_passing_tap("controlled-pass"), b"", 0)], [False]),
        snapshots=[stable] * 12,
    )

    result = module.run_acceptance(
        repo_root=repo_root,
        artifact_root=artifact_root,
        run_id=run_id,
        generated_at="2026-08-30T17:00:00Z",
        parent_env={},
        executor=executor,
        expected_head=stable.git_head,
        specs=(spec,),
        version_validator=lambda _root: True,
        lovable_complete_or_waived=caller_value,
    )

    assert result.decision.outcome is module.DecisionOutcome.TECHNICAL_NO_GO
    assert result.report_record is not None
    lovable = result.report_record["lovable"]
    assert lovable["status"] == expected_status
    assert lovable["project_status"] == expected_status
    assert lovable["completion_or_scope_waiver"] is (
        expected_status == "PROVIDED_OR_WAIVED"
    )
    assert lovable["zero_credit_blocker"] == (
        None
        if expected_status == "PROVIDED_OR_WAIVED"
        else "A blank or zero-credit project is not completion evidence."
    )
def test_repository_figma_scope_waiver_matches_the_frozen_review_snapshot():
    module = importlib.import_module("scripts.run_interaction_acceptance")
    repo_root = Path(__file__).resolve().parents[1]
    artifact_root = repo_root / "artifacts" / "acceptance" / "validation-probe"
    reference = repo_root / "docs" / "figma" / "prototype-reference.md"

    assert reference.read_text(encoding="utf-8") == _valid_figma_scope_waiver_text()
    assert module.FIGMA_SCOPE_WAIVER_TEXT == _valid_figma_scope_waiver_text()
    assert module._verified_figma_scope_waiver_is_valid(artifact_root) is True


def test_unit7_run_orchestration_writes_ignored_canonical_artifacts(tmp_path):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    repo_root = Path(__file__).resolve().parents[1]
    artifact_root = tmp_path / "artifacts" / "acceptance" / "fixed-run"
    stable = FakeRunOneResources()
    specs = tuple(
        module.CommandSpec(
            command_id=command_id,
            argv=("/usr/bin/true",),
            timeout_seconds=3,
            conftest_mode=module.ConftestMode.PROJECT,
            evidence_format=module.EvidenceFormat.TAP,
        )
        for command_id in ("shared_node", "child_node")
    )
    processes = tuple(
        FakeProcess([(_unit7_passing_tap(f"synthetic-{index}"), b"", 0)], [False])
        for index in range(1, 3)
    )

    class ArtifactExecutor(ScriptedProcessExecutor):
        def write_streams(self, command_id, stdout, stderr):
            super().write_streams(command_id, stdout, stderr)
            order = ("shared_node", "child_node").index(command_id) + 1
            command_dir = artifact_root / "commands"
            command_dir.mkdir(parents=True, exist_ok=True)
            prefix = f"{order:02d}-{command_id}"
            (command_dir / f"{prefix}.stdout.log").write_bytes(stdout)
            (command_dir / f"{prefix}.stderr.log").write_bytes(stderr)

    executor = ArtifactExecutor(*processes, snapshots=[stable] * 9)
    result = module.run_acceptance(
        repo_root=repo_root,
        artifact_root=artifact_root,
        run_id="20260829T010203Z-task9",
        generated_at="2026-08-29T01:02:03Z",
        parent_env={},
        executor=executor,
        expected_head=stable.git_head,
        specs=specs,
        version_validator=lambda _root: True,
        lovable_complete_or_waived=False,
    )

    assert result.exit_code == 1
    assert result.decision.outcome is module.DecisionOutcome.TECHNICAL_NO_GO
    assert result.decision.final_go is False
    assert tuple(item.subcommand for item in result.command_results) == (
        "shared_node",
        "child_node",
    )
    report_bytes = (artifact_root / "report.json").read_bytes()
    assert report_bytes == module.canonical_json_bytes(__import__("json").loads(report_bytes))
    report = __import__("json").loads(report_bytes)
    markdown_bytes = (artifact_root / "report.md").read_bytes()
    assert report["report_markdown"] == {
        "path": "report.md",
        "sha256": __import__("hashlib").sha256(markdown_bytes).hexdigest(),
        "size": len(markdown_bytes),
    }
    assert (artifact_root / "resources.before.json").is_file()
    assert (artifact_root / "resources.after.json").is_file()
    assert sorted(path.name for path in (artifact_root / "commands").iterdir()) == [
        "01-shared_node.stderr.log",
        "01-shared_node.stdout.log",
        "02-child_node.stderr.log",
        "02-child_node.stdout.log",
    ]
    assert executor.events.count("start:shared_node") == 1
    assert executor.events.count("start:child_node") == 1


def test_full_run_normalizes_completed_report_validation_failure(tmp_path, monkeypatch):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    repo_root = Path(__file__).resolve().parents[1]
    artifact_root = tmp_path / "artifacts" / "acceptance" / "invalid-report"
    stable = FakeRunOneResources()
    spec = module.CommandSpec(
        command_id="shared_node",
        argv=("/usr/bin/true",),
        timeout_seconds=3,
        conftest_mode=module.ConftestMode.PROJECT,
        evidence_format=module.EvidenceFormat.TAP,
    )
    executor = ScriptedProcessExecutor(
        FakeProcess([(_unit7_passing_tap("synthetic-pass"), b"", 0)], [False]),
        snapshots=[stable] * 8,
    )

    def reject_invalid_report(_record):
        raise module.CliMisuseError("synthetic completed-report validation failure")

    monkeypatch.setattr(module, "render_report_markdown", reject_invalid_report)

    result = module.run_acceptance(
        repo_root=repo_root,
        artifact_root=artifact_root,
        run_id="20260830T120000Z-invalid-report",
        generated_at="2026-08-30T12:00:00Z",
        parent_env={},
        executor=executor,
        expected_head=stable.git_head,
        specs=(spec,),
        version_validator=lambda _root: True,
        lovable_complete_or_waived=False,
    )

    assert result.exit_code == 1
    assert result.decision.outcome is module.DecisionOutcome.TECHNICAL_NO_GO
    assert result.decision.reasons == ("REPORT_INTEGRITY_FAILURE",)
    assert result.report_record is None


@pytest.mark.parametrize(
    ("failure_kind", "artifact_reason"),
    (
        pytest.param("write", "ARTIFACT_WRITE_FAILED", id="oserror"),
        pytest.param("integrity", "REPORT_INTEGRITY_FAILURE", id="cli-misuse"),
    ),
)
@pytest.mark.parametrize("safety_source", ("tripwire", "residual", "drift"))
def test_completed_artifact_failure_cannot_replace_an_existing_safety_decision(
    tmp_path, monkeypatch, safety_source, failure_kind, artifact_reason
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    repo_root = Path(__file__).resolve().parents[1]
    artifact_root = tmp_path / "artifacts" / "acceptance" / (
        f"{safety_source}-{failure_kind}"
    )
    stable = FakeRunOneResources()
    drifted = FakeRunOneResources(token="transient-unsafe")

    if safety_source == "tripwire":
        command_id = "backend"
        junit_path = tmp_path / "backend.junit.xml"
        junit_path.write_text(
            _authenticated_tripwire_junit("external_ai"), encoding="utf-8"
        )
        stderr = _signed_tripwire_sidecar(
            command_id,
            (
                _tripwire_record(
                    "external_ai",
                    command_id=command_id,
                    node_id="test_uncaught_breaker",
                    phase="call",
                    sequence=1,
                ),
            ),
        )
        spec = module.CommandSpec(
            command_id=command_id,
            argv=("/usr/bin/false",),
            timeout_seconds=3,
            conftest_mode=module.ConftestMode.PROJECT,
            evidence_format=module.EvidenceFormat.JUNIT,
            evidence_path=junit_path,
        )
        process = FakeProcess([(b"ordinary failure", stderr, 1)], [False])
        expected_primary = "TRIPWIRE_FAILURE"
    else:
        command_id = "shared_node"
        spec = module.CommandSpec(
            command_id=command_id,
            argv=("/usr/bin/true",),
            timeout_seconds=3,
            conftest_mode=module.ConftestMode.PROJECT,
            evidence_format=module.EvidenceFormat.TAP,
        )
        process = FakeProcess(
            [(_unit7_passing_tap("synthetic-pass"), b"", 0)],
            [True, False] if safety_source == "residual" else [False],
        )
        expected_primary = (
            "COMMAND_SAFETY_FAILURE"
            if safety_source == "residual"
            else "RESOURCE_DRIFT"
        )

    class ArtifactFailureExecutor(ScriptedProcessExecutor):
        def __init__(self, child):
            super().__init__(child)
            self.capture_count = 0

        def capture_resources(self):
            self.events.append("capture")
            self.capture_count += 1
            if safety_source == "drift" and self.capture_count == 4:
                return drifted
            return stable

    def fail_completed_artifacts(**_kwargs):
        target = _kwargs["artifact_root"]
        (target / "report.json").write_bytes(b"untrusted-partial-json")
        (target / "report.md").write_bytes(b"untrusted-partial-markdown")
        if failure_kind == "write":
            raise OSError("synthetic completed artifact write failure")
        raise module.CliMisuseError("synthetic completed artifact integrity failure")

    monkeypatch.setattr(
        module, "_write_completed_run_artifacts", fail_completed_artifacts
    )
    result = module.run_acceptance(
        repo_root=repo_root,
        artifact_root=artifact_root,
        run_id=f"20260830T130000Z-{safety_source}-{failure_kind}",
        generated_at="2026-08-30T13:00:00Z",
        parent_env={},
        executor=ArtifactFailureExecutor(process),
        expected_head=stable.git_head,
        specs=(spec,),
        version_validator=lambda _root: True,
        lovable_complete_or_waived=False,
    )

    assert result.exit_code == 3
    assert result.decision.outcome is module.DecisionOutcome.SAFETY_NO_GO
    assert expected_primary in result.decision.reasons
    assert artifact_reason in result.decision.reasons
    assert result.report_record is None
    assert not (artifact_root / "report.json").exists()
    assert not (artifact_root / "report.md").exists()


@pytest.mark.parametrize(
    ("failure", "expected_reason"),
    (
        pytest.param(OSError("synthetic write failure"), "ARTIFACT_WRITE_FAILED", id="write"),
        pytest.param(
            "integrity", "REPORT_INTEGRITY_FAILURE", id="integrity"
        ),
    ),
)
def test_completed_artifact_failure_without_safety_remains_technical(
    tmp_path, monkeypatch, failure, expected_reason
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    stable = FakeRunOneResources()
    artifact_root = tmp_path / "artifacts" / "acceptance" / "technical-artifact"
    spec = module.CommandSpec(
        command_id="shared_node",
        argv=("/usr/bin/true",),
        timeout_seconds=3,
        conftest_mode=module.ConftestMode.PROJECT,
        evidence_format=module.EvidenceFormat.TAP,
    )
    executor = ScriptedProcessExecutor(
        FakeProcess([(_unit7_passing_tap("synthetic-pass"), b"", 0)], [False]),
        snapshots=[stable] * 10,
    )

    def fail_completed_artifacts(**_kwargs):
        target = _kwargs["artifact_root"]
        (target / "report.json").write_bytes(b"untrusted-partial-json")
        (target / "report.md").write_bytes(b"untrusted-partial-markdown")
        if failure == "integrity":
            raise module.CliMisuseError("synthetic integrity failure")
        raise failure

    monkeypatch.setattr(
        module, "_write_completed_run_artifacts", fail_completed_artifacts
    )
    result = module.run_acceptance(
        repo_root=Path(__file__).resolve().parents[1],
        artifact_root=artifact_root,
        run_id="20260830T131000Z-technical-artifact",
        generated_at="2026-08-30T13:10:00Z",
        parent_env={},
        executor=executor,
        expected_head=stable.git_head,
        specs=(spec,),
        version_validator=lambda _root: True,
        lovable_complete_or_waived=False,
    )

    assert result.exit_code == 1
    assert result.decision.outcome is module.DecisionOutcome.TECHNICAL_NO_GO
    assert result.decision.reasons == (expected_reason,)
    assert result.report_record is None
    assert not (artifact_root / "report.json").exists()
    assert not (artifact_root / "report.md").exists()


def test_unit7_run_moves_junit_into_the_ordered_command_artifact_tree(tmp_path):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    repo_root = Path(__file__).resolve().parents[1]
    artifact_root = tmp_path / "artifacts" / "acceptance" / "junit-run"
    evidence_path = artifact_root / "runner.junit.xml"
    spec = module.CommandSpec(
        command_id="runner",
        argv=("/usr/bin/true",),
        timeout_seconds=3,
        conftest_mode=module.ConftestMode.PURE,
        evidence_format=module.EvidenceFormat.JUNIT,
        evidence_path=evidence_path,
    )
    stable = FakeRunOneResources()

    class JunitArtifactExecutor(ScriptedProcessExecutor):
        def start(self, spec, env):
            evidence_path.write_text(
                '<testsuite tests="1" failures="0" errors="0" skipped="0">'
                '<testcase name="synthetic-pass"/></testsuite>',
                encoding="utf-8",
            )
            return super().start(spec, env)

        def write_streams(self, command_id, stdout, stderr):
            self.events.append(f"write:{command_id}")
            module.PopenProcessExecutor(repo_root, artifact_root).write_streams(
                command_id, stdout, stderr
            )

    executor = JunitArtifactExecutor(
        FakeProcess([(b"pytest-pass", b"", 0)], [False]),
        snapshots=[stable] * 6,
    )
    result = module.run_acceptance(
        repo_root=repo_root,
        artifact_root=artifact_root,
        run_id="20260829T010204Z-task9",
        generated_at="2026-08-29T01:02:04Z",
        parent_env={},
        executor=executor,
        expected_head=stable.git_head,
        specs=(spec,),
        version_validator=lambda _root: True,
        lovable_complete_or_waived=False,
    )

    ordered = artifact_root / "commands" / "01-runner.junit.xml"
    assert result.command_results[0].classified_outcome is module.ClassifiedOutcome.SUCCESS
    assert ordered.is_file()
    assert not evidence_path.exists()
    report = __import__("json").loads((artifact_root / "report.json").read_bytes())
    assert report["commands"][0]["junit"] == {
        "path": "commands/01-runner.junit.xml",
        "sha256": __import__("hashlib").sha256(ordered.read_bytes()).hexdigest(),
        "size": len(ordered.read_bytes()),
    }


def _refresh_completed_report_files(module, artifact_root, record):
    record.pop("report_markdown", None)
    markdown = module.render_report_markdown(record).encode("utf-8")
    record["report_markdown"] = {
        "path": "report.md",
        "sha256": hashlib.sha256(markdown).hexdigest(),
        "size": len(markdown),
    }
    (artifact_root / "report.md").write_bytes(markdown)
    (artifact_root / "report.json").write_bytes(
        module.canonical_json_bytes(record)
    )


def _refresh_completed_limitations_forgery(module, artifact_root, record):
    """Rehash one hostile limitations mutation without using its validator."""

    record.pop("report_markdown", None)
    markdown_path = artifact_root / "report.md"
    lines = markdown_path.read_text(encoding="utf-8").splitlines()
    replacements = [
        index
        for index, line in enumerate(lines)
        if line.startswith("- Limitations: `")
    ]
    assert len(replacements) == 1
    lines[replacements[0]] = "- Limitations: `{}`".format(
        json.dumps(
            record["limitations"],
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    markdown = ("\n".join(lines) + "\n").encode("utf-8")
    record["report_markdown"] = {
        "path": "report.md",
        "sha256": hashlib.sha256(markdown).hexdigest(),
        "size": len(markdown),
    }
    markdown_path.write_bytes(markdown)
    (artifact_root / "report.json").write_bytes(
        module.canonical_json_bytes(record)
    )


def _current_repository_head():
    module = importlib.import_module("scripts.run_interaction_acceptance")
    repo_root = Path(__file__).resolve().parents[1]
    return module._read_trusted_repository_head(repo_root)


def _literal_git_directory(repo_root):
    repo_root.mkdir(parents=True, exist_ok=True)
    git_dir = repo_root / ".git"
    git_dir.mkdir()
    (git_dir / "objects").mkdir()
    (git_dir / "refs").mkdir()
    (git_dir / "config").write_text(
        "[core]\n\trepositoryformatversion = 0\n\tbare = false\n",
        encoding="ascii",
    )
    return git_dir


def _write_literal_git_metadata(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _junit_payload_for_suite(evidence):
    properties_by_node = {}
    for item in evidence.properties:
        properties_by_node.setdefault(item.node_id, []).append(item)
    cases = []
    for node_id in evidence.node_ids:
        properties = properties_by_node.get(node_id, ())
        if properties:
            property_xml = "".join(
                '<property name="{}" value="{}"/>'.format(
                    html.escape(item.name, quote=True),
                    html.escape(item.value, quote=True),
                )
                for item in properties
            )
            body = f"<properties>{property_xml}</properties>"
        else:
            body = ""
        cases.append(
            '<testcase name="{}">{}</testcase>'.format(
                html.escape(node_id, quote=True), body
            )
        )
    return (
        '<testsuite tests="{}" failures="0" errors="0" skipped="0">{}</testsuite>'.format(
            evidence.total, "".join(cases)
        )
    ).encode("utf-8")


def _completed_full_lovable_missing_artifact_tree(
    module, tmp_path, *, safety=False
):
    run_id = "20260830T160000000000Z-task9"
    artifact_root = tmp_path / run_id
    command_root = artifact_root / "commands"
    command_root.mkdir(parents=True)
    pending = _valid_pending_report_record(
        module, tmp_path, tested_head=_current_repository_head()
    )
    repo_root = Path(__file__).resolve().parents[1]
    specs = module.build_command_specs(repo_root, artifact_root)
    suites = {
        command_id: module._report_suite_evidence(value)
        for command_id, value in pending["suite_evidence"].items()
    }
    baseline = module._report_resource_snapshot(pending["resources"]["before"])
    stdout_payloads = {}
    stderr_payloads = {}
    junit_payloads = {}
    results = []
    for spec in specs:
        evidence = suites[spec.command_id]
        if spec.evidence_format is module.EvidenceFormat.JUNIT:
            stdout = b"pytest child output\n"
            stderr = (
                _signed_tripwire_sidecar(spec.command_id, ())
                if spec.conftest_mode is module.ConftestMode.PROJECT
                else b""
            )
            junit_payloads[spec.command_id] = _junit_payload_for_suite(evidence)
        else:
            stdout = _unit7_passing_tap_nodes(evidence.node_ids)
            stderr = b""
        stdout_payloads[spec.command_id] = stdout
        stderr_payloads[spec.command_id] = stderr
        results.append(
            module.CommandResult(
                subcommand=spec.command_id,
                child_started=True,
                child_exit=0,
                termination=module.Termination.EXITED,
                output_complete=True,
                residual_group_observed=False,
                cleanup_failures=(),
                classified_outcome=module.ClassifiedOutcome.SUCCESS,
                reason="SUCCESS",
                before_snapshot=baseline,
                after_snapshot=baseline,
                stdout=stdout,
                stderr=stderr,
                duration_seconds=1.25,
            )
        )

    final_snapshot = baseline
    if safety:
        final_snapshot = FakeRunOneResources(
            git_head=baseline.git_head, token="full-run-safety-drift"
        )
        results[-1] = replace(
            results[-1],
            classified_outcome=module.ClassifiedOutcome.SAFETY_FAILURE,
            reason="RESOURCE_DRIFT",
            after_snapshot=final_snapshot,
        )
    results = tuple(results)
    internal = module._run_internal_evidence(
        command_results=results,
        all_evidence=suites,
        baseline=baseline,
        final_snapshot=final_snapshot,
        version_exact=True,
    )
    manifest_commands = {row.command_id for row in module.SELECTOR_MANIFEST}
    gates = module.evaluate_gates(
        results,
        final_snapshot,
        module.EvidenceMap(
            suites={
                command_id: evidence
                for command_id, evidence in suites.items()
                if command_id in manifest_commands
            },
            internal=internal,
        ),
    )
    resources_unchanged = bool(
        not safety
        and all(
            result.before_snapshot == baseline
            and result.after_snapshot == baseline
            for result in results
        )
    )
    decision = module.decide_release(
        module.DecisionInputs(
            command_results=results,
            gate_results=gates,
            resources_unchanged=resources_unchanged,
            tripwires_clean=True,
            contrast_passed=True,
            incident_decisions=None,
            lovable_complete_or_waived=False,
        )
    )
    record = module.build_report_record(
        run_id=run_id,
        generated_at="2026-08-30T16:00:00Z",
        tested_head=baseline.git_head,
        decision=decision,
        command_results=results,
        command_specs=specs,
        gate_results=gates,
        lovable_status="MISSING",
        external_decision=None,
        baseline_snapshot=baseline,
        final_snapshot=final_snapshot,
        junit_payloads=junit_payloads,
        suite_evidence=suites,
        internal_evidence=internal,
    )
    for command in record["commands"]:
        command_id = command["subcommand"]
        (artifact_root / command["stdout"]["path"]).write_bytes(
            stdout_payloads[command_id]
        )
        (artifact_root / command["stderr"]["path"]).write_bytes(
            stderr_payloads[command_id]
        )
        if command["junit"] is not None:
            (artifact_root / command["junit"]["path"]).write_bytes(
                junit_payloads[command_id]
            )
    resource_artifacts = {}
    for name in ("before", "after"):
        payload = module.canonical_json_bytes(record["resources"][name])
        relative_path = f"resources.{name}.json"
        (artifact_root / relative_path).write_bytes(payload)
        resource_artifacts[name] = {
            "path": relative_path,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size": len(payload),
        }
    record["resource_artifacts"] = resource_artifacts
    _refresh_completed_report_files(module, artifact_root, record)
    control = tmp_path / ("control-safety.md" if safety else "control-technical.md")
    assert module.render_completed_report(
        artifact_root / "report.json", control
    ) == control
    return artifact_root, record


def _rewrite_completed_command_artifact(
    module, artifact_root, record, command_index, field, payload
):
    descriptor = record["commands"][command_index][field]
    path = artifact_root / descriptor["path"]
    path.write_bytes(payload)
    descriptor["sha256"] = hashlib.sha256(payload).hexdigest()
    descriptor["size"] = len(payload)


def _omit_completed_command_suite(artifact_root, record, command_index):
    command = record["commands"][command_index]
    record["suite_evidence"].pop(command["subcommand"])
    if command["junit"] is not None:
        (artifact_root / command["junit"]["path"]).unlink()
        command["junit"] = None
    command["counts"] = {
        "cancelled": None,
        "errors": None,
        "failures": None,
        "passed": None,
        "skipped": None,
        "todo": None,
        "total": None,
        "xfailed": None,
        "xpassed": None,
    }
    command["evidence_reason"] = "MISSING"
    command["evidence_sha256"] = None
    command["evidence_valid"] = False
    command["tripwire_events"] = []


def _recompute_completed_record_gates_and_decision(module, record):
    suites = {
        command_id: module._report_suite_evidence(value)
        for command_id, value in record["suite_evidence"].items()
    }
    results = tuple(
        module._report_command_result(command) for command in record["commands"]
    )
    manifest_commands = {row.command_id for row in module.SELECTOR_MANIFEST}
    gate_suites = {
        command_id: evidence
        for command_id, evidence in suites.items()
        if command_id in manifest_commands
    }
    baseline = module._report_resource_snapshot(record["resources"]["before"])
    final_snapshot = module._report_resource_snapshot(record["resources"]["after"])
    internal = module._run_internal_evidence(
        command_results=results,
        all_evidence=suites,
        baseline=baseline,
        final_snapshot=final_snapshot,
        version_exact=True,
    )
    record["internal_evidence"] = module._canonical_value(internal)
    record["focus_measurements"] = module._structured_suite_values(
        suites, "release_focus_all", "task9.focus_measurement"
    )
    record["database_action_evidence"] = module._structured_suite_values(
        suites, "release_db_action_all", "task9.db_action_evidence"
    )
    record["timeout_evidence"] = module._structured_suite_values(
        suites, "child_chat_timeout_all", "task9.timeout_evidence"
    )
    tripwire_status = module._tripwire_status(
        module._tripwire_event_ids(suites), suites.get("browser")
    )
    record["tripwires"] = {
        "provider_tts_socket_context_worker": tripwire_status
    }
    gates = module.evaluate_gates(
        results,
        final_snapshot,
        module.EvidenceMap(suites=gate_suites, internal=internal),
    )
    record["gates"] = module._gate_report_rows(gates, gate_suites, internal)
    resources_unchanged = bool(
        module._snapshots_are_unchanged(baseline, final_snapshot)
        and all(
            module._snapshots_are_unchanged(
                result.before_snapshot, result.after_snapshot
            )
            for result in results
        )
    )
    decision = module.decide_release(
        module.DecisionInputs(
            command_results=results,
            gate_results=gates,
            resources_unchanged=resources_unchanged,
            tripwires_clean=tripwire_status != "FAIL",
            contrast_passed=True,
            incident_decisions=None,
            lovable_complete_or_waived=False,
        )
    )
    record["decision"] = {
        "final_go": False,
        "outcome": decision.outcome.value,
        "reasons": list(decision.reasons),
        "runner_process_exit": decision.exit_code,
    }


def _rename_completed_command_artifacts(artifact_root, command, order):
    command_id = command["subcommand"]
    for field, suffix in (
        ("stdout", "stdout.log"),
        ("stderr", "stderr.log"),
        ("junit", "junit.xml"),
    ):
        descriptor = command[field]
        if descriptor is None:
            continue
        old_path = artifact_root / descriptor["path"]
        new_relative = f"commands/{order:02d}-{command_id}.{suffix}"
        old_path.rename(artifact_root / new_relative)
        descriptor["path"] = new_relative


def _rewrite_recorded_pytest_junit_roots(record, alternate_root):
    alternate = Path(alternate_root).resolve()
    rewritten = 0
    for command in record["commands"]:
        argv = []
        for argument in command["argv"]:
            if argument.startswith("--junitxml="):
                original = Path(argument.removeprefix("--junitxml="))
                argument = f"--junitxml={alternate / original.name}"
                rewritten += 1
            argv.append(argument)
        command["argv"] = argv
    assert rewritten > 0


def _completed_full_with_verified_lovable_reference(module, tmp_path):
    artifact_root, record = _completed_full_lovable_missing_artifact_tree(
        module, tmp_path, safety=False
    )
    repo_root = tmp_path / "relocated-repository"
    relocated_root = repo_root / "artifacts" / "acceptance" / record["run_id"]
    relocated_root.parent.mkdir(parents=True)
    artifact_root.rename(relocated_root)
    _rewrite_recorded_pytest_junit_roots(record, relocated_root)
    reference = repo_root / "docs" / "lovable" / "prototype-reference.md"
    reference.parent.mkdir(parents=True)
    reference.write_text(
        "# Lovable teacher prototype reference\n\n"
        "视觉参考，不连接鸭鸭日记本后端\n\n"
        "- Review date: 2026-08-29\n"
        "- Share URL: https://task9-evidence.lovable.app/\n"
        f"- Source commit: {record['tested_head']}\n"
        "- Checklist result: GO\n"
        "- Open observations: Reviewed two-screen private visual prototype.\n",
        encoding="utf-8",
    )
    record["lovable"].update(
        {
            "completion_or_scope_waiver": True,
            "project_status": "PROVIDED_OR_WAIVED",
            "status": "PROVIDED_OR_WAIVED",
            "zero_credit_blocker": None,
        }
    )
    record["decision"] = {
        "final_go": False,
        "outcome": "TECHNICAL_PASS_HUMAN_DECISION_PENDING",
        "reasons": ["HUMAN_AUTHORITY_REQUIRED"],
        "runner_process_exit": 2,
    }
    _refresh_completed_report_files(module, relocated_root, record)
    return relocated_root, record, reference


def _completed_full_with_verified_figma_scope_waiver(module, tmp_path):
    artifact_root, record = _completed_full_lovable_missing_artifact_tree(
        module, tmp_path, safety=False
    )
    repo_root = tmp_path / "relocated-figma-repository"
    relocated_root = repo_root / "artifacts" / "acceptance" / record["run_id"]
    relocated_root.parent.mkdir(parents=True)
    artifact_root.rename(relocated_root)
    _rewrite_recorded_pytest_junit_roots(record, relocated_root)

    source_repo = Path(__file__).resolve().parents[1]
    reference = repo_root / "docs" / "figma" / "prototype-reference.md"
    reference.parent.mkdir(parents=True)
    reference.write_text(_valid_figma_scope_waiver_text(), encoding="utf-8")
    plans = repo_root / "docs" / "superpowers" / "plans"
    plans.mkdir(parents=True)
    for name in module.FIGMA_EVIDENCE_PLAN_SHA256:
        shutil.copyfile(source_repo / "docs" / "superpowers" / "plans" / name, plans / name)

    record["lovable"].update(
        {
            "completion_or_scope_waiver": True,
            "project_status": "PROVIDED_OR_WAIVED",
            "status": "PROVIDED_OR_WAIVED",
            "zero_credit_blocker": None,
        }
    )
    record["decision"] = {
        "final_go": False,
        "outcome": "TECHNICAL_PASS_HUMAN_DECISION_PENDING",
        "reasons": ["HUMAN_AUTHORITY_REQUIRED"],
        "runner_process_exit": 2,
    }
    _refresh_completed_report_files(module, relocated_root, record)
    return relocated_root, record, reference, plans


@pytest.mark.parametrize("mutation", ("reference", "plan"))
def test_completed_report_revalidates_verified_figma_scope_waiver(
    tmp_path, mutation
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    artifact_root, _record, reference, plans = (
        _completed_full_with_verified_figma_scope_waiver(module, tmp_path)
    )
    control = tmp_path / f"rendered-figma-waiver-{mutation}.md"

    assert module.render_completed_report(
        artifact_root / "report.json", control
    ) == control

    if mutation == "reference":
        reference.write_text(
            _valid_figma_scope_waiver_text().replace(
                "- Review result: ACCEPTED", "- Review result: PENDING"
            ),
            encoding="utf-8",
        )
    elif mutation == "plan":
        plan = plans / next(iter(module.FIGMA_EVIDENCE_PLAN_SHA256))
        plan.write_bytes(plan.read_bytes() + b"\n# tampered\n")
    else:
        raise AssertionError(mutation)

    rejected = tmp_path / f"rejected-mutated-figma-waiver-{mutation}.md"
    with pytest.raises(module.CliMisuseError, match="completed report"):
        module.render_completed_report(artifact_root / "report.json", rejected)
    assert not rejected.exists()


@pytest.mark.parametrize("outcome", ("technical", "safety"))
@pytest.mark.parametrize(
    "forged_decision",
    (
        pytest.param({"arbitrary": "owner-accepted"}, id="arbitrary-incomplete"),
        pytest.param(
            {
                "authority_verified": True,
                "author": "forged release owner",
                "claimed_role": "release_owner",
                "incident_decisions": {
                    incident_id: "ACCEPT"
                    for incident_id in (
                        "PIPELINE_T8_PROVIDER_20260823",
                        "CHILD_T9_REAL_LOG_20260827",
                        "TEACHER_T5_REAL_LOG_20260829",
                    )
                },
                "label": "VERIFIED_OWNER_ACCEPTANCE",
                "rationales": {
                    incident_id: "forged acceptance"
                    for incident_id in (
                        "PIPELINE_T8_PROVIDER_20260823",
                        "CHILD_T9_REAL_LOG_20260827",
                        "TEACHER_T5_REAL_LOG_20260829",
                    )
                },
                "sha256": "a" * 64,
                "timestamp": "2026-08-30T16:00:00Z",
            },
            id="fully-forged-owner-acceptance",
        ),
    ),
)
def test_completed_report_rejects_self_reported_external_authority(
    tmp_path, outcome, forged_decision
):
    """Removing the exact-null evidence boundary must fail this renderer test."""

    module = importlib.import_module("scripts.run_interaction_acceptance")
    artifact_root, record = _completed_full_lovable_missing_artifact_tree(
        module, tmp_path, safety=outcome == "safety"
    )
    assert record["external_decision"] is None
    record["external_decision"] = forged_decision
    _refresh_completed_report_files(module, artifact_root, record)

    with pytest.raises(module.CliMisuseError, match="completed report"):
        module.render_completed_report(
            artifact_root / "report.json",
            tmp_path / f"rejected-{outcome}-external-authority.md",
        )


@pytest.mark.parametrize("outcome", ("technical", "safety"))
def test_completed_report_accepts_frozen_null_external_decision(tmp_path, outcome):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    artifact_root, record = _completed_full_lovable_missing_artifact_tree(
        module, tmp_path, safety=outcome == "safety"
    )
    assert record["external_decision"] is None
    output = tmp_path / f"accepted-{outcome}-null-external-decision.md"

    assert module.render_completed_report(
        artifact_root / "report.json", output
    ) == output


@pytest.mark.parametrize("outcome", ("technical", "safety"))
@pytest.mark.parametrize(
    ("mutation", "forged_value"),
    (
        pytest.param(
            "run_id", "20260830T160001000000Z-task9", id="alternate-run-id"
        ),
        pytest.param("run_id", "not-a-run-id", id="malformed-run-id"),
        pytest.param("generated_at", "not-a-time", id="malformed-generated-at"),
        pytest.param(
            "generated_at",
            "2026-08-30T16:00:00+00:00",
            id="noncanonical-offset",
        ),
        pytest.param(
            "generated_at",
            "2026-08-30T16:00:00.000000Z",
            id="noncanonical-fraction",
        ),
        pytest.param(
            "generated_at", "2026-02-30T16:00:00Z", id="impossible-date"
        ),
        pytest.param(
            "generated_at", "2026-08-30T16:00:01Z", id="run-time-mismatch"
        ),
    ),
)
def test_completed_report_rejects_forged_run_provenance(
    tmp_path, outcome, mutation, forged_value
):
    """Removing root/time provenance validation must fail this renderer test."""

    module = importlib.import_module("scripts.run_interaction_acceptance")
    artifact_root, record = _completed_full_lovable_missing_artifact_tree(
        module, tmp_path, safety=outcome == "safety"
    )
    record[mutation] = forged_value
    _refresh_completed_report_files(module, artifact_root, record)

    with pytest.raises(module.CliMisuseError, match="completed report"):
        module.render_completed_report(
            artifact_root / "report.json",
            tmp_path / f"rejected-{outcome}-{mutation}.md",
        )


@pytest.mark.parametrize("outcome", ("technical", "safety"))
def test_completed_report_accepts_relocated_canonical_run_provenance(
    tmp_path, outcome
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    artifact_root, record = _completed_full_lovable_missing_artifact_tree(
        module, tmp_path, safety=outcome == "safety"
    )
    assert artifact_root.name == record["run_id"]
    assert record["generated_at"] == "2026-08-30T16:00:00Z"
    output = tmp_path / f"accepted-{outcome}-canonical-provenance.md"

    assert module.render_completed_report(
        artifact_root / "report.json", output
    ) == output


@pytest.mark.parametrize("outcome", ("technical", "safety"))
@pytest.mark.parametrize(
    "mutation",
    (
        "removed-blocker",
        "status-only",
        "project-status-only",
        "completion-only",
        "fully-forged-provided-or-waived",
    ),
)
def test_completed_report_rejects_unverified_lovable_state(
    tmp_path, outcome, mutation
):
    """Removing the exact missing-state boundary must fail this renderer test."""

    module = importlib.import_module("scripts.run_interaction_acceptance")
    artifact_root, record = _completed_full_lovable_missing_artifact_tree(
        module, tmp_path, safety=outcome == "safety"
    )
    lovable = record["lovable"]
    if mutation == "removed-blocker":
        lovable["zero_credit_blocker"] = None
    elif mutation == "status-only":
        lovable["status"] = "PROVIDED_OR_WAIVED"
    elif mutation == "project-status-only":
        lovable["project_status"] = "PROVIDED_OR_WAIVED"
    elif mutation == "completion-only":
        lovable["completion_or_scope_waiver"] = True
    elif mutation == "fully-forged-provided-or-waived":
        lovable.update(
            {
                "completion_or_scope_waiver": True,
                "project_status": "PROVIDED_OR_WAIVED",
                "status": "PROVIDED_OR_WAIVED",
                "zero_credit_blocker": None,
            }
        )
        if outcome == "technical":
            record["decision"] = {
                "final_go": False,
                "outcome": "TECHNICAL_PASS_HUMAN_DECISION_PENDING",
                "reasons": ["HUMAN_AUTHORITY_REQUIRED"],
                "runner_process_exit": 2,
            }
    else:
        raise AssertionError(mutation)
    _refresh_completed_report_files(module, artifact_root, record)

    with pytest.raises(module.CliMisuseError, match="completed report"):
        module.render_completed_report(
            artifact_root / "report.json",
            tmp_path / f"rejected-{outcome}-{mutation}.md",
        )


@pytest.mark.parametrize("outcome", ("technical", "safety"))
def test_completed_report_accepts_exact_missing_lovable_state(tmp_path, outcome):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    artifact_root, record = _completed_full_lovable_missing_artifact_tree(
        module, tmp_path, safety=outcome == "safety"
    )
    assert record["lovable"] == {
        "completion_or_scope_waiver": False,
        "connector_used": False,
        "project_status": "MISSING",
        "publish_performed": False,
        "source_uploaded": False,
        "status": "MISSING",
        "zero_credit_blocker": (
            "A blank or zero-credit project is not completion evidence."
        ),
    }
    output = tmp_path / f"accepted-{outcome}-missing-lovable.md"

    assert module.render_completed_report(
        artifact_root / "report.json", output
    ) == output


def test_completed_report_accepts_verified_regular_lovable_reference(tmp_path):
    """Rejecting a contract-valid regular reference must fail this positive test."""

    module = importlib.import_module("scripts.run_interaction_acceptance")
    artifact_root, record, reference = (
        _completed_full_with_verified_lovable_reference(module, tmp_path)
    )
    assert reference.is_file() and not reference.is_symlink()
    assert record["decision"]["outcome"] == (
        "TECHNICAL_PASS_HUMAN_DECISION_PENDING"
    )
    output = tmp_path / "accepted-verified-lovable-reference.md"

    assert module.render_completed_report(
        artifact_root / "report.json", output
    ) == output


@pytest.mark.parametrize("outcome", ("technical", "safety"))
@pytest.mark.parametrize(
    "mutation",
    (
        "zero",
        "negative",
        "string",
        "object",
        "boolean",
    ),
)
def test_completed_report_rejects_forged_review_state(
    tmp_path, outcome, mutation
):
    """Relaxing the exact pending-review state must fail this renderer test."""

    module = importlib.import_module("scripts.run_interaction_acceptance")
    artifact_root, record = _completed_full_lovable_missing_artifact_tree(
        module, tmp_path, safety=outcome == "safety"
    )
    reviews = record["reviews"]
    if mutation == "zero":
        reviews["p0"] = 0
    elif mutation == "negative":
        reviews["p1"] = -1
    elif mutation == "string":
        reviews["p2"] = "0"
    elif mutation == "object":
        reviews["p0"] = {"count": 0}
    elif mutation == "boolean":
        reviews["p1"] = False
    else:
        raise AssertionError(mutation)
    _refresh_completed_report_files(module, artifact_root, record)

    with pytest.raises(module.CliMisuseError, match="completed report"):
        module.render_completed_report(
            artifact_root / "report.json",
            tmp_path / f"rejected-{outcome}-{mutation}-review.md",
        )


@pytest.mark.parametrize("outcome", ("technical", "safety"))
def test_completed_report_accepts_exact_pending_review_state(tmp_path, outcome):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    artifact_root, record = _completed_full_lovable_missing_artifact_tree(
        module, tmp_path, safety=outcome == "safety"
    )
    assert record["reviews"] == {
        "p0": None,
        "p1": None,
        "p2": None,
        "status": "PENDING_INDEPENDENT_EVIDENCE_REVIEW",
    }
    output = tmp_path / f"accepted-{outcome}-pending-review.md"

    assert module.render_completed_report(
        artifact_root / "report.json", output
    ) == output


@pytest.mark.parametrize("outcome", ("technical", "safety"))
@pytest.mark.parametrize("mutation", ("missing", "extra", "completed-status"))
def test_completed_report_retains_exact_review_shape_guards(
    tmp_path, outcome, mutation
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    artifact_root, record = _completed_full_lovable_missing_artifact_tree(
        module, tmp_path, safety=outcome == "safety"
    )
    if mutation == "missing":
        record["reviews"].pop("p2")
    elif mutation == "extra":
        record["reviews"]["verdict"] = "GO"
    elif mutation == "completed-status":
        record["reviews"]["status"] = (
            "INDEPENDENT_EVIDENCE_REVIEW_COMPLETE"
        )
    else:
        raise AssertionError(mutation)
    (artifact_root / "report.json").write_bytes(
        module.canonical_json_bytes(record)
    )

    with pytest.raises(
        module.CliMisuseError, match="completed report review state is invalid"
    ):
        module.render_completed_report(
            artifact_root / "report.json",
            tmp_path / f"rejected-{outcome}-{mutation}-review-shape.md",
        )


@pytest.mark.parametrize("outcome", ("technical", "safety"))
def test_completed_report_rejects_coherent_alternate_junit_root_for_full_no_go(
    tmp_path, outcome
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    artifact_root, record = _completed_full_lovable_missing_artifact_tree(
        module, tmp_path, safety=outcome == "safety"
    )
    _rewrite_recorded_pytest_junit_roots(
        record, tmp_path / "coherent-alternate-artifact-root"
    )
    _refresh_completed_report_files(module, artifact_root, record)

    with pytest.raises(
        module.CliMisuseError,
        match="completed report execution contract is invalid",
    ):
        module.render_completed_report(
            artifact_root / "report.json",
            tmp_path / f"rejected-full-{outcome}-alternate-root.md",
        )


@pytest.mark.parametrize("outcome", ("technical", "safety"))
@pytest.mark.parametrize(
    "mutation",
    (
        "timeout",
        "argv",
        "order",
        "global_baseline",
        "project_conftest_key",
        "suite_completeness",
        "continued_after_failure",
    ),
)
def test_completed_report_contract_is_not_downgraded_by_final_no_go_reason(
    tmp_path, outcome, mutation
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    artifact_root, record = _completed_full_lovable_missing_artifact_tree(
        module, tmp_path, safety=outcome == "safety"
    )
    if mutation == "timeout":
        record["commands"][0]["timeout_seconds"] += 1
    elif mutation == "argv":
        record["commands"][0]["argv"][-1] = "tests/substituted_runner.py"
    elif mutation == "order":
        record["commands"][0], record["commands"][1] = (
            record["commands"][1],
            record["commands"][0],
        )
        for order, command in enumerate(record["commands"][:2], start=1):
            command["order"] = order
            _rename_completed_command_artifacts(artifact_root, command, order)
    elif mutation == "global_baseline":
        for name in ("before_snapshot", "after_snapshot"):
            record["commands"][0][name]["log"]["size"] += 1
    elif mutation == "project_conftest_key":
        browser_index = tuple(EXPECTED_TIMEOUTS).index("browser")
        record["commands"][browser_index]["conftest_mode"] = "noconftest"
        _rewrite_completed_command_artifact(
            module, artifact_root, record, browser_index, "stderr", b""
        )
    elif mutation == "suite_completeness":
        _omit_completed_command_suite(artifact_root, record, 0)
    elif mutation == "continued_after_failure":
        _omit_completed_command_suite(artifact_root, record, 0)
        command = record["commands"][0]
        command["child_exit"] = 7
        command["classified_outcome"] = "CHILD_NONZERO"
        command["reason"] = "CHILD_NONZERO"
        command["runner_process_exit"] = 7
        _recompute_completed_record_gates_and_decision(module, record)
    else:
        raise AssertionError(mutation)
    _refresh_completed_report_files(module, artifact_root, record)

    with pytest.raises(module.CliMisuseError, match="completed report"):
        module.render_completed_report(
            artifact_root / "report.json",
            tmp_path / f"rejected-{outcome}-{mutation}.md",
        )


def test_completed_report_accepts_exact_truthful_failure_prefix(tmp_path):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    run_id = "20260830T160100000000Z-task9"
    artifact_root = tmp_path / run_id
    command_root = artifact_root / "commands"
    command_root.mkdir(parents=True)
    repo_root = Path(__file__).resolve().parents[1]
    spec = module.build_command_specs(repo_root, artifact_root)[0]
    resources = FakeRunOneResources(
        git_head=_current_repository_head(), token="truthful-prefix"
    )
    result = module.CommandResult(
        subcommand=spec.command_id,
        child_started=True,
        child_exit=7,
        termination=module.Termination.EXITED,
        output_complete=True,
        residual_group_observed=False,
        cleanup_failures=(),
        classified_outcome=module.ClassifiedOutcome.CHILD_NONZERO,
        reason="CHILD_NONZERO",
        before_snapshot=resources,
        after_snapshot=resources,
        stdout=b"ordinary failure",
        stderr=b"",
        duration_seconds=0.25,
    )
    internal = module._run_internal_evidence(
        command_results=(result,),
        all_evidence={},
        baseline=resources,
        final_snapshot=resources,
        version_exact=True,
    )
    gates = module.evaluate_gates(
        (result,), resources, module.EvidenceMap(suites={}, internal=internal)
    )
    decision = module.decide_release(
        module.DecisionInputs(
            command_results=(result,),
            gate_results=gates,
            resources_unchanged=True,
            tripwires_clean=True,
            contrast_passed=True,
            incident_decisions=None,
            lovable_complete_or_waived=False,
        )
    )
    record = module.build_report_record(
        run_id=run_id,
        generated_at="2026-08-30T16:01:00Z",
        tested_head=resources.git_head,
        decision=decision,
        command_results=(result,),
        command_specs=(spec,),
        gate_results=gates,
        lovable_status="MISSING",
        external_decision=None,
        baseline_snapshot=resources,
        final_snapshot=resources,
        suite_evidence={},
        internal_evidence=internal,
    )
    (artifact_root / record["commands"][0]["stdout"]["path"]).write_bytes(
        result.stdout
    )
    (artifact_root / record["commands"][0]["stderr"]["path"]).write_bytes(
        result.stderr
    )
    resource_artifacts = {}
    for name in ("before", "after"):
        payload = module.canonical_json_bytes(record["resources"][name])
        relative_path = f"resources.{name}.json"
        (artifact_root / relative_path).write_bytes(payload)
        resource_artifacts[name] = {
            "path": relative_path,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size": len(payload),
        }
    record["resource_artifacts"] = resource_artifacts
    _refresh_completed_report_files(module, artifact_root, record)
    output = tmp_path / "truthful-prefix.md"

    assert module.render_completed_report(
        artifact_root / "report.json", output
    ) == output


def test_completed_report_accepts_truthful_transient_drift_restored_at_final_capture(
    tmp_path,
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    artifact_root, record = _completed_full_lovable_missing_artifact_tree(
        module, tmp_path, safety=True
    )
    record["resources"]["after"] = _json_clone_record(
        module, record["resources"]["before"]
    )
    after_payload = module.canonical_json_bytes(record["resources"]["after"])
    (artifact_root / "resources.after.json").write_bytes(after_payload)
    record["resource_artifacts"]["after"] = {
        "path": "resources.after.json",
        "sha256": hashlib.sha256(after_payload).hexdigest(),
        "size": len(after_payload),
    }
    _recompute_completed_record_gates_and_decision(module, record)
    _refresh_completed_report_files(module, artifact_root, record)
    output = tmp_path / "truthful-transient-drift.md"

    assert module.render_completed_report(
        artifact_root / "report.json", output
    ) == output


def _completed_partial_artifact_tree(module, tmp_path, *, safety=False):
    run_id = "20260830T090100000000Z-task9"
    artifact_root = tmp_path / run_id
    command_root = artifact_root / "commands"
    command_root.mkdir(parents=True)
    repo_root = Path(__file__).resolve().parents[1]
    spec = module.build_command_specs(repo_root, artifact_root)[0]
    resources = FakeRunOneResources(
        git_head=_current_repository_head(),
        token="partial-safety-baseline" if safety else "technical-stable"
    )
    final_resources = (
        FakeRunOneResources(
            git_head=resources.git_head, token="partial-safety-drift"
        )
        if safety
        else resources
    )
    stdout = b"completed before resource drift" if safety else b"ordinary failure"
    stderr = b""
    result = module.CommandResult(
        subcommand=spec.command_id,
        child_started=True,
        child_exit=0 if safety else 7,
        termination=module.Termination.EXITED,
        output_complete=True,
        residual_group_observed=False,
        cleanup_failures=(),
        classified_outcome=(
            module.ClassifiedOutcome.SAFETY_FAILURE
            if safety
            else module.ClassifiedOutcome.CHILD_NONZERO
        ),
        reason="RESOURCE_DRIFT" if safety else "CHILD_NONZERO",
        before_snapshot=resources,
        after_snapshot=final_resources,
        stdout=stdout,
        stderr=stderr,
        duration_seconds=0.25,
    )
    internal = module._run_internal_evidence(
        command_results=(result,),
        all_evidence={},
        baseline=resources,
        final_snapshot=final_resources,
        version_exact=True,
    )
    gates = module.evaluate_gates(
        (result,),
        final_resources,
        module.EvidenceMap(suites={}, internal=internal),
    )
    decision = module.decide_release(
        module.DecisionInputs(
            command_results=(result,),
            gate_results=gates,
            resources_unchanged=not safety,
            tripwires_clean=True,
            contrast_passed=True,
            incident_decisions=None,
            lovable_complete_or_waived=False,
        )
    )
    record = module.build_report_record(
        run_id=run_id,
        generated_at="2026-08-30T09:01:00Z",
        tested_head=resources.git_head,
        decision=decision,
        command_results=(result,),
        command_specs=(spec,),
        gate_results=gates,
        lovable_status="MISSING",
        external_decision=None,
        baseline_snapshot=resources,
        final_snapshot=final_resources,
        suite_evidence={},
        internal_evidence=internal,
    )
    command = record["commands"][0]
    assert command["stdout"]["sha256"] == hashlib.sha256(stdout).hexdigest()
    assert command["stderr"]["sha256"] == hashlib.sha256(stderr).hexdigest()
    (artifact_root / command["stdout"]["path"]).write_bytes(stdout)
    (artifact_root / command["stderr"]["path"]).write_bytes(stderr)
    resource_artifacts = {}
    for name in ("before", "after"):
        payload = module.canonical_json_bytes(record["resources"][name])
        relative_path = f"resources.{name}.json"
        (artifact_root / relative_path).write_bytes(payload)
        resource_artifacts[name] = {
            "path": relative_path,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size": len(payload),
        }
    record["resource_artifacts"] = resource_artifacts
    _refresh_completed_report_files(module, artifact_root, record)
    return artifact_root, record


def _coherently_rewrite_completed_tested_head(
    module, artifact_root, record, replacement_head
):
    record["tested_head"] = replacement_head
    for snapshot in _all_report_resource_snapshots(record):
        snapshot["git_head"] = replacement_head
    for name in ("before", "after"):
        relative_path = f"resources.{name}.json"
        payload = module.canonical_json_bytes(record["resources"][name])
        (artifact_root / relative_path).write_bytes(payload)
        record["resource_artifacts"][name] = {
            "path": relative_path,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size": len(payload),
        }
    _refresh_completed_report_files(module, artifact_root, record)


@pytest.mark.parametrize("outcome", ("technical", "safety"))
@pytest.mark.parametrize("shape", ("full", "partial"))
def test_completed_report_rejects_coherent_head_not_trusted_by_repository(
    tmp_path, outcome, shape
):
    """Removing the repository-HEAD trust anchor must fail this render test."""

    module = importlib.import_module("scripts.run_interaction_acceptance")
    if shape == "full":
        artifact_root, record = _completed_full_lovable_missing_artifact_tree(
            module, tmp_path, safety=outcome == "safety"
        )
    else:
        artifact_root, record = _completed_partial_artifact_tree(
            module, tmp_path, safety=outcome == "safety"
        )
    trusted_head = _current_repository_head()
    assert record["tested_head"] == trusted_head
    control = tmp_path / f"trusted-head-{shape}-{outcome}.md"
    assert module.render_completed_report(
        artifact_root / "report.json", control
    ) == control

    alternate_head = "0" * 40 if trusted_head != "0" * 40 else "1" * 40
    _coherently_rewrite_completed_tested_head(
        module, artifact_root, record, alternate_head
    )
    rejected = tmp_path / f"untrusted-head-{shape}-{outcome}.md"

    with pytest.raises(module.CliMisuseError, match="completed report"):
        module.render_completed_report(artifact_root / "report.json", rejected)
    assert not rejected.exists()


def test_trusted_repository_head_rejects_parent_repository_discovery(tmp_path):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    parent = tmp_path / "parent-repository"
    git_dir = _literal_git_directory(parent)
    _write_literal_git_metadata(git_dir / "HEAD", ("1" * 40 + "\n").encode())
    child = parent / "nested-without-dot-git"
    child.mkdir()

    with pytest.raises(module.CliMisuseError, match="repository HEAD"):
        module._read_trusted_repository_head(child)


def test_trusted_repository_head_accepts_literal_detached_head(tmp_path):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    repo_root = tmp_path / "detached-repository"
    git_dir = _literal_git_directory(repo_root)
    expected = "2" * 40
    _write_literal_git_metadata(git_dir / "HEAD", (expected + "\n").encode())

    assert module._read_trusted_repository_head(repo_root) == expected


def test_trusted_repository_head_accepts_literal_loose_symbolic_ref(tmp_path):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    repo_root = tmp_path / "loose-repository"
    git_dir = _literal_git_directory(repo_root)
    expected = "3" * 40
    _write_literal_git_metadata(git_dir / "HEAD", b"ref: refs/heads/main\n")
    _write_literal_git_metadata(
        git_dir / "refs" / "heads" / "main", (expected + "\n").encode()
    )

    assert module._read_trusted_repository_head(repo_root) == expected


def test_trusted_repository_head_accepts_literal_packed_ref_fallback(tmp_path):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    repo_root = tmp_path / "packed-repository"
    git_dir = _literal_git_directory(repo_root)
    expected = "4" * 40
    _write_literal_git_metadata(git_dir / "HEAD", b"ref: refs/heads/main\n")
    _write_literal_git_metadata(
        git_dir / "packed-refs",
        (
            "# pack-refs with: peeled fully-peeled sorted\n"
            f"{expected} refs/heads/main\n"
        ).encode(),
    )

    assert module._read_trusted_repository_head(repo_root) == expected


def test_trusted_repository_head_rejects_packed_refs_crlf(tmp_path):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    repo_root = tmp_path / "packed-crlf-repository"
    git_dir = _literal_git_directory(repo_root)
    expected = "a" * 40
    _write_literal_git_metadata(git_dir / "HEAD", b"ref: refs/heads/main\n")
    _write_literal_git_metadata(
        git_dir / "packed-refs",
        f"{expected} refs/heads/main\r\n".encode(),
    )

    with pytest.raises(module.CliMisuseError, match="repository HEAD"):
        module._read_trusted_repository_head(repo_root)


@pytest.mark.parametrize(
    "control",
    tuple(value for value in range(32) if value != 10) + (127,),
    ids=lambda value: {
        9: "tab",
        11: "vertical-tab",
        12: "form-feed",
        13: "carriage-return",
        28: "file-separator",
        29: "group-separator",
        30: "record-separator",
        31: "unit-separator",
        127: "delete",
    }.get(value, f"control-0x{value:02x}"),
)
def test_trusted_repository_head_rejects_packed_refs_ascii_control(
    tmp_path, control
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    repo_root = tmp_path / f"packed-control-{control:02x}-repository"
    git_dir = _literal_git_directory(repo_root)
    unrelated = "b" * 40
    expected = "c" * 40
    _write_literal_git_metadata(git_dir / "HEAD", b"ref: refs/heads/main\n")
    _write_literal_git_metadata(
        git_dir / "packed-refs",
        (
            f"{unrelated} refs/heads/unrelated".encode()
            + bytes((control,))
            + f"{expected} refs/heads/main\n".encode()
        ),
    )

    with pytest.raises(module.CliMisuseError, match="repository HEAD"):
        module._read_trusted_repository_head(repo_root)


def test_trusted_repository_head_accepts_canonical_header_and_peeled_tag(
    tmp_path,
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    repo_root = tmp_path / "packed-peeled-repository"
    git_dir = _literal_git_directory(repo_root)
    expected = "d" * 40
    tag = "e" * 40
    peeled = "f" * 40
    _write_literal_git_metadata(git_dir / "HEAD", b"ref: refs/heads/main\n")
    _write_literal_git_metadata(
        git_dir / "packed-refs",
        (
            "# pack-refs with: peeled fully-peeled sorted\n"
            f"{expected} refs/heads/main\n"
            f"{tag} refs/tags/v1.0\n"
            f"^{peeled}\n"
        ).encode(),
    )

    assert module._read_trusted_repository_head(repo_root) == expected


def test_trusted_repository_head_loose_ref_precedes_unparsed_invalid_packed_refs(
    tmp_path,
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    repo_root = tmp_path / "loose-precedence-repository"
    git_dir = _literal_git_directory(repo_root)
    expected = "1" * 40
    _write_literal_git_metadata(git_dir / "HEAD", b"ref: refs/heads/main\n")
    _write_literal_git_metadata(
        git_dir / "refs" / "heads" / "main", (expected + "\n").encode()
    )
    _write_literal_git_metadata(
        git_dir / "packed-refs", b"invalid and unrelated\r\n"
    )

    assert module._read_trusted_repository_head(repo_root) == expected


def _literal_worktree_repository(tmp_path, *, expected):
    common_root = tmp_path / "common-repository"
    common_dir = _literal_git_directory(common_root)
    git_dir = common_dir / "worktrees" / "candidate"
    git_dir.mkdir(parents=True)
    worktree = tmp_path / "candidate-worktree"
    worktree.mkdir()
    _write_literal_git_metadata(
        worktree / ".git", f"gitdir: {git_dir}\n".encode()
    )
    _write_literal_git_metadata(git_dir / "commondir", b"../..\n")
    _write_literal_git_metadata(
        git_dir / "gitdir", f"{worktree / '.git'}\n".encode()
    )
    _write_literal_git_metadata(git_dir / "HEAD", b"ref: refs/heads/main\n")
    _write_literal_git_metadata(
        common_dir / "refs" / "heads" / "main", (expected + "\n").encode()
    )
    return worktree, git_dir, common_dir


def test_trusted_repository_head_accepts_canonical_worktree_commondir(tmp_path):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    expected = "5" * 40
    worktree, _git_dir, _common_dir = _literal_worktree_repository(
        tmp_path, expected=expected
    )

    assert module._read_trusted_repository_head(worktree) == expected


def test_trusted_repository_head_accepts_bounded_multi_symbolic_ref(tmp_path):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    repo_root = tmp_path / "multi-symbolic-repository"
    git_dir = _literal_git_directory(repo_root)
    expected = "6" * 40
    _write_literal_git_metadata(git_dir / "HEAD", b"ref: refs/heads/first\n")
    _write_literal_git_metadata(
        git_dir / "refs" / "heads" / "first",
        b"ref: refs/heads/second\n",
    )
    _write_literal_git_metadata(
        git_dir / "refs" / "heads" / "second",
        b"ref: refs/heads/final\n",
    )
    _write_literal_git_metadata(
        git_dir / "refs" / "heads" / "final", (expected + "\n").encode()
    )

    assert module._read_trusted_repository_head(repo_root) == expected


@pytest.mark.parametrize(
    "attack",
    (
        "missing-root",
        "git-entry-symlink",
        "head-symlink",
        "head-directory",
        "head-malformed",
        "loose-symlink",
        "ref-cycle",
        "ref-escape",
        "ref-absolute",
        "symbolic-depth",
        "packed-malformed",
        "packed-duplicate",
        "packed-symlink",
        "commondir-symlink",
        "gitdir-ancestor-symlink",
    ),
)
def test_trusted_repository_head_rejects_unsafe_literal_metadata(
    tmp_path, attack
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    expected = "7" * 40
    repo_root = tmp_path / f"unsafe-{attack}"
    if attack == "missing-root":
        with pytest.raises(module.CliMisuseError, match="repository HEAD"):
            module._read_trusted_repository_head(repo_root)
        return

    git_dir = _literal_git_directory(repo_root)
    if attack == "git-entry-symlink":
        real_git = tmp_path / "symlinked-git-directory"
        git_dir.rename(real_git)
        git_dir.symlink_to(real_git, target_is_directory=True)
    elif attack == "head-symlink":
        target = tmp_path / "symlinked-head"
        target.write_bytes((expected + "\n").encode())
        (git_dir / "HEAD").symlink_to(target)
    elif attack == "head-directory":
        (git_dir / "HEAD").mkdir()
    elif attack == "head-malformed":
        _write_literal_git_metadata(git_dir / "HEAD", b"7" * 40)
    elif attack == "loose-symlink":
        _write_literal_git_metadata(git_dir / "HEAD", b"ref: refs/heads/main\n")
        target = tmp_path / "symlinked-loose-ref"
        target.write_bytes((expected + "\n").encode())
        loose = git_dir / "refs" / "heads" / "main"
        loose.parent.mkdir(parents=True)
        loose.symlink_to(target)
    elif attack == "ref-cycle":
        _write_literal_git_metadata(git_dir / "HEAD", b"ref: refs/heads/one\n")
        _write_literal_git_metadata(
            git_dir / "refs" / "heads" / "one", b"ref: refs/heads/two\n"
        )
        _write_literal_git_metadata(
            git_dir / "refs" / "heads" / "two", b"ref: refs/heads/one\n"
        )
    elif attack == "ref-escape":
        _write_literal_git_metadata(
            git_dir / "HEAD", b"ref: refs/heads/../../outside\n"
        )
    elif attack == "ref-absolute":
        _write_literal_git_metadata(git_dir / "HEAD", b"ref: /refs/heads/main\n")
    elif attack == "symbolic-depth":
        _write_literal_git_metadata(git_dir / "HEAD", b"ref: refs/heads/hop0\n")
        for index in range(9):
            _write_literal_git_metadata(
                git_dir / "refs" / "heads" / f"hop{index}",
                f"ref: refs/heads/hop{index + 1}\n".encode(),
            )
        _write_literal_git_metadata(
            git_dir / "refs" / "heads" / "hop9", (expected + "\n").encode()
        )
    elif attack == "packed-malformed":
        _write_literal_git_metadata(git_dir / "HEAD", b"ref: refs/heads/main\n")
        _write_literal_git_metadata(
            git_dir / "packed-refs",
            (f"malformed packed line\n{expected} refs/heads/main\n").encode(),
        )
    elif attack == "packed-duplicate":
        _write_literal_git_metadata(git_dir / "HEAD", b"ref: refs/heads/main\n")
        _write_literal_git_metadata(
            git_dir / "packed-refs",
            (
                f"{expected} refs/heads/main\n"
                f"{'8' * 40} refs/heads/main\n"
            ).encode(),
        )
    elif attack == "packed-symlink":
        _write_literal_git_metadata(git_dir / "HEAD", b"ref: refs/heads/main\n")
        target = tmp_path / "symlinked-packed-refs"
        target.write_bytes(f"{expected} refs/heads/main\n".encode())
        (git_dir / "packed-refs").symlink_to(target)
    elif attack == "commondir-symlink":
        repo_root, git_dir, _common_dir = _literal_worktree_repository(
            tmp_path / "worktree-case", expected=expected
        )
        commondir = git_dir / "commondir"
        commondir.unlink()
        target = tmp_path / "symlinked-commondir"
        target.write_bytes(b"../..\n")
        commondir.symlink_to(target)
    elif attack == "gitdir-ancestor-symlink":
        original_worktree, original_git_dir, _common_dir = (
            _literal_worktree_repository(
                tmp_path / "gitdir-alias-case", expected=expected
            )
        )
        alias = tmp_path / "gitdir-alias"
        alias.symlink_to(original_git_dir.parent, target_is_directory=True)
        (original_worktree / ".git").write_text(
            f"gitdir: {alias / original_git_dir.name}\n", encoding="ascii"
        )
        repo_root = original_worktree
    else:
        raise AssertionError(attack)

    with pytest.raises(module.CliMisuseError, match="repository HEAD"):
        module._read_trusted_repository_head(repo_root)


def test_trusted_repository_head_invokes_no_subprocess_or_git_capture(
    tmp_path, monkeypatch
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    repo_root = tmp_path / "no-subprocess-repository"
    git_dir = _literal_git_directory(repo_root)
    expected = "9" * 40
    _write_literal_git_metadata(git_dir / "HEAD", (expected + "\n").encode())

    def forbidden(*_args, **_kwargs):
        raise AssertionError("trusted repository HEAD must not invoke a subprocess")

    monkeypatch.setattr(module, "_git_capture", forbidden)
    monkeypatch.setattr(module.subprocess, "run", forbidden)

    assert module._read_trusted_repository_head(repo_root) == expected


def test_completed_render_uses_no_subprocess_for_trusted_head(
    tmp_path, monkeypatch
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    artifact_root, _record = _completed_partial_artifact_tree(module, tmp_path)
    output = tmp_path / "rendered-with-logical-head.md"

    def forbidden(*_args, **_kwargs):
        raise AssertionError("completed render must not invoke a subprocess")

    monkeypatch.setattr(module, "_git_capture", forbidden)
    monkeypatch.setattr(module.subprocess, "run", forbidden)

    assert module.render_completed_report(
        artifact_root / "report.json", output
    ) == output


def test_report_record_uses_exact_frozen_limitations(tmp_path):
    """Replacing the generator's frozen limitations must fail this record test."""

    module = importlib.import_module("scripts.run_interaction_acceptance")
    record = _valid_pending_report_record(module, tmp_path)

    assert record["limitations"] == list(EXPECTED_FROZEN_LIMITATIONS)


@pytest.mark.parametrize("outcome", ("technical", "safety", "pending"))
@pytest.mark.parametrize(
    "mutation", ("missing", "extra", "order", "substituted", "non-string")
)
def test_completed_report_rejects_nonexact_frozen_limitations(
    tmp_path, outcome, mutation
):
    """Removing exact limitations identity must fail this production render."""

    module = importlib.import_module("scripts.run_interaction_acceptance")
    if outcome == "pending":
        artifact_root, record, _reference = (
            _completed_full_with_verified_lovable_reference(module, tmp_path)
        )
    else:
        artifact_root, record = _completed_full_lovable_missing_artifact_tree(
            module, tmp_path, safety=outcome == "safety"
        )
    record["limitations"] = list(EXPECTED_FROZEN_LIMITATIONS)
    _refresh_completed_report_files(module, artifact_root, record)
    control = tmp_path / f"exact-limitations-{outcome}-{mutation}.md"
    assert module.render_completed_report(
        artifact_root / "report.json", control
    ) == control

    if mutation == "missing":
        record["limitations"].pop()
    elif mutation == "extra":
        record["limitations"].append("Caller-added limitation.")
    elif mutation == "order":
        record["limitations"][0], record["limitations"][1] = (
            record["limitations"][1],
            record["limitations"][0],
        )
    elif mutation == "substituted":
        record["limitations"][0] = "The runner authorizes release GO."
    elif mutation == "non-string":
        record["limitations"][0] = {"claim": "caller-owned"}
    else:
        raise AssertionError(mutation)
    _refresh_completed_limitations_forgery(module, artifact_root, record)
    rejected = tmp_path / f"nonexact-limitations-{outcome}-{mutation}.md"

    with pytest.raises(module.CliMisuseError, match="completed report"):
        module.render_completed_report(artifact_root / "report.json", rejected)
    assert not rejected.exists()


def _noncanonical_completed_source(artifact_root, alias_kind):
    source = artifact_root / "report.json"
    if alias_kind == "dotdot":
        hop = artifact_root.parent / "hop"
        hop.mkdir()
        return hop / ".." / artifact_root.name / source.name
    if alias_kind == "ancestor-symlink":
        alias = artifact_root.parent / "alias"
        alias.symlink_to(artifact_root.parent, target_is_directory=True)
        return alias / artifact_root.name / source.name
    raise AssertionError(alias_kind)


@pytest.mark.parametrize("outcome", ("technical", "safety"))
@pytest.mark.parametrize("shape", ("full", "partial"))
@pytest.mark.parametrize("alias_kind", ("dotdot", "ancestor-symlink"))
def test_completed_report_rejects_noncanonical_source_alias(
    tmp_path, outcome, shape, alias_kind
):
    """Resolving an untrusted source spelling before validation must fail here."""

    module = importlib.import_module("scripts.run_interaction_acceptance")
    if shape == "full":
        artifact_root, _record = _completed_full_lovable_missing_artifact_tree(
            module, tmp_path, safety=outcome == "safety"
        )
    else:
        artifact_root, _record = _completed_partial_artifact_tree(
            module, tmp_path, safety=outcome == "safety"
        )
        control = tmp_path / f"canonical-{outcome}-{shape}-{alias_kind}.md"
        assert module.render_completed_report(
            artifact_root / "report.json", control
        ) == control
    untrusted_source = _noncanonical_completed_source(artifact_root, alias_kind)
    output = tmp_path / f"rejected-{outcome}-{shape}-{alias_kind}.md"

    with pytest.raises(module.CliMisuseError, match="completed report"):
        module.render_completed_report(untrusted_source, output)
    assert not output.exists()


@pytest.mark.parametrize("spelling", ("relative", "dot", "redundant-separator"))
def test_completed_report_rejects_other_noncanonical_source_spelling(
    tmp_path, monkeypatch, spelling
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    artifact_root, _record = _completed_partial_artifact_tree(module, tmp_path)
    if spelling == "relative":
        monkeypatch.chdir(tmp_path)
        source = f"{artifact_root.name}/report.json"
    elif spelling == "dot":
        source = f"{artifact_root}/./report.json"
    elif spelling == "redundant-separator":
        source = f"{artifact_root}//report.json"
    else:
        raise AssertionError(spelling)

    with pytest.raises(module.CliMisuseError, match="completed report"):
        module.render_completed_report(source, tmp_path / f"rejected-{spelling}.md")


@pytest.mark.parametrize(
    "attack",
    (
        "source-identity",
        "output-symlink",
        "ancestor-symlink",
        "directory",
        "hardlink-to-source",
        "relative",
        "dot",
        "redundant-separator",
    ),
)
def test_completed_report_rejects_unsafe_output_path_without_writing(
    tmp_path, monkeypatch, attack
):
    """Removing canonical output identity checks must fail this render test."""

    module = importlib.import_module("scripts.run_interaction_acceptance")
    artifact_root, _record = _completed_partial_artifact_tree(module, tmp_path)
    source = artifact_root / "report.json"
    source_before = source.read_bytes()
    victim = None
    written_candidate = None
    if attack == "source-identity":
        output = source
    elif attack == "output-symlink":
        victim = tmp_path / "symlink-victim.md"
        victim.write_bytes(b"victim-must-stay")
        output = tmp_path / "output-symlink.md"
        output.symlink_to(victim)
    elif attack == "ancestor-symlink":
        real_parent = tmp_path / "real-output-parent"
        real_parent.mkdir()
        alias_parent = tmp_path / "output-parent-alias"
        alias_parent.symlink_to(real_parent, target_is_directory=True)
        output = alias_parent / "rendered.md"
        written_candidate = real_parent / "rendered.md"
    elif attack == "directory":
        output = tmp_path / "output-directory.md"
        output.mkdir()
    elif attack == "hardlink-to-source":
        output = tmp_path / "source-hardlink.md"
        os.link(source, output)
    elif attack == "relative":
        monkeypatch.chdir(tmp_path)
        output = "relative-output.md"
        written_candidate = tmp_path / output
    elif attack == "dot":
        output = f"{tmp_path}/./dot-output.md"
        written_candidate = tmp_path / "dot-output.md"
    elif attack == "redundant-separator":
        output = f"{tmp_path}//redundant-output.md"
        written_candidate = tmp_path / "redundant-output.md"
    else:
        raise AssertionError(attack)

    with pytest.raises(module.CliMisuseError, match="completed report output"):
        module.render_completed_report(source, output)

    assert source.read_bytes() == source_before
    if victim is not None:
        assert victim.read_bytes() == b"victim-must-stay"
    if written_candidate is not None:
        assert not written_candidate.exists()


@pytest.mark.parametrize("existing", (False, True))
def test_completed_report_accepts_canonical_output_path(tmp_path, existing):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    artifact_root, _record = _completed_partial_artifact_tree(module, tmp_path)
    source = artifact_root / "report.json"
    output = (tmp_path / f"canonical-output-{existing}.md").resolve()
    if existing:
        output.write_bytes(b"replace-one-regular-file")

    assert module.render_completed_report(source, output) == output
    assert output.read_bytes() == (artifact_root / "report.md").read_bytes()
    assert output.is_file() and not output.is_symlink()


def test_completed_report_keeps_duration_as_shape_only_telemetry(tmp_path):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    artifact_root, record = _completed_full_lovable_missing_artifact_tree(
        module, tmp_path
    )
    record["commands"][0]["duration_seconds"] = 987.654
    _refresh_completed_report_files(module, artifact_root, record)
    output = tmp_path / "accepted-duration-telemetry.md"

    assert module.render_completed_report(
        artifact_root / "report.json", output
    ) == output
    assert record["limitations"] == list(EXPECTED_FROZEN_LIMITATIONS)
    assert record["decision"]["outcome"] == "TECHNICAL_NO_GO"


def test_completed_report_distinguishes_pytest_stdout_from_tap_evidence(tmp_path):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    artifact_root, record = _completed_full_lovable_missing_artifact_tree(
        module, tmp_path
    )
    runner_index = tuple(EXPECTED_TIMEOUTS).index("runner")
    _rewrite_completed_command_artifact(
        module,
        artifact_root,
        record,
        runner_index,
        "stdout",
        b"999 passed in 0.01s\n",
    )
    _refresh_completed_report_files(module, artifact_root, record)
    diagnostic_output = tmp_path / "accepted-pytest-diagnostic-stdout.md"
    assert module.render_completed_report(
        artifact_root / "report.json", diagnostic_output
    ) == diagnostic_output

    tap_index = tuple(EXPECTED_TIMEOUTS).index("shared_node")
    _rewrite_completed_command_artifact(
        module,
        artifact_root,
        record,
        tap_index,
        "stdout",
        _unit7_passing_tap_nodes(("caller-forged-tap-node",)),
    )
    _refresh_completed_report_files(module, artifact_root, record)

    with pytest.raises(module.CliMisuseError, match="artifact"):
        module.render_completed_report(
            artifact_root / "report.json",
            tmp_path / "rejected-forged-tap-stdout.md",
        )


@pytest.mark.parametrize("source_kind", ("symlink", "directory"))
def test_completed_report_retains_terminal_source_type_guards(tmp_path, source_kind):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    artifact_root, _record = _completed_partial_artifact_tree(module, tmp_path)
    source = artifact_root / "report.json"
    payload = source.read_bytes()
    source.unlink()
    if source_kind == "symlink":
        target = artifact_root.parent / "report-target.json"
        target.write_bytes(payload)
        source.symlink_to(target)
    elif source_kind == "directory":
        source.mkdir()
    else:
        raise AssertionError(source_kind)

    with pytest.raises(module.CliMisuseError, match="completed report"):
        module.render_completed_report(source, tmp_path / f"rejected-{source_kind}.md")


def _relocated_completed_tree_for_cli(module, tmp_path):
    fixture_root = tmp_path / "fixture"
    fixture_root.mkdir()
    artifact_root, record = _completed_partial_artifact_tree(
        module, fixture_root
    )
    repo_root = tmp_path / "cli-repository"
    relocated_root = (
        repo_root / "artifacts" / "acceptance" / record["run_id"]
    )
    relocated_root.parent.mkdir(parents=True)
    artifact_root.rename(relocated_root)
    _rewrite_recorded_pytest_junit_roots(record, relocated_root)
    _refresh_completed_report_files(module, relocated_root, record)
    (repo_root / "docs").mkdir()
    return repo_root, relocated_root


def test_render_report_cli_accepts_one_canonical_absolute_source(tmp_path):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    repo_root, artifact_root = _relocated_completed_tree_for_cli(module, tmp_path)

    assert module.render_report_from_cli(
        repo_root, str(artifact_root / "report.json")
    ) == 0


@pytest.mark.parametrize(
    "alias_kind", ("relative", "dotdot", "ancestor-symlink")
)
def test_render_report_cli_preserves_and_rejects_noncanonical_source_alias(
    tmp_path, alias_kind
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    repo_root, artifact_root = _relocated_completed_tree_for_cli(module, tmp_path)
    acceptance_root = artifact_root.parent
    if alias_kind == "relative":
        source_argument = (
            f"artifacts/acceptance/{artifact_root.name}/report.json"
        )
    elif alias_kind == "dotdot":
        hop = acceptance_root / "hop"
        hop.mkdir()
        source_argument = str(
            hop / ".." / artifact_root.name / "report.json"
        )
    elif alias_kind == "ancestor-symlink":
        alias = acceptance_root / "alias"
        alias.symlink_to(acceptance_root, target_is_directory=True)
        source_argument = str(alias / artifact_root.name / "report.json")
    else:
        raise AssertionError(alias_kind)

    assert module.render_report_from_cli(repo_root, source_argument) != 0


@pytest.mark.parametrize("outcome", ("technical", "safety"))
def test_completed_report_rejects_coherent_alternate_junit_root_for_failure_prefix(
    tmp_path, outcome
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    artifact_root, record = _completed_partial_artifact_tree(
        module, tmp_path, safety=outcome == "safety"
    )
    control = tmp_path / f"accepted-prefix-{outcome}.md"
    assert module.render_completed_report(
        artifact_root / "report.json", control
    ) == control

    _rewrite_recorded_pytest_junit_roots(
        record, tmp_path / "coherent-alternate-prefix-root"
    )
    _refresh_completed_report_files(module, artifact_root, record)

    with pytest.raises(
        module.CliMisuseError,
        match="completed report execution contract is invalid",
    ):
        module.render_completed_report(
            artifact_root / "report.json",
            tmp_path / f"rejected-prefix-{outcome}-alternate-root.md",
        )


def _completed_suite_artifact_tree(
    module,
    tmp_path,
    *,
    command_id,
    evidence_format,
    evidence_payload,
    stderr=b"",
    project=False,
):
    del project
    artifact_root, record = _completed_full_lovable_missing_artifact_tree(
        module, tmp_path, safety=False
    )
    command_index = tuple(EXPECTED_TIMEOUTS).index(command_id)
    command = record["commands"][command_index]
    spec = module.build_command_specs(
        Path(__file__).resolve().parents[1], artifact_root
    )[command_index]
    assert spec.command_id == command_id
    assert spec.evidence_format is evidence_format
    if evidence_format is module.EvidenceFormat.JUNIT:
        stdout = b"pytest child output\n"
        if spec.conftest_mode is module.ConftestMode.PROJECT and not stderr:
            stderr = _signed_tripwire_sidecar(command_id, ())
        evidence = module.parse_pytest_junit_bytes(
            evidence_payload,
            stderr_payload=stderr,
            command_id=command_id,
            require_tripwire_auth=(
                spec.conftest_mode is module.ConftestMode.PROJECT
            ),
        )
        _rewrite_completed_command_artifact(
            module,
            artifact_root,
            record,
            command_index,
            "junit",
            evidence_payload,
        )
    else:
        stdout = evidence_payload
        evidence = module.parse_node_tap(evidence_payload)
    safety = bool(evidence.tripwire_events)
    record["suite_evidence"][command_id] = module._canonical_value(evidence)
    command["counts"] = module._suite_counts(evidence)
    command["evidence_reason"] = evidence.reason
    command["evidence_sha256"] = module._parsed_evidence_sha256(evidence)
    command["evidence_valid"] = evidence.valid
    command["tripwire_events"] = list(
        module._tripwire_events_for_evidence(evidence)
    )
    _rewrite_completed_command_artifact(
        module, artifact_root, record, command_index, "stdout", stdout
    )
    _rewrite_completed_command_artifact(
        module, artifact_root, record, command_index, "stderr", stderr
    )

    if evidence_format is module.EvidenceFormat.JUNIT:
        for later in record["commands"][command_index + 1 :]:
            for field in ("stdout", "stderr", "junit"):
                descriptor = later[field]
                if descriptor is not None:
                    (artifact_root / descriptor["path"]).unlink()
            record["suite_evidence"].pop(later["subcommand"])
        record["commands"] = record["commands"][: command_index + 1]
        command["child_exit"] = 1
        command["classified_outcome"] = (
            "SAFETY_FAILURE" if safety else "CHILD_NONZERO"
        )
        command["reason"] = "TRIPWIRE_FAILURE" if safety else "CHILD_NONZERO"
        command["runner_process_exit"] = 3 if safety else 1

    _recompute_completed_record_gates_and_decision(module, record)
    _refresh_completed_report_files(module, artifact_root, record)
    control = tmp_path / f"control-suite-{command_id}.md"
    assert module.render_completed_report(
        artifact_root / "report.json", control
    ) == control
    return artifact_root, record


def _rehash_completed_command_artifact(
    module, artifact_root, record, command_id, field, payload
):
    command = next(
        item for item in record["commands"] if item["subcommand"] == command_id
    )
    descriptor = command[field]
    path = artifact_root / descriptor["path"]
    path.write_bytes(payload)
    descriptor["sha256"] = hashlib.sha256(payload).hexdigest()
    descriptor["size"] = len(payload)
    _refresh_completed_report_files(module, artifact_root, record)


def _junit_two_node_payload(*, property_value='{"boundary_ms":10000}'):
    encoded_property = html.escape(property_value, quote=True)
    return (
        '<testsuite tests="2" failures="0" errors="0" skipped="0">'
        '<testcase name="node-a"><properties>'
        '<property name="task9.timeout_evidence" '
        f'value="{encoded_property}"/>'
        '</properties></testcase><testcase name="node-b"/></testsuite>'
    ).encode("utf-8")


@pytest.mark.parametrize(
    "mutation",
    (
        "zero",
        "substituted",
        "missing",
        "duplicate",
        "skip",
        "xfail",
        "xpass",
        "property",
    ),
)
def test_completed_report_binds_full_junit_suite_evidence(
    tmp_path, mutation
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    original = _junit_two_node_payload()
    artifact_root, record = _completed_suite_artifact_tree(
        module,
        tmp_path,
        command_id="backend",
        evidence_format=module.EvidenceFormat.JUNIT,
        evidence_payload=original,
    )
    property_node = (
        '<properties><property name="task9.timeout_evidence" '
        'value="{&quot;boundary_ms&quot;:10000}"/></properties>'
    )
    mutations = {
        "zero": b'<testsuite tests="0" failures="0" errors="0" skipped="0"/>',
        "substituted": _junit_two_node_payload().replace(b"node-b", b"node-x"),
        "missing": (
            '<testsuite tests="1" failures="0" errors="0" skipped="0">'
            f'<testcase name="node-a">{property_node}</testcase></testsuite>'
        ).encode("utf-8"),
        "duplicate": (
            '<testsuite tests="2" failures="0" errors="0" skipped="0">'
            f'<testcase name="node-a">{property_node}</testcase>'
            '<testcase name="node-a"/></testsuite>'
        ).encode("utf-8"),
        "skip": (
            '<testsuite tests="2" failures="0" errors="0" skipped="1">'
            f'<testcase name="node-a">{property_node}<skipped/></testcase>'
            '<testcase name="node-b"/></testsuite>'
        ).encode("utf-8"),
        "xfail": (
            '<testsuite tests="2" failures="0" errors="0" skipped="1">'
            f'<testcase name="node-a">{property_node}'
            '<skipped type="pytest.xfail"/></testcase>'
            '<testcase name="node-b"/></testsuite>'
        ).encode("utf-8"),
        "xpass": (
            '<testsuite tests="2" failures="1" errors="0" skipped="0">'
            f'<testcase name="node-a">{property_node}'
            '<failure type="pytest.xfail" message="[XPASS(strict)] synthetic"/>'
            '</testcase><testcase name="node-b"/></testsuite>'
        ).encode("utf-8"),
        "property": _junit_two_node_payload(
            property_value='{"boundary_ms":9999}'
        ),
    }
    _rehash_completed_command_artifact(
        module, artifact_root, record, "backend", "junit", mutations[mutation]
    )

    with pytest.raises(module.CliMisuseError, match="artifact"):
        module.render_completed_report(
            artifact_root / "report.json", tmp_path / f"junit-{mutation}.md"
        )


@pytest.mark.parametrize(
    "mutation",
    ("zero", "substituted", "missing", "skip", "todo", "changed_count"),
)
def test_completed_report_binds_full_tap_suite_evidence(tmp_path, mutation):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    original = _unit7_passing_tap_nodes(("node-a", "node-b"))
    artifact_root, record = _completed_suite_artifact_tree(
        module,
        tmp_path,
        command_id="shared_node",
        evidence_format=module.EvidenceFormat.TAP,
        evidence_payload=original,
    )
    mutations = {
        "zero": (
            "TAP version 13\n1..0\n# tests 0\n# pass 0\n# fail 0\n"
            "# cancelled 0\n# skipped 0\n# todo 0\n"
        ).encode(),
        "substituted": original.replace(b"node-b", b"node-x"),
        "missing": _unit7_passing_tap_nodes(("node-a",)),
        "skip": (
            "TAP version 13\nok 1 - node-a # SKIP reason\nok 2 - node-b\n"
            "1..2\n# tests 2\n# pass 1\n# fail 0\n# cancelled 0\n"
            "# skipped 1\n# todo 0\n"
        ).encode(),
        "todo": (
            "TAP version 13\nnot ok 1 - node-a # TODO later\nok 2 - node-b\n"
            "1..2\n# tests 2\n# pass 1\n# fail 0\n# cancelled 0\n"
            "# skipped 0\n# todo 1\n"
        ).encode(),
        "changed_count": original.replace(b"# tests 2", b"# tests 3"),
    }
    _rehash_completed_command_artifact(
        module,
        artifact_root,
        record,
        "shared_node",
        "stdout",
        mutations[mutation],
    )

    with pytest.raises(module.CliMisuseError, match="artifact"):
        module.render_completed_report(
            artifact_root / "report.json", tmp_path / f"tap-{mutation}.md"
        )


def test_completed_report_rejects_project_junit_substitution_with_valid_header(
    tmp_path,
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    command_id = "backend"
    original = _junit_two_node_payload()
    stderr = _signed_tripwire_sidecar(command_id, ())
    artifact_root, record = _completed_suite_artifact_tree(
        module,
        tmp_path,
        command_id=command_id,
        evidence_format=module.EvidenceFormat.JUNIT,
        evidence_payload=original,
        stderr=stderr,
        project=True,
    )
    substituted = original.replace(b"node-b", b"ordinary-substitute")
    _rehash_completed_command_artifact(
        module, artifact_root, record, "backend", "junit", substituted
    )

    with pytest.raises(module.CliMisuseError, match="artifact"):
        module.render_completed_report(
            artifact_root / "report.json", tmp_path / "project-substitute.md"
        )


def test_completed_report_keeps_valid_event_safety_with_adjacent_malformed_sidecar(
    tmp_path,
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    command_id = "backend"
    event = _tripwire_record(
        "external_ai",
        command_id=command_id,
        node_id="test_uncaught_breaker",
        phase="call",
        sequence=1,
    )
    stderr = _signed_tripwire_sidecar(
        command_id,
        (event,),
        extra_lines=(b"TASK9_AUTH_V1:EVENT:not-base64:not-a-signature",),
    )
    artifact_root, record = _completed_suite_artifact_tree(
        module,
        tmp_path,
        command_id=command_id,
        evidence_format=module.EvidenceFormat.JUNIT,
        evidence_payload=_authenticated_tripwire_junit("external_ai").encode(),
        stderr=stderr,
        project=True,
    )

    output = tmp_path / "valid-event-safety.md"
    assert record["decision"]["outcome"] == "SAFETY_NO_GO"
    assert record["suite_evidence"][command_id]["reason"] == "TRIPWIRE_AUTH_INVALID"
    assert module.render_completed_report(
        artifact_root / "report.json", output
    ) == output


@pytest.mark.parametrize("evidence_format", ("junit", "tap"))
def test_completed_report_accepts_one_valid_full_suite_artifact(
    tmp_path, evidence_format
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    is_junit = evidence_format == "junit"
    artifact_root, _record = _completed_suite_artifact_tree(
        module,
        tmp_path,
        command_id="backend" if is_junit else "shared_node",
        evidence_format=(
            module.EvidenceFormat.JUNIT if is_junit else module.EvidenceFormat.TAP
        ),
        evidence_payload=(
            _junit_two_node_payload()
            if is_junit
            else _unit7_passing_tap_nodes(("node-a", "node-b"))
        ),
    )

    output = tmp_path / f"valid-{evidence_format}.md"
    assert module.render_completed_report(
        artifact_root / "report.json", output
    ) == output


@pytest.mark.parametrize("evidence_format", ("junit", "tap"))
def test_completed_report_parses_each_verified_evidence_file_once(
    tmp_path, monkeypatch, evidence_format
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    is_junit = evidence_format == "junit"
    artifact_root, record = _completed_suite_artifact_tree(
        module,
        tmp_path,
        command_id="backend" if is_junit else "shared_node",
        evidence_format=(
            module.EvidenceFormat.JUNIT if is_junit else module.EvidenceFormat.TAP
        ),
        evidence_payload=(
            _junit_two_node_payload()
            if is_junit
            else _unit7_passing_tap_nodes(("node-a", "node-b"))
        ),
    )
    descriptor = record["commands"][0]["junit" if is_junit else "stdout"]
    evidence_path = artifact_root / descriptor["path"]
    original_read_bytes = Path.read_bytes
    evidence_reads = 0

    def read_bytes_once(path):
        nonlocal evidence_reads
        if path == evidence_path:
            evidence_reads += 1
            if evidence_reads > 1:
                raise AssertionError("verified evidence path was reopened")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", read_bytes_once)
    output = tmp_path / f"read-once-{evidence_format}.md"

    assert module.render_completed_report(
        artifact_root / "report.json", output
    ) == output
    assert evidence_reads == 1


def test_completed_report_verifies_one_real_exact_artifact_tree(tmp_path):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    artifact_root, _record = _completed_partial_artifact_tree(module, tmp_path)
    output = tmp_path / "tracked-report.md"

    assert module.render_completed_report(
        artifact_root / "report.json", output
    ) == output
    assert output.read_bytes() == (artifact_root / "report.md").read_bytes()


@pytest.mark.parametrize(
    "mutation",
    (
        "missing",
        "wrong_hash",
        "wrong_size",
        "wrong_type",
        "wrong_path",
        "traversal",
        "symlink",
        "extra",
    ),
)
def test_completed_report_rejects_untrusted_artifact_tree(tmp_path, mutation):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    artifact_root, record = _completed_partial_artifact_tree(module, tmp_path)
    command = record["commands"][0]
    stdout_path = artifact_root / command["stdout"]["path"]
    if mutation == "missing":
        stdout_path.unlink()
    elif mutation == "wrong_hash":
        stdout_path.write_bytes(b"ORDINARY FAILURE")
    elif mutation == "wrong_size":
        command["stdout"]["size"] += 1
        _refresh_completed_report_files(module, artifact_root, record)
    elif mutation == "wrong_type":
        stdout_path.unlink()
        stdout_path.mkdir()
    elif mutation == "wrong_path":
        payload = stdout_path.read_bytes()
        stdout_path.unlink()
        command["stdout"]["path"] = "commands/wrong.stdout.log"
        (artifact_root / command["stdout"]["path"]).write_bytes(payload)
        _refresh_completed_report_files(module, artifact_root, record)
    elif mutation == "traversal":
        payload = stdout_path.read_bytes()
        stdout_path.unlink()
        command["stdout"]["path"] = "../outside.stdout.log"
        (artifact_root.parent / "outside.stdout.log").write_bytes(payload)
        _refresh_completed_report_files(module, artifact_root, record)
    elif mutation == "symlink":
        payload = stdout_path.read_bytes()
        stdout_path.unlink()
        target = artifact_root.parent / "symlink-target.log"
        target.write_bytes(payload)
        stdout_path.symlink_to(target)
    elif mutation == "extra":
        (artifact_root / "commands" / "extra.log").write_bytes(b"extra")
    else:
        raise AssertionError(mutation)

    with pytest.raises(
        module.CliMisuseError, match="artifact|execution contract"
    ):
        module.render_completed_report(
            artifact_root / "report.json", tmp_path / f"{mutation}.md"
        )


def test_completed_report_rejects_tripwire_classification_from_hash_mismatched_log(
    tmp_path,
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    artifact_root, record = _completed_partial_artifact_tree(module, tmp_path)
    stdout_path = artifact_root / record["commands"][0]["stdout"]["path"]
    stdout_path.write_bytes(b"AssertionError: TEST_TRIPWIRE:external_ai\n")

    with pytest.raises(module.CliMisuseError, match="artifact"):
        module.render_completed_report(
            artifact_root / "report.json", tmp_path / "must-not-render.md"
        )


def test_unit7_render_report_is_one_way_canonical_and_rejects_noncanonical_json(
    tmp_path,
):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    decision = module.DecisionResult(
        module.DecisionOutcome.TECHNICAL_PASS_HUMAN_DECISION_PENDING,
        2,
        ("HUMAN_AUTHORITY_REQUIRED",),
    )
    record = module.build_report_record(
        run_id="20260829T010203Z-task9",
        generated_at="2026-08-29T01:02:03Z",
        tested_head=FakeRunOneResources().git_head,
        decision=decision,
        command_results=(),
        command_specs=(),
        gate_results=_passing_gate_results(module),
        lovable_status="PROVIDED_OR_WAIVED",
        external_decision=None,
        baseline_snapshot=FakeResources(),
        final_snapshot=FakeResources(),
    )
    with pytest.raises(module.CliMisuseError):
        module.render_report_markdown(record)

    artifact_root, valid_record = _completed_partial_artifact_tree(
        module, tmp_path
    )
    source = artifact_root / "report.json"
    markdown = (artifact_root / "report.md").read_bytes()
    output = tmp_path / "tracked-report.md"

    assert module.render_completed_report(source, output) == output
    assert output.read_bytes() == markdown

    noncanonical = tmp_path / "noncanonical-source" / "report.json"
    noncanonical.parent.mkdir()
    noncanonical.write_text(
        __import__("json").dumps(valid_record, indent=2), encoding="utf-8"
    )
    with pytest.raises(module.CliMisuseError, match="canonical"):
        module.render_completed_report(noncanonical, tmp_path / "must-not-exist.md")

    for field in (
        "runtime_versions",
        "tripwires",
        "focus_measurements",
        "database_action_evidence",
        "timeout_evidence",
        "reviews",
        "pending_status",
    ):
        malformed_record = __import__("json").loads(
            module.canonical_json_bytes(valid_record)
        )
        malformed_record.pop(field)
        malformed = tmp_path / f"missing-{field}" / "report.json"
        malformed.parent.mkdir()
        malformed.write_bytes(module.canonical_json_bytes(malformed_record))
        with pytest.raises(module.CliMisuseError, match="schema"):
            module.render_completed_report(
                malformed, tmp_path / f"missing-{field}.md"
            )


def test_unit7_main_dispatches_only_exact_head_run_and_render_cli_shapes(monkeypatch):
    module = importlib.import_module("scripts.run_interaction_acceptance")
    calls = []

    class FakeFullRun:
        exit_code = 2
        run_id = "20260829T010203Z-task9"
        artifact_root = Path("/tmp/fake-acceptance-run")
        decision = module.DecisionResult(
            module.DecisionOutcome.TECHNICAL_PASS_HUMAN_DECISION_PENDING,
            2,
            ("HUMAN_AUTHORITY_REQUIRED",),
        )

    expected_head = "a" * 40

    def fake_run(repo_root, parent_env, candidate_head):
        calls.append(("run", repo_root, parent_env, candidate_head))
        return FakeFullRun()

    def fake_render(repo_root, source_argument):
        calls.append(("render", repo_root, source_argument))
        return 0

    monkeypatch.setattr(module, "run_full_acceptance", fake_run)
    monkeypatch.setattr(module, "render_report_from_cli", fake_render)

    assert module.main(("run", expected_head)) == 2
    assert module.main(("render-report", "artifacts/acceptance/fixed/report.json")) == 0
    assert [call[0] for call in calls] == ["run", "render"]
    assert calls[0][3] == expected_head
