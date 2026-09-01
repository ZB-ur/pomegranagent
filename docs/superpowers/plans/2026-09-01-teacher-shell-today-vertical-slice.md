# Teacher Shell + Today Vertical Slice Implementation Plan

> Execution truth: Figma is the visual/interaction source of truth, current code is the runtime-contract source of truth, and browser tests are the release source of truth.

**Goal:** Deliver the first independently reviewable and reversible teacher-side slice: PIN setup/unlock/lock, shared teacher shell, and the Today workbench at 1024×768 and 1440×900.

**Figma sources:** `T20/Auth Setup/1024` (`106:2`), `T20/Auth Setup/1440` (`106:58`), `T21/Today Mixed Workbench/1024` (`109:2`), and `T21/Today Mixed Workbench/1440` (`109:158`) in file `czJ3EIKcXyowhfzBuQt32S`.

**Runtime boundaries:** Preserve the existing native HTML/CSS/ES-module stack, hash router, auth/session contract, four independently settling Today reads, analysis retry ownership, focus management, safe error copy, and `#overview` migration. Do not change backend routes, database models, or API DTOs.

**Deferred by explicit product decision:** avatar media upload/storage, monthly arbitrary-date roster batch API, real teacher motion assets, and teacher routes outside this slice.

## Task 1: Freeze the shell and Today acceptance contract

**Files:**

- Modify: `tests/browser/test_teacher_lock.py`
- Modify: `tests/browser/test_teacher_today.py`
- Modify: `tests/browser/test_teacher_accessibility.py` only if an existing semantic assertion must be extended

**Steps:**

1. Add failing browser assertions for the Figma shell structure: semantic brand block, teacher subtitle, page top bar, seven navigation items, disabled locked navigation, and one top-bar lock action after authentication.
2. Add failing Today assertions for the hero plus four-panel grid, panel tone hooks, status badges, and the compact unsupported-metrics strip shown in Figma.
3. Assert both release viewports have no horizontal overflow, no overlapping visible shell/Today regions, 44×44 minimum interactive targets, and the main Today content uses the available desktop width.
4. Run the focused tests and record the expected red state before production changes.

## Task 2: Implement the shared teacher shell and auth surface

**Files:**

- Modify: `app/frontend/teacher.html`
- Modify: `app/frontend/teacher/app.js`
- Modify: `app/frontend/teacher/styles.css`

**Steps:**

1. Introduce the Figma-approved teacher visual tokens and scope them under the teacher shell so child styles are unaffected.
2. Rebuild the sidebar brand/nav structure with Noto Sans SC-compatible fallbacks, the approved dark green/cream/blue-green palette, 48px navigation rows, and explicit disabled/active/focus states.
3. Add the shared top bar owned by `app.js`; update its title as routes change without altering router ownership.
4. Rebuild first-setup and locked PIN forms as the centered auth surface while preserving exact labels relied upon by accessibility and auth tests.
5. Keep PIN material out of DOM text, URL, storage, and logs; preserve authentication-before-business-request ordering.

## Task 3: Implement the Today workbench

**Files:**

- Modify: `app/frontend/teacher/views/today.mjs`
- Modify: `app/frontend/teacher/styles.css`

**Steps:**

1. Replace the linear stack with the Figma hero and responsive 2×2 panel grid.
2. Preserve panel DOM ownership and independent loading/empty/error/retry transitions.
3. Render roster, pending, processing, and failed rows with stable class hooks, status badges, safe copy, and existing links/actions.
4. Keep the compact “本周指标暂不可用” strip and do not introduce `/api/analysis/overview` or any new request.
5. Make the 1024×768 view compact without clipping and let 1440×900 use the available width without stretching text beyond readable measures.

## Task 4: Verify, review, and package the slice

**Files:**

- Modify tests only if a failure proves an incorrect new assumption; never weaken existing contract assertions to make implementation pass.

**Steps:**

1. Run teacher Node tests.
2. Run focused teacher lock, Today, accessibility, routing, and release viewport browser tests against an isolated temporary SQLite database.
3. Run the full frontend Node suite and full root Python suite in isolation from the shared database.
4. Capture both Today viewports and compare against Figma for hierarchy, spacing, overflow, focus, and interaction state.
5. Request independent code review, fix all concrete issues, rerun the affected suites, and commit the independently reversible slice.

## Expected change size

- Production: 4 files, approximately 350–650 changed lines, no backend/database migration.
- Tests: 2–3 files, approximately 100–220 changed lines.
- Risk: medium, concentrated in global teacher CSS and auth shell semantics; runtime/API risk remains low because business contracts are unchanged.
