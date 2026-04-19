---
phase: 21
slug: camera-history-continuous-persistence
status: planned
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-19
updated_by_planner: 2026-04-19
---

# Phase 21 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | jest 29.x (bridge — introduced in Plan 01 / Wave 0) |
| **Config file** | src/mission-control/bridge/jest.config.js |
| **Quick run command** | `cd src/mission-control/bridge && npx jest <testPathPattern>` |
| **Full suite command** | `cd src/mission-control/bridge && npx jest` |
| **Estimated runtime** | ~3 seconds (pure-function suites) |

Smoke verification (live stack, per CLAUDE.md — repo root compose):
- `docker compose up -d --build bridge` from repo root
- `curl -s http://localhost:8081/health | jq '.snapshots'`
- `curl -s 'http://localhost:8081/camera/history?from=...&to=...' | jq '.count, .has_more'`
- `bash scripts/verify/phase-21-smoke.sh` (delivered in Plan 01 Task 2)

Bridge port is **8081** (not 3000 — this line corrects the initial draft).

---

## Sampling Rate

- **After every task commit:** Run `npx jest <file>` for the touched test file; or curl for endpoint tasks.
- **After every plan wave:** Run full `npx jest` + `/health` smoke against live stack.
- **Before `/gsd-verify-work`:** Full suite green + live bridge rebuild with `snapshots_last_24h > 0`.
- **Max feedback latency:** 20 seconds.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 21-01-T1 | 01 | 0 | Wave 0 | T-21-01 | jest pinned in package-lock | smoke | `cd src/mission-control/bridge && npx jest --passWithNoTests` | ❌→✅ (Plan 01 creates) | ⬜ pending |
| 21-01-T2 | 01 | 0 | Wave 0 | T-21-02 | script uses `set -u`, v2 compose | smoke | `bash -n scripts/verify/phase-21-smoke.sh` | ❌→✅ (Plan 01 creates) | ⬜ pending |
| 21-02-T1 | 02 | 1 | D-01, D-02, D-03, D-05 | T-21-03, T-21-04, T-21-05, T-21-07 | parameterized INSERT, stall-gated write, idempotent DDL | integration | grep invariants + `node --check` + live `/health` subscribed=true + 6-min row growth | ❌→✅ (Plan 02 creates) | ⬜ pending |
| 21-02-T2 | 02 | 1 | D-02, D-05, Stall-safety | T-21-04 | decideSource + shouldSkipSnapshot unit-tested | unit | `cd src/mission-control/bridge && npx jest test/snapshot.test.js` | ❌→✅ (Plan 02 creates) | ⬜ pending |
| 21-03-T1 | 03 | 2 | D-04 | T-21-12, T-21-13, T-21-14 | unlink→DELETE, ENOENT-as-success, 30d grace, clamp>=30 | unit | `cd src/mission-control/bridge && npx jest test/retention.test.js` | ❌→✅ (Plan 03 creates) | ⬜ pending |
| 21-03-T2 | 03 | 2 | D-06a | T-21-08, T-21-09, T-21-10, T-21-11 | parameterized SELECT, allowlist camera_id, 30d range cap, 5000 row cap + has_more | unit + integration | `cd src/mission-control/bridge && npx jest test/history.test.js` + live curl shape check | ❌→✅ (Plan 03 creates) | ⬜ pending |
| 21-04-T1 | 04 | 3 | D-06b | T-21-15, T-21-16 | /health stays 200 on sub-query failure | integration | curl /health with DB up and DB down — both return 200 | ✅ (file exists, handler extended) | ⬜ pending |
| 21-04-T2 | 04 | 3 | D-06b | T-21-17 | green >=200, red at 0, grey fall-through | smoke | grep + `node --check` plugin.js | ✅ (file exists, chip added) | ⬜ pending |
| 21-04-T3 | 04 | 3 | D-06b.UI | — | chip visible in Mission Control | manual | browser UAT | N/A | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements (delivered by Plan 01)

- [x] `src/mission-control/bridge/package.json` — add `jest` devDependency + `test` script (Plan 01 Task 1)
- [x] `src/mission-control/bridge/jest.config.js` — minimal node env config (Plan 01 Task 1)
- [x] `src/mission-control/bridge/test/` directory scaffold (Plan 01 Task 1)
- [x] `scripts/verify/phase-21-smoke.sh` — live-stack smoke via compose v2 + port 8081 (Plan 01 Task 2)

`wave_0_complete` flips to `true` once Plan 01 tasks both land on main.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Farmer sees `Snapshots` chip in Mission Control health panel | D-06b | UI rendering requires browser | Plan 04 Task 3 checkpoint |
| 365-day retention prune runs without nuking a fresh install | D-04 | Requires >30 days runtime or clock manipulation | Plan 03 Task 1 unit tests cover the grace logic; real-clock observation deferred to 30-day mark |
| Continuous timeline (no blank hours overnight) | D-01 / D-02 | Requires >1 overnight observation | After 24h live, confirm `SELECT count(*) FROM snapshots WHERE captured_at > now() - interval '24 hours'` ≥ 270 (cadence × 24h ≈ 288) |

---

## Decision Coverage Matrix

| Decision | Plan | Task(s) | Coverage |
|----------|------|---------|----------|
| D-01 (persister architecture — bridge-as-persister, keepalive) | 02 | T1 | Full |
| D-02 (idle cadence 1/5 min) | 02 | T1, T2 | Full |
| D-03 (snapshots hypertable schema) | 02 | T1 | Full |
| D-04 (365-day retention + 30-day grace) | 03 | T1 | Full |
| D-05 (viewer cadence decoupled, same 5 min, source tag) | 02 | T1, T2 | Full |
| D-06a (GET /camera/history) | 03 | T2 | Full |
| D-06b (/health + Phase 16 chip) | 04 | T1, T2, T3 | Full |

Every D-0x appears in at least one plan's `requirements` field.

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (jest install, config, test dir, smoke script)
- [ ] No watch-mode flags
- [ ] Feedback latency < 20s
- [ ] `nyquist_compliant: true` set in frontmatter (to be flipped by plan-checker or execution)

**Approval:** pending
