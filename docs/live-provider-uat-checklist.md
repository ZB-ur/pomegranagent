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
  literal reviewed commit, verifies each blob OID and byte hash, makes the tree
  read-only, and runs the seed, server, frontend, and fixture handoff only from
  that tree. The worktree is never an executable UAT source after preflight.
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

   Each classified path is recorded with its two-character porcelain status and
   role (`path`, or `current`/`original` for rename/copy). A stably missing
   deletion or rename source is valid evidence, but any missing/present or byte
   transition between the two protected snapshots fails closed.

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
   absent from page text, URL, local storage, and session storage. Never capture
   the credential-entry state.

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
   least two ISO dates mapped to exactly two distinct child IDs, and record
   `monthly_roster_attempts` by copying the two server-originated telemetry
   objects: exactly the failed 409 `ROSTER_DATE_CONFLICT` attempt followed by
   the successful 200 attempt whose `error_code` is null. Each object has
   exactly `kind`, `method`, `path`, `order`, `request_id`,
   `canonical_body_sha256`, `replace_existing`, `status`, and `error_code`.
   Both are `POST /api/roster/month`, their request IDs differ, their order is
   1 then 2, and their canonical business-body hashes are identical.
5. `child_conversation_real_provider_tts`: select the new child and complete a
   real exchange of exactly three alternating child/diary turns by controlled
   text handoff. Record exactly three ordered UUID-v4 `chat_request_ids`, the
   first two again as `provider_chat_request_ids`, and the third as
   `local_terminal_request_id`. Only requests one and two invoke DeepSeek;
   request three must return the product's fixed local max-round reply. Verify
   all four generated Edge-TTS outputs: the opening greeting followed by the
   three diary replies. Record `tts_evidence` in that order with `kind`, source
   message ID (null only for the greeting), text SHA-256, run-relative cache
   path, and audio SHA-256. Do not send another message after completion; the
   sixth message and third request-ledger row are the frozen boundary.
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
10. `advanced_search_pagination_deep_link`: search privately with a literal
    keyword, load the next frozen cursor page, and open the result through the
    Review deep link. Record the complete `search_request`, canonical
    `search_cursor`, exact `search_deep_link`, nonempty disjoint ordered
    `search_page_one_ids` and `search_page_two_ids` (IDs must also be unique
    within each page), plus
    `search_result_conversation_id` equal to the retained live conversation.
11. `search_empty_state`: submit a search that has no matches and verify its
    explicit empty state without disturbing the successful search evidence.
12. `logout_login_retained_state`: logout, unlock again, and verify the roster,
    avatars, conversation, confirmed review, weekly metrics, and search result
    remain available.

Use each provenance key exactly once across the journey's `entity_ids` objects;
use `{}` when a step has no new provenance value. Do not infer IDs from display
text when the API/URL supplies the stable ID. The required keys are exactly:
`analysis_job_id`, `assessment_id`, `child_avatar_id`, `chat_request_ids`,
`duck_avatar_id`, `growth_after`, `growth_before`, `live_child_id`,
`live_duck_id`, `live_conversation_id`, `monthly_pairs`,
`monthly_roster_attempts`, `provider_chat_request_ids`,
`local_terminal_request_id`, `search_cursor`, `search_deep_link`,
`search_page_one_ids`, `search_page_two_ids`, `search_request`,
`search_result_conversation_id`, `tts_evidence`, `weekly_metrics_after`,
`weekly_metrics_before`, and `weekly_week_start`. The harness captured
`seed-baseline.json` after the offline seed and before server/browser activity;
seed IDs, files, requests, or projections do not count as live evidence.

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
   `manifest.json`. The harness descriptor-re-reads both terminal files,
   recomputes the inventory, and cross-links every embedded screenshot and TTS
   cache hash before it can return success.
5. Confirm the sanitized telemetry summary protocol is
   `pomegranagent-live-uat-telemetry-summary/v1` and contains, in exact order:
   two roster attempts; greeting TTS; request-one DeepSeek chat; reply-one TTS;
   request-two DeepSeek chat; reply-two TTS; fixed-reply TTS; one extraction;
   and one assessment. Provider events have exactly
   `audio_bytes`, `cache_relative_path`, `cache_sha256`, `correlation_id`,
   `error_class`, `latency_bucket`, `model`, `operation`, `parse_valid`,
   `provider`, `response_bytes`, `response_sha256`, `status`, and `voice`.
   DeepSeek events must be raw-JSON parse-valid, successful, correlated to the
   two exact provider-backed request UUIDs or the analysis job, and use the
   configured model. All four TTS events must use exactly
   `zh-CN-XiaoxiaoNeural`; each nonempty byte count, audio hash, message-text
   correlation, and run-owned cache path/hash must agree with DB provenance.
   A local terminal reply never counts as provider success.
6. Confirm the harness's actual-value and forbidden-pattern scan completed both
   before and after the terminal manifest write. The exact manifest bytes are
   scanned for registered secrets plus authorization, bearer, cookie, session,
   and token patterns. If doing an
   additional pattern check, report only affected file names and never print
   matching content.
7. Visually inspect selected screenshots for credentials or private browser
   state, then copy only redacted, instruction-worthy images into
   `docs/manual/assets/<run-id>/`. Never add the raw run directory to Git.
8. Commit only the curated documentation/assets in the controller-owned Step 10
   commit. A failed run remains ignored and retained for release-owner review;
   start a new run rather than modifying its evidence into `COMPLETE`.
