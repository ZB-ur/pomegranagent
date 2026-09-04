from __future__ import annotations

import base64
import asyncio
from dataclasses import replace
from datetime import date, datetime, timezone
import hashlib
import importlib
import json
import io
import logging
import os
from pathlib import Path
import signal
import sqlite3
import stat
import subprocess
import struct
import sys
import types
from urllib.parse import quote
import zlib

import pytest


HEAD = "a" * 40
PYTHON = "/Users/lddmay/AiCoding/pomegranagent/.venv/bin/python"
STEP_PROVENANCE_KEYS = {
    "teacher_credential_setup_login": set(),
    "child_duck_avatar_management": {
        "child_avatar_id",
        "duck_avatar_id",
        "live_child_id",
        "live_duck_id",
    },
    "invalid_avatar_rejection": set(),
    "monthly_roster_conflict_retry": {
        "monthly_pairs",
        "monthly_roster_request_ids",
    },
    "child_conversation_real_provider_tts": {
        "chat_request_ids",
        "live_conversation_id",
        "local_terminal_request_id",
        "provider_chat_request_ids",
        "tts_evidence",
    },
    "conversation_completion_analysis": {"analysis_job_id"},
    "teacher_today_queues": set(),
    "review_edit_confirm": {"assessment_id"},
    "weekly_metrics_growth": {
        "growth_after",
        "growth_before",
        "weekly_metrics_after",
        "weekly_metrics_before",
        "weekly_week_start",
    },
    "advanced_search_pagination_deep_link": {
        "search_cursor",
        "search_deep_link",
        "search_page_one_ids",
        "search_page_two_ids",
        "search_request",
        "search_result_conversation_id",
    },
    "search_empty_state": set(),
    "logout_login_retained_state": set(),
}


def _native_audio_playback():
    return {
        "error": None,
        "events": ["playing", "ended"],
        "play_promise": "fulfilled",
        "speech_synthesis_fallback": False,
    }


def _module():
    return importlib.import_module("scripts.run_live_provider_uat")


def _repository(tmp_path: Path) -> Path:
    root = tmp_path / "repository"
    root.mkdir()
    (root / ".git").mkdir()
    return root


def test_live_harness_module_import_is_effect_free(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    before = tuple(tmp_path.iterdir())

    module = _module()

    assert module.__name__ == "scripts.run_live_provider_uat"
    assert tuple(tmp_path.iterdir()) == before


def test_cli_accepts_only_explicit_retained_runtime_handoff():
    module = _module()

    parsed = module.parse_args(
        [
            "--retain",
            "--print-runtime-json",
            "--expected-head",
            HEAD,
            "--allow-unrelated-dirty-path",
            "notes/release-observation.md",
        ]
    )

    assert parsed.retain is True
    assert parsed.print_runtime_json is True
    assert parsed.expected_head == HEAD
    assert parsed.allow_unrelated_dirty_path == ["notes/release-observation.md"]
    for invalid in (
        [],
        ["--retain"],
        ["--print-runtime-json"],
        ["--retain", "--print-runtime-json"],
        ["--retain", "--print-runtime-json", "--expected-head", "HEAD"],
        [
            "--retain",
            "--print-runtime-json",
            "--expected-head",
            HEAD,
            "--allow-unrelated-dirty-path",
            "app/backend/main.py",
        ],
        ["--retain", "--print-runtime-json", "--expected-head", HEAD, "extra"],
    ):
        with pytest.raises(SystemExit):
            module.parse_args(invalid)


def test_main_wires_default_adapters_without_starting_live_uat():
    module = _module()
    stdout = io.StringIO()
    stdin = io.StringIO('{"type":"finalize"}\n')
    calls = []

    def execute(**kwargs):
        calls.append(kwargs)
        return object()

    result = module.main(
        ["--retain", "--print-runtime-json", "--expected-head", HEAD],
        execute=execute,
        dotenv_reader=lambda _repository: {"DEEPSEEK_API_KEY": "fake"},
        environ={"PATH": "/synthetic/bin"},
        input_stream=stdin,
        output_stream=stdout,
        python_executable=PYTHON,
        business_today=lambda: date(2026, 9, 4),
    )

    assert result == 0
    assert len(calls) == 1
    assert calls[0]["repository"] == module.PROJECT_ROOT
    assert calls[0]["expected_head"] == HEAD
    assert calls[0]["allowed_unrelated_dirty_paths"] == ()
    assert calls[0]["dotenv_values"] == {"DEEPSEEK_API_KEY": "fake"}
    assert calls[0]["environ"] == {"PATH": "/synthetic/bin"}
    assert calls[0]["input_stream"] is stdin
    assert calls[0]["output_stream"] is stdout
    assert calls[0]["seed_runner"] is module.run_seed_process
    assert calls[0]["server_starter"] is module.start_live_server
    assert calls[0]["readiness_probe"] is module.probe_live_readiness
    assert calls[0]["server_finisher"] is module.finish_live_server


def test_reviewed_checkout_rejects_dirty_runtime_before_launch_and_preserves_explicit_unrelated_path(
    tmp_path,
):
    module = _module()
    unrelated = {
        "relative_path": "notes/release-observation.md",
        "porcelain_destination": None,
        "porcelain_record": 0,
        "porcelain_role": "path",
        "porcelain_status": "??",
        "file": {"kind": "regular", "sha256": "1" * 64},
        "directory": None,
    }
    snapshot = {
        "git_head": HEAD,
        "dirty_paths": [unrelated],
    }

    module.validate_reviewed_checkout(
        snapshot,
        expected_head=HEAD,
        allowed_unrelated_dirty_paths=("notes/release-observation.md",),
    )

    dirty_backend = {
        **snapshot,
        "dirty_paths": [
            {
                "relative_path": "app/backend/main.py",
                "porcelain_destination": None,
                "porcelain_record": 0,
                "porcelain_role": "path",
                "porcelain_status": " M",
                "file": {"kind": "regular", "sha256": "2" * 64},
                "directory": None,
            }
        ],
    }
    for unsafe_snapshot, expected, allowed in (
        (snapshot, "b" * 40, ("notes/release-observation.md",)),
        (snapshot, HEAD, ()),
        (dirty_backend, HEAD, ("app/backend/main.py",)),
    ):
        with pytest.raises(module.HarnessSafetyError, match="reviewed checkout"):
            module.validate_reviewed_checkout(
                unsafe_snapshot,
                expected_head=expected,
                allowed_unrelated_dirty_paths=allowed,
            )

    launches = []

    def capture_resources(_repository):
        return {
            "database": {},
            "dirty_paths": dirty_backend["dirty_paths"],
            "git_head": HEAD,
            "git_porcelain": {},
            "log": {},
            "media": {},
            "tts": {},
        }

    with pytest.raises(module.HarnessSafetyError, match="reviewed checkout"):
        module.execute_retained_uat(
            repository=_repository(tmp_path),
            expected_head=HEAD,
            allowed_unrelated_dirty_paths=(),
            environ={},
            dotenv_values={},
            input_stream=io.StringIO(),
            output_stream=io.StringIO(),
            python_executable=PYTHON,
            business_today=lambda: date(2026, 9, 4),
            capture_resources=capture_resources,
            seed_runner=lambda *_args, **_kwargs: launches.append("seed"),
            server_starter=lambda *_args, **_kwargs: launches.append("server"),
            readiness_probe=lambda _session: (),
            server_finisher=lambda _session: (),
        )
    assert launches == []
    assert not (tmp_path / "repository" / "artifacts").exists()


def test_reviewed_checkout_preserves_both_rename_paths_and_rejects_runtime_endpoint():
    module = _module()

    records = module._dirty_path_records(
        b"R  notes/release-observation.md\0app/backend/main.py\0"
    )
    paths = tuple(sorted(record[0] for record in records))

    assert paths == ("app/backend/main.py", "notes/release-observation.md")
    assert records == (
        (
            "app/backend/main.py",
            "R ",
            "original",
            0,
            "notes/release-observation.md",
        ),
        (
            "notes/release-observation.md",
            "R ",
            "current",
            0,
            "notes/release-observation.md",
        ),
    )
    with pytest.raises(module.HarnessSafetyError, match="runtime or UAT dirt"):
        module.validate_reviewed_checkout(
            {
                "git_head": HEAD,
                "dirty_paths": [
                    {
                        "relative_path": path,
                        "porcelain_role": role,
                        "porcelain_status": status,
                        "porcelain_record": record,
                        "porcelain_destination": destination,
                        "file": {"kind": "missing"},
                        "directory": None,
                    }
                    for path, status, role, record, destination in records
                ],
            },
            expected_head=HEAD,
            allowed_unrelated_dirty_paths=("notes/release-observation.md",),
        )


def test_dirty_porcelain_records_preserve_copy_and_deleted_missing_roles():
    module = _module()

    assert module._dirty_path_records(
        b"C  notes/copied.md\0notes/source.md\0 D notes/deleted.md\0"
    ) == (
        ("notes/copied.md", "C ", "current", 0, "notes/copied.md"),
        ("notes/deleted.md", " D", "path", 1, None),
        ("notes/source.md", "C ", "original", 0, "notes/copied.md"),
    )


def test_dirty_porcelain_preserves_one_source_copied_to_two_destinations():
    module = _module()

    assert module._dirty_path_records(
        b"C  notes/copy-a.md\0notes/source.md\0"
        b"C  notes/copy-b.md\0notes/source.md\0"
    ) == (
        ("notes/copy-a.md", "C ", "current", 0, "notes/copy-a.md"),
        ("notes/copy-b.md", "C ", "current", 1, "notes/copy-b.md"),
        ("notes/source.md", "C ", "original", 0, "notes/copy-a.md"),
        ("notes/source.md", "C ", "original", 1, "notes/copy-b.md"),
    )


def test_real_git_capture_types_rename_copy_and_deletion_endpoints(tmp_path):
    module = _module()
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(("git", "init", "-q"), cwd=repository, check=True)
    subprocess.run(
        ("git", "config", "user.email", "uat@example.invalid"),
        cwd=repository,
        check=True,
    )
    subprocess.run(
        ("git", "config", "user.name", "UAT Test"),
        cwd=repository,
        check=True,
    )
    subprocess.run(
        ("git", "config", "status.renames", "copies"),
        cwd=repository,
        check=True,
    )
    (repository / "rename-source.txt").write_text("rename source\n", encoding="utf-8")
    (repository / "copy-source.txt").write_text("copy source\n", encoding="utf-8")
    (repository / "deleted.txt").write_text("deleted\n", encoding="utf-8")
    subprocess.run(("git", "add", "."), cwd=repository, check=True)
    subprocess.run(("git", "commit", "-qm", "fixture"), cwd=repository, check=True)
    subprocess.run(
        ("git", "mv", "rename-source.txt", "renamed.txt"),
        cwd=repository,
        check=True,
    )
    (repository / "copied.txt").write_text("copy source\n", encoding="utf-8")
    (repository / "copy-source.txt").write_text(
        "copy source modified\n",
        encoding="utf-8",
    )
    (repository / "deleted.txt").unlink()
    subprocess.run(("git", "add", "-A"), cwd=repository, check=True)

    snapshot = module.capture_protected_resources(repository)
    evidence = {
        (item["relative_path"], item["porcelain_role"]): item
        for item in snapshot["dirty_paths"]
    }
    assert evidence[("renamed.txt", "current")]["porcelain_status"] == "R "
    assert evidence[("rename-source.txt", "original")]["file"] == {"kind": "missing"}
    assert evidence[("copied.txt", "current")]["porcelain_status"] == "C "
    assert evidence[("copy-source.txt", "original")]["file"]["kind"] == "regular"
    assert evidence[("copy-source.txt", "original")]["porcelain_destination"] == "copied.txt"
    assert evidence[("deleted.txt", "path")]["porcelain_status"] == "D "
    assert evidence[("deleted.txt", "path")]["file"] == {"kind": "missing"}


def test_run_plan_creation_is_exclusive_unique_and_retained(tmp_path):
    module = _module()
    root = _repository(tmp_path)
    fixed_now = datetime(2026, 9, 3, 12, 34, 56, 123456, tzinfo=timezone.utc)

    first = module.create_run_plan(
        root,
        HEAD,
        now=lambda: fixed_now,
        nonce=lambda: "0123456789ab",
    )
    marker = first.root / "retained.marker"
    marker.write_bytes(b"keep")
    second = module.create_run_plan(
        root,
        HEAD,
        now=lambda: fixed_now,
        nonce=lambda: "0123456789ab",
    )

    assert first.run_id == "20260903T123456123456Z-0123456789ab-aaaaaaaaaaaa"
    assert second.run_id == "20260903T123456123456Z-0123456789ab-01-aaaaaaaaaaaa"
    assert first.root != second.root
    assert marker.read_bytes() == b"keep"
    assert stat.S_IMODE(first.root.lstat().st_mode) == 0o700
    assert first.database == first.root / "duck-diary-uat.db"
    assert first.media == first.root / "media"
    assert first.tts_cache == first.root / "tts-cache"
    assert first.app_log == first.root / "logs" / "app.log"
    assert first.server_stderr == first.root / "logs" / "server.stderr.log"
    assert first.screenshots == first.root / "screenshots"
    assert first.controller_evidence == first.root / "controller-evidence.json"
    assert first.manifest == first.root / "manifest.json"
    assert first.checksums == first.root / "SHA256SUMS"


def test_reviewed_source_is_materialized_from_literal_git_commit_and_never_worktree(
    tmp_path, monkeypatch,
):
    module = _module()
    root = tmp_path / "repository"
    root.mkdir()
    subprocess.run(("git", "init", "-q"), cwd=root, check=True)
    subprocess.run(
        ("git", "config", "user.email", "uat@example.invalid"),
        cwd=root,
        check=True,
    )
    subprocess.run(
        ("git", "config", "user.name", "Retained UAT"), cwd=root, check=True
    )
    seed = root / "scripts" / "seed_demo_database.py"
    seed.parent.mkdir()
    seed.write_text("REVIEWED = 'seed-v1'\n", encoding="utf-8")
    server = root / "scripts" / "live_provider_uat_server.py"
    server.write_text("REVIEWED = 'server-v1'\n", encoding="utf-8")
    frontend = root / "app" / "frontend" / "index.html"
    frontend.parent.mkdir(parents=True)
    frontend.write_text("reviewed frontend\n", encoding="utf-8")
    backend = root / "app" / "backend" / "__init__.py"
    backend.parent.mkdir(parents=True)
    backend.write_text("REVIEWED = True\n", encoding="utf-8")
    fixtures = root / "tests" / "fixtures" / "live_provider" / "avatars"
    fixtures.mkdir(parents=True)
    (fixtures / "child.png").write_bytes(b"reviewed-child")
    (fixtures / "duck.jpg").write_bytes(b"reviewed-duck")
    (root / "app" / "version.json").write_text(
        '{"version":"reviewed"}\n', encoding="utf-8"
    )
    subprocess.run(("git", "add", "."), cwd=root, check=True)
    subprocess.run(("git", "commit", "-qm", "reviewed"), cwd=root, check=True)
    source_head = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    plan = module.create_run_plan(root, source_head)
    expected_tree = subprocess.run(
        ("git", "rev-parse", f"{source_head}^{{tree}}"),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    # A transient working-tree substitute must never become executable input.
    seed.write_text("MALICIOUS = 'temporary import'\n", encoding="utf-8")
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "attacker-controlled-git-dir"))
    git_calls = []

    def git_runner(argv, **kwargs):
        git_calls.append((tuple(argv), dict(kwargs)))
        return subprocess.run(argv, **kwargs)

    reviewed = module.materialize_reviewed_source(plan, runner=git_runner)
    seed.write_text("REVIEWED = 'seed-v1'\n", encoding="utf-8")

    assert reviewed.source_root == reviewed.root / "reviewed-source"
    assert reviewed.source_head == source_head
    assert reviewed.source_tree_oid == expected_tree
    assert (reviewed.source_root / "scripts/seed_demo_database.py").read_text(
        encoding="utf-8"
    ) == "REVIEWED = 'seed-v1'\n"
    assert module.build_seed_argv(
        reviewed,
        python_executable=PYTHON,
        business_today=lambda: date(2026, 9, 4),
    )[1] == str(reviewed.source_root / "scripts/seed_demo_database.py")
    assert module.build_runtime_object(reviewed, port=43123)["fixtures"] == {
        "child_avatar": str(
            reviewed.source_root
            / "tests/fixtures/live_provider/avatars/child.png"
        ),
        "duck_avatar": str(
            reviewed.source_root
            / "tests/fixtures/live_provider/avatars/duck.jpg"
        ),
        "invalid_avatar": str(reviewed.invalid_avatar),
    }
    source_manifest = json.loads(reviewed.source_manifest.read_text(encoding="utf-8"))
    assert source_manifest["source_head"] == source_head
    assert source_manifest["tree_oid"] == reviewed.source_tree_oid
    assert git_calls
    assert all(call[0][:2] == ("git", "--no-replace-objects") for call in git_calls)
    assert all("GIT_DIR" not in call[1]["env"] for call in git_calls)
    assert all(call[1]["env"]["GIT_NO_REPLACE_OBJECTS"] == "1" for call in git_calls)
    assert (
        "git",
        "--no-replace-objects",
        "cat-file",
        "commit",
        source_head,
    ) in [call[0] for call in git_calls]
    assert (
        "git",
        "--no-replace-objects",
        "cat-file",
        "tree",
        reviewed.source_tree_oid,
    ) in [call[0] for call in git_calls]
    assert any(
        item["path"] == "scripts/seed_demo_database.py"
        and item["blob_oid"]
        == hashlib.sha1(
            b"blob 21\0REVIEWED = 'seed-v1'\n", usedforsecurity=False
        ).hexdigest()
        for item in source_manifest["files"]
    )
    module.assert_reviewed_source_pinned(reviewed)
    source_seed = reviewed.source_root / "scripts/seed_demo_database.py"
    os.chmod(source_seed, 0o600)
    source_seed.write_text("MALICIOUS = 'inside source'\n", encoding="utf-8")
    with pytest.raises(module.HarnessSafetyError, match="reviewed source"):
        module.assert_reviewed_source_pinned(reviewed)


def test_candidate_real_git_tree_materializes_app_version(tmp_path):
    module = _module()
    repository = tmp_path / "candidate"
    subprocess.run(
        (
            "git",
            "clone",
            "--quiet",
            "--no-checkout",
            "--shared",
            str(module.PROJECT_ROOT),
            str(repository),
        ),
        check=True,
    )
    source_head = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    reviewed = module.materialize_reviewed_source(
        module.create_run_plan(repository, source_head)
    )

    assert (reviewed.source_root / "app" / "version.json").is_file()
    assert not (reviewed.source_root / "version.json").exists()


def test_run_plan_rejects_symlinked_artifact_ancestry(tmp_path):
    module = _module()
    root = _repository(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "artifacts").symlink_to(outside, target_is_directory=True)

    with pytest.raises(module.HarnessSafetyError, match="artifact ancestry"):
        module.create_run_plan(root, HEAD)

    assert tuple(outside.iterdir()) == ()


