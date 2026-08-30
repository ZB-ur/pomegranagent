# Teacher Task 9 Brief — Final Cross-Surface Acceptance and Honest Release Decision

## Contract status and exact start boundary

- **Status: IMPLEMENTATION NOT AUTHORIZED.** This document must receive an
  independent Contract GO before any Task 9 test, product, runner, artifact, or
  report file is changed.
- Exact required start HEAD:
  `89b3459973bb7cd6e8be43b1251ac6cdb5dfa292`.
- Resume in the existing `master` checkout. Do not create a worktree, replay a
  completed task, amend a prior commit, or reinterpret an older plan sample as
  authority.
- The initial release decision is **NO-GO**. A full fresh run may establish a
  technical pass, but neither an agent nor the runner may sign historical risk
  acceptance or a Lovable scope waiver on the user's behalf.
- This brief supersedes only the old Teacher Task 9 section. Foundation,
  Pipeline, Child, and Teacher Tasks 1–8 remain frozen dependencies.
- For Task 9 only, this exact HEAD also supersedes the stale initial resume HEAD
  at the top of `progress.md`; the latest Task 8/9 ledger entries remain factual.

### Universal clean-exec boundary

Before any Task 9 Git, Node, Python, pytest, syntax, policy, runner, or browser
subprocess, use this exact argv prefix; it is an argv list, not a shell string:

```text
/usr/bin/env
-i
PATH=/Users/lddmay/AiCoding/pomegranagent/.venv/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin
HOME=/Users/lddmay
LANG=C.UTF-8
LC_ALL=C.UTF-8
TMPDIR=/tmp
TZ=Asia/Shanghai
DISABLE_EXTERNAL_AI=1
PYTHONNOUSERSITE=1
PYTHON_DOTENV_DISABLED=1
```

`<CLEAN_ENV>` below means exactly that ordered prefix. Every apparently bare
command block in this brief is invalid unless executed with this prefix. The
launcher uses `shell=False` where it controls subprocess construction; manual
tool invocations pass the prefix as the first argv tokens. No login shell or
wrapper script may rehydrate the parent environment. Only the listed neutral
values cross the boundary; `APP_DB_*` is set later only by the disposable test
fixtures. The orchestrator may compare and record rejected parent variable
**names**, including any name containing `TOKEN`, `KEY`, `PROVIDER`, or `PROXY`,
but must never read, expand, print, hash, or persist their values.

The launcher-produced mapping remains exactly those nine explicit keys. On
Darwin, CoreFoundation may synthesize the child-visible key
`__CF_USER_TEXT_ENCODING` after exec even when `/usr/bin/env -i` did not pass it.
This is the sole platform exception: it is never copied from `parent_env`, its
value is never read, printed, hashed, persisted, or asserted, and it is excluded
from the runner's sanitized mapping. A Darwin child key-only probe accepts
exactly either `explicit_nine` or
`explicit_nine ∪ {__CF_USER_TEXT_ENCODING}`; a non-Darwin probe accepts only
the explicit nine. Any other added or missing key still fails before all
repository work. Tests separately assert the `env` argv itself contains only
the explicit nine assignments and use a hostile parent Mapping whose
`__CF_USER_TEXT_ENCODING` value accessor raises if touched; sanitized mapping
construction must exclude the key without reading its value. Thus the platform
exception cannot widen the launcher allow-list or cause a value access.

This boundary exists before the runner and therefore also governs the initial
preflight and genuine RED commands. Unit 0 first launches one clean Python probe
that prints only its sorted environment key names and applies the exact
platform-aware set rule above. It then runs, as three separate `<CLEAN_ENV>`
commands:

```bash
<CLEAN_ENV> /opt/homebrew/bin/git rev-parse HEAD
<CLEAN_ENV> /opt/homebrew/bin/git status --short --untracked-files=all
<CLEAN_ENV> /opt/homebrew/bin/git diff --check
```

Stop if HEAD differs, if Task 9 already has staged files, or if any inherited
user path has changed unexpectedly.

## Non-negotiable user and safety boundary

Preserve, never edit, never stage, and never restore these inherited paths:

```text
.workbuddy/memory/2026-08-22.md
docs/superpowers/specs/2026-08-23-interaction-stabilization-design.md
.superpowers/brainstorm/
docs/superpowers/plans/
```

No Task 9 top-level orchestration, including pre-runner TDD, may:

- contact an AI/TTS provider or any non-loopback service;
- inherit provider keys, API keys, tokens, or proxy configuration;
- run any Playwright/browser/package download or non-dry-run installer; the
  existing read-only `python -m playwright install --dry-run chromium` browser
  gate remains required;
- run two top-level pytest, Node, runner, or other execution commands at once;
- start the real application service, analysis worker, screenshot script, seed
  script, or demo-database rebuild command;
- write, restore, truncate, rotate, or delete the real application database,
  `logs/app.log`, or `data/tts_cache`;
- turn a failed command, skipped test, zero collection, timeout, resource drift,
  missing evidence, or unresolved decision into a warning.

All top-level pytest and Node execution is strictly serial. A subprocess must finish and
its before/after resource snapshot must be verified before the next subprocess
is created. A resource drift or tripwire hit stops the run immediately; do not
continue to collect prettier evidence and do not rewrite the resource.

Audited tests may synchronously own nested children within their one top-level
command: `tests/test_database_safety.py` starts disposable pytest subprocesses,
the hostile speech Node test starts one child Node process, and the browser
fixture owns one loopback server plus Chromium. Those children must finish before
their parent test finishes; they do not authorize concurrent runner commands.

## Exact ownership and staged allow-list

Task 9 owns exactly:

```text
Create  scripts/run_interaction_acceptance.py
Create  tests/test_interaction_acceptance_runner.py
Create  tests/browser/test_release_viewports.py
Modify  tests/frontend/shared/api-client.test.mjs
Modify  tests/conftest.py
Modify  tests/test_database_safety.py
Modify  tests/browser/test_child_faults.py
Modify  tests/browser/test_teacher_today.py
Modify  tests/browser/test_teacher_review_loading.py
Modify  .gitignore
Create  .superpowers/sdd/2026-08-23-teacher-workbench-and-acceptance/task-9-brief.md
Create  .superpowers/sdd/2026-08-23-teacher-workbench-and-acceptance/task-9-report.md
```

The evidence-only second commit owns exactly:

```text
Generate docs/interaction-acceptance-report.md
Update   .superpowers/sdd/2026-08-23-teacher-workbench-and-acceptance/task-9-report.md
```

The following ownership is conditional and becomes active only after the exact
focus-contrast browser selector records a genuine RED below 3:1:

```text
Modify  app/frontend/teacher/styles.css
Modify  tests/browser/test_teacher_accessibility.py
```

The following ownership is conditional and became active only after the
independently reviewed Unit 7.6 ordered browser RED (`431/432` full-suite and
`1 passed, 1 failed` minimal order proof) showed that the session-scoped
Playwright sync loop makes the existing main-thread `asyncio.run` invalid:

```text
Modify  tests/browser/test_child_shell.py
```

That amendment owns only
`test_edge_tts_fake_stream_trips_before_network` plus the smallest same-file
stdlib import/helper required to create and run its coroutine inside one
synchronously joined isolated worker thread. It must preserve the node ID,
`FakeCommunicate.stream` boundary, exact expected `AssertionError`, and exact
`edge_tts blocked\n` tripwire evidence. It does not authorize a global loop
monkeypatch, loop close, collection reorder, skip/xfail, command split, new
node, CommandSpec, or manifest row.

The existing four viewport suites remain authoritative. Do not create a second
copy of the Child or Teacher keyboard/fault matrices. The only Child-suite edits
are three exact rows in `tests/browser/test_child_faults.py`: first-chat
`10_000 ms` timeout, completion-delay single-flight, and a page-keyboard-only
welcome-to-safe-save core flow. They must reuse the existing controlled clock,
draft, request-ID, no-fake-copy, TTS, completion, and route-cleanup fixtures. The
only Today-suite edit is one exact row that renders pending, processing, and
failed cards together and proves retry belongs only to the failed card. These
four rows are acceptance-evidence gaps, not authorization to change Child or
Today product code; if any records a genuine product RED outside Task 9
ownership, stop for a separate owning repair contract. The new release viewport
file owns only the missing cross-surface evidence: focus-indicator contrast and
a real browser management action followed by a read-only assertion against the
disposable browser SQLite database.

No backend model, route, schema, child/teacher module other than the conditional
CSS, approved test safety files, existing browser suite, or product data file is in
scope. If a fresh gate exposes a defect outside this allow-list, stop with the
failing evidence and create a separate owning repair contract.

## Current known blockers that must not be hidden

1. `tests/frontend/shared/api-client.test.mjs` still extracts an inline script
   from `teacher.html`; the Teacher shell now uses external module
   `/teacher/app.js`. The current Node suite therefore fails before testing the
   shared API client.
2. Teacher focus outline `#ffb800` has measured contrast ratios of only
   `1.734:1` against `#ffffff`, `1.604:1` against `#f5f6f8`, `1.662:1` against
   `#fafafa`, and `1.401:1` against `#e5e7eb`. This is a specification failure,
   not an unmeasured warning.
3. The private Lovable project
   `9d5fe2e4-6910-4c89-a078-c378f7fdc63f` is only a blank bootstrap. The
   implementation message was rejected for zero credits; there is no reviewed
   two-screen prototype and no `docs/lovable/prototype-reference.md`.
4. Three historical safety incidents remain part of the release record and
   require an explicit release-owner disposition. Later green tests do not erase
   them.
5. Existing `docs/acceptance-report.md` predates stabilization and must be named
   as superseded. It is not current release evidence.

## Frozen safe command inventory

Every command below is the exact command tail appended to the universal
`<CLEAN_ENV>` prefix. `<CLEAN_ENV>` is notation in this document, not a literal
executable name; the actual argv contains the ordered `/usr/bin/env -i ...`
tokens frozen above.

### Authoritative CommandSpec IDs and timeout seconds

Timeouts use integer wall-clock **seconds**. This table is the sole authority;
`build_command_specs()` must produce exactly these IDs and values, reject every
missing, extra, or duplicate ID, and may not accept a CLI timeout override. Unit
6 `*_1024` IDs select the named 1024 parameter only; `*_all` IDs select the same
named function at both frozen viewports. Every pytest ID writes a unique JUnit
path derived from its CommandSpec ID.

| CommandSpec ID | Frozen command scope | Timeout seconds |
|---|---|---:|
| `runner` | pure runner unit file | 300 |
| `lovable` | pure Lovable artifact file | 120 |
| `backend` | complete explicit Backend/Foundation/Pipeline/E2E command | 900 |
| `browser` | complete `tests/browser` command | 1800 |
| `shared_node` | shared API-client TAP command | 300 |
| `child_node` | sorted Child TAP command | 600 |
| `teacher_node` | sorted Teacher TAP command | 300 |
| `release_focus_1024` | release focus selector, `1024x768` | 120 |
| `release_focus_all` | release focus selector, both Teacher viewports | 180 |
| `teacher_accessibility_full` | complete Teacher accessibility file | 300 |
| `release_db_action_1024` | disposable-SQLite action selector, `1024x768` | 120 |
| `release_db_action_all` | disposable-SQLite action selector, both Teacher viewports | 180 |
| `review_identity_1024` | Review identity/time/ID/status selector, `1024x768` | 120 |
| `review_identity_all` | Review identity/time/ID/status selector, both Teacher viewports | 180 |
| `child_chat_timeout_1024` | first-chat timeout selector, `1024x576` | 120 |
| `child_chat_timeout_all` | first-chat timeout selector, both Child viewports | 180 |
| `child_completion_delay_1024` | completion-delay selector, `1024x576` | 120 |
| `child_completion_delay_all` | completion-delay selector, both Child viewports | 180 |
| `child_keyboard_core_1024` | Child keyboard core selector, `1024x576` | 180 |
| `child_keyboard_core_all` | Child keyboard core selector, both Child viewports | 240 |
| `today_three_status_1024` | Today three-status selector, `1024x768` | 120 |
| `today_three_status_all` | Today three-status selector, both Teacher viewports | 180 |

Production execution uses `subprocess.Popen(..., shell=False,
start_new_session=True, stdout=PIPE, stderr=PIPE)` plus
`communicate(timeout=spec.timeout_seconds)`. The runner captures the command's
PGID as the `start_new_session=True` child leader PID, without a fallible
post-spawn `getpgid` lookup. Whole-group liveness is checked with
`killpg(pgid, 0)`; only `ESRCH` means extinct.

