# Requirements: Mushroom Farm MVP — FC-1 Humidity Control

**Defined:** 2026-03-28
**Core Value:** A working, production-ready humidity control loop that's better than the current timer solution and ready to ship to growers.

## v1 Requirements

### Infrastructure

- [x] **INFRA-01**: Developer can SSH into FC-1 Pi using key-based auth (no password)
- [x] **INFRA-02**: WireGuard VPN configured on Pi and reachable from developer workstation on mesh network
- [ ] **INFRA-03**: Development workflow documented — how to deploy code changes to Pi and restart nodes
- [x] **INFRA-04**: ROS2 nodes running on Pi are visible from workstation (`ros2 topic list` across machines, `ROS_DOMAIN_ID=69`)

### Hardware

- [x] **HW-01**: Pi OS and GPIO library compatibility confirmed before any GPIO work begins
- [ ] **HW-02**: MOSFET actuator wired to humidifier system on FC-1
- [ ] **HW-03**: MOSFET gate pull-down resistor installed (humidifier defaults OFF on Pi boot/crash)

### Sensing

- [x] **SENS-01**: DHT22 humidity reading works reliably on real hardware (not just simulation)
- [ ] **SENS-02**: Humidity published to `fc/humidity` ROS topic in consistent 0.0–1.0 range
- [x] **SENS-03**: Non-blocking sensor error handling (remove `time.sleep()` from sensor callback)
- [x] **SENS-04**: Sensor normalization is consistent between real hardware and simulation paths
- [x] **SENS-05**: DHT22 spike rejection filters outlier readings before control loop

### Control

- [x] **CTRL-01**: Closed-loop bang-bang control maintains humidity setpoint with hysteresis
- [x] **CTRL-02**: Setpoint and deadband (on/off thresholds) configurable via `fc_config.yaml`
- [x] **CTRL-03**: Minimum dwell time enforced — humidifier cannot cycle faster than configurable interval
- [x] **CTRL-04**: Stale sensor data detected — control loop does not act on data older than threshold
- [x] **CTRL-05**: Sensor failure drives humidifier to safe state (OFF), not frozen last state

### Actuator

- [ ] **ACTR-01**: Humidifier controlled via MOSFET GPIO pin (on/off)
- [x] **ACTR-02**: Humidifier GPIO pin is configurable in `fc_config.yaml` (not hardcoded)
- [ ] **ACTR-03**: Actuator state published to `fc/actuators/humidifier` (`std_msgs/Bool`, `TRANSIENT_LOCAL`)

### Testing & Deployment

- [x] **TEST-01**: Test assertions fixed — `test_humidity_control` tests actuator state, not pin number
- [ ] **TEST-02**: Full control loop verified on real FC-1 hardware (sensor → control → actuator)
- [ ] **DEPL-01**: System runs stably on Pi and is suitable for grower handoff (better than timer)

### Historical Data & Visualization

- [ ] **HIST-01**: Bridge service ingests all 4 ROS topics (humidity, temperature, CO2, humidifier) into TimescaleDB with every reading stored at full resolution
- [ ] **HIST-02**: TimescaleDB schema auto-initialized on bridge startup (CREATE TABLE IF NOT EXISTS + hypertable), no manual migration required
- [ ] **HIST-03**: Database credentials managed via .env file, not hardcoded in docker-compose.yml
- [ ] **HIST-04**: REST history endpoint (GET /history/:topic) serves time-bucketed downsampled data from TimescaleDB
- [ ] **HIST-05**: OpenMCT time conductor defaults to last 24 hours and charts display historical sensor/actuator data via the plugin request() method
- [ ] **HIST-06**: Bridge container runs Node.js entrypoint (replacing rosbridge Python) and continues live WebSocket broadcast even when DB is unavailable

### Camera & Visual Monitoring

- [ ] **CAM-01**: Camera node publishes `sensor_msgs/CompressedImage` on `fc1/camera/compressed` ROS2 topic from USB webcam via OpenCV
- [ ] **CAM-02**: Camera parameters (device, resolution, fps, JPEG quality) configurable in `fc_config.yaml` with simulation mode default
- [ ] **CAM-03**: Bridge serves MJPEG stream at `/camera/mjpeg` by subscribing to the ROS2 CompressedImage topic and re-serving frames via HTTP multipart
- [ ] **CAM-04**: Bridge captures periodic snapshots (configurable interval) to date-organized directory on elder-plops filesystem with metadata logging
- [ ] **CAM-05**: OpenMCT displays camera feed as a dedicated view (custom view provider with `<img>` tag, not chart) in the Fruiting Chamber FC-1 tree

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

| Requirement | Phase | Status |
|-------------|-------|--------|
| INFRA-01 | Phase 1 | Complete |
| INFRA-02 | Phase 1 | Complete |
| INFRA-03 | Phase 1 | Pending |
| INFRA-04 | Phase 1 | Complete |
| HW-01 | Phase 1 | Complete |
| HW-02 | Phase 1 | Pending |
| HW-03 | Phase 1 | Pending |
| SENS-01 | Phase 1 | Complete |
| SENS-03 | Phase 2 | Complete |
| SENS-04 | Phase 2 | Complete |
| SENS-05 | Phase 2 | Complete |
| CTRL-01 | Phase 3 | Complete |
| CTRL-02 | Phase 3 | Complete |
| CTRL-03 | Phase 3 | Complete |
| CTRL-04 | Phase 3 | Complete |
| CTRL-05 | Phase 3 | Complete |
| ACTR-02 | Phase 2 | Complete |
| TEST-01 | Phase 2 | Complete |
| SENS-02 | Phase 4 | Pending |
| ACTR-01 | Phase 4 | Pending |
| ACTR-03 | Phase 4 | Pending |
| TEST-02 | Phase 4 | Pending |
| DEPL-01 | Phase 5 | Pending |
| HIST-01 | Phase 7 | Pending |
| HIST-02 | Phase 7 | Pending |
| HIST-03 | Phase 7 | Pending |
| HIST-04 | Phase 7 | Pending |
| HIST-05 | Phase 7 | Pending |
| HIST-06 | Phase 7 | Pending |
| CAM-01 | Phase 8 | Pending |
| CAM-02 | Phase 8 | Pending |
| CAM-03 | Phase 8 | Pending |
| CAM-04 | Phase 8 | Pending |
| CAM-05 | Phase 8 | Pending |

**Coverage:**
- v1 requirements: 31 total
- Mapped to phases: 31
- Unmapped: 0

---
*Requirements defined: 2026-03-28*
*Last updated: 2026-04-08 after adding CAM-01 to CAM-05 for Phase 8*
