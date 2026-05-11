# Phase 29: Alerter mode awareness + cooldown tuning — Research

**Researched:** 2026-05-08
**Domain:** Alerter (Node.js/Jest), Bridge (rclnodejs/WS), fc_controller (rclpy), Mode plumbing
**Confidence:** HIGH (all claims verified against the live tree at HEAD; CONTEXT.md decisions D-01..D-09 are locked and frame the work)

## Summary

Phase 29 is a focused, surgical job across three already-shipped subsystems:

1. **Bridge (`src/mission-control/bridge/src/index.js`)** — add three ROS subscriptions (`/fc1/control/current_mode`, `/fc1/control/alerter_mode_overrides`, `/fc1/control/alerter_globals`) using the *exact* `humidifierQos` profile already defined at line 736 (TRANSIENT_LOCAL/RELIABLE/depth=1), forward each as a typed WS payload via the existing `broadcast(...)` helper at line 607, and cache the latest of each for on-connect replay using the same `lastSensorHealthBroadcast` pattern at lines 588-598.
2. **Alerter (`src/agents/alerter/src/`)** — add `currentMode`/`alerterModeOverrides`/`alerterGlobals` cache slots in the `onMessage` switch at `index.js:115-138`; gate `isRhOob` and `isHumidifierStuck` in `rules.js` on a freshness-state derived from `wsConnected` + cache age (D-03); extend `formatProblem` for `alertType==='pi'` to include the last-known summary (D-04 / 999.39); reset in-progress dedup windows on mode swap in `state.js` (D-09).
3. **Controller (`src/chambers/fc-core/fc_core/fc_controller.py`)** — declare `modes.{fruiting,pinning}.alerter.*` ROS params (Tier B), declare global Tier C params (`pi_offline_min` etc.), add two new TRANSIENT_LOCAL publishers using the existing `actuator_qos` profile at line 154, extend `_validate_params` at line 434 with new dotted-key invariants, and republish the new topics from the same next-tick drain mechanism (`_pending_current_mode_republish`) used today for `current_mode`.
4. **Tuning (`29-COOLDOWN-TUNING.md`)** — one-shot offline analysis. Confirmed via grep: `alert_history` table does NOT exist anywhere in the repo (no `*.sql` schema files, no `CREATE TABLE` matches). The fallback path from D-07 — `docker logs mushy-alerter` parsed offline — is the *only* path.

**Primary recommendation:** Mirror the Phase 27 telemetry-trio pattern verbatim for the new bridge subscriptions, and the Phase 16.1 `lastSensorHealthBroadcast` pattern verbatim for on-connect replay. Two existing, working precedents already encode every QoS, cache, and replay invariant the planner needs.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Bridge subscribes to `fc1/control/current_mode` (TRANSIENT_LOCAL/RELIABLE/depth=1, matching publisher QoS) and re-broadcasts the full `Mode` payload as a typed WS message to all clients (alerter included). Alerter `bridge-client.js` caches latest mode in module state alongside existing per-topic caches. No new HTTP endpoint, no flat scalar topics.
- **D-02:** Bridge re-broadcasts `current_mode` on every received message AND on each new WS client connection (replay last cached value to a freshly-connecting client). Alerter cold-start gets the active mode within one bridge handshake; no need for the alerter to query an HTTP endpoint at startup.
- **D-03:** Three-state freshness model for mode-driven RH alerts:
  1. **Mode known and fresh** (cached `current_mode` ≤ `mode_stale_min` old, default 5 min, AND `wsConnected === true`) → use cached `target_humidity` ± `band_*` for RH-OOB rule.
  2. **Mode known but WS disconnected OR fc1 sensor topic stale** → suspend RH-band rules entirely AND suspend humidifier-stuck rule. Last-known mode kept in cache for diagnostic message bodies. Pi/sensor-offline rules still fire.
  3. **Mode never received** (cold start before first `current_mode` arrives) → fall back to env defaults `ALERT_RH_TARGET` / `ALERT_RH_BAND` for a bounded grace window (default 60s after WS handshake), then transition to state 2 if still no mode. Env defaults remain in `config.js` as the bootstrap-only backstop.
- **D-04:** Bundle 999.39 into Phase 29. Same module (`rules.js`, `message.js`), same liveness inputs (`wsConnected`, `humidifierLastMsgTs`), same WS-cache invariants. Concretely:
  - Gate `isHumidifierStuck` on `wsConnected === true` AND `humidifierLastMsgTs` fresh ≤ `humidifierStaleMin` (default = `sensorOfflineMin`); suppress when stale.
  - Audit `isRhOob` for the same offline-blind class; gate by D-03 freshness state.
  - Extend `formatProblem` for `alertType === 'pi'` to include last-known summary (humidifier ON/OFF, RH%, T°C, wallclock of last sample).
- **D-05:** Three-tier classification of `src/agents/alerter/src/config.js` env vars:
  - **Tier A (Mode-driven):** `target_humidity`, `band_low`, `band_high` — already in Phase 28 schema. **No new fields added to `Mode.msg`.**
  - **Tier B (Per-mode alerter overrides):** `humidifier_stuck_min`, `oob_n`, `oob_window_min`, `cooldown_min`, `critical_cooldown_min` — NEW optional fields under `fc_config.yaml` `modes.{name}.alerter.*`.
  - **Tier C (Global runtime-tunable):** `pi_offline_min`, `sensor_offline_min`, `heartbeat_hour`, `max_sends_per_hour`.
  - **Tier D (Env-only):** `BRIDGE_*`, `SIGNAL_*`, `TZ`, `DASHBOARD_URL`, `LOG_LEVEL`, `TIMESCALE_*`, `ANTHROPIC_API_KEY`, `WHISPER_URL`, `CAPTURE_*`, `ALERT_RECEIVE_POLL_SEC`.
- **D-06:** Tier B + Tier C delivery channel — two NEW TRANSIENT_LOCAL topics owned by `fc_controller`:
  - `fc1/control/alerter_mode_overrides` (per-mode alerter knobs, republished on mode swap)
  - `fc1/control/alerter_globals` (Tier C globals, republished on param change)
  - Both subscribed by bridge → broadcast on WS → cached by alerter (same pattern as D-01).
- **D-07:** Tuning data source — offline analysis of Timescale `alert_history` table OR alerter docker logs (≥14 days). Deliverable: `29-COOLDOWN-TUNING.md`. **Verified `alert_history` does NOT exist** → docker-logs fallback is the actual path.
- **D-08:** Tuned values land in `fc_config.yaml` `modes.{name}.alerter.*` block (Tier B), not `.env`. Old `.env` values stay as bootstrap fallback (D-03 state 3) and Tier C deploy-time defaults.
- **D-09:** On mode swap, alerter immediately re-evaluates rules against the new mode's `target_humidity`/`band_*`/`oob_*`/`cooldown_*`. In-progress dedup windows are RESET. Cooldowns already-fired stay tracked by `alertType` (NOT keyed by mode).

### Claude's Discretion
All five gray areas delegated to Claude's discretion at discuss-phase. Most reversible later: D-07 (analysis methodology), D-08 (where tuned values land), D-09 (cooldown carry-over semantics). Least reversible: D-01/D-06 (WS-broadcast plumbing pattern).

