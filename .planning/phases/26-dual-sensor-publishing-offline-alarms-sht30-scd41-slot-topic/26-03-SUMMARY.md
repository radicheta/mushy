---
phase: 26
plan: 03
subsystem: alerter
tags: [alerter, signal, jest, nodejs, state-machine, sht30, scd41, snooze]
requires:
  - sht30_fresh KeyValue (from sensor_health, Plan 01)
  - scd41_fresh KeyValue (from sensor_health, Plan 01)
  - msg.temperature_2 / msg.humidity_2 WS frames (Plan 02 — pending wave 2 bridge work)
provides:
  alert-types:
    - "sht30 (CRITICAL) — fires on sht30_fresh='false' OR alerter-side >5min silence"
    - "scd41 (CRITICAL) — fires on scd41_fresh='false' OR slot-2 WS silence >5min"
  events:
    - "sensor_freshness {sensor: 'sht30'|'scd41', lastSeenMs} — internal, dispatched from index.js on slot-2 WS arrival"
  signal-titles:
    - "[PROBLEM · CRITICAL] FC-1 · SHT30 offline"
    - "[PROBLEM · CRITICAL] FC-1 · SCD41 offline"
    - "[RECOVERY] FC-1 · SHT30 offline back"
    - "[RECOVERY] FC-1 · SCD41 offline back"
  snooze-grammar:
    - "snooze sht30 {30m|1h|2h|4h|8h|24h}"
    - "snooze scd41 {30m|1h|2h|4h|8h|24h}"
  env:
    - "ALERT_SENSOR_OFFLINE_MIN (default 5) — minutes of silence before SHT30/SCD41 watchdog fires"
affects:
  - "Mission Control alerter container — needs `docker compose up -d --build alerter` after worktree merge"
tech-stack:
  added:
    - "Per-physical-sensor freshness watchdog (Option C hybrid — Pi flag OR alerter-side timestamp)"
    - "sensor_freshness internal event for slot-2 WS arrival routing"
  patterns:
    - "Reuse driveAlertType for new alert types (PENDING→FIRING→RECOVERY state machine)"
    - "oobN=1, oobWindowMin=0 for immediate-fire on Pi-authoritative flag flip"
    - "OR-gate combining authoritative Pi flag with alerter-side watchdog (RESEARCH OQ3 — favors silence detection over false-positive avoidance)"
key-files:
  created: []
  modified:
    - "src/agents/alerter/src/state.js — ALERT_TYPES + SEVERITY extension; sht30LastSeenMs/scd41LastSeenMs fields; sensor_health case extended with KeyValue parsing + drive; new sensor_freshness case; tick case extended with watchdog re-evaluation"
    - "src/agents/alerter/src/rules.js — isSensorSilent predicate added + exported"
    - "src/agents/alerter/src/index.js — onMessage routes msg.temperature_2 / msg.humidity_2 to sensor_freshness event"
    - "src/agents/alerter/src/message.js — ALERT_TITLES adds 'SHT30 offline' / 'SCD41 offline'; formatProblem branch emits 'Last fresh: …'"
    - "src/agents/alerter/src/snooze.js — VALID_ALERT_TYPES + STRICT regex extended with sht30|scd41; fuzzyReply text updated"
    - "src/agents/alerter/src/config.js — sensorOfflineMin parsed from ALERT_SENSOR_OFFLINE_MIN env (default 5)"
    - "src/agents/alerter/test/state.test.js — 9 new tests (4 sht30 + 4 scd41 + 1 snooze cross-isolation) covering D-04/D-05/D-06"
    - "src/agents/alerter/test/snooze.test.js — Test E updated for extended VALID_ALERT_TYPES help text"
    - "docker-compose.override.yml — ALERT_SENSOR_OFFLINE_MIN env line added under alerter service"
