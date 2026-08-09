#!/usr/bin/env python3
"""Identify the chamber's air-exchange conductance Q and effective fill rate F.

Offline analysis only -- never runs on the Pi, never touches the control path.

Q comes from quiet intervals (delivered duty 0 for longer than the dead time),
where the fill term vanishes and the leak is observed alone. F is then fitted
on active intervals with Q held fixed. Sequential rather than joint: fitting
both at once is degenerate, since a larger F and a larger Q trade off.

Usage:
    python3 scripts/fit-chamber-model.py
    python3 scripts/fit-chamber-model.py --report path/to/RESULTS.md
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / 'src' / 'chambers' / 'fc-core'))

from fc_core.sim.ambient import AmbientSeries          # noqa: E402
from fc_core.sim.psychrometrics import (               # noqa: E402
    CHAMBER_VOLUME_M3, absolute_humidity_g_m3)

CONTAINER = 'mushy-timescale-1'
WINDOW_START = '2026-04-11'
WINDOW_END = '2026-08-09'          # exclusive upper bound for the SQL BETWEEN
SPLIT = datetime(2026, 7, 1, tzinfo=timezone.utc)   # fit < SPLIT <= validate

DEAD_TIME_S = 360.0
QUIET_SETTLE_MIN = 10              # discard this many minutes after duty falls
RH_SATURATED = 99.99               # farmer ruling: exclude, do not clamp
MAX_RH_STEP_PCT = 3.0              # sensor-failover step guard (see design lim. 7)
DEFAULT_REPORT = (REPO_ROOT / '.planning' / 'phases'
                  / '999.33-digital-twin-chamber-sim'
                  / '999.33-06-FIT-RESULTS.md')


def psql(sql: str) -> str:
    r = subprocess.run(
        ['docker', 'exec', CONTAINER, 'psql', '-U', 'postgres', '-d', 'postgres',
         '-F', '\t', '-A', '-t', '-c', sql],
        capture_output=True, text=True, check=True)
    return r.stdout


def load_minutes():
    """One row per minute: temp, rh, and FORWARD-FILLED relay state.

    fc.humidifier is the relay, binary and published ON CHANGE, so a minute
    with no sample means the relay did not change -- not that data is missing.
    Forward-filling is what makes the July-August half usable at all: raw
    coverage falls from 25532 minutes in April to 789 in August purely because
    the controller settled and toggled less.
    """
    sql = f"""
    with grid as (
      select generate_series(timestamptz '{WINDOW_START}',
                             timestamptz '{WINDOW_END}',
                             interval '1 minute') b),
    th as (
      select time_bucket('1 minute', time) b,
             avg(value) filter (where topic='fc.temperature') temp,
             avg(value) filter (where topic='fc.humidity')    rh
      from telemetry
      where topic in ('fc.temperature','fc.humidity')
        and time between '{WINDOW_START}' and '{WINDOW_END}'
      group by 1),
    relay as (
      select time_bucket('1 minute', time) b, avg(value) duty
      from telemetry
      where topic='fc.humidifier'
        and time between '{WINDOW_START}' and '{WINDOW_END}'
      group by 1)
    select g.b, th.temp, th.rh, relay.duty
    from grid g
    left join th    on th.b = g.b
    left join relay on relay.b = g.b
    order by g.b;
    """
    # `th` and `relay` are already one row per minute, so no aggregation is
    # needed here. The relay's gaps stay NULL in this result and are
    # forward-filled in Python below, where the intent is legible.
    rows = []
    for line in psql(sql).splitlines():
        if not line.strip():
            continue
        b, temp, rh, duty = (line.split('\t') + [''] * 4)[:4]
        ts_str = b.strip()
        # psql on this host emits '+00' rather than '+00:00'; Python 3.10's
        # fromisoformat (pre-3.11) requires the colon form.
        if ts_str[-3] in '+-' and ts_str[-2:].isdigit():
            ts_str += ':00'
        rows.append((
            datetime.fromisoformat(ts_str).astimezone(timezone.utc),
            float(temp) if temp.strip() else None,
            float(rh) if rh.strip() else None,
            float(duty) if duty.strip() else None,
        ))
    # Forward-fill the relay in Python -- clearer than doing it in SQL.
    last = None
    filled = []
    for ts, temp, rh, duty in rows:
        if duty is not None:
            last = duty
        filled.append((ts, temp, rh, last))
    return filled


def build_samples(rows, ambient: AmbientSeries):
    """Attach ambient, convert to absolute moisture, and apply exclusions."""
    stats = {'total': 0, 'no_reading': 0, 'no_relay': 0, 'saturated': 0,
             'outside_ambient': 0, 'rh_step': 0, 'kept': 0}
    out = []
    prev_rh = None
    for ts, temp, rh, duty in rows:
        stats['total'] += 1
        if temp is None or rh is None:
            stats['no_reading'] += 1
            prev_rh = None
            continue
        if duty is None:
            stats['no_relay'] += 1
            prev_rh = None
            continue
        if rh >= RH_SATURATED:
            stats['saturated'] += 1
            prev_rh = None
            continue
        if prev_rh is not None and abs(rh - prev_rh) > MAX_RH_STEP_PCT:
            # Sensor failover injects a step; a step is a huge spurious dAH/dt.
            stats['rh_step'] += 1
            prev_rh = rh
            continue
        prev_rh = rh
        try:
            amb = ambient.at(ts)
        except ValueError:
            stats['outside_ambient'] += 1
            continue
        stats['kept'] += 1
        out.append({
            'ts': ts,
            'duty': duty,
            'ah_in': absolute_humidity_g_m3(temp, rh),
            'ah_out': absolute_humidity_g_m3(amb.temp_c, amb.rh_pct),
        })
    return out, stats


def with_derivatives(samples):
    """Central-ish difference on consecutive 1-minute samples, in g/m3 per hour.

    Only pairs exactly 60 s apart are used -- a longer span means an excluded
    sample sits between them and the derivative would smear across it.
    """
    out = []
    for a, b in zip(samples, samples[1:]):
        dt_s = (b['ts'] - a['ts']).total_seconds()
        if dt_s != 60.0:
            continue
        rec = dict(a)
        rec['dah_dt'] = (b['ah_in'] - a['ah_in']) * 3600.0 / dt_s
        out.append(rec)
    return out


def quiet_mask(samples):
    """True where duty has been 0 for longer than dead time + settle."""
    need = int(DEAD_TIME_S / 60.0) + QUIET_SETTLE_MIN
    run = 0
    flags = []
    for s in samples:
        run = run + 1 if s['duty'] == 0.0 else 0
        flags.append(run >= need)
    return flags


def fit_q(samples):
    """Least squares through the origin: -V*dAH/dt = Q * (AH_in - AH_out)."""
    num = den = 0.0
    n = 0
    for s in samples:
        x = s['ah_in'] - s['ah_out']
        y = -CHAMBER_VOLUME_M3 * s['dah_dt']
        num += x * y
        den += x * x
        n += 1
    return (num / den if den else float('nan')), n


def fit_f(samples, q):
    """Least squares through the origin, Q held fixed:
       V*dAH/dt + Q*(AH_in - AH_out) = F * u."""
    num = den = 0.0
    n = 0
    for s in samples:
        if s['duty'] <= 0.0:
            continue
        z = CHAMBER_VOLUME_M3 * s['dah_dt'] + q * (s['ah_in'] - s['ah_out'])
        u = s['duty']
        num += u * z
        den += u * u
        n += 1
    return (num / den if den else float('nan')), n


def fit_half(samples):
    flags = quiet_mask(samples)
    quiet = [s for s, f in zip(samples, flags) if f]
    q, nq = fit_q(quiet)
    f, nf = fit_f(samples, q)
    return {'q_m3_per_h': q, 'n_quiet': nq, 'f_g_per_h': f, 'n_active': nf,
            'n_samples': len(samples)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--report', default=str(DEFAULT_REPORT))
    args = ap.parse_args()

    ambient = AmbientSeries.from_csv()
    rows = load_minutes()
    samples, stats = build_samples(rows, ambient)
    samples = with_derivatives(samples)

    fit_set = [s for s in samples if s['ts'] < SPLIT]
    val_set = [s for s in samples if s['ts'] >= SPLIT]

    results = {
        'all': fit_half(samples),
        'fit_apr_jun': fit_half(fit_set),
        'validate_jul_aug': fit_half(val_set),
        'exclusions': stats,
    }
    print(json.dumps(results, indent=2, default=str))

    report = Path(args.report)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(results))
    print(f'wrote {report}', file=sys.stderr)
    return 0


def render_report(r) -> str:
    def row(name, d):
        return (f"| {name} | {d['q_m3_per_h']:.3f} | {d['n_quiet']} | "
                f"{d['f_g_per_h']:.2f} | {d['n_active']} | {d['n_samples']} |")
    ex = r['exclusions']
    return f"""# 999.33-06 — Chamber model fit results (MUSHY-60)

