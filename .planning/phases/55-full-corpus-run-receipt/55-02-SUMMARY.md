---
phase: 55-full-corpus-run-receipt
plan: "02"
subsystem: backfill-harness
tags: [backfill, runbook, prod-isolation, decision-doc, back-11]
dependency_graph:
  requires:
    - 54-backfill-harness-dev-farmos-smoke-20-pages (Cycle-2 SIGN-OFF gate)
    - 55-01-PLAN (harness extension with --all-pages flag)
  provides:
    - 55-FULL-CORPUS-RUNBOOK.md (operator runbook for full 73-page run)
    - 55-PROMOTION-DECISION.md (BACK-11 decision: dev-only default, per-session-class opt-in)
  affects:
    - Phase 55 GA2 (operator can now execute the full-corpus run)
tech_stack:
  added: []
  patterns:
    - GA1 operational isolation via throwaway postgres :5433 (Option A, DEFAULT)
    - Smoke-before-expensive-batch enforced in runbook (dry-run + 5 pages before --all-pages)
key_files:
  created:
    - .planning/phases/55-full-corpus-run-receipt/55-FULL-CORPUS-RUNBOOK.md
    - .planning/phases/55-full-corpus-run-receipt/55-PROMOTION-DECISION.md
  modified: []
decisions:
  - "Option A (throwaway postgres :5433) is DEFAULT isolation; Option B (stop alerter) is fallback with mandatory pre-restart cleanup"
  - "Cost estimates corrected to ~2.85 USD full / ~0.20 USD smoke-5, derived from Cycle-2 actual rate (20pp/0.78 USD)"
  - "BACK-11 defaults to dev-only; prod promotion is per-session-class opt-in with three explicit gates"
metrics:
  duration: "~25 minutes"
  completed: "2026-06-07"
  tasks_completed: 2
  files_created: 2
---

# Phase 55 Plan 02: Full-Corpus Runbook + Promotion Decision Summary

**One-liner:** Full-corpus operator runbook with GA1 isolation pre-flight (falsified Phase-54 assumption replaced) and BACK-11 dev-only prod-promotion decision with per-session-class opt-in gates.

## What Was Built

### 55-FULL-CORPUS-RUNBOOK.md (366 lines)

Operator runbook for the full 73-page corpus backfill. Key sections:

- **GA2 gate:** Grep check for Cycle-2 SIGN-OFF + Phase 55 unlock lines. Abort if absent.
- **HARD PRE-FLIGHT:** Replaces the falsified Phase-54 "DATABASE_URL is the dev DB" assumption. Documents that one shared TimescaleDB (:5432) exists and the prod-pointing mushy-alerter-1 watchdog polls it every 30s. Both isolation options as copy-pasteable verified-not-trusted checks.
  - Option A (DEFAULT): throwaway postgres :5433 via Docker; no leak risk; drop container after run.
  - Option B (FALLBACK): stop mushy-alerter-1; DEFERS not prevents the leak; mandatory pre-restart cleanup (UPDATE signal_draft SET status='discarded' WHERE needs_review_reason='bulk_backfill_santi'; verify zero rows remain BEFORE docker start).
- **Common pre-flight assertions:** dev farmOS :18080 reachable; FARMOS_URL contains no :8082/prod; ANTHROPIC_API_KEY set; Jest suite green.
- **Smoke-before-full:** dry-run (0 USD, confirms 73 pages), paid smoke-5 (~0.20 USD), then --all-pages (~2.85 USD). Cost estimates from Cycle-2 actual rate.
- **Crash recovery:** --resume-from + fresh --run-id (runIdExistsGuard exit 6 explained). Two partial run dirs accepted; manual receipt concat documented.
- **Skip list:** IMG_3790 / IMG_3810 / IMG_3820 documented as known-bad; they surface per-page failure reasons, do not crash the run.
- **Receipt verification:** duplicate_asset_count==0, upsert_stability.unstable==0, BACK-10 bulk_backfill_auto_yes tag present.

### 55-PROMOTION-DECISION.md (159 lines)

BACK-11 decision record:

- **Default:** dev-only. No autonomous prod write.
- **Rationale:** dev is the validation target; prod carries live data plus May-22 stubs; GA1 watchdog makes any prod-facing confirmed-draft flow hazardous without explicit isolation.
- **Session-class definition:** operator-defined curated subset (by log_type, date range, or strain code).
- **Per-session-class opt-in gates:** (1) clean dev receipt (duplicate_asset_count==0, upsert_stability stable, no unexplained failures); (2) committed operator decision note naming class + pages + dev receipt metrics; (3) Phase 51 upsert path mandatory (enriches May-22 stubs in-place, does not mint duplicates).
- **No authorization:** document records criteria only. A future prod run requires Gate 2 note + all three gates satisfied.
- **Deferred:** origin-guard, 4 bogus dev terms, v1.13 narrowing.

## Deviations from Plan

### Cost Correction Applied (Directive from prompt)

The plan's interface notes carried a stale estimate of "about 7 to 10 USD for full run, about 0.50 USD for smoke-5." These figures were replaced with corrected estimates derived from the Cycle-2 actual rate (20pp/0.78 USD recorded in 54-CYCLE-2-RECEIPT.md):
- Smoke-5: ~0.20 USD (was ~0.50 USD)
- Full 73 pages: ~2.85 USD (was ~7-10 USD)

Both documents include a one-line note citing the derivation source.

## Commits

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Full-corpus runbook with GA1 isolation pre-flight | 12f362a | 55-FULL-CORPUS-RUNBOOK.md (+366 lines) |
| 2 | BACK-11 prod-promotion decision doc | bc1b242 | 55-PROMOTION-DECISION.md (+159 lines) |

## Threat Surface Scan

No new network endpoints, auth paths, file access patterns, or schema changes introduced. Both files are static markdown docs -- no code shipped in this plan. T-55-04 (prod-leak) and T-55-05 (accidental prod promotion) are addressed by the operational runbook pre-flight and the BACK-11 decision record respectively, exactly as specified in the threat register.

## Self-Check: PASSED

- 55-FULL-CORPUS-RUNBOOK.md exists (366 lines >= 80 required): FOUND
- 55-PROMOTION-DECISION.md exists (159 lines >= 40 required): FOUND
- Both verify checks printed PASS (no em-dash/en-dash): VERIFIED
- Corrected cost figures (~2.85 USD full / ~0.20 USD smoke-5) used: VERIFIED
- Operator sentinel "Operator runs this. Do not delegate to an autonomous agent." present in runbook: VERIFIED
- Option A marked DEFAULT, Option B marked FALLBACK with mandatory pre-restart cleanup: VERIFIED
- BACK-11 defaults to dev-only with documented per-session-class opt-in: VERIFIED
- No modifications to STATE.md or ROADMAP.md: CONFIRMED