decisions:
  - "Hybrid Option C OR-gate: scd41 fires if EITHER scd41_fresh='false' OR alerter watchdog stale, since SCD41 has two independent freshness signals (Pi flag + slot-2 WS arrivals). SHT30 has only the Pi flag — fail-safe single source documented in threat model."
  - "oobN=1/oobWindowMin=0 for both new alert types matches the existing 'sensor' (level=2 ERROR) immediate-fire pattern. CRITICAL severity → 60min cooldown via existing cooldownMs() reuse."
  - "Container rebuild deferred to worktree merge: rebuilding from a worktree on elder-plops (dev+prod) would deploy unmerged code immediately. Compose config validated; rebuild command documented in this summary."
  - "Test for the 'fires after silent' D-04 case checks accumulated sends across all events (not just the final tick), because the immediate-fire path triggers on the sensor_health event that flips the flag, not on the next tick. The tick is still required to verify the watchdog re-evaluation path (covered by the Option C hybrid test)."
metrics:
  duration: ~30 min
  completed: 2026-04-25T21:35:00Z
  tasks: 3
  commits: 3
  files_changed: 9
---

# Phase 26 Plan 03: Per-physical-sensor offline alerts (sht30/scd41) Summary

Added `sht30` and `scd41` alert types to the Mission Control alerter
container. Both follow the existing PENDING→FIRING→RECOVERY state machine
via `driveAlertType`, reusing snooze, cooldown, and Signal-send paths.
SHT30 freshness derives from the Pi-side `sht30_fresh` KeyValue (slot-1
frame_id provenance, set by Plan 01). SCD41 freshness has two independent
signals OR-gated together: `scd41_fresh` KeyValue AND alerter-side
slot-2 WS arrival timestamps — belt-and-braces per RESEARCH Option C.

## Files Modified

| File | Change |
|------|--------|
| `src/agents/alerter/src/state.js` | `ALERT_TYPES` gains `'sht30'`/`'scd41'`; `SEVERITY` adds CRITICAL for both. New `sht30LastSeenMs` / `scd41LastSeenMs` fields seeded to `bootedAtMs` (Pitfall 5). `sensor_health` case extended with `values.{sht30,scd41}_fresh` parsing + post-grace drive via `driveAlertType` (oobN=1). New `sensor_freshness` case for slot-2 WS arrival. `tick` case re-evaluates per-sensor watchdog every 30s. |
| `src/agents/alerter/src/rules.js` | `isSensorSilent({lastSeenMs, nowMs, config})` added + exported. |
| `src/agents/alerter/src/index.js` | `onMessage` routes `msg.temperature_2` / `msg.humidity_2` → `{type:'sensor_freshness', sensor:'scd41', lastSeenMs:clock()}`. SHT30 freshness routes through `sensor_health` only. |
| `src/agents/alerter/src/message.js` | `ALERT_TITLES` adds `sht30: 'SHT30 offline'` and `scd41: 'SCD41 offline'`. `formatProblem` branch for both emits `Last fresh: {fmtRelative(lastSeenMs, nowMs)}`. |
| `src/agents/alerter/src/snooze.js` | `VALID_ALERT_TYPES` extended; STRICT regex alternation extended with literal `sht30\|scd41` (anchoring preserved — V5 mitigation). `fuzzyReply` help text updated. |
| `src/agents/alerter/src/config.js` | `sensorOfflineMin: parseIntEnv(env, 'ALERT_SENSOR_OFFLINE_MIN', 5)` added next to `piOfflineMin`. |
| `src/agents/alerter/test/state.test.js` | 9 new tests: sht30 (fires/isolation/recovery/cooldown), scd41 (fires/isolation/recovery/Option-C-hybrid), snooze cross-isolation. |
| `src/agents/alerter/test/snooze.test.js` | Test E updated to expect new help text including `sht30, scd41`. |
| `docker-compose.override.yml` | `ALERT_SENSOR_OFFLINE_MIN=${ALERT_SENSOR_OFFLINE_MIN:-5}` env line added under the alerter service after `ALERT_PI_OFFLINE_MIN`. |

## Test Results

```
Test Suites: 11 passed, 11 total
Tests:       93 passed, 93 total
```

