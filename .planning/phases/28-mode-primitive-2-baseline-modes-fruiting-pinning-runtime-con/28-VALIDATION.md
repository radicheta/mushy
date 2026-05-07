---
phase: 28
slug: mode-primitive-2-baseline-modes-fruiting-pinning-runtime-con
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-07
---

# Phase 28 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Source: 28-RESEARCH.md `## Validation Architecture` section.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x (Python — fc_core, fc_msgs); jest (bridge — Node.js) |
| **Config file** | `src/chambers/fc-core/fc_core/test/` (existing); bridge: `src/mission-control/bridge/test/` (Wave 0 may install) |
| **Quick run command** | `colcon test --packages-select fc_msgs fc_core --pytest-args -x` |
| **Full suite command** | `colcon test --packages-select fc_msgs fc_core && (cd src/mission-control/bridge && npm test)` |
| **Estimated runtime** | ~30-60 seconds (unit); +N minutes for soak-style integration tests |

---

## Sampling Rate

- **After every task commit:** Run quick command (filtered to package touched)
- **After every plan wave:** Run full suite for the wave's packages
- **Before `/gsd-verify-work`:** Full suite green + manual on-fc1 soak attestation
- **Max feedback latency:** ~60 seconds for unit/integration; soak verifications batched at end-of-wave

---

## Per-Task Verification Map

> Filled by gsd-planner during plan creation. Each plan task gets a row.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| TBD | TBD | TBD | MODE-01..05 | TBD | TBD | TBD | TBD | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `src/chambers/fc-msgs/` package skeleton (foundation for D-13 — must build before any task that imports `fc_msgs`)
- [ ] `src/chambers/fc-core/fc_core/test/test_mode_resolution.py` — stubs for MODE-01 / D-08 ModeView resolver
- [ ] `src/chambers/fc-core/fc_core/test/test_band_edge_pid.py` — stubs for MODE-02 / D-09 band-edge error projection
- [ ] `src/chambers/fc-core/fc_core/test/test_mode_switch_service.py` — stubs for MODE-03 service-call (uses `rclpy.executors` + service client)
- [ ] `src/chambers/fc-core/fc_core/test/test_current_mode_topic.py` — stubs for MODE-04 (TRANSIENT_LOCAL late-subscriber assertion)
- [ ] `src/mission-control/bridge/test/control_param.test.js` — stubs for MODE-05 Layer 1 (`POST /control/param` happy path + allowlist reject)
- [ ] `src/mission-control/bridge/test/control_persist.test.js` — stubs for MODE-05 Layer 2 (`POST /control/persist` writes overlay; pivot to fc_buffer if SSH-from-bridge unverified)
- [ ] **Wave 0 spike** — verify rclnodejs `SetParameters` request shape against fc_controller (research Open Question 1) + verify bridge→fc1 SSH path or pivot to fc_buffer endpoint (Open Question 2). Findings feed planning, not just tests.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| HUMID-04 contract preserved under `fruiting` v0 | MODE-02 | Soak-on-fc1 runs hours; cannot be CI-gated | Deploy fc_msgs+fc_core to fc1; let `fruiting` run ≥4h; confirm RH stays inside 0.945–0.975 except brief excursions; compare against Phase 27 baseline window |
| Pinning `defend_side=low` rides diurnal swing without humidifier kicking on at high RH | MODE-02 | Requires real ambient temp swing (hours-to-days) | Switch fc1 to `pinning` mode via service or farmOS; watch `humidifier_duty` topic for ≥6h ambient cycle; confirm duty=0 whenever rh>0.90 |
| farmOS-side endpoint contract works end-to-end | MODE-05 / D-20 | Zoy-side surface; not in this repo's CI | Coordinate with Zoy on farmOS push; round-trip `POST /control/param` from farmOS UI; confirm controller observes new value next tick |
| Overlay yaml persists across `systemctl restart fc-core` | MODE-05 / D-17 Layer 2 | Restart side-effect on real Pi | `POST /control/persist`; `ssh fc1 'sudo systemctl restart fc-core'`; verify topic + ros2 param show overlay value |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s (unit/integration); soak items batched
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
