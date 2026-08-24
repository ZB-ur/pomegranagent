# Child Task 4 Report — Strict Session Storage and Recovery Merge

## Boundary and repository evidence

- Start HEAD: `49fe51679cf5671fae66870da3d76e2716501d61` (the independently approved Child Task 3 boundary).
- Owned implementation paths: `app/frontend/child/session-store.mjs`, `tests/frontend/child/session-store.test.mjs`, and this ignored report only.
- The existing dirty `.workbuddy/memory/2026-08-22.md`, the interaction design spec, `.superpowers/brainstorm/`, and `docs/superpowers/plans/` were inspected only and neither staged nor modified.
- This report is staged forcefully with the implementation commit; the task handoff records that commit's final HEAD because a Git object cannot contain its own final hash.

## TDD evidence

1. Before `session-store.mjs` existed, the focused strict Node command failed at module link with the expected real error:

   ```text
   Error [ERR_MODULE_NOT_FOUND]: Cannot find module
   '/Users/lddmay/AiCoding/pomegranagent/app/frontend/child/session-store.mjs'
   imported from .../tests/frontend/child/session-store.test.mjs
   ```

   Node reported one failing test file and zero passing tests; no production module was present.

2. The focused suite was then green three times while completing the boundary matrix: `23/23` passing, `0` failing, under `--unhandled-rejections=strict`.

3. The full child Node suite was green after the initial focused green: `100/100` passing, `0` failing, with strict unhandled rejections.

## Frozen interface evidence

| Surface | Evidence |
| --- | --- |
| Exports | Exactly `SESSION_KEY`, `createDraft`, `createSessionStore`, and `mergeRecovery`; key is `duck-diary.child-session.v1`. |
| Draft identity | Leading/trailing trim only; RFC-4122 v1–v8 UUID and canonical UTC `toISOString()` validation; injected UUID/clock each read once. |
| Stored schema | Explicit v1 construction of only approved root/child/message/draft/failure keys; all returned values are deep-frozen, copied, and independent. |
| Security projection | PIN/teacher/reply/raw error message and cause are excluded; only `{code,retryable}` is durable failure data. |
| Adapter failure semantics | Construction rejects malformed dependencies; `getItem`, `setItem`, `removeItem`, and throwing clocks retain original error identity; structural failure performs zero clock reads/writes. |

## Recovery-decision evidence

The focused tests cover all 13 authoritative decision-table rows: missing local clear outcomes; remote-active authority; unbound/matching-bound draft retries; all four independent server-binding forms; conversation safety; no-active draft recovery; both reachable child mismatch forms; pending completion and boundary absence; ended-chat and `COMPLETE_FAILED` reloads; teacher-only nonretryable recovery; retryable recovery refresh; remote-failure priority; malformed local-as-missing; and strict malformed tagged-union rejection.

Every merge outcome exposes only `{snapshot,storageAction}`, passes `assertSnapshot()`, resets `teacherUnlocked:false`, and is recursively frozen. The module consumes only `STATES`, `createInitialSnapshot()`, and `assertSnapshot()` from the state machine; it has no browser storage, network, database, or timer access.

## Final verification to accompany commit

```text
node --unhandled-rejections=strict --test tests/frontend/child/session-store.test.mjs  # 25 pass
node --unhandled-rejections=strict --test tests/frontend/child/*.test.mjs             # 102 pass
node --check app/frontend/child/session-store.mjs
node --check tests/frontend/child/session-store.test.mjs
git diff --check
git show --check
```

Residual risk: Task 7 must consume the documented `storageAction` before its reducer-legal recovery resolution and catch the intentionally propagated storage exceptions; no composition surface is owned or changed by Task 4.

## Decoder-hardening correction

Independent review found that pre-copy shape reads could invoke an accessor or Proxy trap before the local decoder's catch boundary, and the remote tagged-union normalizer could leak that arbitrary error instead of its required `TypeError`.

- RED: the new focused regression run had `23/25` pass and two expected failures. A local throwing `version` getter leaked `Error: local getter trap`; a remote getter/proxy case failed because it was not a normalized `TypeError`.
- GREEN: `decodeRecord()` now encloses every local structural read in its malformed-as-null boundary. Strict record and array validators require the normal `Object.prototype`/`Array.prototype` plus own enumerable data descriptors (frozen valid data remains acceptable). Remote tagged-union normalization encloses all structural reads and maps arbitrary trap errors to a fresh `TypeError`.
- Regression matrix: local and remote root accessor (throwing and nonthrowing), `ownKeys`, `get`, and `getPrototypeOf` Proxy traps, plus custom-prototype objects. Local rows resolve as missing with `clear`; remote rows reject as `TypeError` without leaking the trap object.
