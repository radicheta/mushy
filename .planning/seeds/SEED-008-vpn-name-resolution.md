---
id: SEED-008
status: dormant
planted: 2026-05-11
planted_during: v1.6 (Phase 33/34 ship night)
trigger_when: v1.7 milestone planning — operator-quality-of-life pass
scope: Small
---

# SEED-008: VPN name resolution — `fc1.mushy` instead of `10.66.0.11`

## Why This Matters

We added wg-hub in Phase 32 (10.66.0.0/24) and now have 5+ peers — VPS (10.66.0.1), elder-plops (10.66.0.12), fc1 (10.66.0.11), three farmer phones (.20–.22), with gumbald (.10) and a 4th iOS device (.23) queued. Today everyone (operator + farmers + tooling + scripts + uptime-kuma config + the heartbeat receiver's BRIDGE_URL env + the Phase 34 monitor URLs) hardcodes IPs. Any peer renumbering, any new service, or any onboarding of a 6th device starts costing real friction:

- Operator memorizing `.11` vs `.12` vs `.13` and which is which
- Farmer-facing URLs are bare IPs (`http://10.66.0.12:8080/` for Mission Control) — uglier than `mc.mushy/` and harder to remember
- Scripts (sender shims, install scripts, monitor configs) hardcode IPs — re-IP'ing requires sed across the codebase
- New services (timelapse mirror, future status pages, dashboards) inherit the IP-hardcoding pattern

Tailscale solves this with MagicDNS. We deliberately picked WireGuard over Tailscale (Phase 32 DECISION-2 — full self-hosted control, no exit node, no DERP relay surprises). We pay for that choice with no built-in name resolution. SEED-008 is the explicit catch-up.

## Locked Design (decided 2026-05-11 during seed plant)

**dnsmasq on the VPS at 10.66.0.1.** Lightweight, well-known, integrates naturally with the centralized-hub topology we already have.

Three options were evaluated and discarded:

| Option | Why discarded |
|--------|---------------|
| avahi/mDNS over WG with reflector | mDNS is link-local multicast; WireGuard is L3 point-to-point. Avahi reflector mode bridges multicast across interfaces but is fragile (per-host config, breaks on peer reconnect, Apple devices ignore reflectors). Doesn't scale to mobile peers. |
| Static `/etc/hosts` on every peer | What we sort of half-do today via `~/.ssh/config`. Doesn't scale, breaks for non-SSH protocols (browser, ros2 cli, curl), no central source of truth. |
| Headscale (Tailscale-server self-hosted) | Different transport entirely — would replace WireGuard, undoing Phase 32. Out of scope. |

**Implementation shape:**

- `vps/dnsmasq/` compose service or systemd-installed dnsmasq, listening on 10.66.0.1:53 (wg-hub iface only; UFW continues to deny 53 from public).
- Hosts file shape:
  ```
  10.66.0.1   vps.mushy hub.mushy
  10.66.0.10  gumbald.mushy
  10.66.0.11  fc1.mushy
  10.66.0.12  elder-plops.mushy mc.mushy bridge.mushy openmct.mushy
  10.66.0.20  farmer1.mushy
  ...
  ```
  Service aliases (`mc.mushy`, `bridge.mushy`) co-resolve to elder-plops — the "MagicDNS for service URLs" half.
- Each WG peer config gets `DNS = 10.66.0.1` in `[Interface]`. WireGuard's `wg-quick` writes that to `resolv.conf` at peer-up; iOS/Android/Linux honor it natively.
- A `domain mushy` search-domain so `ssh fc1` works (not just `ssh fc1.mushy`).
- One source of truth: a `peers.yaml` checked into repo, generates the hosts file (script). Same file that future Phase 999.X (peer mgmt UI? wg-easy?) consumes.

## Acceptance When Shipped

1. From any wg-hub peer: `ping fc1.mushy` → 10.66.0.11; `dig +short fc1.mushy @10.66.0.1` returns the IP
2. `ssh fc1` (with search-domain) works from gumbald + elder-plops + a fresh peer install
3. Browser: `http://mc.mushy/` opens OpenMCT
4. Renumbering a peer requires editing one yaml + reloading dnsmasq, not sed across the codebase
5. dnsmasq on VPS doesn't answer to public DNS queries (UFW + bind config verifies)

## When to Surface

**Trigger:** v1.7 milestone planning. Operator-QoL items get a pass, and SEED-008 surfaces alongside whatever else (likely 999.47 gumbald peer makes it acutely annoying around then). Could surface earlier if:

- Any peer needs to be renumbered (forces a sed across the codebase that's exactly the pain this fixes)
- A 7th+ peer onboarding makes IP memorization actively bad
- A farmer asks "can you give me a URL instead of `http://10.66.0.12:8080/`?"

## Scope Estimate

**Small** — ~half a day. dnsmasq compose-service, peers.yaml + render script, one-line edit to each peer's WG config, smoke test from each platform (Linux, iOS, Android).

## Composition

- Phase 32 (the WG hub this rides on)
- 999.47 (gumbald peer — fixing this before gumbald lands means gumbald gets named-access from day 1)
- Future peer-mgmt phase (peers.yaml is the obvious source of truth)
- Phase 34 monitor URLs (could be re-pointed at `mc.mushy` / `bridge.mushy` for self-documentation)

## Why NOT Sooner

- Doesn't unblock anything — it's pure quality-of-life, not load-bearing
- Adds a dependency surface (DNS lookups now part of every WG-internal request) that should land when the milestone has bandwidth to validate it carefully, not as a side-quest during a feature ship
- The VPS already runs hub + heartbeat receiver + uptime-kuma; piling DNS onto the same box needs deliberate consideration of "what if dnsmasq goes sideways and now everything WG-internal can't resolve" (mitigation: per-peer fallback DNS as second resolver)
