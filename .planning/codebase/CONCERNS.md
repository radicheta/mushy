# Codebase Concerns

**Analysis Date:** 2026-03-28

## Tech Debt

**Hardware/Simulation Mode Branching:**
- Issue: Control logic across multiple files uses repeated `if not self.get_parameter('simulation_mode').value` branching, making the code harder to test and maintain
- Files: `src/chambers/fc-core/fc_core/fc_controller.py` (lines 34-63, 111-141), `src/chambers/fc-core/fc_core/fc_sensors.py` (lines 23-31, 47-59)
- Impact: Code duplication increases maintenance burden; testing real hardware paths requires actual GPIO hardware; adding new hardware features requires modifying multiple branching locations
- Fix approach: Extract hardware abstraction layer (HAL) with separate implementations for real hardware and simulation modes; allow dependency injection of hardware adapters at node initialization

**Fragile Parameter Access:**
- Issue: Each hardware control method calls `self.get_parameter()` multiple times, causing overhead and inconsistent parameter values if parameters are changed at runtime
- Files: `src/chambers/fc-core/fc_core/fc_controller.py` (lines 111-141, 148-157)
- Impact: Performance overhead from repeated parameter lookups; potential race conditions if parameters are updated mid-control-loop; inconsistent behavior across method calls
- Fix approach: Cache parameters at initialization and provide parameter update callbacks; extract parameter values to local variables at start of control_loop

**Hardcoded Hardware Pin Assignments:**
- Issue: GPIO pin numbers hardcoded in code rather than fully configurable
- Files: `src/chambers/fc-core/fc_core/fc_controller.py` (line 49 - humidifier_pin hardcoded as 17)
- Impact: Requires code changes to adapt to different hardware configurations; not fully configurable via config file
- Fix approach: Move all pin assignments to `fc_config.yaml` configuration file

## Known Bugs

**Sensor Data Conversion Inconsistency:**
- Symptoms: Humidity values may be published in wrong units (percentage vs decimal) depending on simulation mode
- Files: `src/chambers/fc-core/fc_core/fc_sensors.py` (line 70)
- Trigger: Line 70 has conditional logic that divides humidity by 100 only in non-simulation mode, but sensors already publish as decimal (0-1) in simulation
- Workaround: Ensure all sensors publish humidity as decimal 0-1 regardless of mode, convert to percentage only in display layer

**Test Assertion Errors:**
- Symptoms: Tests will fail due to invalid state assertions
- Files: `src/chambers/fc-core/fc_core/test/test_controller.py` (lines 66, 74)
- Trigger: Tests check if `node.humidifier_pin` equals integer values (1 or 0), but `humidifier_pin` is a pin number (GPIO17), not a state variable
- Workaround: Tests should call `node.get_humidifier_state()` which returns boolean state, not examine pin numbers

**Uninitialized Subscription Data:**
- Symptoms: Control loop may execute with None sensor values if subscribers haven't received messages
- Files: `src/chambers/fc-core/fc_core/fc_controller.py` (lines 143-145)
- Trigger: Early execution before first sensor messages arrive; control_loop returns silently without operating
- Workaround: Use QoS policies with history to ensure subscribers get last message; add warning logs if data remains None after timeout

## Security Considerations

**Hardcoded WebSocket Server Address:**
- Risk: WebSocket telemetry server bound to "localhost" only (line 61 in `fc_telemetry.py`), but may be running in Docker container where localhost is unreachable from outside container
- Files: `src/chambers/fc-core/fc_core/fc_telemetry.py` (line 61)
- Current mitigation: Local-only binding prevents remote access
- Recommendations:
  - Make bind address configurable via environment variable or config file
  - Document that websockets are unauthenticated and unencrypted; use behind API gateway with auth
  - Add network policy documentation showing that fc_telemetry should only run in development/controlled networks

**Missing Input Validation:**
- Risk: No validation of sensor values; out-of-range readings could cause erratic behavior
- Files: `src/chambers/fc-core/fc_core/fc_controller.py` (lines 90-94), `src/chambers/fc-core/fc_core/fc_sensors.py` (lines 45-73)
- Current mitigation: Sensors perform bounds-clamping in simulation mode only
- Recommendations:
  - Add schema validation for incoming sensor messages
  - Log and reject out-of-range hardware sensor readings
  - Set reasonable physical bounds (e.g., temperature 5-50°C, humidity 0-100%)

