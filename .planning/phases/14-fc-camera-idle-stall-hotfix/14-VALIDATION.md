---
phase: 14
slug: fc-camera-idle-stall-hotfix
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-17
---

# Phase 14 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (ament_python / colcon test) |
| **Config file** | `src/chambers/fc-core/setup.py` + `src/chambers/fc-core/pytest.ini` if present |
| **Quick run command** | `cd ~/mushroom_farm_ws && colcon test --packages-select fc_core --event-handlers console_direct+ --pytest-args -x --ros-args` (fallback: `pytest src/chambers/fc-core/fc_core/test/test_camera.py -x`) |
| **Full suite command** | `cd ~/mushroom_farm_ws && colcon test --packages-select fc_core && colcon test-result --verbose` |
| **Estimated runtime** | ~15s quick, ~45s full |

---

## Sampling Rate

- **After every task commit:** Run the relevant single-file pytest for what changed (`pytest src/chambers/fc-core/fc_core/test/test_camera.py -x`)
- **After every plan wave:** Run full `colcon test --packages-select fc_core`
- **Before `/gsd-verify-work`:** Full suite green + 30-min live soak on fc1 per PLAN 14-03
- **Max feedback latency:** ~45s for automated; live soak is bounded at 30 min

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 14-01-01 | 01 | 0 | TBD | — | N/A | diagnostic | `ssh fc1-ts 'python3 -c "import rclpy; ..."'` — confirms Path A vs B | ❌ W0 | ⬜ pending |
| 14-02-01 | 02 | 1 | TBD | — | N/A | unit | `pytest src/chambers/fc-core/fc_core/test/test_camera.py::TestIdleToActiveRecovery::test_recovery_on_subscriber_appear` | ❌ W0 | ⬜ pending |
| 14-02-02 | 02 | 1 | TBD | — | N/A | unit | `pytest src/chambers/fc-core/fc_core/test/test_camera.py::TestIdleToActiveRecovery::test_idle_capture_still_works` | ❌ W0 | ⬜ pending |
| 14-02-03 | 02 | 1 | TBD | — | N/A | unit | `pytest src/chambers/fc-core/fc_core/test/test_camera.py::TestIdleToActiveRecovery::test_grace_period_survives_brief_disconnect` | ❌ W0 | ⬜ pending |
| 14-03-01 | 03 | 2 | TBD | — | N/A | integration | `curl -s http://localhost:8080/health \| jq .camera.last_frame_age_sec` — must be numeric when viewer connected | ✅ | ⬜ pending |
| 14-03-02 | 03 | 2 | TBD | — | N/A | soak | 30-min live soak on fc1: journalctl + /health polled every 60s — no stall reproduced after subscriber cycle | ✅ (manual) | ⬜ pending |
| 14-04-01 | 04 | 2 | TBD | — | N/A | UI smoke | MC camera panel shows two status lights; "feed live" green when viewer connected + frames flowing | ✅ (manual) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `src/chambers/fc-core/fc_core/test/test_camera.py` — add `TestIdleToActiveRecovery` class with three methods from the matrix above. Extend `FakeNode` with `count_subscribers()` method; extend `FakePublisher` with `get_subscription_count()` that can be driven independently (to reproduce the DDS asymmetry).
- [ ] No new framework install needed — colcon + pytest are already in place from Phase 1.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 30-min live soak on fc1 | D-02 | Requires real DDS stack, real V4L device, real Tailscale link | Deploy, start polling `/health` every 60s, connect MJPEG viewer, disconnect after 10 min, reconnect after 5 min, watch for `last_frame_age_sec` spike beyond 30s while subscribed=true |
| MC two-lights visual check | D-03 | Color/placement judgment | Open Mission Control → chamber panel → confirm two lights render; disconnect camera container → confirm "feed live" goes red within grace window |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (test harness extensions)
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s for unit tests
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending (autonomous run — will self-approve when all boxes checked at end of phase)