### Deferred Ideas (OUT OF SCOPE)
- Alerter writes to Timescale `alert_history` table (would let D-07 use SQL).
- 999.35 alerter self-pathology meta-watchdog / daily maintenance digest.
- Per-rule custom freshness thresholds (e.g. `humidifier_stale_min` distinct from `sensor_offline_min`).
- Cooldowns keyed by `(alertType, mode)` instead of just `alertType`.
- Time-of-day mode scheduling (Phase 30).
- Forcing modes (Phase 31).
- Any controller-side change to `current_mode` shape — Phase 28 schema is locked.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ALRT-08 | Alerter reads RH target + band from `current_mode` (or controller-published equivalents) instead of static env vars; closes 999.22. | D-01/D-02 plumbing pattern (Bridge §1, Alerter §2). Tier A in D-05. Existing `_publish_current_mode` at fc_controller.py:404 already emits the payload. |
| ALRT-09 | Sweep `config.js` for farmer-meaningful knobs and route them through Phase 28 dynamic source. | D-05 tier classification + D-06 two new topics. Knob inventory in §"`config.js` Tier Audit" below. |
| ALRT-10 | Tune cooldown thresholds against ≥14 days of Phase 17+ data. | D-07/D-08 tuning analysis recipe in §"Tuning Data Access". Confirmed alerter is WS-only — docker-logs is the data source. |

Bundled per D-04: backlog 999.39 (offline-blindness in `rules.js` + last-known summary in pi-offline message).
</phase_requirements>

## Project Constraints (from CLAUDE.md)

- **Build system:** colcon for ROS packages; `colcon build --symlink-install` for Python development.
- **Branch strategy:** `fc1/prod` is the deploy gate for Pi-side changes; `main` for elder-plops services. Memory `feedback_deploy_method` confirms.
- **Naming:** Refer to OpenMCT as "Mission Control" in conversation/docs.
- **Bridge rebuild requirement:** When modifying `src/mission-control/bridge/`, *always* `docker-compose up -d --build bridge` — `up -d` alone reuses cached image.
- **Live compose is repo-root, not src/.** `/docker-compose.yml` + `/docker-compose.override.yml` is the production target.
- **Diff repo vs Pi systemd before committing** (memory `feedback_diff_repo_vs_pi_systemd`) — alerter unit is a Docker compose service so this primarily applies to fc_controller deployment.
- **No Co-Authored-By** on commits.
- **SSH to fc1 via `wg0` (172.16.10.5)**; Tailscale path stale post-v1.5.0.1.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Mode source-of-truth | fc_controller (rclpy on Pi) | — | Phase 28 D-13/D-14 already locks this. |
| Per-mode alerter overrides param storage | fc_controller (rclpy on Pi) | — | Lives in fc_config.yaml; declared in fc_controller; published via TRANSIENT_LOCAL ROS topic per D-06. Co-locating with mode params keeps the validator (`_validate_params`) as single source of truth. |
| WS fan-out + on-connect replay | Bridge (Node.js, elder-plops) | — | Existing `humidifierQos` + `lastSensorHealthBroadcast` pattern is the template. Bridge is the only WS server in the stack. |
| Freshness gating + dedup-on-mode-swap | Alerter (Node.js, elder-plops) | — | All alert decisions are in the alerter — controller doesn't know what an "alert" is. |
| Cooldown tuning analysis (one-shot) | Operator (offline shell) | Alerter (consumes new defaults) | No runtime component; output is a fc_config.yaml diff + a markdown note. |
| Tuning data source | docker logs `mushy-alerter` | (deferred: Timescale `alert_history`) | Confirmed: alerter never writes to Timescale. Memory `project_alerter_is_ws_only` is correct. |

## Standard Stack

### Core (already installed — no new deps)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `ws` | ^8.16.0 | WebSocket client (alerter) and server (bridge) | Already wired. `[VERIFIED: src/agents/alerter/package.json + bridge package.json]` |
| `rclnodejs` | (per bridge package.json) | ROS2 Node.js client for bridge subscriptions | Existing humidifier/sensor_health subscriptions use it. `[VERIFIED: bridge index.js:264, 736]` |
| `rclpy` | ROS2 Jazzy stock | Controller param + topic + service primitives | Phase 28 ships on it. `[VERIFIED]` |
| `jest` | ^29.7.0 | Test runner for alerter | All existing alerter tests use it. `[VERIFIED: package.json]` |
| `pytest` | (ROS2 standard) | Test runner for fc_controller | Phase 28 plans 03/04 are pytest-based. `[VERIFIED]` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `node-cron` | ^4.0.0 | Used by capture-retention; not relevant to Phase 29. | — |
| `pg` | ^8.20.0 | TimescaleDB client (used by capture pipeline only). | — for Phase 29; alerter is WS-only for alert decisions. |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Two new TRANSIENT_LOCAL topics (D-06) | Extending `Mode.msg` | Rejected per D-05 — Phase 28 schema is locked, schema change would force coordinated controller+bridge+alerter+OpenMCT redeploy. |
| Two new TRANSIENT_LOCAL topics (D-06) | New HTTP endpoint on bridge | Rejected per D-01 — alerter is WS-only by design (memory `project_alerter_is_ws_only`); HTTP poll would invent a new pattern. |
| Re-using `current_mode` for Tier B | Adding `humidifier_stuck_min` etc. fields to `Mode.msg` | Same as above. Tier B is per-mode; the *delivery* is independent of `Mode.msg`. |

**Installation:** No new package installs.

**Version verification:** `[VERIFIED: src/agents/alerter/package.json]` — `ws@^8.16.0`, `jest@^29.7.0`, `node-cron@^4.0.0`, `pg@^8.20.0`. Last-modified per `git log` shows package.json untouched in Phase 28; no drift expected.

## Architecture Patterns

### System Architecture Diagram

```
┌─────────────────── fc1 (Pi, ROS2 Jazzy) ───────────────────┐
│                                                             │
│  fc_config.yaml ── declare_parameters ──┐                   │
│  modes.fruiting.alerter.cooldown_min    │                   │
│  modes.pinning.alerter.oob_n            ▼                   │
│  pi_offline_min, sensor_offline_min    fc_controller        │
│                                         │                   │
│   ┌─ on_set_parameters_callback ◄──┐    │                   │
│   │  (atomic batch validate)       │    │                   │
│   │  + queue republish             │    │                   │
│   └────────────────────────────────┘    │                   │
│                                         ▼                   │
│  ┌──── 3 publishers (TRANSIENT_LOCAL/RELIABLE/depth=1) ───┐ │
│  │  /fc1/control/current_mode            (Mode msg)      │ │
│  │  /fc1/control/alerter_mode_overrides  (Mode-shaped or │ │
│  │                                        std_msgs/json) │ │
│  │  /fc1/control/alerter_globals         (std_msgs/json) │ │
│  └───────────────────────────────────────────────────────┘ │
└─────────────────────────────┬───────────────────────────────┘
                              │ DDS over wg0
                              ▼
┌─────────────────── elder-plops (Docker stack) ──────────────┐
│                                                             │
│  bridge container (rclnodejs)                               │
│   ┌── 3 createSubscription calls (humidifierQos profile)─┐  │
│   │  on msg → cache lastModeBroadcast / lastOverrides /  │  │
│   │           lastGlobals; broadcast(payload)            │  │
│   └──────────────────────────────────────────────────────┘  │
│   wss.on('connection', (ws) => {                            │
│     replay lastSensorHealthBroadcast (existing)             │
│     replay lastModeBroadcast       (NEW)                    │
│     replay lastAlerterOverrides    (NEW)                    │
│     replay lastAlerterGlobals      (NEW)                    │
│   })                                                        │
│                          │                                  │
│                          ▼ WebSocket                        │
│  alerter container (Node.js)                                │
│   bridge-client.js — onMessage routes to:                   │
│     msg.current_mode      → applyEvent('mode_update')       │
│     msg.alerter_overrides → applyEvent('overrides_update')  │
│     msg.alerter_globals   → applyEvent('globals_update')    │
│                          │                                  │
│                          ▼                                  │
│   state.js — transition()                                   │
│     'mode_update': RESET in-progress dedup (D-09); store    │
│                    new effective config; mark mode-fresh.   │
│     'overrides_update': merge into effective config.        │
│     'globals_update': merge into effective config.          │
│                          │                                  │
│                          ▼                                  │
│   rules.js — isRhOob / isHumidifierStuck                    │
│     gate by freshness state (D-03):                         │
│       fresh    → use cached target/band                     │
│       stale    → return false (suspend rule)                │
│       cold     → use env fallback (≤60s)                    │
│                          │                                  │
│                          ▼                                  │
│   message.js — formatProblem(alertType==='pi')              │
│     append last-known: humidifier ON/OFF, RH%, T°C, wallclock│
└─────────────────────────────────────────────────────────────┘
```

