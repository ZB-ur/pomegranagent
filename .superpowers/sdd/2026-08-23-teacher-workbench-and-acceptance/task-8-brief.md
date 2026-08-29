# Teacher Task 8 Brief — Failure injection and keyboard-only acceptance

> **For agentic workers:** REQUIRED SUB-SKILL: use
> `superpowers:subagent-driven-development` or `superpowers:executing-plans` to
> execute this brief unit by unit. Use `superpowers:systematic-debugging` before
> any product-code change caused by a RED result. Every execution step below is
> one 2–5 minute action.

## Decision and execution boundary

- This document is the authoritative current-repository brief for Teacher Task
  8. The stale Task 8 section in
  `docs/superpowers/plans/2026-08-23-teacher-workbench-and-acceptance.md`
  cannot be executed directly where it conflicts with this brief.
- Start implementation from the existing `master` checkout at exact HEAD
  `a46d475b8e6bcaa655b7d1827e3c7654e599cefb`. If `git rev-parse HEAD` differs,
  stop and repeat a read-only preflight; do not silently rebase this contract.
- Teacher Tasks 1–7 local repository work is complete. Do not replay or redesign
  it. The external Lovable checkpoint remains a separate user-authenticated
  visual-reference gate and is neither a prerequisite nor acceptance evidence
  for Task 8.
- Implementation is **NO-GO** until an independent reviewer reads this exact
  brief against the frozen HEAD and returns Contract GO with no P0/P1. A
  reviewer request for clarification is not GO.
- Task 8 adds missing browser characterization and keyboard acceptance evidence.
  It is not the final release gate. Task 9 must still evaluate all 14 mandatory
  gates and the historical incidents recorded below.
- Do not create a worktree, install a browser/package, call an AI/TTS provider,
  use an external service, start a real application server, or read/write a
  production account. Browser tests use only the existing loopback disposable
  server and deterministic route fixtures.
- Do not run any pytest command concurrently or overlap it with Node, browser,
  shell, or another pytest command. Do not use `pytest-xdist`, `-n`, background
  jobs, or parallel subagents for test execution.
- Do not run `tests/test_api.py` or `tests/e2e.py` in Task 8. They are outside
  the focused acceptance boundary and historically require explicit isolation.
- Every browser pytest command loads the normal repository conftests. Never add
  `--noconftest`: that would bypass the parent-log guard, disposable server,
  external-call breakers, resource snapshots, and context-egress policy.
- Use strict evidence-led TDD. A characterization test may be direct-GREEN
  against already delivered behavior; record it honestly. Never weaken a test
  or change product code merely to manufacture a RED/GREEN narrative.
- Preserve and never stage, revert, format, or modify these four user-owned
  dirty paths:
  - `.workbuddy/memory/2026-08-22.md`
  - `docs/superpowers/specs/2026-08-23-interaction-stabilization-design.md`
  - `.superpowers/brainstorm/`
  - `docs/superpowers/plans/`

## Owned allow-list

### Required Task 8 paths

- Create `tests/browser/test_teacher_failure_paths.py`.
- Create `tests/browser/test_teacher_accessibility.py`.
- Create and force-add
  `.superpowers/sdd/2026-08-23-teacher-workbench-and-acceptance/task-8-report.md`.
- Force-add this brief in the final Task 8 commit:
  `.superpowers/sdd/2026-08-23-teacher-workbench-and-acceptance/task-8-brief.md`.

### Conditional product paths, only after a focused product RED

- Modify `app/frontend/teacher/styles.css` only for a proven focus-visibility,
  hit-target, overflow, or reduced-motion defect.
- Modify `app/frontend/teacher/app.js` only for a proven PIN/unlock/lock keyboard
  or focus-lifecycle defect.
- Modify `app/frontend/teacher/router.mjs` only for a proven route-heading,
  active-navigation, or route-focus defect.
- Modify `app/frontend/teacher/dirty-guard.mjs` only after the focused dirty
  navigation-dialog seed is genuinely RED for accessible naming, initial
  focus, Escape/continue trigger restoration, discard focus transfer, or
  keyboard operation.
- Modify `app/frontend/teacher/views/today.mjs` only for a proven Today read or
  analysis-retry fault defect.
- Modify `app/frontend/teacher/views/review.mjs` only for a proven queue/detail,
  save, live-region, or keyboard-review defect.
- Modify `app/frontend/teacher/views/management.mjs` only for a proven
  deactivate/reactivate or roster mutation defect.
- Modify `app/frontend/teacher/views/reports.mjs` only for a proven authenticated
  route accessibility defect on `#growth` or `#search`.

No conditional file is edited merely because it is on this list. For each
edited product path, the Task 8 report must name the focused failing node, the
observed failure, the root cause, the minimal diff, and the focused GREEN.

### Explicitly excluded paths

- Do not modify `tests/browser/conftest.py` or
  `tests/browser/child_server.py`; reuse the existing `teacher_browser` safety
  substrate unchanged.
- Do not modify any existing `tests/browser/test_teacher_*.py` file. Missing
  acceptance rows belong in the two new Task 8 files; existing behavior remains
  independently regression-testable.
- Do not modify `tests/frontend/teacher/**`, `tests/conftest.py`, backend code,
  schemas, dependencies, `app/frontend/teacher.html`,
  Child files, prior briefs/reports, runtime data, `data/**`, `logs/**`, or the
  real TTS cache.
- If a valid RED requires an excluded path, stop with Contract Conflict. Do not
  widen ownership during implementation.

## Frozen safety substrate and resource gate

Reuse these committed protections without alteration:

- `tests/browser/conftest.py::browser_parent_logging_guard` removes any parent
  `FileHandler` targeting the real log, installs a disposable handler, and
  compares real log bytes at teardown.
- `tests/browser/conftest.py::child_server` launches only `127.0.0.1` with a
  disposable app-mode SQLite database, log directory, TTS cache, non-starting
  worker, provider/network/context tripwires, and teardown snapshots.
- `tests/browser/conftest.py::teacher_browser` creates fresh contexts with
  service workers blocked and exact-origin fail-closed routing.
- `tests/browser/child_server.py::capture_resource_snapshots` uses a read-only
  SQLite URI plus deterministic `iterdump()` for the application database, an
  exact file digest for the real log, and a path/content digest for TTS cache.
- `tests/conftest.py::disable_external_ai` is the lowest-level parent-process
  `_llm` breaker. The child server independently installs its own lowest-level
  AI/TTS/socket tripwires.

The frozen pre-Task-8 real-resource baseline is exactly:

```text
application DB logical digest  c31f80875458d37e7b9badf086a5ff904a73d1d7f2ef1f5ab716c1f2c9755af3
real log SHA-256               5ee47c6b8322aee20aefecbf2344e8134cec18154fb7eb2d00c60116379fbeb7
real log size                  2961585
real log mtime epoch           1787939944
real TTS cache digest          138263700e062272f93b941cebdb36340d3840c03366e638c9f10e3db684030d
```

Before and after every pytest invocation, execute this read-only command and
compare the complete line byte-for-byte:

```bash
PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -c 'from tests.browser import child_server as c; s=c.capture_resource_snapshots(c.REAL_DATABASE_PATH,c.REAL_LOG_PATH,c.REAL_TTS_CACHE_PATH); t=c.REAL_LOG_PATH.stat(); print(f"{s.database}|{s.log}|{t.st_size}|{int(t.st_mtime)}|{s.tts_cache}")'
```

Expected line:

```text
c31f80875458d37e7b9badf086a5ff904a73d1d7f2ef1f5ab716c1f2c9755af3|5ee47c6b8322aee20aefecbf2344e8134cec18154fb7eb2d00c60116379fbeb7|2961585|1787939944|138263700e062272f93b941cebdb36340d3840c03366e638c9f10e3db684030d
```

Every pytest command must have `DISABLE_EXTERNAL_AI=1` in its environment.
Stop immediately on a baseline mismatch, any before/after difference, any
tripwire assertion, unexpected non-loopback request, or real-resource change.
Do not clean, rotate, restore, truncate, or rewrite a resource to make a gate
pass. A test failure and a safety-gate failure are different: the former enters
debugging; the latter ends Task 8 execution and is reported as NO-GO.

## Existing coverage ledger: do not duplicate

The new files add only protocol rows or end-to-end acceptance not already
proved below.

| Delivered evidence | Existing test | Task 8 ruling |
| --- | --- | --- |
| Today roster and all three queue panels: loading, empty, JSON 500, 200 non-JSON, malformed JSON, scoped retry, sibling preservation | `tests/browser/test_teacher_today.py::test_teacher_today_shows_all_panel_loading_states_before_any_response`, `::test_teacher_today_panel_failures_are_safe_and_retry_only_that_panel` | Do not expand every equivalent panel/fault combination. Use Today roster as the sole Today representative for exact HTML 502 and `internetdisconnected`. |
| Review pending queue and detail: JSON 500, 200 non-JSON, malformed JSON, generic offline, persistent retry | `tests/browser/test_teacher_review_loading.py::test_teacher_review_queue_failures_are_scoped_and_the_retry_does_not_reload_detail`, `::test_teacher_review_detail_failures_keep_the_queue_and_persistent_reload_recovers` | Use pending queue as one strict queue-validator representative. Do not add equivalent processing/failed/detail rows. |
| Held read, route/lock cancellation, and late-response ownership | `tests/browser/test_teacher_review_loading.py::test_teacher_review_navigation_aborts_held_detail_and_only_fast_hash_b_renders`, `::test_teacher_review_lock_aborts_both_held_reads_and_reunlock_starts_one_fresh_reader`; routing held-route tests | Do not add a second generic race suite. |
| Review save: 422, 409, 401, 404, JSON 500, HTML 502, generic offline, hostile acknowledgements, exact typed-value preservation, dirty state, unlocked actions | `tests/browser/test_teacher_review_editing.py::test_teacher_review_save_failures_keep_exact_values_dirty_and_never_refresh` | Do not add another generic offline/status/ACK row. Add only the previously unproved 15,001ms PUT timeout boundary plus connected live-status/focus continuity on success. |
| Review save delay: one PUT, all editor controls disabled, no early success, controlled success | `tests/browser/test_teacher_review_editing.py::test_teacher_review_delayed_save_is_single_flight_and_disables_every_editor_control` | Do not duplicate. |
| Analysis retry: single flight, ordered queue refresh, malformed/status/non-JSON/generic-offline failures, fixed copy, unlock, navigation cancellation | `tests/browser/test_teacher_today.py::test_teacher_today_analysis_retry_is_single_flight_and_refreshes_three_queues_in_order`, `::test_teacher_today_analysis_retry_failures_restore_only_the_row_action_with_safe_copy`, `::test_teacher_today_held_retry_cannot_mutate_after_navigation` | Do not add HTML/offline variants; their user-visible invariant is already covered. |
| Child deactivate/reactivate happy path, undo, 409 reload, latest toast, and held navigation race | `tests/browser/test_teacher_management.py::test_child_deactivation_uses_named_dialog_and_real_undo`, `::test_child_deactivation_409_reloads_enriched_list`, `::test_only_latest_deactivation_undo_toast_remains_live`, `::test_late_deactivation_after_navigation_cannot_write_to_new_route` | Add settled transport faults and delayed repeated-action coverage for both child and duck endpoints. |
| Manual roster exact PUT/body/header happy path; auto roster single-flight, retained/new UUID rules, and strict ACK rejection | `tests/browser/test_teacher_management.py::test_duck_archive_summary_is_text_and_roster_uses_frozen_idempotent_routes`, `::test_auto_roster_lock_retry_uuid_and_exact_ack` | Add the missing settled transport-fault matrix for both forms and a held-request assertion for each. |
| Route Hash, active item, heading focus, rapid selection, A-to-B stale response protection | `tests/browser/test_teacher_routing.py`, `tests/browser/test_teacher_reports.py`, and review loading tests | Do not add a generic rapid-selection test. Task 8 keyboard evidence may traverse these routes but must not duplicate their race matrices. |
| Dirty reload/hash dialogs exist and preserve/discard data | `tests/browser/test_teacher_review_editing.py::test_teacher_review_dirty_detail_reload_requires_one_native_discard_dialog`, `::test_teacher_review_dirty_hash_navigation_continue_restores_review_and_discard_changes_route`; `tests/frontend/teacher/dirty-guard.test.mjs` | Add only the missing real-browser accessible dialog name and pure-keyboard focus lifecycle at both viewports. |

If a proposed test can be removed without losing one of the explicitly missing
rows above or the complete keyboard/a11y acceptance below, remove it before the
first run.

## Frozen endpoint surface

Task 8 route interception is restricted to the exact loopback origin provided
by `teacher_browser.server.base_url`. Every handler first asserts
`tests.browser.conftest.is_exact_fixture_url(request.url, server.port)`.

### Read surfaces

```text
GET /api/roster/today
GET /api/conversations?queue=pending
GET /api/conversations?queue=processing
GET /api/conversations?queue=failed
GET /api/conversations/{positive-conversation-id}
```

### Mutation surfaces

