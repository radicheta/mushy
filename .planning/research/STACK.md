# Technology Stack

**Project:** Mushroom Farm FC-1 Humidity Control
**Researched:** 2026-03-28 (original); v1.3 additions appended 2026-04-18
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

---

---

# v1.3 Stack Additions: Alerts & Unified Farmer Dashboard

**Appended:** 2026-04-18
**Confidence:** HIGH (Signal integration, alert placement), MEDIUM (FarmOS CORS, dashboard host)

This section covers only net-new stack decisions for v1.3. Existing decisions are not
re-examined.

---

## 1. Signal Integration

### Recommended Library

**Use:** `bbernhard/signal-cli-rest-api` as a new Docker container on elder-plops.

**Docker tag:** `bbernhard/signal-cli-rest-api:latest-stable`

The project does not use SemVer releases. Docker Hub exposes three relevant tags:
- `latest` — tracks master HEAD, may include in-progress changes
- `latest-stable` — lags a few days behind master; appropriate for production
- `0.200-dev` — most recent numbered build as of research date; pin this if you need a
  reproducible hash

Use `latest-stable` in docker-compose. If breakage occurs, pin to the numbered dev tag
(`0.200-dev` as of 2026-04-18) and update it at each milestone boundary.

### Why This Option

| Option | Verdict | Reason |
|--------|---------|--------|
| `bbernhard/signal-cli-rest-api` | Recommended | Self-contained Docker service; REST API so callers are language-agnostic; active community; QR-link registration documented; runs on amd64 (elder-plops) |
| `signal-cli` bare JVM | Reject | Requires Java on host or custom image; no REST abstraction; caller must shell out or parse stdout |
| `signald` | Reject | Less active maintenance; requires a separate client library; not simpler |
| `node-signal-client` npm | Reject | Requires native Rust compilation; brittle build; REST API decouples language from protocol entirely |
| Third-party SaaS | Reject | Not Signal; farmer uses Signal specifically |

### Operation Mode

Set `MODE=json-rpc-native` via environment variable.

This runs the native GraalVM binary as a persistent daemon rather than spawning a JVM
per request. For a low-volume farm alert bot (< 10 messages/day), `normal` mode would
work, but `json-rpc-native` avoids the 5-10 second JVM startup on each alert fire and
has lower memory overhead than `json-rpc`.

### Registration Flow

**Use linked-device flow, not primary number registration.**

Primary registration requires a dedicated phone number + SMS verification. The farmer
already has a Signal account on their phone. Linked-device flow requires one manual
setup step:

1. Start the container with the data volume mounted (see compose snippet below).
2. Open `http://elder-plops:8083/v1/qrcodelink?device_name=mushy-alerts` in a browser.
3. On the farmer's phone: Signal Settings → Linked Devices → tap + → scan the QR code.
4. The container is registered as a linked device. `registration_data` is persisted in
   the mounted volume and survives container restarts.

The data volume path inside the container is `/home/.local/share/signal-cli/`. Using
`docker exec` without specifying this path writes to `/root/...` instead (ephemeral).
Always register through the REST API endpoint — do not exec into the container.

### Send Message API

`POST /v2/send` with JSON body:

```json
{
  "message": "[mushy] RH out-of-band: 89% (target 95±2%)",
  "number": "+1XXXXXXXXXX",
  "recipients": ["+1XXXXXXXXXX"]
}
```