**Trace (RH-OOB happy path):** Pi senses RH 88% → publishes `/fc1/humidity` → bridge subscribes (line 658-670) → broadcasts `{humidity: 88}` → alerter `onMessage` (index.js:118) → `applyEvent('humidity')` → `state.transition` calls `isRhOob(88, effectiveConfig)` where `effectiveConfig.rhTarget` came from cached `current_mode` (NOT env). If freshness state is "stale", `isRhOob` short-circuits to `false` regardless of value.

### Recommended Project Structure (existing — no relocation)
```
src/
├── chambers/
│   ├── fc-core/fc_core/fc_controller.py    # +Tier B/C param decl, +2 publishers, +validator extension
│   ├── fc-core/config/fc_config.yaml       # +modes.{name}.alerter.* + global Tier C defaults
│   └── fc-msgs/msg/Mode.msg                # UNTOUCHED (D-05)
├── mission-control/bridge/src/index.js     # +3 subscriptions, +3 cache slots, +on-connect replay
└── agents/alerter/src/
    ├── config.js                            # narrow `.env` to Tier D only; Tier A/B/C move to runtime
    ├── bridge-client.js                     # UNTOUCHED at the WS-transport layer (msgs flow through onMessage already)
    ├── rules.js                             # +freshness gating in isRhOob, isHumidifierStuck
    ├── message.js                           # +last-known summary in formatProblem(alertType='pi')
    ├── state.js                             # +mode_update/overrides_update/globals_update event types; +D-09 dedup reset
    └── index.js                             # +event-routing branches in onMessage switch
```

### Pattern 1: Bridge ROS subscription + WS broadcast + on-connect replay
**What:** The single end-to-end pattern for getting a TRANSIENT_LOCAL ROS topic to a fresh WS client.
**When to use:** Every one of the 3 new topics (D-01 + D-06).
**Example (verified, lifted verbatim from index.js:735-846 with topic name swapped):**
```javascript
// Verified at src/mission-control/bridge/src/index.js:735-743 — REUSE THIS QOS as-is.
const humidifierQos = new rclnodejs.QoS(
    rclnodejs.QoS.HistoryPolicy.RMW_QOS_POLICY_HISTORY_KEEP_LAST,
    1,
    rclnodejs.QoS.ReliabilityPolicy.RMW_QOS_POLICY_RELIABILITY_RELIABLE,
    rclnodejs.QoS.DurabilityPolicy.RMW_QOS_POLICY_DURABILITY_TRANSIENT_LOCAL,
    rclnodejs.QoS.LivelinessPolicy.RMW_QOS_POLICY_LIVELINESS_SYSTEM_DEFAULT,
    false
);

// NEW for Phase 29 — modeled after sensor_health (index.js:825-846)
let lastModeBroadcast = null;     // module scope alongside lastSensorHealthBroadcast (line 590)

node.createSubscription(
    'fc_msgs/msg/Mode',
    '/fc1/control/current_mode',
    { qos: humidifierQos },
    (msg) => {
        const payload = {
            current_mode: {
                name:             msg.name,
                target_humidity:  msg.target_humidity,
                band_low:         msg.band_low,
                band_high:        msg.band_high,
                defend_side:      msg.defend_side,
                t_target:         msg.t_target,           // NaN for v0
                effective_since:  msg.effective_since,    // builtin_interfaces/Time
                source:           msg.source,
            },
            timestamp: Date.now(),
        };
        lastModeBroadcast = payload;
        broadcast(payload);
    }
);
console.log('[bridge] current_mode subscription: TRANSIENT_LOCAL QoS (/fc1/control/current_mode)');
```
**On-connect replay extension** (lifted from index.js:592-604):
```javascript
wss.on('connection', (ws) => {
    console.log('[bridge] Client connected');
    clients.add(ws);

    if (lastSensorHealthBroadcast && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(lastSensorHealthBroadcast));
    }
    // NEW
    if (lastModeBroadcast && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(lastModeBroadcast));
    }
    if (lastAlerterModeOverridesBroadcast && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(lastAlerterModeOverridesBroadcast));
    }
    if (lastAlerterGlobalsBroadcast && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(lastAlerterGlobalsBroadcast));
    }
    // ...
});
```

### Pattern 2: Controller TRANSIENT_LOCAL publisher + validator-driven republish
**What:** A new ROS publisher that follows Phase 28's exact discipline.
**When:** For `alerter_mode_overrides` and `alerter_globals` per D-06.
**Example (verbatim from fc_controller.py:154-188):**
```python
# Verified at src/chambers/fc-core/fc_core/fc_controller.py:154-159 — REUSE THIS as-is.
actuator_qos = QoSProfile(
    depth=1,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    reliability=ReliabilityPolicy.RELIABLE,
    history=HistoryPolicy.KEEP_LAST,
)
# NEW — sibling of self._current_mode_pub (line 186)
self._alerter_overrides_pub = self.create_publisher(
    String,  # OR a fc_msgs/AlerterOverrides — see Pitfall §"Message type choice"
    'fc1/control/alerter_mode_overrides', actuator_qos
)
self._alerter_globals_pub = self.create_publisher(
    String,
    'fc1/control/alerter_globals', actuator_qos
)
```

**Validator extension pattern** — Phase 28's `_validate_params` (line 434+) already enforces dotted-key invariants for `modes.{name}.{band_low,band_high,defend_side,target_humidity}`. Phase 29 extends it with new key suffixes (verified pattern from fc_controller.py:466):
```python
elif n.startswith('modes.') and n.endswith('.alerter.cooldown_min'):
    if not (1 <= v <= 240):
        return SetParametersResult(successful=False,
            reason=f'{n}: must be in [1,240] minutes (got {v})')
    republish_alerter_overrides = True
elif n == 'pi_offline_min':
    if not (1 <= v <= 60):
        return SetParametersResult(successful=False,
            reason=f'pi_offline_min: must be in [1,60] (got {v})')
    republish_alerter_globals = True
# ... etc for each Tier B/C key
```

The next-tick republish drain is already present (`_pending_current_mode_republish` at line 196) — extend with `_pending_alerter_overrides_republish` and `_pending_alerter_globals_republish` flags drained at the same control_loop entry point.

### Pattern 3: Alerter event-routing in onMessage
**What:** Every WS payload key becomes a state-machine event.
**Example (verified from src/agents/alerter/src/index.js:115-138):**
```javascript
// Existing (verbatim) — extend the if/else chain
onMessage(msg) {
    if (msg.humidity !== undefined) {
        applyEvent({ type: 'humidity', value: msg.humidity });
    }
    // ... existing branches ...
    // NEW
    else if (msg.current_mode) {
        applyEvent({ type: 'mode_update', mode: msg.current_mode });
    } else if (msg.alerter_overrides) {
        applyEvent({ type: 'overrides_update', overrides: msg.alerter_overrides });
    } else if (msg.alerter_globals) {
        applyEvent({ type: 'globals_update', globals: msg.alerter_globals });
    }
}
```

### Pattern 4: Freshness-gated rule
**What:** Wrap the existing rule body in a freshness check; do *not* refactor the rule's math.
**Why:** Tests that assert "RH 83 with target 90 ± 3 is OOB" continue to pass when the rule is given a fresh effective config. Only NEW tests assert the gating behavior.
**Example:**
```javascript
// Verified shape from src/agents/alerter/src/rules.js:7-9
function isRhOob(humidity, effective) {
    // effective = { rhTarget, rhBand, freshness } where freshness is
    //   { state: 'fresh' | 'stale' | 'cold', source: 'mode' | 'env' }
    if (effective.freshness.state === 'stale') return false;  // D-03 state 2
    return Math.abs(humidity - effective.rhTarget) > effective.rhBand;
}
```

