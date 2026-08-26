# Child Task 6B Report — Browser Shell and Isolated Evidence Harness

## Boundary and ownership

- Exact approved start HEAD: `fdbe6c7a8fda34bc1de4b6df5a9350238da379bc`, the independently approved Child Task 7 boundary.
- Owned product paths: `app/frontend/child/browser.mjs`, `app/frontend/index.html`, and `requirements-dev.txt`.
- Owned test paths: `tests/test_frontend_foundation.py`, `tests/browser/conftest.py`, `tests/browser/child_server.py`, and `tests/browser/test_child_shell.py`.
- This ignored report is force-staged as the eighth owned path. The implementation is `008dd1c` (`feat(child): compose browser shell`); the first review remediation is `6839819` (`fix(child): close browser fixture isolation gaps`); the context-level route remediation is `65f19539a3fd6d14690fd20163e0746636269b64` (`fix(child): isolate every browser fixture page`).
- Existing user changes in `.workbuddy/memory/2026-08-22.md`, `docs/superpowers/specs/2026-08-23-interaction-stabilization-design.md`, `.superpowers/brainstorm/`, and `docs/superpowers/plans/` remained outside Task 6B and were not staged.

## TDD evidence

1. Foundation shell RED: the first focused run reported `2 failed, 7 passed`. The old child page still had inline style/behavior and no `/child/browser.mjs`; the retained teacher-gate slice stayed green.
2. Browser-entry RED: the eleven named source/composition slices reported `11 failed` because `app/frontend/child/browser.mjs` did not exist. The semantic shell and sole global entry were then implemented without adding Task 8 teacher/PIN behavior.
3. Safety-harness RED: the pure safety selection reported eight failures and thirteen fixture errors. `child_server.py` was absent, and the double-gate/parser/exact-origin fixtures did not exist. No Popen, server, Playwright import, browser, context, page, provider, or transport was constructed by that RED.
4. Browser-provisioning RED/NO-GO: an isolated `test_loopback_server_uses_disposable_resources` attempt stopped in `chromium_browser` before `child_server` setup. It reported both missing paths and the documentation-only human follow-up; no installation command or server was executed.
5. Probe-cleanup RED: an injected probe page whose `close()` raised prevented the browser close (`broken-browser.close` was absent). Nested `finally` cleanup now closes the browser even when probe-page cleanup fails; the focused regression passes while preserving the original page-close exception.

## Delivered browser boundary

| Area | Delivered contract |
| --- | --- |
| Semantic shell | `index.html` contains one preflight main landmark, external stylesheet, ordered Foundation API/auth scripts, and exactly one module entry. It contains no inline style, inline behavior, direct API global, speech/storage behavior, text input, or legacy stage/root/PTT UI. |
| Browser composition | `browser.mjs` owns the exact five-key frozen machine facade and injected store/TTS/speech/view/DOM/keyboard/controller seams. It bootstraps once, attaches the document keydown forwarder only after a non-null app, and removes it with idempotent pagehide cleanup. |
| Maintenance | Foundation `#runtime-maintenance` is never replaced by the child fallback. The child fallback builds fixed text nodes only and never renders an arbitrary error value. |
| Keyboard policy | Interactive/contenteditable targets and active modal dialogs are rejected before Task 7 global Space handling. The forwarder passes the original event and contains no direct action or `preventDefault`. |
| Browser revision gate | Playwright package, two independent whole-output target scans, exact product/revision/install directories, launched browser version, and probe UA are separate fail-closed gates. There is no top-level Playwright import. |
| Server isolation | The launcher inserts the repository root before app imports; disables dotenv first; rejects provider/proxy names before and after main import; redirects every import-time FileHandler; installs lowest-level LLM, Edge-TTS, and socket tripwires; uses a non-starting worker; and binds uvicorn only to `127.0.0.1`. Before any page is created, the browser context registers deterministic fail-closed local routes for roster, active conversation, chat, completion, and TTS, so every page inherits them; individual tests may replace them only with stricter exact-origin fixtures. |
| Resource isolation | The fixture environment is rebuilt from a small execution allowlist, uses a resolved disposable app-mode DB/log/TTS cache, takes read-only logical DB and file/tree digests, blocks service workers and non-exact browser origins, and verifies real snapshots/tripwires only after all browser resources and the server process have exited. |