`number` is the linked sender number (the farmer's own Signal number). `recipients` is
the destination — for self-alerts or a farm Signal group, this can be the same number
or a group ID. No client library needed; Node.js 18+ native `fetch` handles the HTTP
call.

### Compose service addition

```yaml
signal:
  image: bbernhard/signal-cli-rest-api:latest-stable
  environment:
    - MODE=json-rpc-native
  volumes:
    - signal-data:/home/.local/share/signal-cli
  restart: unless-stopped
  # Internal only — no external port. Bridge calls http://localhost:8083
  ports:
    - "127.0.0.1:8083:8080"
```

Do not expose port 8083 to the LAN. The bridge calls it via localhost.

---

## 2. Alert Engine Placement

### Recommendation: Node.js module inside `mission_control_bridge`

Not a new container. Not a new ROS2 node. A new module file loaded by the bridge.

**Rationale referencing existing bridge state:**

The bridge (`src/mission-control/bridge/src/index.js`) already holds every signal the
alert engine needs:

- `lastSensorHealthBroadcast` — current `sensor_health` level (0=OK, 1=WARN, 2=ERROR)
- `humidifierLastMsgTs` — timestamp of most recent humidifier message from the Pi;
  staleness directly indicates Pi offline or humidifier silence
- `rosReady` — flips false if ROS init fails
- Live humidity broadcast values — available via the subscription callback
- `pool` (TimescaleDB) — available for stuck-humidifier historical queries
- `/health` endpoint — the bridge is already the infrastructure health authority

The bridge is always running on elder-plops. This is the right choke point for
infrastructure-level alerts, which must fire even when the Pi is offline.

A ROS2 Python node on the Pi cannot detect that the Pi is offline — the Pi-offline
alert requirement alone eliminates it as a candidate.

A dedicated alerts container would need to poll the bridge's `/health` or duplicate
all ROS2 subscriptions. Both are worse than running inside the bridge directly.

**Implementation:** Extract alerting into `src/mission-control/bridge/src/alerter.js`,
imported by `index.js` after ROS init completes. The module exports an `init(node,
pool)` function that sets up a `setInterval` tick (60 seconds) and evaluates four
conditions:

| Alert | Detection signal | Source in bridge |
|-------|-----------------|-----------------|
| Pi offline | `humidifierLastMsgTs` stale > 5 min AND `rosReady` | Already tracked |
| Sensor unhealthy | `lastSensorHealthBroadcast.sensor_health.level >= 2` | Already tracked |
| RH out-of-band | Latest humidity value outside `[target - band, target + band]` | Last broadcast value |
| Humidifier stuck | Humidifier ON continuously > threshold with RH not recovering | `humidifierLastMsgTs` + Timescale window query |

Each alert carries a per-type cooldown (default 30 minutes) stored in module-level
state. A bridge restart resets cooldowns — acceptable for a farm bot.

Sending is a single `fetch` call to `http://localhost:8083/v2/send`. No new npm
dependency: Node.js 18+ has native `fetch`.

**New environment variables for the `bridge` service:**

```
SIGNAL_API_URL=http://localhost:8083
SIGNAL_SENDER=+1XXXXXXXXXX
SIGNAL_RECIPIENT=+1XXXXXXXXXX
ALERT_RH_TARGET=95
ALERT_RH_BAND=2
ALERT_COOLDOWN_MIN=30
ALERT_HUMIDIFIER_STUCK_MIN=30
```

These go in `.env` and are added to the bridge's `environment:` block in
`docker-compose.yml`.

---

## 3. FarmOS Data Access for Dashboard

### Problem

The farmer dashboard needs recent FarmOS observation logs displayed alongside MC
telemetry. FarmOS is at `http://10.68.155.50:8082` — a different origin from the
dashboard page. Drupal CORS is off by default. The FarmOS instance is shared
farm-wide and managed by the farm team, so `services.yml` changes require coordination.

### Options

| Approach | CORS friction | Auth complexity | Recommended |
|----------|--------------|-----------------|-------------|
| Browser fetches FarmOS JSON:API directly | Must edit Drupal `services.yml` on shared instance; `allowedOrigins: ['*']` disables `withCredentials`, breaking session-cookie auth | High — cross-origin session cookies restricted by browsers (SameSite=Lax) | No |
| Bridge proxies FarmOS (`/farmos/logs` route) | None — browser only talks to bridge (same origin) | Low — bridge calls FarmOS server-side using session-cookie pattern from `farmos_agent` | **Yes** |
| Iframe of FarmOS Drupal page | N/A — Drupal serves its own HTML | None — Drupal session is in the browser already | Fallback only |
| FarmOS hosts the page and embeds MC | N/A | Low | Out of scope |

### Recommendation: Bridge proxy

Add a `/farmos/logs?limit=N` route to the bridge. The bridge calls FarmOS JSON:API
server-side (session-cookie auth, same pattern as `farmos_agent`), caches the response
in memory for 60 seconds, and returns a sanitized array to the browser.

Auth flow: the bridge initializes a FarmOS session on startup using `FARMOS_URL`,
`FARMOS_USERNAME`, `FARMOS_PASSWORD` — already present in `.env` from Phase 13.
Add these three vars to the bridge service's `environment:` block in `docker-compose.yml`
(they already exist for `farmos-agent`; no new secrets required).

The proxy must be read-only (GET only) for v1.3. No write-through.

If FarmOS is unreachable, return cached last-known data or an empty array. Never let
FarmOS downtime break the MC dashboard.

The bridge's existing CORS allowlist (`CORS_ORIGIN`) already covers the dashboard
origin; no CORS changes needed.

---

## 4. Dashboard Host

### Options

| Option | Effort | Auth | FarmOS data | MC data | Verdict |
|--------|--------|------|-------------|---------|---------|
| New OpenMCT plugin view | Low — adds a `plugin.js` view | Reuses MC | Via bridge proxy | Native WS | Good for MC-operator audience |
| Standalone `/farmer` page served by bridge | Low-medium — static HTML in `bridge/static/`, served via `express.static` | None (LAN-only) | Via `/farmos/logs` proxy | Via bridge WS + REST | **Recommended** |
| FarmOS Drupal page iframing MC | High — Drupal theming + CSP changes on shared instance | Drupal session | Native | MC iframe (CSP issues) | Avoid |

### Recommendation: Standalone `/farmer` page served by the bridge

A static HTML + vanilla JS file at `src/mission-control/bridge/static/farmer.html`,
served by the bridge at `http://elder-plops:8081/farmer`.

Three lines of bridge config:
```js
app.use('/static', express.static(path.join(__dirname, '../static')));
app.get('/farmer', (req, res) =>
  res.sendFile(path.join(__dirname, '../static/farmer.html')));
```

The page calls:
- `/history/fc.humidity` (existing) — last 24h RH chart
- `/health` (existing) — Pi/bridge/DB liveness
- `/farmos/logs?limit=5` (new) — recent FarmOS observations
- Bridge WebSocket (existing) — live RH value

No OpenMCT dependency. No build step. No new npm package. The URL is bookmarkable on
the farmer's phone: `http://10.68.155.50:8081/farmer`.

**Heuristic for future decisions:** If the target user is an MC operator who already
has the full dashboard open, use an OpenMCT plugin. If the target user is a farmer who
wants a 10-second morning check without navigating MC, use a standalone page.

For v1.3, the farmer is the target.

---

## 5. What NOT to Add

| Temptation | Why to skip | What to use instead |
|------------|------------|---------------------|
| Full backend framework (NestJS, Fastify) | Bridge is already Express; new routes don't need a framework | Add routes directly to `index.js` or extract to `src/alerter.js` / `src/farmos_proxy.js` |
| Push notifications / PWA service worker | Signal message is the alert channel; dashboard is LAN-only | Signal + `/farmer` static page |
| Dedicated alerting container (Alertmanager, Grafana) | Heavy; duplicates bridge subscriptions; overkill for 4 conditions | In-bridge alerter module |
| OAuth2 for FarmOS bridge proxy | OAuth2 consumer not configured on shared instance; session-cookie is proven | Session-cookie auth (same as `farmos_agent`) |
| React / Vue for `/farmer` page | Adds build step, dependency management; page is read-only telemetry | Vanilla JS + `fetch`; Chart.js if charts needed |
| WebSocket from bridge to signal-cli-rest-api | REST API is request/response; no WS offered | POST to `/v2/send` on alert condition |

---

## New Environment Variables (v1.3)

All go in `.env` on elder-plops. Injected via `docker-compose.yml`.

| Variable | Service | Purpose | Notes |
|----------|---------|---------|-------|
| `SIGNAL_API_URL` | bridge | URL of signal-cli-rest-api | `http://localhost:8083` |
| `SIGNAL_SENDER` | bridge | Farmer's Signal number (linked device) | `+1XXXXXXXXXX` |
| `SIGNAL_RECIPIENT` | bridge | Alert destination | Same as sender for self-alerts |
| `ALERT_RH_TARGET` | bridge | RH setpoint % | `95` |
| `ALERT_RH_BAND` | bridge | ±band % | `2` |
| `ALERT_COOLDOWN_MIN` | bridge | Minutes between repeat alerts per type | `30` |
| `ALERT_HUMIDIFIER_STUCK_MIN` | bridge | Minutes ON with no recovery = stuck | `30` |
| `FARMOS_URL` | bridge | FarmOS base URL (already in .env) | Existing — add to bridge env block |
| `FARMOS_USERNAME` | bridge | FarmOS login (already in .env) | Existing — add to bridge env block |
| `FARMOS_PASSWORD` | bridge | FarmOS password (already in .env) | Existing — add to bridge env block |

`FARMOS_*` vars already exist in `.env` (Phase 13). Only the bridge's `environment:`
block in `docker-compose.yml` needs them added — no new secrets.

---

## Version Summary (v1.3 additions)

| Component | Version / Tag | Notes |
|-----------|--------------|-------|
| `bbernhard/signal-cli-rest-api` | `latest-stable` (pin `0.200-dev` for hash stability) | New Docker service |
| Node.js native `fetch` | Node 18+ built-in | No new npm package |
| `express.static` | Already in bridge `express ^4.x` | No version change |
| FarmOS | `3.x` shared instance | No change |
| TimescaleDB | `latest-pg14` | No change |

No new npm packages are required for the alert engine or farmer dashboard. Node.js 18+
native `fetch` is available in the existing bridge image.

---

## Sources (v1.3 additions)

- [bbernhard/signal-cli-rest-api README](https://github.com/bbernhard/signal-cli-rest-api/blob/master/README.md) — linked-device registration flow, `/v2/send` payload, MODE options — MEDIUM confidence (verified via WebFetch; project has no versioned release tags)
- [Docker Hub: bbernhard/signal-cli-rest-api](https://hub.docker.com/r/bbernhard/signal-cli-rest-api) — tag naming (`latest-stable`, `latest-dev`, numbered dev) — MEDIUM confidence
- [Drupal CORS opt-in documentation](https://www.drupal.org/node/2715637) — `services.yml` CORS config, wildcard credential restriction — HIGH confidence (official Drupal docs)
- [Phase 13 RESEARCH.md](.planning/milestones/v1.2-phases/13-farmos-daily-report/13-RESEARCH.md) — FarmOS session-cookie auth pattern, farmos_agent architecture — HIGH confidence (verified against live instance)
- `src/mission-control/bridge/src/index.js` — bridge subscriptions (`humidifierLastMsgTs`, `lastSensorHealthBroadcast`, `rosReady`), express routes, pool — HIGH confidence (live code, read directly)

---

*v1.3 stack additions researched: 2026-04-18*
