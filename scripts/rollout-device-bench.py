"""Device/precision benchmark for the MUSHY-150 rollout harness.

Mimics the real workload: the chamber moisture balance stepped sequentially
over one day at 10 s (8640 steps), batched across days, with a small MLP
standing in for candidate 5's Q_theta. Measures forward-only and
forward+backward (training needs backprop THROUGH the rollout), in float32
and float64, on CPU and CUDA, plus peak GPU memory.

Backprop through 8640 sequential steps stores per-step activations, so peak
memory -- not throughput -- may be what decides the harness design.
"""
import time
import torch
import torch.nn as nn

DAYS = 150          # batch dimension: the only axis that parallelises
STEPS = 8640        # one day at 10 s; the rollout CANNOT parallelise over this
DT_H = 10.0 / 3600.0
V = 12.0            # placeholder chamber volume, m3


class QNet(nn.Module):
    """Q_theta(T, AH, gradient) -- candidate 5's shape, deliberately tiny."""
    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(3, 16), nn.Tanh(), nn.Linear(16, 1), nn.Softplus())

    def forward(self, t, ah, grad):
        return self.net(torch.stack([t, ah, grad], dim=-1)).squeeze(-1)


def rollout(qnet, ah0, temp, amb, duty, F, C, steps):
    ah = ah0
    for i in range(steps):
        t, a, u = temp[:, i], amb[:, i], duty[:, i]
        grad = ah - a
        q = qnet(t, ah, grad)
        dah = (F * u - q * grad) / V
        ah = ah + dah * DT_H + C * torch.zeros_like(ah)
    return ah


def bench(device, dtype, steps, backward, days=DAYS):
    torch.manual_seed(0)
    dev = torch.device(device)
    qnet = QNet().to(dev, dtype)
    g = torch.Generator(device='cpu').manual_seed(0)
    mk = lambda lo, hi: (lo + (hi - lo) * torch.rand(days, steps, generator=g)).to(dev, dtype)
    temp, amb, duty = mk(5.0, 25.0), mk(6.0, 10.0), mk(0.0, 1.0)
    ah0 = torch.full((days,), 9.0, device=dev, dtype=dtype)
    F = torch.tensor(19.7, device=dev, dtype=dtype, requires_grad=backward)
    C = torch.tensor(2.77, device=dev, dtype=dtype)
    if device == 'cuda':
        torch.cuda.synchronize(); torch.cuda.reset_peak_memory_stats()
    t0 = time.perf_counter()
    ctx = torch.enable_grad() if backward else torch.no_grad()
    with ctx:
        out = rollout(qnet, ah0, temp, amb, duty, F, C, steps)
        if backward:
            out.sum().backward()
    if device == 'cuda':
        torch.cuda.synchronize()
    el = time.perf_counter() - t0
    peak = torch.cuda.max_memory_allocated() / 2**20 if device == 'cuda' else float('nan')
    return el, peak


if __name__ == '__main__':
    print(f'torch {torch.__version__}  cuda_available={torch.cuda.is_available()}')
    if torch.cuda.is_available():
        print(f'device: {torch.cuda.get_device_name(0)}')
    devices = ['cpu'] + (['cuda'] if torch.cuda.is_available() else [])

    # Short probe first (SMOKE before the expensive batch): 200 steps.
    print(f'\n--- probe: {DAYS} days x 200 steps ---')
    print(f'{"device":6} {"dtype":9} {"mode":9} {"sec":>8} {"peakMB":>9}')
    for d in devices:
        for dt in (torch.float32, torch.float64):
            for bw in (False, True):
                el, pk = bench(d, dt, 200, bw)
                print(f'{d:6} {str(dt).split(".")[-1]:9} {"fwd+bwd" if bw else "fwd":9} {el:8.3f} {pk:9.1f}')

    # Full day, forward only -- extrapolate cost; backward at full length is
    # the memory question, run it last and let it OOM loudly if it does.
    print(f'\n--- full day: {DAYS} days x {STEPS} steps ---')
    print(f'{"device":6} {"dtype":9} {"mode":9} {"sec":>8} {"peakMB":>9}')
    for d in devices:
        for dt in (torch.float32, torch.float64):
            el, pk = bench(d, dt, STEPS, False)
            print(f'{d:6} {str(dt).split(".")[-1]:9} {"fwd":9} {el:8.3f} {pk:9.1f}')
    for d in devices:
        for dt in (torch.float32, torch.float64):
            try:
                el, pk = bench(d, dt, STEPS, True)
                print(f'{d:6} {str(dt).split(".")[-1]:9} {"fwd+bwd":9} {el:8.3f} {pk:9.1f}')
            except RuntimeError as e:
                print(f'{d:6} {str(dt).split(".")[-1]:9} {"fwd+bwd":9}   FAILED  {str(e)[:60]}')
