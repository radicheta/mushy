"""Burst scheduler and rolling duty for the FC-2 sprinkler valve (no ROS imports)."""
from typing import Iterable, Optional, Tuple


class BurstScheduler:
    """Decides when the valve should be open, from a bursts-per-hour rate.

    The first burst comes one full gap after start_mono, so a crash-looping
    node never waters once per restart.
    """

    def __init__(self, start_mono: float):
        self.start_mono = start_mono
        self.last_burst_start: Optional[float] = None
        self._open_until = float("-inf")

    def tick(self, now_mono: float, bursts_per_hour: float, pulse_sec: float) -> bool:
        if bursts_per_hour <= 0:
            self._open_until = float("-inf")
            return False
        if now_mono < self._open_until:
            return True
        ref = self.start_mono if self.last_burst_start is None else self.last_burst_start
        if now_mono >= ref + 3600.0 / bursts_per_hour:
            self.last_burst_start = now_mono
            self._open_until = now_mono + pulse_sec
            return True
        return False


def duty_pct(
    intervals: Iterable[Tuple[float, Optional[float]]],
    now_mono: float,
    window_sec: float = 3600.0,
) -> float:
    """Percent of the trailing window the valve was open; an end of None means still open."""
    lo = now_mono - window_sec
    open_sec = sum(
        max(0.0, min(now_mono if end is None else end, now_mono) - max(start, lo))
        for start, end in intervals
    )
    return 100.0 * open_sec / window_sec
