---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: executing
stopped_at: Phase 10 context gathered
last_updated: "2026-04-12T16:29:12.032Z"
last_activity: 2026-04-12
progress:
  total_phases: 2
  completed_phases: 2
  total_plans: 6
  completed_plans: 6
  percent: 100
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-11)

**Core value:** A working, production-ready humidity control loop that's better than the current timer solution and ready to ship to growers.
**Current focus:** Phase 09 — connectivity-boot-stability

## Current Position

Phase: 10
Plan: Not started
Status: Ready to execute
Last activity: 2026-04-12

Progress: [░░░░░░░░░░] 0% (0/2 phases complete)

## Phase List (v1.1)

| Phase | Name | Requirements | Status |
|-------|------|--------------|--------|
| 09 | Connectivity & Boot Stability | CONN-01, TDEBT-03 | Not started |
| 10 | Bridge QoS & MJPEG Delivery | TDEBT-01, TDEBT-02 | Not started |

## Key Context

- v1.0 shipped 2026-04-11. Grower-attested. fc-core running continuously on Pi.
- fc1 Pi offline at farm (no 4G yet) — Phase 09 unblocks all other verification
- TDEBT-03 (cold-boot race on tailscale0) is a systemd `After=`/`Requires=` change; deploy via deploy.sh to fc1/prod branch
- TDEBT-01: bridge subscribes humidifier topic with VOLATILE QoS against TRANSIENT_LOCAL publisher — fix is bridge-side, requires `--build` on docker compose
- TDEBT-02: phantom peer at 192.168.1.193 in CycloneDDS config consuming delivery slots — fix is Pi-side config change (`/etc/cyclonedds/config.xml` or equivalent)
- Always verify against live compose at repo root (`/docker-compose.yml`), not `src/docker-compose.yml`
- Bridge rebuilds require `docker compose up -d --build bridge` — bare `up -d` reuses stale image

## Accumulated Context

### Roadmap Evolution

- Phase 6 added: WireGuard VPN routing for ROS traffic
- Phase 7 added: Historical data storage and OpenMCT time-series visualization
- Phase 8 added: Pi Camera Feed in Mission Control
- Phase 9 added (v1.1): Connectivity & Boot Stability
- Phase 10 added (v1.1): Bridge QoS & MJPEG Delivery

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
- [Phase 03-01]: D-12 fix: set_humidifier(False) on None sensor data instead of silent return — prevents humidifier freezing in last state on sensor failure
- [Phase 03-02]: Dwell guard as _set_humidifier_with_dwell method (not inside set_humidifier) — keeps hardware abstraction thin, makes call sites explicit
- [Phase 03-02]: test_humidity_control updated with clock mocking to fix pre-existing failure caused by dwell guard interaction
- [Phase 03-03]: Staleness check in control_loop (not callback) — check happens on every tick so recovery is immediate when fresh data arrives
- [Phase 03-03]: Safe-state OFF bypasses dwell guard and updates _last_humidifier_toggle — prevents post-recovery rapid cycling (Pitfall 5)

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
| Phase 03-closed-loop-control P01 | 7min | 1 tasks | 3 files |
| Phase 03-closed-loop-control P02 | 5min | 1 tasks | 2 files |
| Phase 03-closed-loop-control P03 | 4min | 1 tasks | 2 files |

## Session

**Last session:** 2026-04-12T13:31:46.596Z
**Stopped at:** Phase 10 context gathered

---
*Initialized: 2026-03-28*
*Last updated: 2026-04-11*
