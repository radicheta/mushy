# Phase 999.46 — fc1 CycloneDDS multi-interface binding (RESEARCH)

**Status:** research-only. No production change executed.
**Filed:** 2026-05-10. **Author:** research pass.
**Why this phase exists:** Phase 32 added `wg-hub` (10.66.0.11) on fc1 alongside the
existing `wg0` LAN tunnel (172.16.10.5). DDS is currently bound to `wg0` only
(see `/etc/cyclonedds.xml` on fc1, line ~12). When fc1 physically returns to the
farm on 4G, `wg0` loses its peer and fc-core goes silent — bridge + alerter lose
all telemetry. Memory: `project_fc1_link_architecture_options`,
`project_fc1_cgnat_confirmed`, `feedback_stopping_tailscaled_kills_pid`.

**Versions in scope:**
- ROS2 Jazzy on fc1: `ros-jazzy-cyclonedds 0.10.5`, `rmw-cyclonedds-cpp 2.2.3`.
- elder-plops bridge: same image / mounts host `~/.config/cyclonedds.xml`.
- Authoritative config reference used:
  https://cyclonedds.io/docs/cyclonedds/latest/config/network_interfaces.html
  and `eclipse-cyclonedds/cyclonedds/docs/manual/options.md` @ master.

---

## 1. CycloneDDS multi-interface — what the docs actually say

Direct quotes from upstream docs, distilled:

| Question | Upstream answer |
|---|---|
| Multiple `<NetworkInterface>` entries allowed? | Yes. *"Multiple network interfaces can be used simultaneously by listing multiple NetworkInterface elements."* |
| SPDP behavior with N interfaces | *"the SPDP packets advertise multiple addresses and sends these packets out on all interfaces."* Each peer learns all of our addresses. |
| Peer matching | *"Cyclone DDS checks which interfaces match the addresses advertised by a peer in its SPDP or SEDP messages."* — peer address must be on a subnet reachable from at least one of our interfaces. |
| Path selection when multiple match | Cost-based: `cost = -priority + {uc|mc|ssm} + |READERS| + SUM(...)`. Lowest cost wins. |
| `priority` default | 0 for normal interfaces, 2 for loopback. Higher = preferred. |
| `presence_required` | *"By default, all specified network interfaces must be present; if they are missing Cyclone will not start."* — **CRITICAL**: must set `presence_required="false"` on `wg-hub` so fc-core can boot when wg-hub flaps. |
| Interface goes down at runtime | Not documented. Empirically (and per ROS2 forum reports): SPDP keeps trying on remaining interfaces; existing readers/writers re-route on the next SPDP cycle (default lease 10s). No graceful "switchover" event — there's a gap. |
| `Peers` list scope | Single global `<Peers>` block. CycloneDDS resolves each Peer address against the routing table to pick which interface to send via. So one Peers list, multiple interfaces — works as long as the kernel can route the peer IP. |
| WireGuard MTU | No CycloneDDS-specific docs. wg default MTU 1420; SPDP/SEDP packets are small (<1KB). User data on `/fc1/temperature` etc. is tiny floats. **Not a concern at our payload sizes.** |

**The "ONE NetworkInterface" warning in our existing XML comments is wrong** —
or rather, was a 2024-era ROS2 Foxy/Galactic-era folk wisdom. Cyclone 0.10+
explicitly supports multi-interface. The historical issues
(`ros2/rmw_cyclonedds#455`, `#459`) were source-IP-selection bugs on Linux
*with multicast enabled and overlapping subnets*. Both got "more-info-needed"
and were not reproduced. Our setup is unicast-only on disjoint /24 subnets
(172.16.10.0/24 vs 10.66.0.0/24) — not the failure shape those issues hit.

---

## 2. Concrete config diff

### fc1: `/etc/cyclonedds.xml`

```diff
         <General>
             <Interfaces>
-                <NetworkInterface name="wg0" multicast="false" />
+                <NetworkInterface name="wg0"     priority="10" multicast="false" presence_required="false"/>
+                <NetworkInterface name="wg-hub"  priority="0"  multicast="false" presence_required="false"/>
             </Interfaces>
             <AllowMulticast>false</AllowMulticast>
         </General>
         <Discovery>
             <Peers>
                 <Peer address="172.16.10.3"/>  <!-- elder-plops via wg0 -->
                 <Peer address="172.16.10.5"/>  <!-- self via wg0 -->
+                <Peer address="10.66.0.12"/>   <!-- elder-plops via wg-hub -->
+                <Peer address="10.66.0.11"/>   <!-- self via wg-hub -->
             </Peers>
         </Discovery>
```

