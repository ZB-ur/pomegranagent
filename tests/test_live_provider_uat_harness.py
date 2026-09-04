from __future__ import annotations

import base64
import asyncio
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
import zlib

import pytest


HEAD = "a" * 40
PYTHON = "/Users/lddmay/AiCoding/pomegranagent/.venv/bin/python"


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

    paths = module._dirty_path_names(
        b"R  notes/release-observation.md\0app/backend/main.py\0"
    )

    assert paths == ("app/backend/main.py", "notes/release-observation.md")
    with pytest.raises(module.HarnessSafetyError, match="runtime or UAT dirt"):
        module.validate_reviewed_checkout(
            {
                "git_head": HEAD,
                "dirty_paths": [
                    {"relative_path": path, "file": {}, "directory": None}
                    for path in paths
                ],
            },
            expected_head=HEAD,
            allowed_unrelated_dirty_paths=("notes/release-observation.md",),
        )


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
        str(plan.repository / "scripts" / "seed_demo_database.py"),
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

    class SeedProcess(_FakeProcess):
        pass

    def popen(actual_argv, **kwargs):
        calls.append((tuple(actual_argv), kwargs))
        kwargs["stdout"].write(module.canonical_json_line(payload).encode())
        kwargs["stdout"].flush()
        kwargs["stderr"].write(b"safe synthetic seed diagnostic\n")
        kwargs["stderr"].flush()
        return SeedProcess()

    result = module.run_seed_process(
        plan,
        argv=argv,
        environment=environment,
        popen=popen,
        getpgid=lambda pid: pid,
        getsid=lambda pid: pid,
    )

    assert result == payload
    assert calls[0][0] == argv
    assert calls[0][1]["cwd"] == plan.repository
    assert calls[0][1]["env"] == environment
    assert calls[0][1]["shell"] is False
    assert calls[0][1]["start_new_session"] is True
    assert calls[0][1]["stdin"] is subprocess.DEVNULL
    assert not any(name.startswith("DEEPSEEK_") for name in calls[0][1]["env"])


