# Phase 27: PID + time-proportional duty-cycle primitive — Context

**Gathered:** 2026-05-01
**Status:** Ready for planning

<domain>
## Phase Boundary

Replace bang-bang humidifier control with a PID loop that emits a 0.0–1.0 duty-cycle setpoint, driven onto the existing SSR via a slow-PWM actuator layer. Closes the structural ±2% RH ceiling proven 2026-04-11 (calibration data on disk).

This phase ships the **primitive only** — Phase 28 wraps it in named modes (`fruiting`, `pinning`). The mode primitive, runtime config delivery, and farmer-facing mode switch are out of scope here.

In scope: `HUMID-01..04` (controller publishes duty; slow-PWM actuator translates to relay windows; gains tunable as ROS params; ±0.5% over 2h farmer-attested).

</domain>

<decisions>
## Implementation Decisions

### Architecture — topic boundary

- **D-01:** Duty cycle is published as `fc1/actuators/humidifier_duty` (`std_msgs/Float32`, range **0.0–1.0**) on every control tick. This is the contract between the PID stage and the actuator stage.
- **D-02:** Scale is **0.0–1.0**, not 0–100%, so the duty topic overlays cleanly with the existing `fc1/actuators/humidifier` Bool on a single Mission Control plot (operator can eyeball "what PID asked for" vs "what the relay did" on one chart). Wording correction to HUMID-01: requirement text says "0–100%"; the topic contract is 0.0–1.0.
- **D-03:** A new slow-PWM driver subscribes to `humidifier_duty` and owns the GPIO27 toggling. fc_controller no longer touches the humidifier GPIO directly. Whether the driver is a separate ROS node, a sibling executable in `fc_core`, or a class with its own timer inside the existing controller process is the planner's call — only the topic contract is locked.

### PID design

- **D-04:** **Single fixed PID gain set**, tuned for near-setpoint operation (~15% steady-state duty per calibration). Gain scheduling deferred. Revisit only if HUMID-04 soak shows unacceptable recovery sluggishness in practice.
- **D-05:** Gains exposed as ROS params (`pid_kp`, `pid_ki`, `pid_kd`); defaults derived from 2026-04-11 system-ID data (rise rate ~0.8 %/min near setpoint, decay rate ~0.7 %/min, dead time ~16s, steady-state duty ~15%). Picking the actual numbers is the planner/researcher's call.
- **D-06:** **Bumpless transfer** on PID startup and on recovery from stale-sensor safe state: integrator pre-loaded so the first few windows don't slam. Avoids a 100% duty spike every time the loop re-engages.
- **D-07:** **Setpoint-change ramp**: when `target_humidity` changes (Phase 28+ mode switches) the *output* duty slews over a few seconds rather than stepping. Exact slew duration = Claude's discretion (target: smooth enough that the operator doesn't see an instant slam on mode switch).

### Slow-PWM actuator behavior

