---
status: partial
phase: 26-dual-sensor-publishing-offline-alarms-sht30-scd41-slot-topic
source: [26-VERIFICATION.md]
started: 2026-04-25T22:50:00Z
updated: 2026-04-25T22:50:00Z
---

## Current Test

[awaiting human testing]

## Tests

### 1. fc1 deploy + ros2 topic echo on slot-2 (Plan 01 hardware smoke)
expected: After `git push fc1/prod`: `ros2 topic list | grep fc1` shows `/fc1/temperature_2` and `/fc1/humidity_2`. `ros2 topic echo /fc1/temperature_2 -n 1` returns a Temperature msg with `header.frame_id == 'scd41'`. `ros2 topic echo /fc1/sensor_health -n 1` shows KeyValue entries `sht30_fresh` and `scd41_fresh`.
result: [pending]

### 2. Bridge container rebuild + slot-2 WS forwarding smoke on elder-plops
expected: After `docker compose up -d --build bridge`: logs clean of error/fatal. `wscat -c ws://elder-plops-ts:8081` shows frames with `temperature_2` / `humidity_2` keys. Timescale has `fc.temperature_2` and `fc.humidity_2` rows.
result: [pending]

### 3. Alerter container rebuild + ALERT_SENSOR_OFFLINE_MIN env confirmation
expected: After `docker compose up -d --build alerter`: `docker compose exec alerter env | grep ALERT_SENSOR_OFFLINE_MIN` outputs `ALERT_SENSOR_OFFLINE_MIN=5`. Logs show `[boot] alerter starting`. No `[fatal]`/`[config]` errors.
result: [pending]

### 4. Hardware end-to-end SHT30 unplug → Signal alert (D-04, D-06)
expected: Pull SHT30 I2C wire on fc1. Within 5 min farmer's Signal receives `[PROBLEM · CRITICAL] FC-1 · SHT30 offline`. Re-plug → `[RECOVERY] FC-1 · SHT30 offline back` within ~30s. SCD41 silence does not produce SHT30 message.
result: [pending]

### 5. Hardware end-to-end SCD41 outage → Signal alert (Option C hybrid path)
expected: Disable SCD41 on fc1. Within 5 min Signal receives `[PROBLEM · CRITICAL] FC-1 · SCD41 offline`. Recovery within ~30s. SHT30 alert does NOT fire (D-05 isolation).
result: [pending]

### 6. Snooze grammar live-fire on Signal
expected: Send `snooze sht30 4h` from farmer's Signal. Alerter responds with snooze-confirmed reply. Trigger SHT30 silence — no alert until 4h elapses. SCD41 silence still produces scd41 alert (D-05 isolation under live receive-loop).
result: [pending]

### 7. Sim-mode launch on a host with working ROS env (optional)
expected: `ros2 launch fc_core fc.launch.py sensor_simulation_mode:=true` then echo /fc1/temperature_2 shows `frame_id == 'scd41'`; sensor_health shows `sht30_fresh: 'true'` and `scd41_fresh: 'true'`. Optional — fc1 hardware deploy supersedes.
result: [pending]

## Summary

total: 7
passed: 0
issues: 0
pending: 7
skipped: 0
blocked: 0

## Gaps
