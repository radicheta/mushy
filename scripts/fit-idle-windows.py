#!/usr/bin/env python3
"""Identify the moisture-loss coefficient Q from IDLE (humidifier-off) windows.

=== Why idle windows ===

The chamber balance is

    V * d(AH_in)/dt = F * duty - Q * (AH_in - AH_out)

With ``duty == 0`` the fill term vanishes identically and this collapses to a
one-parameter model:

    d(AH_in)/dt = -(Q/V) * (AH_in - AH_out)

That is the cleanest identification data this chamber can produce. No
actuator, no PWM quantisation, no control law, no pipe transit, no dead time
(the delay queue only carries duty, which is zero throughout), and no
correlation between the input and the state. It is a straight line through
the origin: regress d(AH_in)/dt against the gradient and the slope IS -Q/V.

The MUSHY-60 fit had to identify Q and F jointly from ACTIVE data, where duty
and gradient are correlated by the control loop itself, and it came out badly
conditioned: the branch's own sweep put Q in [0.658, 1.242], a 1.9x span, and
declared only the ratio F/Q well identified. Idle windows break that
degeneracy for Q.

=== What this CANNOT do ===

F is not identifiable here, at all. It multiplies duty, and duty is zero by
construction. This script deliberately does not report an F. Anyone wanting
one needs active windows, and should not assume the old F survives a change
in Q -- the shipped F was set as Q * (F/Q) precisely so that steady state
matched the identified ratio, so moving Q moves F with it if that ratio is
still believed.

Q is also NOT a physical air-exchange rate (see ChamberParams' docstring): it
lumps infiltration, wall condensation, substrate exchange and an unrecorded
~15 min/hour vent fan. That last one is the main reason to expect genuine
window-to-window spread rather than one true value, and it is unrecorded, so
this script cannot control for it. Spread is reported, not averaged away.

=== Method ===

* Idle windows come from fc.humidifier EDGES: each OFF edge opens a window,
  the next ON edge closes it. Edge-only telemetry, so state is held forward.
* Telemetry is aggregated to 1-minute means in SQL (1 Hz over four months is
  not worth pulling), then AH_in is computed per minute from RH + temp.
* AH_out comes from the AmbientSeries fixture, hourly, interpolated.
* dAH/dt uses central differences over a +/-SMOOTH_MIN window to keep sensor
  noise out of the derivative.
* Q is fitted per window by least squares THROUGH THE ORIGIN on
  y = dAH/dt vs x = -(AH_in - AH_out), then reported as a distribution.

Exclusions, each counted and printed rather than silently applied:
* saturated samples (RH >= SAT_RH) -- sensor membrane saturation, per the
  farmer's 2026-08-09 ruling, same as the MUSHY-60 fit
* windows shorter than MIN_IDLE_MIN
* windows whose gradient never exceeds MIN_GRAD (nothing to decay)
* minutes with no telemetry
"""
import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / 'src' / 'chambers' / 'fc-core'))

from fc_core.sim.ambient import AmbientSeries                      # noqa: E402
from fc_core.sim.psychrometrics import (CHAMBER_VOLUME_M3,         # noqa: E402
                                        absolute_humidity_g_m3)

CONTAINER = 'mushy-timescale-1'
SHIPPED_Q = 0.9634
SAT_RH = 99.9
MIN_IDLE_MIN = 60
MIN_GRAD = 0.5      # g/m3; below this the decay is inside sensor noise
SMOOTH_MIN = 5      # half-width, minutes, for the central difference


def psql(sql: str) -> str:
    return subprocess.run(
        ['docker', 'exec', CONTAINER, 'psql', '-U', 'postgres', '-d', 'postgres',
         '-At', '-F', ',', '-c', 'SET max_parallel_workers_per_gather=0;',
         '-c', sql],
        capture_output=True, text=True, check=True).stdout


def load_edges(start: str, end: str):
    out = psql(f"""
        SELECT extract(epoch from time)::bigint, value FROM telemetry
        WHERE topic='fc.humidifier' AND time >= '{start}' AND time < '{end}'
        ORDER BY time""")
    rows = []
    for line in out.strip().splitlines():
        if not line or line == 'SET':
            continue
        t, v = line.split(',')
        rows.append((int(t), float(v)))
    return rows


