# Teacher Task 5 Report — Atomic, accessible, loss-resistant review editing

## Boundary

- Original Task 5 start HEAD: `fabb152f68a4247f6fd6d07b59331ae704754154`.
- Authorized resume HEAD after the Task 5A safety prerequisite:
  `5fbd06127f695588336299b1e5168f79d91b2685`.
- Authoritative contract: the latest `task-5-brief.md`, including its
  Authorized resume section.
- Only the twelve Task 5 owned frontend, test, CSS, and report paths were
  modified or created. Backend, Today/legacy modules, teacher HTML/PIN tests,
  browser fixtures/dependencies, Child files, and prior reports were not changed.
- The four pre-existing user-dirty paths remained untouched and unstaged.
- No package/browser installation, provider/external network call, real
  application DB/TTS-cache mutation, or manual log rewrite occurred.

## TDD evidence

### Unit 1 — dirty guard lifecycle

- First RED:
  `node --unhandled-rejections=strict --test tests/frontend/teacher/dirty-guard.test.mjs`
  failed with exact `ERR_MODULE_NOT_FOUND` before `dirty-guard.mjs` existed.
- GREEN twice: 3/3 and 3/3. The suite covers exact own-data dependency
  reflection, accessor/Proxy containment, one unload listener, canonical dirty
  snapshots, clean fast path, shared confirmation, Continue/Discard/Escape,
  pending release, idempotent release, and reactivation.
- Final policy RED: the frozen no-`window.` scan found two text-level
  `record.window` member accesses in safe dependency validation. The minimal
  equivalent local destructuring change removed those matches; DirtyGuard then
  passed 3/3 twice and both policy scans passed.

### Unit 2 — strict editor contracts, composition, and active-nav ownership

- Review RED: the first strict acknowledgement test failed because
  `applyReviewAcknowledgement` was absent. GREEN twice was initially 13/13;
  after late-owner/error-projection and independent-review remediation, the
  final strict suite passed 20/20 twice.
- Static composition RED:
  `pytest -q tests/test_frontend_foundation.py` produced 1 failed / 10 passed
  because `app.js` did not yet compose the one shared dirty guard. GREEN: 11/11.
- Router active-nav RED: 11/13; the current-route click refreshed without the
  captured active-state/intent-owned confirmation. GREEN twice: 13/13. The
  matrix covers Continue, Discard, a shared Promise with only the latest click
  refreshing, intervening Hash and Back/Forward changes, pending different
  Hash restoration, and `stop()` invalidation.
- Browser bootstrap exposed one real product RED after the fake injected guard
  gained `isDirty`: Review dependency reflection omitted that required method,
  causing Review 8/13. The exact dependency seam was corrected and Review
  returned to 13/13; the Task 4 deep-link slice remained 2/2.
- The strict acknowledgement rejection table independently covers exact keys,
  accessor/Proxy input, saved flag, identity/status/revision/timestamp, feeding
  IDs/categories/content/duck IDs, emotion strings/bounds/note, insight,
  duplicate/invalid dimensions, scores/reasons, and finite overall. Nested
  saved review data is applied only at `detail.review`.

### Unit 3 — accessible edit, draft, and confirm round trips

- First 1024 browser RED: the succeeded detail had no editor. The minimum form,
  serializer, save state machine, app composition, and CSS were then added.
- Dual-viewport draft proof edits and trims every editable group, preserves
  feeding/duck/dimension IDs, permits a blank draft reason, captures one exact
  complete PUT, accepts only a newer strict acknowledgement, updates nested
  state, announces success, and reloads only the pending queue.
- Accessibility RED: the reason textarea had no `aria-describedby`. Adding
  stable field error IDs/associations made the focused slice 2/2.
- Complete confirm proof passed 2/2 with exact `action: "confirm"`, strict
  `confirmed` acknowledgement, `审阅已确认`, and queue removal.
- Test-only correction: the confirm test initially expected stale copy
  `暂无待审阅记录`; it was changed to the frozen Task 4 copy
  `暂无待审阅会话`. Product behavior was not changed for that failure.

### Unit 4 — validation and failure preservation

- Client-invalid dual-viewport matrix passed 14/14: blank feeding, emotion,
  and insight; missing/out-of-range intensity; missing/out-of-range score. Each
  sends zero PUTs, renders fixed inline copy, associates `aria-invalid`, and
  focuses the first invalid control. Confirm blank reason is rejected, while
  the complete draft round trip proves blank reason remains valid.
- PUT fault matrix passed 22/22 across both viewports: 422 validation, 409,
  401, 404, 500 JSON, non-JSON, offline, wrong conversation/status, stale
  revision, and malformed nested review. Exact typed values remain; actions
  unlock; no raw server detail, success copy, or queue reload appears.
- Strict Node hostile projection passed inside final Review 20/20: outer
  accessor/Proxy, fieldErrors accessor/Proxy/nested accessor, one/two `body.`
  prefixes, aggregate, immutable, unknown/out-of-range paths. Traps are not
  executed, no server values render, and fixed local copies are used.
- Delayed-save browser proof passed 2/2: double/cross-button programmatic
  activation sends one PUT, every form control/action remains disabled for the
  whole mutation, exact options include `timeoutMs: 15000` and no `timeout`,
  and strict success performs one queue refresh.

### Unit 5 — dirty navigation and ignored-signal ownership

- Browser dual-viewport dirty detail reload and Hash navigation proofs passed:
  Continue retains Hash/form; Discard performs the accepted transition/reload;
  dirty beforeunload is prevented. Active-route/back/stop ownership is covered
  by the strict Router matrix.
