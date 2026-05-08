# Phase 31: Experimental forcing modes (`force-condensation`, `force-evaporation`) — Context

**Gathered:** 2026-05-08
**Status:** Ready for planning
**Mode:** Operator-delegated ("same — pick reasonable architecture") — all decisions taken at Claude's discretion against Phase 28/29/30 precedents.

<domain>
## Phase Boundary

Add two timed override modes the farmer can trigger for short experiments:
- `force-condensation` — 100% PWM duty cycle for N minutes
- `force-evaporation` — 0% PWM duty cycle for N minutes

Both auto-revert to the prior active mode on timeout. Start time, end time, and measured RH delta are logged to TimescaleDB so the farmer can review experiment outcomes after the fact.

**In scope:**
- Two new named modes in fc_config.yaml: `force-condensation` and `force-evaporation`.
- An auto-revert TTL primitive in `fc_controller` — when an experiment mode is active, schedule an auto-revert to the prior mode at `start + duration_minutes`.
- A `start_experiment` ROS2 service on `fc_controller` that takes `(experiment_name, duration_minutes)` and returns `(ok, started_at_iso, reverts_at_iso, prior_mode)`.
- Bridge HTTP `POST /control/experiment` endpoint that wraps the service, called from Signal command + future farmer-app button.
- Phase 25 Signal command parser extension to accept `/force-condensation N` and `/force-evaporation N`.
- TimescaleDB table + write path for experiment events (start, end, prior_mode, requested_duration, actual_duration, baseline_rh, final_rh, delta_rh).
- Single-experiment lockout: only one experiment may be active at a time; second `start_experiment` call while one is running rejects with a clear message.
- Hard duration cap (120 min) enforced by both bridge and controller.

**Out of scope (explicitly):**
- VPD-targeted forcing modes — Phase 31+ once VPD telemetry exists (Phase 999.27 / 999.33).
- Any UI surface beyond Signal in v0. Farmer-app button is a thin POST to the bridge endpoint when 999.11 lands; no new endpoint needed.
- Calendar / scheduled experiments. Experiments are always farmer-triggered, never scheduled.
- Multi-step experiments ("force-condensation 10 min, then force-evaporation 10 min, then return"). Out of v0; one experiment per trigger.
- Per-experiment PID gain overrides — forcing modes bypass PID entirely (100%/0% duty), so PID gain is not a knob.
- Temperature-aware safety lockouts — temp control isn't in scope yet; if temp control lands later, revisit safety envelope (deferred).
- Resumption-after-fc-core-restart of an in-flight experiment. If fc-core restarts mid-experiment, on boot the prior_mode (from runtime overlay) is restored and the experiment is logged as truncated. Documented behavior; not a separate feature.

</domain>

<decisions>
## Implementation Decisions

### Mode Definitions (closes EXPT-01, EXPT-02)
- **D-01:** Forcing modes are **named modes in the same schema** as fruiting/pinning (Phase 28 D-01). Add to `fc_config.yaml` under `fc_controller.ros__parameters.modes.*`:
  - `force-condensation`: declarative shape `(target=null, band_low=0.0, band_high=1.0, defend_side=both, T_target=null, force_duty=1.0)`. New optional field `force_duty` is a 0.0–1.0 scalar; when present, controller short-circuits PID and emits `force_duty` directly to slow-PWM driver.
  - `force-evaporation`: same shape but `force_duty=0.0`.
  - The widely-permissive bands are intentional: forcing modes by definition violate normal target bounds; no alerter alarms during force per Phase 28 D-21 (defended-edge rule won't fire because alerter sees the active mode's bands).
- **D-02:** `force_duty` is the **only mode-schema extension** Phase 31 introduces. Existing modes (fruiting, pinning) leave `force_duty=null` (or absent → null). Controller behavior: if `force_duty` is set, skip PID + Mode C entirely and command slow-PWM at the literal duty value. PID integrator parked while force_duty is active; bumpless re-engage on revert (same primitive as Phase 28 D-12).
- **D-03:** Forcing-mode entry is **service-only**, not via plain `set_mode`. Rationale: a force-mode without a TTL is dangerous (100% duty indefinitely could over-saturate the chamber if the operator forgets to revert). The TTL is the safety envelope, so entry must be coupled to a duration commitment. `set_mode('force-condensation')` is rejected by validator unless preceded by `start_experiment`.
- **D-04:** `force_duty=1.0` is interpreted by the slow-PWM driver as continuous-on (no cycling). `force_duty=0.0` is continuous-off. No min-pulse / dwell semantics apply during force — same as Phase 27 Mode C bypass.

### Auto-Revert TTL (closes EXPT-01/02 timeout requirement)
- **D-05:** TTL implementation: when `start_experiment` is invoked, controller records `(experiment_mode, prior_mode, started_at_monotonic, reverts_at_monotonic, requested_duration_min, baseline_rh)` in an in-memory `ActiveExperiment` struct, then calls the existing in-process mode-swap routine to engage the experiment mode. A `create_timer` callback at 1 Hz checks `monotonic() >= reverts_at_monotonic` and, when true, fires the revert: in-process `set_parameters('active_mode', prior_mode)` + bumpless re-engage + clear `ActiveExperiment` + write the experiment-end record to bridge.
- **D-06:** Use **monotonic clock** (not wall clock) for TTL math so a system clock step (NTP correction) cannot extend or truncate an experiment unexpectedly. Wall clock is recorded only for human-readable start/end timestamps in the TimescaleDB log.
- **D-07:** **prior_mode capture** = whatever `active_mode` resolved to at the instant `start_experiment` ran (could be `fruiting`, `pinning`, or even a scheduler-set mode). Auto-revert restores exactly that mode. Phase 30's scheduler will re-take control on its next tick (D-08 boundary check) if the wall clock has crossed a window — that's the intended Phase 30 + 31 interaction.
- **D-08:** **Phase 30 interaction:** If a scheduler boundary fires while a force experiment is active, the scheduler is **suppressed for the duration of the experiment**. Implementation: scheduler tick checks `if active_experiment is not None: return` (no-op). On revert, the next scheduler tick (≤30s later) realigns mode to whatever the schedule says for current time. This avoids a scheduler "fighting" the experiment, and avoids a stale prior_mode after the schedule has moved on. Documented in scheduler comments.
- **D-09:** **fc-core restart during experiment:** On `__init__`, if `runtime_overrides.yaml` shows `active_mode = force-*`, log a WARNING, force `active_mode` back to a safe baseline (`fruiting` if defined, else first mode in `modes:`), and write a truncated experiment-end record (with `actual_duration_min = NaN`, `final_rh = NaN`, note="truncated_by_restart"). Pre-existing post-Phase 28 overlay-write semantics make this safe. Reasoning: never come back up running 100% duty after a crash.

### `start_experiment` Service (signature lock)
- **D-10:** Service definition lives in `fc_msgs` (already created in Phase 28 D-13). New `fc_msgs/srv/StartExperiment.srv`:
  ```
  string experiment_name           # 'force-condensation' | 'force-evaporation'
  uint32 duration_minutes          # 1..120 inclusive
  ---
  bool ok
  string message                   # human-readable reason on failure
  string started_at_iso            # ISO 8601 UTC, empty on failure
  string reverts_at_iso            # ISO 8601 UTC, empty on failure
  string prior_mode                # the mode the experiment will revert to
  ```
- **D-11:** Validation order in service handler:
  1. `experiment_name` ∈ {`force-condensation`, `force-evaporation`} (else `ok=false, message="unknown_experiment"`)
  2. `1 <= duration_minutes <= 120` (else `ok=false, message="duration_out_of_range"`)
  3. `active_experiment is None` (else `ok=false, message="experiment_in_progress"`)
  4. `active_mode` declared and resolves cleanly (else `ok=false, message="controller_not_ready"`)
  Then engage.

### Single-Experiment Lockout & Hard Cap
- **D-12:** Single in-flight experiment guard is the `active_experiment` variable in `fc_controller`. Both the service and the bridge endpoint use it. There is **no separate "queue"** for experiments. Operator must wait or explicitly cancel.
- **D-13:** A `cancel_experiment` service is included in v0 (lightweight: forces immediate revert + writes a normal end-record with `actual_duration_min` set). Without this, an operator who triggered "120 min force-evaporation" by mistake would be stuck waiting. Same `fc_msgs` package; trivial handler.
- **D-14:** Hard cap of **120 minutes** validated at TWO sites: bridge endpoint (rejects before reaching ROS) and controller service handler (defense in depth). Default duration when farmer doesn't specify (Signal command without N) = **15 minutes** (a comfortable "I want to see what happens" window, well under the cap, well above the slow-PWM 120s window primitive).

### Trigger Surface (closes EXPT-01/02 trigger requirement)
- **D-15:** **v0 trigger = Signal-only.** New parser entries in `src/agents/alerter/src/signal_commands.js` (or wherever Phase 25 lives):
  - `/force-condensation [N]` → defaults N=15 if omitted
  - `/force-evaporation [N]` → defaults N=15 if omitted
  - `/cancel-experiment` → calls cancel_experiment
  Signal handler POSTs to bridge `/control/experiment` (or `/control/cancel-experiment`); bridge calls ROS service.
- **D-16:** **farmer-app button** is filed as Phase 999.11 follow-on. Phase 31 ships the bridge endpoint shape that 999.11 will consume; no farmer-app code in scope.
- **D-17:** Mission Control (OpenMCT) gets nothing for Phase 31 v0 — consistent with Phase 28 D-20 (farmOS owns UI).

### Bridge HTTP Surface
- **D-18:** New endpoints on bridge (Phase 28 D-17 precedent):
  - `POST /control/experiment` — body `{name: 'force-condensation'|'force-evaporation', duration_minutes: int}`. Returns service response (200 on ok, 4xx on validation failure).
  - `POST /control/cancel-experiment` — no body. Returns ok or "no experiment active".
  - `GET /control/experiment` — returns current `active_experiment` state (null when none active) for UI polling.
- **D-19:** Both endpoints validate against Phase 31 hard caps (D-14) and route to `fc_controller` services via the existing rclnodejs client (Phase 27.1 / Phase 28 plumbing).
- **D-20:** No new allowlist entry needed — these are dedicated endpoints, not generic param-set. Allowlist only gates the param-set surface (Phase 28 D-17, Phase 30 D-13).

### TimescaleDB Logging (closes EXPT-03)
- **D-21:** New TimescaleDB table `fc_experiments`:
  ```sql
  CREATE TABLE fc_experiments (
    id            BIGSERIAL PRIMARY KEY,
    started_at    TIMESTAMPTZ NOT NULL,
    ended_at      TIMESTAMPTZ,
    experiment    TEXT NOT NULL,                -- 'force-condensation' | 'force-evaporation'
    prior_mode    TEXT NOT NULL,
    requested_min INT NOT NULL,
    actual_min    INT,                          -- NULL while in-flight; populated on revert/cancel
    baseline_rh   REAL,                         -- RH at start, captured by bridge from latest live telemetry
    final_rh      REAL,                         -- RH at end
    delta_rh      REAL,                         -- final - baseline (computed on end-write)
    end_reason    TEXT                          -- 'timeout' | 'cancelled' | 'truncated_by_restart'
  );
  CREATE INDEX ON fc_experiments(started_at DESC);
  ```
  Migration runs in bridge `initDb()` (idempotent CREATE TABLE IF NOT EXISTS), same pattern as Phase 27.1 buffer table.
- **D-22:** Write path: bridge writes start row immediately on a successful `start_experiment` (so an fc-core crash mid-experiment leaves a row with `ended_at=NULL`). On the corresponding `experiment_event` topic message (or controller cancel/timeout signal), bridge updates the row with end fields. Controller publishes `fc1/control/experiment_event` (TRANSIENT_LOCAL) carrying `{event: 'started'|'ended'|'cancelled'|'truncated', actual_minutes, final_rh}`. Bridge subscribes and updates the row.
- **D-23:** **delta_rh computation site = bridge** (not controller). Reasons: (a) bridge has direct DB access and no real-time constraint, (b) controller's job is control + topic publishing, (c) baseline_rh and final_rh are sampled from the bridge's last-known live telemetry buffer at the start/end instants — same buffer that already powers `current_rh` displays. Tradeoff accepted: ±1 measurement-period of imprecision (~5–10s) is irrelevant for an N-minute experiment.
- **D-24:** Cleanup: `fc_experiments` is small (one row per farmer experiment, low cardinality). No retention policy in v0 — keeps every experiment forever for trend analysis. Revisit if cardinality ever becomes a concern (won't).

### Safety Envelope
- **D-25:** Hard cap (D-14): 120 min. Default duration (D-14): 15 min.
- **D-26:** Boot-time safety (D-09): never come up running a force mode. Always revert to safe baseline on `__init__`.
- **D-27:** Single-experiment lockout (D-12): no concurrent experiments.
- **D-28:** No temperature lockout in v0 — temperature isn't in the control loop yet. If temperature control lands later, revisit. Documented as deferred safety knob.
- **D-29:** No "max experiments per day" rate limit. Farmer judgment is the rate limit. Add if abuse pattern emerges (won't — single farmer, careful operator).

### Observability
- **D-30:** Every experiment event logs INFO at controller and bridge sides: `[experiment] started: force-condensation 15min, prior=fruiting, reverts=2026-05-08T18:30:00Z`.
- **D-31:** `current_mode` topic continues to publish on every transition (Phase 28 D-15). When experiment engages, `current_mode.name = 'force-condensation'`, `current_mode.source = 'service_call'` (or new value `'experiment'`; defer to planner). When auto-revert fires, `current_mode.name = prior_mode`, `current_mode.source = 'service_call'` (or `'experiment_revert'`). Planner picks the cleanest enum.

### Alerter Coordination (Phase 29 implication is bounded)
- **D-32:** Alerter doesn't need to know about experiments. Phase 28 D-21 means alerter checks defended edges of the *currently active* mode; force modes have wide-open bands by design (D-01) so no alarms fire. The "no experiment alarms" rule is satisfied automatically without alerter changes. Documented to forestall scope creep.

### Claude's Discretion (planning may refine)
- Exact wire shape of `fc1/control/experiment_event` topic — string-encoded JSON vs custom msg in `fc_msgs`. Custom msg is cleaner; string is simpler. Planner picks.
- Whether `cancel_experiment` is a separate srv or a special case of `start_experiment` with `experiment_name='cancel'`. Separate srv is cleaner.
- Whether to include a `reverts_in_seconds` countdown field on `current_mode` while an experiment is active. Nice for UI; lock at planning.
- Exact value of "safe baseline" on D-09 boot recovery — `fruiting` if declared, else first mode key. Lock at planning if there's a corner case.
- Whether bridge's `GET /control/experiment` should include a server-computed `seconds_remaining` (probably yes; trivial).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 31 anchors
- `.planning/REQUIREMENTS.md` EXPT-01..03 — phase requirements.
- `.planning/ROADMAP.md` Phase 31 entry — phase boundary anchor.

### Phase 28 carry-forward (mandatory — Phase 31 builds directly on these)
- `.planning/phases/28-mode-primitive-2-baseline-modes-fruiting-pinning-runtime-config-delivery/28-CONTEXT.md` — D-01 (mode schema), D-12 (bumpless re-engage), D-13 (fc_msgs Mode + source), D-15 (current_mode republish), D-16 (set_mode service signature), D-17 (bridge two-layer endpoints), D-21 (alerter defended-edge rule).
- `.planning/phases/28-.../28-04-SUMMARY.md` — current_mode publisher + set_mode service implementation site. start_experiment service lives next to it.

### Phase 30 carry-forward (interaction is locked, not free)
- `.planning/phases/30-time-of-day-mode-scheduling/30-CONTEXT.md` — D-08/D-11 establish manual-override semantics. Phase 31 D-08 above defines the experiment-vs-scheduler precedence rule (experiment suppresses scheduler).
- Phase 30 plans (`.planning/phases/30-.../30-0[1-3]-PLAN.md`) — scheduler timer site (`fc_controller._scheduler_tick`). Phase 31 reuses this timer pattern for the TTL check.

### Phase 27.1 carry-forward (TimescaleDB write pattern)
- `.planning/phases/27.1-edge-buffering-fc1-telemetry-replay-on-reconnect-shipped-2026-05-03/27.1-CONTEXT.md` — bridge `initDb()` pattern, idempotent migration, ON CONFLICT DO NOTHING semantics. Phase 31 D-21 follows this for `fc_experiments` table.

### Phase 25 carry-forward (Signal command parser)
- `.planning/phases/25-bidirectional-signal-farmer-robot-capture-channel/` (SUMMARY files) — locates the Signal command parser; Phase 31 D-15 extends it.

### Code (read before touching)
- `src/chambers/fc-core/fc_core/fc_controller.py` — start_experiment + cancel_experiment service handlers, ActiveExperiment state, 1Hz TTL timer all land here. Reuses Phase 28's _engage_pid_bumplessly + Phase 30's _scheduler_tick precedent.
- `src/chambers/fc-core/fc_core/pwm_driver.py` (or wherever slow-PWM lives) — confirm `force_duty` short-circuit (D-02) is wired at the right layer; if duty resolution lives in fc_controller already, no driver change needed.
- `src/chambers/fc-core/config/fc_config.yaml` — add `force-condensation` and `force-evaporation` mode definitions.
- `src/chambers/fc-msgs/srv/StartExperiment.srv` (new), `CancelExperiment.srv` (new) — service definitions.
- `src/mission-control/bridge/src/index.js` — wire new endpoints + experiment_event subscriber + DB migration call.
- `src/mission-control/bridge/src/control_experiment.js` (new) — endpoint handlers, dual-validation (D-19), DB write paths.
- `src/agents/alerter/src/signal_commands.js` (or equivalent path from Phase 25 SUMMARY) — `/force-*` and `/cancel-experiment` parser entries.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`_engage_pid_bumplessly()`** (Phase 28 D-12) — used on experiment-engage AND auto-revert. Same primitive, four sites now (Mode C exit, manual set_mode, scheduler-driven swap, experiment swap).
- **fc_msgs package** (Phase 28 D-13) — already exists; just adds two new srv definitions. `colcon build` already wired through deploy.sh.
- **Bridge rclnodejs client** (Phase 27.1) — already has SetParameters wired; CallService is a small extension of the same library.
- **Bridge `initDb()` migration pattern** (Phase 27.1) — `CREATE TABLE IF NOT EXISTS` + idempotent indexes. Phase 31 D-21 plugs in.
- **Bridge TRANSIENT_LOCAL subscription pattern** (Phase 27.1) — Phase 31 `experiment_event` topic uses the same pattern; late subscribers (UI poll, audit) get last value.
- **Phase 30 scheduler tick** — Phase 31 D-08 piggybacks on the same 30s tick by adding a single `if active_experiment: return` early-out.
- **Slow-PWM driver short-circuit** — if `force_duty` is None, normal PID-driven duty; if set, literal value emitted. May already be implicit in PWM driver if duty is just "what gets written" — verify in planning.

### Established Patterns
- **Memory `feedback_humidity_runtime_param`** + Phase 28 D-17 — runtime param pattern. Force-mode trigger is service-driven (more deliberate), but the bridge endpoint shape mirrors `/control/param`.
- **Memory `project_phase18_22_farmos_proxy_architecture`** + Phase 28 D-20 — farmOS owns UI; Phase 31 ships endpoints, no Mission Control surface.
- **Memory `feedback_no_sparklines`** — farmer prefers annotated event timeline. `fc_experiments` table is exactly that for experiments. UI consumption is farmOS / 999.11 territory.
- **Memory `project_alerter_is_ws_only`** — alerter doesn't read DB. Phase 31 doesn't change this; alerter remains untouched (D-32).
- **Memory `project_blackout_2026_05_02_fc_core_stuck`** — boot recovery must be safe. D-09 (no force-on-boot) follows.

### Integration Points
- **`fc_controller.__init__`** — D-09 boot-recovery hook lands here, before scheduler init.
- **`fc_controller` create_timer** — 1 Hz TTL-check timer. Cheap; coexists with control + scheduler timers.
- **`fc_msgs/srv/`** — two new srv definitions; build wiring in `fc_msgs/CMakeLists.txt` if any.
- **Bridge `index.js`** — endpoint registration + DB migration call + experiment_event subscriber wiring.
- **Signal parser** — two new commands + dispatch.
- **TimescaleDB** — one new table, one new index. Idempotent migration.

</code_context>

<specifics>
## Specific Ideas

- Default duration 15 min, hard cap 120 min (D-14). Adjust if farmer feedback after first attestation says shorter/longer.
- "force-condensation" and "force-evaporation" are the operator-facing names. Internal mode names match exactly (no translation).
- Boot-recovery (D-09) is the load-bearing safety call. If anything in this phase needs operator validation before ship, it's that scenario.
- The Phase 30 + Phase 31 interaction (D-08) is the subtle bit. Make it visible in tests: spawn a force experiment that spans a scheduler boundary, assert scheduler does NOT fire during it, asserts scheduler DOES re-align after revert.

</specifics>

<deferred>
## Deferred Ideas

- **VPD-targeted forcing** (force to specific VPD setpoint) — needs VPD telemetry (999.27/999.33) and possibly temperature control. v1.6+.
- **Multi-step experiment scripting** ("run condensation 10 min, then evaporation 10 min, then return") — out of v0; one experiment per trigger.
- **Per-experiment PID gain overrides** — N/A while forcing modes bypass PID. Revisit if VPD-targeted forcing lands and needs gain tuning.
- **Temperature safety lockouts** — re-evaluate when temp control enters scope. Not in v1.5.
- **Farmer-app button trigger** — filed as Phase 999.11 follow-on. Phase 31 ships the endpoint that 999.11 will consume.
- **Mission Control UI for experiments** — N/A per Phase 28 D-20 (farmOS owns UI).
- **Rate limiting / quota** — not needed; single trusted operator.
- **Experiment archival / retention policy** — defer until cardinality matters (won't, at single-farmer scale).

</deferred>

---

*Phase: 31-experimental-forcing-modes*
*Context gathered: 2026-05-08*
