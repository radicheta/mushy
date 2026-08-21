# FC-1 Fruiting Chamber — Operations Guide

> Verified against the running system on 2026-08-21 (fc1 addresses, systemd
> Restart policy, live topic list, fruiting setpoints). The previous revision
> pointed recovery at a Tailscale address that no longer resolves and quoted an
> 80% ±5% setpoint that had not been true since May.

## Overview

FC-1 is a closed-loop humidity control system for a mushroom fruiting chamber, running on a Raspberry Pi 4 (Ubuntu 24.04 LTS). It continuously reads humidity and temperature from an SHT30 sensor (I2C address 0x44, SDA pin 3, SCL pin 5) and CO2 from an SCD41 sensor (I2C address 0x62), then drives a solid state relay (SSR-10A on GPIO27, pin 13) to switch the 220V AC power strip that powers the humidifier and fans. In fruiting mode the control goal is 90% humidity with a band of 88.5–91.5% (farmer-set 2026-06-27, lowered from 96%). Duty is time-proportional under a PID with a quadratic feather, not bang-bang. The system runs as a systemd service (`fc-core`) with automatic restart on failure and publishes all telemetry to a local ROS2 bus, which the OpenMCT dashboard consumes over WireGuard VPN.

## Architecture

```
FC-1 Pi (10.68.155.56 farm LAN / 172.16.10.5 wg0 / 10.66.0.11 wg-hub)
+-- fc-core.service (systemd, Restart=always, RestartSec=5)
|   +-- fc_sensors     -> SHT30 (I2C 0x44) + SCD41 (I2C 0x62)
|   +-- fc_controller  -> GPIO27 (SSR-10A -> humidifier power strip)
|   +-- fc_display
+-- CycloneDDS (unicast via /etc/cyclonedds.xml over wg0 -- NOT tailscale;
|   tailscaled is not running on fc1 and the 100.x path is dead)
+-- Config: ~/mushroom_farm_ws/src/chambers/fc-core/config/fc_config.yaml

elder-plops (172.16.10.3 VPN)
+-- OpenMCT    (docker: mushy-openmct-1, port 8080)
+-- bridge     (docker: mushy-bridge-1)
+-- alerter-py (docker: mushy-alerter-py-1 -- Signal alerts + farmer record-keeping)
```

### ROS2 Topics

| Topic | Type | QoS | Description |
|-------|------|-----|-------------|
| /fc1/humidity | sensor_msgs/RelativeHumidity | default | SHT30 humidity (0.0–1.0) |
| /fc1/humidity_2 | sensor_msgs/RelativeHumidity | default | SCD41 humidity (second sensor) |
| /fc1/temperature | sensor_msgs/Temperature | default | SHT30 temperature (°C) |
| /fc1/temperature_2 | sensor_msgs/Temperature | default | SCD41 temperature |
| /fc1/co2 | std_msgs/Float32 | default | SCD41 CO2 (ppm) |
| /fc1/actuators/humidifier | std_msgs/Bool | TRANSIENT_LOCAL/RELIABLE | Humidifier SSR state |
| /fc1/actuators/humidifier_duty | std_msgs/Float32 | default | Commanded duty 0.0–1.0 |
| /fc1/control/pid_output | std_msgs/Float32 | default | Raw PID output before clamping |
| /fc1/control/current_mode | std_msgs/String | TRANSIENT_LOCAL | Active mode (fruiting, etc.) |
| /fc1/control/humidity_target | std_msgs/Float32 | default | Effective target for the active mode |
| /fc1/sensor_health | std_msgs/String | default | Per-sensor liveness |

Run `ssh fc1 ros2-cmd topic list` for the current set -- the wrapper injects the
DDS env, which a bare `ros2` over SSH does not have.

## Configuration

All runtime parameters live in `src/chambers/fc-core/config/fc_config.yaml`. Current production values:

| Parameter | Value | Range | Description |
|-----------|-------|-------|-------------|
| sensor_simulation_mode | false | true/false | false = real SHT30 hardware |
| actuator_simulation_mode | false | true/false | false = real GPIO for SSR |
| sht30_i2c_address | 0x44 | I2C address | SHT30 sensor address |
| scd41_enabled | true | true/false | SCD41 CO2 sensor |
| humidifier_pin | 27 | GPIO number | SSR relay for humidifier |
| light_pin | 18 | GPIO number | Light control pin |
| target_temp | 23.0 | °C | Temperature setpoint |
| target_humidity | 0.96 | 0.0–1.0 | Legacy top-level setpoint. OVERRIDDEN by the active mode -- see below. |
| humidity_tolerance | 0.005 | 0.0–1.0 | Band half-width (±0.5%), narrowed from 1.5% on 2026-06-21 |
| modes.fruiting.target_humidity | 0.90 | 0.0–1.0 | **The setpoint that actually runs**, farmer-set 2026-06-27 |
| modes.fruiting.band_low / band_high | 0.885 / 0.915 | 0.0–1.0 | Operating band |
| pid_integrator_decay_tau | 300.0 | seconds | In-band integrator decay. MUST be a float in overrides -- an int crashes the controller on restart. |
| sensor_stale_timeout | 10.0 | seconds | Stale data triggers safe state (OFF) |
| sensor_read_interval | 2.0 | seconds | Time between sensor reads |
| control_interval | 1.0 | seconds | Time between control updates |

> **Note:** Humidity target and tolerance are ROS2 *runtime* parameters -- they can be
> set live with `ros2 param set` for a calibration session, then committed. Everything
> else follows the deploy path below. To change configuration, edit `fc_config.yaml` in the repo, commit to the `fc1/prod` branch, and run `deploy.sh` (or let the `fc-update` systemd oneshot pull it on the next boot). Never edit config directly on the Pi — the Pi's `mushy-repo/` clone is a fast-forward-only checkout of `fc1/prod` and will be reset on every deploy.

## Deploy Procedure

Deploy is git-based. The Pi keeps a clone at `~/mushroom_farm_ws/mushy-repo/` that tracks the `fc1/prod` branch. `deploy.sh` fast-forwards that checkout, rebuilds, and restarts the service.

1. Edit `src/chambers/fc-core/config/fc_config.yaml` on your workstation.
2. Commit and push to `fc1/prod`:
   ```bash
   git checkout fc1/prod
   git merge --ff-only milestone/fc1-humidity-mvp   # or cherry-pick
   git push origin fc1/prod
   ```
3. Run `./scripts/pi-deploy/deploy.sh` from the repo root. The script ssh'es into the Pi, runs `git fetch && git checkout fc1/prod && git pull`, rebuilds `fc_core`, and restarts `fc-core.service`.
4. Verify the service restarted: `ssh fc1 'sudo systemctl is-active fc-core'` — must return `active`.
5. Spot-check recent logs: `ssh fc1 'sudo journalctl -u fc-core -n 10 --no-pager'`
6. Verify config is deployed:
   ```bash
   ssh fc1 'grep target_humidity ~/mushroom_farm_ws/mushy-repo/src/chambers/fc-core/config/fc_config.yaml'
   ```

Override the branch for staging with `BRANCH=milestone/fc1-humidity-mvp ./scripts/pi-deploy/deploy.sh` — but anything run on the physical chamber should come from `fc1/prod`.

## Recovery Procedures

### 5.1 fc-core service not running

**Symptom:** `ssh fc1 'sudo systemctl is-active fc-core'` returns `inactive` or `failed`

**Diagnose:**
```bash
ssh fc1 'sudo journalctl -u fc-core -n 50 --no-pager'
```

**Resolve:**
```bash
ssh fc1 'sudo systemctl restart fc-core'
```

If still failing, check for Python tracebacks:
```bash
ssh fc1 'sudo journalctl -u fc-core -e'
```

### 5.2 Sensor reading 0 or missing

**Symptom:** OpenMCT shows 0% humidity or no data on the humidity chart

**Diagnose:**
```bash
ssh fc1 'sudo journalctl -u fc-core --since "5 min ago" --no-pager | grep -E "SHT30|error|I2C"'
```

**Resolve:** Check the I2C bus for the sensor:
```bash
ssh fc1 'sudo i2cdetect -y 1'
```
Device should appear at address `0x44`. If missing, check SHT30 wiring: SDA → pin 3, SCL → pin 5, VCC → pin 4, GND → pin 6.

**Two failure modes that do not look like failures:**