def test_seed_boundary_samples_date_once_and_uses_exact_full_demo_contract(tmp_path):
    module = _module()
    plan = module.create_run_plan(_repository(tmp_path), HEAD)
    calls = 0

    def business_today() -> date:
        nonlocal calls
        calls += 1
        return date(2026, 9, 3)

    argv = module.build_seed_argv(
        plan,
        python_executable=PYTHON,
        business_today=business_today,
    )

    assert calls == 1
    assert argv == (
        PYTHON,
        str(plan.source_root / "scripts" / "seed_demo_database.py"),
        "full-demo",
        "--anchor-date",
        "2026-09-03",
        "--database",
        str(plan.database),
        "--media-root",
        str(plan.media),
        "--log-path",
        str(plan.app_log),
    )
    assert "--force" not in argv


def test_seed_environment_is_offline_minimal_and_seed_result_is_strict(tmp_path):
    module = _module()
    plan = module.create_run_plan(_repository(tmp_path), HEAD)
    parent = {
        "PATH": "/safe/bin",
        "LANG": "C.UTF-8",
        "HOME": "/private/should-not-pass",
        "DEEPSEEK_API_KEY": "sentinel-provider-secret",
        "UNRELATED_TOKEN": "sentinel-unrelated-secret",
        "HTTPS_PROXY": "https://proxy.invalid/credential",
    }

    environment = module.build_seed_environment(parent)

    assert environment == {
        "DISABLE_EXTERNAL_AI": "1",
        "LANG": "C.UTF-8",
        "PATH": "/safe/bin",
        "PYTHONNOUSERSITE": "1",
        "PYTHON_DOTENV_DISABLED": "1",
        "TZ": "Asia/Shanghai",
    }
    payload = {
        "archive_directory": None,
        "database_path": str(plan.database),
        "log_path": str(plan.app_log),
        "media_root": str(plan.media),
        "media_sha256": "b" * 64,
        "record_sha256": "c" * 64,
    }
    assert module.parse_seed_result(
        (json.dumps(payload, sort_keys=True) + "\n").encode(), plan
    ) == payload
    for mutation in (
        {**payload, "unknown": True},
        {**payload, "database_path": str(plan.root / "other.db")},
        {**payload, "archive_directory": str(plan.root / "archive")},
        {**payload, "record_sha256": "short"},
    ):
        with pytest.raises(module.HarnessSafetyError):
            module.parse_seed_result(json.dumps(mutation).encode(), plan)


def test_default_seed_runner_is_shell_free_owned_offline_and_bounded(tmp_path):
    module = _module()
    plan = module.create_run_plan(_repository(tmp_path), HEAD)
    argv = module.build_seed_argv(
        plan,
        python_executable=PYTHON,
        business_today=lambda: date(2026, 9, 4),
    )
    environment = module.build_seed_environment(
        {
            "PATH": "/synthetic/bin",
            "DEEPSEEK_API_KEY": "must-not-cross",
        }
    )
    payload = {
        "archive_directory": None,
        "database_path": str(plan.database),
        "log_path": str(plan.app_log),
        "media_root": str(plan.media),
        "media_sha256": "b" * 64,
        "record_sha256": "c" * 64,
    }
    calls = []
    process = _FakeProcess()
    group = [(process.pid, process.pid), (process.pid + 1, process.pid)]
    signals = []

    def popen(actual_argv, **kwargs):
        calls.append((tuple(actual_argv), kwargs))
        kwargs["stdout"].write(module.canonical_json_line(payload).encode())
        kwargs["stdout"].flush()
        kwargs["stderr"].write(b"safe synthetic seed diagnostic\n")
        kwargs["stderr"].flush()
        return process

    result = module.run_seed_process(
        plan,
        argv=argv,
        environment=environment,
        popen=popen,
        getpgid=lambda pid: pid,
        getsid=lambda pid: pid,
        group_members=lambda _pgid: tuple(group)
        if process.returncode is None
        else (),
        killpg=lambda pgid, signum: (
            signals.append((pgid, signum)),
            group.__setitem__(slice(None), [(43210, 43210)]),
        ),
        peek_exit=lambda _owned: 0,
        monotonic=lambda: 0.0,
        sleep=lambda _seconds: None,
        source_validator=lambda _plan: None,
    )

    assert result == payload
    assert calls[0][0] == argv
    assert calls[0][1]["cwd"] == plan.source_root
    assert calls[0][1]["env"] == environment
    assert calls[0][1]["shell"] is False
    assert calls[0][1]["start_new_session"] is True
    assert calls[0][1]["stdin"] is subprocess.DEVNULL
    assert not any(name.startswith("DEEPSEEK_") for name in calls[0][1]["env"])
    assert signals == [(43210, signal.SIGTERM)]


def test_telemetry_collector_reads_one_bounded_pipe_and_rejects_truncation():
    module = _module()
    safe = {
        "audio_bytes": 0,
        "cache_relative_path": None,
        "cache_sha256": None,
        "correlation_id": "chat-request:00000000-0000-4000-8000-000000000301",
        "error_class": None,
        "latency_bucket": "1-5s",
        "model": "deepseek-chat",
        "operation": "chat_reply",
        "parse_valid": True,
        "provider": "deepseek",
        "response_bytes": 127,
        "response_sha256": "d" * 64,
        "status": "ok",
        "voice": None,
    }
    read_fd, write_fd = os.pipe()
    collector = module.TelemetryCollector(read_fd)
    collector.start()
    os.write(write_fd, module.canonical_json_line(safe).encode())
    os.close(write_fd)

    assert collector.finish() == (safe,)

    read_fd, write_fd = os.pipe()
    truncated = module.TelemetryCollector(read_fd)
    truncated.start()
    os.write(write_fd, b'{"operation":"chat_reply"}')
    os.close(write_fd)
    with pytest.raises(module.HarnessSafetyError, match="telemetry"):
        truncated.finish()


def _provider_values():
    return {
        "DEEPSEEK_API_KEY": "sk-sentinel-provider-secret-123456",
        "DEEPSEEK_BASE_URL": "https://api.deepseek.com/v1",
        "DEEPSEEK_MODEL": "deepseek-chat",
        "DEEPSEEK_TIMEOUT": "90",
        "DEEPSEEK_MAX_TOKENS": "4096",
    }


def test_provider_settings_use_exact_allowlist_and_reject_unsafe_values():
    module = _module()
    dotenv_values = {
        **_provider_values(),
        "UNRELATED_TOKEN": "dotenv-unrelated-secret",
        "HTTP_PROXY": "http://proxy.invalid/secret",
        "DEEPSEEK_REASONING_EFFORT": "high",
    }
    parent = {
        "DEEPSEEK_MODEL": "deepseek-reasoner",
        "UNRELATED_API_KEY": "parent-unrelated-secret",
        "HTTPS_PROXY": "https://proxy.invalid/secret",
    }

    selected = module.select_provider_settings(parent, dotenv_values)

    assert selected == {
        "DEEPSEEK_API_KEY": "sk-sentinel-provider-secret-123456",
        "DEEPSEEK_BASE_URL": "https://api.deepseek.com/v1",
        "DEEPSEEK_MODEL": "deepseek-reasoner",
        "DEEPSEEK_TIMEOUT": "90",
        "DEEPSEEK_MAX_TOKENS": "4096",
    }
    assert set(selected) == set(module.DEEPSEEK_ALLOWLIST)
    unsafe_cases = (
        {**dotenv_values, "DEEPSEEK_API_KEY": "placeholder"},
        {**dotenv_values, "DEEPSEEK_BASE_URL": "http://api.deepseek.com/v1"},
        {**dotenv_values, "DEEPSEEK_BASE_URL": "https://user:pass@api.deepseek.com/v1"},
        {**dotenv_values, "DEEPSEEK_BASE_URL": "https://api.deepseek.com/v1?secret=x"},
        {**dotenv_values, "DEEPSEEK_MODEL": "../../unsafe"},
        {**dotenv_values, "DEEPSEEK_TIMEOUT": "0"},
        {**dotenv_values, "DEEPSEEK_MAX_TOKENS": "999999999"},
    )
    for values in unsafe_cases:
        with pytest.raises(module.HarnessSafetyError, match="provider configuration") as caught:
            module.select_provider_settings({}, values)
        assert "sentinel" not in str(caught.value)


def test_backend_environment_binds_every_disposable_path_and_nothing_else(tmp_path):
    module = _module()
    plan = replace(
        module.create_run_plan(_repository(tmp_path), HEAD),
        source_tree_oid="b" * 40,
    )
    parent = {
        "PATH": "/safe/bin",
        "LANG": "C.UTF-8",
        "HOME": "/private/not-forwarded",
        "BROWSER_COOKIE": "not-forwarded",
        "UNRELATED_TOKEN": "not-forwarded",
    }

    environment = module.build_backend_environment(parent, plan, _provider_values())

    assert environment == {
        "APP_BUSINESS_TIMEZONE": "Asia/Shanghai",
        "APP_DB_MODE": "app",
        "APP_DB_PATH": str(plan.database),
        "APP_LOG_PATH": str(plan.app_log),
        "APP_MEDIA_ROOT": str(plan.media),
        "APP_REVIEWED_SOURCE_HEAD": HEAD,
        "APP_REVIEWED_SOURCE_MANIFEST": str(plan.source_manifest),
        "APP_REVIEWED_SOURCE_ROOT": str(plan.source_root),
        "APP_REVIEWED_SOURCE_TREE_OID": "b" * 40,
        "APP_TTS_CACHE_PATH": str(plan.tts_cache),
        "DEEPSEEK_API_KEY": "sk-sentinel-provider-secret-123456",
        "DEEPSEEK_BASE_URL": "https://api.deepseek.com/v1",
        "DEEPSEEK_MAX_TOKENS": "4096",
        "DEEPSEEK_MODEL": "deepseek-chat",
        "DEEPSEEK_TIMEOUT": "90",
        "LANG": "C.UTF-8",
        "PATH": "/safe/bin",
        "PYTHONNOUSERSITE": "1",
        "PYTHON_DOTENV_DISABLED": "1",
        "TZ": "Asia/Shanghai",
    }


