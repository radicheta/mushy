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
# Fit bounds are DELIBERATELY wider than the spec section 3 plausibility
# ranges (0.5x the low, 2x the high). Fitting inside the plausibility box makes
# a wild fit pin at the bound and land inside the box, so the guard's refusal
# could never fire; out here a wild fit stays visibly wild -- and if the median
# still sits on a bound, aggregate() rejects it as <param>_at_bound.
BOUNDS_LO = (0.5, 0.05, 2.5, 30.0)      # F, Q, dead_time, tau
BOUNDS_HI = (100.0, 10.0, 1800.0, 7200.0)
BOUND_KEYS = ('fill_g_per_h', 'moisture_loss_m3_per_h', 'dead_time_s', 'tau_s')
AT_BOUND_FRAC = 0.01


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
    """History without probe markers: a quasi window opens on any rising relay
    edge preceded by >= idle_s of OFF time. It no longer requires the rest of
    the window to stay quiet (MUSHY-138 ruling 12) -- ruling 9 already
    established that later background pulses inside the window are modelled
    input (fit_window simulates the actual delivered duty from the relay
    series), not contamination to reject on. Only the idle time BEFORE the
    edge still gates whether a window opens at all."""
    out, idle = [], idle_s   # assume the record starts already idle (unknown history)
    i = 0
    while i < len(relay):
        if relay[i] > 0.5:
            if idle >= idle_s:
                w = _slice(dt, rh, temp, ambient_ah, relay, i, pre_s, post_s)
                if w is not None:
                    out.append(w)
                while i < len(relay) and relay[i] > 0.5:
                    i += 1
                idle = 0.0
                continue
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


GRID_N = 12          # log-spaced dead-time grid over [BOUNDS_LO[2], BOUNDS_HI[2]]
THETA_IDX = 2


def fit_window(w: Window, base: ChamberParams) -> WindowFit:
    """Fit (F, Q, theta, tau) to one probe window.

    ``dead_time_s`` enters ChamberModel through a dt-quantised arrival queue,
    so the residual is a STEP function of theta: the default 1e-8 relative
    finite-difference step falls inside one step and reads a zero gradient,
    leaving theta pinned to whatever it started at (MUSHY-138 ruling 8). So
    theta is searched on a coarse log grid with the other three optimised at
    each point, then all four are polished with a difference step of at least
    2*dt in theta.
    """
    if max(w.temp) - min(w.temp) > MAX_TEMP_MOVE_C:
        return WindowFit(0, 0, 0, 0, 0, rejected='temp_moved')
    if not any(r > 0.5 for r in w.relay[w.probe_start_idx:]):
        return WindowFit(0, 0, 0, 0, 0, rejected='no_pulse')
    obs = np.asarray(w.rh)

    lo3 = (BOUNDS_LO[0], BOUNDS_LO[1], BOUNDS_LO[3])
    hi3 = (BOUNDS_HI[0], BOUNDS_HI[1], BOUNDS_HI[3])
    y0 = np.clip([base.fill_g_per_h, base.moisture_loss_m3_per_h, base.tau_s], lo3, hi3)

    def at_theta(theta):
        return least_squares(lambda y: _simulate([y[0], y[1], theta, y[2]], w, base) - obs,
                             # max_nfev is deliberately tight: an inner fit that stops
                             # short only affects this grid point's RANK, and the
                             # 4-parameter polish re-optimises from the winner anyway.
                             y0, bounds=(lo3, hi3), x_scale=y0, max_nfev=100)

    grid = sorted(set(np.geomspace(BOUNDS_LO[THETA_IDX], BOUNDS_HI[THETA_IDX], GRID_N))
                  | {float(np.clip(base.dead_time_s, BOUNDS_LO[THETA_IDX], BOUNDS_HI[THETA_IDX]))})
    coarse = min(((at_theta(t), t) for t in grid), key=lambda r: r[0].cost)
    r3, theta0 = coarse

    x0 = np.array([r3.x[0], r3.x[1], theta0, r3.x[2]])
    diff_step = np.full(4, 1.49e-8)
    diff_step[THETA_IDX] = max(2.0 * w.dt / theta0, 1e-3)
    res = least_squares(lambda x: _simulate(x, w, base) - obs, x0, bounds=(BOUNDS_LO, BOUNDS_HI),
                        x_scale=x0, max_nfev=200, diff_step=diff_step)
    if res.cost > r3.cost:                       # polish made it worse: keep the grid point
        res = r3
        f, q, tau = (float(v) for v in res.x)
        theta = theta0
    else:
        f, q, theta, tau = (float(v) for v in res.x)
    rmse = float(np.sqrt(np.mean(res.fun ** 2)))
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
    for i, k in enumerate(BOUND_KEYS):
        lo, hi = BOUNDS_LO[i], BOUNDS_HI[i]
        if not good or not (med[k] <= lo * (1 + AT_BOUND_FRAC) or med[k] >= hi * (1 - AT_BOUND_FRAC)):
            continue
        if k == 'dead_time_s' and med[k] <= lo * (1 + AT_BOUND_FRAC):
            # Ruling 15: dead time is NOT identifiable from busy closed-loop
            # windows -- most of them pin theta at whatever the low bound is
            # (7 of 11 in the two-twin sim; scoring residuals only after the
            # probe start, i.e. treating the pre-roll as warm-up, did not move
            # them). Hold the prior instead of shipping the bound: the fit
            # stays valid on F/Q, and theta waits for longer or quieter probes.
            med[k] = getattr(base, k)
            reasons.append('dead_time_held')
        else:
            reasons.append(f'{k}_at_bound')
    params = replace(base, **med)
    # 'dead_time_held' is a note, not a refusal: validity stays F/Q-based.
    blocking = [r for r in reasons if r != 'dead_time_held']
    return Aggregate(valid=not blocking, n=len(good), reasons=reasons, params=params, iqr=iqr,
                      median_temp_c=median(temps) if temps else float('nan'))
