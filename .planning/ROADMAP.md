# Roadmap: Mushroom Farm MVP — FC-1 Humidity Control

## Overview

Starting from a 50-75% complete humidity control implementation, this roadmap delivers a production-ready closed-loop system on Raspberry Pi for FC-1. The path: confirm hardware environment first, then harden the software safety layer, then complete the control algorithm, then wire up observability, and finally validate and deploy. Each phase gates the next — no shortcuts. The goal is "better than timer" in production, not perfection.

## Phases

- [x] **Phase 1: Pi Integration & Environment** - SSH access, VPN/networking, dev workflow, OS confirm, MOSFET wiring, DHT22 validation (completed 2026-03-29)
- [x] **Phase 2: Safety Hardening** - Fix critical bugs before any hardware test (blocking sleep, normalization, spike rejection) (completed 2026-03-30)
- [ ] **Phase 3: Closed-Loop Control** - Complete control algorithm with min dwell time, stale data detection, safe failure state
- [ ] **Phase 4: Observability & Integration** - Actuator state topic, end-to-end hardware validation
- [ ] **Phase 5: Production Deployment** - Deploy to FC-1, validate with grower, declare better than timer

## Phase Details

### Phase 1: Pi Integration & Environment
**Goal**: Developer can SSH into FC-1 Pi, deploy code, and run the ROS stack. All hardware is wired. DHT22 reads correctly on real hardware.
**Depends on**: Nothing (first phase)
**Requirements**: INFRA-01, INFRA-02, INFRA-03, INFRA-04, HW-01, HW-02, HW-03, SENS-01
**Success Criteria** (what must be TRUE):
  1. Developer can SSH into FC-1 Pi from workstation (with and without VPN)
  2. WireGuard VPN config deployed and Pi is reachable on the mesh network
  3. Code deploy workflow defined — can push and run updated nodes on Pi
  4. ROS2 stack launches on Pi and is visible on the ROS domain from workstation
  5. Pi OS confirmed and GPIO library (RPi.GPIO or rpi-lgpio) validated
  6. MOSFET wired to humidifier with gate pull-down resistor installed
  7. DHT22 reports valid humidity readings via `ros2 topic echo fc/humidity` on real hardware

Plans:
- [x] 01-01: SSH key setup and Pi network/VPN configuration (WireGuard)
- [x] 01-02: Development workflow setup (deploy, iterate, observe logs on Pi)
- [x] 01-03: Confirm Pi OS, validate GPIO library compatibility, document dependency choice
- [x] 01-04: Wire MOSFET actuator (with gate pull-down resistor) and verify GPIO control from Pi
- [x] 01-05: Validate DHT22 reading on real hardware end-to-end through ROS stack

### Phase 2: Safety Hardening
**Goal**: All critical blocking bugs fixed — the codebase is safe to run on real hardware without damaging the humidifier or crashing the control loop.
**Depends on**: Phase 1
**Requirements**: SENS-03, SENS-04, SENS-05, ACTR-02, TEST-01
**Success Criteria** (what must be TRUE):
  1. `fc_sensors.py` exception handler uses non-blocking retry (no `time.sleep()` in callbacks)
  2. Humidity values are in consistent 0.0–1.0 range in both simulation and real hardware paths
  3. DHT22 spike rejection filters outlier readings before they reach the control loop
  4. Humidifier GPIO pin is configurable in `fc_config.yaml` (not hardcoded to 17)
  5. `test_humidity_control` tests actuator state (on/off), not pin number

Plans:
- [x] 02-01: Fix `time.sleep()` blocking call in `fc_sensors.py` exception handler
- [x] 02-02: Fix sensor normalization inconsistency between real hardware and simulation paths
- [x] 02-03: Add DHT22 spike rejection to sensor reading pipeline
- [x] 02-04: Make humidifier pin configurable in config + fix broken test assertions

