---
phase: 27
slug: pid-time-proportional-duty-cycle-primitive
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-01
---

# Phase 27 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (ament_python) |
| **Config file** | `src/chambers/fc-core/pytest.ini` (or section in setup.cfg — Wave 0 confirms) |
| **Quick run command** | `pytest src/chambers/fc-core/fc_core/test/ -x --timeout=10` |
| **Full suite command** | `colcon test --packages-select fc_core --event-handlers console_direct+ && colcon test-result --verbose` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest src/chambers/fc-core/fc_core/test/test_<unit>.py -x`
- **After every plan wave:** Run `colcon test --packages-select fc_core`
- **Before `/gsd-verify-work`:** Full suite green AND 2-hour HUMID-04 soak attestation captured on Mission Control
- **Max feedback latency:** 30 seconds (unit) / 2 hours (HUMID-04 soak — manual)

---

## Per-Task Verification Map

> Filled by planner. Each PLAN.md task entry must map to a row here. Coverage requirement: every HUMID-XX requirement appears in at least one row.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 27-01-01 | 01 | 0 | HUMID-01..04 | — | n/a | unit (scaffold) | `pytest src/chambers/fc-core/fc_core/test/test_pid_kernel.py -x` | ❌ W0 | ⬜ pending |
| 27-02-XX | 02 | 1 | HUMID-01 | — | duty publish on every tick | unit | `pytest src/chambers/fc-core/fc_core/test/test_pwm_driver.py -x` | ❌ W0 | ⬜ pending |
| 27-03-XX | 03 | 2 | HUMID-02 | — | bumpless transfer on grace/recovery | unit | `pytest src/chambers/fc-core/fc_core/test/test_pid_controller.py -x` | ❌ W0 | ⬜ pending |
| 27-04-XX | 04 | 3 | HUMID-03 | — | bridge subscribes to humidifier_duty | integration | `pytest src/mission-control/bridge/test/test_duty_topic.test.js` (or curl validation) | ❌ W0 | ⬜ pending |
| 27-05-XX | 05 | 3 | HUMID-04 | — | ±0.5% RH 2h soak | manual | farmer-attested Mission Control trace | n/a | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

> Planner: replace placeholder rows with concrete task IDs once plan structure is finalized.

---

## Wave 0 Requirements

- [ ] `src/chambers/fc-core/fc_core/test/test_pid_kernel.py` — PID math unit tests (saturation, anti-windup clamping, derivative-on-measurement, output_limits, bumpless `set_auto_mode(True, last_output=0.15)`)
- [ ] `src/chambers/fc-core/fc_core/test/test_pwm_driver.py` — slow-PWM windowing math (120s window, 10s min ON pulse rounding-down, rolling 5-min cap, Mode-C bypass entry/exit, sensor-stale duty=0.0 forced state)
- [ ] `src/chambers/fc-core/fc_core/test/test_pid_controller.py` — controller-level integration: setpoint ramp slew (D-07), bumpless integrator preload, sensor-stale safe state, grace gating preserved
- [ ] `src/chambers/fc-core/fc_core/test/conftest.py` — shared fixtures (mock SensorMsg publisher, fake clock, ROS context isolation)
- [ ] Vendor `simple-pid` into `src/chambers/fc-core/fc_core/vendor/simple_pid/` (offline-friendly per fc1 SSH-DERP unreliability)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| ±0.5% RH over 2-hour soak | HUMID-04 | Real-world chamber dynamics + farmer attestation; no simulator approximates SHT30 noise + chamber transport delay faithfully enough | Deploy to fc1, hold target_humidity unchanged for 2h, screenshot Mission Control humidity + humidifier_duty + humidifier traces, confirm trace stays inside ±0.5% band, zero "DWELL-BLOCK" log lines, no operator-visible slam on grace-clear or stale-recovery |
| Mode-C visual sanity | HUMID-02 | Operator-visible behavior — no instant slam on mode switch / setpoint step | Issue `ros2 param set /fc_controller target_humidity` step ≥3% RH, observe Mode-C engages (full-ON), observe smooth handoff back to PID once inside band |
| Bumpless on grace-clear | HUMID-02 | Visual inspection of duty trace on first tick after warmup gate clears | After `systemctl restart fc-core`, observe humidifier_duty starts at ~0.15 (not 1.0), no spike |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (vendor simple-pid, scaffold 3 test files, conftest)
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s for unit tests
- [ ] `nyquist_compliant: true` set in frontmatter (planner flips after task map filled)

**Approval:** pending
