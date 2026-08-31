"""MUSHY-150: refit alice..dave with the forced dry-down/wet-up in the training
set, and replay the cycle before and after.

WHAT THIS DOES AND DOES NOT SHOW. The forced cycle is IN-SAMPLE here -- it is in
train and in the early-stopping validation set. So this answers "how well CAN
each structure fit a forced cycle when allowed to", which is a question about
the equations. It does NOT show generalisation: cycles 2 and 3 are the held-out
test for that, and until they land no claim about improvement should travel.

Weight matters because the cycle is tiny: 124 min at a 2 min stride is 40
windows against 3772 from the corpus, i.e. 1%. At natural weight the corpus
simply outvotes it. Duplicating the forced windows is a blunt but exact way to
buy it a real share of the loss.

    .venv/bin/python scripts/bakeoff/refit_with_forced.py --weight 25
"""
import argparse, json, os, sys
import numpy as np
import torch

sys.path.insert(0, 'scripts/bakeoff')
from run import (CANDIDATES, rollout, load, windows, horizon_mse, fit,
                 ah_sat, HORIZONS, CHANNELS, TAU_LO, TAU_HI)

ap = argparse.ArgumentParser()
ap.add_argument('--split', default='inter')
ap.add_argument('--candidates', default='alice,bob,charlie,dave')
ap.add_argument('--steps', type=int, default=1500)
ap.add_argument('--lr', type=float, default=0.05)
ap.add_argument('--seed', type=int, default=0)
ap.add_argument('--weight', type=int, default=25, help='duplication factor for forced windows')
ap.add_argument('--stride', type=float, default=2.0, help='forced-window stride, minutes')
ap.add_argument('--replay', default='scripts/bakeoff/web/replay.json')
ap.add_argument('--out', default='')
a = ap.parse_args()

R = json.load(open(a.replay))
tr_d, te_d, dt_s = load(a.split)
H = max(HORIZONS)
ks = [int(h * 60 / dt_s) for h in HORIZONS]


def forced_windows(stride_min):
    """The forced cycle, packed exactly like corpus windows."""
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
    for c in CHANNELS:                       # inert for alice..dave
        w[c] = torch.zeros(len(st), k, dtype=torch.float64)
    return w


def cat(a_, b_, reps):
    out = {}
    for k_ in a_:
        if not torch.is_tensor(a_[k_]) or k_ not in b_:
            continue
        out[k_] = torch.cat([a_[k_]] + [b_[k_]] * reps, 0)
    return out


allw = windows(tr_d, dt_s, H, seed=a.seed)
n = len(allw['ah'])
days = np.unique(allw['day'].numpy())
rs = np.random.RandomState(1000 + a.seed)
vdays = set(rs.choice(days, max(1, len(days) // 5), replace=False).tolist())
vm = np.array([d in vdays for d in allw['day'].numpy()])
cut = lambda m: {k: (v[m] if torch.is_tensor(v) and len(v) == n else v)
                 for k, v in allw.items() if torch.is_tensor(v)}
tr_c, va_c = cut(~vm), cut(vm)
te = windows(te_d, dt_s, H)
fw = forced_windows(a.stride)

# forced goes into BOTH train and validation: early stopping on a corpus-only
# val set would cut the fit off at the point best for the corpus, actively
# suppressing the thing we are trying to measure.
tr = cat(tr_c, fw, a.weight)
va = cat(va_c, fw, max(1, a.weight // 4))
print(f'split={a.split}  corpus train {len(tr_c["ah"])}  forced {len(fw["ah"])} x{a.weight}'
      f'  -> train {len(tr["ah"])} ({100*len(fw["ah"])*a.weight/len(tr["ah"]):.1f}% forced)')

# full-cycle replay batch (one row, the whole 124 min)
full = {k: v[:1].clone() for k, v in fw.items()}
N = len(R['actual_rh'])
for k_, src in (('duty', R['duty']), ('temp', R['temp']), ('amb_ah', R['amb_ah']),
                ('rh', R['actual_rh'])):
    full[k_] = torch.tensor(src, dtype=torch.float64)[None]
full['ah'] = full['rh'] / 100.0 * ah_sat(full['temp'])
full['ah0'] = full['ah'][:, 0].clone()
full['valid'] = torch.ones(1, N, dtype=torch.bool)
for c in CHANNELS:
    full[c] = torch.zeros(1, N, dtype=torch.float64)

base_te = [float(x) for x in horizon_mse(te['ah0'][:, None].expand_as(te['ah']), te, ks)]
rows = []
for name in a.candidates.split(','):
    print(f'  fitting {name} ...', flush=True)
    m, tau_s, e_tr, e_te, _ = fit(name, tr, te, dt_s, a.steps, a.lr, a.seed, '', 25, va)
    with torch.no_grad():
        pred = (rollout(m, torch.tensor(tau_s), full, dt_s) / 100.0
                * ah_sat(full['temp'])).numpy()[0]
    act = full['ah'].numpy()[0]
    err = pred - act
    prev = next(x for x in R['models'] if x['name'] == name)
    rows.append(dict(name=name, tau_s=tau_s, ah=pred.tolist(),
                     rmse=float(np.sqrt((err ** 2).mean())), bias=float(err.mean()),
                     final_err=float(err[-1]), n_params=sum(p.numel() for p in m.parameters()) + 1,
                     was_rmse=prev['rmse'], was_bias=prev['bias'],
                     skill=[t / b ** .5 for t, b in zip(e_te, base_te)],
                     params={k: (float(v.exp()) if k.startswith('log') else float(v))
                             for k, v in m.state_dict().items()}))
    r = rows[-1]
    print(f'    cycle rmse {r["rmse"]:.3f} (was {r["was_rmse"]:.3f})  '
          f'bias {r["bias"]:+.3f} (was {r["was_bias"]:+.3f})  '
          f'corpus-test worst skill {max(r["skill"]):.3f}  tau {tau_s:.0f}s', flush=True)

if a.out:
    json.dump(dict(weight=a.weight, stride=a.stride, n_forced=len(fw['ah']),
                   n_train=len(tr['ah']), models=rows,
                   t=R['t'], actual_ah=R['actual_ah'], actual_rh=R['actual_rh'],
                   temp=R['temp'], duty=R['duty'], amb_ah=R['amb_ah'],
                   t0_epoch=R['t0_epoch'], dt_s=R['dt_s']), open(a.out, 'w'))
    print(f'wrote {a.out}')
