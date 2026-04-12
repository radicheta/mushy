---
status: partial
phase: 10-bridge-qos-mjpeg-delivery
source: [10-VERIFICATION.md]
started: 2026-04-12T15:45:00Z
updated: 2026-04-12T15:45:00Z
---

## Current Test

[awaiting human testing]

## Tests

### 1. Bridge restart replays humidifier last-known state
expected: After `docker compose restart bridge` on elder-plops, the Mission Control humidifier-state chart immediately shows the correct last-known state — no blank gap. Log line `[bridge] Humidifier subscription: TRANSIENT_LOCAL QoS (replays last state on restart)` should appear.
result: [pending]

### 2. MJPEG delivers continuous frames for 60+ seconds
expected: `curl -s http://10.68.155.50:8081/camera/mjpeg --max-time 65 -o /dev/null -w "Downloaded %{size_download} bytes in %{time_total}s"` returns >100KB OR Mission Control camera feed shows continuous updates without freezing for 60s.
result: [pending]

### 3. No 192.168.1.193 phantom peer errors in fc-core logs
expected: `ssh ubuntu@100.96.239.75 "journalctl -u fc-core.service --since '5 minutes ago' | grep 192.168.1.193"` returns zero lines.
result: [pending]

## Summary

total: 3
passed: 0
issues: 0
pending: 3
skipped: 0
blocked: 0

## Gaps
