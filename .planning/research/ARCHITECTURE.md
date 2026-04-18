# Architecture: v1.3 Alerts + Unified Farmer Dashboard

**Domain:** ROS2 mushroom farm control — adding alerting and a unified operator HUD
**Researched:** 2026-04-18
**Overall confidence:** HIGH (based on actual codebase + running system; no speculation)

---

## Summary of Existing Integration Points

Before documenting new components, the concrete existing surface area:

**Bridge service** (`src/mission-control/bridge/src/index.js`, port 8081 on host network):
- ROS subscriptions (all with rclnodejs): `/fc1/humidity`, `/fc1/temperature`, `/fc1/co2`, `/fc1/actuators/humidifier` (TRANSIENT_LOCAL), `/fc1/sensor_health` (TRANSIENT_LOCAL, DiagnosticStatus)
- WebSocket: `ws://localhost:8081` — broadcasts `{humidity, timestamp}`, `{temperature, timestamp}`, `{co2, timestamp}`, `{humidifier, timestamp}`, `{sensor_health: {level, name, message, values}, timestamp}`
- REST: `GET /health`, `GET /history/:topic`, `GET /camera/mjpeg`, `GET /camera/snapshot`, `GET /camera/latest.jpg`
- In-process state: `rosReady`, `humidifierLastMsgTs`, `lastSensorHealthBroadcast`, `dbReady`
- CORS: allowlist via `CORS_ORIGIN` env var (comma-separated origins)
- TimescaleDB `telemetry` table: columns `(time, topic, value)` — topics are `fc.humidity`, `fc.temperature`, `fc.co2`, `fc.humidifier`

**farmos-agent** (`src/farmos-agent/farmos_agent/farmos_agent_node.py`):
- Connects to FarmOS via HTTP session (username+password, session cookie auth)
- Reads TimescaleDB for daily aggregates via psycopg2
- Posts observations to FarmOS REST API (`/api/log/observation`)
- Fetches camera snapshot from bridge at `$BRIDGE_URL/camera/latest.jpg`
- Runs on elder-plops as a docker-compose service with host networking

**docker-compose topology** (all services use `network_mode: host` via override):
- `bridge` — host network, port 8081
- `openmct` — host network, port 8080
- `timescale` — bound to `127.0.0.1:5432` only
- `farmos-agent` — host network

**Signal context**: farm uses Signal for notifications (not Telegram/Slack). No existing Signal integration.

---

## Question 1: Alert Engine Placement

### The three options evaluated against the actual codebase

**Option A: New ROS2 node on elder-plops subscribing directly to ROS topics + calling Signal CLI locally.**

The bridge already does all ROS subscriptions needed for alerting. A second rclnodejs or rclpy process on elder-plops subscribing to the same topics is technically valid (DDS pub/sub is many-to-many), but creates duplication: two processes each managing TRANSIENT_LOCAL subscriptions to the same topics, each with their own rclnodejs init lifecycle, each potentially racing for CycloneDDS unicast peer establishment on the Tailscale link. The Pi-offline detection case — noticing that ROS messages stopped arriving — already has a working proxy in the `/health` endpoint's `ros.connected` + `humidifier.last_msg_ts` fields. Rebuilding that detection in a second ROS node is strictly redundant.

Verdict: **reject**. Doubles ROS connection complexity for no benefit given bridge already has all the data.

**Option C: Dedicated container subscribing to bridge WebSocket and calling Signal.**

This is the "microservice" instinct — clean separation, no coupling to bridge internals. The blast radius argument (if the alert service crashes, bridge is unaffected) is real. However, in this system the bridge crashing *is* an alert condition — if the container consuming the bridge WS goes away, the alert engine goes silent at exactly the wrong moment. The WS reconnect dance adds a failure mode: during the reconnection gap between bridge restart and alert consumer reconnect, a sensor_health ERROR or humidifier-stuck event could be missed. The TRANSIENT_LOCAL replay shim for sensor_health (Phase 16.1) mitigates this for that one topic, but not for humidity or humidifier time-series anomalies. Additionally, the Pi-offline detection (noticing absence of messages) is hard to implement correctly in a WS consumer — you'd need to replicate the same timestamp-tracking the bridge already does in `humidifierLastMsgTs`.

