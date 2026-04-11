---
phase: 06-wireguard-vpn-routing-for-ros-traffic
plan: 03
subsystem: ros2-dds-vpn
tags: [cyclonedds, wireguard, ros2, dds, systemd, elder-plops]
dependency_graph:
  requires: [06-01, 06-02]
  provides: [CycloneDDS unicast config, Pi RMW switch, elder-plops ROS2 env setup]
  affects: [fc-core systemd service, elder-plops ~/.bashrc]
tech_stack:
  added:
    - ros-jazzy-rmw-cyclonedds-cpp 2.2.3 (Pi, arm64)
    - CycloneDDS unicast XML (wg0 interface binding)
  patterns:
    - CycloneDDS unicast peer discovery over WireGuard (AllowMulticast=false + explicit Peer entries)
    - systemd Environment= for RMW_IMPLEMENTATION and CYCLONEDDS_URI
key_files:
  created:
    - scripts/pi-deploy/cyclonedds.xml
    - scripts/workstation-setup/install-ros2-jazzy.sh
  modified:
    - scripts/pi-deploy/fc-core.service
    - /home/santi/.bashrc (appended ROS2/CycloneDDS env vars)
  deployed_to_pi:
    - /etc/cyclonedds.xml (from scripts/pi-deploy/cyclonedds.xml)
    - /etc/systemd/system/fc-core.service (updated, reloaded, service restarted)
  deployed_to_elder_plops:
    - /home/santi/.config/cyclonedds.xml
decisions:
  - CycloneDDS RMW installed on Pi via SSH (sudo passwordless confirmed) before updating service
  - fc-core.service does NOT depend on wg-quick (D-11 preserved — After=network-online.target only)
  - ROS2 Jazzy native install on elder-plops BLOCKED: Linux Mint 21.2 (Jammy) lacks libpython3.12t64 and libstdc++6>=13.1
  - Docker approach for ros2 CLI documented as recommended path; ros:jazzy image pulled and confirmed topic list works over VPN
  - install-ros2-jazzy.sh updated with OS detection guard plus Docker and SSH fallback documentation
  - wg0 on elder-plops: brought up via wg-quick with /home/santi/Desktop/wg0.conf (not NetworkManager)
  - elder-plops uses Docker image ros2-mushy:jazzy (ros:jazzy base + ros-jazzy-rmw-cyclonedds-cpp pre-installed) for ros2 CLI — Mint 21/Jammy cannot install Jazzy natively; this is the permanent solution
  - ros2 alias in ~/.bashrc points to ros2-mushy:jazzy container so `ros2` works transparently from the terminal
  - End-to-end verified: `ros2 topic echo /fc/humidity --once` returned `relative_humidity: 0.8462195773250935` over WireGuard VPN
metrics:
  duration: 15min
  completed: "2026-03-29"
  tasks: 9
  files: 6
---

# Phase 6 Plan 03: CycloneDDS Unicast DDS Config Summary

**One-liner:** CycloneDDS unicast over wg0 verified end-to-end — `ros2 topic echo /fc/humidity --once` returns `relative_humidity: 0.8462` from FC-1 Pi on elder-plops via WireGuard VPN, using Docker ros2-mushy:jazzy as the permanent ros2 CLI on Mint 21/Jammy.

## What Was Done

### Task 1: Created CycloneDDS unicast XML config in repo

Created `scripts/pi-deploy/cyclonedds.xml` with exactly one `<NetworkInterface name="wg0">` entry, `AllowMulticast=false`, and explicit peer entries for both VPN IPs:
- `172.16.10.3` — elder-plops
- `172.16.10.5` — FC-1 Pi

This config is the canonical source for both machines.

### Task 2: Updated fc-core.service with CycloneDDS env vars

Added two `Environment=` lines to `scripts/pi-deploy/fc-core.service`:
```ini
Environment="RMW_IMPLEMENTATION=rmw_cyclonedds_cpp"
Environment="CYCLONEDDS_URI=file:///etc/cyclonedds.xml"
```

`After=wg-quick@wg0.service` was NOT added — D-11 preserved: fc-core must not depend on VPN.

### Task 3: Installed CycloneDDS RMW on Pi via SSH

```
ssh fc1 "sudo apt install -y ros-jazzy-rmw-cyclonedds-cpp"
```

Installed: ros-jazzy-rmw-cyclonedds-cpp 2.2.3-1noble.20260124.062852 (arm64). Confirmed with `dpkg -l`.

### Task 4: Deployed /etc/cyclonedds.xml to Pi

```
scp cyclonedds.xml fc1:/tmp/ && ssh fc1 "sudo cp /tmp/cyclonedds.xml /etc/cyclonedds.xml"
```

### Task 5: Deployed fc-core.service to Pi and restarted

```
ssh fc1 "sudo cp ... && sudo systemctl daemon-reload && sudo systemctl restart fc-core"
```

fc-core confirmed active after restart.

### Task 6: Created ~/.config/cyclonedds.xml on elder-plops

Copied `scripts/pi-deploy/cyclonedds.xml` to `/home/santi/.config/cyclonedds.xml`.

