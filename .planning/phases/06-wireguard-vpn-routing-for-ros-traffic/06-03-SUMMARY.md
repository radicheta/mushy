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
  - UBUNTU_CODENAME hardcoded to noble in install script (Mint 21.x workaround — reports jammy but needs noble for Jazzy)
  - ROS2 Jazzy local install deferred: install-ros2-jazzy.sh provided for user to run once with sudo
metrics:
  duration: 8min
  completed: "2026-03-29"
  tasks: 7
  files: 5
---

# Phase 6 Plan 03: CycloneDDS Unicast DDS Config Summary

**One-liner:** CycloneDDS RMW installed on Pi, unicast XML configs deployed to Pi and elder-plops, fc-core.service updated with RMW env vars — ROS2 DDS traffic can traverse the WireGuard tunnel once VPN mesh is active.

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

## What Was NOT Done (requires user action)

### 1. Register FC-1 Pi peer in pfSense WireGuard (Plan 06-02, Task 1)

The Pi is running wg-quick@wg0 with its generated public key:
```
wVYbIBYfptP0uVpAbtk43xLVi75QIGL0yQwgTbMcATA=
```
This key must be added to pfSense → VPN → WireGuard → Peers before the VPN tunnel will establish.

**Steps:**
1. Open pfSense WebGUI at https://10.68.155.1
2. VPN → WireGuard → Peers → + Add Peer
   - Tunnel: tun_wg0 (mossrock)
   - Description: FC-1 Pi
   - Public Key: `wVYbIBYfptP0uVpAbtk43xLVi75QIGL0yQwgTbMcATA=`
   - Allowed IPs: `172.16.10.5/32`
   - Dynamic Endpoint: checked
3. Save → Apply Changes
4. Verify: `ssh fc1 "sudo wg show wg0"` should show "latest handshake:" with timestamp
5. Test: `ssh fc1 "ping -c 2 172.16.10.1"` should return 0% loss

### 2. Install ROS2 Jazzy on elder-plops (requires local sudo)

```bash
sudo bash scripts/workstation-setup/install-ros2-jazzy.sh
```

This installs `ros-jazzy-ros-base` and `ros-jazzy-rmw-cyclonedds-cpp`. The script hardcodes `UBUNTU_CODENAME=noble` because elder-plops (Linux Mint 21.x) reports `jammy` but needs the noble ROS2 repository. If dependency resolution fails, the script comments point to the Ubuntu Toolchain PPA as a fallback.

### 3. Verify end-to-end ROS2 topic visibility over VPN

After completing steps 1 and 2, run from elder-plops:

```bash
source /opt/ros/jazzy/setup.bash
ros2 node list
ros2 topic list
ros2 topic echo /fc/humidity --once
```

Expected: live `float64` humidity reading from FC-1 Pi, delivered over the WireGuard tunnel.

If `ros2 node list` returns empty: check that wg0 is up on both machines (`sudo wg show`), verify fc-core is running (`ssh fc1 "systemctl is-active fc-core"`), and wait 30 seconds for CycloneDDS peer discovery to complete.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical functionality] Hardcoded UBUNTU_CODENAME=noble in install script**
- **Found during:** Task 8 (post-write linter check)
- **Issue:** Linux Mint 21.x reports `UBUNTU_CODENAME=jammy` from `/etc/os-release`, but ROS2 Jazzy packages only exist for `noble`. Using the dynamic value would cause `apt` to fail silently by adding a non-existent repository URL.
- **Fix:** Hardcoded `UBUNTU_CODENAME=noble` with explanatory comment and libstdc++ fallback note
- **Files modified:** `scripts/workstation-setup/install-ros2-jazzy.sh`
- **Commit:** b30cbb6

## Commits

| Hash | Message |
|------|---------|
| b1fcf36 | feat(06-03): CycloneDDS unicast config + Pi-side install + service update |
| b30cbb6 | fix(06-03): hardcode UBUNTU_CODENAME=noble for Mint compatibility in install script |

## Known Stubs

None — all config files are fully wired. The ROS2 end-to-end verify step is deferred not because of a stub but because it requires two user actions (pfSense peer + local sudo) first.

## Self-Check: PASSED

- scripts/pi-deploy/cyclonedds.xml: EXISTS
- scripts/pi-deploy/fc-core.service: MODIFIED (contains RMW_IMPLEMENTATION line)
- scripts/workstation-setup/install-ros2-jazzy.sh: EXISTS
- /home/santi/.config/cyclonedds.xml: EXISTS (deployed locally)
- Pi /etc/cyclonedds.xml: EXISTS (confirmed via SSH)
- Pi fc-core.service: DEPLOYED and ACTIVE (confirmed via SSH)
- ~/.bashrc ROS2 env vars: PRESENT
- git commits b1fcf36 and b30cbb6: PRESENT in log