- **SCD41 silent wedge.** The CO2 sensor can stop producing new readings while the
  bus still answers -- it died silently for ~26h once before anyone noticed. A
  service restart reinitialises it. Check `/fc1/sensor_health` and compare CO2
  timestamps rather than trusting that a value is present.
- **SHT30 heater getter lies.** The library's `.heater` property does not reflect
  the device. Read the status register and mask `0x2000` if you need to know
  whether the heater is on.

### 5.3 Humidifier not activating

**Symptom:** Humidity is below the setpoint but the humidifier is not running

**Diagnose:**
```bash
ssh fc1 'sudo journalctl -u fc-core --since "5 min ago" --no-pager | grep "Humidifier"'
```

**Check:** The dwell guard may be active — the system enforces a 180-second (3-minute) minimum between humidifier toggles. Wait 3 minutes and check again.

**Check:** Confirm the power strip is plugged in and that the green LED on the SSR relay is visible when the humidifier should be ON.

### 5.4 OpenMCT dashboard not loading

**Symptom:** Browser shows a blank page or "connection refused" at `localhost:8080`

**Resolve:**
```bash
cd /path/to/mushy && docker compose up -d openmct bridge
```

**Verify:**
```bash
docker ps | grep mushy
```
Both `mushy-openmct-1` and `mushy-bridge-1` should be listed as running. Note that
"healthy" is not proof of reachability -- containers have come up network-detached
while reporting healthy (BONE-10). If the dashboard is still blank, check that the
container is actually attached to its network.

### 5.5 Pi unreachable via SSH

**Symptom:** `ssh fc1` times out or refuses connection

**Check wg0** (primary path -- this is what telemetry rides):
```bash
ping 172.16.10.5     # or: ssh ubuntu@172.16.10.5
```

**Check the farm LAN** (only reachable from the farm LAN):
```bash
ping 10.68.155.56
```

**Check wg-hub** (heartbeat only, via the VPS):
```bash
ping 10.66.0.11
```

Tailscale is NOT a path any more -- `tailscaled` is not running on fc1 and the old
`100.96.239.75` address is dead. Do not spend outage time on it.

Before concluding the Pi is down, separate "offline" from "uncontrolled": a WAN drop
leaves the chamber controlling itself perfectly well, and fc1 loses WAN when the door
is closed in the rain. The heartbeat tells you the host is alive; telemetry silence
alone does not mean the chamber is unmanaged. fc_buffer replays up to 24h of telemetry
on reconnect, so a gap is not lost data unless it exceeds the ring.

If the Pi is powered but unreachable on all three paths, physical access is required — check power supply and 4G hotspot at the chamber location.

## Monitoring

- **Dashboard:** Run `docker compose up -d openmct bridge` on elder-plops, then open `http://localhost:8080` in a browser. The dashboard shows live humidity, temperature, CO2, and humidifier on/off state.
- **Real-time logs:** `ssh fc1 'sudo journalctl -u fc-core -f'`
- **Quick health check:** `ssh fc1 'sudo systemctl show fc-core --property=NRestarts,ActiveState,SubState'`
- **Service uptime:** `ssh fc1 'sudo systemctl show fc-core --property=ExecMainStartTimestamp'`

## Known Limitations

- **Single chamber only (FC-1)** — multi-chamber support is a future phase.
- ~~No alerts or notifications~~ — obsolete. The chamber alerter sends Signal alerts to the farmer, a daily heartbeat proves it is alive, and `scripts/farm-watchdog/` checks twelve farm capabilities every 15 minutes and pushes to ntfy when one changes state.
- **No remote configuration UI** — there is no UI, though humidity target and tolerance are live ROS2 params and can be changed without a deploy. A config UI via the Mission Control command channel is a future phase capability.
- **Pi 4 only** — not tested on Pi 5 or other single-board computers.
- **GPIO library deprecation path** — RPi.GPIO 0.7.1 works on Pi 4 / Ubuntu 24.04 LTS (kernel 6.8.0-raspi). RPi.GPIO is deprecated upstream; migration to `rpi-lgpio` may be required for future Pi hardware or OS versions.
- **fc1 is behind CGNAT** — it is at the farm on 4G with no inbound route, so all remote access goes through WireGuard: `wg0` (172.16.10.5) for SSH and telemetry, `wg-hub` (10.66.0.11) via the VPS for heartbeat. Tailscale was the original path and is gone.