Every probe, TERM, and KILL syscall is total at the runner boundary. A
non-`ESRCH` `OSError`, including `PermissionError`, is never treated as
extinction and never escapes the runner. Cleanup continues only within the same
bounded TERM/KILL deadlines. If extinction remains unproven, the stable result
is `SAFETY_FAILURE/PROCESS_CLEANUP_INCOMPLETE` with `GROUP_SURVIVED`, a null
after snapshot, exit `3`, and no later command or resource snapshot while the
owned group may still be live.

If the original `communicate()` returns before its deadline, the runner records
the leader's integer return code and complete pipes, then checks the PGID before
any after snapshot. A still-live group is `RESIDUAL_PROCESS_GROUP`, even when
the leader exited normally or by a spontaneous signal and descendants closed
their stdio; `residual_group_observed=true` remains immutable evidence even if
cleanup later succeeds. The runner sends TERM to that group, polls every 50 ms for at most
5 seconds, sends KILL if it remains, and polls for at most 5 more seconds. Even
if this cleanup succeeds, the command is `SAFETY_FAILURE`, no later command
starts, and the after snapshot is taken only after group extinction. If cleanup
does not prove extinction, `cleanup_failures` contains `GROUP_SURVIVED`, the
after snapshot is null, and exit is safety `3`.

If the original deadline expires, the runner sends `SIGTERM` to the entire
PGID and calls `communicate(timeout=5)` to drain pipes. If that communicate
times out or the PGID remains, it sends `SIGKILL` to the PGID and starts one
final 5-second cleanup deadline. Both final pipe drain/leader reap and PGID
extinction must finish inside that same deadline: `communicate(timeout=remaining)`
uses its remaining portion, followed by 50 ms liveness polls using only what
remains. The complete stdout/stderr are exactly the buffers returned by the
last successful `communicate()`; partial buffers attached to earlier
`TimeoutExpired` exceptions are never concatenated and cannot duplicate output.
Only after complete drain/reap **and** PGID `ESRCH` may the runner take the after
snapshot. If any part is unproven at the deadline, it records
`output_complete=false`, `child_exit=proc.poll()` (integer or null),
`after_snapshot=null`, `SAFETY_FAILURE/PROCESS_CLEANUP_INCOMPLETE`, starts no
later command, and exits safety `3`. Its canonical, de-duplicated
`cleanup_failures` tuple is ordered as `PIPE_DRAIN_TIMEOUT`, `LEADER_UNREAPED`,
`GROUP_SURVIVED` and contains every applicable reason: final communicate did
not finish; `proc.poll()` is null; and PGID is not `ESRCH`, respectively. If a
final `communicate()` succeeded, its newest complete stdout/stderr buffers are
written once even when only PGID liveness later fails. Otherwise the raw logs
are the latest `TimeoutExpired.output` and `.stderr` partial byte buffers written
once. Both incomplete-cleanup cases are explicitly marked non-parseable suite
evidence and never merge buffers from different attempts.

At the full-run orchestration boundary, a returned command with
`output_complete=false`, a null after snapshot, or any `cleanup_failures` is
appended once and causes an immediate `SAFETY_NO_GO`, exit `3`. While that owned
group may still be live the runner performs no JUnit stat/read/copy/unlink, no
final resource capture, no `resources.after` write, no completed report, and no
later command start.

The production stream writer owns only the two raw stdout/stderr log writes; it
does not stat, read, copy, or unlink JUnit. The full-run complete branch performs
the first JUnit filesystem operation only after complete pipe drain/reap,
proven PGID extinction, an empty cleanup-failure tuple, and a nonnull after
snapshot. Tests exercise the production writer itself, not only a fake writer,
across timeout and residual probe/TERM/KILL `PermissionError`; those incomplete
paths may preserve raw logs but perform zero JUnit filesystem operations. A
normal complete path retains the exact ordered JUnit name, bytes, size, and
SHA-256.

Tests inject an executor with the same observable PGID/start/communicate/
terminate/kill/reap/liveness contract. They prove: clean normal exit; normal or
spontaneously signaled leader exit while a descendant closes stdio but survives;
TERM cleanup after timeout; a leader that exits while a descendant ignores TERM;
KILL escalation; a KILL-surviving member that holds a pipe; an unreaped leader;
complete nonduplicated output written after the deadline; final group extinction
before the after snapshot; `PermissionError` at probe/TERM/KILL in both timeout
and residual paths; and absence of a later command start.

### Pure runner unit tests — no project conftest

```bash
<CLEAN_ENV> /Users/lddmay/AiCoding/pomegranagent/.venv/bin/python -m pytest \
  -p scripts.run_interaction_acceptance --capture=sys --noconftest -q \
  -o xfail_strict=true \
  --junitxml=<artifact-root>/runner.junit.xml \
  tests/test_interaction_acceptance_runner.py
```

The runner test must be standard-library-only apart from pytest. Authenticated
parser vectors call a runner-owned offline signer that generates an independent
key and never reads or exposes the live producer state/capability; the test file
does not import the signing library. It may create temporary SQLite/log/TTS/git
fixtures, but it must not import application modules, connect to the application
database, or start a service.

### Pure Lovable artifact tests — no project conftest

```bash
<CLEAN_ENV> /Users/lddmay/AiCoding/pomegranagent/.venv/bin/python -m pytest \
  -p scripts.run_interaction_acceptance --capture=sys --noconftest -q \
  -o xfail_strict=true \
  --junitxml=<artifact-root>/lovable.junit.xml \
  tests/test_lovable_artifacts.py
```

This is the only documentation gate. Running it with normal `tests/conftest.py`
would violate the pure-document boundary.

### Backend, Foundation, Pipeline, and E2E — normal project conftest

Use one explicit command; do not target the whole `tests/` directory and do not
name nonexistent aggregate files:

```bash
<CLEAN_ENV> /Users/lddmay/AiCoding/pomegranagent/.venv/bin/python \
  -m pytest -p scripts.run_interaction_acceptance --capture=sys \
  -q -o xfail_strict=true \
  --junitxml=<artifact-root>/backend.junit.xml \
  tests/test_database_safety.py \
  tests/test_rebuild_demo_database.py \
  tests/test_runtime_health.py \
  tests/test_api_errors.py \
  tests/test_http_boundary.py \
  tests/test_teacher_auth.py \
  tests/test_frontend_foundation.py \
  tests/test_pipeline_models.py \
  tests/test_chat_idempotency.py \
  tests/test_conversation_completion.py \
  tests/test_analysis_worker.py \
  tests/test_roster_idempotency.py \
  tests/test_review_atomicity.py \
  tests/test_deactivation.py \
  tests/test_conversation_history.py \
  tests/test_api.py \
  tests/e2e.py
```

`tests/e2e.py` is a pytest target. Running it as `python tests/e2e.py` is a false
green because it executes no tests.

### Browser — normal browser/project conftests

```bash
<CLEAN_ENV> /Users/lddmay/AiCoding/pomegranagent/.venv/bin/python \
  -m pytest -p scripts.run_interaction_acceptance --capture=sys \
  -q -o xfail_strict=true \
  --junitxml=<artifact-root>/browser.junit.xml tests/browser
```

This command must retain the existing Playwright 1.62.0 / Chromium revision 1234
dry-run gate, disposable loopback Uvicorn runtime, non-starting worker, provider,
TTS, socket and context-egress tripwires, logical SQLite guard, parent log guard,
and real TTS-cache guard. It may not use `--noconftest`, skip a missing browser,
or install one.

Authorized project-conftest provider/TTS/network breakers use the single stable
destination-free prefix `TEST_TRIPWIRE:`. The project conftest authenticates an
actually raised breaker from its exception identity/message and exact trusted
final traceback frame, then emits one canonical `task9.tripwire_event` JUnit
testcase property. Browser-child and browser-fixture breakers are authenticated
from their exact exception type/message and known `tests/browser/child_server.py`
or `tests/browser/conftest.py` final frame. The property stores only the event
ID, exception type, and trusted frame; a network destination is never stored.
The seven ordered IDs are `external_ai`, `edge_tts`, `external_network`,
`browser_edge_tts`, `browser_ai`, `browser_network`, and `browser_file`.
A source-code line, comment, raw stdout/stderr marker, ordinary assertion, or
self-test that catches its breaker is not an event. The ordinary word
`tripwire` is never enough.

Top-level tripwire state, internal evidence, gates, and decision are one derived
state: any structured event is `FAIL`; otherwise valid complete browser evidence
is `PASS`; otherwise it is `NOT_PROVEN`. Caller edits to any copy are rejected.
For completed rendering, each JUnit file is first verified against its recorded
regular-file type, size, and SHA-256, then its canonical property, failure/error
message, source definition, and trusted final traceback frame are parsed again.
The command event list and every derived copy must equal those hash-verified
JUnit facts. Missing/tampered/rehashed-substituted JUnit, raw-log-only markers,
and caller edits reject the artifact; raw prose and stdout/stderr are never
tripwire evidence authority.

#### Cooperative same-process TCB and authenticated-event lifecycle

This normative amendment supersedes the sixth-review requirement that Task 9
authentication material be unavailable to repository test code. The Task 9
runner/verifier, authorized breakers, early pytest plugin, project conftest,
browser-child reporting, every repository test, and every imported application,
plugin, and library module form one cooperative same-process trusted computing
base (TCB). TCB code is non-adversarial with respect to private Task 9 state and
interfaces: it must not deliberately reflect, enumerate, reuse, or forge a
private capability. `Private` is a contract boundary, not operating-system
isolation. Authenticated therefore means TCB-originated and
capability-validated, robust against ordinary raw output, `record_property`, a
compiled fake/lookalike, a caught breaker, malformed or stale data, artifact
tampering, and caller edits. It does not promise cryptographic resistance to
malicious code executing in the pytest process. If hostile repository code
enters scope, a future external supervisor or kernel-isolated design is
required; that design is not Task 9 Commit A.

For every pytest command the runner establishes a private command-local
capability without adding an environment key, exposing a secret in argv or
JUnit, or creating a new repository/artifact path. An explicit early plugin is
installed before project conftest, test, application, plugin, or library import
and before collection. The live producer validates that command-local
capability together with the exact exception-class identity, exact message, and
exact trusted code object/final traceback frame before it serializes an event.
This covers `socket.connect` and `socket.connect_ex`, and import, collection,
setup, call, and teardown phases.

Producer state binds each accepted record to its command, testcase node or
synthetic import/collection scope, phase, and monotonically increasing sequence.
The JUnit property payload remains limited to event ID, exception type, and
trusted frame, and never stores a network destination; command, node/synthetic
scope, phase, and sequence are authenticated by the command-local producer and
the captured JUnit context/order. Accepted events form a monotonic union:
malformed, conflicting, or duplicate data cannot erase a valid event; an exact
valid duplicate is idempotent; and node/command attribution is fresh, never
carried from an earlier test or command.

Both `run-one` and the full runner parse and merge authenticated events after
every child exit, including nonzero exits, before making a technical or safety
decision. Any valid event makes tripwire state `FAIL`, even when malformed data
is present beside it. With no valid event, missing, malformed, or
integrity-invalid evidence is `NOT_PROVEN` and rejects the run; it never becomes
`PASS`. The runner hashes and parses the same captured bytes, and completed
rendering verifies and parses those same recorded bytes again.

Pure parser tests may create independent signed offline vectors through the
runner-owned helper. Those vectors own a fresh unrelated key and do not access,
reflect, reuse, or expose the live per-command producer capability; they cannot
authenticate a live command event.

### Node — expanded sorted paths, no shell glob in runner evidence

Human-readable equivalents are:

```bash
<CLEAN_ENV> /opt/homebrew/bin/node --unhandled-rejections=strict --test --test-concurrency=1 --test-reporter=tap tests/frontend/shared/api-client.test.mjs
<CLEAN_ENV> /opt/homebrew/bin/node --unhandled-rejections=strict --test --test-concurrency=1 --test-reporter=tap tests/frontend/child/*.test.mjs
<CLEAN_ENV> /opt/homebrew/bin/node --unhandled-rejections=strict --test --test-concurrency=1 --test-reporter=tap tests/frontend/teacher/*.test.mjs
```

