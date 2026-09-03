"""MUSHY-150: replay the FITTED chrono candidates on the open-loop duty-probe
days (2026-09-01/02), which no fit has ever seen and which are the only days
where the relay was not a function of RH.

The corpus duty channel IS the relay state (prep.delivered_duty: fc.humidifier
zero-order held at 1 s, minus the pipe transit, binned to 10 s), so every
candidate has always been driven by the pulses; what was missing is a test set
where the pulses are exogenous. Scores: skill vs persistence at 5/10 min, and
the movement slope (predicted 10 min change regressed on actual change -- a
model that echoes the present scores ~0.4 skill with slope ~0.1), split by
RH band because probe_coverage.py measured the plant gain collapsing above 90%.

    BAKEOFF_CORPUS=scripts/bakeoff/corpus-probe.npz .venv/bin/python scripts/bakeoff/score_probe.py

CAVEAT: a .ckpt holds the LAST optimiser step, not the early-stopped best that
the JSON leaderboard reports. For the physics candidates the two are within
noise; read frank/gary here with that in mind.
"""
import glob, json, os, re, sys
import numpy as np
import torch

sys.path.insert(0, 'scripts/bakeoff')
from run import (CANDIDATES, HORIZONS, TAU_LO, TAU_HI, ah_sat, horizon_mse,
                 load, rollout, windows)

R = 'scripts/bakeoff/results'
PROBE_DAYS = ('2026-09-01', '2026-09-02')


def sub(b, m):
    n = len(b['ah'])
    return {k: (v[m] if hasattr(v, '__len__') and len(v) == n else v) for k, v in b.items()}


def main():
    tr_d, te_d, dt_s = load('chrono')
    H = max(HORIZONS)
    ks = [int(h * 60 / dt_s) for h in HORIZONS]
    te = windows(te_d, dt_s, H)
    day = np.array([d.split('+')[0] for d in te['dates']])
    sets = {'jul-aug': sub(te, ~np.isin(day, PROBE_DAYS)),
            'probe': sub(te, np.isin(day, PROBE_DAYS))}
    rh0 = sets['probe']['rh'][:, 0]
    sets['probe<90'] = sub(sets['probe'], (rh0 < 90).numpy())
    sets['probe>=90'] = sub(sets['probe'], (rh0 >= 90).numpy())
    for k, w in sets.items():
        print(f'{k:10s} {len(w["ah"]):4d} windows')

    def evaluate(model, tau, w):
        with torch.no_grad():
            pred = rollout(model, tau, w, dt_s) / 100.0 * ah_sat(w['temp'])
            base = horizon_mse(w['ah0'][:, None].expand_as(w['ah']), w, ks)
            err = horizon_mse(pred, w, ks)
            k = ks[-1] - 1
            dp = (pred[:, k] - w['ah0']).numpy(); da = (w['ah'][:, k] - w['ah0']).numpy()
            slope = float(np.polyfit(da, dp, 1)[0]) if len(da) > 2 else float('nan')
        return [float(e / b) for e, b in zip(err, base)], slope

    rows = []
    for ck in sorted(glob.glob(f'{R}/chrono-*-s*.json.*.ckpt')):
        name, seed = re.search(r'chrono-(\w+)-s(\d+)\.json', ck).groups()
        c = torch.load(ck, weights_only=False)
        if c.get('tau_bounds') != (TAU_LO, TAU_HI):
            print(f'skip {ck}: tau bounds {c.get("tau_bounds")}'); continue
        model = CANDIDATES[name](); model.load_state_dict(c['model'])
        tau = TAU_LO + (TAU_HI - TAU_LO) * torch.sigmoid(c['log_tau'])
        r = dict(candidate=name, seed=int(seed), tau_s=float(tau),
                 dead_s=float(model.delay_s()))
        for k, w in sets.items():
            if len(w['ah']):
                r[k], r[k + '_slope'] = evaluate(model, tau, w)
        rows.append(r)
        print(f'  {name:8s} s{seed}  ' + '  '.join(
            f'{k}: {" ".join(f"{x:.3f}" for x in r[k])} m={r[k+"_slope"]:.2f}'
            for k in sets if k in r), flush=True)

    print(f'\nMEAN OVER SEEDS  (skill at {HORIZONS} min, <1 beats persistence; m = 10 min movement slope, 1 = tracks change)')
    print(f'  {"":9s}' + ''.join(f'{k:>26s}' for k in sets))
    for name in CANDIDATES:
        rs = [r for r in rows if r['candidate'] == name]
        if not rs: continue
        line = f'  {name:9s}'
        for k in sets:
            v = [r[k] for r in rs if k in r]
            if v:
                line += f'{np.mean([x[0] for x in v]):8.3f}{np.mean([x[1] for x in v]):7.3f}  m{np.mean([r[k+"_slope"] for r in rs]):5.2f}    '
        print(line + f' (n={len(rs)})')
    out = f'{R}/probe-replay.json'
    json.dump(rows, open(out, 'w'), indent=1)
    print(f'wrote {out}')


if __name__ == '__main__':
    main()