- Node ignored-signal coverage added cleanup-late rejection, detail reload, and
  route A -> B, each with both late success and rejection where applicable.
  Old mutations cannot write success/error, mark clean, reload queue, or unlock
  a new owner. Final Review ran 20/20 twice under strict unhandled rejection.
- Test-only correction: two new owner assertions initially used `nodeText()`,
  but the fake DOM intentionally excludes form control `.value`. The assertions
  were corrected to inspect stable `#review-insight.value`; no product change
  was made for those failures.

### Unit 6 — migrated acceptance and final gates

- Only the succeeded-detail Task 4 assertion migrated from zero controls to the
  editor contract. Pending/processing/failed analysis remain read-only with
  zero edit controls and all Task 4 race/error behavior retained.
- Review loading: 32/32. Review editing bounded union: 50/50. Routing: 20/20.
  Lock: 20/20.
- Today bounded union: 70/70. The first full Today command observed one existing
  `offline-1440x900` timing race (69/70): the mocked abort restored its button
  before the immediate disabled assertion sampled it. The exact unchanged
  non-owned test then passed 1/1. No Today file was edited.

## Independent review remediation

The first independent Code Review returned NO-GO with three concrete findings.
Each was verified against the current code, reproduced with a test-first RED,
and fixed without broadening ownership.

1. **Owning fulfilled `undefined` PUT** — Node focused RED showed the form
   permanently retained `正在保存…`; browser dual-viewport RED timed out waiting
   for fixed failure copy. The owning result path no longer treats `undefined`
   as a silent supersession sentinel: strict acknowledgement validation throws
   into the existing owning catch. GREEN proves fixed generic copy, exact typed
   values and dirty state preserved, every control/action unlocked, no queue
   reload/success/pageerror, and one PUT only.
2. **DirtyGuard Proxy reused after safe reflection** — a Proxy with valid data
   descriptors and a throwing `get` trap produced `activate=0` in the RED. The
   factory now returns the reflection-safe guard method copy rather than the
   original injected Proxy. GREEN proves `activate=1`, `markClean=1`, and the
   two existing loading-to-loaded teardown releases without touching the Proxy
   again. Test-only correction: the first expectation incorrectly stated one
   release; the frozen lifecycle performs two.
3. **422 without own-data `fieldErrors`** — focused RED rendered the validation
   summary. `safeErrorProjection` now requires an own data descriptor for
   `fieldErrors`; missing/accessor input is an invalid projection and therefore
   fixed generic `保存失败，请稍后重试。`. Hostile fieldErrors value projection
   remains trap-safe and uses only fixed local copy.

Remediation evidence: focused Node 0/3 RED -> 3/3 GREEN; browser fulfilled-
undefined 0/2 RED -> 2/2 GREEN; final Review Node 20/20 twice; DirtyGuard 3/3;
Router 13/13; related browser save/late matrix 26/26; combined Node 40/40.
Every remediation pytest kept the frozen incident-log triplet unchanged.

## Task 5A incident and safety evidence

- Before authorized resume, an orchestration batch mistakenly overlapped the
  non-browser review-atomic pytest process with two browser suites. Read-only
  diagnosis identified the shared non-browser TestClient FileHandler as the
  writer of preserved `httpx`/`duck_diary` test records in real `logs/app.log`;
  Task 5 product code and the browser child processes were not the writer.
- Task 5A isolated shared pytest application logs and committed that prerequisite
  as `5fbd06127f695588336299b1e5168f79d91b2685` after independent review.
- Every resumed pytest command ran serially. Before and after every command the
  incident log stayed exactly:
  - SHA-256 `5ee47c6b8322aee20aefecbf2344e8134cec18154fb7eb2d00c60116379fbeb7`
  - size `2961585`
  - mtime epoch `1787939944`
- The incident bytes were preserved; the log was never cleaned or rewritten.

## Final verification

- DirtyGuard Node: 3/3; Review Node: 20/20; Router Node: 13/13.
- Combined Today/Review/Router/DirtyGuard Node: 40/40.
- Foundation static + teacher auth + review atomicity: 47/47.
- Teacher Review loading: 32/32; editing bounded union: 50/50.
- Teacher routing: 20/20; lock: 20/20; Today bounded union: 70/70.
- `node --check` for `dirty-guard.mjs`, `review.mjs`, `router.mjs`, and
  `app.js`: PASS.
- `py_compile` for both owned Review browser files: PASS.
- Frozen direct-global/obsolete-write/PATCH policy scans: no matches.
- `git diff --check`: PASS.

Normal Starlette/httpx and datetime deprecation warnings remain. The inherited
stale `tests/frontend/shared/api-client.test.mjs` remains outside Task 5
ownership and was not changed.

## Exact owned paths and review boundary

1. `app/frontend/teacher/app.js`
2. `app/frontend/teacher/router.mjs`
3. `app/frontend/teacher/views/review.mjs`
4. `app/frontend/teacher/dirty-guard.mjs`
5. `app/frontend/teacher/styles.css`
6. `tests/test_frontend_foundation.py`
7. `tests/frontend/teacher/review.test.mjs`
8. `tests/frontend/teacher/router.test.mjs`
9. `tests/frontend/teacher/dirty-guard.test.mjs`
10. `tests/browser/test_teacher_review_loading.py`
11. `tests/browser/test_teacher_review_editing.py`
12. `.superpowers/sdd/2026-08-23-teacher-workbench-and-acceptance/task-5-report.md`

No Task 5 commit has been made. These exact paths are staged for independent
Code Review only. Intended commit after Review GO:
`feat(teacher): save complete reviews atomically`.
