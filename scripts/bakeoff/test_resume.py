"""MUSHY-150: a fit resumed from a checkpoint must land on exactly the same
parameters as an uninterrupted one. If it does not, restarting after an
outage silently changes the numbers the bake-off is ranking on.

    .venv/bin/python scripts/bakeoff/test_resume.py
"""
import os, sys, tempfile
import numpy as np
import torch

sys.path.insert(0, 'scripts/bakeoff')
from run import fit, load, windows, HORIZONS

STEPS, CAND = 6, 'alice'


def flat(model, tau_s):
    return torch.cat([p.detach().reshape(-1) for p in model.parameters()]
                     + [torch.tensor([tau_s], dtype=torch.float64)])


def main():
    tr_d, te_d, dt_s = load('inter')
    H = max(HORIZONS)
    tr = windows(tr_d, dt_s, H, cap=32, seed=0)                 # small: fast
    te = windows(te_d, dt_s, H, cap=32, seed=0)

    m, lt, _, r_ref, _ = fit(CAND, tr, te, dt_s, STEPS, 0.05, 0)
    ref = flat(m, lt)

    with tempfile.TemporaryDirectory() as d:
        ck = os.path.join(d, 'c.ckpt')
        fit(CAND, tr, te, dt_s, STEPS // 2, 0.05, 0, ck, every=1)   # "outage"
        assert os.path.exists(ck), 'no checkpoint written'
        m2, lt2, _, r2, _ = fit(CAND, tr, te, dt_s, STEPS, 0.05, 0, ck, every=1)

    assert torch.equal(ref, flat(m2, lt2)), (
        f'resumed params differ: max |d| = {(ref - flat(m2, lt2)).abs().max():.3e}')
    assert r_ref == r2, 'resumed test scores differ'
    print(f'OK  resume is bit-exact over {STEPS} steps ({CAND})')


def test_bounds_guard():
    """A checkpoint fitted under different tau bounds must REFUSE to resume.
    log_tau is raw; reading it through a changed tau_of() reinterprets the fit
    instead of continuing it, and emits a plausible wrong result in seconds."""
    import run
    tr_d, te_d, dt_s = load('inter')
    H = max(HORIZONS)
    tr = windows(tr_d, dt_s, H, cap=32, seed=0)
    te = windows(te_d, dt_s, H, cap=32, seed=0)
    with tempfile.TemporaryDirectory() as d:
        ck = os.path.join(d, 'g.ckpt')
        fit(CAND, tr, te, dt_s, 2, 0.05, 0, ck, every=1)
        lo = run.TAU_LO
        try:
            run.TAU_LO = lo / 6.0                       # the 60 -> 10 change
            fit(CAND, tr, te, dt_s, 4, 0.05, 0, ck, every=1)
        except SystemExit as e:
            assert 'tau bounds' in str(e), e
            print('OK  mismatched tau bounds refuse to resume')
            return
        finally:
            run.TAU_LO = lo
    raise AssertionError('resumed across a tau-bound change -- guard is dead')


if __name__ == '__main__':
    main()
    test_bounds_guard()
