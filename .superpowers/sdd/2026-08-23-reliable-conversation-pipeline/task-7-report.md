# Task 7 Report — Reversible Resource Deactivation and Race-Safe New Work

## Status

DONE

## Scope and implementation

- Added the teacher-only resource router for the twelve canonical child/duck
  list, CRUD, state, and tombstone method/path pairs.
- Moved the six legacy child and six legacy duck resource handlers out of
  `main.py`; it now registers the resource router once. No unrelated handler,
  lifespan, auth, roster, review, or model code was changed.
- Added `services/deactivation.py` with conditional state transitions. Child
  deactivation has a SQL `active=true AND NOT EXISTS(active conversation)`
  predicate; zero-row transitions fresh-read and classify missing, same-state,
  or active-conversation outcomes. Duck transitions follow the same
  conditional/idempotent pattern without the conversation guard.
- Lists filter active rows in SQL by default and use one composed query per
  resource type: correlated roster-count/existence subqueries for children and
  a correlated feeding-log count for ducks. UTC presentation converts SQLite's
  naive stored timestamps to aware values serialized with `Z`.
- Child creation always creates an active child, and child PUT changes only
  name/nickname/avatar. State changes are owned solely by the four state
  routes. Authenticated DELETE is a no-body 410 tombstone with no target
  lookup/write; the teacher dependency still runs first.
- The deactivation-wins first-conversation race was reproduced against the
  unmodified chat service. The minimal required chat change is a first-write,
  conditional no-op `UPDATE children ... WHERE id AND active=true` after
  ending the stale observation transaction and before a first conversation or
  chat-request row is created.

## TDD evidence

### RED

Before production edits:

```text
./.venv/bin/pytest -q tests/test_deactivation.py
3 failed in 0.23s
```

The failures were intentional contract gaps: teacher child lists omitted
`deactivated_at`, `future_roster_entries`, and `has_active_conversation`; duck
deactivation was `405`; and locked state routes were `405` rather than the
required `401 TEACHER_AUTH_REQUIRED`.

After the resource service/router existed but before changing `chat.py`, the
actual two-`SessionLocal` deterministic Event/SQL-event race was run:

```text
./.venv/bin/pytest -q tests/test_deactivation.py -k "first_conversation_and_deactivation"
1 failed, 1 passed
```

The deactivation-wins order deterministically settled as
`Child.active=false` plus a newly inserted active conversation. This proved
the stale-read race and justified the chat serialization guard. The
chat-wins order already settled safely.

### GREEN

After the conditional active-child first write:

```text
./.venv/bin/pytest -q tests/test_deactivation.py -k "first_conversation_and_deactivation"
2 passed, 10 deselected
./.venv/bin/pytest -q tests/test_chat_idempotency.py tests/test_deactivation.py
34 passed
```

Final focused verification was run twice:

```text
./.venv/bin/pytest -q tests/test_deactivation.py
14 passed
./.venv/bin/pytest -q tests/test_deactivation.py
14 passed
./.venv/bin/pytest -q tests/test_deactivation.py -k "race or rollback or hard_delete or query_count"
7 passed, 7 deselected
```

The requested Task 1–7 regression gate also passed:

```text
./.venv/bin/pytest -q \
  tests/test_pipeline_models.py \
  tests/test_chat_idempotency.py \
  tests/test_conversation_completion.py \
  tests/test_analysis_worker.py \
  tests/test_roster_idempotency.py \
  tests/test_review_atomicity.py \
  tests/test_deactivation.py
147 passed
```

Warnings are pre-existing `datetime.utcnow` and TestClient deprecation
warnings; no test failed or emitted an application/database error.

## Concurrency, history, and rollback evidence

- Both real threaded `SessionLocal` race orders use `Event` coordination and
  SQL engine events, with no sleep:
  - chat-first holds its conversation insert/write boundary; it creates one
    active conversation and one chat-request record, while deactivation gets
    `409 ACTIVE_CONVERSATION_EXISTS`;
  - deactivation-first pauses chat after its stale read, commits inactive
    state, then chat receives `404 CHILD_NOT_FOUND`, with zero conversations
    and zero request records for that request ID.
- Both assert no leaked `OperationalError`, no inactive child with a new active
  conversation, and no partial `ChatRequestRecord`.
- Child deactivation history fixtures retain exactly the original IDs for
  roster rows (past/today/future), conversation, messages, chat request,
  analysis job, feeding/emotion/insight projections, assessment, and score.
  Default teacher/public-today reads omit an inactive child; reactivation
  makes the same child ID and retained today roster membership visible again.
- Duck deactivation retains all feeding-log IDs and the `DuckArchive` ID,
  removes the duck from default lists and new chat context, and keeps the
  inactive duck ID in historical review detail.
- Forced state `flush` and `commit` exceptions roll back `active` and
  `deactivated_at` as verified from a fresh `SessionLocal`; a forced unrelated
  `IntegrityError` is re-raised, not relabeled.

## Query, auth, and route inventory evidence

