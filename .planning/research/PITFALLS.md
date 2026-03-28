# Domain Pitfalls: ROS2 Closed-Loop Humidity Control

**Domain:** ROS2-based environmental control — fruiting chamber humidity (Raspberry Pi + DHT22 + MOSFET)
**Researched:** 2026-03-28
**Project:** Mushroom Farm FC-1 MVP

---

## Critical Pitfalls

These mistakes cause rewrites, production outages, or hardware damage.

---

### Pitfall 1: Blocking `time.sleep()` Inside a ROS2 Callback

**What goes wrong:** `fc_sensors.py` line 77 calls `time.sleep(2.0)` inside the `read_sensors` timer callback when a `RuntimeError` occurs. This blocks the entire rclpy executor thread for 2 seconds.

**Why it happens:** The default rclpy executor is single-threaded. A blocking call in any callback prevents ALL other callbacks (including the control timer, subscriber callbacks, and shutdown handling) from executing during that window. The 2-second sleep is also exactly the sensor read interval, meaning consecutive failures create a compounding pile-up.

**Consequences:**
- Control loop is starved during sensor error recovery windows
- Humidifier can be left in an indeterminate state (on or off) with no updates
- ROS2 shutdown signal may be ignored during the sleep, making the node unkillable with Ctrl+C (confirmed ROS2 issue: `sleep_for` not exiting on shutdown — ros2/rclpy#1148)
- With repeated errors, the node effectively freezes

**Prevention:** Replace `time.sleep()` with a state flag (`_sensor_error_until = time.monotonic() + 2.0`) checked at the top of the callback. The callback returns immediately; the next timer invocation resumes normal reads. Alternatively, use rclpy async timer patterns.

**Detection:** Node stops logging debug output but process remains alive. Control loop timer callbacks cease firing.

**Confidence:** HIGH — confirmed blocking behavior in rclpy single-threaded executor.

---

### Pitfall 2: Uninitialized Sensor Data — Control Loop Executes with `None`

**What goes wrong:** `fc_controller.py` lines 143–145 guard the control loop with `if self.current_temp is None or self.current_humidity is None: return`. This is silent — no log, no warning, no indication to the operator.

**Why it happens:** At startup, the controller subscribes to `fc/temperature` and `fc/humidity` but has no guarantee of when the first message arrives. The sensor node publishes on a 2-second timer; the control loop fires on a 1-second timer. The control loop silently does nothing for the first 1–2 seconds minimum. On a slow boot or if the sensor node crashes, it does nothing forever.

**Consequences:**
- The humidifier never turns on after node restart if the sensor node is down — this looks identical to "working correctly" from the outside
- No alerting means growers may not notice the system has stopped controlling for hours
- Silent failure is especially dangerous because the previous actuator state persists (humidifier left on indefinitely if it was on before the sensor node crashed)

**Prevention:**
1. Log a warning when control loop fires with None data
2. Implement a stale-data timeout: if data hasn't arrived in N seconds, treat it as a sensor failure and take a safe action (turn humidifier off)
3. Use `TRANSIENT_LOCAL` durability QoS on humidity publisher + subscriber so the controller gets the last published value immediately on subscribe

**Detection:** `ros2 topic echo fc/humidity` returns no messages while the controller is "running."

**Confidence:** HIGH — confirmed via code inspection; known ROS2 pattern documented in community.

---

### Pitfall 3: Humidity Unit Inconsistency Between Hardware and Simulation Modes

**What goes wrong:** `fc_sensors.py` line 70 divides by 100 only in hardware mode: `float(humidity) / 100.0 if not simulation_mode else float(humidity)`. The `adafruit_dht` library returns humidity as a percentage (0–100). The simulation stores it as a fraction (0.0–1.0). The published `RelativeHumidity` message therefore carries different units depending on mode.

**Why it happens:** `sensor_msgs/RelativeHumidity.relative_humidity` is defined as a value in range 0.0–1.0 (fraction, not percent). The simulation was written to match the message spec; hardware mode adds an (incorrect) divide by 100 on top of the raw sensor value.

**Wait — this is actually the bug:** The `adafruit_dht` library returns 85.0 for 85% humidity. The code divides by 100 to get 0.85, which is correct for the message type. The simulation already stores 0.85. So the unit conversion is actually correct for the intended message format.

**The real trap:** If anyone changes the simulation initial value `self.sim_humidity = 0.85` thinking it represents "85 out of 100", then adds a `/100.0` for "consistency," the simulation will publish 0.0085 — way below the target humidity tolerance band, causing the humidifier to run continuously in simulation.

**Consequences:**
- Simulation and hardware behavior diverge silently if the conversion is modified
- Closed-loop tests in simulation pass but real hardware fails (or vice versa)
- The control loop compares `current_humidity` against `target_humidity = 0.85` — if a 1.0x vs 0.01x error creeps in, the humidifier either never turns off or never turns on

**Prevention:**
- Add an assertion/validation on publish: `assert 0.0 <= humidity_msg.relative_humidity <= 1.0`
- Add a comment at line 70 explicitly stating: "DHT22 returns 0–100; divide by 100 to conform to RelativeHumidity message spec (0.0–1.0)"
- Test both modes publish the same range and that the controller target matches

**Confidence:** HIGH — confirmed by code inspection and ROS2 message type spec.

---

### Pitfall 4: MOSFET Not Fully Switching at 3.3V GPIO Logic Level

**What goes wrong:** Many MOSFETs commonly used in hobby projects (e.g., IRF520N, IRLB8721) are not fully enhanced at 3.3V gate voltage. The Raspberry Pi GPIO outputs 3.3V logic. A MOSFET that is only partially on dissipates power as heat instead of cleanly switching the load.

**Why it happens:** Standard MOSFETs are specified for Vgs = 10V. "Logic-level" MOSFETs are specified for Vgs = 4.5V but still may not switch cleanly at 3.3V. Only MOSFETs explicitly rated for 2.5V or 3.3V Vgs threshold (e.g., IRLZ44N, IRL540N, AO3400, 2N7000 for small loads) are guaranteed to fully switch.

**Consequences:**
- MOSFET runs hot, reducing lifespan
- Humidifier may not receive full power, running at reduced capacity
- In worst case, MOSFET fails in partially-on state, leaving humidifier running continuously with no GPIO control
- GPIO pin may be damaged if MOSFET draws excessive gate current

**Prevention:**
- Verify the specific MOSFET part number has a Vgs(th) datasheet rating that ensures full enhancement at 3.3V
- If MOSFET is not rated for 3.3V logic: add a gate driver (e.g., 74HC logic buffer) or level shifter between GPIO and gate
- Add a gate pull-down resistor (10kΩ) to ensure the MOSFET is off when GPIO is floating during Pi boot sequence

**Detection:** MOSFET warm/hot to touch during normal operation. Humidifier runs at partial power.

**Confidence:** MEDIUM — confirmed general electronics principle; specific MOSFET part for this project unknown at research time.

---

### Pitfall 5: Humidifier Left On at Node Crash / Process Kill

**What goes wrong:** If the ROS2 node process is killed with `SIGKILL` (kill -9, OOM killer, Docker stop with insufficient timeout), `GPIO.cleanup()` in the `finally` block is never called. The MOSFET gate retains its last voltage state. If the humidifier was on when the node dies, it stays on indefinitely.

**Why it happens:** `GPIO.cleanup()` resets all pins to input mode (effectively low). This only runs on clean shutdown. `SIGKILL` cannot be caught. Docker's default stop timeout is 10 seconds; if the ROS2 node takes longer to shut down, Docker escalates to `SIGKILL`.

**Consequences:**
- Humidifier runs continuously overnight, flooding the fruiting chamber
- Mushroom substrate waterlogging is irreversible — lost harvest
- Electrical hazard if humidifier water reservoir runs dry while unattended

**Prevention:**
1. Wire the MOSFET gate with a pull-down resistor (10kΩ to GND) so the default hardware state (GPIO floating) is humidifier OFF. This is a hardware safety measure independent of software.
2. Set `stop_grace_period: 30s` in docker-compose for the ros-core service
3. Add SIGTERM handler to ensure GPIO cleanup before process exits
4. Consider a hardware watchdog: if the Pi's WDT is not petted, it resets the Pi, which forces GPIO to re-initialize (pins go low on boot)

**Detection:** Humidifier running with no ROS2 nodes active. `ros2 node list` returns nothing but humidifier is on.

**Confidence:** HIGH — confirmed via code inspection; standard embedded systems safety principle.

---

## Moderate Pitfalls

Issues that cause degraded behavior or require investigation to diagnose.

---

### Pitfall 6: Bang-Bang Control Oscillation Without Minimum On/Off Time

**What goes wrong:** The current control algorithm is a pure bang-bang (on/off) controller with hysteresis band `target ± tolerance` (85% ± 5%). When humidity is near the threshold, the humidifier may cycle on and off rapidly — multiple times per minute.

**Why it happens:** The sensor reads every 2 seconds; the control loop fires every 1 second. When humidity is near `target - tolerance` (80%), a single sensor read triggering "turn on" followed by propagation delay, ultrasonic mist dispersion, then another read hitting `target + tolerance` (90%) causes a fast on/off cycle. This is worsened by DHT22 read noise (±2–5% typical).

**Consequences:**
- MOSFET subjected to excessive switching cycles (reduces lifespan)
- Humidifier motor wears faster
- Ultrasonic transducers are not designed for rapid on/off cycling
- Humidity oscillates rather than stabilizing, stressing the substrate

**Prevention:**
- Implement minimum on-time and minimum off-time (e.g., 30 seconds each) as state variables in the controller
- Track `humidifier_last_state_change` timestamp; enforce minimum dwell time before allowing state transition
- Research shows this is standard practice in mushroom cultivation controllers

**Detection:** Log shows `Humidifier: ON` / `Humidifier: OFF` alternating faster than every 30 seconds.

**Confidence:** HIGH — confirmed in mushroom cultivation control literature and control theory fundamentals.

---

### Pitfall 7: DHT22 Systematic Read Failures Under Humidity

**What goes wrong:** DHT22 sensors have a known failure pattern: at very high humidity (>90%), the sensor can produce systematic errors — `RuntimeError: DHT sensor not responding` or returns implausible values. This is the exact environment a mushroom fruiting chamber operates in.

**Why it happens:** The DHT22 uses a capacitive humidity element that can absorb condensation at very high humidity, causing the internal timing circuit to produce malformed pulses. The Adafruit CircuitPython DHT library raises `RuntimeError` on checksum failure. The sensor requires minimum 2 seconds between reads — reading faster causes persistent errors.

**Consequences:**
- Sensor returns errors precisely when humidity is highest and control is most critical
- The current error handler (`time.sleep(2.0)`) blocks the callback thread
- Multiple consecutive errors cause the control loop to stall (see Pitfall 1)
- If errors persist, the humidifier state is frozen at whatever it last was

**Prevention:**
- Implement retry counter and exponential backoff using state (not sleep)
- After N consecutive failures (e.g., 5), log an error and take a safe default action (turn humidifier off, alert operator)
- Ensure minimum 2-second interval between reads — current `sensor_read_interval: 2.0` is on the minimum edge; increasing to 3.0 reduces error rate
- Position sensor away from direct mist flow; condensation on the sensor element causes errors

**Detection:** Logs show repeating `Failed to read sensor: DHT sensor not responding` entries.

**Confidence:** HIGH — extensively documented in Adafruit forums, community issues, and DHT22 datasheet.

---

### Pitfall 8: Hardcoded GPIO17 for Humidifier Pin

**What goes wrong:** `fc_controller.py` line 49: `self.humidifier_pin = 17` is hardcoded regardless of `fc_config.yaml`. The config file has `dht_pin` and `light_pin` as configurable parameters, but the humidifier pin is not.

**Why it happens:** Oversight during implementation — humidifier control was added after the parameter system was established.

**Consequences:**
- If hardware is rewired to a different pin (e.g., to avoid a faulty pin), code must be modified not just config changed
- Two sources of truth for pin assignments invites configuration drift
- Inconsistency in the codebase makes onboarding new developers error-prone

**Prevention:** Add `humidifier_pin` to `fc_config.yaml` and declare it as a ROS2 parameter; remove the hardcoded constant.

**Confidence:** HIGH — confirmed by code inspection.

---

### Pitfall 9: Control Loop Reads Parameters on Every Cycle

**What goes wrong:** `fc_controller.py` control_loop calls `self.get_parameter()` 8+ times per invocation, once per second. Each call performs a dictionary lookup through the rclpy parameter server.

**Why it happens:** Parameters are accessed inline rather than cached at initialization.

**Consequences:**
- Minor performance overhead (usually acceptable at 1 Hz)
- More critically: if parameters are updated via `ros2 param set` at runtime, mid-loop parameter reads can see inconsistent values — e.g., `target_humidity` read for comparison uses the new value but `humidity_tolerance` still reflects the old value within the same loop iteration
- Race condition is real if parameters are changed during a control cycle

**Prevention:** Cache all parameters at initialization into instance variables. Use `add_on_set_parameters_callback` to update the cache when parameters change externally. This is the documented ROS2 pattern.

**Confidence:** MEDIUM — race condition is real but low probability at 1 Hz; performance impact is negligible in practice.

---

### Pitfall 10: `RPi.GPIO` is Incompatible with Raspberry Pi 5

**What goes wrong:** If/when the hardware is upgraded to a Raspberry Pi 5, `RPi.GPIO` will fail to import. The Pi 5 uses a different GPIO memory-mapping architecture that `RPi.GPIO` does not support.

**Why it happens:** The Pi 5 uses a new RP1 southbridge chip. `RPi.GPIO` directly maps `/dev/mem` using the older Broadcom GPIO register layout, which does not exist on the Pi 5. Raspberry Pi OS Bookworm ships a non-functional stub that throws errors.

**Consequences:**
- Entire hardware mode fails to initialize
- The `if not simulation_mode` import block raises `ImportError`, crashing the node at startup

**Prevention:**
- If hardware will be Pi 4 only for the MVP: no immediate action needed, but document the constraint
- Migration path: `rpi-lgpio` is a drop-in replacement for `RPi.GPIO` that works on Pi 5; `gpiozero` is the officially recommended long-term replacement
- The `adafruit_dht` / `adafruit-circuitpython-dht` library also requires `board` module from Blinka, which has its own Pi 5 compatibility story

**Detection:** `ImportError: No module named 'RPi.GPIO'` or GPIO register errors at node startup.

**Confidence:** HIGH — confirmed by Raspberry Pi Foundation documentation and community reports.

---

### Pitfall 11: Simulation Mode Silently Continues if GPIO Import Fails on Real Hardware

**What goes wrong:** `fc_controller.py` lines 34–63: if `simulation_mode=false` is set but `RPi.GPIO` import fails (library not installed, Pi 5, permission error), Python raises `ImportError` which propagates up through `__init__`, crashing the node. However, if the import *succeeds* but GPIO initialization fails partway through (e.g., `HardwarePWM` channel unavailable), the node crashes mid-initialization with GPIO partially configured — pins may be left in unexpected states.

**Why it happens:** No explicit try/except around the hardware initialization block. No validation that hardware init completed before proceeding.

**Consequences:**
- Partial GPIO initialization leaves some pins configured as outputs, others not
- Next node startup may see "already configured" warnings or incorrect initial states
- `GPIO.cleanup()` in `finally` is only reached if `__init__` completed — if it crashes in `__init__`, cleanup is never called

**Prevention:**
- Wrap hardware initialization in a try/except block with explicit cleanup on failure
- Fail fast with a clear error message: "Hardware initialization failed with simulation_mode=false. Check GPIO library installation and permissions."
- Call `GPIO.cleanup()` in the except handler before re-raising

**Detection:** Node crashes during startup with a traceback originating in `__init__`, not in a callback.

**Confidence:** HIGH — confirmed by code inspection.

---

## Minor Pitfalls

Lower severity but worth addressing for production quality.

---

### Pitfall 12: Test Assertions Check Pin Number, Not State

**What goes wrong:** `test_controller.py` lines 66 and 74 assert `node.humidifier_pin == 1` and `node.humidifier_pin == 0`. `humidifier_pin` is `17` (GPIO pin number) in hardware mode. In simulation mode there is no `humidifier_pin` attribute at all — there is only `humidifier_state`.

**Prevention:** Replace with `assert node.get_humidifier_state() == True` / `False`. Tests currently fail on every run.

**Confidence:** HIGH — confirmed by code inspection and CONCERNS.md.

---

### Pitfall 13: `fan_temp_scale` Formula Can Exceed 100% PWM

**What goes wrong:** `fc_controller.py` lines 150–154: fan speed formula `min_fan_speed + (temp_diff * fan_temp_scale)` uses `min()` clamp to 100 but `max()` against `min_fan_speed`. With `min_fan_speed=50` and `fan_temp_scale=20`, a temp_diff of only +2.5°C drives fan to 100%. A diff of -1°C drives fan to 30%, below `min_fan_speed`. The `max()` prevents going below 50, so the formula is actually: `min(100, max(50, 50 + (temp_diff * 20)))`. This means the fan can never go below 50% — even in cool conditions — which increases humidity loss via evaporation.

**Consequences:** The fan running at minimum 50% continuously works against humidity retention. For a high-humidity fruiting chamber, this may make it impossible to maintain target humidity without the humidifier running almost continuously.

**Prevention:** Review whether 50% minimum fan speed is appropriate for the fruiting chamber or if it was copied from a different context. Consider a lower minimum (20%) or allowing the fan to turn off when temperature is within tolerance.

**Confidence:** MEDIUM — temperature/humidity interaction depends on chamber size, insulation, and airflow that isn't characterized in the codebase.

---

### Pitfall 14: WebSocket Telemetry `localhost` Binding Inside Docker

**What goes wrong:** `fc_telemetry.py` line 61 binds WebSocket to `localhost`. Inside a Docker container, `localhost` is the container's loopback — unreachable from the host machine or other containers.

**Prevention:** Bind to `0.0.0.0` inside Docker and restrict access at the network/firewall level. Already flagged in CONCERNS.md.

**Confidence:** HIGH — confirmed by code inspection.

---

### Pitfall 15: `adafruit_dht` is the Legacy Library (Deprecated 2019)

**What goes wrong:** `setup.py` imports `adafruit-dht` — the legacy pre-Blinka library deprecated since November 2019. The current supported library is `adafruit-circuitpython-dht` (requires `adafruit-blinka`).

**Consequences:**
- No security patches
- May not install cleanly on newer Raspberry Pi OS versions (Bookworm)
- DHT22 read failures on Pi 5 even if RPi.GPIO is solved separately

**Prevention:** Migrate to `adafruit-circuitpython-dht` + `adafruit-blinka`. The API is similar but not identical — `adafruit_dht.DHT22(board.D4)` becomes an import from `adafruit_dht` via CircuitPython. Already flagged in CONCERNS.md.

**Confidence:** HIGH — confirmed by Adafruit official documentation and PyPI deprecation notice.

---

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation |
|-------------|---------------|------------|
| Sensor wiring and first reads | DHT22 systematic read errors at high humidity (Pitfall 7) | Start with low humidity, increase gradually; build retry logic before full deployment |
| MOSFET wiring | 3.3V logic-level compatibility (Pitfall 4); pin float on boot (Pitfall 5 hardware aspect) | Verify MOSFET part number datasheet; add gate pull-down resistor before first power-on |
| Control loop implementation | Bang-bang oscillation (Pitfall 6) | Implement minimum dwell time from day one; not a refactor |
| First real hardware test | `None` initial sensor values causing silent no-op (Pitfall 2) | Add explicit "waiting for sensor data" log at startup; add stale data timeout |
| Production deployment | Node crash leaves humidifier on (Pitfall 5) | Hardware pull-down resistor is mandatory before grower handoff |
| Dependency updates or Pi upgrade | `RPi.GPIO` + `adafruit-dht` deprecation chain (Pitfalls 10, 15) | Pin library versions; document hardware constraints |
| Adding parameters or tuning | Mid-loop parameter inconsistency (Pitfall 9) | Cache parameters; fix before exposing runtime tuning to growers |

---

## Summary: Safety-Critical Items for Production

These three items must be resolved before handing the system to a grower:

1. **Hardware pull-down on MOSFET gate** — ensures humidifier is off by default on power-up and node crash. No software fix substitutes for this.
2. **Sensor failure safe state** — if DHT22 stops responding, the controller must turn the humidifier OFF and alert (not freeze in last state).
3. **Minimum humidifier dwell time** — prevent rapid cycling that damages actuator hardware and causes humidity oscillation.

---

## Sources

- Adafruit DHT forums: [DHT22 failed to read (forums.adafruit.com)](https://forums.adafruit.com/viewtopic.php?t=210100)
- Sensor failures after hours: [DHT22 sensor no reading after some hours (GitHub)](https://github.com/adafruit/DHT-sensor-library/issues/205)
- DHT22 on Pi 5: [Inquiry about DHT Sensor on Raspberry Pi 5 (raspberrypi.com)](https://forums.raspberrypi.com/viewtopic.php?t=386699)
- rclpy sleep blocking: [Sleep inside node is blocking indefinitely (ROS Answers)](https://answers.ros.org/question/407654/)
- rclpy sleep_for not exiting on shutdown: [sleep_for not exiting on node shutdown (GitHub)](https://github.com/ros2/rclpy/issues/1148)
- ROS2 callback race conditions: [Race conditions in publisher and callback (ROS Answers)](https://answers.ros.org/question/395250/)
- ROS2 QoS transient local: [Quality of Service settings (ROS2 docs)](https://docs.ros.org/en/rolling/Concepts/Intermediate/About-Quality-of-Service-Settings.html)
- MOSFET 3.3V GPIO: [N-channel MOSFET on GPIO (raspberrypi.org)](https://www.raspberrypi.org/forums/viewtopic.php?t=49306)
- RPi.GPIO Pi 5 incompatibility: [RPi.GPIO on Pi5 (raspberrypi.com)](https://forums.raspberrypi.com/viewtopic.php?t=361834)
- gpiozero official replacement: [gpiozero 2.0.1 Documentation](https://gpiozero.readthedocs.io/)
- adafruit_dht deprecation: [Adafruit Python Library Deprecation (raspberrypi.com)](https://forums.raspberrypi.com/viewtopic.php?t=364194)
- Mushroom cultivation bang-bang control: [Investigation of Temperature and Humidity Control System for Mushroom House (ResearchGate)](https://www.researchgate.net/publication/336419291_Investigation_of_Temperature_and_Humidity_Control_System_for_Mushroom_House)
- GPIO cleanup on shutdown: [RPi.GPIO basics 3 — exit cleanly (raspi.tv)](https://raspi.tv/2013/rpi-gpio-basics-3-how-to-exit-gpio-programs-cleanly-avoid-warnings-and-protect-your-pi)
- Internal codebase analysis: `.planning/codebase/CONCERNS.md` (2026-03-28)
