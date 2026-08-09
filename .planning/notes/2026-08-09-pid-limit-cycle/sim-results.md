# FC-1 humidity limit cycle: diagnosis and offline fix evaluation

**Date:** 2026-08-09 (overnight, farmer asleep, nothing deployed to fc1)
**Ticket:** MUSHY-56. Sim is 999.33 shape (a) / MUSHY-52.
**Branch:** `feat/chamber-sim-duty-shaping`

## The observation

Farmer reported a ~2 h cycle in humidifier duty: duty climbs to near 100 %,
RH follows with a lag, then duty sits at 0 while RH decays, until RH drops
below target and it repeats.

Confirmed from Timescale, 26 h to 2026-08-09 00:02 UYT:

| Quantity | Measured |
|---|---|
| Cycle period | 1.82 / 1.87 / 2.10 h (2.81 h mean incl. night gaps) |
| RH span | 87.33 - 92.59 (5.26 pts) |
| Duty at ~0 | 52.6 % of minutes |
| Duty commanded in (0, 0.083), then discarded | **22.3 % of minutes** |
| Mean commanded duty | 0.142 |
| Burst onset RH | 88.2 - 88.8 |
| RH peak after onset | 92.0 - 92.6, at +43 to +63 min |

## Root cause

**The controller cannot hold its own setpoint.**

The live control law (quadratic low-side feather, fc1/prod `30534ff`) feeds
`error = 0` at the band midpoint, 0.900. Zero error means zero commanded duty.
But the chamber leaks at 2.24 pts/h and needs a standing **~10 % duty just to
hold station**. So at the setpoint the controller commands nothing, and RH
necessarily drains away from it.

It cannot recover gently either, because of the actuator floor. The feather's
P-term only reaches the equilibrium duty at RH <= 0.887, which is *below*
`band_low`:

```
     RH   P-term  ~delivered   holds?     (equilibrium needs 0.100)
  0.900    0.000       0.000       NO
  0.895    0.030       0.021       NO
  0.890    0.120       0.084       NO
  0.887    0.203       0.142      yes
```

Everything the feather commands between 0.890 and 0.900 is below
`min_pulse_seconds / pwm_window_seconds` = 10/120 = **8.3 %**, so
`fc_pwm_driver` rounds it to zero and the humidifier never fires. That is the
22.3 % of discarded commands in the table above.

Net: RH must fall ~1.3 pts below setpoint before the loop can act at all, by
which point it overshoots to ~92.6, and then spends ~1.2 h draining back.
That is the 2 h cycle.

**The humidifier is not undersized.** Gross fill capacity is ~22.5 pts/h at
full duty against a 2.24 pts/h leak -- roughly 10x headroom. The problem is
resolution and bias, not capacity.

## Two negative results

**1. A slew limiter does nothing.** Requested twice (2026-06-22, 2026-08-09).
The commanded duty already rises at most **0.00046/s**, twelve times slower
than a 180 s limiter's 0.00556/s ceiling. Zero ticks out of 50,400 exceed it,
and the simulated output is byte-identical with and without. The apparent
"slam to 100 %" on the Mission Control chart is the **PWM relay toggling**, not
the duty command -- the command is already a smooth ~25 minute ramp. Pinned by
`test_slew_limiter_cannot_bind_and_is_therefore_not_shipped` so it does not get
re-proposed from intuition. **Not shipped.**

**2. Integrator changes do not help.** Disabling the 999.49 in-band decay makes
it *worse* (p2p 4.28 vs 3.79); raising `Ki` does not help either. In-band the
error is exactly zero, so there is no signal to integrate -- the loop is blind
there, and no gain tuning can fix a missing signal.

## Sweep

20 simulated hours per configuration, fitted chamber model, live gains
(Kp 0.36, Ki 0.001, Kd 4.0, decay 1800, D-filter 60, bypass 0.05).

