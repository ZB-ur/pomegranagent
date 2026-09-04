from __future__ import annotations

from datetime import date, datetime, timezone
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

    parsed = module.parse_args(["--retain", "--print-runtime-json"])

    assert parsed.retain is True
    assert parsed.print_runtime_json is True
    for invalid in ([], ["--retain"], ["--print-runtime-json"], ["--retain", "--print-runtime-json", "extra"]):
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
        ["--retain", "--print-runtime-json"],
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
    assert calls[0]["dotenv_values"] == {"DEEPSEEK_API_KEY": "fake"}
    assert calls[0]["environ"] == {"PATH": "/synthetic/bin"}
    assert calls[0]["input_stream"] is stdin
    assert calls[0]["output_stream"] is stdout
    assert calls[0]["seed_runner"] is module.run_seed_process
    assert calls[0]["server_starter"] is module.start_live_server
    assert calls[0]["readiness_probe"] is module.probe_live_readiness
    assert calls[0]["server_finisher"] is module.finish_live_server


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
        "error_class": None,
        "latency_bucket": "1-5s",
        "model": "deepseek-chat",
        "operation": "chat_reply",
        "provider": "deepseek",
        "response_bytes": 127,
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
        "error_class": None,
        "latency_bucket": "1-5s",
        "model": "deepseek-chat",
        "operation": "chat_reply",
        "provider": "deepseek",
        "response_bytes": 127,
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

    def chat_reply(**_kwargs):
        return {"reply": "safe synthetic response", "ended": False}

    def extract_info(_transcript):
        raise RuntimeError(secret)

    ai_engine = types.SimpleNamespace(
        MODEL="deepseek-safe-model",
        chat_reply=chat_reply,
        extract_info=extract_info,
        assess_conversation=lambda *_args: {"scores": []},
    )
    server.instrument_ai_engine(
        ai_engine,
        emit=events.append,
        monotonic=lambda: next(ticks),
    )

    assert ai_engine.chat_reply(child={})["reply"] == "safe synthetic response"
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


def test_owned_process_group_stops_term_then_bounded_kill_without_foreign_signal():
    module = _module()
    timeout = subprocess.TimeoutExpired(cmd="fake", timeout=8)
    process = _FakeProcess(waits=(timeout, -signal.SIGKILL))
    owned = module.OwnedProcess(process=process, pid=process.pid, pgid=process.pid)
    signals = []

    module.stop_owned_process_group(
        owned,
        getpgid=lambda pid: pid,
        killpg=lambda pgid, signum: signals.append((pgid, signum)),
    )

    assert signals == [
        (process.pid, signal.SIGTERM),
        (process.pid, signal.SIGKILL),
    ]
    assert process.wait_timeouts == [8, 5]

    foreign = _FakeProcess(pid=54321)
    foreign_owned = module.OwnedProcess(process=foreign, pid=foreign.pid, pgid=foreign.pid)
    signals.clear()
    with pytest.raises(module.HarnessSafetyError, match="process-group ownership"):
        module.stop_owned_process_group(
            foreign_owned,
            getpgid=lambda _pid: 99999,
            killpg=lambda pgid, signum: signals.append((pgid, signum)),
        )
    assert signals == []
    assert foreign.poll() is None


