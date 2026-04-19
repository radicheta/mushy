---
phase: 17-alert-engine-signal
verified: 2026-04-18T00:00:00Z
status: human_needed
score: 7/8 must-haves verified (ALRT-07 receive-side blocked by signal-cli-rest-api limitation)
overrides_applied: 0
human_verification:
  - test: "Confirm snooze receive-side is unblocked (ALRT-07 / ALRT-06 gap)"
    expected: "Farmer sends 'snooze rh 4h' via Signal reply; alerter logs '[receive] snooze rh for 14400000ms'; subsequent OOB injection produces no alert for 4h"
    why_human: "signal-cli-rest-api /v1/receive returns HTTP 400 for linked secondary devices (bbernhard/signal-cli-rest-api:0.200-dev + json-rpc-native mode). The receive-loop.js code is correct and tested against a fake; the failure is at the real signal-cli API layer. Requires either: (a) upgrading/reconfiguring signal-cli-rest-api to a version/mode where /v1/receive works for linked secondary devices, or (b) switching the sender account to a primary registration. Once the API returns envelopes, snooze is fully wired."
gaps:
  - truth: "Snooze receive-side: farmer Signal reply dispatches snooze event into state machine in production"
    status: partial
    reason: "signal-cli-rest-api /v1/receive returns HTTP 400 for linked secondary device accounts. receive-loop.js is correct and unit-tested (5/5 tests pass against fake). Grammar (parseSnoozeCommand) fully implemented (8/8 tests). Wiring in index.js is complete. Only the real API endpoint is non-functional — it is a known limitation of the signal-cli-rest-api version, not a code defect."
    artifacts:
      - path: src/agents/alerter/src/receive-loop.js
        issue: "Code is correct. API layer (signal-cli-rest-api /v1/receive) returns 400 in production for linked secondary device mode. The loop catches the error and continues (Pitfall 4 compliant) but no envelopes are ever processed."
      - path: src/agents/alerter/src/signal.js
        issue: "receive() correctly calls /v1/receive/{sender}?timeout=1 and throws on non-2xx. Non-2xx from signal-cli causes the loop to log a warning each poll cycle."
    missing:
      - "Resolve signal-cli-rest-api /v1/receive 400 for linked secondary device — options: primary registration on the alerter number, or upgrade to a signal-cli-rest-api version/mode that supports receive on secondary-linked accounts"
---

# Phase 17: Alert Engine + Signal Verification Report

**Phase Goal:** Deliver PROBLEM/RECOVERY/heartbeat Signal alerts to farmer from fc1 humidity state, with snooze support.
**Verified:** 2026-04-18
**Status:** human_needed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | PROBLEM alert fires when RH is OOB for N consecutive samples | VERIFIED | state.test.js: "OOB debounce" + "window gate" tests pass; integration test end_to_end_rh_problem_and_recovery passes; farmer-attested PROBLEM received on Signal after synthetic OOB injection |
| 2 | RECOVERY alert fires on symmetric debounce back in-band | VERIFIED | state.test.js: "recovery_exactly_once" passes; integration test passes; farmer-attested RECOVERY received on Signal |
| 3 | HEARTBEAT sent daily at configured local-TZ hour | VERIFIED | heartbeat.test.js: 5/5 tests pass (fire once, no double-fire, before-hour suppression, next-day rollover, getSummary forwarding); farmer-attested HEARTBEAT received |
| 4 | Sensor warm-up suppresses RH/humidifier alerts (not sensor ERROR) | VERIFIED | state.test.js: warmup_suppresses_rh, warmup_suppresses_humidifier_stuck, warmup_does_NOT_suppress_sensor_error all pass; integration test warmup_blocks_rh_alert passes |
| 5 | All thresholds/cadences configurable via env vars | VERIFIED | config.test.js: 5/5 tests pass including float parse, int validation, required-var throw; docker-compose.override.yml forwards all ALERT_* vars from .env; .env.example documents all 13 alerter vars with defaults |
| 6 | Snooze grammar parses farmer replies and dispatches into state machine (test layer) | VERIFIED | snooze.test.js: 8/8 pass (valid types/durations, invalid type, invalid duration, injection rejection, fuzzy reply); receive-loop.test.js: 5/5 pass including snooze dispatch and invalid-command reply; integration test snooze_mutes_while_active passes |
| 7 | Snooze receive-side works in production (farmer Signal reply reaches alerter) | FAILED | signal-cli-rest-api /v1/receive returns HTTP 400 for linked secondary device. Snooze grammar, dispatch wiring, and state machine transitions are all correct and tested — only the API bridge is broken. Documented in ground_truth_attestations as known limitation. |
| 8 | Every alert body includes farmer dashboard URL | VERIFIED | message.test.js: Test E asserts dashboardUrl appears exactly once in PROBLEM, RECOVERY, HEARTBEAT outputs; grep confirms `Open: ${config.dashboardUrl}` on last line of all three formatters in message.js |

