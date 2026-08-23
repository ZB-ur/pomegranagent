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

The focused strict suite was run twice consecutively after the final matrix;
each run reported 19 passing tests, 0 failures, and no unhandled rejections:

```text
node --unhandled-rejections=strict --test tests/frontend/child/tts.test.mjs
node --unhandled-rejections=strict --test tests/frontend/child/tts.test.mjs
```

Final checks also run `node --check` on both new ES modules and
`git diff --check` before staging the three owned paths.

## Commit

- Message: `feat(child): guarantee TTS fallback and settlement`
- Files: `app/frontend/child/tts.mjs`,
  `tests/frontend/child/tts.test.mjs`, and this report.