def test_server_startup_exit_is_detected_without_group_discovery():
    module = _module()
    process = _FakeProcess()
    process.returncode = 7
    owned = module.OwnedProcess(process=process, pid=process.pid, pgid=process.pid)

    with pytest.raises(module.HarnessSafetyError, match="exited before readiness"):
        module.require_owned_process_alive(owned, getpgid=lambda pid: pid)
    with pytest.raises(module.HarnessSafetyError, match="process-group ownership"):
        module.require_owned_process_alive(owned, getpgid=lambda _pid: 99999)


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

    scanlines = b"".join(b"\x00" + b"\x6f\xb4\xdd" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(scanlines, level=9))
        + chunk(b"IEND", b"")
    )


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
    screenshots = []
    for viewport in ("1024x768", "1440x900", "1024x576", "1280x720"):
        semantic = f"state-{viewport}"
        width, height = (int(part) for part in viewport.split("x"))
        (plan.screenshots / f"{semantic}.png").write_bytes(_png(width, height))
        screenshots.append(
            {
                "journey_step": module.REQUIRED_JOURNEY_STEPS[0],
                "relative_path": f"screenshots/{semantic}.png",
                "semantic_name": semantic,
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


def _create_provenance_database(plan):
    from PIL import Image

    plan.media.mkdir(mode=0o700)
    avatar_rows = (
        ("11111111-1111-4111-8111-111111111111", "child.webp"),
        ("22222222-2222-4222-8222-222222222222", "duck.webp"),
    )
    avatar_metadata = []
    for avatar_id, filename in avatar_rows:
        path = plan.media / filename
        Image.new("RGB", (16, 12), (25, 120, 210)).save(path, "WEBP", lossless=True)
        content = path.read_bytes()
        avatar_metadata.append((avatar_id, filename, 16, 12, len(content), __import__("hashlib").sha256(content).hexdigest()))
    with sqlite3.connect(plan.database) as connection:
        connection.executescript(
            """
            CREATE TABLE children (id INTEGER PRIMARY KEY, name TEXT, avatar TEXT);
            CREATE TABLE ducks (id INTEGER PRIMARY KEY, name TEXT, avatar TEXT);
            CREATE TABLE avatar_media (id TEXT PRIMARY KEY, file_name TEXT, mime_type TEXT, width INTEGER, height INTEGER, size_bytes INTEGER, sha256 TEXT);
            CREATE TABLE duty_rosters (id INTEGER PRIMARY KEY, cycle TEXT, date TEXT, child_id INTEGER);
            CREATE TABLE conversations (id INTEGER PRIMARY KEY, child_id INTEGER, date TEXT, ended_at TEXT, status TEXT, end_reason TEXT, frozen_last_message_id INTEGER);
            CREATE TABLE messages (id INTEGER PRIMARY KEY, conversation_id INTEGER, role TEXT, text TEXT);
            CREATE TABLE analysis_jobs (id INTEGER PRIMARY KEY, conversation_id INTEGER, frozen_last_message_id INTEGER, status TEXT);
            CREATE TABLE assessments (id INTEGER PRIMARY KEY, conversation_id INTEGER, child_id INTEGER, status TEXT);
            CREATE TABLE assessment_scores (id INTEGER PRIMARY KEY, assessment_id INTEGER, dimension_id INTEGER, score INTEGER, reason TEXT);
            """
        )
        connection.executemany(
            "INSERT INTO avatar_media VALUES (?, ?, 'image/webp', ?, ?, ?, ?)",
            avatar_metadata,
        )
        connection.executemany(
            "INSERT INTO children VALUES (?, ?, ?)",
            (
                (101, "Live Child", "/api/media/avatars/11111111-1111-4111-8111-111111111111"),
                (102, "Partner", None),
            ),
        )
        connection.execute(
            "INSERT INTO ducks VALUES (?, ?, ?)",
            (201, "Live Duck", "/api/media/avatars/22222222-2222-4222-8222-222222222222"),
        )
        connection.executemany(
            "INSERT INTO duty_rosters VALUES (?, '2026-09', '2026-09-03', ?)",
            ((1, 101), (2, 102)),
        )
        connection.executemany(
            "INSERT INTO conversations VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                (301, 101, "2026-09-03", "2026-09-03T02:00:00", "ended", "complete", 402),
                (302, 102, "2026-09-02", "2026-09-02T02:00:00", "ended", "complete", 404),
            ),
        )
        connection.executemany(
            "INSERT INTO messages VALUES (?, ?, ?, ?)",
            ((401, 301, "child", "synthetic child"), (402, 301, "diary", "synthetic diary"), (403, 302, "child", "other"), (404, 302, "diary", "other")),
        )
        connection.execute("INSERT INTO analysis_jobs VALUES (501, 301, 402, 'succeeded')")
        connection.execute("INSERT INTO assessments VALUES (601, 301, 101, 'confirmed')")
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
        "monthly_pairs": {"2026-09-03": [101, 102]},
        "search_page_one_ids": [301],
        "search_page_two_ids": [302],
        "search_result_conversation_id": 301,
        "weekly_week_start": "2026-08-31",
    }


def test_retained_database_provenance_is_read_only_and_fails_one_broken_chain(tmp_path):
    module = _module()
    plan = module.create_run_plan(_repository(tmp_path), HEAD)
    entity_ids = _create_provenance_database(plan)
    before = {
        suffix: (Path(f"{plan.database}{suffix}").read_bytes() if Path(f"{plan.database}{suffix}").exists() else None)
        for suffix in ("", "-wal", "-shm")
    }

    proof = module.validate_database_provenance(plan, entity_ids)

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
        module.validate_database_provenance(plan, entity_ids)


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
        entity_ids = _create_provenance_database(plan)
        if include_controller_evidence:
            controller = _controller_payload(module, plan)
            controller["journey"][0]["entity_ids"] = entity_ids
            module.atomic_write_json(plan.controller_evidence, controller)
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

    safe_events = tuple(
        {
            "audio_bytes": 4096 if operation == "tts" else 0,
            "error_class": None,
            "latency_bucket": "1-5s",
            "model": None if operation == "tts" else "deepseek-safe-model",
            "operation": operation,
            "provider": "edge-tts" if operation == "tts" else "deepseek",
            "response_bytes": 0 if operation == "tts" else 512,
            "status": "ok",
            "voice": "zh-CN-XiaoxiaoNeural" if operation == "tts" else None,
        }
        for operation in ("chat_reply", "extract_info", "assess_conversation", "tts")
    )

    def server_finisher(session):
        process_events.append(("stop", session.pgid, signal.SIGTERM))
        return safe_events

    stdout = io.StringIO()
    plan = module.execute_retained_uat(
        repository=repository,
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