Generated by `scripts/fit-chamber-model.py`. Window 2026-04-11 to 2026-08-08,
1-minute samples, ambient from the MUSHY-64 fixture.

## Fitted parameters

| set | Q (m3/h) | quiet samples | F (g/h) | active samples | total |
|---|---|---|---|---|---|
{row('all', r['all'])}
{row('fit (Apr-Jun)', r['fit_apr_jun'])}
{row('validate (Jul-Aug)', r['validate_jul_aug'])}

Air changes per hour = Q / 5.76.

## Exclusions

| reason | minutes |
|---|---|
| total grid minutes | {ex['total']} |
| no temp/RH reading | {ex['no_reading']} |
| no relay state yet | {ex['no_relay']} |
| RH saturated (>= 99.99) | {ex['saturated']} |
| RH step > 3 pct (sensor failover) | {ex['rh_step']} |
| outside ambient coverage | {ex['outside_ambient']} |
| **kept** | **{ex['kept']}** |

## Reading this honestly

Design limitation 5 applies: the chamber-to-ambient gradient is small and noisy,
with standard deviation 2-6x its monthly mean, and in August it points inward
for the majority of hours. Since `Q = flux / gradient`, `Q` is weakly identified
in exactly this validation half. If the two halves disagree, the honest reading
may be "the gradient was unresolvable in Jul-Aug", NOT "the parameters are
season-dependent". Do not present a disagreement as a physical finding without
first ruling out the identifiability problem.

`Q` is the conductance in the UNSATURATED regime -- saturated samples are
excluded per the farmer's 2026-08-09 ruling, and those are the wettest hours.
"""


if __name__ == '__main__':
    raise SystemExit(main())
