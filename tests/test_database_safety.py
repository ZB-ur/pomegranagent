import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import sys
import textwrap
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from app.backend import ai_engine

# Ensure the project package is importable when pytest prepends tests/ to sys.path.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.backend.settings import (
    DATA_DIR,
    DEFAULT_APP_DB_PATH,
    DEFAULT_LOG_PATH,
    DEFAULT_MEDIA_ROOT,
    DEFAULT_TTS_CACHE_PATH,
    RuntimeSettings,
    UnsafeTestDatabaseError,
    UnsafeTestRuntimePathError,
    assert_safe_test_database_path,
)


_NEUTRAL_SUBPROCESS_ENV_NAMES = ("PATH", "LANG", "LC_ALL", "TMPDIR", "TZ", "SYSTEMROOT")


def _safe_pytest_subprocess_env(test_db_path: Path) -> dict[str, str]:
    """Return the only inherited process state a disposable pytest needs."""
    env = {
        name: value
        for name in _NEUTRAL_SUBPROCESS_ENV_NAMES
        if (value := os.environ.get(name)) is not None
    }
    env.update(
        {
            "APP_DB_MODE": "test",
            "APP_DB_PATH": str(test_db_path.resolve()),
            "DISABLE_EXTERNAL_AI": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTHON_DOTENV_DISABLED": "1",
        }
    )
    return env


def test_safe_pytest_subprocess_env_discards_hostile_parent_configuration(monkeypatch, tmp_path: Path):
    sentinel = tmp_path / "application-sentinel.db"
    child_db = tmp_path / "child-subprocess.db"
    monkeypatch.setenv("APP_DB_MODE", "app")
    monkeypatch.setenv("APP_DB_PATH", str(sentinel))
    monkeypatch.setenv("APP_DB_UNRELATED", "must-not-leak")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-deepseek")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://provider.invalid")
    monkeypatch.setenv("OPENAI_API_KEY", "secret-openai")
    monkeypatch.setenv("SERVICE_API_KEY", "secret-generic")
    monkeypatch.setenv("PROVIDER_TOKEN", "secret-provider")
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid")
    monkeypatch.setenv("ALL_PROXY", "http://proxy.invalid")

    env = _safe_pytest_subprocess_env(child_db)

    assert env["APP_DB_MODE"] == "test"
    assert env["APP_DB_PATH"] == str(child_db.resolve())
    assert env["DISABLE_EXTERNAL_AI"] == "1"
    assert env["PYTHONNOUSERSITE"] == "1"
    assert env["PYTHON_DOTENV_DISABLED"] == "1"
    assert {key for key in env if key.startswith("APP_DB_")} == {"APP_DB_MODE", "APP_DB_PATH"}
    forbidden = ("DEEPSEEK", "OPENAI", "API_KEY", "PROVIDER", "PROXY")
    assert all(not any(marker in key for marker in forbidden) for key in env)


def test_nested_ai_import_disables_synthetic_dotenv_before_module_import(tmp_path: Path):
    package_root = tmp_path / "isolated-ai-import"
    backend_package = package_root / "app" / "backend"
    backend_package.mkdir(parents=True)
    (package_root / "app" / "__init__.py").write_text("", encoding="utf-8")
    (backend_package / "__init__.py").write_text("", encoding="utf-8")
    (backend_package / "ai_engine.py").symlink_to(ROOT / "app" / "backend" / "ai_engine.py")
    (package_root / ".env").write_text(
        "TASK9_DOTENV_SENTINEL=loaded\n",
        encoding="utf-8",
    )
    probe_path = package_root / "probe.py"
    probe_path.write_text(
        "import os\n"
        "import app.backend.ai_engine\n"
        "loaded = os.getenv('TASK9_DOTENV_SENTINEL') == 'loaded'\n"
        "print(f\"sentinel_loaded={str(loaded).lower()}\")\n",
        encoding="utf-8",
    )
    child_database = package_root / "isolated.db"
    child_env = _safe_pytest_subprocess_env(child_database)
    child_env["PYTHONPATH"] = str(package_root)

    result = subprocess.run(
        [sys.executable, str(probe_path)],
        cwd=package_root,
        env=child_env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "sentinel_loaded=false\n"


def test_lowest_level_ai_test_breaker_fails_before_the_provider_transport(monkeypatch):
    """A test must not reach HTTP even when an AI call is accidentally unmocked."""
    outbound: list[dict] = []

    class SyntheticResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"choices": [{"message": {"content": "synthetic provider response"}}]}

    def fake_post(url, **kwargs):
        outbound.append({"url": url, "body": kwargs.get("json")})
        return SyntheticResponse()

    monkeypatch.setattr(ai_engine.httpx, "post", fake_post)
    try:
        ai_engine._llm([{"role": "user", "content": "synthetic test input"}], retries=0)
    except AssertionError as error:
        assert str(error) == "TEST_TRIPWIRE:external_ai"
    else:
        pytest.fail(f"test breaker did not run before outbound={outbound!r}")
    assert outbound == []


