# Phase 26: Dual sensor publishing + offline alarms — Context

**Gathered:** 2026-04-20
**Status:** Ready for planning

<domain>
## Phase Boundary

Publish SHT30 and SCD41 on separate slot topics so the farmer has a live second opinion on temperature/humidity, and fire Signal alerts when either sensor goes offline.

- Slot 1: `fc1/temperature` + `fc1/humidity` — SHT30 primary, SCD41 silent fallback (current behavior preserved)
- Slot 2: `fc1/temperature_2` + `fc1/humidity_2` — SCD41 always, independent of slot 1
- Offline alarms via Signal when a sensor stops reporting for ≥ 5 minutes

Motivation: 2026-04-11 calibration session lost 40 min to an unnoticed SHT30 outage; SCD41 RH suspected ~4% high vs external meters.

</domain>

<decisions>
## Implementation Decisions

### Publishing Model
- **D-01:** Slot 1 keeps the existing silent-fallback behavior — when SHT30 is unavailable, SCD41 values publish on `fc1/temperature` / `fc1/humidity` with no flag or gap. Controller continues to consume slot 1 unchanged.
- **D-02:** Slot 2 (`fc1/temperature_2`, `fc1/humidity_2`) publishes SCD41 readings unconditionally and independently of slot 1 — never gated on SHT30 state.
- **D-03:** Only publish a slot when the underlying physical sensor has a fresh reading (don't fabricate, don't repeat stale values). Gaps on slot 2 are acceptable and expected.

### Offline Alarms
- **D-04:** Offline threshold: **5 minutes** of no fresh readings from a given physical sensor triggers a Signal alert.
- **D-05:** Per-sensor granularity — SHT30 offline and SCD41 offline are distinct alerts.
- **D-06:** Recovery message fires when a sensor resumes publishing after an offline alert (symmetric with existing alerter behavior).

### Claude's Discretion
- Exact mechanism for offline detection (extend Pi-side `sensor_health` from Phase 16 to report per-sensor freshness, or alerter-side topic-silence watchdog, or both) — planner decides based on smallest diff to live code.
- Cooldown / dedup policy — reuse whatever the existing alerter (`src/agents/alerter`) already does for `pi_liveness` and `sensor_health` alerts; don't invent a parallel mechanism.
- Downstream consumer updates (Mission Control panels, farmer dashboard, FarmOS writer) — only update surfaces where slot 2 adds clear operator value; don't blanket-wire every consumer.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Sensor publishing
- `src/chambers/fc-core/fc_core/fc_sensors.py` — current single-slot publisher; starting point for dual-slot refactor
- `src/chambers/fc-core/config/fc_config.yaml` — sensor params (sht30_i2c_address, scd41_enabled, sensor_read_interval)

### Health + alerts
- `src/agents/alerter/src/index.js` — existing alerter; already consumes `sensor_health` and `pi_liveness`
- `src/agents/alerter/src/rules.js` — alert rule engine; extend here rather than duplicate
- Phase 16 artifacts in `.planning/phases/16-system-health-panel/` — `sensor_health` topic contract

### Prior context
- `.planning/STATE.md` §Roadmap Evolution — Phase 26 motivation and slot-topic naming rationale
- `.planning/phases/999.11-farmer-app/FARMER-APP-NOTES-2026-04-11.md` — 40-minute SHT30-offline incident that motivated offline alarms

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `fc_sensors.py` — single-node publisher already holds both sensor handles (`self.sht`, `self.scd`); add two more publishers and a per-sensor freshness counter/timestamp
- `sensor_health` topic (Phase 16) — already aggregates sensor state; natural place to extend per-sensor offline flags
- `alerter` agent — already subscribes to `sensor_health`; extending its rules is cheaper than a new alert path

### Established Patterns
- ROS2 publishers created once in `__init__`, pushed on timer tick (2s default)
- Alerter rules return `{level, message}` tuples; Signal delivery is centralized in `signal.js`
- Gap-over-noise: skip publish when value unavailable (already the pattern for CO2 when SCD41 not ready)

### Integration Points
- New topics `fc1/temperature_2`, `fc1/humidity_2` — consumers to consider: bridge telemetry WS, farmer dashboard cards, FarmOS writer, any Mission Control panels
- `sensor_health` extension — bridge already flattens `DiagnosticStatus` KeyValue[] for browser; keep that contract

</code_context>

<specifics>
## Specific Ideas

- Alert wording should make it impossible to miss which physical sensor is offline (SHT30 vs SCD41) — the 2026-04-11 incident was specifically "didn't notice SHT30 was gone."
- Slot 1 silent fallback is intentional: it keeps the PID-less ±1% control loop fed without requiring controller changes in this phase.

</specifics>

<deferred>
## Deferred Ideas

- Per-slot `sensor_source` telemetry flag so consumers can tell which physical sensor backed a slot 1 reading — useful once trend/graph UI cares, not needed for this phase.
- Cross-sensor drift detection (flag when slot 1 and slot 2 diverge > X%) — different phase; requires agreeing on the "truth" sensor first.
- RH bias correction on SCD41 readings — waits on real calibration against external meters; out of scope here.

</deferred>

---

*Phase: 26-dual-sensor-publishing-offline-alarms-sht30-scd41-slot-topic*
*Context gathered: 2026-04-20*
