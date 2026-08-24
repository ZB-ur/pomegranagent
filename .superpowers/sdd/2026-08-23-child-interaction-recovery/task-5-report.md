# Child Task 5 Report — Deterministic Speech Recognition Lifecycle

## Boundary and repository evidence

- Start HEAD: `0f29641f145666989ac3f923fcbac5268523a1ca`, the independently approved Child Task 4 boundary.
- Owned paths only: `app/frontend/child/speech.mjs`, `tests/frontend/child/speech.test.mjs`, and this ignored report.
- Existing dirty paths `.workbuddy/memory/2026-08-22.md`, `docs/superpowers/specs/2026-08-23-interaction-stabilization-design.md`, `.superpowers/brainstorm/`, and `docs/superpowers/plans/` were retained unchanged and not staged.
- This report is force-staged with the implementation commit. Its task handoff records final HEAD because a Git object cannot contain its own final hash.

## TDD evidence

1. With only the first test file present and no production module, the focused strict command produced the real expected RED:

   ```text
   Error [ERR_MODULE_NOT_FOUND]: Cannot find module
   '/Users/lddmay/AiCoding/pomegranagent/app/frontend/child/speech.mjs'
   imported from .../tests/frontend/child/speech.test.mjs
   ```

   Node reported one failed test file, zero passing tests, and no production `speech.mjs` existed.

2. The complete strict matrix was then written before production code. Its first implementation run was `12/14` green. Both red rows were test-fixture/expectation defects, corrected against the frozen brief rather than relaxed:

   - The timer-rearm assertion referred to the first generation's timer after it had fired. The contract requires clearing the *current generation's* prior timer, so the regression assertion now captures `secondInitial` and proves it is cleared before the result rearm.
   - The synchronous-error fake emitted `onerror` on every generation, preventing the reentrant replacement generation from reaching its required initial timer. The fake now emits only on generation one; the regression assertion proves exactly two instances, the second current instance, and exactly one live timer.

3. Pre-review focused strict runs were green twice: `16/16` passing and `0` failing each time, with no open fake timers or unhandled rejections. The pre-review full strict child Node suite was `118/118` passing and `0` failing.

## Frozen lifecycle evidence

| Contract area | Evidence |
| --- | --- |
| Public surface | The only export is `createSpeechController`; it returns a frozen object with exactly `start`, `stop`, `dispose`, `isListening`, and the current-run `recognition` getter. |
| Recognition generation | Every accepted start creates/configures a new injected recognizer (`zh-CN`, interim and continuous true). Listening duplicate starts are inert; stopping starts suppress/abort the old generation; stale result/error/end callbacks are identity-and-generation inert. |
| Transcript assembly | Per-index final/interim maps consume `resultIndex`, preserve final chunks, remove disappeared interim chunks, render ordered browser chunks with only combined-string trim, and emit final/empty only at terminal end. |
| Silence and stop | The internal interval is always exactly `1500`; no dependency timing override is read. Start/result/speech-end maintain at most one current listening timer. Manual/silence stop enters stopping before recognizer stop, preserves late final results, and never rearms. |
| Terminal/error behavior | Natural end, no-speech, permission, audio, unsupported, generic recognition, constructor/configuration/start, timer, and recognizer-stop cases emit the exact one approved terminal shape. Cleanup/output state is linearized first; `onerror → onend` is one-shot. |
| Reentrancy/cleanup | Synchronous `onerror`, `onend`, timer firing, `onEvent` start/dispose, cleanup abort reentry, `setTimer`/`clearTimer`/stop throws, and suppressed cleanup failures are covered. Returned synchronous timer handles are immediately cleared if their callback already changed the run. |

## Reviewer-GO brief precedence

The legacy plan sample conflicts with the approved Task 5 brief: it exposed a caller-controlled `silenceMs`, set `continuous:false`, omitted the getter/generation lifecycle, and treated `no-speech` as an error-state mapping. The implementation follows the reviewer-GO brief instead: fixed `1500`, `continuous:true`, exact getter surface, and `{type:'empty'}` for no-speech.

## Final verification to accompany commit

```text
node --unhandled-rejections=strict --test tests/frontend/child/speech.test.mjs  # 21 pass (twice after correction)
node --unhandled-rejections=strict --test tests/frontend/child/*.test.mjs       # 123 pass after correction
node --check app/frontend/child/speech.mjs
node --check tests/frontend/child/speech.test.mjs
git diff --check
git show --check
```

Residual risk: Task 7 alone owns browser click/Space composition and mapping these normalized speech events into machine events; this task intentionally has no browser microphone or DOM integration.

## Independent-review lifecycle correction

