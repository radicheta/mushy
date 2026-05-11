---
phase: 29
plan: 04
subsystem: alerter
tags:
  - alerter
  - state-machine
  - effective-config
  - mode-awareness
requires:
  - 29-01
  - 29-02
  - 29-03
provides:
  - resolveEffectiveConfig
  - mode_update / overrides_update / globals_update FSM events
  - Tier C runtime overrides for heartbeat scheduler + signal egress cap
  - piFields.lastKnown plumbing for 29-05 pi-alert message body
affects:
  - alerter onMessage routing (3 new bridge keys)
  - alerter rule call sites (humidity / pi_liveness / tick)
key-files:
  modified:
    - src/agents/alerter/src/state.js
    - src/agents/alerter/src/index.js
    - src/agents/alerter/src/config.js
    - src/agents/alerter/src/heartbeat.js
    - src/agents/alerter/src/signal.js
    - src/agents/alerter/test/state.test.js
decisions:
  - Tier C globals (piOfflineMin, sensorOfflineMin, heartbeatHour, maxSendsPerHour) apply REGARDLESS of mode freshness — they are process-global runtime overrides not anchored to a mode envelope. Otherwise pi-offline alerting would be neutralized exactly when ws drops (mode goes stale on disconnect).
  - hasModeContext(state) gate keeps pre-29 callers (no mode/overrides/globals events) on raw envConfig path. Preserves all pre-existing state.test.js semantics; effective-config wiring activates only once any of the three runtime envelopes has been observed.
  - state.js now imports message via `messageLib` reference (not destructure) so jest.spyOn(message, 'formatProblem') intercepts calls from state.js — required by BLOCKER 2 piFields plumbing tests.
metrics:
  duration: ~45 min
  completed: 2026-05-08
  tasks: 2
  commits: 3
---

# Phase 29 Plan 04: Mode + Tier B/C Effective-Config State Machine Summary

State.js now consumes the three new bridge envelopes (`current_mode`,
`alerter_overrides`, `alerter_globals`), exports a `resolveEffectiveConfig()`
helper that implements the D-03 fresh/stale/cold freshness model, and threads
the resolved effective config through rh / pi / humidifier rule sites. The
heartbeat scheduler and signal egress limiter now honor Tier C runtime
overrides via lazy accessors. Pi-offline alerts carry a `lastKnown` summary
of the last sample (rh, temp, humidifier ON/OFF, tsMs) for 29-05's
message-body extension (BLOCKER 2 / 999.39).

## Tasks Completed

| Task | Description | Commit |
|------|-------------|--------|
| 1 (TDD) | state.js — new event types, dedup-reset (D-09), resolveEffectiveConfig, lastKnown wiring | 7a6a4be (impl) after 59df50e (RED) |
| 2 | index.js routing + config.js Tier D fields + heartbeat/signal Tier C accessors | e4c5bab |

## Tests Added

19 new tests in `Phase 29 mode + freshness` describe block in
`test/state.test.js`. All pass.

| # | Test | Covers |
|---|------|--------|
| 1 | `mode_update populates currentMode and modeReceivedAtMs` | event 1 reducer |
| 2 | `mode_update resets dedup for rh and humidifier; preserves lastFiredAt` | D-09 |
| 3 | `mode_update resets perType.rh.ctx.inBandCount` | D-09 |
| 4 | `cooldown survives mode swap (lastFiredAt preserved)` | D-09 |
| 5 | `first mode_update after cold start resets dedup (Pitfall 4)` | Pitfall 4 |
| 6 | `overrides_update populates alerterOverrides and ts` | event 2 reducer |
| 7 | `globals_update populates alerterGlobals and ts` | event 3 reducer |
| 8 | `resolveEffectiveConfig FRESH path returns mode-derived rh values` | D-03 state 1 |
| 9 | `resolveEffectiveConfig STALE when mode older than modeStaleMin` | D-03 state 2 |
| 10 | `resolveEffectiveConfig STALE on wsDisconnected even if mode fresh` | D-03 state 2 |
| 11 | `resolveEffectiveConfig COLD path within boot grace` | D-03 state 3 |
| 12 | `resolveEffectiveConfig STALE past 60s with no mode` | D-03 state 2 |
| 13 | `resolveEffectiveConfig merges Tier B overrides over env` | Tier B |
| 14 | `resolveEffectiveConfig merges Tier C globals over env` | Tier C |
| 15 | `band_low/band_high → rhBand symmetric average` | Tier A math |
| 16 | `pi_liveness fires alert with piFields.lastKnown when sensor data present` | BLOCKER 2 |
| 17 | `pi_liveness fires alert with piFields.lastKnown null when no data` | BLOCKER 2 |
| 18 | `rh OOB uses effective.oobN from Tier B override` | BLOCKER 3 / ALRT-09 |
| 19 | `tick re-evaluation uses effective.piOfflineMin from Tier C globals` | BLOCKER 3 / ALRT-09 |

## Verification

