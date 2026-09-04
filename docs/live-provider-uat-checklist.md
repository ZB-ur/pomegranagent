# Retained live-provider UAT checklist

This checklist is for the release controller's connected-browser pass. The
deterministic Step 7 gates must already be green. Do not use this command for
routine development or CI, and do not run it in parallel with any test suite.

## Safety boundary

- Use only synthetic children, ducks, diary text, and the tracked fixtures
  printed by the harness.
- Do not display, paste, log, screenshot, or save the DeepSeek credential or
  the temporary teacher credential outside their intended input fields/control
  frame.
- Drive only the exact `http://127.0.0.1:<port>` origin printed by the harness.
  Do not reuse another local server or discover a process by name or port.
- Leave `artifacts/real-uat/<run-id>/` in place whether the run succeeds or
  fails. The harness owns only its newly created run and server process group.
- The harness pins owner/mode/device/inode identities and walks retained/runtime
  ancestors without following links. Renaming, relinking, permission-changing,
  or replacing a run/runtime ancestor makes the run fail; do not repair evidence
  in place.
- The harness materializes `reviewed-source/` from Git objects belonging to the
  literal reviewed commit, with replacement objects/system and global Git
  configuration disabled. It verifies the raw commit, root tree, every blob
  OID and byte hash (including `app/version.json`), makes the tree read-only,
  and runs the seed, server, frontend, and fixture handoff only from that tree.
  The worktree is never an executable UAT source after preflight, and the full
  retained tree is checked again before completion.
- This is an accidental-drift and evidence-integrity boundary, not a security
  boundary against a malicious process running as the same OS user, `ptrace`,
  or abrupt power loss/SIGKILL. Do not run untrusted same-user processes during
  UAT; such an actor could still forge attribution despite the pre/post checks.
- Shutdown verifies the direct leader's PID=PGID=SID identity and boundedly
  keeps that leader unreaped as the kernel-backed group identity until all
  descendants are absent. This applies to successful and failed seed/server
  groups and prevents signalling a numerically reused group.
- Physical microphone capture/acoustic recognition is the only item that may
  be recorded as `HUMAN_UAT_REQUIRED`. All keyboard, button, focus, layout,
  controlled-text, DeepSeek, analysis, and Edge-TTS checks must run.

## Start and handoff

1. Confirm the intended Task 10 commit and a clean result from all four
   deterministic release gates.
2. Start the harness in a dedicated terminal and keep its stdin connected:

   ```bash
   /Users/lddmay/AiCoding/pomegranagent/.venv/bin/python scripts/run_live_provider_uat.py --retain --print-runtime-json --expected-head <literal-reviewed-40-hex-commit>
   ```

   The value after `--expected-head` is mandatory and must be the exact
   independently reviewed lowercase commit, not `HEAD`, a branch, or a shell
   substitution. The harness rejects any dirty runtime/UAT path before creating
   a run or launching a child. If the release owner has explicitly reviewed an
   unrelated user-owned dirty path, classify that exact repository-relative
   path with one repeatable `--allow-unrelated-dirty-path <path>` argument. The
   observed set must equal the classified set, and every classified path remains
   in the protected before/after snapshot. Never classify `app/`, `scripts/`,
   `tests/`, the live checklist, root runtime configuration, or the retained-UAT
   artifact tree as unrelated.

   Each classified path is recorded with its two-character porcelain status,
   logical porcelain record index, destination association, and role (`path`,
   or `current`/`original` for rename/copy). One source copied to multiple
   destinations remains represented by distinct paired records. A stably
   missing deletion or rename source is valid evidence, but any missing/present
   or byte transition between the two protected snapshots fails closed.

3. Wait for exactly one canonical JSON line on stdout. It is printed only after
   the app-mode health/version/worker/auth checks pass. Record the printed
   `run_id`, `source_head`, `base_url`, artifact paths, fixture paths, and four
   approved viewports. The process should then remain silent and wait.
4. Open only the printed teacher/child URLs in the connected browser. Do not
   persist browser storage state, cookies, authorization headers, a HAR, or
   provider traffic.
