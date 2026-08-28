# Teacher Task 5A Report — pytest application-log isolation

## Scope and incident preservation

- Owned changes: `tests/conftest.py` and `tests/test_database_safety.py` only.
- The 2026-08-29 01:59 Asia/Shanghai incident remains preserved in
  `logs/app.log`; no log rotation, truncation, restoration, or rewrite was
  performed.
- Incident baseline, sampled before and after every pytest verification:
  SHA-256 `5ee47c6b8322aee20aefecbf2344e8134cec18154fb7eb2d00c60116379fbeb7`,
  size `2961585`, mtime `1787939944`.
- The preserved tail shows pytest TestClient records beginning at
  `2026-08-29 01:59:02`; this was the recorded RED. No unsafe pre-fix pytest
  rerun was performed.

## Repair

- Before importing `app.backend.main`, pytest now creates a disposable
  `pytest-app.log` inside `TEST_RUNTIME_DIR`.
- `logging.FileHandler` is replaced only during that import. Requests resolving
  to the repository `logs/app.log` are redirected to the disposable log; every
  other requested filename is forwarded unchanged, and the original constructor
  is restored in `finally`.
- Test constants expose both resolved paths. Root-handler reflection ignores
  non-file handlers, rejects a real-log target, and requires the disposable
  target when the application logging configuration constructed a FileHandler.
- The session resource guard snapshots both the logical application database
  and exact real-log bytes before pytest, checks both after pytest, then removes
  only `TEST_RUNTIME_DIR`.
- Added a direct root-handler safety test and a sanitized subprocess regression
  that executes a TestClient/review-atomic node and asserts byte-for-byte real
  log equality.

## Verification (serial)

1. `./.venv/bin/python -m pytest -q tests/test_database_safety.py`
   - PASS: 11 passed (includes the new review-atomic subprocess regression).
   - Real log baseline unchanged after completion.
2. `./.venv/bin/python -m pytest -q tests/test_review_atomicity.py`
   - PASS: 27 passed.
   - Real log baseline unchanged after completion.
3. `./.venv/bin/python -m pytest -q tests/browser/test_child_faults.py::test_browser_parent_logging_is_redirected_from_real_application_log`
   - PASS: 1 passed.
   - Real log baseline unchanged after completion.
4. `./.venv/bin/python -m py_compile tests/conftest.py tests/test_database_safety.py`
   - PASS.
5. `git diff --check`
   - PASS.

Warnings were pre-existing dependency deprecations from Starlette TestClient and
SQLAlchemy UTC APIs; no test failures occurred.

## Handoff

- No product/backend/browser files were changed.
- No Task 5 frontend work or user-owned dirty paths were staged, reverted, or
  modified.
- Await independent code review before committing `test: isolate shared pytest application logs`.
