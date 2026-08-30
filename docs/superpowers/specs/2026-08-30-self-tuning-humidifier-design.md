# Self-tuning humidifier control: probe on the Pi, fit off-Pi

Ticket: MUSHY-138. Date: 2026-08-30.

## Problem

One chamber, two parameter sets, a human in between.

- Controller knobs in `src/chambers/fc-core/config/fc_config.yaml`:
  `pid_kp`, `pid_ki`, `pid_kd`, `humidifier_temp_feedforward`,
  `humidifier_duty_bias`.
- Twin knobs in `fc_core/sim/chamber_model.py` (`ChamberParams`):
  `fill_g_per_h` (F), `FITTED_Q` (Q), `surface_g_per_k` (C),
  `dead_time_s`, `tau_s`.

Every twin refit re-derives gains by hand; every live gain tweak leaves the
twin stale. MUSHY-62/65/125/136 are laps of that circle.

Two facts make it structural, not a tuning problem:

1. Passive identification is degenerate. `scripts/fit-chamber-model.py`
   documents that F and Q trade off when fitted jointly, that Q is
   regime-dependent (1.3-1.8 in the first ~40 min after the relay drops,
   ~0.2 beyond 2 h), and that F/Q is the only well-identified quantity.
2. The gains and the twin already disagree by an order of magnitude. The
   gains were derived by SIMC on 2026-04-11 for dead time L = 16 s and
   tau_c = 3L = 48 s (`.planning/milestones/v1.5-phases/27-.../27-RESEARCH.md`),
   then hand-nudged. The twin now says dead time 360 s, tau 600 s. Against
   the twin, the running gains (kp 0.36, ki 0.001) imply tau_c ~ -300 s from
   Kp and from Ki independently; SIMC at tau_c = theta would give kp ~ 0.015,
   ki ~ 0.00003. The 2026-04 calibration trace (36 s pulse -> 0.13 %RH, peak
   at +50 s, `docs/pid_calibration_notes.md:85`) says the 16 s side may be
   closer to right. Nobody knows. A probe measures it.

## Decision

Santi, 2026-08-30: small in-band probes on the live chamber are acceptable
and welcome ("builds character").

Option chosen: **probe on the Pi, fit off-Pi on a timer.** Rejected: a
recursive estimator on the Pi (new code on the critical path, fits nobody
eyeballs), end-to-end RL (inherits every twin error), MPC (deferred; can sit
on top of the identified model later).

Goal state: the twin is the single source of truth, its fit is live, and
the only human-tuned knobs are preferences (band, probe cadence, `tau_c`),
not physics.

## 1. Probe (Pi, `fc_controller.py`)

A probe is one commanded pulse of known length into a quiet chamber. Its
step response gives F and dead time directly; the decay after it gives Q.

**Trigger.** All of the following, evaluated each control tick:

- active mode is `fruiting` or `pinning`
- `band.band_low <= rh <= band.band_high - 0.005`
- `|dT/dt| < 0.3 C/h` from the existing `TempRateEstimator`
- commanded duty has been below 0.5 for >= 15 min (not in crash recovery); the relay may be pulsing at its standing duty
- sensors fresh (the existing staleness guard is not tripped), not Mode C
- >= `probe_interval_h` since the last probe (monotonic clock; a reboot
  resets the timer, which is fine)

**Action.** Command duty = 1.0 for `probe_seconds`, PID integrator frozen
(same mechanism the staleness guard uses to disengage). The sigma-delta
driver fires once 30 s of demand is banked, so relay-ON starts up to 30 s
after the command; that is why timing is taken from the stored relay
edges (`fc.humidifier`), not from the command. After the pulse, normal
control resumes; RH sits in the upper half of the band where
`project_error_pct` returns 0, so the decay is a natural idle window.

The probe is superposed on the driver's background pulse train; the fitter
simulates the actual delivered duty from the stored relay edges, so that
background is known input, not contamination. A well-tuned loop holds station
just below the band midpoint with a continuous standing duty, which is why
neither a midpoint nor a quiet-relay requirement is workable (Ruling 9).

**Marker.** New topic `fc1/control/probe`, `std_msgs/Float32`,
TRANSIENT_LOCAL, value 1.0 while the probe is commanded, 0.0 otherwise.
Bridge subscribes and stores it as `fc.probe`, copying the
`humidity_target` block at `src/mission-control/bridge/src/index.js:981`.

**Abort.** Duty -> 0 and marker -> 0 if RH crosses `band_high` or the
staleness guard trips mid-probe.