```text
PUT  /api/conversations/{positive-conversation-id}/review
POST /api/conversations/{positive-conversation-id}/analysis/retry
POST /api/children/{positive-child-id}/deactivate
POST /api/children/{positive-child-id}/reactivate
POST /api/ducks/{positive-duck-id}/deactivate
POST /api/ducks/{positive-duck-id}/reactivate
PUT  /api/roster/{YYYY-MM-DD}
POST /api/roster/auto
```

No wildcard route may accidentally intercept runtime/auth/static requests or a
different business endpoint. Record method, parsed path/query, body, and
`x-request-id` for mutations before fulfilling or aborting a route.

## Frozen fault semantics

### Settled failures

The settled transport matrix uses exactly these fixtures:

```text
json-500  -> route.fulfill(status=500, content_type="application/json",
                           body='{"error":{"code":"INTERNAL_ERROR","message":"raw-task8-secret","field_errors":{},"retryable":true}}')
html-502  -> route.fulfill(status=502, content_type="text/html",
                           body='<h1>raw-task8-secret</h1>')
offline   -> route.abort("internetdisconnected")
```

A settled failure must reach a terminal local failure state. It must show only
fixed local copy; `raw-task8-secret`, response HTML, exception text, and service
details never enter DOM, attributes, dialogs, logs asserted by the page, or
accessible names. It must not render success copy, refresh success-only data,
clear review/roster input, change active state, create an undo toast, or strand
an action disabled. The original state or roster action becomes enabled again,
receives keyboard focus, and shows a visible outline; a newly created substitute
button does not satisfy focus restoration.

For review save, preserve the exact untrimmed typed reason/value and dirty state.
For manual and automatic roster, preserve every visible field and selection.
An unchanged roster retry must resend the exact same body bytes, body
`request_id`, and `x-request-id`; any user input/change creates a new snapshot
and new UUID under the already delivered Task 6 contract.

### Delay is pending, not a failure

`delay` is never a member of the settled-fault parameter list. A delay handler
stores the Playwright `Route` without calling `fulfill`, `abort`, or `continue_`.
While held:

- the request count is exactly one after double activation and an additional
  keyboard Enter/Space activation;
- the owning control, or all controls in the owning mutation form, is disabled;
- no success or failure copy appears;
- typed/selected values and the exact request body/UUID remain unchanged; and
- no success-only reload, active-state change, or undo toast occurs.

After those pending assertions, settle the single stored route once with a
strict valid acknowledgement, wait for the existing fixed success projection,
and assert exactly one success-only reload. This controlled settlement prevents
teardown from confusing a pending route with a fault and proves single flight.

Read delays are already covered by delivered loading/abort tests. Review-save
and analysis-retry delays are already covered by delivered single-flight tests.
Task 8 adds delayed tests only for deactivate/reactivate and the two roster
mutations.

### Review PUT timeout is its own boundary

The only new Review failure node holds one exact
`PUT /api/conversations/42/review`, installs the Playwright virtual clock before
page load, and advances it by exactly `15_001` ms after the PUT is observed.
The existing request contract sets `timeoutMs: 15000`; the terminal rejected
error must therefore have `code === "REQUEST_TIMEOUT"`, captured by a
transparent test-only `window.DuckAPI` wrapper that calls the original frozen
request function unchanged, records only the rejected own data fields, and
rethrows the identical error object.

The timeout terminal state shows fixed `保存失败，请稍后重试。`, preserves the
exact typed value and dirty guard, re-enables all editor controls, restores
focus to the original `保存草稿` action with a visible outline, emits no success
copy, and performs zero success-only queue refreshes. A `finally` block aborts
any still-actionable stored Playwright route, unregisters the exact route
handler, and clears the local pending-route collection even when an assertion
fails. Generic offline and HTTP Review-save rows remain solely in the delivered
Task 5 matrix.

### Review save live-status and focus continuity

Before activating `保存草稿`, capture the already connected, initially empty
`.review-save-status[role="status"][aria-live="polite"]` DOM node by identity
and attach a `MutationObserver` to that same node. Record each consecutive
nonblank text value and `node.isConnected` inside the observer callback. One
strict successful PUT must produce exactly this ordered sequence:

```text
正在保存…
全部修改已保存
```

The captured node must remain the same object and stay connected for both
records and after settlement; replacing the editor with a new status element
does not satisfy the contract. After `save_draft` success, keyboard focus is
restored to the visible `保存草稿` action for the refreshed revision and its
outline is visible. The observer is disconnected in `finally`.

## Frozen page-focus keyboard flow

The stale phrase “starting at the address bar” is not executable through a
Playwright page: browser chrome is outside page DOM and `page.keyboard` targets
page focus. The acceptance flow therefore starts after
`page.goto(.../teacher.html)` at the page-owned initial focus, which must be the
labeled PIN input.

After navigation, route setup and deterministic route interception, the test
must not call locator `.click()`, `.fill()`, `.check()`, `.select_option()`,
JavaScript `.focus()`, or dispatch synthetic click/submit events. Locators may
wait and assert only. All user actions use `page.keyboard`:

1. Assert `#teacher-pin` is the active element; type the synthetic PIN with
   `page.keyboard.type`, press `Tab`, and press `Enter` to unlock.
2. Assert the Today `h1` receives route focus and its focus indicator is visible.
   From that heading, use `Shift+Tab` through the page-owned focus order until
   the navigation **button** named `值日审阅` is active; press `Enter`.
3. Assert the Review `h1` receives visible route focus and exactly the Review
   navigation button has `aria-current="page"`.
4. Use `Tab` until the queue item named `审阅雨雨的会话 #42` is active; press
   `Enter`, wait for the selected detail, and assert the re-rendered Review `h1`
   again receives visible focus.
5. Use `Tab` until the textarea labeled `表达能力评分理由` is active. Select its
   content with `ControlOrMeta+A`, type `键盘保留理由`, and assert that exact
   value without programmatic refocus.
6. Use `Shift+Tab` or `Tab` until the currently checked `表达能力` radio is
   active; press one `ArrowRight`. Assert the checked score increases by one and
   the reason remains exactly `键盘保留理由`.
7. Use `Tab` until the button named `保存草稿` is active; press `Enter`. The route
   fixture accepts exactly one strict PUT acknowledgement. Assert the captured
   connected polite `aria-live` node announces `正在保存…` then
   `全部修改已保存`, remains the same connected node, and focus returns to the
   visible refreshed `保存草稿` action. No mouse/programmatic activation occurs.
8. Continue with keyboard Tab order until the button named `立即锁定` is active;
   press `Space`. Assert the authenticated `h1` is gone, the locked `h2` is
   visible, protected navigation buttons are disabled, and no PIN or typed
   review value appears in page text, URL, storage, or serialized DOM.

