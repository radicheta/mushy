---
phase: 03
slug: closed-loop-control
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-04
---

# Phase 03 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (python3-pytest, ROS2 ament test infra) |
| **Config file** | none (driven by colcon test) |
| **Quick run command** | `pytest src/chambers/fc-core/fc_core/test/test_controller.py -x` |
| **Full suite command** | `colcon test --packages-select fc_core && colcon test-result --verbose` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest src/chambers/fc-core/fc_core/test/test_controller.py -x`
- **After every plan wave:** Run `colcon test --packages-select fc_core && colcon test-result --verbose`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 03-01-01 | 01 | 1 | CTRL-01, CTRL-02 | unit | `pytest src/chambers/fc-core/fc_core/test/test_controller.py::test_humidity_control -x` | Yes (extend) | pending |
| 03-01-02 | 01 | 1 | CTRL-02 | unit | `pytest src/chambers/fc-core/fc_core/test/test_controller.py::test_new_params_declared -x` | No — W0 | pending |
| 03-02-01 | 02 | 1 | CTRL-03 | unit | `pytest src/chambers/fc-core/fc_core/test/test_controller.py::test_dwell_time_blocks_toggle -x` | No — W0 | pending |
| 03-02-02 | 02 | 1 | CTRL-03 | unit | `pytest src/chambers/fc-core/fc_core/test/test_controller.py::test_dwell_time_allows_toggle_after_wait -x` | No — W0 | pending |
| 03-03-01 | 03 | 1 | CTRL-04 | unit | `pytest src/chambers/fc-core/fc_core/test/test_controller.py::test_sensor_staleness -x` | No — W0 | pending |
| 03-03-02 | 03 | 1 | CTRL-05 | unit | `pytest src/chambers/fc-core/fc_core/test/test_controller.py::test_none_humidity_safe_state -x` | No — W0 | pending |
| 03-03-03 | 03 | 1 | CTRL-05 | unit | `pytest src/chambers/fc-core/fc_core/test/test_controller.py::test_safe_state_recovery -x` | No — W0 | pending |

*Status: pending · green · red · flaky*

---

## Wave 0 Requirements

- [ ] `test_new_params_declared` — covers CTRL-02 (min_dwell_time, sensor_stale_timeout defaults)
- [ ] `test_dwell_time_blocks_toggle` — covers CTRL-03 (guard prevents early toggle)
- [ ] `test_dwell_time_allows_toggle_after_wait` — covers CTRL-03 (guard permits toggle after wait)
- [ ] `test_sensor_staleness` — covers CTRL-04 (stale data -> humidifier OFF)
- [ ] `test_none_humidity_safe_state` — covers CTRL-05 (None humidity -> explicit OFF, not frozen)
- [ ] `test_safe_state_recovery` — covers CTRL-05 (auto-recover on fresh data)

All new tests go in existing file: `src/chambers/fc-core/fc_core/test/test_controller.py`.
No new test files or conftest.py needed — the `ros_context` fixture already handles rclpy init/shutdown.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| End-to-end on FC-1 hardware | TEST-02 | Requires physical Pi + sensor + actuator | Phase 4 scope — not this phase |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
