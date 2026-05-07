# Phase 28: Mode primitive + 2 baseline modes (`fruiting`, `pinning`) + runtime config delivery — Context

**Gathered:** 2026-05-07
**Status:** Ready for planning

<domain>
## Phase Boundary

Wrap Phase 27's PID primitive in a named-mode abstraction so controller behavior is parametrized by a declarative mode bundle rather than a single `target_humidity` scalar. Ship `fruiting` (v0 = current narrow-band PID behavior, preserves HUMID-04) and `pinning` (v0 = passive ride; defend the floor only). Expose live mode-switching via ROS service. Publish a `current_mode` topic with full resolved mode payload. Deliver a runtime config path (bridge HTTP → ROS2 param service + persistence overlay) so mode/band tuning happens without a deploy cycle. The PID kernel itself stays RH-targeted and unchanged.

**In scope:** mode schema, two baseline modes, mode-switch service, `current_mode` topic + new `fc_msgs` package, controller surgery to consume bands and `defend_side`, bridge HTTP endpoints for live param tuning + overlay-yaml persistence, fc-core launch loading the overlay after `fc_config.yaml`.

**Out of scope (explicitly):** active condensation forcing (Phase 31), VPD-targeted closed loop (Phase 31+ / 999.33), alerter rewiring to consume `current_mode` (Phase 29), Mission Control mode-switch UI (delegated to farmOS / Zoy-side per Phase 18/22 architecture), scheduler issuing time-of-day mode swaps (Phase 30), runtime addition of *new* named modes (always a deploy in v0).

</domain>

<decisions>
## Implementation Decisions

### Mode Schema (closes MODE-01 reconciliation with SEED-004)
- **D-01:** Adopt SEED-004's mode shape verbatim: `(target_humidity, band_low, band_high, defend_side: low|high|both, T_target_optional)`. **REQUIREMENTS.md MODE-01 is rewritten** to reflect this — old wording `(target_RH, band, duty-cycle behavior)` is retired. Memory `project_phase28_mode_schema_seed004_conflict` is closed at this commit.
- **D-02:** `T_target` is reserved for future VPD-anchoring (Phase 31+). Default `null` / `NaN`. Schema migration is avoided when VPD-targeted control eventually lands.
- **D-03:** Mode definitions live as **flat dotted-key ROS2 params** under `fc_controller`'s namespace (e.g. `modes.fruiting.band_low`). YAML supports dotted keys natively; rclpy has no native dict params. Adding a *new* mode (beyond fruiting/pinning) is a deploy in v0 — params must be declared at startup.
- **D-04:** Back-compat: if `modes:` block is absent in `fc_config.yaml`, derive a default `fruiting` mode from `target_humidity` + `humidity_tolerance`. Preserves SCHED-03 "default profile is the constant single-mode case."

### Baseline Mode v0 Values
- **D-05:** `fruiting` v0 = `target=0.96, band_low=0.945, band_high=0.975, defend_side=both, T_target=null`. Preserves Phase 27's HUMID-04 contract (current narrow-band PID behavior).
- **D-06:** `pinning` v0 = `target=0.85 (cosmetic, midpoint of a wide band), band_low=0.90, band_high=0.99, defend_side=low, T_target=null`. **Floor 0.90** is tighter than the research-recommended 0.78 — operator wants pinning to stay near fruiting RH but unlatch the high edge (not "wide passive"). **Ceiling 0.99** is effectively no upper limit; alerter only alarms on extreme saturation in Phase 29 work.
- **D-07:** Pinning v0 is **passive only** — rides the diurnal temp swing for the actual cycle. Active forcing (`force-condensation` / `force-evaporation`) is Phase 31, requires temp control we don't have yet.

