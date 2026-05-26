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

## RESOLVED 2026-05-25 (primary)

Fix committed `82c129c`: runBatchMode routes clean batch drafts to needs_review
(reason `batch_mode_clean`) instead of awaiting_farmer. Regression test added that
models the real partial unique index. Validated via free replay of the cached
Cycle-1 responses (scripts/replay-backfill-responses.js + replay seam): all
**80 entries persist** (24/17/17/8/14) vs 5 before. Full suite 1248 pass / 0 fail.
Then replay-with-commit pushed them to dev farmOS (run 2026-05-25T23-32-41-774Z):
62 assets + 66 logs, duplicate_asset_count=0, upsert unstable=0.

## TWO follow-on findings surfaced by the full-entry receipt (still open)

**(A) Receipt CSV-diff reports 0 hit / all miss on every page** — a receipt-builder
wiring gap, NOT an extraction miss. The drafts DO carry the strain
(`draft_json.species='CAS'`, `block_name='250201_CAS_1'`), but
`build-backfill-receipt.js:strainSetFromCommits` reads `c.strain_codes` off each
commit entry, and the harness (`backfill-notebook.js processDraftsForCapture`) never
attaches it (the function's own comment says callers should). Fix: derive
`strain_codes` from `draft_json.species` (or block_name prefix) and attach to each
commit entry in processDraftsForCapture. Until then the receipt's extraction-accuracy
gate (>=80% CSV hit) is non-functional and Cycle 1 cannot be meaningfully signed off.

**(B) `fungi_type_not_found` on 15 of 80 commits** (IMG_3775:8, 3776:1, 3777:1,
3778:4). Some species codes from the 2025 corpus aren't registered as fungi_type
terms in dev farmOS. Relates to the Phase 48 `fungi_type NOT NULL` reality
(see [[project_v111_backfill_harness_shape]] / 48-LIVE-FIRE notes). Decide: pre-seed
the missing taxonomy terms in dev farmOS, or have the commit path mint them.

NOTE: the run 2026-05-25T23-32-41-774Z receipt shows `total_cost_usd: 0.2542 across
5 LLM calls` -- that is the ORIGINAL paid run's cached cost; the replay spent $0.

## Cleanup done

The 5 confirmed backfill drafts were flipped to `discarded` before the alerter
restarted, so the prod-pointing commit-watchdog could not drain them to prod
(see [[project_backfill_confirmed_drafts_leak_to_prod_via_live_watchdog]]).
Dev farmOS :18080 received 4 single-entry seeding assets/logs from this run
(throwaway dev data).
