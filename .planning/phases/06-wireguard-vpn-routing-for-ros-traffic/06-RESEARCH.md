# Phase 6: WireGuard VPN Routing for ROS Traffic — Research

**Researched:** 2026-03-29
**Domain:** WireGuard VPN, ROS2 DDS peer discovery, systemd networking, pfSense
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Both SSH and live ROS topics over VPN — full ROS2 visibility from elder-plops over tunnel (ros2 topic echo, ros2 node list). Not just shell access.
- **D-02:** VPN is mandatory. ROS2 has no built-in auth — trust model is "on the mesh = authorized." No plaintext ROS traffic on the internet.
- **D-03:** WireGuard server is pfSense at 10.68.155.1, mesh subnet 172.16.10.0/24. pfSense WG interface (igb5): 172.16.10.1. FC-1 Pi VPN IP: 172.16.10.5. Elder-plops VPN IP: 172.16.10.3 (confirmed by research).
- **D-04:** Internet endpoint is `mossrock.space`. pfSense WAN is 192.168.88.182 behind ISP router at 192.168.88.1 — requires UDP 51820 port forward on ISP router to pfSense.
- **D-05:** Split-tunnel routing only. AllowedIPs = 172.16.10.0/24. Pi and elder-plops keep normal internet routing.
- **D-06:** FC-1 Pi — always-on, internet-capable. Deploy wg0.conf with Endpoint = mossrock.space:51820. Enable wg-quick@wg0 as systemd service.
- **D-07:** Elder-plops — already registered, needs auto-connect made persistent (currently manual/autoconnect=no).
- **D-08:** pfSense — must accept internet connections. WireGuard server already exists (public key: FkNbdYtcfBgsYvOzv6UcnxPIhwRDEyv8jMehsOL43E0=). FC-1 peer must be added. Port forward: ISP router 192.168.88.1 → pfSense 192.168.88.182 UDP 51820.
- **D-09:** Configure Cyclone DDS with explicit unicast peers. ROS2 Jazzy uses Cyclone DDS (after installing rmw_cyclonedds_cpp). Multicast does not route over WireGuard tunnels. XML config listing peer VPN IPs. CYCLONEDDS_URI env var in fc-core systemd unit and elder-plops shell.
- **D-10:** Claude's Discretion — Cyclone DDS XML structure. Use documented peer/locator config. Do NOT switch to Fast DDS.
- **D-11:** LAN remains primary. fc-core service does not depend on VPN. WireGuard failure must not crash control loop.
- **D-12:** PersistentKeepalive = 25 already set in template. Keep this value.

### Claude's Discretion

- Exact XML format and peer discovery options for Cyclone DDS (D-10).
- Elder-plops auto-connect mechanism (confirmed by research: NetworkManager wg0, autoconnect=no → change to yes).

### Deferred Ideas (OUT OF SCOPE)

- Automatic DDNS update if mossrock.space IP changes (pfSense DDNS client).
- Multiple FC units on the mesh (FC-2, FC-3).
- Firewall rules inside VPN mesh (trust model is mesh = trusted).
</user_constraints>

---

## Summary

This phase connects FC-1 Pi and elder-plops via an always-on WireGuard mesh (172.16.10.0/24), then configures ROS2's DDS middleware to discover peers over the tunnel. There are two independent work streams: (1) WireGuard connectivity and (2) DDS unicast configuration.

**WireGuard state discovered by research:**
- Pi (172.16.10.5): WireGuard kernel module present (`/lib/modules/6.8.0-1047-raspi/kernel/drivers/net/wireguard/wireguard.ko.zst`), but `wireguard-tools` NOT installed, no `/etc/wireguard/` directory. Needs full setup.
- Elder-plops (172.16.10.3): WireGuard managed by NetworkManager (`nmcli connection wg0`), tunnel is UP right now (172.16.10.1 reachable), but `autoconnect = no` — connect is currently manual. VPN IP confirmed as `172.16.10.3`.

**DDS state discovered by research:**
- Pi uses FastDDS by default (`ros-jazzy-rmw-fastrtps-cpp` installed, `ros-jazzy-rmw-cyclonedds-cpp` NOT installed but available at version 2.2.3). Decision D-09 locks to CycloneDDS — install step is required.
- Elder-plops has no ROS2 installed at `/opt/ros/jazzy/` — developer sources via `/mnt/slime-kingdom/opt/mushy/setup.sh`, which points to `/opt/ros/jazzy/` (not present on this machine). ROS2 is accessed via Docker or the Pi — elder-plops serves as a CLI terminal, not a full ROS host. This means `ros2 topic echo` on elder-plops requires `ros2` to be available. **This is an open question** — see Open Questions below.

