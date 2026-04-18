# Phase 17: Alert Engine + Signal — Research

**Researched:** 2026-04-18
**Domain:** Standalone Node.js agent on elder-plops consuming bridge WebSocket, calling bbernhard/signal-cli-rest-api for bidirectional Signal alerts
**Confidence:** HIGH for architecture (live code + locked decisions), HIGH for signal-cli-rest-api API (verified from README + Docker Hub), MEDIUM for initial cadence values (empirical recommendations drawn from v1.0–v1.2.1 operational history, not live-soak data)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Shape A — Bridge stays thin, agent is separate container**
- **D-01:** Bridge remains the single ROS↔outside-world gateway. It does NOT grow alerter logic. Agents are independent containers that consume bridge WS/REST.
- **D-02:** Alerter is the **reference implementation** for the future agent pattern (weather poller, maturity detector, farmer-app backend, any future autonomous agents follow the same shape).
- **D-03:** Each agent = its own compose service, its own process, its own crash domain, its own volume. Bridge crash = every agent sees "offline" (which for alerter is the correct Pi-offline signal path — bridge is the vantage point).

**Deployment topology**
- **D-04:** Alerter runs as a standalone compose service on elder-plops named `alerter` (sibling to `bridge`, `timescale`, `openmct`, `signal-cli`).
- **D-05:** Telemetry ingress: alerter is a **WS client** of bridge (`ws://bridge:8081`). No rclnodejs/CycloneDDS in the alerter image. Alerter relies on bridge's replay-on-connect for `sensor_health` and `humidifier` state.
- **D-06:** Signal egress: alerter POSTs to `http://signal-cli:8080` on the compose internal network.
- **D-07:** Alerter state (cooldown timers, snooze windows, active-alert map) starts **in-memory**. Promote to a Timescale `alerts` table only if restart-spam proves noisy in soak (per ALRT-03).

**Code layout**
- **D-08:** New top-level directory: **`src/agents/`** — home for all elder-plops-side autonomous services.
- **D-09:** Phase 17 creates `src/agents/alerter/` with its own `package.json`, `Dockerfile`, and entrypoint. Deps: `ws`, `pg` (for eventual Timescale promotion), a Signal REST client (axios/fetch).
- **D-10:** No shared code with bridge in this phase. If duplication appears later, extract to `src/agents/_shared/` — not a Phase 17 concern.

**Signal service**
- **D-11:** `signal-cli-rest-api` (bbernhard) declared in **`docker-compose.override.yml`**.
- **D-12:** Account state in a **named Docker volume** (`signal-cli-data`).
- **D-13:** signal-cli-rest-api is **internal-only** on the compose network — not published to host, not Tailscale-served. Only `alerter` talks to it.

### Claude's Discretion (researcher to propose, no user preference locked)

1. Pi-offline detection: stale ROS heartbeat timeout vs Tailscale ping vs both; grace/debounce values
2. Humidifier-stuck detection: commanded-vs-observed mismatch, RH trajectory post-ON, durations — concrete rule
3. Initial cadences: cooldown minutes, N-consecutive OOB readings, heartbeat time-of-day (farm TZ)
4. Signal message body template: severity prefix, value formatting, timestamp, dashboard link wording
5. Snooze grammar
6. `ALERT_RH_TARGET`/`ALERT_RH_BAND`: independent env vars vs reading `fc_config.yaml` over ROS/bridge
7. signal-cli-rest-api mode: `normal` vs `json-rpc` vs `native`; exact image tag + pin strategy
8. Signal primary-account registration flow via 4G router SIM

### Deferred Ideas (OUT OF SCOPE)

- Timescale `alerts` table — promote only if restart-spam observed
- Shared agent utilities (`src/agents/_shared/`) — premature today
- MJPEG/image attachments in Signal messages
- Multi-recipient routing / on-call rotation
- Backup strategy for `signal-cli-data` volume
- Extracting bridge `/farmer` static serving into its own agent

</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ALRT-01 | bbernhard/signal-cli-rest-api Docker service on elder-plops with Signal registered as primary on 4G router SIM | §1 signal-cli-rest-api config, §8 primary registration flow, §11 compose snippets |
| ALRT-02 | Four alert types fire PROBLEM+RECOVERY: Pi offline, sensor ERROR past grace, RH OOB for N minutes, humidifier stuck | §2 detection rules, §3 state machine |
| ALRT-03 | Dedup + throttle (N≥5 consecutive OOB), severity tiers (WARN/CRITICAL), state persistence strategy | §3 state machine, §4 cadences |
| ALRT-04 | Daily heartbeat — serves as liveness indicator + keeps Signal session warm | §4.3 heartbeat cadence, §9 Signal session hygiene |
| ALRT-05 | Grace-period suppression — no alerts during fc_controller 20s warm-up (consume `sensor_health` WARN) | §2.2 sensor_health consumption, §5 message template |
| ALRT-06 | All thresholds/cadences via env vars (SIGNAL_API_URL, SIGNAL_RECIPIENT, ALERT_RH_TARGET, ALERT_RH_BAND, ALERT_COOLDOWN_MIN, …) | §7 env-var inventory |
| ALRT-07 | Snooze-per-alert-type via Signal reply (`snooze rh 4h`) — bidirectional receive loop + same-store snooze state | §6 snooze grammar, §10 receive loop strategy |
| ALRT-08 | Every alert body includes farmer dashboard link (`http://elder-plops-ts:8081/farmer`) | §5 message template |
</phase_requirements>

## Summary

Phase 17 ships a standalone Node.js 20 agent container (`alerter`) and a bbernhard/signal-cli-rest-api container. The alerter subscribes to the bridge WebSocket, maintains an in-memory alert state machine, fires PROBLEM/RECOVERY Signal messages via HTTP to signal-cli-rest-api, emits a daily heartbeat, and implements a bidirectional snooze grammar by polling `/v1/receive` on the signal-cli-rest-api container. All thresholds are env-var configurable; the code is ~350-450 LOC in one `index.js` plus a `signal.js` client and a `state.js` state machine.

Two specific research recommendations cut against the instinct:

1. **Do NOT ping the Pi directly over Tailscale from the alerter.** Pi-offline detection should be derived from the bridge — stale `humidifierLastMsgTs` as surfaced in the bridge's `/health` endpoint (polled every 30s) and via absence of WS messages. Tailscale ping from alerter adds a second failure mode (alerter network routing) without adding signal, because if the bridge can't reach the Pi, neither can the alerter. The bridge WS going away is itself the Pi-offline signal (per D-03 "bridge crash = every agent sees offline").

2. **`signal-cli-rest-api` mode = `json-rpc-native`, pin tag `0.200-dev`.** The `latest-stable` tag referenced in prior research is NOT currently present on Docker Hub (verified 2026-04-18 — only `latest-dev` and numbered `*-dev` tags are available). `json-rpc-native` is required for `/v1/receive` to work reliably for the snooze loop — `normal` mode re-registers the websocket per request and the receive endpoint docs explicitly warn against mixing `/v1/receive` with `AUTO_RECEIVE_SCHEDULE` in non-daemon modes.

**Primary recommendation:** Ship a minimal one-file agent that enforces one invariant above all others — **every PROBLEM must have a corresponding RECOVERY, and the heartbeat ships in the same commit as the PROBLEM path**. Everything else (exact cadences, snooze grammar precision) is tunable in Phase 20.

## Standard Stack

### Core

| Component | Version | Purpose | Why Standard |
|-----------|---------|---------|--------------|
| Node.js | 20 LTS (alpine) | Alerter runtime | Bridge uses Node + Express; native `fetch`, `AbortController`, `WebSocket` (via `ws` pkg) all stable; alpine base keeps image small [VERIFIED: nodejs.org Node 20 is current LTS] |
| ws | ^8.16.0 | WebSocket client to bridge | Same version as bridge — proven reconnect behavior, minimal API [VERIFIED: `src/mission-control/bridge/package.json`] |
| pg | ^8.20.0 | Postgres/Timescale client (seed only — unused in Phase 17 runtime) | Match bridge pin so future Timescale promotion is zero-churn [VERIFIED: `bridge/package.json`] |
| bbernhard/signal-cli-rest-api | `0.200-dev` (pinned) with fallback `latest-dev` | Signal primary-account host + REST API | Only live, actively maintained Dockerized Signal option with JSON-RPC daemon mode [VERIFIED: hub.docker.com/r/bbernhard/signal-cli-rest-api/tags on 2026-04-18] |

