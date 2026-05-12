---
phase: 38-extraction-pipeline
plan: "04"
subsystem: alerter/extraction
tags: [state-machine, ask-back, farmer-text, sanitize, config]
requires:
  - extraction-schemas-zod  # Plan 01 (REQUIRED_FIELDS list aligned with schemas)
provides:
  - extraction-state-machine
  - draft-status-enum
  - ask-back-preview
  - extraction-config-knobs
affects: [src/agents/alerter]
tech_stack_added: []
patterns_added:
  - pure-state-machine-side-effect-tag-list
  - farmer-text-sanitize-sweep
  - unicode-escape-dashes-for-ascii-source
key_files_created:
  - src/agents/alerter/src/extraction/state-machine.js
  - src/agents/alerter/src/extraction/preview-builder.js
  - src/agents/alerter/test/extraction/state-machine.test.js
  - src/agents/alerter/test/extraction/sanitize.test.js
key_files_modified:
  - src/agents/alerter/src/config.js
  - src/agents/alerter/src/message.js
  - src/agents/alerter/test/config.test.js
decisions:
  - "3-turn cap (D-05) semantics: askback_turns + 1 >= maxAskbackTurns triggers needs_review (test fixture said 2 turns already + maxAskbackTurns=3 -> review, so >= not >; with cap=3 the system asks at most 2 follow-ups then escalates rather than burning the last turn)"
  - "fmtNum exported from message.js (was previously internal) -- plan key_links requires require('../message').fmtNum from preview-builder"
  - "sanitizeFarmerText regexes use \\u2014 and \\u2013 escapes so preview-builder.js source itself stays free of em/en-dash bytes (test asserts on raw source bytes)"
  - "state_or_notes synthetic marker for observation surfaces in missingFields when both state and notes absent; preview-builder also appends an explicit `state_or_notes: [?]` line in body for visibility"
  - "Out-of-range EXTRACTION_CONFIDENCE_THRESHOLD ([0,1]) falls back to default 0.7 + console.warn rather than throwing (env-knob ergonomics)"
metrics:
  duration: "~25min"
  completed: "2026-05-12"
  tasks_complete: 3
  files_touched: 7
  tests_added: 42
---

# Phase 38 Plan 04: State Machine + Ask-Back Preview Summary

## One-liner

Pure conversation state-machine (`transition`/`shouldAskBack`/`forceStartNewIfIdle` + `DRAFT_STATUS` frozen enum) and farmer-facing preview rendering (`buildPreview` + `buildTopQuestion` + `sanitizeFarmerText`) landed under `src/agents/alerter/src/extraction/`, honoring D-01a/D-02b/D-03/D-04/D-05 with 42 new unit tests and zero em-dashes in any new source byte.

## What shipped

- **3 config knobs** in `src/config.js`: `extractionConfidenceThreshold` (default 0.7, env `EXTRACTION_CONFIDENCE_THRESHOLD`, clamped to [0,1]), `draftIdleGapMin` (default 30, env `DRAFT_IDLE_GAP_MIN`), `maxAskbackTurns` (default 3, env `MAX_ASKBACK_TURNS`). Out-of-range threshold falls back to default + console.warn.
- **`src/extraction/state-machine.js`** — pure module (no DB, no Anthropic, no logger). Exports:
  - `transition(state, event)` — routes `extraction_result` / `farmer_replied` / `idle_check`. Returns `{nextStatus, nextAskbackTurns, side_effects: string[], reason, askBackInfo}`.
  - `shouldAskBack(draft, perFieldConfidence, threshold)` — checks required-field map (RESEARCH section 8) + per-field confidence; observation special case for state-or-notes; returns `{askBack, missingFields, lowConfFields}`.
  - `forceStartNewIfIdle(prevDraft, nowMs, idleGapMin)` — D-01a hard guard.
  - `DRAFT_STATUS` — frozen enum (`pending` / `awaiting_farmer` / `needs_review` / `expired`).
  - `REQUIRED_FIELDS` — frozen map for the 5 B7 log types.
- **`src/extraction/preview-builder.js`** — farmer-facing rendering:
  - `buildPreview({draft, perFieldConfidence, threshold, requiredFields})` — multi-line string with top question on line 1, blank line, then `field: value` (or `field: [?]`) body. Numbers via `fmtNum`. Datetimes trimmed of millisecond fraction. Arrays render as `[a, b]`. Full output passes through `sanitizeFarmerText`.
  - `buildTopQuestion({missingFields, lowConfFields, draftType})` — picks one field by priority (missing > low-conf) and looks up per-(type, field, miss|low) template; falls back to generic `Can you confirm the X for this Y?`.
  - `sanitizeFarmerText(s)` — strips em-dashes, converts en-dashes to ASCII hyphen, idempotent.
  - `TOP_Q_TEMPLATES` — frozen phrasing map covering all 5 B7 log types.