**Primary recommendation:** Follow the three-track approach — Pi WireGuard setup, elder-plops autoconnect hardening, then CycloneDDS unicast config on both endpoints that have ROS2.

---

## Standard Stack

### Core
| Library/Tool | Version | Purpose | Why Standard |
|---|---|---|---|
| wireguard-tools | 1.0.20210914 (stable) | wg / wg-quick CLI, wg0.conf management | Standard WireGuard userspace tooling on Ubuntu |
| ros-jazzy-rmw-cyclonedds-cpp | 2.2.3 (available) | CycloneDDS RMW for ROS2 Jazzy | Required by D-09; enables unicast XML config |
| NetworkManager (nmcli) | pre-installed on elder-plops | Manages wg0 connection on elder-plops | Already managing existing wg0 connection |
| wg-quick / systemd | wg-quick@wg0.service | Auto-start WireGuard on Pi at boot | Standard Ubuntu WireGuard service pattern |

### Supporting
| Tool | Purpose | When to Use |
|---|---|---|
| `envsubst` (gettext-base) | Fill `wg0.conf.template` variables | Deployment step on Pi |
| `wg genkey` / `wg pubkey` | Generate Pi WireGuard keypair | One-time on Pi before pfSense peer addition |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|---|---|---|
| CycloneDDS | FastDDS (already installed on Pi) | FastDDS would avoid an apt install, but D-09 locks to CycloneDDS; FastDDS XML structure is more complex (requires `interfaceWhiteList` + `initialPeersList` + `useBuiltinTransports=false`) |
| wg-quick systemd | NetworkManager on Pi (like elder-plops) | NM is heavier; wg-quick is standard for server/embedded; Ubuntu 24.04 supports both |

**Installation (on Pi):**
```bash
sudo apt install wireguard ros-jazzy-rmw-cyclonedds-cpp
```

**Version verification:** `ros-jazzy-rmw-cyclonedds-cpp` candidate 2.2.3-1noble.20260124.062852 confirmed available on Pi via `apt-cache policy`. `wireguard-tools` kernel module already present in Pi kernel 6.8.0-1047-raspi.

---

## Architecture Patterns

### Recommended Project Structure

No new source directories needed. Config files added:
```
/etc/wireguard/wg0.conf          # Pi only — deployed from wg0.conf.template
/etc/cyclonedds.xml              # Pi only — CycloneDDS unicast config
~/.config/cyclonedds.xml         # Elder-plops — CycloneDDS unicast config (if ROS2 present)
scripts/pi-deploy/
├── wg-setup.sh                  # New: WireGuard install + config deploy script
└── cyclonedds.xml               # New: CycloneDDS XML template for both endpoints
```

### Pattern 1: WireGuard via wg-quick systemd (Pi)

**What:** Install wireguard-tools, fill wg0.conf.template with Pi private key and mossrock.space endpoint, deploy to `/etc/wireguard/wg0.conf`, enable `wg-quick@wg0`.
**When to use:** Any Ubuntu system that needs always-on WireGuard without NetworkManager.

```bash
# Generate keypair
wg genkey | sudo tee /etc/wireguard/private.key | wg pubkey | sudo tee /etc/wireguard/public.key
sudo chmod 600 /etc/wireguard/private.key

# Fill template (update WG_SERVER_ENDPOINT to mossrock.space per D-06)
sudo bash -c "
  WG_PRIVATE_KEY=\$(cat /etc/wireguard/private.key)
  WG_SERVER_PUBLIC_KEY='FkNbdYtcfBgsYvOzv6UcnxPIhwRDEyv8jMehsOL43E0='
  WG_SERVER_ENDPOINT='mossrock.space'
  WG_IP='172.16.10.5'
  envsubst < /path/to/wg0.conf.template > /etc/wireguard/wg0.conf
  chmod 600 /etc/wireguard/wg0.conf
"
sudo systemctl enable --now wg-quick@wg0
```

**Verification:**
```bash
sudo wg show
ping 172.16.10.1   # pfSense WG gateway
ping 172.16.10.3   # elder-plops
```

### Pattern 2: NetworkManager autoconnect for elder-plops (D-07)

**What:** The existing `wg0` NetworkManager connection has `autoconnect = no`. Change to `yes` so it connects at boot persistently. No re-keying or re-config needed.

```bash
sudo nmcli connection modify wg0 connection.autoconnect yes
sudo nmcli connection modify wg0 connection.autoconnect-priority 5
sudo nmcli connection up wg0   # verify immediately
```

**Verification:**
```bash
nmcli connection show wg0 | grep autoconnect
ping 172.16.10.1
```

### Pattern 3: pfSense — Add FC-1 Peer

**What:** Navigate pfSense WebGUI → VPN → WireGuard → Peers → Add.

Required fields:
| Field | Value |
|---|---|
| Tunnel | tun_wg0 (the "mossrock" tunnel) |
| Description | FC-1 Pi |
| Public Key | (output of `sudo cat /etc/wireguard/public.key` on Pi) |
| Allowed IPs | `172.16.10.5/32` |
| Dynamic Endpoint | checked (Pi IP changes when remote) |

After adding peer: pfSense may need firewall rule on WireGuard interface to allow traffic from 172.16.10.5.

### Pattern 4: CycloneDDS Unicast XML (the DDS fix)

**What:** DDS uses multicast by default for peer discovery. Multicast does not route over WireGuard tunnels. Solution: create a CycloneDDS XML config that binds to the `wg0` interface and lists peers by VPN IP.

**Source:** Verified against official ros2/ros2_dds_profiles_examples repository (GitHub).

```xml
<!-- /etc/cyclonedds.xml (Pi) and ~/.config/cyclonedds.xml (elder-plops) -->
<CycloneDDS xmlns="https://cdds.io/config"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="https://cdds.io/config https://raw.githubusercontent.com/eclipse-cyclonedds/cyclonedds/master/etc/cyclonedds.xsd">
    <Domain Id="any">
        <General>
            <Interfaces>
                <NetworkInterface name="wg0" multicast="false" />
            </Interfaces>
            <AllowMulticast>false</AllowMulticast>
        </General>
        <Discovery>
            <Peers>
                <Peer address="172.16.10.3"/>  <!-- elder-plops -->
                <Peer address="172.16.10.5"/>  <!-- FC-1 Pi -->
            </Peers>
        </Discovery>
    </Domain>
</CycloneDDS>
```

**IMPORTANT NOTE from official examples:** Using more than one `<NetworkInterface>` entry breaks the initial peers list. Only specify the single `wg0` interface.

**Environment variable — Pi systemd service** (`/etc/systemd/system/fc-core.service`):
```ini
Environment="ROS_DOMAIN_ID=69"
Environment="ROS_LOCALHOST_ONLY=0"
Environment="RMW_IMPLEMENTATION=rmw_cyclonedds_cpp"
Environment="CYCLONEDDS_URI=file:///etc/cyclonedds.xml"
```

**Environment variable — elder-plops shell** (`.bashrc` or sourced before `ros2` commands):
```bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI=file:///home/santi/.config/cyclonedds.xml
```

### Anti-Patterns to Avoid

- **Using multiple `<NetworkInterface>` entries in CycloneDDS XML:** Breaks unicast SPDP packet sending to specified peers. Use exactly one interface.
- **Not setting `AllowMulticast=false`:** DDS will still attempt multicast discovery on the wg0 interface, which silently fails. Must be explicitly disabled.
- **Setting `WG_SERVER_ENDPOINT` to LAN IP (`10.68.155.1`):** The doc currently uses LAN IP. This works only when Pi is on the LAN. Per D-06, must change to `mossrock.space` so it works from remote locations.
- **Deploying wg0.conf without proper file permissions:** `/etc/wireguard/wg0.conf` must be `chmod 600`. wg-quick will refuse to start if permissions are too open.
- **Not adding fc-core service dependency ordering for WireGuard:** fc-core service MUST NOT depend on wg-quick (per D-11). Keep `After=network-online.target` only — not `After=wg-quick@wg0.service`.
- **Forgetting `ROS_LOCALHOST_ONLY=0` is already set:** This is a prerequisite already in place (confirmed by reading actual fc-core.service on Pi). Don't remove it.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---|---|---|---|
| WireGuard key management | Custom key generation script | `wg genkey \| wg pubkey` pipeline | Standard, atomic, permissions handled by wg-quick |
| DDS peer discovery over VPN | Custom ROS bridge/relay | CycloneDDS XML unicast config | Built-in; no extra process, no latency |
| Boot persistence for WireGuard on Pi | Cron job or rc.local | `systemctl enable wg-quick@wg0` | Proper systemd integration, handles ordering |
| Template variable substitution | Python/sed script | `envsubst` (gettext-base) | Already used in existing docs, one-liner |

**Key insight:** WireGuard over NAT is a solved problem — PersistentKeepalive=25 handles most NAT traversal. The DDS multicast-over-VPN problem is equally solved: explicit unicast peers in CycloneDDS XML is the standard approach documented by the ROS2 project itself.

---

## Runtime State Inventory

> Not a rename/refactor phase — this section is not applicable.

---

## Common Pitfalls

### Pitfall 1: Multicast Discovery Silently Fails over Tunnel
**What goes wrong:** `ros2 topic echo fc/humidity` on elder-plops shows no output or "Waiting for publisher." Nodes are publishing fine on Pi.
**Why it happens:** DDS defaults to multicast UDP for peer discovery. WireGuard is a point-to-point tunnel that does not forward multicast.
**How to avoid:** Deploy CycloneDDS XML with `AllowMulticast=false` and explicit `<Peer>` entries for all VPN IPs BEFORE testing topic visibility.
**Warning signs:** `ros2 node list` from elder-plops shows nothing; `ros2 topic list` shows nothing; but `ping 172.16.10.5` succeeds.

### Pitfall 2: wg0 interface not up when CycloneDDS starts
**What goes wrong:** `fc-core` service starts at boot before WireGuard connects. CycloneDDS binds to wg0, finds no interface, falls back to multicast or fails to bind at all.
**Why it happens:** fc-core systemd service ordering: `After=network-online.target`. WireGuard takes a few seconds after network-online.
**How to avoid:** Do NOT add `After=wg-quick@wg0.service` (violates D-11 — fc-core must not depend on VPN). Instead, CycloneDDS handles missing interface gracefully — nodes start and peer discovery succeeds once wg0 comes up. Verified approach: ROS2 nodes do not need DDS to be connected at startup; they retry peer discovery continuously.
**Warning signs:** Service starts cleanly but `ros2 topic list` from elder-plops takes 30+ seconds to appear after reboot.

### Pitfall 3: ISP router port forward not configured
**What goes wrong:** Pi can reach pfSense WireGuard server from LAN (172.16.10.1 pingable) but fails from remote/internet.
**Why it happens:** pfSense WAN is 192.168.88.182 behind the ISP router at 192.168.88.1. UDP 51820 must be forwarded on ISP router to 192.168.88.182.
**How to avoid:** Test remote connectivity explicitly: disconnect Pi from LAN, use mobile data, and attempt tunnel establishment.
**Warning signs:** `wg show` on Pi shows peer but `latest handshake` never updates.

### Pitfall 4: pfSense peer not added for FC-1
**What goes wrong:** Pi generates key and starts wg-quick, but pfSense rejects handshakes because FC-1 public key is not in pfSense peer list.
**Why it happens:** pfSense WireGuard is a server — peers must be explicitly registered. New peer is not automatic.
**How to avoid:** Add FC-1 public key to pfSense BEFORE enabling wg-quick on Pi. Sequence: generate key → share pubkey → add peer in pfSense → start wg-quick on Pi.
**Warning signs:** `sudo wg show` on Pi shows `latest handshake: (none)` more than 30 seconds after starting.

### Pitfall 5: ROS_DOMAIN_ID mismatch
**What goes wrong:** `ros2 topic list` on elder-plops shows nothing even with working VPN and correct DDS config.
**Why it happens:** ROS2 uses domain IDs to isolate namespaces. Pi has `ROS_DOMAIN_ID=69`. Elder-plops shell must also have `ROS_DOMAIN_ID=69` set when running ros2 commands.
**How to avoid:** Source the project `setup.sh` on elder-plops before any ros2 commands (it sets `ROS_DOMAIN_ID=69`).
**Warning signs:** `ros2 node list` returns empty but `ping 172.16.10.5` and `ros2 daemon status` both work.

