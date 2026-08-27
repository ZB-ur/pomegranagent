# Child Task 8 Report — PIN-Gated Teacher Recovery

## Boundary and ownership

- Exact approved start HEAD: `febb24a7bf5adac870fe62f9ee2f65530ee8194d` (`docs: record child browser shell approval`).
- Owned product paths: `app/frontend/child/machine.mjs`, `app/frontend/child/app.mjs`, `app/frontend/child/view.mjs`, and `app/frontend/child/styles.css`.
- Owned tests: `tests/frontend/child/machine.test.mjs`, `tests/frontend/child/app-effects.test.mjs`, `tests/frontend/child/view.test.mjs`, and `tests/browser/test_child_teacher_help.py`.
- Existing user changes in `.workbuddy/memory/2026-08-22.md`, `docs/superpowers/specs/2026-08-23-interaction-stabilization-design.md`, `.superpowers/brainstorm/`, and `docs/superpowers/plans/` were preserved and remain outside Task 8.

## TDD evidence

1. The reducer matrix first failed on illegal `welcome:TEACHER_UNLOCKED`; the controls matrix then failed because all five teacher controls were absent. The minimal reducer change added the two all-state authorization events, five guarded recovery-only actions, and derived controls without another mutable busy flag.
2. Extending the app contract first failed exact surface/action validation. The app now exposes exactly eight new teacher methods and forwards thirteen exact view actions through the existing composition boundary.
3. Teacher status, PIN, relock, text/draft, recovery, microphone, and completion each received focused strict tests. PIN values remain only in the input and immediate local variable, are blanked in every completion path, and never enter snapshots, store writes, rendered text, or raw error copy.
4. Unified-registry cancellation produced a real RED: `openTeacherHelp()` followed by same-tick `reset()` still invoked `teacherStatus`. Capturing the invocation epoch before the initialization microtask closed that registration gap for status/auth/lock; registered late responses already remained inert through the shared effects map.
5. The view contract first failed because it still exposed four methods and six actions. The dialog construction test then failed because no native dialog existed; delegation failed before submit/click handlers; focus failed before Tab trapping; and the scoped-style test failed before modal rules were added.
6. The first full browser run exposed a real CSS defect: the higher-specificity `#teacher-actions { display:grid }` overrode native `[hidden]`, showing locked and unlocked panels together. The corrected exact `[hidden]` selectors made setup ordering and authorization visibility deterministic.
7. A browser recovery expectation was corrected without changing product code: `MIC_PERMISSION_DENIED` is intentionally nonretryable, so a successful active reread retains `recovery` and teacher authorization. The test now asserts the preserved boundary, then verifies explicit microphone retry and safe completion.
8. The current pytest environment provides `free_tcp_port`, while the already-approved Task 6B fixture requests `unused_tcp_port`. Task 8 supplies a local test-only alias in its owned module; it does not modify the shared fixture or production runtime.

## Delivered contract

| Area | Result |
| --- | --- |
| Authorization | Status/setup/unlock/lock use only the injected child adapter. Auth-only transitions are nonpersistent and fail closed. PIN failure copy is fixed by code. |
| Recovery | Teacher text is trimmed into the canonical draft and saved before chat; saved-draft mode makes zero chat calls; retry reuses the exact request ID and text. |
| Safe handoff | Recovery rereads the durable local record, retains authorization only for its current authorized effect, and never mutates the stored projection. Microphone and completion start only after guarded persisted transitions. |
| Dialog | A stable native labelled `dialog` survives child-state renders. Locked and unlocked panels are mutually exclusive; durable retry text is reconstructed from the snapshot; no input is rendered as markup. |
| Accessibility | The help button is always reachable, Tab/Shift+Tab wrap enabled native controls, Escape/return/relock restore focus, modal Space never starts speech, and controls meet 44 px/focus/reduced-motion rules. |
| Isolation | Browser tests use Task 6B's loopback-only server, temporary DB/log/cache, fake auth/business/TTS/speech routes, blocked service workers, real-resource snapshots, and provider/network/context-egress tripwires. |

## Browser gate and evidence

Read-only Playwright dry-run reported package `1.62.0`, Chrome for Testing `151.0.7922.34` revision `1234`, and Chrome Headless Shell `151.0.7922.34` revision `1234`. Both expected directories were present:

```text
/Users/lddmay/Library/Caches/ms-playwright/chromium-1234
/Users/lddmay/Library/Caches/ms-playwright/chromium_headless_shell-1234
```

No install command was run. Runtime version and UA gate passed before any server fixture. The first browser attempt stopped before server construction because `unused_tcp_port` was unavailable; after the local test-only alias, the focused denial path passed `2/2`.

```text
./.venv/bin/python -m pytest tests/browser/test_child_teacher_help.py -q
# 14 passed, 0 failed — twice from final source
```

The fourteen cases cover seven flows at 1024×576 and 1280×720: permission denial/open, PIN setup/cleanup, fixed PIN failure, relock/focus, idempotent teacher retry, recovery/microphone/completion boundaries, and Tab/Space/Escape. No AI, network, browser-egress, real database, real log, or real TTS-cache tripwire fired.

## Final Node/static evidence

```text
node --unhandled-rejections=strict --test \
  tests/frontend/child/machine.test.mjs \
  tests/frontend/child/app-effects.test.mjs \
  tests/frontend/child/view.test.mjs
# 138 passed, 0 failed — twice from final source

node --unhandled-rejections=strict --test tests/frontend/child/*.test.mjs
# 252 passed, 0 failed

node --check app/frontend/child/{machine,app,view}.mjs
node --check tests/frontend/child/{machine,app-effects,view}.test.mjs
./.venv/bin/python -m py_compile tests/browser/test_child_teacher_help.py
git diff --check
```

The direct-global audit found no `DuckAPI`, `DuckAuth`, `fetch`, or legacy `acceptText` in Task 8 product modules. The state-sink audit found no `teacherPin` or `pin:` property. Production source contains none of the synthetic PIN/text sentinels used by tests.

## Commit and downstream gate

Implementation commit: pending. This report is force-staged with the whitelist implementation commit; a report-only follow-up will record its hash and independent-review disposition. Foundation Task 9 remains the cross-surface release gate.
