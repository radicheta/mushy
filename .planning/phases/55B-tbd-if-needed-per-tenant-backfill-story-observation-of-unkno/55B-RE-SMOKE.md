# Phase 55B Re-Smoke Result

Two runs on 2026-06-14. Run 1 FAILED (gate not wired); Run 2 PASSES the hard gate
after the gate-input wiring fix. Details below.

## Run 2 (gate wired) -- run_id re-smoke-55b-1781472136 -- HARD GATE: PASS

- date: 2026-06-14
- img3776_poy_held: **yes** (HARD GATE PASS)
- pages_completed: 5 (IMG_3775, 3776, 3777, 3778, 3779)
- held: 31 drafts / committed: 33 / cost 0.2274 USD
- harness_errors: none

### Hard gate confirmed in the throwaway :5433 DB

```
status        confirmed=33  needs_review=31
held reasons: fidelity_cross_check_unverified=16  fidelity_cross_check_no_csv=15
held by extracted strain:
  unverified: KOY x4   <-- IMG_3776 POY-misread-as-KOY, HELD not committed (THE regression guard)
              CAR x4   <-- IMG_3778 CAZ-misread-as-CAR, HELD
              LIM x5, PIN x3  <-- IMG_3775 LIMA/POY misreads, HELD
  no_csv:     SHI x8, CAS x4, POY x2, ? x1  <-- IMG_3777/3779 (no CSV date), hold-all
```

The 2026-06-07 POY-committed-as-KOY silent misattribution is now CAUGHT and HELD. The
fidelity gate fires. Phase 55B's core purpose works end to end.

### Caveat: duplicate_asset_count=22 in the receipt is a FALSE POSITIVE

The receipt reports assets_created=270, logs_created=482, duplicate_asset_count=22 (its own
"FAIL" line). This is NOT real farmOS duplication -- it is a receipt attribution artifact of
session aggregation. backfill-notebook.js:691-711 attributes the WHOLE session's
asset_ids/log_ids to EACH of its N constituent drafts. So a session that created ~13 assets
ONCE is recorded as 13 assets x 12 member drafts = 156, and the duplicate detector (which
flags "same UUID under >1 block_name") trips on every session-attributed UUID. The actual
assets created are unique and correct; only the per-draft accounting double-counts.

This is a receipt-reporting bug, separate from the gate. Recommended fix: attribute the
session result to ONE representative entry (or dedupe session-attributed UUIDs before the
duplicate check) so duplicate_asset_count / asset totals are meaningful for the full run.

### Page-set note

Harness selected contiguous IMG_3775-3779 (runbook had mis-specified a non-contiguous set
incl. IMG_3782). The hard-gate page (3776), hold-all page (3777), and mode-1 pages
(3775/3778) are all present, so the gate was exercised on the right pages. IMG_3779
substitutes for 3782 (both no-CSV hold-all).

## Run 1 (gate NOT wired) -- run_id re-smoke-55b-1781470439 -- FAIL (kept for history)

All 64 drafts auto-confirmed; ZERO held; POY committed as KOY on IMG_3776 (the exact
2026-06-07 regression). Root cause: main() called processDraftsForCapture without
csvRowsForPage/csvBudget/pageDate, so the gate guard (csvRowsForPage !== undefined) was
false and the whole gate block was skipped. Fixed by wiring those inputs at the
backfill-notebook.js:1050 call site (commit follows). See memory
feedback_unit_tests_dont_catch_wiring -- the gate's unit tests passed because they call
processDraftsForCapture WITH the inputs; the real driver never supplied them.

## Isolation

Both runs used the throwaway postgres on :5433. The prod watchdog polls the shared
timescale on :5432 and never saw these drafts. The prod alerter was never stopped (Option A),
so prod RH alerting ran uninterrupted. Throwaway DB torn down in aftercare. Dev farmOS
:18080 holds the re-smoke assets (rebuild-acceptable per runbook STEP 8).

## Outstanding (not blocking the hard-gate PASS)

1. Receipt false-positive duplicate_asset_count (session attribution) -- fix before the
   full-corpus run so the receipt's PASS criteria are meaningful.
2. Strain gate (Phase 54.1) is also unwired in this driver (curatedStrains not passed;
   config.strains is empty). Not the 55B hard gate, but the same call-site gap -- needs a
   curated-strain source decision before it protects commits.
3. D-03 page-image attach: the A1 mechanism is proven (55B-A1-SMOKE.md PASS), but this
   re-smoke routes via the per-page seeding_session; confirm images land on the session
   group assets in dev farmOS (F2 reconcile, runbook STEP 7) before declaring SESSION-03 live.
