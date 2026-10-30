import io
import json
import urllib.error
from pathlib import Path

import pytest

from fc2_core.weather import build_url, fetch, parse_current

FIXTURE = Path(__file__).parent / 'data' / 'current_2026-10-30.json'


def test_parses_fixture():
    w = parse_current(json.loads(FIXTURE.read_text()), 5.0)
    assert (w.temperature_c, w.precipitation_mm, w.wind_kmh, w.et0_mm) == (20.9, 0.10, 14.6, 0.13)
    assert w.humidity_pct == 55 and w.slot_time_utc == '2026-10-30T15:30' and w.fetched_mono == 5.0


@pytest.mark.parametrize('mutate', [
    lambda d: d['current'].update(precipitation=None),
    lambda d: d['current'].pop('temperature_2m'),
    lambda d: d.pop('current'),
    lambda d: d.update(error=True, reason='Parameter is invalid'),
    lambda d: d['current'].update(wind_speed_10m='14.6'),
    lambda d: d['current'].update(temperature_2m=float('nan')),
    lambda d: d['current'].update(et0_fao_evapotranspiration=float('inf')),
    lambda d: d['current'].update(relative_humidity_2m=True),
    lambda d: d['current'].pop('time'),
])
def test_bad_payload_raises(mutate):
    d = json.loads(FIXTURE.read_text())
    mutate(d)
    with pytest.raises(ValueError):
        parse_current(d, 0.0)


def test_url_uses_precipitation_and_utc():
    u = build_url(-34.5165641, -55.0982273)
    assert 'precipitation' in u and 'timezone=UTC' in u and 'latitude=-34.5165641' in u


class FakeResponse(io.BytesIO):
    def __init__(self, body, status=200):
        super().__init__(body)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_fetch_happy_path_passes_timeout_and_stamps_clock():
    seen = {}

    def opener(url, timeout):
        seen.update(url=url, timeout=timeout)
        return FakeResponse(FIXTURE.read_bytes())

    w = fetch(1.0, 2.0, 7.5, opener=opener, now_mono=lambda: 42.0)
    assert seen['timeout'] == 7.5 and 'latitude=1.0' in seen['url']
    assert w.fetched_mono == 42.0 and w.temperature_c == 20.9


def test_fetch_raises_on_network_error():
    def boom(*a, **k):
        raise urllib.error.URLError('no route')
    with pytest.raises(Exception):
        fetch(0, 0, opener=boom)


def test_fetch_raises_on_non_200():
    with pytest.raises(ValueError):
        fetch(0, 0, opener=lambda u, timeout: FakeResponse(b'{}', status=503))


def test_fetch_raises_on_bad_json():
    with pytest.raises(ValueError):
        fetch(0, 0, opener=lambda u, timeout: FakeResponse(b'not json'))