A bounded helper may press `Tab` or `Shift+Tab` until an exact accessible
name/element type is reached, but it must fail after at most 80 presses, record
the encountered focus sequence, never call `focus()`, and verify every
encountered interactive element has a non-`none` outline with positive width.
This keeps the test keyboard-only while avoiding a brittle hard-coded Tab count.

### Dirty navigation-dialog keyboard flow

At both teacher viewports, the dedicated dirty-dialog test starts on a loaded
Review draft, reaches and edits a review field by keyboard, and reaches a target
navigation button by keyboard. It performs no locator click/fill, JavaScript
focus, hash assignment, or synthetic event after page-owned initial focus.

On the first navigation activation:

- `get_by_role("dialog", name="有未保存的修改", exact=True)` resolves exactly
  one modal; the heading text alone is not accepted as an implicit name;
- initial focus is the `继续编辑` button and its outline is visible; and
- pressing `Escape` cancels navigation, preserves the exact dirty value and
  Review hash, removes the dialog, restores focus to the navigation button that
  triggered it, and preserves that trigger's visible outline.

Press the restored trigger again to reopen the dialog. Initial focus is again
`继续编辑`; one `Tab` reaches `放弃修改`, and `Space` activates discard. The
dialog closes, the dirty Review form is removed, the requested route/hash wins,
and focus lands on the target route `h1` with a visible outline. This test is
named exactly
`test_teacher_dirty_review_dialog_is_named_keyboard_operable_and_restores_focus`.

## Frozen accessibility scope

The authenticated route matrix is exact:

| Fragment | Navigation button | Required visible `h1` |
| --- | --- | --- |
| `#today` | `今日任务` | `今日任务` |
| `#children` | `幼儿管理` | `幼儿管理` |
| `#ducks` | `小鸭管理` | `小鸭管理` |
| `#roster` | `值日排班` | `值日排班` |
| `#review` | `值日审阅` | `值日审阅` |
| `#growth` | `能力成长曲线` | `能力成长曲线` |
| `#search` | `明细检索` | `明细检索` |

For each authenticated route at both `1024x768` and `1440x900`, assert:

- the document contains exactly one `main#main`, and `main#main` contains
  exactly one visible `h1` matching the table;
- all visible enabled `input`, `select`, and `textarea` elements have a nonblank
  computed accessible name, and every visible enabled button/link has a
  nonblank accessible name;
- no interactive element contains another interactive element;
- no element has a positive `tabindex`; the route heading may use `-1`;
- exactly one `#nav button` has `aria-current="page"`, it matches the fragment,
  and no other navigation button has `aria-current`;
- every visible enabled button and application action link except the offscreen
  skip link has a bounding box at least 44 CSS pixels wide and high;
- `document.documentElement.scrollWidth <= clientWidth`; and
- keyboard-focused route headings and interactive controls have a visible
  outline. Reduced-motion CSS remains present and is not weakened.

The initial PIN form and post-lock state intentionally use a visible `h2`, not
an `h1`. They are outside the authenticated one-visible-`h1` invariant. For
those states assert one `main#main`, one visible descriptive `h2`, a labeled PIN
input when input is expected, no protected route `h1`, disabled navigation, no
positive `tabindex`, and no unlabeled visible form control.

Navigation is implemented by `<button data-v>` elements in
`app/frontend/teacher.html`; it is not a link set. Assertions and report copy
must say “navigation button” or “navigation item”, never require a nav anchor.

## P0/P1 conflict register

| Severity | Conflict in the stale plan/current state | Frozen resolution |
| --- | --- | --- |
| P0 | No current Task 8 brief or independent contract verdict existed after Task 7 | This brief must receive independent Contract GO before any implementation edit. |
| P0 | Three historical safety incidents make broad or parallel test execution unsafe | Serial commands, normal conftests, lowest-level breakers, exact resource snapshots, and immediate stop-on-drift are mandatory. |
| P1 | The stale fault matrix repeats large delivered queue/detail/save/retry/race suites | The coverage ledger limits Task 8 to exact missing transport rows, state/roster mutation faults, keyboard flow, and static a11y. |
| P1 | The stale matrix treats `delay` like a terminal fault | Delay is a held pending state with assertions before one controlled settlement; settled failures are JSON 500, HTML 502, and `internetdisconnected`. |
| P1 | “Starting at the address bar” cannot be driven by Playwright page keyboard | Start at the page-owned focused PIN input after `page.goto`; all later actions stay keyboard-only. |
| P1 | The stale static check says exactly one nav link | Current navigation uses buttons; require exactly one matching navigation button with `aria-current="page"`. |
| P1 | “One visible h1” is ambiguous for PIN/locked states | Apply it to seven authenticated routes only; PIN/locked states intentionally use one descriptive `h2`. |
| P1 | The stale commit command stages the entire teacher directory | Stage only exact owned files; conditional product paths appear only when changed for a documented product RED. |
| P1 | Passing Task 8 could be misreported as final release GO | Task 8 may earn a bounded functional/code GO only. Final release remains Task 9 and must resolve all mandatory gates and incident disposition. |

Any new P0/P1 found during contract review is resolved in this brief and
re-reviewed before implementation. Any new P0/P1 found during code review is
fixed through a focused test cycle and re-reviewed before commit.

## TDD unit 0 — Contract and start-state gate

- [ ] **Step 0.1 (2–5 min): Verify the frozen start state.** Run
  `git rev-parse HEAD`, `git status --short`, and
  `git diff --check`. Require exact HEAD
  `a46d475b8e6bcaa655b7d1827e3c7654e599cefb`, the four preserved dirty paths
  only as inherited dirt, and no Task 8 product/test edit.
- [ ] **Step 0.2 (2–5 min): Verify the real-resource baseline.** Run the
  read-only snapshot command in this brief once and compare the whole line to
  the frozen expected line.
- [ ] **Step 0.3 (2–5 min): Request independent contract review.** Give the
  reviewer this brief, exact HEAD, the stale Task 8 plan section, the two new
  test filenames, existing coverage ledger, and three incident reports. Ask for
  an explicit P0/P1/P2 list and GO/NO-GO.
- [ ] **Step 0.4 (2–5 min): Apply review corrections only to this brief.** For
  every P0/P1, make the narrow contract correction, preserve the owned
  allow-list, and request a fresh independent verdict. Do not edit tests or
  product code.
- [ ] **Step 0.5 (2–5 min): Record Contract GO.** Start implementation only
  after a fresh verdict says Contract GO with no P0/P1. Record reviewer identity
  or agent task name, verdict, and remaining P2 advice for the Task 8 report.

## Mandatory seed-first TDD order