Annotation:
- `priority="10"` on wg0 vs `0` on wg-hub → cost calc prefers wg0 (5ms LAN)
  over wg-hub (250ms VPS) when both reach the same peer. This is the failover
  preference knob.
- `presence_required="false"` on **both** so fc-core boots regardless of which
  tunnel is up. Critical for farm-4G scenario where wg0 will be permanently
  absent.
- `<Peers>` has both peer addresses for elder-plops. CycloneDDS will dedupe
  the actual GUID at SPDP time; both addresses just give it discovery hints.

### elder-plops: `/home/santi/.config/cyclonedds.xml` (mounted into bridge)

Symmetric:

```diff
         <General>
             <Interfaces>
-                <NetworkInterface name="wg0" multicast="false" />
+                <NetworkInterface name="wg0"     priority="10" multicast="false" presence_required="false"/>
+                <NetworkInterface name="wg-hub"  priority="0"  multicast="false" presence_required="false"/>
             </Interfaces>
             <AllowMulticast>false</AllowMulticast>
         </General>
         <Discovery>
             <Peers>
                 <Peer address="172.16.10.3"/>
                 <Peer address="172.16.10.5"/>
+                <Peer address="10.66.0.11"/>   <!-- fc1 via wg-hub -->
+                <Peer address="10.66.0.12"/>   <!-- self via wg-hub -->
             </Peers>
         </Discovery>
```

Bridge container restart required (`docker compose restart bridge`) since the
file is bind-mounted read-only.

---

## 3. Test plan

Each phase has explicit verify + rollback. Production loop is the chamber
controller — RH band defended at ±1% must keep working throughout.

### Pre-flight (zero risk)

1. Snapshot current files:
   `ssh fc1 'sudo cp /etc/cyclonedds.xml /etc/cyclonedds.xml.pre-99946'`
   `cp ~/.config/cyclonedds.xml ~/.config/cyclonedds.xml.pre-99946`
2. Confirm both interfaces UP on both ends:
   `ssh fc1 'ip -br addr show wg0 wg-hub'`
   `ip -br addr show wg0 wg-hub`
3. Confirm peer reachability across both paths:
   `ssh fc1 'ping -c2 -W2 172.16.10.3 && ping -c2 -W2 10.66.0.12'`
4. Capture baseline: last 60s of `/fc1/temperature` rate from bridge `/health`
   or directly: `psql ... "select count(*) from temperature where time > now()-interval '60s'"`.

### Phase A — multi-iface ON, both paths UP (production-equivalent)

1. Apply config diff to **elder-plops first** (least risky — bridge restart is
   a known-recoverable operation). `docker compose restart bridge`.
2. Verify telemetry continues for 5 min via Mission Control (per
   `feedback_timescale_over_screenshots`, query Timescale directly:
   `select count(*) from temperature where time > now()-interval '5 min'`
   should be ≥58 rows at 1Hz).
3. If GREEN → apply to fc1: `sudo cp new.xml /etc/cyclonedds.xml &&
   sudo systemctl restart fc-core`. Per
   `feedback_fc1_remote_action_preflight_protocol`: this is a transport-class
   change — preflight before executing.
4. **Verify within 60s** (DDS lease + SPDP cycle):
   - `ros2 topic echo /fc1/temperature --once` from elder-plops env (per
     `feedback_ros2_cli_over_ssh_needs_explicit_dds_env` — export RMW + URI
     + DOMAIN before sourcing setup.bash).
   - Bridge `/health` shows `last_message_age_s < 5`.
   - Timescale row rate matches baseline.
5. **Rollback** if telemetry stops for >30s:
   `ssh fc1 'sudo cp /etc/cyclonedds.xml.pre-99946 /etc/cyclonedds.xml &&
   sudo systemctl restart fc-core'` then revert elder-plops file + restart
   bridge. Recovery target: <2 min total.

### Phase B — simulate wg0 failure, observe wg-hub takes over

1. **DO NOT use `ip link set wg0 down` over SSH if SSH is on wg0.**
   Verify SSH is on wlan0 LAN (`who | grep ubuntu` should show `10.68.155.x`,
   not `172.16.10.x`). If SSH is via wg0, abort and use the lab PTP path
   (`project_lab_topology_gumbald`).
2. Block wg0 traffic with iptables (reversible without losing the interface,
   safer than `link set down`):
   `ssh fc1 'sudo iptables -I OUTPUT -o wg0 -j DROP && sudo iptables -I INPUT -i wg0 -j DROP'`
