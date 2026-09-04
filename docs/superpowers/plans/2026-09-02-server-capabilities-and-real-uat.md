# Server Capabilities and Real UAT Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the complete P6 server-capability release, connect it to every reviewed UI placeholder, and retain a real-provider, real-browser UAT evidence package.

**Architecture:** Build a schema/configuration foundation first, then add business time, media, roster, report, and search services through strict DTO boundaries and transaction-scoped service functions. Preserve P5 endpoints while adding new static routes. Finish with deterministic seed, an isolated app-mode live-UAT runtime, frontend reachability, and versioned release gates.

**Tech Stack:** Python 3.13, FastAPI, Pydantic 2, SQLAlchemy 2, SQLite, Alembic, Pillow, Edge-TTS, vanilla ES modules, Node test runner, pytest, Playwright 1.62.

**Spec:** `docs/superpowers/specs/2026-09-02-server-capabilities-and-real-uat-design.md`

## Global Constraints

- Base all work on `codex/p6-server-capabilities`, created from `codex/p5-teacher-reports-slice@2cac86b`.
- Keep the application loopback-only; external credentials stay in the live-UAT backend process and never enter browser state or artifacts.
- Default `APP_BUSINESS_TIMEZONE` is exactly `Asia/Shanghai`; timestamps remain UTC and calendar dates use the business clock.
- Existing GET history, daily roster, auto roster, and P5 response shapes remain compatible.
- Unknown mutation fields are rejected. Child/duck mutation inputs never accept `active` or `deactivated_at`.
- Avatar input accepts only JPEG/PNG/WebP, at most 5 MiB, 4096×4096, and 16,777,216 decoded pixels; output is static WebP quality 88 with longest edge 1024.
- Monthly roster contains 1–31 unique dates, exactly two distinct active children per date, and one transaction/idempotency record per request.
- Search keyword is POST-body-only, 1–100 characters, never logged, and only matches frozen messages.
- Deterministic tests block providers and use disposable DB/log/TTS/media paths. Live UAT uses `APP_DB_MODE=app` with run-scoped paths outside the repository's real runtime resources.
- Preserve all unrelated dirty paths in the main checkout. Do not touch, stop, copy, or migrate the real application database/server.
- Use synthetic identities and images only. Retain raw UAT evidence under `artifacts/real-uat/<run-id>/` and curated manual images under `docs/manual/assets/<run-id>/`.
- Follow strict TDD: create the focused failing test, observe the expected failure, implement the smallest behavior, then re-run the focused and adjacent tests before committing.
- Never run `tests/e2e.py`, `tests/test_api.py`, backend suites, or browser suites concurrently.

---

### Task 1: Freeze DTOs, dependencies, and safe runtime paths

**Files:**
- Modify: `requirements.txt`
- Modify: `.env.example`
- Modify: `app/backend/settings.py`
- Modify: `app/backend/schemas.py`
- Create: `tests/test_server_capability_contracts.py`
- Modify: `tests/test_database_safety.py`

**Interfaces:**
- Produces: `RuntimeContextResponse`, `ChildMutationRequest`, `DuckMutationRequest`, `AvatarMediaResponse`, `MonthlyRosterEntryRequest`, `MonthlyRosterRequest`, `MonthlyRosterResponse`, `WeeklyReportResponse`, `ConversationSearchRequest`, `ConversationSearchPage`.
- Produces: `RuntimeSettings.business_timezone`, `media_root`, `log_path`, and `tts_cache_path`.
- Consumes: existing `MutableRequestModel`, `StrictResponseModel`, history item schemas, and roster schedule item shapes.

- [ ] **Step 1: Add failing strict-contract tests**

Write literal request cases that prove unknown fields, `active`, duplicate status values, an inverted or 367-day search range, a non-month entry date, duplicate roster dates, blank normalized names, and invalid timezone/path settings fail with the expected Pydantic or runtime error. Include one valid literal for every new DTO and assert its exact `model_dump()`.

```python
def test_child_mutation_rejects_server_owned_active():
    with pytest.raises(ValidationError):
        schemas.ChildMutationRequest(name="小明", active=False)

def test_monthly_roster_rejects_date_outside_month():
    with pytest.raises(ValidationError):
        schemas.MonthlyRosterRequest(
            request_id=UUID("11111111-1111-1111-1111-111111111111"),
            month="2026-09",
            cycle="九月值日",
            entries=[{"date": "2026-10-01", "child_ids": [1, 2]}],
            replace_existing=False,
        )
```

- [ ] **Step 2: Verify RED**

