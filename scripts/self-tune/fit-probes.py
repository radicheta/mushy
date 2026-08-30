#!/usr/bin/env python3
"""Fit the chamber model to identification probes stored in Timescale (MUSHY-138).

Adapter only: pulls the series, resamples to a 10 s grid, hands windows to
fc_core.sim.probe_fit, writes reports/self-tune/<date>.json. Never touches
the control path. --quasi uses idle-then-single-pulse transitions instead
of fc.probe markers (spec section 4 step 2, history before any probe ran).

  PYTHONPATH=src/chambers/fc-core .venv/bin/python scripts/self-tune/fit-probes.py --days 14
  PYTHONPATH=src/chambers/fc-core .venv/bin/python scripts/self-tune/fit-probes.py --quasi --days 30
"""
import argparse
import importlib.util
import json
import math
import sys
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / 'src' / 'chambers' / 'fc-core'))

from fc_core.sim.ambient import AmbientSeries                        # noqa: E402
from fc_core.sim.chamber_model import ChamberParams                  # noqa: E402
from fc_core.sim.probe_fit import (aggregate, find_quasi_windows,     # noqa: E402
                                   find_windows, fit_window)
from fc_core.sim.psychrometrics import absolute_humidity_g_m3        # noqa: E402

_spec = importlib.util.spec_from_file_location(
    'fit_chamber_model', REPO_ROOT / 'scripts' / 'fit-chamber-model.py')
fcm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fcm)

DT = 10.0
IDLE_S = 900.0
REPORT_DIR = REPO_ROOT / 'reports' / 'self-tune'
# ambient_-34.52_-55.10.csv (DEFAULT_FIXTURE) stops 2026-08-08; .recent.csv is
# the sibling that is actually kept refreshed (currently to 2026-08-30T02Z,
# ~1-2 days behind real time). Use it here so `--days` windows near "now"
# don't fall outside AmbientSeries coverage.
AMBIENT_CSV = REPO_ROOT / 'src' / 'chambers' / 'fc-core' / 'fc_core' / 'sim' / 'data' / 'ambient_-34.52_-55.10.recent.csv'


def load(topic, t0, t1):
    sql = (f"select extract(epoch from time), value from telemetry where topic='{topic}' "
           f"and time >= to_timestamp({t0}) and time <= to_timestamp({t1}) order by time")
    rows = []
    for line in fcm.psql(sql).splitlines():
        if line.strip():
            ts, v = line.split('\t')
            rows.append((float(ts), float(v)))
    return rows


def _finite(obj):
    """Recursively replace non-finite floats (inf/nan) with None so json.dumps
    produces strict JSON (MUSHY-138 ruling 13) -- aggregate()'s iqr/median_temp_c
    are float('inf')/float('nan') when too few windows were fit."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _finite(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_finite(v) for v in obj]
    return obj


def resample(rows, t0, t1, dt, initial=None):
    """Sample-and-hold onto [t0, t1) at dt. `initial` is the value before the first row."""
    out, i, cur = [], 0, initial
    t = t0
    while t < t1:
        while i < len(rows) and rows[i][0] <= t:
            cur = rows[i][1]
            i += 1
        out.append(cur if cur is not None else rows[0][1])
        t += dt
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--days', type=float, default=14.0)
    ap.add_argument('--quasi', action='store_true')
    ap.add_argument('--max-windows', type=int, default=40,
                     help='cap on windows fitted (most recent N kept); fit_window '
                          'costs ~4-5s per window at 10s sampling')
    ap.add_argument('--out', default=None)
    a = ap.parse_args()

    now = datetime.now(timezone.utc)
    t0_want = now - timedelta(days=a.days)
    amb = AmbientSeries.from_csv(AMBIENT_CSV)
    t1 = min(now, amb.end)
    t0 = t0_want
    print(f'analysis window: {t0.isoformat()} .. {t1.isoformat()} '
          f'(clamped to ambient coverage ending {amb.end.isoformat()})')
    e0, e1 = t0.timestamp(), t1.timestamp()
    rh = resample(load('fc.humidity', e0, e1), e0, e1, DT)
    temp = resample(load('fc.temperature', e0, e1), e0, e1, DT)
    relay = resample(load('fc.humidifier', e0 - 86400, e1), e0, e1, DT, initial=0.0)
    ambient = []
    t = e0
    while t < e1:
        s = amb.at(datetime.fromtimestamp(t, tz=timezone.utc))
        ambient.append(absolute_humidity_g_m3(s.temp_c, s.rh_pct))
        t += DT
    # guard only: fc.humidity is stored in percent on prod, but defend against
    # a fraction (0-1) representation without silently mis-scaling a genuine
    # low reading.
    rh = [x * 100.0 if x <= 1.0 else x for x in rh]

    if a.quasi:
        windows = find_quasi_windows(DT, rh, temp, ambient, relay, idle_s=IDLE_S)
        # find_quasi_windows preloads its idle counter to idle_s ("assume the
        # record starts already idle"), so the FIRST rising edge in the whole
        # series always qualifies as a window regardless of how much real
        # idle time actually preceded it -- even zero. (Window.probe_start_idx
        # is a LOCAL offset into the sliced window, capped at pre_s/dt=60
        # grid points; it cannot be compared against idle_s/dt=90 to recover
        # the pulse's true position in the series, so that check is done here
        # against the raw relay array instead.) Only that first window can be
        # spurious (MUSHY-138 ruling 7); every later one reset idle from real
        # OFF time within the series.
        first_on = next((i for i, v in enumerate(relay) if v > 0.5), None)
        if windows and first_on is not None and first_on * DT < IDLE_S:
            windows = windows[1:]
    else:
        probe = resample(load('fc.probe', e0, e1), e0, e1, DT, initial=0.0)
        windows = find_windows(DT, rh, temp, ambient, relay, probe)

    n_found = len(windows)
    windows = windows[-a.max_windows:]
    n_dropped = n_found - len(windows)
    print(f'windows found: {n_found}, fitted: {len(windows)} (dropped {n_dropped} oldest, max-windows={a.max_windows})')

    base = ChamberParams()
    fits = [fit_window(w, base) for w in windows]
    temps = [w.temp[w.probe_start_idx] for w, f in zip(windows, fits) if not f.rejected]
    agg = aggregate(fits, base, temps)
    report = {
        'generated': now.isoformat(), 'days': a.days, 'quasi': a.quasi,
        'window_start': t0.isoformat(), 'window_end': t1.isoformat(),
        'windows_found': n_found, 'windows_dropped': n_dropped, 'windows': len(windows),
        'fits': [asdict(f) for f in fits],
        'valid': agg.valid, 'reasons': agg.reasons, 'n': agg.n,
        'params': asdict(agg.params), 'iqr': agg.iqr, 'median_temp_c': agg.median_temp_c,
    }
    report = _finite(report)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = Path(a.out) if a.out else REPORT_DIR / f'{now:%Y-%m-%d}{"-quasi" if a.quasi else ""}.json'
    out.write_text(json.dumps(report, indent=2))
    print(json.dumps({k: report[k] for k in ('valid', 'reasons', 'n', 'params', 'iqr', 'median_temp_c')}, indent=2))
    print(f'report: {out}')
    return 0 if agg.valid else 3


if __name__ == '__main__':
    sys.exit(main())
