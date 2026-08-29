# Teacher Task 6 Brief — Safe management, idempotent rostering, and bounded history reports

## Execution boundary

- Start from the existing `master` checkout at exact HEAD
  `05251b84adf85418e1179579dc49784e1374cc1b`.
- Continue from completed Teacher Tasks 1–5. Do not create a worktree, replay a
  previous task, or alter a completed Task 5 review contract.
- This brief supersedes the stale Task 6 plan where repository reality differs.
  In particular, the old `legacy-routes.mjs` is the stale implementation to
  replace; `views/unavailable.js` does not exist, and new teacher view modules
  use the established `.mjs` extension.
- Use strict TDD: each named unit starts with a focused test that is truly RED,
  then only the smallest implementation needed for GREEN. Do not batch units.
- Do not install packages or browsers, contact a provider, call an external
  service, edit the real application database, real TTS cache, or real log.
- Every pytest command is serial. Before and after *each* pytest invocation,
  verify the preserved incident-log triplet is unchanged:

  ```text
  SHA-256  5ee47c6b8322aee20aefecbf2344e8134cec18154fb7eb2d00c60116379fbeb7
  size     2961585
  mtime    1787939944
  ```

  Reuse the existing disposable test/database/log fixtures and lowest-level
  provider tripwires. Stop immediately if a tripwire, the real DB, TTS cache,
  or the log triplet changes. Never clean or rewrite the incident log.
- Preserve and never stage, revert, or modify these user-owned paths:
  - `.workbuddy/memory/2026-08-22.md`
  - `docs/superpowers/specs/2026-08-23-interaction-stabilization-design.md`
  - `.superpowers/brainstorm/`
  - `docs/superpowers/plans/`

## Scope and owned paths

### Backend history contract

- Modify `app/backend/routes/conversations.py`
- Modify `app/backend/routes/roster.py`
- Create `app/backend/services/history.py`
- Modify `app/backend/schemas.py`
- Create `tests/test_conversation_history.py`
- Modify `tests/test_roster_idempotency.py`
- Modify `tests/test_teacher_auth.py` only to add the new protected static
  history GET to the exact route/dependency inventory. This ownership was
  added after the first regression run proved the pre-existing inventory
  correctly rejects every unlisted route.

### Teacher management and reports

- Modify `app/frontend/teacher/app.js`
- Delete `app/frontend/teacher/legacy-routes.mjs`
- Create `app/frontend/teacher/views/management.mjs`
- Create `app/frontend/teacher/views/reports.mjs`
- Modify `app/frontend/teacher/styles.css`
- Modify `tests/test_frontend_foundation.py`
- Modify `tests/frontend/teacher/router.test.mjs`
- Create `tests/frontend/teacher/management.test.mjs`
- Create `tests/frontend/teacher/reports.test.mjs`
- Modify `tests/browser/test_teacher_routing.py`
- Create `tests/browser/test_teacher_management.py`
- Create `tests/browser/test_teacher_reports.py`
- Create and force-add
  `.superpowers/sdd/2026-08-23-teacher-workbench-and-acceptance/task-6-report.md`

No other file is in scope. In particular, do not modify Teacher HTML/PIN
tests, router/dirty-guard/review/today modules, browser fixtures, dependencies,
Child files, Pipeline services, or earlier task reports. If a required behavior
needs one of those files, stop and report a contract conflict rather than
expanding scope.

## Repository-reality rulings

