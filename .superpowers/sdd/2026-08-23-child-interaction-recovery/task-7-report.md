# Child Task 7 Report — Recoverable Diary Effect Orchestrator

## Boundary and ownership

- Exact start HEAD: `3656a8beb34befe30e6dafbfd8917ce252bc599f`, the independently approved Child Task 6A boundary.
- Owned product paths: `app/frontend/child/app.mjs` and `app/frontend/child/machine.mjs`.
- Owned test paths: `tests/frontend/child/app-effects.test.mjs` and `tests/frontend/child/machine.test.mjs`.
- This ignored report is force-staged with the implementation commit. The implementation commit is recorded as pending here because a Git commit cannot contain its own object ID; a report-only follow-up records the final hash.
- Existing user changes in `.workbuddy/memory/2026-08-22.md`, `docs/superpowers/specs/2026-08-23-interaction-stabilization-design.md`, `.superpowers/brainstorm/`, and `docs/superpowers/plans/` remained outside Task 7 and were not staged.

## TDD evidence and corrections

1. The first strict focused run was a real RED: `tests/frontend/child/app-effects.test.mjs` failed with `ERR_MODULE_NOT_FOUND` because `app/frontend/child/app.mjs` did not exist.
2. Construction/event ordering then produced a real TDZ RED when injected `createSpeech` synchronously emitted an event before the lifecycle binding existed. The implementation now initializes lifecycle storage first, queues construction-time events, and drains only after the exact speech surface and initial render are valid.
3. The following behavioral REDs were captured before their corresponding fixes:
   - a current speech partial rendered but did not announce, and a synchronous final remained in `listening` instead of creating and persisting one canonical draft before chat;
   - destroy after roster entry registration left `abortCalls === 0` rather than one and could allow the deferred work invocation;
   - a recovery result pairing `loading_roster` with `storageAction:'keep'` persisted the loading copy instead of rejecting the invalid pair;
   - a successful completion whose `completed` save failed was relabeled `COMPLETE_RESPONSE_INVALID` instead of remaining the no-write `LOCAL_STORAGE_FAILED` recovery;
   - a synchronous `store.load` callback could reenter `start()` and advance welcome into roster selection during the external-call boundary;
   - a reentrant `bootstrapAPI` callback could begin a second factory chain from the same dependency record;
   - a `SUBMIT_SUCCEEDED` save failure still started reply TTS, creating speech for an unpersisted response;
   - destroy discarded returned rejecting cleanup thenables from speech, TTS, and view (`then` call counts were all zero), risking unhandled rejections.
4. Each RED received a minimal scoped correction: registered-entry cancellation and epoch checks, explicit recovery outcome validation, transition-result checking before downstream effects, one synchronous external-call critical section, same-dependency bootstrap exclusion, and unified cleanup-thenable absorption.
5. A few failures were test-fixture timing/observability issues rather than product behavior and were corrected without weakening the contract: completion promises required one additional consumed-microtask flush; one overridden chat fake needed to record its invocation before an assertion could observe it. Controller, roster-cardinality, replay, render, Space, and most reentrancy additions were direct GREEN coverage of already-correct generic paths and are not represented as implementation REDs.

## Delivered contract

| Area | Evidence |
| --- | --- |
| Public composition | `app.mjs` exports exactly `createChildApp` and `bootstrapBrowserChildApp`; it contains no browser globals. Bootstrap preflights the same ready promise, exposes a strict frozen API facade, blocks same-dependency reentry, transfers ownership atomically, and cleans partial composition in reverse order. |
| State machine | `BEGIN_RECOVERY` is legal from the eleven post-START states and remains illegal from `welcome`. Exhaustive legal and complementary illegal matrices retain frozen valid snapshots. |
| Persistence and recovery | START/bootstrap bridges never overwrite durable state. Merge outcomes are validated, `clear` precedes resolution, `keep` never mutates first, loading continuation discards old local input, and local drafts retain their exact request IDs across controller/read failures. |
| Effect ownership | `roster`, child-scoped active reads, recovery, speech, chat, TTS, and completion use keyed injected controllers plus app/entry epochs. Cancellation before invocation yields zero business calls; late fulfillment after destroy is state/view/store inert. |
| Conversation integrity | Draft persistence precedes chat; retry preserves text/request/time; replay IDs dedupe only when content matches; history conflicts become nonretryable `CHAT_RESPONSE_CONFLICT`; reply TTS starts only after successful persistence. |
| Completion integrity | TTS settlement must persist `saving_conversation` before one exact completion call. Invalid responses use `COMPLETE_RESPONSE_INVALID`; ordinary failures preserve the message boundary; `CONVERSATION_CHANGED` rereads durable local and active state. Pending-completion reload starts completion only, including replay, with zero chat or reply TTS. |
| Reentrancy and cleanup | Save, clear, render, announce, controller abort, speech start/stop/dispose, TTS cancel/dispose, and view destroy callbacks cannot invoke public actions reentrantly. Synchronous speech events are queued against their registered entry. Cleanup rejecting thenables are consumed once under strict unhandled-rejection mode. |
| Input policy | Global Space is accepted only when derived record controls are enabled, the target is noninteractive, no dialog is active, and the event is fresh/unprevented. The first accepted Space starts once; the second requests one manual stop; welcome/loading/recovery and rejected variants never prevent default. |