The `<artifact-root>` tokens above are replaced with unique absolute paths by
the runner; they are not passed literally. The runner expands Child and Teacher
paths with sorted `Path.glob()` and records
each path as a separate argv item. It must not invoke a shell.

### Explicitly forbidden targets

Do not run or include:

```text
tests/seed_demo_assessments.py
tests/screenshot.py
tests/process_ip_images.py
scripts/rebuild_demo_database.py --confirm-rebuild against real `data/`
tests/test_runtime_foundation.py
tests/test_conversation_pipeline.py
```

`tests/test_rebuild_demo_database.py` remains required because it uses an
injected temporary engine/path. Only the real rebuild CLI and real data target
are forbidden.

## Shared API-client migration contract

The shared Node file owns `app/frontend/shared/api.js`; it must not execute a
stale copy of Teacher application code.

1. First run the exact current shared Node command and record its genuine
   top-level failure from the missing inline `<script>` match.
2. Remove `teacherHtml`, `teacherSource`, `loadTeacherWithPendingGates`, and only
   the three Teacher-specific tests that depend on that obsolete inline harness.
3. Preserve and run every shared API test for sequence cancellation, caller
   abort versus timeout, version mismatch, one-shot gate promise, failed-gate
   reuse, state writes, and runtime events.
4. Do not claim coverage loss as success. The runner evidence map must include
   these current owning equivalents:
   - `tests/test_frontend_foundation.py::test_teacher_navigation_is_blocked_until_runtime_ready`
   - `tests/test_frontend_foundation.py::test_teacher_navigation_requires_both_runtime_and_authentication_and_can_relock`
   - `tests/browser/test_teacher_lock.py::test_teacher_locked_bootstrap_makes_only_runtime_and_auth_requests`
   - `tests/browser/test_teacher_lock.py::test_teacher_runtime_failure_keeps_maintenance_and_makes_zero_auth_or_business_requests`
   - `tests/browser/test_teacher_lock.py::test_teacher_auth_status_failure_is_safe_and_makes_zero_business_requests`
5. Run the shared Node command twice. It must report a nonzero number of tests,
   zero failure, zero skip, zero todo, zero cancel, and no unhandled rejection.

## Focus contrast and release viewport contract

The WCAG contrast function is frozen:

```text
sRGB channel c := c/12.92 when c <= 0.04045,
                  ((c+0.055)/1.055)^2.4 otherwise
relative luminance := 0.2126R + 0.7152G + 0.0722B
contrast := (lighter + 0.05) / (darker + 0.05)
```

The first browser RED reaches routes by keyboard and focuses representative
route `h1[tabindex="-1"]`, dialog target/return control, native button, link,
input, select, textarea, nav button, primary blue button, gray button, and
white-panel control at both Teacher viewports `1024x768` and `1440x900`. It reads computed
styles and the nearest nontransparent element/surrounding backgrounds. It must
prove that the existing single `#ffb800` ring falls below 3:1 on at least one
real surface.

The minimal product repair is a two-tone, nontransparent focus indicator with
both rings at least 3 CSS pixels in the relevant dimension. For each adjacent
background, at least one of the two computed ring colors must have contrast
`>= 3.0`; the test also requires both colors to be present, visibly different,
and the focus rectangle to remain inside the viewport without clipping.

The repair may only change the common `:focus-visible` rule in
`app/frontend/teacher/styles.css` and the existing Task 8 structural assertion
if necessary. The common selector must explicitly cover programmatically focused
route `h1/h2[tabindex="-1"]`; it must not redesign brand colors, layout,
typography, or motion.
After GREEN, rerun the complete Teacher accessibility file at both viewports.

`tests/browser/test_release_viewports.py` also performs one real authenticated
Teacher management action at both Teacher viewports against the disposable
loopback server. The test obtains the database path only as
`Path(teacher_browser.server.environment["APP_DB_PATH"]).resolve()`, asserts it
equals `(teacher_browser.server.runtime_dir / "browser-app.db").resolve()`, and
then opens that path by SQLite URI `mode=ro` to assert the expected persisted row
by stable business value. It must never read the parent pytest
`os.environ["APP_DB_PATH"]`. It must:

- reach the action through visible keyboard/mouse controls, not an internal JS
  method or direct HTTP request;
- prove the request completed and the UI announced the result;
- inspect only the disposable `browser-app.db`, never the application DB;
- prove the browser DB path is outside the repository `data/` directory;
- use one collision-resistant synthetic business name and prove a read-only
  query changes from exactly `0` rows before the visible action to exactly `1`
  row after it, without mutating from the test process;
- leave the existing fixture resource/tripwire teardown intact.

The existing Child fault/shell tests remain the authoritative `1024x576` and
`1280x720` viewport evidence. The existing Teacher Task 8 tests remain the
authoritative `1024x768` and `1440x900` keyboard/fault evidence. The new file
must not duplicate those matrices.

### Four missing browser evidence rows

The four newly owned rows have frozen names and semantics:

1. `test_first_chat_timeout_retains_draft_and_reuses_request_id_once` at Child
   IDs `1024x576` and `1280x720`: hold the first `/api/chat`; at controlled
   `9_999 ms` it remains `submitting` with byte-identical durable/sessionStorage
   state, exactly one outstanding request, and zero retry/TTS/completion/success
   projection; cross `10_000 ms` and observe exactly one transition to
   `submission_failed` plus exactly one retry control, still with the exact
   durable text/request ID and zero fake reply/TTS/completion. A rapid real
   page-keyboard `Enter/Space/Enter` retry produces only one second request with
   byte-equivalent normalized text, the same body/header request ID, and no
   duplicate timeout transition.
2. `test_completion_delay_is_single_flight_and_saves_once` at those two IDs:
   reach `saving_conversation`, hold the exact completion route, exercise rapid
   Enter/Space/click-equivalent public actions without a second request, fulfill
   the one boundary request, and reach one completed projection with one
   analysis job acknowledgement.
3. `test_child_core_flow_is_page_keyboard_only_and_saves_once` at those two IDs:
   after navigation, every user action is `page.keyboard`; traverse welcome,
   child selection, Space recording, controlled final/silence turns, multi-round
   transcript, safe completion, and the completed exit control. Test-only speech
   and audio terminal events may be emitted through the existing controlled
   seams, but no mouse click or direct application method is permitted.
4. `test_teacher_today_renders_pending_processing_and_failed_rows_with_retry_boundaries`
   at Teacher IDs `1024x768` and `1440x900`: render all three nonempty queue DTOs
   together, assert visible child/time/conversation/status projections, prove
   only the failed row exposes retry, and prove retry single-flight refreshes
   failed, processing, then pending without cross-row identity drift.

Each row is test-first. A missing test is a genuine collection RED. If existing
product behavior does not make it GREEN within the exact Task 9 product
allow-list, the corresponding gate remains BLOCKED and Task 9 stops; the test is
not weakened or marked expected-failure.

## Runner public contract

`scripts/run_interaction_acceptance.py` is import-safe: importing it performs no
I/O, environment mutation, subprocess, logging configuration, or report write.
Its testable surface is:

```python
build_command_specs(repo_root, artifact_root) -> tuple[CommandSpec, ...]
build_sanitized_env(parent_env, *, browser: bool) -> dict[str, str]
logical_sqlite_digest(path) -> str
file_snapshot(path) -> FileSnapshot
directory_digest(path) -> str
capture_resources(repo_root) -> ResourceSnapshot
run_command(spec, *, env, executor) -> CommandResult
parse_pytest_junit(path) -> SuiteEvidence
parse_node_tap(text) -> SuiteEvidence
evaluate_gates(results, resources, evidence_map) -> tuple[GateResult, ...]
evaluate_technical_decision(...) -> TechnicalDecision
render_canonical_json(record) -> bytes
render_markdown(record) -> str
main(argv=None) -> int
```

Dataclasses/enums must reject unknown fields and invalid states in constructors
or validators. Dependency injection is limited to tests; production CLI paths
use the frozen `Popen` process-group executor, UTC clock, repository root, and
the frozen resource paths. `run_command` reads timeout seconds only from its
validated CommandSpec.

### Sanitized subprocess environment

Only neutral variables may be copied from the parent:

```text
PATH HOME LANG LC_ALL TMPDIR TZ SYSTEMROOT
```

The runner always sets:

```text
DISABLE_EXTERNAL_AI=1
PYTHONNOUSERSITE=1
PYTHON_DOTENV_DISABLED=1
```

