"""MUSHY-150: what do the TRIVIAL predictors score? A structural bake-off only
means something if the candidates clear the models that contain no chamber
physics at all. If "nothing happens today" already scores near the candidates,
the corpus has no dynamic range to rank structures with.

    .venv/bin/python scripts/bakeoff/baselines.py [inter|chrono]
"""
import sys
import torch

sys.path.insert(0, 'scripts/bakeoff')
from run import load, score, ah_to_rh

split = sys.argv[1] if len(sys.argv) > 1 else 'inter'
tr, te, dt_s = load(split)


def rmse(pred, b=None):
    b = b or te
    return float(score(pred, b)[0].mean())


T, rh, m = te['temp'], te['rh'], te['valid']
first = rh[:, :1].expand_as(rh)                       # RH at midnight, held
ah_const = ah_to_rh(T, te['ah0'][:, None].expand_as(T))
mean_day = ((rh * m).sum(1) / m.sum(1).clamp(min=1))[:, None].expand_as(rh)

print(f'split={split}  test {len(rh)} days\n')
print('  TRIVIAL PREDICTORS (no humidifier, no moisture balance)')
print(f'    hold RH at midnight        {rmse(first):6.3f}')
print(f'    hold AH constant           {rmse(ah_const):6.3f}   <- RH moves only with temperature')
print(f'    per-day mean RH (ORACLE)   {rmse(mean_day):6.3f}   <- cheats, uses the answer')
print(f'    global mean RH (ORACLE)    {rmse(torch.full_like(rh, float((rh*m).sum()/m.sum()))):6.3f}')
import numpy as np
from run import ah_sat
s_fit = float((rh/100*ah_sat(T)*ah_sat(T)*m).sum() / ((ah_sat(T)**2*m).sum()))
print(f'    AH = {s_fit:.3f}*AH_sat(T)      {rmse(ah_to_rh(T, s_fit*ah_sat(T))):6.3f}   <- ONE parameter, no duty')
print(f'\n  spread of the recorded signal it has to explain')
print(f'    within-day std of RH       {float((((rh-mean_day)**2*m).sum()/m.sum()).sqrt()):6.3f}')
print(f'    mean duty                  {float(te["duty"].mean()):6.3f}')

# The counterfactual: duty is bang-bang, so long OFF stretches are natural
# open-loop experiments. If the chamber holds its equilibrium through them,
# the humidifier is a small correction on a large passive reservoir.
D, RH_, TT, VV = (torch.cat([tr[k], te[k]]).numpy()
                  for k in ('duty', 'rh', 'temp', 'valid'))
AHs = ah_sat(torch.tensor(TT)).numpy()
AH = RH_ / 100.0 * AHs
runs = []
for i in range(len(D)):
    z = D[i] < 1e-6
    e = np.diff(np.concatenate([[0], z.view(np.int8), [0]]))
    for a, b in zip(np.where(e == 1)[0], np.where(e == -1)[0]):
        if VV[i, a:b].all():
            runs.append((i, a, b - a))
L = np.array([r[2] for r in runs]) * 10 / 60
print(f'\n  HUMIDIFIER-OFF STRETCHES (within a day; duty is bang-bang, '
      f'{100*(D<1e-6).mean():.0f}% zero / {100*(D>0.99).mean():.0f}% saturated)')
for thr in (60, 120, 240, 480):
    print(f'    >= {thr:3d} min : {(L>=thr).sum():4d} stretches')
k = 60
sel = [(i, a, n) for i, a, n in runs if n * 10 / 60 >= 120]
d_rh = np.array([RH_[i, a+n-k:a+n].mean() - RH_[i, a:a+k].mean() for i, a, n in sel])
sat = np.array([(AH[i, a:a+n] / AHs[i, a:a+n]).mean() for i, a, n in sel])
print(f'    across a >= 2 h OFF stretch (n={len(sel)}): dRH mean {d_rh.mean():+.2f} '
      f'median {np.median(d_rh):+.2f} std {d_rh.std():.2f}')
print(f'    AH/AH_sat while OFF: {sat.mean():.3f} +/- {sat.std():.3f}'
      f'   <- same as the fitted s, WITH THE HUMIDIFIER PROVABLY OFF')
