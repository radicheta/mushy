# Roadmap: Mushroom Farm MVP — FC-1 Humidity Control

## Overview

Starting from a 50-75% complete humidity control implementation, this roadmap delivers a production-ready closed-loop system on Raspberry Pi for FC-1. The path: confirm hardware environment first, then harden the software safety layer, then complete the control algorithm, then wire up observability, and finally validate and deploy. Each phase gates the next — no shortcuts. The goal is "better than timer" in production, not perfection.

## Phases

- [ ] **Phase 1: Hardware & Environment** - Confirm Pi OS, wire MOSFET, validate DHT22 on real hardware
- [ ] **Phase 2: Safety Hardening** - Fix critical bugs before any hardware test (blocking sleep, normalization, spike rejection)
- [ ] **Phase 3: Closed-Loop Control** - Complete control algorithm with min dwell time, stale data detection, safe failure state
- [ ] **Phase 4: Observability & Integration** - Actuator state topic, end-to-end hardware validation
- [ ] **Phase 5: Production Deployment** - Deploy to FC-1, validate with grower, declare better than timer

## Phase Details

### Phase 1: Hardware & Environment
**Goal**: All hardware is wired, OS and GPIO library path is confirmed, DHT22 reads correctly on real Pi hardware.
**Depends on**: Nothing (first phase)
**Requirements**: HW-01, HW-02, HW-03, SENS-01
**Success Criteria** (what must be TRUE):
  1. Pi OS is identified and GPIO library (RPi.GPIO or rpi-lgpio) is confirmed working
  2. MOSFET wired to humidifier with gate pull-down resistor installed
  3. DHT22 reports valid humidity readings via `ros2 topic echo fc/humidity` on real hardware
  4. Docker container has verified GPIO device passthrough

Plans:
- [ ] 01-01: Confirm Pi OS, validate GPIO library compatibility, document dependency choice
- [ ] 01-02: Wire MOSFET actuator (with gate pull-down resistor) and verify GPIO control from Pi
- [ ] 01-03: Validate DHT22 reading on real hardware end-to-end through ROS stack

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
- [ ] 02-01: Fix `time.sleep()` blocking call in `fc_sensors.py` exception handler
- [ ] 02-02: Fix sensor normalization inconsistency between real hardware and simulation paths
- [ ] 02-03: Add DHT22 spike rejection to sensor reading pipeline
- [ ] 02-04: Make humidifier pin configurable in config + fix broken test assertions

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
- [ ] 03-01: Implement/complete bang-bang hysteresis control with configurable setpoint and deadband
- [ ] 03-02: Add minimum dwell time guard to prevent rapid actuator cycling
- [ ] 03-03: Add sensor staleness detection and safe failure state logic

### Phase 4: Observability & Integration
**Goal**: System is fully integrated — actuator state is visible in ROS, and the complete control loop is verified working end-to-end on FC-1 hardware.
**Depends on**: Phase 3
**Requirements**: SENS-02, ACTR-01, ACTR-03, TEST-02
**Success Criteria** (what must be TRUE):
  1. `fc/humidity` topic publishes correct readings visible via `ros2 topic echo`
  2. Humidifier activates and deactivates via GPIO on control commands
  3. `fc/actuators/humidifier` topic (`std_msgs/Bool`, `TRANSIENT_LOCAL`) publishes actuator state
  4. Full control loop verified on FC-1: sensor reads → control decision → humidifier actuates

Plans:
- [ ] 04-01: Add actuator state publishing to `fc/actuators/humidifier`
- [ ] 04-02: End-to-end hardware validation on FC-1 (sensor → controller → humidifier)

### Phase 5: Production Deployment
**Goal**: System is running on FC-1 in production, replacing the timer, and is stable enough for grower operation.
**Depends on**: Phase 4
**Requirements**: DEPL-01
**Success Criteria** (what must be TRUE):
  1. System runs continuously on FC-1 Pi without crashes
  2. Humidity maintains target range (85–95%) demonstrably better than the timer did
  3. Grower can observe system state (humidity reading + humidifier on/off)
  4. Known constraints documented (Pi 4 only, GPIO library deprecation path)

Plans:
- [ ] 05-01: Production configuration, deployment to FC-1, stability validation

## Progress

**Execution Order:** 1 → 2 → 3 → 4 → 5

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Hardware & Environment | 0/3 | Not started | - |
| 2. Safety Hardening | 0/4 | Not started | - |
| 3. Closed-Loop Control | 0/3 | Not started | - |
| 4. Observability & Integration | 0/2 | Not started | - |
| 5. Production Deployment | 0/1 | Not started | - |

**Total:** 0/13 plans complete

---
*Roadmap created: 2026-03-28*
*Milestone: MVP — FC-1 Humidity Control*