def load_minutes(start: str, end: str):
    """1-minute means of RH and chamber temp, keyed by epoch-minute."""
    out = psql(f"""
        SELECT extract(epoch from date_trunc('minute', time))::bigint AS m,
               avg(value) FILTER (WHERE topic='fc.humidity')    AS rh,
               avg(value) FILTER (WHERE topic='fc.temperature') AS t
        FROM telemetry
        WHERE topic IN ('fc.humidity','fc.temperature')
          AND time >= '{start}' AND time < '{end}'
        GROUP BY 1 ORDER BY 1""")
    grid = {}
    for line in out.strip().splitlines():
        if not line or line == 'SET':
            continue
        parts = line.split(',')
        if len(parts) != 3 or not parts[1] or not parts[2]:
            continue
        grid[int(parts[0])] = (float(parts[1]), float(parts[2]))
    return grid


def idle_windows(edges, t_start, t_end):
    """Spans during which the relay was held OFF, from edge telemetry."""
    wins, open_at = [], t_start          # assume OFF before the first edge
    for t, v in edges:
        if v >= 0.5:                     # ON: closes any open idle span
            if open_at is not None and t > open_at:
                wins.append((open_at, t))
            open_at = None
        else:                            # OFF: opens one
            if open_at is None:
                open_at = t
    if open_at is not None and t_end > open_at:
        wins.append((open_at, t_end))
    return wins