Every parameterized Task 8 node starts with one `pytest.param` seed containing
all axes in one case object and the exact seed ID named below. Run that seed
before appending a second case. If it exposes a test/fixture error, correct only
the owning new test and rerun it. If it is a genuine product RED, diagnose it
immediately, make the smallest conditional-owned fix, and rerun the seed GREEN
before expanding any kind, action, fault, route, or viewport. After each
expansion slice, stop on its first RED and complete the same focused cycle
before adding another slice. There is no deferred batch-repair unit.

## TDD unit 1 — Representative reads and the Review PUT timeout

Create these exact tests in `tests/browser/test_teacher_failure_paths.py`:

```text
test_teacher_representative_read_validators_cover_missing_transport_faults
test_teacher_review_put_timeout_preserves_dirty_values_and_restores_focus
```

The read matrix is only Today roster and pending Review queue by
`html-502|offline` by two viewports: eight cases. Do not add equivalent Today
pending/processing/failed, Review detail, Review-save offline, or analysis-retry
rows.

- [ ] **Step 1.1 (2–5 min): Create exact-origin builders.** Add synthetic
  Today/queue/detail/strict-ACK data, explicit case objects, raw-secret checks,
  and route records. Reuse `teacher_browser` and `is_exact_fixture_url`.
- [ ] **Step 1.2 (2–5 min): Write and run the sole read seed.** Add only
  `seed_today_roster_html_502_1024`, then run through the resource gate:

  ```bash
  DISABLE_EXTERNAL_AI=1 ./.venv/bin/python -m pytest -q 'tests/browser/test_teacher_failure_paths.py::test_teacher_representative_read_validators_cover_missing_transport_faults[seed_today_roster_html_502_1024]'
  ```

- [ ] **Step 1.3 (2–5 min): Resolve the read seed before expansion.** Require
  fixed error, no raw/success projection, scoped retry, and controlled retry
  success. Correct a harness error or minimally fix `today.mjs`, then rerun the
  seed GREEN; if direct-GREEN, edit no product path.
- [ ] **Step 1.4 (2–5 min): Expand reads one slice at a time.** Add Today offline
  and pending-queue HTML/offline at 1024 and run; only after GREEN add their four
  1440 mirrors and run. Resolve each slice's first RED before continuing.
- [ ] **Step 1.5 (2–5 min): Write the sole timeout seed.** Add only
  `seed_review_timeout_1024`; install virtual time before page load, wrap
  DuckAPI transparently to record/rethrow the identical rejection, hold one
  Review PUT, type an exact dirty value, and advance `15_001` ms.
- [ ] **Step 1.6 (2–5 min): Run the timeout seed through the resource gate.** Run:

  ```bash
  DISABLE_EXTERNAL_AI=1 ./.venv/bin/python -m pytest -q 'tests/browser/test_teacher_failure_paths.py::test_teacher_review_put_timeout_preserves_dirty_values_and_restores_focus[seed_review_timeout_1024]'
  ```

- [ ] **Step 1.7 (2–5 min): Resolve timeout RED before expansion.** Require
  captured `REQUEST_TIMEOUT`, fixed terminal copy, exact value/dirty
  preservation, unlocked controls, focused outlined Save Draft, no success or
  queue refresh, and `finally` route/unroute cleanup. Diagnose/fix/re-run this
  seed GREEN before appending another viewport.
- [ ] **Step 1.8 (2–5 min): Add the 1440 timeout case.** Append
  `review_timeout_1440`, rerun the complete timeout node, and record counts and
  pending-route cleanup.

## TDD unit 2 — Deactivate/reactivate settled and delayed faults

Add these exact tests to `tests/browser/test_teacher_failure_paths.py`:

```text
test_teacher_resource_state_settled_faults_never_claim_success
test_teacher_resource_state_delay_is_single_flight
```

Parameterize `kind` as `child|duck`, `action` as
`deactivate|reactivate`, and viewport at both frozen sizes. Settled faults use
exactly `json-500|html-502|offline`. A deactivate begins from an active strict
enriched row and the named modal; a reactivate begins from an inactive row and
its visible restore action. Use exact child/duck endpoint paths and strict
synthetic rows for each kind.

- [ ] **Step 2.1 (2–5 min): Write and run one settled seed.** Add only
  `seed_child_deactivate_json_500_1024`; assert one POST, unchanged state, fixed
  copy, no raw/toast/reload, and the exact launcher re-enabled, focused, and
  outlined. Run:

  ```bash
  DISABLE_EXTERNAL_AI=1 ./.venv/bin/python -m pytest -q 'tests/browser/test_teacher_failure_paths.py::test_teacher_resource_state_settled_faults_never_claim_success[seed_child_deactivate_json_500_1024]'
  ```

- [ ] **Step 2.2 (2–5 min): Resolve the settled seed before expansion.** Correct
  a harness error or minimally fix `management.mjs`, rerun the exact seed GREEN,
  and only then append another case.
- [ ] **Step 2.3 (2–5 min): Expand action then kind at 1024.** Add child
  reactivate and run; add duck deactivate/reactivate and run. Resolve the first
  RED before the next slice.
- [ ] **Step 2.4 (2–5 min): Expand faults then viewport.** Add HTML 502/offline
  for all four pairs at 1024 and run; only after GREEN add the 1440 mirrors and
  run.
- [ ] **Step 2.5 (2–5 min): Write and run one delay seed.** Add only
  `seed_child_deactivate_1024`; hold one route, repeat activation, assert one
  POST/disabled owner/no projection, then settle one strict ACK. Run:

  ```bash
  DISABLE_EXTERNAL_AI=1 ./.venv/bin/python -m pytest -q 'tests/browser/test_teacher_failure_paths.py::test_teacher_resource_state_delay_is_single_flight[seed_child_deactivate_1024]'
  ```

- [ ] **Step 2.6 (2–5 min): Resolve delay RED before expansion.** Correct or
  minimally fix, rerun the seed GREEN, and require `finally` cleanup of any held
  route.
- [ ] **Step 2.7 (2–5 min): Expand delay serially.** Add reactivate, then duck,
  then 1440 slices, running cumulatively and resolving each first RED before
  continuing.

## TDD unit 3 — Manual and automatic roster fault/idempotency acceptance

Add these exact tests to `tests/browser/test_teacher_failure_paths.py`:

```text
test_teacher_roster_settled_faults_preserve_snapshot_and_request_id
test_teacher_roster_delay_is_single_flight
```

Parameterize `kind` as `daily|auto`, settled fault as
`json-500|html-502|offline`, and both teacher viewports. Daily uses exact
`PUT /api/roster/2026-08-29`; auto uses exact
`POST /api/roster/auto`.

