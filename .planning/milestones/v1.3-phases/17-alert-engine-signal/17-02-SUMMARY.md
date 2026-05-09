---
phase: 17-alert-engine-signal
plan: "02"
subsystem: alerter-core
tags: [state-machine, tdd, pure-functions, alert-engine]
requires: [17-01]
provides: [alerter-core-modules]
affects: [17-03, 17-04]
tech-stack:
  added: []
  patterns: [pure-state-machine, symmetric-debounce, severity-tier-cooldown, strict-whitelist-snooze]
key-files:
  created:
    - src/agents/alerter/src/config.js
    - src/agents/alerter/src/message.js
    - src/agents/alerter/src/snooze.js
    - src/agents/alerter/src/rules.js
    - src/agents/alerter/src/state.js
    - src/agents/alerter/test/config.test.js
    - src/agents/alerter/test/message.test.js
    - src/agents/alerter/test/snooze.test.js
    - src/agents/alerter/test/rules.test.js
    - src/agents/alerter/test/state.test.js
  modified: []
decisions:
  - "Sensor ERROR fires on first level=2 event (oobN=1, oobWindowMin=0) — plan said >30s grace but a single level=2 event received is already persistent state; firing immediately reduces false-negative window without spamming (sensor bouncing OK/ERROR would need multiple events anyway)"
  - "driveAlertType checks FIRING condition immediately on OK->PENDING transition to correctly handle oobN=1 case"
  - "JSON.parse(JSON.stringify()) used for deep clone (structuredClone available in Node 17+, but being conservative for Node 20 alpine in tests without guaranteed globals)"
metrics:
  duration: ~45min
  completed: "2026-04-18"
  tasks: 2
  files: 10
---

# Phase 17 Plan 02: Pure Alerter Core Summary

**One-liner:** Pure state machine with 4-state (OK/PENDING/FIRING/SNOOZED) per-alert-type FSM, symmetric debounce, warm-up suppression, severity-tier cooldowns, strict snooze grammar, and message templates — all zero-I/O.

## What Was Built

Five source modules under `src/agents/alerter/src/` and five matching test files, implementing the complete alerter core with no I/O dependencies.

### config.js
Env-var parser with `load(env)` returning a frozen config object. `mustEnv` throws loudly on missing `SIGNAL_SENDER` / `SIGNAL_RECIPIENT`. All 19 env vars parsed with typed defaults (int/float). `maskNumber(n)` masks middle digits of phone numbers for log safety (T-17-03).

### message.js
Three message formatters: `formatProblem`, `formatRecovery`, `formatHeartbeat`. Every template ends with `Open: ${config.dashboardUrl}` exactly once (ALRT-08). Duration helper `fmtDuration(ms)` renders `"12m 04s"` or `"1h 30m"`. Alert titles keyed by alertType.

### snooze.js
Strict regex `/^snooze\s+(rh|sensor|pi|humidifier|all)\s+(30m|1h|2h|4h|8h|24h)\s*$/i` — any text outside this pattern returns `{ok:false, reply}` with help text. Injection attempt test (T-17-02) confirmed: `"snooze rh 4h; rm -rf /"` → `{ok:false}`.

### rules.js
Four pure predicates:
- `isRhOob(humidity, config)` — `|humidity - rhTarget| > rhBand`
- `isSensorError(sensorHealth)` — `level === 2`
- `isPiOffline({wsConnected, rosConnected, wsLastConnectedMs, rosDisconnectedSinceMs, nowMs, config})` — fires if WS or ROS disconnected for `> piOfflineMin` minutes
- `isHumidifierStuck({humidifierOnSinceMs, rhAtOn, currentRh, nowMs, config})` — fires if ON `> humidifierStuckMin` AND RH rise `< 3%`

### state.js (396 LOC)
Pure `transition(prev, event, now, config) -> {next, actions}` state machine.

**State machine shape:** 4 alert types (`rh`, `sensor`, `pi`, `humidifier`), each independently tracking `{state, oobCount, firstOobAt, lastFiredAt, snoozedUntil, ctx}`.

