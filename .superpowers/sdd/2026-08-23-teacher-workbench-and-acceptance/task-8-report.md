# Teacher Task 8 execution report

Date: 2026-08-29 (Asia/Shanghai)

## Verdict

**Task 8 implementation, safety, review, and exact-stage gates: bounded GO at the requested pre-commit handoff.**

This is a bounded Teacher Task 8 verdict, not final release GO. The first
independent staged-diff review returned P0=0, P1=2, P2=1; all three findings
received focused repair and regression evidence below. The second independent
review approved Contract, Code, and Safety/Stage with P0=0, P1=0, P2=1, and the
two complete owned files then received fresh post-review GREEN runs. Per the
orchestrator's explicit boundary, this handoff stops with the exact diff staged
and makes no commit; commit/verification steps remain outside this execution.
Task 9 must decide the remaining release gates and historical-risk acceptance.
The overall project release therefore remains **NO-GO pending Task 9**.

## Frozen identity and scope

- Start and current HEAD:
  `a46d475b8e6bcaa655b7d1827e3c7654e599cefb`.
- Authoritative contract:
  `.superpowers/sdd/2026-08-23-teacher-workbench-and-acceptance/task-8-brief.md`.
- Independent contract review:
  **GO, P0=0, P1=0**. One P2 was retained: the yellow focus indicator's
  3:1 non-text contrast against light surfaces was not proven and remains a
  Task 9 acceptance item.
- Required owned paths:
  `tests/browser/test_teacher_failure_paths.py`,
  `tests/browser/test_teacher_accessibility.py`, the frozen brief, and this
  report.
- Conditional paths changed only after focused product RED:
  `app/frontend/teacher/dirty-guard.mjs`,
  `app/frontend/teacher/views/review.mjs`, and
  `app/frontend/teacher/views/management.mjs`.
- Conditional paths not changed because no focused product RED mapped to them:
  `styles.css`, `app.js`, `router.mjs`, `today.mjs`, and `reports.mjs`.
- The inherited user-owned paths `.workbuddy/memory/2026-08-22.md`,
  `docs/superpowers/specs/2026-08-23-interaction-stabilization-design.md`,
  `.superpowers/brainstorm/`, and `docs/superpowers/plans/` were not edited,
  staged, reverted, or cleaned by Task 8.

## Safety evidence

Every pytest command used `DISABLE_EXTERNAL_AI=1`, normal conftests, one serial
process, and an immediately preceding/following frozen resource snapshot. No
pytest overlapped another pytest, Node, subagent command, or any other command.
No package installation, network lookup, real service, real database write,
real log write, or real TTS mutation was authorized or observed.

The resource line before and after every pytest invocation was exactly:

```text
c31f80875458d37e7b9badf086a5ff904a73d1d7f2ef1f5ab716c1f2c9755af3|5ee47c6b8322aee20aefecbf2344e8134cec18154fb7eb2d00c60116379fbeb7|2961585|1787939944|138263700e062272f93b941cebdb36340d3840c03366e638c9f10e3db684030d
```

Database digest, log digest/SHA-size-mtime, and TTS digest never changed. No
lowest-level provider breaker, real-resource guard, parent-log tripwire, or
pending-route teardown tripwire fired.

## Seed-first TDD ledger

### Unit 1: missing read faults and Review PUT timeout

- Representative read seed `seed_today_roster_html_502_1024`: direct GREEN,
  `1 passed` (2.49s). The 1024 slice was `4 passed` (5.42s); both viewports were
  `8 passed` (9.50s).
- Review timeout seed produced a reproducible product RED only at original
  `保存草稿` focus restoration; exact timeout classification, typed-value
  preservation, dirty state, unlock, no success copy, and zero refresh already
  passed. The minimal `review.mjs` owning catch fix restored the matching action
  only for non-field failures. Focused rerun: `1 passed` (2.22s); both
  viewports: `2 passed` (2.83s).
- Independent review found that the timeout wrapper itself retained/exported
  the caught `Error`, and that its identity assertion was therefore
  tautological. This was a test-contract defect, not a product RED. The wrapper
  now exports only copied own-data fields, proves no `error`/rethrown object was
  exported, and still executes `throw error` directly. The seed remained GREEN:
  `1 passed` (2.30s).

### Unit 2: child/duck state settled faults and delay

- `seed_child_deactivate_json_500_1024` produced a product RED only at original
  launcher focus restoration. `management.mjs` now re-enables and focuses the
  still-connected owning action. Focused rerun: `1 passed` (2.30s).
- Settled expansions: `4 passed` (5.47s), `12 passed` (13.23s), then
  `24 passed` (26.60s) for child/duck, deactivate/reactivate, three terminal
  faults, and both viewports.
- Held-delay seed was direct GREEN, `1 passed` (2.36s); cumulative expansions
  were `2 passed` (3.58s), `4 passed` (5.49s), and `8 passed` (9.64s).
- Independent review also found that child/duck state focus restoration was
  expressed unconditionally in `finally`, even though the connected-node guard
  normally prevented a post-reload effect. `management.mjs` now records an
  explicit terminal-failure-only focus flag. This was review-driven hardening,
  not a new observable product RED; the settled-failure and delayed-success
  seeds stayed GREEN together: `2 passed` (3.41s).

