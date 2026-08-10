"""Offline ambient weather series for model fitting (MUSHY-64).

Ground truth for fitting and validation ONLY. This is never a runtime input to
the controller: a stale or failed fetch would silently corrupt the control
path, and FC-1 has a documented history of connectivity problems.

Stdlib-only and network-free on purpose -- the test container runs with
--network none.
"""
import csv
from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Union

DEFAULT_FIXTURE = Path(__file__).parent / 'data' / 'ambient_-34.52_-55.10.csv'


@dataclass(frozen=True)
class AmbientSample:
    """Outdoor conditions at one instant."""

    temp_c: float
    rh_pct: float
    precip_mm: float


def _parse_utc(raw: str) -> datetime:
    ts = datetime.fromisoformat(raw)
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts


class AmbientSeries:
    """Hourly outdoor conditions, interpolated onto arbitrary timestamps."""

    def __init__(self, times: List[datetime], samples: List[AmbientSample]):
        self._times = times
        self._samples = samples

    @classmethod
    def from_csv(cls, path: Union[Path, str] = DEFAULT_FIXTURE) -> 'AmbientSeries':
        times: List[datetime] = []
        samples: List[AmbientSample] = []
        with open(path, newline='') as fh:
            for row in csv.DictReader(fh):
                times.append(_parse_utc(row['time_utc']))
                samples.append(AmbientSample(
                    temp_c=float(row['temp_c']),
                    rh_pct=float(row['rh_pct']),
                    precip_mm=float(row['precip_mm']),
                ))
        if not times:
            raise ValueError(f'no rows in {path}')
        return cls(times, samples)

    @property
    def start(self) -> datetime:
        return self._times[0]

    @property
    def end(self) -> datetime:
        return self._times[-1]

    def at(self, when: datetime) -> AmbientSample:
        """Conditions at ``when``.

        Temperature and humidity interpolate linearly between the bracketing
        hours. Precipitation does NOT: it is an hourly accumulation, so it
        step-holds the containing hour's value. Interpolating it would invent
        rain that did not fall in that minute.

        Raises ValueError outside the covered window rather than
        extrapolating -- silently inventing ambient is how a fit starts
        explaining data it never had.
        """
        if when < self.start or when > self.end:
            raise ValueError(
                f'{when.isoformat()} is outside ambient coverage '
                f'{self.start.isoformat()}..{self.end.isoformat()}'
            )
        i = bisect_right(self._times, when) - 1
        if i >= len(self._times) - 1:
            return self._samples[-1]

        lo_t, hi_t = self._times[i], self._times[i + 1]
        lo, hi = self._samples[i], self._samples[i + 1]
        span = (hi_t - lo_t).total_seconds()
        frac = 0.0 if span <= 0 else (when - lo_t).total_seconds() / span
        return AmbientSample(
            temp_c=lo.temp_c + frac * (hi.temp_c - lo.temp_c),
            rh_pct=lo.rh_pct + frac * (hi.rh_pct - lo.rh_pct),
            precip_mm=lo.precip_mm,
        )
