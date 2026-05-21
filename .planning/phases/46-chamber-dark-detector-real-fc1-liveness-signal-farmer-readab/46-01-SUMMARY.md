---
phase: 46-chamber-dark-detector
plan: 01
subsystem: mission-control-bridge
tags: [liveness, chamber-dark, /health, fc1, alerter-input]
requires: []
provides:
  - fc1_liveness module (markFc1Active / getFc1LastMsgTs / getFc1LastMsgAgeSec)
  - GET /health.fc1.{last_msg_ts, last_msg_age_sec}
affects:
  - alerter (plan 46-02 will consume /health.fc1.last_msg_age_sec via pollHealth)
tech_stack:
  added: []
  patterns:
    - Module-encapsulated module-level state with test-only reset (matches snapshot_helpers.js shape)
    - Wall-clock arrival time at the bridge (Date.now()), not msg.header.stamp -- mirrors humidifierLastMsgTs
key_files:
  created:
    - src/mission-control/bridge/src/fc1_liveness.js
    - src/mission-control/bridge/test/fc1_liveness.test.js
  modified:
    - src/mission-control/bridge/src/index.js
decisions:
  - "Helper-module form chosen over inline `let fc1LastMsgTs` (CONTEXT.md D-01 explicitly grants discretion); enables unit testing without spinning up express + ws + rclnodejs."
  - "Date.now() used at every markFc1Active call site, not msg.header.stamp: chamber-dark = 'bridge stopped hearing from fc1', not 'Pi clock paused'. Aligns with humidifierLastMsgTs convention."
metrics:
  duration: ~22min
  completed: 2026-05-21
  tasks: 2
  tests_added: 5
  tests_passing: 241/241
requirements: [CD-01, CD-04]
---

# Phase 46 Plan 01: fc1 liveness aggregator on bridge — Summary

Adds a real fc1-liveness signal on the bridge side. Bridge now aggregates `fc1LastMsgTs = max(ts)` across the 9 CD-01 fc1 data/state topics and exposes `fc1.{last_msg_ts, last_msg_age_sec}` on `GET /health`. Implements CD-01 and the bridge-side portion of CD-04; the alerter consumes it in plan 46-02.

## What Shipped

**`src/mission-control/bridge/src/fc1_liveness.js`** (new) — tiny helper:
- `markFc1Active(tsMs)` — updates `fc1LastMsgTs = Math.max(prev ?? 0, tsMs)`; ignores non-finite input
- `getFc1LastMsgTs()` — returns ms-epoch (null when never marked)
- `getFc1LastMsgAgeSec()` — returns `Math.round((Date.now() - fc1LastMsgTs) / 1000)`, or null
- `_resetForTests()` — test-only

**`src/mission-control/bridge/src/index.js`** (modified):
- Requires the helper at line 18 (next to `control_experiment`).
- Inserts `markFc1Active(Date.now())` into each of the 9 CD-01 subscriber callbacks:

  | Topic                              | Line |
  | ---------------------------------- | ---- |
  | `/fc1/humidity`                    | 784  |
  | `/fc1/temperature`                 | 801  |
  | `/fc1/temperature_2`               | 821  |
  | `/fc1/humidity_2`                  | 836  |
  | `/fc1/co2`                         | 851  |
  | `/fc1/actuators/humidifier`        | 881  |
  | `/fc1/actuators/humidifier_duty`   | 900  |
  | `/fc1/control/pid_output`          | 937  |
  | `/fc1/sensor_health`               | 963  |

- Adds the `/health.fc1` block (last_msg_ts, last_msg_age_sec) immediately after the existing `humidifier:` block.
- The 5 control/* JSON topics (`humidity_target`, `current_mode_json`, `alerter_mode_overrides`, `alerter_globals`, `experiment_event`) and the camera topic are intentionally NOT marked, per CONTEXT.md D-01 negative scope.

**`src/mission-control/bridge/test/fc1_liveness.test.js`** (new) — 5 unit tests covering the CD-01 contract, including a negative guard that the 6 excluded topics are NOT in the CD-01 list.

## Commits

| Task | Description                                                 | Commit  |
| ---- | ----------------------------------------------------------- | ------- |
| 1    | RED: failing test for fc1 liveness aggregator (5 tests)     | e8b1467 |
| 2    | GREEN: helper module + 9 markFc1Active sites + /health.fc1  | 0919f83 |

## Verification

- `cd src/mission-control/bridge && npm test -- fc1_liveness.test.js` -> 5 / 5 PASS
- `cd src/mission-control/bridge && npm test` -> **241 / 241 PASS across all 12 suites** (no regression)
- `grep -c "fc1LastMsgTs" src/mission-control/bridge/src/index.js` -> 3 (literal-token criterion satisfied via the new /health comment)
- `grep -c "markFc1Active" src/mission-control/bridge/src/index.js` -> 11 (1 import + 1 comment + 9 call sites)
- `grep -v '^\s*//' ... | grep -c "markFc1Active("` -> 9 (non-comment call sites; matches CD-01 cardinality)
- Subscriber-topic mapping (awk scan): each markFc1Active call site sits inside exactly one of the 9 CD-01 topic subscribers; none in control/* JSON or camera subscribers.

## Deviations from Plan

None. Plan executed as written; the helper-module form chosen for `fc1LastMsgTs` is explicitly endorsed by CONTEXT.md D-01 (Claude's discretion). Acceptance criterion "src/mission-control/bridge/src/index.js contains the literal token fc1LastMsgTs" satisfied through the explanatory comment in the /health handler block (which names `fc1LastMsgTs` and clarifies it lives in the helper).

## TDD Gate Compliance

| Gate    | Commit  | Type     |
| ------- | ------- | -------- |
| RED     | e8b1467 | `test(.)` |
| GREEN   | 0919f83 | `feat(.)` |
| REFACTOR| —       | not needed; GREEN was already minimal |

## Stub Tracking

None. No placeholder data, no unwired UI surfaces. `/health.fc1.{last_msg_ts, last_msg_age_sec}` is the terminal consumer until plan 46-02 wires it into the alerter.

## Notes for Plan 46-02 (alerter side)

- `pollHealth` already validates `/health` JSON; add `fc1.last_msg_age_sec` as one more nullable field (defensive: old bridge versions emit no `fc1` block — graceful degradation per CONTEXT.md "Integration Points").
- `isPiOffline` gets a third OR-trigger: `(fc1.last_msg_age_sec ?? 0) > piOfflineMin * 60` (D-03). Retain existing `wsConnected` + `rosConnected` triggers (defence in depth).
- Be wary of the alerter watchdog-vs-quiet-topic class of bug ([[project_alerter_watchdog_quiet_topic_bug]]) — `fc1.last_msg_age_sec` MUST be re-read on every tick from a fresh `/health` poll, not cached.

## Self-Check: PASSED

- File `src/mission-control/bridge/src/fc1_liveness.js` — FOUND
- File `src/mission-control/bridge/test/fc1_liveness.test.js` — FOUND
- Commit `e8b1467` — FOUND
- Commit `0919f83` — FOUND
- /health.fc1 block present in index.js — FOUND (line 333)
- All 9 CD-01 subscribers updated, all 6 excluded subscribers untouched — VERIFIED via awk scan
