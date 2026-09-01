# Server Capabilities and Real UAT Design

**Status:** Approved for uninterrupted implementation on 2026-09-02

**Release base:** `codex/p5-teacher-reports-slice@2cac86b`

**Release branch:** `codex/p6-server-capabilities`

## Goal

Deliver every server capability left unavailable by the reviewed P5 interaction design, connect each capability to the current child and teacher interfaces, and produce a retained, replayable real-user acceptance evidence set using synthetic child data, real DeepSeek, and real Edge-TTS.

The release is one product increment but must remain a sequence of independently testable and revertible commits. A genuine microphone/acoustic recognition check is the only human device gate and is not part of the autonomous completion claim.

## Scope

1. Business timezone and runtime context.
2. Strict child and duck mutation contracts.
3. Safe avatar upload, storage, retrieval, and teacher UI integration.
4. Atomic idempotent multi-date monthly partner roster entry and UI integration.
5. Weekly teacher metrics and Today integration.
6. Privacy-preserving advanced conversation search and Search integration.
7. Versioned SQLite migrations and a deterministic full-graph demo seed.
8. Deterministic release gates plus an isolated live-provider browser journey with retained data, screenshots, logs, and manifest.

## Non-goals

- No holiday calendar service or automatic partner-matching policy.
- No absence workflow beyond editing one or more selected dates.
- No LAN/public deployment, TLS, public account system, or remote media service.
- No animated/video asset production; existing motion placeholders remain asset handoff points.
- No real child names, photos, voices, or other personally identifying acceptance data.
- No claim that screenshots prove sound output or acoustic recognition quality.
- No migration of the user's real application database in this release worktree. Migrations are proved against a byte-for-byte disposable copy and a synthetic retained UAT database.

## Global invariants

- Figma remains design truth, current code remains runtime truth, and browser tests remain release truth.
- The application remains loopback-only. Every browser request must stay same-origin; provider credentials are available only to the backend live-UAT process.
- SQLite timestamps remain UTC. Calendar dates and week boundaries use `APP_BUSINESS_TIMEZONE`, defaulting to the exact IANA zone `Asia/Shanghai`.
- Existing P5 API shapes remain compatible unless this document explicitly introduces a new endpoint. Existing GET history and daily/automatic roster endpoints remain supported.
- Mutation requests reject unknown fields. Resource create/update requests never accept `active` or `deactivated_at`.
- Teacher-only writes authenticate before inspecting request bodies. Public avatar reads expose only random server-generated identifiers and processed images.
- All multi-row writes are one transaction. Idempotency records and domain rows commit together or roll back together.
- Deterministic tests never contact external providers. Live-provider UAT never uses the repository's application database, application log, or TTS cache.
- Raw acceptance evidence is retained locally under `artifacts/real-uat/<run-id>/`; approved manual screenshots are copied to `docs/manual/assets/<run-id>/` without overwriting earlier runs.

## 1. Business clock and runtime context

`RuntimeSettings` gains:

```python
business_timezone: str = "Asia/Shanghai"
media_root: Path
log_path: Path
tts_cache_path: Path
```

Invalid or unavailable IANA zones fail startup with a sanitized configuration error. A focused `BusinessClock` provides:

```python
def utc_now() -> datetime
def business_now() -> datetime
def business_today() -> date
def week_window(anchor: date | None = None) -> tuple[date, date]
```

`week_window` returns Monday inclusive and the following Monday exclusive. All current uses of host `date.today()` for roster reads, resource deactivation, seed anchors, weekly metrics, and conversation calendar dates are replaced by the business clock. Stored `created_at`, `updated_at`, `started_at`, and `ended_at` values remain UTC.

New public same-origin endpoint:

```http
GET /api/runtime/context
```

Response:

```json
{
  "timezone": "Asia/Shanghai",
  "business_date": "2026-09-02",
  "week_start": "2026-08-31",
  "week_end_exclusive": "2026-09-07"
}
```

## 2. Strict resource contracts

The existing `/api/children` and `/api/ducks` routes remain. Their mutation DTOs become strict and normalized.

Child request:

```json
{
  "name": "王小明",
  "nickname": "小明",
  "avatar": "/api/media/avatars/6d8b..."
}
```

- `name`: trimmed, 1–64 characters.
- `nickname`: null or trimmed, 1–64 characters.
- `avatar`: null or a canonical local avatar URL returned by the upload endpoint.
- `active` and all unknown fields: rejected with `VALIDATION_ERROR`.

Duck request:

```json
{
  "name": "小黄",
  "avatar": "/api/media/avatars/0f2a...",
  "status": "活泼健康",
  "note": "喜欢在水里玩"
}
```

- `name`: trimmed, 1–64 characters.
- `status`: null or trimmed, 1–255 characters.
- `note`: null or trimmed, 1–2000 characters.
- `avatar` and unknown fields follow the child rules.

Responses remain compatible with P5 and are validated through strict response models.

## 3. Avatar media

New teacher-authenticated upload endpoint:

```http
POST /api/media/avatars
Content-Type: multipart/form-data
file=<binary>
```