- [ ] **Step 3.1 (2–5 min): Write and run one settled roster seed.** Add only
  `seed_daily_json_500_1024`; capture exact request bytes, settle the failure,
  preserve values/selections, and require `保存当日排班` re-enabled, focused, and
  outlined with no success/reload. Run:

  ```bash
  DISABLE_EXTERNAL_AI=1 ./.venv/bin/python -m pytest -q 'tests/browser/test_teacher_failure_paths.py::test_teacher_roster_settled_faults_preserve_snapshot_and_request_id[seed_daily_json_500_1024]'
  ```

- [ ] **Step 3.2 (2–5 min): Resolve the roster seed before expansion.** Correct
  a harness error or minimally fix `management.mjs`, then rerun this seed GREEN.
- [ ] **Step 3.3 (2–5 min): Prove unchanged seed retry identity.** Retry with a
  strict ACK and require byte-identical body plus equal body/header UUID before
  the first success reload.
- [ ] **Step 3.4 (2–5 min): Expand kind, faults, then viewport.** Add auto JSON
  500 at 1024 and run; add HTML 502/offline at 1024 and run; only after GREEN add
  the six 1440 mirrors and run. Resolve each slice's first RED immediately.
- [ ] **Step 3.5 (2–5 min): Write and run one roster-delay seed.** Add only
  `seed_daily_1024`; hold one PUT, repeat/cross-form submit, assert one mutation
  and both forms disabled with immutable body/UUID, then settle one strict ACK.
  Run:

  ```bash
  DISABLE_EXTERNAL_AI=1 ./.venv/bin/python -m pytest -q 'tests/browser/test_teacher_failure_paths.py::test_teacher_roster_delay_is_single_flight[seed_daily_1024]'
  ```

- [ ] **Step 3.6 (2–5 min): Resolve delay RED before expansion.** Correct or
  minimally fix, rerun the seed GREEN, and require no held route in `finally`.
- [ ] **Step 3.7 (2–5 min): Expand delay serially.** Add auto at 1024 and run;
  then add both 1440 cases and run, resolving the first RED before continuing.

## TDD unit 4 — Complete page-keyboard and dirty-dialog workflows

Create these exact tests in `tests/browser/test_teacher_accessibility.py`:

```text
test_teacher_complete_review_flow_is_page_keyboard_only
test_teacher_dirty_review_dialog_is_named_keyboard_operable_and_restores_focus
```

- [ ] **Step 4.1 (2–5 min): Create deterministic keyboard-flow fixtures.** Add
  only the two viewports, strict pending queue/detail/review ACK data, exact
  route handlers, a bounded keyboard Tab walker, active-element description,
  and visible-outline assertion. Reuse `teacher_browser` unchanged.
- [ ] **Step 4.2 (2–5 min): Write only the 1024 keyboard seed.** Add parameter
  ID `seed_keyboard_review_1024`. Assert initial PIN focus; type/Tab/Enter to
  unlock; traverse by keyboard to Review and the queue item; edit the exact
  reason; ArrowRight the rating; save through the same connected live node;
  then Tab/Space to lock. Do not add the 1440 case yet.
- [ ] **Step 4.3 (2–5 min): Run the keyboard seed through the resource gate.**
  Run serially:

  ```bash
  DISABLE_EXTERNAL_AI=1 ./.venv/bin/python -m pytest -q 'tests/browser/test_teacher_accessibility.py::test_teacher_complete_review_flow_is_page_keyboard_only[seed_keyboard_review_1024]'
  ```

  Current CSS does not declare a route-heading focus outline, so a genuine RED
  at a focused `h1` is plausible. Do not assume it: inspect computed style and
  focus sequence. Invoke the inline Unit 6 loop immediately for a product RED.
- [ ] **Step 4.4 (2–5 min): Expand the keyboard workflow to 1440.** Only after
  the seed is GREEN, add `keyboard_review_1440`, run the complete node, and
  resolve its first RED before proceeding.
- [ ] **Step 4.5 (2–5 min): Write only the 1024 dirty-dialog seed.** Add parameter
  ID `seed_dirty_dialog_1024`. Use pure keyboard input/navigation to make the
  Review form dirty, open the named modal, prove initial focus, Escape focus
  return, reopen, Tab/Space discard, target hash, and target route-heading
  focus. Do not add the second viewport yet.
- [ ] **Step 4.6 (2–5 min): Run the dirty-dialog seed through the resource
  gate.** Run serially:

  ```bash
  DISABLE_EXTERNAL_AI=1 ./.venv/bin/python -m pytest -q 'tests/browser/test_teacher_accessibility.py::test_teacher_dirty_review_dialog_is_named_keyboard_operable_and_restores_focus[seed_dirty_dialog_1024]'
  ```

  Invoke the inline Unit 6 loop immediately for any genuine product RED; map a
  dialog naming/focus root cause to the conditional `dirty-guard.mjs` path.
- [ ] **Step 4.7 (2–5 min): Expand the dirty-dialog workflow to 1440.** Only
  after the seed is GREEN, add `dirty_dialog_1440`, run the complete node, and
  resolve its first RED before Unit 5.

## TDD unit 5 — Static authenticated-route and locked-state accessibility

Add these exact tests to `tests/browser/test_teacher_accessibility.py`:

```text
test_teacher_authenticated_routes_have_frozen_accessibility_structure
test_teacher_pin_and_locked_states_use_the_separate_h2_contract
```

- [ ] **Step 5.1 (2–5 min): Write and run only the Today/1024 structure seed.**
  Add parameter ID `seed_a11y_today_1024`, install only Today synthetic reads,
  and assert the full authenticated structural contract. Run serially:

  ```bash
  DISABLE_EXTERNAL_AI=1 ./.venv/bin/python -m pytest -q 'tests/browser/test_teacher_accessibility.py::test_teacher_authenticated_routes_have_frozen_accessibility_structure[seed_a11y_today_1024]'
  ```

  Resolve the first RED through the inline Unit 6 loop before adding a route.
- [ ] **Step 5.2 (2–5 min): Expand authenticated routes at 1024.** Add one route
  at a time in the frozen table, run cumulatively, and resolve the first RED
  before the next route. Only after all seven are GREEN add their seven 1440
  mirrors and run the complete node.
- [ ] **Step 5.3 (2–5 min): Write and run only the initial-PIN/1024 seed.** Add
  parameter ID `seed_pin_initial_1024`; prove the separate h2/PIN contract and
  run serially:

  ```bash
  DISABLE_EXTERNAL_AI=1 ./.venv/bin/python -m pytest -q 'tests/browser/test_teacher_accessibility.py::test_teacher_pin_and_locked_states_use_the_separate_h2_contract[seed_pin_initial_1024]'
  ```

  Resolve the first RED immediately; an h2 result is expected and valid.