### Pattern 5: Mode-swap dedup reset
**What:** On `mode_update` event, RESET `oobCount` / `firstOobAt` / `inBandCount` for `rh` and `humidifier` perType entries; keep `lastFiredAt` (cooldown is keyed on alertType, not mode — D-09).
**Where:** New case in `state.js` `transition()` switch.
```javascript
case 'mode_update': {
    next.currentMode = event.mode;
    next.modeReceivedAtMs = now;
    // D-09: reset dedup but PRESERVE lastFiredAt (cooldown carries across mode swaps)
    for (const t of ['rh', 'humidifier']) {
        next.perType[t].oobCount = 0;
        next.perType[t].firstOobAt = null;
        next.perType[t].ctx.inBandCount = 0;
        // lastFiredAt intentionally NOT reset
        // state field: leave as-is; next humidity tick re-evaluates against new mode
    }
    break;
}
```

### Anti-Patterns to Avoid
- **Re-implementing `humidifierQos` inline.** Reuse the existing `humidifierQos` constant; one of the two existing `QoSProfile` constructions in index.js is identical (line 736 vs line 817). Bind to the same one or extract to a module-scope `const transientLocalQos` once.
- **Adding fields to `Mode.msg`.** D-05 explicitly forbids this. Phase 28 has shipped; the contract is locked.
- **Polling `/health` for mode state.** D-01 says alerter is WS-only. Polling re-introduces the same pattern that got us into 999.22.
- **Resetting `lastFiredAt` on mode swap.** D-09 explicitly preserves cooldown across mode swaps to dampen spam during a deliberate fruiting→pinning transition.
- **Schema-loose JSON in the `alerter_overrides`/`alerter_globals` payloads.** Use a typed shape (either `std_msgs/String` with a JSON discipline, or a custom `fc_msgs/AlerterOverrides.msg`). Recommend the JSON-in-String approach in v0 — avoids a second `fc_msgs` build cycle. Document the shape in `fc_msgs/README.md` next to `Mode.msg`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| WS reconnect with backoff | Custom `setTimeout` loop in alerter | Existing `createBridgeClient` (already does exponential backoff 1s→30s, line 16-17). | Already battle-tested across Phases 17, 25, 26. |
| ROS QoS object | New QoSProfile constructions | The 5 existing ones in fc_controller.py + 2 in bridge index.js | Reduces drift; one place to audit if RMW changes. |
| On-connect replay | Manual subscription replay timer | Add to existing `wss.on('connection')` block (index.js:592). | The pattern is six lines and already proves itself for `lastSensorHealthBroadcast`. |
| Atomic param batch validation | Custom validator | `_validate_params` already does whole-batch / would-be-state checks (line 434-548). Just extend the elif chain. | Phase 28 D-15 + Pitfall 4 already exercised in production. |
| Mode-state dedup logic | Per-rule `inProgressByMode` map | Reset oobCount/firstOobAt on `mode_update` event (D-09). | Composes with existing OK/PENDING/FIRING/SNOOZED FSM at state.js:6 without restructuring it. |
| Cooldown SQL analysis | Anything in TimescaleDB | `docker logs mushy-alerter` + grep/awk pipeline. | `[VERIFIED]` no `alert_history` table exists; `find -name '*.sql'` returns nothing. Memory `project_alerter_is_ws_only` confirms architectural reason. |

**Key insight:** Every Phase 29 mechanism has a working twin already in tree. The phase is overwhelmingly *replication* with deltas, not invention.

## Common Pitfalls

### Pitfall 1: TRANSIENT_LOCAL does NOT survive process restart
**What goes wrong:** A late-joining bridge thinks it'll get the last `current_mode` automatically. It will — but only if the controller process hasn't restarted since publishing. After a controller restart, the durable cache is empty until the controller publishes again.
**Why it happens:** rclpy/CycloneDDS TRANSIENT_LOCAL durability is per-process, not per-host.
**How to avoid:** Phase 28 already mitigated this for `current_mode` via the startup republish at fc_controller.py:257 (`self._publish_current_mode(source='config_default')`). Phase 29 MUST add a parallel startup republish for `alerter_mode_overrides` and `alerter_globals` *at the same site* in `__init__`, after param store is initialized.
**Warning signs:** Alerter caches show stale or never-arrived state after a controller-only restart while bridge stays up.

### Pitfall 2: TRANSIENT_LOCAL late-join on bridge reconnect
**What goes wrong:** Bridge restarts. It re-subscribes to `current_mode`. It DOES get the last value because the controller's publisher's durability cache served it. But subscribing happens asynchronously — there's a window where `lastModeBroadcast` is still null but a WS client connects.
**Why it happens:** rclnodejs subscription callback fires after a small delay; WS server is up before subscriptions are.
**How to avoid:** On-connect replay (D-02) sends whatever's in `lastModeBroadcast` — null is OK; alerter handles the cold-start grace per D-03 state 3. Don't try to "wait for ROS subscriptions to settle before accepting WS clients" — adds complexity, doesn't actually help.
**Warning signs:** First WS message after bridge restart misses the mode; alerter falls into env-fallback grace; clears within seconds when ROS callback fires and broadcast happens.

