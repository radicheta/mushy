# Phase 30: Time-of-day mode scheduling — Context

**Gathered:** 2026-05-08
**Status:** Ready for planning
**Mode:** Operator-delegated ("go ahead you pick reasonable architecture") — all decisions taken at Claude's discretion against Phase 28 precedents.

<domain>
## Phase Boundary

Add a declarative time-of-day schedule that drives mode-switch service calls at window boundaries. Closes backlog 999.23 (canonical target becomes a function of clock instead of a static config). Default profile remains the existing constant-single-mode case (no schedule block → single mode), preserving backward compatibility with HUMID-* and MODE-*.

**In scope:**
- Schedule schema (declarative time-of-day windows → mode names) under fc_controller params.
- Scheduler timer inside `fc_controller` that fires `set_mode` at boundaries.
- Source attribution on `current_mode` topic (`source: 'scheduler'` already reserved in Phase 28 D-13).
- Runtime editability via the same two-layer (Layer 1 ros2 param + Layer 2 overlay-yaml persistence) path Phase 28 established.
- Bridge HTTP allowlist extension to permit schedule edits.
- On-startup alignment: scheduler picks the active window for "now" and calls `set_mode` immediately so reboot-into-the-middle-of-a-window comes up correctly.

**Out of scope (explicitly):**
- Stage-triggered transitions ("spawn-run start" → schedule advances). Deferred to v1.6 per REQUIREMENTS.md "Future Requirements".
- Per-mode PID gains. Deferred (v1.6).
- Mission Control schedule UI. farmOS owns UI surface (Phase 28 D-20).
- Multiple schedule profiles or schedule swapping at runtime. v0 ships exactly one active schedule at a time.
- Calendar-aware scheduling (DST transitions, day-of-week patterns, growth-cycle aware). v0 is a single 24h pattern repeated daily.
- Active forcing modes (`force-condensation` / `force-evaporation`) — Phase 31.

</domain>

<decisions>
## Implementation Decisions

### Schedule Schema & Location (closes SCHED-01)
- **D-01:** Schedule lives under `fc_controller.ros__parameters` as a **single JSON-encoded string param** named `schedule_windows`. Default value: `"[]"` (empty array → no schedule active, single-mode behavior preserved per SCHED-03). Reason: rclpy has no native list-of-dict params; the Phase 28 D-03 dotted-key trick works for fixed mode shapes but not for an unknown number of windows. JSON string is the same primitive farmOS already speaks, validates cleanly via `on_set_parameters_callback`, and allows the whole schedule to be edited atomically via Layer 1 in one param set.
- **D-02:** Window shape: `{"start": "HH:MM", "end": "HH:MM", "mode": "<mode_name>"}`. Times are local (fc1 system TZ — Montevideo). Half-open intervals `[start, end)`. Wraparound supported: if `end < start` the window crosses midnight (e.g. `{"start":"22:00","end":"06:00","mode":"pinning"}`).
- **D-03:** Validation rules in `on_set_parameters_callback`:
  - Each window must have `start`, `end`, `mode` keys; times match `HH:MM` regex; mode name must exist in declared modes (`fruiting`, `pinning` baseline).
  - **Coverage check is advisory, not enforced** — gaps are allowed (gap behavior in D-08); overlaps are warnings, last-defined-wins.
  - Empty array always valid (= disabled).
  - Reject malformed JSON, unknown mode names, or invalid time format. Old value retained on reject (Phase 28 callback pattern).
- **D-04:** Schedule edits are atomic — whole array replaced in one set. No "edit window 3 only" granular API in v0; farmOS submits the full array. Simpler, no concurrency bugs, matches how farmOS already round-trips config.
- **D-05:** SCHED-03 backward-compat is automatic via D-01 default `"[]"`. Existing fc1 config with no `schedule_windows` key continues to use `active_mode` (Phase 28 D-04 / D-16) untouched. No migration step.

### Scheduler Implementation Site (closes SCHED-02)
- **D-06:** Scheduler lives **inside `fc_controller` node** as a `create_timer` callback. Reasons: (a) Phase 27.2 trauma — every new ROS node is new deploy surface and a new boot-race risk, and SYS-04 scenario 2 is still deferred; (b) scheduler shares the controller's clock and lifecycle (no inter-process time skew); (c) `set_mode` service call becomes a direct in-process function call (no rclpy client round-trip), eliminating the failure mode where service call times out and schedule "skips a window"; (d) reuses the same `_engage_pid_bumplessly()` primitive Phase 28 D-12 already wires up for service-driven swaps.
- **D-07:** Timer cadence: **30s**. Boundary precision is 30s worst case, which is well under PID's relevant timescales (RH thermal lag ≫ 30s). Cheap, bounded, no need for clever drift-correction.
- **D-08:** On every tick, scheduler:
  1. Reads current `schedule_windows` (live via `get_parameter` — Phase 28 hot-reload pattern).
  2. If empty → no-op (single-mode behavior).
  3. Else compute `desired_mode` for current local time (first matching window; on overlap last-defined wins; on gap → keep current mode unchanged, log warning once per gap entry).
  4. If `desired_mode != active_mode` AND last transition source was NOT manual-within-current-window (D-09) → fire internal mode switch with `source='scheduler'`.
- **D-09:** **Startup alignment:** On `fc_controller` `__init__`, after PID initialization but before first control tick, scheduler does one immediate evaluation. If `schedule_windows` non-empty and `desired_mode != active_mode` (config_default mode), it fires the swap with `source='scheduler'` and records `effective_since=now`. Solves "fc1 reboots at 23:00, comes up in `fruiting` config_default, should be `pinning`" cleanly.

### Manual Override Semantics (operator UX call)
- **D-10:** Manual `set_mode` (source `service_call`) **wins until the next window boundary**. Schedule fires unconditionally at boundaries; manual override is ephemeral. Rationale:
  - Predictable: farmer mental model is "I overrode it for now, schedule resumes at the next boundary." No hidden "stuck in manual" state.
  - No-state: scheduler doesn't track an override flag — it just compares `desired_mode` to current and fires at boundaries. Implementation is one-liner.
  - Recovery-safe: if farmer forgets they manually swapped, system self-heals at the next window.
  - To lock manual indefinitely: farmer/farmOS sets `schedule_windows` to `[]` (one Layer 1 call) — which is the explicit "disable schedule" gesture and matches D-05.
- **D-11:** Implementation detail: scheduler at every tick computes `desired_mode` from clock and checks `desired_mode != active_mode`. The manual override "expires at next boundary" naturally because at the next boundary the scheduler-desired mode changes to the new window's mode and the inequality fires. Within the same window, manual overrides do persist until that window ends.
- **D-12:** Audit trail: every transition writes `current_mode` topic with `source` field set correctly (`'scheduler'` on schedule-initiated, `'service_call'` on manual, `'config_default'` on initial boot before scheduler aligns). Phase 29 alerter already consumes this topic so transitions are visible in alert context for free.

### Runtime Edit Path (closes 999.23 the Phase 28 way)
- **D-13:** **Layer 1 (hot edit):** `schedule_windows` is added to the Phase 28 D-17 bridge `POST /control/param` allowlist. farmOS posts new schedule JSON, bridge calls `SetParameters` on `fc_controller`, controller validates via `on_set_parameters_callback`, schedule takes effect on the next 30s tick (≤30s).
- **D-14:** **Layer 2 (persistence):** Bridge `POST /control/persist` (Phase 28 D-17) is extended to write `schedule_windows` into `runtime_overrides.yaml` so the schedule survives fc-core restarts. No new endpoint needed — same surface.
- **D-15:** UI surface = farmOS (Phase 28 D-20). Phase 30 ships only:
  - `schedule_windows` param declared in `fc_config.yaml` with default `"[]"`
  - `on_set_parameters_callback` validation extension
  - Scheduler timer + transition logic in `fc_controller`
  - Bridge allowlist extension (one-line change, both layers)
  - Coordinate exact JSON shape with Zoy before bridge wave lands (Phase 18/22 architecture).
- **D-16:** Schedule editing **does NOT** require touching mode definitions. Modes (`fruiting`, `pinning`) are still added/edited via Phase 28's path. Schedule is a separate concern that *references* modes by name.

### Source Attribution & Mode Topic Behavior
- **D-17:** `current_mode` topic continues to be republished on every transition (Phase 28 D-15). Scheduler-initiated transitions populate `source='scheduler'`. The `effective_since` timestamp is updated on each transition (so alerter / UI can show "in this mode since 22:00").
- **D-18:** Phase 29's mode-aware alerter automatically inherits scheduler behavior — it reads `current_mode`, doesn't care about source. No alerter changes required for Phase 30. (Documented to forestall scope creep.)

### Logging & Observability
- **D-19:** Every schedule transition logs at INFO: `[scheduler] transition: <prev_mode> → <new_mode> at <local_time> (window=<start>-<end>)`. Gap entries log at WARNING once per gap (debounced to one log per window-entry, not per tick).
- **D-20:** No new telemetry topic for "scheduled vs manual" — `current_mode.source` is the answer.

### Time Source
- **D-21:** Use fc1 system clock. fc1 already runs NTP via systemd-timesyncd (verified via memory `project_blackout_2026_05_02_fc_core_stuck` — clock was correct after recovery). DST is N/A — Montevideo doesn't observe DST. No clock-validity preflight needed in v0.

### Claude's Discretion (planning is free to refine these)
- Exact location of `schedule_windows` declaration in `fc_config.yaml` (top-level under `fc_controller.ros__parameters` is the obvious slot).
- Exact log format / log channel for transitions.
- Whether to put the time-window evaluation logic in a helper module (`fc_core/scheduler.py`) or inline in `fc_controller.py`. Inline is cheaper if it's <40 lines; pull out to helper if test surface grows.
- How to write tests for the wraparound (22:00→06:00) case — pytest with `freezegun` or hand-built clock fakes; planner picks.
- Whether to surface a "next boundary at HH:MM" field on `current_mode` for UI convenience. Likely yes, but locked at planning if it complicates the schema.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 30 anchors
- `.planning/REQUIREMENTS.md` SCHED-01..03 — phase requirements.
- `.planning/ROADMAP.md` Phase 30 entry — phase boundary anchor.

### Phase 28 carry-forward (mandatory — Phase 30 builds directly on these)
- `.planning/phases/28-mode-primitive-2-baseline-modes-fruiting-pinning-runtime-config-delivery/28-CONTEXT.md` — D-13 (Mode.msg with `source` field), D-14 (TRANSIENT_LOCAL on `fc1/control/current_mode`), D-15 (republish on every swap), D-16 (`set_mode` service signature), D-17 (two-layer config delivery), D-19 (explicit save vs auto-commit policy), D-20 (farmOS owns UI).
- `.planning/phases/28-.../28-04-SUMMARY.md` — `current_mode` publisher + `set_mode` service implementation site in `fc_controller.py`. Phase 30 scheduler reuses this.
- `.planning/phases/28-.../28-05-SUMMARY.md` and `28-06-SUMMARY.md` — bridge `/control/param` and `/control/persist` endpoints + allowlist mechanism. Phase 30 extends the allowlist by one entry.

### Phase 29 carry-forward (alerter implication is known and contained)
- `.planning/phases/29-alerter-mode-awareness-cooldown-tuning/29-CONTEXT.md` — establishes that alerter is mode-source-agnostic. D-18 above relies on this.

### Code (read before touching)
- `src/chambers/fc-core/fc_core/fc_controller.py` — scheduler timer + transition logic land here. Mode resolution + bumpless transfer + service handler all already live in this file post-Phase 28.
- `src/chambers/fc-core/config/fc_config.yaml` — `schedule_windows: "[]"` default declaration goes here under `fc_controller.ros__parameters`.
- `src/mission-control/bridge/src/control_param.js` — Phase 28 Layer 1 endpoint; allowlist extension.
- `src/mission-control/bridge/src/control_persist.js` — Phase 28 Layer 2 endpoint; allowlist extension (same key, both layers).

### Backlog closure
- `.planning/REQUIREMENTS.md` "Future Requirements" — confirms stage-triggered transitions and per-mode PID gains stay deferred. Phase 30 closes 999.23 only.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`fc_controller` `_engage_pid_bumplessly()`** (Phase 28 D-12): scheduler-driven mode swaps go through the same primitive that handles manual `set_mode` and Mode-C exit. No new bumpless-transfer code.
- **`on_set_parameters_callback`** (Phase 28): the validation hook that already gates mode + band edits. D-03 schedule validation plugs into the same callback (one extra branch).
- **`set_mode` service handler** (Phase 28): scheduler doesn't call its own ROS service — it directly invokes the in-process mode-swap routine that the service handler also calls. Same code path, no IPC overhead, no timeout failure mode.
- **Bridge allowlist** (Phase 28 D-17): Layer 1 + Layer 2 already gate which params are externally writable. Adding `schedule_windows` is a one-line change in each.
- **`current_mode` topic + `source` field** (Phase 28 D-13/D-14): Phase 30 just sets `source='scheduler'`. No publisher changes; no new topic.
- **`runtime_overrides.yaml` overlay** (Phase 28 D-17): schedule persistence rides this. fc-core launch already loads it after `fc_config.yaml`.

### Established Patterns
- **JSON-string-as-param** (new for Phase 30, but consistent with rclpy primitives): `schedule_windows` is the first JSON-encoded string param. Set the precedent cleanly so future "schedule of X" knobs reuse it.
- **Memory `project_phase18_22_farmos_proxy_architecture`**: bridge ships data + endpoints, farmOS ships UI. D-15 follows this.
- **Memory `feedback_humidity_runtime_param`**: ros2 param set live first, persist second. The Phase 30 farmOS round-trip mirrors this (Layer 1 then optional Layer 2).
- **Memory `project_phase27_2_partial_sys04`**: minimize new deploy surface. Drives D-06 (scheduler in-process, not new node).

### Integration Points
- **`fc_controller.__init__`** — startup alignment hook (D-09) lands here, after PID init.
- **`fc_controller` create_timer** — 30s scheduler timer added alongside existing control + telemetry timers.
- **`fc_config.yaml`** — single new key, single default value.
- **Bridge allowlist (both control_param.js + control_persist.js)** — `schedule_windows` added.

</code_context>

<specifics>
## Specific Ideas

- The user delegated all gray-area decisions explicitly: "go ahead you pick reasonable architecture." Decisions above lean on Phase 27.2 / Phase 28 / Phase 29 precedents wherever a Phase 30 design degree of freedom existed.
- "Manual override expires at the next boundary" (D-10/D-11) is the load-bearing UX call. If operator preference shifts to "manual locks until cleared", flip D-10 — the rest of the architecture is unchanged.
- v0 schedule is intentionally one-pattern-per-day. Day-of-week / calendar-aware schedules and stage-triggered transitions are explicitly future work, already filed under REQUIREMENTS.md "Future Requirements".

</specifics>

<deferred>
## Deferred Ideas

- **Day-of-week schedule patterns** — different schedules on weekends or on growth-stage days. v1.6 candidate.
- **Calendar-aware schedules** — DST handling, named holidays, blackout days. Not relevant for Montevideo (no DST) and not yet on the roadmap.
- **"Next boundary" field on current_mode topic** — UI convenience. Decided at planning if it complicates schema; otherwise nice-to-have.
- **Multiple named schedule profiles + profile swap** ("weekday", "weekend", "fruiting-cycle-week-2"). v0 ships one schedule at a time. Add when farmOS UI grows the concept.
- **Per-mode PID gains** + **Stage-triggered mode transitions** — already deferred to v1.6 in REQUIREMENTS.md "Future Requirements".

</deferred>

---

*Phase: 30-time-of-day-mode-scheduling*
*Context gathered: 2026-05-08*
