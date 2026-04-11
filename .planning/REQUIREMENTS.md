# Requirements: Mushroom Farm MVP — FC-1 Humidity Control

**Defined:** 2026-03-28
**Core Value:** A working, production-ready humidity control loop that's better than the current timer solution and ready to ship to growers.

## v1 Requirements

### Infrastructure

- [x] **INFRA-01**: Developer can SSH into FC-1 Pi using key-based auth (no password)
- [x] **INFRA-02**: WireGuard VPN configured on Pi and reachable from developer workstation on mesh network
- [x] **INFRA-03**: Development workflow documented — how to deploy code changes to Pi and restart nodes
- [x] **INFRA-04**: ROS2 nodes running on Pi are visible from workstation (`ros2 topic list` across machines, `ROS_DOMAIN_ID=69`)

### Hardware

- [x] **HW-01**: Pi OS and GPIO library compatibility confirmed before any GPIO work begins
- [x] **HW-02**: MOSFET actuator wired to humidifier system on FC-1
- [x] **HW-03**: MOSFET gate pull-down resistor installed (humidifier defaults OFF on Pi boot/crash)

### Sensing

- [x] **SENS-01**: Humidity reading works reliably on real hardware. Primary sensor was SHT30 on I2C 0x44 (upgrade from originally-planned DHT22), validated during Phase 01-05 at 22.6°C/88.5%. SHT30 is currently unplugged; fc_sensors transparently falls back to SCD41 (I2C 0x62) for temp/humidity, which is its documented D-11 behavior. Requirement satisfied via the fallback path — humidity data is live and reliable.
- [x] **SENS-02**: Humidity published to `fc1/humidity` ROS topic in consistent 0.0–1.0 range
- [x] **SENS-03**: Non-blocking sensor error handling (remove `time.sleep()` from sensor callback)
- [x] **SENS-04**: Sensor normalization is consistent between real hardware and simulation paths
- [x] **SENS-05**: Sensor spike rejection filters outlier readings before control loop

### Control

- [x] **CTRL-01**: Closed-loop bang-bang control maintains humidity setpoint with hysteresis
- [x] **CTRL-02**: Setpoint and deadband (on/off thresholds) configurable via `fc_config.yaml`
- [x] **CTRL-03**: Minimum dwell time enforced — humidifier cannot cycle faster than configurable interval
- [x] **CTRL-04**: Stale sensor data detected — control loop does not act on data older than threshold
- [x] **CTRL-05**: Sensor failure drives humidifier to safe state (OFF), not frozen last state

### Actuator

- [x] **ACTR-01**: Humidifier controlled via MOSFET GPIO pin (on/off)
- [x] **ACTR-02**: Humidifier GPIO pin is configurable in `fc_config.yaml` (not hardcoded)
- [x] **ACTR-03**: Actuator state published to `fc1/actuators/humidifier` (`std_msgs/Bool`, `TRANSIENT_LOCAL`) — *tech debt: bridge subscribes VOLATILE, see traceability table*

### Testing & Deployment

- [x] **TEST-01**: Test assertions fixed — `test_humidity_control` tests actuator state, not pin number
- [x] **TEST-02**: Full control loop verified on real FC-1 hardware (sensor → control → actuator)
- [x] **DEPL-01**: System runs stably on Pi and is suitable for grower handoff (better than timer) — *qualitative "better than timer" grower attestation pending, not blocking*

### Historical Data & Visualization

- [x] **HIST-01**: Bridge service ingests all 4 ROS topics (humidity, temperature, CO2, humidifier) into TimescaleDB with every reading stored at full resolution
- [x] **HIST-02**: TimescaleDB schema auto-initialized on bridge startup (CREATE TABLE IF NOT EXISTS + hypertable), no manual migration required
- [x] **HIST-03**: Database credentials managed via .env file, not hardcoded in docker-compose.yml
- [x] **HIST-04**: REST history endpoint (GET /history/:topic) serves time-bucketed downsampled data from TimescaleDB
- [x] **HIST-05**: OpenMCT time conductor defaults to last 24 hours and charts display historical sensor/actuator data via the plugin request() method
- [x] **HIST-06**: Bridge container runs Node.js entrypoint (replacing rosbridge Python) and continues live WebSocket broadcast even when DB is unavailable

