# Task 3 Report — Validated Child API Adapter

## Boundary and ownership

- Started at the required boundary
  `87669808c2b325143055248fdd6f6c62a81e2958`.
- Owned changes only: `app/frontend/child/api.mjs`,
  `tests/frontend/child/api.test.mjs`, and this report.
- Preserved unrelated dirty paths: `.workbuddy/memory/2026-08-22.md`,
  `docs/superpowers/specs/2026-08-23-interaction-stabilization-design.md`,
  `.superpowers/brainstorm/`, and `docs/superpowers/plans/`.

## RED → GREEN evidence

1. Before any production adapter existed, the strict focused test command
   failed with the expected `ERR_MODULE_NOT_FOUND` for
   `app/frontend/child/api.mjs` (0 passing, one failing test file).
2. The first minimal adapter run passed 15 of 16 tests. The remaining failure
   established that `bootstrapBrowserChildAPI` is an async version-gate
   boundary: missing globals must reject as a promise rather than throw from a
   synchronous factory call. Changing only that factory to `async`/`await`
   produced the intended rejection while retaining the original gate error
   object.
3. The strict focused suite then ran twice with 16 passing tests, no failures,
   and no unhandled rejections. The complete child Node suite has 76 passing
   tests and no failures.
4. A final frozen-input audit added RED cases for non-RFC UUID version/variant
   nibbles, non-fixed chat rounds, over-2,000-character input, and the
   impossible `{configured:false, authenticated:true}` teacher status. The
   adapter now rejects all four locally before their external boundary; the
   focused strict suite again ran twice with 16 passing tests.

## Contract evidence

- `createChildAPI(duckAPI, duckAuth)` is entirely injection-based and returns
  one frozen object with exactly the ten approved methods. It uses only
  `duckAPI.request` for HTTP: explicit JSON response types for roster, active,
  chat, and completion; the frozen paths, sequence keys, signal/request ID,
  unmodified chat DTO, and one-field completion DTO; and encoded blob TTS with
  the fixed 10,000 ms timeout. TTS returns the Foundation-validated Blob by
  identity.
- Health validation requires string `release_id`, `api_version`, and
  `schema_version`, app database mode, and string worker status. `ready()`
  calls Foundation `DuckAPI.ready()`, so it consumes the Task 0 shared gate
  attempt rather than starting an independent version request.
- Pipeline responses reject unknown own keys at every frozen strict boundary:
  roster children, active wrapper/conversation/messages, chat, and completion.
  Active conversation validation includes child scope, revision/round zero
  boundaries, strictly increasing message IDs, and the empty/final-message
  last-ID rule. Chat enforces canonical submitted UUID identity, established
  conversation scope, distinct message IDs, and both directions of ended/end
  reason semantics. Completion checks both submitted IDs, save/status/time,
  positive counters/jobs, replay flag, and the forward-compatible analysis
  union `pending|processing|succeeded|failed`.
- The actual backend confirms `StrictResponseModel(extra='forbid')` for the
  roster, active, chat, completion, and nested message DTOs. Its currently
  emitted completion fixture is `pending`; the wider adapter union follows the
  frozen child contract. Foundation `shared/api.js` confirms that
  `bootstrapVersionGate()` and `ready()` use one cached promise.
- Only `api.mjs` resolves `globalObject.DuckAPI` and `globalObject.DuckAuth`.
  The browser factory validates both injections, invokes the version gate once,
  waits for success before creating the adapter, and preserves a rejected gate
  object by identity with zero request/auth effects. No adapter path catches or
  remaps an upstream synchronous or asynchronous exception.
- Local malformed IDs, PINs, text, and chat DTOs fail as `TypeError` before a
  transport/auth call. A chat UUID must use lowercase canonical hyphenation,
  version nibble 1–8, and RFC variant 8/9/a/b; `max_rounds` is exactly `3`, and
  submitted text is 1–2,000 characters. Teacher status also rejects the
  impossible unconfigured/authenticated pair. Malformed successful upstream
  payloads instead become a
  constructor-independent, prototype-normalized injected `APIError` with
  `status:0`, `code:'INVALID_RESPONSE'`, empty field errors, retryability, and
  null request/cause fields.

## Verification

```text
node --unhandled-rejections=strict --test tests/frontend/child/api.test.mjs
node --unhandled-rejections=strict --test tests/frontend/child/api.test.mjs
# 17 passing each run after the review remediations

node --unhandled-rejections=strict --test tests/frontend/child/*.test.mjs
# 77 passing after the independent-review remediation

rg -n 'fetch\(' app/frontend/child
rg -n 'DuckAPI|DuckAuth' app/frontend/child --glob '!api.mjs'
# both intentionally exit 1 with no matches

node --check app/frontend/child/api.mjs
node --check tests/frontend/child/api.test.mjs
git diff --check
```

## Commit

- Message: `feat(child): bind flow to reliable API contracts`
- Staged paths: `app/frontend/child/api.mjs`,
  `tests/frontend/child/api.test.mjs`, and this report only.

## Independent-review remediation

- The independent review of `660122e` identified two malformed-success gaps:
  JavaScript `Date.parse()` normalized impossible calendar days (for example,
  `2026-02-30`), and chat responses could exceed the submitted fixed three
  rounds or claim `max_rounds` before round three.
- RED: the added UTC calendar and chat-boundary cases produced 14 passing and
  3 failing focused tests. The failures were the expected missing rejections
  for `round:4`, `round:1/end_reason:'max_rounds'`, and date strings accepted
  only because `Date.parse()` normalizes them.
- GREEN: completion timestamps now require RFC3339 UTC `Z` form and field-wise
  real calendar/time equality after UTC construction; fractional seconds and a
  real leap-day timestamp remain accepted. Chat now rejects a round above the
  submitted `max_rounds:3`, and only allows `end_reason:'max_rounds'` at round
  three. All malformed successful values still flow through the injected
  prototype-normalized `INVALID_RESPONSE` path.
- Final evidence: focused strict suite passed twice with 17 tests each; the
  full child Node suite passed 77 tests. Follow-up commit message:
  `fix(child): reject impossible chat and completion responses`.

## Second independent-review remediation

### Commit chain

1. `660122e` — `feat(child): bind flow to reliable API contracts`
2. `7d7beec` — `fix(child): reject impossible chat and completion responses`
3. This follow-up — `fix(child): close response boundary semantics`

### RED → GREEN evidence

- RED: extending the existing strict matrices produced 14 passing and 3
  failing focused tests. The failures were the expected missing rejections for
  a zero-length roster name, a third-round continuation/`complete` outcome,
  and `0000-01-01T00:00:00Z`.
- GREEN: roster identity now requires a string with `length > 0` without
  trimming, so whitespace-only backend names remain compatible with the
  machine's frozen normalization contract. With fixed `max_rounds:3`, a
  response at round three is now accepted if and only if it is
  `ended:true/end_reason:'max_rounds'`; continuing or `complete` responses are
  rejected, while lower rounds retain their legal continue and complete paths.
  UTC timestamps reject years below one and continue to accept backend-form
  `Z` values, leap days, and both absent and multi-digit fractional seconds.
- Final evidence: focused strict suite passed twice with 17 tests each; the
  complete child Node suite passed 77 tests without network or application-DB
  access. The same injected `INVALID_RESPONSE` path handles each malformed
  successful response.