def fit_window(w0, w1, grid, ambient):
    """Least squares through the origin: dAH/dt = -(Q/V) * gradient."""
    mins = range(w0 - w0 % 60, w1, 60)
    ah_in, grad, keep = {}, {}, []
    n_sat = n_missing = 0
    for m in mins:
        s = grid.get(m)
        if s is None:
            n_missing += 1
            continue
        rh, temp = s
        if rh >= SAT_RH:
            n_sat += 1
            continue
        when = datetime.fromtimestamp(m, tz=timezone.utc)
        if when > ambient.end:
            return None, 'past ambient coverage'
        a = ambient.at(when)
        ah_in[m] = absolute_humidity_g_m3(temp, rh)
        grad[m] = ah_in[m] - absolute_humidity_g_m3(a.temp_c, a.rh_pct)
        keep.append(m)

    if len(keep) < 2 * SMOOTH_MIN + 10:
        return None, f'too few usable minutes ({len(keep)})'
    if max(grad[m] for m in keep) < MIN_GRAD:
        return None, f'gradient never exceeds {MIN_GRAD}'

    num = den = 0.0
    n_pts = 0
    for i in range(SMOOTH_MIN, len(keep) - SMOOTH_MIN):
        a, b = keep[i - SMOOTH_MIN], keep[i + SMOOTH_MIN]
        if b - a != 2 * SMOOTH_MIN * 60:      # a telemetry hole; skip the point
            continue
        dah_dt = (ah_in[b] - ah_in[a]) / ((b - a) / 3600.0)   # g/m3 per hour
        x = -grad[keep[i]]
        num += x * dah_dt
        den += x * x
        n_pts += 1
    if n_pts < 10 or den <= 0:
        return None, f'too few clean derivative points ({n_pts})'

    slope = num / den                      # = Q/V
    q = slope * CHAMBER_VOLUME_M3
    # R^2 through the origin
    ss_res = ss_tot = 0.0
    for i in range(SMOOTH_MIN, len(keep) - SMOOTH_MIN):
        a, b = keep[i - SMOOTH_MIN], keep[i + SMOOTH_MIN]
        if b - a != 2 * SMOOTH_MIN * 60:
            continue
        y = (ah_in[b] - ah_in[a]) / ((b - a) / 3600.0)
        ss_res += (y - slope * -grad[keep[i]]) ** 2
        ss_tot += y * y
    return dict(q=q, n=n_pts, r2=1.0 - ss_res / ss_tot if ss_tot else float('nan'),
                hours=(w1 - w0) / 3600.0, sat=n_sat, missing=n_missing,
                grad0=grad[keep[0]], grad1=grad[keep[-1]],
                start=datetime.fromtimestamp(w0, tz=timezone.utc)), None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--start', default='2026-04-11')
    ap.add_argument('--end', default='2026-08-31')
    ap.add_argument('--ambient-fixture', default=None)
    ap.add_argument('--min-idle-min', type=int, default=MIN_IDLE_MIN)
    ap.add_argument('--min-r2', type=float, default=0.70,
                    help='report a second summary over only the windows where '
                         'the one-parameter decay actually describes the data. '
                         'A low R2 does not mean a noisy Q, it means the model '
                         'is the wrong shape for that window -- averaging those '
                         'in produces a number with no meaning.')
    args = ap.parse_args()

    ambient = (AmbientSeries.from_csv(args.ambient_fixture)
               if args.ambient_fixture else AmbientSeries.from_csv())

    t_start = int(datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc).timestamp())
    t_end = int(datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc).timestamp())

    print(f'loading telemetry {args.start} .. {args.end} ...', file=sys.stderr)
    edges = load_edges(args.start, args.end)
    grid = load_minutes(args.start, args.end)
    print(f'{len(edges)} relay edges, {len(grid)} telemetry minutes', file=sys.stderr)

    wins = [w for w in idle_windows(edges, t_start, t_end)
            if (w[1] - w[0]) >= args.min_idle_min * 60]
    print(f'{len(wins)} idle windows >= {args.min_idle_min} min\n', file=sys.stderr)

    fits, rejects = [], {}
    for w0, w1 in wins:
        r, why = fit_window(w0, w1, grid, ambient)
        if r:
            fits.append(r)
        else:
            rejects[why] = rejects.get(why, 0) + 1

    print(f'{"window start (UTC)":22s} {"hours":>6s} {"Q":>7s} {"R2":>6s} '
          f'{"grad0":>6s} {"grad1":>6s} {"pts":>5s}')
    for r in sorted(fits, key=lambda r: r['start']):
        print(f'{r["start"].strftime("%Y-%m-%d %H:%M"):22s} {r["hours"]:6.2f} '
              f'{r["q"]:7.3f} {r["r2"]:6.3f} {r["grad0"]:6.2f} {r["grad1"]:6.2f} '
              f'{r["n"]:5d}')

    if not fits:
        print('\nno usable idle windows', file=sys.stderr)
        return 1

    def summarise(rs, title):
        if not rs:
            print(f'\n{title}: none')
            return
        q = sorted(r['q'] for r in rs)
        k = len(q)
        med = q[k // 2] if k % 2 else 0.5 * (q[k // 2 - 1] + q[k // 2])
        tw = sum(r['hours'] for r in rs)
        print(f'\n{title}: {k} windows, {tw:.1f} idle hours')
        print(f'  Q median {med:.3f}   range {q[0]:.3f} .. {q[-1]:.3f}   '
              f'vs shipped {SHIPPED_Q:.4f} ({med / SHIPPED_Q:.2f}x)')
        print(f'  implied tau = V/Q {CHAMBER_VOLUME_M3 / med:.2f} h'
              if med > 0 else '  implied tau: undefined (negative Q)')
        return med

    good = [r for r in fits if r['r2'] >= args.min_r2]
    bad = [r for r in fits if r['r2'] < args.min_r2]
    rose = [r for r in fits if r['grad1'] > r['grad0']]
    summarise(fits, 'ALL windows (includes ones the model does not describe)')
    summarise(good, f'WELL-FIT windows (R2 >= {args.min_r2})')
    summarise(bad, f'POORLY-FIT windows (R2 < {args.min_r2})')
    print(f'\n  {len(rose)} of {len(fits)} windows GAINED gradient while idle '
          f'(chamber got wetter with the humidifier off -- not a decay at all)')
    if good:
        hrs = sorted(r['hours'] for r in good)
        print(f'  well-fit window length: median {hrs[len(hrs) // 2]:.2f} h, '
              f'max {hrs[-1]:.2f} h')
    if bad:
        hrs = sorted(r['hours'] for r in bad)
        print(f'  poorly-fit window length: median {hrs[len(hrs) // 2]:.2f} h, '
              f'max {hrs[-1]:.2f} h')

    qs = sorted(r['q'] for r in fits)
    n = len(qs)
    med = qs[n // 2] if n % 2 else 0.5 * (qs[n // 2 - 1] + qs[n // 2])
    # duration-weighted, since a 6 h window constrains Q far better than a 1 h one
    tw = sum(r['hours'] for r in fits)
    wmean = sum(r['q'] * r['hours'] for r in fits) / tw

    print(f'\n{n} windows fitted, {tw:.1f} idle hours total')
    print(f'  Q median            {med:.3f} m3/h')
    print(f'  Q duration-weighted {wmean:.3f} m3/h')
    print(f'  Q range             {qs[0]:.3f} .. {qs[-1]:.3f}')
    print(f'  shipped Q           {SHIPPED_Q:.4f}  -> median is {med / SHIPPED_Q:.2f}x')
    print(f'  implied tau = V/Q   {CHAMBER_VOLUME_M3 / med:.2f} h '
          f'(shipped {CHAMBER_VOLUME_M3 / SHIPPED_Q:.2f} h)')
    if rejects:
        print('\nrejected windows:')
        for why, k in sorted(rejects.items(), key=lambda kv: -kv[1]):
            print(f'  {k:4d}  {why}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
