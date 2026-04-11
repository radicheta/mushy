# Handover: mushroom_farm_ws → Elder-Plops

## Clone & Setup

```bash
git clone git@github.com:radicheta/mushy.git mushroom_farm_ws
cd mushroom_farm_ws
git checkout milestone/fc1-humidity-mvp

# ROS2 environment (requires ROS2 Jazzy installed)
source /opt/ros/jazzy/setup.bash
colcon build
source install/setup.bash
```

> **Note:** The remote uses a host alias `github.com-radicheta` in the SSH config on gumbald. On Elder-Plops, either set up the same SSH alias or update the remote:
> ```bash
> git remote set-url origin git@github.com:radicheta/mushy.git
> ```

## What This Is

ROS2 Jazzy workspace for a mushroom farm control system. The active work is **FC-1 humidity MVP** — replacing a dumb timer with a closed-loop humidity control loop running on a Raspberry Pi. The existing code is ~50-75% complete.

**Active branch:** `milestone/fc1-humidity-mvp`

Key packages:
- `src/chambers/fc-core/` — `fc_core` ROS2 package (sensors, controller, display nodes)
- `docker-compose.yml` — OpenMCT + ROS bridge services
- `wg0.conf.template` — WireGuard template (fill `WG_PRIVATE_KEY`, `WG_IP`, `WG_SERVER_PUBLIC_KEY`, `WG_SERVER_ENDPOINT`)

## Current Status

**All 5 phases unstarted.** Research is done (`.planning/research/`), roadmap and plans are defined.

| Phase | What | Status |
|-------|------|--------|
| 1 | SSH/VPN to FC-1 Pi, MOSFET wiring, DHT22 validation | Not started |
| 2 | Fix critical bugs (blocking sleep, normalization, hardcoded pins) | Not started |
| 3 | Complete closed-loop control (hysteresis, dwell time, stale data) | Not started |
| 4 | Actuator state topic, end-to-end hardware test | Not started |
| 5 | Production deploy to FC-1 | Not started |

**Phase 1 is the blocker** — can't do anything until there's SSH access to the FC-1 Pi and the Pi OS is confirmed.

## Known Critical Bugs (Phase 2 targets)

1. **Blocking sleep** — `fc_sensors.py` calls `time.sleep(2.0)` inside a ROS callback, stalling the executor
2. **Sensor normalization mismatch** — humidity values inconsistent between real hardware and simulation paths
3. **Hardcoded GPIO pin** — humidifier pin 17 is hardcoded in `fc_controller.py`, not in config
4. **Broken test** — `test_controller.py` asserts on the pin number (17) instead of actuator state

## Network

- ROS domain: `ROS_DOMAIN_ID=69`
- WireGuard mesh: see `wg0.conf.template` — fill in credentials before deploying to Pi
- FC-1 Pi expected on the WireGuard mesh (`172.16.10.0/24`)

## Picking Up Work

The GSD workflow is initialized. To see where things stand:
```bash
cat .planning/STATE.md       # current phase/status
cat .planning/ROADMAP.md     # full phase breakdown
cat .planning/research/      # architecture decisions and pitfalls
```

Next action: plan and execute **Phase 1** — getting SSH access to the FC-1 Pi.

---

The only thing that isn't in the repo is the actual WireGuard credentials — you'll need those separately to fill in `wg0.conf.template` before deploying networking to the Pi.
