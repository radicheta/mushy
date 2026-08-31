"""MUSHY-150: replay the forced dry-down/wet-up through every fitted candidate.

A BASELINE, taken before the forced cycles are folded into the corpus: these
models were fitted on closed-loop data only and have never seen an hour of
forced full-off followed by an hour of forced full-on. Free-running the whole
2 h from a single initial condition is also well past the 45 min horizon they
were trained for, so this is a stress test, not the metric they were ranked on.

    .venv/bin/python scripts/bakeoff/replay_cycle.py > out.json
"""
import csv, glob, json, os, sys
import numpy as np
import torch

sys.path.insert(0, 'scripts/bakeoff')
from run import CANDIDATES, rollout, ah_sat, DEAD_TIME_S, CHANNELS, EWMAS

S = '/tmp/claude-1000/-mnt-slime-kingdom-opt-mushy/2d689b3c-1fac-446c-87a8-4df8c1df98ae/scratchpad'
TEL = sys.argv[1] if len(sys.argv) > 1 else f'{S}/cycle1.csv'
AMB = sys.argv[2] if len(sys.argv) > 2 else f'{S}/amb.csv'
rows = [r for r in csv.reader(open(TEL)) if len(r) == 4 and all(x.strip() for x in r)]
d = np.array([[float(x) for x in r] for r in rows])
t, rh, T, duty = d.T
dt_s = 10.0

# ambient: hourly -> per-sample, then absolute humidity
w = {}
for a, topic, v in csv.reader(open(AMB)):
    w.setdefault(topic, []).append((float(a), float(v)))
wt = np.array([x[0] for x in w['weather.temperature']])
amb_T = np.interp(t, wt, [x[1] for x in w['weather.temperature']])
amb_RH = np.interp(t, np.array([x[0] for x in w['weather.humidity']]),
                   [x[1] for x in w['weather.humidity']])
amb_ah = amb_RH / 100.0 * ah_sat(torch.tensor(amb_T)).numpy()

# every exogenous channel, interpolated onto the 10 s grid, raw units as
# prep.py stores them. Without these eve and frank cannot be replayed at all.
EX = {'amb_t': amb_T, 'amb_rh': amb_RH}
for key, topic in (('precip', 'weather.precipitation'), ('solar', 'weather.solar'),
                   ('cloud', 'weather.cloud'), ('wind', 'weather.wind'),
                   ('pressure', 'weather.pressure')):
    if topic in w:
        EX[key] = np.interp(t, np.array([x[0] for x in w[topic]]),
                            [x[1] for x in w[topic]])
    else:
        EX[key] = np.zeros_like(t)


def _ewma(x, tau_s):
    """Same filter prep.py uses, over one continuous run (this window is)."""
    from scipy.signal import lfilter
    a = min(1.0, dt_s / tau_s)
    return lfilter([a], [1.0, -(1.0 - a)], x, zi=[x[0] * (1.0 - a)])[0]


SRC = {'temp': T, 'duty': duty, 'amb_ah': amb_ah, 'solar': EX['solar']}
for name_, (src, tau_) in EWMAS.items():
    EX[name_] = _ewma(np.asarray(SRC[src], dtype=float), tau_)

ah = rh / 100.0 * ah_sat(torch.tensor(T)).numpy()
def B():
    b = {'duty': torch.tensor(duty)[None], 'temp': torch.tensor(T)[None],
         'amb_ah': torch.tensor(amb_ah)[None], 'ah0': torch.tensor(ah[:1]),
         'rh': torch.tensor(rh)[None],
         'valid': torch.ones(1, len(t), dtype=torch.bool)}
    for k in CHANNELS:
        b[k] = torch.tensor(np.asarray(EX[k], dtype=float))[None]
    return b

out = {'t': (t - t[0]).tolist(), 't0_epoch': t[0], 'dt_s': dt_s,
       'actual_ah': ah.tolist(), 'actual_rh': rh.tolist(),
       'temp': T.tolist(), 'duty': duty.tolist(), 'amb_ah': amb_ah.tolist(),
       'dead_time_s': DEAD_TIME_S, 'models': []}

for name in ('alice', 'bob', 'charlie', 'dave', 'eve', 'frank', 'gary'):
    p = f'scripts/bakeoff/results/inter-{name}-s0.json.{name}.ckpt'
    if not os.path.exists(p):
        continue
    ck = torch.load(p, weights_only=False)
    m = CANDIDATES[name]()
    m.load_state_dict(ck['model'])
    TAU_LO, TAU_HI = 60.0, 1800.0
    tau = TAU_LO + (TAU_HI - TAU_LO) * torch.sigmoid(ck['log_tau'])
    with torch.no_grad():
        pred_ah = (rollout(m, tau, B(), dt_s) / 100.0
                   * ah_sat(torch.tensor(T))).numpy()[0]
    err = pred_ah - ah
    out['models'].append(dict(
        name=name, n_params=sum(x.numel() for x in m.parameters()) + 1,
        tau_s=float(tau), ah=pred_ah.tolist(),
        rmse=float(np.sqrt((err ** 2).mean())), bias=float(err.mean()),
        final_err=float(err[-1]),
        params={k: (float(v.exp()) if k.startswith('log') else float(v))
                for k, v in ck['model'].items() if v.numel() == 1}))
print(json.dumps(out))