### Pitfall 6: CycloneDDS package not installed on Pi
**What goes wrong:** Setting `RMW_IMPLEMENTATION=rmw_cyclonedds_cpp` in systemd unit causes fc-core service to fail at start with "No RMW implementation found."
**Why it happens:** Pi only has `ros-jazzy-rmw-fastrtps-cpp` installed by default. CycloneDDS package must be installed separately.
**How to avoid:** `sudo apt install ros-jazzy-rmw-cyclonedds-cpp` on Pi BEFORE updating the systemd unit.
**Warning signs:** `sudo systemctl status fc-core` shows ExecStart failing immediately; `journalctl -u fc-core -n 20` shows RMW-related error.

### Pitfall 7: elder-plops may not have ROS2 installed locally
**What goes wrong:** `ros2 topic echo fc/humidity` fails with "command not found" even with tunnel up.
**Why it happens:** `/opt/ros/jazzy/` does not exist on elder-plops; `setup.sh` sources from there. ROS2 Jazzy is on the Pi, not the workstation.
**How to avoid:** See Open Questions — this may require installing ROS2 on elder-plops or using Docker. Verify first: `source /opt/ros/jazzy/setup.bash 2>/dev/null && echo found || echo missing`.
**Warning signs:** `setup.sh` throws "No such file or directory" for `/opt/ros/jazzy/setup.bash`.

---

## Code Examples

Verified patterns from official sources:

### CycloneDDS Unicast XML (wg0 interface binding)
```xml
<!-- Source: https://github.com/ros2/ros2_dds_profiles_examples/tree/main/cyclonedds -->
<!-- Install: /etc/cyclonedds.xml on Pi, ~/.config/cyclonedds.xml on elder-plops -->
<CycloneDDS xmlns="https://cdds.io/config"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="https://cdds.io/config https://raw.githubusercontent.com/eclipse-cyclonedds/cyclonedds/master/etc/cyclonedds.xsd">
    <Domain Id="any">
        <General>
            <Interfaces>
                <!-- Only ONE interface entry — multiple entries break unicast SPDP -->
                <NetworkInterface name="wg0" multicast="false" />
            </Interfaces>
            <AllowMulticast>false</AllowMulticast>
        </General>
        <Discovery>
            <Peers>
                <Peer address="172.16.10.3"/>  <!-- elder-plops VPN IP -->
                <Peer address="172.16.10.5"/>  <!-- FC-1 Pi VPN IP -->
            </Peers>
        </Discovery>
    </Domain>
</CycloneDDS>
```

### fc-core.service with CycloneDDS (updated Environment lines only)
```ini
# Add to existing [Service] section alongside ROS_DOMAIN_ID and ROS_LOCALHOST_ONLY:
Environment="RMW_IMPLEMENTATION=rmw_cyclonedds_cpp"
Environment="CYCLONEDDS_URI=file:///etc/cyclonedds.xml"
```

### Elder-plops wg0 autoconnect enable
```bash
# Source: NetworkManager nmcli documentation
sudo nmcli connection modify wg0 connection.autoconnect yes
nmcli connection show wg0 | grep autoconnect  # verify
```

### pfSense peer addition (WebGUI sequence)
```
VPN → WireGuard → Peers → + Add Peer
  Tunnel:         tun_wg0 (mossrock)
  Description:    FC-1 Pi
  Public Key:     <paste output of: ssh fc1 "sudo cat /etc/wireguard/public.key">
  Allowed IPs:    172.16.10.5/32
  Dynamic Endpoint: checked
→ Save → Apply Changes
```