def test_readiness_is_exact_before_safe_runtime_object_is_rendered(tmp_path):
    module = _module()
    plan = module.create_run_plan(_repository(tmp_path), HEAD)
    release = {
        "release_id": "2026.09.02-server-capabilities.1",
        "api_version": "3",
        "schema_version": "3",
    }
    health = {**release, "db_mode": "app", "analysis_worker_status": "running"}

    module.validate_readiness(
        health=health,
        version=release,
        version_cache_control="no-store",
        auth={"configured": False, "authenticated": False},
    )
    runtime = module.build_runtime_object(plan, port=43123)

    assert runtime == {
        "artifact_root": str(plan.root),
        "base_url": "http://127.0.0.1:43123",
        "child_url": "http://127.0.0.1:43123/",
        "controller_evidence_path": str(plan.controller_evidence),
        "fixtures": {
            "child_avatar": str(plan.source_root / "tests/fixtures/live_provider/avatars/child.png"),
            "duck_avatar": str(plan.source_root / "tests/fixtures/live_provider/avatars/duck.jpg"),
            "invalid_avatar": str(plan.invalid_avatar),
        },
        "protocol": "pomegranagent-live-uat/v1",
        "release": release,
        "run_id": plan.run_id,
        "screenshots_dir": str(plan.screenshots),
        "source_head": HEAD,
        "teacher_url": "http://127.0.0.1:43123/teacher.html",
        "viewports": {
            "child": ["1024x576", "1280x720"],
            "teacher": ["1024x768", "1440x900"],
        },
    }
    rendered = module.canonical_json_line(runtime)
    assert rendered == json.dumps(runtime, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"
    assert "sentinel-provider-secret" not in rendered
    for mutation in (
        {**health, "schema_version": "2"},
        {**health, "db_mode": "test"},
        {**health, "analysis_worker_status": "not_started"},
    ):
        with pytest.raises(module.HarnessSafetyError, match="readiness"):
            module.validate_readiness(
                health=mutation,
                version=release,
                version_cache_control="no-store",
                auth={"configured": False, "authenticated": False},
            )


def test_default_readiness_probe_uses_only_exact_loopback_gets():
    module = _module()
    release = dict(module.FROZEN_RELEASE)
    health = {
        **release,
        "db_mode": "app",
        "analysis_worker_status": "running",
    }
    calls = []

    def fetch(port, path):
        calls.append((port, path))
        responses = {
            "/api/health": (health, None),
            "/version.json": (release, "no-store"),
            "/api/auth/status": (
                {"configured": False, "authenticated": False},
                None,
            ),
        }
        return responses[path]

    session = types.SimpleNamespace(
        port=43123,
        owned=types.SimpleNamespace(),
    )
    result = module.probe_live_readiness(
        session,
        fetch_json=fetch,
        require_alive=lambda _owned: None,
        monotonic=iter((0.0, 0.1)).__next__,
        sleep=lambda _seconds: None,
    )

    assert result == (
        health,
        release,
        "no-store",
        {"configured": False, "authenticated": False},
    )
    assert calls == [
        (43123, "/api/health"),
        (43123, "/version.json"),
        (43123, "/api/auth/status"),
    ]


def test_runtime_emitter_writes_exactly_one_line_then_stays_silent(tmp_path):
    module = _module()
    plan = module.create_run_plan(_repository(tmp_path), HEAD)
    runtime = module.build_runtime_object(plan, port=43123)
    output = io.StringIO()
    emitter = module.RuntimeEmitter(output)

    emitter.emit(runtime)
    with pytest.raises(module.HarnessSafetyError, match="already emitted"):
        emitter.emit(runtime)

    assert output.getvalue() == module.canonical_json_line(runtime)
    assert output.getvalue().count("\n") == 1


def test_control_stream_is_canonical_one_way_and_never_echoes_secret(tmp_path):
    module = _module()
    plan = module.create_run_plan(_repository(tmp_path), HEAD)
    secret = "483921"
    evidence = {
        "protocol": "pomegranagent-live-uat-controller/v1",
        "run_id": plan.run_id,
        "source_head": HEAD,
        "journey": [],
        "screenshots": [],
        "issues": [],
        "human_uat_required": [],
    }
    plan.controller_evidence.write_text(
        json.dumps(evidence, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    frames = (
        json.dumps(
            {"kind": "teacher_credential", "type": "register_secret", "value": secret},
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
        + '{"type":"finalize"}\n'
    )
    output = io.StringIO()

    state = module.consume_control_stream(io.StringIO(frames), plan, output=output)

    assert state.finalize_requested is True
    assert state.has_teacher_secret is True
    assert output.getvalue() == ""
    assert secret not in repr(state)
    with pytest.raises(module.HarnessSafetyError, match="canonical control"):
        module.consume_control_stream(
            io.StringIO('{"value":"483921","kind":"teacher_credential","type":"register_secret"}\n'),
            plan,
            output=io.StringIO(),
        )


def test_telemetry_accepts_only_bounded_safe_provider_metadata():
    module = _module()
    safe = {
        "audio_bytes": 0,
        "cache_relative_path": None,
        "cache_sha256": None,
        "correlation_id": "chat-request:00000000-0000-4000-8000-000000000301",
        "error_class": None,
        "latency_bucket": "1-5s",
        "model": "deepseek-chat",
        "operation": "chat_reply",
        "parse_valid": True,
        "provider": "deepseek",
        "response_bytes": 127,
        "response_sha256": "d" * 64,
        "status": "ok",
        "voice": None,
    }
    line = module.canonical_json_line(safe).encode()

    event = module.parse_telemetry_line(line)
    summary = module.summarize_provider_events((event,))

    assert summary == {
        "protocol": "pomegranagent-live-uat-telemetry-summary/v1",
        "events": [safe],
    }
    assert all(set(item) == module.TELEMETRY_KEYS for item in summary["events"])
    assert "provider response" not in json.dumps(summary)
    mutations = (
        {**safe, "raw_reply": "provider response"},
        {**safe, "error_class": "ValueError: secret detail", "status": "error"},
        {**safe, "response_bytes": -1},
        {**safe, "response_bytes": 100_000_001},
        {**safe, "provider": "https://secret.invalid"},
        {**safe, "operation": "unknown"},
    )
    for mutation in mutations:
        with pytest.raises(module.HarnessSafetyError, match="telemetry"):
            module.parse_telemetry_line(module.canonical_json_line(mutation).encode())
    with pytest.raises(module.HarnessSafetyError, match="telemetry"):
        module.parse_telemetry_line(b"{" + b"x" * 5000)


def test_live_server_disables_dotenv_before_backend_import():
    server = importlib.import_module("scripts.live_provider_uat_server")
    assert server.PROJECT_ROOT == Path(server.__file__).resolve().parents[1]
    assert sys.path[0] == str(server.PROJECT_ROOT)
    events = []
    dotenv_module = types.SimpleNamespace(load_dotenv=lambda: events.append("unsafe_dotenv"))
    backend_module = types.SimpleNamespace()

    def importer(name):
        events.append(f"import:{name}")
        if name == "dotenv":
            return dotenv_module
        if name == "app.backend.main":
            assert dotenv_module.load_dotenv() is False
            events.append("backend_observed_disabled_dotenv")
            return backend_module
        raise AssertionError(name)

    loaded = server.load_backend(importer=importer)

    assert loaded is backend_module
    assert events == [
        "import:dotenv",
        "import:app.backend.main",
        "backend_observed_disabled_dotenv",
    ]


def test_live_server_validates_exact_runtime_paths_and_redacts_log_records(tmp_path):
    server = importlib.import_module("scripts.live_provider_uat_server")
    run_root = (tmp_path / "retained-run").resolve()
    run_root.mkdir()
    database = run_root / "duck-diary-uat.db"
    database.write_bytes(b"sqlite-placeholder")
    media = run_root / "media"
    tts = run_root / "tts-cache"
    logs = run_root / "logs"
    media.mkdir()
    tts.mkdir()
    logs.mkdir()
    app_log = logs / "app.log"
    app_log.write_bytes(b"")
    source_root = run_root / "reviewed-source"
    source_file = source_root / "app" / "backend" / "__init__.py"
    source_file.parent.mkdir(parents=True)
    source_payload = b"REVIEWED = True\n"
    source_file.write_bytes(source_payload)
    os.chmod(source_file, 0o400)
    os.chmod(source_file.parent, 0o500)
    os.chmod(source_file.parent.parent, 0o500)
    os.chmod(source_root, 0o500)
    source_head = "b" * 40
    source_tree = "c" * 40
    source_manifest = run_root / "reviewed-source.json"
    source_manifest.write_text(
        json.dumps(
            {
                "files": [
                    {
                        "blob_oid": hashlib.sha1(
                            f"blob {len(source_payload)}\0".encode("ascii")
                            + source_payload,
                            usedforsecurity=False,
                        ).hexdigest(),
                        "git_mode": 0o100644,
                        "path": "app/backend/__init__.py",
                        "sha256": hashlib.sha256(source_payload).hexdigest(),
                        "size": len(source_payload),
                    }
                ],
                "object_format": "sha1",
                "protocol": "pomegranagent-reviewed-source/v1",
                "source_head": source_head,
                "tree_oid": source_tree,
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    secret = "sk-server-secret-1234567890"
    environment = {
        "APP_BUSINESS_TIMEZONE": "Asia/Shanghai",
        "APP_DB_MODE": "app",
        "APP_DB_PATH": str(database),
        "APP_LOG_PATH": str(app_log),
        "APP_MEDIA_ROOT": str(media),
        "APP_REVIEWED_SOURCE_HEAD": source_head,
        "APP_REVIEWED_SOURCE_MANIFEST": str(source_manifest),
        "APP_REVIEWED_SOURCE_ROOT": str(source_root),
        "APP_REVIEWED_SOURCE_TREE_OID": source_tree,
        "APP_TTS_CACHE_PATH": str(tts),
        "DEEPSEEK_API_KEY": secret,
        "DEEPSEEK_BASE_URL": "https://api.deepseek.example/v1",
        "DEEPSEEK_MAX_TOKENS": "8192",
        "DEEPSEEK_MODEL": "deepseek-safe-model",
        "DEEPSEEK_TIMEOUT": "120",
        "PATH": "/synthetic/bin",
        "PYTHONNOUSERSITE": "1",
        "PYTHON_DOTENV_DISABLED": "1",
        "TZ": "Asia/Shanghai",
    }

    paths = server.validate_child_environment(environment)
    parsed = server.parse_args(["--listen-fd", "71", "--telemetry-fd", "72"])

    assert paths.root == run_root
    assert paths.database == database
    assert paths.media == media
    assert paths.tts_cache == tts
    assert paths.app_log == app_log
    assert paths.source_root == source_root
    assert paths.source_manifest == source_manifest
    server.assert_runtime_paths_pinned(paths)
    os.chmod(source_root, 0o700)
    os.chmod(source_file.parent.parent, 0o700)
    os.chmod(source_file.parent, 0o700)
    os.chmod(source_file, 0o600)
    source_file.write_bytes(b"MUTATED = True\n")
    with pytest.raises(server.ServerSafetyError, match="source"):
        server.assert_runtime_paths_pinned(paths)
    assert (parsed.listen_fd, parsed.telemetry_fd) == (71, 72)
    with pytest.raises(server.ServerSafetyError, match="environment"):
        server.validate_child_environment({**environment, "HTTPS_PROXY": "secret"})
    with pytest.raises(server.ServerSafetyError, match="descriptor"):
        server.parse_args(["--listen-fd", "71", "--telemetry-fd", "71"])

    record = logging.LogRecord(
        "synthetic",
        logging.ERROR,
        __file__,
        1,
        "Authorization: Bearer %s Cookie: duck_teacher_session=%s",
        (secret, secret),
        None,
    )
    redactor = server.RedactingFilter((secret,))
    assert redactor.filter(record) is True
    rendered = record.getMessage()
    assert secret not in rendered
    assert "Bearer" not in rendered
    assert "Cookie" not in rendered
    assert "duck_teacher_session" not in rendered


def test_live_server_ai_telemetry_is_bounded_metadata_without_exception_text():
    server = importlib.import_module("scripts.live_provider_uat_server")
    harness = _module()
    secret = "sk-never-retain-this-exception-detail"
    events = []
    ticks = iter((0.0, 2.0, 3.0, 9.0))

    raw_calls = iter(
        (
            '{"end_reason":null,"ended":false,"reply":"safe synthetic response"}',
            RuntimeError(secret),
        )
    )

    def llm(*_args, **_kwargs):
        result = next(raw_calls)
        if isinstance(result, BaseException):
            raise result
        return result

    def chat_reply(**_kwargs):
        return ai_engine._parse_json(ai_engine._llm([], json_mode=True))

    def extract_info(_transcript):
        return ai_engine._parse_json(ai_engine._llm([], json_mode=True))

    ai_engine = types.SimpleNamespace(
        MODEL="deepseek-safe-model",
        _llm=llm,
        _parse_json=json.loads,
        chat_reply=chat_reply,
        extract_info=extract_info,
        assess_conversation=lambda *_args: {"scores": []},
    )
    context = server.instrument_ai_engine(
        ai_engine,
        emit=events.append,
        monotonic=lambda: next(ticks),
    )

    request_id = "55555555-5555-4555-8555-555555555551"
    context.set_next_correlation(f"chat-request:{request_id}")
    assert ai_engine.chat_reply(child={})["reply"] == "safe synthetic response"
    with context.correlate("analysis-job:501"):
        with pytest.raises(RuntimeError, match="never-retain"):
            ai_engine.extract_info("synthetic")
    assert [event["operation"] for event in events] == ["chat_reply", "extract_info"]
    for event in events:
        assert harness.parse_telemetry_line(
            harness.canonical_json_line(event).encode("utf-8")
        ) == event
    assert events[0]["status"] == "ok"
    assert events[0]["response_bytes"] > 0
    assert events[1]["status"] == "error"
    assert events[1]["error_class"] == "RuntimeError"
    assert secret not in json.dumps(events)


def test_live_server_marks_malformed_raw_provider_json_as_error_before_local_fallback():
    server = importlib.import_module("scripts.live_provider_uat_server")
    events = []
    ticks = iter((0.0, 0.2))
    ai_engine = types.SimpleNamespace(MODEL="deepseek-safe-model")
    ai_engine._parse_json = json.loads
    ai_engine._llm = lambda *_args, **_kwargs: "not-json"

    def chat_reply(**_kwargs):
        raw = ai_engine._llm([], json_mode=True)
        try:
            return ai_engine._parse_json(raw)
        except ValueError:
            return {"reply": "local fallback", "ended": False, "end_reason": None}

    ai_engine.chat_reply = chat_reply
    ai_engine.extract_info = lambda _transcript: {}
    ai_engine.assess_conversation = lambda *_args: {}

    context = server.instrument_ai_engine(
        ai_engine,
        emit=events.append,
        monotonic=lambda: next(ticks),
    )
    request_id = "55555555-5555-4555-8555-555555555551"
    context.set_next_correlation(f"chat-request:{request_id}")

    assert ai_engine.chat_reply()["reply"] == "local fallback"
    assert len(events) == 1
    assert events[0]["operation"] == "chat_reply"
    assert events[0]["correlation_id"] == f"chat-request:{request_id}"
    assert events[0]["parse_valid"] is False
    assert events[0]["status"] == "error"
    assert events[0]["error_class"] == "ProviderPayloadInvalid"
    assert "not-json" not in json.dumps(events)


def test_live_server_chat_correlation_uses_exact_claim_request_uuid(monkeypatch):
    server = importlib.import_module("scripts.live_provider_uat_server")
    request_id = "55555555-5555-4555-8555-555555555551"
    contexts = []

    class Correlation:
        def set_next_correlation(self, value):
            contexts.append(value)

    conversations = types.SimpleNamespace(
        ai_engine=object(),
        build_chat_context=lambda _db, _claim, _payload: types.SimpleNamespace(
            conversation_id=301
        ),
    )
    backend = types.SimpleNamespace(ai_engine=conversations.ai_engine)
    original_import = server.importlib.import_module
    monkeypatch.setattr(
        server.importlib,
        "import_module",
        lambda name: conversations
        if name == "app.backend.routes.conversations"
        else original_import(name),
    )

    server.install_chat_correlation(backend, Correlation())
    claim = types.SimpleNamespace(request_id=request_id)
    result = conversations.build_chat_context(object(), claim, object())

    assert result.conversation_id == 301
    assert contexts == [f"chat-request:{request_id}"]
    with pytest.raises(server.ServerSafetyError, match="correlation"):
        conversations.build_chat_context(
            object(), types.SimpleNamespace(request_id="not-a-uuid"), object()
        )


def test_provider_completion_requires_exact_model_voice_correlation_and_run_owned_audio(
    tmp_path,
):
    module = _module()
    plan = module.create_run_plan(_repository(tmp_path), HEAD)
    plan.tts_cache.mkdir(mode=0o700)
    request_ids = [
        "55555555-5555-4555-8555-555555555551",
        "55555555-5555-4555-8555-555555555552",
        "55555555-5555-4555-8555-555555555553",
    ]
    texts = [
        "你好呀，Live Child！我是鸭鸭日记本，今天想听你讲讲照顾小鸭的事～",
        "你观察到小鸭有什么变化？",
        "你照顾得很认真，还有什么感受？",
        "这是一份很完整的池塘日记。",
    ]
    tts_evidence = []
    for index, text in enumerate(texts):
        audio = f"ID3 synthetic exact audio {index}".encode("ascii")
        cache_name = hashlib.md5(
            text.encode("utf-8"), usedforsecurity=False
        ).hexdigest() + ".mp3"
        (plan.tts_cache / cache_name).write_bytes(audio)
        tts_evidence.append(
            {
                "audio_sha256": hashlib.sha256(audio).hexdigest(),
                "cache_relative_path": f"tts-cache/{cache_name}",
                "effective_text_sha256": hashlib.sha256(
                    text.strip()[:500].encode("utf-8")
                ).hexdigest(),
                "kind": "opening_greeting" if index == 0 else "diary_reply",
                "playback": _native_audio_playback(),
                "source_message_id": None if index == 0 else 400 + index * 2,
                "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "truncated": len(text.strip()) > 500,
            }
        )
    entity_ids = {
        "analysis_job_id": 501,
        "chat_request_ids": request_ids,
        "live_conversation_id": 301,
        "local_terminal_request_id": request_ids[2],
        "monthly_roster_attempts": [
            {
                "canonical_body_sha256": "a" * 64,
                "error_code": "ROSTER_DATE_CONFLICT",
                "kind": "roster_attempt",
                "method": "POST",
                "order": 1,
                "path": "/api/roster/month",
                "replace_existing": False,
                "request_id": "33333333-3333-4333-8333-333333333333",
                "status": 409,
            },
            {
                "canonical_body_sha256": "a" * 64,
                "error_code": None,
                "kind": "roster_attempt",
                "method": "POST",
                "order": 2,
                "path": "/api/roster/month",
                "replace_existing": True,
                "request_id": "44444444-4444-4444-8444-444444444444",
                "status": 200,
            },
        ],
        "monthly_roster_request_ids": [
            "33333333-3333-4333-8333-333333333333",
            "44444444-4444-4444-8444-444444444444",
        ],
        "provider_chat_request_ids": request_ids[:2],
        "tts_evidence": tts_evidence,
    }

    def ai_event(operation, correlation):
        return {
            "audio_bytes": 0,
            "cache_relative_path": None,
            "cache_sha256": None,
            "correlation_id": correlation,
            "error_class": None,
            "latency_bucket": "1-5s",
            "model": "deepseek-safe-model",
            "operation": operation,
            "parse_valid": True,
            "provider": "deepseek",
            "response_bytes": 127,
            "response_sha256": "e" * 64,
            "status": "ok",
            "voice": None,
        }

    def tts_event(evidence):
        cache = plan.root / evidence["cache_relative_path"]
        return {
            "audio_bytes": cache.stat().st_size,
            "cache_relative_path": evidence["cache_relative_path"],
            "cache_sha256": evidence["audio_sha256"],
            "correlation_id": "message-text:" + evidence["effective_text_sha256"],
            "error_class": None,
            "latency_bucket": "1-5s",
            "model": None,
            "operation": "tts",
            "parse_valid": None,
            "provider": "edge-tts",
            "response_bytes": 0,
            "response_sha256": None,
            "status": "ok",
            "voice": "zh-CN-XiaoxiaoNeural",
        }

    def tts_request_event(evidence, order, *, cache_hit=False):
        cache = plan.root / evidence["cache_relative_path"]
        return {
            "audio_bytes": cache.stat().st_size,
            "cache_hit": cache_hit,
            "cache_relative_path": evidence["cache_relative_path"],
            "cache_sha256": evidence["audio_sha256"],
            "effective_text_sha256": evidence["effective_text_sha256"],
            "kind": "tts_request",
            "method": "GET",
            "order": order,
            "path": "/api/tts",
            "requested_text_sha256": evidence["text_sha256"],
            "status": 200,
            "truncated": evidence["truncated"],
            "voice": "zh-CN-XiaoxiaoNeural",
        }

    events = (
        *entity_ids["monthly_roster_attempts"],
        tts_event(tts_evidence[0]),
        tts_request_event(tts_evidence[0], 1),
        ai_event("chat_reply", f"chat-request:{request_ids[0]}"),
        tts_event(tts_evidence[1]),
        tts_request_event(tts_evidence[1], 2),
        ai_event("chat_reply", f"chat-request:{request_ids[1]}"),
        tts_event(tts_evidence[2]),
        tts_request_event(tts_evidence[2], 3),
        tts_event(tts_evidence[3]),
        tts_request_event(tts_evidence[3], 4),
        ai_event("extract_info", "analysis-job:501"),
        ai_event("assess_conversation", "analysis-job:501"),
    )

    summary = module._validate_provider_completion(
        events,
        plan=plan,
        provider={**_provider_values(), "DEEPSEEK_MODEL": "deepseek-safe-model"},
        entity_ids=entity_ids,
    )
    assert len(summary["events"]) == 14

    mutations = (
        (*events[:12], {**events[12], "model": "wrong-model"}, events[13]),
        (*events[:10], {**events[10], "voice": "zh-CN-YunxiNeural"}, *events[11:]),
        (*events[:4], {**events[4], "correlation_id": f"chat-request:{request_ids[2]}"}, *events[5:]),
        (*events[:11], {**events[11], "cache_sha256": "0" * 64}, *events[12:]),
        (*events[:11], *events[12:]),
        (*events[:10], ai_event("chat_reply", f"chat-request:{request_ids[2]}"), *events[10:]),
        ({**events[0], "canonical_body_sha256": "b" * 64}, *events[1:]),
    )
    for mutation in mutations:
        with pytest.raises(module.HarnessSafetyError, match="provider telemetry"):
            module._validate_provider_completion(
                tuple(mutation),
                plan=plan,
                provider={**_provider_values(), "DEEPSEEK_MODEL": "deepseek-safe-model"},
                entity_ids=entity_ids,
            )
    fallback_entities = json.loads(json.dumps(entity_ids))
    fallback_entities["tts_evidence"][0]["playback"][
        "speech_synthesis_fallback"
    ] = True
    with pytest.raises(module.HarnessSafetyError, match="provider telemetry TTS"):
        module._validate_provider_completion(
            events,
            plan=plan,
            provider={**_provider_values(), "DEEPSEEK_MODEL": "deepseek-safe-model"},
            entity_ids=fallback_entities,
        )
    (plan.root / tts_evidence[-1]["cache_relative_path"]).unlink()
    with pytest.raises(module.HarnessSafetyError, match="provider telemetry"):
        module._validate_provider_completion(
            events,
            plan=plan,
            provider={**_provider_values(), "DEEPSEEK_MODEL": "deepseek-safe-model"},
            entity_ids=entity_ids,
        )


def test_provider_completion_accepts_early_complete_and_requires_cache_hit_endpoint(
    tmp_path,
):
    module = _module()
    plan = module.create_run_plan(_repository(tmp_path), HEAD)
    plan.tts_cache.mkdir(mode=0o700)
    request_ids = [
        "55555555-5555-4555-8555-555555555551",
        "55555555-5555-4555-8555-555555555552",
    ]
    texts = [
        "你好呀，小星！我是鸭鸭日记本，今天想听你讲讲照顾小鸭的事～",
        "鸭" * 500 + "甲",
        "鸭" * 500 + "乙",
    ]
    effective_texts = [texts[0], "鸭" * 500, "鸭" * 500]
    audio_by_effective = {
        effective_texts[0]: b"ID3 greeting audio",
        effective_texts[1]: b"ID3 shared reply audio",
    }
    evidence = []
    for index, (text, effective) in enumerate(
        zip(texts, effective_texts, strict=True)
    ):
        audio = audio_by_effective[effective]
        cache_name = hashlib.md5(
            effective.encode("utf-8"), usedforsecurity=False
        ).hexdigest() + ".mp3"
        (plan.tts_cache / cache_name).write_bytes(audio)
        evidence.append(
            {
                "audio_sha256": hashlib.sha256(audio).hexdigest(),
                "cache_relative_path": f"tts-cache/{cache_name}",
                "effective_text_sha256": hashlib.sha256(
                    effective.encode("utf-8")
                ).hexdigest(),
                "kind": "opening_greeting" if index == 0 else "diary_reply",
                "playback": _native_audio_playback(),
                "source_message_id": None if index == 0 else 400 + index * 2,
                "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "truncated": index > 0,
            }
        )
    roster = [
        {
            "canonical_body_sha256": "a" * 64,
            "error_code": "ROSTER_DATE_CONFLICT",
            "kind": "roster_attempt",
            "method": "POST",
            "order": 1,
            "path": "/api/roster/month",
            "replace_existing": False,
            "request_id": "33333333-3333-4333-8333-333333333333",
            "status": 409,
        },
        {
            "canonical_body_sha256": "a" * 64,
            "error_code": None,
            "kind": "roster_attempt",
            "method": "POST",
            "order": 2,
            "path": "/api/roster/month",
            "replace_existing": True,
            "request_id": "44444444-4444-4444-8444-444444444444",
            "status": 200,
        },
    ]
    entity_ids = {
        "analysis_job_id": 501,
        "chat_request_ids": request_ids,
        "live_conversation_id": 301,
        "local_terminal_request_id": None,
        "monthly_roster_attempts": roster,
        "monthly_roster_request_ids": [item["request_id"] for item in roster],
        "provider_chat_request_ids": request_ids,
        "tts_evidence": evidence,
    }

    def ai_event(operation, correlation):
        return {
            "audio_bytes": 0,
            "cache_relative_path": None,
            "cache_sha256": None,
            "correlation_id": correlation,
            "error_class": None,
            "latency_bucket": "1-5s",
            "model": "deepseek-safe-model",
            "operation": operation,
            "parse_valid": True,
            "provider": "deepseek",
            "response_bytes": 127,
            "response_sha256": "e" * 64,
            "status": "ok",
            "voice": None,
        }

    def raw_tts(item):
        cache = plan.root / item["cache_relative_path"]
        return {
            "audio_bytes": cache.stat().st_size,
            "cache_relative_path": item["cache_relative_path"],
            "cache_sha256": item["audio_sha256"],
            "correlation_id": "message-text:" + item["effective_text_sha256"],
            "error_class": None,
            "latency_bucket": "1-5s",
            "model": None,
            "operation": "tts",
            "parse_valid": None,
            "provider": "edge-tts",
            "response_bytes": 0,
            "response_sha256": None,
            "status": "ok",
            "voice": "zh-CN-XiaoxiaoNeural",
        }

    def endpoint_tts(item, order, cache_hit):
        cache = plan.root / item["cache_relative_path"]
        return {
            "audio_bytes": cache.stat().st_size,
            "cache_hit": cache_hit,
            "cache_relative_path": item["cache_relative_path"],
            "cache_sha256": item["audio_sha256"],
            "effective_text_sha256": item["effective_text_sha256"],
            "kind": "tts_request",
            "method": "GET",
            "order": order,
            "path": "/api/tts",
            "requested_text_sha256": item["text_sha256"],
            "status": 200,
            "truncated": item["truncated"],
            "voice": "zh-CN-XiaoxiaoNeural",
        }

    events = (
        *roster,
        raw_tts(evidence[0]),
        endpoint_tts(evidence[0], 1, False),
        ai_event("chat_reply", f"chat-request:{request_ids[0]}"),
        raw_tts(evidence[1]),
        endpoint_tts(evidence[1], 2, False),
        ai_event("chat_reply", f"chat-request:{request_ids[1]}"),
        endpoint_tts(evidence[2], 3, True),
        ai_event("extract_info", "analysis-job:501"),
        ai_event("assess_conversation", "analysis-job:501"),
    )

    summary = module._validate_provider_completion(
        events,
        plan=plan,
        provider={**_provider_values(), "DEEPSEEK_MODEL": "deepseek-safe-model"},
        entity_ids=entity_ids,
    )
    assert len(summary["events"]) == 11
    for invalid in (
        (*events[:8], {**events[8], "cache_hit": False}, *events[9:]),
        (*events[:8], raw_tts(evidence[2]), *events[8:]),
    ):
        with pytest.raises(module.HarnessSafetyError, match="provider telemetry"):
            module._validate_provider_completion(
                invalid,
                plan=plan,
                provider={
                    **_provider_values(),
                    "DEEPSEEK_MODEL": "deepseek-safe-model",
                },
                entity_ids=entity_ids,
            )


def test_edge_tts_telemetry_hashes_exact_audio_and_run_cache_name():
    server = importlib.import_module("scripts.live_provider_uat_server")
    events = []
    audio_chunks = (b"audio-one", b"audio-two")

    class Communicate:
        def __init__(self, text, voice, **_kwargs):
            self.text = text
            self.voice = voice

        async def stream(self):
            for chunk in audio_chunks:
                yield {"type": "audio", "data": chunk}

    edge = types.SimpleNamespace(Communicate=Communicate)
    server.instrument_edge_tts(edge, emit=events.append, monotonic=iter((0.0, 0.5)).__next__)

    async def consume():
        return [chunk async for chunk in edge.Communicate("池塘日记", "zh-CN-XiaoxiaoNeural").stream()]

    assert asyncio.run(consume()) == [
        {"type": "audio", "data": audio_chunks[0]},
        {"type": "audio", "data": audio_chunks[1]},
    ]
    combined = b"".join(audio_chunks)
    text_sha = hashlib.sha256("池塘日记".encode("utf-8")).hexdigest()
    assert events == [
        {
            "audio_bytes": len(combined),
            "cache_relative_path": "tts-cache/"
            + hashlib.md5("池塘日记".encode("utf-8")).hexdigest()
            + ".mp3",
            "cache_sha256": hashlib.sha256(combined).hexdigest(),
            "correlation_id": f"message-text:{text_sha}",
            "error_class": None,
            "latency_bucket": "<1s",
            "model": None,
            "operation": "tts",
            "parse_valid": None,
            "provider": "edge-tts",
            "response_bytes": 0,
            "response_sha256": None,
            "status": "ok",
            "voice": "zh-CN-XiaoxiaoNeural",
        }
    ]


def test_live_server_emits_safe_ordered_monthly_roster_attempt_telemetry():
    server = importlib.import_module("scripts.live_provider_uat_server")
    harness = _module()
    events = []
    calls = []

    async def app(scope, receive, send):
        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if not message.get("more_body", False):
                break
        value = json.loads(body)
        calls.append(value)
        if value["replace_existing"]:
            status = 200
            response = {"request_id": value["request_id"], "schedule": []}
        else:
            status = 409
            response = {"error": {"code": "ROSTER_DATE_CONFLICT"}}
        await send({"type": "http.response.start", "status": status, "headers": []})
        await send(
            {
                "type": "http.response.body",
                "body": json.dumps(response).encode("utf-8"),
                "more_body": False,
            }
        )

    wrapped = server.RosterAttemptTelemetry(app, emit=events.append)
    base = {
        "month": "2026-09",
        "cycle": "2026-09",
        "entries": [
            {"date": "2026-09-03", "child_ids": [10, 101]},
            {"date": "2026-09-04", "child_ids": [10, 101]},
        ],
    }
    request_ids = (
        "33333333-3333-4333-8333-333333333333",
        "44444444-4444-4444-8444-444444444444",
    )

    async def invoke(body):
        request_messages = [
            {
                "type": "http.request",
                "body": json.dumps(body).encode("utf-8"),
                "more_body": False,
            }
        ]
        responses = []

        async def receive():
            return request_messages.pop(0)

        async def send(message):
            responses.append(message)

        await wrapped(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/roster/month",
            },
            receive,
            send,
        )
        return responses

    asyncio.run(invoke({**base, "replace_existing": False, "request_id": request_ids[0]}))
    asyncio.run(invoke({**base, "replace_existing": True, "request_id": request_ids[1]}))

    assert calls[0]["entries"] == calls[1]["entries"]
    assert events == [
        {
            "canonical_body_sha256": events[0]["canonical_body_sha256"],
            "error_code": "ROSTER_DATE_CONFLICT",
            "kind": "roster_attempt",
            "method": "POST",
            "order": 1,
            "path": "/api/roster/month",
            "replace_existing": False,
            "request_id": request_ids[0],
            "status": 409,
        },
        {
            "canonical_body_sha256": events[0]["canonical_body_sha256"],
            "error_code": None,
            "kind": "roster_attempt",
            "method": "POST",
            "order": 2,
            "path": "/api/roster/month",
            "replace_existing": True,
            "request_id": request_ids[1],
            "status": 200,
        },
    ]
    for event in events:
        assert harness.parse_telemetry_line(
            harness.canonical_json_line(event).encode("utf-8")
        ) == event


def test_live_server_emits_tts_endpoint_miss_hit_and_truncation_telemetry(tmp_path):
    server = importlib.import_module("scripts.live_provider_uat_server")
    harness = _module()
    cache = tmp_path / "tts-cache"
    cache.mkdir(mode=0o700)
    events = []
    requested = []

    async def app(scope, _receive, send):
        text = scope["query_string"].decode("ascii").removeprefix("text=")
        text = __import__("urllib.parse").parse.unquote(text).strip()[:500]
        requested.append(text)
        cache_file = cache / (
            hashlib.md5(text.encode("utf-8"), usedforsecurity=False).hexdigest()
            + ".mp3"
        )
        if not cache_file.exists():
            cache_file.write_bytes(b"ID3 exact endpoint audio")
        audio = cache_file.read_bytes()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send(
            {
                "type": "http.response.body",
                "body": audio,
                "more_body": False,
            }
        )

    wrapped = server.TTSRequestTelemetry(app, emit=events.append, tts_cache=cache)
    texts = ("鸭" * 500 + "甲", "鸭" * 500 + "乙")

    async def invoke(text):
        responses = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            responses.append(message)

        await wrapped(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/tts",
                "query_string": f"text={quote(text)}".encode("ascii"),
            },
            receive,
            send,
        )
        return responses

    asyncio.run(invoke(texts[0]))
    asyncio.run(invoke(texts[1]))

    effective = "鸭" * 500
    cache_relative = "tts-cache/" + hashlib.md5(
        effective.encode("utf-8"), usedforsecurity=False
    ).hexdigest() + ".mp3"
    audio_sha = hashlib.sha256(b"ID3 exact endpoint audio").hexdigest()
    assert requested == [effective, effective]
    assert events == [
        {
            "audio_bytes": len(b"ID3 exact endpoint audio"),
            "cache_hit": False,
            "cache_relative_path": cache_relative,
            "cache_sha256": audio_sha,
            "effective_text_sha256": hashlib.sha256(effective.encode("utf-8")).hexdigest(),
            "kind": "tts_request",
            "method": "GET",
            "order": 1,
            "path": "/api/tts",
            "requested_text_sha256": hashlib.sha256(texts[0].encode("utf-8")).hexdigest(),
            "status": 200,
            "truncated": True,
            "voice": "zh-CN-XiaoxiaoNeural",
        },
        {
            "audio_bytes": len(b"ID3 exact endpoint audio"),
            "cache_hit": True,
            "cache_relative_path": cache_relative,
            "cache_sha256": audio_sha,
            "effective_text_sha256": hashlib.sha256(effective.encode("utf-8")).hexdigest(),
            "kind": "tts_request",
            "method": "GET",
            "order": 2,
            "path": "/api/tts",
            "requested_text_sha256": hashlib.sha256(texts[1].encode("utf-8")).hexdigest(),
            "status": 200,
            "truncated": True,
            "voice": "zh-CN-XiaoxiaoNeural",
        },
    ]
    for event in events:
        assert harness.parse_telemetry_line(
            harness.canonical_json_line(event).encode("utf-8")
        ) == event


class _FakeBoundSocket:
    def __init__(self):
        self.events = []
        self.closed = False

    def setsockopt(self, *args):
        self.events.append(("setsockopt", args))

    def bind(self, address):
        self.events.append(("bind", address))

    def listen(self, backlog):
        self.events.append(("listen", backlog))

    def getsockname(self):
        return ("127.0.0.1", 43123)

    def fileno(self):
        return 71

    def close(self):
        self.closed = True


class _FakeProcess:
    def __init__(self, pid=43210, *, waits=()):
        self.pid = pid
        self.returncode = None
        self.waits = list(waits)
        self.wait_timeouts = []
        self.terminate_calls = 0
        self.kill_calls = 0

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.wait_timeouts.append(timeout)
        if self.waits:
            result = self.waits.pop(0)
            if isinstance(result, BaseException):
                raise result
            self.returncode = result
        elif self.returncode is None:
            self.returncode = 0
        return self.returncode

    def terminate(self):
        self.terminate_calls += 1
        self.returncode = -signal.SIGTERM

    def kill(self):
        self.kill_calls += 1
        self.returncode = -signal.SIGKILL


def test_server_launch_uses_parent_prebound_random_socket_and_direct_group(tmp_path):
    module = _module()
    plan = module.create_run_plan(_repository(tmp_path), HEAD)
    bound_socket = _FakeBoundSocket()
    created = module.prebind_loopback_socket(socket_factory=lambda *_args: bound_socket)
    process = _FakeProcess()
    calls = []

    def popen(argv, **kwargs):
        calls.append((tuple(argv), kwargs))
        return process

    owned = module.launch_server_process(
        plan,
        environment={"APP_DB_MODE": "app"},
        bound_socket=created.socket,
        telemetry_fd=72,
        output=object(),
        python_executable=PYTHON,
        popen=popen,
        getpgid=lambda pid: pid,
        getsid=lambda pid: pid,
        source_validator=lambda _plan: None,
    )

    assert created.port == 43123
    assert ("bind", ("127.0.0.1", 0)) in bound_socket.events
    assert ("listen", 128) in bound_socket.events
    assert bound_socket.closed is False
    assert owned.pid == owned.pgid == 43210
    assert calls == [
        (
            (
                PYTHON,
                str(plan.source_root / "scripts" / "live_provider_uat_server.py"),
                "--listen-fd",
                "71",
                "--telemetry-fd",
                "72",
            ),
            {
                "close_fds": True,
                "cwd": plan.source_root,
                "env": {"APP_DB_MODE": "app"},
                "pass_fds": (71, 72),
                "shell": False,
                "start_new_session": True,
                "stderr": calls[0][1]["stderr"] if calls else None,
                "stdin": subprocess.DEVNULL,
                "stdout": calls[0][1]["stdout"] if calls else None,
            },
        )
    ]
    assert calls[0][1]["stdout"] is calls[0][1]["stderr"]


def test_post_popen_validation_failure_reaps_seed_and_server_leaders(tmp_path):
    module = _module()
    plan = module.create_run_plan(_repository(tmp_path), HEAD)
    seed_process = _FakeProcess(pid=43210)
    server_process = _FakeProcess(pid=43211)
    bound_socket = _FakeBoundSocket()

    with pytest.raises(module.HarnessSafetyError, match="ownership"):
        module.run_seed_process(
            plan,
            argv=(PYTHON, "seed.py"),
            environment={
                "DISABLE_EXTERNAL_AI": "1",
                "PYTHONNOUSERSITE": "1",
                "PYTHON_DOTENV_DISABLED": "1",
                "TZ": "Asia/Shanghai",
            },
            popen=lambda *_args, **_kwargs: seed_process,
            getpgid=lambda _pid: 99999,
            getsid=lambda pid: pid,
            source_validator=lambda _plan: None,
        )
    assert seed_process.terminate_calls == 1
    assert seed_process.returncode == -signal.SIGTERM

    validations = 0
    stopped_groups = []

    def source_validator(_plan):
        nonlocal validations
        validations += 1
        if validations == 2:
            raise module.HarnessSafetyError("reviewed source changed")

    with pytest.raises(module.HarnessSafetyError, match="reviewed source"):
        module.launch_server_process(
            plan,
            environment={"APP_DB_MODE": "app"},
            bound_socket=bound_socket,
            telemetry_fd=72,
            output=object(),
            python_executable=PYTHON,
            popen=lambda *_args, **_kwargs: server_process,
            getpgid=lambda pid: pid,
            getsid=lambda pid: pid,
            source_validator=source_validator,
            validation_stopper=lambda owned: (
                stopped_groups.append(owned.pgid),
                setattr(owned.process, "returncode", -signal.SIGTERM),
            ),
        )
    assert stopped_groups == [server_process.pid]
    assert server_process.terminate_calls == 0
    assert server_process.returncode == -signal.SIGTERM


def test_start_live_server_cleans_launched_group_when_post_popen_pin_fails(
    tmp_path,
    monkeypatch,
):
    module = _module()
    plan = module.create_run_plan(_repository(tmp_path), HEAD)
    plan.app_log.parent.mkdir(mode=0o700)
    bound_socket = _FakeBoundSocket()
    process = _FakeProcess()
    stopped = []
    collector_events = []
    descriptors = {}
    pin_checks = 0
    real_pin_check = module.assert_run_plan_identity

    def assert_pin(candidate):
        nonlocal pin_checks
        pin_checks += 1
        if pin_checks == 2:
            raise module.HarnessSafetyError("retained run root identity changed")
        real_pin_check(candidate)

    class Collector:
        def __init__(self, descriptor):
            descriptors["read"] = descriptor

        def start(self):
            collector_events.append("start")

        def finish(self):
            os.close(descriptors["read"])
            collector_events.append("finish")
            return ()

    def launch(_plan, **kwargs):
        descriptors["write"] = kwargs["telemetry_fd"]
        return module.OwnedProcess(process, process.pid, process.pid, process.pid)

    monkeypatch.setattr(module, "assert_run_plan_identity", assert_pin)
    with pytest.raises(module.HarnessSafetyError, match="identity changed"):
        module.start_live_server(
            plan,
            environment={"APP_DB_MODE": "app"},
            python_executable=PYTHON,
            prebind=lambda: module.BoundLoopbackSocket(bound_socket, 43123),
            collector_factory=Collector,
            launcher=launch,
            startup_stopper=lambda owned: (
                stopped.append(owned.pgid),
                setattr(owned.process, "returncode", -signal.SIGTERM),
            ),
        )

    assert stopped == [process.pid]
    assert collector_events == ["start", "finish"]
    assert bound_socket.closed is True
    with pytest.raises(OSError):
        os.fstat(descriptors["write"])


def test_live_server_session_closes_parent_fds_and_finishes_once(tmp_path):
    module = _module()
    plan = module.create_run_plan(_repository(tmp_path), HEAD)
    plan.app_log.parent.mkdir(mode=0o700)
    bound_socket = _FakeBoundSocket()
    collector_events = []
    launched = []
    stopped = []
    descriptors = {}

    class Collector:
        def __init__(self, descriptor):
            descriptors["read"] = descriptor

        def start(self):
            collector_events.append("start")

        def finish(self):
            os.close(descriptors["read"])
            collector_events.append("finish")
            return ({"operation": "chat_reply"},)

    def launch(plan_arg, **kwargs):
        assert plan_arg is plan
        descriptors["write"] = kwargs["telemetry_fd"]
        launched.append(kwargs)
        process = _FakeProcess()
        return module.OwnedProcess(process, process.pid, process.pid)

    session = module.start_live_server(
        plan,
        environment={"APP_DB_MODE": "app"},
        python_executable=PYTHON,
        prebind=lambda: module.BoundLoopbackSocket(bound_socket, 43123),
        collector_factory=Collector,
        launcher=launch,
    )

    assert session.port == 43123
    assert bound_socket.closed is True
    assert collector_events == ["start"]
    assert launched[0]["bound_socket"] is bound_socket
    assert launched[0]["output"] is session.output
    with pytest.raises(OSError):
        os.fstat(descriptors["write"])
    assert stat.S_IMODE(plan.server_stderr.lstat().st_mode) == 0o600

    events = module.finish_live_server(
        session,
        stopper=lambda owned: (
            stopped.append(owned.pgid),
            setattr(owned.process, "returncode", 0),
        ),
        peek_exit=lambda _owned: None,
    )
    repeated = module.finish_live_server(session, stopper=lambda _owned: pytest.fail())

    assert events == repeated == ({"operation": "chat_reply"},)
    assert stopped == [session.owned.pgid]
    assert collector_events == ["start", "finish"]
    assert session.output.closed is True


def test_finish_live_server_still_cleans_owned_group_when_leader_already_exited(tmp_path):
    module = _module()
    process = _FakeProcess()
    process.returncode = 7
    owned = module.OwnedProcess(
        process=process,
        pid=process.pid,
        pgid=process.pid,
        sid=process.pid,
    )
    output = (tmp_path / "server.log").open("w+b")
    telemetry = types.SimpleNamespace(finish=lambda: ())
    session = module.LiveServerSession(
        port=43123,
        owned=owned,
        telemetry=telemetry,
        output=output,
    )
    cleaned = []

    with pytest.raises(module.HarnessSafetyError, match="exited unexpectedly"):
        module.finish_live_server(
            session,
            stopper=lambda candidate: cleaned.append(candidate.pgid),
        )

    assert cleaned == [process.pid]
    assert session.finished is True
    assert output.closed is True


def test_owned_process_group_stops_term_then_bounded_kill_without_foreign_signal():
    module = _module()
    process = _FakeProcess(waits=(-signal.SIGKILL,))
    owned = module.OwnedProcess(
        process=process,
        pid=process.pid,
        pgid=process.pid,
        sid=process.pid,
    )
    signals = []
    group = [(process.pid, process.pid)]
    killed = False

    def killpg(pgid, signum):
        nonlocal killed
        signals.append((pgid, signum))
        if signum == signal.SIGKILL:
            killed = True

    def members(_pgid):
        return tuple(group) if process.returncode is None else ()

    module.stop_owned_process_group(
        owned,
        getpgid=lambda pid: pid,
        getsid=lambda pid: pid,
        group_members=members,
        killpg=killpg,
        peek_exit=lambda _owned: -signal.SIGKILL if killed else None,
        monotonic=iter((0.0, 3.0, 4.0)).__next__,
        sleep=lambda _seconds: None,
    )

    assert signals == [
        (process.pid, signal.SIGTERM),
        (process.pid, signal.SIGKILL),
    ]
    assert process.wait_timeouts == [5]

    foreign = _FakeProcess(pid=54321)
    foreign_owned = module.OwnedProcess(
        process=foreign,
        pid=foreign.pid,
        pgid=foreign.pid,
        sid=foreign.pid,
    )
    signals.clear()
    with pytest.raises(module.HarnessSafetyError, match="process-group ownership"):
        module.stop_owned_process_group(
            foreign_owned,
            getpgid=lambda _pid: 99999,
            getsid=lambda pid: pid,
            group_members=lambda _pgid: ((foreign.pid, 99999),),
            killpg=lambda pgid, signum: signals.append((pgid, signum)),
        )
    assert signals == []
    assert foreign.poll() is None

    undiscovered = _FakeProcess(pid=54322)
    with pytest.raises(module.HarnessSafetyError, match="process-group ownership"):
        module.stop_owned_process_group(
            module.OwnedProcess(
                process=undiscovered,
                pid=undiscovered.pid,
                pgid=undiscovered.pid,
                sid=undiscovered.pid,
            ),
            getpgid=lambda pid: pid,
            getsid=lambda pid: pid,
            group_members=lambda _pgid: (),
            killpg=lambda pgid, signum: signals.append((pgid, signum)),
            peek_exit=lambda _owned: None,
        )
    assert signals == []


def test_owned_process_group_keeps_leader_unreaped_until_descendants_are_absent():
    module = _module()
    process = _FakeProcess(pid=43210)
    owned = module.OwnedProcess(
        process=process,
        pid=process.pid,
        pgid=process.pid,
        sid=process.pid,
    )
    stage = {"value": "running"}
    observations = []

    def peek_exit(_owned):
        return None if stage["value"] == "running" else 0

    def members(_pgid):
        observations.append((stage["value"], process.returncode))
        if process.returncode is not None:
            return ()
        if stage["value"] == "running":
            return ((43210, 43210), (43211, 43210))
        return ((43210, 43210),)

    signals = []

    def killpg(pgid, signum):
        signals.append((pgid, signum, process.returncode))
        stage["value"] = "leader-zombie"

    returncode = module.stop_owned_process_group(
        owned,
        getpgid=lambda pid: pid,
        getsid=lambda pid: pid,
        group_members=members,
        killpg=killpg,
        peek_exit=peek_exit,
        monotonic=iter((0.0, 0.1)).__next__,
        sleep=lambda _seconds: None,
    )

    assert returncode == 0
    assert signals == [(43210, signal.SIGTERM, None)]
    assert observations == [
        ("running", None),
        ("leader-zombie", None),
        ("leader-zombie", 0),
    ]
    assert process.wait_timeouts == [5]


def test_waitid_exit_peek_uses_wnowait_and_never_reaps():
    module = _module()
    process = _FakeProcess(pid=43210)
    owned = module.OwnedProcess(process, process.pid, process.pid, process.pid)
    calls = []
    result = types.SimpleNamespace(
        si_pid=process.pid,
        si_code=getattr(os, "CLD_EXITED", 1),
        si_status=7,
    )

    observed = module._peek_owned_exit(
        owned,
        waitid=lambda idtype, pid, options: (
            calls.append((idtype, pid, options)), result
        )[1],
    )

    assert observed == 7
    assert calls[0][0] == os.P_PID
    assert calls[0][1] == process.pid
    assert calls[0][2] & os.WNOWAIT
    assert calls[0][2] & os.WNOHANG
    assert process.returncode is None

def test_owned_process_group_rejects_already_reaped_leader_before_any_group_signal():
    module = _module()
    leader = _FakeProcess(pid=43210)
    leader.returncode = 0
    owned = module.OwnedProcess(
        process=leader,
        pid=leader.pid,
        pgid=leader.pid,
        sid=leader.pid,
    )
    signals = []

    with pytest.raises(module.HarnessSafetyError, match="reaped before cleanup"):
        module.stop_owned_process_group(
            owned,
            getpgid=lambda _pid: pytest.fail("must not inspect a reused PID"),
            getsid=lambda _pid: pytest.fail("must not inspect a reused PID"),
            group_members=lambda _pgid: ((99999, 99999),),
            killpg=lambda pgid, signum: signals.append((pgid, signum)),
        )
    assert signals == []


def test_server_startup_exit_is_detected_without_group_discovery():
    module = _module()
    process = _FakeProcess()
    process.returncode = 7
    owned = module.OwnedProcess(
        process=process,
        pid=process.pid,
        pgid=process.pid,
        sid=process.pid,
    )

    with pytest.raises(module.HarnessSafetyError, match="exited before readiness"):
        module.require_owned_process_alive(
            owned,
            getpgid=lambda pid: pid,
            getsid=lambda pid: pid,
            peek_exit=lambda _owned: 7,
        )
    with pytest.raises(module.HarnessSafetyError, match="process-group ownership"):
        module.require_owned_process_alive(
            owned,
            getpgid=lambda _pid: 99999,
            getsid=lambda pid: pid,
        )


def test_atomic_json_is_canonical_mode_0600_and_replace_failure_stays_incomplete(tmp_path):
    module = _module()
    target = tmp_path / "manifest.json"
    module.atomic_write_json(target, {"status": "FAILED", "z": 1})

    assert target.read_bytes() == b'{"status":"FAILED","z":1}\n'
    assert stat.S_IMODE(target.lstat().st_mode) == 0o600

    incomplete = tmp_path / "incomplete.json"

    def fail_replace(_source, _target):
        raise OSError("injected replace failure")

    with pytest.raises(module.HarnessSafetyError, match="atomic evidence write"):
        module.atomic_write_json(
            incomplete,
            {"status": "COMPLETE"},
            replace=fail_replace,
            nonce=lambda: "fixednonce",
        )
    assert not incomplete.exists()
    assert target.exists()
    assert not any(path.name == "incomplete.json" and path.is_file() for path in tmp_path.iterdir())


def test_pinned_run_root_rejects_ancestor_inode_swap_and_hardlink_target(tmp_path):
    module = _module()
    plan = module.create_run_plan(_repository(tmp_path), HEAD)

    plan.root.chmod(0o500)
    with pytest.raises(module.HarnessSafetyError, match="run root identity"):
        module.assert_run_plan_identity(plan)
    plan.root.chmod(0o700)

    original_root = plan.root.with_name(plan.root.name + "-detached")
    plan.root.rename(original_root)
    plan.root.mkdir(mode=0o700)

    with pytest.raises(module.HarnessSafetyError, match="run root identity"):
        module.atomic_write_json(
            plan.root / "evidence.json",
            {"safe": True},
            pinned_plan=plan,
        )
    assert not (plan.root / "evidence.json").exists()
    assert not (original_root / "evidence.json").exists()

    plan.root.rmdir()
    original_root.rename(plan.root)
    first = plan.root / "first.json"
    first.write_bytes(b"{}\n")
    hardlink = plan.root / "hardlink.json"
    os.link(first, hardlink)
    with pytest.raises(module.HarnessSafetyError, match="unsafe"):
        module.atomic_write_json(hardlink, {"safe": True}, pinned_plan=plan)


def test_pinned_run_file_read_rejects_nested_ancestor_swap(tmp_path):
    module = _module()
    plan = module.create_run_plan(_repository(tmp_path), HEAD)
    plan.screenshots.mkdir(mode=0o700)
    evidence = plan.screenshots / "evidence.bin"
    evidence.write_bytes(b"reviewed evidence")
    detached = plan.root / "screenshots-detached"

    def swap_ancestor():
        plan.screenshots.rename(detached)
        plan.screenshots.mkdir(mode=0o700)
        (plan.screenshots / evidence.name).write_bytes(b"replacement evidence")

    with pytest.raises(module.HarnessSafetyError, match="ancestor identity"):
        module._read_pinned_run_file(
            plan,
            evidence,
            max_bytes=1024,
            before_read=swap_ancestor,
        )


def test_protected_resource_and_dotenv_reads_are_descriptor_safe_and_nofollow(
    tmp_path,
):
    module = _module()
    repository = _repository(tmp_path)
    dotenv = repository / ".env"
    dotenv.write_text("DEEPSEEK_API_KEY=reviewed-value\n", encoding="utf-8")
    loader_calls = []

    def loader(**kwargs):
        loader_calls.append(kwargs)
        dotenv.write_text("DEEPSEEK_API_KEY=substituted-value\n", encoding="utf-8")
        return {
            line.split("=", 1)[0]: line.split("=", 1)[1]
            for line in kwargs["stream"].read().splitlines()
        }

    assert module.read_dotenv_values(repository, loader=loader) == {
        "DEEPSEEK_API_KEY": "reviewed-value"
    }
    assert set(loader_calls[0]) == {"interpolate", "stream", "verbose"}

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "protected.db").write_bytes(b"outside")
    (repository / "linked").symlink_to(outside, target_is_directory=True)
    with pytest.raises(module.HarnessSafetyError, match="protected resource"):
        module._file_evidence(repository / "linked" / "protected.db")

    dotenv.unlink()
    dotenv.symlink_to(outside / "protected.db")
    with pytest.raises(module.HarnessSafetyError, match="configuration file"):
        module.read_dotenv_values(repository, loader=loader)


def test_sqlite_shadow_copies_descriptor_pinned_bytes_without_path_read(
    tmp_path,
    monkeypatch,
):
    module = _module()
    database = tmp_path / "protected.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE proof (value TEXT NOT NULL)")
        connection.execute("INSERT INTO proof VALUES ('reviewed')")

    def reject_path_read(_path):
        raise AssertionError("protected SQLite bytes must be read through a descriptor")

    monkeypatch.setattr(Path, "read_bytes", reject_path_read)
    with module._sqlite_shadow(database) as shadow, sqlite3.connect(
        f"{shadow.as_uri()}?mode=ro",
        uri=True,
    ) as connection:
        assert connection.execute("SELECT value FROM proof").fetchone() == ("reviewed",)


def test_avatar_provenance_decodes_the_same_pinned_bytes_it_hashes(tmp_path, monkeypatch):
    module = _module()
    plan = module.create_run_plan(_repository(tmp_path), HEAD)
    plan.media.mkdir(mode=0o700)
    avatar_id = "00000000-0000-4000-8000-000000000099"
    avatar_path = plan.media / f"{avatar_id}.webp"
    from PIL import Image

    Image.new("RGB", (9, 7), (17, 31, 47)).save(avatar_path, "WEBP", lossless=True)
    payload = avatar_path.read_bytes()
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        "CREATE TABLE children (id INTEGER PRIMARY KEY, avatar TEXT);"
        "CREATE TABLE avatar_media (id TEXT PRIMARY KEY, file_name TEXT, "
        "mime_type TEXT, width INTEGER, height INTEGER, size_bytes INTEGER, "
        "sha256 TEXT);"
    )
    connection.execute(
        "INSERT INTO children VALUES (?, ?)",
        (1, f"/api/media/avatars/{avatar_id}"),
    )
    connection.execute(
        "INSERT INTO avatar_media VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            avatar_id,
            avatar_path.name,
            "image/webp",
            9,
            7,
            len(payload),
            hashlib.sha256(payload).hexdigest(),
        ),
    )
    original_open = Image.open

    def pinned_open(source, *args, **kwargs):
        assert isinstance(source, io.BytesIO)
        return original_open(source, *args, **kwargs)

    monkeypatch.setattr(Image, "open", pinned_open)
    module._avatar_provenance(
        connection,
        plan,
        owner_table="children",
        owner_id=1,
        avatar_id=avatar_id,
    )


def _install_server_source_boundary(run_root: Path) -> dict[str, str]:
    source_root = run_root / "reviewed-source"
    source_file = source_root / "app/backend/__init__.py"
    source_file.parent.mkdir(parents=True)
    source_payload = b"REVIEWED = True\n"
    source_file.write_bytes(source_payload)
    source_head = "b" * 40
    source_tree = "c" * 40
    source_manifest = run_root / "reviewed-source.json"
    source_manifest.write_text(
        json.dumps(
            {
                "files": [
                    {
                        "blob_oid": hashlib.sha1(
                            f"blob {len(source_payload)}\0".encode("ascii")
                            + source_payload,
                            usedforsecurity=False,
                        ).hexdigest(),
                        "git_mode": 0o100644,
                        "path": "app/backend/__init__.py",
                        "sha256": hashlib.sha256(source_payload).hexdigest(),
                        "size": len(source_payload),
                    }
                ],
                "object_format": "sha1",
                "protocol": "pomegranagent-reviewed-source/v1",
                "source_head": source_head,
                "tree_oid": source_tree,
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    os.chmod(source_file, 0o400)
    os.chmod(source_file.parent, 0o500)
    os.chmod(source_file.parent.parent, 0o500)
    os.chmod(source_root, 0o500)
    return {
        "APP_REVIEWED_SOURCE_HEAD": source_head,
        "APP_REVIEWED_SOURCE_MANIFEST": str(source_manifest),
        "APP_REVIEWED_SOURCE_ROOT": str(source_root),
        "APP_REVIEWED_SOURCE_TREE_OID": source_tree,
    }


def test_live_server_retains_runtime_root_and_resource_inode_identity(tmp_path):
    server = importlib.import_module("scripts.live_provider_uat_server")
    run_root = (tmp_path / "retained-run").resolve()
    run_root.mkdir(mode=0o700)
    database = run_root / "duck-diary-uat.db"
    database.write_bytes(b"sqlite-placeholder")
    (run_root / "media").mkdir(mode=0o700)
    (run_root / "tts-cache").mkdir(mode=0o700)
    (run_root / "logs").mkdir(mode=0o700)
    (run_root / "logs/app.log").write_bytes(b"")
    environment = {
        "APP_BUSINESS_TIMEZONE": "Asia/Shanghai",
        "APP_DB_MODE": "app",
        "APP_DB_PATH": str(database),
        "APP_LOG_PATH": str(run_root / "logs/app.log"),
        "APP_MEDIA_ROOT": str(run_root / "media"),
        **_install_server_source_boundary(run_root),
        "APP_TTS_CACHE_PATH": str(run_root / "tts-cache"),
        "DEEPSEEK_API_KEY": "sk-server-secret-1234567890",
        "DEEPSEEK_BASE_URL": "https://api.deepseek.example/v1",
        "DEEPSEEK_MAX_TOKENS": "8192",
        "DEEPSEEK_MODEL": "deepseek-safe-model",
        "DEEPSEEK_TIMEOUT": "120",
        "PATH": "/synthetic/bin",
        "PYTHONNOUSERSITE": "1",
        "PYTHON_DOTENV_DISABLED": "1",
        "TZ": "Asia/Shanghai",
    }
    paths = server.validate_child_environment(environment)
    server.assert_runtime_paths_pinned(paths)

    detached = run_root.with_name("retained-run-detached")
    run_root.rename(detached)
    run_root.mkdir(mode=0o700)
    (run_root / "duck-diary-uat.db").write_bytes(b"replacement")
    (run_root / "media").mkdir(mode=0o700)
    (run_root / "tts-cache").mkdir(mode=0o700)
    (run_root / "logs").mkdir(mode=0o700)
    (run_root / "logs/app.log").write_bytes(b"")
    with pytest.raises(server.ServerSafetyError, match="identity"):
        server.assert_runtime_paths_pinned(paths)


def test_failed_finalization_retains_run_and_never_claims_complete(tmp_path):
    module = _module()
    plan = module.create_run_plan(_repository(tmp_path), HEAD)
    marker = plan.root / "retained.bin"
    marker.write_bytes(b"retain on every failure")

    module.finalize_failed_run(plan, reason_code="CONTROLLER_EVIDENCE_MISSING")

    assert marker.read_bytes() == b"retain on every failure"
    manifest = json.loads(plan.manifest.read_text(encoding="utf-8"))
    assert manifest == {
        "protocol": "pomegranagent-live-uat-manifest/v1",
        "reason_code": "CONTROLLER_EVIDENCE_MISSING",
        "run_id": plan.run_id,
        "source_head": HEAD,
        "status": "FAILED",
    }
    with pytest.raises(module.HarnessSafetyError, match="reason code"):
        module.finalize_failed_run(plan, reason_code="secret provider error text")


def test_complete_manifest_is_never_replaced_after_terminal_commit(tmp_path):
    module = _module()
    plan = module.create_run_plan(_repository(tmp_path), HEAD)
    unverified = {
        "protocol": "pomegranagent-live-uat-manifest/v1",
        "run_id": plan.run_id,
        "source_head": HEAD,
        "status": "COMPLETE",
    }
    module.atomic_write_json(plan.manifest, unverified, pinned_plan=plan)

    with pytest.raises(module.HarnessSafetyError, match="cannot be replaced"):
        module.finalize_failed_run(plan, reason_code="SAFETY_FAILURE")
    assert json.loads(plan.manifest.read_text(encoding="utf-8")) == unverified


def test_complete_manifest_rejects_blocker_issue_even_after_controller_validation(tmp_path):
    module = _module()
    plan = module.create_run_plan(_repository(tmp_path), HEAD)
    controller = {
        "human_uat_required": [{}],
        "issues": [
            {
                "safe_summary": "release blocker",
                "severity": "blocker",
                "step_id": "review_edit_confirm",
            }
        ],
        "screenshots": [],
    }
    with pytest.raises(module.HarnessSafetyError, match="blocker"):
        module._complete_manifest(
            plan,
            seed_result={"media_sha256": "1" * 64, "record_sha256": "2" * 64},
            controller=controller,
            provider_summary={"events": []},
            provenance={"status": "PROVEN"},
        )


def test_terminal_inventory_crosslinks_exact_manifest_screenshot_and_provider_bytes(
    tmp_path,
):
    module = _module()
    plan = module.create_run_plan(_repository(tmp_path), HEAD)
    plan.screenshots.mkdir(mode=0o700)
    plan.tts_cache.mkdir(mode=0o700)
    screenshot = plan.screenshots / "reviewed.png"
    screenshot.write_bytes(_png(16, 9))
    cache = plan.tts_cache / "reviewed.mp3"
    cache.write_bytes(b"reviewed audio bytes")
    screenshot_sha = hashlib.sha256(screenshot.read_bytes()).hexdigest()
    cache_sha = hashlib.sha256(cache.read_bytes()).hexdigest()
    provider_summary = {
        "events": [
            {
                "cache_relative_path": "tts-cache/reviewed.mp3",
                "cache_sha256": cache_sha,
                "operation": "tts",
            }
        ],
        "protocol": "pomegranagent-live-uat-telemetry-summary/v1",
    }
    module.atomic_write_json(
        plan.provider_summary,
        provider_summary,
        pinned_plan=plan,
    )
    manifest = {
        "screenshots": [
            {
                "relative_path": "screenshots/reviewed.png",
                "sha256": screenshot_sha,
            }
        ],
        "status": "COMPLETE",
    }
    manifest_payload = module.canonical_json_line(manifest).encode("utf-8")
    checksums_payload = module._checksum_lines(plan, manifest_payload)
    module._write_owned_bytes(plan.checksums, checksums_payload, pinned_plan=plan)
    module._verify_complete_precommit_state(
        plan,
        manifest_payload=manifest_payload,
        checksums_payload=checksums_payload,
        provider_summary=provider_summary,
    )

    forged = json.loads(json.dumps(provider_summary))
    forged["events"][0]["cache_sha256"] = "f" * 64
    with pytest.raises(module.HarnessSafetyError, match="terminal inventory"):
        module._verify_complete_precommit_state(
            plan,
            manifest_payload=manifest_payload,
            checksums_payload=checksums_payload,
            provider_summary=forged,
        )


def test_manifest_payload_uses_full_secret_scanner_before_and_after_write(tmp_path):
    module = _module()
    plan = module.create_run_plan(_repository(tmp_path), HEAD)
    secret = "sk-manifest-only-secret-value"
    unsafe_payloads = (
        module.canonical_json_line(
            {"status": "COMPLETE", "safe_summary": "Authorization: redacted"}
        ).encode("utf-8"),
        module.canonical_json_line(
            {"status": "COMPLETE", "safe_summary": secret}
        ).encode("utf-8"),
    )
    for payload in unsafe_payloads:
        with pytest.raises(module.HarnessSafetyError, match="manifest") as caught:
            module._assert_secret_free_payload(
                payload,
                actual_secrets=(secret,),
                role="manifest",
            )
        assert secret not in str(caught.value)

    safe_manifest = {"status": "COMPLETE", "safe_summary": "reviewed"}
    safe_payload = module.canonical_json_line(safe_manifest).encode("utf-8")
    module._assert_secret_free_payload(
        safe_payload,
        actual_secrets=(secret,),
        role="manifest",
    )
    module.atomic_write_json(plan.manifest, safe_manifest, pinned_plan=plan)
    written = module._read_pinned_run_file(
        plan,
        plan.manifest,
        max_bytes=1_000_000,
    )
    assert written == safe_payload
    module._assert_secret_free_payload(
        written,
        actual_secrets=(secret,),
        role="manifest",
    )


class _GitState:
    def __init__(self, root: Path):
        self.root = root
        self.head = HEAD
        self.status = b"?? user-note.txt\0"

    def run(self, argv, **kwargs):
        assert kwargs == {"cwd": self.root, "capture_output": True, "check": False}
        if tuple(argv) == ("git", "rev-parse", "HEAD"):
            return types.SimpleNamespace(returncode=0, stdout=(self.head + "\n").encode(), stderr=b"")
        if tuple(argv) == ("git", "status", "--porcelain=v1", "-z", "--untracked-files=all"):
            return types.SimpleNamespace(returncode=0, stdout=self.status, stderr=b"")
        raise AssertionError(tuple(argv))


def _protected_repository(tmp_path: Path):
    root = _repository(tmp_path)
    (root / "data/tts_cache").mkdir(parents=True)
    (root / "data/media").mkdir()
    (root / "logs").mkdir()
    (root / "logs/app.log").write_bytes(b"main-log")
    (root / "data/tts_cache/voice.mp3").write_bytes(b"main-tts")
    (root / "data/media/avatar.webp").write_bytes(b"main-media")
    (root / "user-note.txt").write_bytes(b"dirty-user-content")
    database = root / "data/duck_diary.db"
    connection = sqlite3.connect(database)
    assert connection.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    connection.execute("CREATE TABLE evidence (value TEXT NOT NULL)")
    connection.execute("INSERT INTO evidence VALUES ('before')")
    connection.commit()
    return root, connection, _GitState(root)


@pytest.mark.parametrize("mutation", ("database", "log", "tts", "media", "dirty", "head", "porcelain"))
def test_protected_resource_snapshot_fails_each_independent_drift(tmp_path, mutation):
    module = _module()
    root, connection, git = _protected_repository(tmp_path)
    try:
        before = module.capture_protected_resources(root, runner=git.run)
        if mutation == "database":
            connection.execute("INSERT INTO evidence VALUES ('after')")
            connection.commit()
        elif mutation == "log":
            (root / "logs/app.log").write_bytes(b"changed-log")
        elif mutation == "tts":
            (root / "data/tts_cache/voice.mp3").write_bytes(b"changed-tts")
        elif mutation == "media":
            (root / "data/media/avatar.webp").write_bytes(b"changed-media")
        elif mutation == "dirty":
            (root / "user-note.txt").write_bytes(b"changed-user-content")
        elif mutation == "head":
            git.head = "b" * 40
        elif mutation == "porcelain":
            git.status = b" M user-note.txt\0"
        else:
            raise AssertionError(mutation)
        after = module.capture_protected_resources(root, runner=git.run)
    finally:
        connection.close()

    with pytest.raises(module.HarnessSafetyError, match="protected resource drift") as caught:
        module.assert_protected_resources_equal(before, after)
    assert mutation.upper() in str(caught.value)
    assert before["database"]["logical_digest"]
    assert before["database"]["database"]["kind"] == "regular"
    assert before["database"]["wal"]["kind"] == "regular"
    assert before["database"]["shm"]["kind"] == "regular"
    assert before["dirty_paths"][0]["relative_path"] == "user-note.txt"


def test_unchanged_protected_snapshot_and_read_only_database_capture_pass(tmp_path):
    module = _module()
    root, connection, git = _protected_repository(tmp_path)
    try:
        database = root / "data/duck_diary.db"
        physical_before = {
            suffix: Path(f"{database}{suffix}").read_bytes()
            for suffix in ("", "-wal", "-shm")
        }
        first = module.capture_protected_resources(root, runner=git.run)
        second = module.capture_protected_resources(root, runner=git.run)
        module.assert_protected_resources_equal(first, second)
        physical_after = {
            suffix: Path(f"{database}{suffix}").read_bytes()
            for suffix in ("", "-wal", "-shm")
        }
        assert physical_after == physical_before
    finally:
        connection.close()


def test_secret_scan_uses_actual_values_and_patterns_without_echoing_matches(tmp_path):
    module = _module()
    plan = module.create_run_plan(_repository(tmp_path), HEAD)
    safe_file = plan.root / "safe.json"
    safe_file.write_text('{"status":"ok"}\n', encoding="utf-8")
    module.scan_retained_artifacts(
        plan.root,
        provider_secrets=("sk-actual-secret-123456",),
        runtime_secrets=("483921",),
    )

    cases = (
        b"sk-actual-secret-123456",
        b"483921",
        b"Authorization: redacted",
        b"Bearer redacted",
        b"duck_teacher_session=redacted",
        b"Set-Cookie: redacted",
        b"Cookie: redacted",
        b"auth_token=redacted",
    )
    for index, content in enumerate(cases):
        candidate = plan.root / f"unsafe-{index}.bin"
        candidate.write_bytes(content)
        with pytest.raises(module.HarnessSafetyError, match="secret scan failed") as caught:
            module.scan_retained_artifacts(
                plan.root,
                provider_secrets=("sk-actual-secret-123456",),
                runtime_secrets=("483921",),
            )
        assert "actual-secret" not in str(caught.value)
        assert "483921" not in str(caught.value)
        candidate.unlink()


def test_secret_scan_scopes_teacher_pin_to_runtime_generated_evidence(tmp_path):
    module = _module()
    plan = module.create_run_plan(_repository(tmp_path), HEAD)
    provider_key = "sk-provider-scope-secret-123456"
    teacher_pin = "483921"
    reviewed_source = plan.root / "reviewed-source"
    reviewed_source.mkdir(mode=0o700)
    reviewed_file = reviewed_source / "existing-literal.py"
    reviewed_file.write_text(f"EXAMPLE_CODE = {teacher_pin}\n", encoding="utf-8")

    module.scan_retained_artifacts(
        plan.root,
        provider_secrets=(provider_key,),
        runtime_secrets=(teacher_pin,),
    )

    reviewed_file.write_text(f"PROVIDER = {provider_key!r}\n", encoding="utf-8")
    with pytest.raises(module.HarnessSafetyError, match="secret scan failed"):
        module.scan_retained_artifacts(
            plan.root,
            provider_secrets=(provider_key,),
            runtime_secrets=(teacher_pin,),
        )

    reviewed_file.write_text(f"EXAMPLE_CODE = {teacher_pin}\n", encoding="utf-8")
    runtime_file = plan.root / "journey.json"
    runtime_file.write_text(
        json.dumps({"accidental_pin": teacher_pin}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(module.HarnessSafetyError, match="secret scan failed"):
        module.scan_retained_artifacts(
            plan.root,
            provider_secrets=(provider_key,),
            runtime_secrets=(teacher_pin,),
        )


def _png(width: int, height: int) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)

    rows = []
    for y in range(height):
        row = bytearray(b"\x6f\xb4\xdd" * width)
        if y < 8:
            for x in range(min(width, 8)):
                row[x * 3 : x * 3 + 3] = bytes((20 + x, 40 + y, 90))
        rows.append(b"\x00" + bytes(row))
    scanlines = b"".join(rows)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(scanlines, level=9))
        + chunk(b"IEND", b"")
    )


def _png_with_ztxt(width: int, height: int, value: str) -> bytes:
    payload = _png(width, height)
    compressed = zlib.compress(value.encode("utf-8"), level=9)
    data = b"Comment\x00\x00" + compressed
    chunk = (
        struct.pack(">I", len(data))
        + b"zTXt"
        + data
        + struct.pack(">I", zlib.crc32(b"zTXt" + data) & 0xFFFFFFFF)
    )
    return payload[:-12] + chunk + payload[-12:]


def _controller_payload(module, plan):
    entities = {
        "analysis_job_id": 501,
        "assessment_id": 601,
        "child_avatar_id": "11111111-1111-4111-8111-111111111111",
        "chat_request_ids": ["55555555-5555-4555-8555-555555555551"],
        "duck_avatar_id": "22222222-2222-4222-8222-222222222222",
        "growth_after": {},
        "growth_before": {},
        "live_child_id": 101,
        "live_duck_id": 201,
        "live_conversation_id": 301,
        "local_terminal_request_id": None,
        "monthly_pairs": {
            "2026-09-03": [10, 101],
            "2026-09-04": [10, 101],
        },
        "monthly_roster_request_ids": [
            "33333333-3333-4333-8333-333333333331",
            "33333333-3333-4333-8333-333333333332",
        ],
        "provider_chat_request_ids": [
            "55555555-5555-4555-8555-555555555551"
        ],
        "search_cursor": "cursor",
        "search_deep_link": "#review?conversation_id=301",
        "search_page_one_ids": [301, 30, 29, 28, 27],
        "search_page_two_ids": [26],
        "search_request": {"keyword": "我"},
        "search_result_conversation_id": 301,
        "tts_evidence": [],
        "weekly_metrics_after": {},
        "weekly_metrics_before": {},
        "weekly_week_start": "2026-08-31",
    }
    journey = [
        {
            "entity_ids": {
                key: entities[key]
                for key in STEP_PROVENANCE_KEYS[step_id]
            },
            "status": "PASS",
            "step_id": step_id,
            "visible_assertions": ["approved visible state"],
        }
        for step_id in module.REQUIRED_JOURNEY_STEPS
    ]
    screenshot_specs = (
        ("teacher-management", "teacher", "child_duck_avatar_management", "1024x768"),
        ("teacher-review-confirmed", "teacher", "review_edit_confirm", "1440x900"),
        ("teacher-weekly-growth", "teacher", "weekly_metrics_growth", "1024x768"),
        ("teacher-search-deep-link", "teacher", "advanced_search_pagination_deep_link", "1440x900"),
        ("child-avatar-selected", "child", "child_duck_avatar_management", "1024x576"),
        ("child-conversation-complete", "child", "child_conversation_real_provider_tts", "1280x720"),
    )
    screenshots = []
    for state_id, surface, journey_step, viewport in screenshot_specs:
        semantic = state_id
        width, height = (int(part) for part in viewport.split("x"))
        (plan.screenshots / f"{semantic}.png").write_bytes(_png(width, height))
        screenshots.append(
            {
                "journey_step": journey_step,
                "relative_path": f"screenshots/{semantic}.png",
                "semantic_name": semantic,
                "state_id": state_id,
                "surface": surface,
                "viewport": viewport,
                "visible_assertions": ["approved visible state"],
            }
        )
    return {
        "human_uat_required": [
            {
                "gate_id": "physical_microphone_acoustic_recognition",
                "safe_summary": "physical acoustic path requires a human",
                "status": "HUMAN_UAT_REQUIRED",
            }
        ],
        "issues": [],
        "journey": journey,
        "protocol": "pomegranagent-live-uat-controller/v1",
        "run_id": plan.run_id,
        "screenshots": screenshots,
        "source_head": HEAD,
    }


def _set_controller_entities(payload, entity_ids):
    controller_entities = {
        **entity_ids,
        "monthly_roster_request_ids": [
            attempt["request_id"] for attempt in entity_ids["monthly_roster_attempts"]
        ],
    }
    controller_entities.pop("monthly_roster_attempts")
    for step in payload["journey"]:
        step["entity_ids"] = {
            key: controller_entities[key]
            for key in STEP_PROVENANCE_KEYS[step["step_id"]]
        }
    return payload


def test_controller_evidence_rejects_misplaced_or_private_step_provenance(tmp_path):
    module = _module()
    plan = module.create_run_plan(_repository(tmp_path), HEAD)
    plan.screenshots.mkdir(mode=0o700)
    original = _controller_payload(module, plan)
    by_step = {step["step_id"]: step for step in original["journey"]}

    misplaced = json.loads(json.dumps(original))
    misplaced_steps = {step["step_id"]: step for step in misplaced["journey"]}
    live_child_id = misplaced_steps["child_duck_avatar_management"][
        "entity_ids"
    ].pop("live_child_id")
    misplaced_steps["invalid_avatar_rejection"]["entity_ids"][
        "live_child_id"
    ] = live_child_id

    private = json.loads(json.dumps(original))
    private_steps = {step["step_id"]: step for step in private["journey"]}
    private_steps["monthly_roster_conflict_retry"]["entity_ids"][
        "monthly_roster_attempts"
    ] = []

    assert set(by_step["monthly_roster_conflict_retry"]["entity_ids"]) == {
        "monthly_pairs",
        "monthly_roster_request_ids",
    }
    for invalid in (misplaced, private):
        module.atomic_write_json(plan.controller_evidence, invalid, pinned_plan=plan)
        with pytest.raises(module.HarnessSafetyError, match="journey"):
            module.validate_controller_evidence(plan)


def test_private_roster_telemetry_is_injected_from_visible_request_ids(tmp_path):
    module = _module()
    plan = module.create_run_plan(_repository(tmp_path), HEAD)
    plan.screenshots.mkdir(mode=0o700)
    payload = _controller_payload(module, plan)
    module.atomic_write_json(plan.controller_evidence, payload, pinned_plan=plan)
    controller = module.validate_controller_evidence(plan)
    controller_entities = module._collect_entity_ids(controller)
    request_ids = controller_entities["monthly_roster_request_ids"]
    events = (
        {
            "canonical_body_sha256": "a" * 64,
            "error_code": "ROSTER_DATE_CONFLICT",
            "kind": "roster_attempt",
            "method": "POST",
            "order": 1,
            "path": "/api/roster/month",
            "replace_existing": False,
            "request_id": request_ids[0],
            "status": 409,
        },
        {
            "canonical_body_sha256": "a" * 64,
            "error_code": None,
            "kind": "roster_attempt",
            "method": "POST",
            "order": 2,
            "path": "/api/roster/month",
            "replace_existing": True,
            "request_id": request_ids[1],
            "status": 200,
        },
    )

    enriched = module._inject_private_roster_provenance(events, controller_entities)

    assert "monthly_roster_attempts" not in controller_entities
    assert enriched["monthly_roster_attempts"] == list(events)
    assert enriched["monthly_roster_request_ids"] == request_ids
    for invalid in (
        ({**events[0], "request_id": "99999999-9999-4999-8999-999999999999"}, events[1]),
        (*events, events[1]),
    ):
        with pytest.raises(module.HarnessSafetyError, match="roster evidence"):
            module._inject_private_roster_provenance(tuple(invalid), controller_entities)


def test_controller_evidence_binds_four_viewports_dimensions_and_screenshot_hashes(tmp_path):
    module = _module()
    plan = module.create_run_plan(_repository(tmp_path), HEAD)
    plan.screenshots.mkdir(mode=0o700)
    payload = _controller_payload(module, plan)
    module.atomic_write_json(plan.controller_evidence, payload)

    validated = module.validate_controller_evidence(plan)

    assert validated["journey"] == payload["journey"]
    assert {item["viewport"] for item in validated["screenshots"]} == {
        "1024x768",
        "1440x900",
        "1024x576",
        "1280x720",
    }
    for screenshot in validated["screenshots"]:
        path = plan.root / screenshot["relative_path"]
        assert screenshot["byte_size"] == path.stat().st_size
        assert screenshot["sha256"] == __import__("hashlib").sha256(path.read_bytes()).hexdigest()
        assert screenshot["source_run_id"] == plan.run_id


def test_controller_evidence_rejects_traversal_wrong_dimensions_and_changed_file(tmp_path):
    module = _module()
    plan = module.create_run_plan(_repository(tmp_path), HEAD)
    plan.screenshots.mkdir(mode=0o700)
    payload = _controller_payload(module, plan)
    original = json.loads(json.dumps(payload))

    payload["screenshots"][0]["relative_path"] = "screenshots/../escape.png"
    module.atomic_write_json(plan.controller_evidence, payload)
    with pytest.raises(module.HarnessSafetyError, match="controller evidence"):
        module.validate_controller_evidence(plan)

    payload = json.loads(json.dumps(original))
    first_path = plan.root / payload["screenshots"][0]["relative_path"]
    first_path.write_bytes(_png(1, 1))
    module.atomic_write_json(plan.controller_evidence, payload)
    with pytest.raises(module.HarnessSafetyError, match="screenshot"):
        module.validate_controller_evidence(plan)

    first_path.write_bytes(_png(1024, 768))

    def mutate_after_decode(path):
        if path == first_path:
            path.write_bytes(_png(1024, 768) + b"changed")

    with pytest.raises(module.HarnessSafetyError, match="screenshot changed"):
        module.validate_controller_evidence(plan, after_decode=mutate_after_decode)


def test_controller_evidence_requires_exact_human_gate_and_screenshot_state_mapping(
    tmp_path,
):
    module = _module()
    plan = module.create_run_plan(_repository(tmp_path), HEAD)
    plan.screenshots.mkdir(mode=0o700)
    original = _controller_payload(module, plan)

    mutations = []
    zero_gate = json.loads(json.dumps(original))
    zero_gate["human_uat_required"] = []
    mutations.append(zero_gate)
    wrong_surface = json.loads(json.dumps(original))
    wrong_surface["screenshots"][0]["surface"] = "child"
    mutations.append(wrong_surface)
    duplicate_state = json.loads(json.dumps(original))
    duplicate_state["screenshots"][1]["state_id"] = duplicate_state["screenshots"][0]["state_id"]
    mutations.append(duplicate_state)
    wrong_step = json.loads(json.dumps(original))
    wrong_step["screenshots"][0]["journey_step"] = "review_edit_confirm"
    mutations.append(wrong_step)

    for mutation in mutations:
        module.atomic_write_json(plan.controller_evidence, mutation, pinned_plan=plan)
        with pytest.raises(module.HarnessSafetyError, match="controller evidence"):
            module.validate_controller_evidence(plan)

    blank = json.loads(json.dumps(original))
    blank_path = plan.root / blank["screenshots"][0]["relative_path"]
    from PIL import Image

    Image.new("RGB", (1024, 768), (255, 255, 255)).save(blank_path, "PNG")
    module.atomic_write_json(plan.controller_evidence, blank, pinned_plan=plan)
    with pytest.raises(module.HarnessSafetyError, match="blank"):
        module.validate_controller_evidence(plan)


@pytest.mark.parametrize(
    "first_state,second_state",
    (
        ("teacher-management", "teacher-review-confirmed"),
        ("child-avatar-selected", "child-conversation-complete"),
    ),
)
def test_controller_evidence_rejects_state_viewport_swaps_even_when_global_set_matches(
    tmp_path,
    first_state,
    second_state,
):
    module = _module()
    plan = module.create_run_plan(_repository(tmp_path), HEAD)
    plan.screenshots.mkdir(mode=0o700)
    payload = _controller_payload(module, plan)
    by_state = {item["state_id"]: item for item in payload["screenshots"]}
    first = by_state[first_state]
    second = by_state[second_state]
    first["viewport"], second["viewport"] = second["viewport"], first["viewport"]
    for item in (first, second):
        width, height = (int(part) for part in item["viewport"].split("x"))
        (plan.root / item["relative_path"]).write_bytes(_png(width, height))
    module.atomic_write_json(plan.controller_evidence, payload, pinned_plan=plan)

    with pytest.raises(module.HarnessSafetyError, match="screenshot"):
        module.validate_controller_evidence(plan)


def test_compressed_png_metadata_secret_is_rejected_without_echo(tmp_path):
    module = _module()
    plan = module.create_run_plan(_repository(tmp_path), HEAD)
    plan.screenshots.mkdir(mode=0o700)
    payload = _controller_payload(module, plan)
    secret = "sk-compressed-metadata-secret-123456"
    screenshot = payload["screenshots"][0]
    width, height = (int(part) for part in screenshot["viewport"].split("x"))
    (plan.root / screenshot["relative_path"]).write_bytes(
        _png_with_ztxt(width, height, secret)
    )
    module.atomic_write_json(plan.controller_evidence, payload, pinned_plan=plan)

    with pytest.raises(module.HarnessSafetyError, match="metadata") as controller_error:
        module.validate_controller_evidence(plan)
    assert secret not in str(controller_error.value)
    with pytest.raises(module.HarnessSafetyError, match="secret scan") as scan_error:
        module.scan_retained_artifacts(
            plan.root,
            provider_secrets=(secret,),
            runtime_secrets=(),
            pinned_plan=plan,
        )
    assert secret not in str(scan_error.value)


def _create_seed_provenance_database(plan):
    from PIL import Image

    plan.media.mkdir(mode=0o700)
    seed_avatar_id = "00000000-0000-4000-8000-000000000001"
    seed_avatar_path = plan.media / f"{seed_avatar_id}.webp"
    Image.new("RGB", (8, 8), (80, 80, 80)).save(
        seed_avatar_path,
        "WEBP",
        lossless=True,
    )
    seed_avatar = seed_avatar_path.read_bytes()
    with sqlite3.connect(plan.database) as connection:
        connection.executescript(
            """
            CREATE TABLE children (id INTEGER PRIMARY KEY, name TEXT, nickname TEXT, avatar TEXT);
            CREATE TABLE ducks (id INTEGER PRIMARY KEY, name TEXT, avatar TEXT);
            CREATE TABLE avatar_media (id TEXT PRIMARY KEY, file_name TEXT, mime_type TEXT, width INTEGER, height INTEGER, size_bytes INTEGER, sha256 TEXT);
            CREATE TABLE duty_rosters (id INTEGER PRIMARY KEY, cycle TEXT, date TEXT, child_id INTEGER);
            CREATE TABLE roster_requests (request_id TEXT PRIMARY KEY, operation TEXT, payload_hash TEXT, status TEXT, response_json TEXT, last_error_code TEXT, last_error_message TEXT);
            CREATE TABLE conversations (id INTEGER PRIMARY KEY, child_id INTEGER, date TEXT, ended_at TEXT, status TEXT, end_reason TEXT, frozen_last_message_id INTEGER);
            CREATE TABLE messages (id INTEGER PRIMARY KEY, conversation_id INTEGER, role TEXT, text TEXT);
            CREATE TABLE chat_requests (request_id TEXT PRIMARY KEY, child_id INTEGER, conversation_id INTEGER, base_last_message_id INTEGER, child_message_id INTEGER, diary_message_id INTEGER, payload_hash TEXT, status TEXT, attempt_count INTEGER, response_json TEXT);
            CREATE TABLE analysis_jobs (id INTEGER PRIMARY KEY, conversation_id INTEGER, frozen_last_message_id INTEGER, status TEXT, attempt_count INTEGER);
            CREATE TABLE feeding_logs (id INTEGER PRIMARY KEY, conversation_id INTEGER, child_id INTEGER, duck_id INTEGER, category TEXT, content TEXT);
            CREATE TABLE emotion_logs (id INTEGER PRIMARY KEY, conversation_id INTEGER, child_id INTEGER, emotion TEXT, intensity INTEGER, note TEXT);
            CREATE TABLE insight_notes (id INTEGER PRIMARY KEY, conversation_id INTEGER, child_id INTEGER, content TEXT);
            CREATE TABLE assessment_dimensions (id INTEGER PRIMARY KEY, key TEXT, name TEXT, enabled INTEGER);
            CREATE TABLE assessments (id INTEGER PRIMARY KEY, conversation_id INTEGER, child_id INTEGER, status TEXT, overall REAL);
            CREATE TABLE assessment_scores (id INTEGER PRIMARY KEY, assessment_id INTEGER, dimension_id INTEGER, score INTEGER, reason TEXT);
            """
        )
        connection.execute(
            "INSERT INTO avatar_media VALUES (?, ?, 'image/webp', 8, 8, ?, ?)",
            (
                seed_avatar_id,
                seed_avatar_path.name,
                len(seed_avatar),
                hashlib.sha256(seed_avatar).hexdigest(),
            ),
        )
        connection.executemany(
            "INSERT INTO children VALUES (?, ?, ?, ?)",
            (
                (10, "Seed Child", None, f"/api/media/avatars/{seed_avatar_id}"),
                (11, "Seed Partner", None, None),
            ),
        )
        connection.execute("INSERT INTO ducks VALUES (20, 'Seed Duck', NULL)")
        connection.executemany(
            "INSERT INTO assessment_dimensions VALUES (?, ?, ?, ?)",
            (
                (1, "communication", "Communication", 1),
                (2, "observation", "Observation", 1),
                (3, "responsibility", "Responsibility", 1),
                (4, "disabled", "Disabled", 0),
            ),
        )
        seed_search_rows = (
            (25, "2026-08-14", "2026-08-14T02:00:00.000000", "max_rounds"),
            (26, "2026-08-21", "2026-08-21T02:00:00.000000", "complete"),
            (27, "2026-08-28", "2026-08-28T02:00:00.000000", "complete"),
            (28, "2026-08-29", "2026-08-29T02:00:00.000000", "complete"),
            (29, "2026-08-30", "2026-08-30T02:00:00.000000", "complete"),
            (30, "2026-09-01", "2026-09-01T02:00:00.000000", "max_rounds"),
            (31, "2026-09-08", "2026-09-08T02:00:00.000000", "complete"),
        )
        for conversation_id, conversation_date, ended_at, end_reason in seed_search_rows:
            child_message_id = conversation_id * 10
            diary_message_id = child_message_id + 1
            job_id = 100 + conversation_id
            assessment_id = 200 + conversation_id
            connection.execute(
                "INSERT INTO conversations VALUES (?, 10, ?, ?, 'ended', ?, ?)",
                (
                    conversation_id,
                    conversation_date,
                    ended_at,
                    end_reason,
                    diary_message_id,
                ),
            )
            connection.executemany(
                "INSERT INTO messages VALUES (?, ?, ?, ?)",
                (
                    (
                        child_message_id,
                        conversation_id,
                        "child",
                        f"我在 seed 池塘观察 {conversation_id}",
                    ),
                    (diary_message_id, conversation_id, "diary", "seed diary"),
                ),
            )
            connection.execute(
                "INSERT INTO analysis_jobs VALUES (?, ?, ?, 'succeeded', 1)",
                (job_id, conversation_id, diary_message_id),
            )
            connection.execute(
                "INSERT INTO assessments VALUES (?, ?, 10, 'confirmed', 3.0)",
                (assessment_id, conversation_id),
            )
            connection.executemany(
                "INSERT INTO assessment_scores VALUES (?, ?, ?, 3, 'seed reason')",
                tuple(
                    (
                        conversation_id * 100 + dimension_id,
                        assessment_id,
                        dimension_id,
                    )
                    for dimension_id in (1, 2, 3)
                ),
            )
        connection.execute(
            "INSERT INTO feeding_logs VALUES (80, 30, 10, 20, '观察', 'seed observation')"
        )
        connection.commit()


def _search_cursor(
    search_request,
    *,
    conversation_id: int,
    ended_at: str,
    snapshot_max_id: int,
) -> str:
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
    fingerprint = hashlib.sha256(
        json.dumps(
            fingerprint_source,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    raw = json.dumps(
        {
            "ended_at": ended_at,
            "fingerprint": fingerprint,
            "id": conversation_id,
            "snapshot_max_id": snapshot_max_id,
            "sort": search_request["sort"],
            "version": 1,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _apply_live_provenance(plan):
    from PIL import Image
    module = _module()

    avatar_rows = (
        ("11111111-1111-4111-8111-111111111111", "11111111-1111-4111-8111-111111111111.webp"),
        ("22222222-2222-4222-8222-222222222222", "22222222-2222-4222-8222-222222222222.webp"),
    )
    avatar_metadata = []
    for avatar_id, filename in avatar_rows:
        path = plan.media / filename
        Image.new("RGB", (16, 12), (25, 120, 210)).save(path, "WEBP", lossless=True)
        content = path.read_bytes()
        avatar_metadata.append((avatar_id, filename, 16, 12, len(content), __import__("hashlib").sha256(content).hexdigest()))
    conflict_request = "33333333-3333-4333-8333-333333333333"
    retry_request = "44444444-4444-4444-8444-444444444444"
    roster_body_sha = hashlib.sha256(
        json.dumps(
            {
                "cycle": "2026-09",
                "entries": [
                    {"child_ids": [10, 101], "date": "2026-09-03"},
                    {"child_ids": [10, 101], "date": "2026-09-04"},
                ],
                "month": "2026-09",
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    roster_retry_hash = hashlib.sha256(
        json.dumps(
            {
                "cycle": "2026-09",
                "entries": [
                    {"child_ids": [10, 101], "date": "2026-09-03"},
                    {"child_ids": [10, 101], "date": "2026-09-04"},
                ],
                "month": "2026-09",
                "operation": "monthly_roster",
                "replace_existing": True,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    chat_requests = (
        "55555555-5555-4555-8555-555555555551",
        "55555555-5555-4555-8555-555555555552",
        "55555555-5555-4555-8555-555555555553",
    )
    search_request = {
        "analysis_status": ["succeeded"],
        "child_id": None,
        "date_from": "2026-08-14",
        "date_to": "2026-09-08",
        "end_reason": ["max_rounds", "complete"],
        "keyword": "我",
        "limit": 5,
        "review_status": ["confirmed"],
        "sort": "completed_desc",
    }
    tts_texts = [
        "你好呀，小星！我是鸭鸭日记本，今天想听你讲讲照顾小鸭的事～",
        "你观察到小鸭有什么变化？",
        "你照顾得很认真，还有什么感受？",
        module.FROZEN_MAX_ROUNDS_REPLY,
    ]
    plan.tts_cache.mkdir(mode=0o700, exist_ok=True)
    tts_evidence = []
    for index, tts_text in enumerate(tts_texts):
        tts_audio = f"ID3 synthetic retained UAT audio {index}".encode("ascii")
        tts_cache_name = hashlib.md5(
            tts_text.encode("utf-8"), usedforsecurity=False
        ).hexdigest() + ".mp3"
        (plan.tts_cache / tts_cache_name).write_bytes(tts_audio)
        tts_evidence.append(
            {
                "audio_sha256": hashlib.sha256(tts_audio).hexdigest(),
                "cache_relative_path": f"tts-cache/{tts_cache_name}",
                "effective_text_sha256": hashlib.sha256(
                    tts_text.strip()[:500].encode("utf-8")
                ).hexdigest(),
                "kind": "opening_greeting" if index == 0 else "diary_reply",
                "playback": _native_audio_playback(),
                "source_message_id": None if index == 0 else 400 + index * 2,
                "text_sha256": hashlib.sha256(tts_text.encode("utf-8")).hexdigest(),
                "truncated": len(tts_text.strip()) > 500,
            }
        )
    with sqlite3.connect(plan.database) as connection:
        connection.executemany(
            "INSERT INTO avatar_media VALUES (?, ?, 'image/webp', ?, ?, ?, ?)",
            avatar_metadata,
        )
        connection.executemany(
            "INSERT INTO children VALUES (?, ?, ?, ?)",
            (
                (
                    101,
                    "Live Child",
                    "小星",
                    "/api/media/avatars/11111111-1111-4111-8111-111111111111",
                ),
            ),
        )
        connection.execute(
            "INSERT INTO ducks VALUES (?, ?, ?)",
            (201, "Live Duck", "/api/media/avatars/22222222-2222-4222-8222-222222222222"),
        )
        connection.executemany(
            "INSERT INTO duty_rosters VALUES (?, '2026-09', ?, ?)",
            (
                (101, "2026-09-03", 10),
                (102, "2026-09-03", 101),
                (103, "2026-09-04", 10),
                (104, "2026-09-04", 101),
            ),
        )
        roster_response = json.dumps(
            {
                "month": "2026-09",
                "replayed": False,
                "request_id": retry_request,
                "schedule": [
                    {"child_ids": [10, 101], "cycle": "2026-09", "date": "2026-09-03"},
                    {"child_ids": [10, 101], "cycle": "2026-09", "date": "2026-09-04"},
                ],
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        connection.execute(
            "INSERT INTO roster_requests VALUES (?, 'monthly_roster', ?, 'succeeded', ?, NULL, NULL)",
            (retry_request, roster_retry_hash, roster_response),
        )
        connection.executemany(
            "INSERT INTO conversations VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                (301, 101, "2026-09-03", "2026-09-03T02:00:00.000000", "ended", "max_rounds", 406),
            ),
        )
        connection.executemany(
            "INSERT INTO messages VALUES (?, ?, ?, ?)",
            (
                (401, 301, "child", "我今天在池塘边给小鸭喂食。"),
                (402, 301, "diary", "你观察到小鸭有什么变化？"),
                (403, 301, "child", "它游得更快，我还换了清水。"),
                (404, 301, "diary", "你照顾得很认真，还有什么感受？"),
                (405, 301, "child", "我很开心，也会明天继续照顾。"),
                (406, 301, "diary", module.FROZEN_MAX_ROUNDS_REPLY),
            ),
        )
        for index, request_id in enumerate(chat_requests):
            child_message_id = 401 + index * 2
            diary_message_id = child_message_id + 1
            connection.execute(
                "INSERT INTO chat_requests VALUES (?, 101, 301, ?, ?, ?, ?, 'succeeded', 1, ?)",
                (
                    request_id,
                    None if index == 0 else child_message_id - 1,
                    child_message_id,
                    diary_message_id,
                    chr(ord("b") + index) * 64,
                    json.dumps(
                        {
                            "child_message_id": child_message_id,
                            "conversation_id": 301,
                            "diary_message_id": diary_message_id,
                            "end_reason": "max_rounds" if index == 2 else None,
                            "ended": index == 2,
                            "replayed": False,
                            "reply": connection.execute(
                                "SELECT text FROM messages WHERE id = ?", (diary_message_id,)
                            ).fetchone()[0],
                            "request_id": request_id,
                            "round": index + 1,
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                ),
            )
        connection.execute("INSERT INTO analysis_jobs VALUES (501, 301, 406, 'succeeded', 1)")
        connection.execute("INSERT INTO feeding_logs VALUES (801, 301, 101, 201, '喂食', '在池塘边喂食')")
        connection.execute("INSERT INTO emotion_logs VALUES (901, 301, 101, '开心', 5, '照顾小鸭很开心')")
        connection.execute("INSERT INTO insight_notes VALUES (1001, 301, 101, '主动观察并持续照顾')")
        connection.execute("INSERT INTO assessments VALUES (601, 301, 101, 'confirmed', 4.333333333333333)")
        connection.executemany(
            "INSERT INTO assessment_scores VALUES (?, 601, ?, ?, ?)",
            ((701, 1, 4, "safe"), (702, 2, 4, "safe"), (703, 3, 5, "safe")),
        )
        connection.commit()
    return {
        "analysis_job_id": 501,
        "assessment_id": 601,
        "child_avatar_id": avatar_rows[0][0],
        "duck_avatar_id": avatar_rows[1][0],
        "live_child_id": 101,
        "live_duck_id": 201,
        "live_conversation_id": 301,
        "chat_request_ids": list(chat_requests),
        "provider_chat_request_ids": list(chat_requests[:2]),
        "local_terminal_request_id": chat_requests[2],
        "growth_after": {
            "communication": [{"date": "2026-09-03", "score": 4}],
            "observation": [{"date": "2026-09-03", "score": 4}],
            "responsibility": [{"date": "2026-09-03", "score": 5}],
        },
        "growth_before": {
            "communication": [],
            "observation": [],
            "responsibility": [],
        },
        "monthly_pairs": {"2026-09-03": [10, 101], "2026-09-04": [10, 101]},
        "monthly_roster_attempts": [
            {
                "canonical_body_sha256": roster_body_sha,
                "error_code": "ROSTER_DATE_CONFLICT",
                "kind": "roster_attempt",
                "method": "POST",
                "order": 1,
                "path": "/api/roster/month",
                "replace_existing": False,
                "request_id": conflict_request,
                "status": 409,
            },
            {
                "canonical_body_sha256": roster_body_sha,
                "error_code": None,
                "kind": "roster_attempt",
                "method": "POST",
                "order": 2,
                "path": "/api/roster/month",
                "replace_existing": True,
                "request_id": retry_request,
                "status": 200,
            },
        ],
        "monthly_roster_request_ids": [conflict_request, retry_request],
        "search_cursor": _search_cursor(
            search_request,
            conversation_id=28,
            ended_at="2026-08-29T02:00:00.000000Z",
            snapshot_max_id=301,
        ),
        "search_deep_link": "#review?conversation_id=301",
        "search_page_one_ids": [31, 301, 30, 29, 28],
        "search_page_two_ids": [27, 26, 25],
        "search_request": search_request,
        "search_result_conversation_id": 301,
        "tts_evidence": tts_evidence,
        "weekly_week_start": "2026-08-31",
        "weekly_metrics_after": {
            "completed_conversations": 2,
            "confirmed_reviews": 2,
            "failed_analyses": 0,
            "participating_children": 2,
            "pending_reviews_total": 0,
            "timezone": "Asia/Shanghai",
            "week_end_exclusive": "2026-09-07",
            "week_start": "2026-08-31",
        },
        "weekly_metrics_before": {
            "completed_conversations": 1,
            "confirmed_reviews": 1,
            "failed_analyses": 0,
            "participating_children": 1,
            "pending_reviews_total": 0,
            "timezone": "Asia/Shanghai",
            "week_end_exclusive": "2026-09-07",
            "week_start": "2026-08-31",
        },
    }


def test_retained_database_provenance_is_read_only_and_fails_one_broken_chain(tmp_path):
    module = _module()
    plan = module.create_run_plan(_repository(tmp_path), HEAD)
    _create_seed_provenance_database(plan)
    baseline = module.capture_post_seed_baseline(plan)
    entity_ids = _apply_live_provenance(plan)
    before = {
        suffix: (Path(f"{plan.database}{suffix}").read_bytes() if Path(f"{plan.database}{suffix}").exists() else None)
        for suffix in ("", "-wal", "-shm")
    }

    proof = module.validate_database_provenance(plan, entity_ids, baseline)

    after = {
        suffix: (Path(f"{plan.database}{suffix}").read_bytes() if Path(f"{plan.database}{suffix}").exists() else None)
        for suffix in ("", "-wal", "-shm")
    }
    assert after == before
    assert proof == {
        "analysis_job_id": 501,
        "assessment_id": 601,
        "conversation_id": 301,
        "score_count": 3,
        "search_result_id": 301,
        "status": "PROVEN",
    }
    playback_mutations = (
        {**_native_audio_playback(), "play_promise": "rejected"},
        {**_native_audio_playback(), "events": ["playing"]},
        {**_native_audio_playback(), "error": "MEDIA_ERR_DECODE"},
        {**_native_audio_playback(), "speech_synthesis_fallback": True},
    )
    for playback in playback_mutations:
        invalid_playback = json.loads(json.dumps(entity_ids))
        invalid_playback["tts_evidence"][0]["playback"] = playback
        with pytest.raises(module.HarnessSafetyError, match="TTS source mismatch"):
            module.validate_database_provenance(plan, invalid_playback, baseline)
    wrong_roster_ids = {
        **entity_ids,
        "monthly_roster_request_ids": list(
            reversed(entity_ids["monthly_roster_request_ids"])
        ),
    }
    with pytest.raises(module.HarnessSafetyError, match="roster retry evidence"):
        module.validate_database_provenance(plan, wrong_roster_ids, baseline)
    for bad_request in (
        {**entity_ids["search_request"], "end_reason": ["max_rounds"]},
        {
            **entity_ids["search_request"],
            "end_reason": ["complete", "max_rounds"],
        },
        {**entity_ids["search_request"], "child_id": 101},
        {**entity_ids["search_request"], "date_from": "2026-08-15"},
        {**entity_ids["search_request"], "keyword": "池塘"},
        {**entity_ids["search_request"], "limit": 20},
    ):
        bad_search = {**entity_ids, "search_request": bad_request}
        with pytest.raises(
            module.HarnessSafetyError,
            match="database provenance search request mismatch",
        ):
            module.validate_database_provenance(plan, bad_search, baseline)
    for bad_pages in (
        {
            **entity_ids,
            "search_page_one_ids": entity_ids["search_page_one_ids"][:-1],
        },
        {
            **entity_ids,
            "search_page_two_ids": entity_ids["search_page_two_ids"][:-1],
        },
        {
            **entity_ids,
            "search_page_two_ids": [*entity_ids["search_page_two_ids"][:-1], 999],
        },
    ):
        with pytest.raises(module.HarnessSafetyError, match="database provenance search"):
            module.validate_database_provenance(plan, bad_pages, baseline)
    with sqlite3.connect(plan.database) as connection:
        connection.execute("UPDATE messages SET text='it cared for the duck' WHERE id=403")
        connection.commit()
    with pytest.raises(
        module.HarnessSafetyError,
        match="database provenance frozen messages mismatch",
    ):
        module.validate_database_provenance(plan, entity_ids, baseline)
    with sqlite3.connect(plan.database) as connection:
        connection.execute("UPDATE messages SET text='它游得更快，我还换了清水。' WHERE id=403")
        connection.execute("UPDATE assessments SET status='draft' WHERE id=601")
        connection.commit()
    with pytest.raises(module.HarnessSafetyError, match="database provenance"):
        module.validate_database_provenance(plan, entity_ids, baseline)


def test_database_provenance_accepts_early_completion_and_shared_truncated_tts_cache(
    tmp_path,
):
    module = _module()
    plan = module.create_run_plan(_repository(tmp_path), HEAD)
    _create_seed_provenance_database(plan)
    baseline = module.capture_post_seed_baseline(plan)
    entity_ids = _apply_live_provenance(plan)
    first_reply = "鸭" * 500 + "甲"
    second_reply = "鸭" * 500 + "乙"
    request_ids = entity_ids["chat_request_ids"][:2]
    with sqlite3.connect(plan.database) as connection:
        connection.execute("UPDATE messages SET text = ? WHERE id = 402", (first_reply,))
        connection.execute("UPDATE messages SET text = ? WHERE id = 404", (second_reply,))
        connection.execute("DELETE FROM messages WHERE id IN (405, 406)")
        connection.execute(
            "DELETE FROM chat_requests WHERE request_id = ?",
            (entity_ids["chat_request_ids"][2],),
        )
        connection.execute(
            "UPDATE conversations SET end_reason = 'complete', frozen_last_message_id = 404 WHERE id = 301"
        )
        connection.execute(
            "UPDATE analysis_jobs SET frozen_last_message_id = 404 WHERE id = 501"
        )
        for index, (request_id, reply) in enumerate(
            zip(request_ids, (first_reply, second_reply), strict=True)
        ):
            response = json.loads(
                connection.execute(
                    "SELECT response_json FROM chat_requests WHERE request_id = ?",
                    (request_id,),
                ).fetchone()[0]
            )
            response.update(
                {
                    "end_reason": "complete" if index == 1 else None,
                    "ended": index == 1,
                    "reply": reply,
                }
            )
            connection.execute(
                "UPDATE chat_requests SET response_json = ? WHERE request_id = ?",
                (
                    json.dumps(
                        response,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                    request_id,
                ),
            )
        connection.commit()

    for stale in entity_ids["tts_evidence"][1:]:
        (plan.root / stale["cache_relative_path"]).unlink()
    effective = "鸭" * 500
    shared_audio = b"ID3 shared truncated endpoint audio"
    cache_name = hashlib.md5(
        effective.encode("utf-8"), usedforsecurity=False
    ).hexdigest() + ".mp3"
    (plan.tts_cache / cache_name).write_bytes(shared_audio)

    def evidence(text, message_id):
        return {
            "audio_sha256": hashlib.sha256(shared_audio).hexdigest(),
            "cache_relative_path": f"tts-cache/{cache_name}",
            "effective_text_sha256": hashlib.sha256(
                effective.encode("utf-8")
            ).hexdigest(),
            "kind": "diary_reply",
            "playback": _native_audio_playback(),
            "source_message_id": message_id,
            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "truncated": True,
        }

    entity_ids["chat_request_ids"] = list(request_ids)
    entity_ids["provider_chat_request_ids"] = list(request_ids)
    entity_ids["local_terminal_request_id"] = None
    entity_ids["tts_evidence"] = [
        entity_ids["tts_evidence"][0],
        evidence(first_reply, 402),
        evidence(second_reply, 404),
    ]
    assert module.validate_database_provenance(plan, entity_ids, baseline)["status"] == "PROVEN"


def test_database_provenance_rejects_seed_entities_incomplete_projection_and_unfrozen_search(
    tmp_path,
):
    module = _module()
    plan = module.create_run_plan(_repository(tmp_path), HEAD)
    _create_seed_provenance_database(plan)
    baseline = module.capture_post_seed_baseline(plan)
    entity_ids = _apply_live_provenance(plan)

    seeded_identity = {**entity_ids, "live_child_id": 10}
    with pytest.raises(module.HarnessSafetyError, match="database provenance"):
        module.validate_database_provenance(plan, seeded_identity, baseline)

    with sqlite3.connect(plan.database) as connection:
        connection.execute("DELETE FROM insight_notes WHERE conversation_id = 301")
        connection.commit()
    with pytest.raises(module.HarnessSafetyError, match="database provenance"):
        module.validate_database_provenance(plan, entity_ids, baseline)

    with sqlite3.connect(plan.database) as connection:
        connection.execute(
            "INSERT INTO insight_notes VALUES (1001, 301, 101, '主动观察并持续照顾')"
        )
        connection.commit()
    bad_cursor = {**entity_ids, "search_cursor": entity_ids["search_cursor"][:-1] + "A"}
    with pytest.raises(module.HarnessSafetyError, match="database provenance"):
        module.validate_database_provenance(plan, bad_cursor, baseline)

    with sqlite3.connect(plan.database) as connection:
        connection.execute("DELETE FROM feeding_logs WHERE id = 80")
        connection.execute("UPDATE feeding_logs SET id = 80 WHERE id = 801")
        connection.commit()
    with pytest.raises(module.HarnessSafetyError, match="database provenance"):
        module.validate_database_provenance(plan, entity_ids, baseline)


def test_fake_harness_dry_run_has_one_stdout_owned_stop_redaction_and_retained_failure(
    tmp_path, monkeypatch,
):
    module = _module()
    terminal_events = []
    real_atomic_write_json = module.atomic_write_json
    real_manifest_scan = module._assert_secret_free_payload
    real_artifact_scan = module.scan_retained_artifacts
    real_terminal_verify = module._verify_complete_precommit_state

    def observed_atomic_write(path, value, **kwargs):
        result = real_atomic_write_json(path, value, **kwargs)
        if path.name == "manifest.json" and value.get("status") == "COMPLETE":
            terminal_events.append("COMPLETE")
        return result

    def observed_manifest_scan(*args, **kwargs):
        if kwargs.get("role") == "manifest.json":
            terminal_events.append("manifest-scan")
        return real_manifest_scan(*args, **kwargs)

    def observed_artifact_scan(*args, **kwargs):
        terminal_events.append("artifact-scan")
        return real_artifact_scan(*args, **kwargs)

    def observed_terminal_verify(*args, **kwargs):
        terminal_events.append("terminal-verify")
        return real_terminal_verify(*args, **kwargs)

    monkeypatch.setattr(module, "atomic_write_json", observed_atomic_write)
    monkeypatch.setattr(module, "_assert_secret_free_payload", observed_manifest_scan)
    monkeypatch.setattr(module, "scan_retained_artifacts", observed_artifact_scan)
    monkeypatch.setattr(
        module,
        "_verify_complete_precommit_state",
        observed_terminal_verify,
    )
    repository = _repository(tmp_path)
    provider_secret = "sk-fake-provider-secret-1234567890"
    teacher_secret = "483921"
    environment = {
        "PATH": "/synthetic/bin",
        "LANG": "C.UTF-8",
        "DEEPSEEK_API_KEY": provider_secret,
        "DEEPSEEK_BASE_URL": "https://api.deepseek.example/v1",
        "DEEPSEEK_MODEL": "deepseek-safe-model",
        "DEEPSEEK_TIMEOUT": "120",
        "DEEPSEEK_MAX_TOKENS": "8192",
        "UNRELATED_TOKEN": "must-not-cross",
    }
    fixed_now = datetime(2026, 9, 4, 1, 2, 3, 456789, tzinfo=timezone.utc)
    captures = []
    process_events = []
    include_controller_evidence = True
    live_entities = {}
    live_plan = []

    def capture_resources(_repository):
        snapshot = {
            "database": {"logical_digest": "stable"},
            "dirty_paths": [],
            "git_head": HEAD,
            "git_porcelain": {"sha256": "0" * 64, "size": 0},
            "log": {"kind": "regular"},
            "media": {"digest": "stable"},
            "tts": {"digest": "stable"},
        }
        captures.append(snapshot)
        return snapshot

    def seed_runner(plan, *, argv, environment):
        assert tuple(argv) == module.build_seed_argv(
            plan,
            python_executable=PYTHON,
            business_today=lambda: date(2026, 9, 4),
        )
        assert not any(name.startswith("DEEPSEEK_") for name in environment)
        plan.app_log.parent.mkdir(mode=0o700)
        plan.app_log.write_bytes(b"")
        plan.tts_cache.mkdir(mode=0o700)
        plan.screenshots.mkdir(mode=0o700)
        _create_seed_provenance_database(plan)
        return {
            "archive_directory": None,
            "database_path": str(plan.database),
            "log_path": str(plan.app_log),
            "media_root": str(plan.media),
            "media_sha256": "1" * 64,
            "record_sha256": "2" * 64,
        }

    class FakeSession:
        port = 43123
        pid = 43210
        pgid = 43210

    def server_starter(plan, *, environment, python_executable):
        assert python_executable == PYTHON
        assert environment["APP_DB_PATH"] == str(plan.database)
        assert environment["DEEPSEEK_API_KEY"] == provider_secret
        assert "UNRELATED_TOKEN" not in environment
        entity_ids = _apply_live_provenance(plan)
        live_plan[:] = [plan]
        live_entities.clear()
        live_entities.update(entity_ids)
        if include_controller_evidence:
            controller = _set_controller_entities(
                _controller_payload(module, plan),
                entity_ids,
            )
            module.atomic_write_json(
                plan.controller_evidence,
                controller,
                pinned_plan=plan,
            )
        plan.server_stderr.write_bytes(b"safe server log\n")
        process_events.append(("start", FakeSession.pid, FakeSession.pgid))
        return FakeSession()

    def readiness_probe(session):
        assert session.pid == session.pgid
        return (
            {**module.FROZEN_RELEASE, "db_mode": "app", "analysis_worker_status": "running"},
            dict(module.FROZEN_RELEASE),
            "no-store",
            {"configured": False, "authenticated": False},
        )

    def safe_events(plan):
        def ai_event(operation, correlation):
            return {
                "audio_bytes": 0,
                "cache_relative_path": None,
                "cache_sha256": None,
                "correlation_id": correlation,
                "error_class": None,
                "latency_bucket": "1-5s",
                "model": "deepseek-safe-model",
                "operation": operation,
                "parse_valid": True,
                "provider": "deepseek",
                "response_bytes": 512,
                "response_sha256": "e" * 64,
                "status": "ok",
                "voice": None,
            }

        def tts_event(evidence):
            cache = plan.root / evidence["cache_relative_path"]
            return {
                "audio_bytes": cache.stat().st_size,
                "cache_relative_path": evidence["cache_relative_path"],
                "cache_sha256": evidence["audio_sha256"],
                "correlation_id": "message-text:"
                + evidence["effective_text_sha256"],
                "error_class": None,
                "latency_bucket": "1-5s",
                "model": None,
                "operation": "tts",
                "parse_valid": None,
                "provider": "edge-tts",
                "response_bytes": 0,
                "response_sha256": None,
                "status": "ok",
                "voice": "zh-CN-XiaoxiaoNeural",
            }

        def tts_request_event(evidence, order):
            cache = plan.root / evidence["cache_relative_path"]
            return {
                "audio_bytes": cache.stat().st_size,
                "cache_hit": False,
                "cache_relative_path": evidence["cache_relative_path"],
                "cache_sha256": evidence["audio_sha256"],
                "effective_text_sha256": evidence["effective_text_sha256"],
                "kind": "tts_request",
                "method": "GET",
                "order": order,
                "path": "/api/tts",
                "requested_text_sha256": evidence["text_sha256"],
                "status": 200,
                "truncated": evidence["truncated"],
                "voice": "zh-CN-XiaoxiaoNeural",
            }

        tts = live_entities["tts_evidence"]
        chat_requests = live_entities["chat_request_ids"]
        return (
            *live_entities["monthly_roster_attempts"],
            tts_event(tts[0]),
            tts_request_event(tts[0], 1),
            ai_event("chat_reply", f"chat-request:{chat_requests[0]}"),
            tts_event(tts[1]),
            tts_request_event(tts[1], 2),
            ai_event("chat_reply", f"chat-request:{chat_requests[1]}"),
            tts_event(tts[2]),
            tts_request_event(tts[2], 3),
            tts_event(tts[3]),
            tts_request_event(tts[3], 4),
            ai_event("extract_info", "analysis-job:501"),
            ai_event("assess_conversation", "analysis-job:501"),
        )

    def server_finisher(session):
        process_events.append(("stop", session.pgid, signal.SIGTERM))
        return safe_events(live_plan[0])

    stdout = io.StringIO()
    plan = module.execute_retained_uat(
        repository=repository,
        expected_head=HEAD,
        environ=environment,
        dotenv_values={},
        input_stream=io.StringIO(
            module.canonical_json_line({
                "kind": "teacher_credential",
                "type": "register_secret",
                "value": teacher_secret,
            })
            + module.canonical_json_line({"type": "finalize"})
        ),
        output_stream=stdout,
        python_executable=PYTHON,
        now=lambda: fixed_now,
        nonce=lambda: "123456789abc",
        business_today=lambda: date(2026, 9, 4),
        source_materializer=lambda candidate: replace(
            candidate,
            source_tree_oid="b" * 40,
        ),
        capture_resources=capture_resources,
        seed_runner=seed_runner,
        server_starter=server_starter,
        readiness_probe=readiness_probe,
        server_finisher=server_finisher,
    )

    assert stdout.getvalue().count("\n") == 1
    runtime = json.loads(stdout.getvalue())
    assert runtime["run_id"] == plan.run_id
    assert provider_secret not in stdout.getvalue()
    assert teacher_secret not in stdout.getvalue()
    assert "UNRELATED_TOKEN" not in stdout.getvalue()
    assert process_events == [
        ("start", 43210, 43210),
        ("stop", 43210, signal.SIGTERM),
    ]
    manifest = json.loads(plan.manifest.read_text(encoding="utf-8"))
    assert manifest["status"] == "COMPLETE"
    assert manifest["secret_scan"] == {
        "actual_values": "PASS",
        "forbidden_patterns": "PASS",
        "provider_key": "FULL_RETAINED_TREE_PASS",
        "reviewed_source_forbidden_patterns": "GIT_PINNED_EXEMPT",
        "status": "PASS",
        "teacher_pin": "RUNTIME_GENERATED_EVIDENCE_PASS",
    }
    assert terminal_events == [
        "artifact-scan",
        "manifest-scan",
        "artifact-scan",
        "terminal-verify",
        "COMPLETE",
    ]
    assert plan.checksums.is_file()
    checksum_check = subprocess.run(
        ("shasum", "-a", "256", "-c", plan.checksums.name),
        cwd=plan.root,
        capture_output=True,
        check=False,
        text=True,
    )
    assert checksum_check.returncode == 0, checksum_check.stderr
    assert checksum_check.stdout.count(": OK\n") == len(
        plan.checksums.read_text(encoding="utf-8").splitlines()
    )
    module.scan_retained_artifacts(
        plan.root,
        provider_secrets=(provider_secret,),
        runtime_secrets=(teacher_secret,),
    )
    assert len(captures) == 3

    include_controller_evidence = False
    process_events.clear()
    with pytest.raises(module.HarnessSafetyError, match="controller"):
        module.execute_retained_uat(
            repository=repository,
            expected_head=HEAD,
            environ=environment,
            dotenv_values={},
            input_stream=io.StringIO(""),
            output_stream=io.StringIO(),
            python_executable=PYTHON,
            now=lambda: fixed_now,
            nonce=lambda: "123456789abc",
            business_today=lambda: date(2026, 9, 4),
            source_materializer=lambda candidate: replace(
                candidate,
                source_tree_oid="b" * 40,
            ),
            capture_resources=capture_resources,
            seed_runner=seed_runner,
            server_starter=server_starter,
            readiness_probe=readiness_probe,
            server_finisher=server_finisher,
        )
    failed_runs = [
        candidate
        for candidate in (repository / "artifacts/real-uat").iterdir()
        if json.loads((candidate / "manifest.json").read_text(encoding="utf-8"))["status"]
        == "FAILED"
    ]
    assert len(failed_runs) == 1
    assert (failed_runs[0] / "duck-diary-uat.db").is_file()
    assert process_events == [
        ("start", 43210, 43210),
        ("stop", 43210, signal.SIGTERM),
    ]
