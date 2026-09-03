"""MUSHY-154: rank candidates on predicting the CHANGE, not the level.

Santi, 2026-09-03, after reading the segment plots: "rank them on the ability to
predict RH GRADIENT instead of RH period".

WHY THE LEVEL METRIC FLATTERS EVERYTHING. Scoring RH (or AH) at t+h lets a model
bank the level it was handed and coast: on the 2026-09-01 probe afternoon alice
carries 8% of the actual 5-min movement (slope 0.08) and still scores 0.690 MAE
against persistence's 0.733. The leaderboard has been ranking candidates largely
by how well they echo the present. Scoring the CHANGE removes the free part --
predicting "no change" is the zero of this scale, not a competitor that scores
1.0 while looking respectable.

Three numbers, because they fail differently:

  r      correlation of predicted change with actual change. Does the model know
         WHEN the chamber moves? This is the one the level metric hides.
  slope  regression of predicted change on actual. How much of the movement it
         commits to. NOT independently meaningful -- a predictor with low r
         SHOULD shrink toward zero, so a low slope is usually a symptom of low
         r rather than a calibration bug. `gain` below is what separates them.
  skill  rmse(pred change - actual change) / rmse(actual change). <1 beats
         predicting no change; >1 means the model is worse than standing still.
  gain   skill after rescaling the model's change by its optimal factor. If
         gain << skill the model is MISCALIBRATED (right shape, wrong size,
         fixable); if gain ~= skill its slope was already optimal for its r and
         the only way up is a better r.

    BAKEOFF_CORPUS=scripts/bakeoff/corpus-m08.npz \
    BAKEOFF_RESULTS=scripts/bakeoff/results-m08 \
      .venv/bin/python scripts/bakeoff/rank_gradient.py [split]

READ THE RH TABLE, NOT THE AH ONE. The bake-off scores AH because RH divides by
a temperature-dependent saturation, and that is right for a LEVEL. It is wrong
for a CHANGE: temperature is handed to every model as an exogenous channel, so
part of the AH change is derivable arithmetic rather than a prediction about the
chamber. The _frozen_rh baseline below measures exactly that part, and on m08
chrono it beats alice at 5 min. Both tables are printed; the AH one is kept
because it is what the leaderboard used, not because it is the honest target.
"""
import glob, os, re, sys
import numpy as np
import torch

sys.path.insert(0, 'scripts/bakeoff')
from run import CANDIDATES, HORIZONS, TAU_LO, TAU_HI, ah_sat, load, rollout, windows

R = os.environ.get('BAKEOFF_RESULTS', 'scripts/bakeoff/results')
SPLIT = (sys.argv[1] if len(sys.argv) > 1 else 'chrono')


def metrics(dp, da):
    """dp, da: predicted and actual CHANGE over the horizon."""
    sd = np.sqrt((da ** 2).mean())
    if sd == 0:
        return dict(r=np.nan, slope=np.nan, skill=np.nan, gain=np.nan)
    r = float(np.corrcoef(dp, da)[0, 1]) if dp.std() > 0 else 0.0
    slope = float(np.polyfit(da, dp, 1)[0])
    skill = float(np.sqrt(((dp - da) ** 2).mean()) / sd)
    # optimal rescale of the model's own signal: separates "wrong size" from
    # "does not know when".
    k = float((dp * da).sum() / (dp * dp).sum()) if (dp ** 2).sum() > 0 else 0.0
    gain = float(np.sqrt(((k * dp - da) ** 2).mean()) / sd)
    return dict(r=r, slope=slope, skill=skill, gain=gain)


