# PID Calibration Notes — FC-1 Humidity

**Date:** 2026-05-03  
**Chamber:** FC-1 stack  
**Target:** 94% RH

## TODO

- [x] Find current P/I/D values in config
- [x] Try `ros2 param set /fc_controller pid_kp 0.35` and observe for 30-60 min — 2026-05-04, large limit-cycle decayed from ±0.6% to ±0.1%; Kp=0.35 is keeper for low-RH-target steady state
- [ ] Consider adding a ±0.3% deadband to stop controller chasing sensor noise
- [ ] **Next session (target: weekend 2026-05-10/11):** address the rising-temp under-shoot mode discovered today — see "Session 2 — 2026-05-04" below

## Session 2 — 2026-05-04 (intra-day, target stepped 0.94 → 0.97 → 0.96)

### What we ran
- 11:14 UYT — `pid_kp` 0.5 → **0.35** (live, no restart). Worked: morning's ±0.6% limit cycle decayed to ±0.1%.
- 11:35 UYT — `target_humidity` 0.94 → **0.97**. ⚠️ Mistakenly set as `97.0` first (wrong unit — param is fraction); corrected to 0.97 ~40 s later. `_effective_setpoint` ramper had walked to 22.47 in that window; Mode C bypass froze the integrator → no windup damage; humidifier ran full ON for ~90 s during the ramp-back-down.
- 11:57 UYT — `target_humidity` 0.97 → **0.96** (small step down).

### Three behaviors observed
1. **Climb to 0.97 (14:37–14:56 UTC):** duty pinned at 1.0 the whole time; RH climbed 94.5 → 96.5 over 19 min. Fine but slow.
2. **PID "let go" too aggressively at the 0.96 step (14:57–15:04 UTC):** duty fell `0.98 → 0.83 → 0.73 → 0.64 → 0.58 → 0.52 → 0.49 → 0.46` while RH was still at 96.5+. Derivative-on-measurement + Kd=4.0 dominated. By the time RH actually fell, duty was already too low and chamber lag (~5 min) made the recovery pure overshoot.
3. **Saturated and stuck (15:11–15:21+ UTC):** duty pinned at 1.0, RH flat at 95.2%, target 0.96. Temperature had risen 14.6 → 17.5 °C (+2.9 °C in 65 min). Saturation pressure rose ~20%; at constant water-vapor mass, RH naturally falls. Humidifier is at full output and can't outpace the rising-temp moisture demand.

### Current best understanding
- **Kp=0.35** is keeper for steady state at static-temperature operating points. Don't go lower without re-evaluating.
- **Kd=4.0 may be too high relative to Kp=0.35.** Originally tuned with Kp=0.5 (ratio 8); now ratio is 11.4 → derivative term dominates. Hypothesis: Kd=2.5–3 would soften the duty-shed response on small target changes / transient disturbances without losing high-frequency rejection.
- **Single-input PID can't solve the rising-temp problem.** Reactive feedback always lags chamber thermal mass + ~5 min response lag. The controller needs to know temperature is changing and pre-emptively hold more duty.

### Plan for next session — target weekend 2026-05-10/11

**Why wait:** want a week's worth of dawn-to-dusk temperature swings + multiple target levels (0.94, 0.96, 0.97?) recorded so we can fit a proper feedforward curve, not eyeball it.

**Data to gather between now and then** (no action needed — telemetry is already recording):
- Each morning's temp ramp: how much duty is required to *just hold* RH steady through a 2–3 °C rise?
- Steady-state duty vs (temp, target_RH) — populate a small lookup table from observed quiescent points.
- Observe whether 0.96 is achievable at peak afternoon temperatures, or whether the humidifier is actually at hardware capacity at the high end.

**Tuning experiments to run** (in order, single change at a time, ≥30 min observe each):
1. `pid_kd` 4.0 → **2.5**, then 3.0 — does the "let go" softening fix step-down overshoot without re-introducing a limit cycle?
2. `pid_ki` 0.002 → **0.005** — does a stronger integrator pick up the rising-temp slack reactively (cheaper than feedforward, less responsive)?
3. **±0.2% deadband on RH error** before PID engages — kills sensor-noise chasing, frees actuator to rest at steady state.

**The structural change (composes with 999.27):**

Add a **temperature-feedforward term** to duty:

```python
ff = ff_gain * (current_temp - ff_temp_ref)  # or function of dT/dt
duty = pid(error_pct) + ff
```

Empirical calibration: pick `ff_temp_ref` = morning steady-state temp (~14.5 °C), find `ff_gain` such that observed duty-rise during morning warm-up matches the predicted `ff` curve.

