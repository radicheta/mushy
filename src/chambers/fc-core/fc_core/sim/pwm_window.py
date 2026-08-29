"""Faithful simulation of fc_pwm_driver, plus the physics it is blind to.

Mirrors ``fc_pwm_driver._tick()``: window rollover, the rolling 5-minute duty
cap (D-12), and the min-pulse round-down (D-11).

Adds two things the real driver has no model of:

1. **Pipe transit.** There are ~2 m of pipe between the humidifier element and
   the chamber outlet. Farmer-measured 2026-08-09: vapour takes 5-7 s to appear
   after the relay closes. Every pulse therefore spends its first ~6 s wetting
   pipe and delivering nothing. Short pulses are not merely low-resolution,
   they are disproportionately wasteful -- a 10 s pulse delivers ~4 s of vapour
   (40 % efficient) while a 30 s pulse delivers ~24 s (80 %).

2. **Relay wear.** ``min_pulse_seconds`` exists partly to stop the relay
   chattering, so any fix that trades stability for cycling has to be visible.
   ``relay_cycles`` counts rising edges.

``accumulate`` implements sub-threshold pulse accumulation: bank commanded duty
that is too small to express as a legal pulse, and fire one full-length pulse
once a pulse's worth has accrued. Without it the smallest expressible duty is
``min_pulse_s / window_s`` -- 8.3 % today, 16.7 % at the farmer's preferred 20 s
floor -- against an equilibrium demand of ~10 %.
"""
from collections import deque
from dataclasses import dataclass, field
from typing import List


def pipe_delivery(pulse_elapsed_s: float, transit_s: float, dt_s: float) -> float:
    """Fraction of this tick that delivers vapour at the outlet, given how long
    the relay has been closed. Vapour only emerges after the pipe is wet."""
    if pulse_elapsed_s >= transit_s:
        return 1.0
    remaining = transit_s - pulse_elapsed_s
    if remaining < dt_s:
        return (dt_s - remaining) / dt_s
    return 0.0


@dataclass
class PwmConfig:
    window_s: float = 120.0             # fc_pwm_driver pwm_window_seconds
    min_pulse_s: float = 10.0           # fc_pwm_driver min_pulse_seconds
    max_duty_5min_avg: float = 0.40     # fc_pwm_driver max_duty_5min_avg
    pipe_transit_s: float = 6.0         # farmer-measured 5-7 s
    accumulate: bool = False            # sub-threshold pulse accumulation


@dataclass
class PwmSimulator:
    cfg: PwmConfig

    _elapsed: float = 0.0
    _window_on_s: float = 0.0
    _history: deque = field(default_factory=deque)
    _bank_s: float = 0.0                # accumulated sub-threshold demand
    _relay_high: bool = False
    _pulse_elapsed: float = 0.0

    relay_cycles: int = 0
    commanded_but_discarded_s: float = 0.0
    pulse_lengths: List[float] = field(default_factory=list)

    def __post_init__(self):
        maxlen = max(1, int(round(300.0 / self.cfg.window_s)))
        self._history = deque(maxlen=maxlen)
        self._rollover(0.0)

    # -- window handling ---------------------------------------------------

    def _rollover(self, commanded: float) -> None:
        cfg = self.cfg
        duty = max(0.0, min(1.0, commanded))

        # Rolling 5-min cap (D-12): back-solve so the running mean stays <= cap.
        if self._history:
            n = len(self._history)
            current_sum = sum(self._history)
            if (current_sum + duty) / (n + 1) > cfg.max_duty_5min_avg:
                duty = max(0.0, cfg.max_duty_5min_avg * (n + 1) - current_sum)
                duty = max(0.0, min(1.0, duty))

        on_s = duty * cfg.window_s

        if 0.0 < on_s < cfg.min_pulse_s:
            if cfg.accumulate:
                # Bank it instead of throwing it away.
                self._bank_s += on_s
                if self._bank_s >= cfg.min_pulse_s:
                    on_s = cfg.min_pulse_s
                    self._bank_s -= cfg.min_pulse_s
                else:
                    on_s = 0.0
            else:
                self.commanded_but_discarded_s += on_s
                on_s = 0.0

        on_s = min(on_s, cfg.window_s)
        self._window_on_s = on_s
        self._history.append(on_s / cfg.window_s)
        self._elapsed = 0.0
        self._pulse_elapsed = 0.0
        if on_s > 0.0:
            self.pulse_lengths.append(on_s)

    # -- per-tick ----------------------------------------------------------

    def step(self, commanded_duty: float, dt_s: float) -> float:
        """Advance one tick. Returns DELIVERED duty (vapour at the outlet)."""
        if self._elapsed >= self.cfg.window_s:
            self._rollover(commanded_duty)

        want_high = self._elapsed < self._window_on_s
        if want_high and not self._relay_high:
            self.relay_cycles += 1
            self._pulse_elapsed = 0.0
        self._relay_high = want_high

        delivered = 0.0
        if want_high:
            delivered = pipe_delivery(self._pulse_elapsed, self.cfg.pipe_transit_s, dt_s)
            self._pulse_elapsed += dt_s

        self._elapsed += dt_s
        return delivered
