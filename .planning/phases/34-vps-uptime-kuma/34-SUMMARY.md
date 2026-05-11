# Phase 34 — VPS uptime-kuma outside-in monitoring — SUMMARY

**Status:** INFRA DEPLOYED 2026-05-11. **Operator UI setup pending** (admin user, monitor seed, ntfy notification channel — uptime-kuma owns its own credentials, not seedable headless).

## What shipped (infra side)

| Component | Location | State |
|-----------|----------|-------|
| Compose file | `vps/uptime-kuma/docker-compose.yml` (and on VPS at `/opt/uptime-kuma/docker-compose.yml`) | Deployed |
| Idempotent installer | `vps/uptime-kuma/install.sh` | Run; safe to re-run |
| Docker engine + compose plugin on VPS | apt via official Docker repo | Installed (was missing — Phase 32 didn't include docker) |
| uptime-kuma container | `louislam/uptime-kuma:1` named `uptime-kuma` | Running, health: starting → healthy |
| Listening | `127.0.0.1:3001` + `10.66.0.1:3001` (wg-hub only) | Verified |
| UFW | `allow in on wg-hub to any port 3001 proto tcp` | Added |
| State volume | `uptime-kuma_uptime-kuma-data` (persistent across recreates) | Created |

Reachability verified: `curl http://10.66.0.1:3001/` from elder-plops returns HTTP 302 (redirect to login — expected).

## Operator setup (NOT done by Claude)

uptime-kuma has no headless way to seed admin credentials or monitors. From any wg-hub peer (your laptop if it joins as a peer per 999.47, or the farmer Android, or fc1):

1. Open `http://10.66.0.1:3001/`
2. **Set admin user + password** on first-visit screen
3. **Add notification channel** (Settings → Notifications → Add)
   - Type: ntfy
   - ntfy server URL: `https://ntfy.sh`
   - ntfy topic: `mushy-alerts-7f3a9c2b8e` (same topic as 999.43.1; one app, both alert sources)
   - Priority: 4 (high)
   - Test → confirm push lands
4. **Seed monitors** per 34-CONTEXT.md table (5 monitors):
   - fc1 wg-hub ping → 10.66.0.11
   - elder-plops wg-hub ping → 10.66.0.12
   - Mission Control (openmct) → http://10.66.0.12:8080/
   - Bridge health (keyword `"status":"ok"`) → http://10.66.0.12:8081/health
   - (Optional) Bridge heartbeat-alert reachability
   - For each monitor: assign the ntfy notification channel

5. **Acceptance test:** stop bridge briefly (`docker compose stop bridge` on elder-plops, wait 1-2 min, then `start`). Expect ntfy push from uptime-kuma within 2 polling intervals (default 60s).

## Why operator-setup-only

This is the same posture as the alerter signal-cli registration: critical-path notification credentials are operator-owned by design. Reasonable trade — saves a dev-side secret distribution mechanism, costs ~5 minutes of the operator's time once.

## What's NOT in scope tonight

- Public status page (uptime-kuma supports it; deferred until farmer onboarding asks for "is it up?" without WG)
- Automated monitor-seeding via uptime-kuma's API (manual is faster for 5 monitors)
- Cross-region redundancy
- Custom theme

## Composition with Phase 33 / 999.43.1

| Failure mode | Phase 33 (heartbeat) | Phase 34 (uptime-kuma) |
|--------------|----------------------|------------------------|
| fc1 process dies | ✓ catches (sender stops) | ✓ catches (ping fails) |
| fc1 host loses network | ✓ catches (sender unreachable) | ✓ catches (ping fails) |
| elder-plops up but bridge down | ✗ misses (host heartbeat still fires) | ✓ catches (bridge `/health` keyword fail) |
| elder-plops up but invisible from outside | ✗ misses | ✓ catches (the 2026-05-07 failure mode this phase exists for) |
| Home network up, all services fine, but wifi router NAT broken | ✗ misses | ✓ catches |
| VPS itself down | ✗ misses (receiver dead) | ✗ misses (observer dead) — needs external monitoring |

Both signals together = real outage. One signal = diagnostic info about the failure mode.

## Files

```
ADDED:
  vps/uptime-kuma/docker-compose.yml                            single-container, persistent volume, wg-hub-only bind
  vps/uptime-kuma/install.sh                                    idempotent docker install + compose up
  .planning/phases/34-vps-uptime-kuma/34-CONTEXT.md             decisions D-01..D-08, monitor seed table
  .planning/phases/34-vps-uptime-kuma/34-SUMMARY.md             this file

DEPLOYED (NOT in repo):
  VPS:
    docker engine + compose plugin (via official Docker apt repo)
    /opt/uptime-kuma/docker-compose.yml
    docker volume uptime-kuma_uptime-kuma-data
    UFW: allow in on wg-hub to any port 3001 proto tcp
```
