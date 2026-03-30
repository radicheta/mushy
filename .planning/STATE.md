---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: Ready to plan
stopped_at: "Completed 02-03: rolling median spike rejection in humidity_callback"
last_updated: "2026-03-30T18:22:22.316Z"
progress:
  total_phases: 6
  completed_phases: 3
  total_plans: 12
  completed_plans: 12
  percent: 100
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-28)

**Core value:** A working, production-ready humidity control loop that's better than the current timer solution and ready to ship to growers.
**Current focus:** Phase 02 — safety-hardening

## Status

**Milestone:** MVP — FC-1 Humidity Control
**Progress:** [██████████] 100%
**Phase:** 06 of 5 (wireguard vpn routing for ros traffic)
**Last action:** SHT30 sensor live — 22.6°C, 84.7% real readings on /fc/humidity

## Phase Progress

- [~] Phase 1: Hardware & Environment (4/5 plans — actuator wiring pending)
- [ ] Phase 2: Safety Hardening (0/4 plans)
- [ ] Phase 3: Closed-Loop Control (0/3 plans)
- [ ] Phase 4: Observability & Integration (0/2 plans)
- [ ] Phase 5: Production Deployment (0/1 plans)

## Key Context

- Existing implementation is 50-75% complete
- DHT22 sensors already wired on FC-1
- MOSFET actuator needs wiring (component available)
- **Pi OS confirmed: Ubuntu 24.04.4 LTS (Noble), kernel 6.8.0-1047-raspi — gates Phase 1 cleared**
- **SHT30 I2C sensor live at 0x44** — real readings on /fc/humidity and /fc/temperature
- **Deploy pipeline working** — rsync + colcon build + systemd restart via ./scripts/pi-deploy/deploy.sh
- **fc-core service auto-starts on boot** — systemd enabled, survives reboot
- Sensor: SHT30 wired SDA→pin3, SCL→pin5, VCC→pin4, GND→pin6
- Actuator: SSR-10A (3-32V DC in, 24-480V AC 10A) switches zapatilla (power strip) on GPIO17. Humidifier + fans plug into strip — trigger together. HL-52S MOSFET reserved for independent fan control (Phase 3, GPIO27).
- Pi libs installed: adafruit-blinka, adafruit-circuitpython-sht31d, RPi.GPIO 0.7.1. ubuntu in gpio+i2c groups.
- SSH to FC-1 confirmed working: `ssh fc1` (HostName 10.68.155.53, User ubuntu)

## Accumulated Context

### Roadmap Evolution

- Phase 6 added: WireGuard VPN routing for ROS traffic

## Decisions