### Phase 3: Closed-Loop Control
**Goal**: Control algorithm is complete and correct — maintains setpoint, won't damage the actuator, and fails safe when sensor data is missing or stale.
**Depends on**: Phase 2
**Requirements**: CTRL-01, CTRL-02, CTRL-03, CTRL-04, CTRL-05
**Success Criteria** (what must be TRUE):
  1. Humidifier turns on when humidity drops below lower threshold, off when it exceeds upper threshold
  2. Setpoint and deadband thresholds are configurable in `fc_config.yaml` (grower-readable names)
  3. Humidifier cannot cycle more often than `min_dwell_time` config parameter
  4. Stale sensor data (older than configurable threshold) triggers safe state (humidifier OFF)
  5. Sensor failure drives humidifier to OFF, not frozen last state

Plans:
- [x] 03-01: Implement/complete bang-bang hysteresis control with configurable setpoint and deadband
- [x] 03-02: Add minimum dwell time guard to prevent rapid actuator cycling
- [x] 03-03: Add sensor staleness detection and safe failure state logic

### Phase 4: Observability & Integration
**Goal**: System is fully integrated — actuator state is visible in ROS, and the complete control loop is verified working end-to-end on FC-1 hardware.
**Depends on**: Phase 3
**Requirements**: SENS-02, ACTR-01, ACTR-03, TEST-02
**Plans:** 2 plans
**Success Criteria** (what must be TRUE):
  1. `fc/humidity` topic publishes correct readings visible via `ros2 topic echo`
  2. Humidifier activates and deactivates via GPIO on control commands
  3. `fc/actuators/humidifier` topic (`std_msgs/Bool`, `TRANSIENT_LOCAL`) publishes actuator state
  4. Full control loop verified on FC-1: sensor reads → control decision → humidifier actuates

Plans:
- [x] 04-01-PLAN.md — Actuator state publisher (ACTR-03) + OpenMCT dashboard extension (CO2 + humidifier charts)
- [x] 04-02-PLAN.md — Deploy to FC-1, restore production config, end-to-end hardware soak test (TEST-02)

### Phase 5: Production Deployment
**Goal**: System is running on FC-1 in production, replacing the timer, and is stable enough for grower operation.
**Depends on**: Phase 4
**Requirements**: DEPL-01
**Plans:** 2 plans
**Success Criteria** (what must be TRUE):
  1. System runs continuously on FC-1 Pi without crashes
  2. Humidity maintains target range (75–85%) demonstrably better than the timer did
  3. Grower can observe system state (humidity reading + humidifier on/off)
  4. Known constraints documented (Pi 4 only, GPIO library deprecation path)

Plans:
- [x] 05-01-PLAN.md — Update config (target_humidity 0.80), create OPERATIONS.md and grower checklist
- [ ] 05-02-PLAN.md — Deploy to FC-1, 24-hour soak test, production declaration

## Progress

**Execution Order:** 1 → 2 → 3 → 4 → 5

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Pi Integration & Environment | 5/5 | Complete   | 2026-03-29 |
| 2. Safety Hardening | 4/4 | Complete   | 2026-03-30 |
| 3. Closed-Loop Control | 2/3 | In Progress|  |
| 4. Observability & Integration | 0/2 | Not started | - |
| 5. Production Deployment | 0/2 | Not started | - |

**Total:** 0/17 plans complete

### Phase 6: WireGuard VPN routing for ROS traffic

**Goal:** FC-1 Pi and elder-plops on an always-on WireGuard mesh (172.16.10.0/24) with ROS2 topic visibility over the VPN tunnel via CycloneDDS unicast peer discovery.
**Requirements**: INFRA-02, INFRA-04
**Depends on:** Phase 1 (Pi must be accessible via SSH; independent of Phases 2-5)
**Plans:** 2/3 plans executed

Plans:
- [x] 06-01-PLAN.md — Install WireGuard on FC-1 Pi, generate keys, deploy wg0.conf, enable service
- [x] 06-02-PLAN.md — Register Pi peer in pfSense, enable elder-plops autoconnect, verify mesh connectivity
- [x] 06-03-PLAN.md — Install ROS2 + CycloneDDS on elder-plops, deploy unicast XML config, verify E2E topic visibility

### Phase 7: Historical data storage and OpenMCT time-series visualization

**Goal:** Wire up the existing TimescaleDB container to ingest ROS telemetry from the bridge service and serve historical data to OpenMCT, enabling time-series charts of past sensor/actuator readings.
**Requirements**: HIST-01, HIST-02, HIST-03, HIST-04, HIST-05, HIST-06
**Depends on:** Phase 6
**Plans:** 2 plans