### Controller Surgery (`fc_controller.py` lines 268–451)
- **D-08:** Add `_resolve_active_mode()` helper called once per tick, returns `ModeView(target, band_low, band_high, defend_side, T_target)`. PID kernel math is **unchanged**.
- **D-09:** Replace `error_pct = (current_humidity - effective_setpoint) * 100` with band-edge error projection:
  - `rh < band_low` → `error_pct = (rh - band_low) * 100` (negative → PID demands duty)
  - `rh > band_high AND defend_side ∈ {high, both}` → `error_pct = (rh - band_high) * 100`
  - `rh > band_high AND defend_side = low` → clamp duty to 0, freeze integrator, return early (Claude's discretion: bumpless re-engage on return into band — same primitive as Mode C exit)
  - in-band → `error_pct = 0`, integrator parked
- **D-10:** Setpoint ramp targets `band_low` (or `band_high` on the defended side) — **not** the midpoint. Midpoint is fiction when band is wide (relevant to pinning).
- **D-11:** Mode C bypass (`bypass_threshold: 0.025`) keys off distance from the **nearest defended band edge**, not from `target_humidity`. Otherwise pinning never enters Mode C even when RH crashes to 60%.
- **D-12:** Mode swap (MODE-03 service call writes `active_mode`) calls `_engage_pid_bumplessly()` with current duty — same primitive that already handles Mode C exit. Avoids stale-integrator bump when bands change underfoot.

### `current_mode` Topic (MODE-04)
- **D-13:** Create new `fc_msgs` ROS2 package. Define `fc_msgs/msg/Mode.msg` with fields: `string name`, `float32 target_humidity`, `float32 band_low`, `float32 band_high`, `string defend_side`, `float32 t_target` (NaN when unset), `builtin_interfaces/Time effective_since`, `string source` (`'config_default' | 'service_call' | 'scheduler'`).
- **D-14:** Publish on `fc1/control/current_mode`, **TRANSIENT_LOCAL durability** (same QoS pattern as `sensor_health` and Phase 27 telemetry topics — late subscribers get last value on subscribe).
- **D-15:** Republish on every mode swap or band-edge tweak. Architecturally closes the alerter two-source bug (memory `project_alerter_rh_two_source_bug`); Phase 29 retires the env-fed thresholds against this topic.

### Mode Switch Service (MODE-03)
- **D-16:** Service is `fc_controller/set_mode` (custom srv definition; lives in the same `fc_msgs` package). Writes `active_mode` ROS2 param via callback; new mode takes effect on **next control tick** (≤1s). No confirm dialog; immediate.

### Runtime Config Delivery (MODE-05, closes SEED-001)
- **D-17:** Two-layer design:
  - **Layer 1 (hot path):** Bridge exposes `POST /control/param` taking `{node, param, value}`. Validates against an allowlist (prevents writing dangerous params like `humidifier_pin`). Calls ROS2 SetParameters service via `rclnodejs`. Controller's `on_set_parameters_callback` validates range/type, applies on next tick.
  - **Layer 2 (persistence):** Bridge exposes `POST /control/persist`. Writes the new value into `runtime_overrides.yaml` on fc1 (path: `/etc/fc-core/runtime_overrides.yaml` or similar — finalize during planning). Optionally git-commits and pushes via existing `deploy.sh` plumbing. fc-core's launch loads `fc_config.yaml` *then* `runtime_overrides.yaml` (`--params-file` accepts multiple); overrides win on restart.
- **D-18:** **Reject** MQTT (no broker on this stack), scp+SIGHUP (manual, no farmer UI), Timescale-poll (couples control plane to telemetry sink).
- **D-19:** Persistence policy: **explicit "Save to repo" action** — separate endpoint, separate UI button. Auto-commit-on-debounce was considered and rejected (spammy git history, hard to revert "try-it" tweaks). Manual scp escape hatch remains as ops fallback (memory `feedback_humidity_runtime_param`).
- **D-20:** UI origin surface for v0 = **farmOS** (Zoy-side). Phase 28 ships **bridge HTTP endpoints + the mode primitive only** — no Mission Control card. Matches the Phase 18/22 farmOS-proxy architecture (memory `project_phase18_22_farmos_proxy_architecture`). Coordinate endpoint shape with Zoy before the bridge wave lands.

### Alerter Coordination (semantics for Phase 29)
- **D-21:** Alerter rule once it consumes `current_mode` (Phase 29 work): **alarm only on defended edges**. Always alarm if `RH < band_low` (floor is always defended). Alarm if `RH > band_high` only when `defend_side ∈ {high, both}`. During `pinning`, RH > band_high is *expected* and silent.
- **D-22:** Phase 28 scope ends at the topic + payload. Alerter keeps reading env in Phase 28; Phase 29 retires the env. **Clean phase boundary** — no scope creep into ALRT-08 from this phase.

### VPD
- **D-23:** VPD is **out of Phase 28 scope as a control input.** PID stays RH-targeted in v0.
- **D-24:** VPD as **derived telemetry** is filed against Phase 999.27 (bridge-side `fc_metrics` module per memory `project_999_27_bridge_side_derivation`). Use Tetens-Magnus form, kPa output. Don't put it on fc1 unless/until a closed-loop VPD controller needs it (Phase 31+ decision).
- **D-25:** Schema field `T_target` reserves the future VPD-anchoring hook in the mode struct. No schema migration needed when Phase 31 lands.

### Claude's Discretion
- High-side behavior internals (clamp + freeze integrator + bumpless re-engage). Operationally invisible; research's recommendation accepted without challenge.
- Exact mode-switch service signature, exact bridge endpoint path conventions, exact overlay-yaml location on disk. Lock during planning.
- Whether to inline `set_mode` srv into `fc_msgs` or keep msgs and srvs in separate packages — minor packaging detail.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 28 prep
- `.planning/research/2026-05-06-phase28-mode-schema-and-runtime-config.md` — Full opinionated research note: proposed YAML schema, 40-line controller diff, `fc_msgs/Mode` definition, VPD math, two-layer transport design, sequence diagrams. **The decisions above mirror its recommendations except where explicitly overridden in D-06 (pinning floor 0.90 not 0.78) and D-20 (UI surface farmOS not Mission Control).**

### Seeds
- `.planning/seeds/SEED-001-runtime-config-delivery.md` — Drives MODE-05 / D-17. Closed by Phase 28's two-layer design.
- `.planning/seeds/SEED-004-pinning-cycle-and-vpd-mode-schema.md` — Drives D-01 / D-07. Schema reconciliation source.

### Requirements & roadmap
- `.planning/REQUIREMENTS.md` (MODE-01..05) — **MODE-01 is rewritten by Phase 28** to match D-01.
- `.planning/ROADMAP.md` Phase 28 entry — phase boundary anchor.

### Code (read before touching)
- `src/chambers/fc-core/fc_core/fc_controller.py` lines 268–451 — setpoint/PID hot path; D-08..D-12 surgery point.
- `src/chambers/fc-core/config/fc_config.yaml` — current static config; modes block lands under `fc_controller.ros__parameters.modes`.
- `src/mission-control/bridge/src/index.js` — bridge entry; D-17 endpoints land here. Memory note: this file also contains the buffer-replay cursor bug (`index.js:613`) — do NOT confuse the two; mode-control work touches a different code path.
- `scripts/pi-deploy/fc-core.service` — systemd unit; D-17 overlay yaml requires a launch-arg edit (`--params-file fc_config.yaml --params-file runtime_overrides.yaml`).
- `scripts/pi-deploy/deploy.sh` — git plumbing; D-17 Layer 2 reuses this.

### Phase 27 carry-forward
- `.planning/phases/27-pid-time-proportional-duty-cycle-primitive/27-CONTEXT.md` — PID + Mode C + ramp + bumpless transfer all established here.
- `.planning/phases/27-pid-time-proportional-duty-cycle-primitive/27-03-SUMMARY.md` — fc_controller refactor history; D-08..D-12 build on this.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`fc_controller.py` PID loop + bumpless transfer** (lines 268–451): the integrator-park-on-clamp + re-engage primitive already exists for Mode C. D-09 / D-12 reuse the same primitive for `defend_side: low` mode-swap transitions.
- **Per-tick `get_parameter()` pattern** (lines 419–423 in `fc_controller.py`): controller already live-reads `pid_kp/ki/kd/target_humidity` each tick. D-17 Layer 1 plugs into this — no new live-reload pattern needed.
- **TRANSIENT_LOCAL QoS pattern**: established in Phase 27 for `humidifier_duty / humidity_target / pid_output` and earlier for `sensor_health`. D-14 uses the same pattern — late subscribers (alerter, dashboard, future scheduler) get last-value on subscribe.
- **Bridge HTTP server (`src/mission-control/bridge/src/index.js`)**: already serves `/health`, `/api/...`, `/snapshot/...`, history endpoints. Adding `POST /control/param` and `POST /control/persist` is small.
- **`rclnodejs` already in bridge** (Phase 27.1 buffer replay): bridge already has Node.js ROS bindings; `SetParameters` service call is a small extension of what's wired.
- **`deploy.sh` git plumbing**: `git push fc1/prod` → ssh fetch+pull → colcon build → systemctl restart. D-17 Layer 2 piggybacks on this.

### Established Patterns
- **Memory `feedback_humidity_runtime_param`**: `ros2 param set` live, then commit to repo for persistence — exactly the manual version of D-17. Phase 28 makes it first-class.
- **Memory `project_999_27_bridge_side_derivation`**: derived telemetry lives on bridge `fc_metrics` JS module, not on fc1. D-24 follows this.
- **Memory `project_phase18_22_farmos_proxy_architecture`**: bridge ships data surface, farmOS owns UI. D-20 follows this.
- **Memory `project_alerter_is_ws_only`**: alerter only consumes WS topics (never DB / never config files). D-15 + D-21 match this access pattern.

### Integration Points
- **`fc_msgs` package**: new colcon package. Sits alongside `fc_core`. Setup files: `package.xml`, `CMakeLists.txt` (rosidl-generated), `msg/Mode.msg`, optionally `srv/SetMode.srv`. fc_controller and the alerter (Phase 29) and the bridge subscribe to its messages.
- **`fc.launch.py`**: pass `runtime_overrides.yaml` as a second `--params-file` (or equivalent rclpy launch param). Order matters — overrides must load *after* `fc_config.yaml`.
- **`fc-core.service` ExecStart**: may need adjustment to ensure the overlay file path is consistent (and that a missing overlay file doesn't fail the launch — it must be optional).
- **Bridge `ALLOWED_TOPICS` allowlist** (Phase 27.1 pattern): D-17 needs an analogous *param* allowlist on the bridge side — preventing Mission Control / farmOS from setting dangerous params (humidifier_pin, gpio assignments, etc.). Lock the allowlist contents during planning.

</code_context>

<specifics>
## Specific Ideas

- Pinning floor `band_low: 0.90` is tighter than the research's 0.78 because the operator wants pinning to *stay wet* (near fruiting RH) and just unlatch the high edge — not a "ride wide and dry on cool nights" passive philosophy. The schema supports either; the value is the operator's call.
- UI surface = farmOS. **No Mission Control mode-switch card in Phase 28.** Coordinate with Zoy on the farmOS-side endpoint contract — bridge data shape (`POST /control/param` payload) becomes the contract.
- Custom messages live in a new `fc_msgs` package — avoids the JSON-in-String shortcut explicitly. Type-safety pays off across alerter / scheduler / dashboard.
- Ceiling at 0.99 in pinning is intentionally close-to-saturation to maximize the passive-cycle effect without explicit alarming on saturation events.

</specifics>

<deferred>
## Deferred Ideas

- **Active forcing modes** (`force-condensation`, `force-evaporation`) — Phase 31. Need temperature actuator we don't have yet.
- **VPD-targeted closed-loop control** — Phase 31+ / 999.33 (digital twin sim is the right validation surface).
- **VPD as derived telemetry on Mission Control** — Phase 999.27 (`fc_metrics` bridge module). Composes naturally with Phase 28's `T_target` schema field.
- **Time-of-day scheduler issuing mode swaps** — Phase 30. Phase 28 ships only the manual / service-call origin; scheduler subscribes later.
- **Alerter rewire to consume `current_mode`** — Phase 29 / ALRT-08. Phase 28 ships the topic; Phase 29 retires the env-fed thresholds.
- **Runtime addition of new named modes** (beyond fruiting/pinning) — explicit deploy in v0. Re-evaluate when a real third mode comes up (likely `incubation`).
- **Mission Control mode-switch UI** — delegated to farmOS-side; not in Phase 28 scope. Mission Control may still grow a *read-only* mode-status indicator in a later phase.
- **Auto-commit on persistence** — explicit Save-to-repo button in v0; debounced auto-commit considered as v1+ refinement.
- **SHT30 heater coordination during pinning** — Phase 999.34. Pinning v0 is silent on heater interplay; the heater still runs its own cycle. Resolve when 999.34 plans.

</deferred>

---

*Phase: 28-mode-primitive-2-baseline-modes-fruiting-pinning-runtime-con*
*Context gathered: 2026-05-07*