Cleaner version (proper physics): use **VPD or absolute humidity** as the controlled variable instead of RH — VPD is target-temperature-invariant, so the disturbance from temp is removed at the *measurement* level rather than compensated downstream. This is the 999.27 derived-telemetry path: `vpd` and `abs_humidity` as first-class signals.

**Decision to revisit:**
- Is 0.96 RH at 17.5 °C actually achievable with current humidifier? If today's flat-line at 95.2% is the steady-state ceiling, no amount of tuning fixes it — we need a bigger mister or a second head. Capture this as a hardware question separate from the tuning question.

### Reference: the 0.97 → 0.96 telemetry slice

Useful trace for re-running the "let go" analysis: 14:33 UTC (target step) through 15:21 UTC. Available in Timescale `telemetry` table on elder-plops; topics `fc.humidity`, `fc.humidity_target`, `fc.pid_output`, `fc.humidifier_duty`, `fc.humidifier`, `fc.temperature`.

## Chamber Dynamics — first-pass system identification (2026-05-04)

**Chamber:** "Carpa De Cultivo Indoor Interior 2,4m × 1,2m × 2m Negro" grow tent.
- Volume: 2.4 × 1.2 × 2.0 = **5.76 m³**
- Air mass: ρ_air × V ≈ 1.2 × 5.76 = **~7 kg**

**Mass-balance solved from three operating points** (cold steady-state, warm climb, warm plateau):

| Quantity | Estimate | Method |
|---|---|---|
| **Mister output M** | **~5–6 g/min** (~300 mL/h) | Triangulated from M·duty=L equations across operating points |
| **Leakage rate, cold (8.8°C, 94% RH)** | ~1.4 g/min | M × steady-state duty 0.27 |
| **Leakage rate, hot (17.5°C, 95% RH)** | ~5 g/min | Net dRH/dt during climb at duty=1.0 |
| **Leakage scaling cold→hot** | 3.5× | Matches saturation-pressure-differential physics (~2.6× predicted) |
| **Headroom at peak demand** | **~0.3 g/min net** at duty=1.0 hot ambient | dRH/dt + temperature rise tax |
| **Dead time (relay → RH peak)** | **~50 s** | Single-pulse impulse response, 09:33:32 ON pulse |
| **Approach time constant τ** | **~10 min** | m_excess / leak_rate at warm conditions |

**System ID method (for next session):**

The 09:33:32 pulse (cold morning, target 94 %, 36 s ON pulse) is a clean reference impulse. RH goes 93.93 → 94.06 (0.13 % amplitude), peak at +50 s post-relay-ON. This single trace gives both dead time (lag to peak) and impulse gain (Δw per second of ON time). Repeat at multiple temps to build a temp-conditioned plant model.

**Key revisions to today's diagnosis:**

- Earlier "stuck at 95.2% / 17.5°C" was *wrong* — chamber was still gaining ~0.3 g/min net water; RH was creeping up, just paying a temperature tax simultaneously. Not at hardware ceiling.
- **0.96 RH at 17.5°C is achievable**, just with a 10–15 min catch-up time during which temp keeps rising. The race between temp and water accumulation is winnable for the current hardware envelope.
- The morning's "let-go" failure was a PID problem, not a capacity problem. Feedforward from temp would prevent the let-go entirely.

**Implications for control law:**

- **Dead time = 50 s** is the binding constraint. The PID derivative filter τ_D = 10 s can't see ahead far enough; this is why aggressive Kd worsens transient ringing. Smith predictor or model-predictive controller would be the textbook answer; for now, accept that fast closed-loop tuning is impossible and bias toward conservative (lower Kd, higher integrator).
- **Per-pulse RH amplitude 0.13 %** is below the sensor noise floor for SHT30 (~0.1 % typical). Some of the limit-cycle behavior we tune around may literally be the controller chasing sensor noise. **±0.2 % deadband** (already on TODO) becomes more justified.
- **Capacity ceiling vs achievability:** at duty=1.0 the chamber gains water proportional to (M − L). At today's max temp (17.5 °C) net is ~+0.3 g/min — system winning. If max temp climbs to ~20 °C, L_hot rises further and the net could go zero or negative — at that point 0.96 becomes unreachable. Worth instrumenting **outside temp** (or at least chamber wall temp) to predict when this regime starts.

**Hardware backlog seed (separate from tuning):**

A second ultrasonic head (≈$15 part, doubles M) would push capacity ceiling at any temp, shrink catch-up time after disturbances ~2×, and give comfortable headroom for fruiting-stage 0.97+ targets on warm summer afternoons. **Not required** for current 0.94–0.96 envelope but worth filing as a v1.5+ hardware option. Composes with 999.29 (max-continuous-on cap redesign — second head changes the capacity math fundamentally) and the eventual feedforward work (more actuator authority = feedforward easier to tune).