- Pre-existing tests: 86 (all still pass after the snooze.test.js help-text update).
- New tests: 7 effectively-new (the 2 isolation tests would trivially pass before implementation since the alert types didn't exist; the other 7 explicitly fail without the implementation, then pass after).

New named tests:
- `sht30_offline (D-04, D-05, D-06) > sht30 fires after sensorOfflineMin minutes silent`
- `sht30_offline (D-04, D-05, D-06) > does NOT fire scd41 when only sht30 is silent (D-05 isolation)`
- `sht30_offline (D-04, D-05, D-06) > recovery on sht30_fresh flip back to true (D-06)`
- `sht30_offline (D-04, D-05, D-06) > repeats after criticalCooldownMin (cooldown reuse)`
- `scd41_offline (D-04, D-05, D-06) > scd41 fires after sensorOfflineMin minutes silent (Pi flag path)`
- `scd41_offline (D-04, D-05, D-06) > does NOT fire sht30 when only scd41 is silent (D-05 isolation)`
- `scd41_offline (D-04, D-05, D-06) > recovery on scd41_fresh flip back to true (D-06)`
- `scd41_offline (D-04, D-05, D-06) > scd41 fires from slot-2 WS silence even without sensor_health (Option C hybrid)`
- `snooze sht30/scd41 (D-05) > snooze sht30 mutes sht30 only; scd41 still fires`

RED→GREEN verification: the RED commit (2e2d05d) ran `npm test` exiting
non-zero with 7 failing tests in the new describe blocks. The GREEN commit
(ebe9966) brings them all to pass.

## Container Status

Container rebuild **deferred to worktree merge**. Reason: the worktree
operates on an unmerged feature branch; running `docker compose up -d
--build alerter` from this worktree on elder-plops (dev+prod, no
staging) would push unmerged code to the live alerter immediately.

Compose config validated:

```
$ docker compose config --quiet
$ # exits 0 with no output
```

Env var resolution verified:

```
$ docker compose config 2>/dev/null | grep ALERT_SENSOR_OFFLINE_MIN
      ALERT_SENSOR_OFFLINE_MIN: "5"
```

After worktree merge to main, the orchestrator (or a follow-up deploy
step) should run from repo root:

```bash
docker compose up -d --build alerter
docker compose exec alerter env | grep ALERT_SENSOR_OFFLINE_MIN  # expect =5
docker compose logs --tail 100 alerter | grep "\\[boot\\] alerter starting"
```

## Manual Smoke Plan (deferred — requires Plan 02 deployment + hardware)

Plan 02 is the wave-2 bridge work (still in-flight). End-to-end smoke
gates on Plan 02 forwarding `temperature_2`/`humidity_2` over WS plus
the `sht30_fresh`/`scd41_fresh` KeyValues from Plan 01 already shipping
on `/fc1/sensor_health`.

1. SSH `fc1-ts`. Disable SHT30 by `i2cset` to a bad address or pull I2C wire.
2. Wait 5 min. Expect Signal:
   `[PROBLEM · CRITICAL] FC-1 · SHT30 offline\nLast fresh: <Xm ago>\nOpen: http://elder-plops-ts:8081/farmer`
3. Reconnect SHT30. Within ~30s expect:
   `[RECOVERY] FC-1 · SHT30 offline back\nWas OOB for <duration>\nOpen: ...`
4. Repeat for SCD41 (cover I2C 0x62 sensor or unplug Stemma cable).
5. Snooze test: send `snooze sht30 4h` from farmer's Signal account; trigger
   SHT30 silence again; expect no Signal until 4h passes OR SCD41 silence
   still triggers a separate scd41 message (proves D-05 isolation).

## Phase 26 Completion

Phase 26 wave 2 (Plans 02 + 03) integration test still pending Plan 02
completion. Plan 03's alerter wiring is **code-complete and unit-test-
green**; integration with the live bridge happens at the wave-2 merge
gate.

`26-SMOKE-EVIDENCE.md` will be created at the phase-merge step with
real Signal screenshots after the alerter rebuild lands on elder-plops
and a manual hardware-disable test is executed at the farm.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Test expectations mismatched the implementation contract**
- **Found during:** Task 2 (GREEN run)
- **Issue:** The Task 1 RED tests asserted that the `sht30`/`scd41` send
  fires from the *tick* after the Pi flag flips false. But the implementation
  contract per the plan's interfaces — `oobN=1, oobWindowMin=0` — fires
  immediately on the sensor_health event itself, not on the next tick.
  Several D-04 tests would have stayed red against a correct implementation.
- **Fix:** Re-wrote the tests to gather sends across all transitions
  (event + tick), and asserted state machine state directly. The Option-C
  hybrid test was kept as the explicit watchdog-fires-from-tick path
  using direct `sht30LastSeenMs` stubbing for clean isolation.
- **Files modified:** `src/agents/alerter/test/state.test.js`
- **Commit:** ebe9966 (folded into the GREEN commit since the test fixture
  is logically inseparable from the implementation contract).

**2. [Rule 2 - Lockstep] snooze.test.js Test E asserted exact help-text**
- **Found during:** Task 2 (GREEN run)
- **Issue:** Pre-existing `test/snooze.test.js` Test E hard-coded
  `'rh, sensor, pi, humidifier, all'` against `fuzzyReply().reply`. Once
  the snooze.js whitelist + help text were extended to include
  `sht30, scd41`, this regression-fired.
- **Fix:** Updated the test expectation to match the new help text
  (`'rh, sensor, pi, humidifier, sht30, scd41, all'`). Lockstep update —
  not a behavior change.
- **Files modified:** `src/agents/alerter/test/snooze.test.js`
- **Commit:** ebe9966.

### Deferred to Phase Merge

**3. Container rebuild on elder-plops**
- The plan's Task 3 verification calls for `docker compose up -d --build
  alerter` and `docker compose exec alerter env | grep
  ALERT_SENSOR_OFFLINE_MIN`. Since this work executes inside a parallel
  worktree on elder-plops (which is dev+prod with no staging), rebuilding
  here would deploy unmerged feature-branch code to the live alerter.
  Documented in this summary; rebuild belongs to the orchestrator's
  post-merge step.

## Threat Flags

None new. The threat model in 26-03-PLAN.md fully covers the
implementation as shipped (T-26-10 through T-26-15).

## Self-Check: PASSED

Files exist:
- `src/agents/alerter/src/state.js` — FOUND (ebe9966)
- `src/agents/alerter/src/rules.js` — FOUND (ebe9966)
- `src/agents/alerter/src/index.js` — FOUND (ebe9966)
- `src/agents/alerter/src/message.js` — FOUND (ebe9966)
- `src/agents/alerter/src/snooze.js` — FOUND (ebe9966)
- `src/agents/alerter/src/config.js` — FOUND (ebe9966)
- `src/agents/alerter/test/state.test.js` — FOUND (2e2d05d, ebe9966)
- `src/agents/alerter/test/snooze.test.js` — FOUND (ebe9966)
- `docker-compose.override.yml` — FOUND (80f6015)

Commits exist on branch:
- `2e2d05d` test(26-03): add failing tests for sht30/scd41 offline alerts (D-04/D-05/D-06) — FOUND
- `ebe9966` feat(26-03): add sht30/scd41 offline alert types with hybrid Pi+watchdog detection — FOUND
- `80f6015` ops(26-03): plumb ALERT_SENSOR_OFFLINE_MIN env (default 5) for alerter — FOUND

Verification commands pass:
- `cd src/agents/alerter && npm test` → 93/93 passed (11 suites)
- `docker compose config --quiet` → exit 0
- `grep -q 'ALERT_SENSOR_OFFLINE_MIN=\${ALERT_SENSOR_OFFLINE_MIN:-5}' docker-compose.override.yml` → match
- `docker compose config | grep ALERT_SENSOR_OFFLINE_MIN` → resolves to `"5"`