### Unit 3: manual/automatic roster fault, identity, and delay

- `seed_daily_json_500_1024` produced a product RED only at the original roster
  submit focus. The minimal `management.mjs` failure-only repair records the
  owning submit, unlocks both forms, and restores focus to that connected node.
  Focused rerun: `1 passed` (2.32s).
- The unchanged retry enhancement initially had one harness RED because it
  incorrectly required checked child controls to survive a successful
  server-snapshot reload. That post-success overconstraint was removed; all
  settled-failure preservation and byte/UUID identity checks stayed intact.
  Corrected seed: `1 passed` (2.08s).
- Settled expansions were `2 passed` (3.58s), `6 passed` (8.12s), and
  `12 passed` (14.82s). Every unchanged retry resent byte-identical body bytes,
  the same body `request_id`, and the same `x-request-id`, followed by exactly
  one success-only reload.
- Roster delay seed was direct GREEN, `1 passed` (2.34s); auto expansion was
  `2 passed` (3.22s), and both viewports were `4 passed` (5.24s). Cross-form
  repeat activation remained one request while both forms were disabled; every
  held route was settled or cleared in `finally`.

### Unit 4: page-keyboard Review and dirty dialog

- `seed_keyboard_review_1024` traversed PIN, Today, Review navigation, queue,
  textarea, radio ArrowRight, and exact PUT before a product RED proved the
  original polite status node was replaced (`same=false`, disconnected, only
  `正在保存…` observed). `review.mjs` now retains that same status node through
  refreshed editor rendering, announces `正在保存…` then `全部修改已保存` on the
  connected node, and focuses the corresponding refreshed action. Focused
  rerun: `1 passed` (2.53s); both viewports: `2 passed` (3.80s).
- The first independent review correctly challenged the assumption that a
  MutationObserver callback seeing `isConnected=true` proved connection at the
  instant of mutation. A synchronous `replaceChildren` probe then produced a
  second genuine product RED: the success write occurred with
  `connected=false` (`1 failed`, 2.63s). The editor refresh now moves the
  retained node only between connected parents, attaches it to the refreshed
  form, and only then writes success copy. The focused seed passed in 2.57s and
  the complete accessibility file passed `22` tests in 25.55s; both synchronous
  writes and both observed announcements are ordered and connected.
- Route headings had a visible computed outline on the actual keyboard path, so
  the plausible heading-style RED did not occur and `styles.css` was not edited.
- Dirty-dialog seed proved a product naming/lifecycle gap. `dirty-guard.mjs`
  now supplies explicit `aria-labelledby`, initially focuses `继续编辑`, and
  explicitly restores the still-connected trigger when navigation is denied.
  The next RED was harness timing: an immediate count ran before asynchronous
  `hashchange -> confirmLeave`; adding a named-dialog wait corrected it.
  Focused rerun: `1 passed` (2.37s); both viewports: `2 passed` (3.55s).

### Unit 5: authenticated structure and separate PIN/locked h2

- Today/1024 had three harness-only corrections: mouse unlock was inconsistent
  with a keyboard-focus assertion; ARIA snapshot YAML may end a named link line
  with `:`; and Python converted an embedded JavaScript `\n` into an invalid
  literal. After correcting only the test, the seed was `1 passed` (2.23s).
- Authenticated 1024 routes were added one at a time and stayed GREEN at
  `2/3/4/5/6/7 passed` (3.33/4.34/5.71/6.57/7.43/8.84s). Seven 1440 mirrors
  produced `14 passed` (16.24s).
- The initial PIN h2 seed was direct GREEN, `1 passed` (2.12s). Keyboard-locked
  1024 produced `2 passed` (3.25s); both states at both viewports produced
  `4 passed` (4.94s).
- Static coverage checks exact h1/h2 scope, browser-computed accessible names,
  no nested interactive elements, no positive tabindex, exact navigation
  `aria-current`, 44x44 actions, overflow, focus outlines, and retained
  reduced-motion CSS.

## Minimal product repair summary

- `review.mjs`: restore the owning Review action after generic save failure;
  retain the existing polite live node across a successful refreshed editor;
  keep it connected before the success mutation; restore focus to the
  corresponding refreshed save action.
- `management.mjs`: restore the still-connected child/duck state launcher only
  after terminal failure; restore the correct manual/auto roster submit after
  terminal failure, without changing success focus behavior.
- `dirty-guard.mjs`: explicitly name the modal, focus `继续编辑`, and restore
  the original connected trigger after cancel/continue.

Endpoint paths, methods, strict DTO validation, fixed user copy, idempotency,
dirty-state, abort/race ownership, and success reload contracts were preserved.

## Final serial verification

All pytest commands below used the safety procedure and had the exact unchanged
snapshot line above before and after.

