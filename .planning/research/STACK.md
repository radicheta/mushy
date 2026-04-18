# Technology Stack

**Project:** Mushroom Farm FC-1 Humidity Control
**Researched:** 2026-03-28
**Overall Confidence:** MEDIUM-HIGH

---

## Recommended Stack

### Core Framework

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| ROS2 Jazzy | LTS (jazzy) | Node runtime, pub/sub messaging, parameter system | Already in production; Jazzy is the current LTS on Ubuntu 24.04; do not change |
| rclpy | 3.x (bundled with Jazzy) | Python ROS2 client library | The only correct choice for Python nodes; rclcpp is C++ only |
| Python | 3.12 (Ubuntu 24.04 default) | Node implementation language | Already used throughout; Python 3.12 ships with Ubuntu 24.04 base image |

### Sensor Library (DHT22)

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| adafruit-circuitpython-dht | 3.7.x | DHT22 temperature/humidity reading | Already in the codebase and Dockerfile; verified functional |

**Critical warning:** `adafruit-circuitpython-dht` depends on `libgpiod.so.2`. On **Raspberry Pi OS (Bookworm)** this works correctly. On **Ubuntu 24.04** the system ships `libgpiod3` (not `libgpiod2`), causing an import failure. The current Dockerfile installs `RPi.GPIO` and `adafruit-circuitpython-dht` but does **not** resolve this ABI mismatch.

**Mitigation for MVP:** If the Pi is running Raspberry Pi OS (Bookworm), not Ubuntu, this is not an issue. Confirm the OS before treating this as a blocker. If Ubuntu 24.04 is confirmed, the workaround is `sudo apt-get install libgpiod2` inside the container, or pin the container base to Raspberry Pi OS. Do not attempt to switch the sensor library mid-MVP — fix the OS/library pairing first.

**Confidence:** MEDIUM — libgpiod compatibility is a real, documented issue on forum threads from 2024-2025. Confirmed that Pi OS Bookworm still ships libgpiod2 and is unaffected.

### GPIO Control

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| RPi.GPIO | 0.7.x | MOSFET/humidifier pin control (HIGH/LOW) | Already in codebase; fine for simple on/off GPIO on Raspberry Pi OS |
| rpi-hardware-pwm | 0.3.1 | Fan speed via hardware PWM | Already in use; v0.3.1 released Feb 2026; requires `dtoverlay=pwm-2chan` in `/boot/firmware/config.txt` |

**On Ubuntu 24.04:** `RPi.GPIO` does not reliably work. The drop-in replacement is `rpi-lgpio` (same import interface, built on lgpio/libgpiod). For the MVP, the humidifier pin uses simple on/off (`GPIO.output`), so rpi-lgpio is a safe swap with one caveat: debounce behavior differs slightly, but debounce is not used here.

**Recommendation for MVP:** Keep `RPi.GPIO` if the target hardware runs Raspberry Pi OS. If Ubuntu 24.04, add `rpi-lgpio` as a dependency and no code changes are needed — it is a drop-in replacement with the same API surface.

**Confidence:** MEDIUM-HIGH — rpi-lgpio compatibility claims are corroborated by multiple forum reports and the library's own documentation.

### Closed-Loop Control Algorithm

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| simple-pid | 2.0.1 | PID feedback loop for humidity setpoint | Zero dependencies, MIT license, well-tested, actively maintained |

**Rationale:** The existing controller uses bang-bang (hysteresis) control: humidifier ON below setpoint - tolerance, OFF above setpoint + tolerance. This is adequate for MVP and already implemented. `simple-pid` is the standard library for Python PID in ROS2 projects. It is the library referenced in `simple-ros-pid` (the most-cited ROS2 Python PID project), extracted as a standalone dependency-free package.

**For MVP:** Do not add simple-pid yet unless the bang-bang hysteresis approach proves unstable on the physical hardware. The existing hysteresis controller is correct for a binary actuator (humidifier is either ON or OFF — not PWM-controlled), and a PID output on a binary actuator requires pulse-width modulation of the humidifier on/off cycle, which adds complexity. Defer PID to Phase 2.

**If PID is needed later:** `pip install simple-pid==2.0.1`. Use `sample_time` equal to the control loop interval (1.0 s). Clamp output to `[0.0, 1.0]` representing humidifier duty cycle. Set integral bounds to prevent windup.

