# Phase 34 — VPS uptime-kuma outside-in monitoring — SUMMARY

**Status:** SHIPPED 2026-05-11 — admin live + 4 monitors UP + ntfy alerts wired. Operator setup was driven via `uptime-kuma-api` socket.io client (not in-browser as initially planned — see "Operator setup" section below).

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

## Operator setup (DONE 2026-05-11 — driven via uptime-kuma-api lib, not in-browser)

The "no headless seed" assumption in the original CONTEXT was wrong: there IS a programmatic path via `uptime-kuma-api` (PyPI), which speaks the same socket.io protocol the web UI uses. Operator did first-time admin in browser (~30s), then provided the password; the rest of the seed (notification channel + 5 monitors + test fire) was driven via `/tmp/kuma_seed.py` running from elder-plops in a venv.

For future redeploys (e.g. fresh VPS), the seed script can do EVERYTHING including admin creation by calling `api.setup(user, pass)` — no browser needed. Capture the script under `vps/uptime-kuma/seed.py` if we ever need to re-provision.

Live state:
- Admin: `Mushy` (operator-owned password, not in repo)
- Notification: `mushy ntfy` → `https://ntfy.sh/mushy-alerts-7f3a9c2b8e` (same topic as 999.43.1 — one app, both alert sources). Test push delivered to operator phone 2026-05-11.
- 4 monitors live and UP (5th deleted, see follow-up note below):

| Monitor | Type | Latency observed | Status |
|---|---|---|---|
| fc1 ping (wg-hub) | Ping `10.66.0.11` | 248ms | UP |
| elder-plops ping (wg-hub) | Ping `10.66.0.12` | 248ms | UP |
| Mission Control (openmct) | HTTP `http://10.66.0.12:8080/` | 526ms | UP (200 OK) |
| Bridge health | HTTP+keyword `http://10.66.0.12:8081/health` keyword `"status":"ok"` | 499ms | UP (keyword found) |

All 4 monitors have notification → mushy ntfy enabled, retries=2, retry interval=20s, heartbeat interval=60s.

## Deferred / discovered during deploy

- **5th monitor (VPS heartbeat receiver self-check) DELETED.** uptime-kuma container is on Docker bridge network; the receiver listens on `127.0.0.1:9000` + `10.66.0.1:9000` (wg-hub). Container can't reach 10.66.0.1 from inside docker0 — UFW FORWARD doesn't route docker0 → wg-hub locally back to the host's own listeners on the wg-hub interface. Pings TO wg-hub peers (10.66.0.11/.12) DO work because the destination is on the other side of the tunnel; pings/HTTP TO 10.66.0.1 (the VPS's own wg-hub IP) don't because they need to loop back through the host's network namespace. The receiver is on the same VPS as uptime-kuma anyway — its liveness is implicit (if uptime-kuma is responding, the VPS is up). External outside-in monitoring of the VPS itself is a future Phase 999.X concern and would NOT live on this VPS.
- **If we ever want this self-check working:** add `extra_hosts: ["host.docker.internal:host-gateway"]` to uptime-kuma compose, and monitor `http://host.docker.internal:9000/health`. Untested; deferred until needed.

## Original 5-step in-browser recipe (preserved for posterity / fresh-VPS deploys without the seed script)

If you ever rebuild on a new VPS and don't want to use `uptime-kuma-api`, here's the manual recipe. From any wg-hub peer (your laptop if it joins as a peer per 999.47, or the farmer Android, or fc1):

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
