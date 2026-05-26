---
phase: 55
slug: full-corpus-run-receipt
status: draft
nyquist_compliant: true
wave_0_complete: true
created: 2026-05-25
---

# Phase 55 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | jest 29.x |
| **Config file** | `src/agents/alerter/jest.config.js` |
| **Quick run command** | `cd src/agents/alerter && npx jest --testPathPattern='backfill-notebook|build-backfill-receipt'` |
| **Full suite command** | `cd src/agents/alerter && npx jest` |
| **Estimated runtime** | ~10 seconds (targeted) / ~10s full suite |

Wave 0: existing test files (`scripts/backfill-notebook.test.js`, `scripts/build-backfill-receipt.test.js`) already cover the harness; new tests append to them. No new framework or fixtures required.

---

## Sampling Rate

- **After every task commit:** Run the quick run command (targeted backfill suites)
- **After every plan wave:** Run the full suite command
- **Before `/gsd:verify-work`:** Full suite must be green (baseline 1342 pass / 0 fail)
- **Max feedback latency:** ~10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 55-01-01 | 01 | 1 | BACK-09 | T-55-04 / transfer | `--all-pages` sets limit=Infinity; prod-guard + santi-gate still enforced | unit | `npx jest --testPathPattern=backfill-notebook -t "all-pages"` | ✅ | ⬜ pending |
| 55-01-02 | 01 | 1 | BACK-09, BACK-10 | — | `buildUuidJsonl` one line per UUID; `computePerShapeStats` emits literal `bulk_backfill_auto_yes` tag | unit | `npx jest --testPathPattern=build-backfill-receipt -t "buildUuidJsonl\|computePerShapeStats\|per-shape"` | ✅ | ⬜ pending |
| 55-01-03 | 01 | 1 | BACK-09 | — | `buildReceipt` copies receipt + JSONL to `.planning/notes/` (git-tracked), not gitignored run dir | unit | `npx jest --testPathPattern=build-backfill-receipt -t "notesReceiptPath\|notesJsonlPath\|BACK-10" && npx jest --testPathPattern=backfill-notebook` | ✅ | ⬜ pending |
| 55-02-01 | 02 | 1 | BACK-11 | T-55-04 / mitigate | RUNBOOK HARD pre-flight enforces isolation (throwaway pg :5433 OR stop mushy-alerter-1); smoke-5 + Cycle-2 sign-off gates | doc | `grep`-based section/content + ASCII-only check on `55-FULL-CORPUS-RUNBOOK.md` | ✅ | ⬜ pending |
| 55-02-02 | 02 | 1 | BACK-11 | — | Promotion decision doc defaults to dev-only; prod opt-in per session-class | doc | `grep`-based section/content + ASCII-only check on `55-PROMOTION-DECISION.md` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Existing infrastructure covers all phase requirements. New tests append to `scripts/backfill-notebook.test.js` and `scripts/build-backfill-receipt.test.js`; no new framework, config, or shared fixtures needed.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| The live full-corpus paid-LLM run + receipt against dev farmOS | BACK-09, BACK-10 | Operator-triggered, paid-LLM, gated on Cycle-2 farmer sign-off; intentionally NOT an autonomous executor task | Follow `55-FULL-CORPUS-RUNBOOK.md` after Cycle-2 sign-off: run isolation pre-flight, smoke-5, then `--all-pages`; confirm receipt + UUID JSONL land in `.planning/notes/` |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (none — existing test files reused)
- [x] No watch-mode flags
- [x] Feedback latency < 55s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-05-25 (autonomous plan-phase; filled from 55-RESEARCH.md Phase Requirements -> Test Map per plan-checker blocker)