**Unprotected GPIO Access in Shared Container:**
- Risk: In Docker, multiple containers may attempt GPIO operations without synchronization
- Files: `src/chambers/fc-core/Dockerfile`, `docker-compose.yml`
- Current mitigation: Simulation mode prevents GPIO access in containerized environment
- Recommendations:
  - Document that real hardware mode requires exclusive access
  - Use device isolation in docker-compose when deploying to real hardware
  - Implement GPIO lock file to prevent simultaneous access

## Performance Bottlenecks

**Synchronous WebSocket Blocking:**
- Problem: Telemetry node uses asyncio/websockets in separate thread; potential for blocking ROS2 callbacks
- Files: `src/chambers/fc-core/fc_core/fc_telemetry.py` (lines 33-35, 64-65)
- Cause: Thread-based websocket server not integrated with ROS2 event loop; asyncio.run() creates new event loop in thread
- Improvement path:
  - Use rclpy's built-in timer-based async support instead of manual threading
  - Consider reducing update frequency from 1 second if network bandwidth is constrained

**Repeated Parameter Lookups in Control Loop:**
- Problem: get_parameter() called multiple times per control cycle (every 1 second)
- Files: `src/chambers/fc-core/fc_core/fc_controller.py` (lines 148-157)
- Cause: No caching of frequently-accessed parameters
- Improvement path: Cache parameter values at initialization; use parameter update callbacks to refresh; typical fan control loop should cache 10+ parameters

**Inefficient Sensor Reading Fallback:**
- Problem: RuntimeError in sensor reading causes 2-second sleep (blocking), not retrying on next timer callback
- Files: `src/chambers/fc-core/fc_core/fc_sensors.py` (lines 75-77)
- Cause: Blocking sleep in ROS2 callback thread
- Improvement path: Track error state and use timer scheduling for retries instead of blocking sleep

## Fragile Areas

**Fan Speed Calculation Logic:**
- Files: `src/chambers/fc-core/fc_core/fc_controller.py` (lines 150-154)
- Why fragile: Linear scaling of fan speed based on temperature difference lacks bounds checking; formula `min_fan_speed + (temp_diff * fan_temp_scale)` can exceed 100% if temp_diff is large
- Safe modification: Add explicit bounds checking; document the formula; test with extreme temperature deltas
- Test coverage: test_temperature_control only tests -2/+2°C deltas; no tests for values outside tolerance

**Light Schedule Calculation Across Midnight:**
- Files: `src/chambers/fc-core/fc_core/fc_controller.py` (lines 96-108)
- Why fragile: Logic for light period crossing midnight uses modulo arithmetic; off-by-one errors possible
- Safe modification: Add comprehensive tests for midnight crossing (start=22, hours=4); test 23:00, 00:00, 01:00, 02:00, 03:00 hours
- Test coverage: Only tests 10 AM (in range) and 2 AM (out of range); no midnight tests

**Simulation Mode Initialization:**
- Files: `src/chambers/fc-core/fc_core/fc_controller.py` (lines 34-63)
- Why fragile: If GPIO import fails on real hardware, code continues silently; hardware paths untested in CI
- Safe modification: Add explicit exception handling; fail fast if simulation_mode=false but GPIO unavailable
- Test coverage: No tests verify hardware mode initialization

## Scaling Limits

**Single Thread WebSocket Broadcasting:**
- Current capacity: WebSocket handle_websocket coroutine sends to one client per loop; no broadcast mechanism
- Limit: Adding 2+ clients requires manual connection tracking; current code sends independently to each client
- Scaling path: Implement client list with broadcast on sensor update; use asyncio.gather for concurrent sends

**Fixed Timer-Based Polling:**
- Current capacity: Hardcoded 2-second sensor read interval; cannot be changed without restart
- Limit: Tightly coupled to config parameter; cannot dynamically adjust polling rate based on workload
- Scaling path: Make interval dynamic via ROS2 parameter callbacks; validate minimum safe interval to prevent sensor overload

## Dependencies at Risk

