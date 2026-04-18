# Feature Landscape: v1.3 Alerts + Unified Farmer Dashboard

**Domain:** Operator alerting (Signal bot) + farm-ops unified dashboard
**Researched:** 2026-04-18
**Confidence:** HIGH (alerting patterns — well-established in ops tooling), MEDIUM (dashboard specifics — derived from farmer field notes + IoT dashboard norms)

---

## Existing signals available from v1.2.1 (no new plumbing needed unless noted)

| Signal | Source | What it tells you |
|--------|--------|-------------------|
| `/fc1/sensor_health` | fc_controller, DiagnosticStatus, TRANSIENT_LOCAL | OK / WARN (warmup) / ERROR |
| `/fc1/actuators/humidifier` | fc_controller, TRANSIENT_LOCAL | ON/OFF + timestamp |
| `/fc1/humidity`, `/fc1/temperature`, `/fc1/co2` | fc_sensors | Raw readings |
| `/health` REST (bridge) | bridge, 200/error | ros.connected, camera.last_frame_age_sec, camera.subscribed |
| TimescaleDB `telemetry` table | bridge inserts | All historical topic values |
| FarmOS API | farmos_agent (OAuth2 session-cookie) | Assets, observations for FC-1 (asset 28) |

---

## CATEGORY 1: OPERATOR ALERTING (Signal bot)

### Table Stakes

| Feature | Why Expected | Complexity | Depends On | Notes |
|---------|--------------|------------|------------|-------|
| Alert sending via signal-cli | Core value — nothing works without it | S | signal-cli daemon on elder-plops | `signal-cli` or `bbernhard/signal-cli-rest-api` Docker image; Python `requests` to HTTP REST gateway is simplest deploy path |
| Deduplication / throttle (no spam on flap) | Without this, one sensor flap at 03:00 wakes the operator 200 times. Alert fatigue destroys trust in the system fast. | S | In-process state dict keyed by alert_type | Track `{alert_type: first_fired_at, last_notified_at}`. Re-notify only after `repeat_interval` (e.g. 30 min for WARN, 5 min for CRITICAL). Do not re-fire while still active. |
| Recovery / "all clear" message | Operators need to know it resolved without polling. Without it they assume the worst is still happening. | S | Same state dict | Fire exactly once when alert transitions FIRING → RESOLVED. Message: "✓ [alert] resolved at HH:MM (was firing for N min)". |
| Four concrete alert types | These are the v1.3 scope per PROJECT.md | S-M each | Listed signals above | (1) Pi offline — `ros.connected` false for >2 min; (2) Sensor unhealthy — `sensor_health` level=ERROR for >30s; (3) RH out-of-band — humidity outside [setpoint ± tolerance + margin] for >5 min; (4) Humidifier stuck — actuator ON but RH not rising over 10 min, OR actuator state stale >2 min |
| Severity tiers (WARN vs CRITICAL) | Different urgency warrants different re-notify cadence. Sensor WARN during warmup should not page at 03:00. | S | Same state dict | WARN: re-notify every 60 min; no night suppression needed if quiet hours implemented. CRITICAL (Pi offline, sensor ERROR, humidifier stuck): re-notify every 15 min, no suppression. |
| Alert state persistence across restarts | Without it, a bot restart clears all firing alerts, then immediately re-fires them all, spamming the operator. | S | JSON file or SQLite on elder-plops | Write state dict to disk on every state change. Load on startup. One file is enough for single-chamber. |
| Test message / heartbeat | Operators need to confirm the bot is alive. "Is this thing on?" is the first question after a quiet period. | S | None | (a) Manual: `/test` command triggers a test message. (b) Optional daily heartbeat: "FC-1 watchdog alive, all green" once per day at morning report time (pairs with farmos_agent 06:00). |

**Complexity totals for table stakes: all S (simple), one M per alert type that requires threshold logic (RH out-of-band, humidifier stuck).**