def test_telemetry_collector_reads_one_bounded_pipe_and_rejects_truncation():
    module = _module()
    safe = {
        "audio_bytes": 0,
        "cache_relative_path": None,
        "cache_sha256": None,
        "correlation_id": "conversation:301",
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
    plan = module.create_run_plan(_repository(tmp_path), HEAD)
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
            "child_avatar": str(plan.repository / "tests/fixtures/live_provider/avatars/child.png"),
            "duck_avatar": str(plan.repository / "tests/fixtures/live_provider/avatars/duck.jpg"),
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
        "correlation_id": "conversation:301",
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
        "protocol": "pomegranagent-live-uat-provider-summary/v1",
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
    secret = "sk-server-secret-1234567890"
    environment = {
        "APP_BUSINESS_TIMEZONE": "Asia/Shanghai",
        "APP_DB_MODE": "app",
        "APP_DB_PATH": str(database),
        "APP_LOG_PATH": str(app_log),
        "APP_MEDIA_ROOT": str(media),
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

    context.set_next_correlation("conversation:301")
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
    context.set_next_correlation("conversation:301")

    assert ai_engine.chat_reply()["reply"] == "local fallback"
    assert len(events) == 1
    assert events[0]["operation"] == "chat_reply"
    assert events[0]["correlation_id"] == "conversation:301"
    assert events[0]["parse_valid"] is False
    assert events[0]["status"] == "error"
    assert events[0]["error_class"] == "ProviderPayloadInvalid"
    assert "not-json" not in json.dumps(events)


def test_provider_completion_requires_exact_model_voice_correlation_and_run_owned_audio(
    tmp_path,
):
    module = _module()
    plan = module.create_run_plan(_repository(tmp_path), HEAD)
    plan.tts_cache.mkdir(mode=0o700)
    audio = b"ID3 synthetic exact audio"
    cache_relative = "tts-cache/0123456789abcdef0123456789abcdef.mp3"
    (plan.root / cache_relative).write_bytes(audio)
    audio_sha = hashlib.sha256(audio).hexdigest()
    entity_ids = {
        "analysis_job_id": 501,
        "chat_request_ids": ["one", "two", "three"],
        "live_conversation_id": 301,
        "tts_evidence": {
            "audio_sha256": audio_sha,
            "cache_relative_path": cache_relative,
            "source_message_id": 406,
            "text_sha256": "f" * 64,
        },
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

    events = (
        ai_event("chat_reply", "conversation:301"),
        ai_event("chat_reply", "conversation:301"),
        ai_event("chat_reply", "conversation:301"),
        ai_event("extract_info", "analysis-job:501"),
        ai_event("assess_conversation", "analysis-job:501"),
        {
            "audio_bytes": len(audio),
            "cache_relative_path": cache_relative,
            "cache_sha256": audio_sha,
            "correlation_id": "message-text:" + "f" * 64,
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
        },
    )

    summary = module._validate_provider_completion(
        events,
        plan=plan,
        provider={**_provider_values(), "DEEPSEEK_MODEL": "deepseek-safe-model"},
        entity_ids=entity_ids,
    )
    assert len(summary["events"]) == 6

    mutations = (
        (*events[:3], {**events[3], "model": "wrong-model"}, *events[4:]),
        (*events[:-1], {**events[-1], "voice": "zh-CN-YunxiNeural"}),
        ({**events[0], "correlation_id": "conversation:999"}, *events[1:]),
        (*events[:-1], {**events[-1], "cache_sha256": "0" * 64}),
    )
    for mutation in mutations:
        with pytest.raises(module.HarnessSafetyError, match="provider telemetry"):
            module._validate_provider_completion(
                tuple(mutation),
                plan=plan,
                provider={**_provider_values(), "DEEPSEEK_MODEL": "deepseek-safe-model"},
                entity_ids=entity_ids,
            )
    (plan.root / cache_relative).unlink()
    with pytest.raises(module.HarnessSafetyError, match="provider telemetry"):
        module._validate_provider_completion(
            events,
            plan=plan,
            provider={**_provider_values(), "DEEPSEEK_MODEL": "deepseek-safe-model"},
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
                str(plan.repository / "scripts" / "live_provider_uat_server.py"),
                "--listen-fd",
                "71",
                "--telemetry-fd",
                "72",
            ),
            {
                "close_fds": True,
                "cwd": plan.repository,
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
    timeout = subprocess.TimeoutExpired(cmd="fake", timeout=8)
    process = _FakeProcess(waits=(timeout, -signal.SIGKILL))
    owned = module.OwnedProcess(
        process=process,
        pid=process.pid,
        pgid=process.pid,
        sid=process.pid,
    )
    signals = []
    group = [(process.pid, process.pid)]

    def killpg(pgid, signum):
        signals.append((pgid, signum))
        if signum == signal.SIGKILL:
            group.clear()

    module.stop_owned_process_group(
        owned,
        getpgid=lambda pid: pid,
        getsid=lambda pid: pid,
        group_members=lambda _pgid: tuple(group),
        killpg=killpg,
        monotonic=iter((0.0, 3.0, 4.0)).__next__,
        sleep=lambda _seconds: None,
    )

    assert signals == [
        (process.pid, signal.SIGTERM),
        (process.pid, signal.SIGKILL),
    ]
    assert process.wait_timeouts == [8, 5]

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
        )
    assert signals == []


def test_owned_process_group_kills_surviving_descendant_after_leader_exit_without_reused_group():
    module = _module()
    leader = _FakeProcess(pid=43210)
    leader.returncode = 0
    owned = module.OwnedProcess(
        process=leader,
        pid=leader.pid,
        pgid=leader.pid,
        sid=leader.pid,
    )
    group = [(43211, 43210)]
    signals = []

    def killpg(pgid, signum):
        signals.append((pgid, signum))
        group.clear()

    module.stop_owned_process_group(
        owned,
        getpgid=lambda _pid: (_ for _ in ()).throw(ProcessLookupError()),
        getsid=lambda _pid: (_ for _ in ()).throw(ProcessLookupError()),
        group_members=lambda _pgid: tuple(group),
        killpg=killpg,
        monotonic=iter((0.0, 0.1)).__next__,
        sleep=lambda _seconds: None,
    )

    assert signals == [(43210, signal.SIGTERM)]

    group[:] = [(99999, 99999)]
    signals.clear()
    with pytest.raises(module.HarnessSafetyError, match="process-group ownership"):
        module.stop_owned_process_group(
            owned,
            getpgid=lambda _pid: (_ for _ in ()).throw(ProcessLookupError()),
            getsid=lambda _pid: (_ for _ in ()).throw(ProcessLookupError()),
            group_members=lambda _pgid: tuple(group),
            killpg=lambda pgid, signum: signals.append((pgid, signum)),
        )
    assert signals == []

    group[:] = [(leader.pid, leader.pid)]
    with pytest.raises(module.HarnessSafetyError, match="process-group ownership"):
        module.stop_owned_process_group(
            owned,
            getpgid=lambda _pid: (_ for _ in ()).throw(ProcessLookupError()),
            getsid=lambda _pid: (_ for _ in ()).throw(ProcessLookupError()),
            group_members=lambda _pgid: tuple(group),
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
    module.scan_retained_artifacts(plan.root, actual_secrets=("sk-actual-secret-123456", "483921"))

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
                actual_secrets=("sk-actual-secret-123456", "483921"),
            )
        assert "actual-secret" not in str(caught.value)
        assert "483921" not in str(caught.value)
        candidate.unlink()


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
    journey = [
        {
            "entity_ids": {},
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
            actual_secrets=(secret,),
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
            CREATE TABLE children (id INTEGER PRIMARY KEY, name TEXT, avatar TEXT);
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
            "INSERT INTO children VALUES (?, ?, ?)",
            (
                (10, "Seed Child", f"/api/media/avatars/{seed_avatar_id}"),
                (11, "Seed Partner", None),
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
        connection.execute(
            "INSERT INTO conversations VALUES (30, 10, '2026-09-01', '2026-09-01T02:00:00.000000', 'ended', 'complete', 41)"
        )
        connection.executemany(
            "INSERT INTO messages VALUES (?, 30, ?, ?)",
            ((40, "child", "seed 池塘 child"), (41, "diary", "seed diary")),
        )
        connection.execute(
            "INSERT INTO analysis_jobs VALUES (50, 30, 41, 'succeeded', 1)"
        )
        connection.execute(
            "INSERT INTO assessments VALUES (60, 30, 10, 'confirmed', 3.0)"
        )
        connection.execute(
            "INSERT INTO feeding_logs VALUES (80, 30, 10, 20, '观察', 'seed observation')"
        )
        connection.executemany(
            "INSERT INTO assessment_scores VALUES (?, 60, ?, 3, 'seed reason')",
            ((70, 1), (71, 2), (72, 3)),
        )
        connection.commit()


def _search_cursor(search_request, *, conversation_id: int, snapshot_max_id: int) -> str:
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
            "ended_at": "2026-09-03T02:00:00.000000Z",
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
    chat_requests = (
        "55555555-5555-4555-8555-555555555551",
        "55555555-5555-4555-8555-555555555552",
        "55555555-5555-4555-8555-555555555553",
    )
    search_request = {
        "analysis_status": ["succeeded"],
        "child_id": None,
        "date_from": "2026-08-31",
        "date_to": "2026-09-06",
        "end_reason": ["complete"],
        "keyword": "池塘",
        "review_status": ["confirmed"],
        "sort": "completed_desc",
    }
    tts_text = "这是一份很完整的池塘日记。"
    tts_audio = b"ID3 synthetic retained UAT audio"
    plan.tts_cache.mkdir(mode=0o700, exist_ok=True)
    tts_cache_name = f"{hashlib.md5(tts_text.encode('utf-8')).hexdigest()}.mp3"
    (plan.tts_cache / tts_cache_name).write_bytes(tts_audio)
    with sqlite3.connect(plan.database) as connection:
        connection.executemany(
            "INSERT INTO avatar_media VALUES (?, ?, 'image/webp', ?, ?, ?, ?)",
            avatar_metadata,
        )
        connection.executemany(
            "INSERT INTO children VALUES (?, ?, ?)",
            (
                (101, "Live Child", "/api/media/avatars/11111111-1111-4111-8111-111111111111"),
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
            (retry_request, "a" * 64, roster_response),
        )
        connection.executemany(
            "INSERT INTO conversations VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                (301, 101, "2026-09-03", "2026-09-03T02:00:00.000000", "ended", "complete", 406),
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
                (406, 301, "diary", "这是一份很完整的池塘日记。"),
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
                            "conversation_id": 301,
                            "diary_message_id": diary_message_id,
                            "reply": connection.execute(
                                "SELECT text FROM messages WHERE id = ?", (diary_message_id,)
                            ).fetchone()[0],
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
            {"http_status": 409, "outcome": "ROSTER_DATE_CONFLICT", "request_id": conflict_request},
            {"http_status": 200, "outcome": "SUCCEEDED", "request_id": retry_request},
        ],
        "search_cursor": _search_cursor(search_request, conversation_id=301, snapshot_max_id=301),
        "search_deep_link": "#review?conversation_id=301",
        "search_page_one_ids": [301],
        "search_page_two_ids": [30],
        "search_request": search_request,
        "search_result_conversation_id": 301,
        "tts_evidence": {
            "audio_sha256": hashlib.sha256(tts_audio).hexdigest(),
            "cache_relative_path": f"tts-cache/{tts_cache_name}",
            "source_message_id": 406,
            "text_sha256": hashlib.sha256(tts_text.encode("utf-8")).hexdigest(),
        },
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
    with sqlite3.connect(plan.database) as connection:
        connection.execute("UPDATE assessments SET status='draft' WHERE id=601")
        connection.commit()
    with pytest.raises(module.HarnessSafetyError, match="database provenance"):
        module.validate_database_provenance(plan, entity_ids, baseline)


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
    tmp_path,
):
    module = _module()
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
            controller = _controller_payload(module, plan)
            controller["journey"][0]["entity_ids"] = entity_ids
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

        tts = live_entities["tts_evidence"]
        cache = plan.root / tts["cache_relative_path"]
        return (
            *(ai_event("chat_reply", "conversation:301") for _ in range(3)),
            ai_event("extract_info", "analysis-job:501"),
            ai_event("assess_conversation", "analysis-job:501"),
            {
                "audio_bytes": cache.stat().st_size,
                "cache_relative_path": tts["cache_relative_path"],
                "cache_sha256": tts["audio_sha256"],
                "correlation_id": "message-text:" + tts["text_sha256"],
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
            },
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
        actual_secrets=(provider_secret, teacher_secret),
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