3. Within 10–30s SPDP lease, DDS should re-route to wg-hub. Verify:
   - `ros2 topic echo /fc1/temperature --once` still returns from elder-plops.
   - Latency now ~250ms (visible in any timestamp diff or `ros2 topic delay`).
   - fc-core controller logs show no safe-state transition (RH band defended).
4. Hold for 5 min. Confirm Timescale row rate maintained. Bridge `/health` GREEN.
5. Restore: `ssh fc1 'sudo iptables -D OUTPUT -o wg0 -j DROP && sudo iptables -D INPUT -i wg0 -j DROP'`. Within 10s, DDS should prefer wg0 again (lower cost).

### Phase C — declare ready for farm-4G

If A + B pass, no further action: when fc1 physically moves and `wg0` goes
permanently silent, DDS rides wg-hub from boot (assuming `presence_required="false"`
worked). Farm-move acceptance test: cold-boot fc1 with wg0 deliberately not
brought up (`systemctl mask wg-quick@wg0` for the test, then unmask).

---

## 4. Failure modes

| # | Mode | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| F1 | DDS double-publish on both interfaces | Low | Wastes ~1KB/s on wg-hub (negligible vs 20MB VPS budget headroom) | Cost diff (`priority="10"` vs `0`) makes Cyclone pick one path per locator pair; double-publish only at SPDP layer (small) |
| F2 | Source-IP confusion (issues #455/#459 shape) | Low here | Peer can't reply | Our subnets are disjoint /24s with explicit kernel routes per wg interface; not the failure shape from those issues |
| F3 | Boot race: fc-core starts before wg-hub is up | **HIGH** without `presence_required="false"` | fc-core refuses to start | `presence_required="false"` on **both** entries — locked in diff above |
| F4 | wg0 dies after fc-core started (analog of `feedback_stopping_tailscaled_kills_pid`) | Medium | Pre-99946: PID would safe-state. Post-99946: DDS migrates to wg-hub; PID continues | This is the *whole point* of the phase |
| F5 | wg-hub flaps mid-operation while wg0 is also UP | Low | Brief SPDP re-shuffle; data path stays on wg0 | Cost preference holds; nothing to do |
| F6 | Both wg0 and wg-hub down simultaneously | Low (independent transports) | fc-core safe-state | Phase 33 heartbeat alerts on this; outside 999.46 scope |
| F7 | Cyclone 0.10.5 has an undiscovered multi-iface bug | Unknown | Telemetry stops | Phase A rollback (<2 min); test on a quiet day |
| F8 | MTU mismatch wg0 (1420) vs wg-hub (1420) vs OS (1500) | Very low | Fragmentation | Both wg interfaces same MTU; user data tiny; no action |

**Highest-risk:** **F3 (boot race)** — unmitigated default of `presence_required=true`
would have fc-core fail-to-start any time wg-hub is slow to come up at boot.
This is *worse* than the status quo. The diff above sets it to `false` on
both interfaces — that line is load-bearing.

---

## 5. Composition with other phases

**Enables:**
- "fc1 returns to farm on 4G" — the prerequisite (per
  `project_fc1_link_architecture_options` and `project_fc1_cgnat_confirmed`,
  VPS hub is the only viable 4G path; this phase makes DDS use it).
- Future operator-laptop access to fc1 telemetry from anywhere via wg-hub
  (composes with 999.47 gumbald peer).

**Does NOT solve:**
- elder-plops's wg-hub being down → fc1 can't reach MC over hub. That's a
  bridge/MC availability concern, not a DDS-binding one. Phase 32 + Phase 33
  heartbeat already cover detection.
- `feedback_stopping_tailscaled_kills_pid` exact analog: if both wg0 AND
  wg-hub die on fc1 simultaneously, fc-core still goes safe-state. 999.46
  reduces probability (need both to fail) but doesn't eliminate the class.
- `999.28` (fc-core start-limit-hit on tailscale0 race) — different layer
  (systemd dependency, not DDS config).

**Composes with:**
- Phase 32 (the hub this rides).
- Phase 33 heartbeat (so when *both* paths die, alert still fires via VPS-side
  receiver — the only path that doesn't require fc1 itself to be reachable).
- 999.43 (heartbeat) + 999.45 (offsite backup) — same VPS.

---

## 6. Open questions deferred

- Should we also add `<LeaseDuration>5 s</LeaseDuration>` (as the parked
  tailscale config did) to make the failover window tighter? Default 10s is
  acceptable for our 1Hz telemetry; keep as-is unless Phase B shows a problem.
- Does Cyclone 0.10.5 honor `priority` per-locator or per-interface globally?
  Docs are ambiguous. Phase B is the empirical test — if wg-hub starts winning
  when wg0 is healthy, revisit.
