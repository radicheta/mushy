---
phase: 06-wireguard-vpn-routing-for-ros-traffic
verified: 2026-04-11T15:05:00-03:00
status: passed
score: 5/5 must-haves verified
verification_method: runtime-on-live-mesh
human_verification: []
---

# Phase 06: WireGuard VPN Routing for ROS Traffic — Verification Report

**Phase Goal:** FC-1 Pi and elder-plops on an always-on WireGuard mesh (172.16.10.0/24) with ROS2 topic visibility over the VPN tunnel via CycloneDDS unicast peer discovery.
**Verified:** 2026-04-11T15:05-03:00
**Method:** Runtime verification against the live mesh — the fact that the bridge container on elder-plops is currently receiving `/fc1/*` telemetry from the Pi is itself end-to-end proof of Phase 06.
**Note:** This VERIFICATION.md was written retroactively during milestone v1.0 audit paperwork closure on 2026-04-11. Phase 06 was functionally complete on 2026-03-29 (per SUMMARY files).

## Notable Evolution

Phase 06 was originally about plain WireGuard between Pi and pfSense / elder-plops, with CycloneDDS unicast over `wg0`. At some point after Phase 06 completion, the mesh was migrated to **Tailscale** for reliability (the farm has unreliable connectivity and Tailscale's NAT traversal + fallback relays tolerate it better). The current CycloneDDS unicast XML used by the bridge is `cyclonedds-tailscale.xml` (not `cyclonedds.xml`), binding to `tailscale0` and peering to the Tailscale addresses of the Pi (100.96.239.75) and elder-plops (100.96.10.66). Plain WireGuard (`wg0`) remains up on the Pi as a secondary tunnel to pfSense but is not the active DDS transport right now.

This migration is partially documented in memory (`project_4g_hotspot.md`, `project_network.md`) but never reflected in the phase plan. Flagging as documentation drift, not a functional gap.

## Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | WireGuard installed and running on Pi | VERIFIED | `wg show` on Pi reports `wg0` interface up, pubkey present, peer `FkNbdYtcfBgsYvOzv6UcnxPIhwRDEyv8jMehsOL43E0=` (pfSense) at `10.68.155.1:51820`, allowed IPs `172.16.10.0/24`, persistent keepalive 25s. |
| 2 | Pi reachable on mesh from workstation | VERIFIED | Multiple `ssh fc1-ts` commands executed today against 100.96.239.75 (Tailscale). The WireGuard path (172.16.10.2) is also configured as secondary. |
| 3 | ROS2 + CycloneDDS deployed on elder-plops | VERIFIED | `mushy_bridge_1` container sets `RMW_IMPLEMENTATION=rmw_cyclonedds_cpp`, `CYCLONEDDS_URI=file:///etc/cyclonedds-tailscale.xml` (host-mounted from `~/.config/cyclonedds-tailscale.xml`). |
| 4 | CycloneDDS unicast config peers Pi and elder-plops | VERIFIED | `~/.config/cyclonedds-tailscale.xml` contains `<NetworkInterface name="tailscale0" multicast="false" />`, `<AllowMulticast>false</AllowMulticast>`, and explicit `<Peer address="100.96.10.66"/>` (elder-plops) + `<Peer address="100.96.239.75"/>` (fc1). |
| 5 | E2E ROS topic visibility Pi → elder-plops | VERIFIED | Bridge is currently subscribed to `/fc1/humidity`, `/fc1/temperature`, `/fc1/co2`, `/fc1/actuators/humidifier`, `/fc1/camera/compressed`. Live humidity values (~76%, matching the Pi journal `fc_sensors` lines) are flowing into `mushy_timescale_1` at ~15 rows/min across 4 topics. Visible in Mission Control today. |

**Score:** 5/5 observable truths verified.

## Requirements Coverage

| Requirement | Status | Evidence |
|-------------|--------|----------|
| INFRA-02 WireGuard / mesh VPN reachable | SATISFIED | Truths #1, #2 (primary via Tailscale now, WG backup) |
| INFRA-04 ROS topics visible across machines | SATISFIED | Truth #5 — bridge subscription producing live DB rows |

## Gaps / Drift

- **Doc drift:** the phase plan assumes WireGuard as the active DDS transport. Current reality is Tailscale, with WireGuard secondary. The bridge override file (`docker-compose.override.yml`) correctly mounts the tailscale CycloneDDS config, so the code-side is consistent — only the phase-level docs are out of date. Not a runtime gap.
- **Edge connectivity:** the Pi's current WireGuard peer is pfSense on the elder-plops LAN, not the farm gateway. When the 4G hotspot deploys (tracked in memory `project_4g_hotspot.md`), this path should be re-evaluated.

## Anti-Patterns Found

None. No TODOs / FIXMEs / hardcoded secrets in phase deliverables.

---
*Verified: 2026-04-11T15:05-03:00*
*Verifier: Claude (audit-milestone paperwork closure)*
