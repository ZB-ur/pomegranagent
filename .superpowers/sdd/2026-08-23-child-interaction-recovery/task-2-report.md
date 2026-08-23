# Task 2 Report — Five-Second TTS Fallback With Guaranteed Settlement

## Boundary and ownership

- Started from the required boundary
  `f1db35772a436816f18abd43191ac397c9332ff3`.
- Owned changes only: `app/frontend/child/tts.mjs`,
  `tests/frontend/child/tts.test.mjs`, and this report.
- Preserved unrelated dirty paths: `.workbuddy/memory/2026-08-22.md`,
  `docs/superpowers/specs/2026-08-23-interaction-stabilization-design.md`,
  `.superpowers/brainstorm/`, and `docs/superpowers/plans/`.

## Contract ruling

The historical five-second sample advanced a fake clock immediately after
`speak()`, while the frozen brief requires injected calls to run through
`Promise.resolve().then(...)`. A deferred loader has not subscribed to its
abort signal until a microtask runs, so those two details cannot share the
same fake ordering. The authoritative ruling preserves deferred invocation:
the normal 4,999/5,000 ms abort test flushes microtasks before advancing the
clock, and a separate no-flush test advances directly to 5,000 ms, proves that
browser fallback completes, then proves the later loader receives an already
aborted signal and cannot create URL/audio or settle again.

## RED → GREEN evidence

1. The first focused strict run was RED with the expected
   `ERR_MODULE_NOT_FOUND` for `app/frontend/child/tts.mjs` (the test module
   could not load; Node reported one failing test-file).
2. The initial two edge/timer tests became GREEN after the minimal one-shot
   Edge controller: 2 passing, 0 failing.
3. The browser-synthesis increment was RED: 2 existing edge tests passed and
   3 new default-browser/timeout/cancellation tests failed because no default
   browser fallback existed. Adding the injected synthesis fallback and its
   independent 15,000 ms timer made that set GREEN: 5 passing, 0 failing.
4. The completed strict matrix has 19 passing tests and 0 failures.

## Behavioral evidence

- Each `speak()` starts the cold timer synchronously, invokes injected work
  through deferred promise guards, and resolves only the exact two-field
  result shape (`mode`/`reason`) without rejecting.
- The fake clock specifies observable ordering rather than claiming an
  impossible same-tick JavaScript guarantee: playback observed before the
  timer wins as Edge; the timer observed first aborts Edge, pauses audio,
  revokes its URL once, and starts an independently live browser fallback.
  Captured late `onplaying`/`onended`, late blobs, and late browser settlements
  cannot overwrite the first result.
- Loader, URL, audio-factory, play throw/rejection, audio error, unavailable
  browser speech, browser error, and browser timeout all settle. The strict
  suite explicitly absorbs late request and browser rejections.
- Browser synthesis is built only from injected `speechSynthesis` and
  `SpeechSynthesisUtterance`; it has a separate 15,000 ms one-shot maximum.
  The edge timeout never pre-cancels that browser signal.
- Cancel, supersede, and dispose abort Edge, pause/detach audio, revoke URLs
  exactly once, cancel browser synthesis, clear both timer kinds, and settle
  immediately. A second cancel is idempotent; a superseding request settles
  before its successor loader begins; speak after dispose safely returns
  `cancelled/disposed`.

## Verification

Before independent review, the focused strict suite ran twice with 19 passing
tests. The independent review invalidated that earlier evidence. After the
review remediation, the focused strict suite ran twice with 29 passing tests,
0 failures, and no unhandled rejections; the full child Node suite reported
57 passing tests and 0 failures:

```text
node --unhandled-rejections=strict --test tests/frontend/child/tts.test.mjs
node --unhandled-rejections=strict --test tests/frontend/child/tts.test.mjs
node --unhandled-rejections=strict --test tests/frontend/child/*.test.mjs
```

Final checks also run `node --check` on both new ES modules and
`git diff --check` before staging the three owned paths.

## Commit

- Message: `feat(child): guarantee TTS fallback and settlement`
- Files: `app/frontend/child/tts.mjs`,
  `tests/frontend/child/tts.test.mjs`, and this report.

## Independent-review remediation

