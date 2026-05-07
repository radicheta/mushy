---
phase: 28
status: research-note
author: claude-opus-overnight
date: 2026-05-06
---

# Phase 28 prep — Mode schema + runtime config delivery

This note grounds the upcoming `/gsd-discuss-phase 28` in two strands that the
current REQUIREMENTS.md MODE-01..05 wording elides:

1. **Mode schema** — REQUIREMENTS.md frames a mode as a flat
   `(target_RH, band, duty-cycle behavior)` bundle. SEED-004 (planted today)
   says that's agronomically wrong: pinning is a *cycle* across the dew point,
   bands need to be asymmetric, and VPD is the variable the loop should
   eventually target. The schema must accommodate that *now* even though we
   keep the loop RH-targeted in v0.
2. **Runtime config delivery** — SEED-001 wants any of MQTT / HTTP / scp+SIGHUP
   / Timescale-poll. The existing escape hatch (`ros2 param set` live, then
   commit, per memory `feedback_humidity_runtime_param`) is already 80% of the
   answer; the question is what thin layer we put on top of it.

I'm opinionated below — this is research, not spec, but discuss-phase will be
faster if it starts from a concrete recommendation and pokes at it.

---

## Strand A: Mode Schema

### A.1 — Proposed YAML schema

I recommend a `modes:` block under the controller's namespace, with one entry
per named mode. Each entry expresses target, asymmetric band, defended side,
and an optional `T_target` so the same struct survives a future VPD-targeted
loop without a file-format migration (SEED-004's "Recommended approach for
Phase 28").

```yaml
fc_controller:
  ros__parameters:
    # Active mode name — what MODE-03's service call writes.
    active_mode: fruiting

    modes:
      fruiting:
        # Current narrow-band PID behavior — preserves HUMID-04 contract.
        target_humidity: 0.96       # 96% RH — farmer-set 2026-05-04
        band_low: 0.945             # PID defends below this
        band_high: 0.975            # PID defends above this (symmetric today)
        defend_side: both           # 'low' | 'high' | 'both'
        T_target: null              # optional VPD anchor; null = RH-only loop
        notes: "v0 mirrors current static fc_config behavior"

      pinning:
        # Wide band, defend only the floor — let chamber RH ride upward when
        # cool surfaces accept condensate. Active driving lives in Phase 31.
        target_humidity: 0.85       # midpoint, mostly cosmetic for a wide band
        band_low: 0.80              # we *do* humidify if RH falls below 80%
        band_high: 0.99             # ceiling — never fight upward
        defend_side: low            # the key bit: passive ride on the high side
        T_target: null
        notes: "v0 passive — relies on diurnal temp swing for the cycle"
```

Key properties of this shape:

- **Asymmetric bands fall out naturally** — `band_low`/`band_high` are
  independent, not `target ± tolerance`. The current `humidity_tolerance: 0.015`
  param becomes redundant once a mode is active; for backward compat the
  default `fruiting` mode can be derived from `target_humidity` + `humidity_tolerance`
  if `modes:` is absent (preserves SCHED-03 "default profile is constant
  single-mode case").
- **`defend_side` is the behavioral knob SEED-004 cares about.** It's the
  difference between "PID drives duty up when RH < band_low AND drives toward
  zero when RH > band_high" (`both`, current behavior) versus "PID drives duty
  up when RH < band_low; clamps duty to zero when RH > band_low without
  actively venting" (`low`, pinning v0).
- **`T_target` is reserved for VPD.** Null today. When a future loop computes
  VPD from `(T, RH)`, `T_target` lets a mode anchor the temperature side too.
  No schema migration when that lands.
- **Mode definitions live in the same yaml fc_config.yaml uses today**, so
  the existing ROS2 parameter pipeline carries them. This is critical for
  Strand B — see below.

### A.2 — Smallest controller change

Reading `fc_controller.py` lines 268–451, today's loop is:

```
target = self.get_parameter('target_humidity').value
self._ramp_setpoint(dt)
error_pct = (self.current_humidity - self._effective_setpoint) * 100.0
bypass_pct = self.get_parameter('bypass_threshold').value * 100.0
if abs(error_pct) > bypass_pct:  # Mode C bypass
    duty = 1.0
else:
    raw = self._pid(error_pct, dt=dt)
    duty = raw
```

The smallest internal change is a `_resolve_active_mode()` helper called once
per tick and a *band-aware* error projection feeding PID. PID math doesn't
change. What changes is **which side of the band the loop computes error
against, and whether duty is clamped to zero on the undefended side.**

```python
def _resolve_active_mode(self):
    name = self.get_parameter('active_mode').value
    m = self.get_parameter(f'modes.{name}').value  # nested params via ROS2
    return ModeView(
        target=m['target_humidity'],
        band_low=m['band_low'],
        band_high=m['band_high'],
        defend_side=m['defend_side'],
        T_target=m.get('T_target'),
    )

# In control_loop, replace the error_pct line with:
mode = self._resolve_active_mode()
rh = self.current_humidity
if rh < mode.band_low:
    error_pct = (rh - mode.band_low) * 100.0     # negative → PID demands duty
elif rh > mode.band_high:
    if mode.defend_side in ('high', 'both'):
        error_pct = (rh - mode.band_high) * 100.0  # positive → PID drives duty down
    else:
        # pinning: don't fight upward excursions; clamp duty to 0 and freeze I.
        self._pid.set_auto_mode(False)
        self._publish_duty(0.0)
        return
else:
    # in-band: zero error, integrator parked
    error_pct = 0.0
```

Three subtle points worth surfacing in discuss:

1. **Setpoint ramp** today operates on `target_humidity`. With bands, ramping
   should target `band_low` (or `band_high` on the defended side) — not the
   midpoint — because the midpoint is a fiction when the band is wide. For
   `fruiting` v0 the bands are symmetric so this is invisible; for `pinning`
   the midpoint (0.85) is meaningless.
2. **Mode C bypass (`bypass_threshold: 0.025`)** is currently keyed off
   distance from setpoint. With bands, it should key off distance from the
   *nearest defended band edge*. Otherwise pinning never enters Mode C even
   when RH crashes to 60%, because the midpoint is at 85%.
3. **Bumpless mode swap.** When MODE-03's service call flips `active_mode`,
   PID integrator state is stale (it accumulated against the old band edge).
   The cleanest move is to call `_engage_pid_bumplessly()` with current duty
   on every mode swap — same primitive that already handles Mode C exit.

### A.3 — `current_mode` topic shape (MODE-04)

For decoupling Phase 29 alerter and Phase 30 scheduler, the topic should carry
**the resolved mode struct, not just the name.** The alerter must not reach
back into fc_config.yaml to look up bands — that's exactly the two-source bug
memory `project_alerter_rh_two_source_bug` describes.

I recommend a custom message type `fc_msgs/Mode`:

```
# fc_msgs/msg/Mode.msg
string name                 # 'fruiting' | 'pinning' | future
float32 target_humidity     # 0.0–1.0
float32 band_low            # 0.0–1.0
float32 band_high           # 0.0–1.0
string defend_side          # 'low' | 'high' | 'both'
float32 t_target            # NaN if unset (avoid optional/null in ROS msgs)
builtin_interfaces/Time effective_since
string source               # 'config_default' | 'service_call' | 'scheduler'
```

Published on `fc1/control/current_mode` with `TRANSIENT_LOCAL` durability so
the alerter and scheduler get last-value on subscribe (same pattern as
`sensor_health` today). `effective_since` and `source` are cheap and pay for
themselves the first time we debug "why did pinning kick in at 14:32?".

If `fc_msgs` doesn't exist yet, MODE-04 v0 can stand on a JSON string in
`std_msgs/String` to avoid a new package — but I'd push back on that;
strongly-typed messages are a small cost and the alerter is already burned by
loose coupling once.

### A.4 — VPD calculation

Magnus / Tetens-Magnus is fine for our range (15–30 °C, 50–100% RH). I
recommend the **Tetens form** with WMO 2008 coefficients:

```
e_s(T) = 6.1078 * exp(17.27 * T / (T + 237.3))     # saturation vapor pressure, hPa
e_a    = e_s(T) * (RH / 100)                       # actual vapor pressure
VPD    = e_s(T) - e_a                              # hPa (≡ mbar). Mushroom range: 0.05–0.5 kPa
```

Buck (1996) is marginally more accurate near saturation but the difference is
<0.5% in our range and not worth the more complex coefficients.

**Inputs:** `T` in °C from `fc1/temperature` (SHT30, frame_id=='sht30');
`RH` in % (note: the controller uses 0.0–1.0, the bridge uses %; pick one and
document at the boundary). **Output:** kPa, range ~0.0–4.0 typical, mushroom
fruiting target ~0.4–0.8 kPa.

**Where it lives.** Per memory `project_999_27_bridge_side_derivation`,
derived telemetry goes on the bridge in the `fc_metrics` JS module, not on
fc1. VPD fits this pattern perfectly — it's a pure function of two existing
topics, replay-friendly (deterministic given inputs), and adding it on the
bridge keeps fc1 ROS topology stable. The controller does NOT need VPD to
compute duty in v0; the loop stays RH-targeted.

The one exception that would push VPD onto fc1 is if a future closed-loop VPD
controller needs it as a control input — at that point we'd compute it in
`fc_controller.py` directly (cheap, ~10 floating-point ops) and publish to
`fc1/control/vpd_kpa`, with the bridge derivation becoming redundant. That's
a Phase 31+ decision; don't preempt.

### A.5 — SEED-004 open questions

The three open questions at the bottom of SEED-004, with what we'd need from
the farmer to close each:

1. **How do we measure condensation?**
   *Need from farmer:* willingness to invest in an IR surface-temp probe
   (~$15, MLX90614). Without it we have proxies (SHT30 RH near 100% with
   heater state known, SCD41 RH clipping at 100% as a saturated-flag — memory
   `project_phase26_sht30_happy_path_unverified` notes SCD41 always clips so
   it's finally useful here, rate-of-RH-change after a temp drop). For
   Phase 28 we can ship without measuring condensation directly — pinning v0
   is open-loop on the band-shape side. Closed-loop condensation needs the
   probe.

2. **Is pinning v0 purely passive, or is there a minimum-RH floor?**
   *Need from farmer:* what's the lowest acceptable RH during a pinning
   night? The schema above already supports a floor via `band_low: 0.80` —
   the question is what value to ship. My read: 75–80% is conservative,
   matches commercial oyster guidance. Ask the farmer for the value he'd
   pull a fire alarm at; that's `band_low`.

3. **How does mode interact with the alerter (Phase 29)?**
   *Need from farmer:* nothing — this is an architecture call. The MODE-04
   message above carries `band_low/band_high/defend_side` exactly so the
   alerter can compute "is RH outside the defended portion of the active
   mode's band?" without static thresholds. ALRT-08 is already scoped to
   read from `current_mode`; what SEED-004 adds is that **alerting on
   "RH > target during pinning" must be suppressed** because that side isn't
   defended. Concretely: alerter only alarms when RH violates an edge whose
   `defend_side` includes that edge.

---

## Strand B: Runtime Config Delivery

### B.1 — Evaluation against project constraints

Re-reading SEED-001's four candidates against today's reality:

| Transport | Fit | Verdict |
|---|---|---|
| **MQTT topic** | We don't run an MQTT broker. Mosquitto would be new infra for one purpose. The bridge speaks WebSocket to OpenMCT; MQTT would be parallel infrastructure. | **Reject.** New broker for marginal benefit. |
| **HTTP endpoint on Pi** | fc_buffer already exposes HTTP on `172.16.10.5:8765` (memory `project_fc1_link_architecture_options` adjacent / Phase 27.1). Adding `/control/mode` to the same server is trivial. Native to the bridge. | **Strong fit.** |
| **scp + SIGHUP** | Manual, no farmer UI path, doesn't survive multi-Pi. | **Reject** for farmer-facing changes; keep as ops escape hatch. |
| **TimescaleDB poll** | Couples control plane to telemetry DB. Pi must reach Timescale on every tick of polling. Across multi-Pi this means N pollers hitting one DB. Inverts ownership (Timescale should be a *sink*, not a source of truth). | **Reject.** Coupling smell. |

But the bigger question SEED-001 doesn't address is: **does ROS2 dynamic
reconfigure already cover this?**

It mostly does. `rclpy` parameter callbacks (`add_on_set_parameters_callback`)
fire when any client calls `ros2 param set`. The controller already
**live-reads** `pid_kp/ki/kd` and `target_humidity` each tick (lines 419–423).
Memory `feedback_humidity_runtime_param` confirms this is the working pattern
today: set live, then commit to repo for persistence.

So the Phase 28 question is not "what new transport do we build" but:

- **What's the path from "farmer in Mission Control" to `ros2 param set`?**
- **How do mode definitions (nested dicts under `modes:`) survive
  ROS2 parameter limitations (no native dict params; only flat
  scalars/arrays)?**
- **How does runtime state persist across reboots?**

### B.2 — Recommendation

I recommend a **two-layer design**:

**Layer 1 — Hot path (mode switch + scalar tuning):** Use ROS2 parameters via
the bridge. Bridge exposes a thin HTTP endpoint at
`POST /control/param` that calls the ROS2 parameter service on the
controller node. This is what `ros2 param set` does over the wire; the bridge
just gives Mission Control a JS-friendly door to it.

```
Mission Control (HTML)
      │  HTTP POST /control/param  {"param": "active_mode", "value": "pinning"}
      ▼
Bridge (Node.js, existing)
      │  rclnodejs SetParameters service call
      ▼
fc_controller (rclpy)
      │  on_set_parameters_callback  → validates, applies on next tick
      ▼
fc_controller.control_loop  → reads new value via get_parameter()
```

**Layer 2 — Persistence:** A "save to repo" affordance. After a runtime
change, the bridge writes the new value into a *runtime overlay file*
(`fc_runtime_overrides.yaml`) that fc-core's launch loads *after*
fc_config.yaml. The overlay is committed to the repo on a
`POST /control/persist` call (or auto-committed on a debounce). Boot survival
falls out of the overlay file being on disk and loaded at launch.

This separates "tune now" (Layer 1, ephemeral) from "make it stick" (Layer 2,
explicit). The farmer's mental model matches: red button = try, green button
= commit. Memory `feedback_humidity_runtime_param`'s pattern is exactly this,
just made first-class instead of manual.

**Why not a config DB?** Because fc-core boot must not depend on Timescale
being reachable. The overlay yaml is local to the Pi, on the same disk as
fc_config.yaml. Multi-Pi (Pi Zero remote I/O per memory
`project_multi_chamber_pi_zero`) doesn't change this — each Pi has its own
overlay. Mission Control orchestrates fan-out by calling N bridges (or one
bridge calling N nodes — that's the bridge's problem, not the controller's).

### B.3 — Mode definitions and the ROS2 nested-dict gap

Here's the wrinkle: ROS2 parameters are flat. `modes.fruiting.band_low` is
fine (declared as a scalar with that exact name); `modes` as a dict is not.
ROS2 has no native dict parameter type.

The pragmatic move is to flatten on declare:

```python
self.declare_parameters(
    namespace='',
    parameters=[
        ('active_mode', 'fruiting'),
        ('modes.fruiting.target_humidity', 0.96),
        ('modes.fruiting.band_low', 0.945),
        ('modes.fruiting.band_high', 0.975),
        ('modes.fruiting.defend_side', 'both'),
        ('modes.fruiting.T_target', float('nan')),
        ('modes.pinning.target_humidity', 0.85),
        ('modes.pinning.band_low', 0.80),
        ('modes.pinning.band_high', 0.99),
        ('modes.pinning.defend_side', 'low'),
        ('modes.pinning.T_target', float('nan')),
    ],
)
```

YAML uses dotted keys natively; the existing fc_config.yaml structure already
supports this (e.g. `fc_buffer:` is a separate node namespace today).

**Adding a new mode at runtime** is the only thing this approach can't do
without a restart, because params must be declared at startup. I think
**that's a feature, not a bug** for v0: adding a mode is a structural change
that deserves a deploy. Tuning band edges of an existing mode is the common
case and is fully runtime-tunable.

### B.4 — Sequence diagram: "farmer changes pinning band from 80–95 to 75–95"

Origin of the change: **Mission Control button** is the right v0 surface.
Signal command is tempting but dangerous (typos with no preview). farmOS UI
is the right *long-term* home (single farmer pane of glass per memory
`project_phase18_22_farmos_proxy_architecture`) but that's a Phase 18+ build,
not Phase 28.

```
1. Farmer       Mission Control "pinning band_low: 0.80 → 0.75"
                  │ slider commit
                  ▼
2. Mission Control  POST http://bridge/control/param
                    body: {"node": "fc_controller",
                           "param": "modes.pinning.band_low",
                           "value": 0.75}
                  ▼
3. Bridge       Validates: param name ∈ allowlist, value type/range OK
                  │ (allowlist prevents Mission Control from setting,
                  │  e.g., humidifier_pin)
                  ▼
4. Bridge       rclnodejs.SetParameters({modes.pinning.band_low: 0.75})
                  ▼
5. fc_controller on_set_parameters_callback:
                  - validate range (0.0 ≤ band_low < band_high ≤ 1.0)
                  - SUCCESS → param store updated
                  - FAILURE → reject, response carries reason
                  ▼
6. fc_controller next control tick reads the new band via
                  _resolve_active_mode() if 'pinning' is active.
                  current_mode topic republishes if any field changed.
                  ▼
7. Bridge       HTTP 200 with new effective value
                  ▼
8. Mission Control  Slider snaps to confirmed value, toast "Live."

--- persistence (separate, explicit) ---

9. Farmer       Click "Save to repo" (debounced auto-fire OK too)
                  ▼
10. Bridge      POST /control/persist
                Bridge writes /etc/fc-core/runtime_overrides.yaml:
                  fc_controller:
                    ros__parameters:
                      modes.pinning.band_low: 0.75
                Commits + pushes on fc1/prod (existing deploy plumbing).
                  ▼
11. Boot survival: fc-core.service launch loads fc_config.yaml THEN
    runtime_overrides.yaml (existing ros2 launch arg `--params-file` accepts
    multiple). Overrides win.
```

**Persistence policy.** I'd ship v0 with explicit "Save to repo" — auto-commit
on every slider drag spams git history. A 5-minute debounced auto-commit is a
reasonable v1.

### B.5 — Why this is small

The total surface area is:

- ~1 new endpoint on the bridge (`POST /control/param` + `/control/persist`)
- `add_on_set_parameters_callback` on fc_controller for validation
- One overlay yaml + a launch-file edit to load it
- A Mission Control card with a few sliders

Everything else (the transport, the param store, the live-reload pattern,
even the deploy.sh) already exists. Phase 28 is mostly **plumbing through
what's already there**, not building new infrastructure. That's what
SEED-001 was hoping for.

---

## Recommendations Summary

1. **Mode schema:** Adopt `(target, band_low, band_high, defend_side, T_target)`
   per SEED-004. Ship `fruiting` (v0 = current behavior) and `pinning`
   (v0 = `defend_side: low`, wide band, passive). Keep PID RH-targeted.
   Flatten to dotted-key ROS2 params.

2. **Controller change:** ~40-line surgical change in `fc_controller.py`:
   `_resolve_active_mode()` helper, band-edge error projection, mode-aware
   Mode C bypass, bumpless re-engage on mode swap. PID math untouched.

3. **`current_mode` topic:** Custom `fc_msgs/Mode` message carrying full
   resolved mode struct + `effective_since` + `source`. TRANSIENT_LOCAL QoS.
   Closes the alerter two-source bug (memory `project_alerter_rh_two_source_bug`).

4. **VPD:** Tetens-Magnus, kPa output. Compute on the bridge in `fc_metrics`
   per memory `project_999_27_bridge_side_derivation`. Don't put it on fc1
   until/unless a VPD-targeted controller needs it.

5. **Runtime config delivery:** Bridge HTTP endpoint → ROS2 parameter service
   → `on_set_parameters_callback` validation → live-reload via existing
   per-tick `get_parameter()` pattern. Two layers: ephemeral set + explicit
   "save to repo" overlay yaml. **Reject MQTT, scp, Timescale-poll.**

6. **Origin surface:** Mission Control button for v0; farmOS for v1.5+;
   never Signal command for tunable parameters (preview/undo too important).

---

## Open Questions for Farmer

These are the things `gsd-discuss-phase` should put in front of the farmer.
Most have a recommended default in brackets — discuss should confirm or push
back, not re-ask from zero.

1. **Pinning floor:** What's the minimum RH below which pinning mode should
   actively humidify? [recommend 0.78]
2. **Pinning band ceiling:** Is 99% the right ceiling, or do we hard-cap at
   95% to leave headroom for the SHT30 heater (memory
   `project_phase26_sht30_happy_path_unverified` flags 999.34 collision)?
3. **Mode swap latency tolerance:** Is "next control tick" (≤1s) acceptable,
   or does the farmer want a confirm-dialog "Switch to pinning at 22:00?"
   for scheduled cases? [recommend immediate]
4. **Persist policy:** Explicit "Save to repo" button vs. auto-debounce vs.
   never-persist (each tweak is ephemeral, formal change requires deploy)?
   [recommend explicit button + ops-only auto-commit hourly cron]
5. **Mode add/remove:** Confirm that adding a *new* named mode (beyond
   fruiting/pinning) is a deploy, not a runtime op? [recommend yes]
6. **Alerter behavior in pinning:** Confirm that RH-too-high alerts are
   *suppressed* during pinning (because we want condensation)? [recommend yes,
   per SEED-004 open question #3]

---

## References

### Seeds
- `/mnt/slime-kingdom/opt/mushy/.planning/seeds/SEED-001-runtime-config-delivery.md`
- `/mnt/slime-kingdom/opt/mushy/.planning/seeds/SEED-004-pinning-cycle-and-vpd-mode-schema.md`

### Requirements
- `/mnt/slime-kingdom/opt/mushy/.planning/REQUIREMENTS.md` (MODE-01..05, ALRT-08, SCHED-01..03)

### Code
- `/mnt/slime-kingdom/opt/mushy/src/chambers/fc-core/config/fc_config.yaml` (lines 1–71)
- `/mnt/slime-kingdom/opt/mushy/src/chambers/fc-core/fc_core/fc_controller.py` (lines 268–451 = setpoint/PID hot path)

### Memory (project's MEMORY.md index)
- `feedback_humidity_runtime_param` — `ros2 param set` live + commit later is the working pattern
- `project_alerter_rh_two_source_bug` — band/target hidden in alerter env causes drift; MODE-04 closes
- `project_dynamic_rh_target_groundwork` (Phase 999.23) — RH(t) covers time axis, silent on band shape and VPD
- `project_999_27_bridge_side_derivation` — derived telemetry on bridge, not fc1
- `project_alerter_is_ws_only` — alerter consumes WS topics; mode info reaches it via `current_mode` topic, not config files
- `project_multi_chamber_pi_zero` — multi-Pi shape rules out Timescale-as-config-source
- `project_phase26_sht30_happy_path_unverified` — SCD41 RH clips at 100% (useful as saturated-flag); 999.34 heater collision with pinning
- `project_phase27_shipped` — PID + slow-PWM live, telemetry topics established
- `project_farmer_truth_over_perf` — fidelity > performance for farmer-visible state, supports band-aware alerter
- `feedback_no_sparklines` — annotated event timeline is the farmer's ask; mode-change events are exactly that
- `project_phase18_22_farmos_proxy_architecture` — farmOS as long-term origin surface for tuning UI

### Backlog phases
- Phase 999.23 — dynamic RH target (closes inside SCHED-01..03)
- Phase 999.27 — derived telemetry / `fc_metrics` bridge module (VPD lives here)
- Phase 999.33 — digital twin sim (validation surface for cycle parameters)
- Phase 999.34 — SHT30 heater state machine (must coordinate with pinning)
- Phase 31 — experimental forcing modes (active cycle driving)
