# Phase 28: Mode primitive + 2 baseline modes (`fruiting`, `pinning`) + runtime config delivery — Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-07
**Phase:** 28-mode-primitive-2-baseline-modes-fruiting-pinning-runtime-con
**Areas discussed:** Mode schema reconciliation, Pinning v0 numbers, Runtime config surface, Alerter coordination during pinning

---

## Mode schema reconciliation

### Q1: Adopt SEED-004's mode schema (target, band_low, band_high, defend_side, T_target_optional) and rewrite MODE-01 in REQUIREMENTS.md to match?

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, adopt as-is (Recommended) | Lock schema as proposed. Rewrite MODE-01 in REQUIREMENTS.md. Close memory flag. | ✓ |
| Yes, but T_target out | Adopt the band/defend_side shape but drop T_target now. | |
| Push back on bands | Keep MODE-01 as a flat (target, tolerance) bundle for now. | |

**User's choice:** Yes, adopt as-is. Locks D-01..D-04.

### Q2: MODE-04 message type — strongly-typed fc_msgs/Mode message, or a JSON string in std_msgs/String for v0?

| Option | Description | Selected |
|--------|-------------|----------|
| Custom fc_msgs/Mode (Recommended) | Carries name, target, bands, defend_side, T_target, effective_since, source. TRANSIENT_LOCAL QoS. | ✓ |
| JSON in std_msgs/String | No new package; subscribers JSON.parse on each tick. | |

**User's choice:** Custom `fc_msgs/Mode`. (User asked for an explanation in plain terms first; selection made after explanation of type-safety tradeoff and reference to past alerter loose-coupling burn.) Locks D-13..D-15.

---

## Pinning v0 numbers

### Q3: Pinning floor (band_low) — the only RH-too-low threshold that matters in v0.

| Option | Description | Selected |
|--------|-------------|----------|
| 0.78 / 78% (Recommended) | Research default; commercial oyster guidance. | |
| 0.80 / 80% | Tighter; controller intervenes sooner. | |
| 0.75 / 75% | Wider passive zone; truly passive philosophy. | |
| Different number | Free-text via "Other". | ✓ (0.90) |

**User's choice:** 0.90 / 90% (typed via Other). Tighter than research's 0.78. Reflects an operator preference to keep pinning RH near fruiting territory and only unlatch the *high* edge — not a "ride the swing widely" philosophy. Locks D-06.

### Q4: Pinning ceiling (band_high).

| Option | Description | Selected |
|--------|-------------|----------|
| 0.99 / 99% (Recommended) | Effectively no upper limit; maximum-passive shape. | ✓ |
| 0.95 / 95% | Hard cap; alerter alarms at 95% during pinning. | |

**User's choice:** 0.99. Locks D-06.

### Q-context: User push-back on framing

User flagged that:
- Pinning v0 isn't actually "forcing condensation" — that's Phase 31 territory.
- "Do nothing if RH too high" is the only option in v0 anyway because we have only a humidifier (no dehumidifier / vent / chiller).

Both observations correct. Reframed `defend_side` as primarily a **semantic** field (drives alerter rules + reserves Phase 31 actuation distinction) rather than a hardware-level actuation difference in v0. The "freeze integrator on clamp + bumpless re-engage" internal behavior was therefore moved to Claude's discretion (no farmer call); research's recommendation accepted. Locks D-09 internals as Claude's discretion.

---

## Runtime config surface

### Q5: Adopt the two-layer design (HTTP → ROS2 param service for live tuning + overlay yaml for persistence)?

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, two-layer as proposed (Recommended) | Bridge HTTP endpoint → ROS2 param service → live-reload + 'Save to repo' overlay yaml. | ✓ |
| Live tuning only, no persistence in Phase 28 | Ship Layer 1; defer overlay yaml. | |
| Auto-commit, no separate persist step | Every live tweak auto-commits after 5-min debounce. | |

**User's choice:** Two-layer as proposed. Locks D-17, D-19.

### Q6: Origin surface for v0 — where does the farmer actually click?

| Option | Description | Selected |
|--------|-------------|----------|
| Mission Control button (Recommended) | Small card in MC with mode dropdown + sliders. | |
| Bridge HTTP endpoint only, no UI | Ship endpoint; document curl examples. | |
| farmOS UI | Defer UI to farmOS-side; bridge ships data surface only. | ✓ |

**User's choice:** farmOS UI (Zoy-side). Locks D-20. **Phase 28 ships bridge endpoints + mode primitive only — no Mission Control mode-switch card.** Matches Phase 18/22 farmOS-proxy architecture.

### Q7: Adding a *new* named mode — runtime, or always a deploy?

| Option | Description | Selected |
|--------|-------------|----------|
| Always a deploy (Recommended) | rclpy params declared at startup; new mode = new params = restart. | ✓ |
| Runtime add via overlay yaml | Hot-reload new mode block; requires dynamic param declaration. | |

**User's choice:** Always a deploy. Locks D-03.

---

## Alerter coordination during pinning

### Q8: Alerter rule once it consumes `current_mode` — when should it alarm on RH being out of band?

| Option | Description | Selected |
|--------|-------------|----------|
| Only on defended edges (Recommended) | Alarm if RH < band_low (always); alarm if RH > band_high only if defend_side ∈ {high, both}. | ✓ |
| Always alarm on any out-of-band | Alarm whenever RH is outside [band_low, band_high]. | |
| Alarm only on critical edges | Two thresholds independent of mode bands; treat band as 'controller working range'. | |

**User's choice:** Only on defended edges. SEED-004's recommendation. Locks D-21.

### Q9: Phase 28 lays the schema groundwork; Phase 29 will rewire the alerter. What lands in Phase 28?

| Option | Description | Selected |
|--------|-------------|----------|
| Topic only, alerter unchanged in Phase 28 (Recommended) | Phase 28 ships fc_msgs/Mode + topic; alerter keeps reading env in Phase 28; Phase 29 retires env. | ✓ |
| Topic + alerter quick-rewire in Phase 28 | Pulls Phase 29 work forward; risk: scope creep. | |

**User's choice:** Topic only — clean phase boundary. Locks D-22.

---

## Claude's Discretion

- High-side internal behavior: clamp duty=0, freeze integrator, bumpless re-engage on return into band (matches Mode C exit primitive). User explicitly delegated.
- Exact mode-switch service signature, exact bridge endpoint path conventions, exact overlay-yaml file path on disk.
- Whether to inline `set_mode` srv into `fc_msgs` or split msgs and srvs into separate packages.
- Whether `fc_metrics` VPD work is filed as a separate plan in Phase 28 or fully deferred to Phase 999.27 (likely fully deferred — out of scope).

## Deferred Ideas

- Active forcing modes (`force-condensation`, `force-evaporation`) → Phase 31.
- VPD-targeted closed-loop control → Phase 31+ / 999.33 digital twin.
- VPD as derived telemetry on Mission Control → Phase 999.27.
- Time-of-day scheduler → Phase 30.
- Alerter rewire to consume `current_mode` → Phase 29.
- Runtime addition of new named modes → not in v0.
- Mission Control mode-switch UI → delegated to farmOS-side.
- Auto-commit-on-debounce persistence → v1+.
- SHT30 heater coordination during pinning → Phase 999.34.
