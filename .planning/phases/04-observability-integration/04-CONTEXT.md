# Phase 4: Observability & Integration - Context

**Gathered:** 2026-04-04
**Status:** Ready for planning

<domain>
## Phase Boundary

System fully integrated: all sensor and actuator state visible in ROS topics AND in the OpenMCT browser dashboard. Full control loop verified end-to-end on FC-1 hardware with soak test.

No new control logic, no new actuators. Observability and validation only.

</domain>

<decisions>
## Implementation Decisions

### Actuator state publishing (ACTR-03)
- **D-01:** Publish humidifier state as `std_msgs/Bool` on `fc/actuators/humidifier` with `TRANSIENT_LOCAL` QoS durability — satisfies ACTR-03 spec exactly.
- **D-02:** Also publish all available actuator/sensor data for logging. Current telemetry: temperature, humidity, CO2 (SCD41), humidifier on/off, fan speed, light state. Lower refresh rate acceptable for logging topics.
- **D-03:** Design for extensibility — more sensors will be connected later. Topic structure should accommodate new data sources without restructuring.

### OpenMCT bridge and dashboard
- **D-04:** Full OpenMCT integration — add CO2 (`fc/co2`, Float32) and actuator state (`fc/actuators/humidifier`, Bool) to both the WebSocket bridge (`src/mission-control/bridge/src/index.js`) and the OpenMCT plugin (`src/mission-control/frontend/plugins/fruiting-chamber/plugin.js`).
- **D-05:** Live charts in browser for all telemetry: humidity, temperature, CO2, humidifier state. Existing plugin pattern (SENSORS array with extract function) is the template for new entries.

### Hardware validation (TEST-02)
- **D-06:** Breath test from this session (SCD41 → controller → SSR lamp toggle, 65% → 92% → 69%) validates the control loop end-to-end but does NOT satisfy TEST-02 fully.
- **D-07:** Soak test required: run system for 1+ hours with real humidifier in the actual fruiting chamber. This is gated by physical Pi relocation from lab to farm.
- **D-08:** Remote access (WireGuard over internet) is a blocker for soak test but is deferred as a separate network issue — not Phase 4 scope.

### Already completed (this session)
- **D-09:** ACTR-01 satisfied: SSR on GPIO27 verified toggling 220V load (lamp test).
- **D-10:** SENS-02 satisfied: humidity published correctly on `fc/humidity` in 0.0-1.0 range from SCD41.
- **D-11:** SCD41 CO2 sensor integrated into fc_sensors.py, publishing on `fc/co2` (Float32). Falls back to SCD41 temp/humidity when SHT30 is absent.
- **D-12:** Fan hardware PWM made optional — controller starts without rpi_hardware_pwm installed.
- **D-13:** Humidifier pin moved from GPIO17 to GPIO27 (adjacent pin layout for SSR fichita connector).

### Claude's Discretion
- QoS profile details for non-actuator topics (CO2, fan speed, light state)
- OpenMCT chart axis ranges and display formatting for CO2 (ppm) and boolean actuator state
- Whether to add a combined "system status" endpoint or keep individual topics

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Core Source Files
- `src/chambers/fc-core/fc_core/fc_controller.py` — add actuator state publisher here; humidifier/fan/light getters already exist
- `src/chambers/fc-core/fc_core/fc_sensors.py` — SCD41 + SHT30 sensor node; already publishes fc/temperature, fc/humidity, fc/co2
- `src/chambers/fc-core/config/fc_config.yaml` — current config with GPIO27 humidifier, SCD41 enabled, actuator_simulation_mode false

### OpenMCT Integration
- `src/mission-control/bridge/src/index.js` — WebSocket bridge subscribing to ROS topics; add fc/co2 and fc/actuators/humidifier subscriptions
- `src/mission-control/frontend/plugins/fruiting-chamber/plugin.js` — OpenMCT telemetry plugin; SENSORS array pattern for adding new data sources

### Requirements
- `ACTR-03` — Actuator state topic: `fc/actuators/humidifier`, `std_msgs/Bool`, `TRANSIENT_LOCAL`
- `TEST-02` — Full control loop verified on real FC-1 hardware
- `SENS-02` — Humidity in consistent 0.0-1.0 range (already satisfied)

### Prior Phase Context
- `.planning/phases/03-closed-loop-control/03-CONTEXT.md` — bang-bang control decisions, dwell time, staleness guards
- `.planning/notes/2026-03-29-humidity-display-openmct.md` — note about getting live data into OpenMCT dashboard

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `fc_controller.py` `get_humidifier_state()`, `get_fan_speed()`, `get_light_state()` — all actuator state getters exist, just need a publisher
- `plugin.js` SENSORS array — declarative pattern for adding telemetry; each entry has identifier, name, unit, topic, msgType, extract function
- `index.js` WebSocket bridge — simple ROS subscription → broadcast pattern, easy to extend with new topics

### Established Patterns
- ROS topics follow `fc/{sensor_type}` naming (fc/temperature, fc/humidity, fc/co2)
- Actuator topics should follow `fc/actuators/{actuator_name}` per ACTR-03
- OpenMCT plugin uses `fruiting-chamber` namespace with dot-separated keys (fc.humidity, fc.temperature)
- Bridge broadcasts JSON with value + timestamp to all WebSocket clients

### Integration Points
- Controller's `control_loop()` already calls getters each tick — add publish calls alongside existing debug log
- Bridge needs new ROS subscriptions for fc/co2 (Float32) and fc/actuators/humidifier (Bool)
- Plugin SENSORS array needs new entries for CO2 and humidifier state

</code_context>

<specifics>
## Specific Ideas

- User wants to log ALL available data, not just minimum for requirements — design for future sensors
- Lower refresh rate is acceptable for observability topics (don't need 1s updates for dashboard)
- The SCD41 is already providing CO2 + temp + humidity — this is bonus data beyond original MVP scope

</specifics>

<deferred>
## Deferred Ideas

- **Remote WireGuard access over internet** — needed for soak test when Pi moves to farm, but separate from observability code. Requires pfSense port forwarding or relay. Not Phase 4 scope.
- **Actuator bundle message** — custom msg with all actuator states in one message. Rejected in favor of individual topics per actuator for simplicity and ACTR-03 compliance.
- **TimescaleDB telemetry storage** — docker-compose has a timescale service defined but not wired. Future phase for historical data.

</deferred>

---

*Phase: 04-observability-integration*
*Context gathered: 2026-04-04*
