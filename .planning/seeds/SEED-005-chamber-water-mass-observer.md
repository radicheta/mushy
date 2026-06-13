---
id: SEED-005
status: activating
title: Chamber water-mass observer + condensation camera macro
captured: 2026-05-08
trigger: VPD scoping discussion (farmer call 2026-05-09); composes with Phase 31 force-evaporation review and any future closed-loop VPD work
scope: Medium
composes_with: [SEED-004, 999.27, 999.33, Phase 31]
---

# SEED-005 — Chamber water-mass observer + condensation camera macro

> **2026-06-13 — ACTIVATING (source #3 first).** Macro lens arrived + mounted on the fc1
> camera, satisfying this seed's "camera macro depends on camera being back online"
> dependency. Pulling **data-source #3 (condensation camera macro)** forward on its own to
> calibrate the RH sensors near 100%. Decisions locked + full plan:
> [`../notes/2026-06-13-cv-condensation-detection-plan.md`](../notes/2026-06-13-cv-condensation-detection-plan.md).
> Locked: capture-dataset-first → tiny CNN → bridge-side inference; detect condensation on the
> **outer** bag surface; daylight-only (flash LED deferred). The psychrometric + actuator-integral
> water-mass observer (sources #1/#2) remains the larger arc this feeds.

**Captured:** 2026-05-08, ahead of overnight VPD research and Saturday lab visit.
**Source:** Operator note while planning VPD discussion items for the farmer call.

## The idea

Track **total water mass in the chamber** as a first-class model state variable, not just RH. RH is the *signal* the sensor reports; water mass is the *physical quantity* the actuator changes. Once we have water-mass as state, several pain points dissolve:

- **VPD targeting** has a real underlying quantity to regulate.
- **RH-saturation blindness** (sensor pins at 100% while real water mass keeps climbing) becomes legible.
- **Pinning behavior** (where condensation is the experimental variable, not RH) becomes measurable.

## Three data sources, hybrid observer

### 1. RH < 100% — direct psychrometric calculation

Given chamber air volume `V` (known: chamber dimensions minus substrate volume), temperature `T` (SHT30/SCD41), and relative humidity `RH`:

```
P_sat(T)        = saturation vapor pressure at T   (Tetens-Magnus or Buck)
P_vapor         = RH × P_sat(T)
ρ_vapor         = P_vapor × M_water / (R × T)      (ideal gas, M_water = 0.018015 kg/mol)
m_vapor_in_air  = ρ_vapor × V                      (kg of water in vapor phase)
```

Direct, cheap, real-time. This is the operating regime ~90% of the time.

### 2. RH ≥ 100% (sensor pinned) — integrate humidifier actuator

When RH saturates the sensor, additional water beyond `m_sat(T) = ρ_sat(T) × V` is no longer in vapor phase — it's condensing on surfaces (walls, substrate, sensor body). The sensor goes blind. But the actuator still produces a known mass-flow when commanded:

```
ṁ_humidifier(duty) = k_humidifier × duty   (kg/s, calibrated empirically)
m_total(t)         = m_sat(T) + ∫ ṁ_humidifier(τ) dτ   over time-since-saturation
                                  - m_loss(τ) (leakage + ventilation, also empirical)
```

Calibration: we have months of "duty → ΔRH at known T,V" telemetry already in TimescaleDB. Phase 27 PID tuning data is the calibration set. `k_humidifier` is recoverable from a regression on that data.

This is a classic **observer / state estimator** pattern — Kalman or just exponential-decay-with-bounded-trust depending on how clean the calibration looks.

### 3. Camera macro — condensation as ground truth

Visual condensation on chamber surfaces is a binary-ish signal that becomes valuable at exactly the regime where the RH sensor goes blind:

- **Calibration aid:** "RH sensor reads 100% AND no visible condensation" → `m_total ≈ m_sat(T)`. Anchors the integration baseline.
- **Saturation-onset detection:** First visible droplet on the camera-facing wall → confirm sensor saturation is real (not drift).
- **Beyond-sensor-range measurement:** Density/extent of condensation droplets correlates roughly with `m_total - m_sat(T)`. Not metric, but trend-useful.
- **Pinning observable:** Condensation is *the* phenomenon being driven during force-condensation experiments (Phase 31). Camera macro turns the experiment into a measurable thing.

Implementation sketch: small ROS node (or bridge-side `fc_metrics`-adjacent module per memory `project_999_27_bridge_side_derivation`) that polls `fc1/camera/frame`, runs a lightweight condensation classifier (could be classical CV — local variance / specularity threshold — or a tiny CNN), publishes `fc1/derived/condensation_score` as a 0..1 signal at low rate (e.g. 1/min).

## Why this is a seed, not a phase

- **Order of operations:** can't usefully ship without VPD scoping decision (covered by SEED-004 + 2026-05-09 farmer call).
- **Calibration data needs farmer attestation** — `k_humidifier` regression should be sanity-checked against operator intuition before becoming load-bearing.
- **Camera macro depends on camera being back online** (one of the 2026-05-09 visit items).
- **Composes with Phase 999.27** (derived telemetry on bridge) — water-mass and condensation-score belong in the same `fc_metrics` module.

## Trigger conditions to promote out of seed status

- Farmer call confirms VPD targeting is in scope for v1.6 → SEED-004 + SEED-005 promote together.
- OR: Phase 31 attestation surfaces "force-evaporation behavior is unpredictable past sensor saturation" → SEED-005 alone gets promoted as the diagnostic answer.
- OR: 999.27 (derived telemetry) gets planned and a phase-author wants water-mass as the first non-trivial derived series.

## Open questions (for research / overnight prep)

- What's the actual chamber free-air volume after substrate? Need a measurement. Operator note says "we know the volume" — confirm and write it into config.
- Is `k_humidifier` linear in duty over the full 0..1 range, or does the slow-PWM windowing introduce nonlinearity at low duty? Phase 27 tuning data should answer.
- Does SCD41's RH channel saturate at the same point as SHT30's, or earlier/later? Memory `project_phase26_sht30_happy_path_unverified` notes SCD41 RH clips at 100% — sensor-specific calibration may be needed.
- Camera macro: classical CV vs. small CNN? Tradeoff is fc1 CPU budget (memory `project_fc1_tailscale_cpu_spike`) vs. accuracy. Probably classical to start.
- Leakage/ventilation term `m_loss` — chamber is closed but not sealed; needs an empirical decay constant. Recoverable from "humidifier off, RH decay" data we already have.

## Dependencies / cross-references

- SEED-004 — VPD-targeted control needs this as the underlying state variable.
- 999.27 — derived telemetry, where this lives architecturally.
- 999.33 — twin/sim work would consume the water-mass model directly.
- Phase 31 — force-condensation/evaporation experiments are *the* validation for this observer.
- Memory `project_999_27_bridge_side_derivation` — bridge-side derivation, not fc1 ROS node.
- Memory `project_phase26_sht30_happy_path_unverified` — SCD41 RH clipping; sensor-specific calibration needed.
- Memory `project_blackout_2026_05_02_fc_core_stuck` + `feedback_gap_over_noise` — observer must degrade gracefully when sensor data is missing; no spiky/wrong values.

---

*Seed planted: 2026-05-08*
*Promotes when: VPD scoping decision lands OR Phase 31 surfaces sensor-saturation pain*
