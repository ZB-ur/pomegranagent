# Teacher Task 7 Report — Sanitized Lovable prototype pack

## Scope

Start HEAD: `69a1d072b96fe899c00df152f6796b60a4bfb6e7`

This task creates only a deterministic, fictional Lovable input pack and its
standard-library safety test. It does not change application code, read the
runtime database, generate a prototype, or contact an external service.

Owned local-pack paths:

- `docs/lovable/teacher-prototype-prompt.md`
- `docs/lovable/sanitized-demo-data.json`
- `docs/lovable/teacher-prototype-checklist.md`
- `tests/test_lovable_artifacts.py`
- `.superpowers/sdd/2026-08-23-teacher-workbench-and-acceptance/task-7-report.md`

## Contract review

The independent brief review initially returned NO-GO because ordinary pytest
would load `tests/conftest.py` and cross the document-only database boundary.
The execution brief and every command were changed to use `--noconftest`. The
reviewer then returned Contract GO with no P0/P1.

Three P2 recommendations were also incorporated before implementation:

- `Supabase` and `GitHub` are allowed only in exact negative sentences.
- Prompt and checklist state that the JSON is a visual projection, not an API
  schema.
- Each staged TDD slice has an exact pytest node and expected count.

## TDD evidence

All pytest commands used `./.venv/bin/python -m pytest --noconftest` and ran
serially.

1. Initial RED, before any pack artifact existed:
   - `tests/test_lovable_artifacts.py`: 12 failed.
   - Every failure traced to one of the three missing pack files.
2. JSON GREEN:
   - exact JSON node: 1 passed.
   - JSON parser: passed.
   - full file at that boundary: 9 passed, 3 failed; only prompt/checklist
     absence remained.
3. Prompt GREEN:
   - exact prompt node: 1 passed.
   - full file at that boundary: 10 passed, 2 failed; only checklist absence
     and the consequent complete-pack scan remained.
4. Complete local pack GREEN:
   - first fresh full run: 12 passed.
   - second fresh full run: 12 passed.
   - hostile nested mutation matrix: 8 passed.
5. Independent-review remediation:
   - four focused P1 nodes first failed 0/4, covering the missing complete-input
     sentence, duplicate JSON members, fail-open text patterns/context, and a
     non-standard-library test import.
   - after minimal fixes, the same focused set passed 4/4.
   - the expanded full suite passed 15/15 twice, fresh.
   - the eight hostile nested mutation tests passed 8/8 with seven unrelated
     tests deselected.
6. Second-review matcher remediation:
   - the new focused test first failed 0/1 and listed 13 missed variants across
     adjacent integration names, import/function forms, expanded loopback,
     assignments, and spaced phone numbers.
   - after the matcher fix, the focused test passed 1/1.
   - the second-review expanded full suite passed 16/16 twice, fresh.
   - the hostile nested mutation tests remained 8/8 with eight unrelated tests
     deselected.
7. Third-review matcher remediation:
   - the new focused test first failed 0/1 and listed all seven missed IPv6
     loopback, landline/mobile phone, and fenced-source variants.
   - after the matcher fix, the focused test passed 1/1.
   - the expanded full suite passed 17/17 twice, fresh.
   - the hostile nested mutation tests remained 8/8 with nine unrelated tests
     deselected.
8. Fourth-review contact/path remediation:
   - the focused test first failed 0/1 and listed five missed international
     phone, slash/tilde home-path, and Chinese-adjacent email variants.
   - after the matcher fix, the focused test passed 1/1.
   - the expanded full suite passed 18/18 twice, fresh.
   - the hostile nested mutation tests remained 8/8 with ten unrelated tests
     deselected.

The hostile matrix rejects a nested URL, unknown child name, dangling speaker
reference, duplicate score dimension, integer ID, secret-shaped content,
source-shaped content, and an extra nested key without writing a hostile file.

## Safety and consistency evidence

- JSON is valid UTF-8 and passes `python -m json.tool`.
- Test source passes `python -m py_compile`.
- Prompt size: 5,627 bytes.
- JSON size: 5,076 bytes.
- Checklist size: 4,605 bytes.
- Recursive schema/cross-reference/name/date/status validation passes.
- Direct path, endpoint, secret/config, provider, source-dump, email, and phone
  policy scans return no forbidden match.
- The pack contains exactly four fictional children, two fictional ducks, two
  roster entries, one row in each queue, one six-message selected transcript,
  two feeding records, one emotion/insight, and three delivered score
  dimensions.
- The prompt requests exactly two desktop screens and local mock behavior.
- The checklist contains 48 unchecked review items and marks the output as a
  non-production visual reference.

The preserved incident log remained exactly:

```text
SHA-256  5ee47c6b8322aee20aefecbf2344e8134cec18154fb7eb2d00c60116379fbeb7
size     2961585
mtime    1787939944
```

No shared conftest, application database, TTS cache, provider, browser, or
network path was invoked.

## External checkpoint and limitations

The local pack is the only completed deliverable at this checkpoint. No
Lovable project exists yet, and no share URL is claimed. After this pack passes
independent code review and is committed, an authenticated user-visible
Lovable session may receive only the prompt and JSON. The checklist remains
local. Any generated result is a visual/interaction reference and cannot be
treated as product acceptance or an application API contract.

## Code review

The first independent code review returned NO-GO with four P1 findings:
duplicate JSON keys were not observable after parsing; Windows/bare-repository/
source-import/integration-name patterns could bypass scanning; the prompt did
not freeze the two-document complete-input boundary; and the test imported a
third-party test API despite the standard-library-only contract. It also found
two P2 items: the 32 KiB boundary was inclusive and this report's review status
would become stale.

All six items were corrected via focused RED/GREEN evidence. The parser now
rejects duplicate members before validation, text exceptions are explicit and
context-specific, the prompt has the exact complete-input sentence, the test
imports only a checked standard-library allow-list, and the size boundary is
strictly less than 32 KiB.

The second independent review confirmed those fixes but found one remaining P1
in the same matcher boundary: Unicode-adjacent integration names, additional
import/function forms, expanded loopback, short/lowercase/export assignments,
and spaced phone forms were not all rejected. A focused test captured the full
miss list before the matcher was broadened; it then passed, followed by the
fresh 16/16 full suite twice. At that checkpoint, another independent verdict
was required.

The third independent review confirmed the second-review variants but found
one remaining P1: alternative valid IPv6 loopback notation, common landline/
parenthesized/dot-separated phones, and short Python/JavaScript fence aliases.
The focused RED contained all seven misses. The fix uses the standard-library
IP parser for IPv6 loopback detection, rejects both common mobile and landline
forms, and rejects every triple-backtick block instead of enumerating language
aliases. The focused node and fresh 17/17 full suite are GREEN. At that
checkpoint, another independent review was required.

The fourth independent review confirmed the third-review fixes but found the
standard international Chinese landline form that omits the domestic area-code
zero. The focused RED also included equivalent explicit brief boundaries for a
forward-slash Windows path, tilde home path, compact international mobile, and
an email next to Chinese text; five variants were initially missed. The matcher
now rejects those forms, the focused node is GREEN, and the fresh 18/18 full
suite passes twice.

The fifth independent review returned Code Review GO with no P0, P1, or P2.
It independently reran the 18-test suite, confirmed the 8 hostile cases and 10
deselected cases, verified the incident-log triplet, exact five-path staged
allow-list, report counts, and preservation of the user-owned dirty paths.
