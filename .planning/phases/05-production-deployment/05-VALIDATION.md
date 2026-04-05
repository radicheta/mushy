---
phase: 5
slug: production-deployment
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-05
---

# Phase 5 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (colcon test wrapper) |
| **Config file** | `src/chambers/fc-core/fc_core/test/test_controller.py` |
| **Quick run command** | `pytest src/chambers/fc-core/fc_core/test/ -x -q` |
| **Full suite command** | `colcon test --packages-select fc_core && colcon test-result --verbose` |
| **Estimated runtime** | ~10 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest src/chambers/fc-core/fc_core/test/ -x -q`
- **After every plan wave:** Run `colcon test --packages-select fc_core && colcon test-result --verbose`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 05-01-01 | 01 | 1 | DEPL-01 (config) | — | N/A | manual-verify | `ssh fc1 'grep target_humidity ~/mushroom_farm_ws/src/chambers/fc-core/config/fc_config.yaml'` | ✅ | ⬜ pending |
| 05-01-02 | 01 | 1 | DEPL-01 (stability) | — | N/A | manual-soak | `ssh fc1 'sudo systemctl show fc-core --property=NRestarts,ActiveState'` | ✅ | ⬜ pending |
| 05-01-03 | 01 | 1 | DEPL-01 (observability) | — | N/A | manual-verify | Open browser to localhost:8080 | ✅ | ⬜ pending |
| 05-01-04 | 01 | 1 | DEPL-01 (documentation) | — | N/A | manual-review | File existence + content review | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- None — no new test files needed. DEPL-01 is satisfied by deployment verification steps and human soak sign-off, not unit tests.

*Existing infrastructure covers all phase requirements.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Service runs 24h without unrecoverable crash | DEPL-01 (stability) | Physical soak test at farm — cannot be automated remotely | Deploy, wait 24h, check NRestarts and ActiveState via SSH |
| Dashboard shows live humidity/temp data | DEPL-01 (observability) | Requires browser + visual confirmation | Open localhost:8080 in browser, verify live chart updates |
| Config value 0.80 deployed to Pi | DEPL-01 (config) | Verifies physical deployment, not just repo state | SSH to fc1, grep target_humidity in config file |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
