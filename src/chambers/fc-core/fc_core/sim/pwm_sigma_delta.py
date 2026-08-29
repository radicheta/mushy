"""Sigma-delta (pulse-frequency) humidifier driver: one integrator, no window.

MUSHY-129. ``fc_pwm_driver`` samples commanded duty once per 480s window and
ignores it for the rest of the window; the sub-threshold bank (MUSHY-116)
then integrates only those samples. On 2026-08-29 17:21 UYT a window locked
at duty 0.03 while the command ramped to 0.8 and the relay stayed OFF for
8 min while RH fell 2 points. Two mechanisms, two clocks, both turning
demand-over-time into pulses -- and the lossy one runs first.

This replaces both with a single bank of demand-seconds:

    bank += duty * dt                          every tick
    OFF -> ON  when bank >= min_pulse          one legal pulse's worth accrued
    ON:  bank -= dt;  OFF when bank <= min_pulse - H(duty)

with ``H(d) = max(min_pulse, T * d * (1 - d))``. The bank swings across a band
of width H, so the period is ``H / (d (1-d)) = T``: in steady state this IS
the T-second PWM window (same pulse length, period, edges/day, ripple) -- at
d=0.2, T=480: ON 96s, OFF 384s. At and below the floor it is the MUSHY-116
bank. The difference is phase: the window pays for a pulse up front and fires
at the window's start, so a step lands up to T later; here a pulse fires as
soon as ``min_pulse`` is banked (``<= min_pulse / d`` after a step) and the
rest of the pulse is spent as debt, which the OFF leg repays. The OFF
threshold tracks CURRENT demand, so a demand collapse mid-pulse ends the
pulse at the 30s floor rather than running out a stale commitment.

The D-12 cap is ON-seconds in the trailing ``cap_horizon_s``, checked at
fire time and mid-pulse. Default 960s = 2T, NOT the 300s the parameter name
suggests: at a 480s window the deployed driver's history holds one entry and
its forecast spans n+1 = 2 windows, and MUSHY-116 accepted that (14.4 min
continuous ON in crash recovery). Matching it keeps this change to one
variable; tightening the horizon is a separate decision.
"""
from collections import deque
from dataclasses import dataclass, field
from typing import List

from fc_core.sim.pwm_window import pipe_delivery


@dataclass
class SigmaDeltaConfig:
    period_s: float = 480.0            # T: steady-state period to match (was pwm_window_seconds)
    min_pulse_s: float = 30.0
    max_duty_5min_avg: float = 0.90
    cap_horizon_s: float = 960.0
    pipe_transit_s: float = 6.0

    def hysteresis(self, duty: float) -> float:
        return max(self.min_pulse_s, self.period_s * duty * (1.0 - duty))


@dataclass
class SigmaDeltaSimulator:
    cfg: SigmaDeltaConfig

    bank_s: float = 0.0
    _relay_high: bool = False
    _pulse_elapsed: float = 0.0
    _on_history: deque = field(default_factory=deque)   # 1 per tick: seconds ON

    relay_cycles: int = 0
    commanded_but_discarded_s: float = 0.0   # always 0; kept for RunMetrics parity
    pulse_lengths: List[float] = field(default_factory=list)

    def _cap_allows(self, extra_s: float) -> bool:
        # ponytail: O(horizon) sum per tick is fine for a sim; the Pi driver keeps a running sum.
        return sum(self._on_history) + extra_s <= self.cfg.max_duty_5min_avg * self.cfg.cap_horizon_s

    def step(self, commanded_duty: float, dt_s: float) -> float:
        """Advance one tick. Returns DELIVERED duty (vapour at the outlet)."""
        cfg = self.cfg
        duty = max(0.0, min(1.0, commanded_duty))
        if not self._on_history.maxlen:
            self._on_history = deque(maxlen=max(1, int(round(cfg.cap_horizon_s / dt_s))))

        # Anti-windup: a bank held back by the cap must not turn into minutes
        # of over-delivery once demand drops. Ceiling = the largest legal
        # swing (T/4 at d=0.5).
        self.bank_s = min(self.bank_s + duty * dt_s, cfg.period_s / 4.0)

        if not self._relay_high:
            if self.bank_s >= cfg.min_pulse_s and self._cap_allows(cfg.min_pulse_s):
                self._relay_high = True
                self._pulse_elapsed = 0.0
                self.relay_cycles += 1
        else:
            self.bank_s -= dt_s
            off_at = cfg.min_pulse_s - cfg.hysteresis(duty)
            if self.bank_s <= off_at or not self._cap_allows(dt_s):
                self._relay_high = False
                self.pulse_lengths.append(self._pulse_elapsed)
                self.bank_s = max(self.bank_s, off_at)

        delivered = 0.0
        if self._relay_high:
            delivered = pipe_delivery(self._pulse_elapsed, cfg.pipe_transit_s, dt_s)
            self._pulse_elapsed += dt_s
        self._on_history.append(dt_s if self._relay_high else 0.0)
        return delivered
