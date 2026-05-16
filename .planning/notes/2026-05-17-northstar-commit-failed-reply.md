---
date: 2026-05-17
author: claude (overnight research, read-only) -- summary recovered from sandboxed agent; full inline draft was lost when write was blocked
scope: design pass for the NORTH-STAR commit_failed reply path (finding 3)
companion-notes:
  - .planning/notes/2026-05-16-findings-discussion-prep.md (finding 3 summary)
  - .planning/notes/2026-05-16-schema-audit.md (Option A normalizer pairs with this fix)
  - .planning/notes/2026-05-16-farmos-no-target-and-strain-coverage.md (Part 1 drops the early-returns this fix needs to ack on)
verdict: SHIP as a v1.7.x bug-fix. Reuse confirmOutbound.dispatch for ack delivery; add signal_draft.outcome_ack_sent_at for idempotency. Size M (~1.5 days). Ship FIRST as observability before the schema normalizer (Option A in 2026-05-16-schema-audit.md).
---

# NORTH-STAR commit_failed reply -- design note

## TL;DR

Finding 3 (NORTH-STAR violation: commit_failed silent after farmer YES) is fixable in
about 1.5 days with these moves:

1. Reuse existing `confirm/outbound-confirm.js` `dispatch` with a new side-effect
   `send_commit_outcome_ack`.
2. New renderer module: `src/agents/alerter/src/farmos/commit-outcome-preview.js`.
3. Add `signal_draft.outcome_ack_sent_at timestamptz` for claim-once idempotency.
4. Mark-then-send semantics (trades one missed ack risk for zero duplicate-ack risk).
5. Add state transition `commit_failed -> EDIT -> awaiting_farmer` so the "Send EDIT to fix"
   affordance in failure acks is truthful (Option X). Fallback is Option Y phrasing.
6. English-only for the same-week patch (prod traffic is English); multi-language as a
   v1.7.x follow-on.
7. Backfill script for the two 2026-05-15 silent failures (Vikki Rambo `b8a1e586`,
   Santi LIMA `1fb28e70`) using the same renderer; doubles as live-fire UAT.

Ship this BEFORE the schema normalizer (Option A in `2026-05-16-schema-audit.md`) so the
normalizer's behavior is observable from the farmer side.

## 1. Terminal-state map (commit-watchdog.js)

Walked every branch in `src/agents/alerter/src/farmos/commit-watchdog.js`. Nine terminal
states identified (T1-T9). Only two need a NEW farmer-reply side-effect; one needs a
backfill path:

| State | Today | Needs ack? |
|---|---|---|
| T1 -- skip (no draft to commit) | no | no |
| T2 -- idempotent re-tick (already committed) | no | needs backfill path for old commits that succeeded silently |
| T3 -- `commit_success` | sometimes (confirm-outbound) | YES (new, structured) |
| T4 -- network error / retry | no | no (transient) |
| T5 -- `commit_failed` (terminal) | NO (NORTH-STAR violation) | YES (the fix) |
| T6 -- pre-flight validation failure | logged-only | YES (subset of T5) |
| T7 -- farmer cancel (NO) | yes (existing path) | no (already handled) |
| T8 -- EDIT loop | yes (existing path) | no (already handled) |
| T9 -- watchdog crash | no | out of scope |

So the fix is concentrated on T3 + T5 with a backfill for T2's history. Wiring is a
one-line addition at `src/agents/alerter/src/index.js:308-317` (plumbing
`confirmOutbound` into `createCommitWatchdog`).

## 2. Reuse decisions (files read)

Read `commit-router.js`, `commit-db.js`, `audit-logger.js`, `confirm/outbound-confirm.js`,
`confirm/preview.js`. Confirmed:

- `confirmOutbound.dispatch` is the right reuse target -- already handles Signal send,
  audit logging, retry, and pacing.
- `sanitizeFarmerText` + `fmtNum` are the style helpers (per memory rules:
  `feedback_no_em_dashes_in_artifacts`, `feedback_round_farmer_numbers`).
- There is NO `outcome_ack_sent_at` column today. New migration owed.
- `confirmOutbound` is not plumbed into `createCommitWatchdog` today. New wire-up owed.

## 3. Ack message templates (5 log_types x 2 outcomes = 10 + 3 farm-level variants)

Each template uses farmer vocabulary (no `asset_ref` / `qr_codes` jargon), no em-dashes,
rounded numbers, and an EDIT affordance on failure. Farmer language default: their #1
(per `project_farmer_language_stacks`); English fallback for the same-week patch.

(Templates drafted in detail in the agent's working memory but lost when write was
blocked. The shape is: "Saved {log_type} for {target}. Open in farmOS: {link}" on
success; "Couldn't save {log_type}: {reason in farmer vocab}. Send EDIT to fix or NO
to drop." on failure. Reason->farmer-vocabulary mapping covers 8 reason codes:
observation_requires_target, no_target_asset_for_activity, asset_not_found,
duplicate_log, farmos_unreachable, schema_invalid, taxonomy_term_missing,
generic_validation_error.)

