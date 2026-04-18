---
status: partial
phase: 16-system-health-panel
source: [16-VERIFICATION.md]
started: 2026-04-18
updated: 2026-04-18
---

## Current Test

[awaiting human testing]

## Tests

### 1. Visual browser smoke
expected: Open Mission Control → expand "Fruiting Chamber FC-1" → click "System Health". Six lights render in one horizontal strip. Bridge/Pi/Humidifier/Sensors/Grace green, Camera grey (no viewer active). No DevTools console errors.
result: [pending]

### 2. Sensor/Grace replay policy decision
expected: Farmer decides whether the known gap — Sensors and Grace lights show grey on fresh page load until next fc_controller state transition — is acceptable as shipped, or whether to prioritize the bridge-side "cache last sensor_health and replay to new WS clients" fix.
result: [pending]

## Summary

total: 2
passed: 0
issues: 0
pending: 2
skipped: 0
blocked: 0

## Gaps

_None yet — pending human review._
