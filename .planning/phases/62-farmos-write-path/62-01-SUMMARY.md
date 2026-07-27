---
phase: 62-farmos-write-path
plan: 01
subsystem: database
tags: [postgres, timescaledb, signal_draft, origin-guard, nodejs, migration]

requires:
  - phase: 61-confirm-loop
    provides: signal_draft commit-trigger marker contract
provides:
  - "origin column (NOT NULL DEFAULT 'node') + Phase 40 commit-lifecycle columns on signal_draft (Python migration)"
  - "Node commit-watchdog SELECT origin-guarded with AND origin != 'python'"
  - "Node initDb self-adds the origin column on boot (closes the redeploy ordering trap)"
  - "patched Node alerter deployed live to prod — SC1 structural guarantee active"
affects: [62-10 commit_db, 62-11 commit_watchdog, 62-12 live-fire, farmos-write-path]

tech-stack:
  added: []
  patterns:
    - "origin-guard coexistence: Python writes origin='python'; live Node watchdog excludes them (AND origin != 'python')"
    - "self-sufficient schema bootstrap: both Node initDb and Python migration add origin idempotently"

key-files:
  created:
    - .planning/phases/62-farmos-write-path/62-01-SUMMARY.md
  modified:
    - src/farm-agent/farm_agent/persistence/migrations.py
    - src/farm-agent/tests/test_persistence.py
    - src/agents/alerter/src/farmos/commit-db.js
    - src/agents/alerter/test/farmos/commit-db.test.js
    - src/agents/alerter/test/farmos/fake-pool.js

key-decisions:
  - "D-01: origin column + live Node-watchdog patch is the prod-leak prevention mechanism"
  - "D-02: hard sequencing — patched Node alerter redeployed to prod BEFORE any Python confirmed-write; enforced as a blocking checkpoint"
  - "D-03: legacy/Node rows default origin='node' and keep draining unchanged; no backfill"
  - "Deviation (orchestrator+operator): added origin to Node initDb to remove the ordering trap where the guarded SELECT references a column the Python migration could not add until after redeploy"

patterns-established:
  - "Structural guard over runbook step: the guarantee is enforced by schema+SELECT, not by operator discipline"

requirements-completed: [FWR-04]

duration: ~25min
completed: 2026-06-28
---

# Phase 62 Plan 01: Origin Guard Summary

**The shared-Timescale prod-leak is now structurally prevented: a Python process writing `status='confirmed'` with `origin='python'` can never be drained by the live Node commit-watchdog, with the patched alerter confirmed running in prod.**

## Performance

- **Duration:** ~25 min (incl. operator-equivalent prod redeploy)
- **Completed:** 2026-06-28
- **Tasks:** 3/3 (2 auto + 1 human-action checkpoint, performed on elder-plops)
- **Files modified:** 5

## Accomplishments

- **Task 1 (`418fada`):** Python migration `_run_draft_migrations` extended with `ADD COLUMN IF NOT EXISTS origin text NOT NULL DEFAULT 'node'`, the six Phase-40 commit-lifecycle columns, the `idx_signal_draft_status_confirmed` partial index, and documentation of the new application-validated `fidelity_cross_check_unverified` status (Phase 62 D-06). `test_persistence` green; idempotent.
- **Task 2 (`c844010`):** Node `findConfirmedCandidates` SELECT guarded with `AND origin != 'python'`; fake-pool + tests updated; 16/16 green.
- **Guard-hardening (`68c2262`):** Node `initDb` now adds the `origin` column on boot (DEFAULT 'node'). Closes an ordering trap — the guarded SELECT references `origin`, but the Python migration (the only other adder) cannot run until after the redeploy per D-02; without this, a clean-DB redeploy would throw in the SELECT, the never-throws wrapper would return `[]`, and prod commits would silently freeze. Test asserts 7 ALTERs + the origin statement.
- **Task 3 (checkpoint, done):** Patched Node alerter rebuilt + recreated in prod (`mushy-alerter-1` on elder-plops, image `aa3da7d7d913`). Verified: running container carries the `origin != 'python'` clause and the `origin` column-add; clean boot; `[commit-watchdog] started: interval=30000ms batchCap=10 retryMax=3 staleMin=5`.

## Verification

- SC1 satisfied: structural prevention (schema column + guarded SELECT), not a runbook step.
- Live prod container confirmed patched (grep of RUNNING container, not branch — guards against stale-branch drift).

## Notes for Downstream Plans

- The Python `commit_db` (Plan 10) MUST set `origin='python'` on every confirmed/committing write — this is what the live Node guard keys on.
- The `origin` column now exists in prod Timescale (added by the alerter's initDb on this redeploy).