## Final verification

```text
node --unhandled-rejections=strict --test tests/frontend/child/machine.test.mjs tests/frontend/child/app-effects.test.mjs
# 107 passed, 0 failed — twice from final source

node --unhandled-rejections=strict --test tests/frontend/child/*.test.mjs
# 237 passed, 0 failed

node --check app/frontend/child/app.mjs
node --check app/frontend/child/machine.mjs
node --check tests/frontend/child/app-effects.test.mjs
node --check tests/frontend/child/machine.test.mjs
git diff --check
```

All tests use injected API, storage, speech, TTS, controller, and view fakes. No browser, microphone, network, provider, application database, log, or cache resource is used by Task 7 evidence.

## Residual downstream scope

- Task 6B owns the real `index.html`/browser entry, DOM policy, loopback browser fixture, two-viewport evidence, and static Foundation handoff. Its approved brief must receive this task's final 40-character HEAD before execution.
- Task 8 owns teacher PIN/relock and teacher-authorized text recovery; Task 7 intentionally exposes no teacher input or PIN state.
- The local Playwright package still lacks the required v1234 CFT and Headless Shell artifacts. Task 7 is Node-only and makes no browser acceptance claim.

Implementation commit: `2cfa437d83b8dd43ca48e1b5075b7161ad13769b` (`feat(child): orchestrate recoverable diary effects`).

## Independent-review remediation — guarded thenables and bootstrap uniqueness

- Review start HEAD: `dd3fd7e` (implementation plus report self-reference). The independent reviewer returned **NO-GO** with no P0 and four P1 production findings.
- All four findings were first encoded as exact strict REDs; the selected run was `0/4`:
  1. a rejected `event.code` getter reentered `recordToggle()` before keyboard policy rejection (`speechStart` was `1`, expected `0`);
  2. a roster result's hostile `then` getter/call ran after the external critical section and successfully destroyed the app;
  3. cleanup thenables whose `then()` returned a rejecting chain left all nested-consumption counters at `0`;
  4. `bootstrapAPI()` reentered with a different valid dependency object and created a second live factory chain instead of returning `null`.
- The correction packetizes external results in a frozen null-prototype envelope, manually adopts thenables, and runs work plus `then` getter/call access through the existing critical boundary. It captures and consumes a `then()` return chain without returning raw hostile values through Promise assimilation. Key-event field reads now use the same boundary.
- Bootstrap now owns one module-wide composition guard starting before dependency validation and ending in `finally`. It rejects every synchronous reentrant second chain regardless of dependency identity, while allowing a later sequential bootstrap after the first chain has settled.
- Cleanup helpers preserve exactly-once calls while consuming direct rejections and the captured returned chain. No new state, mutable busy flag, browser global, timer, API method, or storage field was added.
- GREEN evidence after remediation: selected regressions `4/4`; focused machine/app suite `111/111` twice from final source; full strict child Node suite `241/241`; syntax and diff checks accompany the follow-up commit.
- Remediation commit: `8e1a3832ef0e350ceb73459df0d1c9314fb95574` (`fix(child): guard hostile async boundaries`). A separate independent minimal re-review reran all four original P1 regressions at `4/4`, reread the corresponding implementation, returned **GO**, and reported no new finding.
