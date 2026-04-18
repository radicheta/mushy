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

- ✓ Actuator state published on `fc1/actuators/humidifier` with TRANSIENT_LOCAL QoS (ACTR-03) — bridge now also subscribes with TRANSIENT_LOCAL QoS (fixed in Phase 10, TDEBT-01)
- ✓ Humidifier GPIO activates/deactivates via control loop on FC-1 (ACTR-01)
- ✓ Humidity published correctly on `fc1/humidity` in 0.0–1.0 range (SENS-02)
- ✓ Mission Control dashboard extended with CO2 and humidifier state charts (D-04, D-05)
- ✓ SCD41 CO2 sensor integrated, publishing on `fc1/co2`
- ✓ Full soak test — Pi ran continuously for ~24h on current boot and ~5 days across the deploy window (TEST-02, DEPL-01 verified 2026-04-11)

### Validated in v1.1 (Tech Debt & Connectivity)

- ✓ Bridge QoS aligned — humidifier subscription TRANSIENT_LOCAL, last-state replays on bridge restart (TDEBT-01) — v1.1
- ✓ Phantom CycloneDDS peer eliminated — repo config synced to Tailscale, LeaseDuration 5s guard (TDEBT-02) — v1.1
- ✓ fc-core cold boot clean — ExecStartPre polls tailscale0, NRestarts=0 confirmed at farm (TDEBT-03) — v1.1
- ✓ 4G cellular connectivity — fc1 on mossrock-lab MiFi, ROS-over-cellular via Tailscale, dual-location verified (CONN-01) — v1.1
- ✓ fc-system-sync early-boot service — git-shipped /etc config with netplan + wpa_cli reload, future wifi changes via `git push fc1/prod` — v1.1

### Validated in v1.2.1 (Hotfix — camera stall + sensor warmup)

- ✓ fc_camera idle-stall fix — 1 Hz graph-poll on `count_subscribers('/fc1/camera/compressed')`; canonical stall recovery in 9s (HFIX-01..05) — v1.2.1
- ✓ Sensor warm-up grace period — fc_controller early-returns for first 20s post-boot; `/fc1/sensor_health` WARN→OK (SENS-01) — v1.2.1
- ✓ System health panel — six-light strip in Mission Control (Sensors, Camera feed, Humidifier, Bridge, Pi reachable, Grace) via `makeStatusLight` primitive — v1.2.1
- ✓ Replay shim for sensor_health on new WS connect (Phase 16.1) — v1.2.1

### Current State

**v1.0 MVP shipped 2026-04-11.** Grower attested "better than the timer".
**v1.1 Tech Debt & Connectivity shipped 2026-04-12.** All carryover tech debt
closed; fc1 reliably reachable over 4G cellular.
**v1.2 FarmOS Integration & QoL shipped 2026-04-13.** Compose v2 on elder-plops,
subscriber-aware camera, FarmOS daily report (`farmos_agent`). Known gaps carried:
FarmOS admin actions (permissions, FC-1 location), Phase 12 hardware UAT.
**v1.2.1 Hotfix shipped 2026-04-18.** Camera idle-stall fix (9s recovery),
sensor warm-up grace (20s WARN→OK), six-light system health panel with
sensor_health replay shim. Farmer-attested "all green" 2026-04-18.
See `.planning/MILESTONES.md`.

### Out of Scope

- Temperature control — no actuator in v1 scope; revisit when hardware changes
- CO2-triggered ventilation — routed to `/gsd:explore` for v2.0 themes
- Multi-chamber scaling / FC-2 — single-chamber until v2.0+
- PID humidity control — bang-bang with ±1% band is the interim; 999.9 has calibration data
- SHT30 physical reinstall — SCD41 fallback works; sensor redundancy is nice-to-have
- OpenMCT UI enhancements — Mission Control functional; farmer app (999.11) is the next UI surface

## Context

**Current State:**
- v1.0 shipped 2026-04-11 (Phases 01–08). v1.1 shipped 2026-04-12 (Phases 09–10).
- fc-core running continuously on fc1 Pi at the farm over 4G cellular (mossrock-lab MiFi)
- Bang-bang humidity control with ±1% RH operating band, 180s dwell, SCD41 as active sensor
- Mission Control (OpenMCT) stack on elder-plops: bridge + TimescaleDB + camera feed
- Bridge QoS aligned, CycloneDDS config synced to Tailscale, no phantom peers
- fc-system-sync ships /etc config via git — wifi/systemd changes need only `git push fc1/prod`
- Camera at 1 frame/min (4G credit conservation workaround; proper fix is 999.10)
- SHT30 physically disconnected — SCD41 on 0x62 is the sole humidity/temp/CO2 source

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
| Single-chamber MVP (FC-1 only) | Keep scope manageable for quick delivery; multi-chamber scaling is separate concern | ✓ Good — shipped in 14 days |
| Use existing ROS infrastructure | Avoid reinventing; integrate with proven system | ✓ Good — CycloneDDS over Tailscale works well |
| SSR-10A for humidifier (not MOSFET) | Switches 220V AC zapatilla; MOSFET freed for fan | ✓ Good — reliable, GPIO17 |
| Bang-bang with dwell guard | Better than timer; PID deferred to 999.9 | ⚠️ Revisit — ±2% RH structural ceiling; PID needed for tighter control |
| Tailscale over WireGuard | Simpler mesh, survives farm connectivity instability | ✓ Good — 4G cutover was seamless |
| fc-system-sync git-ops deploy | Ship /etc config via git, no SSH needed for wifi/systemd changes | ✓ Good — v1.1 pattern; proven on 4G cutover |
| SCD41 as primary sensor (SHT30 fallback offline) | SCD41 provides humidity + CO2; SHT30 physically disconnected | ⚠️ Revisit — single sensor SPOF, but CO2 is high-value |

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

*Last updated: 2026-04-18 after v1.2.1 milestone*