**Where it lives.** The probe state machine (trigger evaluation, pulse
countdown, abort) is a pure class in `control_kernel.py` and is stepped
from `sim/control_loop.py:ControlLoop` exactly as it is from
`fc_controller.py`, so the simulator runs the same probe logic as the Pi
(section 6 depends on this). `fc_controller` only supplies the inputs
(relay-idle time from the driver, staleness, mode) and publishes the
marker. The probe interval is measured from the end of the previous probe.

**Knobs (yaml).** `probe_seconds` (default 150; a 36 s pulse measured
0.13 %RH, so 150 s is ~0.5 %RH, above the 0.1 %RH sensor noise and inside
the +/-1.5 %RH fruiting band), `probe_interval_h` (default 0 = disabled;
set to 12 on fc1 once the fitter is proven, section 4).

## 2. Fitter (off-Pi, `scripts/fit-probes.py`, cron on elder-plops)

For each `fc.probe` rising edge in the last 14 days:

- pull [-10 min, +90 min] of `fc.temperature`, `fc.humidity`,
  `fc.humidifier` (relay edges) from Timescale, reusing `psql()`,
  `load_temp_rh()` and `load_relay_duty()` from `fit-chamber-model.py`
  (import them; do not copy)
- reconstruct delivered duty from the relay edges (the existing
  time-weighted hold logic)
- fit `fc_core.sim.chamber_model.ChamberModel` run forward on that duty
  to the observed RH with `scipy.optimize.least_squares` over
  (F, Q, dead_time_s, tau_s); C held at the current `surface_g_per_k`
  (it only acts on temperature ramps, which the trigger excludes)
- Dead time is searched on a ~12-point log grid over [5, 900] s with (F, Q, tau)
  fitted at each point, then all four are refined from the best grid point; a
  direct 4-parameter fit cannot move the dead time because ChamberModel quantises
  the delay to the sample interval (Ruling 8).
- reject the window if the temperature moved > 0.5 C; further relay pulses inside
  the decay are allowed and modelled

Aggregate across probes: median per parameter, IQR as the spread. A fit is
**valid** only if >= 5 windows survived and IQR/median < 0.5 for F and Q.

Output: `reports/fit-probes/<date>.json` with per-probe fits, the
aggregate, validity, and the proposed `ChamberParams`. Never touches the
control path by itself.

## 3. Derivation and push (`scripts/push-chamber-params.py`, same cron)

Given a valid fit:

- `K` = (F/Q) g/m3 per unit duty, converted to %RH per unit duty at the
  median chamber temperature over the probes
  (`100 * (F/Q) / absolute_humidity_g_m3(T, 100)`)
- SIMC on FOPDT: `Kp = tau_s / (K * (tau_c + theta))`,
  `Ti = min(tau_s, 4 * (tau_c + theta))`, `Ki = Kp / Ti`,
  `Kd = Kp * theta / 2`, with `theta = dead_time_s`
- `tau_c` is a yaml preference, `pid_simc_tau_c_seconds`, default =
  fitted `theta`
- the temperature feedforward gain already derives from `ChamberParams`
  in `control_kernel.temp_feedforward_gain`; `fill_g_per_h` and
  `surface_g_per_k` become declared ROS parameters on `fc_controller`
  and the kernel takes them as arguments instead of `ChamberParams()`

Guardrails, all checked before anything is pushed:

- every value inside a plausibility range (F 1-50 g/h, Q 0.1-5 m3/h,
  dead_time 5-900 s, tau 60-3600 s, kp 0.001-2, ki 1e-6-0.01)
- a value that moved more than 2x since the last *accepted* fit is CLAMPED to the
  2x bound (ratchet) and reported; plausibility violations still refuse
- fit is valid (section 2)

If the fit is invalid or a plausibility check fails: write the report, exit 3, push nothing.
A crash (no telemetry rows, DB unreachable) exits 1 so the timer unit shows failed instead of
looking like a routine invalid fit. The cron's failure is visible the same way other
elder-plops timers are.

If all pass: `ssh fc1 ros2-cmd param set` each value (runtime params are
already supported and persist until reboot), then edit `fc_config.yaml`
and commit to `main` with the report path in the message. Deploy to the
Pi stays a human action; the human no longer chooses the numbers.

## 4. Proving it before it touches the chamber

In order; each step gates the next.

1. **Two-twin convergence** (section 6). The whole loop, in simulation,
   must tune twin A's parameters onto twin B's.