Run:

```bash
/Users/lddmay/AiCoding/pomegranagent/.venv/bin/pytest -q tests/test_server_capability_contracts.py tests/test_database_safety.py
```

Expected: collection or assertions fail because the named DTOs/settings do not exist.

- [ ] **Step 3: Add exact dependencies and settings**

Add bounded dependencies for `alembic`, `Pillow`, `python-multipart`, and `tzdata`. Resolve relative runtime paths from project root. In test mode reject paths equal to or beneath the real DB, media, log, and TTS roots. Validate the IANA timezone with `ZoneInfo` without echoing environment values in errors.

```python
@dataclass(frozen=True)
class RuntimeSettings:
    db_path: Path
    db_mode: DBMode
    business_timezone: str
    media_root: Path
    log_path: Path
    tts_cache_path: Path
```

- [ ] **Step 4: Implement strict DTOs**

Use `extra="forbid"`, before-validators that trim strings, explicit length limits, unique-list validators, `YYYY-MM` validation, inclusive search-range validation, and exact response fields from the spec. Keep `ConversationHistoryPage` unchanged and add a separate cursor-based search page.

- [ ] **Step 5: Verify GREEN and adjacent contracts**

Run the Step 2 command and:

```bash
/Users/lddmay/AiCoding/pomegranagent/.venv/bin/pytest -q tests/test_http_boundary.py tests/test_api_errors.py
```

- [ ] **Step 6: Commit**

```bash
git add requirements.txt .env.example app/backend/settings.py app/backend/schemas.py tests/test_server_capability_contracts.py tests/test_database_safety.py
git commit -m "feat: freeze P6 server capability contracts"
```

### Task 2: Add schema-2 baseline and schema-3 migration

**Files:**
- Create: `alembic.ini`
- Create: `migrations/env.py`
- Create: `migrations/script.py.mako`
- Create: `migrations/versions/20260902_0001_schema_2_baseline.py`
- Create: `migrations/versions/20260902_0002_schema_3_server_capabilities.py`
- Create: `app/backend/schema_migrations.py`
- Modify: `app/backend/models.py`
- Modify: `app/backend/database.py`
- Modify: `app/backend/main.py`
- Create: `tests/fixtures/schema_2.sql`
- Create: `tests/test_schema_migrations.py`

**Interfaces:**
- Produces: `models.AvatarMedia` and schema-3 query indexes.
- Produces: `ensure_database_schema(engine, db_mode) -> None`.
- Consumes: Task 1 settings and schema-3 version target.

- [ ] **Step 1: Write failing migration tests**

Create a schema-2 SQL fixture with one child, duck, roster, ended conversation, frozen messages, analysis job, and assessment. Test blank DB upgrade, unstamped schema-2 fingerprint/stamp/upgrade with unchanged rows, missing-column rejection before DDL, unknown/newer revision rejection, and startup ordering before worker start.

```python
def test_schema_2_database_is_stamped_then_upgraded_without_data_loss(tmp_path):
    database = load_schema_2_fixture(tmp_path / "schema2.db")
    ensure_database_schema(engine_for(database), db_mode="app")
    assert scalar(database, "select version_num from alembic_version") == SCHEMA_3_REVISION
    assert scalar(database, "select name from children where id=1") == "合成幼儿"
```

- [ ] **Step 2: Verify RED**

```bash
/Users/lddmay/AiCoding/pomegranagent/.venv/bin/pytest -q tests/test_schema_migrations.py
```

Expected: `schema_migrations` and migration revisions are missing.

- [ ] **Step 3: Implement self-contained Alembic revisions**

The schema-2 baseline must create the complete existing schema without importing current ORM models. The schema-3 revision creates `avatar_media` and these exact indexes:

```text
ix_conversations_status_date_ended_id(status,date,ended_at,id)
ix_conversations_child_status_date_ended_id(child_id,status,date,ended_at,id)
ix_messages_conversation_id_id(conversation_id,id)
ix_analysis_jobs_status_conversation_id(status,conversation_id)
ix_assessments_status_conversation_id(status,conversation_id)
```

- [ ] **Step 4: Implement guarded migration startup**

Fingerprint the required schema-2 tables and columns before stamping an unversioned non-empty database. Run `upgrade head` for app mode before worker startup. Keep test fixtures able to use disposable `Base.metadata.create_all()` and test the migrator separately.

- [ ] **Step 5: Verify GREEN and model compatibility**