5. Create a new 4-6 digit teacher credential through the first-time product UI.
   Send the same value once to the harness over stdin as canonical one-line
   NDJSON with fields `kind`, `type`, and `value`, where `kind` is
   `teacher_credential` and `type` is `register_secret`. There is deliberately
   no acknowledgement. Confirm the input becomes empty and the credential is
   absent from visible page text and the URL. Do not inspect browser storage or
   cookies during the connected-browser pass; deterministic auth tests and the
   retained-artifact secret scan cover those boundaries without exposing
   private browser state. Never capture the credential-entry state.

## Browser journey

Record every step below once, in this exact order, with status `PASS`, at least
one concrete visible assertion, and only the noted stable IDs where applicable.

1. `teacher_credential_setup_login`: complete initial credential setup, unlock,
   lock/logout, and unlock again; retain no credential value.
2. `child_duck_avatar_management`: create/edit one synthetic child and duck;
   upload the printed PNG/JPEG fixtures, save each resource, and verify the
   canonical UUID-v4-named WebP display URLs. Record `live_child_id`,
   `child_avatar_id`, `live_duck_id`, and `duck_avatar_id`. These must be new
   after the harness's post-seed baseline.
3. `invalid_avatar_rejection`: choose the printed invalid-avatar fixture and
   verify a visible rejection without changing the successful avatar.
4. `monthly_roster_conflict_retry`: select two children for multiple dates,
   submit the month, intentionally exercise one conflict, then retry with a new
   UUID-v4 request ID and verify the final roster. Record `monthly_pairs` as at
   least two ISO dates mapped to exactly two distinct child IDs. Record only
   `monthly_roster_request_ids`: the two visible UUID-v4 request IDs in
   conflict-then-retry order, as observed in the browser request/response
   boundary. Do not manufacture or copy private server telemetry into the
   controller file. After finalization, the harness obtains the two private
   `POST /api/roster/month` attempt events directly from its telemetry pipe and
   binds them to these IDs, the identical canonical monthly payload, the
   409 `ROSTER_DATE_CONFLICT`, and the successful 200 retry.
5. `child_conversation_real_provider_tts`: select the new child and complete a
   real exchange of one to three alternating child/diary turns by controlled
   text handoff. The opening greeting must use the child's nonempty nickname,
   falling back to its name only when the nickname is empty. Record every
   child utterance with the literal character `我` so the retained live result
   is covered by the later exact search. Record every
   ordered UUID-v4 request as `chat_request_ids`. If DeepSeek returns
   `complete` after turn one or two, stop there: all recorded request IDs are
   also `provider_chat_request_ids` and `local_terminal_request_id` is null. If
   the exchange reaches turn three, only the first two request IDs are
   provider-backed and the third is `local_terminal_request_id`, returning the
   fixed local `max_rounds` reply. Record the actual final message as the frozen
   boundary and never send another message after completion.

   Before the first child-page navigation, install passive browser
   instrumentation around the native `HTMLMediaElement.prototype.play`
   boundary and capture-phase `playing`, `ended`, and `error` listeners. Call
   the original native `play` with its original receiver, return its original
   promise unchanged, and observe whether that promise fulfills. Keep the real
   `Audio` constructor, element, network request, decode, and playback intact;
   never stub or replace them. Also wrap `speechSynthesis.speak` as a
   pass-through usage detector before navigation; never substitute synthesized
   speech for the real audio element.

   Verify the TTS endpoint response and completed native playback for the
   opening greeting and every diary reply. Record `tts_evidence` in that order
   with exactly `kind`, source message ID (null only for the greeting), full
   requested-text SHA-256, effective stripped/500-character-text SHA-256,
   `truncated`, run-relative cache path, audio SHA-256, and `playback`. Each
   `playback` object has exactly `play_promise: "fulfilled"`,
   `events: ["playing", "ended"]`, `error: null`, and
   `speech_synthesis_fallback: false`. Repeated or identically truncated text
   may legitimately reuse one cache file: every endpoint call and real element
   playback is still required, while only the first request for a cache key
   invokes Edge-TTS.
