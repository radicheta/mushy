# Phase 09: Connectivity & Boot Stability - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-11
**Phase:** 09-connectivity-boot-stability
**Areas discussed:** 4G path & Pi link, Boot race fix strategy, WAN-blip recovery, Verification procedure

---

## 4G Path & Pi Link

| Option | Description | Selected |
|--------|-------------|----------|
| WiFi to standalone MiFi | Pi's wlan0 connects to a standalone 4G MiFi; simplest, no USB drivers | ✓ |
| USB tether from phone | Android USB tether; fragile in farm env | |
| USB LTE dongle | USB cellular modem on Pi; needs driver setup | |
| Travel router w/ 4G USB | GL.iNet-style with Pi on Ethernet; more isolated but extra device | |

**Follow-up — MiFi placement (given ~40m farm layout):**

| Option | Description | Selected |
|--------|-------------|----------|
| MiFi next to Pi, Pi on WiFi | Short hop <1m, MiFi shares Pi power area | ✓ |
| MiFi in main area, long-range WiFi | Signal risk through chamber walls | |
| MiFi in main area, 40m Ethernet | Most reliable but physical install | |
| Defer to plan | Plan does signal check first, then decides | |

**User's choice:** Standalone MiFi physically co-located with the Pi, short WiFi hop.
**Notes:** No 40m cable run, no long-range WiFi. Entire WAN path self-contained in the chamber area.

---

## Boot Race Fix Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| After=tailscaled + wait-for-interface ExecStartPre | Belt-and-suspenders: ordering + explicit probe | ✓ |
| After=tailscaled.service only | Minimal, may not catch interface readiness | |
| Dedicated wait-for-tailscale0.service oneshot | Reusable but over-engineered today | |
| ExecStartPre only, no After= | Ordering absent, confusing unit file | |

**User's choice:** Belt-and-suspenders approach — both systemd ordering and explicit interface probe.
**Notes:** Matches milestone audit suggestion. Target is zero automatic restarts on healthy cold boot.

---

## WAN-Blip Recovery Behavior

| Option | Description | Selected |
|--------|-------------|----------|
| Tailscale + kernel handle it; no fc-core restart | fc-core stays running; auto resync; target ~30s | ✓ |
| fc-core restart on WAN loss | Watchdog or netlink monitor; more moving parts | |
| Accept longer recovery, no target | Looser bar for flaky cellular | |

**User's choice:** Passive recovery — no fc-core restart, Tailscale + DDS handle reconnection.
**Notes:** Concrete target is `ros2 topic echo /fc1/humidity` returning within 30s of hotspot toggle-on.

---

## Verification Procedure

| Option | Description | Selected |
|--------|-------------|----------|
| Remote reboot via Tailscale SSH | SSH reboot + journalctl read | |
| Grower power-cycles, you watch | Real cold boot, needs coordination | |
| Both (remote then grower attestation) | Fast iteration + real cold-boot attestation | |
| Other (free text) | — | ✓ |

**User's choice (free text):** "me and the farmer are the same person with different hats. also fc is remote by some 40 meters"
**Notes:** Operator and grower are the same person (Santi) — physical verification is self-serve. Saved as user memory `user_operator_and_grower.md` to prevent future workflows from assuming separate-stakeholder coordination.

**Follow-up — remote access pattern:**

| Option | Description | Selected |
|--------|-------------|----------|
| elder-plops reaches fc1 from anywhere (Tailscale roaming) | Standard mesh; matches Phase 06 | |
| Only from farm LAN when physically present | Simpler success bar | |
| Remote from multiple places (home + farm + elsewhere) | Roaming requirement explicit | ✓ |

**User's choice:** Multi-location roaming. Reachability must be verified from at least two locations to count success criterion 1 as passing.

---

## Claude's Discretion

- ExecStartPre script body specifics (poll interval, max wait within 30s)
- Whether ExecStartPre lives inline or in a separate script file
- Journal log phrasing for failure cases
- Unit file directives beyond the specific changes above (Conflicts=, OnFailure=, etc.)

## Deferred Ideas

- Cellular failover / backup WAN path (future milestone)
- WAN-loss alerts (Phase 999.3 backlog)
- MiFi hardware selection docs (user sourcing independently)
- fc_core self-reconnect logic for DDS peer loss
- Reusable wait-for-tailscale0.service oneshot (revisit if Phase 10 needs it)
