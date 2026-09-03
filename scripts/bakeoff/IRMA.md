# Irma: alice + a learned residual correction (MUSHY-150, decided 2026-09-03)

Santi's call after the frank post-mortem. Not built yet. This note exists
because Plane was unreachable when the decision was made; copy it into a
child work item of MUSHY-150 and delete this file.

## Why

Frank (free MLP with hidden state) fits TRAIN better than alice (0.037 vs
0.045 g/m3 on inter) and loses on TEST on both splits (inter 0.428 vs 0.404,
chrono 0.62 vs 0.53). Its early stop fires at step 99-400 of 3000 with
best-val anywhere from 0.18 to 0.93 across seeds. The shared lr 0.05 was
chosen for 4-parameter physics models initialised at the shipped answer and is
~10x too high for a tanh MLP started from persistence. A superset that loses
is a rigged setup. Frank did learn the one thing alice cannot: pulse response
+0.28 vs alice +0.06, measured +0.31 (pulse_response.py), so there is
something to find.

## Design

irma = alice's balance (F*u - Q*(AH - AH_amb) + C*dT/dt)/V  +  MLP(x)/V,
last layer zero-initialised so step 0 IS alice bit-for-bit.

* two optimiser groups: alice's F, Q, C, dead time at lr 0.05 as today;
  the net at lr 1e-3 with weight decay
* inputs, normalised as eve/frank do: AH-amb, AH-AHsat(T), T, dT/dt, applied
  duty, u_ew5, u_ew30, T-t_ew30. No hidden state in v1.
* score on inter + chrono, 5 seeds; then score_probe.py (open-loop probe
  days) and pulse_response.py
* alternative kept on record: frank trained properly (lr 1e-3, weight decay,
  longer patience). Irma preferred because the correction is one function
  you can plot against RH/T/relay and read off what alice lacks.

## Done when

Leaderboard entry on both splits with seeds, and either a documented no-gain
(the corpus cannot teach more) or a plotted correction plus a proposed
physics term for chamber_model.py.
