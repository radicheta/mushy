---
phase: 47-multi-source-extraction-fusion-groups-shape-inoc-draft
plan: 05
subsystem: extraction
tags: [integration-test, ship-gate, fixtures, anthropic-mock, live-fire-gated, inoc]
dependency_graph:
  requires:
    - "47-01 (SeedingSession schema)"
    - "47-02 (SYSTEM_PROMPT + tu_fewshot_4)"
    - "47-03 (pipeline ask-back + handleStartingSeqReply + seq-helper)"
    - "47-04 (preview-builder placeholder)"
  provides:
    - "Hermetic CI regression guards for INOC-01, INOC-02, INOC-03, INOC-05"
    - "Real-prod fixture corpus at test/fixtures/seeding-session-may22/ (transcript + photo + text + expected draft)"
    - "Live-fire ship-gate (EVAL_RUN_LIVE=1 gated) for INOC-01/02 against the real May 22 capture"
  affects:
    - "Phase 48 commit fan-out (consumes the same SeedingSession draft shape these tests lock)"
    - "Phase 49 eval-corpus formalization (May 22 fixture set is the seed)"
tech_stack:
  added: []
  patterns:
    - "Hermetic Anthropic mock via injectedClient -> tool_use envelope (mirrors extractor's createExtractor({client}) seam)"
    - "Live-fire gate via process.env.EVAL_RUN_LIVE !== '1' (mirrors Phase 44 paid-eval convention per [[feedback_persist_paid_results_default]])"
    - "Real-prod fixtures pulled directly from prod DB + /data/signal-capture (no synthesis where real data exists)"
    - "End-to-end pipeline.enqueue assertions on pool.query INSERT params (no DB write -- pool is stubbed)"
key_files:
  created:
    - src/agents/alerter/test/fixtures/seeding-session-may22/transcript.txt
    - src/agents/alerter/test/fixtures/seeding-session-may22/text-followup.txt
    - src/agents/alerter/test/fixtures/seeding-session-may22/paper-log.jpg
    - src/agents/alerter/test/fixtures/seeding-session-may22/expected-draft.json
    - src/agents/alerter/test/fixtures/seeding-session-may22/README.md
    - src/agents/alerter/test/extraction/integration/seeding-session-may22.test.js
    - src/agents/alerter/test/extraction/integration/seeding-session-conflict.test.js
    - src/agents/alerter/test/extraction/integration/seeding-session-photo-absent.test.js
  modified: []
decisions:
  - "Live-fire path is wired but NOT executed by this plan. The operator runs it separately (cost-bounded). Hermetic mock is the CI gate; live-fire is the operator-attested ship-gate."
  - "Fixtures are real prod data, not synthesized. Pulled from signal_capture rows 01KS8KHYTRJDZQEM5C4P989B8B (audio transcript), 01KS8PT5YH9G76Y3BC54TZV19B (text), and the on-disk attachment for 01KS8KHYTSYYGV500ZQVEY12VX (81KB JPEG)."
  - "expected-draft.json hand-built from CONTEXT.md INOC-01 spec; validated via SeedingSession.safeParse + Submission.safeParse before commit. Each provenanced field carries sources=['audio','paper_log_photo'] for parent/species/qty and sources=['paper_log_photo'] for child_block_names."
  - "Conflict test is hermetic-only (no live-fire branch). The may22 test already proves end-to-end model behavior; the conflict fixture is synthetic so a live run would just re-test the same mock-vs-mock loop at LLM cost."
  - "Photo-absent test uses a mini in-memory extractionDb stub (makeLiveExtractionDb) so the round-trip enqueue -> dispatch askback -> handleStartingSeqReply -> filled draft can be asserted against persisted state. The 47-03 pipeline tests use jest-spy on updateDraftStatus; this one needs a live row to read back."
  - "Test naming: one describe block per INOC requirement ID, no per-task helper sprawl. Each test file is single-describe to keep the ship-gate intent obvious from the file name."
metrics:
  duration: ~30min
  tasks_completed: 1   # Task 1 only; Task 2 (live-fire attestation) is operator-driven
  files_created: 8
  files_modified: 0
  tests_added: 4   # 3 hermetic + 1 live-fire (gated, runs as no-op skip in CI)
  tests_total_passing: 919   # was 915 at end of Plan 03; +4 from this plan, full suite green
  completed_date: 2026-05-23
---

# Phase 47 Plan 05: Hermetic integration ship-gate Summary

Three hermetic integration tests now cover INOC-01/02/03/05 end-to-end against
the post-47-03 pipeline + 47-04 preview-builder + 47-02 prompt-aware extractor
shape. A fourth test inside the may22 file runs the same fixture against the
LIVE Anthropic API when `EVAL_RUN_LIVE=1` -- this is the operator-gated
ship-gate proof that the live model produces the same shape the mock asserts.

