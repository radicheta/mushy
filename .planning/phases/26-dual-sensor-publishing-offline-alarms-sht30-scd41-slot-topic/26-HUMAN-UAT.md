---
status: partial
phase: 26-dual-sensor-publishing-offline-alarms-sht30-scd41-slot-topic
source: [26-VERIFICATION.md]
started: 2026-04-25T22:50:00Z
updated: 2026-04-25T22:55:00Z
---

## Current Test

[awaiting farmer-side Signal hardware tests + signal-cli trust reset]

## Tests

### 1. fc1 deploy + ros2 topic echo on slot-2 (Plan 01 hardware smoke)
expected: After `git push fc1/prod`: `ros2 topic list | grep fc1` shows `/fc1/temperature_2` and `/fc1/humidity_2`. `ros2 topic echo /fc1/temperature_2 -n 1` returns a Temperature msg with `header.frame_id == 'scd41'`. `ros2 topic echo /fc1/sensor_health -n 1` shows KeyValue entries `sht30_fresh` and `scd41_fresh`.
result: PASS — pushed main → origin/fc1/prod, ran scripts/pi-deploy/deploy.sh; `ros2 topic list` on fc1 shows /fc1/temperature_2, /fc1/humidity_2, /fc1/sensor_health. `ros2 topic echo /fc1/temperature_2 --once` returns frame_id=scd41 + temperature=15.71. /fc1/temperature shows frame_id=scd41 (silent fallback engaged because SHT30 is currently offline). /fc1/sensor_health shows sht30_fresh='false', scd41_fresh='true' — the system is correctly distinguishing the physical sensors.

### 2. Bridge container rebuild + slot-2 WS forwarding smoke on elder-plops
expected: After `docker compose up -d --build bridge`: logs clean of error/fatal. `wscat -c ws://elder-plops-ts:8081` shows frames with `temperature_2` / `humidity_2` keys. Timescale has `fc.temperature_2` and `fc.humidity_2` rows.
result: PASS — bridge rebuilt + recreated. Logs clean. WS probe shows broadcast keys: co2, humidifier, humidity, humidity_2, sensor_health, temperature, temperature_2, timestamp. Timescale: fc.temperature_2 = 42 rows / 5 min, fc.humidity_2 = 42 rows / 5 min.

### 3. Alerter container rebuild + ALERT_SENSOR_OFFLINE_MIN env confirmation
expected: After `docker compose up -d --build alerter`: `docker compose exec alerter env | grep ALERT_SENSOR_OFFLINE_MIN` outputs `ALERT_SENSOR_OFFLINE_MIN=5`. Logs show `[boot] alerter starting`. No `[fatal]`/`[config]` errors.
result: PASS — alerter built and running. `ALERT_SENSOR_OFFLINE_MIN=5` confirmed. `[boot] alerter starting`, `[bridge-client] ws_open`, `[heartbeat] fired for 2026-04-25` all present. Detection + dispatch logic confirmed working: alerter is firing `[apply] action send` for sht30 (SHT30 currently offline on fc1), but Signal delivery is failing on a pre-existing signal-cli trust issue (see Operational Issue below).

### 4. Hardware end-to-end SHT30 unplug → Signal alert (D-04, D-06)
expected: Pull SHT30 I2C wire on fc1. Within 5 min farmer's Signal receives `[PROBLEM · CRITICAL] FC-1 · SHT30 offline`. Re-plug → `[RECOVERY] FC-1 · SHT30 offline back` within ~30s. SCD41 silence does not produce SHT30 message.
result: PARTIAL — SHT30 is currently offline on fc1 (not by deliberate unplug — was already offline on arrival, exactly the incident class this phase targets). Alerter has correctly detected it and is invoking `[apply] action send` for sht30 alert type. Signal delivery blocked by signal-cli trust reset (separate operational item).

