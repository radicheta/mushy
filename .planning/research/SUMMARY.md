# Research Summary: v1.3 Alerts & Unified Farmer Dashboard

**Project:** Mushroom Farm FC-1 — v1.3
**Domain:** IoT alerting bot + farm-ops unified HUD
**Researched:** 2026-04-18
**Confidence:** HIGH

---

## Executive Summary

v1.3 adds two features to a running ROS2 + OpenMCT + TimescaleDB + FarmOS system: proactive Signal alerts when something is wrong, and a unified farmer dashboard the grower can glance at from their phone in the chamber. All four researchers converged on the same architecture without coordination: both features live inside the existing `mission_control_bridge`, served from elder-plops, with zero new ROS2 nodes and zero new npm packages. The alert engine goes in `alerter.js` (a module imported by `index.js`), the farmer dashboard goes in `bridge/static/farmer.html` served via `express.static`, FarmOS data flows through a bridge proxy route (`GET /farmos/summary`), and Signal delivery goes through `bbernhard/signal-cli-rest-api` running as a new Docker service on elder-plops.

The recommended approach is additive and conservative: hook into data the bridge already has (`humidifierLastMsgTs`, `lastSensorHealthBroadcast`, `rosReady`), send via REST to signal-cli-rest-api on localhost, and serve a vanilla-JS HTML page with no build step. The only genuinely new piece of infrastructure is the `bbernhard/signal-cli-rest-api` Docker container and its one-time linked-device registration. All alert signals are already tracked by the bridge; no new ROS subscriptions are needed.

The dominant risks are behavioral rather than architectural: alert flap-storms if debounce is skipped, alert fatigue if recovery messages are omitted, a silent dead alerter if the daily heartbeat is deferred, and a UX regression if the `sensor_health` replay-on-connect pattern from Phase 16.1 is not carried into the new farmer dashboard. These risks have known mitigations — the project's own v1.0–v1.2.1 history supplies most of the lessons.

---

## Key Findings

### Recommended Stack (v1.3 additions only)

All four researchers independently recommended the same stack. There are no unresolved technology debates.

**New service:**
- `bbernhard/signal-cli-rest-api:latest-stable` — Signal delivery via REST; Docker service on elder-plops; `MODE=json-rpc-native` avoids JVM-per-request startup; linked-device registration via QR code (one-time manual step); `POST /v2/send` with native `fetch` — no new npm package needed.

**Bridge additions (no new containers):**
- `alerter.js` — alert state machine, dedupe, Signal invocation; imported by `index.js`
- `bridge/static/farmer.html` + JS — vanilla HTML/CSS/JS; served via `express.static`; no build step, no framework
- `GET /farmos/summary` route — bridge-proxies FarmOS server-to-server using existing session-cookie auth from Phase 13 `.env` vars

**No new npm packages.** Node.js 18+ native `fetch` handles the HTTP call to signal-cli-rest-api. `Chart.js` via CDN `<script>` tag is the only external dependency on the dashboard page, and it is optional (SVG sparklines are sufficient).

