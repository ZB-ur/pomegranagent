# Teacher Workbench Task 2 Report — Fresh Hash Route Lifecycle

## Boundary

- Start HEAD: `0cd5c93c97b77f34a9dd75d8c266804aa8e88b16` (`feat(teacher): extract pin-gated teacher shell`).
- Work remained on the existing `master` checkout. No worktree, dependency installation,
  browser installation, external request, real database, real application log, or TTS cache
  change was made.
- Owned paths staged for review are limited to the eight paths in the Task 2 brief:
  `app/frontend/teacher/router.mjs`, `app/frontend/teacher/legacy-routes.mjs`,
  `app/frontend/teacher/app.js`, `tests/test_frontend_foundation.py`,
  `tests/frontend/teacher/router.test.mjs`, `tests/browser/test_teacher_routing.py`,
  `tests/browser/test_teacher_lock.py`, and this report.
- Preserved and unstaged user paths: `.workbuddy/memory/2026-08-22.md`,
  `docs/superpowers/specs/2026-08-23-interaction-stabilization-design.md`,
  `.superpowers/brainstorm/`, and `docs/superpowers/plans/`.

## TDD evidence

### RED before the route integration

1. Initial Node route-suite RED was recorded as
   `ERR_MODULE_NOT_FOUND` for `app/frontend/teacher/router.mjs`.
2. The first real browser lifecycle node was run before integrating `app.js`:

   ```text
   tests/browser/test_teacher_routing.py::test_teacher_hash_click_back_forward_active_and_focus[1024x768]
   AssertionError: '' == 'overview'
   ```

   The authenticated old page stayed at `/teacher.html` rather than canonicalizing to
   `#overview`.
3. The pre-integration Review/Search error nodes each timed out waiting for the fixed local
   alert `加载失败，请重新进入此页面。`; the hard DELETE error node did the same. This
   confirms the former persistent-view shell had neither router ownership nor route-local
   safe error rendering.
4. The static integration RED was `4 failed, 7 passed`: the router and legacy modules were
   absent and the permanent view cache was still present.

### Implementation

- `router.mjs` owns fragment parsing/canonicalization, intent tokens, native abort controllers,
  stale-result fencing, exactly-once cleanup, active navigation state, heading focus,
  hash/back-forward lifecycle, same-route refresh, and idempotent stop.
- `legacy-routes.mjs` owns the seven delivered route builders and all legacy endpoint literals.
  Its injected scoped request helper attaches the epoch signal, silently consumes cancellation
  and stale continuations, and renders only the fixed route-local failure copy for a current
  non-abort failure.
- `app.js` retains the Task 1 ready-before-auth/PIN lifecycle, creates a single router only
  after server-side authentication, and stops/nulls it before the post-lock form is rendered.
  Successful setup/unlock canonicalizes on the same document to `#overview`; a pre-existing
  fragment query is preserved.

## GREEN verification

All commands below completed on the cached Playwright 1.62.0 / Chrome for Testing and Headless
Shell 151.0.7922.34 revision 1234 gate. Each browser fixture used the disposable app-mode
server, exact-origin route policy, resource digests, and egress/AI/TTS tripwires.

```text
node --unhandled-rejections=strict --test tests/frontend/teacher/router.test.mjs
11 pass, twice

node --unhandled-rejections=strict --test \
  tests/frontend/teacher/router.test.mjs tests/frontend/child/*.test.mjs
263 pass

DISABLE_EXTERNAL_AI=1 ./.venv/bin/python -m pytest -q \
  tests/test_frontend_foundation.py tests/test_teacher_auth.py
20 passed

./.venv/bin/python -m pytest -q tests/browser/test_teacher_lock.py
20 passed

./.venv/bin/python -m pytest -q tests/browser/test_teacher_routing.py
22 passed

node --check app/frontend/teacher/app.js
node --check app/frontend/teacher/router.mjs
node --check app/frontend/teacher/legacy-routes.mjs
./.venv/bin/python -m py_compile \
  tests/browser/test_teacher_lock.py tests/browser/test_teacher_routing.py
all passed
```

