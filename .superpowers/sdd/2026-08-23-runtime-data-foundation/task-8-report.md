# Task 8 Report: Teacher PIN Credentials, Revocable Browser Sessions, and Route Guards

## Delivered

- Added one-time 4–6 ASCII digit PIN setup using a per-credential salt and `hashlib.scrypt`; only the salt and derived hash are persisted.
- Added opaque, SHA-256-hashed server sessions and the `/api/auth/status`, `/setup`, `/unlock`, and `/lock` contract. Setup/unlock issue a non-persistent `duck_teacher_session` cookie with `HttpOnly`, `SameSite=Strict`, `Path=/`, and no `Secure`, `Max-Age`, or `Expires` attribute. Lock revokes the server record and clears the browser cookie.
- Protected the full teacher route inventory with `require_teacher_session`; unauthenticated teacher operations return the standard `401 TEACHER_AUTH_REQUIRED` envelope/request ID. Health, version, auth, today-roster, chat, temporary finalize, and TTS remain public.
- Added the frozen `DuckAuth` browser adapter and loaded it immediately after the shared API client on both pages.
- Teacher navigation now stays disabled and busy until both runtime verification and PIN authentication succeed. Locking clears cached views, revokes the session, immediately presents the PIN re-unlock flow, restores the current hash route on successful unlock, avoids duplicate lock controls, and surfaces a lock failure while retaining the unlocked view.
- Removed the child page's empty-roster fallback to protected `/api/children`; it now presents `今天还未排班，请老师帮忙`.
- Updated the legacy API/error-envelope tests only where they intentionally exercise protected behavior after authentication. The `tests/test_api_errors.py` update was explicitly authorized after the full-suite diagnosis.

## TDD evidence

RED command:

```text
./.venv/bin/pytest tests/test_teacher_auth.py tests/test_frontend_foundation.py tests/test_api.py -q
21 failed, 7 passed, 1 warning in 0.59s
```

The failures proved that auth endpoints and models were absent, all teacher routes were public, the browser adapter/load order was absent, and the child page still requested `/api/children` when the roster was empty.

The executable teacher readiness regression was also RED before the gate change:

```text
node --test tests/frontend/shared/api-client.test.mjs
3 passed, 1 failed
```

It showed `DuckAuth.status()` was not awaited before a business request could begin.

## Verification

```text
./.venv/bin/pytest tests/test_api_errors.py -q
8 passed, 7 warnings in 0.26s

./.venv/bin/pytest tests/test_teacher_auth.py tests/test_frontend_foundation.py tests/test_api.py -q
28 passed, 72 warnings in 1.35s

node --test tests/frontend/shared/api-client.test.mjs
4 passed, 0 failed

./.venv/bin/pytest -q
71 passed, 78 warnings in 3.15s

git diff --check
exit 0
```

The warning output is limited to Starlette TestClient and SQLAlchemy `datetime.utcnow()` deprecations; there are no test failures.

## Scope

The commit contains only Task 8 implementation/tests, the permitted executable frontend regression, and the explicitly authorized two-case `tests/test_api_errors.py` integration update. Existing `.workbuddy`, specs, plans, and unrelated `.superpowers` files remain excluded.

## Review follow-up: concurrent setup and teacher bootstrap failures

### Delivered

- Wrapped only the initial credential `db.commit()` in `setup()` with a SQLAlchemy `IntegrityError` handler. It rolls back the failed request session and returns the established `409 PIN_ALREADY_CONFIGURED` envelope. Session issuance remains outside that handler, so unrelated token/session errors still use their normal failure path.
- Replaced the teacher bootstrap no-op catch with a handler that preserves the runtime-maintenance screen if shared `api.js` already rendered it. For auth-status/network failures it keeps navigation disabled and renders the safe API error message in the teacher locked card.
- Added deterministic integration coverage that inserts the competing credential through a second real SQLAlchemy session immediately before the setup request commits. It proves the conflict envelope, persisted competing record, usable status query, and usable subsequent unlock request.
- Added executable Node coverage for both rejected `DuckAuth.status()` (visible non-blank locked error) and rejected runtime readiness when maintenance is already present (maintenance remains untouched).

### TDD evidence

RED commands:

```text
./.venv/bin/pytest tests/test_teacher_auth.py -q
1 failed, 8 passed, 18 warnings in 1.07s
```

The injected competing credential committed successfully in a separate real session; the setup request then raised the authentic SQLite/SQLAlchemy `IntegrityError` from its credential insert rather than producing a standard 409 response.

```text
node --test tests/frontend/shared/api-client.test.mjs
5 passed, 1 failed
```

The rejected `DuckAuth.status()` regression found a blank main panel (`0 !== 1`) because the bootstrap catch discarded the error.

The runtime-maintenance preservation branch was mutation-checked by temporarily removing its guard:

```text
node --test tests/frontend/shared/api-client.test.mjs
5 passed, 1 failed
```

The test observed the forbidden replacement of the main panel (`1 !== 0`); restoring the guard returned the full Node suite to green.

### Follow-up verification

```text
./.venv/bin/pytest tests/test_teacher_auth.py tests/test_frontend_foundation.py tests/test_api.py -q
29 passed, 76 warnings in 1.61s

node --test tests/frontend/shared/api-client.test.mjs
6 passed, 0 failed

./.venv/bin/pytest -q
72 passed, 82 warnings in 3.39s

git diff --check
exit 0
```