### Differentiators

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Snooze per alert-type | Operator can suppress a known-flapping alert for N hours without silencing everything. Essential for sensor-swap maintenance windows. | M | Snooze expiry tracked in state dict | E.g., reply "snooze rh 2h" — bot parses inbound Signal message via signal-cli receive. Requires bidirectional bot, not just send-only. |
| Scheduled quiet hours | Farmer does not want WARN alerts at 03:00. CRITICAL still fires. | S | `datetime` check at notify time | Config: `quiet_hours: ["22:00", "07:00"]`. CRITICALs bypass. WARNs queue and deliver at quiet-hours end. |
| Chart snapshot attachment | "Here's the last hour of RH" removes the need to open Mission Control to understand context. Dramatically reduces time-to-understand. | M | Query TimescaleDB, render with matplotlib or quickchart.io | Fetch last 60 min of `fc1/humidity` from Timescale, generate PNG, attach to Signal message. Matplotlib is straightforward; quickchart.io avoids a dependency if HTTP is acceptable. |
| Runbook link per alert type | Operator on-call at 03:00 doesn't remember what "humidifier stuck" means. One URL to triage guide removes cognitive load. | S | Static config dict | E.g., `"humidifier_stuck": "https://wiki/mushy/runbooks/humidifier-stuck"`. Append URL to alert body. No actual wiki needed in v1.3 — can point to a README section. |
| Acknowledgement / silence until resolved | Operator confirms "I know, I'm on it" — suppresses re-fires until RESOLVED or explicit un-ack. | M | Inbound message parsing (bidirectional) | Requires bidirectional bot. Reply "ack" to last alert message threads the response. Lower priority than snooze since quiet hours + throttle cover most of the use case. |

### Anti-Features

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Per-sensor granular alerts (SHT30 vs SCD41 individual channels) | Adds 4+ alert types with no operator action available — farmer can't swap a sensor at 03:00 | Roll up into `sensor_health` ERROR, which already aggregates |
| Alert routing to multiple recipients with escalation chains | Single operator (Santi). Escalation is over-engineering for a one-person op. | One Signal number in config. Add second number in v1.4 when farm crew grows. |
| Webhook/email fallback | Signal is the chosen channel. Dual channels fragment ack state. | Signal only. If Signal is down, that's a separate incident. |
| Alert severity > 2 tiers in v1.3 | INFO tier creates noise, 3 tiers need routing logic. Only WARN/CRITICAL needed for the four alert types. | WARN and CRITICAL. Heartbeat is not an alert tier — it's a separate scheduled message. |

---

## CATEGORY 2: UNIFIED FARMER DASHBOARD

### Table Stakes

| Feature | Why Expected | Complexity | Depends On | Notes |
|---------|--------------|------------|------------|-------|
| Current readings with sensor provenance | Farmer field notes (2026-04-11): "we spent 40 min calibrating before realizing SHT30 was offline." SCD41 vs SHT30 accuracy difference (±6% vs ±1.5%) materially affects trust in numbers. | S | `/health` + `/fc1/sensor_health` | Show "81.3% RH (SCD41, ±6%)" not just "81.3%". Source and accuracy class inline with every number. This is the #1 lesson from the calibration session. |
| Service health at a glance | Farmer's first question on opening any view: "is the system up?" | S | Bridge `/health` endpoint (already exists) | Reuse the six-light strip from v1.2.1 Phase 16. No new plumbing. Render the same `ros.connected`, `camera.subscribed`, `sensor_health.level` signals in the page. |
| "What's unusual" anomaly callout | Farmer field notes: "the 28.4°C spike and the 63% RH crash should have been called out automatically." Without this, the operator reads a table looking for outliers — error-prone and slow. | M | TimescaleDB query (24h mean + stddev per topic) | Query last 24h mean/stddev per metric. Flag any reading in the current hour that is >2σ from 24h mean. Show as a banner: "RH unusual: 63.1% (24h avg 80.4%)". One callout section, max 3 items. |
| Production data from FarmOS (current grow log) | Grower role is primary user of this dashboard. They need to see what's in the chamber — current stage (pinning/fruiting/flush), last observation, days since inoculation. | M | FarmOS API via farmos_agent pattern (OAuth2 session-cookie, asset 28) | Fetch latest 3 observations for asset 28 from FarmOS `/api/log` endpoint. Display: stage, last note text, date. farmos_agent already proved the auth pattern works. |
| Mobile-legible layout | Farmer is often in the chamber 40m from main infra, on a phone, possibly in humidity. Farmer field notes: "big targets, high-contrast text, no multi-column layouts." | S | CSS only | Single-column layout below 600px. Font size min 16px. No hover-required interactions. High contrast. This is a CSS constraint, not a new component. |
| Time in local farm timezone | Farmer field notes explicit: "time in local farm tz, not UTC." UTC timestamps are disorienting when correlating with "what I did at 6pm." | S | `pytz` / `Intl.DateTimeFormat` with `Europe/Madrid` or config-driven tz | All timestamps localized. UTC shown on hover/tooltip only. |
| Last camera snapshot | Farmer wants visual confirmation of chamber state. Replaces need to open Mission Control separately. | S | Bridge `/camera/latest.jpg` endpoint (already exists from Phase 13) | Static `<img>` tag polling `/camera/latest.jpg` every 60s. No live MJPEG stream — conserves 4G. Show timestamp of frame. |