**Confidence:** HIGH — verified against PyPI, GitHub, and official docs.

### ROS2 Message Types

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| sensor_msgs/RelativeHumidity | Jazzy built-in | Humidity topic message type | Standard message; includes `header` (stamp + frame_id) and `relative_humidity` (float64, 0.0-1.0) and `variance` (0.0 = unknown) |
| sensor_msgs/Temperature | Jazzy built-in | Temperature topic message type | Same pattern; already used |
| std_msgs/Bool | Jazzy built-in | Humidifier actuator state publication | Publish actuator state for observability/OpenMCT |

**Note on RelativeHumidity:** The field is in the range [0.0, 1.0], not percentage. The existing sensor code has an inconsistency: simulation mode sets `sim_humidity` to values like 0.85 (correct), but the hardware path divides by 100.0 after reading — DHT22 already returns 0-100, so that division is correct. The simulation and hardware paths are not equivalent. This is a pre-existing bug to fix.

### Testing

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| pytest | 7.x (via system/pip) | Unit tests for node logic | Already in use; standard for ROS2 Python packages |
| unittest.mock | stdlib | Mock GPIO, DHT22, hardware calls in tests | No additional dependency; prevents hardware calls in CI |
| ament_flake8 | Jazzy bundled | Linting | Already configured |
| ament_pep257 | Jazzy bundled | Docstring style | Already configured |

**ROS2 test patterns:** For unit tests of node logic (control algorithm, parameter handling), instantiate the node directly after `rclpy.init()` and call callbacks/methods directly. Do not use `rclpy.spin()` in tests. Use `unittest.mock.patch` to mock GPIO imports that would fail in CI without hardware.

**Integration test pattern:** Use `launch_testing` for end-to-end tests that need a full ROS2 graph. For MVP, pure pytest unit tests are sufficient.

**Confidence:** HIGH — verified against official ROS2 Jazzy testing docs and existing test file patterns in the codebase.

### Build and Packaging

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| colcon | current | Workspace build orchestrator | Standard for ROS2; already used |
| ament_python | Jazzy bundled | Python package build system within colcon | Standard for pure-Python ROS2 packages |
| rosdep | current | ROS dependency resolution | Already initialized in Dockerfile |

---

## Alternatives Considered

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| PID control | simple-pid (deferred) | ros2_control PID controller | ros2_control is heavyweight machinery for robotics actuators; overkill for a humidity loop; requires hardware interface abstractions not needed here |
| PID control | simple-pid (deferred) | Custom PID implementation | simple-pid is well-tested, handles anti-windup, supports sample_time; no reason to reimplement |
| GPIO (Ubuntu) | rpi-lgpio | python3-gpiod (low-level) | rpi-lgpio is a drop-in API replacement; gpiod requires rewriting all GPIO calls |
| GPIO (Ubuntu) | rpi-lgpio | gpiozero | gpiozero does not currently support DHT22; would require adafruit library anyway |
| DHT22 reading | adafruit-circuitpython-dht | Adafruit_Python_DHT (legacy) | Legacy library is archived/unmaintained since 2021; use circuitpython variant |
| DHT22 reading | adafruit-circuitpython-dht | Pure bit-bang Python (bullet64/DHT22_Python) | Unreliable timing on Linux; not recommended for production |
| Control algorithm | Bang-bang hysteresis (MVP) | PID | Humidifier is binary ON/OFF; PID output on a digital pin requires duty-cycle scheduling (adds complexity). Hysteresis is correct for this actuator type in MVP. |

---

## What to Avoid

### RPi.GPIO on Ubuntu 24.04
`RPi.GPIO` uses the legacy `/sys/class/gpio` sysfs interface deprecated in kernel 6.6. On Ubuntu 24.04 (kernel 6.8+), it will fail silently or error. Use `rpi-lgpio` as a drop-in replacement if targeting Ubuntu. If the Pi runs Raspberry Pi OS Bookworm, RPi.GPIO continues to work.

### Installing both RPi.GPIO and rpi-lgpio
Only one should be installed. `rpi-lgpio` conflicts with `RPi.GPIO` if both are present because they both expose the `RPi.GPIO` module name.

### adafruit-circuitpython-dht on Ubuntu 24.04 without libgpiod2
The library links to `libgpiod.so.2`. Ubuntu 24.04 ships `libgpiod3` (`.so.3`). Install `libgpiod2` explicitly, or use Raspberry Pi OS as the container base where `libgpiod2` is present.