```bash
/Users/lddmay/AiCoding/pomegranagent/.venv/bin/pytest -q tests/test_schema_migrations.py tests/test_pipeline_models.py tests/test_runtime_health.py
```

- [ ] **Step 6: Commit**

```bash
git add alembic.ini migrations app/backend/schema_migrations.py app/backend/models.py app/backend/database.py app/backend/main.py tests/fixtures/schema_2.sql tests/test_schema_migrations.py
git commit -m "feat: add guarded schema three migrations"
```

### Task 3: Introduce the business clock and isolated runtime resources

**Files:**
- Create: `app/backend/business_time.py`
- Create: `app/backend/routes/runtime.py`
- Modify: `app/backend/main.py`
- Modify: `app/backend/routes/resources.py`
- Modify: `app/backend/routes/roster.py`
- Modify: `app/backend/routes/conversations.py`
- Modify: `app/backend/services/chat.py`
- Modify: `tests/conftest.py`
- Modify: `tests/browser/child_server.py`
- Create: `tests/test_business_time.py`
- Create: `tests/test_runtime_context.py`
- Modify: `tests/test_chat_idempotency.py`
- Modify: `tests/test_conversation_completion.py`
- Modify: `tests/test_deactivation.py`
- Modify: `tests/test_roster_idempotency.py`

**Interfaces:**
- Produces: `BusinessClock.utc_now()`, `business_now()`, `business_today()`, `week_window(anchor=None)`.
- Produces: public `GET /api/runtime/context`.
- Consumes: Task 1 settings and existing service parameters `today`/`now`.

- [ ] **Step 1: Write failing time and resource-isolation tests**

Cover UTC 15:59/16:00 Shanghai date rollover, Monday window boundaries, explicit anchor, invalid query parameters, exact runtime response, conversation date creation, roster today, deactivation future-count date, and injected log/TTS/media roots.

```python
def test_business_date_rolls_at_shanghai_midnight():
    clock = BusinessClock("Asia/Shanghai", now=lambda: datetime(2026, 9, 1, 16, 0, tzinfo=UTC))
    assert clock.business_today() == date(2026, 9, 2)
    assert clock.week_window() == (date(2026, 8, 31), date(2026, 9, 7))
```

- [ ] **Step 2: Verify RED**

```bash
/Users/lddmay/AiCoding/pomegranagent/.venv/bin/pytest -q tests/test_business_time.py tests/test_runtime_context.py tests/test_chat_idempotency.py tests/test_deactivation.py tests/test_roster_idempotency.py
```

- [ ] **Step 3: Implement the clock and route**

Use injected aware UTC `now`, `ZoneInfo`, and Monday-inclusive windows. Register a static runtime router and reject all query parameters for `/api/runtime/context`.

- [ ] **Step 4: Replace host-calendar calls and hard-coded resource roots**

Route/service boundaries receive one clock-derived `now` and `business_date`. Configure `logging.FileHandler`, `TTS_CACHE_DIR`, and future media paths from `RuntimeSettings`. Update test/browser subprocess environments before importing the app.

- [ ] **Step 5: Verify GREEN and no protected-resource drift**

Run the Step 2 command plus:

```bash
/Users/lddmay/AiCoding/pomegranagent/.venv/bin/pytest -q tests/test_database_safety.py tests/browser/test_child_shell.py
```

- [ ] **Step 6: Commit**

```bash
git add app/backend/business_time.py app/backend/routes/runtime.py app/backend/main.py app/backend/routes/resources.py app/backend/routes/roster.py app/backend/routes/conversations.py app/backend/services/chat.py tests/conftest.py tests/browser/child_server.py tests/test_business_time.py tests/test_runtime_context.py tests/test_chat_idempotency.py tests/test_conversation_completion.py tests/test_deactivation.py tests/test_roster_idempotency.py
git commit -m "feat: use a Shanghai business clock"
```

### Task 4: Enforce strict child and duck mutations

**Files:**
- Modify: `app/backend/routes/resources.py`
- Modify: `tests/test_deactivation.py`
- Modify: `tests/test_api.py`

**Interfaces:**
- Consumes: Task 1 resource DTOs and Task 3 business clock.
- Produces: normalized P5-compatible resource writes that reject server-owned fields.

- [ ] **Step 1: Change resource tests to the desired strict behavior**

Replace the legacy assertion that `active=false` is silently ignored with a 422/no-write assertion. Add whitespace/null normalization, maximum lengths, unknown fields, 404, and exact response tests.

- [ ] **Step 2: Verify RED**