### Differentiators

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Sparkline / last-6h trend per reading | Context without opening Mission Control. "Is it trending toward the setpoint or away?" answered at a glance. | M | TimescaleDB query for last 6h, SVG sparkline (lightweight, no chart lib needed) | 6h window bucketed to 5-min averages. SVG path drawn inline. ~80 data points. No axes needed — just shape. This is the single highest-value dashboard differentiator per farmer field notes ("last-6h trend sparklines" listed as first specific wish). |
| Annotated event timeline | Farmer field notes Moment 2: "a story view" — restarts, DWELL-BLOCK events, threshold crossings as first-class events with telemetry underneath. | L | Requires fc_controller to emit structured events (currently only logs), or a log-scraping approach | This is L because it requires either (a) a new structured event topic from fc_controller, or (b) scraping journalctl for DWELL-BLOCK lines. The farmer wants this strongly but it's v1.4 scope in complexity. Flag for v1.4. |
| "Compare to yesterday's cycle" view | Calibration gold: did today's RH pattern match yesterday's? | L | TimescaleDB time-shift query, overlaid chart | Two-series chart with today and yesterday overlaid. Useful but requires chart rendering infrastructure. Defer to v1.4. |
| Embed FarmOS logs inline | Unified view — no tab-switching. Grower can read their own notes alongside sensor data. | S-M | FarmOS API (already connected via farmos_agent) | Fetch last 5 observations for asset 28. Render as a simple list below the production section. Moderate complexity; low risk. Candidate for v1.3 if time allows. |

### Anti-Features

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Full native mobile app (iOS/Android) | App store friction, push notification infra, binary deployment — weeks of overhead for a one-grower operation | Responsive webpage. Signal handles proactive push. PWA possible in v1.4 if offline matters. |
| Parameter-change UI (setpoint sliders, tolerance knobs) | Strong farmer desire (Moment 3), but it requires deploy pipeline integration, safety guardrails, and rollback — its own milestone. Building it half-baked is worse than not building it. | Defer to v1.4 explicitly. Farmer field notes captured the full spec. |
| Multi-chamber switching / FC-2 tab | No FC-2 hardware yet. Designing multi-chamber nav before the hardware exists will be wrong. | Single-chamber view. FC-2 tab added when FC-2 ships (v1.4+). |
| Live MJPEG camera stream in dashboard | 4G cost is real and unpredictable. Always-on stream can blow a monthly SIM allowance. | Static frame poll (60s). User-triggered "go live" is the right pattern — defer to v1.4. |
| OpenMCT replacement | Mission Control (OpenMCT) is the engineer/PM surface. Farmer dashboard supplements it, does not replace it. | Share the same bridge backend. Different URL/port. |
| Authentication / login | Single-operator farm, internal network. Auth adds friction with no security benefit at this scale. | No auth in v1.3. Revisit when farm crew grows. |

---

## CATEGORY 3: INFRASTRUCTURE (shared by both features)

### What needs to exist / be decided