Verdict: **reject for MVP**. The "clean separation" benefit is real but the failure-mode complexity is not worth it at this scale. Revisit if the bridge grows beyond one file.

**Option B: Alert module inside `src/mission-control/bridge/src/`.**

The bridge already has:
- All four ROS subscriptions needed for alert conditions
- `humidifierLastMsgTs` — exact state needed for Pi-offline and humidifier-stuck detection
- `rosReady` — bridge-internal health flag
- `lastSensorHealthBroadcast` — cached sensor_health for level checks
- The `/health` endpoint already computing derived health state

Adding alert logic here means zero new ROS subscriptions, zero new DDS sessions, zero new WS connection management. A restart of the bridge restarts the alert engine with it — that is correct behavior, not a bug (a crashed bridge should stop alerting because it has no data to alert on). Signal CLI invocation from Node.js is `child_process.exec('signal-cli ...')` — a one-liner.

The "blast radius if it crashes" concern cuts the other way: the alert engine crashing *should* bring down the bridge, because silent alert engine failure is worse than visible bridge failure. The whole container restarts cleanly via `restart: always`.

Verdict: **recommend Option B**.

### Recommended integration: alert module in bridge

Create `src/mission-control/bridge/src/alerter.js` — a plain JS module (not a class, just exported functions) that the bridge's `index.js` calls after each relevant subscription callback.

```
src/mission-control/bridge/src/
  index.js           (existing — calls alerter.check*() after subscriptions fire)
  alerter.js         (new — alert state machine, Signal CLI invocation, dedupe logic)
```

`alerter.js` exports:
- `checkSensorHealth(level, message)` — called from sensor_health subscription callback
- `checkHumidity(valuePercent)` — called from humidity callback
- `checkHumidifier(state, ts)` — called from humidifier callback; also used by Pi-offline ticker
- `checkPiOffline(humidifierLastMsgTs, rosReady)` — called from a `setInterval` in index.js (60s tick)

Alert conditions to implement (from PROJECT.md v1.3 scope):
1. Pi offline: `rosReady === false` OR `humidifierLastMsgTs` not updated in N minutes
2. Sensor unhealthy: `sensor_health.level >= 2` (ERROR) persists for >1 tick
3. RH out-of-band: humidity value outside `[target - tolerance, target + tolerance]` for >N minutes
4. Humidifier stuck: `humidifier === 1` (or 0) continuously for >N minutes without cycling

Signal invocation: Signal CLI must be installed on the elder-plops host (not in the bridge container). Because all services use `network_mode: host`, `child_process.exec('signal-cli -u +1... send -m "..." +1...')` runs against the host's PATH directly. Alternatively, use signal-cli REST API mode — a local HTTP server on a fixed port — which is easier to mock in tests.

Environment variables to add to bridge service in docker-compose:
```
SIGNAL_PHONE=+1...           # sender number registered with signal-cli
SIGNAL_RECIPIENT=+1...       # farmer's Signal number
ALERT_RH_MIN=78              # lower OOB threshold for RH alert
ALERT_RH_MAX=83              # upper OOB threshold
ALERT_OFFLINE_MINUTES=5      # minutes before Pi-offline alert fires
ALERT_STUCK_MINUTES=30       # minutes humidifier in same state before stuck alert
```

---

## Question 2: Unified Dashboard Integration

### Where the page lives

Serve the farmer dashboard as a static HTML page from the bridge itself. Add a route:

```
GET /farmer  → serves src/mission-control/bridge/src/farmer/index.html
```

