# Phase 6: WireGuard VPN Routing for ROS Traffic — Context

**Gathered:** 2026-03-29
**Status:** Complete

<domain>
## Phase Boundary

Get FC-1 Pi and elder-plops onto an always-on WireGuard mesh so that ROS2 topics (not just SSH) are accessible between machines — from the LAN and from remote locations over the internet. VPN is the mandatory security boundary; no ROS traffic travels unencrypted over the internet.

This phase is done when: Pi and elder-plops are auto-connected to the 172.16.10.0/24 mesh, `ros2 topic echo fc/humidity` works from elder-plops over the VPN tunnel, and this works whether FC-1 is physically on the LAN or at a remote location.

</domain>

<decisions>
## Implementation Decisions

### Access Model

- **D-01: Both SSH and live ROS topics over VPN.** SSH alone is insufficient — the goal is full ROS2 visibility (ros2 topic echo, ros2 node list) from elder-plops over the tunnel, not just shell access. This requires fixing DDS peer discovery.

- **D-02: VPN is mandatory, not optional.** Security rationale: delegate authentication and encryption to the VPN layer. ROS2 has no built-in auth — all trust comes from "if you're on the mesh, you're authorized." No plaintext ROS traffic on the internet.

### Network Topology

- **D-03: WireGuard server is pfSense at 10.68.155.1, mesh subnet 172.16.10.0/24.**
  - pfSense WireGuard interface (igb5): `172.16.10.1`
  - FC-1 Pi VPN IP: `172.16.10.5` (pre-assigned)
  - Elder-plops VPN IP: already registered (exact IP to confirm during implementation)

- **D-04: Internet endpoint is `mossrock.space` (user-owned domain).** DNS must point to pfSense WAN. Fallback option: free DDNS service. pfSense WAN is `192.168.88.182` behind ISP router at `192.168.88.1` — requires UDP 51820 port forward on ISP router to pfSense.

- **D-05: Split-tunnel routing only.** AllowedIPs = `172.16.10.0/24` — only mesh traffic goes through tunnel, not default route. Pi and elder-plops keep their normal internet routing.

### WireGuard Peer Configuration

- **D-06: FC-1 Pi — always-on, internet-capable endpoint.**
  - Deploy `wg0.conf` with `Endpoint = mossrock.space:51820` (works from LAN and remote)
  - Enable `wg-quick@wg0` as systemd service (starts on boot, always reconnects)
  - FC-1 Pi must be added as a new peer in pfSense WireGuard config

- **D-07: Elder-plops — already registered, needs auto-connect.**
  - Currently connects manually; this phase makes it automatic (persistent connection)
  - Exact auto-connect mechanism depends on how it's currently set up (wg-quick, NetworkManager, etc.) — researcher/planner to check

- **D-08: pfSense — must accept internet connections.**
  - WireGuard server already exists on pfSense (server public key: `FkNbdYtcfBgsYvOzv6UcnxPIhwRDEyv8jMehsOL43E0=`)
  - Port forward needed: ISP router 192.168.88.1 → pfSense 192.168.88.182 UDP 51820
  - FC-1 Pi peer entry must be added via pfSense WebGUI or CLI

### ROS2 Topic Visibility (DDS Unicast)

- **D-09: Configure Cyclone DDS with explicit unicast peers.** ROS2 Jazzy uses Cyclone DDS by default. Multicast doesn't route over WireGuard tunnels — must configure explicit unicast peer discovery.
  - Implementation: XML config file listing peer VPN IPs (`172.16.10.5`, elder-plops VPN IP)
  - Env var `CYCLONEDDS_URI` pointing to the XML file, set in:
    - FC-1 Pi systemd service unit
    - Elder-plops shell/ROS environment
  - Existing systemd service already has `ROS_LOCALHOST_ONLY=0` — prerequisite is met

- **D-10: Claude's Discretion — Cyclone DDS XML structure.** The exact XML format and peer discovery options are for the researcher to determine. Use documented Cyclone DDS peer/locator config. Do not switch to Fast DDS.

