# Feature Landscape: Closed-Loop Humidity Control

**Domain:** Agricultural environmental control — mushroom fruiting chamber
**Researched:** 2026-03-28
**Confidence:** HIGH (core control strategy), MEDIUM (parameter values)

---

## Existing Implementation Audit

Before categorizing features, it is important to identify what is already present in
`fc_controller.py` and `fc_sensors.py`, so the roadmap builds on rather than duplicates work.

### Already Implemented (do not rebuild)

| Feature | Location | Notes |
|---------|----------|-------|
| Bang-bang humidity control with deadband | `fc_controller.py:160-163` | `target - tolerance` / `target + tolerance` thresholds |
| Humidifier GPIO on/off actuation | `fc_controller.py:116-120` | MOSFET via GPIO17 |
| DHT22 humidity sensor reading | `fc_sensors.py:49` | adafruit-dht library |
| Humidity ROS topic publication | `fc_sensors.py:68-71` | `fc/humidity` as RelativeHumidity |
| Config-driven setpoint and tolerance | `fc_config.yaml:14,19` | `target_humidity: 0.85`, `humidity_tolerance: 0.05` |
| Missing-sensor guard in control loop | `fc_controller.py:144` | Early return if humidity is None |
| Simulation mode with random walk | `fc_sensors.py:53-58` | Constrained to 50-100% range |

### Gaps (what the milestone must close)

| Gap | Symptom | Priority |
|-----|---------|----------|
| No minimum off-time protection | Humidifier can cycle on/off every 1s (control_interval), damaging ultrasonic units | Critical |
| No sensor outlier rejection | DHT22 spikes (documented: multi-hundred-percent readings) flow directly into control logic | Critical |
| MOSFET wiring not complete | Hardware not yet wired; listed as "TBD" in PROJECT.md | Blocking |
| Humidifier state not published as ROS topic | External systems (OpenMCT) cannot observe actuator state | High |
| Sensor normalization inconsistency | Real hardware: `humidity / 100.0`; simulation: raw fractional — bug risk | High |
| No setpoint topic publication | Target humidity not observable from outside the node | Medium |

---

## Table Stakes

Features growers expect. A system without these feels broken or untrustworthy.

