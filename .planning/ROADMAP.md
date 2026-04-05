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
- [ ] 05-01-PLAN.md — Update config (target_humidity 0.80), create OPERATIONS.md and grower checklist
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

---
*Roadmap created: 2026-03-28*
*Milestone: MVP — FC-1 Humidity Control*