- **D-08:** **PWM window length = 120s** (fixed, locked). Resolves the collision between the empirical 10s min-fog-pulse (D-11) and the ~15% steady-state operating duty: at 120s windows, 10s min ON pulse = 8.3% min effective duty, comfortably under the operating point. See DISCUSSION-LOG.md for the full collision analysis.
- **D-09:** **Bypass mode ("Mode C")**: when `|error| > bypass_threshold`, slow-PWM is suspended and the humidifier holds **full ON open-loop** until error returns inside the threshold. PID + slow-PWM resume once inside. This sidesteps the 5× rise/decay nonlinearity at recovery (calibration finding §System Identification) without needing a second PID gain set.
- **D-10:** `bypass_threshold` is a tunable ROS param. Default = Claude's discretion (target: well outside the ±0.5% attestation band but inside any reasonable mode-switch step — likely 2–3% RH).
- **D-11:** **Min effective ON pulse: 10s** (empirical fog-visibility floor measured by farmer 2026-05-01). Within slow-PWM, if PID-requested duty × window < 10s, emit 0 for that window (round down). Keeps the actuator from issuing pulses too short to physically produce mist. Tunable as `min_pulse_seconds`.
- **D-12:** **Rolling max-duty cap** as belt-and-suspenders for water consumption — duty averaged over a 5-minute rolling window is capped (Claude's discretion on default value; spec it as a tunable param). Prevents a stuck-high integrator from draining the tank in an afternoon.

### Safety semantics — what carries over, what changes

- **D-13:** **Sensor-stale safe state preserved.** If humidity reading is older than `sensor_stale_timeout`, duty is forced to 0.0 immediately (no slew, bypasses ramp D-07). Same contract as Phase 03 D-09/D-10/D-11.
- **D-14:** **Startup grace preserved** (Phase 15). No actuation until `_grace_active()` clears; duty = 0.0 during warmup. Sensor_health WARN→OK transition unchanged.
- **D-15:** **`min_dwell_time` is removed/deprecated** as a humidifier parameter. Rationale: SSR-10A is solid-state and has no mechanical-cycling wear concern; the 180s dwell guard was the structural cause of the ±2% ceiling per calibration findings. Window length (D-08) is the new safety floor — there is no SSR-edge minimum-gap constraint.

### Acceptance — HUMID-04

- **D-16:** **±0.5% RH over a 2-hour soak**, farmer-attested on Mission Control. Pass criteria: trace stays inside ±0.5% band, zero "DWELL-BLOCK"-equivalent log lines, no operator-visible humidifier slam on grace-clear or recovery. Soak runs against slot-1 humidity (D-17).

### Sensor source

- **D-17:** PID input = `fc1/humidity` (slot-1). Phase 26 D-01 silent SHT30→SCD41 fallback preserved unchanged. The PID does not see slot-2 (`fc1/humidity_2`). Mode-aware sensor selection deferred to v1.6.

### Claude's Discretion

- D-05 default Kp/Ki/Kd values (research from calibration data)
- D-07 setpoint-ramp slew duration
- D-10 `bypass_threshold` default
- D-12 rolling max-duty cap default
- Anti-windup mechanism (clamping vs back-calculation)
- Derivative-on-measurement vs derivative-on-error; D-term filtering
- Physical packaging of the slow-PWM driver (separate node, sibling exe, or in-process class) — topic contract D-01 is what's locked
- Param naming under D-08/D-11 once the planner picks YAML keys

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Calibration + design rationale
- `.planning/phases/999.9-pid-time-proportional-humidity-control/CALIBRATION-FINDINGS-2026-04-11.md` — system ID data (rise/decay rates, dead time, steady-state duty estimate); the structural argument for why bang-bang+dwell caps at ±2%; PID design recommendations including the window-length range and the "replace min_dwell with min_window_duration" semantic shift this CONTEXT acted on
- `.planning/REQUIREMENTS.md` §HUMID — the four phase requirements (HUMID-01..04). Note D-02 wording correction: HUMID-01 topic scale is 0.0–1.0, not 0–100%

### Code — rewrite target
- `src/chambers/fc-core/fc_core/fc_controller.py` — current bang-bang `control_loop()` + `_set_humidifier_with_dwell()` (lines ~190–230, 327–400); this is what gets refactored. Preserve `_grace_active()`, stale-detection branch, sensor_health publish-on-change pattern, and the safe-state OFF on sensor failure
- `src/chambers/fc-core/config/fc_config.yaml` — `target_humidity`, `humidity_tolerance`, `min_dwell_time` (to be removed), `sensor_stale_timeout`, `humidifier_pin`. New params land here

### Contracts preserved
- `.planning/phases/26-dual-sensor-publishing-offline-alarms-sht30-scd41-slot-topic/26-CONTEXT.md` — D-01 slot-1 silent-fallback contract; this CONTEXT D-17 inherits it directly
- `.planning/phases/15-sensor-warmup-grace-period/` — startup grace contract preserved (D-14)
- `.planning/phases/16-system-health-panel/` — sensor_health DiagnosticStatus contract; new actuator topic should not break flatten-for-browser pattern
- Phase 04 ACTR-03 — `fc1/actuators/humidifier` Bool with TRANSIENT_LOCAL QoS stays as-is (slow-PWM driver writes it on every toggle); D-02's overlay-on-one-chart depends on this remaining

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable assets
- `fc_controller.py` already has the structure for an iterative control loop (timer tick, sensor staleness check, safe-state OFF, grace gating). PID computation slots into the existing tick.
- TRANSIENT_LOCAL QoS pattern is already established (`humidifier_state_pub`, `sensor_health_pub`) — the new `humidifier_duty` topic should follow the same QoS so late-joining subscribers see last-known duty (Mission Control bridge will).
- `_publish_sensor_health()` publish-on-change-only pattern (Phase 16) is the right model for any new diagnostic topics this phase adds.

### Established patterns
- ROS params declared in `__init__` with `declare_parameters` and read via `get_parameter().value` per tick — new PID/PWM params follow same pattern.
- Gap-over-noise (memory `feedback_gap_over_noise`): when sensor is stale, *don't* keep emitting last duty — drop to 0.0. Already locked in D-13.
- ros2 launch + systemd Restart=always (memory `feedback_systemd_restart_ros2_launch`): if the slow-PWM driver lands as a new ROS node launched via `ros2 launch`, the systemd unit needs `Restart=always` (not on-failure).

### Integration points
- New topic `fc1/actuators/humidifier_duty` — bridge needs to subscribe (telemetry WS forwarding) and farmer-app/Mission Control need to know about it for charting; D-02 overlay layout is a follow-up Mission Control config change (composes naturally with backlog 999.17 overlay-plot work — note for later).
- TimescaleDB `telemetry` hypertable already ingests scalar topics from the bridge — duty cycle should land there automatically once bridge subscribes.
- `min_dwell_time` removal (D-15) — anywhere this param is referenced (config, docs, alerter rules referencing dwell behavior) needs updating; planner's job to sweep.

</code_context>

<specifics>
## Specific Ideas

- **Operator visualization is a first-class design constraint.** The 0.0–1.0 scale (D-02) was chosen explicitly so duty + relay-state share an axis on Mission Control. Don't rescale to 0–100% downstream "for readability."
- **Window length 120s is locked, not "research and decide."** It came out of a specific collision analysis: 10s min-fog-pulse vs ~15% steady-state duty. See DISCUSSION-LOG.md §Safety floor for the full reasoning. Don't second-guess it from generic PWM literature.
- **Mode C (full-ON bypass for far-from-setpoint) is the chosen substitute for gain scheduling.** Calibration recommends gain scheduling for the 5× nonlinearity; this CONTEXT trades that for an open-loop pull-up regime instead — simpler to reason about, simpler to attest. Revisit only if it's visibly inadequate during HUMID-04 soak.
- **The 10s fog floor is empirical, not a guess.** Farmer measured time-to-visible-fog from the nozzle on 2026-05-01. If a future humidifier swap changes this, `min_pulse_seconds` is tunable.

</specifics>

<deferred>
## Deferred Ideas

- **Per-mode PID gains** — different gains per mode (fruiting vs pinning) — v1.6 candidate per REQUIREMENTS line 47.
- **Zone gain scheduling within a single mode** — only if HUMID-04 soak shows recovery is too slow under D-04's near-setpoint-tuned single set.
- **Mode-aware sensor selection** (trust SHT30 RH during incubation, SCD41 RH during fruiting) — gated on SCD41-clipping investigation (Phase 26 known issue), v1.6.
- **PID auto-tuning** — out of scope per REQUIREMENTS line 55; manual tune from calibration data is sufficient.
- **Mission Control overlay layout for duty + relay state on one chart** — composes with backlog 999.17 (overlay plots); defer the layout config until 999.17 lands or until the farmer asks for it on this specific data pair.
- **`min_dwell_time` deprecation sweep across docs/alerter** — Phase 27 removes the param; if alerter or any other agent references dwell-block-style semantics, a follow-up sweep can clean it up — not blocking the controller refactor.

</deferred>

---

*Phase: 27-pid-time-proportional-duty-cycle-primitive*
*Context gathered: 2026-05-01*
