"""MUSHY-150: pull the forced dry-down/wet-up cycles out of Timescale.

Three cycles have run on fc1 and only ONE was ever extracted. forced_only.py
was therefore fitting on 125 min containing a single duty transition, which is
not enough to determine a model -- it came back worse than persistence, with
all four candidates agreeing on a ~700 s dead time against a physical ~140 s.
Four structures agreeing on one absurd number is unconstrained data, not a
shared modelling error.

Cycle boundaries come from fc1's own /home/ubuntu/drywet-cycle.log, which
stamps every phase with the label it was launched under.

    .venv/bin/python scripts/bakeoff/extract_cycles.py --list
    .venv/bin/python scripts/bakeoff/extract_cycles.py --out scripts/bakeoff/data
"""
import argparse, json, subprocess, sys
import numpy as np

sys.path.insert(0, 'src/chambers/fc-core')
from fc_core.sim.psychrometrics import absolute_humidity_g_m3

DT = 10.0
# label -> (start, end). end=None means "still running, take what exists".
# Read off fc1:/home/ubuntu/drywet-cycle.log on 2026-09-01.
CYCLES = {
    'cycle1b-afternoon': ('2026-08-31T19:12:39Z', '2026-08-31T21:23:32Z'),
    'cycle2-night':      ('2026-09-01T01:00:22Z', '2026-09-01T05:10:19Z'),
    'cycle3-morning':    ('2026-09-01T12:00:20Z', None),
}


def q(sql):
    out = subprocess.run(
        ['docker', 'exec', 'mushy-timescale-1', 'psql', '-U', 'postgres',
         '-d', 'postgres', '-At', '-F', '\t', '-c',
         'SET max_parallel_workers_per_gather=0; ' + sql],
        capture_output=True, text=True, check=True).stdout
    rows = [l.split('\t') for l in out.splitlines() if l.strip()]
    if not rows:
        return np.zeros(0), np.zeros(0)
    a = np.array(rows, dtype=float)
    return a[:, 0], a[:, 1]


def series(topic, t0, t1, table='telemetry'):
    end = f"and time < '{t1}' " if t1 else ''
    return q(f"select extract(epoch from time), value from {table} "
             f"where topic='{topic}' and time >= '{t0}' {end}order by time")


def zoh(t, v, grid, default):
    if len(t) == 0:
        return np.full(len(grid), default)
    i = np.searchsorted(t, grid, side='right') - 1
    out = np.where(i >= 0, v[np.clip(i, 0, len(v) - 1)], default)
    return out


def one(label, t0, t1):
    rh_t, rh_v = series('fc.humidity', t0, t1)
    tp_t, tp_v = series('fc.temperature', t0, t1)
    du_t, du_v = series('fc.humidifier', t0, t1)
    wt_t, wt_v = series('weather.temperature', t0, t1, 'weather')
    wh_t, wh_v = series('weather.humidity', t0, t1, 'weather')
    if len(rh_t) == 0:
        print(f'  {label}: NO TELEMETRY in range'); return None
    g0, g1 = max(rh_t[0], tp_t[0]), min(rh_t[-1], tp_t[-1])
    grid = np.arange(g0, g1, DT)
    rh = np.interp(grid, rh_t, rh_v)
    tp = np.interp(grid, tp_t, tp_v)
    duty = zoh(du_t, du_v, grid, 0.0)           # relay state is a switch: HOLD
    # Ambient is INTERPOLATED, not held. prep.py builds the corpus with
    # interp_gap() for amb_ah / ambient T / ambient RH, and holding them here
    # would mean the forced cycles were prepared differently from the corpus
    # they are scored against -- the exact confound prep.py's docstring exists
    # to prevent. The weather feed is hourly, so a hold also puts a 1 h
    # staircase into a driver that physically varies smoothly, which is
    # indistinguishable from a real step to anything fitting a step response.
    wt = np.interp(grid, wt_t, wt_v) if len(wt_t) else np.full(len(grid), 15.0)
    wh = np.interp(grid, wh_t, wh_v) if len(wh_t) else np.full(len(grid), 70.0)
    amb = np.array([absolute_humidity_g_m3(a, b / 100.0) for a, b in zip(wt, wh)])
    rh_pct = rh * 100.0 if np.nanmax(rh) <= 1.5 else rh
    ch = int((np.diff(duty) != 0).sum())
    print(f'  {label:20s} {len(grid):5d} samples  {len(grid)*DT/60:6.1f} min  '
          f'RH {rh_pct.min():5.1f}-{rh_pct.max():5.1f}  T {tp.min():5.2f}-{tp.max():5.2f}  '
          f'duty levels {len(set(np.round(duty,2)))}  transitions {ch}')
    return dict(label=label, t=grid.tolist(), actual_rh=rh_pct.tolist(),
                temp=tp.tolist(), duty=duty.tolist(), amb_ah=amb.tolist())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--out', default='')
    a = ap.parse_args()
    print(f'{"cycle":20s} {"samples":>7s}  {"duration":>10s}  RH range      T range      excitation')
    got = [c for c in (one(k, *v) for k, v in CYCLES.items()) if c]
    if a.out:
        p = f'{a.out}/cycles.json'
        json.dump(got, open(p, 'w'))
        print(f'\nwrote {p}  ({len(got)} cycles, '
              f'{sum(len(c["t"]) for c in got)*DT/3600:.1f} h total)')


if __name__ == '__main__':
    main()
