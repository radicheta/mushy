---
phase: 17-alert-engine-signal
plan: "04"
subsystem: alerter-wire-up
tags: [integration, scheduler, receive-loop, wire-up, tdd]
requires:
  - plan: 17-02
    provides: pure core state machine (config, state, rules, message, snooze)
  - plan: 17-03
    provides: I/O adapters (signal.js, bridge-client.js)
provides:
  - src/agents/alerter/src/heartbeat.js — daily heartbeat scheduler (TZ-aware, fires once per local day)
  - src/agents/alerter/src/receive-loop.js — polling receive loop with sender whitelist and snooze dispatch
  - src/agents/alerter/src/index.js — entrypoint wiring all modules; createAlerter test seam + main() crash handlers
  - test/heartbeat.test.js — 5 unit tests
  - test/receive-loop.test.js — 5 unit tests
  - test/integration.test.js — 5 end-to-end tests against in-process fakes
affects: [17-05]
tech-stack:
  added: []
  patterns:
    - "Intl.DateTimeFormat en-CA for TZ-aware YYYY-MM-DD day key + hour extraction (DST-safe)"
    - "lastFiredDay string guard prevents double-fire on same local calendar day"
    - "Sender whitelist Set before parseSnoozeCommand (T-17-02)"
    - "receive-loop never dies silently: catch logs warn + continues (Pitfall 4)"
    - "createAlerter test seam vs main() crash handler separation"
    - "bypassCap:true on heartbeat send skips hourly cap"
    - "waitFor() polling helper for async integration assertions"
key-files:
  created:
    - src/agents/alerter/src/heartbeat.js
    - src/agents/alerter/src/receive-loop.js
    - src/agents/alerter/src/index.js
    - src/agents/alerter/test/heartbeat.test.js
    - src/agents/alerter/test/receive-loop.test.js
    - src/agents/alerter/test/integration.test.js
  modified: []
decisions:
  - "state.js consumed per Plan 02 contract (currentTemp/currentCo2/humidifierCyclesLast24h) without modification — no state.js changes were necessary"
  - "integration test uses clock() injection (not fake timers) for snooze/heartbeat — avoids jest fake timer incompatibility with async WS/HTTP servers"
  - "snooze test advances clock +30min (within 1h snooze window) rather than +2h to keep snooze active while still bypassing cooldown=0"
  - "unhandled_rejection test verifies handler registration via source inspection + listener count, not by actually triggering rejection in jest worker (would poison the test process)"
metrics:
  duration: ~35min
  completed: "2026-04-18"
  tasks: 2
  files: 6
---

# Phase 17 Plan 04: Wire-Up + Integration Test Summary

**One-liner:** index.js wires all six modules (config/state/signal/bridge-client/heartbeat/receive-loop) into a single createAlerter factory with crash handlers in main(); heartbeat scheduler and receive-loop are independently tested; integration test drives PROBLEM→RECOVERY→HEARTBEAT→SNOOZE lifecycle against in-process fakes with 84 total passing tests.

## Performance

- **Duration:** ~35 min
- **Started:** 2026-04-18
- **Completed:** 2026-04-18
- **Tasks:** 2 of 2 complete
- **Files created:** 6

## Accomplishments

### heartbeat.js (74 LOC)

Daily heartbeat scheduler that fires exactly once per local-TZ calendar day when `clock()` reaches or exceeds `config.heartbeatHour`. Uses `Intl.DateTimeFormat('en-CA', { timeZone })` to extract both the local day string (`YYYY-MM-DD`) and the local hour — DST-safe since Intl does the offset math. Stores `lastFiredDay` as a string; resets to `null` on `stop()`. Errors in tick are caught and logged, never thrown.

### receive-loop.js (81 LOC)

Polls `signalClient.receive({ timeoutSec: 1 })` on a `setInterval` driven by `config.receivePollSec`. Applies a sender whitelist (T-17-02) before any parsing: `Set([config.signalSender, config.signalRecipient])`. Valid snooze text → `dispatch({type:'snooze', alertType, untilMs})`. Invalid text → `signalClient.send(parsed.reply)` (help text, caught on failure). All tick errors are caught and logged as warnings — the loop never dies silently (Pitfall 4).

### index.js (163 LOC)

Single `createAlerter({env, clock, logger})` factory that:
1. Loads config via `config.load(env)`
2. Creates `signalClient`, initializes `state = stateLib.initialState(clock())`
3. Defines `applyEvent(event)` — calls `stateLib.transition(state, event, clock(), config)`, replaces state, fires actions through `signalClient.send()` (with `bypassCap:true` for heartbeat actions)
4. Creates `bridge` with `onMessage` routing `humidity/temperature/co2/humidifier/sensor_health` WS shapes into `applyEvent`, and `onLiveness` routing `pi_liveness`
5. Creates `heartbeat` scheduler using `getSummary()` which reads `state.currentTemp`, `state.currentCo2`, `state.humidifierCyclesLast24h` (Plan 02 declared contract — no state.js modifications)
6. Creates `receiveLoop` and a 30s `tick` timer
7. Returns `{ dispatch, close, _state }` with `close()` tearing down all timers and the bridge

