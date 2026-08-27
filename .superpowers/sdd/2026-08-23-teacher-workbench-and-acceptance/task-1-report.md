# Teacher Workbench Task 1 Report — PIN-Gated Shell Extraction

## Scope and start point

- Exact start HEAD: `420bb927da1273eb6255d07c61c945695879273c` on `master`.
- Owned paths only: the semantic teacher shell, extracted stylesheet/module,
  Foundation/static coverage, the isolated teacher browser harness and browser
  coverage, plus this report.
- Preserved user-owned dirty paths without staging or modification:
  `.workbuddy/memory/2026-08-22.md`,
  `docs/superpowers/specs/2026-08-23-interaction-stabilization-design.md`,
  `.superpowers/brainstorm/`, and `docs/superpowers/plans/`.
- No package installation, browser installation, production-server start, real
  database write, real log write, cache write, provider call, or external
  network call was performed.

## TDD evidence

### Unit 1 — static shell RED then GREEN

1. Added the external-shell contract tests before creating the assets.
2. RED command:

   ```text
   ./.venv/bin/python -m pytest -q tests/test_frontend_foundation.py
   6 failed, 4 passed
   ```

   The failures were the expected missing `/teacher/styles.css` and
   `/teacher/app.js` files, missing external entry, and old inline style/script
   assertions.
3. Extracted the CSS and module, changed the HTML to exactly shared API, shared
   auth, and the teacher module, and moved the logo dimensions into CSS.
4. GREEN command:

   ```text
   node --check app/frontend/teacher/app.js
   ./.venv/bin/python -m pytest -q tests/test_frontend_foundation.py
   10 passed
   ```

### Unit 2 — browser shell RED then GREEN

1. Added the `TeacherBrowserHarness` before product extraction. It starts a new
   pinned Chromium browser per test, creates a fresh context with service workers
   blocked, installs the exact-origin route policy before a page exists, and
   never installs Child fail-closed business routes or seeds a cookie.
2. Browser collection:

   ```text
   16 initial tests collected
   ```

3. First exact RED node:

   ```text
   test_teacher_shell_has_no_inline_runtime[1024x768]
   AssertionError: style count was 1, expected 0
   ```

   This was the delivered teacher monolith's inline stylesheet.
4. GREEN first node, then full teacher browser run:

   ```text
   test_teacher_shell_has_no_inline_runtime[1024x768]  1 passed
   tests/browser/test_teacher_lock.py                 16 passed before review follow-up
   ```

### Runtime/PIN lifecycle finding and correction

The initial extracted module exposed a real same-document race: on successful
setup/unlock the old PIN form remained in `main` while the overview was appended.
On a second lock an automation could target the old disabled unlock button.
The module now removes the successful form before resolving the auth transition.
Browser tests explicitly require zero `form` and zero `#teacher-pin` elements in
the authenticated overview, and the setup/manual-lock/pagehide nodes passed at
both `1024x768` and `1440x900`.

### Independent-review P1 — auth-status error sanitization

Independent review found that a standard 500 envelope from
`/api/auth/status` could reach `handleTeacherBootstrapFailure` after runtime
readiness and render the server's raw `error.message`. A new two-viewport node
was added first and correctly RED:

```text
test_teacher_auth_status_failure_is_safe_and_makes_zero_business_requests
2 failed: the fixed safety copy was absent
```

The non-maintenance bootstrap branch now renders only
`教师端暂不可用，请稍后重试。`; the Foundation-maintenance early return remains
unchanged. The new test routes only exact-origin `/api/auth/status` to a 500
standard envelope and proves raw detail is absent, navigation remains disabled,
and no business request occurs. It then GREENed at both viewports.

## Final verification

```text
DISABLE_EXTERNAL_AI=1 ./.venv/bin/python -m pytest -q \
  tests/test_frontend_foundation.py tests/test_teacher_auth.py
19 passed

./.venv/bin/python -m pytest -q tests/browser/test_teacher_lock.py
18 passed

./.venv/bin/python -m pytest -q tests/browser/test_child_teacher_help.py
14 passed

./.venv/bin/python -m pytest -q tests/browser/test_child_faults.py \
  -k 'shared_unused or parent_logging or controlled_recognition or manual_space or silence_clock or chat_retryable or chat_fault_matrix or chat_replay or chat_conflicting'
22 passed, 32 deselected

./.venv/bin/python -m pytest -q tests/browser/test_child_faults.py \
  -k 'tts_faults or tts_cold_start'
14 passed, 40 deselected

./.venv/bin/python -m pytest -q tests/browser/test_child_faults.py \
  -k 'completion_fault_matrix or completion_replay or reload_during_submit or pagehide_destroy or completed_reset or fault_recovery'
20 passed, 34 deselected

./.venv/bin/python -m pytest -q tests/browser/test_child_shell.py \
  -k 'not keyboard_modality and not empty_roster and not active_conversation_shell and not space_is_single_action and not keyboard_focus_visible and not projection_is_reachable and not child_health_validation_fallback'
36 passed, 14 deselected

./.venv/bin/python -m pytest -q tests/browser/test_child_shell.py \
  -k 'keyboard_modality or empty_roster or active_conversation_shell or space_is_single_action or keyboard_focus_visible or projection_is_reachable or child_health_validation_fallback'
14 passed, 36 deselected

node --check app/frontend/teacher/app.js
./.venv/bin/python -m py_compile tests/browser/conftest.py tests/browser/test_teacher_lock.py
git diff --check
all passed
```

The Child-fault partitions intentionally overlap two terminal accessibility rows
because their parameter IDs contain the selected recovery tokens; together they
cover every one of the 54 collected nodes. The Child-shell partitions cover all
50 collected nodes. An initial combined Child-browser run reached 62 dots before
the desktop command window limit; it was stopped at 60 seconds, and all nodes
were then rerun in the bounded partitions above.

The static policy scans for direct fetch, PIN persistence, reload, inline style,
and inline executable scripts returned no matches. The pinned browser gates
validated Playwright `1.62.0`, Chrome for Testing and Headless Shell
`151.0.7922.34`, revision `1234`. Fixture teardown verified the application
database, log, and TTS-cache snapshots were unchanged, and all provider/network/
egress tripwire files remained absent.

## Delivered behavior retained

- The existing overview, children, ducks, roster, review, growth, and search
  route builders and their existing endpoint operations remain in the module.
- `window.DuckAPI.ready()` completes before the first `window.DuckAuth.status()`
  and before any business route is built.
- First setup, wrong PIN, real unlock, real same-document lock, lock failure,
  auth-status failure, context-cookie expiry, runtime maintenance, and pagehide
  cleanup are exercised over the disposable loopback server at both required
  viewports.
- Wrong-PIN, lock-failure, and auth-status-failure copy is fixed and API-safe;
  no raw server detail is rendered. PIN material is cleared after successful
  auth, lock, and pagehide, and is not stored in DOM text, URL, session storage,
  or local storage.

## Residual risks / deferred scope

- This task intentionally preserves the delivered management/review route
  behaviors; their redesign and stronger workflow semantics belong to later
  Teacher Workbench tasks.
- The existing tests emit known FastAPI/SQLAlchemy deprecation warnings; no new
  task-specific warning or failure was observed.
- Independent code review initially found and then re-reviewed the auth-status
  disclosure P1; the fix received Code Review GO before this exact commit.