The original Task 2 commit was not approved because caller-supplied timeout
overrides changed product behavior; a hand-rolled abort signal was not a
native `AbortSignal`; cleanup only caught synchronous exceptions; and cleanup
callbacks could reenter `cancel`, `dispose`, or `speak` while the obsolete
request kept constructing browser fallback state.

### Review RED → GREEN

- The review regression set was first run against `a02ccf5`. It produced 21
  passing tests and 6 failing tests, covering overrideable timeouts, nonnative
  signals, missing controller handling, clear-timer reentrancy, pause
  reentrancy, and invalid input. Its async URL-revoke case also generated the
  strict-mode unhandled rejection that the old `safely()` helper missed.
- A final added regression for a rejecting `speechSynthesis.speak()` call was
  RED against the intermediate implementation: it timed out instead of
  returning `text/browser-error` and emitted an unhandled rejection. Browser
  speak is now invoked through a deferred guarded promise and its rejection is
  converted to the one-shot text result.
- The post-review focused suite has 29 passing tests and 0 failures under
  `--unhandled-rejections=strict`.

### Remediation evidence

- Product timings are constants: 5,000 ms cold start and 15,000 ms browser
  maximum. Callers cannot shorten either; fakes control clock advancement.
- With an injected native `AbortController`, the Edge loader receives a genuine
  native `AbortSignal`. A structurally conforming cross-realm or polyfill
  controller is accepted through the `{aborted,addEventListener,
  removeEventListener}` protocol without claiming it is an instance of this
  realm's native signal. Missing or structurally incomplete controllers bypass
  Edge safely into fallback without throwing. Edge and browser controllers
  remain distinct.
- Cleanup invocation absorbs both synchronous throws and thenable rejections,
  including `clearTimer`, abort, pause, URL revocation, browser cancellation,
  and synthesis cancellation. Main loader/audio/browser promises still use
  their own settlement paths rather than being swallowed as cleanup.
- Each reentrant side-effect boundary rechecks that its request remains active
  before it can create a browser aborter/timer or invoke `browserSpeak`.
  Regressions cover reentrant `clearTimer`, `audio.pause`, and a timer callback
  that fires before returning its handle; all leave zero timers and no stale
  browser start.
- Browser constructor/synchronous/async speak errors, missing dependencies,
  empty or non-string input, timer throws, and custom `onCancel` execution are
  all explicitly covered. `onCancel` is one-shot, and late browser results
  still cannot replace a cancellation result.

## Second independent-review remediation

### Commit lineage and RED → GREEN

- `a02ccf5 feat(child): guarantee TTS fallback and settlement` was the initial
  Task 2 delivery.
- `f315967 fix(child): harden TTS cleanup and timing contracts` was the
  cleanup/timing repair.
- `4b38f59 fix(child): preserve TTS terminal lifecycle ordering` was the
  terminal-lifecycle and signal-validation repair.
- The second review added three focused regressions against `f315967`; the
  strict suite was RED with 29 passing tests and 3 failures. They proved that
  invalid input wrongly outranked terminal disposal, an invalid second speak
  failed to supersede active work, and a malformed injected controller reached
  the Edge loader.

### Second-remediation evidence

- `speak()` now gives terminal disposal priority for every input. When live,
  it settles an existing request as `cancelled/superseded` before deciding that
  a new empty or non-string input is `text/invalid-text`; the invalid request
  creates neither timer nor loader work.
- A controller is considered usable only when `abort` is callable and its
  signal has boolean `aborted` plus callable `addEventListener` and
  `removeEventListener`. An injected native controller gives the loader a
  genuine native `AbortSignal`; a cross-realm/polyfill controller is accepted
  only for that structural protocol and is not described as a native-instance
  match. Only structurally incomplete controllers bypass Edge.
- Missing controller constructors use the
  `abort-controller-unavailable` fallback. Constructor failures and malformed
  abort/signal structures use `abort-controller-invalid`; both bypass Edge
  (`loaderCalls === 0`) and settle through the normal fallback path.
- The second-review focused strict suite ran twice with 32 passing tests and
  0 failures; the full child Node suite has 60 passing tests and 0 failures.
  Syntax checks and diff check also pass before the follow-up commit.

## Evidence wording correction

This final change is report-only: controller and test code are unchanged, so
the fresh 32/32 focused and 60/60 full-child evidence above is retained rather
than rerun for documentation wording alone.