def test_pytest_application_logging_uses_only_the_disposable_runtime_file():
    """Import-time application logging must never retain the real application log."""
    from conftest import (
        APPLICATION_FILE_HANDLER_INSTALLED,
        REAL_APPLICATION_LOG_PATH,
        TEST_APPLICATION_LOG_PATH,
        TEST_RUNTIME_DIR,
        root_file_handler_paths,
    )

    handler_paths = root_file_handler_paths()
    assert REAL_APPLICATION_LOG_PATH not in handler_paths
    if APPLICATION_FILE_HANDLER_INSTALLED:
        assert TEST_APPLICATION_LOG_PATH in handler_paths
        assert TEST_APPLICATION_LOG_PATH.is_relative_to(TEST_RUNTIME_DIR)


def test_application_resource_guard_captures_db_sidecars_log_tts_and_media_trees(
    tmp_path: Path,
):
    from conftest import (
        application_resource_violations,
        capture_application_resources,
    )

    database = tmp_path / "guard.db"
    application_log = tmp_path / "app.log"
    tts_cache = tmp_path / "tts-cache"
    media_root = tmp_path / "media"
    application_log.write_bytes(b"before-log")
    tts_cache.mkdir()
    (tts_cache / "voice.mp3").write_bytes(b"before-audio")
    media_root.mkdir()
    (media_root / "avatar.webp").write_bytes(b"before-avatar")

    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        connection.execute("CREATE TABLE evidence (value TEXT NOT NULL)")
        connection.execute("INSERT INTO evidence VALUES ('before')")
        connection.commit()
        before = capture_application_resources(
            database,
            application_log,
            tts_cache,
            media_root,
        )
        assert before.database.database.kind.value == "regular"
        assert before.database.wal.kind.value == "regular"
        assert before.database.shm.kind.value == "regular"
        assert before.log.kind.value == "regular"
        assert before.tts.root.kind.value == "directory"
        assert before.tts.entries[0].relative_path == "voice.mp3"
        assert before.media.root.kind.value == "directory"
        assert before.media.entries[0].relative_path == "avatar.webp"
        assert before.unsafe_reasons == ()

        connection.execute("INSERT INTO evidence VALUES ('after')")
        connection.commit()
        application_log.write_bytes(b"after-log")
        (tts_cache / "voice.mp3").write_bytes(b"after-audio")
        (media_root / "avatar.webp").write_bytes(b"after-avatar")
        after = capture_application_resources(
            database,
            application_log,
            tts_cache,
            media_root,
        )

    violations = set(application_resource_violations(before, after))
    assert "DATABASE_LOGICAL_CHANGED" in violations
    assert "DATABASE_WAL_CHANGED" in violations
    assert "APPLICATION_LOG_CHANGED" in violations
    assert "TTS_TREE_CHANGED" in violations
    assert "MEDIA_TREE_CHANGED" in violations


def test_real_application_resource_baseline_is_complete_and_stable():
    from conftest import (
        APPLICATION_RESOURCE_BASELINE,
        REAL_APPLICATION_DATABASE_PATH,
        REAL_APPLICATION_LOG_PATH,
        REAL_MEDIA_ROOT,
        REAL_TTS_CACHE_PATH,
        capture_application_resources,
    )

    baseline = APPLICATION_RESOURCE_BASELINE
    assert REAL_APPLICATION_DATABASE_PATH == (ROOT / "data" / "duck_diary.db").resolve()
    assert REAL_APPLICATION_LOG_PATH == (ROOT / "logs" / "app.log").resolve()
    assert REAL_TTS_CACHE_PATH == (ROOT / "data" / "tts_cache").resolve()
    assert REAL_MEDIA_ROOT == (ROOT / "data" / "media").resolve()
    assert baseline.database.database.kind.value == "regular"
    assert baseline.database.wal.kind.value in {"missing", "regular"}
    assert baseline.database.shm.kind.value in {"missing", "regular"}
    assert baseline.log.kind.value == "regular"
    assert baseline.tts.root.kind.value == "directory"
    assert baseline.media.root.kind.value in {"missing", "directory"}
    assert baseline.unsafe_reasons == ()
    assert capture_application_resources() == baseline