**New environment variables for the bridge service** (9 total; `FARMOS_*` already exist in `.env`, just need adding to the bridge's `environment:` block):
- `SIGNAL_API_URL`, `SIGNAL_SENDER`, `SIGNAL_RECIPIENT`
- `ALERT_RH_TARGET`, `ALERT_RH_BAND`, `ALERT_COOLDOWN_MIN`, `ALERT_HUMIDIFIER_STUCK_MIN`
- `FARMOS_URL`, `FARMOS_USERNAME`, `FARMOS_PASSWORD` (promote from farmos-agent only to bridge too)

---

### Expected Features

**Must ship (table stakes):**

Alerts:
- signal-cli REST API container + send-only wrapper
- Four alert types: Pi offline, sensor ERROR, RH out-of-band, humidifier stuck
- Deduplication + throttle + RECOVERY messages (every PROBLEM fires exactly one RECOVERY)
- WARN/CRITICAL severity tiers with different repeat cadences
- Alert state persistence across restarts (in-memory for MVP; Timescale `alerts` table if restart-spam proves noisy)
- Daily heartbeat message ("FC-1 watchdog alive") — mandatory, not deferred
- Grace-period suppression: no alerts during fc_controller 20s sensor warm-up

Dashboard:
- Current readings with sensor provenance ("81.3% RH (SCD41, ±6%)")
- Service health strip (reuse Phase 16 signals via `/health`)
- Last camera frame (60s poll to `/camera/latest.jpg`)
- FarmOS latest observations (3 entries via `/farmos/summary`)
- Mobile-first layout (single-column, 44px touch targets, min 16px font)
- Local timezone (browser `Intl.DateTimeFormat`; UTC on hover only)
- Staleness display: server-computed `_age_sec` fields, stale banner at `2 x publish_interval`
- `sensor_health` replay-on-connect (WS client must handle the bridge's replayed state)

**Should ship (high-value, moderate complexity):**
- 6h RH + CO2 sparklines — farmer's #1 stated wish; SVG or Chart.js (M)
- Quiet hours for WARN alerts — one `datetime` check (S)
- "What's unusual" anomaly callout: values >2sigma from 24h mean (M)
- Embed FarmOS observation list inline (S-M)

**Defer to v1.4:**
- Snooze / acknowledgement (requires bidirectional Signal bot)
- Chart snapshot attachment (matplotlib overhead)
- Annotated event timeline (requires fc_controller to emit structured events)
- Parameter-change UI (its own milestone)
- Live MJPEG stream (4G cost)
- Multi-chamber switching

---

### Architecture Approach

The bridge is the right host for both features because it is the single point that holds all state needed for alerting and is always running on elder-plops. A ROS2 node on fc1 cannot detect that fc1 is offline. A dedicated alerts container would need to replicate the same timestamp-tracking the bridge already does in `humidifierLastMsgTs` and `rosReady`. The farmer dashboard served from the bridge has same-origin access to the bridge WS and REST endpoints with no CORS friction.

**Major components:**
1. `alerter.js` (new, inside bridge) — alert conditions, cooldown state, Signal REST call, daily heartbeat timer
2. `bridge/static/farmer.html` (new, served by bridge) — vanilla JS HUD consuming WS + REST; no auth, no build step
3. `GET /farmos/summary` (new bridge route) — server-side FarmOS proxy, 60s cache, returns empty array on FarmOS downtime
4. `bbernhard/signal-cli-rest-api` (new Docker service) — Signal delivery, port 8083 bound to `127.0.0.1` only
5. `index.js` modifications — wire alerter into existing subscription callbacks; Pi-offline `setInterval` (60s); `express.static` for `/farmer`; `/farmos/summary` route

**Concrete new files:**
```
src/mission-control/bridge/src/alerter.js
src/mission-control/bridge/src/farmer/index.html
```

**Concrete modified files:**
```
src/mission-control/bridge/src/index.js
docker-compose.yml  (bridge environment block + signal service)
.env                (new SIGNAL_* + ALERT_* vars)
```

---

### Critical Pitfalls

All four researchers flagged the same top risks. Most are drawn from v1.0–v1.2.1 production history.

1. **Flap-storm on sensor bounce** — RH jitter around the ±1% band edge generates rapid alert/recover cycles. Require N consecutive (>=5) out-of-band readings before firing; suppress RECOVERY if alert is <60s old. Must be tested before enabling real thresholds on fc1.

2. **Missing RECOVERY messages** — Farmer wakes at 07:00 to a 02:00 alert with no recovery confirmation. Never ship PROBLEM without RECOVERY. Test both paths explicitly.

3. **Alert bot dies silently** — The worst failure mode: alerter crashes, nothing monitors it, farmer gets no alerts for weeks. The daily heartbeat prevents this. It must ship in the same phase as the alert bot. `restart: unless-stopped` is required.

4. **Stale WS looks live** — A reconnect between sensor publishes leaves stale values displayed. Show server-computed `_age_sec` on every value; show stale banner at `>2x publish_interval`. Lesson from `feedback_gap_over_noise.md`.

5. **sensor_health replay not carried forward** — Phase 16.1 added a bridge-side replay shim. The farmer dashboard WS client must consume this message or it regresses to grey-lights-on-cold-open. Hard-reload test is the verification gate.

6. **Signal linked-device expiry** — Signal expires linked devices after 45 days of inactivity. Daily heartbeat prevents expiry. Document re-registration procedure in OPERATIONS.md before Phase 17 closes.

7. **Pi-offline alert on the Pi** — If alert logic runs on fc1, it cannot fire when fc1 is down. This is an architecture decision; wrong placement requires a full rewrite. Alert engine must live on elder-plops.

---

## Implications for Roadmap

All four researchers proposed the same 4-phase structure. Phases 17 and 18 are fully parallelizable; Phase 19 depends on Phase 18 being live; Phase 20 is tuning and carryover cleanup.

### Phase 17: Alert Engine + Signal Integration

**Rationale:** Alerts are higher-value than the dashboard and fully independent. Shipping alerts first means the farmer gets protection during the dashboard build period. The signal-cli-rest-api QR registration (pre-phase manual step, ~1-2 hours) must be done before coding begins.

**Delivers:** Signal messages on all four conditions. RECOVERY messages. Daily heartbeat. WARN/CRITICAL tiers with cooldowns. Grace-period suppression during fc_controller warmup.

**Avoids:** Shipping without end-to-end delivery test on the real Signal account (human-attestation gate, not CI gate). Shipping without the heartbeat. Hardcoded thresholds (env vars from day one).

**No deeper research needed.** Architecture settled; STACK.md has the exact compose snippet.

### Phase 18: Farmer Dashboard HUD (core, no FarmOS section)

**Rationale:** Dashboard depends only on bridge serving static files (trivial Express addition). Parallelizable with Phase 17. Build without FarmOS section to avoid blocking on FarmOS admin carryover.

**Delivers:** `http://elder-plops-ip:8081/farmer`. Live readings with sensor provenance. Health strip. Camera snapshot. Staleness banners. Mobile layout. Local timezone. `sensor_health` replay on connect.

**Avoids:** Any frontend framework or build step. Starting without verifying CORS from the farmer's phone (Tailscale IP). Re-implementing health logic instead of consuming bridge `/health`.

**Pre-condition check:** Verify WS connection from farmer dashboard origin before building any UI. Audit bridge replay coverage (humidifier state may need `/health` poll on page load for initial state).

### Phase 19: FarmOS Proxy + Dashboard FarmOS Section

**Rationale:** Adding FarmOS data after the base dashboard is live means Phase 18 ships without waiting on FarmOS admin carryover. Phase 19 completes the v1.2 FarmOS carryover (FC-1 asset location, permissions) simultaneously.

**Delivers:** `GET /farmos/summary` bridge route with cache and graceful fallback. FarmOS observations section on the farmer dashboard. FarmOS admin carryover closed.

**Avoids:** Blocking dashboard render on FarmOS response. Using iframes (cookie collision). Letting FarmOS 401 redirect the whole page. FarmOS downtime must return empty array, not an error.

### Phase 20: Hardware UAT + Polish

**Rationale:** Phase 12 hardware UAT (camera on real hardware) has been carried since v1.2. After Phase 17 has been live for a week, alert cooldown values need real-world tuning. Dashboard UX feedback from farmer lands here too.

**Delivers:** Phase 12 UAT complete. Alert thresholds tuned. Dashboard polish from farmer feedback. Timescale `alerts` table added if in-memory cooldown proved noisy.

---

### Phase Ordering Rationale

- Phase 17 before Phase 18: alerts deliver value immediately and are fully independent
- Phase 18 without FarmOS section: avoids blocking on FarmOS admin carryover; base dashboard ships faster
- Phase 19 after Phase 18: extending an existing page is faster than building and extending in one phase
- Phases 17 and 18 are parallelizable: `alerter.js` and `farmer/index.html` share no code; both ship in a single `docker compose up -d --build bridge`

### Research Flags

**No phases need `/gsd-research-phase`.** Architecture is settled, file paths are specified, env vars are enumerated. All work from live codebase.

Pre-condition checks (not research, just go/no-go at phase start):
- Phase 17: signal-cli-rest-api QR registration complete on elder-plops before coding begins
- Phase 18: WS CORS from Tailscale phone IP verified; bridge replay coverage audited
- Phase 19: FarmOS admin carryover (FC-1 asset, permissions) addressed or explicitly proxied around

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | signal-cli-rest-api verified from live README + Docker Hub; bridge additions drawn from live `index.js`; no speculation |
| Features | HIGH | Feature list from PROJECT.md scope + farmer field notes (first-person, 2026-04-11); anti-features explicit |
| Architecture | HIGH | Unanimous across all 4 researchers; based on reading live code; file paths and route names are concrete |
| Pitfalls | HIGH | Top pitfalls drawn from v1.0–v1.2.1 production retrospectives and FARMER-APP-NOTES; not hypothetical |

**Overall confidence: HIGH.**

### Gaps to Address

- **Signal linked-device vs dedicated SIM** — Decide before Phase 17 begins. Linked-device is lower friction but subject to 45-day expiry (daily heartbeat mitigates). Recommended: start with linked-device; document re-registration procedure before Phase 17 closes.

- **CORS for farmer's phone (Tailscale IP)** — Dashboard will be accessed from the farmer's phone on Tailscale. If the phone's IP is not in `CORS_ORIGIN`, WS connections fail silently. Resolve at Phase 18 start by testing from the actual device.

- **Humidifier replay parity** — `sensor_health` got a replay shim (Phase 16.1); humidifier state still relies on ROS TRANSIENT_LOCAL replay. Mitigation: poll `/health` once on page load for initial humidifier state, then switch to WS. Budget 30 minutes in Phase 18.

- **Alert threshold initial values** — `ALERT_RH_TARGET=95`, `ALERT_RH_BAND=2` are starting values from the v1.2.1 empirical operating band. Real-world tuning happens in Phase 20 after one week of live behavior. Do not over-optimize in Phase 17.

---

## Sources

### Primary (HIGH confidence)
- `src/mission-control/bridge/src/index.js` — live code; bridge subscriptions, state vars, health endpoint
- `src/farmos-agent/farmos_agent/farmos_agent_node.py` — FarmOS auth pattern
- `.planning/PROJECT.md` — v1.3 feature scope, deferrals
- `.planning/phases/999.11-farmer-app/FARMER-APP-NOTES-2026-04-11.md` — farmer field notes (first-person)
- `.planning/milestones/v1.2-phases/13-farmos-daily-report/13-RESEARCH.md` — FarmOS session-cookie auth
- v1.2.1 RETROSPECTIVE — cold-open lesson, replay shim origin, humidifier parity gap
- Drupal CORS documentation (official) — wildcard + credential restriction

### Secondary (MEDIUM confidence)
- `bbernhard/signal-cli-rest-api` README + Docker Hub — linked-device flow, `/v2/send`, MODE options; no versioned releases
- Signal support docs — linked-device 45-day inactivity expiry
- signal-cli GitHub issues #1911, #1603, #1823 — rate limiting behavior (HTTP 413, CAPTCHA challenge)

---

*Research completed: 2026-04-18*
*Ready for roadmap: yes*