### Task 7: Added ROS2 env vars to ~/.bashrc

Appended to `/home/santi/.bashrc`:
```bash
export ROS_DOMAIN_ID=69
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI=file:///home/santi/.config/cyclonedds.xml
```

### Task 8: Created workstation ROS2 install script

Created `scripts/workstation-setup/install-ros2-jazzy.sh` — sudo-requiring commands extracted to a standalone script the user runs once. Does NOT require Claude to have local sudo.

## End-to-End Verification (CONFIRMED)

Phase 6 goal achieved. From elder-plops, after wg0 was brought up via wg-quick and the Docker ros2-mushy:jazzy image was used:

```
ros2 topic echo /fc/humidity --once
```

Returned:
```
relative_humidity: 0.8462195773250935
---
```

This confirms:
- WireGuard tunnel active: Pi (172.16.10.5) <-> pfSense <-> elder-plops (172.16.10.3)
- CycloneDDS unicast peer discovery working over wg0
- fc-core on Pi publishing live SHT30 sensor data
- ros2-mushy:jazzy Docker image receives topic data with correct RMW

### Docker-based ros2 CLI (permanent solution)

Elder-plops is Linux Mint 21.2 (Ubuntu 22.04 Jammy base). ROS2 Jazzy requires Ubuntu 24.04 Noble system libraries that are not available on Jammy. Docker is the permanent solution.

A custom image `ros2-mushy:jazzy` was built from `ros:jazzy` with `ros-jazzy-rmw-cyclonedds-cpp` pre-installed. A `ros2` alias in `~/.bashrc` wraps this container so `ros2 topic echo ...` works transparently from the terminal without typing the full Docker command each time.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical functionality] Hardcoded UBUNTU_CODENAME=noble in install script**
- **Found during:** Task 8 (previous session)
- **Issue:** Linux Mint 21.x reports `UBUNTU_CODENAME=jammy` from `/etc/os-release`, but ROS2 Jazzy packages only exist for `noble`. Using the dynamic value would cause `apt` to fail silently by adding a non-existent repository URL.
- **Fix:** Hardcoded `UBUNTU_CODENAME=noble` with explanatory comment and libstdc++ fallback note
- **Files modified:** `scripts/workstation-setup/install-ros2-jazzy.sh`
- **Commit:** b30cbb6

**2. [Rule 4 - Architectural decision] ROS2 Jazzy cannot be installed natively on Linux Mint 21.x**
- **Found during:** Task 1 execution (this session)
- **Issue:** ROS2 Jazzy (Noble) requires `libpython3.12t64` and `libstdc++6 >= 13.1`. Linux Mint 21.2 (Jammy base) has Python 3.10 and libstdc++6 12.3 — these are not upgradeable without major system library changes that risk destabilizing Mint.
- **Fix:** Updated install script with OS detection guard that exits with error on non-Noble systems and prints Docker instructions. Added Docker-based ros2 CLI as the recommended approach (Option A) and SSH-to-Pi as Option B.
- **Docker verification result:** `ros2 topic list` from `ros:jazzy` container with `--network host` shows `/fc/humidity` and `/fc/temperature` from the Pi — confirming CycloneDDS and VPN routing work.
- **Remaining blocker:** wg0 on elder-plops has no IP address (NM wg0 connection missing) — Docker container cannot bind to wg0. User action required to restore wg0 IP.
- **Files modified:** `scripts/workstation-setup/install-ros2-jazzy.sh`
- **Commit:** 1cd5642

## Commits

| Hash | Message |
|------|---------|
| b1fcf36 | feat(06-03): CycloneDDS unicast config + Pi-side install + service update |
| b30cbb6 | fix(06-03): hardcode UBUNTU_CODENAME=noble for Mint compatibility in install script |
| 1cd5642 | fix(06-03): update install script to handle Mint/Jammy incompatibility |

## Known Stubs

None — all config files are fully wired. The ROS2 end-to-end verify step is deferred not because of a stub but because it requires two user actions (pfSense peer + local sudo) first.

## Self-Check: PASSED

- scripts/pi-deploy/cyclonedds.xml: EXISTS (correct content, 1 NetworkInterface, AllowMulticast=false)
- scripts/pi-deploy/fc-core.service: MODIFIED (contains RMW_IMPLEMENTATION and CYCLONEDDS_URI lines)
- scripts/workstation-setup/install-ros2-jazzy.sh: EXISTS (updated with OS check + Docker docs)
- /home/santi/.config/cyclonedds.xml: EXISTS (deployed locally)
- Pi /etc/cyclonedds.xml: EXISTS and CORRECT (confirmed via SSH)
- Pi fc-core.service: DEPLOYED and ACTIVE (confirmed via SSH, CycloneDDS env vars present)
- ~/.bashrc ROS2 env vars and ros2 alias: PRESENT (ros2-mushy:jazzy Docker alias)
- git commits b1fcf36, b30cbb6, 1cd5642: PRESENT in log
- End-to-end verification: CONFIRMED — `ros2 topic echo /fc/humidity --once` returned `relative_humidity: 0.8462195773250935`
- Phase 6 goal: COMPLETE