```bash
/Users/lddmay/AiCoding/pomegranagent/.venv/bin/pytest -q tests/test_deactivation.py tests/test_api.py -k 'resource or child or duck'
```

- [ ] **Step 3: Switch routes to strict DTOs**

Create/update only the public fields from `model_dump()`, force active state only on creation, preserve active/deactivation state on update, and leave avatar existence validation for Task 5.

- [ ] **Step 4: Verify GREEN**

Run the Step 2 command and `tests/test_api_errors.py`.

- [ ] **Step 5: Commit**

```bash
git add app/backend/routes/resources.py tests/test_deactivation.py tests/test_api.py
git commit -m "feat: reject server-owned resource fields"
```

### Task 5: Deliver avatar media backend and UI

**Files:**
- Create: `app/backend/services/avatar_media.py`
- Create: `app/backend/routes/media.py`
- Modify: `app/backend/routes/resources.py`
- Modify: `app/backend/main.py`
- Create: `app/frontend/shared/avatar.mjs`
- Modify: `app/frontend/teacher/views/management.mjs`
- Modify: `app/frontend/teacher/styles.css`
- Modify: `app/frontend/child/view.mjs`
- Modify: `app/frontend/child/styles.css`
- Create: `tests/test_avatar_media.py`
- Modify: `tests/frontend/teacher/management.test.mjs`
- Modify: `tests/frontend/child/view.test.mjs`
- Modify: `tests/browser/test_teacher_management.py`
- Modify: `tests/browser/test_child_shell.py`

**Interfaces:**
- Produces: `store_avatar`, `load_avatar`, `validate_avatar_reference`.
- Produces: teacher `POST /api/media/avatars` and public `GET /api/media/avatars/{media_id}`.
- Produces: `renderAvatarImage(document, avatar, fallbackText)` that only accepts canonical same-origin media URLs.
- Consumes: Task 2 `AvatarMedia`, Task 1 media DTO/path, and Task 4 resource writes.

- [ ] **Step 1: Write failing backend media tests**

Test teacher authentication before parsing, valid PNG/JPEG/WebP, EXIF orientation, metadata stripping, max-edge resize, fixed WebP response, SVG/GIF/animation/polyglot/malformed/oversize rejection, atomic rename cleanup, missing row/file, symlink/path escape, headers, and reference validation.

- [ ] **Step 2: Verify backend RED**

```bash
/Users/lddmay/AiCoding/pomegranagent/.venv/bin/pytest -q tests/test_avatar_media.py tests/test_teacher_auth.py tests/test_http_boundary.py
```

- [ ] **Step 3: Implement media service and routes**

Use `UploadFile`, a bounded read, Pillow `verify` followed by a fresh decode, EXIF transpose, static frame enforcement, 1024-pixel thumbnail, quality-88 WebP, SHA-256, UUID metadata/file names, `fsync` plus atomic replace, and compensating cleanup on DB/file failure.

- [ ] **Step 4: Verify backend GREEN**

Run the Step 2 command and `tests/test_api_errors.py`.

- [ ] **Step 5: Write failing frontend avatar tests**

Assert file input/preview/upload/save sequence, old-avatar preservation, upload-failure form retention, remove action, strict response parsing, canonical URL only, child card image, and image-error initial fallback. External, `javascript:`, data, and malformed URLs must never create an image.

- [ ] **Step 6: Verify frontend RED**

```bash
node --test tests/frontend/teacher/management.test.mjs tests/frontend/child/view.test.mjs
```

- [ ] **Step 7: Implement shared renderer and dialogs**

Upload the selected file before the resource mutation, retain the original form snapshot and request ID across retry, preview with a revocable object URL, and restore focus/status on failure. Render canonical images in management and child selection with decorative empty alt and initial fallback.

- [ ] **Step 8: Verify frontend/browser GREEN**

```bash
node --test tests/frontend/teacher/management.test.mjs tests/frontend/child/view.test.mjs
/Users/lddmay/AiCoding/pomegranagent/.venv/bin/pytest -q tests/browser/test_teacher_management.py tests/browser/test_child_shell.py
```

- [ ] **Step 9: Commit**

```bash
git add app/backend/services/avatar_media.py app/backend/routes/media.py app/backend/routes/resources.py app/backend/main.py app/frontend/shared/avatar.mjs app/frontend/teacher/views/management.mjs app/frontend/teacher/styles.css app/frontend/child/view.mjs app/frontend/child/styles.css tests/test_avatar_media.py tests/frontend/teacher/management.test.mjs tests/frontend/child/view.test.mjs tests/browser/test_teacher_management.py tests/browser/test_child_shell.py
git commit -m "feat: add safe avatar uploads"
```

