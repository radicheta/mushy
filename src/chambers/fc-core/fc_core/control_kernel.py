"""Pure, ROS-free control-law kernel.

Lifted verbatim from ``fc_controller.py``'s error-projection block (fc1/prod
commits ``b4f18e4`` + ``30534ff``) so the offline simulator and the live
controller can never drift apart.

No rclpy, no clock reads, no parameter lookups. Everything is an argument.
"""
from dataclasses import dataclass

from fc_core.sim.chamber_model import ChamberParams
from fc_core.sim.psychrometrics import CHAMBER_VOLUME_M3, absolute_humidity_g_m3


@dataclass(frozen=True)
class BandSpec:
    """Resolved mode band. Fractions, not percent (0.885 == 88.5 %)."""

    band_low: float
    band_high: float
    defend_side: str    # 'low' | 'high' | 'both'

    @property
    def midpoint(self) -> float:
        return (self.band_low + self.band_high) / 2.0

    @property
    def half_width_pct(self) -> float:
        return (self.band_high - self.band_low) / 2.0 * 100.0


def project_error_pct(rh: float, band: BandSpec):
    """Band-aware error projection with the quadratic low-side feather.

    Returns the error in percentage points; negative drives duty up. Returns
    ``None`` for the ``defend_side='low'`` freeze case, which the caller must
    handle by publishing duty 0 and disengaging the PID.

    The feather ramps quadratically from 0 at the band MIDPOINT to -w/2 at
    ``band_low``, then continues linearly below the floor. The join at s == w
    is C1 (value and slope match) — that continuity is what removed the
    derivative kick that used to slam duty to 100 % at the floor.

    Anchored on the midpoint rather than ``mode.target`` on purpose: pinning's
    cosmetic target (0.85) sits below its band_low (0.90), so anchoring on
    target would zero the error exactly where the floor must be defended.
    """
    midpoint = band.midpoint
    w = band.half_width_pct

    if rh < midpoint:
        s = (midpoint - rh) * 100.0          # pct below midpoint, > 0
        if w > 0 and s <= w:
            return -(s * s) / (2.0 * w)      # quadratic feather
        return -(s - w / 2.0)                # linear, C1 with the feather

    if rh > band.band_high:
        if band.defend_side in ('high', 'both'):
            return (rh - band.band_high) * 100.0
        return None                          # defend_side='low': freeze

    return 0.0                               # upper half of band: no forcing


def duty_bias_factor(rh: float, band: BandSpec) -> float:
    """Scale for the feedforward duty bias, in [0, 1] (MUSHY-57).

    The bias is added AFTER the PID's own (0, 1) clamp, so a flat bias would
    become the minimum commandable duty: the humidifier could never turn off,
    and it can only add moisture. On a high-ambient day the chamber's true
    standing demand is zero, and a floored duty walks RH up without limit.

    So the bias fades: full below the band MIDPOINT, where the feather zeroes
    the error and the standing duty is what holds station, then linearly to 0
    at ``band_high``. Continuous at the midpoint on purpose -- a hard gate
    would inject a bias-sized step into commanded duty on every midpoint
    crossing, landing in the PWM min-pulse discard zone that drove the original
    limit cycle.
    """
    if rh >= band.band_high:
        return 0.0                           # incl. the zero-width band case
    if rh <= band.midpoint:
        return 1.0
    return (band.band_high - rh) / (band.band_high - band.midpoint)


class TempRateEstimator:
    """Filtered chamber-temperature rate, deg C per hour (MUSHY-125).

    First-order low-pass on temperature; the rate is the filter's own error
    term, (T - T_filt) / tau. A 0.01 C sensor quantum at 1 Hz would read as
    36 C/h raw; through a 600 s filter it is 0.06 C/h and decays away. The
    lag is deliberate and small against the plant (360 s dead time, 600 s
    mixing) and against a dawn ramp that lasts hours.
    """

    def __init__(self, tau_s: float = 600.0):
        self.tau_s = tau_s
        self._filt = None

    def update(self, temp_c: float, dt: float) -> float:
        if self._filt is None or dt <= 0.0:
            self._filt = temp_c
            return 0.0
        alpha = dt / (self.tau_s + dt)
        self._filt += alpha * (temp_c - self._filt)
        return (temp_c - self._filt) / self.tau_s * 3600.0


def temp_feedforward_gain(rh: float, temp_c: float) -> float:
    """Duty per (C/h) of chamber warming needed to hold RH (MUSHY-125).

    (rh * V * dAH_sat/dT - C) / F: the water the air must gain per kelvin
    to keep RH fixed, minus what wet surfaces re-evaporate on their own
    (MUSHY-136, C = 2.77 g/K, ~0.9x the saturation slope at 10 C), over
    the humidifier's fill rate. Strongly temperature dependent -- the
    saturation slope roughly doubles between 10 and 20 C -- so at ~4 C the
    surfaces over-supply and the sign flips, while at 16 C it is ~0.4.
    That is why this is a function and not a tuned constant.
    """
    slope = (absolute_humidity_g_m3(temp_c + 0.5, 100.0)
             - absolute_humidity_g_m3(temp_c - 0.5, 100.0))          # g/m3 per K
    p = ChamberParams()
    return (rh * CHAMBER_VOLUME_M3 * slope - p.surface_g_per_k) / p.fill_g_per_h


def temp_feedforward_duty(trim: float, rate_c_per_h: float, rh: float, temp_c: float,
                          band: BandSpec) -> float:
    """Duty to add for a temperature ramp (MUSHY-125), before the final clamp.

    A warming chamber's saturation pressure runs away from a water content
    that has not changed; the PID only sees the RH error after it opens,
    while dT/dt is locally sensed and arrives first. ``trim`` scales the
    model-derived gain (1.0 = trust the model, 0.0 = off) and is the one
    knob to calibrate on the real chamber. Negative on cooling for the same
    physics in reverse. Faded with ``duty_bias_factor`` so a chamber already
    above the band is never pushed wetter by a ramp.
    """
    if trim == 0.0:
        return 0.0
    return (trim * temp_feedforward_gain(rh, temp_c) * rate_c_per_h
            * duty_bias_factor(rh, band))
