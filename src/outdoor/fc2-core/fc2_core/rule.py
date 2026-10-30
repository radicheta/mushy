"""Pure weather-to-burst-rate rule for the FC-2 sprinklers (no ROS imports)."""
from dataclasses import dataclass
from datetime import time


@dataclass(frozen=True)
class WeatherReading:
    temperature_c: float
    humidity_pct: float
    wind_kmh: float
    precipitation_mm: float
    et0_mm: float
    slot_time_utc: str
    fetched_mono: float


@dataclass(frozen=True)
class RuleParams:
    rain_threshold_mm: float = 0.0
    cool_bursts_per_hour: float = 1.0
    hot_bursts_per_hour: float = 6.0
    pulse_sec: float = 60.0
    fallback_bursts_per_hour: float = 1.0
    # Placeholders, to be tuned on site.
    cool_temp_c: float = 15.0
    hot_temp_c: float = 28.0
    max_open_sec: float = 120.0
    weather_stale_sec: float = 2700.0
    night_enabled: bool = False
    night_start: str = '20:00'
    night_end: str = '06:00'


@dataclass(frozen=True)
class Decision:
    mode: str  # 'weather' | 'raining' | 'fallback' | 'night'
    bursts_per_hour: float


MODE_CODES = {'weather': 0, 'raining': 1, 'fallback': 2, 'night': 3}


def ramp_rate(temp_c: float, p: RuleParams) -> float:
    """Linear ramp from cool to hot rate, clamped at both ends."""
    if temp_c <= p.cool_temp_c:
        return p.cool_bursts_per_hour
    if temp_c >= p.hot_temp_c:
        return p.hot_bursts_per_hour
    frac = (temp_c - p.cool_temp_c) / (p.hot_temp_c - p.cool_temp_c)
    return p.cool_bursts_per_hour + frac * (
        p.hot_bursts_per_hour - p.cool_bursts_per_hour)


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(':')
    return int(h) * 60 + int(m)


def in_night(t: time, start: str, end: str) -> bool:
    """True if t is in [start, end); the window may wrap midnight."""
    now = t.hour * 60 + t.minute
    s, e = _minutes(start), _minutes(end)
    if s <= e:
        return s <= now < e
    return now >= s or now < e


def decide(reading, now_mono: float, local_time, p: RuleParams) -> Decision:
    if p.night_enabled and local_time is not None and in_night(
            local_time, p.night_start, p.night_end):
        return Decision('night', 0.0)
    if reading is None or now_mono - reading.fetched_mono > p.weather_stale_sec:
        return Decision('fallback', p.fallback_bursts_per_hour)
    if reading.precipitation_mm > p.rain_threshold_mm:
        return Decision('raining', 0.0)
    return Decision('weather', ramp_rate(reading.temperature_c, p))