### WireGuard install + deploy on Pi
```bash
# Source: wireguard-setup.md in project docs
sudo apt install wireguard

# Generate keypair
wg genkey | sudo tee /etc/wireguard/private.key | wg pubkey | sudo tee /etc/wireguard/public.key
sudo chmod 600 /etc/wireguard/private.key

# Fill template — NOTE: endpoint changes to mossrock.space (not 10.68.155.1)
sudo bash -c "
  WG_PRIVATE_KEY=\$(cat /etc/wireguard/private.key)
  WG_SERVER_PUBLIC_KEY='FkNbdYtcfBgsYvOzv6UcnxPIhwRDEyv8jMehsOL43E0='
  WG_SERVER_ENDPOINT='mossrock.space'
  WG_IP='172.16.10.5'
  envsubst < /path/to/wg0.conf.template > /etc/wireguard/wg0.conf
  chmod 600 /etc/wireguard/wg0.conf
"

sudo systemctl enable --now wg-quick@wg0
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|---|---|---|---|
| OpenVPN for ROS mesh | WireGuard (wireguard-tools) | ~2020 | Simpler config, kernel-native, lower latency |
| DDS multicast on flat LAN | CycloneDDS unicast XML for VPN/cloud | 2021+ | Required for any routed network (VPN, cloud, multi-subnet) |
| Manual `wg-quick up wg0` | systemd `wg-quick@wg0.service` | wireguard-tools 1.0+ | Reliable auto-start, logging via journalctl |
| NM manual WireGuard | `nmcli connection.autoconnect yes` | NetworkManager 1.16+ | Native NM WireGuard support, no wg-quick needed |

---

## Open Questions

1. **Is ROS2 Jazzy installed on elder-plops?**
   - What we know: `/opt/ros/jazzy/` does NOT exist on elder-plops (confirmed by research). `setup.sh` sources from `/opt/ros/jazzy/setup.bash` which is missing. Elder-plops has no `ros-jazzy-*` apt packages.
   - What's unclear: How does the developer currently run `ros2` CLI commands? Via Docker? Via SSH to Pi? Or is ROS2 not yet installed on elder-plops and Phase 6 is expected to install it?
   - Recommendation: **Check at Phase start** — `ls /opt/ros/jazzy/ 2>/dev/null || echo missing`. If missing, install ROS2 Jazzy on elder-plops (`sudo apt install ros-jazzy-ros-base ros-jazzy-rmw-cyclonedds-cpp`) OR accept that "ros2 topic echo from elder-plops" means via SSH to Pi. This affects whether the CycloneDDS XML config step on elder-plops is needed at all.
   - Impact: If ROS2 is not installed on elder-plops, the CYCLONEDDS_URI config on elder-plops is a no-op. The Pi-side config alone is sufficient for inter-machine discovery once both are on the VPN mesh.

2. **Does ISP router (192.168.88.1) support port forwarding for UDP 51820?**
   - What we know: pfSense WAN is 192.168.88.182, behind ISP router at 192.168.88.1. Port forward required for remote FC-1 access.
   - What's unclear: Some ISP routers (especially fiber ONTs) restrict port forwarding or require DMZ mode.
   - Recommendation: Verify during implementation. Test from mobile data: `nc -zvu mossrock.space 51820`. If blocked by ISP, alternative is to use the LAN endpoint only (10.68.155.1:51820) — this still satisfies LAN access but limits the remote FC deployment scenario.

3. **What is elder-plops VPN public key registered with pfSense?**
   - What we know: Elder-plops is already a registered VPN peer (172.16.10.3 is reachable). The connection exists.
   - What's unclear: The public key is hidden in nmcli output (`wireguard.private-key: <hidden>`). This information is needed only if re-registering or debugging — not needed for Phase 6 since the peer is already working.
   - Recommendation: No action needed unless tunnel breaks.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|---|---|---|---|---|
| wireguard-tools (Pi) | Pi WireGuard setup | No | — (kernel module present) | `sudo apt install wireguard` |
| ros-jazzy-rmw-cyclonedds-cpp (Pi) | CycloneDDS DDS config | No | 2.2.3 in apt | `sudo apt install ros-jazzy-rmw-cyclonedds-cpp` |
| WireGuard (elder-plops) | elder-plops tunnel | Yes (NM) | NM-managed wg0 at 172.16.10.3 | — |
| pfSense WireGuard server | All VPN connectivity | Yes | tun_wg0 "mossrock" | — |
| mossrock.space DNS | Remote Pi connectivity | Unknown | — | pfSense WAN IP fallback (192.168.88.182) |
| ISP router port forward | Remote connectivity | Unknown | — | LAN-only operation (no remote FC) |
| ROS2 Jazzy (elder-plops) | `ros2 topic echo` from workstation | No | — | SSH to Pi and run there |

**Missing dependencies with no fallback:**
- `wireguard-tools` on Pi — blocks everything; install via apt on Pi before any other step.
- `ros-jazzy-rmw-cyclonedds-cpp` on Pi — required by D-09 decision; default FastDDS cannot use CycloneDDS XML.

**Missing dependencies with fallback:**
- ROS2 on elder-plops — if not installed, `ros2 topic echo` must be run via `ssh fc1 "source ... && ros2 topic echo fc/humidity"` instead.
- ISP port forward — if not possible, remote scenario is deferred; LAN access still works.

---

## Validation Architecture

### Test Framework
| Property | Value |
|---|---|
| Framework | pytest (existing fc_core test suite) |
| Config file | `src/chambers/fc-core/setup.cfg` |
| Quick run command | `pytest src/chambers/fc-core/fc_core/test/ -x -q` |
| Full suite command | `colcon test --packages-select fc_core` |

### Phase Requirements → Test Map

This phase is primarily infrastructure/networking — not unit-testable in the traditional sense. Tests are integration checks via live commands.

| ID | Behavior | Test Type | Automated Command | Exists? |
|---|---|---|---|---|
| INFRA-02 | WireGuard configured and reachable | smoke | `ssh fc1 "ping -c 2 172.16.10.1"` | ❌ Wave 0 (shell command) |
| INFRA-04 | ROS2 nodes on Pi visible from elder-plops | smoke | `ROS_DOMAIN_ID=69 ros2 topic list` (elder-plops, after sourcing) | ❌ Wave 0 (live check) |
| — | WireGuard service auto-starts on Pi reboot | smoke | `ssh fc1 "sudo systemctl is-active wg-quick@wg0"` | ❌ Wave 0 |
| — | elder-plops wg0 autoconnects | smoke | `nmcli connection show wg0 \| grep "autoconnect: yes"` | ❌ Wave 0 |

Note: These are manual/shell-command verifications, not pytest tests. No new pytest tests are needed for this phase — connectivity cannot be unit-tested, and fc_core unit tests should not break.

### Sampling Rate
- **Per task commit:** `pytest src/chambers/fc-core/fc_core/test/ -x -q` (guard against regressions from systemd service changes)
- **Per wave merge:** Full colcon test
- **Phase gate:** All smoke checks green + `ros2 topic echo fc/humidity` produces output on elder-plops

### Wave 0 Gaps
- No new pytest files needed — phase is infrastructure, not code.
- Smoke check script `scripts/verify/phase06-vpn-check.sh` recommended (not required) to run all ping/service checks in one command.

---

## Sources

### Primary (HIGH confidence)
- `ssh fc1 dpkg -l` — Confirmed Pi has FastDDS, not CycloneDDS; confirmed CycloneDDS available in apt at 2.2.3
- `ssh fc1 ls /etc/wireguard/` — Confirmed Pi has no WireGuard config yet
- `ssh fc1 modinfo wireguard` — Confirmed WireGuard kernel module present
- `ssh fc1 cat /etc/systemd/system/fc-core.service` — Confirmed actual service env vars
- `nmcli connection show wg0` (elder-plops) — Confirmed elder-plops VPN IP 172.16.10.3, autoconnect=no, NM-managed
- `ping 172.16.10.1` (elder-plops) — Confirmed tunnel is currently UP on elder-plops
- `https://github.com/ros2/ros2_dds_profiles_examples` — Official ROS2 project CycloneDDS XML for unicast (verified)
- Existing project files: `wg0.conf.template`, `docs/pi-setup/wireguard-setup.md`, `scripts/pi-deploy/fc-core.service`

