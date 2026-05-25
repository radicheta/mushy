# Cycle 1 finding: batch-mode in_flight_conflict drops all but the first draft per page

**Filed:** 2026-05-25 (Phase 54 Cycle 1 real-run, run_id `2026-05-25T22-35-41-238Z`)
**Severity:** BLOCKER for the 2025-notebook backfill; also a latent prod bug for clean multi-entry paper-log photos.
**Status:** open — Cycle 1 NOT signed off.

## Symptom

Cycle 1 ran 5 pages (IMG_3775-3779) through real extraction on dev farmOS :18080.
Every page logged `[extraction] batch: insertDraft idx=N failed: in_flight_conflict`
for all entries after the first. Each page persisted exactly **1 draft** instead of
the 24/17/?/8/? entries the extractor actually produced (output tokens
5094/3727/2760/1984/3044 confirm multi-draft extraction). Receipt CSV diff:
`0 hit / 24 miss`, `0 hit / 17 miss`, `0 hit / 8 miss`. One page (IMG_3778) also
hit `fungi_type_not_found` on commit (secondary; see below).

## Root cause

- `extraction-db.js:50-53` — partial unique index
  `ON signal_draft (sender_e164) WHERE status IN ('pending','awaiting_farmer')`
  enforces at-most-one in-flight draft per sender (D-02c; designed for the
  one-conversation-per-farmer live path).
- `pipeline.js` `runBatchMode` inserts each draft as `status='pending'`, then
  transitions it via the state machine (maxAskbackTurns=0).
- `state-machine.js:137-145` — a CLEAN draft transitions to `AWAITING_FARMER`
  regardless of maxAskbackTurns. `awaiting_farmer` is still in the in-flight set.
- So draft idx=0 (clean) lands in `awaiting_farmer`, holds the unique-index slot,
  and every subsequent `pending` insert in the same page raises 23505 ->
  `in_flight_conflict`. Only idx=0 survives.

Batch mode only "works" when the first draft is low-confidence (-> `needs_review`,
which is NOT in the in-flight set, freeing the slot). Clean-first multi-draft
pages silently lose every sibling.

## Why hermetic tests missed it

Batch-mode unit tests inject the DB and don't exercise the real partial-unique
index against a sequence of clean drafts. Classic producer->consumer wiring seam
(see [[feedback_unit_tests_dont_catch_wiring]]). The live-fire run is what caught it.

## Fix options (decide before re-running Cycle 1)

1. **Batch drafts -> needs_review, not awaiting_farmer.** Batch mode never asks the
   farmer back (one operator summary per page), so a clean batch draft has no
   business sitting in `awaiting_farmer` waiting for a YES. Make runBatchMode force
   `needs_review` (or a batch-terminal status) for clean drafts too. Frees the slot
   AND is semantically correct. Smallest principled change; touches prod batch path.
2. **Exclude batch drafts from the in-flight index** (e.g. add a `batch_id`/origin
   column and `WHERE ... AND batch_id IS NULL`). Bigger schema change.
3. **Bulk-backfill inserts drafts directly as `confirmed`**, bypassing the
   pending->awaiting dance entirely (pipeline needs a backfill flag). Scopes the
   fix to backfill only; leaves the latent prod bug for clean multi-entry photos.

Recommend option 1 (fixes prod + backfill), with a regression test that inserts
>1 clean draft for one sender in a single batch and asserts all persist.

## Secondary finding (IMG_3778)

The single surviving draft committed as `log_type=seeding` and failed with
`fungi_type_not_found` on 1 of 5 pages. Re-evaluate once option-1 fix lands and the
full entry set actually persists. Relates to the Phase 48 `fungi_type NOT NULL`
schema reality (see [[project_v111_backfill_harness_shape]] / 48-LIVE-FIRE notes).

## Cleanup done

The 5 confirmed backfill drafts were flipped to `discarded` before the alerter
restarted, so the prod-pointing commit-watchdog could not drain them to prod
(see [[project_backfill_confirmed_drafts_leak_to_prod_via_live_watchdog]]).
Dev farmOS :18080 received 4 single-entry seeding assets/logs from this run
(throwaway dev data).