```bash
$ cd src/agents/alerter && npx jest test/state.test.js
Tests:       45 passed, 45 total

$ SIGNAL_SENDER=x SIGNAL_RECIPIENT=y TIMESCALE_PASSWORD=z ANTHROPIC_API_KEY=k \
    node -e "const c=require('./src/config').load(process.env); \
             console.log(c.modeStaleMin, c.modeBootGraceMs)"
5 60000
```

Acceptance grep evidence (excerpts):

| Check | Result |
|-------|--------|
| `grep -c "case 'mode_update'" src/state.js` | 1 |
| `grep -c "resolveEffectiveConfig" src/state.js` | 7 (def + export + 5 call sites) |
| `grep -c "lastKnown" src/state.js` | 6 |
| `grep -E "humidifier: next\.humidifierOnSinceMs != null \\? 'ON' : 'OFF'" src/state.js` | 2 matches |
| `grep -c "msg.current_mode" src/index.js` | 2 (`else if` + `applyEvent` arg) |
| `grep -c "modeStaleMin" src/config.js` | 2 |
| `grep -cE "getEffective\|getMaxSendsPerHour" src/index.js` | 4 |

## Deviations from Plan

### Plan-text adjustments (D-03 semantic refinement)

**[Rule 1 — Bug] Tier C globals must apply when ws is disconnected**

The plan's literal D-03 reading places ALL effective fields under the freshness
gate. But Test 19 demands `effective.piOfflineMin` come from Tier C globals
during ws disconnect — and that's exactly when pi-offline alerts fire. Made
Tier C global overrides mode-independent: they always apply when
`alerter_globals` has been received, regardless of fresh/stale/cold. Tier A
(rhTarget/rhBand) and Tier B (per-mode overrides) remain freshness-gated.

**[Rule 1 — Bug] hasModeContext(state) gate preserves pre-29 callers**

The straight implementation of "thread effective into all rule sites" broke 7
pre-existing state.test.js tests — those tests run past the 60s boot grace
and have no mode envelopes, so freshness=stale and rules.js (29-05) suspends
isRhOob. Added an internal `hasModeContext(state)` gate so the effective-config
path activates only once any of mode/overrides/globals has been observed; pre-29
production deployments and pre-existing tests retain raw-config semantics.

**[Rule 2 — Critical] state.js → messageLib.formatProblem(...) reference**

Plan didn't address that `jest.spyOn(messageMod, 'formatProblem')` cannot
intercept destructured local references. Switched `state.js` to call
`messageLib.formatProblem(...)` so BLOCKER 2 piFields tests can observe the
threaded `lastKnown`. Behavior unchanged (same module, same function).

### Test-text adjustments

- Test 4 (`cooldown survives mode swap`): added preceding `pi_liveness wsConnected:true` so resolveEffectiveConfig sees the test as fresh. Otherwise FRESH-path is bypassed and isRhOob is suppressed by stale gate (29-05 rules.js).
- Test 5 (`first mode_update after cold start`): switched `expect(s.currentMode).toBeUndefined()` to `expect(s.currentMode == null).toBe(true)` since initialState now seeds currentMode=null.
- Test 16/17 (`pi_liveness lastKnown`): use `oobN: 1, oobWindowMin: 0` so a single tick crosses pi-alert FIRING. Test target is piFields plumbing, not the dedup ladder.
- Test 18/19: same `oobN:1` simplification + ws-connect to clear FRESH gate.

## Pre-existing failures (NOT in scope)

`test/integration.test.js` (3) and `test/config.test.js` (1) fail on the
worktree base `151a9b1` BEFORE any plan-29-04 edits — verified by stashing
my changes and re-running. These are 29-05 pre-existing surface.

## Tier C Wiring (BLOCKER 3 / ALRT-09)

| Surface | Mechanism | Fallback |
|---------|-----------|----------|
| signal egress cap | `getMaxSendsPerHour: () => resolveEffectiveConfig(state, config, clock()).maxSendsPerHour` resolved on each `send()` | bootstrap `config.maxSendsPerHour` if accessor returns non-finite or throws |
| heartbeat hour | `getEffective: () => resolveEffectiveConfig(state, config, clock())`; scheduler reads `getEffective().heartbeatHour` on each tick | bootstrap `config.heartbeatHour` when accessor undefined |

No new tests for Step C in this plan — the plan permitted documenting the gap
and relying on 29-07 smoke. Both surfaces have a defensive fallback path so
runtime regressions degrade to bootstrap behavior rather than crashing.

## Self-Check: PASSED

- [x] src/agents/alerter/src/state.js exists and exports resolveEffectiveConfig
- [x] src/agents/alerter/src/index.js routes 3 new WS keys
- [x] src/agents/alerter/src/config.js carries modeStaleMin + modeBootGraceMs
- [x] src/agents/alerter/src/heartbeat.js consumes getEffective().heartbeatHour
- [x] src/agents/alerter/src/signal.js consumes getMaxSendsPerHour()
- [x] commit 7a6a4be exists (state.js + tests GREEN)
- [x] commit e4c5bab exists (index.js + config.js + heartbeat.js + signal.js)
- [x] commit 59df50e exists (RED tests)