| Stale behavior | Current truth | Frozen Task 6 ruling |
| --- | --- | --- |
| Management sends `DELETE` from the UI | Both DELETE endpoints are authenticated `410 HARD_DELETE_DISABLED` tombstones | No teacher UI code may issue a DELETE request. Preserve history with POST deactivate/reactivate only. |
| Manual roster writes `POST /api/roster` | That endpoint is an authenticated `410 LEGACY_ENDPOINT_REMOVED` tombstone | Manual save is only `PUT /api/roster/{ISO-date}` with a durable UUID. |
| Search calls `/api/conversations` with no queue and reads flat `feeding_logs`/`emotion` | Current `/api/conversations` requires `queue=pending|processing|failed`; detail is the nested review DTO | Add the bounded, explicit history list contract below. Search links to the existing review reader; it does not duplicate a detail reader. |
| Old Task 6 lists only frontend files | No existing route can honestly implement full historical search without queue ambiguity | The minimal new backend history endpoint is in this task's owned paths and has its own strict DTO and tests. |
| Growth is rendered by building an SVG string with `innerHTML` | Service data must be treated as untrusted at the browser boundary | Build SVG/text nodes with DOM APIs and `textContent`; never interpolate service strings into HTML. |
| Old tests assert search/delete failures | The intended Task 6 result is successful safe management/report routes | Replace those tests with success and safety evidence; do not preserve failure expectations. |

## Frozen backend history interface

Register this exact static route **before** the current dynamic
`GET /api/conversations/{conversation_id}` route:

```http
GET /api/conversations/history?limit=20&child_id=7&before_id=42
```

- `require_teacher_session` is required. Unauthenticated callers receive the
  existing `TEACHER_AUTH_REQUIRED` envelope before any business/database read.
- `child_id` is optional and, when present, is a positive integer.
- `before_id` is optional and, when present, is a positive integer.
- `limit` defaults to `20` and is bounded inclusively to `1..50`. There is no
  `queue`, `status`, free-text, unbounded page, offset, or legacy alias.
- After authentication, reject every unknown query key and every duplicate
  `limit`, `child_id`, or `before_id` with the standard `422 VALIDATION_ERROR`
  envelope. Only the exact three optional keys are accepted; parsing never
  silently takes a first/last duplicate value.
- Results use declared keyset semantics: `Conversation.id DESC`; when
  `before_id` is present, return only conversation IDs strictly lower than it.
  Read `limit + 1` rows, expose at most `limit`, and set `next_before_id` to
  the last returned item ID only when another row exists; otherwise it is null.
- The list includes ended, frozen conversations with a matching analysis job,
  including `pending`, `processing`, `failed`, `draft`, and `confirmed` states.
  It never lists an active conversation and never claims that an item is
  selectable unless the existing `GET /api/conversations/{id}` reader can load
  its detail.
- The bounded candidate query must require the same base projection as
  `get_review_detail`: ended status; non-null start/end/end_reason and frozen
  last-message ID; joined child; exactly one matching analysis job whose frozen
  boundary equals the conversation; valid job status and non-null `updated_at`;
  at least one frozen message; maximum frozen message ID equals the boundary;
  and a child-message count used for round.
- Before returning any page, validate *all* selected items as one unit. For a
  succeeded analysis, require exactly one assessment for that conversation with
  status pending/draft/confirmed, non-null finite overall, and a complete review
  projection readable by Task 4: every feeding row satisfies the strict review
  DTO; exactly one valid emotion; exactly one nonblank insight; score rows have
  unique positive dimensions, joined nonblank dimension names, integer 1–5
  values and string reasons; joined score count equals stored score count. For
  non-succeeded analysis, project unavailable and do not require review rows.
  A malformed assessment/projection or child/conversation mismatch raises
  `500 INTERNAL_ERROR` for the whole request; never return a partial page or a
  link that will deterministically fail detail loading.
- Use one bounded candidate query plus a constant number of page-wide `IN (...)`
  validation reads; the statement count is independent of page size and never
  performs per-item queries. Tests freeze the exact maximum budget selected by
  the implementation and compare limit 1 vs limit 20. Roll back the read session
  before either success or error return.

Add these exact strict Pydantic response models, inheriting
`StrictResponseModel`:

```text
ConversationHistoryItem
  id: PositiveInt
  child: ChildIdentity
  date: date
  completed_at: datetime
  status: Literal["ended"]
  end_reason: ConversationEndReason
  message_count: integer >= 1
  round: integer >= 0
  analysis_status: AnalysisJobStatus
  review_status: ReviewStatus
  revision: integer >= 0

ConversationHistoryPage
  items: list[ConversationHistoryItem]
  next_before_id: PositiveInt | null
```