**Score:** 7/8 truths verified (ALRT-07 receive-side partial due to API limitation)

---

## Required Artifacts

| Artifact | Status | Evidence |
|----------|--------|----------|
| `src/agents/alerter/package.json` | VERIFIED | Exists; declares jest@29.7.0, ws@8.16.0, pg@8.20.0; `"test": "jest"` script present |
| `src/agents/alerter/jest.config.js` | VERIFIED | Exists; node env, testMatch `**/test/**/*.test.js` |
| `src/agents/alerter/Dockerfile` | VERIFIED | Exists; `FROM node:20-alpine`, `npm ci --omit=dev` |
| `src/agents/alerter/src/config.js` | VERIFIED | 57 LOC; exports `load`, `maskNumber`; mustEnv throws on missing required vars |
| `src/agents/alerter/src/rules.js` | VERIFIED | Exports isRhOob, isSensorError, isPiOffline, isHumidifierStuck; 11 tests pass |
| `src/agents/alerter/src/state.js` | VERIFIED | 396 LOC; exports transition, initialState, STATES; all 15 state tests pass; currentTemp/currentCo2/humidifierCyclesLast24h declared |
| `src/agents/alerter/src/message.js` | VERIFIED | Exports formatProblem, formatRecovery, formatHeartbeat; dashboardUrl in all three templates; 8 tests pass |
| `src/agents/alerter/src/snooze.js` | VERIFIED | Strict regex whitelist; exports parseSnoozeCommand, VALID_ALERT_TYPES, VALID_DURATIONS; 8 tests pass including injection rejection |
| `src/agents/alerter/src/signal.js` | VERIFIED | 64 LOC; native fetch + AbortController; sliding-window hourly cap; maskNumber on all log lines; 10 tests pass |
| `src/agents/alerter/src/bridge-client.js` | VERIFIED | 87 LOC; WS exponential backoff 1s→30s; /health bootstrap before onMessage; no process.exit; 7 tests pass |
| `src/agents/alerter/src/heartbeat.js` | VERIFIED | 74 LOC; Intl.DateTimeFormat TZ-aware; lastFiredDay guard; 5 tests pass |
| `src/agents/alerter/src/receive-loop.js` | VERIFIED (code) | 81 LOC; sender whitelist Set; parseSnoozeCommand dispatch; never dies silently; 5 tests pass. Runtime receive blocked by API limitation (see gaps). |
| `src/agents/alerter/src/index.js` | VERIFIED | 163 LOC; wires all 6 modules; createAlerter test seam + main() crash handlers; 5 integration tests pass |
| `docker-compose.override.yml` | VERIFIED | alerter + signal-cli services present; extra_hosts host-gateway; signal-net; named volume signal-cli-data; all ALERT_* vars forwarded |
| `.env.example` | VERIFIED | All 13 alerter env vars documented with defaults; two-places warning for RH target; E.164 placeholder format for phone numbers |
| `src/agents/alerter/README.md` | VERIFIED | Registration runbook (Steps 1-5), deploy commands, snooze grammar table, two-places warning, env-var inventory |

---

## Key Link Verification