def test_import_guard_blocks_tts_provider_and_nonlocal_network_before_transport():
    import edge_tts

    from app.backend import main as main_module
    from conftest import (
        BLOCKED_NETWORK_ATTEMPTS,
        EXTERNAL_NETWORK_TRIPWIRE_INSTALLED,
        REAL_TTS_CACHE_PATH,
        TEST_RUNTIME_DIR,
        TEST_TTS_CACHE_PATH,
        TTS_PROVIDER_TRIPWIRE_INSTALLED,
    )

    assert EXTERNAL_NETWORK_TRIPWIRE_INSTALLED is True
    assert TTS_PROVIDER_TRIPWIRE_INSTALLED is True
    assert main_module.TTS_CACHE_DIR == TEST_TTS_CACHE_PATH
    assert TEST_TTS_CACHE_PATH.is_relative_to(TEST_RUNTIME_DIR)
    assert main_module.TTS_CACHE_DIR != REAL_TTS_CACHE_PATH
    with pytest.raises(AssertionError) as tts_error:
        edge_tts.Communicate("synthetic text", "synthetic voice")
    assert str(tts_error.value) == "TEST_TRIPWIRE:edge_tts"

    before_attempts = len(BLOCKED_NETWORK_ATTEMPTS)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
        with pytest.raises(AssertionError) as network_error:
            candidate.connect(("provider.invalid", 443))
    assert str(network_error.value) == "TEST_TRIPWIRE:external_network"
    assert len(BLOCKED_NETWORK_ATTEMPTS) == before_attempts + 1


