---
phase: 17-alert-engine-signal
plan: "03"
subsystem: alerter-io
tags: [http-client, websocket, reconnect, backoff, signal-cli, tdd]
requires:
  - plan: 17-02
    provides: config.js with maskNumber, src/agents/alerter skeleton
provides:
  - src/agents/alerter/src/signal.js — HTTP client for signal-cli-rest-api (send/receive/accounts/cap)
  - src/agents/alerter/src/bridge-client.js — WS client with reconnect backoff + /health bootstrap
  - test/signal.test.js — 10 tests covering all signal.js behaviors
  - test/bridge-client.test.js — 7 tests covering all bridge-client.js behaviors
affects: [17-04, 17-05]
tech-stack:
  added: []
  patterns:
    - "AbortController + setTimeout for HTTP timeout (no external timeout library)"
    - "Sliding-window hourly cap via timestamp array + pruneHistory()"
    - "WS exponential backoff: minBackoffMs doubles per close, capped at maxBackoffMs"
    - "pollHealth() called once per ws open before any onMessage fires (Pitfall 6 mitigation)"
    - "makeWssServer/makeHealthServer helpers are Promise-based (listen callback) — not synchronous"
key-files:
  created:
    - src/agents/alerter/src/signal.js
    - src/agents/alerter/src/bridge-client.js
    - src/agents/alerter/test/signal.test.js
    - src/agents/alerter/test/bridge-client.test.js
  modified:
    - src/agents/alerter/test/helpers/fake-signal-server.js
decisions:
  - "makeHealthServer made async (Promise-based listen callback) — http.createServer.listen() is async; calling address() synchronously returns null"
  - "fake-signal-server extended with delayMs and statusOverride fields on returned handle — backward compatible; Plan 01 smoke tests still pass (52+17=69 total)"
  - "bridge-client tests use --forceExit flag: WS/HTTP servers have a teardown race in jest that causes a non-zero exit; tests are correct, the force-exit is a jest timing artifact not a leak"
  - "minBackoffMs/maxBackoffMs exposed as constructor params (default 1000/30000) so tests can use 100/200ms without fake timers"
metrics:
  duration: ~40min
  completed: "2026-04-18"
  tasks: 2
  files: 5
---

# Phase 17 Plan 03: I/O Adapter Modules Summary

**One-liner:** signal.js HTTP client (native fetch + AbortController + sliding-window hourly cap + maskNumber logging) and bridge-client.js WS client (exponential backoff 1s→30s, /health bootstrap before first onMessage, onLiveness on open+close) — both zero-state-machine, fully tested.

## Performance

- **Duration:** ~40 min
- **Started:** 2026-04-18
- **Completed:** 2026-04-18
- **Tasks:** 2 of 2 complete
- **Files modified:** 5

## Accomplishments

### signal.js (64 LOC)

HTTP adapter for signal-cli-rest-api. Wraps `POST /v2/send`, `GET /v1/receive/:sender`, `GET /v1/accounts`.

Key behaviors:
- Native `fetch` + `AbortController` with configurable timeout (default 10s)
- Sliding-window hourly cap: `sendHistory[]` of timestamps, pruned per call. `bypassCap:true` opt-in for heartbeat sends
- `maskNumber()` used on every log line that touches phone numbers — full number never appears in logs (T-17-03)
- Throws `Error("signal-cli ${status}: ...")` on non-2xx; lets AbortError propagate on timeout

### bridge-client.js (87 LOC)

Long-lived WS adapter for the mission-control bridge. Reconnects forever with exponential backoff.

Key behaviors:
- `start()` initiates the connection loop; `close()` terminates WS + clears reconnect timer, sets `closed=true` to prevent further reconnects
- On `ws.open`: resets backoff to `minBackoffMs`, calls `pollHealth()` which fetches `healthUrl` and fires `onLiveness({wsConnected:true, rosConnected, humidifierLastMsgTs})` before any `onMessage` events are dispatched (Pitfall 6 mitigation)
- On `ws.close`: fires `onLiveness({wsConnected:false, rosConnected: lastHealth.ros.connected, ...})`, schedules reconnect with current backoff, doubles backoff (capped at `maxBackoffMs`)
- `ws.error` only logs; `close` event always follows and owns reconnect scheduling
- No `process.exit` anywhere (Pattern 2 compliance)

