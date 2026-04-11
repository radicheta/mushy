# Mushroom Farm MVP: Humidity Control on FC-1

## What This Is

A closed-loop humidity control system for fruiting chamber 1 (FC-1) running on Raspberry Pi, replacing the current timer-based solution with active sensor feedback and actuator control. Integrates with the existing ROS2 system and is production-ready for single-chamber operation.

## Core Value

**A working, production-ready humidity control loop that's better than the current timer solution and ready to ship to growers.**

## Requirements

### Validated

Existing codebase provides:

- ✓ ROS2 Jazzy node framework for fruiting chamber control
- ✓ Docker containerization and orchestration
- ✓ I2C humidity/temperature sensing (SHT30 on 0x44 originally, with documented SCD41 fallback on 0x62 when SHT30 is absent — currently in fallback mode)
- ✓ OpenMCT Mission Control bridge (Node.js, historical + live)
- ✓ Configuration system (fc_config.yaml)
- ✓ GPIO and hardware abstraction layer

### Validated in Phase 01 (Hardware & Environment)

- ✓ Humidity/temperature sensor reading on FC-1 (SHT30 on I2C 0x44 when plugged, SCD41 on 0x62 as documented fallback — currently fallback)
- ✓ Publish sensor data to ROS topics `fc1/humidity` and `fc1/temperature`
- ✓ Humidifier actuator via MOSFET on GPIO27 with pull-down for safe-default-OFF
- ✓ Deploy pipeline: `scripts/pi-deploy/deploy.sh` fast-forwards `fc1/prod` on the Pi's `~/mushroom_farm_ws/mushy-repo/` checkout, runs colcon build, restarts `fc-core.service`. `fc-update.service` systemd oneshot also pulls `fc1/prod` on every boot.
- ✓ Live telemetry visible on Mission Control dashboard

### Validated in Phase 02 (Safety Hardening)

- ✓ Non-blocking sensor error handling (SENS-03)
- ✓ Config cleaned up for I2C sensors + MOSFET hardware (SENS-04)
- ✓ Rolling median spike rejection in humidity_callback (SENS-05)
- ✓ Humidifier GPIO pin configurable from fc_config.yaml (ACTR-02)
- ✓ Test assertions fixed and passing (TEST-01)

### Validated in Phase 03 (Closed-Loop Control)

- ✓ Closed-loop bang-bang control with hysteresis (CTRL-01)
- ✓ Configurable setpoint, deadband, dwell time, staleness timeout (CTRL-02)
- ✓ Minimum dwell time guard prevents rapid actuator cycling (CTRL-03)
- ✓ Stale sensor data detection triggers safe state (CTRL-04)
- ✓ Sensor failure drives humidifier OFF, not frozen last state (CTRL-05)

### Validated in Phase 04 (Observability & Integration)

- ✓ Actuator state published on `fc1/actuators/humidifier` with TRANSIENT_LOCAL QoS (ACTR-03) — bridge subscribes with default VOLATILE QoS; data flows but last-state replay on restart is a tech-debt item deferred to v1.1
- ✓ Humidifier GPIO activates/deactivates via control loop on FC-1 (ACTR-01)
- ✓ Humidity published correctly on `fc1/humidity` in 0.0–1.0 range (SENS-02)
- ✓ Mission Control dashboard extended with CO2 and humidifier state charts (D-04, D-05)
- ✓ SCD41 CO2 sensor integrated, publishing on `fc1/co2`
- ✓ Full soak test — Pi ran continuously for ~24h on current boot and ~5 days across the deploy window (TEST-02, DEPL-01 verified 2026-04-11)

### Current State

**v1.0 MVP shipped 2026-04-11.** Grower attested "better than the timer" —
passes. See `.planning/MILESTONES.md` and `.planning/milestones/v1.0-*`.

## Current Milestone: v1.1 Tech Debt & Connectivity

**Goal:** Close v1.0 tech debt bugs and get reliable farm connectivity to fc1.

