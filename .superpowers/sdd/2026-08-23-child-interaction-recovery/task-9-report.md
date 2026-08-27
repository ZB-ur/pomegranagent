# Child Interaction Recovery — Task 9 Report

## Decision

- **Functional implementation gate: GO.** The final child browser release matrix
  is green at both `1024x576` and `1280x720`.
- **Task 9 process-compliance gate: NO-GO.** One pre-remediation run wrote an
  asyncio error to the real application log. Later tests prove the corrected
  parent/subprocess guards, but they cannot erase that historical breach.
- **Overall release decision: NO-GO pending explicit final risk acceptance.**
  Teacher Workbench delivery and the final Foundation/release review also remain
  downstream gates.

## Boundary

- Exact start HEAD: `4a8036a3ea05b01604bbcf86db8897d3a1b89824`.
- Product code and backend code changed: none.
- Owned paths only:
  - `tests/browser/child_fakes.py`
  - `tests/browser/test_child_faults.py`
  - `tests/browser/conftest.py`
  - `tests/browser/test_child_shell.py`
  - `tests/browser/test_child_teacher_help.py`
  - this report
- Existing user changes in `.workbuddy/memory/2026-08-22.md`, the interaction
  stabilization spec, `.superpowers/brainstorm/`, and `docs/superpowers/plans/`
  remained untouched and unstaged.

## Browser gate and isolation evidence

- Playwright package: `1.62.0`.
- `playwright install --dry-run chromium` resolved, without installing:
  - Chrome for Testing `151.0.7922.34`, revision `1234`, at
    `~/Library/Caches/ms-playwright/chromium-1234`.
  - Chrome Headless Shell `151.0.7922.34`, revision `1234`, at
    `~/Library/Caches/ms-playwright/chromium_headless_shell-1234`.
- Runtime launch and user-agent validation passed before any loopback server was
  constructed.
- Every server used `127.0.0.1`, a disposable app-mode SQLite database, disposable
  log directory, disposable TTS cache, a non-starting analysis worker, disabled
  dotenv/provider environment, lowest-level AI/TTS/socket tripwires, service-worker
  blocking, fail-closed business routes, and exact-origin context routing.
- The application database logical SQLite digest, real log bytes, and real TTS
  cache digest were checked at teardown. AI, network, and context-egress tripwire
  files remained absent in the final full runs.
- The parent pytest process is now independently guarded: any real `app.log`
  handler inherited from early backend import is removed for the browser session,
  replaced with a disposable handler, and the real log bytes are compared before
  restoration.

## TDD and incident record

The following were genuine RED results and were not hidden:

1. The first shared-port test failed because `unused_tcp_port` did not exist in
   every browser module. One shared fixture replaced the teacher-local shadow.
2. The first controlled-recognition test failed because `window.__childTest` did
   not exist. A single shared deterministic recognition/audio/browser-speech fake
   replaced the old auto-ending fakes.
3. The migrated shell test failed on the removed `window.__childSpeech` surface;
   assertions were moved to the controlled fake and explicit terminal events.
4. The initial silence test advanced a running Playwright clock before the
   1,499 ms assertion. The test now pauses at a known epoch and proves no stop at
   1,499 ms and exactly one stop at 1,500 ms.
5. The initial cold-start holder assertion ran before the route callback recorded
   the held request. The assertion was moved behind the request event; the product
   behavior was unchanged.
6. The first accessibility node exposed a Playwright Python argument-signature
   mistake, and the completion row then exposed an incorrect expected copy. The
   test now asserts the frozen local fallback copy
   `这次对话需要老师检查后再继续`.
7. The first full fault run had 55 passing functional nodes but teardown correctly
   failed because the parent pytest process wrote an asyncio pending-route error to
   the real `logs/app.log` at 2026-08-27 19:33:50 Asia/Shanghai. The log was not
   reverted or deleted. Root cause was the real FileHandler inherited from the
   parent backend import, not the disposable child server. The parent logging guard
   above was added test-first; the original trigger node, two consecutive fault
   suites, and the full browser suite then preserved the real log bytes.
8. The first three-suite run finished 118 passing with two failures because an old
   shell assertion still required `老师帮忙` to be disabled for an empty roster.
   Task 8 freezes the button as enabled in every state. The stale assertion was
   updated to require enabled and focusable behavior; both focused viewports and
   the complete suite then passed.
9. A final shared-fixture source audit initially matched its own assertion string
   as though it were a fixture declaration. It was narrowed to line-leading Python
   declarations and then proved the single conftest definition plus zero shell,
   teacher, or fault-module shadows.
10. Independent review found a disallowed `boundary_mismatch` ID in the chat fault
    matrix. It had no handler branch and duplicated non-JSON coverage. The two
    false-green rows were removed; boundary mismatch remains only in the frozen
    completion matrix. Review also found the reload row conditionally accepted a
    closed route. That exception branch was removed. Both viewports now require
    the pre-reload held response to be fulfilled successfully, then prove the
    restored bytes and visible retry state are unchanged.

All other new chat, replay, TTS, completion, reload, pagehide, reset, and
accessibility rows were direct-GREEN against the approved Task 0–8 implementation.
No product change was made to manufacture a browser pass.

## Behavioral evidence

- Manual button and global Space paths start one live recognition generation and
  require explicit terminal events.
- Silence stops at exactly 1,500 ms.
- Retryable chat preserves and reuses the same request ID and text; double-click
  creates one retry. HTTP 500, non-JSON, offline, valid replay, and conflicting
  replay paths keep raw details out of DOM and session storage.
- Edge HTTP/non-JSON/offline, rejected playback, audio error, browser speech error,
  and the reachable 5,000 ms cold-start fallback settle deterministically without
  duplicate completion.
- Completion HTTP 500, non-JSON, offline, boundary mismatch, and replay retain the
  exact last-message boundary and never show false success.
- Reload during a held chat restores the same durable draft, successfully fulfills
  the pre-reload held response, and ignores its old page callback. `pagehide` makes
  a held callback inert. Completed reset clears
  only the isolated child-session key and returns to welcome without another
  completion request.
- Retryable-chat and completion-recovery projections have one labelled main and
  heading, one fixed-copy alert, one status, correct focus target, unique button
  names, visible nontransparent focus outline, controls at least 44 by 44 px, no
  horizontal clipping, and zero-duration animation/transition under reduced motion.

## Final verification

- `tests/browser/test_child_faults.py`: `54 passed` twice, including teardown.
- Shell + teacher-help + faults browser suite: `118 passed`.
- `node --unhandled-rejections=strict --test tests/frontend/child/*.test.mjs`:
  `252 passed`.
- Chat/completion/models/API boundary suite: `69 passed` with
  `DISABLE_EXTERNAL_AI=1`.
- Foundation/auth/runtime suite: `21 passed` with `DISABLE_EXTERNAL_AI=1`.
- Python compilation for all five executable browser files: pass.
- `git diff --check`: pass.
- Browser policy scan: no session-wide storage clear, no 300 ms sleep, no automatic
  synthetic `onend`, no executable Playwright install, and no production global API
  access in the new fake/fault modules.

Known warnings are the existing Starlette `httpx` and Python
`datetime.utcnow()` deprecations. They did not affect the gate result.
