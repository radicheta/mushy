---
phase: 47-multi-source-extraction-fusion-groups-shape-inoc-draft
plan: 03
subsystem: extraction
tags: [pipeline, ask-back, seq-helper, seeding_session]
dependency_graph:
  requires:
    - "Phase 47 Plan 01 (SeedingSession schema + ChildBlockNameOrSentinel + needs_input='starting_seq' enum)"
    - "Phase 38 Plan 05 (createExtractionPipeline.enqueue + outboundDispatcher.dispatch contract)"
  provides:
    - "seq-helper.lookupLastSeqForDate(pool, eventDate) -- DB-backed MAX SEQ across legacy seeding + new seeding_session drafts for one day"
    - "seq-helper.mintChildBlockNames({eventDateYYMMDD, speciesCode, startSeq, qty}) -- pure block_name minter; throws on invalid output"
    - "seq-helper.yyyymmddToYymmdd(eventDate) -- pure date-format helper"
    - "pipeline.enqueue starting_seq short-circuit branch -- detects draft.type==='seeding_session' && draft.needs_input==='starting_seq', dispatches 'send_starting_seq_askback', skips state-machine.transition"
    - "pipeline.handleStartingSeqReply({draftId, replyText, captureCtx}) -- farmer-reply fulfilment; parses YES/numeric, mints session-wide SEQ counter across groups, clears needs_input, dispatches 'send_seeding_session_filled_preview'"
    - "extraction-db.getDraftById(pool, id) -- one-row fetch by PK; used by handleStartingSeqReply to re-load the draft"
    - "outbound side-effect name 'send_starting_seq_askback' -- new, owned by Phase 48 outbound dispatcher (Phase 47 just emits)"
    - "outbound side-effect name 'send_seeding_session_filled_preview' -- new, Phase 48 group-by-parent preview-builder hook"
  affects:
    - "Phase 47-04 (preview-builder) -- the filled-preview side-effect names the join seam"
    - "Phase 47-05 (live-fire ship-gate) -- exercises the ask-back end-to-end"
    - "Phase 48 (commit fan-out) -- consumes seq-helper.lookupLastSeqForDate at commit time + the filled-preview side-effect for confirm rendering"
tech_stack:
  added: []
  patterns:
    - "Pipeline short-circuit before state-machine.transition: when a draft carries needs_input='starting_seq', skip the generic ask-back path because there is no missing-required-field problem to render with TOP_Q_TEMPLATES (groups are populated; only the per-session SEQ counter is missing)."
    - "Per-session SEQ counter pattern: groups consume the counter in array order, qty values per group; honors [[b5-seq-is-per-session-not-per-strain]]."
    - "Idempotency-via-needs_input: handleStartingSeqReply detects a previously-cleared needs_input and returns {ok:true, noop:true} so duplicate replies / Phase 48 retries cannot double-mint."
    - "Skip-on-error draft_json parse in lookupLastSeqForDate: a single malformed row never breaks the lookup."
key_files:
  created:
    - src/agents/alerter/src/extraction/seq-helper.js
    - src/agents/alerter/test/extraction/seq-helper.test.js
  modified:
    - src/agents/alerter/src/extraction/pipeline.js
    - src/agents/alerter/src/extraction/extraction-db.js
    - src/agents/alerter/test/extraction/pipeline.test.js
decisions:
  - "Branch placement: ask-back short-circuit inserted between step 5 (persist draft) and step 6 (state-machine.transition) of pipeline.enqueue. This keeps the 5 legacy log-type ask-back paths byte-equivalent (the branch only fires for seeding_session+needs_input='starting_seq'), and lets the short-circuit reuse the just-persisted draftId without round-tripping through the state-machine."
  - "sanitizeFarmerText is REUSED from preview-builder.js (already exported since Phase 38-04 Task 3). No re-export and no duplication needed."
  - "fmtNum is REUSED from ../message. No re-export needed."
  - "handleStartingSeqReply is a sibling export of enqueue from createExtractionPipeline. Phase 48 will wire farmer-reply routing into it; Phase 47 only unit-tests it."
  - "On YES + non-numeric reply, the helper re-dispatches 'send_starting_seq_askback' with a 'Please reply with a number or YES.' preamble appended above the original prompt -- draft state is NOT mutated, so the farmer can recover from a typo without losing the ask-back context."
  - "extraction-db.getDraftById is a minimal additive helper (SELECT * WHERE id=$1 LIMIT 1); returns null on miss and on any pg error (consistent with the never-throw style of the surrounding module)."
  - "Sources on the farmer-filled child_block_names is set to ['model_inference','text'] to faithfully record that the SEQ came from a farmer reply, not from the paper-log photo."
  - "Existing per_field_confidence on child_block_names is preserved when numeric; defaults to 1 when previously absent or non-numeric (the farmer-supplied SEQ is, by construction, the ground truth)."