The service must calculate `review_status` explicitly: a succeeded analysis
uses only an existing assessment status `pending`, `draft`, or `confirmed`;
every non-succeeded analysis uses `unavailable`. A succeeded row without a
    valid and complete assessment/review projection, an impossible
    ended/frozen/job/message projection, an invalid analysis state, or
    impossible count is an `INTERNAL_ERROR`, never a partly
filled response. The service must not call `list_review_queue` or accept its
queue parameter; list semantics are deliberately distinct.

## Frozen management interfaces

All resource reads/mutations remain teacher-session protected and use only the
current endpoints and DTOs.

### Children

```text
GET  /api/children?include_inactive=true
POST /api/children
PUT  /api/children/{positive-id}
POST /api/children/{positive-id}/deactivate
POST /api/children/{positive-id}/reactivate
```

- The management list must always request `include_inactive=true` and strictly
  accept every `TeacherChildOut` key:
  `id`, `name`, `nickname`, `avatar`, `active`, `deactivated_at`,
  `future_roster_entries`, `has_active_conversation`.
- Create/edit uses a native labeled form. `幼儿姓名` is required, trimmed, and
  constrained in the UI to 1–64 characters. `小名` is optional and at most 64;
  `头像` is optional and at most 255. Empty optional values are submitted as
  `null`. Create sends exactly `{name,nickname,avatar}`; edit sends the same
  three keys to the selected ID. It never submits an `active` field.
- Accept a create/edit acknowledgement only when its exact known `ChildOut`
  fields are own data, the returned ID is the expected ID, and normalized
  submitted display values match. Re-fetch the enriched list before declaring
  the row current. Do not render arbitrary response/error text.
- An active child has a button named `停用：{nickname-or-name}`. A native modal
  dialog named `停用{nickname-or-name}` must state the pre-mutation impact from
  the already loaded enriched row: active/visible duty participation stops,
  `future_roster_entries` is retained as historical schedule data, and no
  history is deleted. A row with `has_active_conversation === true` disables
  the stop action and states why; a 409 race from the server is handled with
  fixed local copy and a list reload.

### Ducks

```text
GET  /api/ducks?include_inactive=true
POST /api/ducks
PUT  /api/ducks/{positive-id}
POST /api/ducks/{positive-id}/deactivate
POST /api/ducks/{positive-id}/reactivate
GET  /api/ducks/{positive-id}/archive
POST /api/ducks/{positive-id}/summarize
```

- Strictly accept list keys `id`, `name`, `avatar`, `status`, `note`, `active`,
  `deactivated_at`, and `historical_feeding_log_count`.
- Create/edit retains the delivered duck capability through native labeled
  forms. `小鸭名字` is required/trimmed/1–64; avatar is at most 255; status at
  most 255; note at most 2000. Optional blanks become `null`. The exact bodies
  are `{name,avatar,status,note}`; no active field is submitted.
- Preserve archive access and explicit user-triggered `生成档案`, but replace
  `alert()` with accessible, fixed-copy inline/modal output. Summary results
  must validate exact own data `{duck_id,summary}` before display. `GET archive`
  accepts `summary:null|string` (bounded to 20,000 characters in the UI); null
  or blank displays fixed `暂无档案内容`. `POST summarize` requires matching duck
  ID and a nonblank string of at most 20,000 characters before success. The
  summary is the sole exception to the no-provider-content display rule: after
  this strict ID/type/length validation it is treated as application data and
  rendered only with `textContent`; raw provider errors/bodies are never shown.
  Browser tests stub both endpoints; no test may call a provider.
- The named deactivation dialog says that the loaded
  `historical_feeding_log_count` feeding records and archive remain. It does
  not imply that data will be erased.

### Reversible state mutation and undo

For either kind, a stop/restore request has no body and uses a per-target
single-flight lock. Request state must own a local controller and sequence;
the action is disabled before the request begins and remains disabled until the
owning request settles. Outer route cancellation, row reload, lock, navigation,
and an ignored-abort late success/rejection must not mutate DOM, focus, toast,
or error state for a newer owner.

