"""MUSHY-150: a fit resumed from a checkpoint must land on exactly the same
parameters as an uninterrupted one. If it does not, restarting after an
outage silently changes the numbers the bake-off is ranking on.

    .venv/bin/python scripts/bakeoff/test_resume.py
"""
import os, sys, tempfile
import numpy as np
import torch

sys.path.insert(0, 'scripts/bakeoff')
from run import fit, load

STEPS, CAND = 6, 'alice'


def flat(model, log_tau):
    return torch.cat([p.detach().reshape(-1) for p in model.parameters()]
                     + [log_tau.detach().reshape(-1)])


def main():
    tr, te, dt_s = load('inter')
    sel = np.linspace(0, len(tr['rh']) - 1, 2).astype(int)      # 2 days: fast
    tr = {k: (v[sel] if hasattr(v, '__len__') else v) for k, v in tr.items()}
    te = {k: (v[:2] if hasattr(v, '__len__') else v) for k, v in te.items()}

    m, lt, _, r_ref, _ = fit(CAND, tr, te, dt_s, STEPS, 0.05, 0)
    ref = flat(m, lt)

    with tempfile.TemporaryDirectory() as d:
        ck = os.path.join(d, 'c.ckpt')
        fit(CAND, tr, te, dt_s, STEPS // 2, 0.05, 0, ck, every=1)   # "outage"
        assert os.path.exists(ck), 'no checkpoint written'
        m2, lt2, _, r2, _ = fit(CAND, tr, te, dt_s, STEPS, 0.05, 0, ck, every=1)

    assert torch.equal(ref, flat(m2, lt2)), (
        f'resumed params differ: max |d| = {(ref - flat(m2, lt2)).abs().max():.3e}')
    assert torch.equal(r_ref, r2), 'resumed test scores differ'
    print(f'OK  resume is bit-exact over {STEPS} steps ({CAND})')


if __name__ == '__main__':
    main()
