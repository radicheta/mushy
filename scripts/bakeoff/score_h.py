"""MUSHY-150: rank candidates on SHORT-HORIZON prediction (default 45 min),
which is the horizon the controller acts on.

Day-long rollout is the wrong ranking: it integrates the causal signal away
(the controller has cancelled the disturbance by then), so a flat line wins
and every candidate scores worse than "RH does not change today". One-step
scoring is the opposite trap -- AH(t+1) ~= AH(t) is the identity function.
45 min sits between: persistence error is 0.383 g/m3, well clear of noise,
and the humidifier is visible at 10+ sigma once stratified by drying gap.

Scores AH, not RH: RH = AH / a temperature-dependent number, so scoring RH
lets temperature errors and moisture errors cancel (2026-07-17 lost 3 g/m3
of water while RH ROSE).

    .venv/bin/python scripts/bakeoff/score_h.py [inter|chrono] [minutes]
"""
import glob, os, sys
import numpy as np
import torch

sys.path.insert(0, 'scripts/bakeoff')
from run import CANDIDATES, rollout, load, ah_sat, CHANNELS

SPLIT = sys.argv[1] if len(sys.argv) > 1 else 'inter'
HORIZONS = [float(x) for x in sys.argv[2].split(',')] if len(sys.argv) > 2 else [5., 15., 45.]


def windows(b, dt_s, mins, stride_min=30):
    """Reshape [days, T] into [windows, H]. rollout() batches over rows and
    does not care whether a row is a day or a window, so nothing else changes."""
    H, S = int(mins * 60 / dt_s), int(stride_min * 60 / dt_s)
    ah = b['rh'] / 100.0 * ah_sat(b['temp'])
    starts = [(i, t) for i in range(len(b['rh']))
              for t in range(0, b['rh'].shape[1] - H, S)
              if bool(b['valid'][i, t:t + H].all())]
    i, t = (torch.tensor(x) for x in zip(*starts))
    take = lambda v: torch.stack([v[a, s:s + H] for a, s in zip(i, t)])
    out = {k: take(b[k]) for k in ('duty', 'temp', 'rh', 'valid', 'amb_ah') + CHANNELS}
    out['ah0'] = ah[i, t]
    out['ah'] = take(ah)
    out['dates'] = np.array([f'{b["dates"][a]}+{int(s*dt_s/60):04d}m' for a, s in zip(i, t)])
    out['gap'] = (out['ah'] - out['amb_ah']).mean(1)
    return out


def err_at(pred_ah, w, k):
    """per-window error on ABSOLUTE HUMIDITY at the END of the horizon.
    Averaging over the window would be dominated by the first minutes, where
    any model initialised from truth is trivially right -- that hides exactly
    the divergence the controller needs predicted."""
    return (pred_ah[:, k - 1] - w['ah'][:, k - 1]).abs()


def main():
    tr, te, dt_s = load(SPLIT)
    # ONE set of start points, sized to the longest horizon, evaluated at each
    # prefix -- so every horizon scores the identical windows and the columns
    # are comparable.
    w = windows(te, dt_s, max(HORIZONS))
    ks = [int(h * 60 / dt_s) for h in HORIZONS]
    hdr = ''.join(f'{h:.0f}min'.rjust(15) for h in HORIZONS)
    print(f'split={SPLIT}  {len(w["ah"])} test windows  |  error in g/m3 AH at each '
          f'horizon, and SKILL vs persistence (<1.00 beats it)\n')
    print(f'  {"":26s}{"par":>5s}{hdr}')

    base = [err_at(w['ah0'][:, None].expand_as(w['ah']), w, k).mean() for k in ks]
    row = lambda name, e, par='': print(
        f'  {name:26s}{par:>5s}' + ''.join(
            f'{v:8.3f}{"  --  " if b is None else f"  {v/b:4.2f}"}'
            for v, b in zip(e, base if name != "BASELINE persistence" else [None]*len(ks))))
    row('BASELINE persistence', base)
    s_ = float((w['ah'] * ah_sat(w['temp']) * w['valid']).sum()
               / ((ah_sat(w['temp']) ** 2 * w['valid']).sum()))
    sat = s_ * ah_sat(w['temp'])
    row(f'BASELINE {s_:.3f}*AH_sat(T)', [err_at(sat, w, k).mean() for k in ks])
    print()
    for p_ in sorted(glob.glob(f'scripts/bakeoff/results/{SPLIT}-*.ckpt')):
        tag = os.path.basename(p_).split('.json')[0]
        c = tag.split('-')[1]
        ck = torch.load(p_, weights_only=False)
        m = CANDIDATES[c]()
        m.load_state_dict(ck['model'])
        with torch.no_grad():
            ah = rollout(m, ck['log_tau'].exp(), w, dt_s) / 100.0 * ah_sat(w['temp'])
        row(f'{tag} it={ck["it"]}', [err_at(ah, w, k).mean() for k in ks],
            str(sum(x.numel() for x in m.parameters()) + 1))


if __name__ == '__main__':
    main()