### Failure Behavior

- **D-11: LAN remains primary access; VPN is for remote use.** If VPN is down, SSH over LAN still works. systemd `fc-core` service does not depend on VPN tunnel — it starts regardless. WireGuard failure should not crash the control loop.

- **D-12: `PersistentKeepalive = 25` already set in template.** Handles NAT traversal for remote FC scenarios. Keep this value.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing WireGuard Assets
- `wg0.conf.template` — WireGuard peer config template in project root; variables `${WG_PRIVATE_KEY}`, `${WG_IP}`, `${WG_SERVER_PUBLIC_KEY}`, `${WG_SERVER_ENDPOINT}` to be filled
- `docs/pi-setup/wireguard-setup.md` — Setup instructions already written; use as base, update endpoint to `mossrock.space`

### Existing ROS Configuration
- `src/chambers/fc-core/config/fc_config.yaml` — Primary config; `simulation_mode: false` confirmed from Phase 1
- `scripts/pi-deploy/deploy.sh` — Deployment pipeline (rsync + colcon + systemd restart)
- Systemd service unit (check Pi at `/etc/systemd/system/fc-core.service`) — Add `CYCLONEDDS_URI` env var here

### Network Reference
- `.planning/phases/01-pi-integration-environment/01-CONTEXT.md` — D-06 through D-08: network decisions, VPN background

### Project Planning
- `.planning/ROADMAP.md` §Phase 6 — Goal statement (sparse — this CONTEXT.md is the authoritative scope)
- `.planning/STATE.md` — Current Pi status, confirmed network IPs

</canonical_refs>

<code_context>
## Existing Code and Infrastructure Insights

### Reusable Assets
- `wg0.conf.template` — already correct structure; only change needed is `Endpoint = mossrock.space:51820`
- `docs/pi-setup/wireguard-setup.md` — step-by-step setup already written; planner should reference, not rewrite
- FC-1 systemd service — already handles env vars; add `CYCLONEDDS_URI` alongside existing `ROS_DOMAIN_ID` and `ROS_LOCALHOST_ONLY`

### Integration Points
- Pi: `wg-quick@wg0` systemd service is the VPN auto-connect mechanism (same pattern as `wg-quick@wg0` on Ubuntu)
- Elder-plops: current WireGuard setup unknown — researcher should check (NetworkManager? manual wg-quick? nmcli?)
- pfSense: WebGUI at 10.68.155.1 — WireGuard peer management via VPN > WireGuard menu

### Known State (from Phase 1)
- Pi OS: Ubuntu 24.04.4 LTS, WireGuard installable via `apt install wireguard`
- SSH: `ssh fc1` (HostName 10.68.155.53) confirmed working
- ROS_LOCALHOST_ONLY=0 already set — cross-machine ROS prerequisite met
- ROS_DOMAIN_ID=69 set on Pi systemd — must match workstation env

</code_context>

<specifics>
## Specific Notes

- User's phrasing: "delegate authentication to the VPN layer" — trust model is mesh membership = authorization. No per-service auth needed inside the mesh.
- FC physical location: may be deployed remotely (not on home LAN). Phase must work for this scenario — `mossrock.space` endpoint is the key enabler.
- Elder-plops role: "mission control" — needs persistent, reliable VPN connectivity to see live ROS topics from FC-1.
- User is comfortable with pfSense WebGUI for router config but may need hand-holding on WireGuard peer addition steps.

</specifics>

<deferred>
## Deferred Ideas

- Automatic DDNS update if `mossrock.space` IP changes (pfSense DDNS client can handle this — out of phase scope, note for router maintenance)
- Multiple FC units on the mesh (FC-2, FC-3) — mesh subnet has room; multi-chamber addressed in v2 requirements
- Firewall rules inside the VPN mesh (limiting which peers can reach which ROS topics) — not needed now; trust model is mesh = trusted

</deferred>

---

*Phase: 06-wireguard-vpn-routing-for-ros-traffic*
*Context gathered: 2026-03-29*