2. **History as quasi-probes.** Run the fitter over the last month with
   "relay OFF >= 15 min, then a single pulse" transitions standing in for
   probe markers. Output is a first real answer on theta = 50 vs 360 s and
   a shakedown of the Timescale path. Nothing is pushed.
   Result 2026-08-30: 60 days of history, 40 candidate windows, 31 rejected for
   temperature movement, 9 fitted; F 7.94 g/h (IQR 6.19), Q 1.01 m3/h (IQR 1.34),
   dead time 33 s, tau 61 s; INVALID by the IQR gate, push refused. Inconclusive;
   the first accepted fit waits for deployed probes. Hints only: F/Q ~ 7.9 is
   consistent with today's standing duty, and dead time lands on the short side,
   not 360 s.
3. **Probes on, push off.** Deploy the controller change with
   `probe_interval_h: 12`. Watch two days of probes on Mission Control
   (marker, relay edges, RH response). Run the fitter by hand.
4. **Push on.** Enable the cron. First accepted fit gets a human read of
   the report before the yaml commit is deployed.

## 6. Two-twin convergence test (Santi, 2026-08-30)

The end-to-end test of the design, run entirely in simulation before any
of it reaches fc1. Two instances of `ChamberModel` with different
parameters:

- **B, the "real" chamber**: hidden parameters, e.g. F 2x, Q 0.7x,
  dead_time 50 s, tau 400 s relative to today's `ChamberParams`. Plays
  the plant inside `run_closed_loop`, on the sigma-delta driver
  simulator, driven by the recorded ambient/temperature fixture.
- **A, the controller's belief**: today's `ChamberParams`. SIMC gains and
  the feedforward gain are derived from A and given to `ControlLoop`.

Loop, N rounds of simulated days:

1. run `run_closed_loop` for D simulated days with the probe enabled;
   record the trace (RH, T, delivered duty, relay edges, probe marker)
2. run the fitter on that trace (the fitter takes in-memory series; the
   Timescale loaders are one adapter in front of it, so the same fitting
   code runs on sim and on prod)
3. run the push step in-process: guardrails, SIMC derivation, new gains
   and `ChamberParams` into `ControlLoop`
4. repeat

Pass criteria:

- after the rounds, A's (F, Q, dead_time, tau) are within the fitter's
  reported IQR of B's, and within 20 % of B's absolute
- the closed-loop metrics from `_metrics` (in-band fraction, relay
  cycles) in the last round are no worse than a run that used B's true
  parameters from the start
- the guardrails held every round (no pushed value outside plausibility,
  no > 2x step)

Also run with A = B to confirm the probe does not degrade a chamber that
is already right (in-band fraction unchanged, probes counted).

Caveat written down so nobody over-reads a pass: the fitter's forward
model IS `ChamberModel`, so this proves the pipeline, not that the model
class matches the real chamber. Step 2 of section 4 (last month's
history as quasi-probes) is where model adequacy first gets tested.
Add sensor quantisation (0.01 %RH) and noise (0.1 %RH) to B's output so
the fit is not trivially exact.

Result 2026-08-30: after 5 rounds, F +0.1%, Q +0.7%, dead time -16%, tau +2.3% vs B;
in-band fraction 1.000 = oracle; kp 1.22x oracle; 3.7 probes/day, 0 aborted; test runs
~4 min.

## 5. Not built

No on-Pi estimator, no MPC, no learned feedforward. The feather,
sigma-delta driver, duty cap, staleness guard, Mode C, and modes are
unchanged and remain the safety envelope outside the learned part.
`humidifier_duty_bias` and `humidifier_temp_feedforward` stay as knobs;
once the model is right the trim should sit at 1.0 and the bias should be
redundant with it. Retiring them is a follow-up ticket, not this one.

## Files touched

- `src/chambers/fc-core/fc_core/fc_controller.py`: probe trigger, marker
  publisher, integrator freeze, three new params
- `src/chambers/fc-core/fc_core/control_kernel.py`: `temp_feedforward_gain`
  takes F and C as arguments
- `src/chambers/fc-core/config/fc_config.yaml`: `probe_seconds`,
  `probe_interval_h`, `pid_simc_tau_c_seconds`, `fill_g_per_h`,
  `surface_g_per_k`
- `src/mission-control/bridge/src/index.js`: `fc.probe` subscription
- `src/chambers/fc-core/fc_core/sim/control_loop.py`: steps the probe
- `scripts/self-tune/fit-probes.py`, `scripts/self-tune/push-chamber-params.py`,
  `reports/self-tune/`, one systemd timer on elder-plops; both scripts import
  their core from a `fc_core.sim` module so the two-twin test can call it in-process
