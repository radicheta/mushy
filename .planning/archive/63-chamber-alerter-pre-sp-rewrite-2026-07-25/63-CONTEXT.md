# Phase 63: Chamber Alerter - Context

**Gathered:** 2026-07-13
**Status:** Ready for planning

<domain>
## Phase Boundary

Port the Node ROS-bridge WebSocket alerter into the `chamber/` **mushy-private** Python
package under `src/farm-agent/farm_agent/chamber/`. Reproduces:

- the WS bridge client (reconnect + `/health` poll for `fc1LastMsgTs` chamber-dark signal),
- the pure detectors (`rules.js`: RH out-of-band, sensor-error, pi-offline/chamber-dark,
  humidifier-stuck, per-sensor silence),
- the per-alert-type state machine (`state.js`: OK/PENDING/FIRING/SNOOZED, cooldown, severity,
  drive-alert),
- snooze/mute command parsing (`snooze.js`),
- the daily heartbeat scheduler (`heartbeat.js`),
- farmer-facing message formatting (`message.js`) with the **TZ bug fixed to
  America/Montevideo** and round-number formatting.

Requirements in scope: **CHM-01, CHM-02** (see REQUIREMENTS.md).

`chamber/` is the **only** mushy-private package in the port (the Foray seam depends on it).

### NOT in scope
- Parity validation against the golden corpus (Phase 64).
- Cutover / stopping the Node alerter (Phase 65).
- Any new alerting capability beyond Node parity.

</domain>

<decisions>
## Implementation Decisions

### Foray seam direction (CORRECTION — read before planning)
- **D-00 (canonical clarification):** ROADMAP SC3 wording — *"the `chamber/` package has
  zero imports from any non-chamber Foray package"* — is **INVERTED** relative to the actual
  Phase-56 gate. The enforced contract (`.lint-imports` `foray-seam` + `tests/test_foray_seam.py`)
  is a `forbidden` contract in the OPPOSITE direction: **Foray packages must NOT import
  `farm_agent.chamber`**. `chamber/`, as the composing app, is **free to import** `signal_io`,
  `persistence`, `tenancy`, etc. The seam test file itself documents this "ROADMAP token
  divergence." Plan against the real gate direction, not the SC3 prose. Phase 63 activates the
  secondary gate: add `chamber/` to the pytest run so `.lint-imports` is enforced (per
  `.lint-imports` header note "Do NOT add import-linter to the pytest run until Phase 63").

### Runtime config + live overrides  *(discussed this session)*
- **D-01 — Port the full Tier A/B/C effective-config resolver.** Reproduce
  `resolveEffectiveConfig(state, envConfig, nowMs)` verbatim: detectors consume the
  **effective** config, never raw env. Layers:
  - **Tier A (mode-anchored):** `rhTarget = currentMode.target_humidity * 100`, `rhBand` from the
    live ROS `mode` message received over the WS bridge — applies only when mode is FRESH
    (`modeAge <= modeStaleMin`, ws connected).
  - **Tier B (per-mode override):** `oobN`, `oobWindowMin`, `cooldownMin`, `criticalCooldownMin`,
    `humidifierStuckMin` from `alerterOverrides[mode.name]`.
  - **Tier C (global override):** `piOfflineMin`, `sensorOfflineMin`, `heartbeatHour`,
    `maxSendsPerHour` from `alerterGlobals` — apply **independent of mode freshness** (e.g.
    `piOfflineMin` must hold precisely when fc1 is offline / ws disconnected).
  - **Freshness / cold-start gate:** `freshness = {state: fresh|stale|cold, source: mode|env}`;
    stale/cold falls back to env config. This freshness state ALSO feeds `isRhOob` (stale ⇒
    suspend RH rule — the 2026-05-07 false-CRITICAL guard).
  - Rationale: this dynamic RH target IS the live prod behavior (pinning→fruiting setpoint
    moves), and Phase 64's ≥95% parity gate requires it. Static-only would count as a parity
    failure. See memory `dynamic_rh_target_groundwork`, `alerter_rh_two_source_bug`.

- **D-02 — Chamber config lives in a chamber-local `ChamberConfig`, not TenantConfig.** New
  `chamber/config.py` owns ALL alerter knobs. `ChamberConfig` reads only **secrets + shared
  identity** (signal_sender, signal_recipient, signal_api_url, tenant_id, timescale creds) from
  the Foray `TenantConfig`. Keeps the extractable Foray island genuinely free of mushy-private
  alerter concerns (consistent with the ChamberConfig choice).

- **D-03 — MOVE the 7 alerter knobs already sitting in `TenantConfig` into `ChamberConfig`.**
  `rh_target`, `rh_band`, `pi_offline_min`, `sensor_offline_min`, `heartbeat_hour`,
  `max_sends_per_hour`, `timezone` are alerter-only (no extraction/confirm/farmos package reads
  them) and must relocate to `ChamberConfig`. This touches `TenantConfig` + its Phase-56 tests —
  update those references. ChamberConfig then owns the full alerter knob set, including the ones
  not yet ported: `oob_n`, `oob_window_min`, `cooldown_min`, `critical_cooldown_min`,
  `humidifier_stuck_min`, `sht30_enabled`, `scd41_enabled`, `sensor_flap_min_sec`,
  `mode_stale_min`, `mode_boot_grace_ms`, `bridge_ws_url`, `bridge_health_url`, `dashboard_url`,
  `receive_poll_sec`.
  - **Verify no orphaned references:** grep the ported Foray packages (signal_io, confirm,
    extraction, farmos_client, persistence) for reads of these 7 fields before moving — if any
    non-chamber package reads one, that read is itself a latent mis-layering to flag.

- **D-04 — TZ fix (CHM-02): ChamberConfig-driven, default `America/Montevideo`, `TZ` env may
  override.** Message-formatting reads `ChamberConfig.timezone`; the code **default flips
  Toronto→Montevideo**. Preserves Node's config-driven formatting shape (best parity for
  Phase 64) and keeps the knob for future Foray multi-tenant. The *actual* bug fix (per memory
  `alerter_tz_toronto_legacy`): route **ALL** farmer-facing time formatting through the
  configured zone via `ZoneInfo` — the legacy `hhmm()` ignored config entirely and emitted UTC.
  A snapshot test pins a formatted alert to Montevideo/UYT (UTC-3), satisfying SC2. This TZ
  change is **pre-declared as an intentional parity delta** for Phase 64.

### Defaults accepted for un-discussed areas (planner may proceed; not re-opened)
- **D-05 — Signal I/O: reuse, do not duplicate.** chamber **reuses** `signal_io.client` for
  outbound sends and hooks the shared `signal_io.receive_loop`/`router` for INBOUND snooze/mute
  commands (the seam permits chamber→signal_io). One Signal number, one receive loop (built in
  Phase 57) — a second client would double-poll and conflict. Planner: define how the router
  dispatches snooze/mute text to a chamber handler.
- **D-06 — Alert FSM state is IN-MEMORY (Node parity).** Snooze/cooldown/`humidifierOnSinceMs`
  reset on restart, exactly like Node. Required for the Phase-64 parity gate; persisting would
  itself be a parity delta. Durable-snooze deferred to a follow-on only if the farmer hits it.
- **D-07 — Port ALL 6 alert types:** `rh, sensor, pi, humidifier, sht30, scd41`. The roadmap
  goal's "4" is shorthand. `sht30_enabled`/`scd41_enabled` are live prod flags (SHT30 physically
  disconnected since 2026-04-11, muted via flag, not removed). Full parity needed for Phase 64.
  Also carry the `sensor_flap_min_sec` single-tick flap floor (2026-05-12) and the Phase-29/46
  offline-blindness gates on humidifier-stuck.

### Claude's Discretion
- Async mechanics: asyncio task loop + `ZoneInfo` for the heartbeat (replacing Node
  `setInterval` + `Intl.DateTimeFormat`); WS reconnect/backoff shape; how `resolveEffectiveConfig`
  is structured in Python. Planner/executor decide, constrained by parity with Node outputs.

### Folded Todos
- **`2026-05-21-alerter-tz-montevideo-and-local-time-rendering.md`** (match 0.9) — "Fix alerter
  timezone America/Toronto → America/Montevideo + local-time rendering." Folded: this IS CHM-02
  / D-04. The port fixes it at the source (ChamberConfig default + config-driven `ZoneInfo`
  formatting), closing the todo.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & roadmap
- `.planning/REQUIREMENTS.md` §CHM (CHM-01, CHM-02) — the two locked requirements.
- `.planning/ROADMAP.md` §"Phase 63: Chamber Alerter" — goal + SC1–SC3 (note D-00: SC3 wording is
  inverted vs the real gate).

### Node source to port (reference implementation — parity target for Phase 64)
- `src/agents/alerter/src/rules.js` — the 5 pure detectors (RH-oob w/ stale-suspend, sensor-error,
  pi-offline w/ hard-coded 3-min chamber-dark threshold, humidifier-stuck w/ offline-blindness
  gates, sensor-silent).
- `src/agents/alerter/src/state.js` — per-type FSM (OK/PENDING/FIRING/SNOOZED), SEVERITY map,
  `resolveEffectiveConfig` (Tier A/B/C + freshness), drive-alert, cooldown.
- `src/agents/alerter/src/bridge-client.js` — WS client + `/health` poll (`fc1LastMsgTs`).
- `src/agents/alerter/src/heartbeat.js` — daily TZ-aware heartbeat scheduler.
- `src/agents/alerter/src/snooze.js` — snooze/mute grammar (strict + simple).
- `src/agents/alerter/src/message.js` — farmer-facing formatting (the TZ/round-number surface).
- `src/agents/alerter/src/config.js` — the Tier A/B/C/D knob classification (comments are the spec).

### Python port targets & the Foray seam
- `src/farm-agent/farm_agent/tenancy/tenant.py` — `TenantConfig` (sole `os.environ` reader);
  D-03 moves the 7 alerter knobs OUT of here.
- `src/farm-agent/.lint-imports` — the `foray-seam` forbidden contract; Phase 63 activates it.
- `src/farm-agent/tests/test_foray_seam.py` — the grep gate + the "ROADMAP token divergence" note.
- `src/farm-agent/farm_agent/signal_io/client.py`, `receive_loop.py`, `router.py` — reused for
  outbound send + inbound snooze routing (D-05).
- `.planning/phases/56-foundation/56-CONTEXT.md` §D-03/D-05 — package layout + Foray seam decisions.

### Memory (project knowledge — verify against live code before relying)
- `alerter_tz_toronto_legacy` — hhmm() used UTC, not config (the real D-04 bug).
- `alerter_config_env_not_tenant_yaml_live` — live config comes from compose ENV; tenant YAML
  layer is inert in Docker.
- `phase46_d09_globals_shadow_env` — global overrides shadow env; relevant to Tier C.
- `alerter_oob_window_8min` — f1 ignores <4min RH drifts (`ALERT_OOB_WINDOW_MIN=8` in prod).
- `alerter_is_ws_only` — never queries Timescale for alert decisions.
- `dynamic_rh_target_groundwork`, `alerter_rh_two_source_bug` — the dynamic-RH-target rationale
  behind D-01.
- `feedback_round_farmer_numbers`, `feedback_no_em_dashes_in_artifacts` — formatting constraints.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `signal_io.client` (Phase 57) — outbound Signal send with FLAT quote fields (0.200-dev). Reuse
  for chamber alert sends (D-05); do NOT rebuild a Signal client.
- `signal_io.receive_loop` + `router` — inbound message loop; extend routing to dispatch snooze/mute
  to chamber (D-05).
- `tenancy.TenantConfig` — secrets + shared identity; ChamberConfig composes it (D-02).
- `persistence` async pool — available if durable state is ever needed (not this phase, D-06).

### Established Patterns
- **Sole env reader:** business code never reads `os.environ`; config flows through a frozen
  dataclass (TenantConfig pattern). ChamberConfig follows the same shape (frozen, layered,
  secrets via `_must_env`).
- **Graceful degradation on liveness inputs:** detectors treat `None`/absent liveness inputs as
  "no trigger" (opt-in gates) — preserve this exactly (undefined≠false semantics) or parity breaks.
- **Foray seam:** `forbidden` contract Foray↛chamber; chamber→Foray is fine (D-00).

### Integration Points
- WS bridge (`bridge_ws_url`, `bridge_health_url`) — chamber's inbound telemetry + fc1 liveness.
- Shared Signal number — chamber alerts out + snooze commands in via the Phase-57 receive loop.
- `boot.py` — the only cross-package composer; wires chamber into the running process.

</code_context>

<specifics>
## Specific Ideas

- Detectors must consume `resolveEffectiveConfig` output, never raw ChamberConfig — the whole
  point of Tier A/B/C is that live mode messages move the RH target under the detectors' feet.
- Snapshot test for D-04 must assert a concrete Montevideo/UYT (UTC-3) local time on a formatted
  alert — that is SC2's literal proof.

</specifics>

<deferred>
## Deferred Ideas

- **Durable snooze/cooldown across restart** — considered (D-06); deferred. Only revisit if the
  farmer is bitten by a restart un-muting alerts. Would be a Phase-64 parity delta if added now.

### Reviewed Todos (not folded)
- **`2026-05-14-port-alerter-to-farm-agent-python.md`** (match 0.6) — the v1.12 milestone itself,
  not a Phase-63-specific item. Background context, not folded.
- **`2026-05-24-phase50-quote-rendering-broken-end-to-end.md`** (match 0.6) — a **Node-side** bug
  (Phase-50 quote threading builds the nested `quote` shape the 0.200-dev container silently
  drops). Out of scope for the chamber port; the Python `signal_io.client` already sends FLAT
  quote fields (Phase 57). Left for the Node stack until Phase-65 cutover retires it.

</deferred>

---

*Phase: 63-chamber-alerter*
*Context gathered: 2026-07-13*