| From | To | Via | Status | Evidence |
|------|----|-----|--------|----------|
| index.js | state.js | require('./state') + transition() call in applyEvent | WIRED | Line 12: `const stateLib = require('./state')`, line 45: `stateLib.transition(...)` |
| index.js | signal.js | require('./signal') + signalClient.send() in applyEvent | WIRED | Line 14: `const { createSignalClient } = require('./signal')`, lines 50-57: action dispatch |
| index.js | bridge-client.js | require('./bridge-client') + onMessage → applyEvent | WIRED | Line 15: `const { createBridgeClient } = require('./bridge-client')`, lines 64-83: onMessage routing |
| index.js | heartbeat.js | require('./heartbeat') + dispatch: applyEvent | WIRED | Line 16: `const { createHeartbeatScheduler } = require('./heartbeat')` |
| index.js | receive-loop.js | require('./receive-loop') + dispatch: applyEvent | WIRED | Line 17: `const { createReceiveLoop } = require('./receive-loop')` |
| state.js | rules.js | require('./rules') + predicate calls in transition() | WIRED | Line 3: `const { isRhOob, isSensorError, isPiOffline, isHumidifierStuck } = require('./rules')` |
| state.js | message.js | require('./message') + formatProblem/formatRecovery in actions | WIRED | Line 4: `const { formatProblem, formatRecovery, formatHeartbeat } = require('./message')` |
| receive-loop.js | snooze.js | require('./snooze') + parseSnoozeCommand | WIRED | Line 3: `const { parseSnoozeCommand } = require('./snooze')` |
| signal.js | config.js | require('./config') + maskNumber in log lines | WIRED | Line 3: `const { maskNumber } = require('./config')` |
| alerter (compose) | signal-cli (compose) | signal-net network, SIGNAL_API_URL=http://signal-cli:8080 | WIRED (infra) | docker-compose.override.yml: both services on signal-net |
| alerter (compose) | bridge (host) | extra_hosts host-gateway, BRIDGE_WS_URL=ws://host.docker.internal:8081 | WIRED (infra) | docker-compose.override.yml: extra_hosts + env var; validated by Plan 01 networking probe |

---

## Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| receive-loop.js | envelopes | signalClient.receive() → signal-cli /v1/receive | No (HTTP 400 in production for linked secondary device) | HOLLOW in production; code correct, API layer fails |
| heartbeat.js → getSummary | currentRh, currentTemp, currentCo2 | state.currentRh/Temp/Co2 via applyEvent({type:'humidity/temperature/co2'}) | Yes, when fc1 is connected and sending bridge WS messages | FLOWING (attested: heartbeat showed real RH/Temp/CO2 from production fc1 in Plan 04 summary note) |
| message.js | dashboardUrl | config.dashboardUrl from DASHBOARD_URL env var | Yes | FLOWING |

**Note on heartbeat null fields:** SUMMARY notes that heartbeat shows null for RH/Temp/CO2 when state is empty (no bridge messages yet). In production with live fc1 telemetry these fields populate from state.currentRh/Temp/Co2. This is correct behavior — not a stub.

---

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| All 84 unit/integration tests pass | `cd src/agents/alerter && npm test` | Test Suites: 11 passed, 11 total; Tests: 84 passed, 84 total | PASS |
| config.js fails loudly without required vars | `node -e "require('./src/agents/alerter/src/config.js').load({})"` | Throws: "[config] Required env var SIGNAL_SENDER is missing" | PASS (verified by config.test.js Test B) |
| snooze grammar rejects injection | parseSnoozeCommand('snooze rh 4h; rm -rf /', 0) | {ok:false, reply:"Sorry, didn't get that..."} | PASS (snooze.test.js Test F) |
| Alerter refuses to start without env vars | Container exits immediately (config.js mustEnv throws) | Documented in 17-05-SUMMARY: alerter stopped as expected | PASS (design verified) |

**Note on jest force-exit warning:** One worker process fails to exit gracefully after test suite. This is a jest teardown race with in-process WS/HTTP servers. Documented and accepted in Plan 03 decisions (`--forceExit` flag on bridge-client tests). Not a test failure — 84/84 pass. Does not affect correctness.

---

## Requirements Coverage

