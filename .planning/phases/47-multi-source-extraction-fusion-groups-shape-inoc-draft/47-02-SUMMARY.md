---
phase: 47-multi-source-extraction-fusion-groups-shape-inoc-draft
plan: 02
subsystem: extraction
tags: [system-prompt, few-shot, provenance, conflict-policy, seeding-session]
dependency_graph:
  requires:
    - "47-01 (SeedingSession + Provenanced + ConflictEntry schemas)"
  provides:
    - "SYSTEM_PROMPT sections: session-vs-single, provenance, conflict-resolution, missing-SEQ"
    - "FEW_SHOT pair (tu_fewshot_4) demonstrating May-22 5-group / 11-child seeding_session shape"
    - "FEW_SHOT well-formedness invariant: tu_fewshot_3 remains the live-handshake boundary"
  affects:
    - "Phase 47 Plan 03 (pipeline needs_input='starting_seq' handler)"
    - "Phase 47 Plan 05 (May-22 integration replay)"
    - "Phase 48 (commit fan-out reads the shape this prompt teaches the model to emit)"
tech_stack:
  added: []
  patterns:
    - "Provenance taught via verbatim {value, confidence, sources[]} description plus a worked few-shot example"
    - "Photo-wins-silent conflict policy with conflicts[] forensics, never surfaced to farmer"
    - "Sentinel literals as ask-back trigger ('NEEDS_SEQ', 'NO_PARENT')"
    - "Few-shot tool_use/tool_result chain preserves Plan 38-07 Rule 1 invariant (last tool_use closed by live-turn handshake)"
key_files:
  created: []
  modified:
    - src/agents/alerter/src/extraction/prompts/system.js
    - src/agents/alerter/test/extraction/extractor.test.js
decisions:
  - "Five-group framing for the few-shot: 3 SHI singletons (groups 0-2) + 2 KOY multi-child groups (groups 3-4, qty 4 each). 11 children total. Picked over the 3-group alternative because it directly mirrors the CONTEXT.md INOC-01 phrasing '11 blocks across 5 parents and 2 species' and exercises both single-child and multi-child group sizes in one example."
  - "Conflict demonstrated on groups[3].parent (KOY parent 260118_KOY_23 from audio vs 260118_KOY_25 from photo) so the model sees photo_wins_implicit applied to a real disagreement rather than as abstract policy text."
  - "tu_fewshot_4 inserted as the second-to-last assistant turn; tu_fewshot_3 remains the FINAL tool_use so extractor.js:53-91 buildInitialUserContent's live-turn tool_result handshake is untouched (Plan 38-07 Rule 1 preserved)."
  - "tu_fewshot_2's tool_result moved from the old continuity=replace user turn onto the new seeding_session user turn; the continuity=replace user turn now opens with tool_result for tu_fewshot_4. Verified by the new test 'each tool_use has matching tool_result in next user turn'."
metrics:
  duration: ~20min
  tasks_completed: 2
  files_created: 0
  files_modified: 2
  tests_added: 12  # 8 SYSTEM_PROMPT policy assertions + 4 FEW_SHOT well-formedness/Submission-validation
  tests_total_passing: 903  # was 872 at end of Plan 01; delta +31 (12 new here, 19 from prior Plan 01 surface)
  completed_date: 2026-05-23
---

# Phase 47 Plan 02: System prompt -- groups-shape session + provenance + conflict policy Summary

System prompt now teaches the model four new policies (session-vs-single, inline provenance, photo-wins-silent conflict, missing-SEQ ask-back) and the few-shot list contains one worked May-22 example that emits a structurally-valid SeedingSession draft with 5 groups, 11 children, and one photo_wins_implicit conflict entry. Downstream plans 03-05 can now exercise the new shape against a model that has actually been shown how to produce it.

## What Shipped

### Task 1 -- SYSTEM_PROMPT gains four policy sections

Inserted four new sections between `Field rules` and `Year handling (CRITICAL)`:

1. **Session vs single-event seeding** -- cardinality rule (total children > 1 => `seeding_session`; else `seeding`). Single-parent multi-child still emits `groups.length === 1`. `event_date` is day-grain YYYY-MM-DD; per-bag timestamps are derived downstream.
2. **Provenance (groups-shape only)** -- inline `{value, confidence, sources[]}` shape; sources[] is a non-empty subset of the closed enum `[audio, paper_log_photo, bag_label_photo, text, model_inference]`; multi-source agreement lists ALL sources.
3. **Conflict resolution (groups-shape only)** -- photo wins silently on audio-vs-photo disagreement; ALSO push an entry to `draft.conflicts[]` with `path`, two-element `candidates[]`, `resolution: 'photo_wins_implicit'`. NEVER surface conflicts in human-readable text.
4. **Missing SEQ ask-back** -- when no SEQ source available, emit `child_block_names.value` as an array of `'NEEDS_SEQ'` literals matching qty, set `draft.needs_input = 'starting_seq'`. Pipeline asks farmer back. Also documents `'NO_PARENT'` sentinel for fresh-grain inoc.

All four sections use the field-name vocabulary verbatim from `schemas/seeding-session.js` (parent, species, qty, child_block_names, event_date, groups, conflicts, needs_input). No em-dashes anywhere.

### Task 2 -- FEW_SHOT gains the May-22 multi-parent multi-species example (tu_fewshot_4)