It rejects or removes every key containing `DEEPSEEK`, `OPENAI`, `API_KEY`,
`TOKEN`, `PROVIDER`, `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, or `NO_PROXY`.
It does not load `.env`. Before importing `app.backend.ai_engine`,
`tests/conftest.py` also sets `PYTHON_DOTENV_DISABLED=1`; the nested subprocess
builder in `tests/test_database_safety.py` sets the same value. The pure runner
suite tests only the environment builder and never imports an application
module. The actual application-import sentinel belongs to
`tests/test_database_safety.py`: the parent pytest itself still starts with
`PYTHON_DOTENV_DISABLED=1`, then the test creates a temporary `app/backend` package
topology with empty temporary `__init__.py` files and a symlink named
`ai_engine.py` to the real source, places a `.env` containing only
`TASK9_DOTENV_SENTINEL=loaded` at the temporary package root, and writes a real
temporary `probe.py` at that same root. The child argv is exactly
`[sys.executable, str(probe_path)]`, `cwd` is that package root, and its
`PYTHONPATH` is exactly that root; it does not use `python -c`. Its import path
therefore contains the temporary package plus normal installed dependencies,
never the repository root. The probe imports temporary
`app.backend.ai_engine` before any monkeypatch and emits only a fixed
`sentinel_loaded=true|false` token. Before the nested-helper fix the marker must
load and print `true`; after adding `PYTHON_DOTENV_DISABLED=1` it must print
`false`. Either missing RED or missing GREEN fails the test. It must neither
locate, open, copy, print, nor compare the repository `.env`. Browser commands
may retain `HOME` solely to find the
already-provisioned Playwright cache; they receive no credential-bearing browser
profile.

### Resource snapshots

The real resource snapshot is captured before the first command, immediately
before and after every command, and after the final ignored artifact write:

- application SQLite: read-only URI `file:...?mode=ro`, `iterdump()`, UTF-8,
  SHA-256, plus `lstat` existence/type/mode/size/`mtime_ns` for the database and
  its exact `-wal` and `-shm` siblings; the database must be a regular nonsymlink
  file, and each present sidecar must also be a regular nonsymlink file. A
  missing/unreadable database or unreadable/symlink/special present sidecar is a
  preflight failure;
- `logs/app.log`: SHA-256, byte size, and `mtime_ns`; missing/unreadable log is a
  preflight failure;
- `data/tts_cache`: readable root-directory `lstat` type/mode/size/`mtime_ns`, SHA-256 of
  sorted relative POSIX path, file length, and file bytes, plus every entry's
  `lstat` type/mode/size/`mtime_ns`; symlink, unreadable entry, chmod, same-byte
  rewrite, missing/unreadable root, or directory-type change is a failure;
- inherited user paths: recursive `lstat` entry type, mode, size, `mtime_ns`,
  symlink target where applicable, and content digest. Directory entry names are
  sorted and included, so write-then-restore or metadata/type replacement cannot
  masquerade as preservation;
- Git HEAD and porcelain status bytes. During the clean-HEAD evidence run the
  ignored artifact directory may change, but porcelain must remain byte-identical.

The first complete snapshot is the one global baseline. That exact object is
passed into every `run_command`; each command's stored before **and** after
snapshot must equal the global baseline. A self-consistent later `B/B` pair can
never replace baseline `A`, even if the final snapshot returns to `A`. Drift
observed immediately before the next command yields a not-started
`RESOURCE_DRIFT`, exit `3`, and zero child starts for that command.

The SQLite digest must see WAL-visible data. Raw database-file SHA is prohibited
as a business-data equality test, but physical database/WAL/SHM metadata is a
separate write detector and is mandatory. Every command attempt that establishes
a baseline stores its exact before/after snapshot, except any
`PROCESS_CLEANUP_INCOMPLETE` result stores the exact before snapshot plus an
explicit null after snapshot and is immediately `SAFETY_NO_GO`. Any observed
mismatch stops execution and records `SAFETY_NO_GO`.

Every canonical directory snapshot carries paired nullable `scan_error` and
`scan_source` fields in addition to its root, ordered entries, digest, and
reasons. A root `lstat`/read failure is
`DIRECTORY_ROOT_UNREADABLE`; an ordinary file, symlink, or special root is
`DIRECTORY_NOT_DIRECTORY`. A `scandir` failure retains the valid directory root
and every entry yielded before the failure and records the exact stable reason
`SCANDIR:<relative-source>:<exception-class>`; `.` denotes the root. Zero-entry
and partial-entry scan failures are therefore distinct. Capture and report
reconstruction use one semantic constructor to validate source attribution,
derive entry/scan reasons, and recompute the digest. A safe allowed-symlink
protected directory still round-trips, while any forged source, reason, or
digest fails closed.

The central unsafe predicate has identical behavior for runtime dataclass
snapshots and their canonical Mapping form. A nonnull pair is safe only when
both before and after have empty `unsafe_reasons` and are exactly equal. Any
unsafe before, unsafe after, or mismatch forces
`SAFETY_FAILURE/RESOURCE_DRIFT`, regardless of whether the underlying command
otherwise exited zero, failed evidence, was signaled, timed out, or had a
technical caller classification.

Canonical report validation recursively reconstructs the complete snapshot; a
placeholder such as `{token, unsafe_reasons}` is invalid. Every object has the
exact dataclass key set and field types. File kind controls the allowed metadata,
digest, symlink-target, and error combination; directory entries are sorted,
unique relative POSIX paths; protected paths are exactly the four frozen paths;
Git HEAD is null or a lowercase 40-hex hash; Git porcelain is null or an exact
SHA-256/size bytes descriptor. Database logical state plus physical
database/WAL/SHM, log, TTS root/entries/content, user paths, Git, and every
unsafe reason are therefore reconstructed rather than trusted as arbitrary
Mappings.

Reconstruction also recomputes semantics rather than trusting nested or
top-level digest/reason strings. It derives database physical and logical
safety, WAL/SHM/log protected-path reasons, the TTS and protected-directory
digest from exact root metadata plus ordered entries/content, user-path and Git
safety, and the exact ordered union of top-level unsafe reasons. Missing logical
database state with empty reasons, a nested unsafe object under a top-level safe
claim, or any supplied digest/reason mismatch is report-integrity failure. A
truthful unsafe snapshot remains renderable only as safety evidence.

After a baseline exists, `capture_resources` is total: disappearance,
unreadability, symlink/type replacement, or logical-digest failure is encoded as
an explicit unsafe state in a nonnull after snapshot and compares unequal; it is
never converted to an exception or a null after snapshot. Process-cleanup
incompleteness is the sole reason an established-baseline attempt may lack the
after snapshot, because observing resources while owned work may still run is
itself unsafe.

### Command results and artifacts

Commands use the synchronous process-group executor frozen in the authoritative
timeout table. Timeouts are explicit per CommandSpec; timeout, signal, negative
exit, nonzero exit, missing JUnit/TAP, zero tests, skip, xfail/xpass, todo,
cancel, parse error, or invalid UTF-8 all fail the command.

Every canonical `CommandResult` records separate, non-interchangeable fields:
`subcommand` is the frozen CommandSpec ID; `child_started` is a boolean;
`child_exit` is the exact final-reap integer exit code or `null` when no child
was reaped; `termination` is one of `NOT_STARTED`, `EXITED`,
`TIMED_OUT`, `SIGNALED`, or `SPAWN_FAILED`; and `classified_outcome` is one of
`SUCCESS`, `CHILD_NONZERO`, `TECHNICAL_FAILURE`, `SAFETY_FAILURE`, or
`CLI_MISUSE`. The runner process exit is recorded separately at the run level.
`output_complete` is `null` when no child started, `true` only when all child
pipes were drained and its PGID is extinct, and `false` when a started process
group could not be fully drained, reaped, and contained within the cleanup
deadline. `residual_group_observed` is true only when a normal/spontaneously
signaled leader finished before its deadline while its PGID remained live.
`cleanup_failures` is the canonical unique tuple drawn, in fixed order, from
`PIPE_DRAIN_TIMEOUT`, `LEADER_UNREAPED`, and `GROUP_SURVIVED`.
`before_snapshot` and `after_snapshot` are explicit nullable fields. When no
baseline can exist, both are null and the only legal combination is
`child_started=false`, `child_exit=null`, `termination=NOT_STARTED`,
`output_complete=null`, `residual_group_observed=false`, and empty
`cleanup_failures`; its reason is either `CLI_MISUSE` before resource I/O or
`RESOURCE_BASELINE_UNAVAILABLE` classified `SAFETY_FAILURE`. No technical
preflight is permitted before the baseline: HEAD/version and artifact/evidence
preparation are checked only after a complete before snapshot exists. When
`before_snapshot` is nonnull, `after_snapshot` is null **iff**
`output_complete=false` and `cleanup_failures` is nonempty, in which case the
only legal classification is `SAFETY_FAILURE` and execution stops. Every other
attempt with a baseline has a nonnull after snapshot.

The validator enforces these exact combinations before serialization:

- contained timeout: `child_started=true`, integer final-reap `child_exit`,
  `termination=TIMED_OUT`, `output_complete=true`, and
  `residual_group_observed=false`, empty `cleanup_failures`, and
  `classified_outcome=TECHNICAL_FAILURE` unless post-command resource drift
  upgrades it to `SAFETY_FAILURE`; TERM-handler exit `0`, `-SIGTERM`, and
  escalated `-SIGKILL` are all valid final-reap values while `TIMED_OUT`
  preserves the cause;
- uncontained timeout: `child_started=true`, integer-or-null `child_exit` from
  final `proc.poll()`, `termination=TIMED_OUT`, `output_complete=false`, null
  after snapshot, `residual_group_observed=false`, nonempty exact
  `cleanup_failures`, and
  `classified_outcome=SAFETY_FAILURE`; null `child_exit` requires
  `LEADER_UNREAPED`;
- spontaneous signal before the deadline: `child_started=true`,
  `child_exit<0`, `termination=SIGNALED`; when no residual group is observed it
  has `output_complete=true`, `residual_group_observed=false`, and empty
  `cleanup_failures`, with the same technical-to-safety override rule; a signal
  sent by timeout cleanup remains `TIMED_OUT`, never `SIGNALED`;
- normal return: `child_started=true`, integer `child_exit>=0`,
  `termination=EXITED`; when no residual group is observed it has
  `output_complete=true`, `residual_group_observed=false`, and empty
  `cleanup_failures`; zero may be `SUCCESS` or a later evidence-derived
  `TECHNICAL_FAILURE`, while positive is `CHILD_NONZERO` unless safety drift
  overrides it;
- any normally exited or spontaneously signaled leader whose PGID outlives it
  has `residual_group_observed=true` and is always `SAFETY_FAILURE`. If bounded
  cleanup proves extinction and its nonnull before/after pair is safe and
  unchanged, the reason is `RESIDUAL_PROCESS_GROUP`; any unsafe or unequal pair
  takes the higher-precedence reason `RESOURCE_DRIFT`. `output_complete=true`
  and an after snapshot with empty `cleanup_failures` are legal only after
  cleanup proves extinction, otherwise it has `output_complete=false`, a null
  after snapshot, and nonempty `cleanup_failures`;
- CLI misuse or unavailable baseline has the exact no-baseline combination
  above and is classified `CLI_MISUSE` or `SAFETY_FAILURE`, respectively;
- technical preflight refusal after a baseline: `child_started=false`,
  `child_exit=null`, `termination=NOT_STARTED`, `output_complete=null`,
  `residual_group_observed=false`, empty `cleanup_failures`, nonnull equal
  before/after snapshots, and `TECHNICAL_FAILURE` unless drift upgrades it to
  `SAFETY_FAILURE`;
- spawn failure: `child_started=false`, `child_exit=null`,
  `termination=SPAWN_FAILED`, `output_complete=null`, normally
  `residual_group_observed=false`, empty `cleanup_failures`, normally
  `TECHNICAL_FAILURE` but
  `SAFETY_FAILURE` when its established before/after snapshots drift.

For `termination=EXITED`, a positive child exit of `2`, `3`, or `64` therefore
remains `CHILD_NONZERO`; it can never be presented as the runner's
human-decision-pending, safety, or CLI classification merely because the
integers overlap. A numeric timeout-cleanup exit is classified from
`termination=TIMED_OUT`, not from that number. JSON, Markdown, and parser/golden
tests cover every valid combination above, reject every invalid cross-product,
and never infer classification from a shared number.

For `run-one`, arguments and the frozen `CommandSpec` ID are validated before
resource I/O; malformed CLI or an unknown ID returns `64` and starts no child.
It next establishes the complete protected-resource baseline; a missing,
unreadable, or unsafe resource produces `RESOURCE_BASELINE_UNAVAILABLE`, returns
`3`, and starts no child. Only after that baseline exists does it check frozen
HEAD/version and prepare artifacts/evidence; failure is technical, captures an
after snapshot, and returns `1` unless safety drift overrides it. Once a before snapshot
exists, every path—including technical preflight refusal, spawn failure, child
exit, timeout, signal, parser failure, and artifact failure—must either capture
an after snapshot or report incomplete process cleanup. **Any**
`classified_outcome=SAFETY_FAILURE` returns `3` with highest priority, including
resource/user-path/Git drift, a tripwire, cleaned `RESIDUAL_PROCESS_GROUP`, and
`PROCESS_CLEANUP_INCOMPLETE`; this overrides every
technical/preflight/spawn/child/evidence result. Child-code passthrough applies
only to `termination=EXITED && classified_outcome=CHILD_NONZERO`. With identical
resources, timeout, spontaneous signal/negative return code, parser/evidence
failure, spawn failure, or artifact-write failure returns `1`. Only
`termination=EXITED`, child exit `0`, valid evidence, identical resources, and
`classified_outcome=SUCCESS` returns `0`.

Persistent evidence lives only under ignored:

```text
artifacts/acceptance/<UTC-run-id>/
  report.json
  report.md
  resources.before.json
  resources.after.json
  commands/<order>-<id>.stdout.log
  commands/<order>-<id>.stderr.log
  commands/<order>-<id>.junit.xml