Plans:
- [x] 07-01-PLAN.md — Switch bridge to Node.js entrypoint, add TimescaleDB ingestion for all 4 topics, migrate credentials to .env
- [x] 07-02-PLAN.md — Add REST history endpoint with time_bucket downsampling, wire OpenMCT plugin request() and WebSocket handler

### Phase 8: Pi Camera Feed in Mission Control

**Goal:** USB webcam on fc1 Pi streams live video accessible from Mission Control (OpenMCT). Foundation for future vision features (time-lapse, contamination detection, growth monitoring).
**Requirements**: CAM-01, CAM-02, CAM-03, CAM-04, CAM-05
**Depends on:** Phase 7
**Plans:** 4 plans
**Status:** Blocked — all code committed, Pi deploy + human verification pending (fc1 offline, awaiting 4G hotspot)

Plans:
- [x] 08-01-PLAN.md — Create ROS2 camera node (fc_camera.py) with OpenCV capture, config, launch, and unit tests
- [x] 08-02-PLAN.md — Add MJPEG streaming endpoint and snapshot storage to bridge, update docker-compose
- [x] 08-03-PLAN.md — Add camera view to OpenMCT plugin with custom view provider, human verify
- [~] 08-04-PLAN.md — Gap closure: camera name fix, production URLs, disable simulation mode (code done, deploy blocked)

## Backlog

### Phase 999.1: Edge buffering — local telemetry on Pi with store-and-forward sync (BACKLOG)

**Goal:** Local SQLite/TimescaleDB buffer on fc1 Pi stores telemetry readings regardless of connectivity. A sync agent forwards buffered data to elder-plops when Tailscale/internet reconnects. Prevents data gaps during network outages at the farm.
**Requirements:** TBD
**Plans:** 0 plans

Plans:
- [ ] TBD (promote with /gsd-review-backlog when ready)

### Phase 999.2: FarmOS Integration (BACKLOG)

**Goal:** Integrate with farm-wide FarmOS instance for mushroom production tracking. Contribute fungi schema, build ROS→FarmOS API bridge for automated observations, configure farmer data entry workflows. Blocked on farm team completing schema design and production instance setup.
**Requirements:** TBD
**Plans:** 0 plans

Plans:
- [ ] TBD (promote with /gsd-review-backlog when ready)

### Phase 999.3: Alerts & Notifications (BACKLOG)

**Goal:** Proactive alerts when things go wrong — sensor failures, humidity/CO2 out of range, Pi offline, actuator stuck. Telegram bot for mobile notifications (free, simple, works on farm). Alert deduplication so you don't get spammed. Alert history in TimescaleDB.
**Foundation:** Bridge `/health` endpoint exists. All sensor values already flow through bridge to DB. WebSocket broadcast infrastructure in place.
**Builds from scratch:** Threshold engine, alert state machine, Telegram integration, alert persistence.
**Requirements:** TBD
**Plans:** 0 plans

Plans:
- [ ] TBD (promote with /gsd-review-backlog when ready)

### Phase 999.4: Environmental Expansion — Fan & Light Telemetry (BACKLOG)

**Goal:** Complete the environmental control picture. Wire HL-52S MOSFET (GPIO27) for independent fan speed control, publish fan PWM duty cycle and light on/off state to ROS topics, ingest both into TimescaleDB, add charts to Mission Control. Fan control already has partial logic (temp-triggered ramp in fc_controller.py) but no configured GPIO pin and no telemetry. Light scheduling already works (GPIO18) but state isn't published.
**Foundation:** HW PWM code exists in fc_controller.py (25kHz, min 50% duty). Light schedule logic exists (6AM start, 12h duration). HL-52S MOSFET physically available, reserved for GPIO27 since Phase 1.
**Needs:** GPIO27 config for fan, fan/light state ROS publishers, bridge subscriptions, DB ingestion, Mission Control charts.
**Requirements:** TBD
**Plans:** 0 plans

Plans:
- [ ] TBD (promote with /gsd-review-backlog when ready)

### Phase 999.5: Vision — Time-lapse & Growth Monitoring (BACKLOG)

