"""Open-Meteo `current` client for FC-2 (stdlib only, no ROS imports)."""
import json
import math
import time
import urllib.request

from fc2_core.rule import WeatherReading

_FIELDS = ('temperature_2m', 'relative_humidity_2m', 'precipitation',
           'wind_speed_10m', 'et0_fao_evapotranspiration')


def build_url(lat: float, lon: float) -> str:
    return (
        'https://api.open-meteo.com/v1/forecast'
        f'?latitude={lat}&longitude={lon}'
        '&current=temperature_2m,relative_humidity_2m,precipitation,rain,'
        'wind_speed_10m,et0_fao_evapotranspiration'
        '&timezone=UTC'
    )


def parse_current(payload: dict, fetched_mono: float) -> WeatherReading:
    if not isinstance(payload, dict) or payload.get('error'):
        reason = payload.get('reason') if isinstance(payload, dict) else payload
        raise ValueError(f'Open-Meteo error: {reason}')
    cur = payload.get('current')
    if not isinstance(cur, dict):
        raise ValueError('Open-Meteo payload has no "current" block')
    vals = {}
    for key in _FIELDS:
        v = cur.get(key)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise ValueError(f'Open-Meteo field {key!r} is not a finite number: {v!r}')
        vals[key] = v
    slot = cur.get('time')
    if not isinstance(slot, str) or not slot:
        raise ValueError('Open-Meteo "current.time" missing')
    return WeatherReading(
        temperature_c=vals['temperature_2m'],
        humidity_pct=vals['relative_humidity_2m'],
        wind_kmh=vals['wind_speed_10m'],
        precipitation_mm=vals['precipitation'],
        et0_mm=vals['et0_fao_evapotranspiration'],
        slot_time_utc=slot,
        fetched_mono=fetched_mono,
    )


def fetch(lat: float, lon: float, timeout_sec: float = 10.0, *,
          opener=urllib.request.urlopen, now_mono=time.monotonic) -> WeatherReading:
    """Fetch the current reading. Raises on any failure; caller keeps its old reading."""
    with opener(build_url(lat, lon), timeout=timeout_sec) as resp:
        status = getattr(resp, 'status', 200)
        if status != 200:
            raise ValueError(f'Open-Meteo HTTP {status}')
        body = resp.read()
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f'Open-Meteo returned invalid JSON: {e}') from e
    return parse_current(payload, now_mono())
