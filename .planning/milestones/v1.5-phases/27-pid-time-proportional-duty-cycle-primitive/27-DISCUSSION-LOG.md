# Phase 27: PID + time-proportional duty-cycle primitive — Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in 27-CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-01
**Phase:** 27 — pid-time-proportional-duty-cycle-primitive
**Areas discussed:** Architecture, Gain handling, Safety floor, HUMID-04 acceptance band

---

## Architecture

| Option | Description | Selected |
|--------|-------------|----------|
| Topic boundary | fc_controller publishes `fc1/actuators/humidifier_duty`; new slow-PWM driver subscribes and toggles GPIO. Observable, recordable, mode-pluggable. Extra ROS hop + extra node. | ✓ |
| In-process | PID and slow-PWM both inside fc_controller; duty as private variable. Smallest diff; harder to observe; mode injection reaches into internals. | |
| Topic + actuator inside controller (hybrid) | Publish duty as observable topic but keep slow-PWM in fc_controller (controller subscribes to its own topic, or just side-publishes). | |

**User's choice:** Topic boundary, with duty scaled **0.0–1.0** (Float32) so it overlays with the existing `fc1/actuators/humidifier` Bool on the same Mission Control chart.
**Notes:** The scale change (0.0–1.0 vs 0–100%) is operator-driven — chart overlay was the explicit reason. HUMID-01 wording correction recorded in CONTEXT D-02. Physical packaging (separate node vs in-process class) left to the planner; the topic contract is what's locked.

---

## Gain handling (5× rise/decay nonlinearity)

| Option | Description | Selected |
|--------|-------------|----------|
| Single fixed PID set, near-setpoint tuned | One Kp/Ki/Kd from steady-state data. Slow recovery accepted. Simplest path to HUMID-04 attestation. | ✓ |
| Two-zone gain scheduling now | Recovery gains + steady-state gains, threshold-switched. Covers nonlinearity but doubles tuning surface. | |
| Single set + saturation guard | One PID with output clamped (anti-windup-style). Bounds violent recovery without zone scheduling. | |

**User's choice:** Single fixed set, near-setpoint tuned.
**Notes:** Slow recovery turned out to be a non-issue once the safety-floor discussion landed on Mode C (full-ON open-loop bypass for far-from-setpoint), which gives recovery a separate regime entirely. Gain scheduling deferred unless HUMID-04 surfaces it.

---

## Safety floor (replacement for `min_dwell_time`)

This area required two follow-up exchanges. Initial options offered:

| Option | Description | Selected |
|--------|-------------|----------|
| `min_window_duration` only | Window length is itself the safety floor. Per calibration recommendation. | (partial — see refinement) |
| `min_window` + `max_duty_delta_per_window` | Floor on window AND cap on duty change between windows. | |
| Keep `min_dwell_time` at GPIO edge (e.g. 5s) | Most permissive; relies on PID not to chatter. | |

**User's first response:** "we'll need to talk in more depth about this."

### Wear-target analysis (asked by user)

Walked through what each component actually wears on:
- SSR-10A: solid-state, effectively zero cycle wear → not a constraint
- Ultrasonic transducer: cares about *runtime hours*, not cycle count → limit average duty, not switching frequency
- Humidifier internal control board: low concern (most cheap units are passive)
- **PSU/power-bank caps & bridge rectifier: medium — the real one.** Inrush current per switch-on stresses input caps; longer windows = fewer inrush events
- Water consumption: operator-facing, motivates a max-duty cap

**Conclusion:** longer windows are friendly to the only thing that actually wears (PSU). Operator instinct of "long when possible, short when fine-tuning" matches hardware reality.

### Window-shape sub-question (after wear analysis)

| Option | Description | Selected |
|--------|-------------|----------|
| A) Two windows, threshold-switched | Long near setpoint, short far off. One discrete switch. | |
| B) Continuous interpolation | Window duration as a smooth function of error. | |
| C) Long-window default + far-off open-loop bypass | Slow-PWM at long window near setpoint; bypass to full-ON open-loop when error exceeds threshold. | ✓ |

**User's choice:** C — simplest, matches "long when possible, short-circuit when far off."

### Min-effective-duty + window collision (raised after C was picked)

After locking C with a short follow-up:
- User confirmed empirical min ON pulse for visible fog: **10 seconds**
- Surfaced collision: 10s min pulse vs 60s window vs ~15% steady-state duty → 16.7% floor sits *at* the operating point → limit-cycle risk
- Three resolutions offered: (i) longer window (120s → 8.3% floor), (ii) pulse-skipping delta-sigma, (iii) asymmetric round-up

**User's choice:** (i) — longer window (120s). Locked.

### Locked into CONTEXT.md
- D-08 window = 120s
- D-09 Mode C bypass when |error| > bypass_threshold
- D-11 min effective ON pulse = 10s
- D-15 `min_dwell_time` removed (no SSR-side cycle-rate concern)
- D-12 rolling max-duty cap (Claude's discretion on default — bounds water consumption)
- D-06 bumpless transfer + D-07 setpoint-change ramp (also locked here for "ramp on big changes" intent)

---

## HUMID-04 acceptance band

| Option | Description | Selected |
|--------|-------------|----------|
| ±0.5% over 2h | Half the bang-bang interim band; well above sensor noise floor; concrete + farmer-eyeballable. | ✓ |
| ±0.3% over 2h | Aggressive; calibration overshoots suggest reachable; risk if SHT30 still offline at attestation. | |
| ±1% with zero DWELL-BLOCK events | Same number, qualitative win — "no dwell blocks + visibly smoother trace." | |
| Defer the number; pick after live tuning | Lock the number empirically before phase close. | |

**User's choice:** ±0.5% over 2h, farmer-attested.
**Notes:** Locked as D-16 in CONTEXT.md. Soak runs against slot-1 humidity (`fc1/humidity`) per D-17.

---

## Claude's Discretion

Captured in CONTEXT.md:
- Default Kp/Ki/Kd values (researcher derives from calibration data)
- Setpoint-ramp slew duration (D-07)
- `bypass_threshold` default (D-10)
- Rolling max-duty cap default (D-12)
- Anti-windup mechanism, derivative-on-measurement vs error, D-term filtering
- Physical packaging of slow-PWM driver (separate node vs in-process class)
- YAML key naming for new params

## Deferred Ideas

Captured in CONTEXT.md `<deferred>` section. Headline items: per-mode gains (v1.6), zone scheduling within a mode (only if HUMID-04 surfaces it), mode-aware sensor selection (v1.6), PID auto-tuning (out of scope), Mission Control overlay layout (composes with 999.17), `min_dwell_time` doc/alerter sweep (follow-up, non-blocking).
