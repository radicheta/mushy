"""Empirically-fitted first-order-plus-dead-time model of FC-1's humidity.

Parameters are fitted to the 2026-08-08 26 h trace, NOT derived from air mass.

Why not first principles: the prior 999.33 plan specified ``air_mass_kg=7.0``
and ``mister_rate_g_per_min=6.0``. At 4.8 C the chamber's 5.76 m3 holds only
~38 g of water at saturation, so 1 pct RH is ~0.38 g and 6 g/min would move RH
at roughly 950 pts/h. Measured rise is 22.5 pts/h -- off by a factor of ~40.
The missing capacitance is the substrate: a fruiting chamber full of wet blocks
is a moisture buffer orders of magnitude larger than its air volume. Rather
than model the substrate explicitly, fit the aggregate response.
"""
from collections import deque
from dataclasses import dataclass


@dataclass
class ChamberParams:
    """All rates in RH percentage points per hour. Measured unless noted."""

    fill_pts_per_hour: float = 22.5     # measured: gross rise at delivered duty 1.0
    leak_pts_per_hour: float = 2.24     # measured: fall at delivered duty 0
    dead_time_s: float = 360.0          # fitted: transport + mixing lag
    tau_s: float = 600.0                # fitted: first-order mixing constant

    @property
    def equilibrium_duty(self) -> float:
        """Delivered duty that exactly cancels the leak (~0.10 for FC-1)."""
        return self.leak_pts_per_hour / self.fill_pts_per_hour


class ChamberModel:
    """Delayed first-order humidity response to delivered duty.

    ``delivered_duty`` means vapour actually leaving the outlet. The PWM
    simulator subtracts pipe transit loss before calling this -- do not apply
    that loss twice.
    """

    def __init__(self, params: ChamberParams, rh0: float):
        self.p = params
        self._rh = float(rh0)
        self._now_s = 0.0
        self._applied = 0.0                 # duty after mixing lag
        self._emerged = 0.0                 # duty that has cleared the dead time
        self._queue: deque = deque()        # (arrival_time_s, duty)

    @property
    def rh(self) -> float:
        return self._rh

    def step(self, delivered_duty: float, dt_s: float) -> float:
        self._now_s += dt_s

        # Transport delay: duty commanded now takes effect dead_time_s later.
        self._queue.append((self._now_s + self.p.dead_time_s, float(delivered_duty)))
        while self._queue and self._queue[0][0] <= self._now_s:
            _, self._emerged = self._queue.popleft()

        # First-order mixing toward whatever has emerged from the delay.
        alpha = min(1.0, dt_s / max(self.p.tau_s, 1e-9))
        self._applied += alpha * (self._emerged - self._applied)

        hours = dt_s / 3600.0
        self._rh += (self._applied * self.p.fill_pts_per_hour
                     - self.p.leak_pts_per_hour) * hours
        return self._rh