This plan executed the hermetic half only. Live-fire is Don Santiago's
follow-up (see below).

## What Shipped

### Fixtures: real May 22 prod capture (5 files)

Pulled 2026-05-23 from the prod `signal_capture` table on `mushy-timescale-1`
plus `/data/signal-capture/2026-05-22/`:

- `transcript.txt` -- 761-char Whisper transcript from capture
  `01KS8KHYTRJDZQEM5C4P989B8B`. Decodes 5 parents across 2 species in one
  voice memo ("all right may 22 inoculation session...").
- `text-followup.txt` -- 131-char farmer text from capture
  `01KS8PT5YH9G76Y3BC54TZV19B` ("yes i still want to log this inoculation
  session from may 22...").
- `paper-log.jpg` -- 82 KB JPEG, the paper-log photo from capture
  `01KS8KHYTSYYGV500ZQVEY12VX`. Checked in binary; lives under `test/fixtures/`
  so jest's `testPathIgnorePatterns` skips it during test discovery.
- `expected-draft.json` -- canonical `seeding_session` Submission body
  (5 groups, 11 children, session-wide SEQ `260522_SHI_1..3` +
  `260522_KOY_4..11`). Validated against `SeedingSession.safeParse` AND
  `Submission.safeParse` (wrapped in the multi-draft envelope) before commit.
- `README.md` -- one-line provenance per file + the canonical 5-group
  breakdown + live-fire pointer.

### Three new integration test files

- `seeding-session-may22.test.js` (INOC-01 + INOC-02). Two tests:
  - **Hermetic**: injects a mock Anthropic client that returns the gold draft
    wrapped in a `tool_use` envelope. Asserts pipeline.enqueue persists the
    draft with all 11 named child_block_names in the INSERT params, every
    provenanced field carries non-empty `sources[]` from `SOURCE_ENUM`,
    `child_block_names.sources` includes `paper_log_photo` (INOC-02), and
    preview-builder produces the Phase 48 placeholder ("11 blocks across 5
    groups for 2026-05-22 ... Phase 48").
  - **Live-fire (EVAL_RUN_LIVE=1)**: calls the real extractor against the
    fixture, asserts the real model emits a draft containing all 11 canonical
    child_block_names. Skips cleanly with a console.log if the env var is
    unset.
- `seeding-session-conflict.test.js` (INOC-03). One hermetic test. Synthetic
  fixture: audio says `260118_SHI_23`, photo shows `260118_SHI_25`. Mock
  returns a draft where `groups[1].parent.value` is the photo's value and
  `conflicts[0]` lists both candidates with `resolution:
  'photo_wins_implicit'`. Asserts: pipeline persists the photo's value (not
  audio's); the conflict entry survives the round-trip; the farmer-facing
  preview contains neither `'118-23'`, `'118-25'`, nor the word `'conflict'`
  (CONTEXT.md Gray Area 4 lock).
- `seeding-session-photo-absent.test.js` (INOC-05). One hermetic test with a
  full round-trip: pipeline.enqueue -> ask-back dispatched -> persisted draft
  retains `'NEEDS_SEQ'` sentinels -> farmer replies `'4'` ->
  handleStartingSeqReply mints `260522_SHI_4..6, 260522_KOY_7..14` (11
  consecutive names across 2 groups starting at 4), clears `needs_input`,
  dispatches `send_seeding_session_filled_preview`. Asserts every filled name
  matches `BLOCK_NAME_RE`.

### Hermetic test results

```
$ cd src/agents/alerter && npx jest test/extraction/integration --no-coverage
PASS test/extraction/integration/seeding-session-may22.test.js
PASS test/extraction/integration/seeding-session-photo-absent.test.js
PASS test/extraction/integration/seeding-session-conflict.test.js
PASS test/extraction/integration.test.js    # pre-existing Phase 38 harness, untouched

Test Suites: 4 passed, 4 total
Tests:       17 passed, 17 total    # 4 new + 13 pre-existing in the dir
Time:        2.851 s

$ npx jest --no-coverage    # full alerter regression sweep
Test Suites: 2 skipped, 69 passed, 69 of 71 total
Tests:       9 skipped, 919 passed, 928 total      # was 915 at end of Plan 03; +4 here
```

## Live-Fire Instructions (operator-only)

To attest the live model produces the same shape the mock asserts:

```bash
cd src/agents/alerter
EVAL_RUN_LIVE=1 \
  ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  npx jest test/extraction/integration/seeding-session-may22.test.js --no-coverage
```

Expected console output (in addition to the hermetic test passing):

```
LIVE-FIRE pipeline result: {
  "ok": true,
  "draftId": "draft-CAP_MAY22_LIVE-0",
  "status": "awaiting_farmer",  // or "ready" depending on per-field confidence
  ...
}
```

The live-fire test asserts the real model's draft contains all 11 canonical
child_block_names (`260522_SHI_1..3 + 260522_KOY_4..11`). Per CONTEXT.md
INOC-01 wording, **child_block_names is the regression guard, not the parent
strings** -- the audio transcript ambiguously says "one eighteen twelve" /
"104" for the KOY parents, and the model may decode these differently. If the
draft has the right shape (5 groups, 11 children, correct child_block_names)
but different parent strings, that is a PASS; record the parent-string
deviation in `47-LIVE-FIRE.md` for the paper trail.

**Cost estimate:** ~$0.10 per run. Sonnet 4.6, ~3-5K input tokens (image
~1.5K, transcript ~250, text ~50, system prompt cached, few-shot cached),
~1-2K output tokens for the SeedingSession JSON.

**Paper trail:** Save the full stdout + the rendered draft to
`.planning/phases/47-multi-source-extraction-fusion-groups-shape-inoc-draft/47-LIVE-FIRE.md`
with timestamp + cost. Per `[[feedback_persist_paid_results_default]]`, never
overwrite previous live-fire transcripts -- if you re-run, append with a new
timestamp section.

## Deviations from Plan

None on behavior. Implementation notes:

1. **Conflict test is hermetic-only (no live-fire branch).** The plan
   allowed live-fire on any of the three; I dropped it on conflict and
   photo-absent because:
   - Conflict fixture is synthetic (no real "audio:118-23 vs photo:118-25"
     prod row exists), so a live run would just re-test the mock-vs-mock loop
     at real cost.
   - Photo-absent fixture is also synthetic.
   - The may22 file's live-fire IS the live-model attestation; the other two
     prove the pipeline contract holds for those specific shapes regardless
     of how the model arrived at them.
2. **No `--no-verify`, no `git commit` flag bypass.** Pre-commit hooks (if
   any) ran clean.
3. **Photo-absent test uses a mini in-memory extractionDb stub** rather than
   the prod extraction-db module. The 47-03 unit tests already cover the
   handleStartingSeqReply contract against jest-spy mocks; this integration
   test needed the persisted-row read-back after enqueue, which prod
   extraction-db cannot deliver without a real pg pool. The stub mirrors the
   3 methods the round-trip exercises (insertDraft, updateDraftStatus,
   getDraftById) and nothing else.
4. **INOC-04 is explicitly Phase 48 scope** per the plan's success_criteria
   and the CONTEXT.md INOC-04 carry-forward marker. Not covered here.

## Hermetic vs Live-Fire Attestation Status

| INOC ID | Hermetic | Live-fire |
|---------|----------|-----------|
| INOC-01 (5-group/11-child shape) | yes (this plan) | gated, operator-pending |
| INOC-02 (per-field provenance) | yes (this plan) | gated, operator-pending (via same may22 test) |
| INOC-03 (conflict logged + farmer preview clean) | yes (this plan) | not in scope (synthetic fixture) |
| INOC-04 (single-parent legacy) | n/a | n/a -- Phase 48 owns it |
| INOC-05 (photo-absent ask-back + reply fills) | yes (this plan) | not in scope (synthetic fixture) |

## Known Stubs

None in shipped code or test fixtures. The live-fire branch is a deliberate
gated execution path, not a stub.

## Threat Flags

None. Two notes:
- `paper-log.jpg` is a binary fixture from a real prod capture. The image
  shows the farmer's paper log handwriting; no PII visible (no names, no
  phone numbers, no addresses). Safe to commit.
- The transcript text contains no PII (no names, no contacts -- just bag
  identifiers and species codes).

## Self-Check: PASSED

- [x] `src/agents/alerter/test/fixtures/seeding-session-may22/transcript.txt` exists (762 bytes from prod)
- [x] `src/agents/alerter/test/fixtures/seeding-session-may22/text-followup.txt` exists (132 bytes from prod)
- [x] `src/agents/alerter/test/fixtures/seeding-session-may22/paper-log.jpg` exists (82743 bytes from prod /data)
- [x] `src/agents/alerter/test/fixtures/seeding-session-may22/expected-draft.json` validates against SeedingSession AND Submission
- [x] `src/agents/alerter/test/fixtures/seeding-session-may22/README.md` documents file origins
- [x] `test/extraction/integration/seeding-session-may22.test.js` -- 2 tests (1 hermetic + 1 live-gated)
- [x] `test/extraction/integration/seeding-session-conflict.test.js` -- 1 hermetic test
- [x] `test/extraction/integration/seeding-session-photo-absent.test.js` -- 1 hermetic test
- [x] All 4 integration test suites green (17 tests)
- [x] Full alerter suite 919 passing, 0 failing (was 915 at Plan 03 end, +4 here)
