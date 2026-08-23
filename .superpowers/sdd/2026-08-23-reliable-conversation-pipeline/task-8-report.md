# Task 8 Report — Reliable Backend Release Gate

## Scope and preserved state

Started from `7bc6352`. This migration updates the stale Foundation/API release
contracts, converts E2E to a disposable-fixture test, replaces the remaining
legacy child finalizer with a public no-write tombstone, and adds release safety
regressions. No product schemas/models/services/new routers/frontends changed.

The working tree already contained unrelated changes to
`.workbuddy/memory/2026-08-22.md`,
`docs/superpowers/specs/2026-08-23-interaction-stabilization-design.md`, and
untracked `.superpowers/brainstorm/` plus `docs/superpowers/plans/`; they remain
unstaged and untouched.

## TDD evidence

### Original stale-suite RED

- `DISABLE_EXTERNAL_AI=1 ./.venv/bin/pytest -q tests/test_api.py`:
  `7 failed, 6 passed`. The stale requests omitted UUID request IDs, expected the
  old finalize mutation, and asserted old error contracts.
- `DISABLE_EXTERNAL_AI=1 ./.venv/bin/pytest -q tests/test_teacher_auth.py tests/test_api_errors.py`:
  `3 failed, 14 passed`. The route inventory was not flattened/normalized, public
  chat omitted its UUID, and the old generic missing-detail code was expected.
- Including `tests/e2e.py` aborted collection with
  `SystemExit: set RUN_REAL_INTEGRATION=1 to run real LLM/TTS integration`.

After migrating the Foundation API/E2E/auth/error contracts and tombstone,
`DISABLE_EXTERNAL_AI=1 ./.venv/bin/pytest -q tests/test_api.py tests/e2e.py tests/test_teacher_auth.py tests/test_api_errors.py`
passed `29/29`.

### Lowest-level external-AI circuit breaker

`tests/test_database_safety.py::test_lowest_level_ai_test_breaker_fails_before_the_provider_transport`
was RED using a synthetic-only local `httpx.post` response: without the fixture,
the fake transport recorded one attempted DeepSeek URL/body and the expected
`external AI disabled in tests` assertion was absent. It made no network call.

The GREEN fixture imports `app.backend.ai_engine` and monkeypatches `_llm` for
every test to immediately raise `AssertionError("external AI disabled in tests")`.
The GREEN test proves the exception is raised before its fake transport and
`outbound == []`.

### Test-engine stale-pool regression

`tests/test_database_safety.py::test_concurrent_retry_does_not_leave_schema_reflection_on_a_stale_connection`
was RED in a subprocess running exactly:

```text
tests/test_analysis_worker.py::test_two_concurrent_retries_have_one_accept_and_one_pending_replay
tests/test_pipeline_models.py::test_required_reliability_schema_names_are_visible_on_the_test_engine
```

It first reproduced the stale-connection schema reflection failure:
`uq_analysis_job_conversation` was absent from the inspector result after the
concurrent retry expanded the retained SQLite pool. The reset fixture now calls
`engine.dispose()` before its existing `drop_all/create_all`; no model or
inspector contract changed. The two-node subprocess is GREEN.

An intermittent follow-up exposed a separate fixture race in the existing
concurrent retry test: after `db_session.commit()` expired `conversation`, both
threads evaluated `conversation.id` at `tests/test_analysis_worker.py:1079`,
concurrently lazy-loading through the same main session. The confirmed traceback
origin was that expired ORM load (`IndexError`); the other thread then raised
`BrokenBarrierError`. The test-only repair captures the scalar `conversation_id`
on the main thread before commit, and worker threads use only that integer. The
node passed 30 consecutive invocations; no production retry code changed.

### Subprocess environment review fix

Review found that two safety subprocesses still copied their parent's full
environment and one deliberately started in app DB mode. The test-only helper
`_safe_pytest_subprocess_env()` now inherits only present neutral process values
(`PATH`, `LANG`, `LC_ALL`, `TMPDIR`, `TZ`, and `SYSTEMROOT`) and explicitly sets
`APP_DB_MODE=test`, a fresh `tmp_path` child DB, `DISABLE_EXTERNAL_AI=1`, and
`PYTHONNOUSERSITE=1`. It never merges `os.environ`; inherited `APP_DB_*`,
DeepSeek/OpenAI/generic API-key/provider credentials, and proxy variables are
excluded. The hostile-parent regression proves this output. All Python
subprocesses in `tests/test_database_safety.py` now use this helper, including
the protected-sentinel guard; no child process intentionally starts in app mode.

## Migrated contracts

- API chat and auto-roster requests use UUID request IDs. Active chat history
  comes from public `/api/children/{id}/active-conversation`.
- Completion posts frozen `expected_last_message_id`, immediately returns
  pending, and analysis uses a local, non-started
  `AnalysisWorker(session_factory=SessionLocal, analyzer=FakeAnalyzer).run_once()`.
  Both API and E2E use fake `chat_reply` plus fake `extract_info` and
  `assess_conversation`; no lifecycle worker or second engine is created.
- E2E is now a normal pytest test over Foundation fixtures: authenticated resource
  setup, idempotent roster replay, three UUID chat turns, completion, exactly one
  manual fake-worker run, nested detail, full confirm review, growth, and both
  pages.
- Review confirmation sends the complete revisioned document with all score
  reasons nonblank. Empty chat is `422 VALIDATION_ERROR`; unknown child is
  `404 CHILD_NOT_FOUND`; absent teacher detail is
  `404 CONVERSATION_NOT_FOUND`.
