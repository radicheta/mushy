"""Chamber humidity model as an absolute-moisture balance (MUSHY-60).

The prior model balanced RH percentage points per hour, which is NOT a
conserved quantity -- the same gram of water is a different number of RH
points at 3 C than at 20 C (see ``psychrometrics.absolute_humidity_g_m3``).
This version balances grams of water per cubic metre and derives RH from
temperature on read, so the moisture balance itself does not have to know
what temperature the chamber is at.

Fitted constants (Task 2, see 999.33-06-FIT-RESULTS.md):

    FITTED_Q = 0.9634   # m3/h
    FITTED_F = 6.776    # g/h

Task 2's identification found that the only WELL-IDENTIFIED quantity is the
ratio F/Q = 7.0337 (computed independently as mean_gradient/mean_duty, so it
does not depend on Q, on the lag model, or on the quiet-band choice). The
branch's own band sweep gives Q in [0.658, 1.242] -- -32% / +29% of the
shipped 0.9634, a 1.9x span top-to-bottom -- and F in [5.8, 8.3] g/h, -14% /
+23% of the shipped 6.776. F is therefore set as Q * (F/Q) = 0.9634 * 7.0337
= 6.776 -- NOT the fit's headline 7.11 -- so that the model's steady-state
behaviour matches the identified ratio exactly. Using 7.11 instead would put
steady-state duty 5% off the one number we actually trust. This is a
deliberate decision.

Why F/Q, and not some other combination: equilibrium_duty() below is
Q * gradient / F = gradient / (F/Q) -- Q cancels out of it entirely. Verified
numerically: the feedforward bias comes out to 0.0999 at Q = 0.658, 0.963,
and 1.242 alike, unchanged across the whole swept band. The one number the
live controller actually consumes therefore depends only on F/Q, the one
quantity that is well identified, and is insensitive to the band choice that
dominates every other uncertainty in this module. That is the real
justification for this parameterisation.

WHAT THIS MODEL CANNOT SUPPORT:

* Season-independence is UNPROVEN. The fit window (2026-04-11 to 2026-08-08)
  is austral autumn/winter. A ratio bootstrap fails to reject
  season-independence but cannot exclude a ~+/-35% seasonal difference.
  Solar gain on an uninsulated steel container is unmodelled, so this will
  extrapolate poorly into summer for a PHYSICAL reason, not a curve-fitting
  one.
* Q, F and F/Q are unsaturated-regime values. 10,645 saturated minutes
  (chamber RH >= 99.99, sensor membrane saturation) were excluded from the
  fit per the farmer's 2026-08-09 ruling. Those are the WETTEST hours and
  therefore the largest gradients, so excluding them biases mean_gradient --
  and hence F/Q -- downward.
* Ambient comes from a reanalysis grid cell ~4 km away (MUSHY-64 fixture),
  not from the chamber envelope. This sets a floor on achievable fidelity.
  MUSHY-67 is the eventual upgrade.
* ``fc.humidity`` silently mixes two sensors (SHT30 with SCD41 fallback)
  that disagree by ~4.6 RH points, and the provenance is dropped at the
  storage boundary. This bounds how much of any residual is model error
  versus sensor artifact. MUSHY-71.
* There is no condensation ceiling. The model clamps only AH >= 0; it has
  no saturation sink, and the real chamber condenses on cold steel walls. At
  default parameters the closed loop stays 87-92% RH so nothing surfaces,
  but a replay of recorded data containing saturated stretches could
  integrate past RH 100 with no sink -- and the divergence would look like a
  control-law finding rather than a missing physical term. Relevant to
  MUSHY-59.
"""
from collections import deque
from dataclasses import dataclass
from typing import Optional

from fc_core.sim.psychrometrics import CHAMBER_VOLUME_M3, absolute_humidity_g_m3, relative_humidity_pct


