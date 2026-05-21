---
slug: alerter-co2-only-not-pi
status: root-cause-found
trigger: |
  During the 2026-05-20 fc1 outage (13:04 → ~24:00 UTC, 10h47m), the
  alerter fired multiple "co2 sensor offline" Signal alerts to f1
  (+5...3012) — farmer confirmed receipt. BUT the alerter did NOT fire
  a higher-level "fc1 offline" / "chamber dark" / "pi offline" message,
  even though ALL sensors (humidity, temperature, co2, humidifier
  state) went silent at the same instant — i.e. fc1 itself was dead.
  Farmer ended up asking "sensors offline ??? panic? all good?" 10h
  into the outage. The single-sensor message did not communicate the
  actual situation (entire pi is dark).
created: 2026-05-20
updated: 2026-05-21
---

# Debug: alerter fires per-sensor message but not pi-offline / chamber-dark

## Symptoms

**Expected:** When fc1 itself goes dark (ALL `fc.*` topics silent simultaneously), alerter should emit a high-level "FC-1 offline" / "pi offline" message so the farmer immediately understands the chamber is uncontrolled — NOT just a per-sensor "co2 sensor offline" alert.

**Actual:** Farmer received only "co2 sensor offline" Signal alerts (78-char messages, multiple). No higher-level "pi offline" or "chamber dark" message ever fired during the 10h47m outage. Farmer interpreted the messages as a CO2-sensor-specific problem (or noise), not a chamber-wide outage, and only investigated 10h later via manual ping.

**Error messages:** None — alerter operated within its own logic. The bug is in *which* alert fires and *what* it communicates, not a crash.

**Timeline:** Outage started 13:04 UTC 2026-05-20. CO2-offline Signal sends visible in `docker logs mushy-alerter-1` shortly after. Outage ended ~24:00 UTC when farmer rebooted fc1.

**Reproduction:** Stop bridge↔fc1 connectivity (or stop fc1 entirely). Wait `ALERT_SENSOR_OFFLINE_MIN` (5 min). Observe what alerts the alerter emits.

## Config during outage

- `ALERT_SENSOR_OFFLINE_MIN=5`
- `ALERT_PI_OFFLINE_MIN=10`
- `ALERT_SCD41_ENABLED=true`
- `ALERT_SHT30_ENABLED=false`

## Known-relevant code paths

