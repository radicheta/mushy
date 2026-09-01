"""MUSHY-150: the analyses behind the 2026-09-01 ticket comments. Kept because
the numbers they produce are cited as decisions, and a result whose script was
a scratch file is a result nobody can re-check.

    .venv/bin/python scripts/bakeoff/analyse.py horizons  # per-horizon + movement
    .venv/bin/python scripts/bakeoff/analyse.py paired [split]  # within-seed, vs alice
    .venv/bin/python scripts/bakeoff/analyse.py alpha     # Euler vs exact ZOH

NOT wired into run.py's ranking -- changing what the leaderboard ranks on is a
decision, not a cleanup.
"""
import glob, json, os, statistics as st, sys
import torch

sys.path.insert(0, 'scripts/bakeoff')
from run import (CANDIDATES, HORIZONS, TAU_LO, TAU_HI, ah_sat, horizon_mse,
                 load, rollout, windows)

R = 'scripts/bakeoff/results'


def _skills(key, split='inter'):
    out = {}
    for f in glob.glob(f'{R}/{split}-*.json'):
        for r in json.load(open(f)):
            if 'skill' in r:
                out.setdefault(r['candidate'], {})[r['seed']] = r[key]
    return out


def horizons():
    """Which horizon is hard, and which one DISCRIMINATES? The ranking uses
    max() over horizons, and max() picks 5 min for every candidate and every
    seed -- so the leaderboard is a 5-minute leaderboard and the 15/45 min
    measurements have never moved a ranking."""
    _, te_d, dt_s = load('inter')
    te = windows(te_d, dt_s, max(HORIZONS))
    ks = [int(h * 60 / dt_s) for h in HORIZONS]
    print('MOVEMENT of the target (test windows, g/m3 AH)')
    print(f'{"horizon":>8s} {"persist rmse":>13s} {"med |move|":>11s} {"p90 |move|":>11s}')
    for h, k in zip(HORIZONS, ks):
        d = te['ah'][:, k - 1] - te['ah0']
        print(f'{h:6.0f}m {float((d ** 2).mean()) ** .5:13.4f} '
              f'{float(d.abs().median()):11.4f} {float(d.abs().quantile(0.9)):11.4f}')

    sk = _skills('skill')
    print('\nSKILL vs persistence per horizon (median of seeds, lower better)')
    print(f'{"candidate":10s}' + ''.join(f'{h:.0f}min'.rjust(9) for h in HORIZONS))
    med = {c: [st.median([v[s][i] for s in v]) for i in range(len(HORIZONS))]
           for c, v in sk.items()}
    for c in sorted(med, key=lambda c: med[c][0]):
        print(f'{c:10s}' + ''.join(f'{x:9.3f}' for x in med[c]))

    good = [c for c in med if med[c][0] < 0.9]      # drop the broken candidates
    print('\nSPREAD across sensible candidates vs SEED NOISE, per horizon')
    print(f'{"":10s}' + ''.join(f'{h:.0f}min'.rjust(9) for h in HORIZONS))
    print(f'{"spread":10s}' + ''.join(
        f'{max(med[c][i] for c in good) - min(med[c][i] for c in good):9.3f}'
        for i in range(len(HORIZONS))))
    print(f'{"seednoise":10s}' + ''.join(
        f'{max(max(sk[c][s][i] for s in sk[c]) - min(sk[c][s][i] for s in sk[c]) for c in good):9.3f}'
        for i in range(len(HORIZONS))))


def paired(split='inter'):
    """Seeds are SHARED across candidates, so compare WITHIN a seed. The
    marginal spread carries a per-seed offset common to every candidate (the
    validation day split; alice has no random init at all), and pairing
    cancels it -- which is what turns 'inside seed noise' into a verdict."""
    # RANK ON WHAT THE HARNESS RANKS ON. This read skill_worst while run.py
    # ranks skill_mean, which silently produced a different ordering -- and
    # the two disagree because max() slides along a dead-time ridge the
    # objective is indifferent to.
    sk = _skills('skill_mean', split)
    # only seeds every candidate has finished -- pairing needs the same seed
    # on both sides, and a half-finished matrix would otherwise crash or,
    # worse, compare candidates over different seed sets.
    seeds = sorted(set.intersection(*(set(v) for v in sk.values())))
    print(f'[{split}] mean-horizon skill by seed')
    print(f'{"cand":10s}' + ''.join(f's{s}'.rjust(8) for s in seeds))
    order = sorted(sk, key=lambda c: st.median(list(sk[c].values())))
    for c in order:
        print(f'{c:10s}' + ''.join(f'{sk[c][s]:8.3f}' for s in seeds))

    print('\nPAIRED vs alice (negative = beats the shipped structure)')
    print(f'{"cand":10s}' + ''.join(f's{s}'.rjust(8) for s in seeds) +
          f'{"mean":>9s}{"worst":>8s}  verdict')
    for c in order:
        if c == 'alice':
            continue
        d = [sk[c][s] - sk['alice'][s] for s in seeds]
        v = ('BEATS alice on every seed' if max(d) < 0 else
             'loses on every seed' if min(d) > 0 else 'inconsistent')
        print(f'{c:10s}' + ''.join(f'{x:+8.3f}' for x in d) +
              f'{st.mean(d):+9.3f}{max(d):+8.3f}  {v}')


def alpha():
    """Does the Euler-vs-exact alpha move the SCORES, or only the tau readout?
    Same weights, same tau, same data -- alpha is the only difference."""
    _, te_d, dt_s = load('inter')
    te = windows(te_d, dt_s, max(HORIZONS))
    ks = [int(h * 60 / dt_s) for h in HORIZONS]
    base = [float(x) ** .5 for x in horizon_mse(
        te['ah0'][:, None].expand_as(te['ah']), te, ks)]
    print(f'{"candidate":10s} {"tau_s":>7s} {"aEuler":>7s} {"aZOH":>7s} '
          f'{"worstEuler":>10s} {"worstZOH":>9s} {"delta":>7s}')
    for c in CANDIDATES:
        f = f'{R}/inter-{c}-s0.json.{c}.ckpt'
        if not os.path.exists(f):
            continue
        ck = torch.load(f, weights_only=False)
        m = CANDIDATES[c]()
        m.load_state_dict(ck['model'])
        tau = TAU_LO + (TAU_HI - TAU_LO) * torch.sigmoid(ck['log_tau'])
        out = []
        for smooth in (False, True):
            with torch.no_grad():
                ah = rollout(m, tau, te, dt_s, smooth) / 100.0 * ah_sat(te['temp'])
            out.append(max(float(x) ** .5 / b for x, b
                           in zip(horizon_mse(ah, te, ks), base)))
        print(f'{c:10s} {float(tau):7.1f} '
              f'{float((dt_s / tau.clamp(min=dt_s)).clamp(max=1.0)):7.4f} '
              f'{float(-torch.expm1(-dt_s / tau)):7.4f} '
              f'{out[0]:10.4f} {out[1]:9.4f} {out[1] - out[0]:+7.4f}')


if __name__ == '__main__':
    {'horizons': horizons, 'paired': paired,
     'alpha': alpha}[sys.argv[1]](*sys.argv[2:])
