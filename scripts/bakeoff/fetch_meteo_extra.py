#!/usr/bin/env python3
"""MUSHY-150: pull the meteo channels the ambient fixture does not carry.

scripts/fetch-ambient-weather.py fetches temperature, RH and precipitation
into a COMMITTED, CHECKSUMMED fixture (test_ambient.py asserts the sha256), so
it must not be rewritten to add variables. This writes the extra channels
straight into the Timescale `weather` table under their own topics and leaves
that fixture untouched.

Why these four: FC-1 is an uninsulated steel container outdoors. The
chamber_model docstring names unmodelled SOLAR GAIN as the specific physical
reason the fit will extrapolate poorly into summer, and wind sets the external
convection coefficient -- both drive the wall temperature that Charlie and
Dave are built around, and neither is currently observable to any candidate.

    .venv/bin/python scripts/bakeoff/fetch_meteo_extra.py
"""
import json, subprocess, sys, urllib.parse, urllib.request
from datetime import date, timedelta

LAT, LON = -34.5165641, -55.0982273
URL = 'https://archive-api.open-meteo.com/v1/archive'
CONTAINER = 'mushy-timescale-1'
VARS = {'shortwave_radiation': 'weather.solar',        # W/m2, direct solar gain
        'cloud_cover': 'weather.cloud',                # %, night-time IR loss
        'wind_speed_10m': 'weather.wind',              # km/h, external convection
        'surface_pressure': 'weather.pressure'}        # hPa, completeness


def main():
    start = sys.argv[1] if len(sys.argv) > 1 else '2026-04-11'
    end = sys.argv[2] if len(sys.argv) > 2 else (date.today() - timedelta(days=1)).isoformat()
    q = urllib.parse.urlencode({'latitude': LAT, 'longitude': LON,
                                'start_date': start, 'end_date': end,
                                'hourly': ','.join(VARS), 'timezone': 'UTC'})
    print(f'GET {URL}?{q}', file=sys.stderr)
    with urllib.request.urlopen(f'{URL}?{q}', timeout=120) as r:
        h = json.load(r)['hourly']

    values, n_null = [], 0
    for i, t in enumerate(h['time']):
        for var, topic in VARS.items():
            v = h[var][i]
            if v is None:
                n_null += 1
                continue
            values.append(f"('{t}+00','{topic}',{float(v)})")
    if not values:
        print('ERROR: no rows', file=sys.stderr)
        return 1
    print(f'{len(h["time"])} hours, {len(values)} points, {n_null} nulls skipped', file=sys.stderr)

    # chunked so the statement stays a sane size
    for i in range(0, len(values), 20000):
        sql = ('INSERT INTO weather (time, topic, value) VALUES '
               + ','.join(values[i:i + 20000])
               + ' ON CONFLICT (topic, time) DO UPDATE SET value = EXCLUDED.value;')
        subprocess.run(['docker', 'exec', '-i', CONTAINER, 'psql', '-U', 'postgres',
                        '-d', 'postgres', '-v', 'ON_ERROR_STOP=1', '-f', '-'],
                       input=sql, text=True, check=True, capture_output=True)
    print(f'loaded {len(values)} points', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
