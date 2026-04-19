---
phase: 21
slug: camera-history-continuous-persistence
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-19
---

# Phase 21 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | jest 29.x (bridge — to be introduced in Wave 0) |
| **Config file** | src/mission-control/bridge/jest.config.js (Wave 0 installs) |
| **Quick run command** | `cd src/mission-control/bridge && npx jest --testPathPattern=<file>` |
| **Full suite command** | `cd src/mission-control/bridge && npx jest` |
| **Estimated runtime** | ~15 seconds |

Smoke verification (live stack):
- `docker compose up -d --build bridge` from repo root
- `curl -s http://localhost:3000/health | jq '.snapshots_last_24h, .oldest_snapshot_at'`
- `curl -s 'http://localhost:3000/camera/history?from=...&to=...' | jq '.items | length'`

---

## Sampling Rate

- **After every task commit:** Run quick jest for the touched file (or smoke curl for endpoint tasks)
- **After every plan wave:** Run full `npx jest` + `/health` smoke
- **Before `/gsd-verify-work`:** Full suite green + live bridge rebuild with `snapshots_last_24h > 0`
- **Max feedback latency:** 20 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| TBD — filled by planner | — | — | D-0x from CONTEXT.md | — | — | unit/integration/smoke | `npx jest <file>` / curl | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

*Planner MUST fill this table with one row per task, binding each to a D-0x decision from CONTEXT.md (since phase_req_ids is null).*

---

## Wave 0 Requirements

- [ ] `src/mission-control/bridge/package.json` — add `jest` devDependency + `test` script
- [ ] `src/mission-control/bridge/jest.config.js` — minimal config (node env)
- [ ] `src/mission-control/bridge/test/` directory scaffold
- [ ] Smoke script `scripts/smoke-phase-21.sh` (or inline in PLAN verification) — curls `/health` + `/camera/history` after compose rebuild

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Farmer sees `snapshots_last_24h` chip in Mission Control health panel | D-06b | UI rendering requires browser | Load Mission Control, confirm chip visible and non-zero after 5+ min idle |
| 365-day retention prune runs without nuking a fresh install | D-04 | Requires >30 days runtime or clock manipulation | Verify prune guard logic in code + manual check at 30-day mark |
| Continuous timeline (no blank hours overnight) | D-01 / D-02 | Requires >1 overnight observation | After 24h of live bridge, confirm `SELECT count(*) FROM snapshots WHERE captured_at > now() - interval '24 hours'` ≥ 270 |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (jest install, config, test dir)
- [ ] No watch-mode flags
- [ ] Feedback latency < 20s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
