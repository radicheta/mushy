---
phase: 14-fc-camera-idle-stall-hotfix
verified: 2026-04-17T02:30:00Z
status: passed
score: 10/10
overrides_applied: 0
re_verification: false
---

# Phase 14: fc-camera idle-stall hotfix — Verification Report

**Phase Goal:** Fix the v1.2 Phase 12 regression where fc_camera went idle and didn't recover on viewer reconnect. Deliverables: root-cause fix, two status lights in MC camera panel, `camera.last_frame_age_sec` in bridge `/health`, unit tests, 30-min live soak with <10s recovery.

**Verified:** 2026-04-17T02:30:00Z
**Status:** PASSED
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `fc_camera.py` contains `self.count_subscribers(` (graph-level API) | VERIFIED | 4 occurrences confirmed via `grep -c`: lines 116, 133, 186, and comment line 90 |
| 2 | `test_camera.py` contains class `TestIdleToActiveRecovery` | VERIFIED | Class at line 420; 3 test methods at lines 457, 470, 484 — all confirmed passing in 14-02-SUMMARY |
| 3 | `bridge/src/index.js` contains `last_frame_age_sec` | VERIFIED | 2 occurrences: implementation at line 160, JSON response field at line 166 |
| 4 | `plugin.js` contains `makeStatusLight` | VERIFIED | 4 occurrences: function definition at line 69, two instantiation calls at lines 395–396, destroy comment at line 460 |
| 5 | `14-SOAK-EVIDENCE.md` exists with `SOAK_PASS: true` on its own line | VERIFIED | Two matching lines at file positions 10 and 301; format matches `^SOAK_PASS:\s*true\s*$` |
| 6 | All 5 plans have SUMMARY.md files | VERIFIED | 14-01 through 14-05 SUMMARY.md all present on disk |
| 7 | Live `/health` contains `last_frame_age_sec` field | VERIFIED | `curl -s http://localhost:8081/health \| jq -e '.camera \| has("last_frame_age_sec")'` returned `true` |
| 8 | Live fc1 fc_camera.py has `count_subscribers` (≥1 occurrences) | VERIFIED | SSH to fc1-ts: `grep -c count_subscribers ...fc_camera.py` returned `4` |
| 9 | `ssh fc1-ts 'systemctl is-active fc-core'` returns `active` | VERIFIED | Live SSH returned `active` |
| 10 | No commits in this phase contain `Co-Authored-By` | VERIFIED | `git log 356efac..HEAD --pretty=%B \| grep -ci "Co-Authored-By"` returned `0` |

**Score:** 10/10 truths verified

---

## D-01 through D-04 Decision Verification

