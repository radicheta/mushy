# 2026-06-07 -- Strain taxonomy provisioning (dev + prod farmOS)

Pre-provisioned the 2025-notebook dataset's strain codes as `fungi_type`
taxonomy terms in BOTH dev (:18080) and prod (:8082) farmOS so the Phase 55
full-corpus backfill commits cleanly. Done during Phase 55 execution after a
code review surfaced that the backfill strain-confirm gate is wired off.

## Why (the trigger)

Phase 55 code review (55-REVIEW.md) found two blockers in `backfill-notebook.js`:

- CR-01: `main()` calls `processDraftsForCapture` WITHOUT `curatedStrains`, so
  the Phase 54.1 strain-confirm gate (`if (curatedStrains && ...)`) is always
  falsy -- it never holds unknown strains.
- CR-02: `main()` drops the `heldUnknownCodes` return and never calls
  `sendUnknownStrainBatch`, so no batched farmer confirm + no
  `pending-strain-confirm.json` is written.

Net: the hold -> batched-confirm -> mint flow is dead end-to-end in the backfill
path. This is pre-existing (wiring gap from `99e3f98 feat(54-02)`; 54.1 added the
gate params to the function but never updated the call site). It also reframes
the Cycle-2 receipt's "0 held / 17 fungi_type_not_found": those were not all
extraction errors -- they were real strains farmOS simply lacked terms for.

## Decision (Santi, 2026-06-07)

Rather than fix the (dead) gate wiring, make our lives easy: ensure every strain
in the santi-attested notebook actually exists in farmOS. A code in the
ground-truth notebook IS real ([[feedback_farmer_is_reality_source_of_truth]]),
so provisioning the canonical terms up front is the right move. The confirm-gate
existed to guard against EXTRACTION variants/typos, not curated ground-truth
codes.

## What changed

Dataset (ground-truth CSV) has 23 distinct strain codes. Dev + prod each had the
curated 14. Gap = 11 codes. After review of notebook provenance, WEDGE was
SKIPPED (its rows are substrate experiments -- 100% ALFALFA / 50 ALF 50 SD /
SD + BOK CHOI -- not a strain). The other 10 were minted in BOTH instances.

Minted terms (name = code verbatim):

| Code | Notebook read           | dev :18080 UUID                        | prod :8082 UUID                        |
|------|-------------------------|----------------------------------------|----------------------------------------|
| CCM  | recurring (x36)         | e62915f3-ae5e-469c-be77-a2cba93e4f03   | c8eb0fba-e31a-4821-9147-da2f46a3963a   |
| ENO  | Enoki (x30)             | 86ffa7d2-3981-4582-9c81-f6a925acf400   | 3ace2960-808e-4ae5-a59e-a625e70244b0   |
| CA3  | CA-family, AGAR/LC (x24)| b44b39ac-f07b-4c6b-8574-d8372797fe02   | 9a55b3b7-c7c3-4193-b3d3-9c99dc9d1b5b   |
| POY  | oyster (x12)            | a5863795-be87-4630-8712-ae4010aa3724   | fff09873-4f28-4a50-9400-dc655cb92907   |
| CY   | LC 2024 (x4)            | ee179289-068d-43d6-bf8e-a43d1e91dfbc   | e2081e76-ab2e-4728-86ab-52a700a51fb7   |
| PB2  | CLONE (x3)              | 4b504851-eedd-4a28-844e-693e22fca1e6   | f098b79b-b11a-47d6-bfbe-5830676d2c99   |
| POR  | src 111-30 (x3)         | e65b8b70-1518-4112-98cf-76c7b03c497b   | eabf2bd5-f4d3-4f5b-9837-9b7463be4ba7   |
| REI  | Reishi (x2)             | aafbdc26-b2a9-477c-91c1-a0ad7bb0d421   | 6bbd7cfd-2724-4549-b4d1-f688cde3220a   |
| SH3  | SH-family (x2)          | 9e6eab40-ee75-4221-89be-6d5db90eecee   | 53ba694b-7135-4981-b485-a17824325fef   |
| PB3  | SPORES (GILLS) (x1)     | 72f5c313-2e9a-4aa6-8ab0-2170c118ba02   | 39629f9f-6f40-4b80-825c-73dcc8798878   |

SKIPPED: WEDGE (substrate experiments, not a strain).

## Result

- dev + prod fungi_type vocab: 14 -> 24 terms, IN SYNC.
- Coverage: all 22 dataset codes (23 minus WEDGE) now resolve in farmOS.
- `backfill-notebook.js:404` sets `createMissingFungiType: false`, so the
  backfill never auto-mints. With terms pre-provisioned, canonical strains
  commit cleanly and genuine extraction typos/variants fail cleanly as
  fungi_type_not_found with ZERO taxonomy pollution.

## Still open (not blocking the run)

- CR-01 / CR-02: the backfill strain-confirm gate wiring remains dead. Now MOOT
  for the full-corpus run (terms pre-exist; no-mint guard on), but should be
  fixed or formally retired so the dead code does not mislead later. Candidate
  follow-up; relates to [[project_strain_confirm_before_mint]] and
  [[project_v113_watchdog_origin_guard_candidate]].
- WR-01 (55-REVIEW.md): notes copy-out overwrites on same-date crash-and-retry.
  Minor Phase 55 hardening.
- WEDGE's 6 rows will remain fungi_type_not_found in the backfill (intentional).

## Next

Operator-triggered, per 55-FULL-CORPUS-RUNBOOK.md: dry-run -> paid smoke-N
(~0.20 USD) -> verify fungi_type_not_found dropped to ~0 -> full --all-pages run
(~2.85 USD). Triple-check the smoke receipt before the full dataset.