- [ ] **Step 5.4 (2–5 min): Expand locked state then viewport.** Add the
  keyboard-locked 1024 state and run; only after GREEN add both 1440 mirrors and
  run the complete node. Never force an h1 into PIN/locked states.

## TDD unit 6 — Minimal evidence-driven product repair

This is an inline repair loop, not a batch that runs after Units 1–5. Invoke
Steps 6.1–6.5 immediately when any seed or expansion slice in Units 1–5 is RED;
do not write the next case first. This unit is skipped only when every prior
seed and slice is direct-GREEN. Skipping it is recorded; it is not a missing
implementation step.

- [ ] **Step 6.1 (2–5 min): Classify one failing assertion.** Re-run only that
  parameter/node through the resource gate, inspect request count, active
  element, computed style, and DOM state, and decide whether the cause is the
  test, fixture, or product. Do not edit product code while classification is
  uncertain.
- [ ] **Step 6.2 (2–5 min): Correct a test/fixture error in the owning new test
  file.** Re-run the exact node, record the correction, and do not call this a
  product RED.
- [ ] **Step 6.3 (2–5 min): For a proven product RED, select one owning product
  path.** Map focus style to `styles.css`, PIN lifecycle to `app.js`, route focus
  to `router.mjs`, Today/retry to `today.mjs`, Review/save/live status to
  `review.mjs`, dirty-dialog naming/focus to `dirty-guard.mjs`, resource/roster
  to `management.mjs`, or report structure to `reports.mjs`. Stop if the root
  cause maps outside the conditional allow-list.
- [ ] **Step 6.4 (2–5 min): Make the smallest owning fix.** Preserve endpoint,
  DTO, copy, race, dirty-state, and existing route contracts. Do not refactor an
  adjacent subsystem.
- [ ] **Step 6.5 (2–5 min): Re-run the exact RED node through the resource gate.**
  Require focused GREEN and unchanged real-resource snapshots.
- [ ] **Step 6.6 (2–5 min): Re-run the owning new file through the resource
  gate.** Use one of the exact commands below, serially, and require all nodes in
  that file GREEN:

  ```bash
  DISABLE_EXTERNAL_AI=1 ./.venv/bin/python -m pytest -q tests/browser/test_teacher_failure_paths.py
  DISABLE_EXTERNAL_AI=1 ./.venv/bin/python -m pytest -q tests/browser/test_teacher_accessibility.py
  ```

  These are two separate invocations with a snapshot before/after each; never
  execute both lines concurrently.

## TDD unit 7 — Serial regression and report

- [ ] **Step 7.1 (2–5 min): Run the complete new failure file through the
  resource gate.** Run
  `DISABLE_EXTERNAL_AI=1 ./.venv/bin/python -m pytest -q tests/browser/test_teacher_failure_paths.py`
  and record exact pass/fail/deselect counts.
- [ ] **Step 7.2 (2–5 min): Run the complete new accessibility file through the
  resource gate.** Run
  `DISABLE_EXTERNAL_AI=1 ./.venv/bin/python -m pytest -q tests/browser/test_teacher_accessibility.py`
  and record exact counts.
- [ ] **Step 7.3 (2–5 min): Run existing Teacher lock/Today regression through
  the resource gate.** Run serially:

  ```bash
  DISABLE_EXTERNAL_AI=1 ./.venv/bin/python -m pytest -q tests/browser/test_teacher_lock.py tests/browser/test_teacher_today.py
  ```

  Record exact counts.
- [ ] **Step 7.4 (2–5 min): Run existing Teacher routing/review-loading
  regression through the resource gate.** Run serially:

  ```bash
  DISABLE_EXTERNAL_AI=1 ./.venv/bin/python -m pytest -q tests/browser/test_teacher_routing.py tests/browser/test_teacher_review_loading.py
  ```

  Record exact counts.
- [ ] **Step 7.5 (2–5 min): Run existing Teacher review-editing regression
  through the resource gate.** Run serially:

  ```bash
  DISABLE_EXTERNAL_AI=1 ./.venv/bin/python -m pytest -q tests/browser/test_teacher_review_editing.py
  ```

  Record exact counts.
- [ ] **Step 7.6 (2–5 min): Run existing Teacher management/reports regression
  through the resource gate.** Run serially:

  ```bash
  DISABLE_EXTERNAL_AI=1 ./.venv/bin/python -m pytest -q tests/browser/test_teacher_management.py tests/browser/test_teacher_reports.py
  ```

  Record exact counts.
- [ ] **Step 7.7 (2–5 min): Run all six Teacher Node suites serially.** Run:

  ```bash
  node --test --test-concurrency=1 tests/frontend/teacher/dirty-guard.test.mjs tests/frontend/teacher/management.test.mjs tests/frontend/teacher/reports.test.mjs tests/frontend/teacher/review.test.mjs tests/frontend/teacher/router.test.mjs tests/frontend/teacher/today.test.mjs
  ```

  Record exact counts. Node tests do not replace browser acceptance.
- [ ] **Step 7.8 (2–5 min): Run syntax and policy checks.** Run `node --check`
  separately for each changed teacher JavaScript/module path, then run:

  ```bash
  rg -n "fetch\(|\.then\(r\s*=>\s*r\.json|alert\(|method:\s*['\"]DELETE" app/frontend/teacher/app.js app/frontend/teacher/router.mjs app/frontend/teacher/dirty-guard.mjs app/frontend/teacher/views app/frontend/teacher/styles.css
  git diff --check
  ```

  The policy scan must have no matches; `git diff --check` must exit 0.
- [ ] **Step 7.9 (2–5 min): Write the Task 8 report.** Include start HEAD,
  contract-review verdict, required/conditional paths, every direct-GREEN,
  genuine RED, test-harness correction, minimal fix, command/count, before/after
  resource line, tripwire status, three historical incidents, P0/P1 disposition,
  limitations, and bounded Task 8 GO/NO-GO. Do not claim final release GO.

## Historical safety incidents and final acceptance handoff

Task 8 report and independent review must explicitly carry all three incidents:

1. **Pipeline Task 8 provider incident.** Before the permanent breaker existed,
   the first RED of a legacy-finalizer API test failed to fake two high-level
   calls. At `2026-08-23 22:59:31 +08` and `22:59:44 +08`, two synthetic-only
   DeepSeek requests returned HTTP 200. The test used a temporary SQLite file
   and no real child/application DB data, but it crossed the provider boundary.
   Permanent prevention is the autouse lowest-level `_llm` breaker plus fake
   high-level calls. Source:
   `.superpowers/sdd/2026-08-23-reliable-conversation-pipeline/task-8-report.md`.
