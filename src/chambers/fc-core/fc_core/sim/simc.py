"""SIMC gains from fitted chamber params, and the guard for pushing them (MUSHY-138).

Skogestad SIMC for a first-order-plus-dead-time plant:
    Kp = tau / (K (tau_c + theta)),  Ti = min(tau, 4 (tau_c + theta)),  Kd = Kp theta / 2
K is the steady-state RH gain per unit duty: F/Q in g/m3, converted to
%RH at the operating temperature. tau_c is the one preference knob
(desired closed-loop time constant); default tau_c = theta.
"""
from dataclasses import dataclass, replace
from typing import List, Optional

from fc_core.sim.chamber_model import ChamberParams
from fc_core.sim.control_loop import Gains
from fc_core.sim.psychrometrics import absolute_humidity_g_m3

RANGES = {
    'fill_g_per_h': (1.0, 50.0),
    'moisture_loss_m3_per_h': (0.1, 5.0),
    'dead_time_s': (5.0, 900.0),
    'tau_s': (60.0, 3600.0),
    'kp': (0.001, 2.0),
    'ki': (1e-6, 0.01),
}
FITTED = ('fill_g_per_h', 'moisture_loss_m3_per_h', 'dead_time_s', 'tau_s')


def plant_gain_pct_per_duty(params: ChamberParams, temp_c: float) -> float:
    return 100.0 * (params.fill_g_per_h / params.moisture_loss_m3_per_h) \
        / absolute_humidity_g_m3(temp_c, 100.0)


def simc_gains(params: ChamberParams, temp_c: float, tau_c_s: Optional[float] = None) -> Gains:
    theta, tau = params.dead_time_s, params.tau_s
    tau_c = theta if tau_c_s is None else tau_c_s
    k = plant_gain_pct_per_duty(params, temp_c)
    kp = tau / (k * (tau_c + theta))
    ti = min(tau, 4.0 * (tau_c + theta))
    return Gains(kp=kp, ki=kp / ti, kd=kp * theta / 2.0)


@dataclass
class Push:
    ok: bool
    reasons: List[str]
    clamped: List[str]
    params: ChamberParams
    gains: Gains


def guard(fit: ChamberParams, last_accepted: ChamberParams, temp_c: float,
          tau_c_s: Optional[float] = None, max_ratio: float = 2.0) -> Push:
    reasons, clamped, vals = [], [], {}
    for k in FITTED:
        v, prev = getattr(fit, k), getattr(last_accepted, k)
        lo, hi = RANGES[k]
        if not (lo <= v <= hi):
            reasons.append(f'{k}={v:.4g} outside [{lo}, {hi}]')
        # ponytail: ratchet instead of refuse, else a 7x-wrong dead time is stuck forever
        if prev > 0 and v > prev * max_ratio:
            v = prev * max_ratio
            clamped.append(k)
        elif prev > 0 and v < prev / max_ratio:
            v = prev / max_ratio
            clamped.append(k)
        vals[k] = v
    params = replace(last_accepted, **vals)
    gains = simc_gains(params, temp_c, tau_c_s)
    for k in ('kp', 'ki'):
        lo, hi = RANGES[k]
        g = getattr(gains, k)
        if not (lo <= g <= hi):
            reasons.append(f'{k}={g:.4g} outside [{lo}, {hi}]')
    return Push(ok=not reasons, reasons=reasons, clamped=clamped, params=params, gains=gains)
