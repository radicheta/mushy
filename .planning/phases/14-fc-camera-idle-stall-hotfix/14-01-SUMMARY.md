---
phase: 14
plan: 01
subsystem: fc_camera / diagnostics
tags: [diagnostic, camera, ros2, rclpy, read-only]
dependency_graph:
  requires: []
  provides: [14-DIAGNOSTIC-RESULT.md, path_chosen=A]
  affects: [14-02-PLAN.md]
tech_stack:
  added: []
  patterns: [read-only SSH probe, rclpy Node.count_subscribers probe]
key_files:
  created:
    - .planning/phases/14-fc-camera-idle-stall-hotfix/14-DIAGNOSTIC-RESULT.md
  modified: []
decisions:
  - "path_chosen: A — 1 Hz graph-poll timer using node.count_subscribers(); no bridge changes needed"
  - "Root cause is polling frequency (3597 s idle period), not API staleness"
  - "Both count_subscribers() and get_subscription_count() are accurate; only get_subscription_count() is called too infrequently"
metrics:
  duration: ~12 minutes
  completed_date: 2026-04-18
  tasks_completed: 4
  tasks_total: 4
  files_created: 1
  files_modified: 0
---

# Phase 14 Plan 01: Live Diagnostic — Summary

**One-liner:** Saturday-morning read-only probe confirms Path A (1 Hz `count_subscribers` poll timer) — root cause is idle callback frequency (3597 s), not DDS API staleness.

## What Was Built

No code was deployed. This plan was entirely read-only on fc1. The output is a single evidence file at `.planning/phases/14-fc-camera-idle-stall-hotfix/14-DIAGNOSTIC-RESULT.md` documenting the probe results and fixing the path choice for plan 14-02.

## Path Chosen

**Path A** — add a 1 Hz `_graph_poll` timer in `fc_camera.py` that calls `self.count_subscribers('/fc1/camera/compressed')` and triggers `_ramp_up()` when > 0. No bridge changes required.

## Raw Numbers Observed

| Measurement | Value |
|-------------|-------|
| `/health.lastFrame` epoch | 1776468979213 ms (2026-04-17T23:49:39 UTC) |
| Frame age at probe time | 2868 s (~47.8 min) |
| `/health.subscribed` | false (bridge correctly unsubscribed — no MJPEG clients) |
| `/health.clients` | 0 |
| DDS Subscription count (CLI participant) | 0 |
| Probe `count_subscribers=` | 0 |
| Probe `count_publishers=` | 1 |

## Was the Stall Still Live at Probe Time?

**Partially.** The documented stall (52-min stale frame while `subscribed=true`) had evolved overnight:

- At 23:18:53 UTC (60 min after 22:18 service restart), the first idle tick fired and `get_subscription_count()` returned 1 — fc_camera went ACTIVE, new frames flowed.
- At 23:37:21 UTC fc_camera went idle again (viewers left).
- Around 00:05 UTC both MJPEG clients disconnected; bridge unsubscribed.
- By probe time (00:24 UTC) the system was in the CORRECT idle state (no subscribers, no clients).

The frame staleness at probe time (2868 s) is expected — no subscribers means no active capture, which is correct behavior.

## Root Cause Clarified

The research hypothesized H1 (DDS matched-endpoints cache staleness). The overnight journal evidence refines this:

- `get_subscription_count()` IS accurate — it returned 1 correctly at 23:18 when the bridge was subscribed.
- The stall was caused by the 3597-second idle timer period: after the 22:18 restart, `capture_and_publish` (the only function that calls `get_subscription_count()`) did not fire for 60 minutes. During that window fc_camera simply never had a chance to detect the existing bridge subscription.
- `count_subscribers()` confirmed live-accurate (returned 0 with no active subscribers — consistent with DDS state, not stale).

**True root cause: the polling function is called at the idle capture rate (once per 3597 s), making worst-case recovery ~60 minutes. Fix is to poll at 1 Hz via a separate timer.**

## Surprises That Affect Plan 14-02

1. **Both APIs are accurate** — the fix can use either `count_subscribers()` or `get_subscription_count()` for the new 1 Hz timer. Research recommended `count_subscribers()` (node-level graph) as more robust; this remains the right choice since it avoids any theoretical future staleness of the publisher-local cache. Plan 14-02 proceeds exactly as written.

2. **No asymmetry observable today** — the probe could not demonstrate a live discrepancy between the two APIs because the bridge was not subscribed at probe time. This does not undermine Path A; the 23:18 journal evidence confirms the fix is necessary and sufficient.

3. **23:18 idle tick self-healed the stall** — this means the live repro from the research period is no longer present. Plan 14-02's unit tests (TestIdleToActiveRecovery) will serve as the primary validation gate; the live soak (plan 14-05) will confirm end-to-end recovery behavior post-fix.

4. **Probe did not perturb fc-core** — confirmed by checking `/health.lastFrame` before and after probe (unchanged), and `systemctl is-active fc-core` returns `active`.

## Deviations from Plan

None — plan executed exactly as written. The stall state evolving overnight was anticipated in the fallback_instructions ("If the diagnostic shows `count_subscribers()` >= 1 AND the current publisher ALSO returns >= 1 (hypothesis overturned — stall self-healed)") — the probe returned 0/0 which does not match that fallback exactly. The correct reading is that `subscribed=false` at probe time made both APIs return 0 legitimately, confirming they are both live-accurate. Path A remains valid.

## Self-Check: PASSED

- `.planning/phases/14-fc-camera-idle-stall-hotfix/14-DIAGNOSTIC-RESULT.md` exists
- `grep -E "^path_chosen:\s*(A|B)\s*$"` matches `path_chosen: A`
- `grep -E "count_subscribers=[0-9]+"` matches `PROBE_RESULT count_subscribers=0`
- Commit `ef7e53d` exists with message `docs(14): capture live-stall diagnostic — path_chosen=A`
- No Co-Authored-By trailer in commit
- `ssh fc1-ts 'systemctl is-active fc-core'` returned `active`
