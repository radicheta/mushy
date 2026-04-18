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
result: partial — farmer reported 3 green / 3 grey on fresh page load 2026-04-18. Green: Bridge + Pi + Humidifier. Grey: Sensors + Grace + Camera (Camera is correct; Sensors/Grace was the known gap, now addressed by Phase 16.1).

### 2. Sensor/Grace replay policy decision
expected: Farmer decides whether the known gap — Sensors and Grace lights show grey on fresh page load until next fc_controller state transition — is acceptable as shipped, or whether to prioritize the bridge-side "cache last sensor_health and replay to new WS clients" fix.
result: resolved — farmer chose the fix. Phase 16.1 shipped commit `3ccece1`: bridge caches last sensor_health broadcast and replays to every new WS client on connect. In-container test confirmed level=0 delivered immediately on connect. Fresh page loads should now show Sensors + Grace as green.

### 3. Post-16.1 visual re-check
expected: After a hard-refresh (Ctrl+Shift+R) of Mission Control, Sensors and Grace lights should now be green on page load without needing to wait for an fc_controller state transition.
result: passed — farmer reported "all green" after hard-refresh 2026-04-18. All 6 lights green: Sensors, Grace, Camera feed, Humidifier, Bridge, Pi reachable. Farmer quote: "i wanna see a panel of green lights like the farmer said!" — goal met.

## Summary

total: 3
passed: 1
issues: 0
pending: 0
skipped: 0
blocked: 0
resolved: 2

## Gaps

_None. Phase 16 UAT complete — farmer-attested "all green"._