### Supporting

| Component | Version | Purpose | When to Use |
|-----------|---------|---------|-------------|
| Node native `fetch` | Built-in Node 18+ | HTTP calls to signal-cli-rest-api (`POST /v2/send`, `GET /v1/receive`) | Default — no new dep [VERIFIED: nodejs.org native fetch stable since Node 18] |
| `AbortController` | Built-in Node 18+ | Timeout on fetch calls to signal-cli-rest-api | Default — 10s timeout on every HTTP call |
| `setInterval` / `setTimeout` | Built-in | Heartbeat timer, Pi-offline tick, receive-loop tick | No cron lib needed at this cadence |

**Intentionally NOT used:**

| Skip | Why |
|------|-----|
| `axios` | Native fetch covers all needs; axios adds ~500KB and a semver surface for no gain |
| `node-cron` | Heartbeat is one `setInterval` + TZ check; cron string parsing is overkill |
| `winston`/`pino` | `console.log` with JSON format is sufficient for one container; add a logger only when multiple agents exist |
| `dotenv` | docker-compose injects env vars directly; dotenv would only help local dev, and local dev of this agent requires a running bridge + signal-cli anyway |
| `signal-cli-client` npm package | No actively maintained node client for signal-cli-rest-api exists; direct HTTP is simpler |

**Installation (Phase 17 alerter `package.json` proposed):**
```json
{
  "name": "mushy-alerter",
  "version": "0.1.0",
  "main": "src/index.js",
  "scripts": { "start": "node src/index.js" },
  "dependencies": {
    "ws": "^8.16.0",
    "pg": "^8.20.0"
  }
}
```

**Version verification (performed 2026-04-18):**
- `ws@8.16.0` — matches bridge; latest is `8.18.x` but bridge is pinned to `^8.16.0` and works [VERIFIED: `bridge/package.json`]
- `pg@8.20.0` — matches bridge [VERIFIED: `bridge/package.json`]
- `bbernhard/signal-cli-rest-api:0.200-dev` — pushed ~20h before 2026-04-18 [VERIFIED: Docker Hub tags page]
- `bbernhard/signal-cli-rest-api:latest-stable` — **not present in current tag listing** [VERIFIED: Docker Hub 2026-04-18]. Use `0.200-dev` (pin) with manual promotion per milestone. Prior research (STACK.md v1.3 additions) referenced `latest-stable`; that guidance is stale.

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| bbernhard/signal-cli-rest-api | `signald` | `signald` is less active; no REST abstraction — caller must speak Unix socket JSON protocol |
| bbernhard/signal-cli-rest-api | `signal-cli` bare JVM on host | Requires Java on host and breaks the container-only deployment invariant (memory: elder-plops stays containerized) |
| node-ws client | rclnodejs (subscribe directly to ROS) | Re-violates D-01/D-05 (bridge = single ROS gateway); adds CycloneDDS config burden to every agent |
| `json-rpc-native` MODE | `normal` MODE | `normal` starts a fresh JVM per request (5-10s latency), breaks bidirectional receive; unacceptable for snooze loop |
| `json-rpc-native` MODE | `native` MODE | `native` (pure GraalVM) is one-shot per call; still no daemon; same receive issue |
| `json-rpc-native` MODE | `json-rpc` (JVM daemon) | Works, but uses ~300MB RAM persistent vs ~80MB for native daemon. On elder-plops this is fine; choose native for thrift consistency |

## Architecture Patterns

### Recommended Project Structure

```
src/agents/                          # NEW top-level dir per D-08
  alerter/
    Dockerfile                       # FROM node:20-alpine
    package.json
    package-lock.json
    src/
      index.js                       # entrypoint, WS connect, tick loops, signal-cli polling
      state.js                       # pure state machine: transitions, cooldowns, snoozes
      signal.js                      # thin client around signal-cli-rest-api HTTP (send, receive)
      rules.js                       # detection predicates: isPiOffline, isRhOob, isHumidifierStuck
      config.js                      # env-var parsing + defaults in one place (ALRT-06)
    test/
      state.test.js                  # unit tests against state machine (Node --test runner)
      rules.test.js                  # unit tests against detection predicates
      README.md                      # how to run locally against mock ws + mock signal-cli
```

Five small files — each one earns its place. If any single file exceeds 200 LOC that's a signal to split. Total expected ~400-550 LOC across all files.

### Pattern 1: Separate state machine from I/O

**What:** `state.js` is a pure module: `transition(prevState, event) -> {newState, actions}`. No side effects, no network, no timers. `index.js` owns all timers and all network calls and dispatches events into `state.js`, then executes the returned actions (send Signal message, reset a timer).

**When to use:** Always for alert engines. Dedupe, cooldown, and snooze logic are the part most likely to have subtle bugs. Keeping them in a pure function makes them unit-testable without mocking `fetch` or `ws`.

**Example shape (pseudocode):**
```javascript
// state.js
// Per alert type: { state: 'OK'|'PENDING'|'FIRING'|'SNOOZED', oobCount, lastFiredAt, firstOobAt, snoozedUntil }
function transition(prev, event, now, config) {
  // event: {type: 'humidity', value: 82.3} | {type: 'sensor_health', level: 2}
  //        | {type: 'tick'}  | {type: 'snooze', alertType, untilMs}
  // returns: { next, actions: [{kind:'send', severity, body}, ...] }
}
```

### Pattern 2: Alerter reconnects forever, never exits

**What:** WS disconnect → exponential backoff (1s, 2s, 4s, 8s, cap 30s) → reconnect → re-request state via reconnection. On reconnect, bridge automatically replays `lastSensorHealthBroadcast` (per `bridge/src/index.js:301`), which is how `sensor_health` state is restored. For humidifier state, poll `GET /health` on reconnect to grab `humidifier.last_msg_ts`.

**When to use:** Every long-lived agent. `process.exit()` is never appropriate — `restart: unless-stopped` is a last resort, not a first-line strategy. Bridge restart (production rebuild) must not require alerter to restart.

**Warning signs:** Unhandled `'error'` event on WS; catch block that calls `process.exit(1)`; no backoff between reconnects.

### Pattern 3: Config is parsed once at boot, errors loudly

**What:** `config.js` parses every env var at module load, applies defaults, validates ranges, logs the effective config to stdout, and throws on invalid values (process exits with a message, not a stack trace).

**When to use:** All env-var-driven services. Better to refuse-to-start than to run with a silently-parsed `NaN` threshold.

**Example:**
```javascript
// config.js
function parseIntEnv(key, def) { ... }
function parseFloatEnv(key, def) { ... }
module.exports = {
  bridgeWsUrl: process.env.BRIDGE_WS_URL || 'ws://localhost:8081',
  signalApiUrl: process.env.SIGNAL_API_URL || 'http://localhost:8085',
  signalSender: mustEnv('SIGNAL_SENDER'),
  signalRecipient: mustEnv('SIGNAL_RECIPIENT'),
  rhTarget: parseFloatEnv('ALERT_RH_TARGET', 90),      // percent
  rhBand: parseFloatEnv('ALERT_RH_BAND', 3),           // ±percent; looser than fc_config 1% on purpose
  oobConsecutive: parseIntEnv('ALERT_OOB_N', 5),       // readings
  oobWindowMin: parseIntEnv('ALERT_OOB_WINDOW_MIN', 3),
  cooldownMin: parseIntEnv('ALERT_COOLDOWN_MIN', 30),
  criticalCooldownMin: parseIntEnv('ALERT_CRITICAL_COOLDOWN_MIN', 60),
  humidifierStuckMin: parseIntEnv('ALERT_HUMIDIFIER_STUCK_MIN', 30),
  piOfflineMin: parseIntEnv('ALERT_PI_OFFLINE_MIN', 5),
  heartbeatHourLocal: parseIntEnv('ALERT_HEARTBEAT_HOUR', 8),
  timezone: process.env.TZ || 'America/Toronto',
  dashboardUrl: process.env.DASHBOARD_URL || 'http://elder-plops-ts:8081/farmer',
};
```

### Anti-Patterns to Avoid

