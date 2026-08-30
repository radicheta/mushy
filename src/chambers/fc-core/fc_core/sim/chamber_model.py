"""Chamber humidity model as an absolute-moisture balance (MUSHY-60).

The prior model balanced RH percentage points per hour, which is NOT a
conserved quantity -- the same gram of water is a different number of RH
points at 3 C than at 20 C (see ``psychrometrics.absolute_humidity_g_m3``).
This version balances grams of water per cubic metre and derives RH from
temperature on read, so the moisture balance itself does not have to know
what temperature the chamber is at.

Fitted constants (MUSHY-136 refit of the MUSHY-60 identification, see
999.33-06-FIT-RESULTS.md):

    FITTED_Q = 0.553    # m3/h   [0.40, 0.68]
    FITTED_C = 2.77     # g/K    [2.56, 3.00]
    FITTED_F = 3.890    # g/h    = Q * (F/Q)

The balance is V*dAH/dt = F*u - Q*(AH_in - AH_out) + C*dT/dt. The third
term is the MUSHY-136 surface reservoir: the chamber air exchanges water
reversibly with wet walls, substrate and standing water as its temperature
moves, ~0.9x the saturation slope, so an idle chamber's absolute humidity
tracks the saturation curve at near-constant RH. The MUSHY-62 audit found
this term explains 83% of idle-window variance where the gradient leak
alone explained 10%, and that BOTH earlier Q estimates (0.96 and 1.9) were
measuring the cooling rate of the windows they selected. C is flat across
every quiet-band choice (2.75-2.90); Q still moves with the band
(0.39-0.73) but is now the minor term.

F/Q = 7.0337 (mean_gradient/mean_duty, independent of Q, of the lag and of
the band) remains the one quantity the live controller consumes, so F is
set as Q * (F/Q) rather than the regression's 4.35 [3.29, 5.36], exactly as
MUSHY-60 did. Driven replays (real temperature and ambient in, RH out) with
these values: 2026-08-08 RMSE 1.69 (was 4.58), held-out 2026-08-14 3.45
(was 10.54), held-out idle 2026-08-18 1.88 (was 4.09), held-out sigma-delta
night 2026-08-29 1.81 (was 8.93). See 999.33-10-MUSHY-136-VALIDATION.md.

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

    Steady-state behaviour is well identified (via the F/Q ratio, see
    module docstring). The transient response is now dominated by the
    surface term whenever chamber temperature is moving, and by V/Q
    (~10 h at the fitted Q, band-dependent) when it is not. Driven replays
    against recorded days land within 2-3.5 RH points RMSE; a
    constant-temperature synthetic run cannot exercise the surface term at
    all, so amplitude claims from such runs say little about the real
    chamber (see test_replay_fidelity.py).
    """

    moisture_loss_m3_per_h: float = 0.553   # fitted (MUSHY-136); see module docstring
    fill_g_per_h: float = 3.890             # Q * (F/Q); see module docstring
    dead_time_s: float = 360.0              # fitted: transport + mixing lag
    tau_s: float = 600.0                    # fitted: first-order mixing constant
    # MUSHY-136: reversible exchange with wet surfaces (walls, substrate,
    # standing water). Grams of water the chamber AIR gains per kelvin of
    # chamber warming, and loses per kelvin of cooling. 0.0 reproduces the
    # MUSHY-60 model exactly.
    # ponytail: linear in dT/dt, no RH-level dependence; fitted at 85-99% RH
    # on a chamber kept wet. A chamber pinned at 97% for a day drifts +1.8 pp
    # wet under this form -- upgrade to a relaxation toward a surface
    # equilibrium RH if that, or a dry chamber, ever matters.
    surface_g_per_k: float = 2.77           # fitted (MUSHY-136); see module docstring

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
