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

### Active

MVP scope for this milestone:

- [ ] Humidity sensor reading from DHT22 on FC-1
- [ ] Publish humidity data to ROS topic `fc/humidity`
- [ ] MOSFET actuator wiring and GPIO control
- [ ] Humidifier actuator state control via ROS
- [ ] Closed-loop control algorithm (maintain setpoint)
- [ ] Test on real hardware (Raspberry Pi + sensors + actuator)
- [ ] Production deployment readiness

### Out of Scope

- Temperature control — defer to Phase 2 (framework ready, logic pending)
- CO2 monitoring and control — defer to Phase 2+
- Multi-chamber scaling / FC-2 integration — open question for roadmap
- Advanced features: tuning, optimization, safety interlocks — Phase 2+
- OpenMCT UI enhancements — display existing topics first, UI polish later

## Context

**Current State:**
- 50-75% of humidity control logic already implemented
- Core ROS/Docker infrastructure established
- DHT22 sensors wired and functional
- MOSFET actuator component available, needs wiring during development

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

*Last updated: 2026-03-28 after project initialization*
