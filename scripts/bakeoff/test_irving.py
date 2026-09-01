"""MUSHY-150: irving must be a strict SUPERSET of both alice and dave.

The whole reading of irving rests on that. If irving loses to alice we want to
conclude "the wall state buys nothing", and that conclusion is only available
if irving could have BEEN alice and chose not to. A superset that cannot
reproduce its own subset is a rigged comparison, not a result.

    .venv/bin/python scripts/bakeoff/test_irving.py
"""
import sys
import torch

sys.path.insert(0, 'scripts/bakeoff')
from run import CHANNELS, Alice, Dave, Irving, rollout

B, N, DT = 3, 400, 10.0


def batch(seed=0):
    g = torch.Generator().manual_seed(seed)
    b = {'duty': torch.rand(B, N, generator=g),
         'temp': 12.0 + 3.0 * torch.rand(B, N, generator=g),
         'amb_ah': 8.0 + torch.rand(B, N, generator=g),
         'ah0': 9.0 + torch.rand(B, generator=g)}
    for k in CHANNELS:                      # unused by these three, but rollout
        b[k] = torch.zeros(B, N)            # reads every channel every step
    return b


def main():
    b = ba = batch()
    tau = torch.tensor(600.0)

    # C = 0  ->  irving IS dave. Same parameters, so bit-for-bit.
    d, i = Dave(), Irving()
    i.load_state_dict({**d.state_dict(), 'C': torch.tensor(0.0)})
    with torch.no_grad():
        gap = (rollout(i, tau, b, DT) - rollout(d, tau, b, DT)).abs().max()
    print(f'irving(C=0) vs dave:            max |diff| = {float(gap):.3e} RH')
    assert gap == 0.0, 'irving with C=0 must reproduce dave exactly'

    # kw -> 0  ->  the wall term vanishes and irving IS alice.
    a, i = Alice(), Irving()
    i.load_state_dict({**i.state_dict(), 'logF': a.logF.detach(),
                       'logQ': a.logQ.detach(), 'C': a.C.detach(),
                       'logkw': torch.tensor(-40.0), 'raw_d': a.raw_d.detach()})
    with torch.no_grad():
        gap = (rollout(i, tau, ba, DT) - rollout(a, tau, ba, DT)).abs().max()
    print(f'irving(kw->0) vs alice:         max |diff| = {float(gap):.3e} RH')
    assert gap < 1e-9, 'irving with kw->0 must reproduce alice'

    # and it must not be trivially equal to either at its own defaults
    i = Irving()
    with torch.no_grad():
        da = (rollout(i, tau, ba, DT) - rollout(Alice(), tau, ba, DT)).abs().max()
        dd = (rollout(i, tau, b, DT) - rollout(Dave(), tau, b, DT)).abs().max()
    print(f'irving(default) vs alice/dave:  {float(da):.3e} / {float(dd):.3e} RH')
    assert da > 1e-6 and dd > 1e-6, 'irving must differ from both at its defaults'
    print('IRVING SUPERSET OK')


if __name__ == '__main__':
    main()