6. `conversation_completion_analysis`: complete the conversation, wait for the
   one real analysis worker job to succeed, and record `analysis_job_id`. The
   final DB proof requires nonempty feeding, emotion, and insight projections
   tied to the new conversation/child/duck.
7. `teacher_today_queues`: verify the completed item appears in the correct
   Today queue and other queue states remain coherent.
8. `review_edit_confirm`: open the analysis, edit the review, confirm exactly
   all currently enabled dimension scores, and record `assessment_id`. The
   confirmed overall must equal the mean of those scores.
9. `weekly_metrics_growth`: verify the conversation contributes to the intended
   weekly metrics and Growth view. Record the Monday ISO date as
   `weekly_week_start`, plus the exact displayed `weekly_metrics_before`,
   `weekly_metrics_after`, `growth_before`, and `growth_after` objects.
10. `advanced_search_pagination_deep_link`: search privately with literal
    keyword `我` across all children (`child_id: null`), analysis status exactly
    `succeeded`, review status exactly `confirmed`, and both end reasons in UI
    order: `max_rounds`, then `complete`. Set the inclusive dates to cover the
    seeded qualifying range from anchor `day_offset=-21` through
    `day_offset=+4` and the live conversation. Submit literal `limit: 5`. Load
    the next frozen cursor page and open the result through the Review deep
    link. Record the complete
    `search_request`, canonical `search_cursor`, exact `search_deep_link`,
    exactly five ordered `search_page_one_ids`, and the nonempty exact second
    five-result slice as `search_page_two_ids`. IDs must be unique within each
    page and disjoint across pages. Record
    `search_result_conversation_id` equal to the retained live conversation.
    The live conversation's actual end reason must be covered by the selected
    two-reason filter. The harness independently reconstructs the complete
    matching ID set from the stopped database and requires these lists to equal
    its first and second slices at the cursor's immutable snapshot.
11. `search_empty_state`: submit a search that has no matches and verify its
    explicit empty state without disturbing the successful search evidence.
12. `logout_login_retained_state`: logout, unlock again, and verify the roster,
    avatars, conversation, confirmed review, weekly metrics, and search result
    remain available.

Use each provenance key exactly once and only in the journey step below; a key
placed in another step fails even if the global union is unchanged. Do not infer
IDs from display text when the API/URL supplies the stable ID. The exact
`entity_ids` key sets are:

- `teacher_credential_setup_login`: `{}`
- `child_duck_avatar_management`: `child_avatar_id`, `duck_avatar_id`,
  `live_child_id`, `live_duck_id`
- `invalid_avatar_rejection`: `{}`
- `monthly_roster_conflict_retry`: `monthly_pairs`,
  `monthly_roster_request_ids`
- `child_conversation_real_provider_tts`: `chat_request_ids`,
  `live_conversation_id`, `local_terminal_request_id`,
  `provider_chat_request_ids`, `tts_evidence`
- `conversation_completion_analysis`: `analysis_job_id`
- `teacher_today_queues`: `{}`
- `review_edit_confirm`: `assessment_id`
- `weekly_metrics_growth`: `growth_after`, `growth_before`,
  `weekly_metrics_after`, `weekly_metrics_before`, `weekly_week_start`
- `advanced_search_pagination_deep_link`: `search_cursor`,
  `search_deep_link`, `search_page_one_ids`, `search_page_two_ids`,
  `search_request`, `search_result_conversation_id`
- `search_empty_state`: `{}`
- `logout_login_retained_state`: `{}`

The controller must never include the private `monthly_roster_attempts` field;
the harness adds that field only after parsing the stopped server's telemetry.
The harness captured `seed-baseline.json` after the offline seed and before
server/browser activity; seed IDs, files, requests, or projections do not count
as live evidence.

The approved fixture bytes are fixed and come from project-owner-supplied IP
for internal product/testing; external redistribution rights are not asserted.
`child.png` is a byte-for-byte copy of
`app/frontend/assets/duck-front-128.png`; both SHA-256 values are
`89b67c4243f1a5812e48ba115e0035a392cdd1897590b69d4a88755142b8ecd6`.
`duck.jpg` is the metadata-stripped JPEG derivation of
`app/frontend/assets/duck-side-512.png` (source SHA-256
`275c8db008ff40a16f9fec1236271bf9f44d7ea9a94aae98170fd55078b24378`);
its current SHA-256 is
`a34318126cc0371919ee33751be4042897ee1e86b10070bbf454ef3b32956d22`.

