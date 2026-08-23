# Task 0 Report — Foundation Version Gate Promise Reuse

## Boundary and scope

- Started from `e2d98b6397cb2ebf40a58a28dab67d9a6519cfa7`.
- Owned changes: `app/frontend/shared/api.js`, `tests/frontend/shared/api-client.test.mjs`, and this report only.
- Preserved unrelated dirty paths: `.workbuddy/memory/2026-08-22.md`, `docs/superpowers/specs/2026-08-23-interaction-stabilization-design.md`, `.superpowers/brainstorm/`, and `docs/superpowers/plans/`.

## RED

Before changing production code, added direct `bootstrapVersionGate()`/`ready()` regression coverage and ran:

```text
node --unhandled-rejections=strict --test tests/frontend/shared/api-client.test.mjs
```

Result: 9 tests total; 6 passed and the 3 new gate tests failed. Each failure was the expected strict Promise identity failure: direct bootstrap followed by ready, ready followed by bootstrap/repeated ready, and a previously rejected gate followed by direct bootstrap all returned a distinct Promise. No pre-existing test failed.

## GREEN and evidence

The effectful body is now private `performVersionGate()`. `bootstrapVersionGate()` is a non-async cache wrapper and `ready()` synchronously returns it; neither clears the cache after rejection.

The direct-success test proves `bootstrapVersionGate()` then `ready()` returns the same pending Promise, produces exactly one `/version.json` request and one `/api/health` request, resolves both callers to the same health object, writes `data-app-state=ready` once, and dispatches one `duck:runtime-ready` event.

The reverse/repeated test proves `ready()`, direct bootstrap, and another `ready()` share that same pending Promise with the same one-version/one-health fetch and one ready state/event effect.

The failed mismatch test proves the original and later direct/repeated calls return the same rejected Promise and the same `VERSION_MISMATCH` `APIError` object, do not fetch again, write maintenance once, dispatch one `duck:runtime-blocked` event, and replace the DOM with exactly one `runtime-maintenance` panel.

Both required clean runs passed:

```text
node --unhandled-rejections=strict --test tests/frontend/shared/api-client.test.mjs
# 9 passed, 0 failed

node --unhandled-rejections=strict --test tests/frontend/shared/api-client.test.mjs
# 9 passed, 0 failed
```

`rg -n "readyPromise|bootstrapVersionGate|performVersionGate" app/frontend/shared/api.js` confirms one cache owner, private effectful body, and both public wrappers. `git diff --check` passed.

## Commit

- Message: `fix: reuse the foundation version gate promise`
- Files: `app/frontend/shared/api.js`, `tests/frontend/shared/api-client.test.mjs`, `.superpowers/sdd/2026-08-23-child-interaction-recovery/task-0-report.md`

## Review remediation — settled success reuse

Independent review identified a missing success-settlement proof. The direct-success regression now calls both `bootstrapVersionGate()` and `ready()` again after the initial gate has resolved. It asserts both calls remain strictly identical to the original Promise, resolve to the original health object, retain exactly one version and one health request, and do not add a ready state write or ready event.

This is a black-box behavior check: clearing or replacing the successful cache would break strict Promise identity and the single-request/single-effect assertions. The existing implementation satisfies the frozen behavior, so the added proof was directly GREEN without changing `app/frontend/shared/api.js`.