### Camera & Visual Monitoring

- [x] **CAM-01**: Camera node publishes `sensor_msgs/CompressedImage` on `fc1/camera/compressed` ROS2 topic from USB webcam via OpenCV
- [x] **CAM-02**: Camera parameters (device, resolution, fps, JPEG quality) configurable in `fc_config.yaml` with simulation mode default
- [~] **CAM-03**: Bridge serves MJPEG stream at `/camera/mjpeg` by subscribing to the ROS2 CompressedImage topic and re-serving frames via HTTP multipart — *endpoint wired, live delivery intermittent due to CycloneDDS stale-subscriber tech debt*
- [x] **CAM-04**: Bridge captures periodic snapshots (configurable interval) to date-organized directory on elder-plops filesystem with metadata logging
- [x] **CAM-05**: OpenMCT displays camera feed as a dedicated view (custom view provider with `<img>` tag, not chart) in the Fruiting Chamber FC-1 tree

## v2 Requirements

### Temperature Control

- **TEMP-01**: Temperature sensor reading from FC-1
- **TEMP-02**: Closed-loop temperature control (heating/cooling actuator)
- **TEMP-03**: Temperature setpoint configurable per chamber

### CO2 Control

- **CO2-01**: CO2 sensor reading and publishing
- **CO2-02**: CO2 setpoint control via ventilation actuator

### Multi-Chamber

- **MC-01**: FC-2 hardware setup and integration
- **MC-02**: Per-chamber configuration profiles
- **MC-03**: Chamber status dashboard in OpenMCT

### Advanced Control

- **ADV-01**: PWM-based proportional humidity control (if actuator supports it)
- **ADV-02**: PID controller with tuning support (Phase 2+ only)
- **ADV-03**: Alarm/notification system for out-of-range conditions

## Out of Scope

| Feature | Reason |
|---------|--------|
| PID control algorithm | Wrong for on/off actuator — bang-bang is correct. PID needs duty-cycle logic, out of MVP scope |
| Temperature control | Defer to Phase 2; framework exists, logic not required for humidity MVP |
| CO2 control | Defer to Phase 2+; no sensors or actuators in scope |
| FC-2 integration | Hardware open question; multi-chamber scaling deferred |
| OpenMCT UI enhancements | Existing display sufficient; topics will auto-appear in mission control |
| PWM humidifier control | Current actuator is on/off MOSFET; PWM requires different hardware |
| Alarm/notification system | Not required to beat timer solution; Phase 2+ |

## Traceability