### Pitfall 3: sht30_fresh-as-ping band-aid (`ALERT_SENSOR_OFFLINE_MIN=1440`)
**What goes wrong:** The 2026-05-06 hourly false-alarm pathology (memory `project_alerter_watchdog_quiet_topic_bug`) was patched with `ALERT_SENSOR_OFFLINE_MIN=1440` (24h). After Phase 29 lands, freshness-gating + offline-blindness (D-04) fix the root cause. **If the band-aid env var is left at 1440, sensor-offline alerts will be useless** (won't fire until 24h of silence).
**Why it happens:** The band-aid was a pragmatic mute, not a fix. D-03 + Tier C delivery of `sensor_offline_min` lets the farmer dial it back to ~5 min.
**How to avoid:** Phase 29 must include an explicit step: **revert `ALERT_SENSOR_OFFLINE_MIN` to 5 in `.env` (or remove and rely on the Tier C ROS param default)**, gated on the new freshness gating being verified GREEN on fc1.
**Warning signs:** After deploy, no sht30/scd41 offline alerts fire when expected. Check the env value first.

### Pitfall 4: Env-fallback grace boundary race
**What goes wrong:** Alerter boots, WS connects, 60s grace timer arms (D-03 state 3). At 59s a `current_mode` message arrives — but the alerter has *just* fired an OOB alert against env defaults that disagrees with the new mode. Mode-swap reset (D-09) doesn't fire because this isn't a "swap", it's "first mode arrival".
**Why it happens:** State 3 → state 1 transition is not a swap.
**How to avoid:** Treat the *first* `mode_update` event the same as a swap — reset in-progress dedup. Add an explicit test: "first mode_update after cold start with stale env-config-driven OOB resets dedup".
**Warning signs:** First-minute false alerts that immediately recover when mode arrives.

### Pitfall 5: Mode.msg `t_target` is NaN
**What goes wrong:** The bridge serializes `Mode.t_target` to the WS payload as `NaN` → `JSON.stringify(NaN)` produces `null` (not `NaN`). Alerter receives `t_target: null` and any code path that does `t_target * something` becomes NaN-poisoned.
**Why it happens:** JSON has no NaN literal; serialization silently coerces.
**How to avoid:** Phase 29 doesn't consume `t_target` directly. Document that it's `null`-on-the-wire and skip it in the payload extraction. Or: emit `Number.isFinite(msg.t_target) ? msg.t_target : null` explicitly.
**Warning signs:** Browser console shows `t_target: null` despite controller log saying `t_target=NaN`.

### Pitfall 6: `humidifierLastMsgTs` is the bridge's `/health` view, not WS
**What goes wrong:** Plan author assumes `humidifierLastMsgTs` flows through WS. It does NOT — it's polled from `/health` by `pollHealth()` at bridge-client.js:20-36, then handed to `onLiveness({ humidifierLastMsgTs })` at line 27-31.
**Why it matters:** D-04 humidifier-stuck offline gating must read the value already in `state.humidifierLastMsgTs` (state.js:40) — fed by the existing `pi_liveness` event path. No new wiring required.
**How to avoid:** Read state, don't add a topic. The plumbing is done.
**Warning signs:** Plan proposes a new ROS topic to "carry humidifier last-seen" — that's wasted work.

### Pitfall 7: Cooldown not preserved across alerter restart
**What goes wrong:** state.js `initialState` zeroes everything. After an alerter restart, every alert type's `lastFiredAt` is null → next OOB fires immediately, ignoring its cooldown.
**Why it matters:** Phase 29's tuned cooldowns are useless if a sleepy `docker compose up -d --build alerter` triggers a fresh OOB-spam cycle. This is *pre-existing* behavior (memory `feedback_verify_docker`), not new — but the cooldown tuning analysis must factor it in (alerter restarts on most operator pushes).
**How to avoid:** Out of scope for Phase 29 (no persistent state). Note in `29-COOLDOWN-TUNING.md` that observed cooldown intervals exclude post-restart fires; recommend `cooldown_min` floor accounts for human "nuisance restart" cadence (~3-5 per week historically).
**Warning signs:** Tuning data shows clusters of fires immediately following deploy timestamps in `docker logs`.

### Pitfall 8: D-09 cooldown semantics
**What goes wrong:** D-09 specifies cooldowns key on `alertType` not `(alertType, mode)`. Implementer "improves" this by keying on the tuple → mode-swap into a noisier mode (pinning) suddenly emits a fresh `rh_oob` PROBLEM 1 minute after a fruiting `rh_oob` PROBLEM. Spam.
**Why it happens:** The tuple keying *seems* more correct. It isn't, in our usage.
**How to avoid:** Don't change the keying. Add a regression test: "fruiting rh_oob fires at t=0, mode-swaps to pinning at t=5min, pinning rh_oob fires at t=6min — second fire is suppressed by cooldown_min=30 (or whatever the new tuned value is)".
**Warning signs:** If pinning has a `cooldown_min` < (mode-swap-typical-time), revisit per the deferred bullet "Cooldowns keyed by (alertType, mode)".

## Runtime State Inventory

> Phase 29 is a code/config phase, not a rename/refactor — this section is light. Included for completeness.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — alerter is WS-only at runtime; capture pipeline writes to Timescale `signal_capture_*` tables but those are unaffected by Phase 29. | None |
| Live service config | `mushy-alerter` container env vars (production `.env` on elder-plops). Tier A/B/C move to runtime config; Tier D stays. | Update `.env`: revert `ALERT_SENSOR_OFFLINE_MIN=1440` to default 5 (Pitfall 3); keep `ALERT_RH_TARGET`/`ALERT_RH_BAND` as bootstrap fallback (D-03 state 3). |
| OS-registered state | None — alerter has no systemd unit on Pi; it's a Docker compose service on elder-plops. | None |
| Secrets/env vars | Nothing renames. | None |
| Build artifacts | `src/agents/alerter/node_modules` — npm install on container rebuild handles. | `docker compose up -d --build alerter` after merge. |
| **Pi-side build artifacts** | `fc_controller.py` declarations change → ROS param store needs reload. fc_config.yaml change → re-deploy via `git push fc1/prod` + `deploy.sh` per memory `feedback_deploy_method`. | Standard fc1 deploy cycle. |
| **Pi systemd drift** | Memory `feedback_diff_repo_vs_pi_systemd` warns to diff. fc_controller unit unchanged in Phase 29 — no new deps, no new unit fields. | Diff `/etc/systemd/system/fc-core.service` against repo; expect no diff or only previously-known drift. |

## Environment Availability

> Phase 29 has external dependencies (ROS2 stack, Docker stack, Timescale). All confirmed live per Phase 28 VERIFICATION.md.

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Phase 28 controller (current_mode topic live) | All bridge subscriptions; alerter freshness gating | ✓ | shipped 2026-05-08 (VERIFICATION.md) | — |
| `wg0` link fc1↔elder-plops | Bridge ROS subscription, deploy SSH | ✓ | active | — |
| Docker compose v2 on elder-plops (per memory `project_compose_v2_upgrade`) | Alerter container build/run | ✓ | v2 | — |
| `docker logs` retention for `mushy-alerter` | D-07 cooldown tuning data source | Probe required | — | If <14d retained, decrement window or supplement with manual notes |
| `git remote fc1/prod` | Pi deploy of fc_controller param changes | ✓ | per memory | — |
| `fc_msgs` already built on bridge image | rclnodejs needs Mode.msg type definition resolvable | ✓ (Phase 28 verified) | — | Rebuild bridge with --build per CLAUDE.md if Mode.msg path missing |
| Phase 28 `_publish_current_mode` startup-republish behavior | Late-joiner correctness | ✓ (line 257) | — | — |

**Missing dependencies with no fallback:** None known.

**Missing dependencies with fallback:** `docker logs` retention window for alerter — verify before committing to D-07 14-day target. Probe: `docker logs mushy-alerter --since 14d 2>&1 | head -1` — if the first line postdates 14d-ago, window is shorter; lower the analysis bound and document in `29-COOLDOWN-TUNING.md`.

## `config.js` Tier Audit (D-05 Concretization)

Verified line-by-line against `src/agents/alerter/src/config.js` (lines 23-58):

| Env var | Tier | Phase 29 Action | Notes |
|---------|------|------------------|-------|
| `BRIDGE_WS_URL` | D | unchanged | Container topology |
| `BRIDGE_HEALTH_URL` | D | unchanged | Container topology |
| `BRIDGE_HTTP_URL` | D | unchanged | Container topology |
| `SIGNAL_API_URL` | D | unchanged | Internal mechanic |
| `SIGNAL_SENDER` | D | unchanged | Secret-shaped |
| `SIGNAL_RECIPIENT` | D | unchanged | Recipient identity |
| `SIGNAL_ADDITIONAL_SENDERS` | D | unchanged | Auth list |
| `ALERT_RH_TARGET` | A | bootstrap fallback only (D-03 state 3) | Read from `current_mode.target_humidity` at runtime |
| `ALERT_RH_BAND` | A | bootstrap fallback only | Read from `current_mode.band_low` / `band_high` (paired) |
| `ALERT_OOB_N` | B | move to `modes.{name}.alerter.oob_n` | Per-mode sensitivity |
| `ALERT_OOB_WINDOW_MIN` | B | move to `modes.{name}.alerter.oob_window_min` | Per-mode |
| `ALERT_COOLDOWN_MIN` | B | move to `modes.{name}.alerter.cooldown_min` | Per-mode (D-08) |
| `ALERT_CRITICAL_COOLDOWN_MIN` | B | move to `modes.{name}.alerter.critical_cooldown_min` | Per-mode |
| `ALERT_PI_OFFLINE_MIN` | C | move to global ROS param via `alerter_globals` | Global liveness |
| `ALERT_SENSOR_OFFLINE_MIN` | C | move to global ROS param; **revert band-aid 1440→5** | Pitfall 3 — gated on D-03 lands |
| `ALERT_HUMIDIFIER_STUCK_MIN` | B | move to `modes.{name}.alerter.humidifier_stuck_min` | Per-mode (fruiting tight, pinning intentionally swings) |
| `ALERT_HEARTBEAT_HOUR` | C | move to global ROS param | Daily ops cadence |
| `ALERT_RECEIVE_POLL_SEC` | D | unchanged | Internal mechanic, not farmer-meaningful |
| `ALERT_MAX_SENDS_PER_HOUR` | C | move to global ROS param | Egress budget |
| `TZ` | D | unchanged | Container locale |
| `DASHBOARD_URL` | D | unchanged | Branded surface |
| `LOG_LEVEL` | D | unchanged | Ops |
| `TIMESCALE_*` | D | unchanged | Capture pipeline only |
| `ANTHROPIC_API_KEY` | D | unchanged | Capture pipeline |
| `WHISPER_URL` | D | unchanged | Capture pipeline |
| `CAPTURE_*` | D | unchanged | Capture pipeline |

**14 env vars currently active** that fall into Tier A/B/C; **23 stay in Tier D**.

## Code Examples

### Example A: state.js — new event types (D-05/D-06/D-09)
```javascript
// Add to transition() switch:
case 'mode_update': {
    next.currentMode = event.mode;            // {name, target_humidity, band_low, band_high, ...}
    next.modeReceivedAtMs = now;              // freshness ts (D-03)
    // D-09: reset in-progress dedup for mode-driven rules
    for (const t of ['rh', 'humidifier']) {
        next.perType[t].oobCount = 0;
        next.perType[t].firstOobAt = null;
        next.perType[t].ctx.inBandCount = 0;
        // lastFiredAt PRESERVED — cooldown is alertType-keyed (D-09)
    }
    break;
}
case 'overrides_update': {
    next.alerterOverrides = event.overrides;  // {fruiting: {...}, pinning: {...}}
    next.overridesReceivedAtMs = now;
    break;
}
case 'globals_update': {
    next.alerterGlobals = event.globals;      // {pi_offline_min, sensor_offline_min, ...}
    next.globalsReceivedAtMs = now;
    break;
}
```

### Example B: effective-config resolver (lives in state.js or a new tiny module)
```javascript
function resolveEffectiveConfig(state, envConfig, nowMs) {
    const MODE_STALE_MS = 5 * 60 * 1000;                  // D-03 default
    const COLD_GRACE_MS = 60 * 1000;                      // D-03 state 3
    const wsConnected = state.wsConnected;
    const modeAge = state.modeReceivedAtMs ? nowMs - state.modeReceivedAtMs : Infinity;

    // D-03 state 1: mode known and fresh
    if (state.currentMode && wsConnected && modeAge <= MODE_STALE_MS) {
        const m = state.currentMode;
        const overrides = state.alerterOverrides?.[m.name] || {};
        const globals   = state.alerterGlobals || {};
        return {
            rhTarget: m.target_humidity * 100,                // wire is 0-1; alerter convention is 0-100
            rhBand:   ((m.band_high - m.band_low) / 2) * 100, // symmetric proxy; OR use full band per band-asymmetric branch
            oobN:                overrides.oob_n              ?? envConfig.oobN,
            oobWindowMin:        overrides.oob_window_min     ?? envConfig.oobWindowMin,
            cooldownMin:         overrides.cooldown_min       ?? envConfig.cooldownMin,
            criticalCooldownMin: overrides.critical_cooldown_min ?? envConfig.criticalCooldownMin,
            humidifierStuckMin:  overrides.humidifier_stuck_min ?? envConfig.humidifierStuckMin,
            piOfflineMin:        globals.pi_offline_min       ?? envConfig.piOfflineMin,
            sensorOfflineMin:    globals.sensor_offline_min   ?? envConfig.sensorOfflineMin,
            heartbeatHour:       globals.heartbeat_hour       ?? envConfig.heartbeatHour,
            maxSendsPerHour:     globals.max_sends_per_hour   ?? envConfig.maxSendsPerHour,
            ...envConfig,                                     // Tier D pass-through
            freshness: { state: 'fresh', source: 'mode' },
        };
    }
    // D-03 state 3: cold start grace
    const bootAge = nowMs - state.bootedAtMs;
    if (!state.currentMode && bootAge <= COLD_GRACE_MS) {
        return { ...envConfig, freshness: { state: 'cold', source: 'env' } };
    }
    // D-03 state 2: stale or never-arrived past grace
    return { ...envConfig, freshness: { state: 'stale', source: 'env' } };
}
```

### Example C: rules.js gated isHumidifierStuck (D-04 + 999.39)
```javascript
function isHumidifierStuck({ humidifierOnSinceMs, rhAtOn, currentRh, nowMs, config, liveness }) {
    // D-04 / 999.39: suspend during offline-blind windows
    if (!liveness.wsConnected) return false;
    if (liveness.humidifierLastMsgTs == null) return false;
    if (nowMs - liveness.humidifierLastMsgTs > config.sensorOfflineMin * 60000) return false;

    if (humidifierOnSinceMs == null) return false;
    const onDurationMs = nowMs - humidifierOnSinceMs;
    if (onDurationMs <= config.humidifierStuckMin * 60000) return false;
    return (currentRh - rhAtOn) < 3.0;
}
```

### Example D: message.js extended pi formatter (D-04 / 999.39)
```javascript
} else if (alertType === 'pi') {
    const { lastSeenMs, lastKnown } = fields;       // NEW lastKnown surface
    if (lastSeenMs != null) {
        body += `Last seen: ${fmtRelative(lastSeenMs, nowMs)}\n`;
    }
    if (lastKnown) {
        const { humidifier, rh, temp, sampleAtMs } = lastKnown;
        body += `Last known: humidifier ${humidifier}, RH ${rh}%, T ${temp}°C`;
        if (sampleAtMs != null) body += ` (${fmtRelative(sampleAtMs, nowMs)})`;
        body += '\n';
    }
}
```

## Tuning Data Access (D-07)

**Primary path (DEFERRED, NOT AVAILABLE):** Timescale `alert_history` table. **Verified absent** via `find . -name "*.sql"` (returns nothing) and `grep -r 'CREATE TABLE.*alert' --include='*.sql' --include='*.js'` (returns nothing). Memory `project_alerter_is_ws_only` is the architectural cause.

**Fallback path (the actual path):**
```bash
# On elder-plops, where mushy-alerter runs:
docker logs mushy-alerter --since 14d > /tmp/alerter-14d.log 2>&1

# Phase 29 cooldown analysis grammar — rely on the kind+alertType log lines emitted
# by index.js apply-action (line 100-105 region). Verify exact grep pattern by
# inspecting one day of logs first; the canonical grep is roughly:
grep -E '\[(send|recovery|heartbeat)\] ' /tmp/alerter-14d.log \
  | awk '{print $1, $2, $3, $4}' > /tmp/alerter-events.tsv

# Per alertType: count fires, mean inter-fire interval, P95 fires/hour
# Output landed in 29-COOLDOWN-TUNING.md as a table:
#   alertType | fires | recoveries | mean_inter_fire_min | p95_per_hour | proposed_cooldown_min | rationale
```

**Pre-flight check:** Run `docker logs mushy-alerter --since 14d 2>&1 | head -1` — if the timestamp is younger than 14d (i.e. log retention is shorter), shorten the analysis window and document in the tuning note. Docker default is unlimited but compose may impose a `max-size`/`max-file` rotation.

**Why not extend alerter to write to Timescale now:** explicitly deferred per CONTEXT.md "Deferred Ideas" — composes with 999.35 and is its own scope.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| RH target/band as static env vars | Live mode-driven from `current_mode` | Phase 29 (this) | Closes 999.22 |
| Alerter fires during fc1 outage | Offline-blind gating; pi-alert carries last-known | Phase 29 (this) | Closes 999.39 |
| Cooldowns as flat `.env` defaults | Per-mode tuned values in `fc_config.yaml` | Phase 29 (this) | Per-mode signal-to-noise |
| Schema-locked Mode.msg | (unchanged in v0; deliberate) | Phase 28 | Phase 29 routes around via two new topics |

**Deprecated/outdated:**
- `ALERT_SENSOR_OFFLINE_MIN=1440` band-aid (memory `project_alerter_watchdog_quiet_topic_bug`) — to be reverted as part of Phase 29 deploy.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | jest@^29.7.0 (alerter), pytest (fc_controller) |
| Config file | `src/agents/alerter/jest.config.js`, `src/chambers/fc-core/setup.cfg` (existing) |
| Quick run command | `cd src/agents/alerter && npx jest test/rules.test.js test/message.test.js test/state.test.js` |
| Full alerter suite | `cd src/agents/alerter && npx jest` |
| Full controller suite | `cd src/chambers/fc-core && pytest` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| ALRT-08 | RH-OOB rule reads target/band from cached `current_mode` (D-03 state 1) | unit | `npx jest test/rules.test.js -t 'fresh mode drives target'` | ❌ Wave 0 |
| ALRT-08 | Mode_update event populates state.currentMode | unit | `npx jest test/state.test.js -t 'mode_update'` | ❌ Wave 0 |
| ALRT-08 | Bridge subscribes to /fc1/control/current_mode and broadcasts | integration | (bridge has no test harness today; covered by smoke test on elder-plops) | ❌ Wave 0 (defer to smoke; document in plan) |
| ALRT-09 | overrides_update / globals_update merge into effective config | unit | `npx jest test/state.test.js -t 'overrides_update'` | ❌ Wave 0 |
| ALRT-09 | New ROS params declared and validated atomically | unit | `pytest src/chambers/fc-core/fc_core/test/test_validate_params.py -k alerter` | ❌ Wave 0 (extend existing Phase 28 validator tests) |
| ALRT-10 | Cooldown values match tuning recommendation | smoke | manual: read fc_config.yaml diff vs 29-COOLDOWN-TUNING.md table | manual |
| 999.39 (D-04) | isHumidifierStuck returns false when wsConnected=false | unit | `npx jest test/rules.test.js -t 'humidifier-stuck offline-blind'` | ❌ Wave 0 |
| 999.39 (D-04) | formatProblem(pi) includes last-known summary | unit | `npx jest test/message.test.js -t 'pi includes last-known'` | ❌ Wave 0 |
| D-03 | Mode stale (>5min) → isRhOob returns false | unit | `npx jest test/rules.test.js -t 'mode stale suspends rh-oob'` | ❌ Wave 0 |
| D-03 | Cold-start ≤60s grace uses env fallback | unit | `npx jest test/state.test.js -t 'cold-start env fallback'` | ❌ Wave 0 |
| D-09 | Mode swap resets oobCount/firstOobAt; preserves lastFiredAt | unit | `npx jest test/state.test.js -t 'mode swap resets dedup'` | ❌ Wave 0 |
| D-09 | Cooldown carries across mode swap (alertType-keyed, not tuple) | unit | `npx jest test/state.test.js -t 'cooldown survives mode swap'` | ❌ Wave 0 |
| Pitfall 4 | First mode_update after cold start resets dedup | unit | `npx jest test/state.test.js -t 'first mode arrival resets dedup'` | ❌ Wave 0 |
| Soak | On-host fc1: mode-swap + alert-fire + recovery end-to-end | manual smoke | `ros2 service call /fc_controller/set_mode fc_msgs/srv/SetMode "{mode_name: 'pinning'}"` then watch alerter logs | manual |

### Sampling Rate
- **Per task commit:** `cd src/agents/alerter && npx jest test/rules.test.js test/state.test.js test/message.test.js` (~5s)
- **Per wave merge:** `cd src/agents/alerter && npx jest` AND `cd src/chambers/fc-core && pytest`
- **Phase gate:** Full suites green + on-host fc1 smoke (mode swap → expected alert behavior)

### Wave 0 Gaps
- [ ] `src/agents/alerter/test/rules.test.js` — extend with freshness-state tests (D-03), offline-blind tests (D-04)
- [ ] `src/agents/alerter/test/state.test.js` — extend with mode_update/overrides_update/globals_update event tests, mode-swap dedup reset (D-09), cooldown-survives-swap test
- [ ] `src/agents/alerter/test/message.test.js` — extend with pi last-known summary test
- [ ] `src/chambers/fc-core/fc_core/test/` — extend Phase 28 validator tests with new dotted-key invariants (Tier B/C)
- [ ] No new test files needed; all tests extend existing files. Existing fixtures live at `src/agents/alerter/test/fixtures/` and `helpers/` — reuse.

## Existing Test Shape (Reference for Planner)

`rules.test.js` style (verified):
```javascript
const { isRhOob } = require('../src/rules');
describe('isRhOob', () => {
  const cfg = { rhTarget: 90, rhBand: 3 };
  test('exactly on target: false', () => {
    expect(isRhOob(90, cfg)).toBe(false);
  });
});
```
Phase 29 extension follows same shape — pass `{rhTarget, rhBand, freshness: {state: 'fresh'}}` for the new gate. Do NOT change the existing 4 `isRhOob` tests; they're all `freshness.state === 'fresh'` implicitly via a default-fresh `effective` builder helper.

`state.test.js` covers FSM transitions; mode_update event tests slot in via `transition(state, {type: 'mode_update', mode: {...}}, now, config)` and assertions on returned `next.currentMode`, `next.perType.rh.oobCount`, etc.

`message.test.js` (verified pattern from `Test E`) — reuse the dashboardUrl-once invariant when extending pi formatter.

## Security Domain

Phase 29 is internal plumbing; no new auth surfaces, no new public endpoints, no new secrets.

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | — |
| V3 Session Management | no | — |
| V4 Access Control | partial | The bridge's existing param-set HTTP allowlist (Phase 28-05) needs to allow new dotted-keys (`modes.*.alerter.*`, `pi_offline_min`, etc.) — confirm allowlist mechanism explicitly admits the new keys. |
| V5 Input Validation | yes | rclpy `_validate_params` extension at fc_controller.py:434 — bound new int/float ranges, reject obviously-wrong values. JSON parse of `alerter_overrides`/`alerter_globals` payloads in alerter must wrap in `try/catch` (existing `bridge-client.js` line 49-55 already does this for the WS message at large). |
| V6 Cryptography | no | — |

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Param injection via SetParameters batch | Tampering | `_validate_params` whole-batch atomic check; Phase 28 already enforces. Extend to new keys. |
| WS message-shape spoofing (alerter receives `alerter_globals` with malicious values) | Tampering | Bridge is the only WS publisher; clients can't write back. Defense-in-depth: alerter clamps overrides to sane ranges before storing in state. |
| Disclosure of operational ranges via WS broadcast | Information Disclosure | Bridge already broadcasts mode/PID/sensor data publicly to all WS clients; alerter overrides are not more sensitive than what's already on the wire. |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Tier B/C delivery via JSON-in-`std_msgs/String` is preferred over a custom `fc_msgs/AlerterOverrides.msg` | Pattern 2 / Anti-Patterns | If a custom msg type is required for OpenMCT consumption, planner adds a `fc_msgs` build step — small delta; doesn't change alerter logic. `[ASSUMED]` |
| A2 | Bridge param-set HTTP allowlist (Phase 28-05) is regex- or prefix-extendable to admit `modes.*.alerter.*` | Security V4 | If allowlist is a hardcoded enum, it needs explicit addition for each new key. Verify by reading bridge's param-set handler. `[ASSUMED]` — not re-verified in this research; flagged for plan-checker |
| A3 | Docker logs retain ≥14 days of `mushy-alerter` history on elder-plops | Tuning Data Access | If retention < 14d, the D-07 window narrows; `29-COOLDOWN-TUNING.md` documents the actual window used. `[ASSUMED]` until probe lands |
| A4 | The `band_low`/`band_high` cooldown semantics for symmetric vs asymmetric pinning use a single representative `rhBand` for `isRhOob` | Example B | The existing rule is `abs(value - target) > band` (symmetric). For pinning's asymmetric defend-side, the rule may need a more nuanced gate. CONTEXT.md doesn't dictate; flagged so the plan can revisit. `[ASSUMED]` |
| A5 | The `_validate_params` extension's range bounds (e.g., `pi_offline_min` ∈ [1,60]) are acceptable to operator | Pattern 2 | Range bounds are illustrative; operator may want wider/narrower. Defaults are sane; exact bounds are a planning detail. `[ASSUMED]` |

## Open Questions

1. **Is the bridge param-set HTTP allowlist regex-based or hardcoded?**
   - What we know: Phase 28-05 introduced an allowlist for SetParameters POSTs.
   - What's unclear: Whether new keys (`modes.fruiting.alerter.cooldown_min` etc.) need explicit per-key addition or if a prefix wildcard (`modes.*.alerter.*`) is supported.
   - Recommendation: Plan-checker reads `src/mission-control/bridge/src/control_persist.js` (or equivalent) and adds a Wave 0 task to extend the allowlist if hardcoded.

2. **`Mode.msg` serialization of NaN `t_target` over rclnodejs → JSON?**
   - What we know: `t_target` is a `float32` and explicitly NaN for v0 (D-04 sentinel).
   - What's unclear: Whether rclnodejs converts NaN to `null` or to the JS `NaN` (which `JSON.stringify` produces `null`).
   - Recommendation: Bridge subscription callback explicitly emits `Number.isFinite(msg.t_target) ? msg.t_target : null` in the WS payload; document in code comment.

3. **Should mode-swap reset `humidifierLastMsgTs` snapshot for `humidifier-stuck`?**
   - What we know: D-09 says reset oobCount/firstOobAt for in-progress dedup; preserves lastFiredAt.
   - What's unclear: `humidifierOnSinceMs` and `rhAtOn` are not "dedup" state — they're "current cycle" state. They survive mode swap because they reflect physical actuator state. Confirm.
   - Recommendation: Document in PLAN.md that `humidifierOnSinceMs`/`rhAtOn` are NOT reset on mode swap (they're physical, not policy).

## Sources

### Primary (HIGH confidence — read directly from HEAD tree)
- `src/mission-control/bridge/src/index.js` — lines 264 (wss), 585-614 (clients/broadcast), 656-846 (ROS subscriptions), 736-742 (humidifierQos profile)
- `src/chambers/fc-core/fc_core/fc_controller.py` — lines 14-17 (Mode/SetMode imports), 154-188 (actuator_qos + 5 publishers), 196-204 (validator + service registration), 257 (startup republish), 404-432 (`_publish_current_mode`), 434-548 (`_validate_params`)
- `src/chambers/fc-core/config/fc_config.yaml` — lines 76-90 (modes block)
- `src/chambers/fc-msgs/msg/Mode.msg` — full 8 lines
- `src/agents/alerter/src/config.js` — lines 23-58 (env loader)
- `src/agents/alerter/src/rules.js` — lines 7-66 (all 5 rule functions)
- `src/agents/alerter/src/bridge-client.js` — lines 5-87 (WS client + health poll + onLiveness)
- `src/agents/alerter/src/state.js` — lines 6 (STATES enum), 20-64 (initialState + cooldownMs), 80-164 (driveAlertType FSM), 169-483 (transition switch), 217-302 (sensor_health/sensor_freshness handling)
- `src/agents/alerter/src/index.js` — lines 100-178 (apply + onMessage + tickTimer wiring)
- `src/agents/alerter/src/message.js` — lines 50-130 (formatProblem/formatRecovery/formatHeartbeat)
- `src/agents/alerter/test/rules.test.js`, `test/message.test.js`, `test/bridge-client.test.js` (top-of-file probed)
- `src/agents/alerter/package.json` — version pins
- `.planning/phases/28-mode-primitive-2-baseline-modes-fruiting-pinning-runtime-con/VERIFICATION.md` — top frontmatter (status: passed)

### Secondary (cross-referenced project memory)
- `project_alerter_is_ws_only` — confirmed by absence of any `.sql` schema file
- `project_alerter_watchdog_quiet_topic_bug` — Pitfall 3
- `feedback_diff_repo_vs_pi_systemd` — flagged in Project Constraints
- `project_2026_05_07_fc1_reboot_unrecoverable` + 999.39 — informs D-04

### Tertiary
- None used. All claims verified against tree or memory.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — versions verified from package.json; no new deps proposed.
- Architecture: HIGH — every pattern mirrors a working precedent in tree (Phase 16.1 sensor_health on-connect replay, Phase 27 telemetry-trio TRANSIENT_LOCAL, Phase 28 actuator_qos + `_validate_params`).
- Pitfalls: HIGH for Pitfalls 1, 2, 5, 6 (verified in code/comments); MEDIUM for Pitfalls 3, 4, 7, 8 (informed by memory + reasoning, not directly probed at runtime).
- Validation Architecture: HIGH — existing test shape probed verbatim.
- Tuning data path: HIGH — confirmed alert_history absent via filesystem grep.

**Research date:** 2026-05-08
**Valid until:** 2026-06-07 (30 days; stable subsystem)

## What Planner Needs to Know — Punch List

1. **Three new bridge subscriptions, copy-paste-modify-from index.js:735-846.** All three reuse `humidifierQos`. All three add a `lastXBroadcast` module-level cache and an on-connect replay block in `wss.on('connection')`. This is one cohesive plan/task.
2. **Two new fc_controller publishers + Tier B/C param declarations + validator extension + startup republish.** Single plan/task on the controller side; test extension reuses Phase 28-04 validator test scaffolding.
3. **`fc_config.yaml`** gains `modes.fruiting.alerter.*` and `modes.pinning.alerter.*` blocks (Tier B) PLUS a global Tier C block (decide: top-level under `fc_controller: ros__parameters:` or a new `alerter_globals: ros__parameters:` section — recommend the former; keeps single-source).
4. **Alerter event-routing in `index.js:115-138`** — three new branches in the if/else chain.
5. **Alerter `state.js`** — three new event types (`mode_update`, `overrides_update`, `globals_update`) + an effective-config resolver helper. D-09 dedup-reset logic lives in `mode_update` case.
6. **Alerter `rules.js`** — freshness-gate `isRhOob` and `isHumidifierStuck`. Don't refactor the math; wrap.
7. **Alerter `message.js`** — extend `formatProblem` for `alertType==='pi'` to read `fields.lastKnown`; add lastKnown construction at the call site (`state.js` driveAlertType for pi alerts).
8. **`config.js` Tier D narrowing** — keep all Tier A/B/C parsers as bootstrap fallbacks but document they're fallback-only; production source-of-truth is the WS-cached values.
9. **Tuning analysis** — separate one-shot deliverable, `29-COOLDOWN-TUNING.md`, runs against `docker logs mushy-alerter`. Output: a fc_config.yaml diff for `modes.{name}.alerter.cooldown_min` etc.
10. **Pitfall 3 deploy step** — revert `ALERT_SENSOR_OFFLINE_MIN=1440` band-aid in elder-plops `.env` *after* Phase 29 freshness-gating is verified GREEN on fc1.
11. **Wave 0 test scaffolding** — extend existing test files; no new test files. Recommend Wave 0 = "extend test fixtures + add the freshness-state helper", Wave 1 = "bridge + fc_controller plumbing", Wave 2 = "alerter wiring + rule gating", Wave 3 = "cooldown tuning analysis + deploy", Wave 4 = "smoke + revert band-aid + verify".
12. **Open Question 1** (allowlist regex) is the highest-priority verification — flag for plan-checker as Wave 0.