def main():
    _, te_d, dt_s = load(SPLIT)
    H = max(HORIZONS)
    te = windows(te_d, dt_s, H)
    ks = [int(h * 60 / dt_s) for h in HORIZONS]
    print(f'corpus={os.environ.get("BAKEOFF_CORPUS", "scripts/bakeoff/corpus.npz")}  '
          f'results={R}  split={SPLIT}  {len(te["ah"])} test windows')

    rows = {}
    for ck in sorted(glob.glob(f'{R}/{SPLIT}-*-s*.json.*.ckpt')):
        m = re.search(rf'{SPLIT}-(\w+)-s(\d+)\.json', ck)
        name, seed = m.group(1), int(m.group(2))
        if name not in CANDIDATES:
            continue
        c = torch.load(ck, weights_only=False)
        if c.get('tau_bounds') != (TAU_LO, TAU_HI):
            print(f'  skip {ck}: tau bounds {c.get("tau_bounds")}')
            continue
        state, log_tau = (c['best'][1], c['best'][2]) \
            if c.get('best') and c['best'][1] else (c['model'], c['log_tau'])
        model = CANDIDATES[name]()
        model.load_state_dict(state)
        tau = TAU_LO + (TAU_HI - TAU_LO) * torch.sigmoid(log_tau)
        with torch.no_grad():
            rh = rollout(model, tau, te, dt_s)
            ah = rh / 100.0 * ah_sat(te['temp'])
        for h, k in zip(HORIZONS, ks):
            j = k - 1
            for unit, pred, actual, start in (
                    ('ah', ah[:, j], te['ah'][:, j], te['ah0']),
                    ('rh', rh[:, j], te['rh'][:, j], te['rh'][:, 0])):
                d = metrics((pred - start).numpy(), (actual - start).numpy())
                rows.setdefault((name, h, unit), []).append(d)

    # THE BASELINE THAT EXPOSES THE AH METRIC: hold RH at its initial value and
    # use the KNOWN future temperature. It predicts no humidity movement at all;
    # every point of AH-change skill it scores is temperature bookkeeping, free
    # to any model handed the temperature channel. On m08 chrono it scores
    # r 0.73 / skill 0.679 at 5 min -- BETTER than alice's 0.689. That is why
    # this whole ranking exists: the bake-off scored AH, and at 5 min AH change
    # is mostly the saturation curve, not the chamber.
    for h, k in zip(HORIZONS, ks):
        j = k - 1
        pred = te['rh'][:, 0] / 100.0 * ah_sat(te['temp'][:, j])
        rows.setdefault(('_frozen_rh', h, 'ah'), []).append(
            metrics((pred - te['ah0']).numpy(), (te['ah'][:, j] - te['ah0']).numpy()))
        rows.setdefault(('_frozen_rh', h, 'rh'), []).append(
            metrics(np.zeros(len(te['rh'])), (te['rh'][:, j] - te['rh'][:, 0]).numpy()))

    for unit, label in (('ah', 'ABSOLUTE HUMIDITY g/m3'), ('rh', 'RELATIVE HUMIDITY pts')):
        for h in HORIZONS:
            got = [(n, v) for (n, hh, u), v in rows.items() if hh == h and u == unit]
            if not got:
                continue
            print(f'\n=== {label}  change over {h:.0f} min  ({SPLIT}) ===')
            print(f'  {"cand":<12}{"r":>7}{"slope":>8}{"skill":>8}{"gain":>8}   '
                  f'(skill<1 beats predicting no change)')
            agg = sorted(((n, {k: np.mean([d[k] for d in v]) for k in v[0]}, len(v))
                          for n, v in got), key=lambda t: t[1]['skill'])
            for n, d, cnt in agg:
                flag = ''
                if d['skill'] >= 1.0:
                    flag = '  <- worse than standing still'
                elif d['gain'] < d['skill'] - 0.02:
                    flag = '  <- miscalibrated: rescaling its output would fix this'
                print(f'  {n:<12}{d["r"]:7.2f}{d["slope"]:8.2f}{d["skill"]:8.3f}'
                      f'{d["gain"]:8.3f}   n={cnt}{flag}')


if __name__ == '__main__':
    main()