| Requirement | Phase | Status | Notes |
|-------------|-------|--------|-------|
| INFRA-01 | Phase 1 | Complete | SSH via Tailscale `fc1-ts` verified 2026-04-11 |
| INFRA-02 | Phase 1 | Complete | Primary via Tailscale; WireGuard `wg0` up as secondary |
| INFRA-03 | Phase 1 | Complete | `scripts/pi-deploy/deploy.sh` (git-based, `fc1/prod`) + `fc-update.service` systemd oneshot |
| INFRA-04 | Phase 1 | Complete | `ros2 topic list` on Pi shows all 5 `/fc1/*` topics; bridge subscribes over CycloneDDS unicast |
| HW-01 | Phase 1 | Complete | Ubuntu 24.04 ARM64, RPi.GPIO importable, kernel 6.8.0-1051-raspi |
| HW-02 | Phase 1 | Complete | humidifier_pin 27, `fc_controller` running, physical attestation at Phase 01 |
| HW-03 | Phase 1 | Complete | Physical pull-down attested; journal shows no "humidifier stuck ON at boot" |
| SENS-01 | Phase 1 | Complete | SHT30 originally wired + validated at 22.6°C/88.5%; currently unplugged, humidity served by SCD41 via documented D-11 fallback path. 19.2°C / 76% readings live at audit time. |
| SENS-03 | Phase 2 | Complete | Non-blocking sensor error handling |
| SENS-04 | Phase 2 | Complete | Normalization consistent across paths |
| SENS-05 | Phase 2 | Complete | Spike rejection in place (less critical for I2C sensors but preserved) |
| CTRL-01 | Phase 3 | Complete | Bang-bang hysteresis at ±0.05 around 0.80 |
| CTRL-02 | Phase 3 | Complete | Setpoint + deadband in fc_config.yaml |
| CTRL-03 | Phase 3 | Complete | min_dwell_time 180s |
| CTRL-04 | Phase 3 | Complete | Stale sensor timeout 10s |
| CTRL-05 | Phase 3 | Complete | Sensor failure → safe OFF |
| ACTR-02 | Phase 2 | Complete | Pin configurable via fc_config.yaml |
| TEST-01 | Phase 2 | Complete | Tests assert actuator state not pin number |
| SENS-02 | Phase 4 | Complete | `/fc1/humidity` publishing in consistent 0–1 range |
| ACTR-01 | Phase 4 | Complete | Humidifier GPIO toggles on state changes (~2235 events in 50 min DB sample) |
| ACTR-03 | Phase 4 | Complete (tech debt) | `/fc1/actuators/humidifier` published TRANSIENT_LOCAL; bridge subscribes VOLATILE (QoS mismatch, data flows but last-state replay on restart is missed — tech debt) |
| TEST-02 | Phase 4 | Complete | E2E hardware verified — sensor→control→actuator→bridge→DB→chart |
| DEPL-01 | Phase 5 | Complete | Pi continuous uptime >24h on current boot; ~5 days operation since deploy; qualitative "better than timer" attestation captured as pending human confirmation, not blocking |
| HIST-01 | Phase 7 | Complete | Bridge ingests 4 ROS topics to TimescaleDB |
| HIST-02 | Phase 7 | Complete | Schema auto-init on bridge startup (hypertable + index) |
| HIST-03 | Phase 7 | Complete | `TIMESCALE_PASSWORD` via root `.env`, fail-fast if missing |
| HIST-04 | Phase 7 | Complete | `/history/:topic` with `time_bucket` downsampling |
| HIST-05 | Phase 7 | Complete | OpenMCT "24h Fixed" default time conductor |
| HIST-06 | Phase 7 | Complete | Node.js bridge, live WebSocket independent of DB state |
| CAM-01 | Phase 8 | Complete | `fc_camera` publishing `/fc1/camera/compressed` at 1Hz |
| CAM-02 | Phase 8 | Complete | Camera params in fc_config.yaml deployed and live |
| CAM-03 | Phase 8 | Partial (tech debt) | `/camera/mjpeg` endpoint exists and served a 23KB JPEG on snapshot; live MJPEG delivery intermittent due to CycloneDDS stale subscriber at 192.168.1.193 (tech debt) |
| CAM-04 | Phase 8 | Complete | Snapshots saving to `/data/snapshots/fc1/YYYY-MM-DD/` at 15-min interval |
| CAM-05 | Phase 8 | Complete (runtime depends on CAM-03) | OpenMCT plugin wires camera type + view provider, hostname resolved dynamically |

**Coverage:**
- v1 requirements: 31 total
- Mapped to phases: 31
- Unmapped: 0
- Fully complete: 29
- Partial (tech debt): 2 (ACTR-03 QoS mismatch, CAM-03 live MJPEG delivery)

**Tech debt carried forward to v1.1:**
- ACTR-03: bridge subscription should specify `{durability: 'transient_local'}` to match publisher
- CAM-03: investigate stale CycloneDDS subscriber at 192.168.1.193 causing camera topic write failures

---
*Requirements defined: 2026-03-28*
*Last updated: 2026-04-11 during milestone v1.0 audit paperwork closure*
