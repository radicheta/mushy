"""MUSHY-150: a fitted model must actually respond to duty.

Every silent failure on this ticket ended the same way -- the dead time escaped
past the scoring window, rollout() zeroed duty for the whole window, and the
model scored respectably while ignoring the humidifier entirely. It happened
TWICE and both times I reported the numbers before noticing. "No known defect"
is a claim about what I have checked, so this is the check.

    .venv/bin/python scripts/bakeoff/test_duty_sensitivity.py
"""
import sys
import torch

sys.path.insert(0, 'scripts/bakeoff')
from run import CHANNELS, HORIZONS, Alice, ah_sat, rollout

W = int(max(HORIZONS) * 60 / 10.0)          # window length in samples


def batch(n=W):
    b = {'duty': torch.zeros(1, n), 'temp': torch.full((1, n), 15.0),
         'amb_ah': torch.full((1, n), 8.0), 'ah0': torch.tensor([9.0])}
    b['duty'][:, n // 3:] = 1.0             # one edge, mid-window
    for c in CHANNELS:
        b[c] = torch.zeros(1, n)
    return b


def sensitivity(dead_s, d_max):
    m = Alice()
    m.D_MAX = d_max
    with torch.no_grad():
        m.raw_d.copy_(torch.log(torch.tensor(dead_s / (d_max - dead_s))))
    b = batch()
    bumped = dict(b); bumped['duty'] = (b['duty'] + 0.1).clamp(max=1.0)
    with torch.no_grad():
        d = (rollout(m, torch.tensor(600.0), bumped, 10.0)
             - rollout(m, torch.tensor(600.0), b, 10.0)).abs().mean()
    return float(d) / 100.0 * float(ah_sat(torch.tensor(15.0)))


def main():
    print(f'scoring window = {max(HORIZONS):.0f} min = {W * 10:.0f} s\n')
    print(f'{"dead_s":>8s}{"D_MAX":>8s}{"d|AH| for +0.10 duty":>24s}   verdict')
    rows = []
    for dead, dmax in ((140.0, 300.0), (250.0, 300.0), (700.0, 1800.0), (900.0, 1800.0)):
        s = sensitivity(dead, dmax)
        ok = s >= 1e-4
        rows.append((dead, dmax, s, ok))
        print(f'{dead:8.0f}{dmax:8.0f}{s:24.6f}   '
              f'{"responds" if ok else "IGNORES DUTY"}')
    # a dead time inside the window must respond; one past it must not.
    assert rows[0][3] and rows[1][3], 'a dead time inside the window must respond to duty'
    assert not rows[2][3] and not rows[3][3], \
        'a dead time past the window must read as insensitive -- that is the bug we are catching'
    print('\nOK: the guard separates a working model from one that ignores its input.')


if __name__ == '__main__':
    main()