The only valid state acknowledgement is an exact own-data
`DeactivationResponse`:

```text
id, kind, name, active, deactivated_at,
affected_future_roster_entries, changed
```

It must match selected ID, expected kind, the loaded canonical name, expected
active state, a nonnegative safe impact count, and an own boolean `changed`.
For deactivate, `deactivated_at` is a parseable timestamp; for reactivate, it
is exactly null. Only `changed === true` creates a 10-second undo toast. The
toast action is named `撤销停用：{nickname-or-name}` and sends the matching real
`/reactivate` request; it is never a client-only visual reversal. The timer,
toast, and any outer abort listener are removed by idempotent route cleanup.
`changed === false` reloads state without a false success/undo claim.

There is no permanent-delete button, request, retry, fallback, hidden control,
or `method: 'DELETE'` token in teacher frontend source.

## Frozen roster interfaces

The roster view first loads the roster list and enriched children list. It
uses active children only as selectable assignees, while retaining inactive
children’s names when rendering historical roster rows.

`GET /api/roster` is called with no query and gains the strict backend response
model `list[RosterListItem]`. Each exact item is:

```text
id: positive integer
cycle: trimmed nonblank string, max 64
date: exact ISO calendar date
child_id: positive integer
```

The frontend independently validates the exact own-data shape. Every historical
row must resolve `child_id` to exactly one item in the enriched
`include_inactive=true` child list; inactive names remain visible. A duplicate or
missing child mapping, malformed/extra roster key, invalid date/cycle, or failed
roster/child read renders fixed roster error and no misleading partial rows.

```http
PUT /api/roster/{YYYY-MM-DD}
Content-Type: application/json

{"request_id":"uuid","cycle":"2026-W34","child_ids":[7,8]}
```

```http
POST /api/roster/auto
Content-Type: application/json

{"request_id":"uuid","start_date":"2026-08-24","days":5,
 "cycle":"2026-W34","replace_existing":false}
```

- The retired `POST /api/roster` is never called.
- Both forms use native `<form>` controls, visible labels, `required`,
  min/max constraints, `form.reportValidity()`, and fixed local validation
  copy. Dates must also pass explicit exact ISO-calendar validation, including
  rejection of impossible dates. Cycle is trimmed nonblank and at most 64.
- Manual selection consists of exactly two distinct active child IDs. Automatic
  `days` is an integer 1–31 and `replace_existing` is an explicit, labeled
  boolean that defaults to false.
- Manual body keys are exactly `request_id`, `cycle`, and `child_ids`; its
  path date is never duplicated in the body. Automatic body keys are exactly
  `request_id`, `start_date`, `days`, `cycle`, and `replace_existing`.
- Both forms share one mutation lock. No double click, Enter repeat, or
  cross-form activation can create two concurrent roster writes.
- At the first valid submission, take an immutable normalized form snapshot
  and create one UUID. Pass it both as body `request_id` and DuckAPI's
  `requestId` header option. On timeout/offline/500/non-JSON/invalid response,
  keep that UUID and snapshot so an unchanged retry repeats *exactly* the same
  request. Any user input/change invalidates the retained snapshot and UUID.
- A daily success is an exact `DailyRosterResponse` matching submitted UUID,
  path date, normalized cycle, sorted selected IDs, and a boolean `replayed`.
  An auto success is an exact `AutoRosterResponse` matching UUID, bounded
  weekday schedule pairs, and boolean `replayed`. A mismatched/malformed
  acknowledgement is a fixed local failure, not success.
- `replayed:true` is a valid successful replay. `REQUEST_IN_PROGRESS`,
  `IDEMPOTENCY_CONFLICT`, `ROSTER_DATE_CONFLICT`, `CHILD_NOT_FOUND`, and every
  other server/network failure use fixed local copy, unlock controls, preserve
  the form, and never render raw messages. On valid success reload the roster
  and children data once.

## Frozen reports interfaces and route composition

`app.js` composes all existing routes without changing the manifest, router,
or dirty guard:

```js
const management = createManagementRoutes({
  request: (path, options) => window.DuckAPI.request(path, options),
  document,
  createAbortController: () => new AbortController(),
});
const reports = createReportRoutes({
  request: (path, options) => window.DuckAPI.request(path, options),
  document,
  createAbortController: () => new AbortController(),
  navigate: fragment => { window.location.hash = fragment; },
});
```

Route ownership is exact:

```text
today   -> createTodayRoute
review  -> createReviewRoute
children, ducks, roster -> createManagementRoutes
growth, search -> createReportRoutes
```

Delete `legacy-routes.mjs` after all routes are composed. `app.js` remains the
only module with the browser global wiring; both new view modules require exact
own-data injected dependencies and must not read `window`, `DuckAPI`,
`DuckAuth`, direct `fetch`, or global alert APIs.

### Growth

- Preserve the deep link `#growth?child_id=7`. On route entry, fetch the
  all-children list with `include_inactive=true`; an absent `child_id` renders a
  labeled selector and does not request growth. A syntactically valid but
  currently absent child ID renders fixed local selection copy and also sends
  no growth request.
- Selecting a child calls injected `navigate` with canonical
  `#growth?child_id={positive-id}`. The existing Router owns Hash, back/forward,
  route focus, confirmation, epoch, and outer abort; Reports does not install a
  second hash listener.
- `GET /api/analysis/growth?child_id={id}` is the only growth API. Strictly
  validate exact top-level `{child_id,dimensions}` and each dimension's exact
  `{key,name,points}` with nonblank strings; each point is exact `{date,score}`
  with an ISO date and integer score 1–5. Result `child_id` must equal selection.
- Create one local controller and monotonic sequence per selection/request,
  bridge outer abort to it, detach the bridge in cleanup, and check both local
  ownership and `context.isCurrent()` after every await. A delayed A success or
  rejection must never replace B's chart/status/focus. Build all chart content
  with DOM/SVG node APIs and `textContent`.

### History search

- Preserve the `#search` route and add optional canonical
  `#search?child_id={positive-id}` filtering. Children are loaded with
  `include_inactive=true`; the filter includes inactive children so retained
  history remains findable.
- Changing the Search child selector never refreshes in place. Selection calls
  only injected `navigate('#search?child_id={positive-id}')`; clearing calls only
  `navigate('#search')`. Router remains the sole Hash/back/forward/DirtyGuard
  owner. A syntactically valid but absent ID renders fixed selection copy and
  sends no history request.
- Load only the frozen history endpoint with `limit=20`, optional `child_id`,
  and `before_id` from the last accepted page. Strictly validate the complete
  history page/item DTO above before replacing or appending content.
- A result is a real anchor to `#review?conversation_id={id}`. Reports neither
  flattens detail fields nor calls the review PUT/PATCH/assessment endpoints.
- `加载更多` exists only when a validated `next_before_id` exists, disables while
  its one request is in flight, and appends only if the same history sequence
  remains current. A late previous-page success/rejection cannot append a row,
  show an error, restore focus, or alter a newer filter.
- Empty, malformed, HTTP, non-JSON, offline, and timeout results use fixed
  local copies and an accessible retry. No server error text is put in the DOM.

## UI, accessibility, and lifecycle requirements

- Each view has one visible `<h1>`; route focus remains Router-owned.
- Every input/select/textarea/checkbox has a visible native `<label>`; no
  placeholder is its only label. Validation uses `aria-invalid`, fixed
  field-local errors, and focus moves to the first invalid control.
- Deactivation dialogs are native modal `<dialog>` elements with accessible
  names, Cancel and explicit Confirm controls. Escape/cancel performs no
  mutation and restores focus to the launching action.
- Use `role="status"`/`aria-live="polite"` for success and current load state;
  use `role="alert"` only for fixed failures. Never expose raw `error.message`,
  HTTP body, provider errors, or request IDs in UI copy. The only provider-
  derived application data that may render is a strictly validated matching
  duck archive summary, inserted with `textContent` as frozen above.
