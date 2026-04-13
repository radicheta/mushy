---
phase: 12
slug: subscriber-aware-camera
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-13
---

# Phase 12 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | src/chambers/fc-core/fc_core/test/ (existing) |
| **Quick run command** | `pytest src/chambers/fc-core/fc_core/test/ -x -q` |
| **Full suite command** | `pytest src/chambers/fc-core/fc_core/test/` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest src/chambers/fc-core/fc_core/test/ -x -q`
- **After every plan wave:** Run `pytest src/chambers/fc-core/fc_core/test/`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 12-01-01 | 01 | 0 | CAM-01 | — | N/A | unit | `pytest src/chambers/fc-core/fc_core/test/test_camera_subscriber.py -x -q` | ❌ W0 | ⬜ pending |
| 12-01-02 | 01 | 0 | CAM-02 | — | N/A | unit | `pytest src/chambers/fc-core/fc_core/test/test_camera_subscriber.py -x -q` | ❌ W0 | ⬜ pending |
| 12-01-03 | 01 | 0 | CAM-03 | — | N/A | unit | `pytest src/chambers/fc-core/fc_core/test/test_camera_grace_period.py -x -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `src/chambers/fc-core/fc_core/test/test_camera_subscriber.py` — stubs for CAM-01, CAM-02
- [ ] `src/chambers/fc-core/fc_core/test/test_camera_grace_period.py` — stubs for CAM-03
- [ ] Extend existing `FakeNode`/`FakePublisher` test harness with subscriber count simulation

*Existing pytest infrastructure covers framework needs.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| MJPEG stream smooth during rate transition | CAM-02 (SC-4) | Visual quality requires human judgment | Open Mission Control, watch stream, close/reopen — no visible stutter |
| 4G bandwidth reduction at idle | CAM-01 | Requires real hardware + 4G link | Monitor `ros2 topic hz /fc1/camera/compressed` on Pi with 4G hotspot |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
