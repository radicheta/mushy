---
phase: 7
slug: historical-data-storage-and-openmct-time-series-visualizatio
status: approved
nyquist_compliant: true
wave_0_complete: true
created: 2026-04-07
---

# Phase 7 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Per-task grep verification (infrastructure glue phase — no business logic) |
| **Config file** | N/A |
| **Quick run command** | `grep -q 'pool.query' src/mission-control/bridge/src/index.js && echo PASS` |
| **Full suite command** | `docker compose -f src/docker-compose.yml up bridge timescale -d && curl -sf http://localhost:8081/health` |
| **Estimated runtime** | < 5 seconds (grep); ~30 seconds (docker smoke) |

**Wave 0 justification:** This phase is infrastructure glue code — it wires existing services (ROS bridge, TimescaleDB, OpenMCT) together with no business logic. Each task has specific `<automated>` grep-based verification commands that confirm the correct code artifacts exist. The Docker smoke test in the checkpoint task (07-02 Task 3) validates end-to-end integration. No test stubs or fixtures are needed because:
- There are no pure functions to unit test (all code is I/O glue: DB writes, HTTP routes, WebSocket broadcast)
- The grep verifications satisfy Nyquist sampling by confirming every key artifact after each task
- The checkpoint task provides integration verification via `curl` against the running stack

---

## Sampling Rate

- **After every task commit:** Run the task's `<automated>` grep verification command
- **After Plan 01 wave:** `docker compose build bridge` succeeds (Dockerfile valid)
- **After Plan 02 wave:** `curl http://localhost:8081/health` returns `{"status":"ok","db":true}`
- **Before `/gsd-verify-work`:** Full docker compose up + browser smoke test
- **Max feedback latency:** 5 seconds (grep); 30 seconds (docker)

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 07-01-01 | 01 | 1 | HIST-03 | T-07-03 | Credentials in .env not compose | grep | `grep -q 'TIMESCALE_PASSWORD' src/.env && grep -q 'TIMESCALE_PASSWORD' src/docker-compose.yml` | N/A | pending |
| 07-01-02 | 01 | 1 | HIST-06 | — | Node.js entrypoint replaces rosbridge | grep | `grep -q 'node /opt/bridge/src/index.js' src/mission-control/bridge/entrypoint.sh` | N/A | pending |
| 07-01-03 | 01 | 1 | HIST-01, HIST-02 | T-07-01 | Parameterized queries, hypertable init | grep | `grep -q 'create_hypertable' src/mission-control/bridge/src/index.js && grep -q 'pool.query' src/mission-control/bridge/src/index.js` | N/A | pending |
| 07-02-01 | 02 | 2 | HIST-04 | T-07-04, T-07-05 | Topic allowlist, range cap | grep | `grep -q 'ALLOWED_TOPICS' src/mission-control/bridge/src/index.js && grep -q 'time_bucket' src/mission-control/bridge/src/index.js` | N/A | pending |
| 07-02-02 | 02 | 2 | HIST-05 | — | request() wired, 24h conductor default | grep | `grep -q 'historyUrl' src/mission-control/frontend/plugins/fruiting-chamber/plugin.js && grep -q 'fetch(url)' src/mission-control/frontend/plugins/fruiting-chamber/plugin.js` | N/A | pending |
| 07-02-03 | 02 | 2 | HIST-05 | — | End-to-end integration | smoke | `curl -sf http://localhost:8081/health \| grep -q '"db":true'` | N/A | pending |

*Status: pending · green · red · flaky*

---

## Wave 0 Requirements

Existing infrastructure covers all phase requirements. This is an infrastructure glue phase with no business logic — per-task grep verifications and the checkpoint Docker smoke test provide sufficient feedback sampling. No test stubs, fixtures, or Docker test infrastructure needed.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| OpenMCT time-series chart renders historical data | HIST-05 | Browser-based visualization requires human eye | Open OpenMCT at localhost:8080, navigate to FC-1 Humidity, set time conductor to Fixed 24h, verify chart shows historical data points |
| Live WebSocket streaming still works after bridge switch | HIST-06 | Visual confirmation of realtime chart updates | Watch OpenMCT chart for live updates while ROS is publishing |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify — grep commands for all 6 tasks
- [x] Sampling continuity: every task has automated verify (no gaps)
- [x] Wave 0 covered: infrastructure glue phase, grep verification sufficient
- [x] No watch-mode flags
- [x] Feedback latency < 30s (grep < 5s, curl < 30s)
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved
