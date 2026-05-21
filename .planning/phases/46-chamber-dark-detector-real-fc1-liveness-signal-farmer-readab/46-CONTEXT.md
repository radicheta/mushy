# Phase 46: Chamber-dark detector — real fc1-liveness signal + farmer-readable pi-offline message - Context

**Gathered:** 2026-05-20
**Status:** Ready for planning

<domain>
## Phase Boundary

Hotfix arising from the 2026-05-20 fc1 outage debug session. The alerter's `isPiOffline` rule keys off the alerter↔bridge WebSocket and a one-shot `rosReady` boot flag on the bridge — neither input reflects whether fc1 is actually publishing. During the 10h 47m outage, the only Signal alert that fired was "co2 sensor offline" (per-sensor, vague). This phase makes the alerter detect fc1 publisher silence as the real chamber-dark signal and surfaces it to the farmer as a chamber-level "FC-1 offline, chamber uncontrolled" message that carries last-known telemetry.

In scope: bridge tracks an `fc1LastMsgTs` aggregate across subscribed fc1 topics; alerter consumes it as a third OR-trigger for `isPiOffline`; `formatProblem('pi')` becomes chamber-level using the existing `lastKnown` payload; per-sensor alerts (sht30/co2/RH-OOB) are suppressed while chamber-dark is firing; the existing `wsConnected` + `rosConnected` triggers are retained as defence in depth.

Out of scope: any new chamber-dark cooldown tunable; per-topic alerting; restructuring the existing per-sensor watchdog logic; UI changes beyond the Signal message; the meta-watchdog / self-pathology detection that [[feedback_alerter_needs_meta_watchdog]] flags (belongs in 999.35 daily-maintenance digest).

</domain>

<decisions>
## Implementation Decisions

### Liveness signal shape (bridge → alerter)
- **D-01:** Bridge tracks a single aggregate `fc1LastMsgTs = max(timestamp)` across every subscribed fc1 topic (`humidity`, `humidity_2`, `temperature`, `temperature_2`, `co2`, `humidifier`, `humidifier_duty`, `sensor_health`, `pid_output`). Rationale: triggers chamber-dark only when ALL topics go silent simultaneously, which is the actual "fc1 is dead" pattern. A `min(ts)` aggregator would produce false positives whenever one topic stalls while others are fine (e.g., a single-sensor I2C glitch). Per-topic with an explicit aggregator rule is more flexible but adds surface area without a known need — defer until a per-topic alert use case actually surfaces.
- **D-02:** Bridge `/health` exposes both `fc1.last_msg_ts` (the raw aggregated timestamp) AND `fc1.last_msg_age_sec` (computed convenience for the alerter). Alerter consumes via the existing `pi_liveness` event path through `bridge-client.js`.

### Trigger composition (alerter rules.js)
- **D-03:** `isPiOffline` gets a third OR-trigger: `(now - fc1LastMsgTs) > piOfflineMin*60000`. The existing `wsConnected` and `rosConnected` triggers are RETAINED — they still catch the real failure modes (alerter↔bridge partition, bridge container ROS init failure). The new trigger is additive.
- **D-04:** Chamber-dark shares the existing `piOfflineMin` tunable (Tier C, currently 10 min) and the existing `criticalCooldownMin` (Tier B, currently 60 min). No new env var. Rationale: one knob, one mental model; the new trigger is just another OR-input to the same rule, not a separate alarm class.

### Message shape (alerter message.js)
- **D-05:** `formatProblem({ alertType: 'pi' })` produces a chamber-level message using the `lastKnown` payload `state.js:513-520` already builds. Suggested shape: `FC-1 offline ?? no telemetry XXm. chamber uncontrolled. last RH XX% @ HH:MM.` (no em-dashes per [[feedback_no_em_dashes_in_artifacts]]; rounded numbers per [[feedback_round_farmer_numbers]]). Exact wording is Claude's discretion within these constraints.
- **D-06:** When `lastKnown` is null (cold-start chamber-dark with no prior data), message falls back to `FC-1 offline ?? no telemetry XXm. chamber uncontrolled. no recent samples.` Don't crash.

### Per-sensor alert suppression
- **D-07:** While `perType.pi` is in the FIRING state, the per-sensor watchdogs (sht30_fresh, scd41_fresh, RH-OOB, humidifier-stuck) are SUPPRESSED at the evaluation level — they should not fire or re-fire while chamber-dark is active. Rationale: one alert per outage. Today's outage would have been 1 Signal message instead of 11. When chamber-dark clears (any fc1 topic publishes again), the suppression lifts naturally on the next tick.
- **D-08:** Suppression is one-directional only: chamber-dark suppresses per-sensor alerts. Per-sensor alerts NEVER suppress chamber-dark. This preserves the diagnostic path "co2 sensor offline" → "co2 only" (no chamber-dark, real I2C glitch) and "chamber-dark" → "fc1 itself is gone" (per-sensor noise muted).

### Claude's Discretion
- The exact ASCII rendering of the chamber-dark message (within the constraint of no em-dashes, rounded numbers, and the suggested shape above).
- Whether `lastKnown` payload assembly stays in `state.js` or moves to a small `lastKnown.js` module — refactor only if the suppression logic forces it.
- Whether the bridge's per-subscription handler updates `fc1LastMsgTs` inline or via a shared helper — fine either way as long as every topic path updates it.
- Test naming and file structure within `src/agents/alerter/test/` and `src/mission-control/bridge/test/`.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Debug session that triggered this phase
- `.planning/debug/alerter-co2-only-not-pi.md` — root cause analysis, evidence trail, file:line citations, and the original proposed fix direction. Read this FIRST.

### Related ROADMAP items (closure context)
- `.planning/ROADMAP.md` §999.42 (CLOSED 2026-05-11 by commit `20d8339`) — per-sensor enable flags. Adjacent fix; chamber-dark is a layer ABOVE per-sensor watchdogs, not a replacement.
- `.planning/ROADMAP.md` §999.27 — derived telemetry / `fc_metrics` bridge module. Composes naturally: `fc1LastMsgTs` is itself a derived/liveness channel.

### Code paths (file:line landmarks from the debug session)
- `src/mission-control/bridge/src/index.js:38, 318, 1107` — `rosReady` one-shot boot flag (NOT the right liveness signal; this phase adds a new one).
- `src/agents/alerter/src/rules.js:33-45` — `isPiOffline` signature; this phase extends it with a third OR-trigger.
- `src/agents/alerter/src/bridge-client.js:26-34, 57-64` — `wsConnected` (alerter↔bridge WS state); `pollHealth` is where `fc1LastMsgTs` enters the alerter.
- `src/agents/alerter/src/state.js:513-520` — `lastKnown` payload assembly (already builds the data the new message needs).
- `src/agents/alerter/src/state.js:69-73, 134-135` — `cooldownMs` + lastFiredAt cooldown gate. D-04 says chamber-dark uses these existing knobs.
- `src/agents/alerter/src/message.js` — `formatProblem({ alertType: 'pi' })`. D-05/D-06 rewrite this.

### Cross-cutting memory pointers (read for tone and constraints)
- [[feedback_no_em_dashes_in_artifacts]] — farmer-facing messages use `?`/`--`/`n/a`, not em-dashes.
- [[feedback_round_farmer_numbers]] — `fmtNum(n)`; 1 decimal, strip trailing `.0`.
- [[feedback_alerter_needs_meta_watchdog]] — the related "alerter self-pathology" gap; out of scope here but informs framing.
- [[project_alerter_watchdog_quiet_topic_bug]] — sibling pattern (alerter trusting cache too much).
- [[project_alerter_is_ws_only]] — alerter never queries Timescale by design; consume only WS-side signals.
- [[project_2026_05_20_fc_buffer_real_outage_validation]] — the outage that motivated this phase.
- [[project_elder_plops_dual_role]] — elder-plops is dev+prod; rebuild of bridge+alerter ships to f1 immediately. Atomic deploy required.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `pi_liveness` event path: alerter already plumbs WS/ROS liveness from bridge `/health` through `bridge-client.js` `pollHealth` into the state machine. Adding `fc1LastMsgTs` is one more field on the same payload.
- `lastKnown` payload (`state.js:513-520`): already carries last-RH, last-T, last-humidifier-state, last-timestamp. D-05 just routes it into `formatProblem('pi')` instead of letting it sit unused for the pi-alert path.
- `cooldownMs` + `criticalCooldownMin` Tier B: existing rate-limit mechanism; chamber-dark inherits.
- `transientLocalQos` shared profile (999.40, commit `092f43f`): all 9 fc1 topic subscriptions on the bridge already use it. The new `fc1LastMsgTs` updater piggybacks on those existing handlers.

### Established Patterns
- Bridge subscriptions follow a uniform shape (subscribe → handler → broadcast over WS). Each handler is the natural place to bump `fc1LastMsgTs`. Either inline `Math.max(fc1LastMsgTs, msg.timestamp)` per handler, or a tiny `markFc1Active(ts)` helper called from each.
- Alerter state machine evaluates per-type per-tick (`state.js` main eval loop). Chamber-dark suppression is naturally expressed as "if perType.pi.state === FIRING, skip evaluation of sht30/scd41/rh/humidifier-stuck".
- `pollHealth` already validates and normalizes the bridge `/health` JSON; one more nullable field follows the same pattern.

### Integration Points
- Bridge → `/health` payload schema: must add `fc1: { last_msg_ts, last_msg_age_sec }` without breaking existing consumers. Field is purely additive.
- Alerter `bridge-client.js` → `pi_liveness` event: payload gets one new field; downstream `state.js` listener must handle null gracefully for old bridge versions (defensive — atomic deploy mitigates).
- elder-plops rebuild: `docker-compose up -d --build bridge alerter` is one command, both containers come up with the new schema. If only one rebuilds, the new field is missing and the old `isPiOffline` triggers still work — graceful degradation.

</code_context>

<specifics>
## Specific Ideas

- Today's outage as the implicit reference behavior: had this phase shipped before 2026-05-20, the farmer would have received ONE Signal message at ~13:14 UTC reading `FC-1 offline ?? no telemetry 10m. chamber uncontrolled. last RH 94.0% @ 13:04.` instead of 11 "co2 sensor offline" messages. That's the unit test of success.
- The `fc1LastMsgTs` aggregator is conceptually similar to a "publisher heartbeat" — it's an inferred heartbeat derived from data flow rather than an explicit `/fc1/controller_heartbeat` topic. The latter would also work but requires controller-side work (Python publisher); the former is bridge-only JS and lands faster.

</specifics>

<deferred>
## Deferred Ideas

- Explicit `/fc1/controller_heartbeat` topic from fc_controller (Python side) — would also satisfy chamber-dark detection but adds controller-side work. Inferred-heartbeat-from-data-flow (D-01) is sufficient for this phase. If a future need arises (e.g., distinguishing "controller running but not publishing" from "controller dead"), the explicit topic can be added without invalidating D-01.
- Meta-watchdog / alerter self-pathology detection ([[feedback_alerter_needs_meta_watchdog]]) — the "alerter is sending identical CRITICAL alarms hourly" detector. Belongs in 999.35 daily-maintenance digest, not here.
- Per-topic chamber-dark alerts (e.g., "humidifier topic stalled while sensors are fine") — D-01's max-aggregator doesn't surface this. Worth filing as a 999.* item if it ever actually happens; speculative for now.
- Migrating `lastKnown` payload to a dedicated `lastKnown.js` module — refactor only if D-07's suppression logic forces it.

</deferred>

---

*Phase: 46-chamber-dark-detector*
*Context gathered: 2026-05-20*
