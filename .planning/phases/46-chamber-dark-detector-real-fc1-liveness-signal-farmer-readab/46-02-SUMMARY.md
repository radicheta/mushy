---
phase: 46-chamber-dark-detector
plan: 02
subsystem: alerter
tags: [alerter, chamber-dark, fc1-liveness, signal-alerts]
requires: [46-01]  # consumes h.fc1.last_msg_ts from /health (added by parallel plan 46-01)
provides: [chamber-level-pi-alert, fc1-liveness-trigger, per-sensor-suppression]
affects: [src/agents/alerter]
tech-stack:
  added: []
  patterns: [graceful-degradation-via-null-coalesce, one-directional-suppression]
key-files:
  created: []
  modified:
    - src/agents/alerter/src/rules.js
    - src/agents/alerter/src/bridge-client.js
    - src/agents/alerter/src/state.js
    - src/agents/alerter/src/message.js
    - src/agents/alerter/test/rules.test.js
    - src/agents/alerter/test/state.test.js
    - src/agents/alerter/test/message.test.js
    - src/agents/alerter/test/bridge-client.test.js
decisions:
  - "D-03 implemented as `!= null` guard so undefined (pre-46 caller) and null (old bridge) both skip the new branch identically"
  - "D-07 suppression placed at every per-sensor driveAlertType call site; state updates (sht30LastSeenMs/scd41LastSeenMs) deliberately retained so re-evaluation post-recovery uses accurate liveness"
  - "Test fixture for fmtNum rounding moved from 94.05 to 94.15 (JS float quirk: 94.05 rounds to 94.0 via toFixed)"
metrics:
  duration: "~45min"
  completed: 2026-05-21
  tasks: 2
  files-touched: 8
  test-count-delta: "+22 (706 -> 728), all 720 non-skipped passing"
---

# Phase 46 Plan 02: Alerter chamber-dark wiring Summary

Wire bridge-emitted `fc1LastMsgTs` into the alerter as a third OR-trigger for `isPiOffline`, rewrite the pi-alert message chamber-level, and suppress per-sensor noise while chamber-dark fires.

## Tasks

### Task 1 — Failing tests
**Commit:** `1e78cf1`

Added 22 failing tests across the four target files:

- `rules.test.js` (+6 tests): stale `fc1LastMsgTs` fires; fresh blocks; `undefined`/`null` graceful-degrade; existing ws/ros triggers retained as independent paths.
- `state.test.js` (+8 tests): `pi_liveness` with stale `fc1LastMsgTs` drives `perType.pi` to FIRING with one `send` action; sht30/scd41/RH-OOB/humidifier-stuck suppressed while `pi` FIRING (D-07); D-08 one-directional (scd41 FIRING does NOT block pi); recovery resumes per-sensor evaluation.
- `message.test.js` (Tests A and 1–4 retargeted to new chamber-level format; Test 5 dashboardUrl-once preserved): contains `FC-1 offline`, `chamber uncontrolled`, `last RH ... @ HH:MM`, `no recent samples` fallback, no em-dash, fmtNum rounding.
- `bridge-client.test.js` (+3 tests): `pollHealth` forwards `fc1LastMsgTs` from `h.fc1.last_msg_ts`; null when block absent; `ws_close` mirrors cached `lastHealth.fc1.last_msg_ts`.

Baseline before commit: 16 new tests failed (one further test surfaced post-implementation as a JS float quirk — see Deviations). 98 existing tests still green.

### Task 2 — Implementation
**Commit:** `aeee31a`

- **`rules.js`** — `isPiOffline` adds the third OR-trigger as a tail block after the two existing branches, guarded by `fc1LastMsgTs != null`. The existing `wsConnected`/`rosConnected` paths are unchanged.
- **`bridge-client.js`** — `pollHealth`, `ws.on('close')` and the catch branch all forward `fc1LastMsgTs: h.fc1 ? h.fc1.last_msg_ts : null` (catch path forwards `null`).
- **`state.js`**:
  - Initial state factory gains `fc1LastMsgTs: null`.
  - `pi_liveness` handler destructures `fc1LastMsgTs` from the event, stores it on `next` (only when not `undefined` — preserves prior value if an old event arrives), and forwards into both `isPiOffline` calls (handler + `tick` case).
  - D-07 suppression: a `next.perType.pi.state !== STATES.FIRING` guard wraps every per-sensor `driveAlertType` call site: humidity case (rh + humidifier-stuck), sensor_health case (sht30 + scd41), sensor_freshness case (single-sensor re-eval), tick case (humidifier-stuck + per-sensor watchdog re-eval). The pi evaluator itself is intentionally NOT wrapped (D-08).
