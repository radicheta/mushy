"""MUSHY-150: fit on the FORCED cycle ONLY, then test on the closed-loop corpus.

THE POINT (Santi 2026-09-01): in closed loop, duty is not an independent input.
The controller raises duty BECAUSE RH fell, so "duty causes RH to rise" and "low
RH causes duty to rise" are not separable in five months of corpus. Every number
on this ticket so far was fitted through that confound. The forced cycle is the
only data where duty was set independently of the chamber's state, so it is the
only data where cause and effect are actually distinguishable.

The trade is brutal and has to be stated: 124 min against five months, and only
TWO duty levels (0.0 and 1.0), over one temperature span (16.9-18.3 C), at one
time of day, on one date. So this cannot identify anything that varies with
temperature, season, or duty level. What it CAN identify is the causal chain the
corpus confounds: gain F, loss Q, and the dead time.

Read it as: does a model fitted on 2 h of clean cause-effect predict five months
of closed-loop operation as well as one fitted on the five months? If yes, the
corpus was adding confounding, not information.

NO HONEST VALIDATION SET EXISTS. One cycle cannot be split -- a temporal split
puts the dry-down in train and the wet-up in validation, which is not a
validation set, it is a different experiment. Early stopping therefore runs on
the forced windows themselves (in-sample, so it only detects convergence). The
HELD-OUT number is the corpus test set, which is what gets reported.

    .venv/bin/python scripts/bakeoff/forced_only.py --candidates alice,charlie
"""
import argparse, json, sys
import numpy as np
import torch

sys.path.insert(0, 'scripts/bakeoff')
from run import (CHANNELS, HORIZONS, ah_sat, fit, horizon_mse, load, rollout,
                 windows)

ap = argparse.ArgumentParser()
ap.add_argument('--candidates', default='alice,charlie,gary,irving')
ap.add_argument('--steps', type=int, default=3000)
ap.add_argument('--lr', type=float, default=0.05)
ap.add_argument('--seed', type=int, default=0)
ap.add_argument('--stride', type=float, default=1.0, help='forced-window stride, min')
ap.add_argument('--dead-time-s', type=float, default=0.0)
ap.add_argument('--replay', default='scripts/bakeoff/web/replay.json')
ap.add_argument('--out', default='')
a = ap.parse_args()

R = json.load(open(a.replay))
H = max(HORIZONS)


def forced_windows(stride_min, dt_s):
    """The forced cycle, packed exactly like corpus windows (from
    refit_with_forced.py, which already got this right)."""
    rh = torch.tensor(R['actual_rh'], dtype=torch.float64)
    T = torch.tensor(R['temp'], dtype=torch.float64)
    duty = torch.tensor(R['duty'], dtype=torch.float64)
    amb = torch.tensor(R['amb_ah'], dtype=torch.float64)
    ah = rh / 100.0 * ah_sat(T)
    n, k, s = len(rh), int(H * 60 / dt_s), int(stride_min * 60 / dt_s)
    st = list(range(0, n - k, s))
    take = lambda v: torch.stack([v[i:i + k] for i in st])
    w = {'duty': take(duty), 'temp': take(T), 'rh': take(rh), 'amb_ah': take(amb),
         'ah': take(ah), 'ah0': torch.tensor([ah[i] for i in st], dtype=torch.float64),
         'valid': torch.ones(len(st), k, dtype=torch.bool)}
    for c in CHANNELS:              # inert for the physics candidates
        w[c] = torch.zeros(len(st), k, dtype=torch.float64)
    return w


def main():
    _, te_i, dt_s = load('inter')
    _, te_c, _ = load('chrono')
    te = {'inter': windows(te_i, dt_s, H), 'chrono': windows(te_c, dt_s, H)}
    ks = [int(h * 60 / dt_s) for h in HORIZONS]
    base = {s: [float(x) ** .5 for x in horizon_mse(
        w['ah0'][:, None].expand_as(w['ah']), w, ks)] for s, w in te.items()}

    fw = forced_windows(a.stride, dt_s)
    print(f'TRAIN: forced cycle only -- {len(fw["ah"])} windows from '
          f'{len(R["actual_rh"])*dt_s/60:.0f} min, duty levels '
          f'{sorted(set(np.round(R["duty"], 2)))[:6]}...')
    print(f'TEST : corpus, inter {len(te["inter"]["ah"])} windows / '
          f'chrono {len(te["chrono"]["ah"])} windows\n')

    rows = []
    for name in a.candidates.split(','):
        model, tau_s, e_tr, _, dead_s = fit(
            name, fw, fw, dt_s, a.steps, a.lr, a.seed, va=fw,
            dead_time_s=a.dead_time_s)
        r = dict(candidate=name, seed=a.seed, trained_on='forced_cycle_only',
                 tau_s=tau_s, dead_time_s=dead_s, forced_err=e_tr)
        for s, w in te.items():
            with torch.no_grad():
                ah = rollout(model, torch.tensor(tau_s), w, dt_s) / 100.0 * ah_sat(w['temp'])
            e = [float(x) ** .5 for x in horizon_mse(ah, w, ks)]
            sk = [x / b for x, b in zip(e, base[s])]
            r[f'{s}_skill'] = sk
            r[f'{s}_skill_mean'] = sum(sk) / len(sk)
        rows.append(r)
        print(f'  {name:9s} tau={tau_s:6.0f}s dead={dead_s:6.0f}s   '
              f'inter {r["inter_skill_mean"]:.4f}   chrono {r["chrono_skill_mean"]:.4f}',
              flush=True)

    print('\n  (compare: fitted ON the corpus, chrono -- alice 0.518, irving 0.519,')
    print('   charlie 0.535, gary 0.541. Lower is better; 1.0 = persistence.)')
    if a.out:
        json.dump(rows, open(a.out, 'w'), indent=1)
        print(f'wrote {a.out}')


if __name__ == '__main__':
    main()
