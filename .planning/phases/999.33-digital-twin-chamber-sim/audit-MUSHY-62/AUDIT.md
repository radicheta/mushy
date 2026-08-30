# Audit of the idle-window Q identification (MUSHY-62, 2026-08-30)

Question put to the auditor: is the idle-window Q (1.899, "well-fit" cluster,
commit 9f9f69d6) or the MUSHY-60 joint active-data fit (0.9634, band
[0.658, 1.242]) the better-conditioned estimate?

**Answer: neither. Both are fitted to the wrong model shape, and both numbers
are mostly measuring how fast the chamber was COOLING in the windows each
method happens to select.** The idle chamber's absolute humidity tracks the
saturation curve at near-constant RH: it loses ~0.49 g/m3 per kelvin of
cooling and gets it back on warming. That reversible, temperature-coupled
surface term explains 83% of the idle-window variance; the gradient-driven
leak the model is built around explains 10%.

Everything below was run on branch `audit/MUSHY-62-idle-q`. The shipped
`ChamberParams` is unchanged; the branch adds one default-off parameter
(`surface_g_per_k = 0.0`) so the term can be tried, and `--q/--f/--c`
overrides on `replay-chamber-day.py`. Default replay regenerates the committed
2026-08-08 artefacts byte-identically; container suite 366 passed / 3 xfailed.

## 1. The idle-window method itself (fit-idle-windows.py) -- checks

Reproduced exactly: 192 windows, 2033 h, well-fit (R2>=0.7) 52 windows
Q median 1.899, poorly-fit 140 windows Q median 0.520.

* Math is right for the model it assumes: with duty=0 the balance is a
  one-parameter line through the origin, slope Q/V. Central difference,
  hole rejection, saturation exclusion all behave as described.
* fc.humidifier is NOT edge-only for the whole history: April has 1.51M rows
  (~2 s periodic), May 115k, Jun-Aug 14-23k. `idle_windows()` is idempotent
  on repeated same-value rows so the windows are still right; note for anyone
  averaging that topic.
* R2 through the origin (`1 - ss_res/sum(y^2)`) selects for windows with a
  strong monotone decay, i.e. it selects for the model being right, as the
  filing already warned.
* Start-of-window effect is real but secondary: dropping the first 0/15/30/60
  min gives well-fit Q 1.899 / 1.787 / 1.579 / 1.482. The fast regime
  survives an hour into the window, so it is not mist settling or the 600 s
  mixing lag.
* Q vs window length: medians 1.12 (<1.5 h), 1.10, 1.16, 0.99, 0.78 (5-10 h),
  0.50 (10-24 h), 0.34 (>24 h). Spearman Q~length -0.26.

## 2. What actually sets Q: the cooling rate

Pooled derivative points (106,198), bucketed by minutes since the relay
dropped, split at dT/dt = -0.3 C/h:

| minutes since OFF | Q pooled | Q while cooling (n) | Q not cooling (n) |
|---|---|---|---|
| 4-8     | 1.450 | 1.788 (480)   | 0.136 (260) |
| 9-16    | 1.596 | 1.859 (848)   | 0.509 (436) |
| 17-40   | 1.585 | 1.970 (2746)  | 0.318 (1454) |
| 41-120  | 1.151 | 1.703 (6804)  | 0.048 (4994) |
| 121-360 | 0.945 | 1.812 (8958)  | -0.069 (10097) |
| >360    | -0.172 | 0.793 (16354) | -0.496 (52049) |

Spearman Q~dT/dt across all 192 windows: **-0.715**. Among well-fit windows
the Q median runs 2.16 / 1.93 / 1.87 / 1.27 / 0.72 as the cooling rate goes
from < -1 C/h to > 0. The MUSHY-60 FIT-RESULTS "Q is regime-dependent" table
(1.8 at 4-8 min falling to 0.3 beyond 2 h) and MUSHY-62's well-fit/poorly-fit
split are the same composition effect: short post-OFF windows are evening
cool-downs, long ones span the day.

## 3. Two-regressor fit: dAH/dt = -(Q/V)*(AH_in - AH_out) + (C/V)*dT/dt

| points | 1-param Q | R2 | 2-param Q | C (g/K) | R2 | dT-only R2 |
|---|---|---|---|---|---|---|
| all (106,198) | 0.774 | 0.099 | 0.363 | 2.825 | 0.830 | 0.809 |
| since OFF >= 30 min | 0.583 | 0.054 | 0.320 | 2.788 | 0.840 | 0.824 |
| since OFF 30..360 min | 1.132 | 0.315 | 0.366 | 2.779 | 0.810 | 0.784 |

Per-window R2 >= 0.7: **52/192 with one parameter, 174/192 with two.**
Per-window medians: Q 0.26, C 2.72.

C = 2.8 g/K over the 5.76 m3 chamber = 0.49 g/m3/K, which is 0.9x the
saturation slope dAH_sat/dT at 10 C (0.60 g/m3/K). Physically: the idle air
is in equilibrium with wet surfaces (walls, substrate, standing water) and
its RH is pinned; AH is a slave to temperature.

Steady-state leak (|dT/dt| <= 0.1 C/h, >= 30 min since OFF, n=18,282):
Q = 0.146 m3/h (R2 0.05 -- there is almost no gradient-driven signal).

## 4. It is condensation/re-evaporation, not the vent

The unrecorded ~15 min/h vent was the standing explanation for the spread in
Q. Two tests, both negative:

* Air exchange drops temperature and moisture together only while the
  chamber is warmer than outside; when it is colder the temperature term
  flips sign. C does not flip: chamber warmer than outside (Tin-Tout > 0.5)
  C = 2.82; colder (< -0.5) C = 2.72; within 0.5: 2.83.