- `src/agents/alerter/src/state.js` — watchdog state machine, drives evaluation per-tick
- `src/agents/alerter/src/rules.js` — `isPiOffline`, `isSensorSilent` etc.
- `src/agents/alerter/src/message.js` — alert formatting
- `src/agents/alerter/src/bridge-client.js` — `wsConnected` (the alerter's view of bridge), and per-topic last-message timestamps
- `src/mission-control/bridge/src/index.js` — bridge represents fc1 disconnect separately from alerter↔bridge connection

## Hypotheses to test

1. **`isPiOffline` uses `wsConnected` between alerter and bridge** — but bridge stayed up during the outage (only fc1↔bridge dropped). So alerter's WS to bridge never disconnected; `isPiOffline` was permanently false despite fc1 being dark.
2. **`isPiOffline` requires a dedicated "pi heartbeat" topic** that doesn't exist (memory: `feedback_alerter_needs_meta_watchdog` flagged this; 999.42 closure said it was deferred to 999.35 daily-maintenance digest).
3. **Per-sensor `isSensorSilent` fires per-topic** with no aggregation — so CO2-offline, humidity-offline, temp-offline all fire as separate alerts, but they're rate-limited/deduped such that only CO2 made it through (or CO2 was the first to trip and the others were suppressed by cooldown).

## Current Focus

- hypothesis: H1 CONFIRMED. H3 partially confirmed but reshaped: per-sensor watchdogs key off `sht30_fresh` / `scd41_fresh` only; there is no separate humidity/temperature topic-level watchdog. SHT30 was muted (`ALERT_SHT30_ENABLED=false`) so only SCD41 (CO2) was an eligible per-sensor alert. H2 is the actual structural fix path.
- test: read `isPiOffline` and bridge `/health` — see Evidence below
- expecting: `isPiOffline` keys off alerter↔bridge WS and the bridge's `rosReady` boot flag — neither reflects fc1 publisher liveness
- next_action: present fix options to farmer; the structural fix is "fc1 publisher freshness as the actual pi-liveness signal"
- reasoning_checkpoint: null
- tdd_checkpoint: null

## Evidence

- timestamp: 2026-05-20T~24:00 UTC — farmer confirmed receipt of "co2 sensor offline" alerts on +5...3012 during outage
- timestamp: 2026-05-21T00:30 UTC — `docker logs --since 14h mushy-alerter-1` shows many `[signal] sent -> +5XXXXXX3012 (78 chars)` and zero matches for `pi.offline|sensor.silent|critical`
- bridge ws_close → ws_open cycles in alerter log during outage — bridge↔alerter link bounced repeatedly but ultimately stayed reachable
- All 9 telemetry topics in Timescale went silent at 13:04 UTC ±1 sec — clean fc1 death, not gradual sensor degradation
- `src/agents/alerter/src/rules.js:33-45` — `isPiOffline({ wsConnected, rosConnected, wsLastConnectedMs, rosDisconnectedSinceMs, config })`. Fires only when **alerter↔bridge** WS is down past `piOfflineMin`, or `rosConnected===false` past `piOfflineMin`. Neither input reflects fc1 publisher liveness.
- `src/agents/alerter/src/bridge-client.js:26-34, 57-64` — `wsConnected` is literally the alerter's own WebSocket to the bridge container. It only flips false when the alerter container can't reach the bridge container. During a pure fc1 outage these stayed up.
- `src/mission-control/bridge/src/index.js:38, 318, 1107` — `rosReady` is a one-shot boolean set true once after `rclnodejs.init()` on bridge boot. It is **never** set back to false when fc1's ROS publishers stop sending. So `/health` reports `ros.connected: true` for the entire lifetime of the bridge container, regardless of fc1 state. The alerter therefore sees `rosConnected: true` perpetually.
- Net: `isPiOffline` returned `false` for the full 10h47m outage. The `pi` alert type was never even a candidate to fire.
- Per-sensor watchdog DID fire correctly: `state.js:376-405` drives `scd41` (and `sht30` when enabled) via `isSensorSilent` keyed on `scd41LastSeenMs` (refreshed by `sensor_health.values.scd41_fresh==='true'` events from fc1). When fc1 stopped publishing `sensor_health`, `scd41LastSeenMs` froze; after `sensorOfflineMin=5` the SCD41 watchdog fired. SHT30 watchdog was disabled via `ALERT_SHT30_ENABLED=false` so no humidity/temperature equivalent ever ran.
- There is no per-topic watchdog for `fc.humidity` / `fc.temperature` / `fc.co2` payload freshness. The only sensor-level freshness signals are `sht30_fresh` / `scd41_fresh` from the `sensor_health` envelope. So even with both sensors enabled, the farmer would have received "sht30 offline" + "scd41 offline" — still per-sensor, still no chamber-dark framing.
- `signal.js` enforces `maxSendsPerHour` (resolved via Tier C globals) which explains why the SCD41 alert delivered only ~11 messages over 10h47m instead of one per `criticalCooldownMin`.

## Eliminated

- H2 as the *cause* (no dedicated pi-heartbeat topic exists, but that's the *missing thing*, not a bug in existing code). Reframed as the fix direction.

## Root Cause

`isPiOffline` is misnamed: it detects "alerter cannot reach the bridge container" + "bridge never finished its own ROS init at boot". Neither input is a function of fc1 publisher activity. During the 2026-05-20 outage the bridge container was healthy and `rosReady` was perpetually true, so `isPiOffline` was structurally incapable of firing despite fc1 being dark for 10h47m.

The per-sensor `scd41` watchdog correctly tripped (it keys off `scd41_fresh` flags that originate on fc1), but:
1. SHT30 was disabled, so no humidity/temperature equivalent fired.
2. There is no chamber-level aggregator that says "ALL fc.* topics silent → fc1 is dark" — the farmer-facing message stayed "co2 sensor offline", which reads like a single-sensor I2C glitch, not a chamber outage.

This is the structural gap flagged by `feedback_alerter_needs_meta_watchdog.md` and explicitly out-of-scope of 999.42's closure (commit 20d8339 added per-sensor enable flags but did not add a chamber-dark detector).

## Fix Direction (proposed; awaiting farmer go-ahead)

**Two complementary changes, smallest-correct:**

**A. Add real fc1-liveness signal (replaces what `isPiOffline` was supposed to mean).**

   On the **bridge** side (`src/mission-control/bridge/src/index.js`), track `fc1LastMsgTs = max(timestamp)` across every fc1 topic the bridge subscribes to (humidity, temperature, co2, humidifier, humidity_2, temperature_2, sensor_health, humidifier_duty, pid_output). Expose in `/health` as `fc1: { last_msg_ts, last_msg_age_sec }`.

   On the **alerter** side (`bridge-client.js` `pollHealth`), forward `fc1LastMsgTs` via the existing `pi_liveness` event. In `rules.js` `isPiOffline`, add a third trigger: `fc1LastMsgTs != null && (nowMs - fc1LastMsgTs) > piOfflineMin*60000 → true`. This is the actual "fc1 is dark" signal we want.

   Crucially, the existing `wsConnected` / `rosConnected` triggers stay — they still cover real failure modes (alerter↔bridge partition, bridge container ROS init failure). The new trigger is an OR, not a replacement.

**B. Make the pi-offline message clearly chamber-level.**

   `message.js` `formatProblem({alertType:'pi'})` should produce a farmer-facing line like:
   `FC-1 offline ?? no telemetry XXm. chamber uncontrolled. last RH XX% @ HH:MM.`
   (no em-dashes per `feedback_no_em_dashes_in_artifacts`). The existing `lastKnown` payload (state.js:513-520) already carries the data.

**Tests to add (before any rebuild):**
- `rules.test.js` — `isPiOffline` returns true when `fc1LastMsgTs` exceeds threshold even though `wsConnected===true && rosConnected===true`.
- `state.test.js` — `pi_liveness` event carrying a stale `fc1LastMsgTs` drives `perType.pi` to FIRING and emits a `send` action.
- `bridge` side: unit test that `/health` exposes `fc1.last_msg_age_sec`, advancing after each subscribed topic.

**Deployment:** elder-plops is dev+prod with no staging (memory). Rebuilding the alerter container ships immediately to f1. Test suite must be green before `docker-compose up -d --build bridge alerter`.

## Resolution

(pending farmer go-ahead on fix direction)
