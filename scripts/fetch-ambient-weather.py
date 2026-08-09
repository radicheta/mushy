#!/usr/bin/env python3
"""Fetch historical ambient weather for FC-1 and write the offline fixture.

One-shot and idempotent -- safe to re-run to extend the window. NOT a daemon,
NOT scheduled, and never read by the controller at runtime (MUSHY-64).

Usage:
    python3 scripts/fetch-ambient-weather.py
    python3 scripts/fetch-ambient-weather.py --start 2026-04-11 --end 2026-08-09
    python3 scripts/fetch-ambient-weather.py --load-timescale
"""
import argparse
import csv
import json
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

# FC-1 sits in an uninsulated shipping container outdoors at these coordinates.
# The API snaps to a reanalysis grid cell ~4 km away at 253 m elevation.
LATITUDE = -34.5165641
LONGITUDE = -55.0982273

ARCHIVE_URL = 'https://archive-api.open-meteo.com/v1/archive'
TELEMETRY_START = '2026-04-11'

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (REPO_ROOT / 'src' / 'chambers' / 'fc-core' / 'fc_core' / 'sim'
           / 'data' / 'ambient_-34.52_-55.10.csv')

TIMESCALE_CONTAINER = 'mushy-timescale-1'


def fetch(start: str, end: str) -> dict:
    params = urllib.parse.urlencode({
        'latitude': LATITUDE,
        'longitude': LONGITUDE,
        'start_date': start,
        'end_date': end,
        'hourly': 'temperature_2m,relative_humidity_2m,precipitation',
        'timezone': 'UTC',
    })
    url = f'{ARCHIVE_URL}?{params}'
    print(f'GET {url}', file=sys.stderr)
    with urllib.request.urlopen(url, timeout=60) as resp:
        return json.load(resp)


def to_rows(payload: dict):
    """Flatten the API's column-oriented response into rows, dropping any hour
    with a null reading. A null would become a silent hole in the fit."""
    hourly = payload['hourly']
    dropped = 0
    rows = []
    for t, temp, rh, precip in zip(hourly['time'],
                                   hourly['temperature_2m'],
                                   hourly['relative_humidity_2m'],
                                   hourly['precipitation']):
        if temp is None or rh is None or precip is None:
            dropped += 1
            continue
        ts = datetime.fromisoformat(t).replace(tzinfo=timezone.utc)
        rows.append((ts, float(temp), float(rh), float(precip)))
    if dropped:
        print(f'WARNING: dropped {dropped} hours with null readings',
              file=sys.stderr)
    return rows


def write_fixture(rows) -> None:
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    with open(FIXTURE, 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['time_utc', 'temp_c', 'rh_pct', 'precip_mm'])
        for ts, temp, rh, precip in rows:
            w.writerow([ts.isoformat(), f'{temp:.1f}', f'{rh:.1f}', f'{precip:.2f}'])
    print(f'wrote {len(rows)} rows to {FIXTURE}', file=sys.stderr)


def load_timescale(rows) -> None:
    """Upsert into the weather table, mirroring the telemetry hypertable shape."""
    ddl = """
    CREATE TABLE IF NOT EXISTS weather (
        time  timestamptz      NOT NULL,
        topic text             NOT NULL,
        value double precision NOT NULL,
        CONSTRAINT weather_topic_time_unique UNIQUE (topic, time)
    );
    """
    values = []
    for ts, temp, rh, precip in rows:
        iso = ts.isoformat()
        values.append(f"('{iso}','weather.temperature',{temp})")
        values.append(f"('{iso}','weather.humidity',{rh})")
        values.append(f"('{iso}','weather.precipitation',{precip})")
    insert = (
        'INSERT INTO weather (time, topic, value) VALUES '
        + ','.join(values)
        + ' ON CONFLICT (topic, time) DO UPDATE SET value = EXCLUDED.value;'
    )
    sql = ddl + insert
    subprocess.run(
        ['docker', 'exec', '-i', TIMESCALE_CONTAINER,
         'psql', '-U', 'postgres', '-d', 'postgres', '-v', 'ON_ERROR_STOP=1', '-f', '-'],
        input=sql, text=True, check=True,
    )
    print(f'loaded {len(values)} weather points into Timescale', file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--start', default=TELEMETRY_START)
    ap.add_argument('--end', default=date.today().isoformat())
    ap.add_argument('--load-timescale', action='store_true',
                    help='also upsert into the Timescale weather table')
    args = ap.parse_args()

    rows = to_rows(fetch(args.start, args.end))
    if not rows:
        print('ERROR: no usable rows returned', file=sys.stderr)
        return 1
    write_fixture(rows)
    if args.load_timescale:
        load_timescale(rows)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