Rationale: The bridge is already on host network at port 8081, already has CORS configured, already serves the MJPEG endpoint. Adding one more `express.static()` or `res.sendFile()` is trivial. Avoids a new service, new port mapping, new container to rebuild.

The OpenMCT app continues on port 8080 unchanged. Farmer dashboard is on port 8081 at path `/farmer`. These are separate HTML pages sharing the same bridge WS and REST backend.

Static file location: `src/mission-control/bridge/src/farmer/` — a directory of vanilla HTML/CSS/JS files, no build step.

### Data access pattern (concrete)

```
Browser (farmer dashboard at http://elder-plops-ip:8081/farmer)
  │
  ├── WebSocket: ws://elder-plops-ip:8081
  │     Receives: humidity, temperature, co2, humidifier, sensor_health (real-time)
  │     Same WS endpoint already used by OpenMCT plugin.js
  │
  ├── REST GET /health
  │     Returns: {status, db, ros, camera, humidifier.last_msg_ts}
  │     Polling interval: 30s (not real-time; just for connectivity status panel)
  │
  ├── REST GET /history/fc.humidity?start=...&end=...
  ├── REST GET /history/fc.co2?start=...&end=...
  │     Used for sparkline/trend view (last 6h on page load)
  │
  └── REST GET /farmos/summary  (NEW proxy endpoint on bridge)
        Bridge calls FarmOS REST API server-side and returns a sanitized JSON
        → avoids browser needing FarmOS credentials/CORS
```

### CORS and FarmOS auth

FarmOS is on a separate host (`http://10.68.155.50:8082` per farmos_agent_node.py). The browser cannot call FarmOS directly without: (a) FarmOS CORS headers allowing the dashboard origin, and (b) the farmer's browser having a valid FarmOS session.

The right solution at this scale: **bridge proxies FarmOS**. Add one route:

```
GET /farmos/summary
```

Bridge calls FarmOS server-to-server (same pattern as farmos_agent: session cookie or Basic auth from env vars), fetches the most recent observation for FC-1, and returns a stripped-down JSON. This keeps FarmOS credentials server-side, avoids CORS configuration on the FarmOS Drupal instance, and means the farmer dashboard only needs to trust the bridge origin — which it already does.

```javascript
// src/mission-control/bridge/src/index.js addition
app.get('/farmos/summary', async (req, res) => {
    // fetch latest FC-1 observation from FarmOS using stored session
    // return { date, rh_avg, co2_avg, notes_preview, observation_url }
});
```