```

`report.json` is the canonical source. JSON uses UTF-8, sorted object keys,
stable array order, no NaN/Infinity, and one trailing newline. Markdown is a
pure one-way rendering of that in-memory record. Each command entry contains
the frozen `subcommand`, `child_started`, nullable exact `child_exit`, explicit
`termination`, nullable `output_complete`, `residual_group_observed`, canonical
`cleanup_failures`, explicit `classified_outcome`, nullable snapshots, and the
separate run-level process exit. Each log path, JUnit path, and the final
Markdown carries a SHA-256 in JSON.

Failure while writing or validating completed report artifacts is monotonic.
An already established tripwire, residual-process, unsafe-resource, or drift
safety decision remains `SAFETY_NO_GO`/exit `3`; the exact artifact write or
report-integrity reason is appended as secondary evidence, even if a later
resource capture returns to the baseline. Without any safety fact the artifact
failure remains technical/exit `1`. A failed completed report returns no report
record, and untrusted partial `report.json`/`report.md` files are discarded;
resource evidence and raw command logs are not represented as a completed
report.

Before `render-report` produces Markdown, it verifies the complete artifact tree
root and `commands/` directory are real nonsymlink directories; every referenced
stdout, stderr, JUnit, resource, and Markdown artifact has its exact fixed
relative path, is a real nonsymlink regular file, and matches its recorded byte
size and SHA-256. `resources.before.json` and `resources.after.json` must also
equal the canonical bytes of their reconstructed resource objects. Traversal,
absolute or substituted paths, missing files, symlinks, wrong types, extra root
or command files, wrong bytes, hashes, or sizes all fail closed before Markdown.
The renderer builds the canonical `SuiteEvidence` map once and binds every
entry to the same captured bytes that passed those checks: JUnit evidence is
reparsed from the verified XML plus verified stderr bytes, and TAP evidence is
reparsed from the verified stdout bytes. The complete reconstructed
`SuiteEvidence` must equal the canonical record, including validity, total and
all pass/nonpass counters, ordered unique node IDs, reason, structured
properties, and authenticated tripwire events. A JUnit artifact without its
suite entry, a suite entry without a corresponding command, or any zero,
missing, duplicate, substituted, skipped, xfailed, XPASS, todo, cancelled,
count, property, reason, or event difference fails closed. Parsing consumes
the already hash-verified byte objects and never reopens evidence paths. A
truthful partial child-nonzero command may omit both parsed evidence and its
JUnit artifact, while a valid authenticated tripwire event remains safety even
when an adjacent malformed sidecar record makes that suite reason
`TRIPWIRE_AUTH_INVALID`.
The canonical JSON remains the sole truth source, so Commit B rendering can
operate on the ignored artifact tree without trusting caller prose.

Schema v2 validation reconstructs every command, SuiteEvidence, structured
property, and internal-evidence state from the canonical record, then recomputes
all fourteen gates from those raw states; caller-supplied PASS rows are never
authoritative. A `TECHNICAL_PASS_HUMAN_DECISION_PENDING` record additionally
requires the exact ordered 22 CommandSpecs with frozen argv/timeouts/conftest
modes, success plus nonzero clean parser evidence for each command, one global
resource baseline across every command, the exact five fresh passing internal
IDs, tripwire PASS, exact focus/disposable-DB/timeout property node sets and
schemas at both viewports, the designated candidate HEAD, and a provided
Lovable completion/reference or owner waiver. Missing, duplicate, substituted,
or malformed evidence is report-integrity `TECHNICAL_NO_GO`, never pending.
Every `SAFETY_NO_GO`, `TECHNICAL_NO_GO`, and pending outcome, runner exit, and
ordered reason list is likewise recomputed from raw commands, global and
per-command resources, gates, tripwire state, and Lovable state. A truthful
partial technical report remains renderable only when it contains no safety
fact; forged decision types, exits, or reasons are rejected.

### Post-Unit-8 completed-report verifier amendment

The first Unit 8 evidence review exposed one decision-dependent verifier gap:
the exact execution contract above was enforced only when the recomputed
decision was `TECHNICAL_PASS_HUMAN_DECISION_PENDING`. A completed
`TECHNICAL_NO_GO` or `SAFETY_NO_GO` record could therefore retain internally
consistent hashes while substituting a timeout or argv, replacing the global
resource baseline with a self-consistent per-command pair, downgrading a
project-conftest command to `--noconftest`, removing its authenticated KEY
sidecar, omitting successful suite evidence, or claiming later commands ran
after an earlier failure. Lovable absence, incident status, a command failure,
or a safety outcome is never authority to relax these immutable fields.

Every completed report, independent of its final decision, now satisfies this
execution contract before artifact rendering:

- commands are a nonempty exact ordered prefix of the 22 frozen
  `CommandSpec`s, including IDs, argv, integer timeouts, conftest modes, and
  ordered stdout/stderr/JUnit paths. The expected specs use only the canonical
  renderer source root described below, never an absolute path recovered from
  recorded argv;
- every command before the last is `SUCCESS`; the last may be non-success, but
  a successful last command is legal only for the complete 22-command run;
- every command `before_snapshot` equals the one global baseline, every prior
  successful `after_snapshot` equals it, and final resource drift remains
  truthful safety evidence. A transient command-level drift may remain in the
  last after-snapshot even when the later final capture has returned to the
  baseline;
- every successful command has one nonzero valid suite bound to its exact
  artifact bytes. A final failed JUnit command may truthfully retain or omit
  its JUnit plus parsed evidence together; a failed TAP command has no parsed
  TAP suite because production parses TAP only after command success;
- the five internal evidence rows are recomputed exactly from the executed
  prefix, suites, global resources, tested HEAD/version, tripwire state, and
  browser-DB evidence. Structured-property completeness is enforced for every
  successful executed suite;
- the frozen project conftest mode cannot be downgraded. Consequently completed
  artifact verification still requires the authenticated command-local KEY
  sidecar for every project pytest JUnit, including technical and safety
  outcomes.

This rule deliberately preserves truthful early-stop artifacts: they use the
exact prefix through the first technical or contained safety failure and never
claim a later command. Incomplete process cleanup still produces no completed
report at all. Any completed-report execution-contract mismatch fails closed as
`REPORT_INTEGRITY_FAILURE`/`CliMisuseError`; it cannot be hidden behind
`LOVABLE_DELIVERABLE_MISSING`, unresolved incidents, or any other decision
reason.

Commit A `e2d3b2d795b76b24895dbac5fa2b3797c5ad9be5` and its first Unit 8
artifact are invalid release candidates because this verifier gap was found
after that run. The repair must be a new reviewed implementation Commit A-prime
on top (never an amend), followed by a complete fresh Unit 8 run against that
exact clean HEAD. The old ignored artifact remains untouched diagnostic
evidence and may not be rendered into Commit B or reused for release.

#### Trusted completed-artifact root clarification

The first scoped replacement-A review found that decision-independent spec
validation was still rooted in the record itself: it recovered the runner's
absolute `--junitxml` parent and then built every expected `CommandSpec` from
that untrusted value. A coherent rewrite of all pytest JUnit argv roots could
therefore pass even though the descriptor-bound artifact bytes remained under
the renderer's real source directory.

For completed rendering, the sole spec trust anchor is now the canonical
`source_path.parent.resolve()` directory of the `report.json` bytes actually
read by `render_completed_report`. That trusted directory is passed explicitly
through completed-record validation and is used to construct every full or
partial expected `CommandSpec`. No recorded argv, descriptor, report field, or
first-command convention may supply or override the root. The existing
artifact-tree `lstat` checks still reject a symlink/nonregular `report.json`, a
symlink/non-directory parent or `commands` directory, and unexpected paths or
entries; canonicalization does not weaken or replace those fail-closed checks.

This root binding applies equally to complete technical/safety NO-GO records
and truthful early-stop technical/safety prefixes. Rewriting one or every
recorded `--junitxml` root is `REPORT_INTEGRITY_FAILURE`, while the otherwise
identical record rooted at the directory actually containing `report.json`
remains renderable. The scoped review was Contract/Code/Safety NO-GO and Stage
GO (`P0=0, P1=1, P2=0`), so Commit A-prime remains unauthorized pending a
fresh scoped re-review; the complete replacement Unit 8 run remains mandatory
after that reviewed commit exists.

The report `tested_head` is not permanently bound to `FROZEN_START_HEAD`.
Before Commit A it may equal that start hash; after Commit A it must equal the
exact lowercase 40-hex candidate in the complete global before/after snapshot
and every command before/after snapshot. This equality is unconditional for
pending, technical, and safety completed reports. Any top/global/per-command
HEAD mismatch, or any runtime release/API/schema version mismatch, rejects the
record. A completed-
report shape or cross-field validation exception is normalized to stable
`REPORT_INTEGRITY_FAILURE`, technical exit `1`, unless an observed resource
drift upgrades the result to safety exit `3`; it never escapes as uncaught CLI
misuse.

The `run` subcommand writes ignored artifacts only. A separate deterministic
`render-report` subcommand reads a completed canonical JSON record and writes the
human-readable tracked report at `docs/interaction-acceptance-report.md`; it
never starts a test. The report explicitly supersedes the old
`docs/acceptance-report.md` and never copies raw provider, exception, PIN, child,
or environment data.

Evidence assigns two final commit roles to avoid an impossible self-referential
Git hash. A later reviewed implementation repair may replace the candidate
implementation HEAD A; the final evidence still refers to exactly one clean,
fully rerun implementation HEAD A and one evidence-only Commit B:

1. **Commit A** contains the reviewed runner, tests, shared Node migration,
   safety fixes, `.gitignore`, conditional focus CSS/a11y change, Task 9 brief,
   and the pre-evidence Task 9 report. Its tree is clean before the full run.
2. The full runner tests exact clean **Commit A** and records that HEAD in JSON.
   It writes only ignored artifacts while resource/Git equality is enforced.
3. `render-report` creates the tracked report from that JSON. Independent
   evidence review verifies artifact/report hashes and stages only the report
   plus updated Task 9 report as **Commit B**.

The report states that Commit A is the tested implementation and Commit B is
evidence-only. It must not claim that the self-referential evidence commit was
the tested HEAD.

## Fourteen mandatory gate evidence map

Every gate begins `BLOCKED`. It becomes `PASS` only when all listed current-run
evidence exists and passed. A whole-file pass count is not a substitute for a
missing named selector.

| Gate | Required fresh evidence |
|---|---|
| 1 — application DB unchanged | Runner global/per-command logical SQLite equality; `tests/test_database_safety.py`; browser resource guards. |
| 2 — version match and mismatch lock | `tests/test_runtime_health.py`; shared API version-gate Node tests; Foundation static navigation tests; Child maintenance fallback; Teacher runtime/auth zero-business-request browser rows. |
| 3 — duplicate prevention | Chat idempotency, completion, roster idempotency, review CAS suites; Child chat/complete fault/retry rows; Teacher mutation timeout/delay/retry rows. |
| 4 — failed utterance retained, no fake reply | Child `test_chat_fault_matrix_retains_draft_without_success_copy` at both viewports and chat idempotency failure projection. |
| 5 — refresh recovery | Child session-store Node recovery tests plus held-chat reload and pagehide browser rows, including stable text/request ID/storage bytes. The two exact serialized session-store selectors for pending completion and ended-chat completion are the `speaking` reload simulation evidence; deleting either keeps this gate BLOCKED. |
| 6 — microphone denial help | Child Teacher-help denial row at both viewports, with visible/focused help control. |
| 7 — saved child exit, tracked analysis | E2E reliable flow, completion one-job tests, analysis worker status/retry tests, and Teacher Today pending/processing/failed queue rows. |
| 8 — complete review round-trip | Review atomic full-document refetch test and Teacher editing draft/confirm browser rows covering feeding, emotion, insight, score, and reason. |
| 9 — review identity/time/ID/status | Review queue/detail service tests and Teacher Review loading/detail browser assertions. |
| 10 — 5-second TTS fallback | Child TTS Node time boundary plus cold-start and six voice-fault browser rows at both viewports; text/completion remains reachable. |
| 11 — roster replay | Roster idempotency suite plus Teacher daily/auto same-body, same-header request-ID retry browser rows. |
| 12 — undoable deactivation | Deactivation backend suite plus Teacher management deactivate/reactivate/undo rows and static no-DELETE policy. |
| 13 — keyboard core flows | Child keyboard/Space flows, Teacher Task 8 page-keyboard review flow, reduced motion, 44px targets, and the Task 9 computed focus contrast `>=3:1`. |
| 14 — real interaction/fault/DB assertions | Full browser fault suites, E2E database assertions, browser fixture tripwires, exact fixture database-path identity, and a visible Teacher management action followed by a read-only `0 -> 1` business-row assertion against that exact disposable database. |

The complete machine-readable selector manifest is frozen below. Format is
`command_id | anchored node-name regex | exact expected count | gates`. Regexes
match the JUnit/TAP node name, not arbitrary stdout. Every listed row must be
present exactly once as a manifest entry; matched test counts are exact. The
language of every parameter regex below is the exact frozen parameter-ID set,
not an open wildcard. Runner unit tests materialize each expected node ID, prove
the row matches exactly that set and count, and reject a same-count substitution.

```text
backend | ^test_pytest_application_logging_uses_only_the_disposable_runtime_file$ | 1 | 1,14
backend | ^test_pytest_subprocess_does_not_change_application_db$ | 1 | 1
backend | ^test_review_atomic_pytest_subprocess_does_not_change_the_real_application_log$ | 1 | 1
backend | ^test_health_returns_frozen_runtime_versions$ | 1 | 2
backend | ^test_version_manifest_is_no_store$ | 1 | 2
backend | ^test_teacher_navigation_is_blocked_until_runtime_ready$ | 1 | 2
backend | ^test_teacher_navigation_requires_both_runtime_and_authentication_and_can_relock$ | 1 | 2
backend | ^test_chat_writes_one_pair_after_ai_success$ | 1 | 3
backend | ^test_duplicate_request_replays_stored_pair_without_a_second_ai_call$ | 1 | 3
backend | ^test_internal_chat_fault_marks_current_claim_failed_and_allows_retry\[(commit|context)\]$ | 2 | 3,4,14
backend | ^test_fixed_max_round_commit_fault_marks_current_claim_failed_and_allows_retry$ | 1 | 3,7,14
backend | ^test_complete_replays_the_frozen_snapshot_without_a_second_job$ | 1 | 3,7
backend | ^test_completion_write_failure_rolls_back_the_job_and_end_state\[(commit|flush)\]$ | 2 | 3,7,14
backend | ^test_process_builds_the_frozen_input_outside_a_database_session_and_projects_once$ | 1 | 7
backend | ^test_restart_recovers_only_expired_processing_jobs_and_preserves_attempts$ | 1 | 7
backend | ^test_failure_uses_bounded_backoff_then_a_sanitized_terminal_state\[(1-pending-1|2-pending-5|3-failed-0)\]$ | 3 | 7,14
backend | ^test_teacher_retry_requires_session_and_reuses_the_failed_job$ | 1 | 7
backend | ^test_teacher_retry_has_frozen_pending_and_terminal_state_contracts\[(pending-2-200-None|processing-1-409-ANALYSIS_IN_PROGRESS|succeeded-1-409-ANALYSIS_ALREADY_SUCCEEDED)\]$ | 3 | 7
backend | ^test_lifespan_uses_the_injected_single_worker_for_health_and_teardown$ | 1 | 7
backend | ^test_auto_generates_five_rotating_weekday_pairs_and_replays_first_snapshot$ | 1 | 3,11
backend | ^test_draft_review_replaces_the_full_document_and_refetches_identically$ | 1 | 3,8
backend | ^test_confirm_requires_complete_reasoned_scores_then_leaves_every_queue$ | 1 | 8
backend | ^test_reliable_end_to_end_flow$ | 1 | 7,8,14
backend | ^test_teacher_queue_uses_job_matrix_frozen_counts_sort_and_historical_child$ | 1 | 9
backend | ^test_succeeded_detail_has_one_complete_ordered_document_or_a_stable_corruption_error$ | 1 | 9
backend | ^test_child_deactivation_preserves_history_and_reactivation_restores_today_visibility$ | 1 | 12
backend | ^test_resource_state_routes_are_locked_and_hard_delete_is_an_auth_first_tombstone$ | 1 | 12
backend | ^test_hard_delete_tombstones_have_stable_missing_codes_and_no_target_lookup_or_write$ | 1 | 12
backend | ^test_resource_route_inventory_flattens_direct_and_included_routes_and_rejects_legacy_parameter_aliases$ | 1 | 12
backend | ^test_teacher_composes_safe_management_and_reports_without_legacy_routes$ | 1 | 12
shared_node | ^version mismatch enters maintenance before any business request$ | 1 | 2
shared_node | ^bootstrapVersionGate and ready share one pending successful gate promise$ | 1 | 2
shared_node | ^caller abort stays AbortError while timeout becomes REQUEST_TIMEOUT$ | 1 | 3,14
child_node | ^unbound and matching bound drafts become child-retryable without changing their request identity$ | 1 | 5
child_node | ^a COMPLETE_FAILED recovery reload returns to saving_conversation at the same remote boundary$ | 1 | 5,7
child_node | ^pending completion keeps the remote completion boundary and never reopens chat$ | 1 | 5,7
child_node | ^ended chat saved through the machine restores only the completion path$ | 1 | 5,7
child_node | ^uses the exact 1500 ms silence boundary and replaces one live timer on results and speech end$ | 1 | 10
child_node | ^a timeout before deferred loader invocation falls back safely and ignores its late blob$ | 1 | 10
teacher_node | ^Today validates every queue DTO shape, fixed labels, and queue-specific combinations$ | 1 | 7
browser | ^test_child_health_validation_fallback_preserves_foundation_maintenance\[(1024x576|1280x720)\]$ | 2 | 2
browser | ^test_teacher_locked_bootstrap_makes_only_runtime_and_auth_requests\[(1024x768|1440x900)\]$ | 2 | 2
browser | ^test_teacher_runtime_failure_keeps_maintenance_and_makes_zero_auth_or_business_requests\[(1024x768|1440x900)\]$ | 2 | 2
browser | ^test_teacher_auth_status_failure_is_safe_and_makes_zero_business_requests\[(1024x768|1440x900)\]$ | 2 | 2
browser | ^test_chat_retryable_fault_reuses_persisted_request_id_once\[(1024x576|1280x720)\]$ | 2 | 3
browser | ^test_first_chat_timeout_retains_draft_and_reuses_request_id_once\[(1024x576|1280x720)\]$ | 2 | 3,4,14
browser | ^test_chat_fault_matrix_retains_draft_without_success_copy\[(http_500|non_json|offline)-(1024x576|1280x720)\]$ | 6 | 3,4,14
browser | ^test_completion_delay_is_single_flight_and_saves_once\[(1024x576|1280x720)\]$ | 2 | 3,7,14
browser | ^test_teacher_review_put_timeout_preserves_dirty_values_and_restores_focus\[(seed_review_timeout_1024|review_timeout_1440)\]$ | 2 | 3,14
browser | ^test_teacher_review_delayed_save_is_single_flight_and_disables_every_editor_control\[(1024x768|1440x900)\]$ | 2 | 3,14
browser | ^test_teacher_resource_state_delay_is_single_flight\[(seed_child_deactivate_1024|child_reactivate_1024|duck_deactivate_1024|duck_reactivate_1024|(child|duck)_(deactivate|reactivate)_1440)\]$ | 8 | 3,12,14
browser | ^test_teacher_roster_delay_is_single_flight\[(seed_daily_1024|auto_1024|daily_1440|auto_1440)\]$ | 4 | 3,11,14
browser | ^test_teacher_roster_settled_faults_preserve_snapshot_and_request_id\[(seed_daily_json_500_1024|auto_json_500_1024|(daily|auto)_(html_502|offline)_1024|(daily|auto)_(json_500|html_502|offline)_1440)\]$ | 12 | 3,11,14
browser | ^test_reload_during_submit_restores_same_draft_and_ignores_old_response\[(1024x576|1280x720)\]$ | 2 | 5
browser | ^test_pagehide_destroy_makes_held_callback_inert\[(1024x576|1280x720)\]$ | 2 | 5,14
browser | ^test_microphone_denial_focuses_visible_teacher_help_then_opens_dialog\[(1024x576|1280x720)\]$ | 2 | 6
browser | ^test_completion_replay_reaches_completed_once_after_strict_save\[(1024x576|1280x720)\]$ | 2 | 3,7
browser | ^test_child_core_flow_is_page_keyboard_only_and_saves_once\[(1024x576|1280x720)\]$ | 2 | 7,13,14
browser | ^test_teacher_today_renders_pending_processing_and_failed_rows_with_retry_boundaries\[(1024x768|1440x900)\]$ | 2 | 7,14
browser | ^test_teacher_today_each_panel_has_its_fixed_empty_state\[(pending|processing|failed)-(1024x768|1440x900)\]$ | 6 | 7
browser | ^test_teacher_today_analysis_retry_is_single_flight_and_refreshes_three_queues_in_order\[(accepted|replayed)-(1024x768|1440x900)\]$ | 4 | 3,7,14
browser | ^test_teacher_today_analysis_retry_failures_restore_only_the_row_action_with_safe_copy\[(mismatch|malformed|401|404|409|500|non-json|offline)-(1024x768|1440x900)\]$ | 16 | 7,14
browser | ^test_teacher_review_editor_saves_the_complete_normalized_draft_and_refreshes_only_queue\[(1024x768|1440x900)\]$ | 2 | 8
browser | ^test_teacher_review_complete_confirm_uses_confirm_action_and_removes_the_pending_row\[(1024x768|1440x900)\]$ | 2 | 8
browser | ^test_teacher_review_queue_and_detail_show_identity_time_id_and_status\[(1024x768|1440x900)\]$ | 2 | 9
browser | ^test_tts_cold_start_uses_reachable_five_second_fallback\[(1024x576|1280x720)\]$ | 2 | 10,14
browser | ^test_tts_faults_settle_and_do_not_block_completion\[(edge_http_500|edge_non_json|edge_offline|play_rejected|audio_error|browser_speech_error)-(1024x576|1280x720)\]$ | 12 | 10,14
browser | ^test_child_deactivation_uses_named_dialog_and_real_undo\[(1024x768|1440x900)\]$ | 2 | 12
browser | ^test_children_management_is_labeled_strict_and_never_sends_delete\[(1024x768|1440x900)\]$ | 2 | 12
browser | ^test_teacher_management_exposes_reversible_state_without_delete\[(1024x768|1440x900)\]$ | 2 | 12
browser | ^test_teacher_resource_state_settled_faults_never_claim_success\[(seed_child_deactivate_json_500_1024|child_reactivate_json_500_1024|duck_deactivate_json_500_1024|duck_reactivate_json_500_1024|(child|duck)_(deactivate|reactivate)_(html_502|offline)_1024|(child|duck)_(deactivate|reactivate)_(json_500|html_502|offline)_1440)\]$ | 24 | 12,14
browser | ^test_manual_space_stop_requires_one_explicit_end\[(1024x576|1280x720)\]$ | 2 | 13
browser | ^test_space_is_single_action_for_native_and_global_paths\[(1024x576|1280x720)\]$ | 2 | 13
browser | ^test_keyboard_focus_visible_uses_start_to_ready_flow\[(1024x576|1280x720)\]$ | 2 | 13
browser | ^test_fault_recovery_preserves_accessibility_and_projection_constraints\[(chat_retryable|completion_failure)-(1024x576|1280x720)\]$ | 4 | 13,14
browser | ^test_teacher_complete_review_flow_is_page_keyboard_only\[(seed_keyboard_review_1024|keyboard_review_1440)\]$ | 2 | 13
browser | ^test_teacher_dirty_review_dialog_is_named_keyboard_operable_and_restores_focus\[(seed_dirty_dialog_1024|dirty_dialog_1440)\]$ | 2 | 13
browser | ^test_teacher_authenticated_routes_have_frozen_accessibility_structure\[(seed_a11y_today_1024|a11y_(children|ducks|roster|review|growth|search)_1024|a11y_(today|children|ducks|roster|review|growth|search)_1440)\]$ | 14 | 13
browser | ^test_release_focus_indicator_meets_three_to_one\[(1024x768|1440x900)\]$ | 2 | 13
browser | ^test_completion_fault_matrix_never_claims_saved_copy\[(http_500|non_json|offline|boundary_mismatch)-(1024x576|1280x720)\]$ | 8 | 3,14
browser | ^test_teacher_representative_read_validators_cover_missing_transport_faults\[(seed_today_roster_html_502_1024|today_roster_offline_1024|review_pending_html_502_1024|review_pending_offline_1024|today_roster_html_502_1440|today_roster_offline_1440|review_pending_html_502_1440|review_pending_offline_1440)\]$ | 8 | 14
browser | ^test_teacher_review_save_failures_keep_exact_values_dirty_and_never_refresh\[(server|non-json|offline)-\\u4fdd\\u5b58\\u5931\\u8d25\\uff0c\\u8bf7\\u7a0d\\u540e\\u91cd\\u8bd5\\u3002-(1024x768|1440x900)\]$ | 6 | 14
browser | ^test_child_server_import_preflight_blocks_provider_env$ | 1 | 14
browser | ^test_main_import_filehandler_is_redirected_from_real_log$ | 1 | 1,14
browser | ^test_edge_tts_fake_stream_trips_before_network$ | 1 | 14
browser | ^test_nonstarting_worker_has_no_start_side_effect$ | 1 | 14
browser | ^test_browser_subprocess_environment_is_minimal$ | 1 | 14
browser | ^test_real_resource_snapshots_are_read_only$ | 1 | 1,14
browser | ^test_socket_guard_blocks_non_loopback$ | 1 | 14
browser | ^test_fixture_teardown_closes_before_process_assertions$ | 1 | 14
browser | ^test_context_loopback_policy_allows_only_exact_origin\[(data:text/plain,synthetic-False|http://127\.0\.0\.1/-False|http://127\.0\.0\.1:43123/-True|http://127\.0\.0\.1:43123/api/health\?x=1-True|http://127\.0\.0\.1:43124/-False|http://127\.0\.0\.1:not-a-port/-False|http://\[::1\]:43123/-False|http://example\.invalid:43123/-False|http://localhost:43123/-False|http://user:pass@127\.0\.0\.1:43123/-False|https://127\.0\.0\.1:43123/-False)\]$ | 11 | 14
browser | ^test_loopback_server_uses_disposable_resources$ | 1 | 1,14
browser | ^test_child_page_registers_fail_closed_business_routes_before_navigation$ | 1 | 14
browser | ^test_page_specific_routes_cannot_widen_loopback_policy$ | 1 | 14
browser | ^test_browser_parent_logging_is_redirected_from_real_application_log$ | 1 | 1,14
browser | ^test_release_teacher_action_persists_to_disposable_sqlite\[(1024x768|1440x900)\]$ | 2 | 14
```

Runner unit tests verify that all fourteen gate numbers occur, every manifest
pattern compiles, and no one test result can satisfy two different manifest rows
unless the same row explicitly lists multiple gates. Unknown, duplicate, absent,
skipped, xfailed, xpassed, todo, cancelled, or ambiguous matches keep the gate
`BLOCKED`/`FAIL`. They also build and store a reverse selector-to-gate index and
assert every evidence phrase in the fourteen-row table has at least one exact
selector or mandatory internal evidence ID; no whole-suite count can fill a
missing phrase.

The following non-JUnit/TAP evidence IDs are separately mandatory and occur
exactly once in the canonical record:

```text
resource | global_and_per_command_logical_and_physical_equality | 1 | 1,14
resource | inherited_user_paths_and_git_porcelain_equal | 1 | 1,14
runtime | tested_head_api_schema_and_release_versions_exact | 1 | 2,14
tripwire | provider_tts_socket_context_and_worker_tripwires_clean | 1 | 14
browser_db | exact_fixture_path_and_read_only_zero_to_one_business_row | 1 | 14
```

A missing, duplicate, false, malformed, or stale internal evidence ID blocks all
listed gates even when every test selector passed.

## Historical incident ledger and authority boundary

The report always contains these immutable incident IDs and facts:

1. `PIPELINE_T8_PROVIDER_20260823`
   - two real DeepSeek HTTP 200 calls at 2026-08-23 22:59:31 and 22:59:44 +08;
   - synthetic transcript and disposable SQLite only;
   - corrected high-level fakes, permanent autouse lowest-level `_llm` breaker,
     sanitized subprocess environment, and subsequent breaker-free suites.
2. `CHILD_T9_REAL_LOG_20260827`
   - asyncio pending-route teardown appended to real `logs/app.log` at
     2026-08-27 19:33:50 +08;
   - inherited parent pytest `FileHandler` was the root cause;
   - bytes preserved; parent logging guard and byte comparison added; later
     Child browser gates remained byte-identical.
3. `TEACHER_T5_REAL_LOG_20260829`
   - a non-browser review pytest was incorrectly run concurrently with two
     browser suites at 2026-08-29 01:59 +08;
   - shared TestClient `FileHandler` wrote the real log;
   - bytes preserved; Task 5A isolated pytest logging and all later gates ran
     strictly serial.

The completed incident list is an exact immutable ledger: exact incident order,
IDs, fact bytes, corrective-control bytes, and only the frozen derived fields
`release_owner_acknowledgement=ABSENT`,
`status=HUMAN_DECISION_REQUIRED`, and
`technical_review_status=PENDING_INDEPENDENT_EVIDENCE_REVIEW`. Missing, extra,
reordered, substituted, or augmented incidents and any changed derived field
are stable report-integrity failures, never uncaught key/type errors.

Technical review may recommend `CLOSED_NO_RESIDUAL` or `RESIDUAL_RISK`, but an
agent/reviewer/runner cannot sign the release-owner acknowledgement. Until the
user or named release owner supplies a separate, explicit written disposition,
the release outcome remains `TECHNICAL_PASS_HUMAN_DECISION_PENDING` at best.

The runner may accept an optional external decision JSON only to quote, hash,
and label it `UNVERIFIED_SUPPLIED_ARTIFACT`. Self-declared author/role fields do
not prove authority and never change the runner outcome. It never creates or
edits that file. The strict document must contain exact incident IDs, `ACCEPT`
or `REJECT`, author name, claimed `user` or `release_owner` role, RFC3339
timestamp, and nonempty rationale; no aliases, missing/extra incident, or
agent/reviewer role is accepted. Actual authorization exists only when the user
or named release owner gives an explicit instruction in a follow-up, which is
then recorded during a separately authorized report-only task.

## Lovable delivery boundary

Lovable is not one of specification section 16's numbered gates, so the runner
must not forge a numbered PASS/FAIL for it. It is nevertheless a required
parallel deliverable and completion criterion.

Overall release can leave human-decision-pending only when one of these is
provided by the user/release owner:

- a real private two-screen Lovable prototype completed from the sanitized pack,
  checklist review evidence, and a valid `prototype-reference.md`; or
- an explicit written scope waiver separating runtime release from prototype
  delivery.

The current blank project, project URL alone, local sanitized pack, or zero-credit
error is never accepted as prototype completion. Task 9 does not buy credits,
publish, connect a database, upload source, or create a fake reference file.

## Decision model

The runner itself emits only:

```text
SAFETY_NO_GO
TECHNICAL_NO_GO
TECHNICAL_PASS_HUMAN_DECISION_PENDING
```

It never emits final `GO`.

- `SAFETY_NO_GO`: preflight/resource/tripwire/user-path violation; exit `3`.
- `TECHNICAL_NO_GO`: command, parse, evidence, 14-gate, contrast, HEAD, version,
  or report-integrity failure; exit `1`.
- `TECHNICAL_PASS_HUMAN_DECISION_PENDING`: every technical command and all 14
  gates pass with unchanged resources, but final incident/Lovable authority is
  still a human act; exit `2`.
- CLI misuse or malformed external decision input: exit `64`, with no tests run.

Final release `GO` can be recorded only in a follow-up authorized by an explicit
user/release-owner decision and after an independent Task 9 Code/Safety review.
That follow-up is outside this implementation contract.

The exit-2 runner result is a truthful non-GO/PENDING process result, not a green
suite result and not a warning conversion. Any pytest, Node, static check, or
evidence parser nonzero is a technical failure and can never be normalized to
exit 2.

## Strict TDD execution plan

Each checkbox is one bounded 2–5 minute action. Record genuine RED, direct-GREEN,
and harness-only correction honestly in the Task 9 report.

### Unit 0 — contract and immutable preflight

- [ ] **0.1** Through `<CLEAN_ENV>`, launch the exact key-only Python environment
  probe before Git or any repository import. Assert its sorted key set is the
  nine explicit keys `DISABLE_EXTERNAL_AI`, `HOME`, `LANG`, `LC_ALL`, `PATH`,
  `PYTHONNOUSERSITE`, `PYTHON_DOTENV_DISABLED`, `TMPDIR`, and `TZ`, plus only the
  optionally Darwin-synthesized `__CF_USER_TEXT_ENCODING` when
  `sys.platform == "darwin"`. Both the nine-only and nine-plus-one Darwin sets
  are valid. Record names only, never inspect that platform key's value, and
  fail before all later work on any other extra or missing key. Also assert the
  launcher assignment argv itself still contains exactly the explicit nine.
- [ ] **0.2** Through three separate `<CLEAN_ENV>` invocations, run the exact
  HEAD/status/diff preflight and record the frozen real DB/log/TTS/user-path
  snapshot without starting pytest or a service.
- [ ] **0.3** Obtain independent Contract GO for this brief. Stop on any P0/P1.

### Unit 1 — stale shared API Node boundary

- [ ] **1.1** Through `<CLEAN_ENV>`, run the shared API Node command once and
  capture the real inline script extraction RED.
- [ ] **1.2** Delete only the obsolete Teacher inline harness and its three
  misplaced tests; preserve every shared API test.
- [ ] **1.3** Run the shared API Node command twice and record exact test totals
  with no skip/todo/cancel.
- [ ] **1.4** Run the five frozen owning Foundation/Teacher selectors that replace
  the removed inline-harness coverage.

### Unit 2 — runner inventory and import safety

- [ ] **2.1** Create `tests/test_interaction_acceptance_runner.py` with an import
  test; run its exact pytest argv through `<CLEAN_ENV>` to capture
  `ModuleNotFoundError` RED.
- [ ] **2.2** Create an effect-free runner module with only dataclasses/enums and
  the frozen command builder; run the import/inventory test GREEN.
- [ ] **2.3** Add exact tests for sorted explicit argv, conftest mode, all 22
  authoritative CommandSpec IDs and their exact timeout seconds, full and Unit
  6 focused selectors, unique JUnit paths, and forbidden-target absence; run
  RED.
- [ ] **2.4** Implement the exact command specs and run the inventory tests GREEN.

### Unit 3 — environment and resource digests

- [ ] **3.1** Add hostile-parent environment tests covering provider/key/token/
  proxy stripping and browser `HOME`. Include a Mapping that permits key
  enumeration but raises if the `__CF_USER_TEXT_ENCODING` value is accessed;
  prove the sanitized mapping and argv exclude it without touching the value;
  run RED.
- [ ] **3.2** Implement the minimal sanitized environment and run GREEN.
- [ ] **3.2a** In `tests/test_database_safety.py`, add the frozen temporary-package
  symlink, real `probe.py`, cwd, argv, and `PYTHONPATH` synthetic `.env` test.
  Import that isolated AI module before any monkeypatch; start the parent pytest
  with `PYTHON_DOTENV_DISABLED=1`, then capture RED because only the not-yet-fixed
  nested helper omits the flag and the probe reports
  `sentinel_loaded=true`. The parent must never remove its dotenv breaker to
  manufacture RED. Never put the repository root on child `sys.path`, read the
  repository `.env`, or supply a provider value.
- [ ] **3.2b** Set `PYTHON_DOTENV_DISABLED=1` before the conftest AI import and in
  every nested safe-pytest environment; rerun that sentinel and the existing
  database-safety subprocess matrix GREEN, requiring exact probe output
  `sentinel_loaded=false`. Keep the pure runner suite limited to the
  environment-builder contract.
- [ ] **3.3** Add a temporary SQLite WAL-visible change test that defeats raw-file
  SHA but changes logical `iterdump()` digest; run RED.
- [ ] **3.4** Implement read-only logical SQLite digest; verify no fixture bytes
  are changed and that observing the digest leaves database, `-wal`, and `-shm`
  existence, bytes, and metadata unchanged.
- [ ] **3.5a** Add log SHA/size/mtime and database/WAL/SHM `lstat` tests for
  missing, same-byte rewrite, chmod, symlink, unreadable, and sidecar cases; run
  their focused RED.
- [ ] **3.5b** Add stable sorted TTS root/entry/content metadata tests for order,
  same-byte rewrite, chmod, symlink, unreadable, and type-change cases; run their
  focused RED.
- [ ] **3.5c** Implement strict file/database resource capture and run the 3.5a
  matrix GREEN.
- [ ] **3.6** Implement strict directory capture and run the 3.5b matrix, then all
  Unit 3 tests GREEN.

### Unit 4 — serial executor and evidence parsing

- [ ] **4.1a** Add fake process-group tests for clean normal/signal exit and a
  normally exited **and** a spontaneously signaled leader, each with a
  stdio-closed surviving descendant; prove both residual paths remain safety
  even after bounded cleanup; run focused RED.
- [ ] **4.1b** Add timeout tests for TERM cleanup, a TERM-ignoring descendant,
  KILL escalation, final-reap integer capture, and full nonduplicated output;
  run focused RED.
- [ ] **4.1c** Add incomplete-cleanup tests for a KILL-surviving pipe holder and
  unreaped leader; separately cover final-communicate success followed by group
  liveness failure and final-communicate timeout where the leader is reaped and
  PGID is already `ESRCH`. Assert the latter exact tuple is only
  `(PIPE_DRAIN_TIMEOUT,)`, communicate and liveness consume one shared remaining
  deadline, every exact cleanup-failure tuple is canonical, the correct newest
  complete-or-partial buffer is written once, the after snapshot is null, and
  exit is safety `3`; run focused RED.
- [ ] **4.1d** Add serial-order tests proving PGID extinction and after snapshot
  both precede command N+1, and that every residual/incomplete path starts no
  N+1; run focused RED.
- [ ] **4.2** Implement synchronous serial process-group execution using only
  the CommandSpec timeout and first-failure stop; run GREEN.
- [ ] **4.3** Add JUnit parser tests for pass, failure, error, skip, xfail/xpass,
  zero collection, malformed XML, and duplicate node IDs; run RED.
- [ ] **4.4** Implement strict JUnit parsing and run GREEN.
- [ ] **4.5** Add TAP parser tests for pass, failure, skip, todo, cancel, malformed,
  and duplicate subtests; run RED.
- [ ] **4.6** Implement strict TAP parsing and run GREEN.

### Unit 5 — gate map and honest decisions

- [ ] **5.1a** Encode all 14 gates, the 96 unique selector rows, full literal
  parameter-ID sets, reverse selector-to-gate index, and five internal evidence
  IDs in runner tests; run the manifest-shape RED.
- [ ] **5.1b** For Gates 1–7, delete each owning selector/internal ID in turn and
  assert the affected gate remains BLOCKED; run the focused mutation RED.
- [ ] **5.1c** Repeat the deletion matrix for Gates 8–14 and prove every
  same-count substituted parameter ID fails; run the focused mutation RED.
- [ ] **5.2** Implement gate evaluation and run the complete 14-gate unit matrix
  GREEN.
- [ ] **5.3** Add decision tests for command failure, resource drift, tripwire,
  contrast failure, unresolved incident, rejected incident, missing Lovable,
  malformed decision file, and technical pass; run RED.
- [ ] **5.4** Implement the three runner outcomes and exact exit codes; prove the
  runner never emits final GO.
- [ ] **5.5** Add canonical JSON and Markdown golden tests with a fixed clock and
  fixed run ID, including timeout resolved by TERM and timeout escalated to KILL
  with their exact final-reap integers; run RED.
- [ ] **5.6** Implement one-way report rendering and run golden tests twice.
- [ ] **5.6a** Before the first repository-local `run-one`, capture a genuine
  `git check-ignore` RED for `artifacts/acceptance/probe/report.json`; add only
  `/artifacts/acceptance/` to `.gitignore`; prove the probe is ignored while
  sibling `artifacts/`, logs, databases, screenshots, and tracked reports are
  not newly ignored. Stage only `.gitignore`, assert the interim cached path list
  is exactly `.gitignore`, and record the stable porcelain baseline.
- [ ] **5.7** Implement and unit-test a `run-one` CLI path that accepts only a
  frozen CommandSpec ID, takes strict resources before/after, writes ignored
  evidence, and obeys the frozen `CLI misuse -> 64; protected-resource safety ->
  3; wrong HEAD/version or runner-evidence failure -> 1; otherwise positive
  child nonzero unchanged; success -> 0` precedence. It may not accept raw shell
  text or an arbitrary executable.

### Unit 6 — focus and real browser/SQLite evidence

Every Unit 6 focused browser node is executed through the reviewed `run-one`
path, not raw pytest. This adds the runner's strict missing-resource preflight
and global DB/log/TTS/user-path comparison outside the older nullable fixture
snapshots.

- [ ] **6.1** Create the exact 1024 focus-contrast selector and capture the current
  `#ffb800` genuine RED with measured ratios.
- [ ] **6.2** Implement only the two-tone common focus rule; run the 1024 selector
  GREEN and inspect computed ring colors/rectangles.
- [ ] **6.3** Expand the same selector to 1440 and run both viewports GREEN.
- [ ] **6.4** Rerun the complete Teacher accessibility file; stop if any keyboard,
  reduced-motion, focus, 44px, or overflow regression appears.
- [ ] **6.5** Add the 1024 real management-action/disposable-SQLite selector and
  run it; record RED or direct-GREEN without product changes outside scope.
- [ ] **6.6** Expand the database selector to 1440 and run both viewports GREEN;
  verify global resource snapshots and browser tripwires remain clean.
- [ ] **6.7** Add the exact Review loading assertion for visible child name,
  completed time, conversation ID, queue review status, and detail analysis
  status; run the 1024 node first, then both viewports. If current visible markup
  satisfies it, record direct-GREEN rather than changing product code.
- [ ] **6.8** Add the frozen first-chat timeout row; run its 1024 node first, then
  both Child viewports. Stop rather than weakening the `9_999/10_000 ms`, durable
  draft, same-request-ID, and zero-fake-copy assertions.
- [ ] **6.9** Add the frozen completion-delay single-flight row; run its 1024 node
  first, then both Child viewports. Assert exactly one completion request before
  and after the held acknowledgement settles.
- [ ] **6.10** Add the frozen page-keyboard-only Child core flow; run its 1024 node
  first, then both Child viewports. Record every user action modality and the
  single saved/completed boundary.
- [ ] **6.11** Add the frozen Today three-status row; run its 1024 node first, then
  both Teacher viewports. Assert the three queue identities/statuses and the
  failed-only retry ordering.

### Unit 7 — runner CLI and implementation commit A

- [ ] **7.1a** Add CLI refusal tests for invalid args, unknown ID with zero
  resource I/O/child starts, missing/unsafe baseline, and wrong HEAD after a
  baseline with zero child starts. Assert the two exact no-baseline reason/state
  combinations and the baseline-bearing technical-refusal combination; run the
  focused RED.
- [ ] **7.1b** Add process-result tests for spawn failure, normal failure,
  contained timeout, spontaneous signal/negative return, residual descendants,
  incomplete process cleanup, and artifact-write failure; run the focused RED.
- [ ] **7.1c** Add drift-precedence tests for child failure, technical preflight
  refusal, and spawn failure after an established before snapshot; assert safety
  exit `3` wins, plus null-after incomplete cleanup; run the focused RED.
- [ ] **7.1d** Assert every valid `child_started/child_exit/termination/
  output_complete/residual_group_observed/cleanup_failures/
  classified_outcome/snapshot` combination, reject every invalid cross-product,
  including null snapshots with any unapproved reason. Prove normally exited
  child codes `2/3/64` remain distinct from run-level meanings in canonical
  JSON/Markdown; run the focused RED.
- [ ] **7.2** Implement fail-closed CLI orchestration and run all runner unit tests
  twice with `--noconftest`.
- [ ] **7.3** Reverify the already-staged exact `/artifacts/acceptance/` ignore
  rule and its negative sibling cases; do not add or broaden an ignore here.
- [ ] **7.4** Run syntax checks for runner and release browser test; run shared,
  Child, and Teacher Node commands strictly serial.
- [ ] **7.5** Run policy scans and `git diff --check`, then stage Commit A with
  explicit paths only:

  ```bash
  git add .gitignore scripts/run_interaction_acceptance.py \
    tests/test_interaction_acceptance_runner.py \
    tests/browser/test_release_viewports.py \
    tests/browser/test_child_faults.py \
    tests/browser/test_teacher_today.py \
    tests/browser/test_teacher_review_loading.py \
    tests/frontend/shared/api-client.test.mjs \
    tests/conftest.py tests/test_database_safety.py
  git add -f \
    .superpowers/sdd/2026-08-23-teacher-workbench-and-acceptance/task-9-brief.md \
    .superpowers/sdd/2026-08-23-teacher-workbench-and-acceptance/task-9-report.md
  ```

  Add `app/frontend/teacher/styles.css` and
  `tests/browser/test_teacher_accessibility.py` explicitly only when the
  documented focus RED activated conditional ownership. Add
  `tests/browser/test_child_shell.py` explicitly only when the independently
  reviewed Unit 7.6 ordered Playwright-loop RED activated its narrow
  conditional ownership. Compare cached paths exactly to that allow-list, run
  `git diff --cached --check`, then request independent Code/Safety/Stage
  review.
- [ ] **7.6** If review returns any P0/P1, treat the prior review and staged-byte
  verdict as invalid. Resolve each item with focused RED/GREEN, rerun every
  affected full gate, update and force-add the Task 9 report, restage the exact
  Commit A allow-list, recheck cached paths and cached/worktree diffs, and request
  a fresh independent Code/Safety/Stage review. Repeat until the current staged
  bytes receive GO. Only then commit the implementation as:

  ```bash
  git commit -m "test: add honest stabilization acceptance runner"
  ```

  Confirm the resulting worktree is clean except the four inherited user path
  categories. This exact commit becomes evidence HEAD A.

### Unit 8 — fresh full release evidence from clean commit A

Unit 8 is the explicitly declared long-running acceptance phase; its commands
are not 2–5 minute slices. They remain strictly serial and are never used as the
first RED for a product fix.

- [ ] **8.1** Capture the exact global baseline and run the pure runner unit suite.
- [ ] **8.2** Verify unchanged resources; run the pure Lovable artifact suite.
- [ ] **8.3** Verify unchanged resources; run the complete explicit backend/E2E
  command.
- [ ] **8.4** Verify unchanged resources; run the complete browser command alone.
  If it exceeds 60 seconds, poll the same process and report progress; never start
  another command.
- [ ] **8.5** Verify unchanged resources; run shared, Child, and Teacher Node
  commands one at a time.
- [ ] **8.6** Invoke the runner from a fresh process to reproduce the same command
  inventory and generate canonical artifacts. With no human decision/Lovable
  completion, expected exit is `2` only if all technical gates pass; otherwise
  the exact fail-closed exit is expected.
- [ ] **8.7** Verify the ignored canonical JSON and Markdown artifact against
  clean commit A. Do not create a tracked report until all resource snapshots
  and command parsers have settled.

### Unit 9 — evidence render, independent review, and report-only commit B

- [ ] **9.1** Run `render-report` against the immutable JSON artifact to create
  `docs/interaction-acceptance-report.md`; update only the ignored Task 9 report.
- [ ] **9.2** Run report-integrity unit tests and verify every hash, count,
  selector, gate, incident, blocker, decision, and tested HEAD equals the
  canonical artifact.
- [ ] **9.3** Stage only the tracked acceptance report and force-add the updated
  Task 9 report:

  ```bash
  git add docs/interaction-acceptance-report.md
  git add -f \
    .superpowers/sdd/2026-08-23-teacher-workbench-and-acceptance/task-9-report.md
  ```

  Compare cached paths exactly to those two paths, run cached/worktree diff
  checks, and prove no implementation or user path is staged before Evidence
  review.
- [ ] **9.4** Request independent Evidence/Safety/Stage review. Reviewer must
  challenge at least one gate or decision assumption and return P0/P1/P2.
- [ ] **9.5** If Evidence review returns any P0/P1, invalidate its prior verdict.
  A report-input or deterministic render invocation issue may be corrected by
  rerendering from the unchanged canonical JSON, then rerunning report-integrity
  gates, updating/force-adding the Task 9 report, restaging exactly the two
  Commit B paths, rechecking cached paths/diffs, and requesting fresh review. If
  the runner, renderer code, canonical evidence, or implementation is wrong,
  abandon the Commit B candidate: create a separately reviewed non-amend
  implementation repair commit, designate it the replacement evidence HEAD A,
  and rerun all of Units 8 and 9 from that clean commit. Commit B never contains
  runner/renderer code. Repeat until current evidence-only staged bytes receive
  GO. Do not hand-edit a PASS into the Markdown.
- [ ] **9.6** After evidence review GO, commit with:

  ```bash
  git commit -m "docs: record stabilization release evidence"
  ```

  Commit B may contain a truthful NO-GO/PENDING report. It must identify commit A
  as the tested HEAD and must not fabricate release GO.

## Final report required fields

The tracked report must contain:

- exact HEAD, release/API/schema versions, UTC run time, runner schema and run ID;
- explicit supersession of `docs/acceptance-report.md`;
- exact command argv, conftest mode, timeout, exit, counts, duration, logs and
  evidence hashes;
- global and per-command logical DB plus physical DB/`-wal`/`-shm`, log,
  TTS-root/entry metadata and content, and inherited-user-path snapshots;
- provider/TTS/socket/context tripwire states;
- all 14 gates with exact current selectors and PASS/FAIL/BLOCKED reasons;
- the four viewport contracts, focus contrast measurements, disposable-DB
  action evidence, and exact 9,999/10,000 ms timeout evidence;
- all three historical incidents, corrective controls, technical review status,
  and absent/present release-owner acknowledgement;
- Lovable project status, zero-credit blocker, absent/present completion or
  scope waiver, and confirmation that no connector/publish/source upload occurred;
- P0/P1/P2, limitations, technical outcome, runner exit, and the explicit fact
  that final GO remains a human release decision.

## Completion rule

Task 9 implementation is complete when the safe runner, strict tests, current
evidence artifact, honest tracked report, and independent reviews are committed
without touching user resources. This does **not** imply release GO.

At the current boundary, complete stabilization remains NO-GO because the
Lovable two-screen deliverable and release-owner incident disposition are absent.
The runner may improve that only to `TECHNICAL_PASS_HUMAN_DECISION_PENDING`; it
cannot accept those risks itself.