The routing browser suite covers both `1024x768` and `1440x900`: canonical empty/unknown
fragments after auth, direct `#growth?child_id=7` and same-context authenticated refresh,
back/forward, active/ARIA/focus, same-route re-read without a history entry, held-request
abort with no late DOM mutation, rapid transitions, manual lock/unlock listener ownership,
and the Review/Search/DELETE standard-error boundaries. The fixture records a canceled held
request before accepting the new route; stale response data cannot replace the new view.

One browser-test helper defect was corrected during GREEN verification: Playwright evaluates
the supplied element as the callback argument, so `node => document.activeElement === node`
is required; the old source-string use of `arguments[0]` raised a test-side `ReferenceError`.
This was not a product focus failure. After the correction the 22-row suite passed cleanly.

## Independent-review P1 correction

Independent review identified two lifecycle races after the original GREEN run. Both were
reproduced with new RED tests before modifying product code.

1. **Post-lock auth-status failure.** A successful `DuckAuth.lock()` removes the lock control
   before `unlockTeacherPage()` rechecks server status. With a 500 status response, the former
   broad `catch` attempted `lockButton.disabled` after nulling it, preventing the safe terminal
   state. The new two-viewport browser test first completes setup, then routes only the
   post-lock `/api/auth/status` to a standard-error body containing
   `raw-post-lock-status-detail-2468`. RED timed out waiting for
   `教师端暂不可用，请稍后重试。`. The lock RPC catch is now separate and retains the
   authenticated view/button only when the lock RPC itself fails. Once lock succeeds, the
   transition stops router ownership, nulls the control, and wraps unlock/start in a separate
   catch that calls `handleTeacherBootstrapFailure`. GREEN proves the fixed copy, no raw detail,
   disabled navigation, no PIN form/business view, no post-failure business request even after a
   forced disabled navigation click, and no page error.
2. **Pending leave-confirmation forks.** Two new pure-router REDs showed an old deferred
   Overview→Children confirmation could still accept after Back returned to `#overview`, or
   after clicking the current Overview button left the URL at `#children`. The first RED ended
   with current hash `children`; the second ended with `#children`. A same-fragment transition
   now invalidates the outstanding intent before returning. A current-button click whose location
   hash differs from the accepted fragment first restores the accepted fragment with
   `replaceState`, then refreshes, which invalidates the older intent. Both targeted rows pass;
   the old confirmation cannot invoke the Children loader.

Post-correction verification:

```text
node --unhandled-rejections=strict --test tests/frontend/teacher/router.test.mjs
11 pass, twice

./.venv/bin/python -m pytest -q tests/browser/test_teacher_lock.py
20 passed

./.venv/bin/python -m pytest -q tests/browser/test_teacher_routing.py
22 passed

DISABLE_EXTERNAL_AI=1 ./.venv/bin/python -m pytest -q \
  tests/test_frontend_foundation.py tests/test_teacher_auth.py
20 passed

node --unhandled-rejections=strict --test --test-reporter=dot \
  tests/frontend/teacher/router.test.mjs tests/frontend/child/*.test.mjs
263 passing rows
```

Policy scans were empty:

```text
rg -n 'fetch\\(|bootstrapVersionGate|const views = \\{|location\\.reload\\(' app/frontend/teacher
rg -n 'error\\.message|innerHTML\\s*=\\s*error|textContent\\s*=\\s*error' app/frontend/teacher
```

`git diff --check` passed. Browser fixture safety assertions passed; no tripwire fired and
the real DB/log/TTS-cache digests were unchanged.

## Residual limitation for later tasks

This is deliberately a lifecycle migration. The seven legacy route builders and their
success-only management/review operations are still present, but unsupported legacy endpoints
now fail visibly with fixed local copy rather than raw server detail or fabricated success.
Tasks 3+ own their product-contract replacements; this task does not claim those legacy
operations are newly supported.

## Warnings

- The Python suites emitted existing Starlette TestClient and SQLAlchemy `utcnow()` deprecation
  warnings. They are unrelated to this frontend lifecycle change.
- Commit is intentionally not created here: staged evidence awaits independent code review.
