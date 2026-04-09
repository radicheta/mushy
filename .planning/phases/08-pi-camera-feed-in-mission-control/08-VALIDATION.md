---
phase: 08
slug: pi-camera-feed-in-mission-control
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-08
---

# Phase 08 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (existing fc_core tests) + manual verification (camera stream) |
| **Config file** | src/chambers/fc-core/fc_core/test/ (existing test directory) |
| **Quick run command** | `pytest src/chambers/fc-core/fc_core/test/ -x -q` |
| **Full suite command** | `colcon test --packages-select fc_core` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest src/chambers/fc-core/fc_core/test/ -x -q`
- **After every plan wave:** Run `colcon test --packages-select fc_core`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 08-01-01 | 01 | 1 | — | — | N/A | unit | `pytest -x -q` | ❌ W0 | ⬜ pending |
| 08-02-01 | 02 | 2 | — | — | N/A | integration | `curl http://localhost:8081/camera/mjpeg` | ❌ W0 | ⬜ pending |
| 08-03-01 | 03 | 3 | — | — | N/A | manual | Browser opens Mission Control camera view | ❌ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `src/chambers/fc-core/fc_core/test/test_camera.py` — stub for camera node config and topic tests
- [ ] Verify USB webcam accessible via v4l2 on fc1 Pi (`ls /dev/video*`)

*Existing pytest infrastructure covers framework requirements.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Camera feed visible in Mission Control | D-13, D-14 | Requires browser + running OpenMCT instance | Open Mission Control, navigate to camera view, verify MJPEG stream displays |
| Snapshot files created on elder-plops | D-10, D-11 | Requires running system with time passage | Wait 15+ minutes, check /data/snapshots/fc1/ for timestamped JPEG files |
| Stream works over WireGuard/cellular | D-02, D-04 | Requires farm network environment | Access Mission Control from remote device over VPN, verify camera loads |

*Stream quality and bandwidth usage require production environment verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