def test_uncaught_tripwire_probe_exposes_exact_junit_types_and_frames(
    tmp_path: Path,
):
    probe = tmp_path / "test_uncaught_tripwire_probe.py"
    junit = tmp_path / "tripwire-probe.junit.xml"
    browser_child = ROOT / "tests" / "browser" / "child_server.py"
    browser_conftest = ROOT / "tests" / "browser" / "conftest.py"
    probe.write_text(
        textwrap.dedent(
            f"""
            import asyncio
            import importlib.util
            import os
            import pytest
            import socket
            import types
            from pathlib import Path

            def load(path, name):
                spec = importlib.util.spec_from_file_location(name, path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                return module

            def test_root_external_ai():
                import conftest
                conftest._blocked_external_ai()

            def test_root_edge_tts():
                import edge_tts
                edge_tts.Communicate("synthetic", "synthetic")

            def test_root_external_network():
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
                    candidate.connect(("provider.invalid", 443))

            def test_root_external_network_connect_ex():
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
                    candidate.connect_ex(("provider.invalid", 443))

            def test_browser_edge_tts():
                module = load({str(browser_child)!r}, "task9_child_server_edge")
                os.environ["BROWSER_AI_TRIPWIRE_PATH"] = {str(tmp_path / "edge.tripwire")!r}
                stream = module.FakeCommunicate().stream()
                asyncio.run(stream.__anext__())

            def test_browser_external_ai():
                module = load({str(browser_child)!r}, "task9_child_server_ai")
                os.environ["BROWSER_AI_TRIPWIRE_PATH"] = {str(tmp_path / "ai.tripwire")!r}
                os.environ["BROWSER_NETWORK_TRIPWIRE_PATH"] = {str(tmp_path / "ai-network.tripwire")!r}
                os.environ["BROWSER_CONTEXT_EGRESS_TRIPWIRE_PATH"] = {str(tmp_path / "ai-context.tripwire")!r}
                main = types.SimpleNamespace(
                    ai_engine=types.SimpleNamespace(_llm=lambda: None)
                )
                module._install_external_tripwires(main)
                main.ai_engine._llm()

            def test_browser_external_network():
                module = load({str(browser_child)!r}, "task9_child_server_network")
                guarded = module.make_loopback_connect_guard(
                    Path({str(tmp_path / "network.tripwire")!r}), lambda *_args: None
                )
                guarded(None, ("provider.invalid", 443))

            @pytest.fixture
            def browser_file_guard():
                module = load({str(browser_conftest)!r}, "task9_browser_conftest")
                tripwire = {str(tmp_path / "browser_ai.tripwire")!r}
                open(tripwire, "wb").close()
                environment = {{
                    "BROWSER_AI_TRIPWIRE_PATH": tripwire,
                    "BROWSER_NETWORK_TRIPWIRE_PATH": {str(tmp_path / "absent-network")!r},
                    "BROWSER_CONTEXT_EGRESS_TRIPWIRE_PATH": {str(tmp_path / "absent-context")!r},
                }}
                sentinel = object()
                fake_module = types.SimpleNamespace(
                    capture_resource_snapshots=lambda *_args: sentinel,
                    REAL_DATABASE_PATH=None,
                    REAL_LOG_PATH=None,
                    REAL_TTS_CACHE_PATH=None,
                    REAL_MEDIA_ROOT=None,
                )
                server = types.SimpleNamespace(
                    real_snapshots=sentinel, environment=environment
                )
                yield
                module._verify_server_safety(fake_module, server)

            def test_browser_fixture_file(browser_file_guard):
                pass
            """
        ),
        encoding="utf-8",
    )
    child_env = _safe_pytest_subprocess_env(tmp_path / "tripwire-probe.db")
    child_env["PYTHONPATH"] = str(ROOT / "tests")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "scripts.run_interaction_acceptance",
            "--capture=sys",
            "-p",
            "conftest",
            f"--junitxml={junit}",
            str(probe),
        ],
        cwd=ROOT,
        env=child_env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1, result.stdout + result.stderr
    cases = {
        case.attrib["name"]: case
        for case in ET.parse(junit).getroot().iter("testcase")
    }
    expected = {
        "test_root_external_ai": (
            "AssertionError",
            "tests/conftest.py",
            "TEST_TRIPWIRE:external_ai",
            "external_ai",
            "tests/conftest.py:_blocked_external_ai",
        ),
        "test_root_edge_tts": (
            "AssertionError",
            "tests/conftest.py",
            "TEST_TRIPWIRE:edge_tts",
            "edge_tts",
            "tests/conftest.py:__init__",
        ),
        "test_root_external_network": (
            "AssertionError",
            "tests/conftest.py",
            "TEST_TRIPWIRE:external_network",
            "external_network",
            "tests/conftest.py:_guarded_socket_connect",
        ),
        "test_root_external_network_connect_ex": (
            "AssertionError",
            "tests/conftest.py",
            "TEST_TRIPWIRE:external_network",
            "external_network",
            "tests/conftest.py:_guarded_socket_connect_ex",
        ),
        "test_browser_edge_tts": (
            "AssertionError",
            "tests/browser/child_server.py",
            "external edge_tts disabled in browser tests",
            "browser_edge_tts",
            "tests/browser/child_server.py:stream",
        ),
        "test_browser_external_ai": (
            "AssertionError",
            "tests/browser/child_server.py",
            "external AI disabled in browser tests",
            "browser_ai",
            "tests/browser/child_server.py:blocked_llm",
        ),
        "test_browser_external_network": (
            "PermissionError",
            "tests/browser/child_server.py",
            "non-loopback socket blocked:",
            "browser_network",
            "tests/browser/child_server.py:guarded",
        ),
        "test_browser_fixture_file": (
            "AssertionError",
            "tests/browser/conftest.py",
            "browser tripwire fired: BROWSER_AI_TRIPWIRE_PATH",
            "browser_file",
            "tests/browser/conftest.py:_verify_server_safety",
        ),
    }
    assert set(cases) == set(expected)
    for name, (
        exception_type,
        frame_path,
        message,
        event_id,
        frame,
    ) in expected.items():
        failure = cases[name].find("failure")
        if failure is None:
            failure = cases[name].find("error")
        assert failure is not None
        assert message in failure.attrib["message"]
        assert failure.attrib["message"].startswith(
            f"{exception_type}: {message}"
        ) or name == "test_browser_fixture_file"
        assert frame_path in (failure.text or "")
        properties = cases[name].findall("./properties/property")
        assert [(item.attrib["name"], item.attrib["value"]) for item in properties] == [
            (
                "task9.tripwire_event",
                json.dumps(
                    {
                        "event_id": event_id,
                        "exception_type": exception_type,
                        "frame": frame,
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            )
        ]

    from scripts import run_interaction_acceptance as runner

    sidecar = runner.parse_tripwire_sidecar(
        result.stderr.encode("utf-8"), command_id="tripwire-probe"
    )
    assert sidecar.integrity_valid is True, sidecar
    assert len(sidecar.records) == len(expected)
    evidence = runner.parse_pytest_junit_bytes(
        junit.read_bytes(),
        stderr_payload=result.stderr.encode("utf-8"),
        command_id="tripwire-probe",
        require_tripwire_auth=True,
    )
    assert evidence.reason == "NONPASS_TESTS"
    assert tuple(
        (item.node_id, item.event_id, item.exception_type, item.frame)
        for item in evidence.tripwire_events
    ) == tuple(
        (name, values[3], values[0], values[4])
        for name, values in expected.items()
    )


def _run_authenticated_tripwire_probe(
    tmp_path: Path,
    *,
    name: str,
    source: str,
    extra_plugins: tuple[str, ...] = (),
):
    probe = tmp_path / f"test_{name}.py"
    junit = tmp_path / f"{name}.junit.xml"
    probe.write_text(textwrap.dedent(source), encoding="utf-8")
    child_env = _safe_pytest_subprocess_env(tmp_path / f"{name}.db")
    child_env["PYTHONPATH"] = os.pathsep.join(
        (str(tmp_path), str(ROOT / "tests"))
    )
    arguments = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-p",
        "scripts.run_interaction_acceptance",
        "--capture=sys",
        "-p",
        "conftest",
    ]
    for plugin in extra_plugins:
        arguments.extend(("-p", plugin))
    arguments.extend((f"--junitxml={junit}", str(probe)))
    result = subprocess.run(
        arguments,
        cwd=ROOT,
        env=child_env,
        capture_output=True,
        text=True,
        check=False,
    )
    return result, junit


def test_authenticated_tripwire_plugin_covers_all_phases_without_stale_events(
    tmp_path: Path,
):
    from scripts import run_interaction_acceptance as runner

    lifecycle, lifecycle_junit = _run_authenticated_tripwire_probe(
        tmp_path,
        name="lifecycle",
        source="""
            import conftest
            import pytest
            import socket

            @pytest.fixture
            def setup_breaker():
                conftest._blocked_external_ai()

            @pytest.fixture
            def teardown_breaker():
                yield
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
                    candidate.connect_ex(("provider.invalid", 443))

            def test_setup_phase(setup_breaker):
                pass

            def test_call_and_teardown_phases(teardown_breaker):
                conftest._blocked_external_ai()
        """,
    )
    assert lifecycle.returncode == 1, lifecycle.stdout + lifecycle.stderr
    lifecycle_sidecar = runner.parse_tripwire_sidecar(
        lifecycle.stderr.encode("utf-8"), command_id="lifecycle"
    )
    assert lifecycle_sidecar.integrity_valid is True, lifecycle_sidecar
    assert tuple(
        (item.node_id, item.phase, item.sequence, item.event.event_id)
        for item in lifecycle_sidecar.records
    ) == (
        ("test_setup_phase", "setup", 1, "external_ai"),
        ("test_call_and_teardown_phases", "call", 2, "external_ai"),
        (
            "test_call_and_teardown_phases",
            "teardown",
            3,
            "external_network",
        ),
    )
    lifecycle_evidence = runner.parse_pytest_junit_bytes(
        lifecycle_junit.read_bytes(),
        stderr_payload=lifecycle.stderr.encode("utf-8"),
        command_id="lifecycle",
        require_tripwire_auth=True,
    )
    assert tuple(
        (item.node_id, item.event_id)
        for item in lifecycle_evidence.tripwire_events
    ) == (
        ("test_setup_phase", "external_ai"),
        ("test_call_and_teardown_phases", "external_ai"),
        ("test_call_and_teardown_phases", "external_network"),
    )

    import_result, _import_junit = _run_authenticated_tripwire_probe(
        tmp_path,
        name="import_phase",
        source="""
            import conftest
            conftest._blocked_external_ai()
        """,
    )
    assert import_result.returncode != 0
    import_sidecar = runner.parse_tripwire_sidecar(
        import_result.stderr.encode("utf-8"), command_id="import_phase"
    )
    assert tuple(item.phase for item in import_sidecar.records) == ("import",)

    collection_plugin = tmp_path / "task9_collection_probe.py"
    collection_plugin.write_text(
        textwrap.dedent(
            """
            def pytest_collection_modifyitems():
                import conftest
                conftest._blocked_external_ai()
            """
        ),
        encoding="utf-8",
    )
    collection_result, _collection_junit = _run_authenticated_tripwire_probe(
        tmp_path,
        name="collection_phase",
        source="""
            def test_never_runs():
                pass
        """,
        extra_plugins=("task9_collection_probe",),
    )
    assert collection_result.returncode != 0
    collection_sidecar = runner.parse_tripwire_sidecar(
        collection_result.stderr.encode("utf-8"), command_id="collection_phase"
    )
    assert tuple(item.phase for item in collection_sidecar.records) == (
        "collection",
    )

    clean_result, clean_junit = _run_authenticated_tripwire_probe(
        tmp_path,
        name="caught_and_fake",
        source=f"""
            import conftest
            import json

            def test_caught_raw_property_and_compile_lookalike(record_property):
                try:
                    conftest._blocked_external_ai()
                except AssertionError:
                    pass
                namespace = {{}}
                exec(compile(
                    'def _blocked_external_ai():\\n    raise AssertionError("TEST_TRIPWIRE:external_ai")',
                    {str(ROOT / 'tests' / 'conftest.py')!r},
                    'exec',
                ), namespace)
                try:
                    namespace['_blocked_external_ai']()
                except AssertionError:
                    pass
                record_property('task9.tripwire_event', json.dumps({{
                    'event_id': 'external_ai',
                    'exception_type': 'AssertionError',
                    'frame': 'tests/conftest.py:_blocked_external_ai',
                }}, separators=(',', ':'), sort_keys=True))
                print('TASK9_AUTH_V1:EVENT:not-base64:not-a-signature')
        """,
    )
    assert clean_result.returncode == 0, clean_result.stdout + clean_result.stderr
    clean_sidecar = runner.parse_tripwire_sidecar(
        clean_result.stderr.encode("utf-8"), command_id="caught_and_fake"
    )
    assert clean_sidecar.integrity_valid is True
    assert clean_sidecar.records == ()
    clean_evidence = runner.parse_pytest_junit_bytes(
        clean_junit.read_bytes(),
        stderr_payload=clean_result.stderr.encode("utf-8"),
        command_id="caught_and_fake",
        require_tripwire_auth=True,
    )
    assert clean_evidence.tripwire_events == ()
    assert clean_evidence.reason == "TRIPWIRE_AUTH_INVALID"


def test_concurrent_retry_does_not_leave_schema_reflection_on_a_stale_connection(tmp_path: Path):
    """The shared test engine must clear retained pool connections between resets."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_analysis_worker.py::test_two_concurrent_retries_have_one_accept_and_one_pending_replay",
            "tests/test_pipeline_models.py::test_required_reliability_schema_names_are_visible_on_the_test_engine",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=_safe_pytest_subprocess_env(tmp_path / "stale-pool-subprocess.db"),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_relative_app_db_path_resolves_from_project_root(monkeypatch):
    monkeypatch.setenv("APP_DB_MODE", "app")
    monkeypatch.setenv("APP_DB_PATH", "var/local-demo.db")
    settings = RuntimeSettings.from_env()
    assert settings.db_path.is_absolute()
    assert settings.db_path.name == "local-demo.db"


def test_runtime_settings_resolve_all_relative_app_paths_and_default_timezone():
    settings = RuntimeSettings.from_env({
        "APP_DB_MODE": "app",
        "APP_DB_PATH": "var/local-demo.db",
        "APP_MEDIA_ROOT": "var/media",
        "APP_LOG_PATH": "var/logs/app.log",
        "APP_TTS_CACHE_PATH": "var/tts-cache",
    })

    assert settings.db_path == (ROOT / "var/local-demo.db").resolve()
    assert settings.business_timezone == "Asia/Shanghai"
    assert settings.media_root == (ROOT / "var/media").resolve()
    assert settings.log_path == (ROOT / "var/logs/app.log").resolve()
    assert settings.tts_cache_path == (ROOT / "var/tts-cache").resolve()


def test_runtime_settings_reject_invalid_timezone_without_echoing_the_value():
    secret_value = "Not/AZone-secret-configuration"

    with pytest.raises(RuntimeError) as captured:
        RuntimeSettings.from_env({
            "APP_DB_MODE": "app",
            "APP_BUSINESS_TIMEZONE": secret_value,
        })

    assert "APP_BUSINESS_TIMEZONE" in str(captured.value)
    assert secret_value not in str(captured.value)


def test_test_mode_derives_every_runtime_path_beside_its_disposable_database(tmp_path: Path):
    database = (tmp_path / "runtime" / "pytest.db").resolve()

    settings = RuntimeSettings.from_env({
        "APP_DB_MODE": "test",
        "APP_DB_PATH": str(database),
    })

    assert settings.db_path == database
    assert settings.media_root == database.parent / "media"
    assert settings.log_path == database.parent / "app.log"
    assert settings.tts_cache_path == database.parent / "tts-cache"


@pytest.mark.parametrize(
    ("environment_name", "unsafe_path"),
    [
        ("APP_MEDIA_ROOT", DEFAULT_MEDIA_ROOT),
        ("APP_MEDIA_ROOT", DEFAULT_MEDIA_ROOT / "nested"),
        ("APP_LOG_PATH", DEFAULT_LOG_PATH),
        ("APP_LOG_PATH", DEFAULT_LOG_PATH / "nested"),
        ("APP_TTS_CACHE_PATH", DEFAULT_TTS_CACHE_PATH),
        ("APP_TTS_CACHE_PATH", DEFAULT_TTS_CACHE_PATH / "nested"),
    ],
)
def test_test_mode_rejects_real_runtime_resource_paths(
    environment_name: str,
    unsafe_path: Path,
    tmp_path: Path,
):
    with pytest.raises(UnsafeTestRuntimePathError, match="unsafe test runtime path"):
        RuntimeSettings.from_env({
            "APP_DB_MODE": "test",
            "APP_DB_PATH": str(tmp_path / "pytest.db"),
            environment_name: str(unsafe_path),
        })


@pytest.mark.parametrize(
    "candidate",
    [
        DEFAULT_LOG_PATH,
        DEFAULT_LOG_PATH.parent,
        DEFAULT_LOG_PATH.parent / "pytest.db",
    ],
)
def test_test_mode_rejects_application_log_paths_as_database(
    candidate: Path,
    tmp_path: Path,
):
    with pytest.raises(UnsafeTestDatabaseError, match="unsafe test database"):
        RuntimeSettings.from_env({
            "APP_DB_MODE": "test",
            "APP_DB_PATH": str(candidate),
            "APP_MEDIA_ROOT": str(tmp_path / "media"),
            "APP_LOG_PATH": str(tmp_path / "app.log"),
            "APP_TTS_CACHE_PATH": str(tmp_path / "tts-cache"),
        })


@pytest.mark.parametrize("candidate", [DEFAULT_APP_DB_PATH, DATA_DIR / "pytest.db"])
def test_test_mode_rejects_application_data_paths(candidate: Path):
    with pytest.raises(UnsafeTestDatabaseError, match="unsafe test database"):
        assert_safe_test_database_path(candidate)


def test_test_mode_accepts_a_pytest_temp_path(tmp_path: Path):
    candidate = tmp_path / "test.db"
    assert assert_safe_test_database_path(candidate) == candidate.resolve()


def test_importing_database_does_not_create_tables(tmp_path: Path):
    db_path = tmp_path / "import-only.db"
    result = subprocess.run(
        [sys.executable, "-c", "import app.backend.database"],
        cwd=Path(__file__).resolve().parents[1],
        env=_safe_pytest_subprocess_env(db_path),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert not db_path.exists()


def _sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def test_pytest_subprocess_does_not_change_application_db(tmp_path: Path):
    application_db = tmp_path / "protected-app.db"
    application_db.write_bytes(b"application-database-sentinel")
    before = _sha256(application_db)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_api.py::test_dimensions_seeded", "-q"],
        cwd=Path(__file__).resolve().parents[1],
        env=_safe_pytest_subprocess_env(tmp_path / "isolated-pytest-subprocess.db"),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert _sha256(application_db) == before


def test_review_atomic_pytest_subprocess_does_not_change_the_real_application_log(tmp_path: Path):
    """A disposable TestClient pytest process must leave the incident log byte-identical."""
    real_log = (ROOT / "logs" / "app.log").resolve()
    before = real_log.read_bytes() if real_log.exists() else None
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_review_atomicity.py::test_teacher_review_routes_require_a_session_before_queue_detail_or_write",
        ],
        cwd=ROOT,
        env=_safe_pytest_subprocess_env(tmp_path / "review-atomic-subprocess.db"),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    after = real_log.read_bytes() if real_log.exists() else None
    assert after == before
