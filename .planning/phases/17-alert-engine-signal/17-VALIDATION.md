---
phase: 17
slug: alert-engine-signal
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-18
---

# Phase 17 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Planner must populate the Per-Task Verification Map from PLAN.md task IDs.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | jest 29.x (Node, matches bridge stack) |
| **Config file** | `src/agents/alerter/jest.config.js` (Wave 0 installs) |
| **Quick run command** | `cd src/agents/alerter && npm test -- --testPathPattern=<file>` |
| **Full suite command** | `cd src/agents/alerter && npm test` |
| **Estimated runtime** | ~15 seconds (pure-fn unit tests; no I/O) |

Integration/human-attested tests (Wave 4) use docker compose + live signal-cli and are not part of the jest suite.

---

## Sampling Rate

- **After every task commit:** Run quick command for the file touched
- **After every plan wave:** Run full suite
- **Before `/gsd-verify-work`:** Full suite green + Wave 4 human-attested delivery confirmed
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

*Planner fills this in from PLAN.md task IDs. Template rows below.*

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 17-01-01 | 01 | 0 | ALRT-06 | — | env-var config only | scaffold | `ls src/agents/alerter/package.json` | ❌ W0 | ⬜ pending |
| 17-XX-XX | XX | X | ALRT-XX | T-17-XX | {secure behavior} | unit/integration | `{cmd}` | ❌ W0 | ⬜ pending |

---

## Wave 0 Requirements

- [ ] `src/agents/alerter/package.json` — deps: ws, pg, axios, jest
- [ ] `src/agents/alerter/jest.config.js` — test runner config
- [ ] `src/agents/alerter/test/fixtures/` — canned bridge WS messages (sensor_health WARN/OK/ERROR, humidifier on/off, RH in/out-of-band)
- [ ] `src/agents/alerter/test/helpers/fake-signal-server.js` — mock signal-cli-rest-api for integration tests
- [ ] Container networking probe task (host-mode bridge ↔ bridge-network alerter) — validates `host.docker.internal:host-gateway` before any state-machine work

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Farmer receives PROBLEM + RECOVERY Signal on phone for each of 4 alert types | ALRT-02, ALRT-03, ALRT-04 | Requires real Signal delivery to farmer's registered device | Wave 4 runbook: trigger each condition on fc1 or via test harness, confirm farmer-attested delivery |
| Daily heartbeat arrives at configured TZ time | ALRT-04 | 24h elapsed-time observation | Deploy, wait 24h, farmer confirms |
| Snooze reply suppresses alerts for duration | ALRT-07 | Real Signal inbound via 4G SIM | Farmer sends `snooze rh 1h`, ops re-triggers RH OOB, confirms silence until window ends |
| Signal primary-account registration on 4G router SIM | ALRT-01 pre-gate | Operator physical action + SMS verification | Pre-phase runbook in RESEARCH.md §8 |
| No alerts in 20s sensor warm-up window | ALRT-05 | Restart fc-core, observe real stack | `systemctl restart fc-core` on fc1; `docker logs alerter` shows zero Signal POSTs in first 25s |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (jest, fixtures, fake-signal-server, networking probe)
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s for unit tests
- [ ] `nyquist_compliant: true` set in frontmatter after planner populates map

**Approval:** pending
