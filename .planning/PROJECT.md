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
- ✓ DHT22 sensor integration (temperature/humidity reading)
- ✓ OpenMCT mission control bridge
- ✓ Configuration system (fc_config.yaml)
- ✓ GPIO and hardware abstraction layer

### Validated in Phase 01 (Hardware & Environment)

- ✓ Humidity/temperature sensor reading from SHT30 on FC-1 (I2C 0x44)
- ✓ Publish sensor data to ROS topics `fc/humidity` and `fc/temperature`
- ✓ SSR-10A actuator wiring (GPIO17) + humidifier actuator state control via ROS
- ✓ Deploy pipeline: rsync + colcon build + systemd auto-restart
- ✓ Live telemetry visible on OpenMCT dashboard

### Validated in Phase 02 (Safety Hardening)

- ✓ Non-blocking sensor error handling (SENS-03)
- ✓ Config cleaned up for SHT30/SSR-10A hardware (SENS-04)
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

- ✓ Actuator state published on `fc/actuators/humidifier` with TRANSIENT_LOCAL QoS (ACTR-03)
- ✓ Humidifier GPIO activates/deactivates via control loop on FC-1 (ACTR-01)
- ✓ Humidity published correctly on `fc/humidity` in 0.0-1.0 range (SENS-02)
- ✓ OpenMCT dashboard extended with CO2 and humidifier state charts (D-04, D-05)
- ✓ SCD41 CO2 sensor integrated, publishing on `fc/co2`
- ⏳ Full soak test pending Pi relocation to farm (TEST-02 partial — tracked in 04-HUMAN-UAT.md)

### Active

MVP scope remaining:

- [ ] Production deployment readiness

### Out of Scope

- Temperature control — defer to Phase 2 (framework ready, logic pending)
- CO2 monitoring and control — defer to Phase 2+
- Multi-chamber scaling / FC-2 integration — open question for roadmap
- Advanced features: tuning, optimization, safety interlocks — Phase 2+
- OpenMCT UI enhancements — display existing topics first, UI polish later

## Context

**Current State:**
- Phase 01 complete: SHT30 live, SSR-10A wired, deploy pipeline working
- Phase 02 complete: sensor hardened, config clean, spike rejection active, GPIO configurable
- Phase 03 complete: bang-bang control with dwell time guard, staleness detection, safe failure state
- Phase 04 complete: actuator state topic, OpenMCT CO2/humidifier charts, FC-1 hardware verified
- Phase 07 complete: bridge migrated to Node.js, TimescaleDB ingestion for all 4 topics, REST history endpoint with time_bucket downsampling, OpenMCT historical charts with 24h Fixed default
- Remaining: production deploy (Phase 05), FarmOS integration (Phase 08)

**Hardware Setup:**
- Fruiting chamber 1 (FC-1) with Raspberry Pi
- DHT22 humidity sensor (wired)
- MOSFET for humidifier control (component available, wiring TBD)
- No temperature or CO2 sensors in scope for MVP

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

*Last updated: 2026-04-04 after Phase 04 completion*
