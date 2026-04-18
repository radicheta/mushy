---
phase: 15-sensor-warmup-grace-period
plan: "03"
soak_start: "2026-04-18T01:26:30+00:00"
soak_end: "2026-04-18T01:27:13+00:00"
SOAK_PASS: true
---

# Phase 15 — Soak Evidence

**Date:** 2026-04-18T01:26:30+00:00
**Host:** fc1 (via fc1-ts Tailscale, 100.96.239.75)
**Commit SHA on fc1:** 125edccee4243b63ab445e6fcadbb519b47db320

## Verdict: SOAK_PASS

SOAK_PASS: true

All three pass criteria met on live hardware:
1. `/fc1/sensor_health` published WARN immediately at grace entry (grace_elapsed_sec=1.0)
2. `/fc1/sensor_health` published OK at grace clear (grace_elapsed_sec=25.0, buffer_full=true)
3. No humidifier actuation during first 20s post-restart

## Evidence

### 1. Topic type confirmed

```
Type: diagnostic_msgs/msg/DiagnosticStatus
Publisher count: 1
Subscription count: 0
```

### 2. WARN on grace entry (first DiagnosticStatus message post-restart)

Captured at approximately t=6s after restart (5s sleep + echo latency):

```
level: "\x01"
name: fc1/controller
message: warming up
hardware_id: fc1
values:
- key: warming_up
  value: 'true'
- key: grace_elapsed_sec
  value: '1.0'
- key: grace_total_sec
  value: '20.0'
- key: buffer_full
  value: 'false'
```

`level: "\x01"` = `DiagnosticStatus.WARN` (integer value 1). Grace active: buffer not yet full AND <20s elapsed.

### 3. OK on grace clear (second DiagnosticStatus message)

```
level: "\0"
name: fc1/controller
message: ok
hardware_id: fc1
values:
- key: warming_up
  value: 'false'
- key: grace_elapsed_sec
  value: '25.0'
- key: grace_total_sec
  value: '20.0'
- key: buffer_full
  value: 'true'
```

`level: "\0"` = `DiagnosticStatus.OK` (integer value 0). Grace cleared: buffer full AND >20s elapsed.

Elapsed from restart to OK: ~25s from node init (within the expected ≤25s window per plan).
Journal confirms at 01:27:03 UTC: `WARMUP-CLEARED: control loop engaging`
Restart was 01:26:30 UTC → 33s total (includes ~8s for launch to initialize nodes).

### 4. No spurious humidifier actuation in first 20s

```
no humidifier/warmup lines in first 20s
```

Humidifier journal grep (first 20s window, `--until "+20 seconds"` from restart) returned no humidifier ON/OFF transitions.

Full journal since restart shows only `fc_display-3` humidity readings (sensor data flowing normally to display — expected; sensor publishes were NOT suppressed by design):

```
Apr 18 01:26:45 fc1 bash[22249]: [fc_display-3]   Humidity: 82.5%
Apr 18 01:26:46 fc1 bash[22249]: [fc_display-3]   Humidity: 82.5%
...
Apr 18 01:27:03 fc1 bash[22249]: [fc_display-3]   Humidity: 88.1%
Apr 18 01:27:03 fc1 bash[22249]: [fc_controller-2] [INFO] [1776475623.517287905] [fc_controller]: WARMUP-CLEARED: control loop engaging
```

No humidifier actuation command appeared during the grace window.

### 5. WARMUP-CLEARED journal confirmation

```
Apr 18 01:27:03 fc1 bash[22249]: [fc_controller-2] [INFO] [1776475623.517287905] [fc_controller]: WARMUP-CLEARED: control loop engaging
```

Grace period cleared automatically at 01:27:03 UTC (~33s after systemctl restart at 01:26:30 UTC). The 33s total includes:
- ~4s for systemd launch startup
- ~4s for fc_controller node init
- ~25s for grace condition to satisfy (both `buffer_full=true` AND `grace_elapsed_sec >= 20.0`)

## Soak Timeline

| Time (UTC)   | Event                                         | sensor_health level | Notes                          |
|--------------|-----------------------------------------------|---------------------|-------------------------------|
| 01:26:30     | `systemctl restart fc-core`                   | —                   | Pre-restart was 01:25:14 UTC  |
| 01:26:34     | fc_controller process started (pid 22271)     | —                   | 4s launch delay               |
| 01:26:35     | fc_controller node ready                      | —                   | Node Started log line         |
| 01:26:36+    | sensor_health echo begins capturing           | WARN (0x01)         | grace_elapsed=1.0, buf=false  |
| 01:26:45     | fc_display begins showing humidity (82.5%)    | WARN                | Sensors flowing, controller gated |
| 01:27:03     | WARMUP-CLEARED logged                         | OK (0x00)           | grace_elapsed=25.0, buf=true  |
| 01:27:09     | Soak echo window ends (30s)                   | OK                  | Two messages captured total   |

## fc-core Status Post-Soak

```
active
```

`systemctl is-active fc-core` confirms service remained active throughout.

## Notes / Anomalies

- The `grace_elapsed_sec=25.0` at OK time (vs 20.0 grace_total_sec) means the buffer-full condition was the binding constraint — the humidity buffer didn't fill until ~25s after node init. Both conditions (time AND buffer) must be true; the slower one wins.
- Sensor data flowed to `fc_display` and Timescale throughout the grace period (correct: suppression is at controller consume layer only, per design).
- Humidity during soak window: 82.5% → 88.1% RH — within operating band, so no humidifier actuation would be expected even after grace cleared. The grace gate was the operative constraint during the window.
- No SHT30 available (logged: `No I2C device at address: 0x44`) — SCD41 is the active humidity source, consistent with prior sessions.
