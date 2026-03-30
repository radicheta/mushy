# Phase 2: Safety Hardening - Context

**Gathered:** 2026-03-30
**Status:** Ready for planning

<domain>
## Phase Boundary

Fix the critical bugs that make it unsafe to run on real hardware. Four concrete fixes: audit/confirm non-blocking sensor error handling, fix sensor normalization, add spike rejection, make humidifier pin configurable, fix broken test assertions. Clean up config to match actual hardware (SHT30, SSR-10A).

No new capabilities. No control logic changes. Bug fixes and config hygiene only.

</domain>

<decisions>
## Implementation Decisions

### Spike Rejection (SENS-05)
- **D-01:** Use **rolling median** over a **5-sample window** — not rolling average (spikes skew average; median is immune to single outliers)
- **D-02:** Filter lives in **`fc_controller.py`** on the receive side — sensors publish raw truth, controller decides what to act on. Cleaner separation of concerns for ROS design.
- **D-03:** At 2s sensor interval, 5 samples = ~10s window. Acceptable lag for mushroom humidity dynamics.

### Sensor Error Handling (SENS-03)
- **D-04:** Keep it simple — log every error at `ERROR` level, skip the sample. No consecutive failure counters, no log rate limiting.
- **D-05:** Audit confirms: no `time.sleep()` exists in the current exception handler in `fc_sensors.py`. SENS-03 is a verification task, not a code change.

### Config Cleanup (ACTR-02 + SENS-04)
- **D-06:** Add `humidifier_pin: 17` to `fc_config.yaml` and read it from params in `fc_controller.py` (currently hardcoded at line 49)
- **D-07:** Remove `dht_pin: 4` from config — wrong sensor, no longer used
- **D-08:** Update all DHT22 comments/references in config to say SHT30
- **D-09:** Add `sht30_i2c_address: 0x44` to `fc_config.yaml` — currently declared as a node param but absent from yaml, making it untunable without editing code

### Test Assertions (TEST-01)
- **D-10:** Fix `test_controller.py` lines 66 and 73 — currently assert `node.humidifier_pin == 1/0` (tests the GPIO pin number, not the state). Should assert `node.humidifier_state == True/False`.

### Sensor Normalization (SENS-04)
- **D-11:** Audit confirms: both real and sim paths in current `fc_sensors.py` produce 0-100 before the `/100.0` division, publishing 0-1 to the topic. This is already consistent. SENS-04 is a verification task; cleanup is covered by D-07/D-08.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Core Source Files
- `src/chambers/fc-core/fc_core/fc_sensors.py` — sensor node; exception handler to audit, normalization to verify
- `src/chambers/fc-core/fc_core/fc_controller.py` — controller node; hardcoded humidifier_pin (line 49), add rolling median filter here
- `src/chambers/fc-core/fc_core/test/test_controller.py` — broken test assertions (lines 66, 73)
- `src/chambers/fc-core/config/fc_config.yaml` — config to clean up (add humidifier_pin, remove dht_pin, add sht30_i2c_address)

### Requirements
- `SENS-03` — Non-blocking sensor error handling
- `SENS-04` — Sensor normalization consistency
- `SENS-05` — Spike rejection
- `ACTR-02` — Humidifier pin configurable
- `TEST-01` — Test assertions test actuator state, not pin number

No external ADRs or specs — requirements fully captured in decisions above.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `fc_controller.py` already has `self.humidifier_state` (boolean) in simulation mode — this is the correct thing for tests to assert against
- `fc_controller.py` already reads `light_pin` from params — same pattern to use for `humidifier_pin`
- `fc_controller.py` `humidity_callback` at line 94 is where the rolling median buffer should be inserted

### Established Patterns
- Config params declared via `declare_parameters()` in `__init__`, read via `get_parameter().value` — humidifier_pin should follow this same pattern
- Both nodes use the `sensor_simulation_mode` / `actuator_simulation_mode` split — don't conflate them

### Integration Points
- `fc_config.yaml` uses `/**:` namespace — all params go under `ros__parameters:` and are picked up by both nodes
- Tests run in simulation mode by default (no GPIO) — median filter must work in simulation mode

</code_context>

<specifics>
## Specific Ideas

- User noted the humidity curve on OpenMCT looks "a little noisy" — rolling median at 5 samples is appropriate, not over-engineered
- "More honest" for sensor placement: raw sensor topic, filtered controller. Preserve this separation.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 02-safety-hardening*
*Context gathered: 2026-03-30*
