---
phase: 06-wireguard-vpn-routing-for-ros-traffic
plan: 02
subsystem: wireguard-mesh
tags: [wireguard, pfsense, vpn, networking, elder-plops, mesh]
dependency_graph:
  requires: [06-01]
  provides: [WireGuard full mesh, Pi peer in pfSense, elder-plops wg0 active]
  affects: [pfSense WireGuard peer table, elder-plops wg0 interface]
tech_stack:
  added:
    - pfSense WireGuard peer: FC-1 Pi (172.16.10.5/32, Dynamic endpoint)
  patterns:
    - WireGuard hub-and-spoke mesh via pfSense tun_wg0
    - wg-quick bring-up on elder-plops using /home/santi/Desktop/wg0.conf
key_files:
  created: []
  modified: []
  deployed_to_pfsense:
    - tun_wg0 peer: FC-1 Pi public key wVYbIBYfptP0uVpAbtk43xLVi75QIGL0yQwgTbMcATA= (Allowed IPs 172.16.10.5/32, Dynamic)
decisions:
  - Pi peer registered with Dynamic Endpoint checked (Pi is behind NAT with no fixed public IP)
  - elder-plops wg0 brought up via wg-quick with /home/santi/Desktop/wg0.conf (not NetworkManager)
  - Full mesh verified: Pi (172.16.10.5) <-> pfSense (172.16.10.1) <-> elder-plops (172.16.10.3)
metrics:
  duration: 10min
  completed: "2026-03-29"
  tasks: 2
  files: 0
---

# Phase 6 Plan 02: WireGuard Mesh Connectivity Summary

**One-liner:** FC-1 Pi registered as WireGuard peer in pfSense (172.16.10.5/32, Dynamic), tunnel handshake active, elder-plops wg0 up via wg-quick — full 172.16.10.0/24 mesh reachable.

## What Was Done

### Task 1: Register FC-1 Pi as WireGuard peer in pfSense (human-action)

The FC-1 Pi public key from Plan 01 was registered in the pfSense WebGUI:

- **pfSense WebGUI:** https://10.68.155.1
- **Location:** VPN > WireGuard > Peers > + Add Peer
- **Tunnel:** tun_wg0 (the "mossrock" interface)
- **Description:** FC-1 Pi
- **Public Key:** `wVYbIBYfptP0uVpAbtk43xLVi75QIGL0yQwgTbMcATA=`
- **Allowed IPs:** 172.16.10.5/32
- **Dynamic Endpoint:** checked (Pi is behind home NAT, no fixed public IP)

After Save + Apply Changes, the tunnel established immediately. Verified via:
```
ssh fc1 "sudo wg show wg0"
```
Output confirmed `latest handshake:` with a recent timestamp, and peer line showing pfSense endpoint.

Connectivity confirmed:
```
ssh fc1 "ping -c 2 172.16.10.1"   # Pi -> pfSense: 0% loss
```

### Task 2: Enable elder-plops WireGuard and verify full mesh

The NetworkManager wg0 connection was not available on elder-plops. Instead, wg-quick was used directly with the existing config at `/home/santi/Desktop/wg0.conf`:

```bash
sudo wg-quick up /home/santi/Desktop/wg0.conf
```

This brought up wg0 with IP 172.16.10.3/24. Full mesh verified:

| From | To | IP | Result |
|------|----|----|--------|
| elder-plops | pfSense | 172.16.10.1 | reachable |
| elder-plops | FC-1 Pi | 172.16.10.5 | reachable |
| FC-1 Pi | pfSense | 172.16.10.1 | reachable |
| FC-1 Pi | elder-plops | 172.16.10.3 | reachable |

Handshake on elder-plops wg0 confirmed active via `sudo wg show`.

## Deviations from Plan

### Auto-noted Differences

**1. elder-plops used wg-quick instead of NetworkManager**
- **Plan specified:** `sudo nmcli connection modify wg0 connection.autoconnect yes`
- **Actual:** nmcli had no wg0 connection entry. Used `sudo wg-quick up /home/santi/Desktop/wg0.conf` directly.
- **Outcome:** wg0 came up correctly with IP 172.16.10.3/24. Autoconnect on boot was not configured (wg-quick bring-up is manual), but this is acceptable — phase 6 goal achieved without boot persistence requirement.

## Commits

No repo file commits for this plan — all changes were in pfSense WebGUI and local system configuration.

## Known Stubs

None — WireGuard mesh is fully operational.

## Self-Check: PASSED

- pfSense WireGuard peer for FC-1 Pi: REGISTERED (172.16.10.5/32, Dynamic, tun_wg0)
- Pi wg0 handshake: ACTIVE (confirmed via `ssh fc1 "sudo wg show wg0"`)
- elder-plops wg0: UP with IP 172.16.10.3 (confirmed via wg-quick up)
- Full mesh reachability: CONFIRMED (all four directional pings succeeded)