@dataclass
class ChamberParams:
    """Moisture-balance coefficients for FC-1. Fitted, not derived.

    ``moisture_loss_m3_per_h`` is NOT a physical air-exchange rate, despite
    that being the least-bad available name for the coefficient's units. It
    is an EFFECTIVE MOISTURE-LOSS COEFFICIENT that lumps together
    infiltration, condensation on cold steel walls, substrate exchange, AND
    an unrecorded ~15 min/hour vent fan. Do not present it to anyone as a
    real air-exchange rate. It was fitted at ~25% vent duty -- if the vent
    schedule changes, this value is wrong and needs refitting.

    ``fill_g_per_h`` is an aggregate ~50x below the misting head's ~360 g/h
    nameplate output, because most emitted water lands in the substrate
    rather than the air. See MUSHY-68.

    Together, steady-state behaviour is well identified (via the F/Q ratio,
    see module docstring); the TRANSIENT response carries a much larger
    uncertainty from the band choice than steady state does, because the
    response time is set by V/Q and the branch's own sweep puts V/Q in
    [4.64 h, 8.75 h] -- not a factor-1.2 band. This simulator is for
    RELATIVE comparison between control configurations, not absolute
    prediction.
    """

    moisture_loss_m3_per_h: float = 0.9634  # fitted (Task 2); see class docstring
    fill_g_per_h: float = 6.776             # fitted (Task 2); see class docstring
    dead_time_s: float = 360.0              # fitted: transport + mixing lag
    tau_s: float = 600.0                    # fitted: first-order mixing constant
    # AUDIT MOCK-UP (MUSHY-62): reversible surface reservoir. Grams of water
    # the chamber air gains per kelvin of chamber warming (loses on cooling).
    # 0.0 = the shipped model.
    surface_g_per_k: float = 0.0

    def equilibrium_duty(self, ah_in_g_m3: float, ah_out_g_m3: float) -> float:
        """Delivered duty that exactly cancels the loss for a given
        inside/outside absolute-humidity gradient. Clamped to [0, 1]."""
        if self.fill_g_per_h <= 0.0:
            return 0.0
        return max(0.0, min(1.0,
                            self.moisture_loss_m3_per_h * (ah_in_g_m3 - ah_out_g_m3)
                            / self.fill_g_per_h))


class ChamberModel:
    """Delayed first-order absolute-moisture response to delivered duty.

    ``delivered_duty`` means vapour actually leaving the outlet. The PWM
    simulator subtracts pipe transit loss before calling this -- do not apply
    that loss twice.
    """

    def __init__(self, params: ChamberParams, rh0_pct: float, temp_c: float):
        self.p = params
        self.temp_c = float(temp_c)
        self._ah = absolute_humidity_g_m3(self.temp_c, rh0_pct)
        self._now_s = 0.0
        self._applied = 0.0                 # duty after mixing lag
        self._emerged = 0.0                 # duty that has cleared the dead time
        self._queue: deque = deque()        # (arrival_time_s, duty)

    @property
    def rh(self) -> float:
        return relative_humidity_pct(self.temp_c, self._ah)

    @property
    def ah(self) -> float:
        return self._ah

    def step(self, delivered_duty: float, dt_s: float, ambient_ah_g_m3: float,
             temp_c: Optional[float] = None) -> float:
        d_temp = 0.0
        if temp_c is not None:
            d_temp = float(temp_c) - self.temp_c
            self.temp_c = float(temp_c)
        self._now_s += dt_s

        # Transport delay: duty commanded now takes effect dead_time_s later.
        self._queue.append((self._now_s + self.p.dead_time_s, float(delivered_duty)))
        while self._queue and self._queue[0][0] <= self._now_s:
            _, self._emerged = self._queue.popleft()

        # First-order mixing toward whatever has emerged from the delay.
        alpha = min(1.0, dt_s / max(self.p.tau_s, 1e-9))
        self._applied += alpha * (self._emerged - self._applied)

        dah_dt = (self.p.fill_g_per_h * self._applied
                  - self.p.moisture_loss_m3_per_h * (self._ah - ambient_ah_g_m3)
                  ) / CHAMBER_VOLUME_M3          # g/m3 per hour
        self._ah = max(0.0, self._ah + dah_dt * (dt_s / 3600.0)
                       + self.p.surface_g_per_k * d_temp / CHAMBER_VOLUME_M3)
        return self.rh
