# Task 1 Report — Pure Child Interaction State Machine

## Boundary and ownership

- Started from the required boundary `195c7e3a4899b9ecb68b422d0834a3f43e3f02aa`.
- Owned changes only: `app/frontend/child/machine.mjs`, `tests/frontend/child/machine.test.mjs`, and this report.
- Preserved unrelated dirty paths: `.workbuddy/memory/2026-08-22.md`, `docs/superpowers/specs/2026-08-23-interaction-stabilization-design.md`, `.superpowers/brainstorm/`, and `docs/superpowers/plans/`.

## RED

Before production code existed, the focused Node suite was run:

```text
node --unhandled-rejections=strict --test tests/frontend/child/machine.test.mjs
```

It failed exactly with `ERR_MODULE_NOT_FOUND` for
`app/frontend/child/machine.mjs`. The test file had already specified the
twelve-state happy path, legal/illegal transition matrix, failures and retry,
completion boundaries, controls, recovery, reset, duplicate IDs, stale stop
flags, and mutation resistance.

## GREEN and invariants

- `machine.mjs` has exactly the five approved exports and no imports or browser/effect/API/timer/storage/UUID/DOM/speech dependencies.
- Every output snapshot is normalized, defensively copied, recursively frozen, and validated by `assertSnapshot`. Initial overrides, event data, and recovery snapshots therefore cannot mutate reducer-owned roster, child, messages, draft, or error data later.
- The reducer enumerates the twelve approved states and all authorized Task 1 event sources. All other state/event pairs throw.
- Roster entries are shape-validated and deduplicated by first appearance. Successful submissions require the matching draft request ID plus positive, distinct acknowledgement IDs; acknowledgement insertion checks IDs sequentially in child then diary order.
- Completion accepts only `conversation_saved: true` with matching conversation ID, last-message ID, and message count. Retryable failure retains the normalized draft and request identity; nonretryable submission and every completion failure preserve recovery context.
- `stopRequested` is reset for a fresh listening cycle and on every transition out of `listening`. `controlsFor` derives the sole child lock from state; recovery remains child-locked after `TEACHER_UNLOCKED`.
- `RESET` returns a fresh clean snapshot with distinct nested arrays.

## Verification

The focused suite was run twice consecutively after implementation; each clean
run reported `16` passing tests and `0` failures:

```text
node --unhandled-rejections=strict --test tests/frontend/child/machine.test.mjs
node --unhandled-rejections=strict --test tests/frontend/child/machine.test.mjs
```

The final verification also runs `node --check` on the module and test, plus
`git diff --check`.

## Commit

- Message: `feat(child): add explicit interaction state machine`
- Files: `app/frontend/child/machine.mjs`, `tests/frontend/child/machine.test.mjs`, `.superpowers/sdd/2026-08-23-child-interaction-recovery/task-1-report.md`

## Independent-review remediation

The independent review of `37cc270` found valid state-boundary gaps. Before
changing production code, the expanded focused suite ran RED with `27` tests:
`16` passed and `11` failed. The expected failures proved all of the following
missing behaviors: `revision: 0` acceptance; established-conversation ID
matching; both `ended`/`end_reason` consistency directions; replay conflict
rejection; saving/completed message-history and final-message boundaries;
positive completion message count validation; rejection of an incomplete
recovered completed snapshot; and an own `event.type` requirement.

The minimal remediation makes `revision` nullable/non-negative, rejects a
submit result that changes an established conversation, validates both end
semantics, and requires an own event type. It also validates the same persisted
conversation boundary in `saving_conversation` and `completed`: positive
conversation/last-message IDs, at least one message, and a final message whose
ID equals `lastMessageId`. Completion `message_count` is positive and must
still equal the local message length.

Replay acknowledgement dedupe now admits an already-known ID only when every
existing occurrence has the same role and text as the incoming child/diary
message. The ordered child-then-diary pass remains intact and result IDs remain
distinct. A second focused RED run (`28` total; `27` passed, `1` failed) proved
that a last-entry-only lookup could conceal an older conflicting duplicate; the
final scan fixes that case.

GREEN evidence after the remediation:

```text
node --unhandled-rejections=strict --test tests/frontend/child/machine.test.mjs
# 28 passed, 0 failed
```

Final verification reruns this exact strict suite twice, checks both ES modules
with `node --check`, and runs `git diff --check` before the follow-up commit.
