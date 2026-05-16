# Phase 34 — VPS uptime-kuma outside-in monitoring — CONTEXT

**Status:** SHIPPED 2026-05-11 (continued from Phase 33 same session).
**Source:** ROADMAP backlog 999.44 (filed 2026-05-10) + DECISION-6 workload #2.

## Why this exists

Phase 33 ships Tier 1 alerts: VPS notices when monitored hosts go *self-silent* (heartbeat stops). But on 2026-05-07 elder-plops was reachable from the LAN while the world couldn't see it — the heartbeat would have kept firing because elder-plops itself was up. That failure mode needs an *outside-in* check.

uptime-kuma is the standard self-hosted Pingdom-alike. Single Docker container, web UI, polls HTTP/TCP/ping/etc., alerts on transitions. Composes cleanly with Phase 33 (different signal: source-self-reported vs externally-observed).

## Architecture

**One container** on the VPS (`vps/uptime-kuma/docker-compose.yml`). Persistent state in named volume. Web UI on port 3001 bound to `127.0.0.1:3001` and `10.66.0.1:3001` (wg-hub) — NOT public-facing. UFW continues to deny port 3001 from public; only wg-hub peers reach the dashboard.

Initial admin setup is done in-browser on first visit (uptime-kuma has no headless seed for credentials — operator-owned by design).

## Decisions (locked)

| ID | Decision | Source |
|----|----------|--------|
| D-01 | Single container, official image `louislam/uptime-kuma:1` | Standard install; v1 line is stable, v2 is a major rewrite still maturing |
| D-02 | Bind UI to `127.0.0.1:3001` + `10.66.0.1:3001`; NOT public | Defense in depth — operator dashboard, not public status page (yet) |
| D-03 | UFW rule: `allow in on wg-hub to any port 3001 proto tcp` | Mirrors Phase 33's wg-hub-only ingress posture |
| D-04 | Persistent state in named volume `uptime-kuma-data` | Standard; survives container recreation |
| D-05 | Initial monitor seed (post-deploy, in-UI): | See "Monitor seed list" below — starts minimal, expands as needed |
| D-06 | Notification channel: ntfy.sh to the same topic as Phase 999.43.1 | Reuse the operator's already-installed ntfy app + subscribed topic. One alert app, not two. |
| D-07 | NOT in scope tonight: public status page; SSO; multi-tenant; per-user notification fan-out | Operator-only dashboard for now |
| D-08 | Docker installed via official Docker apt repo (not snap, not Debian's docker.io package) | Phase 32 didn't install docker; Phase 34 is the first VPS-side container deploy. Standard install. |

## Monitor seed list (configure in UI after first launch)

| Name | Type | Target | Why |
|------|------|--------|-----|
| fc1 wg-hub ping | ping | `10.66.0.11` | LAN-side liveness via WG hub — composes with Phase 33 fc1 heartbeat |
| elder-plops wg-hub ping | ping | `10.66.0.12` | Same as above for elder-plops |
| Mission Control (openmct) | http | `http://10.66.0.12:8080/` | What farmers actually see; HTTP 200 expected |
| Bridge health | http (keyword) | `http://10.66.0.12:8081/health` | Expect keyword `"status":"ok"` in response — catches DB-down + ROS-down even if HTTP returns 200 |
| Bridge heartbeat-alert receiver | http (POST or keyword) | `http://10.66.0.12:8081/heartbeat-alert` | (Optional) — proves the Phase 33 dispatch endpoint is reachable from VPS. Skip if it adds noise — Phase 33 already covers fc1/elder-plops liveness from the inside. |

(Outside-in checks of the VPS itself are added by future Phase 999.X — outside-in is meaningless from the VPS itself since the VPS *is* the observer.)

## Acceptance

1. ✓ uptime-kuma container running on VPS as compose service
2. ✓ Web UI reachable at `http://10.66.0.1:3001/` from any wg-hub peer; NOT reachable from public internet
3. ✓ Admin user set on first visit by operator (in-UI; uptime-kuma owns its own credentials)
4. ✓ Initial monitors seeded per table above
5. ✓ ntfy.sh notification channel wired (same topic as 999.43.1)
6. ✓ Simulated outage (e.g. stop bridge container briefly) triggers ntfy push within 2 polling intervals

## What's NOT in scope tonight

- Public status page (uptime-kuma supports it; deferred until farmer onboarding asks for "is it up?" without WG)
- Multi-monitor escalation chains
- Custom dashboard themes
- API-driven monitor seeding (manual seed in UI is faster for ~5 monitors)

## Composition

- Phase 32 (rides the WG hub) — `10.66.0.1` is the VPS WG IP
- Phase 33 + 999.43.1 (different signal: heartbeat = self-reported; uptime-kuma = externally observed). When both fire, that's a real outage. When only one fires, that's diagnostic info about the failure mode.
- Memory `project_2026_05_07_fc1_reboot_unrecoverable` — the elder-plops-up-but-invisible failure mode this addresses.