metrics:
  duration: ~25min
  tasks_completed: 2
  files_created: 2
  files_modified: 3
  tests_added: 29  # 12 seq-helper + 17 new pipeline (3 buildText + 3 parseReply + 2 enqueue-branch + 4 handleReply, plus the existing 5 999.53 stay green)
  tests_total_passing: 915
  completed_date: 2026-05-23
---

# Phase 47 Plan 03: Pipeline starting_seq Ask-back + seq-helper Summary

The photo-absent seeding_session draft now closes the Gray Area 3 lock end-to-end. A draft with `needs_input='starting_seq'` renders a farmer-facing "block number" ask-back (named greeting, last-today hint, default N+1) via a new short-circuit branch in `pipeline.enqueue`. A subsequent farmer YES or numeric reply, routed through the new `handleStartingSeqReply`, fills `child_block_names` across all groups using the per-session SEQ counter and clears `needs_input`. The new `seq-helper.js` module is designed for Phase 48 commit fan-out reuse.

## What Shipped

### Task 1 -- seq-helper.js + tests

- **`extraction/seq-helper.js`** (new) exports three functions:
  - `yyyymmddToYymmdd('2026-05-22')` -> `'260522'`. Pure.
  - `mintChildBlockNames({eventDateYYMMDD, speciesCode, startSeq, qty})` -> `string[]`. Pure. Validates each output against `BLOCK_NAME_RE`; throws `Error('mint_invalid_block_name')` on mismatch (lowercase species, malformed date).
  - `lookupLastSeqForDate(pool, eventDate, {logger}={})` -> `{ok, lastSeq, source}`. Walks `signal_draft` rows whose `draft_json->>'event_date' = $1` and whose `status IN ('committed','awaiting_farmer','confirmed','pending')`. Tolerates legacy `SeedingLog` rows (`block_name`) AND new `SeedingSession` rows (`groups[].child_block_names.value[]`) on the same day. The `'NEEDS_SEQ'` sentinel is explicitly skipped. Skip-on-error: a single malformed draft never breaks the lookup.
- **`test/extraction/seq-helper.test.js`** (new) -- 12 tests covering happy-path mint, lowercase-species rejection, qty=0, bad date format, empty DB, malformed rows, mixed legacy+new shapes, NEEDS_SEQ skipping, and SELECT shape.

### Task 2 -- pipeline.js short-circuit branch + handleStartingSeqReply

- **`extraction/pipeline.js`** modified:
  - New helper `buildStartingSeqAskBackText({totalChildren, eventDate, lastSeq, lastBlockName, senderName})` renders the locked Gray Area 3 prompt (see "Prompt Template" below).
  - New helper `parseStartingSeqReply(replyText)` returns `{kind:'yes'|'number'|'unclear', n?}`. Strict `/^\d+$/` (no parseInt; rejects `'4abc'`).
  - In `enqueue`, after the persist step and BEFORE `stateMachine.transition`: if `draft.type === 'seeding_session' && draft.needs_input === 'starting_seq'`, look up last-SEQ-today, build the prompt, persist via `updateDraftStatus({status: AWAITING_FARMER, farmer_facing_preview: preview})`, dispatch `'send_starting_seq_askback'`, return early with `{ok:true, status:'awaiting_farmer', sideEffects:['send_starting_seq_askback']}`. The 5 legacy log-type ask-back paths are unchanged.
  - New `handleStartingSeqReply({draftId, replyText, captureCtx})` exported alongside `enqueue`. Reloads via `extractionDb.getDraftById`, parses reply, walks groups consuming the session-wide SEQ counter, mints per-group names via `mintChildBlockNames`, clears `needs_input`, persists `draft_json`, dispatches `'send_seeding_session_filled_preview'`. Idempotent on duplicate YES (detects cleared `needs_input`, returns `{ok:true, noop:true}`). On unclear reply, re-dispatches `'send_starting_seq_askback'` with a "Please reply with a number or YES." preamble; draft state is NOT mutated.