**Target scope:**
- ACTR-03 bridge QoS alignment (`transient_local`) so last-state replays on bridge restart
- CAM-03 phantom CycloneDDS subscriber at `192.168.1.193` stalling live MJPEG delivery
- fc-core boot race on `tailscale0` interface (~4 restarts on each Pi cold boot)
- 4G hotspot for reliable fc1 farm connectivity (unblocks stalled Phase 08-04 deploy)

**Explicitly deferred from v1.1:**
- SHT30 physical reinstall — sensor redundancy is nice-to-have; SCD41 fallback works
- CO2-first features — routed to a separate `/gsd:explore` session for v2.0 themes
- Backlog 999.x promotions (edge buffering, Signal alerts, fan/light telemetry) — v2.0+

### Out of Scope

- Temperature control — defer to Phase 2 (framework ready, logic pending)
- CO2 monitoring and control — defer to Phase 2+
- Multi-chamber scaling / FC-2 integration — open question for roadmap
- Advanced features: tuning, optimization, safety interlocks — Phase 2+
- OpenMCT UI enhancements — display existing topics first, UI polish later

## Context

**Current State:**
- Phases 01–08 complete. v1.0 milestone achieved 2026-04-11.
- Phase 01: I2C humidity/temp sensing live, humidifier MOSFET wired, git-based deploy pipeline
- Phase 02: sensor hardened, config clean, spike rejection, GPIO configurable
- Phase 03: bang-bang control with dwell time guard, staleness detection, safe failure state
- Phase 04: actuator state topic, Mission Control CO2/humidifier charts, E2E hardware verified
- Phase 05: production deployed to FC-1, multi-day soak test passed
- Phase 06: WireGuard + Tailscale mesh, CycloneDDS unicast for ROS DDS over VPN
- Phase 07: Node.js bridge with TimescaleDB ingestion and `/history/:topic` REST (Mission Control historical data was silently broken for weeks due to compose-file drift — fixed during audit closure 2026-04-11)
- Phase 08: fc_camera ROS2 node, MJPEG bridge endpoint, snapshot archive, Mission Control camera view (live MJPEG delivery carries tech debt — see Active)

**Hardware Setup:**
- Fruiting chamber 1 (FC-1) with Raspberry Pi 4 (Ubuntu 24.04 aarch64)
- SHT30 humidity/temperature sensor on I2C 0x44 (physically disconnected as of 2026-04-11 — fc_sensors falls back to SCD41 for humidity when SHT30 is absent)
- SCD41 CO2/temp/humidity sensor on I2C 0x62 (currently the active humidity source)
- MOSFET for humidifier control on GPIO27 with pull-down resistor
- USB webcam at /dev/video0 (640x480 @ 1fps)
- No dedicated temperature or ventilation actuator in v1 scope

**Production Pressure:**
- Current solution: timer-based humidification (no feedback)
- Need: alternative control method ready for production use
- Goal: ship improved solution even if not feature-complete
- Flexibility: can defer non-MVP features without blocking release

**Development Environment:**
- ROS2 Jazzy with colcon build system
- Python-based nodes
- Simulation mode available for testing without hardware
- Existing test framework and patterns in codebase

## Constraints

- **Hardware**: Single chamber (FC-1 only) for MVP — multi-chamber deferred
- **Timeline**: Production-driven (ASAP) — acceptable to ship incomplete features if core loop works
- **Dependencies**: Must integrate with existing ROS2 system, not fork/replace
- **Reliability**: Must be stable enough for grower operation (better than timer)
- **Compatibility**: Runs on Raspberry Pi with existing GPIO and sensor setup

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Single-chamber MVP (FC-1 only) | Keep scope manageable for quick delivery; multi-chamber scaling is separate concern | — Pending |
| Use existing ROS infrastructure | Avoid reinventing; integrate with proven system | — Pending |
| MOSFET for humidifier control | Existing hardware choice; simple, reliable | — Pending |
| Closed-loop setpoint control | Better than timer; proportional control insufficient, need feedback | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (e.g., after Phase 1 completes):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After this milestone completes:**
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid? (especially Temp/CO2 control timing)
4. Update Context with production learnings

---

*Last updated: 2026-04-11 at start of v1.1 milestone*
