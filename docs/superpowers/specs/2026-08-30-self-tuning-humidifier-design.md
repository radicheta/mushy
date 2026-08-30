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
- `band.midpoint <= rh <= band.band_high - 0.005`
- `|dT/dt| < 0.3 C/h` from the existing `TempRateEstimator`
- relay has been OFF for >= 15 min (from the driver's last edge)
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

**Marker.** New topic `fc1/control/probe`, `std_msgs/Float32`,
TRANSIENT_LOCAL, value 1.0 while the probe is commanded, 0.0 otherwise.
Bridge subscribes and stores it as `fc.probe`, copying the
`humidity_target` block at `src/mission-control/bridge/src/index.js:981`.

**Abort.** Duty -> 0 and marker -> 0 if RH crosses `band_high` or the
staleness guard trips mid-probe.

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
- reject the window if the temperature moved > 0.5 C or the relay fired
  again inside the decay

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
- no value moved more than 2x since the last *accepted* fit
- fit is valid (section 2)

If any check fails: write the report, exit non-zero, push nothing. The
cron's failure is visible the same way other elder-plops timers are.

If all pass: `ssh fc1 ros2-cmd param set` each value (runtime params are
already supported and persist until reboot), then edit `fc_config.yaml`
and commit to `main` with the report path in the message. Deploy to the
Pi stays a human action; the human no longer chooses the numbers.

## 4. Proving it before it touches the chamber

In order; each step gates the next.

1. **Twin round-trip.** Generate probe windows from `ChamberModel` with
   known (F, Q, theta, tau) plus sensor noise; the fitter must recover
   them within the IQR it reports. This is the fitter's one test.
2. **History as quasi-probes.** Run the fitter over the last month with
   "relay OFF >= 15 min, then a single pulse" transitions standing in for
   probe markers. Output is a first real answer on theta = 50 vs 360 s and
   a shakedown of the Timescale path. Nothing is pushed.
3. **Probes on, push off.** Deploy the controller change with
   `probe_interval_h: 12`. Watch two days of probes on Mission Control
   (marker, relay edges, RH response). Run the fitter by hand.
4. **Push on.** Enable the cron. First accepted fit gets a human read of
   the report before the yaml commit is deployed.

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
- `scripts/fit-probes.py`, `scripts/push-chamber-params.py`, one
  systemd timer on elder-plops
- `scripts/fit-chamber-model.py`: unchanged except that its loaders are
  importable
