# VPD, "negative vapor pressure," and the chamber water-mass observer

**Date:** 2026-05-08 (overnight prep for 2026-05-09 fc1 lab visit)
**Inputs:** SEED-005 (water-mass observer), SEED-004 (VPD-anchored control), Phase 31 (force-condensation/evaporation), discussion item #2 in the visit plan.
**Audience:** Claude + farmer call talking points.
**Out of scope:** writing code; this is the conceptual + numerical scaffolding so the farmer-call decision is informed.

---

## 1. Why the framing matters

The current control surface is **RH around a setpoint with a ±1% band** (memory `project_rh_operating_band`). That's adequate ~90% of the time and breaks at exactly the regimes the operator cares about most:

- **Pinning / primordia initiation** — operator wants *condensation*, which is a physical state past 100% RH. Sensor reads 100% and stays pinned. The controller has no idea whether the chamber is "100% RH dry walls" or "100% RH soaked walls with standing water."
- **Cross-temperature comparability** — 95% RH at 18 °C and 95% RH at 22 °C are *different evaporative environments* for the mushroom. RH alone doesn't tell us the driving force of transpiration.
- **Forced-evaporation experiments (Phase 31)** — running humidifier at 0% duty drops RH but the *meaningful quantity* (drying power on the substrate) is VPD, not RH.

**VPD** gives us the cross-temperature unit. **Water mass** gives us the past-saturation unit. SEED-005 is the bridge between them.

There is no such thing as "negative vapor pressure" physically — the operator phrase points at **supersaturation / condensation regime**, where the *sensor* clips at 100% RH but the chamber keeps gaining liquid water. The right mental model is "RH is censored at 100%; water mass is not."

---

## 2. Psychrometrics — minimum viable math

### 2.1 Saturation vapor pressure `P_sat(T)`

Three candidates surveyed:

| Formula | Form | Accuracy 0–50 °C | Notes |
|---|---|---|---|
| Tetens (1930) | `0.61078 · exp(17.27·T/(T+237.3))` kPa | ±0.1% above 0 °C | Simplest. Standard in agronomy. |
| Magnus (Alduchov-Eskridge 1996) | `0.61094 · exp(17.625·T/(T+243.04))` kPa | ±0.05% | Marginal upgrade. |
| Buck (1981, AMS 2018 fit) | richer fit, separate ice/water branches | ±0.02% | Overkill for chamber. |

**Pick Magnus.** Tetens-equivalent runtime cost; better tail behavior; current go-to in agronomy and HVAC. Buck is overkill given SHT30's stated RH accuracy is ±2%.

Reference implementation (target: bridge-side `fc_metrics`, per memory `project_999_27_bridge_side_derivation`):

```js
const P_SAT_KPA = (T_celsius) =>
  0.61094 * Math.exp((17.625 * T_celsius) / (T_celsius + 243.04));
```

### 2.2 Derived quantities from `T, RH`

```
P_vapor   = (RH/100) * P_sat(T)            // kPa
VPD       = P_sat(T) - P_vapor             // kPa  (the operative quantity)
ρ_vapor   = P_vapor * M_water / (R * T_K)  // kg/m^3
            // M_water = 0.018015 kg/mol;  R = 8.31446 J/(mol·K);  T_K = T+273.15
m_vapor   = ρ_vapor * V_chamber             // kg of water in vapor phase
```

Sanity check at chamber-typical 22 °C, 95% RH, 0.5 m³ free air (placeholder — confirm V on visit):

```
P_sat(22)   ≈ 2.645 kPa
P_vapor     ≈ 2.513 kPa
VPD         ≈ 0.132 kPa     ← extremely low; consistent with fruiting band
ρ_vapor     ≈ 0.0184 kg/m³
m_vapor     ≈ 9.2 g of water in vapor phase
```

Compare 22 °C, 100% RH:

```
m_sat(22)   ≈ 9.7 g
```

So the **gap between band-edge fruiting and saturation is ~0.5 g of water in vapor phase** for a half-cubic-metre chamber. That's the entire control budget — ~250 ms of a ~2 g/min ultrasonic humidifier. Tiny. Explains why the current PID dwell-clamp gymnastics matter so much.

### 2.3 VPD reference targets (cross-checked from cannabis/agronomy + the mushroom-glossary results)

Mushrooms are emphatically **not** cannabis, but the VPD-vs-stage shape is the same; mushroom stages run cooler and wetter, hence lower VPD across the board:

| Stage | RH | T | VPD (Magnus, kPa) |
|---|---|---|---|
| Spawn run / colonization | ~100% | 24 °C | ~0 |
| Pinning (oyster-like) | 95–100% | 16–20 °C | 0.00–0.10 |
| Pinning + condensation pulse | "supersat" | 16–18 °C | <0 (sensor-blind) |
| Fruiting (oyster) | 85–90% | 18–22 °C | 0.25–0.40 |
| Fruiting (shiitake) | 80–85% | 16–20 °C | 0.27–0.45 |
| Drydown / pre-harvest dwell | 60–70% | 18–22 °C | 0.80–1.05 |

The interesting numbers for our system:

- **VPD < 0.1 kPa is the "near-saturation" zone** where Phase 31 force-condensation is actually meaningful.
- **VPD > 0.4 kPa is the "force-evaporation" target** — Phase 31's 0% duty mode operates here.
- **VPD between 0.15 and 0.35 kPa is normal fruiting** — current PID lives here happily.

This gives the farmer-call discussion item #2 a clean shape: the VPD numbers we care about are 0–0.5 kPa with **resolution of ~0.05 kPa**. Magnus gives us that with room to spare.

---

## 3. The water-mass observer (SEED-005 made concrete)

### 3.1 Three regimes, three estimators

```
                         m_total(t)     ← the state we want
                              |
              +---------------+----------------+
              |                                |
        RH < 100% (sensor trustworthy)    RH ≥ 100% (sensor blind)
              |                                |
        m_total = m_vapor(T, RH)         m_total = m_sat(T) + ∫ṁ_in − ∫ṁ_out
              |                                |
        Direct psychrometric calc        Actuator-integral observer
                                                |
                                         Camera macro = ground-truth anchor
```

The observer has three modes; `RH` selects the mode.

### 3.2 Regime A: `RH < 99.5%` — pure psychrometric

Formula in §2.2 above. Cheap. This is the dominant operating regime; most of fc1's life is here.

### 3.3 Regime B: `RH ≥ 99.5%` — actuator-integral

Once the sensor saturates, the equation becomes:

```
dm_total/dt = ṁ_in(duty) − ṁ_out(T, surfaces, leakage)
m_total(t)  = m_sat(T_now) + ∫_{t_sat}^{t} (ṁ_in − ṁ_out) dτ
```

Where:
- `t_sat` = first sample where RH ≥ 99.5% (or returning from below).
- `ṁ_in(duty)` = humidifier mass-flow as a function of duty cycle. **First-order linear assumption: `ṁ_in = k_h · duty`**, with `k_h ≈ 1–2 g/min` for a 1.6MHz ultrasonic at 100% duty (vendor-typical; confirm against Phase 27 calibration data).
- `ṁ_out(T, …)` = passive losses: leakage + sensor body absorption + wall film accumulation. Recoverable from "humidifier off, RH decay" data (we have plenty in TimescaleDB). First-pass: model as `m_loss/τ` with `τ` being a fitted decay constant (probably 30–120 min).

**Nonlinearity warning** (from SEED-005 open question): slow-PWM windowing at low duty introduces a "burst-or-nothing" regime — at 5% duty, the humidifier is fully on for short windows and fully off otherwise. Mass-flow may therefore be approximately linear in duty *averaged over a window* but step-shaped instantaneously. For an integrator at 1 Hz sample rate against ~30 s PWM windows, the linearity assumption holds in expectation; integrated drift over a ~15 min experiment should be well under 5% — acceptable for v0.

### 3.4 Regime C: camera macro — ground truth

Two roles:

1. **Calibration anchor:** when RH first reads 100% AND camera shows zero condensation, set `m_total := m_sat(T)`. Resets observer drift.
2. **Beyond-sensor measurement:** condensation density correlates with `m_total − m_sat(T)`. Not metric, but trend-useful and crucially **monotonic with the right physical quantity**.

Implementation sketch (deferred to a future phase, NOT for tomorrow):

- Subscribe to `fc1/camera/frame` at 1/min.
- Run a classical-CV detector — local variance + specularity threshold on a fixed ROI on the chamber wall. Threshold-tuned per chamber on first deploy.
- Publish `fc1/derived/condensation_score` ∈ [0, 1] at 1/min via the bridge `fc_metrics` module (memory `project_999_27_bridge_side_derivation`).

### 3.5 Bridge-side, replay-aware

Per memory `project_999_27_bridge_side_derivation` and `project_alerter_is_ws_only`: the observer must run on the **bridge**, not on fc1, and must handle backfilled samples from `fc_buffer` correctly. The integrator state `(m_total, t_sat, last_T, last_duty)` needs to be:

- Rebuilt from the latest known `RH < 99.5%` anchor when a buffered batch arrives.
- Idempotent under replay.
- Degraded gracefully when there's a gap (e.g., emit `null` rather than extrapolate; per `feedback_gap_over_noise`).

This is all spec, not code. Phase-day-of, we don't touch this — but the farmer call discussion benefits from the "yes we have a path here" framing.

---

## 4. How this folds into the Phase 31 force-experiments

| Force-mode | What we currently observe | What the observer adds |
|---|---|---|
| `force-condensation` (100% duty) | RH pins at 100; `delta_rh` ends ≈ 0; experiment "succeeded" by clock | `m_total` keeps climbing; `condensation_score` ≥ threshold; experiment success ≡ "we drove water mass past `m_sat` by N grams" |
| `force-evaporation` (0% duty) | RH falls; `delta_rh` numerically meaningful | `VPD` directly readable; experiment success ≡ "we held VPD ≥ X kPa for Y minutes" |

The observer is what makes `force-condensation` an actually-measurable experiment instead of a clock-driven open-loop pulse. **This is the load-bearing argument for promoting SEED-005 if Phase 31 attestation surfaces "force-evap behavior is unpredictable past sensor saturation"** (one of SEED-005's own promotion triggers).

---

## 5. Decision shape for the farmer call

Three crisp framings to put in front of the farmer (item #2 in the visit-plan discussion list):

**Option A — "Timed bursts are enough."** Phase 31 is the final shape. RH is the user-visible quantity; force-condensation is a clock pulse with a duty cap. Close 999.33. SEED-004 + SEED-005 stay dormant.

**Option B — "Want VPD as a first-class number, but no closed-loop yet."** Promote SEED-005's regime-A psychrometric calc into 999.27 (bridge-side derived telemetry); expose `vpd` as a topic/metric. No control changes. Defers SEED-004 closed-loop to v1.6. Cheap, immediately useful, no risk to Phase 27 PID kernel (memory: byte-identical kernel preserved through Phase 28).

**Option C — "Yes to closed-loop VPD."** Promote SEED-004 + SEED-005 together; v1.6 milestone. Requires actuator integration past saturation (regime B), camera macro (regime C), and rewrites the controller setpoint surface from RH to VPD. Several phases of work. Real value if the operator is doing batch-level experiments with VPD as an independent variable.

**Recommendation to bring to the call:** B is the obviously-correct next step. It costs nothing, exposes the right quantity to the operator, and makes Phase 31 results legible. C waits on whether the operator actually thinks in VPD when running batches.

---

## 6. Open numerical questions for tomorrow at the chamber

1. **Free-air volume `V`** — measure or derive (chamber inner dims minus substrate trays). SEED-005 says "operator says we know it." Get the number, write it into config, baseline the observer math.
2. **Humidifier `k_h` calibration** — pull a 6h slice from Phase 27 PID tuning data: `(duty, T, RH) → ΔRH/Δt` regression. Solve for `k_h`. Sanity-check against vendor spec.
3. **Leakage `τ`** — pull "humidifier off" intervals from telemetry (there are plenty during operator overrides). Fit exponential decay of RH toward outdoor ambient. Should converge to ~30–120 min; if much shorter, chamber is leakier than expected.
4. **SCD41 vs SHT30 saturation behavior** — at the chamber, briefly run RH up to 100% (humidifier 100% for 2 min) and watch both sensors. Memory `project_phase26_sht30_happy_path_unverified` says SCD41 clips weirdly; we should know exactly how. Capture a screenshot.

These are nice-to-haves; none of them block tomorrow's UAT.

---

## 7. References

- [Tetens equation — Wikipedia](https://en.wikipedia.org/wiki/Tetens_equation)
- [Improved Magnus' Form Approximation of Saturation Vapor Pressure (Alduchov & Eskridge)](https://www.osti.gov/servlets/purl/548871)
- [A Simple Accurate Formula for Calculating Saturation Vapor Pressure of Water and Ice (AMS 2018)](https://journals.ametsoc.org/view/journals/apme/57/6/jamc-d-17-0334.1.xml)
- [Vapor Pressure Deficit — Pulse Labs Ultimate Guide](https://community.pulsegrow.com/t/the-ultimate-vapor-pressure-deficit-vpd-guide-pulse-labs/1069)
- [VPD glossary — mushroom cultivation](https://shroomandbud.com/glossary/vapor-pressure-deficit-vpd/)
- [Performance Evaluation of the Ultrasonic Humidification Process (MDPI 2025)](https://www.mdpi.com/2227-9717/13/10/3374)
- [Development and Evaluation of an Ultrasonic Humidifier — PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC8145257/)