| config | RH p2p | period | RH min | RH max | relay/h | deliv | discard |
|--------------------------------------------|--------|---------|--------|--------|---------|-------|---------|
| baseline (as-live)                         |   3.79 |  2.90 h |  88.92 |  92.71 |    10.4 | 0.101 |     186 |
| min_pulse 20 only                          |   4.01 |  2.98 h |  88.83 |  92.84 |     9.6 | 0.104 |     543 |
| accumulate only                            |   3.74 |  2.84 h |  88.96 |  92.69 |    10.5 | 0.099 |       0 |
| slew 180s only                             |   3.79 |  2.90 h |  88.92 |  92.71 |    10.4 | 0.101 |     186 |
| bias 0.10 only                             |   2.60 |    none |  89.32 |  91.92 |    29.9 | 0.103 |       0 |
| accumulate + bias                          |   2.49 |    none |  89.35 |  91.84 |    22.9 | 0.102 |       0 |
| **300s/30s + accum + bias (recommended)**  | **2.50** | **none** | **89.37** | **91.88** | **11.9** | 0.101 |   **0** |
| 600s/60s + accum + bias                    |   2.96 |    none |  89.29 |  92.25 |     5.9 | 0.100 |       0 |

Note `min_pulse 20 only` -- raising the floor without accumulation makes things
**worse** (discard triples to 543 s), which is what the farmer's instinct to
raise it to 20 s would have done on its own.

## Recommendation

`pwm_window_seconds` 300, `min_pulse_seconds` 30, `accumulate_subthreshold`
true, `humidifier_duty_bias` 0.10.

- Limit cycle gone (zero bursts in 20 h).
- Swing down 34 % (3.79 -> 2.50 pts), and RH stays inside 89.37 - 91.88.
- Relay wear essentially unchanged: 11.9/h vs baseline 10.4/h.
- 30 s min pulse respects the farmer's "~20 s minimum useful run".

If wear matters more than tightness, **600s/60s halves the wear** (5.9/h) and
still beats baseline on swing (2.96 vs 3.79).

## What is shipped, and how it is gated

Both default to **off**. Nothing changes on fc1 until someone sets them.

| Parameter | File | Default |
|---|---|---|
| `accumulate_subthreshold` | `fc_pwm_driver.py` | `False` |
| `humidifier_duty_bias` | `fc_controller.py` | `0.0` |

## Model fidelity, honestly

The sim reproduces the cycle: p2p 3.79 vs measured ~4.3/cycle, mean commanded
duty 0.146 vs measured 0.142, overshoot past `band_high`, and the discarded-
command mechanism. Known limits, also encoded in the test docstring:

- Period runs ~40 % long (2.90 h vs 1.82-2.10 h daytime). An RH-proportional
  leak was trialled to close this and **rejected** -- non-monotonic across
  floor values (86 -> no bursts, 84 -> 4.14 h), which is fragility, not fidelity.
- Under-represents the discarded band: 9.7 % of samples vs 22.3 % measured.
- Never fires Mode C bypass; the real chamber hit duty 1.0 for 2.9 % of samples.

**Use this model for relative comparison between configurations. Do not quote
its absolute numbers as predictions.** The recommendation rests on a consistent
ranking across configs, not on the precise values.

## Before deploying

1. The bias is feedforward: it assumes the equilibrium duty is ~10 %. That was
   measured at 4.8 C in Uruguayan winter. If the chamber warms or the substrate
   changes, the true equilibrium moves and a fixed bias will shift the
   operating point. Re-measure the leak rate before trusting the number in a
   different season, and prefer under-biasing to over-biasing.
2. `test_scheduler_gap_keeps_current_mode` fails on this branch. It fails
   **identically at the pre-refactor commit** (verified via worktree), so it is
   pre-existing, not caused by this work.
3. The rclpy suite cannot run on elder-plops (Mint 21.2/jammy; Jazzy is
   noble-only) and must not run on fc1 (test nodes would join domain 69 with
   the live chamber). Use `docker/fc-core-test.Dockerfile`, always with
   `--network none`.
4. Separately: `test_camera.py` installs a mock `sensor_msgs` into
   `sys.modules` at collection time and never restores it, which breaks
   whole-directory pytest collection. Pre-existing; not fixed here. The test
   runner works around it by running one file per process.

## Files

- `timescale-26h-1min.csv` -- the source trace
- `src/chambers/fc-core/fc_core/sim/` -- chamber model, PWM/relay sim, replay harness
- `src/chambers/fc-core/fc_core/test/test_replay_fidelity.py` -- fidelity gate + fix evaluation