### Task 6: Deliver atomic monthly roster backend and UI

**Files:**
- Modify: `app/backend/services/roster.py`
- Modify: `app/backend/routes/roster.py`
- Modify: `app/frontend/teacher/views/management.mjs`
- Modify: `app/frontend/teacher/styles.css`
- Modify: `tests/test_roster_idempotency.py`
- Modify: `tests/test_teacher_auth.py`
- Modify: `tests/frontend/teacher/management.test.mjs`
- Modify: `tests/browser/test_teacher_management.py`

**Interfaces:**
- Produces: `set_monthly_roster(db, payload, now) -> MonthlyRosterResponse` and static `POST /api/roster/month`.
- Consumes: Task 1 monthly DTOs and existing roster ledger/hash helpers.

- [ ] **Step 1: Write failing monthly roster service tests**

Cover 1–31 unique in-month dates, distinct active pairs, all-child validation before writes, conflict/no-change, selected-date replacement, untouched dates, replay, same-ID conflict, processing state, flush/commit rollback, and two-session concurrency.

- [ ] **Step 2: Verify backend RED**

```bash
/Users/lddmay/AiCoding/pomegranagent/.venv/bin/pytest -q tests/test_roster_idempotency.py tests/test_teacher_auth.py
```

- [ ] **Step 3: Implement monthly service and static route**

Canonicalize entries by date and child IDs, use operation `monthly_roster`, validate all IDs in one query, query all occupied dates before deletion, replace only submitted dates, and commit ledger plus rows once. Register `/month` before `/{roster_date}`.

- [ ] **Step 4: Verify backend GREEN**

Run the Step 2 command twice for the real concurrency case if its first run hits the recorded P5 timing flake; both successful final runs must be recorded.

- [ ] **Step 5: Write failing modal tests**

Assert the monthly launcher is enabled, month/date rows and two distinct dropdowns are generated, rows can be removed, same-body retry reuses UUID, conflict retains input, explicit overwrite uses a new UUID, exact ack is parsed, and reload reflects saved dates.

- [ ] **Step 6: Verify frontend RED**

```bash
node --test tests/frontend/teacher/management.test.mjs
```

- [ ] **Step 7: Implement monthly modal and responsive layout**

Default to the current server business month, pre-generate duty rows from active-child count and two children per duty day, allow arbitrary date edits/removals, prevent duplicate pair selection, and keep single-day/auto fallbacks unchanged.

- [ ] **Step 8: Verify frontend/browser GREEN and commit**

```bash
node --test tests/frontend/teacher/management.test.mjs
/Users/lddmay/AiCoding/pomegranagent/.venv/bin/pytest -q tests/browser/test_teacher_management.py tests/browser/test_release_viewports.py -k roster
git add app/backend/services/roster.py app/backend/routes/roster.py app/frontend/teacher/views/management.mjs app/frontend/teacher/styles.css tests/test_roster_idempotency.py tests/test_teacher_auth.py tests/frontend/teacher/management.test.mjs tests/browser/test_teacher_management.py
git commit -m "feat: add monthly partner roster entry"
```

### Task 7: Deliver weekly metrics backend and Today UI

**Files:**
- Create: `app/backend/services/reports.py`
- Create: `app/backend/routes/reports.py`
- Modify: `app/backend/main.py`
- Modify: `app/frontend/teacher/views/today.mjs`
- Modify: `app/frontend/teacher/styles.css`
- Create: `tests/test_weekly_reports.py`
- Modify: `tests/test_teacher_auth.py`
- Modify: `tests/frontend/teacher/today.test.mjs`
- Modify: `tests/browser/test_teacher_today.py`

**Interfaces:**
- Produces: `weekly_report(db, week_start, week_end_exclusive) -> WeeklyReportResponse` and `GET /api/reports/weekly`.
- Consumes: Task 3 business week and Task 1 report DTO.

- [ ] **Step 1: Write failing weekly service/route tests**

Test auth-first behavior, no/one query parameter, Monday validation, inclusive/exclusive boundaries, completed count, distinct child count, confirmed count, failed analysis count, global pending backlog, exact zero response, corrupted enum fail-closed behavior, and bounded SQL statement count.

- [ ] **Step 2: Verify backend RED**

```bash
/Users/lddmay/AiCoding/pomegranagent/.venv/bin/pytest -q tests/test_weekly_reports.py tests/test_teacher_auth.py
```