- Every action, navigation link, form control, confirmation, and undo control
  is at least 44×44. Maintain visible focus and reduced-motion behavior.
- At 1024×768 and 1440×900 there is no document-level horizontal overflow.
  At 1024, management uses responsive grids/cards or bounded internal table
  scroll containers with `min-width:0`; long historical content wraps rather
  than widening the page.
- Each loader returns idempotent cleanup that aborts local controllers, removes
  outer-signal listeners, clears timers/toasts, and prevents late DOM writes.
  `teacherRouter.stop()` during immediate lock must leave no management/report
  data, handlers, undo timer, or pending visual mutation behind.
- Task 5's shared DirtyGuard remains injected only into Review and remains the
  Router's `confirmLeave` gate. A dirty review still guards every management or
  reports navigation, including active-route refresh; Task 6 must not modify
  DirtyGuard/router to bypass, duplicate, or reinterpret that behavior.

## TDD execution units

### Unit 1 — history backend contract

1. Add focused failing `tests/test_conversation_history.py` coverage for route
   order, pre-auth 401, exact query bounds, strict exact output, inactive-child
   filtering, pending/processing/failed/draft/confirmed state projection,
   cursor pagination, no active conversation, unknown/duplicate query rejection,
   and constant statement budget/no N+1. Add malformed frozen-message boundary,
   missing/duplicate/foreign assessment, invalid updated_at/status/end reason,
   and every succeeded review-projection integrity failure; each is whole-page
   `INTERNAL_ERROR` and emits no partial items.
2. Run the file serially and record its real RED because the route/service/DTO
   do not exist.
3. Add only schemas, history service, and static route needed for GREEN.
4. Re-run the focused file serially; verify the incident triplet before/after.

### Unit 2 — management loading, CRUD, and no DELETE

1. Add Node REDs for dependency validation, enriched child/duck DTO rejection,
   `include_inactive=true`, labeled/trimmed forms, and exact create/edit bodies
   with no active field.
2. Add browser REDs for visible labels, blank-name zero-request rejection,
   valid create/edit acknowledgement reload, the archive/summarize action with
   stubbed archive/provider routes, nullable archive, strict matching summary,
   HTML-like summary rendered as text, and the global no-DELETE request capture.
   Add create/edit/archive/summarize single-flight and ignored-abort late
   success/rejection after reload/navigation/lock; no stale data/status/focus may
   write, but no backend idempotency is invented.
3. Implement `management.mjs` minimally, then run its Node and browser slices
   serially to GREEN.

### Unit 3 — named deactivate/reactivate and real undo

1. Add REDs for preloaded child/duck impact, active-conversation disable/409,
   named dialog/cancel, exact state ACK, repeated action suppression, 10-second
   real undo, malformed ACK, and no DELETE.
2. Add hostile ignored-signal Node races: stop A then reload/navigate/lock;
   late A success and rejection cannot show toast/error or mutate B.
3. Implement the smallest state controller and cleanup needed for GREEN.

### Unit 4 — manual and automatic roster idempotency UI

1. Add REDs for native invalid date/days/cycle/cardinality zero requests,
   exact PUT/POST body/path/header UUIDs, one shared mutation lock, timeout
   retry UUID reuse, user-edit UUID invalidation, replay success, malformed
   acknowledgement, and retained values after failures.
   First freeze `GET /api/roster` backend response_model and frontend strict
   items: malformed/extra keys, inactive-child name retention, duplicate/missing
   child join, exact no-query request, and fixed whole-view error.
2. Use browser delayed routes to prove double click, Enter repeat, and
   cross-form action produce exactly one request.
3. Implement only the valid form/controller behavior, then run Node/browser
   slices to GREEN.

### Unit 5 — growth and bounded history reports

1. Add reports Node REDs for strict Growth/History DTOs, no direct globals,
   canonical injected navigation, A→B ignored-abort success/rejection, history
   paging late responses, cleanup listener removal, and safe DOM/SVG text.
