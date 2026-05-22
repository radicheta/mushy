---
phase: 44
slug: event-gate-durable-signal-outbound-tenant-aware
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-21
---

# Phase 44 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | node:test (alerter subsystem) |
| **Config file** | src/agents/alerter/package.json `scripts.test` |
| **Quick run command** | `npm --prefix src/agents/alerter test -- <pattern>` |
| **Full suite command** | `npm --prefix src/agents/alerter test` |
| **Estimated runtime** | ~30s (unit), ~90s including integration |

---

## Sampling Rate

- **After every task commit:** Run quick test matching modified file
- **After every plan wave:** Run full alerter suite
- **Before `/gsd:verify-work`:** Full suite must be green + Plan-01 100-capture smoke green
- **Max feedback latency:** 30s

---

## Per-Task Verification Map

*Filled out by planner; one row per task in the plan files. Status starts ⬜ pending and is updated by the executor.*

---

## Wave 0 Requirements

- [ ] `src/agents/alerter/test/event-gate/` — directory + per-module test stubs (rules, haiku-classifier, integration)
- [ ] `src/agents/alerter/test/outbound-db.test.js` — DDL idempotency + insertOutbound contract
- [ ] `src/agents/alerter/test/llm-client.outbound-merge.test.js` — fmtHistory merge ordering
- [ ] `yaml` dependency added to `src/agents/alerter/package.json` (per RESEARCH.md, marked `[ASSUMED]`)
- [ ] `tenants/` directory + `.gitignore` rule for `tenants/*/secrets.env` (BEFORE any tenant file is committed — pitfall 7)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 100-capture hand classification (Plan-01) | GATE-01, GATE-02 | Operator/Don Santiago judgment per `[[feedback_real_data_before_ship_gate_pass]]` | Pull live Timescale `signal_capture` rows, stratify per CONTEXT.md D-20 distribution, hand-label `expected_gate_action` per row, save as `44-hand-classified-100.jsonl` |
| Live-fire Haiku 4.5 smoke (Plan-04) | GATE-01, GATE-02 | Live API spend; `EVAL_RUN_LIVE=1` gated | Run integration test over the 100 hand-labeled rows with `EVAL_RUN_LIVE=1`; assert ship-gate metrics from D-22 |
| `pgcrypto` extension enabled on elder-plops Timescale | OUTBOUND-01 | Requires DB superuser access (RESEARCH.md open question A2) | `psql -c "CREATE EXTENSION IF NOT EXISTS pgcrypto;"` against the prod DB or confirm migration includes it |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