- [ ] **Step 3: Implement aggregate service and route**

Use conversation `date` for the weekly window, distinct child IDs, confirmed assessments joined to conversations, failed jobs joined to conversations, and the same succeeded-plus-pending/draft definition used by Review for cumulative backlog.

- [ ] **Step 4: Verify backend GREEN**

Run the Step 2 command.

- [ ] **Step 5: Write failing Today tests**

Assert strict response parsing, five labels and week range, zero state, independent loading, independent failure/retry, stale-response suppression, and no impact on roster/pending/processing/failed panels.

- [ ] **Step 6: Implement fifth independent Today panel**

Give weekly metrics its own generation token, status region, retry button, and responsive metric grid. Remove “本周指标暂不可用”.

- [ ] **Step 7: Verify frontend/browser GREEN and commit**

```bash
node --test tests/frontend/teacher/today.test.mjs
/Users/lddmay/AiCoding/pomegranagent/.venv/bin/pytest -q tests/browser/test_teacher_today.py tests/browser/test_release_viewports.py -k today
git add app/backend/services/reports.py app/backend/routes/reports.py app/backend/main.py app/frontend/teacher/views/today.mjs app/frontend/teacher/styles.css tests/test_weekly_reports.py tests/test_teacher_auth.py tests/frontend/teacher/today.test.mjs tests/browser/test_teacher_today.py
git commit -m "feat: show weekly teacher metrics"
```

### Task 8: Deliver advanced search backend and Search UI

**Files:**
- Modify: `app/backend/services/history.py`
- Modify: `app/backend/routes/conversations.py`
- Modify: `app/frontend/teacher/views/reports.mjs`
- Modify: `app/frontend/teacher/styles.css`
- Create: `tests/test_conversation_search.py`
- Modify: `tests/test_conversation_history.py`
- Modify: `tests/test_teacher_auth.py`
- Modify: `tests/frontend/teacher/reports.test.mjs`
- Modify: `tests/browser/test_teacher_reports.py`

**Interfaces:**
- Produces: `search_conversations(db, payload) -> ConversationSearchPage` and static `POST /api/conversations/search`.
- Consumes: Task 1 search DTOs and existing page-wide history projection/integrity validation.

- [ ] **Step 1: Write failing search service/route tests**

