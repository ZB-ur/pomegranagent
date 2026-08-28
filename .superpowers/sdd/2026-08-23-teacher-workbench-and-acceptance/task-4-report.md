# Teacher Task 4 Report — Race-safe split review reader

## Boundary

- Start HEAD: `670aa3671f16844273943c0aeb27a2d9daaf7488`
- Authoritative contract: `task-4-brief.md` (Contract GO before product edits)
- Only the Task 4 owned frontend, test, CSS, and this report paths were changed.
- Backend, `router.mjs`, Today files/tests, PIN shell/tests, browser fixtures,
  dependencies, Child product, and prior reports were not modified.
- No package installation, provider/network call, or real application DB/log/TTS-cache mutation occurred.
- The four pre-existing user-dirty paths remained untouched and will remain unstaged.

## TDD evidence

### Unit 1 — legacy ownership transfer

- Static RED: `tests/test_frontend_foundation.py` failed because `app.js` did
  not import the Review factory.
- Legacy wiring RED: `router.test.mjs` failed because legacy still exported
  `review`.
- GREEN: static 11/11 and router Node 11/11. `review` is no longer a legacy
  export; the old flat queue read and review-only `/logs` and `/assessments/*/confirm`
  writes are removed. App composition is explicitly Today -> Today, Review ->
  Review, remaining five -> legacy.

### Unit 2 — strict pure contracts

- RED: the first review Node run failed with the expected
  `ERR_MODULE_NOT_FOUND` for `views/review.mjs`.
- GREEN twice: 8 pure contract nodes passed before the race additions. Coverage
  includes exact own-data dependencies, accessor/Proxy containment, native-
  compatible injected controllers, canonical safe-positive deep links, all
  nested detail analysis/review unions, strict keys, message boundary/order/
  round, blank draft reasons, duplicate dimensions, ID mismatch, and exact
  cross-source child identity comparison.

### Unit 3 — split read-only deep link

- Browser RED: the first 1024x768 node timed out waiting for the missing
  `值日审阅` h1.
- One implementation correction followed the RED: the detail facts originally
  used a compound text node, so `会话 #42` was not independently available;
  the header now has separate fact elements.
- GREEN: dual viewport 2/2. The reader renders a synchronous 300px split shell,
  starts queue then selected detail independently, keeps the persistent 44px
  detail reload action during loading/loaded states, preserves deep-link Hash,
  renders transcript/results/scores read-only, and has no 1024px overflow.

### Unit 4 — ownership, unavailable states, and reader errors

- Node RED: clicking persistent same-ID reload made only one request (`1 != 2`).
  Root cause was the shell's lack of route-local detail controller/sequence.
- GREEN twice: final Review Node 12/12 under strict unhandled-rejection mode.
  Hostile injected requests deliberately ignore abort while proving A -> B,
  same-ID A -> B, explicit queue reload A -> B, queue replacement, idempotent cleanup, late resolution, and
  late rejection cannot write DOM or report errors.
- Browser RED: pending/processing/failed detail responses fell through the
  succeeded-review renderer and never exposed the transcript.
- GREEN in bounded browser partitions: 32/32 union. Coverage includes queue
  and detail 500/non-JSON/malformed/offline scoped recovery, persistent detail
  reload, valid unavailable analysis (including no server error copy), real
  Hash A -> B abort behavior, lock/reunlock cleanup, both cross-source child
  mismatch response orders, pageerror absence, 44px targets, and 1024/1440
  layout.

### Unit 5 — Task 2 routing acceptance

- Replaced the stale Review+Search legacy fixed-error expectation with
  Search-only; Review has its dedicated reader suite.
- GREEN: teacher routing browser 20/20; Today browser 70/70 via exhaustive
  named partitions (16 + 24 + 12 + 16 + 2) because a single full command
  exceeds the 30-second interactive tool window.

## Final verification

- Teacher router Node: 11/11.
- Review Node: 12/12; combined Today/Review/Router Node: 27/27.
- Full Child + Teacher Node gate: 279/279.
- Foundation frontend + teacher auth + review atomicity: 47/47.
- Teacher routing browser: 20/20.
- Teacher Today browser: 70/70 via named partition union.
- Teacher Review browser: 32/32 via named partition union.
- `node --check` for `app.js`, `legacy-routes.mjs`, and `review.mjs`: PASS.
- `py_compile` for owned browser suites: PASS.
- Policy scans for direct fetch/globals/raw error access, obsolete review write
  endpoints, and editing primitives: no matches.
- `git diff --check`: PASS.

The normal Starlette/httpx and datetime deprecation warnings remain. The
inherited stale `tests/frontend/shared/api-client.test.mjs` remains outside
Task 4 ownership and was not changed.

## Review and commit boundary

- No commit has been made.
- Exact Task 4 owned paths are staged for independent review only.
- Intended commit after independent Code Review GO:
  `feat(teacher): add race-safe review reader`.