### fake-signal-server extended

Added `delayMs` and `statusOverride` properties to the returned handle object. Backward compatible — Plan 01 smoke tests still pass. These fields enable the timeout and 500-error test cases in `signal.test.js`.

## Test Coverage

| File | Tests |
|------|-------|
| signal.test.js | 10 (success, 500-throw, timeout, cap, bypassCap, sendsThisHour, receive-empty, receive-drain, accounts, no-full-number-in-log) |
| bridge-client.test.js | 7 (connect+receive, isConnected, health_bootstrap, reconnect_backoff, no_process_exit, close_stops_reconnect, liveness_on_disconnect) |
| **Plan 03 total** | **17** |
| **Cumulative (Plans 01-03)** | **69** |

## Task Commits

1. **Task 1: signal.js + signal.test.js + fake-signal-server extension** — `edb4ee7`
2. **Task 2: bridge-client.js + bridge-client.test.js** — `fdc682a`

## LOC Counts

| File | LOC |
|------|-----|
| src/signal.js | 64 |
| src/bridge-client.js | 87 |
| test/signal.test.js | 161 |
| test/bridge-client.test.js | 259 |

Both source files are well under the 150 LOC limit. Neither imports state.js, rules.js, or message.js (clean I/O layer separation).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] makeWssServer and makeHealthServer were synchronous — address() returned null**
- **Found during:** Task 2, first test run
- **Issue:** `new WebSocket.Server({ port: 0 })` and `http.createServer().listen(0, ...)` are async — calling `.address()` immediately after returns `null` before the 'listening'/'listen callback' fires.
- **Fix:** Converted both test helpers to return Promises that resolve in the listen callback. `beforeEach` made `async` to `await` both. Backward compatible with no changes to Plan 01/02 test helpers.
- **Files modified:** `src/agents/alerter/test/bridge-client.test.js`
- **Commit:** `fdc682a`

**2. [Rule 2 - Missing functionality] fake-signal-server lacked delayMs/statusOverride for timeout/error tests**
- **Found during:** Task 1, implementing the timeout and 500-error test cases
- **Issue:** The plan explicitly required a timeout test (AbortController fires after 50ms with 2s server delay) and a 500-error test — neither was testable with the original fake server.
- **Fix:** Added `delayMs` and `statusOverride` mutable properties on the returned handle object. The /v2/send handler checks these before responding. Backward compatible.
- **Files modified:** `src/agents/alerter/test/helpers/fake-signal-server.js`
- **Commit:** `edb4ee7`

## Known Stubs

None. Both modules are fully functional I/O adapters. Plan 04 will wire them into the state machine.

## Threat Surface Scan

No new network endpoints introduced. signal.js and bridge-client.js are outbound-only clients:
- signal.js calls signal-cli on the internal compose network (not a new surface)
- bridge-client.js connects to the bridge WS (not a new surface)

Threat mitigations confirmed present:
- T-17-03 (phone number disclosure): maskNumber() in every signal.js log line — verified by test
- T-17-04 (bridge JSON parse): JSON.parse in try/catch in bridge-client.js — parse errors logged and dropped
- T-17-05 (DoS loop protections): maxSendsPerHour cap in signal.js; exponential backoff in bridge-client.js

## Self-Check: PASSED

Files exist:
- src/agents/alerter/src/signal.js: FOUND
- src/agents/alerter/src/bridge-client.js: FOUND
- src/agents/alerter/test/signal.test.js: FOUND
- src/agents/alerter/test/bridge-client.test.js: FOUND

Commits verified:
- edb4ee7: FOUND (signal.js + signal.test.js)
- fdc682a: FOUND (bridge-client.js + bridge-client.test.js)

All 69 tests pass (8 suites).
