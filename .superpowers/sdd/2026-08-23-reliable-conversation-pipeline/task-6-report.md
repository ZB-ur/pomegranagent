# Task 6 — Teacher Queues, Detail, and Atomic Review

## Result

Implemented the service-backed authenticated teacher queue, immutable detail,
and revisioned full-document review PUT. The review service performs all
semantic reads before mutation, rolls the read transaction back, wins the
conversation revision with a CAS, revalidates the winner state, and replaces
every editable projection in one commit. SQLite timestamps are exposed as
aware UTC values.

Legacy successful conversation list/detail registrations were removed from
`main.py`. The legacy partial review endpoints are authenticated no-write 410
`LEGACY_ENDPOINT_REMOVED` tombstones; malformed JSON reaches the tombstone
after authentication. The child `/finalize` route and Task 4 retry/lifespan
work were retained.

## TDD evidence

- RED: `./.venv/bin/pytest -q tests/test_review_atomicity.py` before Task 6
  production code: **5 failed**. The absent review PUT returned 405, legacy
  list returned every conversation instead of queue membership, and legacy
  detail omitted `review_status` for all pending/processing/failed cases.
- GREEN: the focused suite passed **23/23** after the implementation; the
  required second focused run also passed **23/23**.

## Matrix and transaction evidence

- Queue tests cover succeeded pending/draft, analysis pending/processing/failed,
  confirmed exclusion, newest ended sorting, inactive historical identity, and
  frozen message/child-turn counts.
- Detail tests cover all unavailable states, exact sanitized failed analysis
  error, ordered frozen transcript/scores, UTC `Z` timestamps, and coherent
  succeeded-document corruption as stable `INTERNAL_ERROR`.
- Draft replacement retains a feeding ID, deletes an omitted row, creates a
  new row, replaces emotion/insight/scores, increments revision once, and
  matches a fresh detail read. Confirm enforces full enabled dimensions and
  nonblank reasons, then disappears from every queue.
- Rollback snapshots cover foreign/duplicate feeding IDs, missing/new
  inactive/reassigned ducks, missing/disabled dimensions, duplicate schema
  dimensions, DTO validation, stale revision, and forced flush/commit failures.
  Every fresh SQLite snapshot retained conversation revision, all feeding,
  emotion, insight, assessment, overall, and score state exactly.
- Two independent sessions synchronize after validation and before CAS: one
  saves revision 3 and the other returns `REVIEW_REVISION_CONFLICT` with
  `当前版本为 3`; the final document is exactly the winner's document.
- Route inventory normalizes placeholders and finds exactly one queue, detail,
  review, and canonical Task 4 retry handler. Both legacy tombstones are 401
  while locked and 410 without writes after unlock.

## Verification

```text
./.venv/bin/pytest -q tests/test_review_atomicity.py                  23 passed
./.venv/bin/pytest -q tests/test_review_atomicity.py                  23 passed
./.venv/bin/pytest -q tests/test_review_atomicity.py -k "rollback or revision"  2 passed, 21 deselected
./.venv/bin/pytest -q tests/test_pipeline_models.py tests/test_chat_idempotency.py tests/test_conversation_completion.py tests/test_analysis_worker.py tests/test_roster_idempotency.py tests/test_review_atomicity.py
                                                                    129 passed
./.venv/bin/python -m py_compile app/backend/services/reviews.py app/backend/routes/conversations.py app/backend/main.py
git diff --check                                               passed
```

The runs use only the disposable fixture SQLite database. The existing test
environment emits FastAPI/httpx and pre-existing `datetime.utcnow` deprecation
warnings; there were no test failures or Task 6 warnings.

## Files and commit

- `app/backend/services/reviews.py`
- `app/backend/routes/conversations.py`
- `app/backend/main.py` (only Task 6 legacy GET/tombstone hunks and import)
- `tests/test_review_atomicity.py`
- this report

Commit: `feat: save teacher reviews atomically` (the final SHA is supplied in
the task handoff after the staged diff is committed).

Preserved unrelated dirty paths: `.workbuddy/memory/2026-08-22.md`,
`docs/superpowers/specs/2026-08-23-interaction-stabilization-design.md`,
`.superpowers/brainstorm/`, and `docs/superpowers/plans/`.

## Post-review CAS reference-race correction

Independent review found that the original post-CAS boundary checks did not
fresh-read mutable requested ducks and dimensions. A separate session could
therefore disable/delete a prevalidated reference after the read rollback and
before the winner's CAS, allowing an invalid revision to commit.

- RED: `./.venv/bin/pytest -q tests/test_review_atomicity.py -k "post_cas"`
  produced **3 failed**. The writer incorrectly returned a successful
  revision-3 response after a requested dimension was disabled or a new duck
  was deactivated/deleted.
- The shared `_load_review_reference_rows` / `_review_reference_errors` path
  now runs before and after CAS. The post-CAS pass freshly checks requested
  dimension existence/enabled state, requested duck existence/active state,
  exact historical inactive-duck retention, and retained feeding ownership.
  A post-CAS semantic error raises `REVIEW_VALIDATION_FAILED` inside the CAS
  transaction, so its revision increment and every projected write roll back.
- Deterministic independent-session tests pause at the validation/CAS seam;
  they cover dimension disable, new-duck deactivation, new-duck deletion, and
  simultaneous changes. Each asserts precise indexed field keys, one semantic
  error response (not an ORM/Pydantic error), and an exact fresh-snapshot match
  for revision, feeding/emotion/insight/assessment/overall/scores.

```text
./.venv/bin/pytest -q tests/test_review_atomicity.py                  27 passed
./.venv/bin/pytest -q tests/test_review_atomicity.py                  27 passed
./.venv/bin/pytest -q tests/test_review_atomicity.py -k "rollback or revision or post_cas"
                                                                     6 passed, 21 deselected
./.venv/bin/pytest -q tests/test_pipeline_models.py tests/test_chat_idempotency.py tests/test_conversation_completion.py tests/test_analysis_worker.py tests/test_roster_idempotency.py tests/test_review_atomicity.py
                                                                    133 passed
./.venv/bin/python -m py_compile app/backend/services/reviews.py    passed
git diff --check                                                       passed
```