`main()` — called only when `require.main === module` — creates the alerter and registers `unhandledRejection` and `uncaughtException` handlers that log, close the alerter, and `process.exit(1)`.

## Plan 02 Contract Consumption

state.js was **not modified**. The following fields declared by Plan 02 are consumed in index.js's `getSummary()`:

| Field | Declared in state.js | Consumed in index.js |
|-------|---------------------|---------------------|
| `currentTemp` | Line 38 | Line 98 |
| `currentCo2` | Line 39 | Line 99 |
| `humidifierCyclesLast24h` | Line 40 | Line 101 |

## Test Coverage

| File | Tests | What they cover |
|------|-------|-----------------|
| heartbeat.test.js | 5 | First tick dispatch, no-double-fire same day, before-hour suppression, next-day rollover, getSummary forwarding |
| receive-loop.test.js | 5 | Valid snooze dispatch, invalid → help reply, unknown sender drop, error continuity, stop() halts |
| integration.test.js | 5 | PROBLEM+RECOVERY, warmup suppression, snooze mute, heartbeat cap bypass, crash handler verification |
| **Plan 04 total** | **15** | |
| **Cumulative (Plans 01-04)** | **84** | |

## LOC Counts

| File | LOC |
|------|-----|
| src/heartbeat.js | 74 |
| src/receive-loop.js | 81 |
| src/index.js | 163 |
| test/heartbeat.test.js | 202 |
| test/receive-loop.test.js | 183 |
| test/integration.test.js | 327 |

## Task Commits

1. **Task 1: heartbeat.js + receive-loop.js + unit tests** — `c8e6843`
2. **Task 2: index.js + integration.test.js** — `cdbb53a`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Integration test recovery assertion used wrong message substring**
- **Found during:** Task 2, first integration test run
- **Issue:** Test expected `/RH back/` but `formatRecovery` produces `"RH out of band back"` (from `ALERT_TITLES.rh + ' back'` in message.js)
- **Fix:** Updated test assertion to `/RH out of band back/` to match the actual template
- **Files modified:** `test/integration.test.js`
- **Commit:** `cdbb53a`

**2. [Rule 1 - Bug] Snooze test clock advanced +2h — expired the 1h snooze window**
- **Found during:** Task 2, snooze test failure
- **Issue:** Snooze envelope was `snooze rh 1h` → `untilMs = nowMs + 3600000`. Clock advanced `+2h` → `clock() > untilMs` → snooze expired → second PROBLEM fired
- **Fix:** Changed clock advance to `+30min` — still past `cooldownMin=0` threshold but within the 1h snooze window
- **Files modified:** `test/integration.test.js`
- **Commit:** `cdbb53a`

## Known Stubs

None. All wiring is live. Plan 05 will containerize and deploy to elder-plops with a real Signal registration.

## Threat Surface Scan

No new network endpoints or auth paths introduced. index.js is a consumer of bridge WS (existing surface) and signal-cli HTTP (existing surface). All threat mitigations from Plan 04 threat model confirmed present:

- **T-17-02** (sender whitelist): `allowedSenders` Set in receive-loop.js, checked before `parseSnoozeCommand` — test C in receive-loop.test.js verifies drop
- **T-17-03** (phone number masking): `maskNumber()` used on all boot log lines referencing sender/recipient
- **T-17-04** (crash handlers): `unhandledRejection` + `uncaughtException` registered in `main()`, call `alerter.close()` then `process.exit(1)` — verified by integration test 5
- **T-17-05** (DoS via WS flood): `applyEvent` is pure (<1ms per transition); `maxSendsPerHour` cap prevents Signal spam even under message flood

## Self-Check: PASSED

Files exist:
- src/agents/alerter/src/heartbeat.js: FOUND
- src/agents/alerter/src/receive-loop.js: FOUND
- src/agents/alerter/src/index.js: FOUND
- src/agents/alerter/test/heartbeat.test.js: FOUND
- src/agents/alerter/test/receive-loop.test.js: FOUND
- src/agents/alerter/test/integration.test.js: FOUND

Commits verified:
- c8e6843: FOUND (heartbeat.js + receive-loop.js + unit tests)
- cdbb53a: FOUND (index.js + integration.test.js)

All 84 tests pass (11 suites).
