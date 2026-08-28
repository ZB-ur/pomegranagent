# Teacher Task 3 Report — Today task workbench

## Boundary

- Start HEAD: `06df3fe237c2da2ca5377a8823411bb49ba1b265`
- Authoritative contract: `task-3-brief.md` (independent Contract GO before product edits)
- Backend, shared router, browser harness, dependencies, Child product, and prior reports were not modified.
- No package installation, provider call, external network request, real application DB/log/TTS-cache write, or tripwire event occurred.
- The four pre-existing user-dirty paths remained untouched and unstaged.

## TDD evidence

### Unit 1 — Today route migration

- Static RED: Foundation frontend test failed because the external Today module and Today default route did not exist.
- Legacy wiring RED: the legacy factory exported seven routes including `overview`, not the frozen six.
- GREEN: navigation is `today`, the app injects `createTodayRoute`, default Hash is Today, the legacy Overview loader and `/api/analysis/overview` request are absent, and the generic router's synthetic Overview tests remain intact.

### Unit 2 — strict Today contracts

- RED: `tests/frontend/teacher/today.test.mjs` failed with `ERR_MODULE_NOT_FOUND` before `today.mjs` existed.
- First implementation run exposed a local dependency-validation `ReferenceError`; the implementation scope was corrected without weakening the tests.
- GREEN twice: 4/4. Coverage includes own data descriptors, accessor/Proxy failures, roster DTOs, all three queue DTO/state combinations, safe display names, and exact accepted/replayed retry pairs.

### Unit 3 — synchronous shell and Hash migration

- Browser RED: the 1024x768 exact node timed out waiting for the missing `今日任务` h1.
- GREEN: 6/6 across 1024x768 and 1440x900. Coverage includes authenticated-only `#overview` -> `#today` replacement, empty/unknown Hash canonicalization, focus, visual order, fixed initial request order, no cumulative overview request, 44px primary action, keyboard focus, and no horizontal overflow.

### Unit 4 — independent panel states

- Browser RED: an HTTP 500 left its panel permanently in the visible loading state instead of the fixed scoped failure state.
- GREEN in bounded partitions: 24 + 8 + 8 + 8 = 48 passing nodes. Coverage includes loading, empty, HTTP 500, non-JSON, malformed JSON, mixed sibling outcomes, invalid processing/failed combinations, panel-local retry, 44px controls, and no horizontal overflow.
- Test-only correction: a Python closure captured the wrong parameter and raised `KeyError`; the fixture callback signature was corrected. No product contract changed.

### Unit 5 — analysis retry

- Browser RED: the failed-row retry button was not disabled immediately.
- GREEN exact accepted node: 1/1.
- GREEN full retry matrix: 20/20. Coverage includes synchronous disabled state, double-click/Enter single flight, exact endpoint, accepted and pending replay responses, failed -> processing -> pending refresh order, mismatch/malformed/401/404/409/500/non-JSON/offline fixed errors, restored failure action, raw-detail suppression, and navigation abort ownership.

### Unit 6 — Task 2 regression migration

- Teacher lock suite: 20/20.
- Teacher routing suite: 22/22.
- Only the product default label/Hash/request changed from Overview to Today. Auth-before-business, back/forward, current-route refresh, history, focus, stale request abort, lock teardown/fresh unlock, fixed errors, and confirm interleavings remain covered.

## Final verification

- `node --unhandled-rejections=strict --test tests/frontend/teacher/router.test.mjs`: 11/11.
- `node --unhandled-rejections=strict --test tests/frontend/teacher/today.test.mjs`: 4/4.
- Full Child + Teacher Node suite: 267/267.
- Foundation frontend + teacher auth: 20/20.
- Teacher lock browser suite: 20/20.
- Teacher routing browser suite: 22/22.
- Teacher Today browser suite: 70/70 in 72.08s.
- `node --check` for `app.js`, `legacy-routes.mjs`, and `today.mjs`: PASS.
- `py_compile` for all three owned browser test files: PASS.
- `git diff --check`: PASS.
- Policy scans for direct fetch/global adapters/raw errors and `/api/analysis/overview` in the teacher frontend: no matches (expected `rg` exit 1).

Only the existing Starlette/httpx and datetime deprecation warnings were observed; no test failure or unhandled rejection remains.

## Review and commit boundary

- Independent code review returned GO with no P0/P1. It independently reran
  Teacher Node 15/15, Foundation frontend 11/11, the held-retry/navigation
  browser node 1/1, and the staged diff check.
- Review recorded one inherited P2 outside Task 3 ownership:
  `tests/frontend/shared/api-client.test.mjs` still assumes an inline teacher
  script. Therefore 267/267 is accurately the frozen Child + Teacher Node gate,
  not a claim that every `tests/frontend/**/*.test.mjs` file is green. Carry
  this stale shared-test risk into the final acceptance gate.
- No commit has been made by this report at the time of this update.
- Intended commit message after Code Review GO: `feat(teacher): add today task workbench`.