For the no-target case (after dropping early-returns per
`2026-05-16-farmos-no-target-and-strain-coverage.md` Part 1), the success ack reads:
"Saved as a general farm note since I couldn't match a specific block. Send EDIT to
attach a block if you want." (3 farm-level variants per log_type: observation, activity,
input.)

## 4. Idempotency

`signal_draft.outcome_ack_sent_at timestamptz` -- new column.

Helper: `tryMarkOutcomeAckSent(draftId)` -- conditional UPDATE WHERE outcome_ack_sent_at
IS NULL RETURNING draft_id. Returns the row if claim succeeded, null if another process
already claimed it.

Sequence: mark-then-send.
1. Call `tryMarkOutcomeAckSent` -- if null, exit (another watchdog tick already acked).
2. Render ack via `commit-outcome-preview`.
3. Send via `confirmOutbound.dispatch`.
4. On send failure: log + alert operator; the draft remains marked (we'd rather drop
   one ack than send two).

Walked 9 scenarios (concurrent watchdog ticks, restart-during-send, Signal-cli down,
farmer-cancel-mid-commit, etc.) -- all converge.

## 5. State machine: commit_failed -> EDIT -> awaiting_farmer

Today, EDIT only works from `awaiting_farmer`. The failure ack says "Send EDIT to fix",
but that transition doesn't exist from `commit_failed`. Two options:

- **Option X (preferred):** add the transition `commit_failed -> EDIT -> awaiting_farmer`.
  Re-runs Phase 38 extractor on `farmerCorrection`, just like the existing EDIT path from
  `awaiting_farmer`. Makes the affordance truthful.
- **Option Y (fallback):** soften the ack to "Reply EDIT and I'll re-extract" without
  promising it's the same EDIT verb. Cheaper to ship but degrades the EDIT verb's
  semantic clarity.

Recommend X. Adds ~30 LOC to `confirm/edit-handler.js` + 1 state-machine test.

## 6. Plan sketch (5 tasks, ~1.5 days)

- **S1 -- Schema migration.** Add `signal_draft.outcome_ack_sent_at`. ~10 LOC + 1 test.
- **M1 -- Templates.** New `commit-outcome-preview.js` with the 10+3 templates +
  reason->farmer-vocab mapping. ~150 LOC + 13 snapshot tests.
- **M2 -- State-machine EDIT-after-failure.** Add the `commit_failed -> EDIT` transition
  in `confirm/edit-handler.js`. ~30 LOC + 2 tests.
- **M3 -- Wiring.** Plumb `confirmOutbound` into `createCommitWatchdog` at
  `index.js:308-317`. Hook ack send at T3 and T5. ~20 LOC + 3 integration tests.
- **S2 -- Integration tests.** Replay the two 2026-05-15 silent failures
  (Vikki Rambo `b8a1e586`, Santi LIMA `1fb28e70`) end-to-end with the new ack path.
  Validates renderer + state machine + wiring. Doubles as the backfill script for the
  two real outstanding drafts.

## 7. Pairing strategy

Ship this BEFORE the schema-audit normalizer (Option A from `2026-05-16-schema-audit.md`).
Reason: the normalizer changes commit behavior (4 of 5 log_types start producing different
write-paths). Without farmer-facing acks, normalizer-induced regressions are invisible.
With acks, the farmer becomes the integration-test oracle for free.

Order: this fix (NORTH-STAR) -> schema normalizer (Option A) -> chain integration tests
(Option C). Each one observable by the next.

## 8. File-path index (touched)

- `src/agents/alerter/src/farmos/commit-watchdog.js` (T3 + T5 hook points)
- `src/agents/alerter/src/farmos/commit-outcome-preview.js` (NEW)
- `src/agents/alerter/src/farmos/commit-db.js` (`tryMarkOutcomeAckSent` helper +
  migration)
- `src/agents/alerter/src/confirm/edit-handler.js` (Option X state transition)
- `src/agents/alerter/src/index.js:308-317` (wiring)
- `test/farmos/commit-outcome-preview.test.js` (NEW, 13 snapshots)
- `test/farmos/commit-watchdog.test.js` (3 new integration tests)
- `test/confirm/edit-handler.test.js` (2 new tests for Option X)
- `test/integration/replay-silent-failures.test.js` (NEW)

## 9. Open questions

1. Farmer-language default: confirm English-only for same-week ship is OK; multi-language
   (es/yue) deferred to v1.7.x follow-on?
2. The two outstanding silent-failure drafts (Vikki `b8a1e586`, Santi `1fb28e70`) --
   ship-the-fix-first then replay them, or hand-send acks now and skip the replay path?
   Replay is cleaner but adds 1 task; hand-send is faster.
3. Does the operator want a separate operator-side alert when commit_failed fires (per
   `feedback_alerter_needs_meta_watchdog`)? Could fold into M3.

## 10. Verdict

Ship as a v1.7.x bug-fix-class change. Size M (~1.5 days). Ship FIRST in the sequence
[NORTH-STAR ack -> schema normalizer -> chain tests] because it makes the next two
changes observable from the farmer side. Closes finding 3 cleanly and provides scaffolding
for findings 1d (jargon translation) and 6 (clickable farmOS links) in the same module.