### PID control with a digital-only actuator without duty-cycle logic
Applying a PID controller output directly to a GPIO HIGH/LOW without implementing duty-cycle switching is incorrect. A PID output of 0.7 on a digital pin should mean "ON for 70% of the control period", not just "set HIGH if > 0.5". Implement duty-cycle scheduling or stay with hysteresis for MVP.

### time.sleep() inside ROS2 callbacks
`fc_sensors.py` currently calls `time.sleep(2.0)` in the exception handler inside a timer callback. This blocks the ROS2 executor thread and can cascade into missed control loop ticks. Replace with a logged error and return; rely on the timer interval for retry.

### rclpy.spin_until_future_complete() in callbacks
Causes sync deadlock in the ROS2 executor. Use `call_async()` and handle via future callbacks if service calls are needed.

---

## Installation

### Production container (Dockerfile additions)

```bash
# If Ubuntu 24.04 base — add libgpiod2 for adafruit-circuitpython-dht compatibility
RUN apt-get update && apt-get install -y libgpiod2 && rm -rf /var/lib/apt/lists/*

# Replace RPi.GPIO with rpi-lgpio on Ubuntu 24.04
# (skip if using Raspberry Pi OS base image)
RUN pip3 install --break-system-packages rpi-lgpio

# PID library — defer to Phase 2
# RUN pip3 install --break-system-packages simple-pid==2.0.1
```

### Dev/test environment

```bash
pip install simple-pid==2.0.1
pip install pytest
# GPIO libraries are mocked in tests; do not install hardware libs in CI
```

---

## Docker Device Mounts (Production Raspberry Pi)

For GPIO and DHT22 access from a container, the following device mounts are required in `docker-compose.yml`:

```yaml
devices:
  - /dev/gpiomem:/dev/gpiomem
  - /dev/gpiochip0:/dev/gpiochip0   # for lgpio/libgpiod
privileged: true                     # or use specific device grants
```

`--privileged` is the bluntest tool; for tighter security, mount only `/dev/gpiomem` and the specific `/dev/gpiochipX` device. The container user needs to be in the `gpio` group.

---

## Sources

- [ROS2 Jazzy rclpy documentation](https://docs.ros.org/en/jazzy/p/rclpy/rclpy.html) — HIGH confidence
- [simple-pid GitHub (m-lundberg)](https://github.com/m-lundberg/simple-pid) — HIGH confidence
- [simple-pid PyPI](https://pypi.org/project/simple-pid/) — HIGH confidence
- [adafruit-circuitpython-dht PyPI](https://pypi.org/project/adafruit-circuitpython-dht/) — HIGH confidence
- [rpi-hardware-pwm PyPI v0.3.1](https://pypi.org/project/rpi-hardware-pwm/) — HIGH confidence
- [libgpiod.so.2 missing issue on Trixie/Ubuntu](https://forums.raspberrypi.com/viewtopic.php?t=393326) — MEDIUM confidence (forum, multiple confirmations)
- [Pi 4 Ubuntu 24.04 DHT22 unresolved thread](https://forums.raspberrypi.com/viewtopic.php?t=384938) — MEDIUM confidence (confirms problem, no clean solution)
- [rpi-lgpio differences from RPi.GPIO](https://github.com/waveform80/rpi-lgpio/blob/main/docs/differences.rst) — MEDIUM confidence (GitHub source)
- [Ubuntu GPIO configuration guide 2026-03-02](https://oneuptime.com/blog/post/2026-03-02-how-to-configure-gpio-access-on-ubuntu-for-raspberry-pi/view) — MEDIUM confidence
- [ROS2 Jazzy pytest unit test tutorial](https://automaticaddison.com/how-to-create-unit-tests-with-pytest-ros-2-jazzy/) — MEDIUM confidence
- [Docker GPIO access for ROS2 on Raspberry Pi](https://forums.docker.com/t/accessing-gpios-in-a-docker-container-created-from-a-ros2-image/147545) — MEDIUM confidence
- [sensor_msgs/RelativeHumidity message definition](https://docs.ros.org/en/api/sensor_msgs/html/msg/RelativeHumidity.html) — HIGH confidence

---

*Stack research: 2026-03-28*
