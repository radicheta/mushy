"""MUSHY-150: does a model predict CHANGE, or just echo the present?

The decisive diagnostic, and the one the skill score hides. For each forecast
compare what the model said would change against what did:

    dPred = pred(t) - truth(t-h)        dTrue = truth(t) - truth(t-h)

A regression slope of 1.0 means the model predicts the full movement. A slope
near 0 means it is saying "everything will be as it is now" -- which draws as
ground truth time-shifted by the horizon, and still scores respectably against
persistence because any correctly-signed lean helps.

Santi spotted this by eye ("graphs look more like 'my prediction for the future
is everything will be as is now' and we are seeing a copy of ground truth,
time-shifted"). Baseline alice's slope at 5 min is 0.13; frank's is 0.02.

    .venv/bin/python scripts/bakeoff/predicted_change.py web/rolling.html
"""
import json, re, sys
import numpy as np

h = open(sys.argv[1] if len(sys.argv) > 1 else 'scripts/bakeoff/web/rolling.html').read()
D = json.loads(re.search(r'const D=(\{.*?\});\n', h, re.S).group(1))
x = np.array(D['x'])
tg = np.array(D['target'])
dt = x[1] - x[0]

print(f'{"model":16s}{"h":>4s}{"std dPred":>11s}{"std dTrue":>11s}{"captured":>10s}'
      f'{"corr":>7s}{"slope":>7s}')
for m in D['models']:
    for hz in D['h']:
        k = int(round(hz / dt))
        past = np.concatenate([np.full(k, tg[0]), tg[:-k]])
        dP = np.array(m['series'][str(hz)])[k:] - past[k:]
        dT = tg[k:] - past[k:]
        print(f'{m["name"]:16s}{hz:4d}{dP.std():11.3f}{dT.std():11.3f}'
              f'{dP.std()/dT.std():9.0%}{np.corrcoef(dT, dP)[0, 1]:7.2f}'
              f'{np.polyfit(dT, dP, 1)[0]:7.2f}')
