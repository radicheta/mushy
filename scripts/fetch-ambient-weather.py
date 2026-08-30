#!/usr/bin/env python3
"""Fetch historical ambient weather for FC-1 and write the offline fixture.

One-shot and idempotent -- safe to re-run to extend the window. NOT a daemon,
NOT scheduled, and never read by the controller at runtime (MUSHY-64).

Usage:
    python3 scripts/fetch-ambient-weather.py --fetch
    python3 scripts/fetch-ambient-weather.py --fetch --start 2026-04-11 --end 2026-08-08
    python3 scripts/fetch-ambient-weather.py --load-timescale
    python3 scripts/fetch-ambient-weather.py --fetch --load-timescale
"""
import argparse
import csv
import hashlib
import json
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
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
FIXTURE_META = FIXTURE.with_name(FIXTURE.stem + '.meta.json')

TIMESCALE_CONTAINER = 'mushy-timescale-1'


def fetch(start: str, end: str):
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
        return json.load(resp), url


def to_rows(payload: dict, fetch_moment: datetime):
    """Flatten the API's column-oriented response into rows.

    Drops any hour with a null reading -- a null would become a silent hole
    in the fit. Also drops any hour later than ``fetch_moment``: Open-Meteo's
    archive endpoint returns model-forecast hours for the current day (and
    would happily return more if a caller passed a future ``--end``), and
    forecast committed as historical ground truth would corrupt the fit
    without warning.
    """
    hourly = payload['hourly']
    dropped_null = 0
    dropped_future = 0
    rows = []
    for t, temp, rh, precip in zip(hourly['time'],
                                   hourly['temperature_2m'],
                                   hourly['relative_humidity_2m'],
                                   hourly['precipitation']):
        if temp is None or rh is None or precip is None:
            dropped_null += 1
            continue
        ts = datetime.fromisoformat(t).replace(tzinfo=timezone.utc)
        if ts > fetch_moment:
            dropped_future += 1
            continue
        rows.append((ts, float(temp), float(rh), float(precip)))
    if dropped_null:
        print(f'WARNING: dropped {dropped_null} hours with null readings',
              file=sys.stderr)
    if dropped_future:
        print(f'WARNING: dropped {dropped_future} hours later than fetch '
              f'time ({fetch_moment.isoformat()}) -- forecast, not '
              f'reanalysis', file=sys.stderr)
    return rows


def write_fixture(rows) -> None:
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    with open(FIXTURE, 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['time_utc', 'temp_c', 'rh_pct', 'precip_mm'])
        for ts, temp, rh, precip in rows:
            w.writerow([ts.isoformat(), f'{temp:.1f}', f'{rh:.1f}', f'{precip:.2f}'])
    print(f'wrote {len(rows)} rows to {FIXTURE}', file=sys.stderr)


def write_meta(url: str, start: str, end: str, rows) -> None:
    """Write a sidecar recording exactly what was fetched and a checksum of
    the fixture bytes. Open-Meteo serves preliminary ERA5T values for recent
    days and later replaces them with final ERA5 (different values, same
    timestamps), so a re-run months from now can silently alter historical
    rows. The sha256 here turns that silent drift into a loud test failure --
    see test_ambient.py's checksum test."""
    digest = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    meta = {
        'generated_utc': datetime.now(timezone.utc).isoformat(),
        'url': url,
        'start': start,
        'end': end,
        'rows': len(rows),
        'sha256': digest,
    }
    with open(FIXTURE_META, 'w') as fh:
        json.dump(meta, fh, indent=2)
        fh.write('\n')
    print(f'wrote {FIXTURE_META}', file=sys.stderr)


def read_fixture_rows():
    """Read rows back out of the already-committed fixture, no network
    involved. This is what lets --load-timescale reload the database without
    re-fetching and overwriting the scientific input file."""
    rows = []
    with open(FIXTURE, newline='') as fh:
        for row in csv.DictReader(fh):
            ts = datetime.fromisoformat(row['time_utc'])
            rows.append((ts, float(row['temp_c']), float(row['rh_pct']),
                         float(row['precip_mm'])))
    return rows


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
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--start', default=TELEMETRY_START)
    ap.add_argument('--end', default=(date.today() - timedelta(days=1)).isoformat(),
                    help='defaults to yesterday -- the archive returns '
                         'forecast hours for today, not reanalysis')
    ap.add_argument('--fetch', action='store_true',
                    help='fetch from Open-Meteo and (re)write the committed '
                         'fixture and its checksum sidecar')
    ap.add_argument('--out', default=None,
                    help='write to this path instead of the committed '
                         'fixture. Use it for any window whose recent days '
                         'Open-Meteo still serves as forecast/ERA5T rather '
                         'than final ERA5 -- the committed fixture is a '
                         'scientific input to the MUSHY-60 fit and to '
                         "test_ambient.py's checksum test, and overwriting "
                         'it in place would silently move both.')
    ap.add_argument('--load-timescale', action='store_true',
                    help='load the committed fixture into the Timescale '
                         'weather table (reads the fixture on disk, no '
                         'network involved)')
    args = ap.parse_args()

    if args.out:
        global FIXTURE, FIXTURE_META
        FIXTURE = Path(args.out)
        FIXTURE_META = FIXTURE.with_name(FIXTURE.stem + '.meta.json')

    if not args.fetch and not args.load_timescale:
        ap.error('nothing to do: pass --fetch, --load-timescale, or both')

    if args.fetch:
        fetch_moment = datetime.now(timezone.utc)
        payload, url = fetch(args.start, args.end)
        rows = to_rows(payload, fetch_moment)
        if not rows:
            print('ERROR: no usable rows returned', file=sys.stderr)
            return 1
        write_fixture(rows)
        write_meta(url, args.start, args.end, rows)

    if args.load_timescale:
        rows = read_fixture_rows()
        if not rows:
            print('ERROR: fixture has no rows', file=sys.stderr)
            return 1
        load_timescale(rows)

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