Add `FARMOS_URL`, `FARMOS_USERNAME`, `FARMOS_PASSWORD` env vars to the bridge service (they're currently only on farmos-agent). The bridge only calls FarmOS on demand (per `/farmos/summary` request), not on a schedule.

CORS for the farmer dashboard: The dashboard is served from `localhost:8081/farmer`, so same-origin — no CORS headers needed for the bridge API calls. If the farmer accesses from a different IP (their phone on Tailscale), add `http://farmer-phone-ip:8081` or use `CORS_ORIGIN` env var. The existing CORS allowlist mechanism handles this without code changes.

### Static asset pipeline

Vanilla HTML + CSS + JS only. No React, no Vite, no build step. The bridge already serves static files (e.g., the OpenMCT frontend is a separate container but this page is even simpler). A `<script>` tag with vanilla fetch and DOM manipulation is sufficient for the HUD MVP described in the farmer app notes (readings, sparklines, camera snapshot, health lights).

One dependency that earns its weight: a small charting library for the sparklines. `Chart.js` (CDN link, ~60KB gzipped) via a `<script src="https://cdn.jsdelivr.net/npm/chart.js">` tag — no npm install, no bundler.

---

## Question 3: Alert State Persistence

### Do we need it?

The concrete restart scenario: bridge restarts, alert module initializes with empty state, first sensor_health message arrives (TRANSIENT_LOCAL replay), state is ERROR, alert fires. This is correct behavior, not spam — the farmer wants to know the sensor is still unhealthy after a restart.

The spam scenario the question is worried about: bridge restarts 3 times in 5 minutes, farmer gets 3 "Pi back online" messages. This is a real annoyance.

### Recommendation: in-memory dedupe with reset-on-restart, no persistence

For the MVP, use a per-alert-type cooldown map in alerter.js:

```javascript
const lastAlertTs = {};  // { 'pi_offline': ms, 'sensor_unhealthy': ms, ... }
const COOLDOWN_MS = 60 * 60 * 1000;  // 1 hour between same-type alerts
```

A bridge restart clears `lastAlertTs`, which means a restart can fire one instance of each alert type if the condition still holds. That is acceptable — the farmer gets one alert per restart, not three in five minutes. Three restarts in five minutes is itself an infrastructure problem that warrants investigation.

If this proves noisy in practice, the next step is a Timescale `alerts` table (not SQLite — Timescale is already there):

```sql
CREATE TABLE IF NOT EXISTS alerts (
    time        TIMESTAMPTZ NOT NULL,
    alert_type  TEXT        NOT NULL,
    message     TEXT        NOT NULL,
    resolved_at TIMESTAMPTZ
);
```

The bridge queries `SELECT MAX(time) FROM alerts WHERE alert_type = $1` before firing. This adds one DB round-trip per alert check but eliminates cross-restart spam entirely. **Defer this to Phase 2 of the milestone — ship in-memory first.**

---

## Question 4: Build Order

### Dependency graph

```
FarmOS admin setup (carryover from v1.2)
    → required before /farmos/summary proxy returns useful data
    → but dashboard can ship without it (show placeholder if no FarmOS data)

alert engine (alerter.js in bridge)
    → depends on: Signal CLI installed on elder-plops host
    → does NOT depend on: dashboard, FarmOS

dashboard static page
    → depends on: bridge /farmos/summary endpoint (for FarmOS section)
    → does NOT depend on: alert engine

Phase 12 hardware UAT (carryover)
    → independent of all new v1.3 work
```

### Recommended phase decomposition (4 phases)

**Phase 17: Alert engine + Signal integration**
- Install and configure signal-cli on elder-plops (manual step, pre-phase)
- Create `src/mission-control/bridge/src/alerter.js`
- Wire alerter calls into existing subscription callbacks in `index.js`
- Add Pi-offline ticker (`setInterval` in index.js)
- Add alert env vars to `docker-compose.yml`
- Test: force sensor_health ERROR level, verify Signal message received
- Ship to production before dashboard — alerts are higher value and fully independent

**Phase 18: Farmer dashboard HUD**
- Create `src/mission-control/bridge/src/farmer/` directory with `index.html`
- Add `express.static()` route in `index.js` for `/farmer`
- Implement: WS connection for live readings, `/health` poll for status lights, `/history/fc.*` for sparklines, `/camera/snapshot` for latest frame
- No FarmOS section yet — show placeholder
- Ship: `docker compose up -d --build bridge`

**Phase 19: FarmOS proxy + dashboard FarmOS section**
- Add `GET /farmos/summary` route to bridge
- Add `FARMOS_URL`, `FARMOS_USERNAME`, `FARMOS_PASSWORD` to bridge env
- Add FarmOS section to farmer dashboard consuming `/farmos/summary`
- Complete FarmOS admin carryover (FC-1 asset location, permissions)
- Ship bridge rebuild

**Phase 20: Phase 12 hardware UAT + polish**
- Execute Phase 12 hardware UAT checklist (camera on real hardware)
- Alert cooldown tuning based on real-world behavior from Phase 17
- Dashboard UX polish based on farmer feedback from Phase 18
- Consider Timescale `alerts` table if in-memory cooldown proved noisy

### Parallelism

Phase 17 and Phase 18 are fully parallel — alerter.js and the farmer dashboard page share no code. They require the same bridge rebuild to ship but can be developed independently and merged before a single `docker compose up -d --build bridge`.

Phase 19 requires Phase 18 to be live (dashboard already exists to add the FarmOS section to).

Phase 20 is independent of everything except needing Phase 17 in production long enough to observe cooldown behavior.

---

## Concrete File Paths and Route Summary

### New files
```
src/mission-control/bridge/src/alerter.js
src/mission-control/bridge/src/farmer/index.html
src/mission-control/bridge/src/farmer/farmer.css     (optional, can inline)
src/mission-control/bridge/src/farmer/farmer.js      (optional, can inline)
```

### Modified files
```
src/mission-control/bridge/src/index.js
  + import alerter.js
  + call alerter.checkSensorHealth() in sensor_health subscription callback
  + call alerter.checkHumidity() in humidity callback
  + call alerter.checkHumidifier() in humidifier callback
  + add setInterval Pi-offline check (60s tick)
  + add express.static() for /farmer
  + add GET /farmos/summary proxy route

docker-compose.yml  (bridge service environment block)
  + SIGNAL_PHONE, SIGNAL_RECIPIENT
  + ALERT_RH_MIN, ALERT_RH_MAX, ALERT_OFFLINE_MINUTES, ALERT_STUCK_MINUTES
  + FARMOS_URL, FARMOS_USERNAME, FARMOS_PASSWORD  (Phase 19)
```

### New HTTP routes on bridge (port 8081)
```
GET /farmer              → serves static farmer dashboard HTML
GET /farmos/summary      → proxied FarmOS latest observation for FC-1
```

### ROS topics consumed (no new subscriptions needed)
```
/fc1/humidity             — already subscribed; alerter.checkHumidity() added to callback
/fc1/actuators/humidifier — already subscribed; alerter.checkHumidifier() added to callback
/fc1/sensor_health        — already subscribed; alerter.checkSensorHealth() added to callback
(Pi-offline uses existing humidifierLastMsgTs + rosReady state variables)
```

### TimescaleDB (Phase 1 of alerts: no changes; Phase 2 if cooldown proves noisy)
```sql
CREATE TABLE alerts (
    time        TIMESTAMPTZ NOT NULL,
    alert_type  TEXT        NOT NULL,
    message     TEXT        NOT NULL,
    resolved_at TIMESTAMPTZ
);
SELECT create_hypertable('alerts', 'time', if_not_exists => TRUE);
```

---

## Key Constraints and Risks

**Signal CLI host dependency.** signal-cli must be installed and registered on elder-plops before Phase 17 can ship. This is a pre-phase manual step that requires a phone number registration flow. It cannot be automated in the compose stack without significant complexity. Factor 1-2 hours for setup + registration.

**elder-plops is dev + prod simultaneously.** Per memory, rebuilding the bridge affects production immediately. The `--build bridge` command on a system with live production traffic means the bridge goes down for the rebuild duration (typically <60 seconds). Alert logic must be verified in dev/sim mode before shipping.

**FarmOS auth in bridge.** Adding `FARMOS_USERNAME`/`FARMOS_PASSWORD` to the bridge docker-compose means those credentials appear in environment variables accessible to any process in the bridge container. Current practice (farmos-agent already does this). Not a new risk, just the same risk extended to one more service.

**Farmer dashboard has no auth.** The dashboard at `http://elder-plops-ip:8081/farmer` will be accessible to anyone on the Tailscale network. That is acceptable for this farm (same trust model as OpenMCT at port 8080). Do not add auth in v1.3.

**CORS for mobile access.** If the farmer accesses the dashboard from their phone via Tailscale, the `CORS_ORIGIN` env var needs to include the phone's browser origin or the farmer must access via the elder-plops IP (not a hostname). Document in the phase plan — do not solve automatically.
