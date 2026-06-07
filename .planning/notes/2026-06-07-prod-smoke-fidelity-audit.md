# 2026-06-07 -- Prod smoke fidelity audit (10-page set vs original notebook)

Santi authorized pushing a small 10-page set ALL THE WAY to PROD farmOS (:8082)
to audit the final artifact against the original notebook, then decide on the
full corpus from that audit. This is the audit.

## What was written to prod

- Run: `2026-06-07T23-39-18-403Z` (run dir on disk, gitignored).
- Mechanism: harness `--allow-prod-write --farmer=santi` (new BACK-11 opt-in),
  drafts isolated in throwaway pg :5433 (live watchdog never saw them), commits
  direct to prod :8082.
- Committed: 10 pages, 112 drafts, **99 assets + 98 logs**, 0 duplicates, $0.38.
- fungi_type_not_found: 15 (LIM 6, CAR 4, OYS 3, PIN 2). 1 partial_commit_failed,
  2 no_target_asset_for_activity.

## Fidelity vs ground truth (the 4 pages that have CSV ground truth)

| Page | hit | miss (notebook) | extra (extractor) | mode |
|------|-----|-----------------|-------------------|------|
| IMG_3775 (02-01) | 17 | LIMA x4, POY x3 | LIM x4, OYS x3 | misread -> failed (7 lost) |
| IMG_3776 (02-04) | 12 | POY x4, LIMA x1 | KOY x4, LIM x1 | POY committed AS KOY (silent) + 1 lost |
| IMG_3778 (02-20) | 4  | CAZ x4          | CAR x4            | misread -> failed (4 lost) |
| IMG_3782 (04-06) | 0  | SHI x4          | --                | under-capture (4 missed) |

Aggregate on checkable pages: **33 hit / 20 miss / 16 extra -> ~38% of notebook
entries not faithfully captured.** 5 of 10 pages (3777, 3779, 3780, 3781, 3783,
3784) had NO CSV ground truth to check against.

## Three failure modes (root causes)

1. **Lost to misread-failure** -- extractor writes a non-canonical variant
   (LIMA->LIM, CAZ->CAR, POY->OYS); commit fails fungi_type_not_found
   (createMissingFungiType:false, so no pollution). Visible in receipt. Data not
   committed.
2. **Silent misattribution** -- extractor writes a DIFFERENT VALID code
   (POY->KOY on IMG_3776); commit succeeds as the WRONG strain, NO error flag.
   This is the dangerous one: wrong data in prod that looks valid.
3. **Under-capture** -- page content largely missed (IMG_3782: 4 SHI -> 0
   captured).

## Why provisioning + the strain-gate fix do NOT solve this

- Provisioning real terms (done, dev+prod 24) fixes the missing-term half only.
- The dead strain-gate (CR-01/CR-02) would hold non-canonical variants (LIM,
  CAR, OYS) for confirm -- helps mode 1, NOT mode 2. It CANNOT catch
  POY->KOY because KOY is a valid curated code; exact-match passes it straight
  through. Silent misattribution is an EXTRACTION-QUALITY problem.

## The lever that WOULD catch it

The receipt already computes a per-page CSV diff (hit/miss/extra) against the
santi-attested ground-truth CSV. That same diff could be a COMMIT-TIME
cross-check: when a page has ground truth, only commit strains that match (or
flag/hold mismatches). This catches modes 1, 2, and 3 on the ~half of pages
that have ground truth. Pages without ground truth remain unverifiable.

## Decision input

- The full corpus run is NOT ready: ~38% infidelity on checkable pages, with
  silent misattribution actively writing wrong strains.
- 99 assets + 98 logs are now in PROD from this audit set, some misattributed
  (POY-as-KOY) and the set is incomplete. Bot cannot delete -> cleanup needs a
  farmOS admin, or leave as test data and reconcile via the eventual clean run
  (Phase 51 upsert is content-addressable by block_name, so a corrected re-run
  converges names but will NOT fix a wrong fungi_type on an already-committed
  asset -- those need manual correction).

## Recommended next step (for discussion)

Before any full run: add a ground-truth commit-time cross-check (and/or harden
the extraction prompt for the strain column), re-smoke, re-audit. Treat the
strain-gate wiring (CR-01/CR-02) as secondary -- it only addresses mode 1.
