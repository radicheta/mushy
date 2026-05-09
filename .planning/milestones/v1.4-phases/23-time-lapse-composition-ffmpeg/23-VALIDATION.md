---
phase: 23
slug: time-lapse-composition-ffmpeg
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-26
---

# Phase 23 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | jest (Node.js) |
| **Config file** | `src/mission-control/timelapse/package.json` — Wave 0 installs |
| **Quick run command** | `cd src/mission-control/timelapse && npm test` |
| **Full suite command** | `cd src/mission-control/timelapse && npm test` |
| **Estimated runtime** | ~10 seconds |

---

## Sampling Rate

- **After every task commit:** Run `cd src/mission-control/timelapse && npm test`
- **After every plan wave:** Run `cd src/mission-control/timelapse && npm test`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 23-01-01 | 01 | 1 | — | — | N/A | manual | `docker build -t timelapse src/mission-control/timelapse` | ❌ W0 | ⬜ pending |
| 23-01-02 | 01 | 1 | — | — | N/A | manual | `docker compose config` exits 0 | ❌ W0 | ⬜ pending |
| 23-02-01 | 02 | 1 | — | — | N/A | unit | `cd src/mission-control/timelapse && npm test -- composer` | ❌ W0 | ⬜ pending |
| 23-02-02 | 02 | 1 | — | T-23-01 | Path traversal rejected | unit | `cd src/mission-control/timelapse && npm test -- path` | ❌ W0 | ⬜ pending |
| 23-03-01 | 03 | 2 | — | — | N/A | unit | `cd src/mission-control/timelapse && npm test -- rh-lookup` | ❌ W0 | ⬜ pending |
| 23-04-01 | 04 | 2 | — | — | N/A | manual | `curl http://localhost:3002/timelapse?from=...` | ❌ W0 | ⬜ pending |
| 23-05-01 | 05 | 3 | — | — | N/A | manual | Inspect output mp4 for timestamp + RH overlay | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `src/mission-control/timelapse/test/composer.test.js` — stubs for composer unit tests
- [ ] `src/mission-control/timelapse/test/rh-lookup.test.js` — stubs for RH nearest-neighbor lookup
- [ ] `jest` — install in timelapse package.json devDependencies

*If none: "Existing infrastructure covers all phase requirements."*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| mp4 overlay correct (timestamp + RH readable) | D-06 | Requires visual inspection of video frame | Play output mp4, verify top-left timestamp and top-right RH text are legible |
| Nightly cron fires at 00:30 | D-02 | Time-based trigger requires 24h wait | Check container logs morning after deploy |
| On-demand endpoint returns 202 + job-id on miss | D-03 | Requires integration with compose stack | `curl http://localhost:3002/timelapse?from=2026-04-25T00:00:00Z&to=2026-04-25T23:59:59Z&camera_id=fc1` |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