| Requirement | Plans | Description | Status | Evidence |
|-------------|-------|-------------|--------|----------|
| ALRT-01 | 17-01, 17-03 | signal-cli-rest-api Docker service on elder-plops with Signal registered | SATISFIED | signal-cli service in docker-compose.override.yml; farmer-attested test message received on Signal (+59892893012) from alerter registered as secondary on +59891840205 |
| ALRT-02 | 17-02, 17-04 | Four alert types fire PROBLEM+RECOVERY: Pi offline, sensor ERROR, RH OOB, humidifier stuck | SATISFIED | state.test.js: 15 tests; integration.test.js: end-to-end PROBLEM+RECOVERY; farmer-attested PROBLEM and RECOVERY for RH OOB |
| ALRT-03 | 17-02, 17-04 | Dedup + throttle (N≥5 consecutive OOB), severity tiers (WARN/CRITICAL), state persistence | SATISFIED | state.test.js: debounce, window gate, cooldown, severity cadence tests all pass; in-memory state confirmed |
| ALRT-04 | 17-04 | Daily heartbeat — liveness indicator + keeps Signal session warm | SATISFIED | heartbeat.test.js: 5/5 pass; farmer-attested daily HEARTBEAT received |
| ALRT-05 | 17-02, 17-04 | Grace-period suppression during fc_controller 20s warm-up | SATISFIED | state.test.js: warmup_suppresses_rh, warmup_suppresses_humidifier_stuck pass; integration test warmup_blocks_rh_alert passes |
| ALRT-06 | 17-02 | All thresholds/cadences configurable via env vars | SATISFIED | config.test.js: 5/5 pass; .env.example documents all 13 vars; docker-compose.override.yml forwards all ALERT_* from .env |
| ALRT-07 | 17-02, 17-04 | Snooze-per-alert-type via Signal reply — bidirectional receive loop + snooze state | PARTIAL | Grammar, state machine snooze transitions, and receive-loop dispatch are all fully implemented and tested. SEND side works (farmer attested). RECEIVE side blocked in production: signal-cli-rest-api /v1/receive returns HTTP 400 for linked secondary device accounts. Loop continues correctly on error (Pitfall 4 compliant) but no envelopes reach the state machine. |
| ALRT-08 | 17-02 | Every alert body includes farmer dashboard link | SATISFIED | message.test.js Test E asserts dashboardUrl exactly once in PROBLEM/RECOVERY/HEARTBEAT; message.js confirmed: `Open: ${config.dashboardUrl}` on last line of all three formatters |

---

## Anti-Patterns Found

| File | Pattern | Severity | Impact |
|------|---------|----------|--------|
| test/ (all) | Jest worker force-exit warning | Info | Test teardown race with WS/HTTP servers; all 84 tests pass; accepted in Plan 03 decisions; no correctness impact |

No TODO/FIXME/placeholder patterns found in src/ files. No empty implementations. No hardcoded empty data flowing to render paths.

---

## Human Verification Required

### 1. Snooze Receive-Side Unblock (ALRT-07 production gap)

**Test:** With alerter running on elder-plops, farmer sends "snooze rh 4h" as a Signal reply from their number (+59892893012) to the alerter's number. Then inject 5+ OOB RH values via bridge (or synthetic injection). Wait 2 minutes. Assert no PROBLEM alert is received.

**Expected:** Alerter logs show `[receive] snooze rh for 14400000ms`; no PROBLEM alert sent during the 4h snooze window; alert resumes after snooze expires.

**Why human:** The receive-loop code is correct and fully tested against the fake server. The real signal-cli-rest-api (bbernhard/signal-cli-rest-api:0.200-dev, json-rpc-native mode) returns HTTP 400 when /v1/receive is called for a linked secondary device account. Resolving this requires a change at the infrastructure layer: either (a) register the alerter's Signal account as a primary (not secondary linked device), or (b) find a version/mode of signal-cli-rest-api that supports /v1/receive for secondary accounts. Once the API returns envelopes, no code changes are needed — the receive-loop dispatch path is wired end-to-end.

---

## Gaps Summary

One gap blocking full ALRT-07 goal achievement in production:

**ALRT-07 receive-side (snooze from farmer Signal reply):** The snooze feature works end-to-end in tests (against fake signal server). In production, signal-cli-rest-api's `/v1/receive` endpoint returns HTTP 400 for the linked secondary device registration mode. This is a known API limitation of `bbernhard/signal-cli-rest-api:0.200-dev` — the json-rpc receive path does not work for secondary/linked accounts.

**What is working:** snooze grammar parsing (parseSnoozeCommand, 8 tests), state machine snooze transitions (state.test.js snooze_mutes_sends, snooze_all tests), receive-loop dispatch wiring (receive-loop.test.js, 5 tests), error-continue behavior (Pitfall 4), and integration test snooze_mutes_while_active against fake.

**What is not working:** The real signal-cli-rest-api /v1/receive returning actual Signal message envelopes from the farmer's phone.

**Root cause:** signal-cli-rest-api API limitation, not a code defect in the alerter.

**Resolution path:** Primary registration on the alerter Signal account, or upgrade to a signal-cli-rest-api version that supports /v1/receive for linked secondary accounts.

All other phase goals are fully achieved and farmer-attested: PROBLEM alerts, RECOVERY alerts, daily HEARTBEAT, warm-up suppression, dedup/cooldown/severity-tiers, env-var configurability, and dashboard URL inclusion.

---

_Verified: 2026-04-18_
_Verifier: Claude (gsd-verifier)_