| Item | For | Complexity | Notes |
|------|-----|------------|-------|
| signal-cli REST API container on elder-plops | Alerts | S | `bbernhard/signal-cli-rest-api` Docker image. One-time phone number registration. Add to docker-compose.yml. Alerts service calls `POST /v2/send`. |
| Alerts watchdog service (Python) | Alerts | S | New container or host process on elder-plops. Polls bridge `/health` + queries TimescaleDB. Owns alert state dict. Runs independent of farmos_agent but follows the same patterns (Python, psycopg2, requests). NOT a ROS2 node — no reason for ROS2 lifecycle overhead here since it doesn't touch the ROS graph. |
| Farmer dashboard hosting | Dashboard | S | Static HTML/JS/CSS served from a new nginx container on elder-plops, or added as a route in the bridge Express server. Bridge route is simpler (no new container), nginx gives cleaner separation. Recommend bridge route for v1.3 (`GET /farmer` serves index.html). |
| TimescaleDB queries for dashboard | Dashboard | S | Same `pg` pool used by bridge already. SQL for last-6h bucketed averages, 24h mean/stddev. Expose as `GET /api/summary` on bridge. farmos_agent pattern already proves query approach. |
| FarmOS API access from dashboard | Dashboard | S | Dashboard fetches from bridge proxy endpoint (`GET /api/farmos/observations`), not directly from FarmOS. Bridge already has FarmOS credentials pattern from Phase 13. Keeps auth server-side. |

---

## Feature Dependencies (ordering constraints)

```
signal-cli container                    → alerts service (nothing sends without it)
alert state dict (in-process)           → deduplication, recovery, all four alert types
Four alert types (basic send)           → quiet hours, snooze (snooze needs inbound — bidirectional)
Bidirectional bot (signal-cli receive)  → snooze, acknowledgement (optional, v1.3 stretch)

Bridge /api/summary endpoint            → dashboard current readings, sparklines
Bridge /api/farmos/observations         → dashboard production data section
Dashboard static serve (nginx/bridge)   → everything dashboard

signal-cli container + alert types      → chart snapshot attachment (adds matplotlib, optional)
```

---

## MVP Recommendation for v1.3 (2-4 week scope)

### Must ship (table stakes, low complexity, high trust impact)

**Alerts:**
1. signal-cli REST API container + send-only wrapper
2. Four alert types with deduplication + throttle + recovery messages
3. WARN/CRITICAL severity tiers with repeat intervals
4. Alert state persistence to disk
5. Test message command

**Dashboard:**
6. Current readings with sensor provenance (SCD41 label + accuracy)
7. Service health strip (reuse Phase 16 signals)
8. Last camera frame (60s poll)
9. FarmOS latest observations (3 entries)
10. Mobile layout + local timezone

### Should ship if time allows

11. Quiet hours (S — one config option, one datetime check)
12. 6h sparklines (M — most impactful differentiator, farmer's #1 wish)
13. "What's unusual" anomaly callout (M — genuinely useful, moderate SQL)
14. Embed FarmOS logs inline (S-M — low risk, completes the unified view)

### Defer to v1.4

- Snooze per alert-type (requires bidirectional bot)
- Acknowledgement (requires bidirectional bot)
- Chart snapshot attachment (matplotlib overhead, nice-to-have)
- Annotated event timeline (requires new event emission from fc_controller — L)
- "Compare to yesterday's cycle" (chart infra — L)
- Parameter-change UI (its own milestone)
- Live camera stream (4G cost concern)
- Multi-chamber switching

---

## Sources

- Farmer field notes: `.planning/phases/999.11-farmer-app/FARMER-APP-NOTES-2026-04-11.md` (HIGH confidence — first-person session capture)
- Phase 16 context: `.planning/milestones/v1.2.1-phases/16-system-health-panel/16-CONTEXT.md` (HIGH — existing signals)
- Phase 13 context: `.planning/milestones/v1.2-phases/13-farmos-daily-report/13-CONTEXT.md` (HIGH — FarmOS auth pattern)
- PROJECT.md v1.3 section (HIGH — explicit feature list and deferrals)
- Prometheus Alertmanager patterns: https://www.netdata.cloud/academy/prometheus-alert-manager/ (MEDIUM — general alerting, adapted for single-service context)
- Alert fatigue best practices: https://incident.io/blog/alert-fatigue-solutions-for-dev-ops-teams-in-2025-what-works (MEDIUM)
- IoT dashboard design: https://statsandinsights.com/2025/01/10/iot-dashboard-design-create-powerful-data-visualizations/ (LOW — general IoT, not farm-specific)