- `POST /api/conversations/{conversation_id}/finalize` is public and body-free;
  it raises only `410 LEGACY_ENDPOINT_REMOVED`, has no database dependency, and
  the focused test snapshots conversation/messages/job/projections before and
  after an existing-ID call.
- Teacher route inventory now flattens included routes, normalizes placeholders,
  counts every method/path exactly once, verifies dependencies, and compares the
  exact documented method sets.

## Provider incident and prevention

Before the breaker existed, the first RED execution of
`tests/test_api.py::test_missing_resources_and_tombstones_use_frozen_contracts`
failed to fake the legacy finalizer's two high-level calls. At
`2026-08-23 22:59:31 +08` and `2026-08-23 22:59:44 +08`, two synthetic-fixture
DeepSeek completion requests returned HTTP 200. The input was only the synthetic
child text `我喂了小鸭`, fake diary reply `真棒！还有呢？`, synthetic child name
`终结墓碑`, and seeded default dimensions. The test used Foundation's temporary
SQLite path under `/private/var/folders/.../duck-diary-pytest-.../pytest.db`; it
did not use the application DB, real child data, nonempty TTS, or report any key.

The test was immediately corrected to fake both high-level finalizer calls. The
autouse `_llm` breaker above is the permanent prevention. All subsequent
verification ran with it active and no breaker hit. No test calls nonempty TTS;
the only TTS assertion uses empty text and returns before Edge-TTS import.

## Verification

Application DB logical hash uses read-only SQLite URI `mode=ro` plus deterministic
`iterdump()` (therefore includes WAL-visible state):

```text
path: /Users/lddmay/AiCoding/pomegranagent/data/duck_diary.db
before: c31f80875458d37e7b9badf086a5ff904a73d1d7f2ef1f5ab716c1f2c9755af3
after:  c31f80875458d37e7b9badf086a5ff904a73d1d7f2ef1f5ab716c1f2c9755af3
```

- Original AI-breaker and stale-pool subprocess regressions: `2 passed`.
- Review environment regression: hostile-parent helper `1 passed`; stale-pool
  and protected-sentinel subprocesses `2 passed`.
- Concurrent retry regression: `30` consecutive node passes.
- Task 4 focused suite: `34 passed`.
- Seven pipeline suites plus migrated API/E2E: `159 passed`.
- Complete backend suite, explicitly including E2E:
  `DISABLE_EXTERNAL_AI=1 ./.venv/bin/pytest -q tests tests/e2e.py`:
  `220 passed` (the original 219 plus the new hostile-parent environment test).
- Corrected failure matrix: chat `4`, worker `15`, roster `11`, review `6`,
  deactivation `6` selected tests; every selector collected tests and passed.
- `./.venv/bin/python -m py_compile` over every changed Python file: exit 0.
- `git diff --check`: exit 0.

Existing project deprecation warnings remain in the suite output; no new test
failure or external-provider warning occurred after the breaker.

## Static audit and runtime routes

- The migrated API/E2E bypass search has no match for `drop_all`, global
  `TestClient`, `RUN_REAL_INTEGRATION`, `TemporaryDirectory`, or `APP_DB_*`.
- The legacy-path search has one intentional match: the focused `/finalize`
  no-write tombstone assertion in `tests/test_api.py`.
- `rg -n "HTTPException\\(" app/backend/routes app/backend/services` has no
  matches.
- Runtime flattened/normalized inventory has exactly one handler for each of
  `43` method/path pairs, including `POST /api/chat`; its exact documented
  methods are asserted by `test_teacher_route_inventory_has_the_session_dependency`.

```text
DELETE /api/children/{}
DELETE /api/ducks/{}
GET /api/analysis/growth
GET /api/analysis/overview
GET /api/assessments
GET /api/auth/status
GET /api/children
GET /api/children/{}/active-conversation
GET /api/conversations
GET /api/conversations/{}
GET /api/dimensions
GET /api/ducks
GET /api/ducks/{}/archive
GET /api/health
GET /api/roster
GET /api/roster/today
GET /api/tts
GET /version.json
PATCH /api/conversations/{}/logs
POST /api/assessments/{}/confirm
POST /api/auth/lock
POST /api/auth/setup
POST /api/auth/unlock
POST /api/chat
POST /api/children
POST /api/children/{}/deactivate
POST /api/children/{}/reactivate
POST /api/conversations/{}/analysis/retry
POST /api/conversations/{}/complete
POST /api/conversations/{}/finalize
POST /api/dimensions
POST /api/ducks
POST /api/ducks/{}/deactivate
POST /api/ducks/{}/reactivate
POST /api/ducks/{}/summarize
POST /api/roster
POST /api/roster/auto
PUT /api/children/{}
PUT /api/conversations/{}/review
PUT /api/dimensions/{}
PUT /api/ducks/{}
PUT /api/ducks/{}/archive
PUT /api/roster/{}
```

## Files

Changed Task 8 files:

- `app/backend/main.py`
- `tests/conftest.py`
- `tests/e2e.py`
- `tests/test_api.py`
- `tests/test_api_errors.py`
- `tests/test_teacher_auth.py`
- `tests/test_database_safety.py`
- `tests/test_analysis_worker.py`
- this report

Commit subject: `test: enforce reliable backend release gate`.

Review-fix commit subject: `test: sanitize release-gate subprocesses`.
