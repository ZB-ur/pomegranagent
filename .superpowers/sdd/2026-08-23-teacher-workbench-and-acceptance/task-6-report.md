# Teacher Task 6 execution report

Date: 2026-08-29
Start HEAD: `05251b84adf85418e1179579dc49784e1374cc1b`

## Result

Task 6 replaces the unsafe legacy teacher routes with two injected modules:

- management: strict child/duck CRUD, reversible deactivate/reactivate with a
  real 10-second undo request, archive/summarize display through `textContent`,
  and idempotent manual/automatic rostering;
- reports: strict growth SVG rendering and bounded keyset history search whose
  rows link to the existing Review reader.

The backend adds authenticated `GET /api/conversations/history` before the
dynamic detail route, a strict history page DTO and page-wide integrity checks.
`GET /api/roster` now has a strict response model and accepts no query aliases.
The stale `legacy-routes.mjs` is deleted. Teacher frontend source contains no
DELETE request, direct fetch, alert, legacy roster POST, flat conversation
search, or HTML interpolation of service data.

## TDD evidence

- Unit 1 RED: `tests/test_conversation_history.py` failed collection with
  `ModuleNotFoundError: app.backend.services.history`; initial GREEN: 29 passed.
- Unit 2/5 Node RED: both new suites failed with `ERR_MODULE_NOT_FOUND` for
  `management.mjs` and `reports.mjs`; GREEN: 8 focused parser/factory tests.
- Browser RED: children could not locate the labeled `幼儿姓名` field; Growth
  could not locate `选择幼儿`. After implementation and an explicit `for/id`
  selector label, management is 6/6 and reports 4/4 across both viewports.
- Roster response RED: the exact route inventory had no
  `schemas.RosterListItem`; GREEN: strict response model and no-query contract.
- Regression RED: the pre-existing roster test still expected a cycle query;
  it was migrated to the frozen no-query contract. The teacher-auth exact route
  inventory correctly rejected the new history route. The brief was amended to
  grant that test-only ownership, independently re-reviewed Contract GO, and
  the inventory then passed.
- Test-fixture corrections were not counted as production failures: the first
  child stub intercepted only the query-bearing GET and therefore missed the
  POST; the reports label initially wrapped a select whose option text changed
  the accessible name. Both fixtures now assert the intended boundary.

### Independent review remediation

The first independent code review returned NO-GO with no P0 and seven P1
classes. Each finding was verified against repository behavior before a fix:

- History cursor RED: the frontend rejected the backend's declared cursor equal
  to the last returned ID. The parser and browser fixture now require that exact
  keyset cursor.
- Reader-parity RED: a Review-readable partial-score draft returned history
  `500`, while invalid message roles and invalid analysis attempt bounds returned
  `200`. History now performs one page-wide frozen-message read, validates
  `ConversationMessage` and `ConversationAnalysis`, and accepts the same partial
  score projection that the existing detail reader accepts. Focused history is
  now 32/32 with constant statement count.
- Reversible-state RED: a child deactivation 409 left the enriched row stale,
  and two sequential deactivations left two mutually corrupting undo toasts.
  Safe own-data error-code projection now triggers a list reload for
  `ACTIVE_CONVERSATION_EXISTS`; the route owns one explicit toast/timer record
  and removes the previous record before installing the next.
- Roster RED: duplicate child IDs were silently collapsed, child ACK active
  state was not matched, and automatic ACKs accepted short, out-of-range, or
  repeated-child schedules. Strict parsers now reject duplicate IDs; automatic
  ACKs require the exact weekday sequence and distinct active children. Browser
  coverage proves double-submit suppression, malformed-ACK failure, UUID reuse
  for unchanged retry, and UUID invalidation after input change.
- Reports RED: Growth and Search failures had no actionable retry. Both now
  render fixed, accessible retry buttons and restore status semantics after a
  successful retry.
- Hostile lifecycle coverage now uses a browser-injected request adapter whose
  promises deliberately ignore abort. Late Growth/Search success and rejection
  after A-to-B navigation cannot replace B; a late deactivation after navigation
  cannot add a toast, error, or stale route content.
- Review P2s were also closed: UUID generation is injected only by `app.js`,
  state/archive actions disable before request, native dialog cancel restores
  launcher focus, and child create/edit ACKs match expected active state.

The initial retry tests had two fixture-only failures: an empty Growth series
correctly omitted its legend, and a Search history item incorrectly reused the
enriched child object with extra keys. The fixtures were corrected to use a
real point and the strict four-key `ChildIdentity`; no product change was made
for those two failures.

## Fresh verification

Every pytest command was serial. Before and after every invocation the real
incident log remained exactly:

```text
SHA-256  5ee47c6b8322aee20aefecbf2344e8134cec18154fb7eb2d00c60116379fbeb7
size     2961585
mtime    1787939944
```

Final successful gates:

```text
tests/test_conversation_history.py                                      32 passed
tests/test_deactivation.py + test_roster_idempotency.py + test_api.py   48 passed
test_frontend_foundation.py + test_teacher_auth.py +
  test_review_atomicity.py                                               47 passed
teacher Today/Review/Router/Dirty/Management/Reports Node               47 passed
tests/browser/test_teacher_management.py                                 16 passed
tests/browser/test_teacher_reports.py                                    12 passed
tests/browser/test_teacher_routing.py                                    20 passed
tests/browser/test_teacher_today.py                                      70 passed
tests/browser/test_teacher_review_loading.py                             32 passed
tests/browser/test_teacher_review_editing.py                             50 passed
tests/browser/test_teacher_lock.py                                       20 passed
```

All three `node --check` commands, Python `py_compile`, both negated policy
scans, `git diff --check`, and the final incident-log check passed.

## Safety and residual release status

- No provider, external network, real database, real TTS cache, or real log was
  touched by Task 6.
- The four user-owned dirty paths remained unstaged and unmodified by this task.
- This task does not waive any previously recorded incident or Foundation Task
  9 release gate. Final release remains NO-GO until the frozen final acceptance
  process explicitly decides those items.