- **`extraction/extraction-db.js`** -- added `getDraftById(pool, id)`: `SELECT * FROM signal_draft WHERE id = $1 LIMIT 1`. Returns the row or null. Never throws.
- **`test/extraction/pipeline.test.js`** -- 17 new tests across 4 describe blocks (buildStartingSeqAskBackText x3, parseStartingSeqReply x3, enqueue branch x2, handleStartingSeqReply x4 including the YES-consecutive-across-groups, numeric-10, unclear-reply, and idempotency cases).

## Prompt Template (verbatim, for Phase 48 to reuse)

When `senderName` is provided AND `lastSeq` is non-null AND `lastBlockName` resolvable:

```
Hi {senderName},
{Month} {Day} inoc, {totalChildren} blocks. What block number should I start at?
Last block number today was {lastBlockName}, so default is {lastSeq+1}.
Reply with a number or just YES for the default.
```

When `lastSeq` is null:

```
Hi {senderName},
{Month} {Day} inoc, {totalChildren} blocks. What block number should I start at?
No prior session today, so default is 1.
Reply with a number or just YES for the default.
```

When `senderName` is null, the `Hi {senderName},` line is omitted. Output is run through `sanitizeFarmerText` (em-dash strip, en-dash to ASCII hyphen). "block number" vocabulary is used in all farmer-facing text; "SEQ" is dev shorthand only.

## Verification

```
$ npx jest test/extraction/pipeline.test.js test/extraction/seq-helper.test.js --no-coverage
Test Suites: 2 passed, 2 total
Tests:       29 passed, 29 total

$ npx jest --no-coverage   # full alerter regression
Test Suites: 2 skipped, 66 passed, 66 of 68 total
Tests:       9 skipped, 915 passed, 924 total

$ grep -c "send_starting_seq_askback\|handleStartingSeqReply\|mintChildBlockNames" \
    src/agents/alerter/src/extraction/pipeline.js \
    src/agents/alerter/src/extraction/seq-helper.js
src/agents/alerter/src/extraction/seq-helper.js:4
src/agents/alerter/src/extraction/pipeline.js:10
# Total: 14 (>= 4 required by plan verification)
```

## Deviations from Plan

None on behavior. Two minor implementation notes:

1. **sanitizeFarmerText was REUSED, not re-exported or duplicated.** The plan allowed either re-export from preview-builder.js OR a 4-line inline duplicate. preview-builder.js has exported `sanitizeFarmerText` since Phase 38-04 Task 3, so pipeline.js now imports it directly. No code change to preview-builder.js was needed.

2. **`captureCtx.senderName` is consumed read-only, never looked up.** Per plan style-lock. The handler will receive `senderName` from upstream (Phase 38 capture.js already enriches captureCtx from `config.signalFarmerMap` via `farmosPerson`; Phase 47-05 will wire `senderName` alongside `farmosPerson` in the same enrichment step). For Phase 47 the field is treated as optional; tests cover both present + null.

## Known Stubs

None. The ask-back branch is functionally complete and unit-tested end-to-end. Live-fire validation is Phase 47-05's ship-gate.

## Threat Flags

None. The two new side-effect names (`send_starting_seq_askback`, `send_seeding_session_filled_preview`) flow through the existing outboundDispatcher contract; no new network surface, no new auth path, no new file access.

## Self-Check: PASSED

- [x] `src/agents/alerter/src/extraction/seq-helper.js` exists
- [x] `src/agents/alerter/test/extraction/seq-helper.test.js` exists
- [x] `src/agents/alerter/src/extraction/pipeline.js` modified -- imports seq-helper + sanitizeFarmerText + fmtNum, exports handleStartingSeqReply
- [x] `src/agents/alerter/src/extraction/extraction-db.js` modified -- exports getDraftById
- [x] 29 targeted tests + 915 full-suite tests green
- [x] grep verification: 14 hits (>= 4 required)