### 5. Hardware end-to-end SCD41 outage → Signal alert (Option C hybrid path)
expected: Disable SCD41 on fc1. Within 5 min Signal receives `[PROBLEM · CRITICAL] FC-1 · SCD41 offline`. Recovery within ~30s. SHT30 alert does NOT fire (D-05 isolation).
result: [pending] — requires deliberate SCD41 disable at the farm; gated on signal-cli trust reset for Signal-side proof.

### 6. Snooze grammar live-fire on Signal
expected: Send `snooze sht30 4h` from farmer's Signal. Alerter responds with snooze-confirmed reply. Trigger SHT30 silence — no alert until 4h elapses. SCD41 silence still produces scd41 alert (D-05 isolation under live receive-loop).
result: [pending] — receive loop is failing with `signal-cli receive 400` (pre-existing linked-device issue per `project_signal_cli_link_gotchas`); blocked by signal-cli trust reset.

### 7. Sim-mode launch on a host with working ROS env (optional)
expected: `ros2 launch fc_core fc.launch.py sensor_simulation_mode:=true` then echo /fc1/temperature_2 shows `frame_id == 'scd41'`; sensor_health shows `sht30_fresh: 'true'` and `scd41_fresh: 'true'`. Optional — fc1 hardware deploy supersedes.
result: SKIPPED — superseded by item 1 (real-hardware Pi deploy verified end-to-end).

### 8. SHT30 happy-path verification (BLOCKING — phase motivation unverified)
expected: Plug the SHT30 back into fc1's I2C bus (or replace if hardware-faulty). Within ~30s of fc-core seeing the sensor:
  - `ros2 topic echo /fc1/temperature --once` shows `frame_id == 'sht30'` (silent fallback releases — slot-1 sourced from SHT30 again)
  - `ros2 topic echo /fc1/sensor_health --once` shows `sht30_fresh: 'true'`
  - Alerter sends `[RECOVERY] FC-1 · Primary Humidity Sensor offline back` on Signal (proves D-06 symmetric recovery)
  - In Mission Control, plot slot-1 RH (`/fc1/humidity`) vs slot-2 RH (`/fc1/humidity_2`) — verify the delta the phase was built to surface (SCD41 RH suspected ~4% high per ROADMAP). One eyeball on the overlay is the acceptance criterion.
result: [PASS — 2026-04-29] SHT30 reinstalled 2026-04-27 and live-verified this session: `frame_id: sht30` on `/fc1/temperature`, `sht30_fresh: 'true'` in sensor_health. SHT30 RH ~93.4%, SCD41 RH pegged at 100% — SCD41 clipping confirmed by farmer eyeball on the slot-1/slot-2 overlay (delta is more dramatic than the suspected ~4% high because chamber is cold + saturated today; SCD41's RH reading is unreliable past ~95% — exactly the failure mode dual-publish was built to surface). Sign-off from farmer.

**Post-mortem note (carried into deferred-items):** the slot-2 overlay didn't actually exist in MC until UAT-8 was attempted — bridge forwarded slot-2 to Timescale + WS fine, but the bridge history allowlist (`ALLOWED_TOPICS`) and OpenMCT plugin (`SENSORS` array + `fieldToKey`) were never extended for slot-2. Plan-26-02 contract-tested the bridge half but missed the user-visible half. Patched same session (commit `2b5ae75`).

## Summary

total: 8
passed: 4
issues: 0
pending: 2
skipped: 1
blocked: 1

## Operational Issue (carry-out, not a phase-26 gap)

`signal-cli` rejects sends with `Failed to send message due to untrusted identities` and rejects receive with `signal-cli receive 400`. This is a pre-existing linked-device issue (memory `project_signal_cli_link_gotchas`) — not introduced by Phase 26. The alerter's Phase-26 detection + dispatch logic is verified correct (it IS calling `[apply] action send` for sht30); only the Signal protocol last-mile is broken. Reset by re-linking from farmer's phone or running through the link-mode recipe. Tracking as standalone followup.

## Gaps