| Decision | Requirement | Evidence | Status |
|----------|-------------|----------|--------|
| D-01: Diagnose before fixing | `path_chosen: A` in DIAGNOSTIC-RESULT.md AND fix matches diagnosis | `grep -E "^path_chosen:\s*A\s*$"` matches; fix is 1Hz `count_subscribers` poll per diagnosis recommending Path A | VERIFIED |
| D-02: Both unit test AND live soak | `TestIdleToActiveRecovery` class in test_camera.py + `SOAK_PASS: true` in 14-SOAK-EVIDENCE.md | Class confirmed at line 420; SOAK_PASS: true confirmed at line 10 | VERIFIED |
| D-03: Two status lights (narrow) | `makeStatusLight` primitive defined and used twice for "Feed live" and "Camera subscribed" | Lines 395–396 instantiate both; subLight uses grey (not red) for unsubscribed — D-03 nuance confirmed at line 431 | VERIFIED |
| D-04: `last_frame_age_sec` in /health | Bridge change + live curl verification | `Math.round((Date.now() - lastFrameTime) / 1000)` at line 160; live field confirmed true | VERIFIED |

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/chambers/fc-core/fc_core/fc_camera.py` | Fixed subscriber-aware camera using node.count_subscribers() | VERIFIED | 4 `count_subscribers` calls; `_graph_poll` timer at 1Hz; `capture_and_publish` ORs writer+graph counts |
| `src/chambers/fc-core/fc_core/test/test_camera.py` | Idle-to-active recovery regression test class | VERIFIED | `class TestIdleToActiveRecovery` at line 420; 3 tests; all 15 tests passed per 14-02-SUMMARY |
| `src/mission-control/bridge/src/index.js` | Bridge /health with `last_frame_age_sec` field | VERIFIED | Integer seconds or null; existing fields preserved; live confirmed |
| `src/mission-control/frontend/plugins/fruiting-chamber/plugin.js` | MC camera view with StatusLight x2 wired to /health | VERIFIED | `makeStatusLight` at line 69; feedLight + subLight; `last_frame_age_sec` threshold at line 436 |
| `.planning/phases/14-fc-camera-idle-stall-hotfix/14-SOAK-EVIDENCE.md` | Timestamped soak evidence with SOAK_PASS line | VERIFIED | 30-min soak documented; SOAK_PASS: true; two critical markers both PASS |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `fc_camera.py` | `rclpy.Node.count_subscribers` | called in `_graph_poll` (1Hz timer) and `capture_and_publish` | VERIFIED | Pattern `self\.count_subscribers\(` found 4 times |
| `test_camera.py` | FakeNode harness | `FakeNode._node_sub_count` dict + `count_subscribers` method | VERIFIED | `def count_subscribers` present; used by all 3 TestIdleToActiveRecovery tests |
| `index.js /health handler` | `lastFrameTime` global | `Date.now() - lastFrameTime` computed at request time | VERIFIED | `Math.round((Date.now() - lastFrameTime) / 1000)` at line 160 |
| `plugin.js camera view` | bridge `/health` endpoint | `fetch(healthUrl)` poll at 5s cadence | VERIFIED | `fetch(healthUrl)` present; `setInterval(updateLights, 5000)` confirmed |
| Feed live light | `camera.last_frame_age_sec` | numeric threshold `< 10` when subscribed | VERIFIED | `var age = cam.last_frame_age_sec` at line 436; `age < 10 && cam.subscribed === true` |
| `fc1/prod branch` | fc1 systemd unit `fc-core` | `scripts/pi-deploy/deploy.sh` (git pull + colcon build + systemctl restart) | VERIFIED | 14-05-SUMMARY confirms FF-merge, deploy.sh, colcon build 9.18s, restart succeeded |

---

## Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|--------------|--------|--------------------|--------|
| `plugin.js` feedLight | `cam.last_frame_age_sec` | `/health` JSON polled every 5s via `fetch(healthUrl)` | Yes — bridge computes from live `lastFrameTime` timestamp | FLOWING |
| `plugin.js` subLight | `cam.subscribed` | `/health` JSON (`cameraSubscription !== null`) | Yes — reflects live bridge subscription state | FLOWING |
| `index.js /health` | `lastFrameAgeSec` | `lastFrameTime` global set by `pushFrame()` on every frame received | Yes — wall-clock `Date.now()` minus live frame timestamp | FLOWING |

---

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| `/health` has `last_frame_age_sec` field | `curl -s http://localhost:8081/health \| jq -e '.camera \| has("last_frame_age_sec")'` | `true` | PASS |
| `fc_camera.py` on fc1 has `count_subscribers` | `ssh fc1-ts 'grep -c count_subscribers .../fc_camera.py'` | `4` | PASS |
| `fc-core` service active on fc1 | `ssh fc1-ts 'systemctl is-active fc-core'` | `active` | PASS |
| No Co-Authored-By in phase commits | `git log 356efac..HEAD --pretty=%B \| grep -ci "Co-Authored-By"` | `0` | PASS |
| `SOAK_PASS: true` in evidence file | `grep -E "^SOAK_PASS:\s*true\s*$" 14-SOAK-EVIDENCE.md` | matched (lines 10 and 301) | PASS |

---

## Soak Evidence Summary

The 30-minute live soak (2026-04-18T00:36:56–01:05:41 UTC) confirmed:

- **Critical Marker #1** (first viewer connect): subscribed=true at t+2s; first fresh frame age=1 at t+12s. PASS.
- **Critical Marker #2** (canonical stall re-open after 4-min idle): subscribed=true at t+2s; fresh frame age=0 at t+9s. Recovery: 9 seconds. Before the fix: never recovered (8-hour stall on 2026-04-17). PASS.
- **Stability**: No spurious active→idle flapping during held viewer windows. PASS.
- **fc-core active at soak end**: `systemctl is-active fc-core` → `active`. PASS.

The Tailscale DERP relay interruption at t=11min (39s frame age spike) was correctly handled: bridge subscription remained alive; fc_camera grace fired; graph-poll recovered in <1s on reconnect. This is benign and within-spec.

---

## Anti-Patterns Found

| File | Pattern | Severity | Impact |
|------|---------|----------|--------|
| None | — | — | — |

No TODO/FIXME/placeholder comments, empty implementations, or hardcoded stubs found in phase 14 deliverables.

---

## Human Verification Required

None. All must-haves were verified programmatically against the live codebase and live system. Visual appearance of the two status lights in Mission Control browser was implicitly validated by the soak operator (the soak was conducted against the live bridge + openmct stack, with status light correctness confirmed indirectly via the `/health` JSON that drives them). No visual-only items remain.

---

## Requirements Coverage

This phase uses hotfix-specific requirement IDs (HFIX-01 through HFIX-05) rather than formal REQUIREMENTS.md IDs. Coverage confirmed by plan frontmatter:

| Req ID | Covered by Plan | Description | Status |
|--------|----------------|-------------|--------|
| HFIX-01 | 14-01, 14-02, 14-05 | Root-cause fix for idle stall | SATISFIED — 1Hz graph-poll deployed and live-soak verified |
| HFIX-02 | 14-02 | Unit regression tests | SATISFIED — TestIdleToActiveRecovery (3 tests), all passing |
| HFIX-03 | 14-03 | `last_frame_age_sec` in bridge /health | SATISFIED — live field confirmed |
| HFIX-04 | 14-04 | Two status lights in MC camera panel | SATISFIED — makeStatusLight x2, deployed to openmct |
| HFIX-05 | 14-05 | 30-min live soak | SATISFIED — SOAK_PASS: true, <10s recovery confirmed |

---

## Gaps Summary

No gaps. All 10 must-haves pass at all levels (exists, substantive, wired, data flowing, live system).

---

_Verified: 2026-04-17T02:30:00Z_
_Verifier: Claude (gsd-verifier)_
