# Calibration findings — 2026-04-11

## ⚠️ Data caveat — read this first

**SHT30 was offline during this session** (known v1.0 tech debt, pending
physical reinstall). All humidity readings came from the **SCD41**'s
secondary RH channel, not the SHT30.

Implications for how to read this document:

- **Nominal SCD41 RH accuracy is ±6%** vs SHT30's ±1.5% — so overshoot
  and undershoot figures at the <1% scale may be within sensor noise.
- **SCD41 samples RH at a different physical location** than SHT30
  would, so what we're measuring is the SCD41's thermal/moisture
  environment — not necessarily what a mushroom on the shelf sees.
- **SCD41 RH has its own warm-up/settling behavior** that may contribute
  to the post-restart spike attributed to "sensor warm-up" in backlog 999.8.
- The **qualitative findings remain valid** — bang-bang + dwell does
  structurally overshoot under narrow bands, and PID + slow-PWM is still
  the right architectural answer. But any specific number in this doc
  (rise rate, decay rate, overshoot magnitude) should be **re-measured
  once SHT30 is back online** before being used to tune a PID loop.

**The single most important thing in this document** — the DWELL-BLOCK
log line showing the controller wanting to toggle but being clamped — is
a controller-behavior observation, not a sensor-accuracy observation,
and is not affected by the SHT30 absence.

---

Empirical data from a farmer-led calibration session on fc1 (live chamber,
real hardware, **SCD41 humidity only** — SHT30 offline, see caveat above,
SSR-driven ultrasonic humidifier). Session narrowed `humidity_tolerance`
from ±5% → ±1% → ±0.5% and observed the resulting bounce behavior.

This document is feedback for the development team on why bang-bang +
dwell control has a structural ceiling and why PID + time-proportional
output (this phase) is the right next step.

## System identification

Measured from multiple cycles under different band widths:

| Metric | Value | Notes |
|---|---|---|
| Rise rate (dry, RH ~65%) | ~5 %/min | Humidifier fighting low equilibrium |
| Rise rate (near setpoint, RH ~80%) | ~0.8 %/min | Evaporative equilibrium dominates |
| Decay rate (passive, RH ~80%) | ~0.7 %/min | Ventilation + absorption |
| Rise/decay asymmetry near setpoint | ~15% | Humidifier barely outpaces decay |
| Coast overshoot after OFF (±1% band) | +0.19 % | Clean, minimal |
| Coast undershoot after ON (±1% band) | −0.30 % | Clean, minimal |

**Key insight:** the rise/decay rates are strongly nonlinear in RH. Dry
recovery is ~5× faster than near-setpoint operation. A PID tune must
account for this — a single gain set will either be sluggish at
steady-state or violent during recovery.

## The ±0.5% pathology — why bang-bang + dwell is capped

Session narrowed to a ±0.5% band (79.5–80.5%) with `min_dwell_time = 180s`
unchanged. Observed one DWELL-BLOCK event and one full cycle:

```
20:36:47 DWELL-BLOCK: humidifier ON->OFF delayed by dwell
         (elapsed 118.0s < 180s, 62.0s remaining) | RH=80.54%
```

At the moment RH crossed the upper threshold, the controller wanted to
toggle OFF but dwell clamped the humidifier ON for another 62 seconds.
During those 62s, RH continued rising at ~0.8 %/min.

**Result:**

| | Target | Actual | Excursion |
|---|---|---|---|
| Upper bound | 80.5 % | **82.49 %** | **+1.99 %** |
| Lower bound | 79.5 % | 79.31 % | −0.19 % |

**The forced overshoot was 4× the band width itself.** The dwell guard,
intended to protect humidifier hardware from rapid cycling, is
**structurally incompatible with narrow bands** — it actively causes the
very bounce it's supposed to prevent.

## Conclusion

**Bang-bang + 180s dwell has an effective regulation ceiling of ~±2% RH**,
regardless of how narrow the nominal band is configured. Tightening
`humidity_tolerance` below ~1% produces no additional regulation benefit
and simply shifts overshoot from configurable to hardware-constrained.

For regulation tighter than ±1%, the controller must be able to
**modulate actuator duty cycle** rather than issue discrete toggles. This
is what phase 999.9 is for.

## Recommendations for the PID + slow-PWM design

Based on today's data:

1. **Time-proportional window length ≈ 30–60s.** The dry-rise rate (~5 %/min)
   means a 60s window can deliver up to 5% RH in one shot — fine granularity
   for near-setpoint control, aggressive enough for recovery.

2. **Duty-cycle saturation near setpoint should be ~15%.** That's the
   measured excess of humidifier output over passive decay. A PID integrator
   should settle somewhere near 15% duty under nominal conditions — useful
   as a sanity check during tuning.

3. **Gain scheduling or adaptive tuning.** The 5× rise-rate nonlinearity
   between dry and near-setpoint operation is too large for a single fixed
   Kp. Either schedule gains by RH zone, or use an adaptive algorithm.

4. **Replace `min_dwell_time` with `min_window_duration`.** In a
   time-proportional scheme, the safety constraint is "humidifier may not
   change duty more than X% per window" or "windows may not be shorter
   than Ys", not "toggles must be Zs apart". The semantic shift matters
   for how safety tests are written.

5. **Preserve the existing sensor-stale safe-state.** Today's dwell
   behavior is unsafe under narrow bands but the staleness-triggered OFF
   is sound — keep it, just graft it onto the new output layer.

6. **Operating band recommendation for the interim (until 999.9 ships):**
   `humidity_tolerance: 0.01` (±1%). The data shows this produces clean
   ~6–7 min cycles with <0.3% overshoot/undershoot and no dwell engagement.
   Anything tighter is wasted config until duty-cycle control exists.

## Prerequisite data already collected

Everything a PID tuner or Ziegler-Nichols-style identifier needs for this
chamber has been captured in telemetry:

- Step response from 64% → 81% (restart recovery, 20:27–20:30)
- Steady-state cycle under hysteresis (20:34–20:42, ±0.5% band)
- Passive decay curves (multiple)
- Deadtime measurement: humidifier OFF at 20:37:49, RH peak at ~20:38:05 →
  ~16s dead time between actuator change and sensor response

The full raw data is in the `telemetry` hypertable on
`mushy_timescale_1` for the window 2026-04-11 19:48 to 20:43 UTC.

---

*Captured during farmer-led calibration session 2026-04-11.
Session ended at ±1% band, pending 999.9 implementation.*