- Follow-up start HEAD: `75775ce0a121a6ae1f8ad119e85a711ae4ee7acd`.
- The reviewer supplied four independently failing RED cases before this correction. A stopping supersede whose old `abort()` synchronously called `dispose()` incorrectly constructed a second recognizer (`2 !== 1`). A manual `clearTimer()` reentry through dispose still called old `stop()` (`1 !== 0`). Constructor/configuration/start failures with a throwing `name` accessor escaped `start()` as `name trap`. Manual/silence `stop()` throws performed no abort cleanup (`['stop']` rather than `['stop','abort']`).
- `start()` now rechecks `disposed`, `suppressing`, and current-run identity immediately after suppression. `requestStop()` separately distinguishes its own timer-clear failure (still best-effort stops) from a reentrantly invalidated run (never calls an obsolete recognizer). Synchronous-error name lookup is trap-safe. The later follow-up below refines cleanup further: after a manual/silence `stop()` was attempted, an abort failure never retries that same `stop()`.
- Additional regression coverage exercises `clearTimer() → controller.start()`: it suppresses the old generation, leaves the replacement current, leaves exactly one timer, and does not stop the old recognizer. All cleanup reentry fixtures retain zero stale events and one exact terminal event where an error is required.
- During final cleanup review, the composed local `clearTimer` throw followed by a `stop()` throw was also made RED: it initially stopped without attempting abort. The stale local-failure branch now performs abort cleanup with start suppression, so it remains one `SPEECH_FAILED` while releasing the recognizer.
- Correction verification: focused strict ran twice at `21/21` passing; the full child strict suite ran at `123/123` passing. Syntax checks, `git diff --check`, and post-commit `git show --check` accompany the follow-up commit.

## Second independent-review correction — hostile external boundaries

- Follow-up start HEAD: `f715cf76ae52dfb3a038ed4996fc7885b76808d7`.
- All five requested cases were first made independently RED. (A) A manual/silence `stop()` throw followed by an `abort()` throw made the old cleanup call `stop()` a second time: actual call order was `['stop', 'abort', 'stop']`; the frozen lifecycle permits exactly `['stop', 'abort']`. (B) Constructor disposal and each `lang`/`interimResults`/`continuous` setter disposal/replacement continued setup on an invalid run. (C) A `stop` getter that synchronously replaced the run was read twice and still invoked the old stop. (D) `abort`/`stop` return values with a throwing `then` getter were swallowed. (E) an abort thenable's synchronous/asynchronous reentrant `start()`/`dispose()` created an unwanted replacement generation or escaped the cleanup boundary.
- The correction linearizes `current = run` before construction, proves listening/current identity after constructor, every assignment, `start` getter/call, timer operation, and before a captured `stop` method call. It captures `stop` once, records `stopAttempted`, and gives terminal cleanup that fact so a failed first stop is never retried. Cleanup still attempts `stop` after an abort failure when no earlier stop was attempted.
- `consumeThenable()` intentionally reads and calls `then` directly so a getter/call exception is handled as the synchronous dependency failure required by the brief. Cleanup-owned thenables hold a suppression barrier through their resolve/reject callback, preventing synchronous or microtask reentry from creating another generation; terminal/current checks make stale callbacks inert.
- A final timer-boundary audit was also independently RED: a `setTimer` returned value with a throwing `then` getter initially emitted no event (`[]`). The same explicit thenable boundary now maps it to the one current `SPEECH_FAILED`; the test also proves the `clearTimer` path.
- Latest verification before this follow-up commit: focused strict twice, each `26/26` passing; full strict child Node suite `128/128` passing; all fakes/injections only, with strict unhandled-rejection mode and zero fake timers at each lifecycle assertion. Node syntax, diff, staged-path, and post-commit show checks are recorded with the commit handoff.

## Third independent-review correction — raw construction and bounded thenable failures

- Follow-up start HEAD: `f5b9058be18b28cf1cec6cf21ea957892134a036`.
- Each new row was independently RED before production code changed. A constructor that synchronously called `dispose()` returned a raw recognizer with `abortCount === undefined` instead of exactly one abort, because cleanup ran while `run.recognition` was null. A thrown `clearTimer()` terminalized the run, then a hostile old `stop` getter reentered `start()` and produced two instances (`2 !== 1`). Native rejected thenables from each of `recognition.start`, `setTimer`, `clearTimer`, `recognition.stop`, and cleanup `abort` were treated as success: runs remained listening/stopping or abort failed to fall back to one stop. A never-settling cleanup thenable permanently blocked a later legitimate start (`1 !== 2`). Finally, both `resolve(); queueMicrotask(start)` and `reject(); queueMicrotask(start)` created a replacement generation (`2 !== 1`), as did a throwing cleanup `then` getter that queued a microtask before throwing.
- Raw construction now assigns the returned instance to the already-installed run before the invalidation check. Cleanup does not mark itself started while the raw instance is unavailable; the invalidated return path enters the same suppression section and aborts that exact instance once, with no configuration or recognition start.
- `clearTimer`'s synchronous failure still owns the one `SPEECH_FAILED`, but its required old `stop` best-effort call now executes in a nested suppression critical section. Therefore a getter/call cannot create a replacement generation while the old terminal cleanup is being consumed.
- Thenable rejection is a dependency failure, not fulfillment: start, set-timer, clear-timer, and stop rejection handlers first prove the captured run is still current before terminalizing it. A cleanup abort rejection uses only the captured old recognizer and its per-run `cleanupFallbackStarted`/`stopAttempted` guards to attempt exactly one fallback stop without a duplicate manual/silence stop or a second terminal event. Native promise rejection is consumed with a rejection callback, so strict unhandled-rejection mode remains clean.
- **Frozen-contract boundary for thenables:** Web Speech `start`/`stop`/`abort` and timer functions are specified as void; a returned thenable is an adversarial injected boundary, not a new asynchronous product protocol. The brief requires safe direct reentry, but cannot distinguish a future callback's `controller.start()` from a legitimate later public start. The implementation therefore uses no timer and no permanent quarantine. For cleanup only, a fence opens before reading `then`, remains active through the `then` call and one language-level Promise microtask scheduled after that call returns, and is scheduled exactly once even if `resolve`/`reject` fires repeatedly, never fires, or the scheduling primitive throws. This protects getter/call and their directly queued microtask reentry. It then releases independently of settlement; later callbacks are handled only against their captured generation/identity, while a later legitimate `start()` remains allowed. The never-settle and resolved/rejected direct-microtask RED rows prove both sides of that boundary. Independent review should assess this causal boundary rather than require an unprovable forever/global-time distinction.
- Latest verification before this follow-up commit: focused strict `35/35` passing and full strict child Node suite `137/137` passing, all under `--unhandled-rejections=strict`; each new fixture uses only injected fake recognition/timer behavior and asserts no retained fake timer where applicable. The required second focused run, syntax/diff checks, precise staging, and post-commit show check accompany this commit handoff.