**Goal:** Turn the camera snapshot archive into actionable growth intelligence. Auto-compose daily time-lapses from snapshots (already saving JPEG every 15 min to /data/snapshots/fc1/YYYY-MM-DD/). Serve time-lapse videos in Mission Control. Add growth stage classification — detect pinning, primordia, fruiting body maturity from camera frames. Flag contamination (green/black mold, cobweb) with visual alerts. **Grower-facing alerts:** notify when pinning blocks are detected (time to increase FAE) and when fruit bodies are approaching harvest size ("almost ready to pick" — reduces missed flushes and over-mature harvests).
**Foundation:** fc_camera.py captures 640x480 JPEG at 1 FPS. Bridge stores snapshots to date-organized dirs. MJPEG stream and OpenMCT camera view both working. ~96 snapshots/day at 15-min intervals. Alerts integration via Phase 999.3 (Telegram).
**Needs:** FFmpeg time-lapse composition, video serving endpoint, ML inference pipeline (likely lightweight — MobileNet or YOLO on elder-plops, not Pi), training data collection, growth stage labeled dataset (pinning → primordia → mature → overmature), contamination alert integration with Phase 999.3.
**Requirements:** TBD
**Plans:** 0 plans

Plans:
- [ ] TBD (promote with /gsd-review-backlog when ready)

### Phase 999.6: Multi-Chamber Scaling (BACKLOG)

**Goal:** Replicate the system to FC-2, FC-3, etc. Parameterize chamber ID throughout the stack so a second Pi can run the same code with different config. Multi-chamber views in Mission Control — side-by-side comparison, aggregate dashboard.
**Foundation:** Currently hard-coded to "fc1" in ~15 locations across fc_sensors.py, fc_controller.py, fc_camera.py, bridge index.js, plugin.js, and docker-compose.yml. No chamber_id config parameter exists.
**Effort:** 20-30% refactor. Add chamber_id to fc_config.yaml and ROS2 launch params. Parameterize all topic names. Bridge needs multi-chamber subscription loop. Plugin needs per-chamber folder generation in UI tree. Docker compose needs templating or per-chamber overrides.
**Requirements:** TBD
**Plans:** 0 plans

Plans:
- [ ] TBD (promote with /gsd-review-backlog when ready)

### Phase 999.7: Farm Rover — Mobile Inspection & Actuation (BACKLOG)

**Goal:** Autonomous or tele-operated rover that patrols fruiting chambers with onboard camera, airgun (contamination removal / FAE boost), and humidifier nozzle. Extends the static per-chamber system into a mobile platform that can service multiple chambers, get close-up views of individual blocks, and intervene physically. ROS2-native — same stack as the chamber nodes.
**Concept:**
- **Camera:** Onboard USB or CSI camera publishes to `/rover/camera/compressed`. Close-up block inspection, feeds into 999.5 vision pipeline for per-block growth stage classification. Pan/tilt or gimbal for aiming.
- **Airgun actuator:** Compressed air nozzle for blasting contamination off blocks (trich, cobweb) and targeted FAE bursts. GPIO-triggered solenoid valve. Published on `/rover/actuators/airgun`.
- **Humidifier actuator:** Onboard misting nozzle for spot-humidification of dry zones. Pump or solenoid-fed from reservoir. Published on `/rover/actuators/humidifier`.
- **Navigation:** Start with tele-op via Mission Control (joystick widget in OpenMCT). Graduate to waypoint-based autonomous patrol using ROS2 Nav2 stack if chamber layout is mapped.
- **Hardware candidates:** Modified RC chassis with Pi or Jetson Nano, motor driver (L298N or similar), battery + charging dock.
**Foundation:** ROS2 Jazzy stack, CycloneDDS unicast over WireGuard, Mission Control plugin architecture, camera/MJPEG infrastructure from Phase 8, alerting from 999.3.
**Depends on:** 999.5 (vision pipeline for block-level classification), 999.3 (alerts for autonomous intervention triggers), 999.6 (multi-chamber parameterization for rover to move between chambers).
**Requirements:** TBD
**Plans:** 0 plans

Plans:
- [ ] TBD (promote with /gsd-review-backlog when ready)

---
*Roadmap created: 2026-03-28*
*Milestone: MVP — FC-1 Humidity Control*