2. Add browser REDs for `#growth?child_id`, `#search?child_id`, inactive-child
   selection, bounded pagination, review anchors, retry/empty/error states,
   selector/clear using canonical injected Hash navigation, back/forward,
   DirtyGuard confirmation when leaving Review, Search A→B ignored-abort late
   success/rejection, and both frozen viewports.
3. Implement reports minimally and rerun focused tests to GREEN.

### Unit 6 — composition and regression migration

1. First make static composition tests RED by requiring management/reports
   imports and rejecting the legacy import/file, stale POST roster route, flat
   detail fields, direct fetch, alert, and DELETE method tokens.
2. Compose the two route factories in `app.js`, delete `legacy-routes.mjs`, and
   update Router tests to verify all seven routes retain injected route signals.
3. Replace old routing browser assertions that expect Search/Delete failure
   with safe successful management/search navigation assertions.
4. Re-run static, Node, and browser focused suites to GREEN.

## Final verification and handoff

Run these commands serially; each pytest command has the incident-log pre/post
check stated above. Do not claim success from an earlier run.

```bash
pytest -q tests/test_conversation_history.py
pytest -q tests/test_deactivation.py tests/test_roster_idempotency.py tests/test_api.py
pytest -q tests/test_frontend_foundation.py tests/test_teacher_auth.py tests/test_review_atomicity.py
node --unhandled-rejections=strict --test tests/frontend/teacher/today.test.mjs tests/frontend/teacher/review.test.mjs tests/frontend/teacher/router.test.mjs tests/frontend/teacher/dirty-guard.test.mjs tests/frontend/teacher/management.test.mjs tests/frontend/teacher/reports.test.mjs
pytest -q tests/browser/test_teacher_management.py
pytest -q tests/browser/test_teacher_reports.py tests/browser/test_teacher_routing.py
pytest -q tests/browser/test_teacher_today.py
pytest -q tests/browser/test_teacher_review_loading.py
pytest -q tests/browser/test_teacher_review_editing.py
pytest -q tests/browser/test_teacher_lock.py
node --check app/frontend/teacher/app.js
node --check app/frontend/teacher/views/management.mjs
node --check app/frontend/teacher/views/reports.mjs
python -m py_compile tests/test_conversation_history.py tests/browser/test_teacher_management.py tests/browser/test_teacher_reports.py
```

Then run the exact policy/cleanliness checks:

```bash
rg -n "fetch\\(|\\.then\\(r\\s*=>\\s*r\\.json|alert\\(|method:\\s*['\\\"]DELETE" app/frontend/teacher.html app/frontend/teacher
rg -n "POST.*?/api/roster['\\\"]|/api/conversations['\\\"]" app/frontend/teacher
git diff --check
git status --short
```

The two `rg` commands must return no product-source matches. `git diff --check`
must be silent. Status must contain only Task 6 owned changes plus the four
pre-existing user-owned dirty paths.

After independent code review returns GO, stage only the owned paths above and
commit exactly:

```bash
git add app/backend/routes/conversations.py app/backend/routes/roster.py app/backend/services/history.py app/backend/schemas.py tests/test_conversation_history.py tests/test_roster_idempotency.py tests/test_teacher_auth.py
git add app/frontend/teacher/app.js app/frontend/teacher/views/management.mjs app/frontend/teacher/views/reports.mjs app/frontend/teacher/styles.css
git add -u app/frontend/teacher/legacy-routes.mjs
git add tests/test_frontend_foundation.py tests/frontend/teacher/router.test.mjs tests/frontend/teacher/management.test.mjs tests/frontend/teacher/reports.test.mjs
git add tests/browser/test_teacher_routing.py tests/browser/test_teacher_management.py tests/browser/test_teacher_reports.py
git add -f .superpowers/sdd/2026-08-23-teacher-workbench-and-acceptance/task-6-brief.md .superpowers/sdd/2026-08-23-teacher-workbench-and-acceptance/task-6-report.md
git commit -m "feat(teacher): restore safe management and history reports"
```

Do not stage unrelated dirty paths. A successful Task 6 does not waive the
recorded real-log incident or the inherited shared API-client test risk; final
release remains subject to Foundation Task 9's explicit NO-GO rules.