Test auth first, extra/invalid ranges/statuses, AND between filter families, OR within status arrays, frozen-message keyword matching, escaped `%`, `_`, and `\`, ascending/descending `(ended_at,id)` ordering, cursor fingerprint/direction, corrupt/mismatched cursor, stable pagination with equal timestamps/new inserts, fixed query budget, and unchanged GET history.

- [ ] **Step 2: Verify backend RED**

```bash
/Users/lddmay/AiCoding/pomegranagent/.venv/bin/pytest -q tests/test_conversation_search.py tests/test_conversation_history.py tests/test_teacher_auth.py
```

- [ ] **Step 3: Implement query, cursor, and static route**

Build a filter fingerprint from canonical JSON excluding cursor/limit. Encode the last UTC `ended_at`, ID, sort, and fingerprint with URL-safe base64. Reject mismatches. Use `EXISTS` for keyword/frozen-message matching and feed candidate IDs through the existing strict page projection.

- [ ] **Step 4: Verify backend GREEN**

Run the Step 2 command.

- [ ] **Step 5: Write failing Search UI tests**

Assert child/date/analysis/review/end-reason/keyword/sort controls, invalid date prevention, POST body exactness, cursor omission on new search, load-more retention/retry, empty state, strict response parsing, and Review deep link.

- [ ] **Step 6: Implement advanced Search view**

Remove the capability disclaimer, keep cursor out of the URL hash, reset results on new filters, preserve rendered rows and cursor on load-more failure, and provide accessible labels/statuses at both teacher viewports.

- [ ] **Step 7: Verify frontend/browser GREEN and commit**

```bash
node --test tests/frontend/teacher/reports.test.mjs
/Users/lddmay/AiCoding/pomegranagent/.venv/bin/pytest -q tests/browser/test_teacher_reports.py tests/browser/test_release_viewports.py -k 'search or reports'
git add app/backend/services/history.py app/backend/routes/conversations.py app/frontend/teacher/views/reports.mjs app/frontend/teacher/styles.css tests/test_conversation_search.py tests/test_conversation_history.py tests/test_teacher_auth.py tests/frontend/teacher/reports.test.mjs tests/browser/test_teacher_reports.py
git commit -m "feat: add private advanced history search"
```

### Task 9: Add deterministic full-demo seed and release version

**Files:**
- Create: `app/backend/services/demo_seed.py`
- Create: `app/backend/demo_data/full_demo.json`
- Create: `scripts/seed_demo_database.py`
- Create: `tests/test_demo_seed.py`
- Modify: `app/backend/main.py`
- Modify: `scripts/rebuild_demo_database.py`
- Modify: `tests/test_rebuild_demo_database.py`
- Modify: `README.md`
- Modify: `app/version.json`
- Modify: `tests/test_runtime_health.py`

**Interfaces:**
- Produces: explicit `full-demo` seed CLI with anchor date, target DB/media roots, and optional force/archive behavior.
- Produces: release `2026.09.02-server-capabilities.1`, API `3`, schema `3`.
- Consumes: Tasks 2–8 models and service invariants.

- [ ] **Step 1: Write failing seed tests**

Test deterministic record/media hashes for a fixed anchor, minimum entity/status graph, frozen boundaries, analysis/review consistency, searchable keyword, weekly/growth readability, no credential/provider call, one-transaction rollback, non-empty refusal, and force archive of DB sidecars/media/log.

- [ ] **Step 2: Verify RED**

```bash
/Users/lddmay/AiCoding/pomegranagent/.venv/bin/pytest -q tests/test_demo_seed.py tests/test_rebuild_demo_database.py tests/test_runtime_health.py
```

- [ ] **Step 3: Implement deterministic seed service and CLI**

Use at least 8 synthetic children, 3 ducks, local generated avatar pixels, past/current/future roster pairs, 25+ historical conversations, all four analysis states, all three review states, and complete succeeded projections. Never call AI/TTS and never configure a PIN.

- [ ] **Step 4: Remove implicit person/demo seeding from lifespan**

Keep reference assessment dimensions idempotent. Ordinary startup migrates and seeds only dimensions; demo people require the explicit CLI.

- [ ] **Step 5: Update release manifest and verify GREEN**

Run the Step 2 command plus:

```bash
/Users/lddmay/AiCoding/pomegranagent/.venv/bin/pytest -q tests/e2e.py
```

- [ ] **Step 6: Commit**

```bash
git add app/backend/services/demo_seed.py app/backend/demo_data/full_demo.json scripts/seed_demo_database.py tests/test_demo_seed.py app/backend/main.py scripts/rebuild_demo_database.py tests/test_rebuild_demo_database.py README.md app/version.json tests/test_runtime_health.py
git commit -m "feat: add deterministic full demo seed"
```

### Task 10: Build retained live-provider UAT and release gates

**Files:**
- Create: `scripts/run_live_provider_uat.py`
- Create: `scripts/live_provider_uat_server.py`
- Create: `tests/test_live_provider_uat_harness.py`
- Create: `docs/live-provider-uat-checklist.md`
- Create: `tests/fixtures/live_provider/avatars/child.png`
- Create: `tests/fixtures/live_provider/avatars/duck.jpg`
- Modify: `.gitignore`
- Modify: `scripts/run_interaction_acceptance.py`
- Modify: `tests/test_interaction_acceptance_runner.py`
- Modify: `tests/browser/child_server.py`
- Modify: `tests/browser/conftest.py`
- Modify: `tests/browser/test_child_shell.py`
- Modify: `tests/browser/test_release_viewports.py`
- Modify: `tests/conftest.py`
- Create: `tests/fixtures/interaction_acceptance/p5_selector_oracle.json`
- Create: `tests/fixtures/live_provider/avatars/PROVENANCE.json`
- Modify: `tests/test_database_safety.py`
- Modify: `tests/test_frontend_foundation.py`
- Modify: `tests/test_review_atomicity.py`

**Interfaces:**
- Produces: a non-default `run_live_provider_uat.py` command that retains one complete evidence directory and owns only its own process group.
- Produces: updated deterministic route/browser inventory for all P6 capabilities while continuing to block providers.
- Consumes: explicit full-demo seed, runtime path settings, all P6 APIs, real `.env` provider credentials, and current Chromium.

- [ ] **Step 1: Write failing harness isolation/redaction tests**

Use fake subprocess/provider inputs to prove run ID uniqueness, app-mode run-scoped DB/log/TTS/media paths, random loopback port, secret allowlist into the backend only, PID ownership, no cleanup of retained evidence, sanitized provider summaries, screenshot manifest hashes, and protected resource before/after equality.

- [ ] **Step 2: Verify RED**

```bash
/Users/lddmay/AiCoding/pomegranagent/.venv/bin/pytest -q tests/test_live_provider_uat_harness.py tests/test_interaction_acceptance_runner.py
```

- [ ] **Step 3: Implement the retained run harness**

Create `artifacts/real-uat/<UTC-run-id>-<head12>/` with `duck-diary-uat.db`, media, TTS cache, log, screenshots, manifest, journey, issues, and sanitized provider summary. Seed synthetic data, start one app-mode uvicorn process, validate health/version, and terminate only that process group. Never delete the run directory.

- [ ] **Step 4: Extend deterministic inventory and browser fixtures**

Add the four new teacher capabilities, runtime/media public reads, two teacher viewports, two child viewports, upload chooser fixtures, monthly conflict/retry, weekly isolation, advanced search pagination, and canonical avatar fallback. Keep fake provider/audio/SpeechRecognition boundaries in deterministic tests.

- [ ] **Step 5: Verify focused harness and browser gates**

```bash
/Users/lddmay/AiCoding/pomegranagent/.venv/bin/pytest -q tests/test_live_provider_uat_harness.py tests/test_interaction_acceptance_runner.py
/Users/lddmay/AiCoding/pomegranagent/.venv/bin/pytest -q tests/browser
```

- [ ] **Step 6: Commit harness and gate changes**

```bash
git add scripts/run_live_provider_uat.py scripts/live_provider_uat_server.py tests/test_live_provider_uat_harness.py docs/live-provider-uat-checklist.md tests/fixtures/live_provider/avatars .gitignore scripts/run_interaction_acceptance.py tests/test_interaction_acceptance_runner.py tests/browser/child_server.py tests/browser/conftest.py tests/browser/test_child_shell.py tests/browser/test_release_viewports.py tests/conftest.py tests/fixtures/interaction_acceptance/p5_selector_oracle.json tests/test_database_safety.py tests/test_frontend_foundation.py tests/test_review_atomicity.py
git commit -m "test: add retained live provider UAT"
```

- [ ] **Step 7: Run all deterministic verification serially**

Run exactly in this order, never concurrently:

```bash
/Users/lddmay/AiCoding/pomegranagent/.venv/bin/pytest -q --ignore=tests/browser
node --test tests/frontend/child/*.test.mjs tests/frontend/shared/*.test.mjs tests/frontend/teacher/*.test.mjs
/Users/lddmay/AiCoding/pomegranagent/.venv/bin/pytest -q tests/browser
/Users/lddmay/AiCoding/pomegranagent/.venv/bin/python scripts/run_interaction_acceptance.py run <literal-reviewed-40-hex-commit>
```

If the recorded P5 roster concurrency test flakes, re-run that exact test twice and include all three outputs in the final evidence; do not hide the first failure.

- [ ] **Step 8: Run live-provider UAT and retain evidence**

Start the harness, then use the connected in-app browser to walk the approved checklist. Capture teacher 1024×768 and 1440×900 plus child 1024×576 and 1280×720 key states. Exercise real DeepSeek chat/analysis and real Edge-TTS. Use controlled text handoff for autonomous child input and mark physical microphone/acoustic recognition `HUMAN_UAT_REQUIRED`.

```bash
/Users/lddmay/AiCoding/pomegranagent/.venv/bin/python scripts/run_live_provider_uat.py --retain --print-runtime-json --expected-head <literal-reviewed-40-hex-commit>
```

- [ ] **Step 9: Final evidence validation**

Accept evidence only after the harness exits successfully with a terminal
`COMPLETE` manifest. The harness performs the authoritative registered-secret
and forbidden-pattern scans over its bounded artifact inventory; do not run a
broad text search across `reviewed-source/`, because ordinary source literals
are not retained credentials and would create false positives. Verify every
manifest screenshot hash, compare protected main-checkout DB/WAL/SHM/log/TTS
hashes, and open the retained DB read-only to confirm live conversation,
analysis, confirmed review, weekly metric, and search result provenance.

```bash
python -c 'import json; value=json.load(open("artifacts/real-uat/<run-id>/manifest.json", encoding="utf-8")); assert value["status"] == "COMPLETE"'
(cd artifacts/real-uat/<run-id> && shasum -a 256 -c SHA256SUMS)
```

- [ ] **Step 10: Commit only curated documentation, never raw retained evidence**

```bash
git add docs/manual/assets/<run-id> docs/live-provider-uat-checklist.md
git commit -m "docs: retain P6 UAT manual screenshots"
```

Raw `artifacts/real-uat/<run-id>/` remains ignored and locally retained for the release owner.