## Screenshot evidence

Capture exactly the six real PNG screenshots below directly under the printed
`screenshots_dir`; do not overwrite a captured file. Every row fixes the
`state_id`/semantic filename, surface, journey step, and approved viewport:

- `child-avatar-selected`: child,
  `child_duck_avatar_management`, `1024x576`.
- `child-conversation-complete`: child,
  `child_conversation_real_provider_tts`, `1280x720`.
- `teacher-management`: teacher, `child_duck_avatar_management`, `1024x768`.
- `teacher-review-confirmed`: teacher, `review_edit_confirm`, `1440x900`.
- `teacher-search-deep-link`: teacher,
  `advanced_search_pagination_deep_link`, `1440x900`.
- `teacher-weekly-growth`: teacher, `weekly_metrics_growth`, `1024x768`.

Together they cover exactly these viewport values:

- Teacher: `1024x768` and `1440x900`.
- Child: `1024x576` and `1280x720`.

For each image, record `relative_path`, `semantic_name`, `state_id`, `surface`,
`viewport`, `journey_step`, and concrete `visible_assertions`. Confirm dialogs
fit, the active control/focus is visible, canonical avatars or fallback are
visible as intended, fixed panels do not overlap content, and there is no
horizontal scrolling. A uniform/blank image, duplicate state, wrong surface or
step, dimension mismatch, symlink/hardlink, changed file, or any nonessential
PNG metadata fails closed. Do not capture credential entry, cookies, request
headers, provider payloads, or developer tools.

## Controller evidence and finalize

Write `controller-evidence.json` atomically at the exact printed path as one
UTF-8 canonical JSON object (sorted keys, compact separators, one trailing
newline). It must contain exactly:

- `protocol`: `pomegranagent-live-uat-controller/v1`
- the printed `run_id` and literal 40-hex `source_head`
- `journey`: the 12 ordered entries above; each has exactly `step_id`, `status`,
  `visible_assertions`, and `entity_ids`
- `screenshots`: the exact six entries above, each with exactly
  `relative_path`, `semantic_name`, `state_id`, `surface`, `viewport`,
  `journey_step`, and `visible_assertions`
- `issues`: safe summaries with exactly `severity`, `step_id`, and
  `safe_summary`; do not include raw exception/provider/credential content
- `human_uat_required`: one entry with gate ID
  `physical_microphone_acoustic_recognition`, status `HUMAN_UAT_REQUIRED`, and a
  safe summary

Do not include unknown fields, duplicate steps/semantic names/paths, absolute or
traversing screenshot paths, a blocker issue, or another/zero human-only gate.
Any blocker issue prevents `COMPLETE`, both during controller validation and in
the terminal-manifest builder.

After the evidence file is durably in place, send the canonical stdin line
`{"type":"finalize"}`. Do not use SIGINT/SIGTERM for a successful run: signals
are an emergency stop and intentionally retain a failed/incomplete manifest.
Wait for the harness to stop and exit successfully.

## Final validation and curation

1. Confirm `manifest.json` has status `COMPLETE`, the expected release triple,
   the literal source commit, screenshot metadata/hashes, provider event count,
   and `database_provenance.status=PROVEN`.
2. From the printed artifact root, verify every finalized file hash:

   ```bash
   shasum -a 256 -c SHA256SUMS
   ```

3. Confirm `resources.before.json` and `resources.after.json` are equal for the
   protected main DB/WAL/SHM/log/TTS/media, repository HEAD/raw porcelain, and
   every pre-existing dirty path. The harness treats any mismatch as a safety
   failure.
4. Confirm `reviewed-source.json` identifies the literal source commit/tree and
   every retained reviewed-source blob. `SHA256SUMS` must cover this manifest,
   the whole reviewed source, provider summary, screenshots, caches, and final
   `manifest.json`. Before committing COMPLETE, the harness descriptor-re-reads
   the checksum and provider files, recomputes the inventory from pinned bytes,
   and cross-links every embedded screenshot and TTS cache hash. The atomic
   COMPLETE manifest replacement is the last controlled write; an abrupt
   SIGKILL or power loss at that boundary is a documented residual risk.
