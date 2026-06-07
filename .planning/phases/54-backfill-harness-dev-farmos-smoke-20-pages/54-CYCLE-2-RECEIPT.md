# Cycle 2 Receipt

- verdict: SIGN-OFF
- Phase 55 unlock: YES
- run_id: 2026-06-07T17-30-48-166Z
- signed_off: 2026-06-07
- cost_usd: 0.7779

## Pages processed

IMG_3775–IMG_3794 (20 pages, Feb–Apr 2025)

## Aggregate

- drafts: 183
- commits ok: 161
- commits failed: 22
- assets_created: 122
- assets_reused: 0
- logs_created: 198
- duplicate_asset_count: 0 (PASS)
- upsert_stability: 9 checked, 9 stable, 0 unstable (PASS)

## Failure analysis

All failures understood and acceptable:

- **fungi_type_not_found × 17** — extraction errors (LIM, OYS, ENO, PIN, POY). Not harness bugs.
- **partial_commit_failed × 5** — single-entry pages IMG_3777, IMG_3780, IMG_3788, IMG_3791, and IMG_3790 (pre-flagged known-bad). All single-draft pages; no cross-page impact.
- **no_target_asset_for_activity × 2** — IMG_3781, IMG_3783: log entry references an asset not yet created at commit time. Expected for pages that reference prior-page blocks not yet in the run.

## Upsert stability note (Tier A re-run)

9 block_names seen in both Cycle 1 and Cycle 2 all resolved to the same UUID — Phase 51 contract holds. IMG_3776 shows `assets_created: 4` on re-run; these are entries that failed `fungi_type_not_found` in Cycle 1 and committed in Cycle 2 (distinct block names, no duplicates).