Accepted input: JPEG, PNG, or WebP; maximum encoded size 5 MiB; maximum decoded dimensions 4096×4096; maximum decoded pixels 16,777,216. SVG, GIF, animated images, polyglots, malformed images, and mismatched declared/decoded formats are rejected.

The server decodes with Pillow, applies EXIF orientation, converts to RGB/RGBA, strips metadata, bounds the longest edge to 1024 pixels, and re-encodes one static WebP at quality 88. It computes SHA-256, writes through a same-directory temporary file plus atomic rename, and stores metadata in `avatar_media`:

```text
id UUID primary key
file_name random UUID + .webp
mime_type image/webp
width positive integer
height positive integer
size_bytes positive integer
sha256 64 hex characters
created_at UTC
```

Response:

```json
{
  "id": "6d8b...",
  "url": "/api/media/avatars/6d8b...",
  "mime_type": "image/webp",
  "width": 768,
  "height": 768,
  "size_bytes": 84231,
  "sha256": "..."
}
```

Public same-origin read:

```http
GET /api/media/avatars/{media_id}
```

It returns only a known metadata row and its regular file, with `nosniff` and bounded cache headers. Missing rows/files fail closed. Resource DTOs only accept a URL whose media row and file both exist. Replaced and canceled uploads remain unreferenced evidence rather than being deleted during the request; a teacher-only cleanup CLI may remove unreferenced files older than 24 hours, but the live-UAT run disables cleanup so its evidence remains reviewable.

Teacher dialogs add a file input, preview, replace/remove controls, upload progress/status, and recovery that retains form text after upload or save failure. Child roster and teacher cards render the image with a text-initial fallback.

## 4. Monthly partner roster

New route, registered before the dynamic `/{roster_date}` route:

```http
POST /api/roster/month
```

Request:

```json
{
  "request_id": "UUID",
  "month": "2026-09",
  "cycle": "2026-09月值日",
  "entries": [
    {"date": "2026-09-03", "child_ids": [1, 4]},
    {"date": "2026-09-08", "child_ids": [2, 5]}
  ],
  "replace_existing": false
}
```

Rules:

- 1–31 entries; dates are unique and belong to `month`.
- Every entry contains exactly two distinct active children.
- `cycle` is trimmed and 1–64 characters.
- All validation happens before any delete/insert.
- With `replace_existing=false`, any occupied target date returns `ROSTER_DATE_CONFLICT` and changes nothing.
- With `replace_existing=true`, only the submitted dates are replaced.
- The existing `roster_requests` ledger records operation `monthly_roster`, canonical payload hash, response, replay, in-progress conflict, and same-request/different-payload conflict.

Response:

```json
{
  "request_id": "UUID",
  "month": "2026-09",
  "schedule": [
    {"date": "2026-09-03", "cycle": "2026-09月值日", "child_ids": [1, 4]}
  ],
  "replayed": false
}
```

The teacher modal pre-generates date rows for the chosen month from active class size and two children per duty day. Teachers select partner pairs with two dropdowns, may remove unwanted dates, and can submit many dates once. Conflict recovery offers a deliberate overwrite retry with a new request ID; ordinary retry reuses the original ID and body.

## 5. Weekly metrics

Teacher-authenticated endpoint:

```http
GET /api/reports/weekly
GET /api/reports/weekly?week_start=2026-08-31
```

`week_start` must be a Monday. No parameter uses the current business week. Response:

```json
{
  "timezone": "Asia/Shanghai",
  "week_start": "2026-08-31",
  "week_end_exclusive": "2026-09-07",
  "completed_conversations": 4,
  "participating_children": 3,
  "confirmed_reviews": 2,
  "failed_analyses": 1,
  "pending_reviews_total": 5
}
```

Weekly fields use conversation calendar dates in `[week_start, week_end_exclusive)`. `pending_reviews_total` is explicitly cumulative current workload, not a weekly count. One aggregate query (or a fixed bounded set with no per-row reads) supplies the response. Today renders five labeled metrics plus loading, empty/zero, failure, and retry states without blocking its existing independent panels.

## 6. Advanced history search

The existing GET `/api/conversations/history` remains unchanged. New teacher-authenticated endpoint:

```http
POST /api/conversations/search
```

Request:

```json
{
  "child_id": 1,
  "date_from": "2026-08-01",
  "date_to": "2026-09-02",
  "analysis_status": ["succeeded"],
  "review_status": ["confirmed"],
  "end_reason": ["complete", "manual"],
  "keyword": "喂菜叶",
  "sort": "completed_desc",
  "limit": 20,
  "cursor": null
}
```

- Unknown fields are rejected.
- `date_from <= date_to`; the range is inclusive and at most 366 days.
- Keyword is trimmed, 1–100 characters, escaped for SQL LIKE, and matched against frozen child and diary message text. It never appears in the URL or request logs.
- Status arrays are unique and limited to their public enums.
- Sort is `completed_desc` or `completed_asc`.
- Limit is 1–50.
- The opaque URL-safe cursor contains the last `(ended_at, id)`, direction, and a SHA-256 fingerprint of all filters except cursor/limit. Invalid, mismatched, or malformed cursors return `VALIDATION_ERROR`.
- Ordering is stable by `(ended_at, id)`. No offset pagination is used.

