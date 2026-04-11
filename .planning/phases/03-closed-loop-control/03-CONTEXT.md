# Phase 3: Closed-Loop Control - Context

**Gathered:** 2026-04-04
**Status:** Ready for planning

<domain>
## Phase Boundary

Complete the control algorithm so it maintains humidity setpoint, won't damage the actuator through rapid cycling, and fails safe when sensor data is missing or stale. The existing bang-bang skeleton in `control_loop()` is the starting point — this phase fills in the missing safety guards and makes thresholds configurable.

No new topics, no new actuators, no observability work. Control logic only.

</domain>

<decisions>
## Implementation Decisions

### Config naming (CTRL-02)
- **D-01:** Keep existing parameter names (`target_humidity`, `humidity_tolerance`) — they're already grower-readable and deployed on FC-1. Renaming would break the live config.
- **D-02:** Add new params to `fc_config.yaml` with descriptive comments. New params: `min_dwell_time`, `sensor_stale_timeout`.
- **D-03:** The existing bang-bang logic at `fc_controller.py:164-168` already uses `target_humidity ± humidity_tolerance` as the hysteresis band. CTRL-01 is partially satisfied — needs dwell time and staleness guards to be complete.

### Minimum dwell time (CTRL-03)
- **D-04:** Default `min_dwell_time: 300.0` (5 minutes) in `fc_config.yaml`. Mushroom chambers need time to respond to humidity changes; SSR-10A + ultrasonic humidifier can physically toggle faster but the chamber dynamics can't.
- **D-05:** Track `_last_humidifier_toggle` timestamp in the controller. When `set_humidifier()` is called with a state change, check elapsed time since last toggle. If under dwell time, skip the change and log at DEBUG level.
- **D-06:** Dwell time applies to both ON→OFF and OFF→ON transitions equally.

### Staleness detection (CTRL-04)
- **D-07:** Default `sensor_stale_timeout: 10.0` (10 seconds) in `fc_config.yaml`. At 2s sensor interval, this means 5 missed reads.
- **D-08:** Track `_last_humidity_timestamp` in `humidity_callback()` — update it each time a message arrives (use `self.get_clock().now()`).
- **D-09:** In `control_loop()`, check if current time minus `_last_humidity_timestamp` exceeds `sensor_stale_timeout`. If stale → enter safe state.

### Safe state (CTRL-05)
- **D-10:** Safe state = humidifier OFF. Log at WARN level on entry ("Sensor data stale — humidifier OFF for safety").
- **D-11:** Auto-recover when fresh data arrives — no manual reset or restart needed. Log at INFO level on recovery ("Fresh sensor data received — resuming control").
- **D-12:** The existing `if self.current_humidity is None: return` at line 149 must be changed to explicitly call `set_humidifier(False)` instead of silently returning (which freezes the last state — unsafe).
- **D-13:** Fans and lights are unaffected by humidity safe state — they serve different purposes and have independent control paths.

### Claude's Discretion
- Exact placement of dwell time check (inside `set_humidifier` vs in `control_loop` before calling it)
- Whether to add a `_safe_state_active` boolean flag for cleaner logging (avoid repeated WARN on every control tick)
- Test structure and simulation helpers for the new behaviors

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Core Source Files
- `src/chambers/fc-core/fc_core/fc_controller.py` — control loop (line 148), bang-bang logic (lines 164-168), humidity_callback (line 97), set_humidifier (line 121)
- `src/chambers/fc-core/config/fc_config.yaml` — add min_dwell_time and sensor_stale_timeout here
- `src/chambers/fc-core/fc_core/test/test_controller.py` — existing tests to extend with dwell time, staleness, and safe state cases

### Prior Phase Context
- `.planning/phases/02-safety-hardening/02-CONTEXT.md` — D-02 established that filter lives in controller (not sensor); D-01 chose rolling median with 5-sample window

### Requirements
- `CTRL-01` — Bang-bang hysteresis control (partially exists, needs guards)
- `CTRL-02` — Configurable setpoint and deadband (exists, add new params)
- `CTRL-03` — Minimum dwell time
- `CTRL-04` — Stale sensor data detection
- `CTRL-05` — Sensor failure → safe state (OFF)

No external ADRs or specs — requirements fully captured in decisions above.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `set_humidifier(state)` at line 121 — already abstracts sim vs GPIO; dwell time guard can wrap this or be added to `control_loop`
- `get_humidifier_state()` at line 138 — returns current state, useful for detecting state changes in dwell time logic
- `self._humidity_buffer = deque(maxlen=5)` at line 84 — rolling median buffer from Phase 2; timestamp tracking should be added alongside this
- `self.get_clock().now()` — ROS2 clock available on the node for timestamps (consistent with sim time if ever used)

### Established Patterns
- Parameters declared in `__init__` via `declare_parameters()`, read via `get_parameter().value` — new params follow this pattern
- Simulation mode split: `actuator_simulation_mode` gates GPIO vs software state — all new logic must work in both modes
- Control loop runs on a timer (`control_interval: 1.0s`) — staleness check happens every tick

### Integration Points
- `humidity_callback` (line 97) — add timestamp tracking here
- `control_loop` (line 148) — add staleness check before existing logic, add dwell time check around humidifier control
- `fc_config.yaml` — add `min_dwell_time` and `sensor_stale_timeout` under existing parameters

</code_context>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches. The goal is "better than timer" — the control loop should be conservative and safe, not clever.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 03-closed-loop-control*
*Context gathered: 2026-04-04*
