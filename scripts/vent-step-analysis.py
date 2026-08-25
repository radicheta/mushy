#!/usr/bin/env python3
"""Split the chamber's moisture-loss coefficient into passive + ventilation (MUSHY-72).

The fitted ``moisture_loss_m3_per_h`` (0.9634) silently lumps infiltration,
wall condensation, substrate exchange AND an unrecorded ~15 min/hour vent fan
into one constant. It was fitted at ~25% vent duty, so it is wrong the moment
the vent schedule changes. This recovers the two-term form the model wants:

    Q_eff(t) = Q_passive + Q_vent * vent_state(t)

by measuring it across deliberately alternated vent-ON / vent-OFF blocks.

=== Why this does NOT need the blocks to reach steady state ===

The chamber's open-loop moisture time constant is V/Q, which the MUSHY-60 band
sweep puts at 4.64-8.75 h (5.76 m3 / 0.9634 m3/h = 5.98 h nominal). A "few
hours" block therefore never equilibrates, and any analysis that compares
settled duty between blocks would be reading a transient and calling it a
steady state.

So don't assume equilibrium -- integrate the moisture balance over whatever the
block actually was:

    F * integral(duty dt)  -  V * delta_AH  =  Q_eff * integral(gradient dt)

    => Q_eff = (F * mean_duty - V * dAH_dt) / mean_gradient

The ``V * delta_AH`` term is the moisture that went into or out of STORAGE in
the chamber air rather than being lost. Including it is exactly what removes
the steady-state requirement: a block that is still filling up simply shows a
positive dAH_dt and gets credited for it. Blocks only need to be long enough
that noise in delta_AH is small against the integral -- a few hours is ample.

=== What is measured well, and what is not ===

F carries -14%/+23% uncertainty, and it multiplies mean_duty, so ABSOLUTE
Q_passive and Q_vent inherit that. But both blocks share the same F, so the
RATIO Q_vent / Q_passive -- "how much of the chamber's moisture loss is the
fan?", which is the actual question -- is insensitive to it. Report both, and
trust the ratio more than the absolutes.

=== Inputs ===

A schedule JSON: [{"start": "...Z", "end": "...Z", "vent": "on"|"off"}, ...]
Times are the ACTUAL switch times, not the planned ones.

Ambient absolute humidity comes from the MUSHY-64 AmbientSeries fixture, which
must COVER the experiment window -- it is a fixture, not a live feed, and its
coverage ended 2026-08-08. Run scripts/fetch-ambient-weather.py for the new
dates first; this script refuses to guess rather than silently step-holding the
last available hour across days of experiment.

Run:  python3 scripts/vent-step-analysis.py --schedule vent-blocks.json
      python3 scripts/vent-step-analysis.py --self-check
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / 'src' / 'chambers' / 'fc-core'))

from fc_core.sim.chamber_model import ChamberParams                  # noqa: E402
from fc_core.sim.psychrometrics import (CHAMBER_VOLUME_M3,           # noqa: E402
                                        absolute_humidity_g_m3)

CONTAINER = 'mushy-timescale-1'
PARAMS = ChamberParams()
F_G_PER_H = PARAMS.fill_g_per_h
V_M3 = CHAMBER_VOLUME_M3

# Discard the first slice of each block: the vent's own transport lag plus the
# controller's dead time (360 s fitted) mean the first minutes belong to the
# previous state. Short enough not to eat a 4 h block, long enough to clear it.
SETTLE_MINUTES = 20


def psql(sql: str) -> str:
    # See build-control-epochs.py: parallel workers blow out the container's
    # /dev/shm on these row counts and the error blames disk space.
    full = f'set max_parallel_workers_per_gather=0; {sql}'
    return subprocess.run(
        ['docker', 'exec', CONTAINER, 'psql', '-U', 'postgres', '-d', 'postgres',
         '-At', '-F', ',', '-c', full],
        capture_output=True, text=True, check=True).stdout


def load_chamber_minutes(start: datetime, end: datetime) -> list:
    """(minute, mean duty, mean RH pct, mean temp C) over [start, end)."""
    sql = f"""
        select to_char(date_trunc('minute', time) at time zone 'UTC',
                       'YYYY-MM-DD"T"HH24:MI:SS') as m,
               avg(value) filter (where topic = 'fc.humidifier_duty') as duty,
               avg(value) filter (where topic = 'fc.humidity')        as rh,
               avg(value) filter (where topic = 'fc.temperature')     as temp
        from telemetry
        where topic in ('fc.humidifier_duty', 'fc.humidity', 'fc.temperature')
          and time >= '{start.isoformat()}' and time < '{end.isoformat()}'
        group by 1 order by 1
    """
    rows = []
    for line in psql(sql).strip().splitlines():
        if not line:
            continue
        m, duty, rh, temp = line.split(',')
        if duty and rh and temp:
            rows.append((datetime.strptime(m, '%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc),
                         float(duty), float(rh), float(temp)))
    return rows


def block_q_eff(minutes: list, ambient_ah) -> dict:
    """Effective moisture-loss coefficient over one block, via the balance.

    ``ambient_ah`` is a callable taking a datetime and returning g/m3.
    """
    if len(minutes) < 2:
        return {'error': 'not enough samples'}

    usable = minutes[SETTLE_MINUTES:]
    if len(usable) < 2:
        return {'error': f'block shorter than the {SETTLE_MINUTES}-min settle discard'}

    ah_in = [absolute_humidity_g_m3(temp, rh) for _, _, rh, temp in usable]
    gradients = [ah - ambient_ah(ts)
                 for ah, (ts, _, _, _) in zip(ah_in, usable)]

    hours = (usable[-1][0] - usable[0][0]).total_seconds() / 3600.0
    if hours <= 0:
        return {'error': 'zero-length block'}

    mean_duty = sum(d for _, d, _, _ in usable) / len(usable)
    mean_gradient = sum(gradients) / len(gradients)
    # Storage term: moisture that went into the air rather than being lost.
    # Endpoints are averaged over 5 min to keep sensor noise out of a difference.
    edge = min(5, len(ah_in) // 2)
    d_ah = (sum(ah_in[-edge:]) / edge) - (sum(ah_in[:edge]) / edge)
    d_ah_dt = d_ah / hours

    if abs(mean_gradient) < 1e-6:
        return {'error': 'gradient ~0: chamber and ambient at the same AH'}

    q_eff = (F_G_PER_H * mean_duty - V_M3 * d_ah_dt) / mean_gradient
    return {
        'hours': round(hours, 2), 'samples': len(usable),
        'mean_duty': round(mean_duty, 4),
        'mean_gradient_g_m3': round(mean_gradient, 4),
        'd_ah_dt_g_m3_per_h': round(d_ah_dt, 4),
        'storage_share': round(abs(V_M3 * d_ah_dt) / max(abs(F_G_PER_H * mean_duty), 1e-9), 3),
        'q_eff_m3_per_h': round(q_eff, 4),
    }


def summarise(blocks: list) -> dict:
    """Q_passive from the OFF blocks, Q_vent from the ON-minus-OFF difference."""
    def qs(state):
        return [b['result']['q_eff_m3_per_h'] for b in blocks
                if b['vent'] == state and 'q_eff_m3_per_h' in b['result']]

    on, off = qs('on'), qs('off')
    if not on or not off:
        return {'error': f'need at least one usable block of each state '
                         f'(on={len(on)}, off={len(off)})'}

    def mean(xs):
        return sum(xs) / len(xs)

    def spread(xs):
        return (max(xs) - min(xs)) if len(xs) > 1 else None

    q_passive, q_on = mean(off), mean(on)
    q_vent = q_on - q_passive
    return {
        'q_passive_m3_per_h': round(q_passive, 4),
        'q_vented_m3_per_h': round(q_on, 4),
        'q_vent_m3_per_h': round(q_vent, 4),
        'vent_share_of_vented_loss': round(q_vent / q_on, 3) if q_on else None,
        'n_off': len(off), 'n_on': len(on),
        'off_spread': spread(off), 'on_spread': spread(on),
        'fitted_lumped_q': PARAMS.moisture_loss_m3_per_h,
        'note': 'Absolute values inherit F\'s -14%/+23% uncertainty; the ratio '
                'q_vent/q_vented does not, because both states share F.',
    }


# --------------------------------------------------------------------------
# self-check: recover a KNOWN Q_vent from synthetic data
# --------------------------------------------------------------------------

def _synthetic_block(q_true, hours, ambient, temp_c=10.0, rh0=90.0, dt_min=1):
    """Simulate the balance forward at a known q_true; return minute rows.

    Deliberately NOT started at equilibrium -- the whole point is that the
    estimator must work on a block that is still drifting.
    """
    rows = []
    ah = absolute_humidity_g_m3(temp_c, rh0)
    t0 = datetime(2026, 9, 1, tzinfo=timezone.utc)
    duty = 0.30
    for i in range(int(hours * 60 / dt_min)):
        ts = t0 + timedelta(minutes=i * dt_min)
        loss = q_true * (ah - ambient)
        fill = F_G_PER_H * duty
        ah += (fill - loss) / V_M3 * (dt_min / 60.0)
        rh = 100.0 * ah / absolute_humidity_g_m3(temp_c, 100.0)
        rows.append((ts, duty, rh, temp_c))
    return rows


def self_check() -> int:
    ambient_val = 6.0
    ok = True
    print('Recovering a known Q from synthetic, deliberately non-equilibrated blocks:')
    for q_true in (0.60, 0.96, 1.80):
        rows = _synthetic_block(q_true, hours=4, ambient=ambient_val)
        got = block_q_eff(rows, lambda _ts: ambient_val)
        q_hat = got['q_eff_m3_per_h']
        err = abs(q_hat - q_true) / q_true
        flag = 'ok  ' if err < 0.02 else 'FAIL'
        if err >= 0.02:
            ok = False
        print(f'  {flag} q_true={q_true:.2f}  q_est={q_hat:.4f}  '
              f'err={err*100:.2f}%  storage_share={got["storage_share"]}')

    # And the thing the experiment actually claims: the DIFFERENCE.
    off = _synthetic_block(0.60, 4, ambient_val)
    on = _synthetic_block(1.50, 4, ambient_val)
    blocks = [{'vent': 'off', 'result': block_q_eff(off, lambda _t: ambient_val)},
              {'vent': 'on', 'result': block_q_eff(on, lambda _t: ambient_val)}]
    s = summarise(blocks)
    err = abs(s['q_vent_m3_per_h'] - 0.90) / 0.90
    flag = 'ok  ' if err < 0.02 else 'FAIL'
    if err >= 0.02:
        ok = False
    print(f'  {flag} q_vent true=0.90  est={s["q_vent_m3_per_h"]}  err={err*100:.2f}%')

    # A block that ignores storage would be badly wrong -- prove the term earns
    # its place rather than asserting it.
    naive = (F_G_PER_H * 0.30) / (
        sum(absolute_humidity_g_m3(10.0, rh) - ambient_val for _, _, rh, _ in off)
        / len(off))
    print(f'\n  for contrast, ignoring the storage term on the same OFF block: '
          f'q={naive:.4f} vs true 0.60 ({abs(naive-0.60)/0.60*100:.0f}% off)')
    print('\nSELF-CHECK', 'PASSED' if ok else 'FAILED')
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--schedule', help='JSON list of {start, end, vent} blocks')
    ap.add_argument('--self-check', action='store_true',
                    help='validate the estimator against synthetic data')
    args = ap.parse_args()

    if args.self_check:
        return self_check()
    if not args.schedule:
        ap.error('need --schedule or --self-check')

    schedule = json.loads(Path(args.schedule).read_text())
    from fc_core.sim.ambient import AmbientSeries
    ambient = AmbientSeries.from_csv()

    def ambient_ah(when: datetime) -> float:
        # .at() raises outside its covered window rather than extrapolating,
        # which is what we want: an uncovered experiment should fail loudly,
        # not quietly borrow the last hour it happens to have.
        s = ambient.at(when)
        return absolute_humidity_g_m3(s.temp_c, s.rh_pct)

    span = [datetime.fromisoformat(e['start'].replace('Z', '+00:00')) for e in schedule]
    span += [datetime.fromisoformat(e['end'].replace('Z', '+00:00')) for e in schedule]
    if min(span) < ambient.start or max(span) > ambient.end:
        print(f'ERROR: ambient fixture covers {ambient.start.isoformat()}..'
              f'{ambient.end.isoformat()}, experiment spans '
              f'{min(span).isoformat()}..{max(span).isoformat()}.\n'
              f'Run scripts/fetch-ambient-weather.py for the experiment dates first.',
              file=sys.stderr)
        return 2

    blocks = []
    for entry in schedule:
        start = datetime.fromisoformat(entry['start'].replace('Z', '+00:00'))
        end = datetime.fromisoformat(entry['end'].replace('Z', '+00:00'))
        rows = load_chamber_minutes(start, end)
        blocks.append({'vent': entry['vent'], 'start': entry['start'],
                       'result': block_q_eff(rows, ambient_ah)})

    print(f'{"block":<22} {"vent":<5} {"h":>5} {"duty":>7} {"grad":>7} '
          f'{"dAH/dt":>8} {"store":>6} {"Q_eff":>7}')
    for b in blocks:
        r = b['result']
        if 'error' in r:
            print(f'{b["start"]:<22} {b["vent"]:<5}  -- {r["error"]}')
            continue
        print(f'{b["start"]:<22} {b["vent"]:<5} {r["hours"]:>5} {r["mean_duty"]:>7} '
              f'{r["mean_gradient_g_m3"]:>7} {r["d_ah_dt_g_m3_per_h"]:>8} '
              f'{r["storage_share"]:>6} {r["q_eff_m3_per_h"]:>7}')

    print()
    print(json.dumps(summarise(blocks), indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
