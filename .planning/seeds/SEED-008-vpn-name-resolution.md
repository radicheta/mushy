---
id: SEED-008
status: dormant
planted: 2026-05-11
planted_during: v1.6 (Phase 33/34 ship night)
trigger_when: v1.7 milestone planning — operator-quality-of-life pass
scope: Medium
---

# SEED-008: VPN name resolution — `fc1.mushy.mossrock.space` instead of `10.66.0.11`

> **Design revised 2026-05-11** during plant-seed conversation. Original draft used a private `.mushy` fake-TLD; revised to **split-horizon FQDN under `mushy.mossrock.space`** for real-cert-friendly browser/email/identity composition. See "Locked Design (revised)" below.

## Why This Matters

We added wg-hub in Phase 32 (10.66.0.0/24) and now have 5+ peers — VPS (10.66.0.1), elder-plops (10.66.0.12), fc1 (10.66.0.11), three farmer phones (.20–.22), with gumbald (.10) and a 4th iOS device (.23) queued. Today everyone (operator + farmers + tooling + scripts + uptime-kuma config + the heartbeat receiver's BRIDGE_URL env + the Phase 34 monitor URLs) hardcodes IPs. Any peer renumbering, any new service, or any onboarding of a 6th device starts costing real friction:

- Operator memorizing `.11` vs `.12` vs `.13` and which is which
- Farmer-facing URLs are bare IPs (`http://10.66.0.12:8080/` for Mission Control) — uglier than `mc.mushy/` and harder to remember
- Scripts (sender shims, install scripts, monitor configs) hardcode IPs — re-IP'ing requires sed across the codebase
- New services (timelapse mirror, future status pages, dashboards) inherit the IP-hardcoding pattern

Tailscale solves this with MagicDNS. We deliberately picked WireGuard over Tailscale (Phase 32 DECISION-2 — full self-hosted control, no exit node, no DERP relay surprises). We pay for that choice with no built-in name resolution. SEED-008 is the explicit catch-up.

## Locked Design (revised 2026-05-11)

**Split-horizon FQDN under `mushy.mossrock.space`, served by an authoritative DNS on the VPS.**

Why FQDN over a fake `.mushy` private TLD:
- Real names → real **Let's Encrypt certs via DNS-01** for `*.mushy.mossrock.space` even on WG-only hosts (no browser warnings, no self-signed cert UX rot)
- `gumbald@mushy.mossrock.space` style email/identity addressing composes with anything mossrock.space ever does
- Browsers / SSH / mail clients just work without per-host `search` domain configuration
- Zero risk of fake-TLD collision (ICANN doesn't reserve `.mushy`, and `.farm` / `.box` are real new gTLDs)

Why split-horizon over public-IPs:
- Chamber control endpoints (fc1, bridge, openmct) should not advertise their existence to the public internet
- Public DNS knows nothing about `*.mushy.mossrock.space`; it only resolves on the WG-hub DNS
- Future public-facing names (e.g. an external uptime-kuma status page) get their own public A records on demand — hybrid is additive

Three options evaluated and discarded:
- Tailscale MagicDNS — would replace WireGuard, undoes Phase 32
- avahi/mDNS over WG with reflector — fragile, breaks for Apple peers
- Static `/etc/hosts` everywhere — doesn't scale, breaks for non-SSH protocols

**Implementation shape:**

1. **DNS hosting:** delegate the entire `mushy.mossrock.space` subdomain from HostGator to the VPS. One-time HostGator panel edit:
   ```
   mushy.mossrock.space.  IN NS  ns.mushy.mossrock.space.
   ns.mushy.mossrock.space.  IN A  178.105.84.13
   ```
   After that, HostGator never has to be touched again — VPS owns the subdomain. (Why not just publish A records on HostGator: HostGator's DNS API is poor for Let's Encrypt DNS-01 automation; delegation moves us to a controllable surface.)

2. **VPS authoritative DNS** (e.g. `nsd` or `knot-dns`, both tiny single-file binaries): listens on `0.0.0.0:53` for the public NS queries it'll get from the world (to delegate the subdomain successfully). Serves only `mushy.mossrock.space.` zone. UFW opens 53/tcp+udp for public. Returns NXDOMAIN for everything else.

3. **VPS resolver for WG peers** (dnsmasq, separate process or layered): listens on `10.66.0.1:53` (wg-hub interface only), serves the same `mushy.mossrock.space.` records to WG peers. Peers see private 10.66.0.x IPs; the public authoritative answers different (or nothing — see split-horizon below).

   **Split-horizon options to choose between at impl time:**
   - **(a) Stealth:** public NS returns NXDOMAIN for all `mushy.mossrock.space` records. Subdomain "exists" only for the DNS-01 challenge TXT records. Topology fully hidden.
   - **(b) Public stub:** public NS returns SOA + NS records but no A records (so `dig fc1.mushy.mossrock.space` gives nothing publicly). Same effective hiding; cleaner DNS protocol shape.
   - **(c) Public-private:** public NS returns A records pointing to 10.66.0.x. Topology becomes public knowledge but unreachable. Simplest TLS path.

4. **Records (zone source-of-truth lives in repo):**
   ```
   ; Hosts (private, served on wg-hub side only in stealth mode)
   vps.mushy.mossrock.space.        A  10.66.0.1
   hub.mushy.mossrock.space.        A  10.66.0.1
   gumbald.mushy.mossrock.space.    A  10.66.0.10
   fc1.mushy.mossrock.space.        A  10.66.0.11
   elder-plops.mushy.mossrock.space. A 10.66.0.12
   farmer1.mushy.mossrock.space.    A  10.66.0.20
   ...
   ; Service aliases (CNAME to host)
   mc.mushy.mossrock.space.         CNAME elder-plops.mushy.mossrock.space.
   bridge.mushy.mossrock.space.     CNAME elder-plops.mushy.mossrock.space.
   openmct.mushy.mossrock.space.    CNAME elder-plops.mushy.mossrock.space.
   monitor.mushy.mossrock.space.    CNAME vps.mushy.mossrock.space.
   ```

5. **Each WG peer config** gets `DNS = 10.66.0.1` in `[Interface]`. WireGuard `wg-quick` writes that to `resolv.conf` on peer-up. Plus a `search mushy.mossrock.space` so `ssh fc1` works (not just `ssh fc1.mushy.mossrock.space`).

6. **TLS:** `certbot --dns-rfc2136` against the VPS's own NSD (or whatever auth DNS we choose). Issues real certs for `*.mushy.mossrock.space` wildcard. Renewal cron on VPS. Bridge/openmct/uptime-kuma serve those certs going forward.

7. **Source of truth:** `vps/dns/zone.yaml` (or similar) checked into repo. Render script produces both the authoritative zone file and any dnsmasq overrides. Same file feeds future peer-mgmt phases.

## Acceptance When Shipped

1. From any wg-hub peer: `dig +short fc1.mushy.mossrock.space @10.66.0.1` returns 10.66.0.11; `ping fc1` works (via `search` domain)
2. From the public internet: `dig +short fc1.mushy.mossrock.space @8.8.8.8` returns NXDOMAIN (or empty — depending on stealth mode chosen at impl time)
3. `ssh fc1` works from any peer (search domain handles the suffix)
4. Browser: `https://mc.mushy.mossrock.space/` opens OpenMCT with **a real Let's Encrypt cert** (no warning)
5. Renumbering a peer requires editing one zone-source yaml + reloading the auth DNS + dnsmasq, not sed across the codebase
6. Public NS (`ns.mushy.mossrock.space`) properly responds to delegated queries from HostGator-side resolvers (so DNS-01 challenges resolve)

## When to Surface

**Trigger:** v1.7 milestone planning. Operator-QoL items get a pass, and SEED-008 surfaces alongside whatever else (likely 999.47 gumbald peer makes it acutely annoying around then). Could surface earlier if:

- Any peer needs to be renumbered (forces a sed across the codebase that's exactly the pain this fixes)
- A 7th+ peer onboarding makes IP memorization actively bad
- A farmer asks "can you give me a URL instead of `http://10.66.0.12:8080/`?"

## Scope Estimate

**Medium** — ~1-2 days. Bumped from Small after design revision: now includes (a) auth DNS server on VPS (nsd / knot — single binary but new operational surface), (b) HostGator subdomain delegation (one-time but irreversible-ish), (c) Let's Encrypt DNS-01 wildcard cert + auto-renew on VPS, (d) wiring real certs into bridge / openmct / uptime-kuma, (e) zone-source-of-truth yaml + render script, (f) per-peer WG `DNS=` + `search` config edits, (g) smoke from each platform (Linux, iOS, Android, browser, ssh, ros2 cli).

Worth doing as one phase, not split — partial shipment leaves operators in a worse spot than today.

## Composition

- Phase 32 (the WG hub this rides on)
- 999.47 (gumbald peer — fixing this before gumbald lands means gumbald gets named-access from day 1)
- Future peer-mgmt phase (peers.yaml is the obvious source of truth)
- Phase 34 monitor URLs (could be re-pointed at `mc.mushy` / `bridge.mushy` for self-documentation)

## Why NOT Sooner

- Doesn't unblock anything — it's pure quality-of-life, not load-bearing
- Adds a dependency surface (DNS lookups now part of every WG-internal request) that should land when the milestone has bandwidth to validate it carefully, not as a side-quest during a feature ship
- The VPS already runs hub + heartbeat receiver + uptime-kuma; piling DNS onto the same box needs deliberate consideration of "what if dnsmasq goes sideways and now everything WG-internal can't resolve" (mitigation: per-peer fallback DNS as second resolver)