5. Confirm the sanitized telemetry summary protocol is
   `pomegranagent-live-uat-telemetry-summary/v1`. It starts with exactly two
   roster attempts. It then contains the opening TTS request, each real
   DeepSeek chat reply followed by that diary reply's TTS request, any third
   fixed local reply's TTS request, then one extraction and one assessment.
   Each first use of a TTS cache key has a raw Edge-TTS event immediately before
   its endpoint event; a repeated cache hit has only the endpoint event. Raw
   provider events have exactly
   `audio_bytes`, `cache_relative_path`, `cache_sha256`, `correlation_id`,
   `error_class`, `latency_bucket`, `model`, `operation`, `parse_valid`,
   `provider`, `response_bytes`, `response_sha256`, `status`, and `voice`.
   DeepSeek events must be raw-JSON parse-valid, successful, correlated to the
   exact provider-backed request UUIDs or the analysis job, and use the
   configured model. Raw Edge-TTS events correlate to the effective-text hash.
   Every TTS endpoint event has exactly `audio_bytes`, `cache_hit`,
   `cache_relative_path`, `cache_sha256`, `effective_text_sha256`, `kind`,
   `method`, `order`, `path`, `requested_text_sha256`, `status`, `truncated`,
   and `voice`; all endpoint calls and cache bytes must agree with DB
   provenance and use `zh-CN-XiaoxiaoNeural`. A local terminal reply never
   counts as provider success.
6. Confirm `manifest.json.secret_scan.status` is `PASS`, with actual values and
   forbidden patterns also `PASS`, `provider_key` equal to
   `FULL_RETAINED_TREE_PASS`, and `teacher_pin` equal to
   `RUNTIME_GENERATED_EVIDENCE_PASS`. The exact prepared manifest bytes and the
   retained artifact tree are scanned before the final COMPLETE commit. The
   provider key is checked byte-for-byte across the entire retained tree,
   including the Git-pinned `reviewed-source/`. The temporary teacher PIN is
   checked in every credential-capable runtime artifact. The closed artifact
   classification is: exact Git-pinned `reviewed-source/` bytes; an exact
   canonical `reviewed-source.json`; a recomputed, complete `SHA256SUMS`;
   strictly shaped and equal `resources.before.json` / `resources.after.json`;
   a complete, strictly shaped `seed-baseline.json`; strictly shaped
   controller, journey, issue, provider-summary, and manifest objects whose
   human/free-text projections are scanned; strictly parsed app/server log
   records whose message fields are scanned; and a read-only SQLite shadow
   whose exact schema, credential/session hash formats, and free-text columns
   are validated and scanned. Dates, IDs, UUIDs, paths, numeric values,
   digests, checksums, and the validated log timestamp/logger/level envelope
   are machine metadata and are not raw-substring PIN-scanned. Screenshot PNGs,
   TTS/media bytes, and every unknown file or unknown structured shape remain
   conservatively byte-scanned and fail closed. Thus a PIN equal to a year or
   commit fragment does not false-fail solely because it appears in validated
   machine metadata, but the same value in a log message, controller visible
   text, database free-text column, screenshot, audio, or unknown file fails.
   Authorization, bearer, cookie, session, and token detector patterns
   apply to runtime evidence; reviewed Git source is marked
   `GIT_PINNED_EXEMPT` for those generic patterns because it contains the
   scanner literals themselves. Do not run a broad content-printing `rg` over
   `reviewed-source/`; rely on the typed harness attestation. Any optional audit
   must never print matching content.
7. Visually inspect selected screenshots for credentials or private browser
   state, then copy only redacted, instruction-worthy images into
   `docs/manual/assets/<run-id>/`. Never add the raw run directory to Git.
8. Commit only the curated documentation/assets in the controller-owned Step 10
   commit. A failed run remains ignored and retained for release-owner review;
   start a new run rather than modifying its evidence into `COMPLETE`.
