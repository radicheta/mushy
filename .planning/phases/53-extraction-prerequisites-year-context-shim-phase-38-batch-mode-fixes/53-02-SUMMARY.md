---
phase: 53-extraction-prerequisites-year-context-shim-phase-38-batch-mode-fixes
plan: 02
subsystem: alerter-extraction
tags: [back-02, routing-heuristic, multi-draft, dt-tubs]
requires: [back-01]
provides: [multi_confirm-mode, small-n-fanout]
affects: [extraction-pipeline-routing]
tech_added: []
patterns: [confidence-min-leaf-walk, routing-policy-not-extractor]
key_files_modified:
  - src/agents/alerter/src/extraction/pipeline.js
  - src/agents/alerter/test/extraction/pipeline.test.js
  - src/agents/alerter/test/extraction/integration.test.js
decisions:
  - "Inline fan-out instead of full processSingleDraft helper extraction (lower regression risk; preserves legacy single-draft path verbatim)"
  - "Existing Plan-08 integration tests B1/B2 bumped from 3/5 drafts -> 6 drafts to stay on batch-mode path under the new >5 threshold"
metrics:
  duration_min: 12
  tasks_complete: 2
  completed: 2026-05-24
---

# Phase 53 Plan 02: BACK-02 routing heuristic for small-N multi-draft captures Summary

Fixed the Phase 38 routing seam: small high-confidence multi-draft captures
(e.g. DT tubs `01KSCW771VB2FDWBPWNS4MEHAZ` — 2 spawn-tub photos with
captions) now dispatch N independent `send_confirm_prompt`s to the farmer
instead of dumping into `needs_review` and pinging the operator channel.

Heuristic locked per D-BACK-02:
- `drafts.length > 5` OR `min(per-draft min-leaf confidence) < 0.7` → existing `runBatchMode` (operator summary)
- Else → new multi_confirm fan-out (N per-draft confirm flows)
- `seeding_session` in the mix → falls through to runBatchMode (safe default)

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1+2 | minLeafConfidence helper + routing heuristic + DT-tubs regression fixture | `9835caf` | pipeline.js, pipeline.test.js, integration.test.js |

(Tasks 1 and 2 from the plan combined into one commit per gsd execute-plan
convention — both task bodies landed atomically without intermediate state.)

## Verification

- `cd src/agents/alerter && npx jest test/extraction/pipeline.test.js` — 24/24 green
- `cd src/agents/alerter && npx jest test/extraction/integration.test.js` — 13/13 green
- `cd src/agents/alerter && npx jest` — full suite 1142 passed, 9 skipped, 0 failed
- DT-tubs fixture case dispatches 2× `send_confirm_prompt`, 0× `send_batch_review_summary`
- 6-draft case still dispatches 1× `send_batch_review_summary`
- 2-draft case with one confidence 0.5 still dispatches 1× `send_batch_review_summary`

## Deviations from Plan

**[Rule 3 - Adjustment] Updated existing B1/B2 integration tests to match new heuristic.**
- Found during: post-implementation full-suite run.
- Issue: Plan-08 integration tests B1 (3 clean drafts) and B2 (5 mixed drafts) asserted the
  old batch-mode behavior, but those exact inputs now route to multi_confirm under the new
  >5 OR <0.7 heuristic — which is the intended BACK-02 outcome.
- Fix: Bumped B1 from 3 → 6 clean drafts and B2 from 5 → 6 mixed drafts (with 2 dirty)
  so the batch-mode regression coverage is preserved under the new >5 threshold.
  Adjusted `cleanCount` expectation from 3 → 4 in B2 to match (4 clean + 2 dirty = 6).
- Files modified: `test/extraction/integration.test.js`
- Commit: `9835caf` (combined with the implementation commit since they are inseparable —
  the test updates ARE the BACK-02 deviation from old behavior)

**[Plan deviation - simplification] Did NOT extract a `processSingleDraft` helper from the
legacy single-draft path (lines 343-583).**
- The plan suggested factoring out the legacy single-draft body into a helper. Inlining
  the small-N fan-out logic instead (~80 lines, similar shape to `runBatchMode`) keeps
  the legacy path verbatim and avoids the regression risk of a large refactor across the
  continuity/seeding-session/state-machine paths. The fan-out only ever needs the
  start_new path (multi-draft inherently resets conversational state), so re-using the
  full legacy machinery would have been overkill.
- Tradeoff: ~30 lines of duplication between the new fan-out block and the legacy single
  path (PFC handling + dispatch loop). Acceptable given the alternative was touching
  the 240-line legacy body.

## Self-Check: PASSED

- `src/agents/alerter/src/extraction/pipeline.js` contains `minLeafConfidence`,
  `shouldBatchReview`, and the `mode: 'multi_confirm'` return branch
- New 5 BACK-02 tests in `pipeline.test.js` all pass (DT-tubs + low-conf + >5 +
  seeding_session-mix + inflight-expire)
- Commit `9835caf` present in `git log --oneline`
- DT-tubs capture id `01KSCW771VB2FDWBPWNS4MEHAZ` literally referenced in the new test