2. **Child Task 9 real-log incident.** A pre-remediation full fault run reached
   55 passing functional nodes, then teardown caught an asyncio pending-route
   error appended to real `logs/app.log` at `2026-08-27 19:33:50` Asia/Shanghai.
   Root cause was a parent-process real FileHandler. The incident bytes were not
   reverted/deleted; the child report keeps process compliance and overall
   release NO-GO pending explicit final risk acceptance. Permanent prevention
   is the browser parent logging guard and byte comparison. Source:
   `.superpowers/sdd/2026-08-23-child-interaction-recovery/task-9-report.md`.
3. **Teacher Task 5/5A real-log incident.** An orchestration batch overlapped one
   non-browser review-atomic pytest with two browser suites. The shared
   non-browser TestClient FileHandler wrote preserved test records to the real
   log. Task 5A isolated shared pytest logging at commit
   `5fbd06127f695588336299b1e5168f79d91b2685`; incident bytes remain preserved
   at the frozen SHA/size/mtime. Permanent prevention is serial execution plus
   disposable parent/application logs and session resource guards. Sources:
   `.superpowers/sdd/2026-08-23-teacher-workbench-and-acceptance/task-5-report.md`
   and `task-5a-log-isolation-report.md`.

Task 8 can return bounded GO only when its contract, code, safety, and exact
stage gates pass. It cannot accept historical release risk on the user's
behalf. The final Task 9 acceptance must inventory current real suites, use the
lowest-level provider breaker and logical SQLite digest, map concrete evidence
to all 14 mandatory gates in specification section 16, list all three incidents
with remediation evidence, and record explicit reviewer/user disposition.
Any failed mandatory gate, resource drift, new safety incident, or unaccepted
required risk keeps the overall release at NO-GO.

Task 8 directly contributes evidence to mandatory gates 3, 11, 12, 13, and 14:
repeated/faulted operations do not duplicate work; auto roster replay is stable;
deactivation is named/reversible; the teacher review flow is keyboard-only; and
browser tests exercise real UI interactions with fault paths under disposable
database/resource assertions. It does not independently satisfy the other nine
gates.

## Exact stage, independent review, and commit boundary

- [ ] **Step 8.1 (2–5 min): Confirm the owned worktree set.** Run
  `git status --short --untracked-files=all`, `git diff --name-only`, and
  `git ls-files --others --ignored --exclude-standard` for the two SDD files.
  Require only the four inherited dirty paths plus Task 8 allow-listed changes.
- [ ] **Step 8.2 (2–5 min): Stage required Task 8 files exactly.** Run:

  ```bash
  git add -- tests/browser/test_teacher_failure_paths.py tests/browser/test_teacher_accessibility.py
  git add -f -- .superpowers/sdd/2026-08-23-teacher-workbench-and-acceptance/task-8-brief.md .superpowers/sdd/2026-08-23-teacher-workbench-and-acceptance/task-8-report.md
  ```

- [ ] **Step 8.3 (2–5 min): Stage only changed conditional product paths.** For
  each changed path documented by a focused product RED, run its exact command:

  ```bash
  git add -- app/frontend/teacher/styles.css
  git add -- app/frontend/teacher/app.js
  git add -- app/frontend/teacher/router.mjs
  git add -- app/frontend/teacher/dirty-guard.mjs
  git add -- app/frontend/teacher/views/today.mjs
  git add -- app/frontend/teacher/views/review.mjs
  git add -- app/frontend/teacher/views/management.mjs
  git add -- app/frontend/teacher/views/reports.mjs
  ```

  A command for an unchanged path is omitted. Never stage a directory.
- [ ] **Step 8.4 (2–5 min): Verify the staged allow-list.** Run
  `git diff --cached --name-only`, `git diff --cached --check`, and
  `git diff --cached --stat`. The staged list must contain all four required
  Task 8 paths and only conditional files that have report-linked RED/GREEN
  evidence. It must contain none of the four user-owned dirty paths.
- [ ] **Step 8.5 (2–5 min): Request independent staged-diff review.** Give the
  reviewer the frozen brief, report, staged diff, direct-GREEN/RED ledger,
  resource snapshots, and coverage ledger. Require an explicit contract/code/
  safety verdict with P0/P1/P2 and a challenge to at least one assumption.
- [ ] **Step 8.6 (2–5 min): Resolve each review P0/P1 through focused TDD.**
  Unstage nothing outside Task 8, reproduce the finding with one focused node,
  apply the minimal owned fix, rerun focused and owning regression, update the
  report, restage exact paths, and request a fresh independent review.
- [ ] **Step 8.7 (2–5 min): Run the final focused files after Review GO.** With
  snapshots around each separate invocation, rerun the complete failure file
  and complete accessibility file. Require fresh GREEN and unchanged resources.
- [ ] **Step 8.8 (2–5 min): Recheck staged and preserved state.** Require
  `git diff --cached --check` and `git diff --check` exit 0, exact staged
  allow-list, unchanged four user paths, exact resource baseline, and exact HEAD
  still equal to the frozen start commit before committing.
- [ ] **Step 8.9 (2–5 min): Create one atomic Task 8 commit.** Only after fresh
  Review GO with no P0/P1, commit exactly:

  ```text
  test: cover teacher faults and keyboard workflow
  ```

  Do not amend an earlier commit and do not make intermediate implementation
  commits.
- [ ] **Step 8.10 (2–5 min): Verify the commit.** Run `git show --check HEAD`,
  compare `git show --format= --name-only HEAD` to the final exact allow-list,
  verify the four user dirty paths remain unstaged/unmodified by Task 8, and run
  the read-only resource snapshot once more. Report the new commit hash and the
  bounded Task 8 verdict; leave overall release status to Task 9.

## Task 8 completion rule

Task 8 is bounded GO only when all of these are true:

- independent Contract GO preceded implementation;
- every required new test has honest direct-GREEN or genuine RED/GREEN evidence;
- every genuine product RED has one minimal allow-listed fix and focused GREEN;
- both new files and all owning Teacher regressions are fresh GREEN, serially;
- no raw service text, duplicate mutation, early success, lost value, stuck
  action, keyboard trap, unlabeled control, false h1 requirement, or nav-element
  mismatch remains;
- the application DB logical digest, real log SHA/size/mtime, and TTS cache
  digest stayed exact around every pytest command, with no tripwire hit;
- independent staged-diff review returns GO with no P0/P1;
- the staged and committed paths equal the exact required set plus only
  report-justified conditional product paths; and
- the report carries all three historical incidents and explicitly states that
  final release remains governed by Task 9 and the 14 mandatory gates.

Any unmet item is Task 8 NO-GO with the exact failing evidence and next focused
retest condition. Never convert a failed safety or acceptance item into a
warning.
