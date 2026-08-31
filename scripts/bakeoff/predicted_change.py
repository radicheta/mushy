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


def match_vs_shift(pred, truth, dt_min, lags=(0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50)):
    """Is the curve a DELAYED COPY of truth, or does it match where it stands?

    Shift the prediction left by L and compare. A delayed copy improves
    monotonically up to L = horizon; a real forecast is best at L = 0 and gets
    worse. This is the diagnostic to use -- comparing the location of a single
    minimum is fragile, and gave two contradictory answers on this data before
    the window happened to clip one curve and then the other.
    """
    import numpy as np
    out = []
    for Lm in lags:
        L = int(round(Lm / dt_min))
        a, b = pred[L:], (truth[:len(truth) - L] if L else truth)
        a, b = a - a.mean(), b - b.mean()
        out.append((Lm, float(np.sqrt(((a - b) ** 2).mean())),
                    float(np.corrcoef(a, b)[0, 1])))
    return out


if __name__ == '__main__' and len(sys.argv) > 2 and sys.argv[2] == '--shift':
    dt_min = x[1] - x[0]
    for m in D['models']:
        for hz in D['h']:
            c = match_vs_shift(np.array(m['series'][str(hz)]), tg, dt_min)
            best = min(c, key=lambda r: r[1])[0]
            print(f'{m["name"]:16s} h={hz:2d}  best match at shift {best:3d} min'
                  f'   rmse L=0 {c[0][1]:.2f} -> L=45 {c[-2][1]:.2f}')