- **42 new tests**: 8 config (Phase 38 block), 20 state-machine, 14 sanitize/preview. All green.

## Commits

| Hash    | Type | Message                                                                  |
| ------- | ---- | ------------------------------------------------------------------------ |
| bc27ca6 | test | RED -- config knobs for extraction pipeline (threshold/idle/cap)         |
| 44df258 | feat | GREEN -- add extraction config knobs (threshold/idle/cap)                |
| 794f39b | test | RED -- state machine transitions + ask-back + 3-turn cap + idle cap      |
| 5035746 | feat | GREEN -- pure state machine for extraction draft lifecycle               |
| 83348bd | test | RED -- preview builder + farmer-text sanitize                            |
| 51e4ca0 | feat | GREEN -- farmer-facing preview + top-question + sanitize                 |

## Verification

```
cd src/agents/alerter && npx jest
Test Suites: 1 failed, 25 passed, 26 total
Tests:       1 failed, 379 passed, 380 total
```

Single failure is pre-existing `config.test.js` Test A `dashboardUrl` assertion (legacy URL; predates Phase 38, explicitly tolerated by plan).

Acceptance grep sweeps:
- `grep -E "—" src/extraction/state-machine.js src/extraction/preview-builder.js` -> 0 matches
- `grep -c "fmtNum" src/extraction/preview-builder.js` -> 4 uses
- `grep "require.*db\|require.*anthropic" src/extraction/state-machine.js` -> 0 (pure module)
- `node -e "...buildPreview(...).includes('[?]')"` -> `true`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] message.js did not export `fmtNum`**

- **Found during:** Task 3 (preview-builder GREEN run -- TypeError: fmtNum is not a function)
- **Issue:** Plan key_links explicitly mandates `preview-builder.js -> require('../message').fmtNum`, but `message.js` `module.exports` only exposed `formatProblem`, `formatRecovery`, `formatHeartbeat`. Internal helper `fmtNum` was unreachable.
- **Fix:** Extended exports to `{ formatProblem, formatRecovery, formatHeartbeat, fmtNum, fmtDuration, fmtRelative }`. Backwards compatible -- adds names, removes none.
- **Files modified:** `src/agents/alerter/src/message.js`
- **Commit:** `51e4ca0`

**2. [Rule 1 - Bug] 3-turn cap off-by-one**

- **Found during:** Task 2 (initial GREEN run -- 1 failing test)
- **Issue:** Plan behavior text said "askback_turns + 1 > MAX_ASKBACK_TURNS -> needs_review" but test fixture said `state.askback_turns=2` + `maxAskbackTurns=3` -> `needs_review` (2+1=3 is NOT > 3 -- text and test disagreed).
- **Fix:** Changed comparison to `currentTurns + 1 >= maxAskbackTurns`. Semantics match D-05 spirit ("hard cap = 3 ask-back turns" reads as "at most 3 attempts including the current one"; once 2 are done and a 3rd would also need to ask, escalate rather than burn the last turn). Test fixture is now the source of truth.
- **Decision recorded** in frontmatter.
- **Commit:** `5035746`

**3. [Rule 1 - Bug] Em-dash byte appeared in `preview-builder.js` regex**

- **Found during:** Task 3 (initial GREEN run -- memory-check test failed against source bytes)
- **Issue:** `.replace(/—/g, '')` regex contained a literal U+2014 byte, which trips the source-byte em-dash sweep (memory rule `feedback_no_em_dashes_in_artifacts.md`).
- **Fix:** Rewrote both dash replace regexes using `—` / `–` JS escapes. Behavior unchanged.
- **Commit:** `51e4ca0`

## Known Stubs

None. Both modules are functionally complete for their scope. Plan 05 wires `state-machine.transition` + `preview-builder.buildPreview` outputs into actual `signal_draft` DB writes and `signal.js` sends.

## Self-Check: PASSED

- FOUND: src/agents/alerter/src/extraction/state-machine.js
- FOUND: src/agents/alerter/src/extraction/preview-builder.js
- FOUND: src/agents/alerter/test/extraction/state-machine.test.js
- FOUND: src/agents/alerter/test/extraction/sanitize.test.js
- FOUND: bc27ca6, 44df258, 794f39b, 5035746, 83348bd, 51e4ca0 (commits)