- **Ping-ing the Pi from alerter over Tailscale.** Bridge already does this work. Adds a second path that can disagree with the bridge, which creates flaky alerts when the alerter's DNS blips but bridge's WS to Pi is fine.
- **Reading `fc_config.yaml` from alerter.** The config file is on the Pi, not elder-plops. The alerter would need to ssh/scp or publish it over a ROS topic — both are heavyweight. Use env vars, accept that RH target/band live in two places (Pi and alerter), and document that both must change together in the phase runbook.
- **Calling `signal-cli` CLI directly from Node via `child_process`.** The whole point of picking signal-cli-rest-api is to have a language-agnostic HTTP boundary; spawning CLI processes re-introduces the JVM-startup-per-call problem.
- **Firing on a single OOB reading.** The SCD41 bounces. Require N consecutive (default 5) readings before transitioning `PENDING -> FIRING`. See §3 state machine.
- **Silent exception swallowing in the receive loop.** If `/v1/receive` throws, log + continue; do not let the snooze loop silently die and leave the farmer unable to snooze.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Signal protocol stack | A custom libsignal wrapper | bbernhard/signal-cli-rest-api | libsignal's protocol churns; signal-cli absorbs that for you |
| WebSocket reconnect with backoff | Naive `setTimeout(reconnect, 1000)` loop | Hand-rolled exponential-backoff function is OK (30 LOC), but copy the pattern from farmos-agent / mission_control_bridge rather than re-inventing — bridge does it correctly |
| Cron-style scheduling for daily heartbeat | `node-cron` | `setInterval(1000 * 60 * 60)` checking "is it N o'clock in TZ yet and has today's heartbeat been sent?" — 20 LOC |
| Rate limiting the send loop | Token bucket library | In-memory `lastSentAt[alertType]` + cooldown check in `state.js`; the cooldown IS the rate limiter |
| Persisting alert state across restart | SQLite/LevelDB | Nothing — in-memory per D-07. If Phase 20 soak says "noisy," promote to Timescale `alerts` table. |
| HTTP timeouts | `timeout-signal` package | `AbortController` + `setTimeout(() => ctrl.abort(), 10000)` — built-in |