| Feature | Why Expected | Complexity | Confidence |
|---------|--------------|------------|------------|
| Setpoint maintenance via bang-bang hysteresis | Industry standard for single on/off actuators; all consumer humidity controllers (Inkbird, etc.) use this exact pattern | Low — already structurally present | HIGH |
| Configurable setpoint and deadband in YAML | Growers need to adjust for species (Oyster: 85-95%, Lion's Mane: 80-90%); magic numbers in code are unacceptable | Low — already in config, validate values | HIGH |
| Sensor read on fixed interval with failure recovery | DHT22 requires 2s minimum between reads; retry on failure already present | Low — already implemented | HIGH |
| Humidifier on/off GPIO actuation | Single-bit control is the only sensible interface for a MOSFET-driven ultrasonic humidifier | Low — already implemented | HIGH |
| Actuator state observable via ROS topic | Controller state must be visible to OpenMCT and other nodes without parsing debug logs | Low — publish Bool to `fc/humidifier_state` | HIGH |
| Minimum off-time between humidifier cycles | Ultrasonic humidifiers require rest between activations to prevent overheating; relay life protection standard per Omron and Mycodo documentation | Low-Medium — add state timestamp check | HIGH |
| DHT22 spike rejection | DHT22 is documented to produce large erroneous spikes; a spike flowing into the control loop causes false actuation | Low — rolling window with deviation check | HIGH |

### Minimum off-time rationale

Omron's relay controller documentation states: "ON/OFF control can cause frequent output switching near the set point (chattering), which shortens relay life. The control period for relay outputs should be set to 20 seconds minimum."

Mycodo (the leading open-source mushroom controller on Raspberry Pi) implements `min_off_duration` specifically for devices damaged by rapid cycling. At a 1-second `control_interval` with a 5% deadband, the current implementation will cycle the humidifier every few seconds whenever humidity oscillates near the threshold — this is the most dangerous gap in the current design.

**Recommended value:** 30 seconds minimum off-time as config parameter `humidifier_min_off_seconds`. Adjustable; default of 30s is conservative and safe.

### DHT22 spike rejection rationale

Adafruit's DHT library documentation and community reports document DHT22 producing wildly incorrect values (e.g., 1546°C readings, humidity spikes to 0% or 100%) on timing-sensitive reads. The current `fc_sensors.py` publishes raw values with no validation. A reading deviating more than 15% RH from the previous valid reading should be discarded and the previous value retained.

**Recommended approach:** Keep a rolling buffer of the last 3 valid readings. Reject any reading that deviates more than 15% from the median. If 3 consecutive readings are rejected, log an error and publish the last known good value (stale data is safer than spike data for this actuator).

---

## Differentiators

Features that improve on the current timer-based solution and make this meaningfully better than consumer controllers.

| Feature | Value Proposition | Complexity | Confidence |
|---------|-------------------|------------|------------|
| Actuator state topic (`fc/humidifier_state`) | Enables OpenMCT dashboards, logging, and future alert logic without polling GPIO | Low | HIGH |
| Setpoint topic (`fc/humidity_setpoint`) | Allows remote setpoint visibility; growers see what the system is targeting, not just what it reads | Low | HIGH |
| Simulation mode that exercises control edge cases | Current simulation only does random walk in happy range; adding threshold-crossing simulation validates the control loop before hardware deployment | Medium | MEDIUM |
| Configurable hysteresis separate from setpoint | Current config uses single `humidity_tolerance` as symmetric deadband. Separating `humidity_lower_threshold` and `humidity_upper_threshold` makes the asymmetric mushroom range (e.g., turn on at 85%, off at 90%) explicit to growers | Low | HIGH |

### Asymmetric deadband rationale

Consumer mushroom growers universally configure humidity control as "turn on at X%, turn off at Y%" — not as "setpoint plus/minus tolerance". The current symmetric model (`0.85 +/- 0.05`) is equivalent, but the mental model for growers is the asymmetric form. Renaming or adding explicit `humidity_on_threshold` and `humidity_off_threshold` parameters eliminates confusion when growers try to configure the system.

The current config is functionally correct at default values (on below 80%, off above 90%). The feature is making this explicit, not changing behavior.

---

## Anti-Features

Features to explicitly not build in this MVP.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| PID humidity control | PID is appropriate for proportional actuators (valves, variable-speed pumps). A MOSFET-switched on/off humidifier has no proportional control surface. PID produces meaningless integral windup and output values that get rounded to on/off anyway. Bang-bang with hysteresis is the correct and industry-standard algorithm for this hardware. | Bang-bang hysteresis — already implemented |
| Tunable PID gains exposed to growers | Growers cannot tune KP/KI/KD. Parameters they cannot understand will be set wrong. The system must work correctly with no tuning beyond setpoint and deadband. | Config with only setpoint, deadband (or on/off threshold), and min-off-time |
| Humidity ramping / gradual setpoint changes | Complex to implement, adds state machine complexity, and the benefit (smoother approach to setpoint) is minimal for an on/off actuator. | Immediate setpoint control with adequate deadband |
| Predictive/feedforward humidity modeling | Requires knowing chamber volume, substrate evaporation rate, humidifier output — none of which are measured. Data to calibrate this does not exist at MVP. | Reactive feedback-only control |
| Dehumidification logic | No dehumidifier actuator exists in hardware. Excess humidity is handled by ventilation (fan). Adding humidity-lowering logic requires a second actuator type. | Defer: ventilation control is Phase 2 |
| Multi-species preset profiles | Different mushroom species have different humidity requirements but the mechanism is the same. Profiles are a UI concern, not a control concern. | Single configurable setpoint; profiles can be YAML variants |
| Web UI for setpoint adjustment | OpenMCT integration exists but setpoint write-back over ROS is out of scope. Config-file-driven setpoints are sufficient for MVP. | YAML config file change + restart |

---

## Feature Dependencies

```
MOSFET wiring complete
    -> Humidifier GPIO actuation (hardware path)
    -> Real-hardware control loop test

DHT22 spike rejection
    -> Reliable sensor readings
    -> Reliable control loop (humidifier won't false-fire on spikes)

Reliable sensor readings
    -> Bang-bang control loop (already structurally present)
    -> Minimum off-time enforcement (need accurate humidity to know when to re-enable)

Bang-bang control loop
    -> Actuator state topic publication
    -> Setpoint topic publication

Actuator state topic
    -> OpenMCT observability
```

### Critical path

The blocking dependency is MOSFET wiring. Everything else can be developed and tested in simulation. The minimum off-time and spike rejection features must be in place before first real-hardware test to protect the humidifier hardware.

---

## MVP Recommendation

### Must ship (blocking production)

1. **MOSFET wiring completed** — hardware prerequisite, not software
2. **DHT22 spike rejection in fc_sensors** — protects control loop from false actuation
3. **Minimum off-time in fc_controller** — protects humidifier hardware from cycling damage
4. **Sensor normalization bug fixed** — real hardware path divides by 100, simulation path does not; this must be consistent before any real-hardware test

### Should ship (high value, low effort)

5. **Actuator state topic** (`fc/humidifier_state` as std_msgs/Bool) — makes the system observable without reading logs
6. **Explicit on/off threshold config** — replace `target_humidity` + `humidity_tolerance` with `humidity_on_threshold` and `humidity_off_threshold` (functionally equivalent, grower-legible)

### Defer without regret

7. **Setpoint topic** — nice to have, not blocking production or grower operation
8. **Simulation edge-case improvements** — useful for testing but not blocking

---

## Parameter Recommendations

Based on mushroom industry standards (Oyster, Shiitake fruiting range):

| Parameter | Recommended Default | Rationale |
|-----------|--------------------|-----------|
| `humidity_on_threshold` | 0.85 (85%) | Turn humidifier on when humidity drops below this |
| `humidity_off_threshold` | 0.90 (90%) | Turn humidifier off when humidity exceeds this |
| `humidifier_min_off_seconds` | 30 | Conservative protection for ultrasonic units; matches Omron guidance |
| `sensor_read_interval` | 2.0s | DHT22 hardware minimum; cannot go lower |
| `control_interval` | 5.0s | Increase from current 1.0s — no benefit to checking faster than sensor updates |
| DHT spike threshold | 0.15 (15% RH) | Reject readings deviating >15% from 3-sample median |

Note: Current `control_interval: 1.0` runs the control loop faster than the sensor updates (`sensor_read_interval: 2.0`). Half the control cycles see stale data. Increasing `control_interval` to 5.0s reduces CPU and makes the timing relationship explicit without affecting control quality for a slow-response system like humidity.

---

## Sources

- [Omron — ON/OFF Control and Relay Protection](https://www.ia.omron.com/support/guide/53/explanation_of_terms.html) — relay minimum period guidance (HIGH confidence, official)
- [Mycodo Functions Documentation](https://kizniche.github.io/Mycodo/Functions/) — min_off_duration pattern for Raspberry Pi environmental control (HIGH confidence, official open-source project)
- [ESPHome Bang-Bang Climate Component](https://esphome.io/components/climate/bang_bang/) — deadband/hysteresis behavior definition (HIGH confidence, official)
- [x-engineer.org On-Off Control](https://x-engineer.org/on-off-control-system/) — hysteresis trade-offs, switching frequency vs overshoot (MEDIUM confidence, technical reference)
- [Adafruit DHT22 Overview](https://learn.adafruit.com/dht) — 2s minimum read interval, spike behavior (HIGH confidence, official hardware docs)
- [Mushroom Humidity Control — Redwood Mushroom Supply](https://www.redwoodmushroomsupply.com/blogs/mushroom-cultivation/controlling-humidity-and-why-it-s-important-for-mushroom-cultivation) — grower target range 85-95%, on/off threshold mental model (MEDIUM confidence, domain practitioner)
- [Zombie Myco — Humidifier Control for Mushrooms](https://zombiemyco.com/blogs/mushroom-teks/humidifiers-for-mushroom-growing-do-they-work) — Inkbird-style controller as grower standard (MEDIUM confidence, practitioner)
- [Multitech — Hysteresis](https://multitech.com/iot-wiki/hysteresis/) — definition and deadband behavior (MEDIUM confidence)
