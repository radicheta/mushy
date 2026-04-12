---
phase: 10
slug: bridge-qos-mjpeg-delivery
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-12
---

# Phase 10 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (existing fc_core tests) + manual bridge verification |
| **Config file** | `src/chambers/fc-core/fc_core/test/` (existing) |
| **Quick run command** | `pytest src/chambers/fc-core/fc_core/test/ -x -q` |
| **Full suite command** | `colcon test --packages-select fc_core && colcon test-result --verbose` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest src/chambers/fc-core/fc_core/test/ -x -q`
- **After every plan wave:** Run `colcon test --packages-select fc_core && colcon test-result --verbose`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 10-01-01 | 01 | 1 | TDEBT-01 | — | N/A | integration | `docker compose restart bridge && curl -s http://localhost:8081/health` | N/A (manual) | ⬜ pending |
| 10-02-01 | 02 | 1 | TDEBT-02 | — | N/A | manual | SSH to Pi: `journalctl -u fc-core.service -b \| grep 192.168.1.193` | N/A (manual) | ⬜ pending |
| 10-02-02 | 02 | 1 | TDEBT-02 | — | N/A | manual | `curl -s --max-time 60 http://localhost:8081/camera/mjpeg > /dev/null` | N/A (manual) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Existing infrastructure covers all phase requirements. No new test framework or stubs needed.

Bridge verification is manual (docker compose restart + visual check). Pi verification requires SSH access (Phase 09 prerequisite).

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Humidifier state replays on bridge restart | TDEBT-01 | Requires running bridge container + Mission Control UI | `docker compose restart bridge`, check humidifier chart shows correct last state immediately |
| MJPEG stream delivers continuous frames | TDEBT-02 | Requires live camera feed from Pi over Tailscale | Open `/camera/mjpeg` in browser, confirm frame updates for 60+ seconds |
| No phantom peer log lines | TDEBT-02 | Requires Pi journalctl access | `journalctl -u fc-core.service -b` — no lines referencing `192.168.1.193` |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