**Numbers to validate on a quiet morning:**

- At duty=0 (humidifier OFF) for 10+ min, observe RH decay rate to confirm leakage τ.
- At a clean OFF→ON transition with stable temp, confirm dead time and Δw per ON-second.
- Pull a few clean transitions across different temps to map M(T) and L(T) — is M actually temp-independent (ultrasonic prediction) or does it drift?

## Session 2 (cont.) — afternoon temp-peak event (2026-05-04 ~13:32–14:47 UYT)

After the 11:57 step to target=0.96 and the brief mid-day mini-cycles, the system rode through a clean temperature peak which produced the cleanest overshoot/undershoot dataset of the day.

### Capacity revision

Earlier conclusion "0.96 RH unreachable at 17.5°C" was **wrong**. At 18.84 °C (temp peak ~12:59 UYT) with duty=1.0, RH bottomed at **95.63 %** — only 0.37 % below target. Mister output estimate revises upward: **~6 g/min** (was 4–5). Real capacity ceiling for 0.96 RH is closer to **19.5–20 °C ambient**, not 17.5.

Even later at 19.95 °C peak (~13:55 UYT) the system held RH near 96 %. Hardware envelope is more generous than the morning's "stuck plateau" suggested.

### Two flavors of overshoot observed today

| Event | Trigger | Duty trough | RH undershoot |
|---|---|---|---|
| 11:57 UYT | **Setpoint step** 0.97→0.96 | 0.46 | 95.2 (large) |
| 12:44 | Organic cross @ rising temp | 0.90 | ~none |
| 12:59 | Organic cross @ temp peak | 0.89 | ~none |
| **14:00–14:30** | **Temp plateau + falling** | **0.40** | 95.8 |

**Pattern:** crossings during *ongoing* rising-temp demand stay gentle (duty trough ~0.9). Crossings triggered by setpoint steps OR temp-plateau-and-fall trigger deep over-shed (duty trough ~0.4) → measurable RH undershoot → recovery cycle.

**Both failure modes are structurally identical** — the controller has no awareness that demand is *changing*, so it over-corrects whenever the chamber's environmental driver shifts. A feedforward-from-temp term would smooth both. This validates the next-session direction.

### New measurement: chamber response to sustained perturbation

Temp peak at **13:55 UYT** (19.95 °C) → RH peak at **14:14 UYT** (96.35 %) → **19-minute lag.**

This is *not* the 50-s impulse dead time — it's the chamber's effective **second-order response** to a sustained driver shift (temperature). Useful model parameter for any future MPC / Smith predictor work. Order-of-magnitude consistent with the ~10 min τ estimated from the morning OFF→ON transient, with extra delay from the integrator's continued push past the natural peak.

### Visual confirmation of bug 999.32 on dashboard

The orange duty trace shows clear tick-to-tick jitter (~±5–8 % swings) throughout the 14:02 → 14:47 descent and recovery. The magenta PWM cycling looks proportionally clean (driven by the duty *average* per window). This is the unfiltered-derivative noise made visible — the bug is observable on the live dashboard, not just in code review.

### Updated next-session plan additions

- Capture this temp-peak event slice (15:30 → 17:00 UTC, 2026-05-04) as the **canonical feedforward calibration dataset** — it has clean temp peak, RH lag, full overshoot/undershoot cycle, all without manual perturbation.
- Re-think Session 1's "drop Kd 4.0 → 2.5" hypothesis: the deep let-go at 14:00 was *integrator-driven*, not derivative-driven. Lowering Kd may not help that mode. **Lowering Ki** (or adding integrator clamping below the simple_pid output_limits clamp) is probably the right knob for plateau-undershoot, not Kd.
- Updated tuning experiment order:
  1. **Fix 999.32 first** (filter the derivative) — must precede any Kd retuning so we're tuning to a clean signal.
  2. Then evaluate Kd at *quiet operating points* — does it still need to come down with derivative properly filtered?
  3. **Lower Ki** (0.002 → 0.001) and observe whether the temp-plateau undershoot shrinks. Tradeoff: weaker integrator means more steady-state error during persistent demand.
  4. Feedforward-from-temp as the structural fix that makes the Ki tradeoff moot.

### Late-afternoon limit cycle — integral-driven oscillation (16:30–18:30 UYT)

After temp peaked and started falling, a clean regular oscillation emerged that is structurally different from morning's P-driven ringing.