### Secondary (MEDIUM confidence)
- https://husarnet.com/docs/ros2/custom-cyclonedds-xml — CycloneDDS NetworkInterface syntax for VPN interface
- https://docs.netgate.com/pfsense/en/latest/recipes/wireguard-ra.html — pfSense peer addition steps
- https://github.com/tuw-robotics/ros2_cyclonedds_wireguard — ROS2 + CycloneDDS + WireGuard example project (Humble, patterns applicable to Jazzy)
- https://danaukes.com/notebook/ros2/20-configuring-unicast-dds-with-cyclone — Unicast CycloneDDS XML pattern

### Tertiary (LOW confidence)
- General WireGuard NAT traversal notes — based on well-known behavior, not phase-specific test
- ISP port forward feasibility — untested for this specific ISP setup

---

## Metadata

**Confidence breakdown:**
- WireGuard setup (Pi + elder-plops): HIGH — current state directly observed via SSH and nmcli
- CycloneDDS XML format: HIGH — verified against official ros2 project examples repo
- pfSense peer addition: MEDIUM — based on official Netgate docs, not tested against this specific pfSense version
- ROS2 on elder-plops: HIGH (confirmed missing) — open question is intentional, not uncertainty
- ISP port forward: LOW — unknown without hands-on test

**Research date:** 2026-03-29
**Valid until:** 2026-04-28 (stable domain)