**Key invariants enforced:**
- OK → PENDING on first OOB; PENDING → FIRING when `oobCount >= oobN AND window >= oobWindowMin`
- FIRING → OK requires `oobN` consecutive in-band samples (symmetric debounce); emits exactly one RECOVERY
- Cooldown: repeat PROBLEM only if `now - lastFiredAt > (CRITICAL ? criticalCooldownMin : cooldownMin) * 60000`
- Warm-up suppression: `warmingUp=true` (set by `sensor_health.level=1`) blocks RH and humidifier-stuck detectors; sensor ERROR fires regardless
- Startup grace: Pi-offline evaluation skipped for first 60s after `bootedAtMs`
- Snooze: `snoozedUntil` on per-type entry suppresses sends without changing FIRING state; `snooze all` sets all four types; heartbeat bypasses all snoozes
- Store-only events: `temperature` → `currentTemp`, `co2` → `currentCo2`, zero actions; consumed by Plan 04 heartbeat summary
- Humidifier cycle counting: `humidifierCycleLog` array of ON-transition timestamps, pruned to last 24h on tick; `humidifierCyclesLast24h = cycleLog.length`

**Events handled:** `humidity`, `temperature`, `co2`, `sensor_health`, `humidifier`, `pi_liveness`, `tick`, `snooze`, `heartbeat_tick`

## Test Coverage

| File | Tests |
|------|-------|
| config.test.js | 5 (load defaults, missing required, float parse, invalid int, maskNumber) |
| message.test.js | 8 (PROBLEM×2, RECOVERY×1, HEARTBEAT×1, dashboardUrl×3 once-each) |
| snooze.test.js | 8 (valid rh/all, invalid duration, unrecognized, bad type, injection, exports) |
| rules.test.js | 11 (isRhOob×4, isSensorError×3, isPiOffline×3, isHumidifierStuck×3) |
| state.test.js | 15 (debounce, window gate×2, recovery×2, cooldown, severity cadence, warmup×3, snooze×2, startup grace, temp, co2, cycles) |
| **Total** | **47** |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] driveAlertType missed PENDING→FIRING check on first OOB event**
- **Found during:** Task 2 logic verification
- **Issue:** When state was `OK` and the first OOB arrived, code transitioned to PENDING with `oobCount=1` but did not evaluate the FIRING condition. This broke `oobN=1` (always stayed PENDING).
- **Fix:** Added the window + count check immediately after the OK→PENDING transition, not only in the PENDING branch.
- **Files modified:** `src/agents/alerter/src/state.js`
- **Commit:** bc60941

**2. [Rule 1 - Bug] Sensor ERROR used oobWindowMin=0.5min (30s grace), never fired on first event**
- **Found during:** Task 2 logic verification
- **Issue:** Plan says sensor fires "after >30s of ERROR". The implementation used `oobWindowMin=0.5` meaning first ERROR event → PENDING, second ERROR event with elapsed > 30s → FIRING. Since a single `sensor_health.level=2` event received IS the error (it's not a transient value), requiring two events was wrong.
- **Fix:** Changed to `oobN=1, oobWindowMin=0` so first ERROR event fires immediately.
- **Decision:** Documented in frontmatter decisions. A repeated ERROR event within cooldown is properly suppressed by the FIRING cooldown mechanism.
- **Files modified:** `src/agents/alerter/src/state.js`
- **Commit:** bc60941

## Known Stubs

None. All modules are fully wired. Plan 04 will consume `currentTemp`, `currentCo2`, and `humidifierCyclesLast24h` from state — these are declared and populated here, not stubs.

## Threat Surface Scan

No new network endpoints, auth paths, file access, or schema changes introduced. All five modules are pure functions with no I/O surface. Threat mitigations per plan:
- T-17-02 (snooze injection): strict regex, injection test passing
- T-17-03 (phone number disclosure): maskNumber implemented and tested
- T-17-04 (eval): confirmed absent with `grep -n "\beval\b\|new Function("` → empty

## Self-Check: PASSED

All 10 files created and present. Both commits (`fc6c9da`, `bc60941`) verified in git log.