## Fourth independent-review correction — clearTimer boundary and returned chains

- Follow-up start HEAD: `a6c8b59cdb9935ff78d3333c10c3a5f624c0e4ee`. The final commit ID is reported in the task handoff because a commit cannot contain its own object ID.
- Independent REDs were captured before this production change. The strict focused command first reported `0/3` passing: an invalid synchronous timer arm let `clearTimer()` create a second recognizer (`2 !== 1`); natural terminal cleanup let its queued replacement create a second recognizer (`2 !== 1`); and a strict subprocess for `abort() -> { then() { return Promise.reject(...) } }` showed fallback stop count `0` and then the unhandled `nested abort rejection`. After the frozen void-boundary decision, a separate exact RED preserved the legal path: a void terminal `clearTimer()` incorrectly blocked the caller's immediate next `start()` (`1 !== 2`).
- `invokeClearTimer()` now captures the clear return while terminal/invalid-handle cleanup is synchronously suppressed. A returned object/function with a callable `then` (or a throwing `then` getter) is consumed behind the same bounded cleanup fence, so direct getter/call/microtask reentry cannot create a replacement generation. The manual nonterminal clear path remains unfenced, preserving its documented supersede/replacement behavior.
- The frozen void contract is deliberately narrower: ordinary `clearTimeout`-style void returns leave no fence, so a natural end can accept an immediate subsequent public `start()`. A void implementation that privately queues a future `start()` is observationally indistinguishable from a legitimate future public start; the brief authorizes no permanent/global quarantine. The hostile direct-microtask fixture therefore returns a consumable thenable, while a separate void fixture proves the synchronous legal restart.
- `consumeThenable()` now captures one distinct return from its first `then.call`, consumes that one returned native/cross-realm promise or thenable, and routes its rejection through the same once-only captured-run handler. It rejects source identity cycles and intentionally does not recursively chase returned chains. Thus cleanup-abort failure takes exactly one fallback `stop()` and the strict subprocess exits without an unhandled rejection.
- GREEN evidence after the correction: selected strict regressions `4/4`; complete focused speech suite `39/39`; complete `tests/frontend/child/*.test.mjs` suite `141/141`, all under `--unhandled-rejections=strict`. All fixtures remain injected; no microphone, browser, real timer, network, storage, or database is used.
- Owned paths remain only `app/frontend/child/speech.mjs`, `tests/frontend/child/speech.test.mjs`, and this report. Pre-existing dirty paths `.workbuddy/memory/2026-08-22.md`, `docs/superpowers/specs/2026-08-23-interaction-stabilization-design.md`, `.superpowers/brainstorm/`, and `docs/superpowers/plans/` were retained and are outside the staged set.

## Fifth independent-review correction — noncallable then getter fence

- Follow-up start HEAD: `5487036c453d83ce8793798103da0d98b5c5f77a`; final commit ID is supplied in the handoff because a commit cannot contain its own ID.
- Two independent strict REDs preceded production changes. An invalid synchronous timer arm whose returned-handle `clearTimer()` object had a `then` getter that queued `controller.start()` and returned `undefined` created a replacement (`2 !== 1`). The same noncallable getter on natural terminal `clearTimer()` also created a replacement (`2 !== 1`).
- `consumeThenable()` now opens a requested cleanup fence immediately after confirming an object/function value and before reading `value.then`. Getter throw, noncallable getter, and callable getter/call all release that exact fence once. Primitive/undefined returns still exit before any fence, preserving the frozen void clearTimer immediate-restart behavior.
- GREEN evidence after the minimal move: targeted strict regressions `2/2`; complete focused speech suite `40/40`. Final second focused run, full child suite, syntax/diff, exact staging, and post-commit show checks accompany this follow-up commit.