| Gate | Exact result |
| --- | --- |
| `DISABLE_EXTERNAL_AI=1 ./.venv/bin/python -m pytest -q tests/browser/test_teacher_failure_paths.py` | Initial: `58 passed, 1 warning in 63.30s`; post-repair: `58 passed, 1 warning in 64.01s`; final after Review GO: `58 passed, 1 warning in 63.85s` |
| `DISABLE_EXTERNAL_AI=1 ./.venv/bin/python -m pytest -q tests/browser/test_teacher_accessibility.py` | Unit 6: `22 passed, 1 warning in 24.89s`; Unit 7: `22 passed, 1 warning in 25.68s`; post-repair: `22 passed, 1 warning in 25.55s`; final after Review GO: `22 passed, 1 warning in 25.70s` |
| `DISABLE_EXTERNAL_AI=1 ./.venv/bin/python -m pytest -q tests/browser/test_teacher_lock.py tests/browser/test_teacher_today.py` | `90 passed, 1 warning in 93.67s` |
| `DISABLE_EXTERNAL_AI=1 ./.venv/bin/python -m pytest -q tests/browser/test_teacher_routing.py tests/browser/test_teacher_review_loading.py` | Initial: `52 passed, 1 warning in 56.05s`; post-review repair: `52 passed, 1 warning in 56.85s` |
| `DISABLE_EXTERNAL_AI=1 ./.venv/bin/python -m pytest -q tests/browser/test_teacher_review_editing.py` | Initial: `50 passed, 1 warning in 53.61s`; post-review repair: `50 passed, 1 warning in 54.35s` |
| `DISABLE_EXTERNAL_AI=1 ./.venv/bin/python -m pytest -q tests/browser/test_teacher_management.py tests/browser/test_teacher_reports.py` | Initial: `28 passed, 1 warning in 31.08s`; post-review repair: `28 passed, 1 warning in 30.85s` |
| Six Teacher Node suites with `node --test --test-concurrency=1` | `47 passed, 0 failed` |
| Separate `node --check` for the three changed modules | all exit 0 |
| Frozen policy `rg` scan | no matches, expected exit 1 |
| `git diff --check` | exit 0 |

The sole warning in browser invocations is the existing Starlette TestClient
deprecation warning; it is not a Task 8 functional failure.

## Historical safety incidents carried forward

1. **Pipeline Task 8 provider incident.** Before the permanent lowest-level
   breaker existed, two synthetic-only DeepSeek calls returned HTTP 200 at
   `2026-08-23 22:59:31 +08` and `22:59:44 +08`. The test used temporary SQLite
   and no real child/application data. Permanent prevention is the autouse
   `_llm` breaker plus high-level fakes. Source: reliable-conversation-pipeline
   `task-8-report.md`.
2. **Child Task 9 real-log incident.** A pre-remediation fault run reached 55
   passing nodes, then an asyncio pending-route teardown error reached the real
   `logs/app.log` at `2026-08-27 19:33:50` Asia/Shanghai through a parent real
   FileHandler. The bytes were preserved, not reverted. Permanent prevention is
   the browser parent logging guard plus byte comparison. Source:
   child-interaction-recovery `task-9-report.md`.
3. **Teacher Task 5/5A real-log incident.** An orchestration batch overlapped a
   non-browser Review pytest with two browser suites; the non-browser TestClient
   FileHandler wrote preserved test records to the real log. Task 5A isolated
   shared pytest logging at `5fbd06127f695588336299b1e5168f79d91b2685`.
   Permanent prevention is strict serial execution plus disposable logs and
   session resource guards. Sources: Teacher `task-5-report.md` and
   `task-5a-log-isolation-report.md`.

Task 8 produced no recurrence of any incident.

## P0/P1/P2 disposition and limitations

- P0: 0 open in the frozen Task 8 contract and implementation evidence.
- P1: 0 open in the frozen Task 8 contract and implementation evidence.
- P2: focus visibility is behaviorally covered, but `#ffb800` against light
  surfaces has not been proven to meet the 3:1 non-text contrast requirement.
  Task 9 must measure and disposition it; Task 8 does not silently change the
  brand focus color without a focused failing contract.
- Task 8 contributes evidence only to mandatory gates 3, 11, 12, 13, and 14.
  It does not independently satisfy the other nine release gates.
- Task 8 cannot accept the preserved historical release risk on the user's
  behalf. Final Task 9 must inventory current real suites, lowest-level provider
  isolation, logical SQLite digest, all 14 mandatory gates, all three incidents,
  and explicit reviewer/user risk disposition.

## Independent-review handoff

The first exact staged-diff review returned contract/code NO-GO and
safety/stage PASS: P0=0, P1=2, P2=1. It challenged the live-region connectivity
assumption and found the timeout-wrapper and success-focus issues documented
above. The fresh second review approved Contract, Code, and Safety/Stage with
P0=0, P1=0, P2=1. It independently re-challenged whether the two-hop retained
status move could detach the node and confirmed that both parents are connected
before the success write. The only retained P2 is the reported focus-color
contrast measurement for Task 9. The final complete owned-file runs after that
GO were `58 passed` and `22 passed` with exact unchanged resource snapshots.
This is a reviewed pre-commit Task 8 handoff, not release GO.
