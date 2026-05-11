# Phase 29: Alerter mode awareness + cooldown tuning - Context

**Gathered:** 2026-05-08
**Status:** Ready for planning

<domain>
## Phase Boundary

Make the alerter consume the controller's live mode state (target/band/etc.) from Phase 28's `current_mode` topic instead of static env vars, sweep `src/agents/alerter/src/config.js` for other farmer-tunable knobs hiding in env and route them through Phase 28's runtime-config path, and tune alert cooldown thresholds based on accumulated Phase 17+ data. Closes backlog 999.22 and carries Phase 20.

**In scope:**
- ALRT-08: alerter reads RH target + band from `current_mode` (or controller-published equivalents) instead of `ALERT_RH_TARGET`/`ALERT_RH_BAND`.
- ALRT-09: sweep alerter env vars; route farmer-meaningful knobs through Phase 28 mode/runtime-config; keep ops/secret env.
- ALRT-10: tune cooldown thresholds against Phase 17+ Timescale alert history; commit new defaults.
- Bundled per D-04 below: 999.39 (offline-blindness in `rules.js` + last-known summary in pi-offline message).

**Out of scope** (deferred):
- 999.35 daily maintenance agent / alerter self-pathology meta-watchdog.
- Time-of-day mode scheduling (Phase 30 owns).
- Forcing modes (Phase 31 owns).
- Any controller-side change to `current_mode` shape — Phase 28 schema is locked.

</domain>

<decisions>
## Implementation Decisions

### Mode Signal Plumbing (ALRT-08)

- **D-01:** **Bridge subscribes to `fc1/control/current_mode` (TRANSIENT_LOCAL/RELIABLE/depth=1, matching publisher QoS) and re-broadcasts the full `Mode` payload as a typed WS message to all clients (alerter included).** Alerter's `bridge-client.js` caches the latest mode in module state alongside the existing per-topic caches. No new HTTP endpoint, no flat scalar topics.
  - **Rationale:** Alerter is WS-only by design (`project_alerter_is_ws_only`); polling would invent a new pattern. TRANSIENT_LOCAL gives near-zero-gap recovery on WS reconnect (Phase 28 Pitfall-2 mitigation already in controller via startup republish). Atomic mode payload preserves `(target_humidity, band_low, band_high, defend_side, effective_since, source)` consistency — flat scalar topics could deliver inconsistent tuples mid-swap.
  - **Touches:** bridge `src/mission-control/bridge/src/index.js` (new ROS subscription + WS forward), `src/agents/alerter/src/bridge-client.js` (new `currentMode` cache + accessor).

- **D-02:** **Bridge re-broadcasts `current_mode` on every received message AND on each new WS client connection** (replay last cached value to a freshly-connecting client). Alerter cold-start gets the active mode within one bridge handshake; no need for the alerter to query an HTTP endpoint at startup.

### Behavior When Mode Is Absent / Stale / fc1 Offline

- **D-03:** **Three-state freshness model for mode-driven RH alerts:**
  1. **Mode known and fresh** (cached `current_mode` ≤ `mode_stale_min` old, default 5 min, AND `wsConnected === true`) → use cached `target_humidity` ± `band_*` for RH-OOB rule.
  2. **Mode known but WS disconnected OR fc1 sensor topic stale** → suspend RH-band rules entirely (do not alert OOB) AND suspend humidifier-stuck rule (per D-04 below). Last-known mode kept in cache for diagnostic message bodies. The pi/sensor-offline rules still fire — those are the right alerts during outages.
  3. **Mode never received** (cold start before first `current_mode` message arrives) → fall back to env defaults `ALERT_RH_TARGET` / `ALERT_RH_BAND` for a bounded grace window (default 60s after WS handshake), then transition to state 2 if still no mode. Env defaults remain in `config.js` as the bootstrap-only backstop.
  - **Rationale:** This is the load-bearing decision for not regressing on the 2026-05-07 false-CRITICAL pattern (`project_2026_05_07_fc1_reboot_unrecoverable` + 999.39). RH alerts during fc1 offline have no signal — suspending them is correct; pi-offline alert carries the situational context instead.

### Bundle 999.39 (Offline-Blindness)