**Key insight:** The hardest part of an alert engine is not the Signal integration or the WebSocket — it's the **state machine that ensures every PROBLEM has exactly one RECOVERY and that flaps don't spam**. Do hand-roll this (it's 80 LOC of pure logic), but keep it in a file with no I/O.

## Runtime State Inventory

> Phase 17 is net-new greenfield — creating `src/agents/alerter/` and adding two new compose services. No rename, no refactor.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — alerter is stateless per D-07 | None |
| Live service config | Two new compose services added (`alerter`, `signal-cli`) in `docker-compose.override.yml` | Declare in override; rebuild `bridge` not required — alerter depends on it but bridge doesn't change |
| OS-registered state | None — no systemd units, no host-level registrations | None |
| Secrets/env vars | New env vars: `SIGNAL_SENDER`, `SIGNAL_RECIPIENT`, `ALERT_*` (see §7). No new secret material (Signal account state lives in `signal-cli-data` volume, not `.env`) | Add to `.env` on elder-plops; document in `.env.example` |
| Build artifacts | `src/agents/alerter/node_modules/` (gitignored), alerter image in local Docker cache | New `.gitignore` entry for `src/agents/*/node_modules/`; `docker compose build alerter` at deploy |

**Nothing found in other categories:** Verified by reading existing docker-compose files, `.env` structure, and the absence of any existing agent service on elder-plops.

## Common Pitfalls

### Pitfall 1: Linked-device expiry (NOT applicable — primary registration locked)

**What goes wrong:** Signal expires linked devices after 45 days of inactivity. The daily heartbeat is normally the mitigation.

**Why this does not apply here:** CONTEXT.md pre-phase gate specifies **primary registration on the 4G router SIM**, not linked-device flow. Primary accounts do not have a 45-day inactivity expiry; they have a ~120-day re-verification cycle [CITED: support.signal.org, Signal account lifecycle docs] — well beyond heartbeat cadence concerns.

**How to avoid:** Follow the primary-registration flow in §8 exactly. If primary registration proves infeasible (SMS can't be received on 4G SIM — verify during pre-phase gate), fall back to linked-device + daily heartbeat. Document the fallback explicitly in the phase runbook.

**Warning signs:** The farmer's phone shows "mushy-alerts" in Settings → Linked Devices. If it does, you're in linked-device mode and the 45-day expiry applies.

### Pitfall 2: Flap-storm on sensor bounce [CRITICAL]

**What goes wrong:** RH reading bounces around the ±1% operating band edge. Without debounce, a single sample can fire "RH out-of-band" and recovery alternately 10–20 times in a minute.

**Why it happens here specifically:** fc_config.yaml locks `target_humidity: 0.90` / `humidity_tolerance: 0.01` (±1%). SCD41 accuracy is ±1.8% in practice. The sensor noise floor is LARGER than the operating band. [VERIFIED: `src/chambers/fc-core/config/fc_config.yaml` lines 18, 23]

**How to avoid:**
- Alert's band is **looser than the controller's band**. Recommendation: `ALERT_RH_BAND=3` (±3%). The controller actuates on ±1%; the alerter only alerts when the system fails to keep the farm within ±3% — i.e. the controller is failing, not just noisy.
- Require **5 consecutive out-of-band samples** over a 3-minute window before firing (the controller publishes humidity roughly every ~2-5s, so 5 consecutive samples = ~10-25s of sustained OOB).
- Recovery requires 5 consecutive **in-band** samples — symmetric debounce.

**Warning signs during development:** In simulation, injecting a sine wave through the band boundary produces >1 alert per minute.

### Pitfall 3: Missing RECOVERY notification [CRITICAL]

**What goes wrong:** PROBLEM fires at 02:00. Condition resolves at 02:03. No RECOVERY message. Farmer wakes at 07:00, sees the alert, cannot tell if the chamber has been broken for 5 hours or was fine at 02:04.

**How to avoid:**
- The state machine tracks per-type state explicitly (`OK`/`PENDING`/`FIRING`/`SNOOZED`). Transition `FIRING -> OK` is the ONLY path that generates a RECOVERY message.
- RECOVERY body includes duration: `"[RECOVERY] RH back in band (89.1%) — was OOB for 4m 12s. <link>"`
- Unit test: inject a PROBLEM→RECOVERY sequence with synthetic events and assert both messages are generated.

### Pitfall 4: Alert bot dies silently [CRITICAL]

**What goes wrong:** Alerter crashes on an unhandled exception at 14:22 Monday. Nothing monitors it. Farmer receives zero alerts for two weeks until they notice "it's been quiet."

**How to avoid:**
- `restart: unless-stopped` on the alerter service [VERIFIED: farmos-agent uses this in `docker-compose.yml:59`]
- **Daily heartbeat is the canonical liveness signal.** Ships in the same commit as the PROBLEM path — never deferred. If heartbeat stops arriving, farmer knows something is wrong.
- Process-level `process.on('unhandledRejection', ...)` + `process.on('uncaughtException', ...)` → log and exit, letting compose restart.
- Do NOT swallow exceptions in the main loop. Log and rethrow or exit.

### Pitfall 5: Alert fatigue from warm-up spikes

**What goes wrong:** fc-core restarts at 04:00 for boot-time fc-update pull. Sensor readings spike during the 20s warm-up window. Alerter fires "RH out of band 77%" before the controller has engaged. Farmer mutes the thread.

**How to avoid (locked in ALRT-05):**
- Alerter subscribes to `sensor_health` WS messages and maintains a `warming_up` boolean. On `{level: 1, message: "warming up"}`, set `warming_up=true`; on `{level: 0, message: "ok"}`, set `warming_up=false`.
- While `warming_up === true`, the state machine's RH-OOB and humidifier-stuck detectors are **suppressed** (input events ignored, no state transitions).
- Pi-offline detector continues to operate during warm-up — the Pi can still be offline while a sensor is warming up. Sensor-ERROR detector also operates, but with a grace of `max(warmup_window, 30s)` before firing (per ALRT-05 the warm-up itself produces WARN not ERROR).

### Pitfall 6: Race between bridge restart and first alerter message

**What goes wrong:** Alerter WS connects during the 5s window where bridge has started but ROS hasn't fully re-subscribed. Alerter sees no `humidifier` for 60s and fires "humidifier stuck" incorrectly.

**How to avoid:**
- On WS `open`, poll bridge `GET /health` for initial `humidifier.last_msg_ts` and `ros.connected`. Use that as baseline.
- Pi-offline detection requires both: `(bridge WS disconnected for >piOfflineMin)` OR `(bridge `/health`.ros.connected === false for >piOfflineMin)` OR `(humidifier last_msg_ts stale > piOfflineMin)`. Any single one can trip; require all three to have been *checked* at least once before firing (i.e. do not fire in first 60s after alerter start).

### Pitfall 7: Two-places-to-change-RH-target

**What goes wrong:** Farmer wants to change RH target from 90% to 92%. Updates `fc_config.yaml`, pushes to Pi. Alerter is still configured with `ALERT_RH_TARGET=90` in elder-plops `.env`. Alerts fire for "RH out of band at 91%".

**How to avoid:**
- Document in `src/agents/alerter/README.md` (plan Wave deliverable): "Threshold changes require updating BOTH `fc_config.yaml` (Pi) AND `.env` on elder-plops (for alerter). Deploy both before expecting alerts to match controller behavior."
- Use a wider alert band (ALERT_RH_BAND=3%) so small target drift doesn't immediately cause false positives (a controller tuned to 90±1% still keeps the farm inside 92±3%).
- Deferred idea — Phase 20 candidate: alerter polls bridge `/health` which has already fetched the target from Pi over ROS parameters. Not Phase 17 work.

### Pitfall 8: Rate limit / CAPTCHA on burst sends

**What goes wrong:** A flap-storm triggers Signal server-side rate limit (HTTP 413). Further sends are delayed or dropped; CAPTCHA challenge requires manual intervention.

**How to avoid:**
- Debounce (Pitfall 2) prevents the cause.
- Defensive layer: max 20 sends/hour total across all alert types. If exceeded, alerter logs a warning and drops further sends for the rest of the hour. Heartbeat bypasses the cap.

### Pitfall 9: signal-cli-rest-api DB volume not mounted correctly

**What goes wrong:** Volume mounted at `/root/.local/share/signal-cli` instead of `/home/.local/share/signal-cli/`. Registration succeeds once, survives restart, fails after container recreation.

**How to avoid:**
- The path **inside the container** is `/home/.local/share/signal-cli/` (not `/root/...`). Named volume `signal-cli-data` mounts there. [VERIFIED: bbernhard README `SIGNAL_CLI_CONFIG_DIR`]
- Registration must go through the REST API — never `docker exec` into the container.

## Code Examples

Verified patterns from official sources + the live codebase.

### WebSocket client with reconnect (pattern from ecosystem; adapt into alerter)

```javascript
// Source: ws npm README + bridge/src/index.js reconnect behavior
const WebSocket = require('ws');

function connect(url, onMessage) {
  let ws;
  let backoffMs = 1000;
  const MAX_BACKOFF = 30000;

  function open() {
    ws = new WebSocket(url);
    ws.on('open', () => {
      console.log(JSON.stringify({ level: 'info', event: 'ws_open', url }));
      backoffMs = 1000;
      // Fetch initial state from /health here
    });
    ws.on('message', (data) => {
      try { onMessage(JSON.parse(data.toString())); }
      catch (e) { console.error(JSON.stringify({ level: 'error', event: 'parse', err: e.message })); }
    });
    ws.on('close', () => {
      console.log(JSON.stringify({ level: 'warn', event: 'ws_close', backoffMs }));
      setTimeout(open, backoffMs);
      backoffMs = Math.min(backoffMs * 2, MAX_BACKOFF);
    });
    ws.on('error', (err) => {
      console.error(JSON.stringify({ level: 'error', event: 'ws_error', err: err.message }));
      // 'close' will follow; don't double-schedule
    });
  }
  open();
}
```

### signal-cli-rest-api send (verified against official docs)

```javascript
// Source: github.com/bbernhard/signal-cli-rest-api README §"Send messages"
async function sendSignal(apiUrl, sender, recipient, body) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 10000);
  try {
    const res = await fetch(`${apiUrl}/v2/send`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: body,
        number: sender,
        recipients: [recipient]
      }),
      signal: controller.signal
    });
    if (!res.ok) throw new Error(`signal-cli ${res.status}: ${await res.text()}`);
    return await res.json();
  } finally {
    clearTimeout(timeoutId);
  }
}
```

### signal-cli-rest-api receive (for snooze loop)

```javascript
// Source: github.com/bbernhard/signal-cli-rest-api README §"Receive messages"
// In json-rpc-native MODE, /v1/receive returns queued messages since last call.
async function pollReceive(apiUrl, sender) {
  const res = await fetch(
    `${apiUrl}/v1/receive/${encodeURIComponent(sender)}?timeout=1&ignore_attachments=true`,
    { method: 'GET' }
  );
  if (!res.ok) throw new Error(`receive ${res.status}`);
  return await res.json();  // array of envelope objects
}
```

Response envelope shape (excerpt): `{envelope: {source: "+1...", dataMessage: {message: "snooze rh 4h"}}}`. Parse `dataMessage.message` for the snooze grammar.

### Primary registration (one-time manual, §8)

```bash
# On elder-plops, with signal-cli container running and 4G SIM able to receive SMS:

# Step 1: get captcha at https://signalcaptchas.org/registration/generate.html
# Copy the signalcaptcha://... link (right-click "Open Signal", copy link).

# Step 2: register
curl -X POST 'http://localhost:8085/v1/register/+14165551234' \
  -H 'Content-Type: application/json' \
  -d '{"captcha":"signalcaptcha://abc123...","use_voice":false}'

# Step 3: wait for SMS on the 4G SIM, then verify
curl -X POST 'http://localhost:8085/v1/register/+14165551234/verify/123456'

# Step 4: confirm registration
curl http://localhost:8085/v1/accounts
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| signal-cli CLI via `child_process.exec` | signal-cli-rest-api HTTP daemon (json-rpc-native mode) | ~2022+ | 10-20x faster per send, language-agnostic caller, bidirectional receive possible |
| `latest-stable` Docker tag | `latest-dev` or pinned `0.2XX-dev` | Sometime 2025 [INFERRED from tag listing 2026-04-18] | Must pin a numbered tag or accept drift — `latest-stable` appears deprecated |
| `json-rpc` (JVM daemon) | `json-rpc-native` (GraalVM daemon) | ~2023+ | ~4× less RAM (80MB vs 300MB), same latency |
| Alerter-in-bridge (prior v1.3 research SUMMARY.md recommendation) | Alerter-as-separate-container (this phase D-01/D-02) | 2026-04-18 (user decision in CONTEXT.md) | Reference pattern for all future agents; supersedes prior SUMMARY.md recommendation |

**Deprecated/outdated:**
- `latest-stable` Docker tag reference in `.planning/research/STACK.md` v1.3 additions — Not currently present on Docker Hub [VERIFIED 2026-04-18]
- "alerter.js inside bridge" in `.planning/STATE.md` line 72 — superseded by CONTEXT.md D-01/D-02. The planner should disregard that STATE.md line.

## Alert Engine Specification

> This is where Claude's Discretion items 1–6 are resolved with concrete recommendations.

### §1 signal-cli-rest-api compose service

Recommended snippet for `docker-compose.override.yml`:

```yaml
  signal-cli:
    image: bbernhard/signal-cli-rest-api:0.200-dev
    environment:
      - MODE=json-rpc-native
    volumes:
      - signal-cli-data:/home/.local/share/signal-cli
    restart: unless-stopped
    # Internal-only per D-13 — no `ports:` binding to host.
    # Alerter talks to http://signal-cli:8080 on the compose default network.
    # NOTE: existing services (bridge, openmct, farmos-agent) all use network_mode: host.
    # signal-cli + alerter stay on the default compose bridge network so they can resolve each
    # other by service name AND signal-cli stays off the host/Tailscale network.

volumes:
  signal-cli-data:
```

**Critical networking note:** This is the one deviation from existing network topology. The override file currently puts every service on `network_mode: host`. For this phase:
- `alerter`: default compose network (so it can resolve `signal-cli` by service name per D-06)
- `signal-cli`: default compose network (internal-only per D-13)
- `alerter` reaches bridge via `ws://host.docker.internal:8081` on Linux (with `extra_hosts: ["host.docker.internal:host-gateway"]`) OR via `ws://<elder-plops-host-ip>:8081`.

The planner MUST decide this topology explicitly in a Wave 0 task. **Recommendation:** `extra_hosts: ["host.docker.internal:host-gateway"]` and `BRIDGE_WS_URL=ws://host.docker.internal:8081`. This is the cleanest bridge (host-network service) ↔ agent (compose-network service) pattern.

### §2 Detection Rules

#### §2.1 Pi-offline detection

**Recommendation:** Use bridge state, not direct Tailscale ping.

Detector fires when ANY of:
- Alerter WS has been disconnected from bridge for `>ALERT_PI_OFFLINE_MIN` minutes (default 5)
- Bridge `/health` (polled every 60s) returns `ros.connected=false` for `>ALERT_PI_OFFLINE_MIN` consecutive polls
- Bridge `/health.humidifier.last_msg_ts` is older than `ALERT_PI_OFFLINE_MIN` minutes

**Severity:** CRITICAL (the Pi being off means no control loop; the farm is unattended hardware).

**Why not direct Tailscale ping:** Duplicates work the bridge already does; adds a second signal that can disagree with bridge; if elder-plops ↔ Pi Tailscale is fine but bridge has a bug, alerter would report "Pi online" while no control data is flowing — wrong answer. Bridge is the vantage point (per D-03).

**Grace on alerter startup:** Do not fire Pi-offline in the first 60s after alerter boot (allows WS connection + `/health` poll to complete).

#### §2.2 Sensor ERROR detection

Detector fires when `sensor_health.level === 2` (ERROR) for `>30s` (consumed from bridge WS).

**Severity:** CRITICAL.

**Warm-up suppression (ALRT-05):** When `sensor_health.level === 1` (WARN, "warming up"), set `warming_up=true`. Suppress RH-OOB and humidifier-stuck detectors. Do NOT suppress sensor-ERROR itself (ERROR is ERROR even in warm-up).

**Source of truth:** `bridge/src/index.js:413-433` forwards `/fc1/sensor_health` to WS as `{sensor_health: {level, name, message, values}, timestamp}`. Alerter consumes this directly. TRANSIENT_LOCAL replay on the ROS side combined with `lastSensorHealthBroadcast` in bridge means alerter gets current state within 500ms of WS connect.

#### §2.3 RH out-of-band detection

Detector fires when `abs(humidity - ALERT_RH_TARGET) > ALERT_RH_BAND` for N consecutive samples (`ALERT_OOB_N`, default 5) AND total elapsed window ≥ `ALERT_OOB_WINDOW_MIN` minutes (default 3).

**Recommendation:** `ALERT_RH_TARGET=90`, `ALERT_RH_BAND=3`. Controller uses ±1% as its operational band; alerter alerts only when the system has failed to keep RH within ±3% for 3+ minutes. This asymmetry (alerter looser than controller) is intentional per Pitfall 2.

**Severity:** WARN.

**Warm-up suppression:** Yes (ALRT-05).

#### §2.4 Humidifier-stuck detection

**The tricky one.** The humidifier in simulation/real mode publishes `std_msgs/Bool` on `/fc1/actuators/humidifier` every tick. There is no "commanded vs observed" distinction on the bridge side — what the bridge sees is what the controller published (which is `get_humidifier_state()`, i.e. the actual GPIO state read-back in hardware mode).

Concrete rule (recommendation):

**Trigger:** `humidifier === 1` for `>ALERT_HUMIDIFIER_STUCK_MIN` minutes AND RH has not risen by more than 3% from when it turned on.

**Operationalization:**
- On humidifier `0 -> 1` transition, snapshot `rhAtOnStart = current_rh` and `onStartTs = now`.
- On every humidity message while humidifier is ON: if `(now - onStartTs) > stuckMin_ms` AND `(current_rh - rhAtOnStart) < 3.0`, fire PROBLEM.
- On humidifier `1 -> 0`: clear snapshot. Clears FIRING → RECOVERY automatically.

**Severity:** WARN (not CRITICAL — the farmer has time to investigate; not an immediate crop loss).

**Recommendation:** `ALERT_HUMIDIFIER_STUCK_MIN=30` minutes (aligns with `min_dwell_time=180s` × several cycles — if RH hasn't climbed after several full dwell windows, something's wrong). Initial cadence; expected to be tuned in Phase 20.

**Known edge cases (document, don't over-engineer):**
- Very low starting RH + tiny water in the humidifier tank → ON for 30+ minutes but RH doesn't rise. TRUE stuck. Alert correct.
- Bridge restart resets `rhAtOnStart` even if humidifier was already on. Accept the miss; heartbeat confirms alerter is alive.
- Humidifier cycles ON/OFF due to controller dwell → snapshot resets every cycle; stuck detector never trips in a healthy system.

### §3 State Machine

Per alert type: `{state, oobCount, firstOobAt, lastFiredAt, snoozedUntil}`.

States: `OK` | `PENDING` | `FIRING` | `SNOOZED`

Transitions:
- `OK -> PENDING`: first OOB event received. `oobCount=1`, `firstOobAt=now`.
- `PENDING -> PENDING`: further OOB events. `oobCount++`.
- `PENDING -> OK`: in-band event before `oobCount` reached threshold. Reset.
- `PENDING -> FIRING`: `oobCount >= ALERT_OOB_N` AND `(now - firstOobAt) >= ALERT_OOB_WINDOW_MIN`. Emit PROBLEM. Set `lastFiredAt=now`.
- `FIRING -> FIRING`: OOB events continue. Emit repeat only if `(now - lastFiredAt) > criticalCooldownMin` (for CRITICAL) or `> cooldownMin` (for WARN).
- `FIRING -> OK`: in-band event observed for `ALERT_OOB_N` consecutive samples (symmetric debounce). Emit RECOVERY with duration.
- `* -> SNOOZED`: on snooze command (§6). `snoozedUntil=now + duration`. Suppresses outbound sends but continues state tracking (so FIRING state is preserved through snooze).
- `SNOOZED -> *`: when `now > snoozedUntil`. Resume previous state; if still FIRING, repeat-alert cadence resumes.

**Severity tier repeat cadences (recommendation):**
- WARN: repeat every `cooldownMin` (default 30 min) while FIRING.
- CRITICAL: repeat every `criticalCooldownMin` (default 60 min) while FIRING. Counter-intuitive? Rationale: the farmer already knows — don't spam during the middle-of-the-night crisis. Tune in Phase 20.

### §4 Cadences (initial recommendations — ALL env-driven per ALRT-06)

| Setting | Default | Rationale |
|---------|---------|-----------|
| `ALERT_OOB_N` | 5 | Covers ~10-25s of SCD41 samples; shorter than bridge restart window |
| `ALERT_OOB_WINDOW_MIN` | 3 | Belt-and-suspenders — blocks sub-minute blip from firing even if sample rate changes |
| `ALERT_COOLDOWN_MIN` | 30 | Matches Phase 17 SUMMARY recommendation; 30min is "not yet annoying" |
| `ALERT_CRITICAL_COOLDOWN_MIN` | 60 | CRITICAL alerts don't need to repeat as fast; fewer reminders is better |
| `ALERT_PI_OFFLINE_MIN` | 5 | Tolerates Phase 14 ~9s stall recovery + bridge restarts; 5 min is "something is actually broken" |
| `ALERT_HUMIDIFIER_STUCK_MIN` | 30 | Several dwell cycles; below this it looks like normal control action |
| `ALERT_HEARTBEAT_HOUR` | 8 | 8am local farm time = farmer's morning check. Must be AFTER typical maintenance restart window (overnight). |
| Heartbeat check interval | 15 min | Tick checks "is it the heartbeat hour and haven't I sent today's?" |

**Farm timezone:** `TZ=America/Toronto` [VERIFIED: `docker-compose.yml:54-55` `farmos-agent` env]. Alerter must set `TZ=America/Toronto` in its environment and use `Intl.DateTimeFormat` for time-of-day decisions.

### §5 Signal Message Body Template

**Recommended format** (plain text, no markdown — Signal clients render Signal's own styling):

PROBLEM:
```
[PROBLEM · CRITICAL] FC-1 · Pi offline
Last seen: 14:23 EDT (12m ago)
Open: http://elder-plops-ts:8081/farmer
```

```
[PROBLEM · WARN] FC-1 · RH out of band
Now: 83.2% · target 90±3%
First OOB: 14:17 EDT (6m ago)
Open: http://elder-plops-ts:8081/farmer
```

RECOVERY:
```
[RECOVERY] FC-1 · RH back in band
Now: 89.6%
Was OOB for 12m 04s
Open: http://elder-plops-ts:8081/farmer
```

HEARTBEAT:
```
[HEARTBEAT] FC-1 watchdog alive
RH: 90.1%  ·  Temp: 23.1°C  ·  CO2: 812 ppm
Humidifier: OFF (cycled 14× in last 24h)
Pi last seen: 8 seconds ago
Last alert: RH OOB at 02:14 yesterday (recovered 02:19)
Open: http://elder-plops-ts:8081/farmer
```

**Design notes:**
- Severity prefix in square brackets so farmer's eye catches it first.
- Chamber ID (`FC-1`) always present — future-proofs for multi-chamber.
- One bare URL line — Signal auto-linkifies. No Markdown `[text](url)`.
- Timestamps in local TZ, 24h clock, with relative time ("12m ago") for cognitive ease.
- "Open:" as the link label — action-oriented, short.

### §6 Snooze Grammar

**Recommendation: strict grammar with one fuzzy fallback.**

```
snooze <alert-type> <duration>
```

Where:
- `<alert-type>` ∈ `rh`, `sensor`, `pi`, `humidifier`, `all`
- `<duration>` ∈ `30m`, `1h`, `2h`, `4h`, `8h`, `24h` (integer + unit: `m` or `h`, max 24h)

Examples:
- `snooze rh 4h` — mutes RH alerts for 4 hours
- `snooze all 8h` — mutes everything except heartbeat for 8 hours
- `snooze pi 1h`

**Fuzzy fallback:** If the farmer sends anything starting with "snooze" that doesn't parse, alerter replies with:
```
Sorry, didn't get that. Try: snooze rh 4h
Valid alert types: rh, sensor, pi, humidifier, all
Valid durations: 30m, 1h, 2h, 4h, 8h, 24h
```

**Rationale for strict grammar:** The farmer is typing on a phone in a humid chamber. A short, rigid grammar with a helpful error message beats "natural language" every time — cognitive load is zero once they've done it once.

**Snooze state:** Map `{[alertType]: snoozedUntilMs}` in alerter memory (D-07). Snooze survives alerter's own lifecycle only as long as the container doesn't restart. Container restart clears snoozes (acceptable — restart = farmer's been notified by the restart event, can re-snooze if needed).

**Heartbeat bypasses snooze** — `snooze all` does NOT suppress heartbeat. The heartbeat is the liveness signal; muting it defeats the entire point.

### §7 Environment Variable Inventory (ALRT-06)

All in `.env` at elder-plops repo root (same convention as `TIMESCALE_PASSWORD`, `CORS_ORIGIN`).

| Var | Default | Purpose |
|-----|---------|---------|
| `BRIDGE_WS_URL` | `ws://host.docker.internal:8081` | Bridge WS endpoint from inside alerter container |
| `BRIDGE_HEALTH_URL` | `http://host.docker.internal:8081/health` | Bridge REST health endpoint |
| `SIGNAL_API_URL` | `http://signal-cli:8080` | signal-cli-rest-api endpoint on compose network |
| `SIGNAL_SENDER` | (required) | Farmer's primary Signal number, registered on the 4G SIM. `+1XXXXXXXXXX` |
| `SIGNAL_RECIPIENT` | (required) | Alert destination — same as sender for self-alerts |
| `ALERT_RH_TARGET` | `90` | RH setpoint percent |
| `ALERT_RH_BAND` | `3` | ±percent outside which alerter fires |
| `ALERT_OOB_N` | `5` | Consecutive samples required to fire |
| `ALERT_OOB_WINDOW_MIN` | `3` | Minimum window for OOB to count |
| `ALERT_COOLDOWN_MIN` | `30` | WARN repeat cadence |
| `ALERT_CRITICAL_COOLDOWN_MIN` | `60` | CRITICAL repeat cadence |
| `ALERT_PI_OFFLINE_MIN` | `5` | Minutes of bridge/ROS absence before firing |
| `ALERT_HUMIDIFIER_STUCK_MIN` | `30` | Minutes ON without RH rise before firing |
| `ALERT_HEARTBEAT_HOUR` | `8` | Local-TZ hour for daily heartbeat (0-23) |
| `ALERT_RECEIVE_POLL_SEC` | `30` | Snooze receive-loop cadence |
| `ALERT_MAX_SENDS_PER_HOUR` | `20` | Defensive rate cap |
| `TZ` | `America/Toronto` | Farm timezone |
| `DASHBOARD_URL` | `http://elder-plops-ts:8081/farmer` | Link in every alert body |
| `LOG_LEVEL` | `info` | `debug`/`info`/`warn`/`error` |

### §8 Primary Registration Flow (one-time, pre-phase gate)

Pre-phase gate per ROADMAP.md Phase 17:
1. Confirm 4G router can route incoming SMS to the SIM (test: send SMS from a regular phone; observe it arrive at the router's SMS UI or forwarded to email). This is NOT in code — it's an ops check the farmer/operator does manually.
2. Bring up `signal-cli` container with `signal-cli-data` volume and port 8085 bound to `127.0.0.1`.
3. Obtain captcha token from https://signalcaptchas.org/registration/generate.html (human in a browser).
4. `POST /v1/register/+1XXXXXXXXXX` with captcha JSON body.
5. Retrieve SMS verification code from 4G router's SMS inbox.
6. `POST /v1/register/+1XXXXXXXXXX/verify/NNNNNN`.
7. `GET /v1/accounts` — confirms registration.
8. `POST /v2/send` with a test message to self — confirms bidirectional flow.

**Fallback path if the 4G SIM cannot receive SMS:** Use `use_voice=true` in the registration body (voice call with spoken code). If both fail, escalate to linked-device flow (farmer's phone scans QR), and document explicitly that the 45-day expiry mitigation (heartbeat) applies.

**Do NOT automate registration.** This is a one-time operator step. Document it in the phase's `RUNBOOK.md`.

### §9 Signal Session Hygiene

- Primary accounts: ~120-day re-verification cycle; `signal-cli-rest-api` handles this transparently as long as the daemon is running. Document the re-verification procedure (will require farmer to receive SMS again on 4G SIM).
- Heartbeat keeps account active; not strictly required for primary but cheap insurance.
- If a `/v2/send` call returns 500 with "account not registered" — container has lost state. Runbook: restore `signal-cli-data` volume from backup OR re-register.

### §10 Receive Loop Strategy

**Recommendation: Poll `GET /v1/receive/{sender}?timeout=1&ignore_attachments=true` every 30s from alerter.**

Why polling and not a persistent connection:
- signal-cli-rest-api doesn't expose a websocket receive endpoint [VERIFIED: README has only `/v1/receive`].
- `timeout=1` means the server holds the connection for up to 1 second waiting for a message; this is long-poll-like.
- 30s cadence keeps latency bounded (farmer's snooze takes effect within 30s) without hammering the daemon.

In `json-rpc-native` MODE, signal-cli keeps the receive socket to Signal servers always open. The REST `/v1/receive` call returns whatever has arrived since the last call — no messages are lost between polls. [VERIFIED: README §"Receive messages" + known behavior in `MODE=json-rpc-native`.]

### §11 signal-cli port selection

Existing host-ports in use:
- 8080: openmct
- 8081: bridge (HTTP + WS)
- 8082: FarmOS
- 5432: timescale (localhost only)

**Recommendation: `signal-cli` container binds `8080` INTERNALLY on the compose network** (no host publish per D-13). If a host-side debug binding is ever needed during registration, use `127.0.0.1:8085:8080` temporarily, then remove.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Docker Engine | Build/run alerter + signal-cli containers | ✓ | (matches existing deploy on elder-plops) | — |
| docker-compose | Compose file updates | ✓ | v1.29 on elder-plops [per memory `project_compose_v2_upgrade.md`] | Must use `docker-compose` (v1 syntax); deploy still works with `up -d --build` |
| Node.js 20 (in container) | Alerter runtime | ✓ (via `node:20-alpine` pull) | 20 LTS | — |
| Internet outbound (Docker Hub) | Pull `bbernhard/signal-cli-rest-api:0.200-dev` | ✓ (elder-plops has internet) | — | Mirror image locally if pulls flake |
| 4G SIM inbound SMS | Signal primary registration | **✗ unverified** | — | `use_voice=true`; or linked-device flow + 45-day heartbeat discipline |
| Signal network reachability | `signal-cli-rest-api` connects to Signal servers | ✓ (elder-plops has internet) | — | — |

**Missing dependencies with no automated fallback:**
- 4G SIM SMS reception — this is the pre-phase gate. The plan must block on it.

**Missing dependencies with fallback:**
- Voice registration is a documented alternative to SMS.

## Validation Architecture

> nyquist_validation is enabled (config absent → treat as enabled).

### Test Framework

| Property | Value |
|----------|-------|
| Framework | Node.js built-in `node --test` (Node 20) + `node:test` assertions |
| Config file | None needed — `node --test test/*.test.js` runs all |
| Quick run command | `cd src/agents/alerter && node --test test/` |
| Full suite command | `cd src/agents/alerter && node --test test/ && node -e "require('./src/config').validate()"` |

**Why `node --test` and not jest/mocha:** Zero dependency, built into Node 20, fast, sufficient for a ~400 LOC agent. Follows the "don't add deps that aren't pulling weight" principle that bridge already embodies.

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| ALRT-01 | signal-cli-rest-api is reachable and registered | smoke (manual) | `curl http://localhost:8085/v1/accounts \| grep "+1"` on elder-plops | ❌ Wave 0 |
| ALRT-01 | Primary number can send a test message | smoke (manual, human-attested) | Runbook step "send test — farmer confirms receipt on phone" | ❌ Wave 0 (runbook) |
| ALRT-02 | Four alert types fire PROBLEM + RECOVERY | unit (state machine) | `node --test test/state.test.js` — simulated events for each alert type | ❌ Wave 0 |
| ALRT-02 | Every PROBLEM produces exactly one RECOVERY | unit (invariant) | `node --test test/state.test.js --test-name-pattern=recovery_exactly_once` | ❌ Wave 0 |
| ALRT-03 | Dedup: N≥5 consecutive OOB before firing | unit | `node --test test/rules.test.js --test-name-pattern=debounce` | ❌ Wave 0 |
| ALRT-03 | Cooldown suppresses repeat same-type alerts | unit | `node --test test/state.test.js --test-name-pattern=cooldown` | ❌ Wave 0 |
| ALRT-03 | Severity tiers (WARN/CRITICAL) have distinct cadences | unit | `node --test test/state.test.js --test-name-pattern=severity` | ❌ Wave 0 |
| ALRT-04 | Heartbeat fires daily at configured TZ hour | unit | `node --test test/state.test.js --test-name-pattern=heartbeat` (inject fake clock) | ❌ Wave 0 |
| ALRT-04 | Heartbeat fires on real stack | smoke (observation) | Wait 24h after deploy; human attests receipt. Fallback: temporarily set `ALERT_HEARTBEAT_HOUR` to current+1 and observe. | ❌ Wave 0 (runbook) |
| ALRT-05 | No alert during sensor warm-up (first 20s after fc-core restart) | integration | Runbook: `ssh fc1 'systemctl restart fc-core'` then `grep ALERT_SEND /var/log/docker/alerter-*.log` in next 25s → expect zero | ❌ Wave 0 (runbook + log-grep script) |
| ALRT-06 | All thresholds env-var configurable | unit | `node --test test/config.test.js` — verify `config.js` reads every env var and applies default | ❌ Wave 0 |
| ALRT-06 | Changing threshold requires only compose rebuild | smoke | Runbook: edit `.env`, `docker compose up -d alerter`, observe log `[config] ALERT_RH_TARGET=92` | ❌ Wave 0 (runbook) |
| ALRT-07 | Signal reply `snooze rh 4h` mutes RH alerts | integration (manual) | Runbook: farmer sends snooze, operator forces RH spike on Pi, no alert for 4h, alert resumes after | ❌ Wave 0 (runbook) |
| ALRT-07 | Invalid snooze message gets helpful reply | unit | `node --test test/snooze.test.js --test-name-pattern=fuzzy_fallback` | ❌ Wave 0 |
| ALRT-08 | Every alert body contains dashboard link | unit | `node --test test/message.test.js --test-name-pattern=dashboard_link` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `cd src/agents/alerter && node --test test/`
- **Per wave merge:** Full suite + lint + `docker build` of alerter image
- **Phase gate:** All unit tests green + runbook items 1-01 through 1-07 (the smoke/integration ones marked manual) completed with human attestation logged in VERIFICATION.md. **Hard gate:** human-attested end-to-end Signal delivery to farmer's real phone (per Pitfalls doc line 332: "Not a signal-cli exit-code 0 test — a human reads the message on their phone.")

### Wave 0 Gaps

- [ ] `src/agents/alerter/package.json` — declare deps (ws, pg)
- [ ] `src/agents/alerter/src/config.js` — env-var parsing + defaults + validation
- [ ] `src/agents/alerter/src/state.js` — pure state machine with exported `transition()`
- [ ] `src/agents/alerter/src/rules.js` — pure detection predicates
- [ ] `src/agents/alerter/src/signal.js` — HTTP client (send + receive) with timeout
- [ ] `src/agents/alerter/src/index.js` — WS connect, tick loops, wire-up
- [ ] `src/agents/alerter/test/state.test.js` — covers ALRT-02, ALRT-03, ALRT-04 unit paths
- [ ] `src/agents/alerter/test/rules.test.js` — covers ALRT-03 debounce
- [ ] `src/agents/alerter/test/snooze.test.js` — covers ALRT-07 grammar
- [ ] `src/agents/alerter/test/message.test.js` — covers ALRT-08
- [ ] `src/agents/alerter/test/config.test.js` — covers ALRT-06
- [ ] `src/agents/alerter/Dockerfile` — `FROM node:20-alpine`, install, run
- [ ] `src/agents/alerter/README.md` — runbook (registration, deploy, snooze usage)
- [ ] `docker-compose.override.yml` — add `alerter` + `signal-cli` services, `signal-cli-data` volume
- [ ] `.env.example` — document all new vars (existing convention: none exists — add one, or just document in alerter README)
- [ ] `.gitignore` — add `src/agents/*/node_modules/`

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | signal-cli-rest-api registration is primary authentication to Signal; no alerter→bridge auth (trust boundary per existing CORS model) |
| V3 Session Management | yes | signal-cli daemon maintains a long-lived session to Signal; state in `signal-cli-data` volume |
| V4 Access Control | yes | signal-cli-rest-api is internal-only on compose network (D-13); alerter reaches bridge over WS (trusted) |
| V5 Input Validation | yes | Snooze grammar parser must handle arbitrary farmer input — must not eval, must cap duration, must whitelist alert types |
| V6 Cryptography | indirect | Signal protocol handles E2E — never hand-roll. Alerter only speaks plain HTTP to signal-cli daemon (local network) |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Injection via snooze message | Tampering | Whitelist `[a-z]+` for alert type, `\d{1,3}[mh]` for duration, `.test()` before parse; reject everything else |
| Unbounded send rate (self-DoS via flap) | Denial-of-service | Hourly send cap (`ALERT_MAX_SENDS_PER_HOUR=20`) + debounce |
| Leaked Signal number in logs | Info Disclosure | Mask `SIGNAL_SENDER` to `+1XXXXXX1234` in any log line that includes it |
| signal-cli data volume on shared host | Info Disclosure | Named Docker volume (not bind mount) keeps state outside working directory; not committed to git |
| signal-cli-rest-api exposed to network | Elevation of Privilege | Internal-only per D-13 — no host port binding |
| Alerter impersonating bridge data | Tampering | Alerter is read-only consumer of bridge; bridge is not modified by this phase |

## Project Constraints (from CLAUDE.md)

- **Build tool:** colcon for ROS packages; this phase adds Node code only (no ROS package), so colcon is not touched.
- **docker-compose v1** on elder-plops per `project_compose_v2_upgrade.md` memory; syntax compatible.
- **Rebuild pattern:** `docker compose up -d --build bridge` — for this phase, `docker compose up -d --build alerter signal-cli`.
- **`.env` required:** `TIMESCALE_PASSWORD`, `CORS_ORIGIN`. New required vars: `SIGNAL_SENDER`, `SIGNAL_RECIPIENT`.
- **Compose file layout:** `/docker-compose.yml` + `/docker-compose.override.yml` at repo root. Override is where farm-specific (production-only) concerns live — signal-cli belongs in override per D-11.
- **Deploy method:** `git push fc1/prod` is for Pi ONLY. This phase deploys on elder-plops via `docker compose up -d --build alerter signal-cli` (no Pi changes).
- **Signal is the farm's notification channel** per memory `project_signal_alerts.md`.
- **Call it "Mission Control"** in docs/conversation per memory `feedback_naming.md`.
- **No `Co-Authored-By`** on commits per memory `feedback_no_coauthor.md`.
- **SSH fc1 via Tailscale `fc1-ts`** if Pi debugging becomes necessary (it shouldn't for this phase).
- **Gap over noise** (memory `feedback_gap_over_noise.md`) — when unsure whether the system is actually in an alert state, do not fire. Silence + missing heartbeat is better than a false alarm.

## Assumptions Log

> Every claim below is tagged `[ASSUMED]` in prior research and has NOT been verified against live soak data. The planner and discuss-phase should confirm with the farmer or treat as Phase 20 tuning targets.

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `ALERT_RH_BAND=3` (loose enough to beat sensor noise, tight enough to catch real excursions) | §2.3 | Too tight → flap-storm anyway; too loose → real problems missed. Tune in Phase 20. |
| A2 | `ALERT_HUMIDIFIER_STUCK_MIN=30` with "RH not risen by 3%" as the rule | §2.4 | Too aggressive → false-positive during slow recovery from a large disturbance; too lax → genuine stuck humidifier not alerted for hours. Tune in Phase 20. |
| A3 | `ALERT_PI_OFFLINE_MIN=5` tolerates Phase 14 ~9s stall and bridge restart | §2.1 | Too short → false Pi-offline on every bridge rebuild; too long → real Pi crashes silently for >5min. |
| A4 | `ALERT_HEARTBEAT_HOUR=8` is the right morning-check time for the farmer | §4 | Farmer prefers 7am or 6am. Cheap to change (env var). |
| A5 | Primary registration on 4G SIM is feasible (SMS delivery works) | §8 | Fails → fall back to `use_voice=true` → then to linked-device. Pre-phase gate must verify. |
| A6 | `json-rpc-native` MODE supports reliable `/v1/receive` at 30s cadence | §10 | If not, snooze lag > 30s; functional but poor UX. Worst case: poll every 10s. |
| A7 | Alerter on compose bridge network + `host.docker.internal:host-gateway` can reach host-network-mode bridge service at `ws://host.docker.internal:8081` | §1 | Needs validation in Wave 0; fallback is `network_mode: host` for alerter (but then signal-cli service-name DNS breaks, so signal-cli would also need host mode + a host port, violating D-13). Networking topology is the single highest-risk Wave 0 item. |
| A8 | Primary Signal account re-verification cycle is ~120 days | §9 | If shorter, may need quarterly re-registration runbook. Farmer impact is low (runbook step). |
| A9 | `latest-stable` Docker tag deprecation is permanent, not a temporary hub.docker.com display glitch | Stack | If `latest-stable` returns, could unpin. Low-impact — pinning is the safer default regardless. |
| A10 | WARN alerts should repeat every 30min, CRITICAL every 60min (CRITICAL slower) | §3 | Counter-intuitive; farmer may prefer faster CRITICAL. Tune in Phase 20. |

## Open Questions

1. **Networking topology for alerter container.** (A7 above.)
   - What we know: Existing services are all `network_mode: host`. signal-cli must NOT be on host (D-13). So alerter + signal-cli are on compose's default bridge network. But bridge (the WS source) is host-mode, so alerter can't resolve `bridge` by service name.
   - What's unclear: Is `host.docker.internal:host-gateway` the cleanest path on Linux (elder-plops is Ubuntu), or should alerter also be host-mode and call signal-cli via `127.0.0.1:PORT` on a host-bound port?
   - Recommendation: Try `extra_hosts: ["host.docker.internal:host-gateway"]` first as a Wave 0 task. If it doesn't work (older Docker versions), pivot to host-mode alerter + internal-only signal-cli via a single shared compose network with an explicit `networks:` block. Plan must acknowledge this fork.

2. **Should the alerter send a "startup" Signal on first boot after a fresh deploy?**
   - Pro: Confirms registration + delivery end-to-end with human attestation.
   - Con: Noise on every `docker compose up -d --build alerter`. Could be annoying during development.
   - Recommendation: Yes for v1 via an explicit flag: send once on first-boot-after-registration (detect by absence of a marker file in `signal-cli-data` volume). Phase planner decides.

3. **Does the alerter need to emit a ROS topic or Timescale row when it sends a Signal?**
   - Not required by ALRT-01..08. Out of scope for Phase 17.
   - Logs in stdout are enough; `docker logs alerter` is the audit trail. Mention only as deferred candidate for Phase 20 Timescale `alerts` table.

4. **Heartbeat format: should it include "flag it" or "snooze all 24h" hints?**
   - v1 answer: keep heartbeat minimal (see §5). Adding hints inflates the message and might confuse. If the farmer asks for it in live usage, add in Phase 20.

## Sources

### Primary (HIGH confidence)
- `src/mission-control/bridge/src/index.js` — live code; bridge WS broadcasts, `lastSensorHealthBroadcast`, humidifier QoS, `/health`
- `src/mission-control/bridge/package.json` — `ws`, `pg`, `express` versions
- `src/chambers/fc-core/config/fc_config.yaml` — `target_humidity=0.90`, `humidity_tolerance=0.01`, `startup_grace_period=20.0`
- `src/chambers/fc-core/fc_core/fc_controller.py` — `DiagnosticStatus` publication shape (OK=0, WARN=1, ERROR=2), warm-up state
- `docker-compose.yml` + `docker-compose.override.yml` — service topology, `network_mode: host` pattern, `TZ=America/Toronto`
- `.planning/phases/17-alert-engine-signal/17-CONTEXT.md` — locked decisions D-01..D-13
- `.planning/REQUIREMENTS.md` — ALRT-01..ALRT-08 spec
- `.planning/research/PITFALLS.md` — v1.0–v1.2.1 lessons (flap-storm, missing recovery, alert-bot-dies-silently)
- `.planning/research/STACK.md` v1.3 additions — signal-cli-rest-api API shape + MODE options
- [ws npm README](https://www.npmjs.com/package/ws) — WebSocket client API

### Secondary (MEDIUM confidence)
- [bbernhard/signal-cli-rest-api README (github)](https://github.com/bbernhard/signal-cli-rest-api) — verified 2026-04-18 for MODE options, `/v2/send`, `/v1/receive`, volume path
- [Docker Hub: bbernhard/signal-cli-rest-api tags](https://hub.docker.com/r/bbernhard/signal-cli-rest-api/tags) — verified 2026-04-18; `latest-stable` NOT present, pin `0.200-dev`
- [signalcaptchas.org](https://signalcaptchas.org/registration/generate.html) — captcha source for primary registration
- Signal support docs (support.signal.org) — linked-device 45-day expiry, primary ~120-day re-verification

### Tertiary (LOW confidence — flagged for Phase 20 validation)
- Initial cadence values (A1, A2, A3, A4, A10 in Assumptions Log) — based on prior research + memory, not live soak data

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all deps verified in live `bridge/package.json` or Docker Hub
- Architecture: HIGH — enforced by locked CONTEXT.md decisions; only open question is container networking topology (A7)
- Detection rules: MEDIUM — structurally sound (based on current bridge WS shape), initial cadence values are recommendations not guarantees
- Signal integration: MEDIUM — API verified from README; primary registration flow not personally executed in this session (operator will during pre-phase gate)
- Pitfalls: HIGH — drawn from v1.0–v1.2.1 live production history

**Research date:** 2026-04-18
**Valid until:** 2026-05-18 (30 days — signal-cli-rest-api Docker tags churn weekly; re-verify tag pin at Phase 20 entry)
