"""Pure, ROS-free control-law kernel.

Lifted verbatim from ``fc_controller.py``'s error-projection block (fc1/prod
commits ``b4f18e4`` + ``30534ff``) so the offline simulator and the live
controller can never drift apart.

No rclpy, no clock reads, no parameter lookups. Everything is an argument.
"""
from dataclasses import dataclass


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