Inserted a new (user, assistant) pair as the third pair of FEW_SHOT (now four pairs total). Positioning preserves the Plan 38-07 Rule 1 boundary: tu_fewshot_3 remains the LAST tool_use, so `extractor.buildInitialUserContent`'s `tool_result: tu_fewshot_3` block at runtime still closes the last unhandled tool_use.

- **User turn:** corpus_context + In-flight: none + synthetic audio transcript (3 shiitakes + 8 king oysters) + paper-log photo description (5 rows) + an explicit note that audio says KOY parent `260118_KOY_23` but photo shows `260118_KOY_25` (the conflict fixture).
- **Assistant turn:** `submit_extraction` tool_use `tu_fewshot_4` whose `drafts[0].draft` is type `seeding_session`, `event_date='2026-05-22'`, 5 groups, 11 total children with the canonical session-wide SEQ sequence `260522_SHI_1..3, 260522_KOY_4..7, 260522_KOY_8..11`. Conflicts[] carries the photo-wins entry for `groups[3].parent.value`.

The OLD continuity=replace pair (now fourth, with `tu_fewshot_3` assistant) had its opening `tool_result` switched from `tu_fewshot_2` to `tu_fewshot_4` so the chain remains intact.

### Five-group framing choice

Picked **3 SHI singletons + 2 KOY multi-child groups** over the 3-group alternative (1 SHI multi-child + 2 KOY multi-child). Reasoning:

- Mirrors CONTEXT.md INOC-01 wording "11 blocks across 5 parents and 2 species" exactly (5 parents == 5 groups).
- Exercises BOTH `qty=1` single-child groups AND `qty=4` multi-child groups in one example, so the model learns that group cardinality varies per row.
- Each SHI singleton has its own parent block_name, demonstrating that "same species, different parents" is one row per parent (not collapsed to a single qty=3 group).

## Verification

```
$ cd src/agents/alerter && npx jest test/extraction/extractor.test.js --no-coverage
Test Suites: 1 passed, 1 total
Tests:       26 passed, 26 total

$ npx jest --no-coverage    # full alerter regression
Test Suites: 2 skipped, 66 passed, 66 of 68 total
Tests:       9 skipped, 903 passed, 912 total

$ node -e "const {CACHEABLE_SYSTEM_BLOCKS} = require('./src/extraction/prompts/system'); const t = CACHEABLE_SYSTEM_BLOCKS[0].text; ['seeding_session','NEEDS_SEQ','photo_wins_implicit','needs_input','starting_seq','conflicts'].forEach(k=>{ if(!t.includes(k)) throw new Error('missing '+k); }); console.log('ok')"
ok

$ grep -c "tu_fewshot_4" src/agents/alerter/src/extraction/prompts/system.js
2
```

New tests (12):

- 8 in `Phase 47 Plan 02: SYSTEM_PROMPT teaches seeding_session policy` -- assert presence of every required token (`seeding_session`, `NEEDS_SEQ`, `photo_wins_implicit`, `needs_input`, `starting_seq`, `conflicts`, `NO_PARENT`, `groups`) + no em-dashes.
- 4 in `Phase 47 Plan 02: FEW_SHOT includes May-22 multi-parent seeding_session example` -- assert tu_fewshot_4 exists, its input.drafts[0].draft validates as SeedingSession via `Submission.safeParse`, every tool_use in FEW_SHOT (except the final) has a matching tool_result in the next user turn, and tu_fewshot_3 remains the LAST tool_use.

## Deviations from Plan

None on behavior. Two implementation notes:

1. **Audio transcript text is multi-line synthesized prose, not a literal copy of the real `01KS8KHYTRJDZQEM5C4P989B8B` transcript.** The plan said "synthesized audio transcript snippet"; I wrote a faithful summary that names 5 parents and quantities consistent with the canonical 11-block / 5-group shape. The real May-22 transcript will only enter the test surface in Plan 05 (integration replay), where the prompt's job is to teach the SHAPE, not to memorize the exact transcript bytes.
2. **per_field_confidence in tu_fewshot_4 uses dotted-path keys** (`'groups[0].parent'`, `'groups[3].parent'`, `'groups[4].child_block_names'`, plus top-level `event_date`) rather than the flat-field shape used by the legacy SeedingLog few-shots. Submission's `per_field_confidence` is `z.record(z.string(), z.number())` so this validates; the dotted-path convention also matches `ConflictEntry.path` so downstream tooling has one path grammar.

## Token-cost-related observations

The few-shot now has 4 pairs instead of 3, and the new pair is by far the largest assistant turn (the seeding_session JSON is ~2KB minified). Cache hit on the few-shot is unchanged (still ephemeral, still applied to the last block of the last user turn by `cacheableFewShot()`). Phase 47 Plan 05 should log the input_tokens delta against the Plan 01 baseline (872 tests) to confirm the increase is bounded and amortized by cache.

## Known Stubs

None. The few-shot is functional and validated by Submission.safeParse.

## Self-Check: PASSED

- [x] `src/agents/alerter/src/extraction/prompts/system.js` modified (SYSTEM_PROMPT + FEW_SHOT)
- [x] `src/agents/alerter/test/extraction/extractor.test.js` modified (12 new tests)
- [x] All 6 plan-required tokens present in SYSTEM_PROMPT
- [x] tu_fewshot_4 referenced exactly 2x in system.js (tool_use definition + matching tool_result)
- [x] tu_fewshot_3 remains LAST tool_use in FEW_SHOT (live-handshake boundary preserved)
- [x] 26 extractor.test.js tests green; 903 full-suite tests green