- **[01-01] Pi LAN is 10.68.155.0/24** (not planned 192.168.88.x). Static IP 10.68.155.53 set via `/etc/netplan/99-static.yaml`.
- **[01-01] VPN not a Phase 1 blocker** — WireGuard config prepared and documented; proceeds over LAN SSH per D-07/D-08.
- **[01-01] Pi confirmed RPi 4 on Ubuntu 24.04 Noble** — RPi.GPIO compatible, no migration needed (D-01, D-02 validated).
- [Phase 01-02]: Deploy pattern is rsync to Pi + colcon rebuild on Pi per D-04; systemd service with Restart=on-failure per D-05
- [Phase 01-02]: ROS_DOMAIN_ID=69 and ROS_LOCALHOST_ONLY=0 set in systemd unit for cross-machine ROS topic visibility
- [Phase 01-03]: RPi.GPIO 0.7.1 confirmed functional on Pi 4 / Ubuntu 24.04.4 / kernel 6.8.0-1047-raspi — no migration to rpi-lgpio needed
- [Phase 01-03]: ubuntu user in gpio+i2c groups — no sudoers changes required for GPIO pin access
- [Phase 01-pi-integration-environment]: HL-52S MOSFET CH1 uses on-board pull-down — no external 10k resistor needed on FC-1 build
- [Phase 01-05]: Plan adapted from DHT22 (adafruit_dht/GPIO4) to SHT30 (adafruit_sht31d/I2C 0x44) — fc_sensors.py uses SHT30, test scripts updated accordingly
- **[Phase 01-04]: SSR-10A chosen over MOSFET for humidifier** — switches 220V AC zapatilla, humidifier+fans share one circuit. GPIO17 unchanged. HL-52S MOSFET freed for Phase 3 independent fan control.
- [Phase 01-05]: SENS-01 satisfied: SHT30 live at 22.6C/88.5% humidity confirmed via journalctl (ros2 topic echo DDS discovery timeout is a CLI quirk, not node failure)
- [Phase 06-01]: Endpoint is 10.68.155.1:51820 (pfSense LAN) — mossrock.space DNS deferred per D-04
- [Phase 06-01]: wg-setup.sh redesigned as on-Pi idempotent script (sudo bash) — hardcodes values, no envsubst
- [Phase 06-03]: CycloneDDS RMW installed on Pi via SSH; fc-core.service updated with RMW_IMPLEMENTATION + CYCLONEDDS_URI; After=wg-quick NOT added (D-11); install-ros2-jazzy.sh defers local sudo to user
- [Phase 06-wireguard-vpn-routing-for-ros-traffic]: elder-plops uses Docker ros2-mushy:jazzy for ROS2 CLI — Linux Mint 21.2 (Jammy) cannot install ROS2 Jazzy natively; Docker is the permanent solution; ros2 alias in ~/.bashrc points to ros2-mushy:jazzy
- [Phase 06-wireguard-vpn-routing-for-ros-traffic]: elder-plops wg0 brought up via wg-quick with /home/santi/Desktop/wg0.conf — NetworkManager wg0 connection was absent; wg-quick is the working approach
- [Phase 06-wireguard-vpn-routing-for-ros-traffic]: Phase 6 complete — ros2 topic echo /fc/humidity --once returned relative_humidity: 0.8462195773250935 over WireGuard VPN
- [Phase 02-01]: D-05 confirmed: fc_sensors.py exception handler has no time.sleep() — SENS-03 is verification-only, no code change needed
- [Phase 02-02]: Config reflects actual hardware (SHT30 over I2C 0x44, not DHT22 on GPIO4) — sht30_i2c_address made tunable from config
- [Phase 02-04]: humidifier_pin defaults to 17, configurable from fc_config.yaml via ROS2 get_parameter — same pattern as light_pin (ACTR-02 satisfied)
- [Phase 02-03]: Filter lives in controller receive side (D-02): sensors publish raw truth, controller applies rolling median before acting
- [Phase 02-03]: SENS-05: deque(maxlen=5) + statistics.median chosen for spike rejection — stdlib, no extra dependency, handles odd/even lengths

## Performance Metrics

| Phase | Plan | Duration | Tasks | Files |
|-------|------|----------|-------|-------|
| 01-pi-integration-environment | 01 | 15min | 2 | 3 |
| Phase 01-pi-integration-environment P02 | 1min | 1 tasks | 3 files |
| Phase 01-pi-integration-environment P03 | 8min | 1 tasks | 1 files |
| Phase 01-pi-integration-environment P04 | 3min | 1 tasks | 2 files |
| Phase 01-pi-integration-environment P05 | 5min | 2 tasks | 2 files |
| Phase 06-wireguard-vpn-routing-for-ros-traffic P01 | 3min | 2 tasks | 2 files |
| Phase 06-wireguard-vpn-routing-for-ros-traffic P03 | 6min | 7 tasks | 5 files |
| Phase 06-wireguard-vpn-routing-for-ros-traffic P03 | 20min | 9 tasks | 4 files |
| Phase 02-safety-hardening P01 | 1min | 1 tasks | 1 files |
| Phase 02-safety-hardening P02 | 5min | 1 tasks | 1 files |
| Phase 02-safety-hardening P04 | 5min | 1 tasks | 3 files |
| Phase 02-safety-hardening P03 | 3min | 1 tasks | 2 files |

## Session

**Last session:** 2026-03-30T18:17:36.622Z
**Stopped at:** Completed 02-03: rolling median spike rejection in humidity_callback

---
*Initialized: 2026-03-28*
*Last updated: 2026-03-29*