- **D-04:** **Bundle 999.39 into Phase 29.** Same module (`rules.js`, `message.js`), same liveness inputs (`wsConnected`, `humidifierLastMsgTs`), same WS-cache invariants. Splitting forces two consecutive rules-module rewrites with subtle ordering hazards.
  - Concretely:
    - Gate `isHumidifierStuck` on `wsConnected === true` AND `humidifierLastMsgTs` fresh ≤ `humidifierStaleMin` (default = `sensorOfflineMin`); suppress when stale.
    - Audit `isRhOob` for the same offline-blind class; gate by D-03 freshness state.
    - Extend `formatProblem` for `alertType === 'pi'` to include last-known summary (humidifier ON/OFF, RH%, T°C, wallclock of last sample) per 999.39 acceptance shape.
  - Add to ROADMAP.md upon phase completion: 999.39 marked as resolved-by-Phase-29.

### Knob Sweep (ALRT-09)

- **D-05:** **Three-tier classification of `src/agents/alerter/src/config.js` env vars:**

  **Tier A — Mode-driven** (consumed from `current_mode` payload, declared in `fc_config.yaml` `modes.{name}.*`; alerter reads only):
  - `target_humidity` (replaces `ALERT_RH_TARGET`) — already in Phase 28 schema
  - `band_low`, `band_high` (replaces single-scalar `ALERT_RH_BAND`) — already in Phase 28 schema
  - **No new fields added to `Mode.msg`** — Phase 28's 7-field schema is locked.

  **Tier B — Per-mode alerter overrides** (NEW optional fields under `fc_config.yaml` `modes.{name}.alerter.*` block, NOT in `Mode.msg` itself; alerter reads `fc_controller`'s ROS params via the bridge's existing `/control/param` GET path or via dedicated `current_mode_alerter` topic — see D-06):
  - `humidifier_stuck_min` — fruiting wants tight; pinning intentionally swings
  - `oob_n`, `oob_window_min` — sensitivity differs by mode
  - `cooldown_min`, `critical_cooldown_min` — alert volume should reflect mode noise floor

  **Tier C — Global runtime-tunable** (controller-owned ROS params, runtime-mutable via Phase 28 Layer 1 SetParameters; alerter consumes via dedicated WS-broadcast topic):
  - `pi_offline_min`, `sensor_offline_min` — global liveness; not per-mode
  - `heartbeat_hour` — daily ops cadence
  - `max_sends_per_hour` — Signal egress budget

  **Tier D — Env-only** (ops/secret config, deploy-time, NOT runtime-tunable):
  - `BRIDGE_WS_URL`, `BRIDGE_HEALTH_URL`, `BRIDGE_HTTP_URL`, `SIGNAL_API_URL`, `SIGNAL_SENDER`, `SIGNAL_RECIPIENT`, `SIGNAL_ADDITIONAL_SENDERS`, `TZ`, `DASHBOARD_URL`, `LOG_LEVEL`
  - All `TIMESCALE_*`, `ANTHROPIC_API_KEY`, `WHISPER_URL`, `CAPTURE_*`, `CAPTURE_RETENTION_*`
  - `ALERT_RECEIVE_POLL_SEC` (Signal poll cadence — internal mechanic, not farmer-meaningful)

- **D-06:** **Tier B + Tier C delivery channel (avoid broadening `Mode.msg`):** Add **two new TRANSIENT_LOCAL topics** owned by `fc_controller`:
  - `fc1/control/alerter_mode_overrides` (per-mode alerter knobs, republished on mode swap)
  - `fc1/control/alerter_globals` (Tier C globals, republished on param change)

  Both subscribed by bridge → broadcast on WS → cached by alerter, same pattern as D-01. This keeps `Mode.msg` (Phase 28 contract) untouched and avoids per-tier HTTP endpoints.
  - Bridge uses the same TRANSIENT_LOCAL/RELIABLE QoS profile as `current_mode` (matches publisher).
  - Alerter uses last-known cached values; falls back to env defaults during the same bootstrap grace window as D-03 state 3.

### Cooldown Tuning (ALRT-10)