**Deprecated Hardware Libraries:**
- Risk: `RPi.GPIO` and `rpi_hardware_pwm` are legacy; maintainers recommend newer `gpiozero` and `rpi-gpio` alternatives
- Impact: May stop working with newer Raspberry Pi OS versions; security patches unlikely
- Files: `src/chambers/fc-core/setup.py` (lines 24-25), `src/chambers/fc-core/Dockerfile` (lines 11-14)
- Migration plan: Evaluate gpiozero (more modern, wider device support); verify all GPIO operations work; update dependencies; test on target hardware

**Websockets Library Without Version Pin:**
- Risk: `websockets` in setup.py not pinned to version; breaking API changes possible between major versions
- Impact: Telemetry node may break silently with package updates
- Files: `src/chambers/fc-core/setup.py` (line 20)
- Migration plan: Pin websockets to known stable version (e.g., ~10.0); document minimum version for protocol compatibility

**Adafruit DHT Library Deprecation:**
- Risk: Adafruit DHT library reaches end-of-life; newer sensors recommend alternative libraries
- Impact: DHT22 is outdated; newer temperature/humidity sensors may be unavailable
- Files: `src/chambers/fc-core/setup.py` (line 26)
- Migration plan: Consider newer sensor types (BME680, BME688); evaluate updated libraries

## Missing Critical Features

**No Error Recovery or Retry Logic:**
- Problem: Sensor failures cause control loop to stop updating; no automatic recovery
- Blocks: Cannot operate reliably if sensors temporarily fail
- Recommendations: Implement exponential backoff for sensor retries; maintain state from last successful read; alert operator after N consecutive failures

**No Health Monitoring or Watchdog:**
- Problem: No indication if nodes are alive; no alerting on control loop failures
- Blocks: Cannot detect silent failures; no visibility into system health
- Recommendations: Implement ROS2 lifecycle nodes; add watchdog timer that publishes health status; create system monitor node

**No Configuration Validation at Startup:**
- Problem: Invalid parameters cause runtime failures, not startup errors
- Blocks: Cannot catch configuration mistakes before deployment
- Recommendations: Validate parameter ranges at node initialization; reject invalid combinations (e.g., light_start_hour > 23)

**Missing Logging Strategy:**
- Problem: Debug logs but no structured logging; no way to query past events
- Blocks: Troubleshooting failures requires reading console output; no audit trail
- Recommendations: Integrate rosbag2 for recording; consider structured logging (JSON); add log rotation to prevent disk fill

## Test Coverage Gaps

**Simulation Mode Initialization Not Tested:**
- What's not tested: If RPi.GPIO/hardware import fails on real hardware, code doesn't error
- Files: `src/chambers/fc-core/fc_core/fc_controller.py` (lines 34-63)
- Risk: Real hardware deployment could fail silently
- Priority: High - affects safety-critical hardware control

**Humidity Conversion Not Tested:**
- What's not tested: Humidity scaling between simulation (0-1) and real hardware (percentage conversion)
- Files: `src/chambers/fc-core/fc_core/fc_sensors.py` (line 70)
- Risk: Wrong units causing incorrect humidity control
- Priority: High - affects environmental control

**Midnight Light Schedule Not Tested:**
- What's not tested: Light control when schedule crosses midnight (e.g., start=22:00, hours=4)
- Files: `src/chambers/fc-core/fc_core/fc_controller.py` (lines 96-108)
- Risk: Lights may stay on/off incorrectly at midnight boundary
- Priority: Medium - affects one feature, detectable issue

**Fan Speed Bounds Not Tested:**
- What's not tested: Fan speed calculation with extreme temperature deltas (>20°C difference)
- Files: `src/chambers/fc-core/fc_core/fc_controller.py` (lines 150-154)
- Risk: Fan PWM given invalid speed >100% or <0%
- Priority: Medium - may not be triggered in normal operation

**WebSocket Client Connection/Disconnection Not Tested:**
- What's not tested: Multiple clients connecting/disconnecting; error handling when send fails
- Files: `src/chambers/fc-core/fc_core/fc_telemetry.py` (lines 47-62)
- Risk: Telemetry service may crash if client disconnects mid-send
- Priority: Low - local development only currently

---

*Concerns audit: 2026-03-28*