- With multiple active/inactive rows, each `GET /api/children?include_inactive=true`
  and `GET /api/ducks?include_inactive=true` made exactly two statements: one
  teacher-session lookup and one composed list statement. Therefore the list
  itself is one statement with no per-row count/existence query.
- All twelve canonical routes are present exactly once in the effective
  included-router inventory and each depends on `require_teacher_session`.
  The public `/api/roster/today` route remains present.
- Locked list/state/delete calls return `401 TEACHER_AUTH_REQUIRED`; authenticated
  existing and missing DELETE calls return `410 HARD_DELETE_DISABLED`. The
  delete query capture records only one `teacher_sessions` query per request,
  never a child/duck lookup or write.

## Additional verification

```text
./.venv/bin/python -m py_compile \
  app/backend/main.py \
  app/backend/routes/resources.py \
  app/backend/services/deactivation.py \
  app/backend/services/chat.py \
  tests/test_deactivation.py
# exit 0

git diff --check
# exit 0
```

No external service, real AI/TTS provider, network service, or application
database was used. All tests used the disposable test SQLite fixture.

## Preserved unrelated work

At task start and completion, the following non-Task-7 work was preserved and
not staged: `.workbuddy/memory/2026-08-22.md`,
`docs/superpowers/specs/2026-08-23-interaction-stabilization-design.md`,
`.superpowers/brainstorm/`, and `docs/superpowers/plans/`.

`tests/test_teacher_auth.py` was inspected but not modified. It has two
pre-existing/stale failures outside this task's ownership: it scans only direct
FastAPI routes even though the installed FastAPI stores included routers in
`_IncludedRouter`, and it omits the frozen Task 2-required chat `request_id`.

## Commit and owned files

`feat: replace hard deletes with deactivation` (final SHA is recorded in the
task handoff and repository HEAD).

- `app/backend/main.py`
- `app/backend/routes/resources.py`
- `app/backend/services/deactivation.py`
- `app/backend/services/chat.py`
- `tests/test_deactivation.py`
- `.superpowers/sdd/2026-08-23-reliable-conversation-pipeline/task-7-report.md`

## Review evidence correction

The Task 7 review requested stronger release evidence. This correction changes
only `tests/test_deactivation.py` and this report; production files remain at
`68a4143` because the strengthened tests did not expose an invariant failure.

- The route inventory now recursively flattens both direct application routes
  and every `_IncludedRouter.original_router` route. It normalizes every
  `{parameter_name}` path placeholder to `{}` before `Counter`-based
  `(method, path)` counting, so a direct legacy
  `DELETE /api/children/{id}` would produce the same normalized pair as the
  canonical `{child_id}` route and fail the exact-one assertion. It reasserts
  teacher-session protection for all twelve canonical routes and verifies that
  DELETE has only the direct teacher dependency, not a direct `get_db`
  dependency.
- Each real `claim_chat_request` versus `set_child_active` race now seeds an
  ended transcript, past/today/future rosters, an unrelated retained chat
  request, analysis job, feeding/emotion/insight rows, assessment, and score
  before racing two independent `SessionLocal` threads. Fresh-session
  snapshots compare 17 tables: children, ducks, rosters, conversations,
  messages, chat requests, analysis jobs, roster requests, feeding/emotion/
  insight projections, dimensions, assessments/scores, archives, credentials,
  and sessions. The chat winner may add exactly one active conversation and
  one processing request; the deactivate winner may change only the target
  child state/timestamp. Every seeded row tuple is asserted unchanged, and the
  losing request is asserted absent.
- Duck same-state deactivation now explicitly returns `changed:false` while
  retaining the exact non-null `deactivated_at` timestamp.

The first stricter race attempt was intentionally RED because its generic
immutable-row helper also compared the explicitly allowed child state change
in the deactivation-wins case:

```text
./.venv/bin/pytest -q tests/test_deactivation.py -k "race or route_inventory or duck_deactivation"
1 failed, 3 passed, 10 deselected
```

The helper was narrowed only to immutable history tables; child state is
checked separately against its permitted transition. No production code was
altered. GREEN evidence:

```text
./.venv/bin/pytest -q tests/test_deactivation.py
14 passed
./.venv/bin/pytest -q tests/test_deactivation.py
14 passed
./.venv/bin/pytest -q tests/test_deactivation.py -k "race or route_inventory or history or duck_deactivation"
6 passed, 8 deselected
```

The Task 1–7 regression gate was rerun after the evidence correction:

```text
./.venv/bin/pytest -q \
  tests/test_pipeline_models.py \
  tests/test_chat_idempotency.py \
  tests/test_conversation_completion.py \
  tests/test_analysis_worker.py \
  tests/test_roster_idempotency.py \
  tests/test_review_atomicity.py \
  tests/test_deactivation.py
147 passed
```

Task 7 implementation commit: `68a4143 feat: replace hard deletes with deactivation`.
Evidence correction commit: `824087b test: strengthen deactivation release evidence`.