* C is symmetric between cooling (3.12) and warming (2.60): the water comes
  back. A leak never gives water back.
* Minute-of-hour stack of detrended chamber temp/AH inside idle windows: a
  real hourly signature exists, but it is ~13 mK and ~7 mg/m3 peak-to-peak
  (warm around minutes 30-40). A 15 min/h exchange at a ~2 g/m3 gradient
  would be two orders of magnitude larger. Either the vent is not on a
  wall-clock timer, or it does not run during idle stretches, or it moves
  negligible air. Relevant to MUSHY-72.

## 5. The 46 "gained gradient while idle" windows

36 of 46 had ambient AH falling; in 30 ambient fell by more than the chamber
rose (a dry front the slow chamber lags -- the shipped model CAN do that).
Only 24 saw chamber AH actually rise, and those are warming windows
(dT +1.5..+2.7 C): re-evaporation, i.e. the same C term with the sign
reversed. There is no unexplained moisture source.

## 6. Does the twin get better? Replays, nothing tuned to the window

C = 2.8 came from the idle-window population (the two windows below
contribute 210 and ~1,000 of 106k points -- near-independent, not held out).

2026-08-08, full day, closed loop, window PWM (recorded span 5.35 pp,
period 3.15 h):

| Q | F | C | RMSE | mean err | predicted span | period | water ratio |
|---|---|---|---|---|---|---|---|
| 0.9634 | 6.776 | 0 (shipped) | 4.58 | +0.49 | 22.6 (79.5-102.2) | 2.93 h | 1.156 |
| 0.9634 | 6.776 | 2.8 | **1.92** | -0.02 | 6.56 (87.9-94.5) | 4.86 h | 0.878 |
| 0.32 | 2.25 | 2.8 | 1.87 | +0.24 | 5.64 | 13.75 h | 0.847 |
| 0.32 | 2.25 | 0 | 8.78 | -3.00 | 33.2 | 4.51 h | 1.401 |

Sigma-delta night 2026-08-29 21:09..00:39 UTC, duty = 0 throughout
(recorded 94.26 -> 89.07, span 5.81):

| Q | F | C | RMSE | mean err | predicted |
|---|---|---|---|---|---|
| 0.9634 | 6.776 | 0 (shipped) | 8.93 | +8.51 | 94.2 -> 99.6, peak 104.35 |
| 1.899 | 13.36 | 0 | 3.67 | +3.45 | 91.8-99.1 |
| 2.10 | 14.77 | 0 | 2.83 | +2.58 | 90.6-98.5 |
| 0.9634 | 6.776 | 2.8 | **0.62** | -0.51 | 89.8-94.3 |
| 0.32 | 2.25 | 2.8 | 3.08 | +2.69 | 94.3-96.1 |

Keeping the shipped Q and F and adding the one term is the best row in both
tables. Doubling Q (the MUSHY-62 headline) helps the night and would flip the
three synthetic-gate xfails (Q=1.899: p2p 4.27, 6 bursts, 2.27 h, duty 0.159)
but leaves +2.6 pp of bias the gradient term cannot remove, and it is fitting
a cooling artefact.

Synthetic fidelity gate (`test_replay_fidelity.py`) holds temperature
constant, so C cannot act there; it stays 3 xfailed with the term on or off.
That gate cannot exercise the dominant idle-time physics of this chamber.

## 7. What remains uncertain

* Q with the term present: the pooled idle fit says 0.3-0.4, the sigma night
  prefers ~1.0. Residual band roughly [0.3, 1.0], but it is now the minor term.
* C is empirical, fitted at 85-99% RH on a chamber that is kept wet. It will
  not hold for a dry chamber (nothing to re-evaporate) and may depend on RH
  level. No held-out epoch yet.
* Predicted period on 2026-08-08 lengthened to 4.86 h against 3.15 recorded.
  Amplitude is right, dynamics are slower. Not tuned.
* Ambient is still the ~4 km grid cell (MUSHY-67); the sigma night used the
  `.recent` fixture.
* F/Q = 7.03 as a DAILY balance is untouched in principle (dT/dt integrates
  to ~0 over a day) but the active regime also loses water to the same
  surfaces; F and Q should be refitted jointly with dT/dt in the regressor
  set before any parameter is changed.

## Reproduce

    ./.venv/bin/python scripts/fit-idle-windows.py --ambient-fixture src/chambers/fc-core/fc_core/sim/data/ambient_-34.52_-55.10.recent.csv   # fit-baseline.txt
    ./.venv/bin/python <this dir>/idle_diag.py <outdir>      # per-window CSV + skip sweep
    ./.venv/bin/python <this dir>/since_off.py               # table in section 2
    ./.venv/bin/python <this dir>/two_reg.py <outdir>        # section 3
    ./.venv/bin/python <this dir>/vent_vs_cond.py            # section 4
    ./.venv/bin/python <this dir>/gate_sweep.py              # synthetic gate Q sweep
    ./.venv/bin/python scripts/replay-chamber-day.py --c 2.8 --out-tag x
    ./.venv/bin/python scripts/replay-chamber-day.py --start '2026-08-29 21:09:00+00' --end '2026-08-30 00:39:00+00' --pwm sigma --ambient-fixture src/chambers/fc-core/fc_core/sim/data/ambient_-34.52_-55.10.recent.csv --c 2.8 --out-tag y

The per-run reports are the `999.33-08-CHAMBER-DAY-audit-*.md` files here;
their 1 Hz CSVs were not kept (regenerable). Timescale DB is `postgres`.