- **D-07:** **Tuning data source: offline analysis of Timescale `alert_history` table (or alerter logs if no DB row exists) over the Phase 17+ window** — minimum 14 days. Compute per-rule: total fires, deduped fires, farmer-acknowledged fires, mean inter-fire interval, fires-per-hour P95. Deliverable: a short tuning note in the phase artifacts (`29-COOLDOWN-TUNING.md`) with the analysis + proposed defaults + rationale.
  - **Rationale:** Farmer-gut is biased by recent loud incidents (e.g. 2026-05-06 hourly-clockwork pathology); the data has the truth. We already have ≥2 weeks of live alerts in Timescale.
  - If `alert_history` is not populated (alerter currently doesn't write to Timescale per `project_alerter_is_ws_only`), the tuning note uses `docker logs mushy-alerter` parsed output instead — a one-shot recipe in the analysis doc.

- **D-08:** **Tuned values land in `fc_config.yaml` `modes.{name}.alerter.*` block (Tier B per D-05)**, not in `.env`. Per-mode tuning is the whole point — fruiting cooldowns differ from pinning cooldowns. Old `.env` values stay as the bootstrap fallback (D-03 state 3) and the deploy-time defaults for Tier C globals.

### Reload Semantics on Mode Swap

- **D-09:** **On mode swap, alerter immediately re-evaluates rules against the new mode's `target_humidity`/`band_*`/`oob_*`/`cooldown_*`. Any in-progress dedup window for a rule is RESET (not preserved across modes).** Different modes have different "normal" — carrying a fruiting OOB-fire-count into pinning would corrupt the new-mode noise floor.
  - Cooldowns already-fired stay tracked by `alertType` keyed on the rule, not the mode — a `rh_oob` cooldown fired 5 min ago in fruiting still suppresses a fresh `rh_oob` fire 5 min later in pinning if the new-mode `cooldown_min` says so. (This is a tradeoff: prevents alert spam during a deliberate mode swap into a "loud" mode like pinning. Plan-phase may revisit if data says otherwise.)

### Claude's Discretion

All five gray areas were delegated to Claude's discretion (user answered "non" to area selection). Above decisions are Claude's reasoned defaults grounded in prior memory + Phase 28 contract; user is invited to redirect any of them at planning time. The most reversible later are D-07 (analysis methodology), D-08 (where tuned values land), D-09 (cooldown carry-over semantics). The least reversible is D-01/D-06 (WS-broadcast plumbing pattern) — once bridge ships these subscriptions, alerter is locked to the pattern.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 29 Requirements
- `.planning/REQUIREMENTS.md` ALRT-08, ALRT-09, ALRT-10 (lines 63-65)

### Phase 28 (Mode Primitive — Upstream Contract)
- `.planning/phases/28-mode-primitive-2-baseline-modes-fruiting-pinning-runtime-con/28-CONTEXT.md` — D-01..D-25; Mode.msg schema (D-13), set_mode service (D-16), TRANSIENT_LOCAL `current_mode` (D-14), Layer 1 + Layer 2 runtime config delivery
- `.planning/phases/28-mode-primitive-2-baseline-modes-fruiting-pinning-runtime-con/VERIFICATION.md` — proves the upstream contract is shipped and live on fc1
- `src/chambers/fc-msgs/msg/Mode.msg` — 7-field schema (locked, do not extend in this phase)
- `src/chambers/fc-msgs/srv/SetMode.srv` — service contract
- `src/chambers/fc-core/config/fc_config.yaml` lines 76-90 — `modes.fruiting.*` and `modes.pinning.*` v0 values (D-05/D-06 of Phase 28)
- `src/chambers/fc-core/fc_core/fc_controller.py` — current_mode publisher (line 186-187, 257), on_set_parameters_callback validator (line 434), `_validate_params` (line 434+)

### Alerter (Module Being Modified)
- `src/agents/alerter/src/config.js` — env var inventory; baseline for the D-05 tier classification
- `src/agents/alerter/src/rules.js` — `isRhOob`, `isHumidifierStuck`, `isPiOffline`, `isSensorSilent` — primary surgery target
- `src/agents/alerter/src/bridge-client.js` — WS subscription + per-topic cache pattern; new `currentMode` cache lands here
- `src/agents/alerter/src/message.js` — `formatProblem` extension for D-04 last-known summary
- `src/agents/alerter/test/rules.test.js`, `message.test.js` — test surface

### Bridge (New Subscriptions)
- `src/mission-control/bridge/src/index.js` — ROS subscription + WS forward pattern (existing fc1/* subscriptions are the template)

### Backlog Items Composed With / Resolved By This Phase
- ROADMAP backlog 999.22 — alerter ops thresholds in env (RESOLVED by ALRT-08/09)
- ROADMAP backlog 999.39 — alerter offline-blind rules + pi-alert last-known summary (BUNDLED per D-04)

### Operating Memory (Project-Specific)
- `feedback_diff_repo_vs_pi_systemd` — diff repo vs Pi `/etc/systemd` before committing (alerter unit may have drifted)
- `project_alerter_watchdog_quiet_topic_bug` — sht30_fresh-as-ping band-aid (`ALERT_SENSOR_OFFLINE_MIN=1440`); D-03 + D-05 Tier C should let us un-band-aid this
- `feedback_run_verifications_yourself` — execute curl/probe/log-read steps before stalling

### Reference (Tuning Data Source)
- TimescaleDB on elder-plops — `alert_history` table (or `mushy-alerter` docker logs as fallback per D-07) — Phase 17 onward

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`bridge-client.js` per-topic cache pattern** — `currentMode`, `alerterModeOverrides`, `alerterGlobals` slot in cleanly alongside existing `humidifierLastMsgTs` etc.
- **Bridge `fc1/*` subscription scaffolding** — `src/mission-control/bridge/src/index.js` already runs rclnodejs subscriptions and forwards to WS clients; new topics follow the same template.
- **Phase 28 TRANSIENT_LOCAL/RELIABLE QoS profile (`actuator_qos`)** in `fc_controller.py:186` — re-use for the new `alerter_mode_overrides` / `alerter_globals` publishers.
- **Phase 28 `on_set_parameters_callback` validator** — already enforces the dotted-key invariants we'd extend with new `modes.{name}.alerter.*` keys.

### Established Patterns
- **WS-only alerter contract** — never query Timescale at runtime; Tier B/C delivery via WS preserves this.
- **Atomic mode swap via SetParameters batch** — Phase 28 D-12; Phase 29 mode-swap reset (D-09) hooks into the same swap event.
- **TRANSIENT_LOCAL → on-connect replay** — Phase 28 Pitfall-2 mitigated via startup republish; bridge inherits this for free.

### Integration Points
- **Bridge index.js** — new ROS subscriptions + WS broadcasts (3 new topics).
- **Alerter bridge-client.js** — new WS message handlers + caches.
- **Alerter rules.js** — read from caches instead of `config`; gate by freshness state (D-03).
- **Alerter message.js** — extend pi-offline formatter (D-04 carry-over from 999.39).
- **fc_config.yaml `modes.*` block** — extend with `.alerter.*` sub-block (Tier B keys).
- **fc_controller.py** — declare new `modes.{name}.alerter.*` ROS params; publish two new topics (D-06).
- **Tests** — `rules.test.js`, `message.test.js`, plus a new `bridge-client.test.js` if mode-cache logic warrants it.

</code_context>

<specifics>
## Specific Ideas

- **Tuning analysis artifact** (`29-COOLDOWN-TUNING.md`) is a one-shot deliverable, not maintained doc. Lives next to PLAN.md files; referenced from SUMMARY.md.
- **Backwards-compat path:** `.env` keeps old `ALERT_*` vars as bootstrap fallback values (D-03 state 3) and Tier C deploy-time defaults; nothing removed from `.env` until the WS broadcast loop is proven on fc1.
- **Mode-swap dedup reset (D-09)** is the kind of detail a planner would want a dedicated test for — mention in PLAN.md.

</specifics>

<deferred>
## Deferred Ideas

- **Alerter writes to Timescale `alert_history` table** — would let D-07 tuning analysis use SQL instead of log parsing. Composes with 999.35 (daily maintenance digest reads from same table). Not in scope for Phase 29.
- **999.35 alerter self-pathology meta-watchdog** — daily maintenance agent / clockwork-alarm detector. Separate scope.
- **Per-rule custom freshness thresholds** (e.g. `humidifier_stale_min` distinct from `sensor_offline_min`) — D-04 picks the simple "reuse `sensorOfflineMin`" answer; revisit if soak data shows it's wrong.
- **Cooldowns keyed by `(alertType, mode)` instead of just `alertType`** — D-09 picks the simpler keying; if pinning swap creates spam, revisit.

</deferred>

---

*Phase: 29-alerter-mode-awareness-cooldown-tuning*
*Context gathered: 2026-05-08*
