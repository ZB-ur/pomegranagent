# Child Task 6A Report — Pure Semantic Child View and Projection Styles

## Boundary and start state

- Exact start HEAD verified before writing: `4ed037bb2e4ff4861cbf96f651b7d892f6138be6`.
- Owned implementation paths are only `app/frontend/child/view.mjs`, `app/frontend/child/styles.css`, and `tests/frontend/child/view.test.mjs`; this report is force-staged with the commit.
- No shell, app composition, browser dependency, fixture, API, storage, speech, TTS, machine, backend, or unrelated test was changed.
- Existing user changes in `.workbuddy/memory/2026-08-22.md`, `docs/superpowers/specs/2026-08-23-interaction-stabilization-design.md`, `.superpowers/brainstorm/`, and `docs/superpowers/plans/` were retained and excluded from staging.

## TDD evidence

1. Before `view.mjs` existed, the strict focused command was run against the new Node fake test seam:

   ```text
   node --unhandled-rejections=strict --test tests/frontend/child/view.test.mjs
   ERR_MODULE_NOT_FOUND: Cannot find module
   .../app/frontend/child/view.mjs
   0 pass / 1 fail
   ```

2. The first `view.mjs` implementation was then added without styles. The focused matrix reached 10 passing rows and exposed the expected missing `styles.css` path. Two initial assertions were corrected to match the frozen contract rather than production behavior: a same-state full tree replacement must not move focus onto the new heading, and the per-code fixed recovery copy belongs to the `role=alert` region while only microphone denial overrides the recovery status line.

3. After the standalone scoped styles were added, the focused strict matrix passed twice at `13/13`. It covers exact export/return seams, strict root/action/dom validation, one delegated listener and current-render identity fence, all twelve state frames/status/focus targets, empty roster, log/speaker/draft semantics, defensive retry routing, text-only dynamic content, fixed error mapping, null teacher-help boundary, focus epoch/destroy behavior, and static CSS safety requirements.

4. Independent review then found two construction-boundary defects. New RED coverage first proved that mutating a current rendered native button to `data-child-action="toString"`, `"constructor"`, or `"__proto__"` called a prototype value and threw; the token map is now null-prototype, own-key-gated, and callable-gated. It also proved own action/DOM accessors were invoked during construction and proxy `ownKeys`/descriptor trap errors could escape. Construction now reads exact own keys, then validates each own data descriptor before reading its value; accessors are rejected without invocation and all reflection-trap errors are wrapped in fresh `TypeError` values. The first raw-`TypeError` ownKeys RED specifically rejected the original error object, confirming no exception identity leaked.

## Delivered contract

- `createChildView(root, actions, dom)` imports only `STATES`, `assertSnapshot`, and `controlsFor` from the machine. It reads no browser global and creates no network/storage/speech/timer/HTML-string effect.
- It returns a frozen four-method surface: `render`, `announce`, `focus`, and idempotent `destroy`.
- The strict injected DOM seam prevents hidden browser dependencies. Rendering validates the machine snapshot before mutation, rebuilds exactly one semantic section, uses text nodes for dynamic values, and limits focus to live current-render identities.
- The root has one delegated click listener. Data-action tokens are accepted only for current, connected native buttons, with canonical child IDs; forged, detached, foreign, disabled, unknown, and text-only targets are inert.
- Every state has the required heading/status/help frame. The help button is visibly disabled with an honest note when the Task 8 callback is `null`; no synthetic no-op, dialog, PIN, or teacher action has been introduced.
- Styles are strictly scoped under `#child-app .child-view`, include 44px target minima, 4px focus, scrollable flow/log behavior, reduced motion, and projection breakpoints. They make no viewport measurement claim.

## Final verification

```text
node --unhandled-rejections=strict --test tests/frontend/child/view.test.mjs  # 16 pass
node --unhandled-rejections=strict --test tests/frontend/child/view.test.mjs  # 16 pass
node --unhandled-rejections=strict --test tests/frontend/child/*.test.mjs     # 158 pass
node --check app/frontend/child/view.mjs
node --check tests/frontend/child/view.test.mjs
git diff --check
```

Residual integration scope is intentionally downstream: Task 7 owns browser/app composition and keyboard behavior; Task 6B owns shell migration, real DOM seam injection, Playwright isolation, native-bounds/log/main-heading, and two-viewport evidence; Task 8 owns the real teacher dialog/PIN/relock flow.
