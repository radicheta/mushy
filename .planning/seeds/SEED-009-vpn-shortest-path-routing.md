---
id: SEED-009
status: dormant
planted: 2026-05-11
planted_during: v1.6 (post-Phase 35 — outage+recovery stack shipped)
trigger_when: any phase touching WireGuard routing, farmer-device VPN config, or "farmer onboarding to mushy" — also surfaces if VPS bandwidth/cost becomes a constraint, or if farmer reports MC latency
scope: Medium
---

# SEED-009: VPN tunnel should be fallback, not primary — shortest-path routing for on-site farmers

## Why This Matters

Phase 32 shipped the Hetzner VPS WireGuard hub (`wg-hub`, `10.66.0.0/24`) so
that off-LAN devices — farmer phones on cellular, fc1 when it moves back to
farm 4G, future remote operators — can reach Mission Control. That part is
working: 3 farmer iOS devices, fc1, elder-plops, and operator gear all peer
through Nuremberg.

But the current config sends **every peer↔peer packet through the VPS
unconditionally**, including the local case where:
- Farmer is on-site at the farm or the lab
- Farmer's phone is on the SAME wifi as elder-plops / fc1
- Their physically-adjacent path is sub-millisecond LAN

Instead we route them ~6,000 km to Nuremberg and back. Cost:
- **Latency:** ~250ms RTT vs <5ms LAN — MC dashboard interactions feel
  noticeably laggy through the hub vs direct
- **Bandwidth:** every farmer dashboard refresh, every camera frame burns
  Hetzner CX22 traffic budget that could be free LAN bytes
- **Resilience:** when VPS is unreachable (CX22 reboot, Nuremberg routing
  flap, our own systemd misconfig), farmer-on-LAN loses access to MC even
  though everything they need is physically next to them
- **Cost optics:** if we scale to N farmers and the camera bumps to higher
  res (memory: `project_phase999_21_timelapse_resolution_bump`), VPS bw
  burn grows linearly with users for no functional benefit

Ideal behavior: turn on WireGuard once, the device transparently uses the
shortest viable path. On-site → direct LAN; off-site → hub. No farmer-side
toggle, no per-location config, no thought.

## When to Surface

**Trigger:** any phase touching WireGuard routing, farmer device VPN config,
or "farmer onboarding to mushy" — also surfaces if VPS bandwidth/cost becomes
a constraint, or if farmer reports MC latency through the hub.

This seed should be presented during `/gsd-new-milestone` when the milestone
scope matches any of these conditions:
- Adding more farmer/operator devices to wg-hub (composes with 999.47 / 999.48)
- Restructuring fc1 connectivity (composes with 999.46 multi-iface — same family)
- Performance/latency phases for MC or camera streaming
- Cost-optimization or bandwidth-budget phases for the VPS
- "Multi-site" or "second chamber" phases — naturally adds the
  is-the-other-end-on-my-LAN question

## Scope Estimate

**Medium** — not a one-liner, but bounded.

The technical mechanisms exist and are well-trodden:
1. **Endpoint-based selection (simplest):** keep each peer's hub-side
   `AllowedIPs` as 10.66.0.0/24, but add a SECOND peer entry on each device
   with a LAN endpoint + matching AllowedIPs covering the same VPN IP. WG
   prefers the more-specific match; if the LAN peer responds, traffic goes
   direct. Requires every farmer device to have BOTH peer entries and a
   reliable way to detect "am I on the LAN" (usually mDNS or DHCP lease
   matching a known SSID).
2. **Roaming endpoint (cleaner but trickier):** the peer's Endpoint field
   is updated by WG itself based on observed return-traffic. If we get the
   initial handshake to go LAN, WG stays LAN. Needs each side to publish
   its current LAN IP somewhere the other can read (mDNS / dnsmasq on the
   VPS — composes with SEED-008).
3. **Split-DNS + name-based routing:** resolve `mc.mushy.internal` to the
   LAN IP when on-site, hub IP when remote. Simpler conceptually but
   requires DNS infra (composes with SEED-008 dnsmasq idea).

**Risk:** misconfigured routes can create asymmetric paths (request via LAN,
response via hub or vice versa) which break TCP. Need careful AllowedIPs
specificity, possibly per-host preset configs delivered via the Phase 32
RUNBOOK recipe rather than hand-edited.

Plan-phase work, not a sprint task. Budget ~2-3 phases:
1. spike to pick mechanism (a/b/c) — likely Small
2. implement + multi-device test matrix (lab + farm + roaming) — Medium
3. operator + farmer rollout (regenerate configs, document, gradually
   migrate existing peers) — Small

## Breadcrumbs

Related code and decisions in the current codebase:

- `vps/wg-hub/` — wg0 server config on Hetzner CX22 (Phase 32)
- `.planning/phases/32-vps-multi-purpose-hub/32-RUNBOOK.md` — current
  add-peer recipe; would need a parallel "add-peer-with-LAN-fallback"
  section
- `scripts/pi-deploy/cyclonedds-tailscale.xml` — historical fc1 DDS binding,
  pre-Phase 32 (worth comparing how Tailscale solved this with magic DNS)
- `.planning/seeds/SEED-008-vpn-name-resolution.md` — composes directly;
  split-horizon DNS is the natural layer for mechanism (c) above
- Memory `project_fc1_link_architecture_options.md` — VPS hub vs LAN
  bridge tradeoff history
- Memory `project_fc1_cgnat_confirmed.md` — fc1 specifically NEEDS the
  hub when on 4G (CGNAT); this seed is about NOT punishing the LAN case
  for fc1's remote case
- Memory `feedback_stopping_tailscaled_kills_pid.md` — caution about
  changing fc1's network transport while DDS is active
- ROADMAP 999.46 (CycloneDDS multi-iface) — same family of "DDS over a
  non-trivial network topology"

## Notes

The Tailscale crowd handles this transparently via DERP relay only as
fallback + local subnet detection. We're on plain WireGuard so we don't
get that for free — but the underlying mechanism is just "WG prefers
more-specific AllowedIPs and roams endpoints on observed traffic."

User framing 2026-05-11: "ideally transparently — just turn on wireguard
and the thing magically routes through the shortest path." That's the
acceptance criteria in plain language.

When this seed surfaces, also pull SEED-008 (VPN name resolution) and
ROADMAP 999.46 (CycloneDDS multi-iface) into the same plan-phase scope —
all three are aspects of "make the wg-hub topology actually feel like one
unified network instead of a tunnel-to-Nuremberg."