Response reuses the strict history item shape and adds `next_cursor`:

```json
{"items": [], "next_cursor": null}
```

Search UI provides child, date range, status, keyword, and sort controls. A new search resets results and cursor; load-more preserves existing rows on failure; results deep-link to Review.

## 7. Migrations, versioning, and seed

Add Alembic with an immutable schema-2 baseline and schema-3 upgrade. The upgrade creates `avatar_media` and indexes needed by weekly/search queries. Existing schema-2 databases without `alembic_version` are fingerprinted against required tables/columns before being stamped; unknown or newer schemas fail closed. Empty databases upgrade from base. Startup performs migration before workers and seed logic.

Release manifest becomes:

```json
{
  "release_id": "2026.09.02-server-capabilities.1",
  "api_version": "3",
  "schema_version": "3"
}
```

Ordinary startup never silently inserts demo people. A new explicit CLI accepts a target database, anchor date, and profile `full-demo`. It refuses non-empty databases unless `--force` is supplied, uses one transaction, performs no network/LLM calls, and creates a deterministic graph containing:

- at least 8 synthetic children and 3 synthetic ducks;
- avatar media generated from local non-PII fixtures;
- prior/current/future roster pairs;
- ended conversations with frozen messages;
- pending, processing, succeeded, and failed analysis jobs;
- pending, draft, and confirmed reviews;
- feeding, emotion, insight, assessment, score, growth, and searchable keyword examples.

No PIN is preconfigured. Live UAT configures a run-specific teacher PIN through the UI.

## 8. Dual-track acceptance and retained evidence

### Deterministic release track

- Run new focused Python and Node tests after each TDD slice.
- Run backend and frontend suites serially with temporary DB/media/log/TTS paths and provider tripwires.
- Run the interaction acceptance runner after its inventory is updated for the P6 endpoints and browser journeys.
- Verify the main checkout's real database, WAL/SHM, log, and TTS cache are unchanged before and after.

### Live-provider real-user track

A dedicated command creates `artifacts/real-uat/<run-id>/` and never deletes it. It contains:

```text
duck-diary-uat.db
media/
tts-cache/
logs/app.log
screenshots/<sequence>-<scenario>-<viewport>.png
manifest.json
journey.md
issues.md
provider-summary.json
```

The harness starts its own loopback server on a random port with `APP_DB_MODE=app`, the retained database path outside the repository, retained media/log/TTS paths, `APP_BUSINESS_TIMEZONE=Asia/Shanghai`, and real provider credentials available only in the backend process. `app` mode is required because both user interfaces correctly reject a test-mode runtime; isolation comes from the run-scoped paths and resource checks, not from presenting a test runtime to the browser. It seeds synthetic data, configures PIN through the UI, and walks:

1. Teacher PIN setup, lock, and unlock.
2. Child and duck creation/editing with real avatar uploads and fallbacks.
3. Monthly roster batch save, conflict, overwrite, and single-day adjustment.
4. Child selection, ready/listening/submitting/speaking/saving/completed states using a controlled text handoff for autonomous execution.
5. Real DeepSeek reply, completion, analysis worker result, review draft/confirm, Growth, weekly metrics, and advanced Search.
6. Provider/failure recovery paths that do not lose child text or falsely claim save success.

Child screenshots cover 1024×576 and 1280×720. Teacher screenshots cover 1024×768 and 1440×900. The manifest records scenario, route, viewport, timestamp, screenshot SHA-256, expected state, observed state, and whether the image is a manual candidate. Screenshots containing secrets, PIN digits, provider payloads, or request headers are forbidden.

Real DeepSeek and Edge-TTS success is recorded as sanitized status/latency/byte-count/hash only. The run retains provider-generated diary text because all identities and source messages are synthetic. No API key or raw provider response envelope is retained.

### Human device gate

The autonomous journey verifies SpeechRecognition success/error state handling through controlled browser seams and verifies real Edge-TTS bytes plus browser playback events. It does not claim that a physical microphone, OS permission prompt, ambient acoustic recognition, speaker volume, or heard audio passed. Those remain `HUMAN_UAT_REQUIRED` until the release owner performs one spoken Mandarin check on the target device.

## Completion criteria

- Every scoped API has strict contract, authorization, TDD red/green evidence, atomicity/idempotency coverage where applicable, and frontend reachability.
- Fresh full deterministic suites pass from the P6 head.
- One retained live-provider run completes all autonomous scenarios with real DeepSeek and Edge-TTS.
- The retained run contains its database, screenshots, manifest, journey report, issue list, and sanitized provider summary.
- The main checkout's protected runtime resources and unrelated dirty paths are byte-for-byte unchanged.
- Final whole-branch review has no open Critical or Important finding.
- The final report names every discovered product/system/interaction issue and clearly leaves the microphone gate unpassed.