## Browser package and provisioning result

`requirements-dev.txt` pins `playwright==1.62.0`. The installed package reports `1.62.0`. The only executed browser provisioning command was read-only:

```text
./.venv/bin/python -m playwright install --dry-run chromium

Chrome for Testing 151.0.7922.34 (playwright chromium v1234)
  Install location: /Users/lddmay/Library/Caches/ms-playwright/chromium-1234

FFmpeg (playwright ffmpeg v1011)
  Install location: /Users/lddmay/Library/Caches/ms-playwright/ffmpeg-1011

Chrome Headless Shell 151.0.7922.34 (playwright chromium-headless-shell v1234)
  Install location: /Users/lddmay/Library/Caches/ms-playwright/chromium_headless_shell-1234
```

Both required v1234 directories were absent. The whole-output parser tests independently located the CFT and Headless Shell headers and each header's own first install location while ignoring interleaved Download/Fallback and FFmpeg blocks. The gate combines captured stdout and stderr before both independent scans; the stderr-only regression is green. Both parser targets were green against synthetic existing directories.

**Browser coverage: NO-GO.** Gate 2 did not launch; therefore no runtime `browser.version`, probe `navigator.userAgent`, application server, test browser/context/page, loopback port, service-worker-block runtime observation, or two-viewport browser assertion is claimed. No Task 6B code, test, fixture, script, or agent ran an installation command. The gate printed only this documentation-only, human-authorized follow-up: `./.venv/bin/python -m playwright install chromium`.

Because gate 1 stopped before fixture construction, no browser runtime directory was created. Pure pytest seams used pytest-owned temporary directories beneath the system `/private/var/folders/.../T/pytest-of-lddmay/` root only.

## Isolation evidence that was executable without Chromium

- Shared fresh-main guard: the exact event order was `dotenv_disabled → provider_environment_absent_pre → real_log_snapshotted → filehandler_redirected → main_imported → filehandler_restored → provider_environment_absent_post → logging_configured`. An injected `OPENAI_API_KEY` branch failed after `dotenv_disabled` and before the importer was invoked.
- FileHandler evidence: every handler requested by fresh `main` import resolved to the pytest temporary `BROWSER_LOG_DIR/app.log`; `logging.FileHandler` was restored in `finally`; the real log byte snapshot was identical before and after the guard.
- Edge seam: a real `async for` over `FakeCommunicate.stream()` wrote only the disposable tripwire and raised `external edge_tts disabled in browser tests` before any yielded transport/cache data.
- Worker seam: `_NonStartingAnalysisWorker.start()` and `.stop()` were no-ops and `.status()` remained exactly `not_started`.
- Minimal environment: only safe execution variables and the ten exact disposable/browser-control variables survived; provider, proxy, arbitrary app, Playwright-cache, and API-key variables were absent.
- Read-only snapshots: the SQLite helper was observed using a `file:` URI with `mode=ro` and `uri=True`; repeated DB/log/cache digests were identical and source bytes remained unchanged. The final read-only real-resource baseline was database `c31f80875458d37e7b9badf086a5ff904a73d1d7f2ef1f5ab716c1f2c9755af3`, log `ece5af0377c0aa6c63149055a5f45d795a86ec63c330d44d27b27ec9c0178cb5`, and TTS cache `138263700e062272f93b941cebdb36340d3840c03366e638c9f10e3db684030d`.
- Socket seam: `127.0.0.1` and `::1` delegated to the injected connect function; `example.invalid:443` wrote the disposable tripwire and raised before a connect.
- Route seam: all eleven URL rows used one `urlsplit` predicate. Exact `http://127.0.0.1:<port>` called `continue_()`; HTTPS, localhost, IPv6, userinfo, wrong/missing/invalid port, remote host, and non-HTTP values wrote the disposable egress tripwire and called `abort("blockedbyclient")`.
- Teardown seam: the deterministic fake-process trace was `close:page → close:context → close:browser → terminate → wait:5 → kill → wait:5 → verify`. Verification could not run before confirmed exit.
- Actual server health, page-specific routing, service-worker block, absence of runtime tripwires, and post-server real-resource equality remain unexecuted browser evidence because the artifact gate failed first.

