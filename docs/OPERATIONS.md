# FC-1 Fruiting Chamber — Operations Guide

## Overview

FC-1 is a closed-loop humidity control system for a mushroom fruiting chamber, running on a Raspberry Pi 4 (Ubuntu 24.04 LTS). It continuously reads humidity and temperature from an SHT30 sensor (I2C address 0x44, SDA pin 3, SCL pin 5) and CO2 from an SCD41 sensor (I2C address 0x62), then drives a solid state relay (SSR-10A on GPIO27, pin 13) to switch the 220V AC power strip that powers the humidifier and fans. The control goal is 80% humidity ±5%, giving a 75–85% operational band. The system runs as a systemd service (`fc-core`) with automatic restart on failure and publishes all telemetry to a local ROS2 bus, which the OpenMCT dashboard consumes over WireGuard VPN.

## Architecture

```
FC-1 Pi (10.68.155.53 LAN / 172.16.10.5 VPN)
+-- fc-core.service (systemd, Restart=on-failure, RestartSec=5)
|   +-- fc_sensors     -> SHT30 (I2C 0x44) + SCD41 (I2C 0x62)
|   +-- fc_controller  -> GPIO27 (SSR-10A -> humidifier power strip)
|   +-- fc_display
+-- CycloneDDS (unicast via /etc/cyclonedds.xml over wg0)
+-- Config: ~/mushroom_farm_ws/src/chambers/fc-core/config/fc_config.yaml

elder-plops (172.16.10.3 VPN)
+-- OpenMCT    (docker: mushy_openmct_1, port 8080)
+-- rosbridge  (docker: mushy_bridge_1)
```

### ROS2 Topics

| Topic | Type | QoS | Description |
|-------|------|-----|-------------|
| /fc/humidity | sensor_msgs/RelativeHumidity | default | SHT30 humidity (0.0–1.0) |
| /fc/temperature | sensor_msgs/Temperature | default | SHT30 temperature (°C) |
| /fc/co2 | std_msgs/Float32 | default | SCD41 CO2 (ppm) |
| /fc/actuators/humidifier | std_msgs/Bool | TRANSIENT_LOCAL/RELIABLE | Humidifier SSR state |

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
| target_humidity | 0.80 | 0.0–1.0 | Humidity setpoint (80%) |
| humidity_tolerance | 0.05 | 0.0–1.0 | Deadband (±5%) |
| min_dwell_time | 300.0 | seconds | Min time between humidifier toggles |
| sensor_stale_timeout | 10.0 | seconds | Stale data triggers safe state (OFF) |
| sensor_read_interval | 2.0 | seconds | Time between sensor reads |
| control_interval | 1.0 | seconds | Time between control updates |

> **Note:** To change configuration, edit `fc_config.yaml` in the repo and run `deploy.sh`. Never edit config directly on the Pi — `deploy.sh` rsync overwrites Pi files on every deploy.

## Deploy Procedure

1. Edit `src/chambers/fc-core/config/fc_config.yaml` on your workstation.
2. Run `./scripts/pi-deploy/deploy.sh` from the repo root.
3. Verify the service restarted: `ssh fc1 'sudo systemctl is-active fc-core'` — must return `active`.
4. Spot-check recent logs: `ssh fc1 'sudo journalctl -u fc-core -n 10 --no-pager'`
5. Verify config is deployed: `ssh fc1 'grep target_humidity ~/mushroom_farm_ws/src/chambers/fc-core/config/fc_config.yaml'`

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

### 5.3 Humidifier not activating

**Symptom:** Humidity is below the setpoint but the humidifier is not running

**Diagnose:**
```bash
ssh fc1 'sudo journalctl -u fc-core --since "5 min ago" --no-pager | grep "Humidifier"'
```

**Check:** The dwell guard may be active — the system enforces a 300-second (5-minute) minimum between humidifier toggles. Wait 5 minutes and check again.

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
Both `mushy_openmct_1` and `mushy_bridge_1` containers should be listed as running.

### 5.5 Pi unreachable via SSH

**Symptom:** `ssh fc1` times out or refuses connection

**Check LAN connectivity:**
```bash
ping 10.68.155.53
```

**Check VPN connectivity** (requires WireGuard `wg0` up on workstation):
```bash
ping 172.16.10.5
```

If the Pi is powered but unreachable on both paths, physical access is required — check the network cable and power supply at the chamber location.

## Monitoring

- **Dashboard:** Run `docker compose up -d openmct bridge` on elder-plops, then open `http://localhost:8080` in a browser. The dashboard shows live humidity, temperature, CO2, and humidifier on/off state.
- **Real-time logs:** `ssh fc1 'sudo journalctl -u fc-core -f'`
- **Quick health check:** `ssh fc1 'sudo systemctl show fc-core --property=NRestarts,ActiveState,SubState'`
- **Service uptime:** `ssh fc1 'sudo systemctl show fc-core --property=ExecMainStartTimestamp'`

## Known Limitations

- **Single chamber only (FC-1)** — multi-chamber support is a future phase.
- **No alerts or notifications** — monitoring requires manual dashboard checks or SSH log review. An alert/notification system is a future phase capability.
- **No remote configuration UI** — all config changes require editing `fc_config.yaml` in the repo and running `deploy.sh`. A runtime config UI via the OpenMCT command channel is a future phase capability.
- **Pi 4 only** — not tested on Pi 5 or other single-board computers.
- **GPIO library deprecation path** — RPi.GPIO 0.7.1 works on Pi 4 / Ubuntu 24.04 LTS (kernel 6.8.0-raspi). RPi.GPIO is deprecated upstream; migration to `rpi-lgpio` may be required for future Pi hardware or OS versions.
- **WireGuard VPN required for remote access** — the `wg0` interface must be up on both the Pi and the workstation for remote monitoring and SSH over VPN.
