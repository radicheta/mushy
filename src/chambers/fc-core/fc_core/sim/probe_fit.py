"""Fit ChamberModel to identification-probe windows (MUSHY-138).

A probe is one relay pulse of known length into a chamber that has been
idle for >= 15 min. Its step response identifies F and the dead time
directly and the decay after it identifies Q -- the joint (F, Q) fit that
scripts/fit-chamber-model.py documents as degenerate on passive data is
well-posed here because the input is known and isolated.

The forward model IS ChamberModel, so this proves the pipeline, not the
model class (spec section 6 caveat). Pure: takes in-memory series, no I/O.
"""
from dataclasses import dataclass, replace
from statistics import median
from typing import List

import numpy as np
from scipy.optimize import least_squares

from fc_core.sim.chamber_model import ChamberModel, ChamberParams
from fc_core.sim.pwm_window import pipe_delivery

PRE_S = 600.0
POST_S = 5400.0
MIN_WINDOWS = 5
MAX_IQR_RATIO = 0.5
MAX_TEMP_MOVE_C = 0.5
# spec section 3 plausibility ranges, used as fit bounds too
BOUNDS_LO = (1.0, 0.1, 5.0, 60.0)       # F, Q, dead_time, tau
BOUNDS_HI = (50.0, 5.0, 900.0, 3600.0)


@dataclass
class Window:
    dt: float
    rh: List[float]
    temp: List[float]
    ambient_ah: List[float]
    relay: List[float]
    probe_start_idx: int


@dataclass
class WindowFit:
    fill_g_per_h: float
    moisture_loss_m3_per_h: float
    dead_time_s: float
    tau_s: float
    rmse_pct: float
    rejected: str = ''


@dataclass
class Aggregate:
    valid: bool
    n: int
    reasons: List[str]
    params: ChamberParams
    iqr: dict
    median_temp_c: float


def delivered_from_relay(relay, dt, transit_s=6.0):
    out, elapsed = [], 0.0
    for r in relay:
        if r > 0.5:
            out.append(pipe_delivery(elapsed, transit_s, dt))
            elapsed += dt
        else:
            out.append(0.0)
            elapsed = 0.0
    return out


def _slice(dt, rh, temp, ambient_ah, relay, start_idx, pre_s, post_s):
    a = max(0, start_idx - int(pre_s / dt))
    b = start_idx + int(post_s / dt)
    if b > len(rh):
        return None
    return Window(dt=dt, rh=list(rh[a:b]), temp=list(temp[a:b]), ambient_ah=list(ambient_ah[a:b]),
                  relay=list(relay[a:b]), probe_start_idx=start_idx - a)


def find_windows(dt, rh, temp, ambient_ah, relay, probe, pre_s=PRE_S, post_s=POST_S):
    out = []
    for i in range(1, len(probe)):
        if probe[i] > 0.5 and probe[i - 1] <= 0.5:
            w = _slice(dt, rh, temp, ambient_ah, relay, i, pre_s, post_s)
            if w is not None:
                out.append(w)
    return out


def find_quasi_windows(dt, rh, temp, ambient_ah, relay, idle_s=900.0, pre_s=PRE_S, post_s=POST_S):
    """History without probe markers: relay OFF >= idle_s, then ONE pulse, then
    no relay activity for the rest of the window."""
    out, idle = [], idle_s   # assume the record starts already idle (unknown history)
    i = 0
    while i < len(relay):
        if relay[i] > 0.5:
            if idle >= idle_s:
                j = i
                while j < len(relay) and relay[j] > 0.5:
                    j += 1
                k = j
                quiet = True
                while k < len(relay) and (k - i) * dt < post_s:
                    if relay[k] > 0.5:
                        quiet = False
                        break
                    k += 1
                if quiet:
                    w = _slice(dt, rh, temp, ambient_ah, relay, i, pre_s, post_s)
                    if w is not None:
                        out.append(w)
                i = j
            idle = 0.0
        else:
            idle += dt
        i += 1
    return out


def _simulate(x, w: Window, base: ChamberParams):
    f, q, theta, tau = x
    p = replace(base, fill_g_per_h=f, moisture_loss_m3_per_h=q, dead_time_s=theta, tau_s=tau)
    ch = ChamberModel(p, rh0_pct=w.rh[0], temp_c=w.temp[0])
    delivered = delivered_from_relay(w.relay, w.dt)
    out = np.empty(len(w.rh))
    for i in range(len(w.rh)):
        out[i] = ch.rh
        ch.step(delivered[i], w.dt, w.ambient_ah[i], w.temp[i])
    return out


def fit_window(w: Window, base: ChamberParams) -> WindowFit:
    if max(w.temp) - min(w.temp) > MAX_TEMP_MOVE_C:
        return WindowFit(0, 0, 0, 0, 0, rejected='temp_moved')
    if not any(r > 0.5 for r in w.relay[w.probe_start_idx:]):
        return WindowFit(0, 0, 0, 0, 0, rejected='no_pulse')
    obs = np.asarray(w.rh)

    def run(dead_time_start):
        x0 = np.clip([base.fill_g_per_h, base.moisture_loss_m3_per_h, dead_time_start, base.tau_s],
                     BOUNDS_LO, BOUNDS_HI)
        return least_squares(lambda x: _simulate(x, w, base) - obs, x0,
                             bounds=(BOUNDS_LO, BOUNDS_HI), x_scale=x0, max_nfev=200)

    # two starts on dead_time_s: today's belief (360 s) can trap the optimiser
    # in a local minimum when the true dead time is much shorter (spec note).
    candidates = [run(base.dead_time_s), run(30.0)]
    res = min(candidates, key=lambda r: r.cost)
    rmse = float(np.sqrt(np.mean(res.fun ** 2)))
    f, q, theta, tau = (float(v) for v in res.x)
    return WindowFit(f, q, theta, tau, rmse)


def _iqr(vals):
    s = sorted(vals)
    n = len(s)
    return s[(3 * n) // 4] - s[n // 4]


def aggregate(fits: List[WindowFit], base: ChamberParams, temps: List[float]) -> Aggregate:
    good = [f for f in fits if not f.rejected]
    reasons = []
    if len(good) < MIN_WINDOWS:
        reasons.append(f'n<{MIN_WINDOWS}')
    cols = {
        'fill_g_per_h': [f.fill_g_per_h for f in good],
        'moisture_loss_m3_per_h': [f.moisture_loss_m3_per_h for f in good],
        'dead_time_s': [f.dead_time_s for f in good],
        'tau_s': [f.tau_s for f in good],
    }
    med = {k: (median(v) if v else getattr(base, k)) for k, v in cols.items()}
    iqr = {k: (_iqr(v) if len(v) >= 2 else float('inf')) for k, v in cols.items()}
    for k in ('fill_g_per_h', 'moisture_loss_m3_per_h'):
        if good and iqr[k] / max(med[k], 1e-9) >= MAX_IQR_RATIO:
            reasons.append(f'{k}_iqr')
    params = replace(base, **med)
    return Aggregate(valid=not reasons, n=len(good), reasons=reasons, params=params, iqr=iqr,
                      median_temp_c=median(temps) if temps else float('nan'))