- `src/chambers/fc-core/fc_core/test/test_two_twin_convergence.py`
- `scripts/fit-chamber-model.py`: unchanged except that its loaders are
  importable

## 7. Amendments from implementation (2026-08-30)

Rulings and design notes recorded in implementation:

- Ruling 4: idle gate criterion is commanded duty below a threshold, not relay
  OFF time. Dead-time measurement requires a transition from sustained idle to
  commanded pulse, and the fitter detects that on duty edges.
- Ruling 8: dead_time is not jointly optimizable with (F, Q, tau) because
  ChamberModel quantises delay to the sample interval. Grid search on [5, 900] s
  with (F, Q, tau) refined at each point solves it.
- Ruling 9: a well-tuned loop holds station just below band.midpoint with
  continuous standing duty. Neither band.midpoint as a trigger gate nor a
  quiet-relay requirement is workable because background pulses are always
  present.
- Ruling 11: single isolated pulses are poor data for dead-time identification.
  Closed-loop windows with background pulses fit better because the model can
  reason about the combined input (commanded pulse plus background duty).
- Ruling 12: quasi-probe windows (history as probes) require a quiet period
  BEFORE the pulse window only, not after; the decay is inference-rich and
  including post-decay periods adds noise.
- Ruling 13: report JSON uses null for invalid fits and plausibility-rejected
  values.
- Deviation from guard spec: a value that violates the 2x threshold is CLAMPED
  to the bound and reported (ratchet logic). Plausibility violations still refuse
  the entire fit.
- Mid-probe parameter-change abort: if `probe_seconds` or `probe_interval_h`
  change live while a probe is active, the probe aborts cleanly (duty -> 0,
  marker -> 0).
- scipy is an exec_depend, used only by `fc_core.sim.probe_fit` and `simc`,
  never on the Pi's controller path.
- Deviation from section 2: `fit-probes.py` imports only `psql()`/`parse_epoch()`
  from `fit-chamber-model.py` and uses its own `load()`/`resample()` at 10 s
  resolution instead of the per-minute loaders (the probe needs sub-minute
  timing).
- The nightly wrapper captures the fitter's exit status directly (`set +e; ...;
  rc=$?`); `if ! cmd; then rc=$?` captures the NEGATED status, so every crash
  read as "exit 0" and the timer never failed.
- Dry run is the default and `SELF_TUNE_PUSH=1` opts into a real push (the unit
  carries it commented out), so a hand run of the wrapper on elder-plops -- which
  is also production -- cannot touch fc1.
- The five `param set` calls go over ONE ssh chained with `&&`, then `pid_kp` is
  read back and must match to 1e-6 before the yaml is edited; values serialise
  with `repr(float(v))` because a double param set from an int literal has
  crashed the controller before (decay_tau, 2026-06-28). The yaml commit also
  requires HEAD == main and a working tree holding only the two target files.
- Fit bounds in `probe_fit` are 0.5x/2x the section 3 plausibility ranges. Fitting
  inside the plausibility box let a wild fit pin at a bound and land inside the
  box, making the guard's refusal unreachable; a median still sitting within 1 %
  of a bound is now rejected as `<param>_at_bound`.
- Ruling 15: dead time is NOT identifiable from busy closed-loop windows. 7 of
  11 two-twin windows pin theta at whatever the low fit bound is (2.5 s now;
  5.0 s under the old bounds, which was also the plausibility floor -- so the
  guard accepted the bound and the section 6 "dead time -16 %" result was the
  2x ratchet walking the belief 360 -> 45 s, not identification). Treating the
  pre-roll as warm-up (residuals scored only from `probe_start_idx`, theta
  capped at the warm-up length) was tried and did NOT move the pinned windows,
  so it was reverted. `aggregate` now holds the prior dead time when the median
  sits at the low bound and reports `dead_time_held`, which is a note and does
  not invalidate the fit (validity stays F/Q-based). Theta waits for longer or
  quieter probes. F, Q and tau still converge (F/Q/tau within 20 % of the hidden
  twin; in-band fraction and kp within the oracle bounds).
- An in-flight probe is aborted (marker 0, PID re-engaged on the pre-probe duty)
  by a force experiment, the staleness guard, and a missing reading, not only by
  a live parameter change. During a probe the controller republishes
  `humidity_target` and `pid_output` so Mission Control has no 150 s hole.
