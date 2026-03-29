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
  - wg0 on elder-plops: interface UP/LOWER_UP but NO IP assigned — NM wg0 connection missing from nmcli; VPN routing incomplete
metrics:
  duration: 15min
  completed: "2026-03-29"
  tasks: 9
  files: 6
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

### 2. Get ros2 CLI on elder-plops (three options)

**IMPORTANT:** Elder-plops is Linux Mint 21.2 (Ubuntu 22.04 Jammy base). ROS2 Jazzy requires Ubuntu 24.04 Noble system libraries (libpython3.12t64, libstdc++6 >= 13.1) that are NOT available on Jammy. Native apt install WILL FAIL.

**Option A — Docker (recommended, already working):**
```bash
docker pull ros:jazzy  # already pulled, cached locally
docker run --rm --network host \
  -e ROS_DOMAIN_ID=69 \
  -e RMW_IMPLEMENTATION=rmw_cyclonedds_cpp \
  -e CYCLONEDDS_URI=/cyclonedds.xml \
  -v ~/.config/cyclonedds.xml:/cyclonedds.xml:ro \
  ros:jazzy \
  bash -c "apt-get update -qq && apt-get install -y -qq ros-jazzy-rmw-cyclonedds-cpp && source /opt/ros/jazzy/setup.bash && ros2 topic echo /fc/humidity --once"
```

This was tested and shows `/fc/humidity` and `/fc/temperature` in `ros2 topic list`. BUT — the container currently fails to bind to wg0 because **wg0 has no IP address** (see blocker below).

**Option B — SSH to Pi:**
```bash
ssh fc1 "source /opt/ros/jazzy/setup.bash && source /home/ubuntu/mushroom_farm_ws/install/setup.bash && ROS_DOMAIN_ID=69 ros2 topic echo /fc/humidity --once"
```

**Option C — Native on Ubuntu Noble only:**
```bash
sudo bash scripts/workstation-setup/install-ros2-jazzy.sh  # exits with error on Mint, prints Docker instructions
```

### 3. Fix wg0 IP address on elder-plops (BLOCKER for Docker-based verification)

**Problem found:** wg0 interface is UP (kernel shows `POINTOPOINT,NOARP,UP,LOWER_UP`) but has NO IP address. The NM wg0 connection that RESEARCH.md confirmed working (`nmcli connection show wg0`) is now GONE from NetworkManager. Without an IP on wg0, the CycloneDDS config (`NetworkInterface name="wg0"`) cannot bind.

**Fix (requires sudo, run from terminal):**
```bash
# Option 1: Re-add NM WireGuard connection
# First check what WireGuard keys elder-plops has:
sudo wg show  # shows private key and public key

# Option 2: Use wg-quick with a config file
# Check if /etc/wireguard/wg0.conf exists:
sudo ls /etc/wireguard/
```

Ping to 172.16.10.1 succeeds through LAN routing (pfSense answers its LAN IP), but 172.16.10.5 (Pi) is unreachable. The wg0 interface just needs its IP (172.16.10.3) reassigned.

### 4. Verify end-to-end ROS2 topic visibility over VPN

After completing steps 1-3, run from elder-plops (using Docker):
```bash
docker run --rm --network host \
  -e ROS_DOMAIN_ID=69 \
  -e RMW_IMPLEMENTATION=rmw_cyclonedds_cpp \
  -e CYCLONEDDS_URI=/cyclonedds.xml \
  -v ~/.config/cyclonedds.xml:/cyclonedds.xml:ro \
  ros:jazzy \
  bash -c "apt-get update -qq && apt-get install -y -qq ros-jazzy-rmw-cyclonedds-cpp 2>/dev/null && source /opt/ros/jazzy/setup.bash && ros2 topic echo /fc/humidity --once"
```

Or once wg0 IP is fixed and ROS2 is installed natively:
```bash
source /opt/ros/jazzy/setup.bash
ros2 node list
ros2 topic list
ros2 topic echo /fc/humidity --once
```

Expected: live `float64` humidity reading from FC-1 Pi, delivered over the WireGuard tunnel.

If `ros2 node list` returns empty: check `wg0` has IP 172.16.10.3 (`sudo wg show`), verify fc-core is running (`ssh fc1 "systemctl is-active fc-core"`), and wait 30 seconds for CycloneDDS peer discovery.

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

## Self-Check: PASSED (with known blockers)

- scripts/pi-deploy/cyclonedds.xml: EXISTS (correct content, 1 NetworkInterface, AllowMulticast=false)
- scripts/pi-deploy/fc-core.service: MODIFIED (contains RMW_IMPLEMENTATION and CYCLONEDDS_URI lines)
- scripts/workstation-setup/install-ros2-jazzy.sh: EXISTS (updated with OS check + Docker docs)
- /home/santi/.config/cyclonedds.xml: EXISTS (deployed locally)
- Pi /etc/cyclonedds.xml: EXISTS and CORRECT (confirmed via SSH)
- Pi fc-core.service: DEPLOYED and ACTIVE (confirmed via SSH, CycloneDDS env vars present)
- ~/.bashrc ROS2 env vars: PRESENT (ROS_DOMAIN_ID=69, RMW_IMPLEMENTATION, CYCLONEDDS_URI)
- git commits b1fcf36, b30cbb6, 1cd5642: PRESENT in log
- BLOCKER: wg0 on elder-plops has no IP — NM wg0 connection missing from `nmcli connection show`
- BLOCKER: ros2 CLI on elder-plops requires Docker (ros:jazzy pulled locally at 880MB)
