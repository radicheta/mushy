"""MUSHY-154: 5-minute predictions vs reality over one segment, per candidate.

The leaderboard is an aggregate and aggregates hide shape. This dumps the raw
curve for a few hours so the failure modes are visible: which models echo the
present, which chase the pulses, which overshoot.

Defaults to the afternoon of 2026-09-01 -- an OPEN-LOOP duty-probe day, the
only kind where the relay is not a function of RH, and one no fit has seen.
Models are the AUGUST fits (results-m08), so this is August-trained against a
held-out September day.

    BAKEOFF_CORPUS=scripts/bakeoff/corpus-probe.npz \
      .venv/bin/python scripts/bakeoff/segment_replay.py > web/segment.json

Uses the EARLY-STOPPED BEST state out of the checkpoint (ck['best'][1:3]), not
ck['model'] which is the last optimiser step. score_probe.py reads the latter
and carries a caveat saying so; here the best state is available, so use it and
the numbers match what the leaderboard actually reported.
"""
import glob, json, os, sys
import numpy as np
import torch

sys.path.insert(0, 'scripts/bakeoff')
from run import CANDIDATES, TAU_LO, TAU_HI, ah_sat, load, rollout, windows

R = os.environ.get('BAKEOFF_RESULTS', 'scripts/bakeoff/results-m08')
DAY = os.environ.get('SEG_DAY', '2026-09-01')
T0, T1 = int(os.environ.get('SEG_FROM', 13 * 60)), int(os.environ.get('SEG_TO', 18 * 60))
HORIZON_MIN = 5.0
SHOW = ['alice', 'charlie', 'gary', 'irving', 'frank', 'irma']


def main():
    _, te_d, dt_s = load('chrono')
    w = windows(te_d, dt_s, HORIZON_MIN, stride_min=1)
    day = np.array([d.split('+')[0] for d in w['dates']])
    mins = np.array([int(d.split('+')[1].rstrip('m')) for d in w['dates']])
    m = (day == DAY) & (mins >= T0) & (mins < T1)
    if not m.sum():
        raise SystemExit(f'no windows for {DAY} {T0}-{T1}; days: {sorted(set(day))[-4:]}')
    n = len(w['ah'])
    seg = {k: (v[m] if hasattr(v, '__len__') and len(v) == n else v) for k, v in w.items()}
    order = np.argsort(mins[m])
    idx = torch.tensor(order.copy())

    # the target time is the window START plus the horizon: these are 5-min-ahead
    # predictions, plotted against the reality they were predicting.
    out = {'day': DAY, 'horizon_min': HORIZON_MIN,
           'minute': (mins[m][order] + HORIZON_MIN).tolist(),
           'actual_rh': seg['rh'][idx, -1].tolist(),
           'rh_now': seg['rh'][idx, 0].tolist(),
           'duty': seg['duty'][idx].mean(1).tolist(),
           'models': {}}

    for name in SHOW:
        cks = sorted(glob.glob(f'{R}/chrono-{name}-s0.json.*.ckpt'))
        if not cks:
            print(f'# no checkpoint for {name} in {R}', file=sys.stderr)
            continue
        ck = torch.load(cks[0], weights_only=False)
        state, log_tau = (ck['best'][1], ck['best'][2]) \
            if ck.get('best') and ck['best'][1] else (ck['model'], ck['log_tau'])
        model = CANDIDATES[name]()
        model.load_state_dict(state)
        tau = TAU_LO + (TAU_HI - TAU_LO) * torch.sigmoid(log_tau)
        with torch.no_grad():
            pred = rollout(model, tau, seg, dt_s)[idx, -1]
        err = float((pred - seg['rh'][idx, -1]).abs().mean())
        out['models'][name] = {'pred_rh': pred.tolist(), 'mae_rh': err,
                               'tau_s': float(tau), 'dead_s': float(model.delay_s())}
        print(f'# {name:9s} MAE {err:5.2f} pts   tau {float(tau):6.1f}s  '
              f'dead {float(model.delay_s()):6.1f}s', file=sys.stderr)

    # persistence is the thing every skill number is measured against, so it
    # belongs on the chart rather than in a caption.
    pers = seg['rh'][idx, 0]
    out['models']['persistence'] = {
        'pred_rh': pers.tolist(),
        'mae_rh': float((pers - seg['rh'][idx, -1]).abs().mean()),
        'tau_s': None, 'dead_s': None}
    print(f'# persistence MAE {out["models"]["persistence"]["mae_rh"]:5.2f} pts',
          file=sys.stderr)
    json.dump(out, sys.stdout)


if __name__ == '__main__':
    main()
