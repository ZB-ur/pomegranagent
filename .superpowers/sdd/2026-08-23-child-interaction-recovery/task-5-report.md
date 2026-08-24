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
- `start()` now rechecks `disposed`, `suppressing`, and current-run identity immediately after suppression. `requestStop()` separately distinguishes its own timer-clear failure (still best-effort stops) from a reentrantly invalidated run (never calls an obsolete recognizer). Synchronous-error name lookup is trap-safe. Stop failure terminal cleanup attempts `abort()`, then attempts `stop()` exactly once more only when abort itself throws, without recursive terminal emission.
- Additional regression coverage exercises `clearTimer() → controller.start()`: it suppresses the old generation, leaves the replacement current, leaves exactly one timer, and does not stop the old recognizer. All cleanup reentry fixtures retain zero stale events and one exact terminal event where an error is required.
- During final cleanup review, the composed local `clearTimer` throw followed by a `stop()` throw was also made RED: it initially stopped without attempting abort. The stale local-failure branch now performs abort cleanup with start suppression, so it remains one `SPEECH_FAILED` while releasing the recognizer.
- Correction verification: focused strict ran twice at `21/21` passing; the full child strict suite ran at `123/123` passing. Syntax checks, `git diff --check`, and post-commit `git show --check` accompany the follow-up commit.
