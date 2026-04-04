---
phase: 4
slug: observability-integration
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-04
---

# Phase 4 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (via `colcon test`) |
| **Config file** | none — `setup.py` with `tests_require=['pytest']` |
| **Quick run command** | `pytest src/chambers/fc-core/fc_core/test/test_controller.py -x` |
| **Full suite command** | `colcon test --packages-select fc_core && colcon test-result --verbose` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest src/chambers/fc-core/fc_core/test/test_controller.py -x`
- **After every plan wave:** Run `colcon test --packages-select fc_core && colcon test-result --verbose`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 04-01-01 | 01 | 1 | ACTR-03 | — | N/A | unit | `pytest .../test_controller.py::test_humidifier_state_published -x` | ❌ W0 | ⬜ pending |
| 04-01-02 | 01 | 1 | SENS-02 | — | N/A | unit | `pytest .../test_controller.py::test_humidity_control -x` | ✅ | ⬜ pending |
| 04-02-01 | 02 | 2 | ACTR-01 | — | N/A | hardware | Manual on FC-1: `ssh fc1 'sudo journalctl -u fc-core -f'` + observe SSR | Manual only | ⬜ pending |
| 04-02-02 | 02 | 2 | TEST-02 | — | N/A | hardware/soak | Manual: 1-hour soak test with logging | Manual only | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `src/chambers/fc-core/fc_core/test/test_controller.py::test_humidifier_state_published` — stub for ACTR-03
- [ ] Verify `test_temperature_control` passes (fan_pwm None bug may cause failure)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Humidifier GPIO activates on control commands | ACTR-01 | Requires physical hardware (SSR + 220V load) | SSH to FC-1, observe SSR click and journalctl output during control loop |
| Full control loop on real hardware | TEST-02 | End-to-end hardware integration test | Run system for 1+ hours, verify humidity maintains 85-95% range, check logs for proper cycling |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
