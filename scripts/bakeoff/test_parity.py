"""MUSHY-150: the torch rollout must reproduce the shipped numpy ChamberModel
bit-for-bit when Alice is set to the shipped parameters. If it does not, every
score this harness produces is measuring a reimplementation bug rather than a
model structure.

    .venv/bin/python scripts/bakeoff/test_parity.py
"""
import sys
import numpy as np
import torch

sys.path.insert(0, 'src/chambers/fc-core')
sys.path.insert(0, 'scripts/bakeoff')
from fc_core.sim.chamber_model import ChamberModel, ChamberParams
from run import Alice, rollout, ah_to_rh


def main():
    z = np.load('scripts/bakeoff/corpus.npz')
    dt_s = float(z['dt'])
    # a day the humidifier actually ran on, else dF/dlogF is identically zero
    d = int(np.argmax(z['duty'].mean(axis=1) * (z['valid'].mean(axis=1) > 0.99)))
    duty, temp, amb = z['duty'][d], z['temp'][d], z['amb_ah'][d]
    ah0 = z['ah'][d][0]

    p = ChamberParams()                      # shipped defaults
    ch = ChamberModel(p, rh0_pct=50.0, temp_c=float(temp[0]))
    ch._ah = float(ah0)                      # same initial state as the harness
    ref = []
    for i in range(len(duty)):
        ref.append(ch.step(float(duty[i]), dt_s, float(amb[i]), float(temp[i])))
    ref = np.array(ref)

    model = Alice()
    with torch.no_grad():
        model.logF.fill_(np.log(p.fill_g_per_h))
        model.logQ.fill_(np.log(p.moisture_loss_m3_per_h))
        model.C.fill_(p.surface_g_per_k)
        batch = {k: torch.tensor(v[d:d + 1]) for k, v in
                 (('duty', z['duty']), ('temp', z['temp']), ('amb_ah', z['amb_ah']),
                  ('amb_temp', z['amb_temp']), ('precip', z['precip']))}
        batch['ah0'] = torch.tensor(z['ah'][d:d + 1, 0])
        got = rollout(model, torch.tensor(p.tau_s), batch, dt_s)[0].numpy()

    err = np.abs(got - ref)
    print(f'day {z["dates"][d]}  n={len(ref)}  ref RH {ref.min():.2f}..{ref.max():.2f}')
    print(f'max |torch - numpy| = {err.max():.3e} RH points  (mean {err.mean():.3e})')
    assert err.max() < 1e-9, f'rollout diverges from shipped ChamberModel: {err.max()}'

    # the shared duty path must actually delay: a step in duty must not move AH
    # for DEAD_TIME_S. Guards against silently dropping the lag.
    # compare AGAINST a zero-duty run, else the leak term moves AH on its own
    b2 = {k: v.clone() for k, v in batch.items()}
    b2['temp'] = torch.full_like(batch['temp'], 12.0)
    b2['duty'] = torch.zeros_like(batch['duty'])
    b3 = {k: v.clone() for k, v in b2.items()}
    b3['duty'][0, 100:] = 1.0
    with torch.no_grad():
        r0 = rollout(model, torch.tensor(p.tau_s), b2, dt_s)[0].numpy()
        r = rollout(model, torch.tensor(p.tau_s), b3, dt_s)[0].numpy()
    moved = np.where(np.abs(r - r0) > 1e-9)[0]
    lag = moved[0] - 100 if len(moved) else -1
    print(f'duty step at i=100 first moves AH at i={moved[0]}  -> lag {lag*dt_s:.0f}s (expect 360s)')
    assert 35 <= lag <= 37, f'dead time not applied: lag={lag}'

    # gradients must reach every parameter, or a candidate silently never fits
    model.zero_grad()
    rollout(model, torch.tensor(p.tau_s), batch, dt_s).sum().backward()
    for n_, p_ in model.named_parameters():
        assert p_.grad is not None and torch.isfinite(p_.grad).all() and p_.grad != 0, \
            f'no usable gradient for {n_}'
    print('gradients reach F, Q, C: ok')
    print('PARITY OK')


if __name__ == '__main__':
    main()