- **`message.js`** — pi branch fully rewritten:
  - `FC-1 offline ?? no telemetry XXm. chamber uncontrolled. last RH XX% @ HH:MM.` when `lastKnown` present.
  - `FC-1 offline ?? no telemetry XXm. chamber uncontrolled. no recent samples.` when `lastKnown == null`.
  - New `hhmm(tsMs)` helper renders UTC zero-padded HH:MM via `Date#toISOString().slice(11,16)`.
  - `ageMin` derived from `lastKnown.tsMs` (preferred) or `lastSeenMs` (fallback).
  - No em-dash anywhere; uses existing `fmtNum` for RH rounding.

## Replay of 2026-05-20 outage scenario

Before this plan: 11 "co2 sensor offline" Signal messages over 10h47m; no chamber-dark framing.
After this plan: ONE pi-FIRING transition at outage_start + piOfflineMin (default 10 min), single Signal message reading `FC-1 offline ?? no telemetry 10m. chamber uncontrolled. last RH 94% @ 13:04.`; all per-sensor watchdogs suppressed until fc1 publishes again (D-07). Validated by the per-sensor-suppression and recovery-clears-suppression tests in `state.test.js`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] fmtNum test fixture used a JS-float-quirky value**

- **Found during:** Task 2 verification
- **Issue:** Plan acceptance example said `94.05 -> '94.1'`. In actual Node `(94.05).toFixed(1) === '94.0'` because 94.05 stores as 94.049999…, so `fmtNum(94.05)` returns `'94'` (strip-trailing-.0 path). The plan's example case was unreachable.
- **Fix:** Retargeted Test 4 to `94.15` which unambiguously rounds to `'94.2'` via `toFixed(1)`. Same code path, valid fixture. Test 4 also retains the `94.0 -> '94'` case which works as-plan-specified.
- **Files modified:** `src/agents/alerter/test/message.test.js`
- **Commit:** `aeee31a` (bundled with Task 2 implementation since the fix was identifying that the existing-but-untested fmtNum behavior matched the plan's *intent*, not its literal example)

### Authentication gates

None.

### Threat surface

No new network endpoints, no new file/data trust boundaries. Pure in-process state and message wording changes.

## Known Stubs

None — every code path is exercised by tests; no hardcoded placeholders flow to the farmer.

## Test results

- Targeted suite (`rules.test.js state.test.js message.test.js bridge-client.test.js`): 114 tests, all passing.
- Full alerter suite: 728 tests total (8 skipped pre-existing), 720 passing, 0 failing.

## Acceptance criteria

All criteria from the plan met:

| Criterion | Required | Actual |
|---|---|---|
| `grep -c "fc1LastMsgTs" src/rules.js` | ≥ 2 | 7 |
| `grep -c "fc1LastMsgTs" src/bridge-client.js` | ≥ 3 | 4 |
| `grep -c "fc1LastMsgTs" src/state.js` | ≥ 3 | 7 |
| `grep -c "FC-1 offline" src/message.js` | ≥ 1 | 2 |
| `grep -c "chamber uncontrolled" src/message.js` | ≥ 1 | 3 |
| `grep -c "no recent samples" src/message.js` | ≥ 1 | 1 |
| em-dash in message.js | none | none |
| `grep -c "perType.pi.state" src/state.js` | ≥ 4 | 5 |
| `npm test` exit code | 0 | 0 |
| `ALERT_CHAMBER_DARK` env vars | none | none |
| `isPiOffline` retains ws/ros branches | yes | yes (7 references) |

## Downstream

Plan 46-03 (atomic rebuild of bridge + alerter on elder-plops) consumes this work. Until that ships:
- The alerter container running on prod has the OLD behavior (single CO2-offline per outage).
- This plan's changes are dormant in the worktree until the deploy command in 46-03 runs.

## Self-Check: PASSED

- `[ -f src/agents/alerter/src/rules.js ]` — FOUND
- `[ -f src/agents/alerter/src/bridge-client.js ]` — FOUND
- `[ -f src/agents/alerter/src/state.js ]` — FOUND
- `[ -f src/agents/alerter/src/message.js ]` — FOUND
- Commit `1e78cf1` — FOUND
- Commit `aeee31a` — FOUND
- No files outside `src/agents/alerter/` modified — VERIFIED via `git diff --name-only ae672b7..HEAD`