**Observed:**
- Period: **~28 min** (vs morning's ~7 min P-driven ring)
- Amplitude: ±0.3 % RH (95.7 ↔ 96.3), ±0.2 duty (0.4 ↔ 0.6)
- RH-to-duty phase: roughly **quarter cycle lag** — duty bottoms ~7 min after RH peaks, and vice versa
- Mean duty trend: smoothly falling 0.5 → 0.2 over 2 hours as temp drops 18.7 → 14.3 °C
- Temp itself: monotonic, no oscillation — disturbance input is smooth, output oscillation is internally generated

**Diagnosis: integrator chasing a slow plant.**

For a dead-time-dominated plant (θ ≈ 50 s, τ ≈ 10 min), a P-only limit cycle would run with RH and duty roughly in antiphase. Our observed cycle has them in **quadrature** (~90° out of phase) — the signature of an I-dominated loop. Mechanism:

1. RH dips below target → integrator builds positive correction over time
2. Plant lag (chamber τ + dead time) delays the response
3. By the time RH responds and crosses target, the integrator is already over-committed
4. Integrator now slowly unwinds in the negative direction → over-correction in the other direction
5. Repeat, indefinitely

**Skogestad SIMC sanity check:** for our θ ≈ 50 s, τ ≈ 600 s, with τc ≈ θ, recommended Ki ≈ 1/(Kp × (τc + θ)) ≈ 1/(0.35 × 100) ≈ **0.029** in error-percent-per-second units. simple_pid's Ki uses different units (output per error per second), so direct numerical comparison is fragile — but the empirical answer is clear: try halving Ki and observe.

**Why it didn't show up earlier in the day:**
- Cold morning steady state: low duty (~0.27), small disturbances, integrator dwelling near zero — couldn't develop a swing
- Mid-day chaos: saturation clipped both this cycle and the higher-frequency P-ring
- Afternoon falling-temp: mid-range duty, slow monotonic disturbance creates ideal conditions for I-loop ringing
- 2026-05-03 evening calibration session didn't surface it because Kp=0.5 then meant P-driven ±0.6 % cycle masked any longer-period I cycle

**Tuning takeaway:**
- This cycle is **not killable by Kp adjustment** — it's I-loop, not P-loop. Lowering Kp would make the integrator do *more* of the work, potentially worsening the cycle.
- This cycle is **not killable by Kd adjustment** — derivative is fast-acting, won't damp a 28-min period.
- **Lowering Ki is the right knob.** Try Ki 0.002 → 0.001 first; if cycle persists, → 0.0005. Tradeoff: weaker integrator means more steady-state error under persistent disturbance — fine for our ±1 % operating band.
- **Bumps Ki experiment up in priority** to be alongside the 999.32 derivative-filter fix — both valuable, neither dominates the other.

**Updated experiment priority for next session:**
1. Fix 999.32 (derivative filter) — clean signal to tune against
2. **Lower Ki 0.002 → 0.001** — directly addresses the late-afternoon cycle
3. Re-evaluate Kd at quiet operating points (post-filter)
4. Feedforward-from-temp as the structural fix

**Operating-point sensitivity warning:**
The morning's calm at 0.94/9 °C with Kp=0.35 vs the afternoon's ringing at 0.96/18 °C with the same gains demonstrates the plant is **non-linear** (saturation pressure curve makes process gain temperature-dependent). Single-point PID tuning will always be a compromise. Long-term path: gain scheduling on temp, or move to controlling VPD instead of RH (composes with 999.27 derived telemetry).

## Current PID Config (`src/chambers/fc-core/config/fc_config.yaml`)

| Param | Value |
|-------|-------|
| `pid_kp` | 0.5 |
| `pid_ki` | 0.002 |
| `pid_kd` | 4.0 |
| `pid_derivative_filter_tau` | 10.0s |
| `pwm_window_seconds` | 120.0s (2-min duty cycle window) |

Params are **live-reloadable** — re-read every control tick. Use `ros2 param set` to tune without restart. Changes don't write back to yaml; update manually once a value is confirmed good.

## Diagnosis

This is a **limit cycle**, not a transient. The oscillation does not decay — same amplitude at 21:00 as 22:15. Caused by P gain being too aggressive for the ~5 min system lag between duty change and sensor response.

A well-tuned PID on this system should reach essentially flat steady state. Next step: drop Kp ~30% (0.5 → 0.35) and observe whether oscillation decays over 30-60 min.

## First Run Observations

Humidity settles well to setpoint but oscillates with ~5-7 minute period, ±0.2-0.3% amplitude.

- Initial heat-up (17:00–19:00): underdamped, large overshoot/undershoot
- Steady state (20:00+): centered on 94%, limit cycling, duty steady at ~0.55–0.65
- Actuator: PWM duty on humidifier (2-min window), pink dots = instantaneous on/off within cycle

## Charts

![Overview](pid_cal_overview.png)
![Full session](pid_cal_full.png)
![Zoomed steady state 21:00–22:15](pid_cal_zoomed.png)