## Verification

```text
./.venv/bin/python -m pytest tests/test_frontend_foundation.py -q
# 9 passed

./.venv/bin/python -m pytest tests/browser/test_child_shell.py -q \
  -k '<all no-browser source/parser/import/seam/predicate slices>'
# 34 passed, 16 deselected

node --unhandled-rejections=strict --test tests/frontend/child/*.test.mjs
# 241 passed, 0 failed

DISABLE_EXTERNAL_AI=1 ./.venv/bin/python -m pytest -q tests --ignore=tests/browser tests/e2e.py
# 222 passed

node --check app/frontend/child/browser.mjs
./.venv/bin/python -m py_compile tests/browser/conftest.py tests/browser/child_server.py tests/browser/test_child_shell.py
git diff --check
# all exited 0
```

The isolated browser-gated selector exited nonzero exactly as required:

```text
test_loopback_server_uses_disposable_resources
# ERROR before Popen:
# browser provisioning: NO-GO; missing
# /Users/lddmay/Library/Caches/ms-playwright/chromium-1234
# /Users/lddmay/Library/Caches/ms-playwright/chromium_headless_shell-1234
```

## Commit and review status

- Implementation commit: `008dd1c` (`feat(child): compose browser shell`), with an exact eight-of-eight cached whitelist and clean cached diff.
- The first independent implementation review returned **NO-GO** with two P1 findings and one P2 report finding: gate 1 ignored stderr; chat/completion lacked navigation-time default interception; and this status section had not yet recorded the implementation hash/review outcome.
- Remediation RED/GREEN: an stderr-only valid v1234 result and the five-route fail-closed registry were added to the pure suite. Before implementation, both new selectors errored on missing fixtures; the reviewer's direct stdout/stderr reproduction independently showed the existing gate rejected a valid stderr-only dry run. After the fix both selected tests pass, gate 1 scans combined captured output, and the child page owns all five deterministic default interceptors before yield/navigation.
- First remediation commit: `6839819` (`fix(child): close browser fixture isolation gaps`), limited to `conftest.py`, `test_child_shell.py`, and this report.
- The second independent review confirmed the first three findings closed, then returned **NO-GO** on one new P1: the five default business interceptors were page-owned, while the health-fallback path creates a second page from the same context. It also flagged this report's stale top-level implementation status as P2.
- Context-route RED/GREEN: a source-order regression first failed because `install_fail_closed_business_routes(context, port=child_server.port)` was absent. The fixture now installs all five defaults on the browser context before `context.new_page()`, removes the page-owned registration, and the focused regression passes. This makes the initial page and every later page inherit the same fail-closed defaults.
- Context-route remediation commit: `65f19539a3fd6d14690fd20163e0746636269b64` (`fix(child): isolate every browser fixture page`), limited to `conftest.py`, `test_child_shell.py`, and this report.
- Final independent re-review: **GO** for implementation and isolation at `65f19539a3fd6d14690fd20163e0746636269b64`. The reviewer confirmed the five defaults are context-owned before any page, cover the health-fallback second page, preserve page-route exact-origin overrides, and passed the focused regression, Python compile, and diff check without launching a browser, server, Popen, installer, or network.
- Browser runtime evidence remains **NO-GO** solely because the required local Playwright v1234 Chrome for Testing and Headless Shell artifacts are absent. No browser-runtime claim is made.
