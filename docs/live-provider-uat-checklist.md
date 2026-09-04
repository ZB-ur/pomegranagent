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
- Physical microphone capture/acoustic recognition is the only item that may
  be recorded as `HUMAN_UAT_REQUIRED`. All keyboard, button, focus, layout,
  controlled-text, DeepSeek, analysis, and Edge-TTS checks must run.

## Start and handoff

1. Confirm the intended Task 10 commit and a clean result from all four
   deterministic release gates.
2. Start the harness in a dedicated terminal and keep its stdin connected:

   ```bash
   /Users/lddmay/AiCoding/pomegranagent/.venv/bin/python scripts/run_live_provider_uat.py --retain --print-runtime-json
   ```

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
   canonical WebP display URLs. Record `live_child_id`, `child_avatar_id`,
   `live_duck_id`, and `duck_avatar_id`.
3. `invalid_avatar_rejection`: choose the printed invalid-avatar fixture and
   verify a visible rejection without changing the successful avatar.
4. `monthly_roster_conflict_retry`: select two children for multiple dates,
   submit the month, intentionally exercise one conflict, then retry with a new
   request ID and verify the final roster. Record `monthly_pairs` as ISO dates
   mapped to exactly two distinct child IDs.
5. `child_conversation_real_provider_tts`: select the new child and complete a
   real multi-turn diary exchange by controlled text handoff. Verify real model
   replies and audible/generated Edge-TTS output. Record
   `live_conversation_id`.
6. `conversation_completion_analysis`: complete the conversation, wait for the
   real analysis worker to succeed, and record `analysis_job_id`.
7. `teacher_today_queues`: verify the completed item appears in the correct
   Today queue and other queue states remain coherent.
8. `review_edit_confirm`: open the analysis, edit the review, confirm exactly
   three dimension scores, and record `assessment_id`.
9. `weekly_metrics_growth`: verify the conversation contributes to the intended
   weekly metrics and Growth view. Record the Monday ISO date as
   `weekly_week_start`.
10. `advanced_search_pagination_deep_link`: search privately with a literal
    keyword, load the next frozen cursor page, and open the result through the
    Review deep link. Record nonempty, disjoint `search_page_one_ids` and
    `search_page_two_ids`, plus `search_result_conversation_id` equal to the
    retained live conversation.
11. `search_empty_state`: submit a search that has no matches and verify its
    explicit empty state without disturbing the successful search evidence.
12. `logout_login_retained_state`: logout, unlock again, and verify the roster,
    avatars, conversation, confirmed review, weekly metrics, and search result
    remain available.

Use each provenance key exactly once across the journey's `entity_ids` objects;
use `{}` when a step has no new provenance value. Do not infer IDs from display
text when the API/URL supplies the stable ID.

## Screenshot evidence

Capture real PNG screenshots directly under the printed `screenshots_dir`.
Use stable lowercase semantic names and do not overwrite a captured file.
Collect instruction-worthy states covering exactly these viewport values:

- Teacher: `1024x768` and `1440x900`.
- Child: `1024x576` and `1280x720`.

At minimum, show teacher management/review/report/search state and the child
canonical-avatar/conversation state across those four viewports. For each image,
record the relative path `screenshots/<semantic-name>.png`, semantic name,
viewport, one journey step ID, and concrete visible assertions. Confirm dialogs
fit, the active control/focus is visible, canonical avatars or fallback are
visible as intended, fixed panels do not overlap content, and there is no
horizontal scrolling. Do not capture credential entry, cookies, request
headers, provider payloads, or developer tools.

## Controller evidence and finalize

Write `controller-evidence.json` atomically at the exact printed path as one
UTF-8 canonical JSON object (sorted keys, compact separators, one trailing
newline). It must contain exactly:

- `protocol`: `pomegranagent-live-uat-controller/v1`
- the printed `run_id` and literal 40-hex `source_head`
- `journey`: the 12 ordered entries above; each has exactly `step_id`, `status`,
  `visible_assertions`, and `entity_ids`
- `screenshots`: entries with exactly `relative_path`, `semantic_name`,
  `viewport`, `journey_step`, and `visible_assertions`
- `issues`: safe summaries with exactly `severity`, `step_id`, and
  `safe_summary`; do not include raw exception/provider/credential content
- `human_uat_required`: one entry with gate ID
  `physical_microphone_acoustic_recognition`, status `HUMAN_UAT_REQUIRED`, and a
  safe summary

Do not include unknown fields, duplicate steps/semantic names/paths, absolute or
traversing screenshot paths, a blocker issue, or another human-only gate.

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
4. Confirm the sanitized provider summary contains successful real
   `chat_reply`, `extract_info`, `assess_conversation`, and `tts` events, with
   only provider/model/voice/status/latency bucket/byte counts/error class.
5. Confirm the harness's actual-value and pattern scan completed. If doing an
   additional pattern check, report only affected file names and never print
   matching content.
6. Visually inspect selected screenshots for credentials or private browser
   state, then copy only redacted, instruction-worthy images into
   `docs/manual/assets/<run-id>/`. Never add the raw run directory to Git.
7. Commit only the curated documentation/assets in the controller-owned Step 10
   commit. A failed run remains ignored and retained for release-owner review;
   start a new run rather than modifying its evidence into `COMPLETE`.
