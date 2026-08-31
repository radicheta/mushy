"""MUSHY-150: score chamber-model STRUCTURES by open-loop replay.

Every candidate is fitted and scored by the SAME differentiable rollout, the
same loss and the same optimizer, so a loss is a structural loss and not an
optimizer artifact (ticket comment 2026-08-31 15:35Z).

Rules the whole harness exists to enforce:
  * free-running rollout, never one-step -- initialise once per day, drive
    with recorded duty/temperature/ambient, run 24 h, score against recorded RH
  * the state is AH; RH is derived on read, so the balance never balances a
    non-conserved quantity
  * no controller anywhere in the path -- duty is what the relay RECORDED
  * no time-of-day input (the vent is a mechanical timer, perfectly aliased)

    .venv/bin/python scripts/bakeoff/run.py --split inter --candidates alice,bob
"""
import argparse, json, time
import numpy as np
import torch
import torch.nn as nn

# Exogenous per-step channels handed to the candidates. History is carried by
# fixed-timescale EWMAs of DRIVERS ONLY -- never of AH, which is the target.
CHANNELS = ('amb_t', 'amb_rh', 'precip', 'solar', 'cloud', 'wind', 'pressure',
            't_ew5', 't_ew30', 't_ew60', 'u_ew5', 'u_ew30', 'u_ew60',
            'a_ew30', 'a_ew60', 's_ew30', 's_ew60')

V = 5.76                        # chamber volume m3
MW_OVER_R = 18.01528 / 8.31446
DEAD_TIME_S = 360.0             # shipped default; see note in fit() below
CORPUS = 'scripts/bakeoff/corpus.npz'
torch.set_default_dtype(torch.float64)          # settled by measurement, see ticket


def svp_kpa(t):
    return 0.6108 * torch.exp((17.27 * t) / (t + 237.3))


def ah_to_rh(t, ah):
    return 100.0 * (ah * (t + 273.15) / MW_OVER_R) / (svp_kpa(t) * 1000.0)


def ah_sat(t):
    """AH of saturated air at t -- the wall/condensation driver."""
    return MW_OVER_R * (svp_kpa(t) * 1000.0) / (t + 273.15)


# ---------------------------------------------------------------- candidates
class Candidate(nn.Module):
    """A structure. `extra_states` is how many states beyond AH it carries."""
    extra = 0

    def reset(self, ah0, temp0):
        return ()

    def deriv(self, ah, aux, u, T, dT_dt, amb, ctx):
        """returns dAH/dt in g/m3/h, and the new aux tuple."""
        raise NotImplementedError


class Alice(Candidate):
    """Constant Q -- the shipped structure. Baseline everything must beat."""
    def __init__(self):
        super().__init__()
        self.logF = nn.Parameter(torch.tensor(np.log(3.89)))
        self.logQ = nn.Parameter(torch.tensor(np.log(0.553)))
        self.C = nn.Parameter(torch.tensor(2.77))

    def deriv(self, ah, aux, u, T, dT_dt, amb, ctx):
        F, Q = self.logF.exp(), self.logQ.exp()
        return (F * u - Q * (ah - amb) + self.C * dT_dt) / V, aux


class Bob(Candidate):
    """Q = Q0*(1 + k*(T - Tref)). One extra parameter; Santi's hypothesis in
    its simplest testable form."""
    TREF = 12.0

    def __init__(self):
        super().__init__()
        self.logF = nn.Parameter(torch.tensor(np.log(3.89)))
        self.logQ = nn.Parameter(torch.tensor(np.log(0.553)))
        self.k = nn.Parameter(torch.tensor(0.0))
        self.C = nn.Parameter(torch.tensor(2.77))

    def deriv(self, ah, aux, u, T, dT_dt, amb, ctx):
        Q = self.logQ.exp() * (1.0 + self.k * (T - self.TREF)).clamp(min=0.05)
        return (self.logF.exp() * u - Q * (ah - amb) + self.C * dT_dt) / V, aux


class Charlie(Candidate):
    """Saturation-driven loss: the sink is (AH - s*AH_sat(T_wall)), not the
    ambient gradient. Chamber T stands in for wall T (memoryless)."""
    def __init__(self):
        super().__init__()
        self.logF = nn.Parameter(torch.tensor(np.log(3.89)))
        self.logQ = nn.Parameter(torch.tensor(np.log(0.553)))
        self.s = nn.Parameter(torch.tensor(0.95))
        self.C = nn.Parameter(torch.tensor(2.77))

    def deriv(self, ah, aux, u, T, dT_dt, amb, ctx):
        drive = ah - self.s.clamp(0.5, 1.2) * ah_sat(T)
        return (self.logF.exp() * u - self.logQ.exp() * drive
                + self.C * dT_dt) / V, aux


class Dave(Candidate):
    """Wall moisture as a STATE, replacing C*dT. Wall temperature lags chamber
    temperature with its own time constant; the wall exchanges water with the
    air toward its surface equilibrium. Warming therefore releases moisture
    with a lag and hysteresis instead of instantaneously and reversibly --
    which is what the probe programme kept running into."""
    extra = 1

    def __init__(self):
        super().__init__()
        self.logF = nn.Parameter(torch.tensor(np.log(3.89)))
        self.logQ = nn.Parameter(torch.tensor(np.log(0.553)))
        self.logkw = nn.Parameter(torch.tensor(np.log(0.5)))
        self.s = nn.Parameter(torch.tensor(0.95))
        self.logtauw = nn.Parameter(torch.tensor(np.log(3600.0)))   # seconds

    def reset(self, ah0, temp0):
        return (temp0.clone(),)

    def deriv(self, ah, aux, u, T, dT_dt, amb, ctx):
        (Tw,) = aux
        a = (ctx['dt_s'] / self.logtauw.exp().clamp(60.0, 86400.0)).clamp(max=1.0)
        Tw = Tw + a * (T - Tw)
        wall = self.logkw.exp() * (self.s.clamp(0.5, 1.2) * ah_sat(Tw) - ah)
        return (self.logF.exp() * u - self.logQ.exp() * (ah - amb) + wall) / V, (Tw,)


class Eve(Candidate):
    """Neural Q inside the SAME conservation balance. Q_theta is a smooth
    scalar function of three physical inputs, so the learned function can be
    plotted against temperature and read off -- it answers the structural
    question rather than only winning the benchmark."""
    def __init__(self, width=16):
        super().__init__()
        self.logF = nn.Parameter(torch.tensor(np.log(3.89)))
        self.C = nn.Parameter(torch.tensor(2.77))
        self.net = nn.Sequential(nn.Linear(6, width), nn.Tanh(),
                                 nn.Linear(width, width), nn.Tanh(),
                                 nn.Linear(width, 1))
        with torch.no_grad():                    # start near the shipped Q
            self.net[-1].bias.fill_(np.log(np.exp(0.553) - 1.0))
            self.net[-1].weight.mul_(0.01)

    def deriv(self, ah, aux, u, T, dT_dt, amb, ctx):
        # T - T_ewma30 is a WALL-LAG proxy: the wall trails the air, so this
        # is the sign and size of the air/wall temperature difference that
        # drives condensation. Solar enters because an uninsulated steel wall
        # is heated directly by it, not only through air temperature.
        x = torch.stack([(T - 12.0) / 8.0,
                         (T - ctx['t_ew30']) / 1.5, (T - ctx['t_ew60']) / 2.0,
                         (ah - amb) / 4.0, u, ctx['solar'] / 300.0], dim=-1)
        Q = torch.nn.functional.softplus(self.net(x).squeeze(-1))
        return (self.logF.exp() * u - Q * (ah - amb) + self.C * dT_dt) / V, aux


class Frank(Candidate):
    """Black-box upper bound: how much predictive accuracy exists in this data
    at all. dAH/dt = NN(inputs, h) with its OWN hidden state h.

    The hidden state is not decoration. Without it Frank is a memoryless
    function of AH, and it then cannot represent a wall reservoir -- so Dave
    could beat it, and "the black box could not do better" would be a
    statement about my architecture rather than about the data. An upper
    bound has to be at least as expressive as every candidate it bounds.

    History also enters as fixed-timescale EWMAs of the EXOGENOUS drivers
    (5 min and 30 min). Those are safe: they are computed from recorded
    inputs, never from AH, so nothing leaks the target (TRAP 3).
    """
    extra = 2                          # learned reservoir states
    N_IN = 22

    def __init__(self, width=32):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(self.N_IN + self.extra, width), nn.Tanh(),
                                 nn.Linear(width, width), nn.Tanh(),
                                 nn.Linear(width, 1 + self.extra))
        with torch.no_grad():
            self.net[-1].weight.mul_(0.01); self.net[-1].bias.zero_()

    def reset(self, ah0, temp0):
        return (torch.zeros(len(ah0), self.extra, dtype=ah0.dtype),)

    def deriv(self, ah, aux, u, T, dT_dt, amb, ctx):
        (h,) = aux
        x = torch.stack([
            (ah - 9.0) / 3.0, (T - 12.0) / 8.0, (ah - amb) / 4.0, u, dT_dt,
            (ctx['amb_t'] - 12.0) / 8.0, (ctx['amb_rh'] - 75.0) / 20.0, ctx['precip'],
            ctx['solar'] / 300.0, (ctx['cloud'] - 50.0) / 40.0,
            ctx['wind'] / 15.0, (ctx['pressure'] - 1013.0) / 10.0,
            (ctx['t_ew5'] - 12.0) / 8.0, (ctx['t_ew30'] - 12.0) / 8.0,
            (ctx['t_ew60'] - 12.0) / 8.0,
            ctx['u_ew5'], ctx['u_ew30'], ctx['u_ew60'],
            (ctx['a_ew30'] - 8.0) / 3.0, (ctx['a_ew60'] - 8.0) / 3.0,
            ctx['s_ew30'] / 300.0, ctx['s_ew60'] / 300.0,
        ], dim=-1)
        y = self.net(torch.cat([x, h], dim=-1))
        dh = y[:, 1:] - 0.2 * h                  # leak keeps h bounded
        return y[:, 0] * 2.0, (h + dh * (ctx['dt_s'] / 3600.0),)


CANDIDATES = {'alice': Alice, 'bob': Bob, 'charlie': Charlie,
              'dave': Dave, 'eve': Eve, 'frank': Frank}


# ------------------------------------------------------------------ rollout
def rollout(model, tau_s, batch, dt_s):
    """Free-running open-loop replay, batched over days. Returns predicted RH
    [B, T]. The duty path (dead time + first-order mixing) is SHARED by every
    candidate, so it cannot bias the ranking."""
    duty, temp, amb = batch['duty'], batch['temp'], batch['amb_ah']
    B, N = duty.shape
    ah = batch['ah0'].clone()
    aux = model.reset(ah, temp[:, 0])
    applied = torch.zeros(B, dtype=duty.dtype)
    alpha = (dt_s / tau_s.clamp(min=dt_s)).clamp(max=1.0)
    lag = int(round(DEAD_TIME_S / dt_s))
    u_delayed = torch.cat([torch.zeros(B, lag, dtype=duty.dtype), duty[:, :-lag]], dim=1)
    dT = torch.zeros(B, N, dtype=temp.dtype)
    dT[:, 1:] = (temp[:, 1:] - temp[:, :-1]) * (3600.0 / dt_s)      # K/h
    out = []
    ctx = {'dt_s': dt_s}
    for i in range(N):
        applied = applied + alpha * (u_delayed[:, i] - applied)
        for k in CHANNELS:
            ctx[k] = batch[k][:, i]
        d, aux = model.deriv(ah, aux, applied, temp[:, i], dT[:, i], amb[:, i], ctx)
        ah = torch.clamp(ah + d * (dt_s / 3600.0), min=0.0)
        out.append(ah)
    return ah_to_rh(temp, torch.stack(out, dim=1))


def _runs(dates):
    """Index runs of calendar-consecutive days present in the corpus. prep.py
    drops unusable days, so the corpus is ordered but not gap-free."""
    d = np.array([np.datetime64(x) for x in dates])
    brk = np.where((d[1:] - d[:-1]) != np.timedelta64(1, 'D'))[0] + 1
    return np.split(np.arange(len(d)), brk)


def ewma(x, tau_s, dt_s, dates):
    """EWMA along time, carried ACROSS midnight wherever the previous day is
    actually present in the corpus. Each rollout is still one day, but the
    driver history is real history: 23:30 yesterday is what the average at
    00:00 today is built from. Only a day that STARTS a run has nothing to
    inherit, and only those days pay a warm-up (see warmup_mask)."""
    from scipy.signal import lfilter
    a = min(1.0, dt_s / tau_s)
    out = np.empty_like(x)
    for run in _runs(dates):
        flat = x[run].reshape(-1)                     # one continuous timeline
        y = lfilter([a], [1.0, -(1.0 - a)], flat, zi=[flat[0] * (1.0 - a)])[0]
        out[run] = y.reshape(len(run), -1)
    return out


# (channel -> source series, tau seconds). 5 min catches the mixing-scale
# response, 30 and 60 min bracket the wall/substrate timescale -- which is
# unknown, so both are offered and the fit chooses.
EWMAS = {'t_ew5': ('temp', 300.), 't_ew30': ('temp', 1800.), 't_ew60': ('temp', 3600.),
         'u_ew5': ('duty', 300.), 'u_ew30': ('duty', 1800.), 'u_ew60': ('duty', 3600.),
         'a_ew30': ('amb_ah', 1800.), 'a_ew60': ('amb_ah', 3600.),
         's_ew30': ('solar', 1800.), 's_ew60': ('solar', 3600.)}

WARMUP_MIN = 60          # applied ONLY to days that start a contiguous run


def warmup_mask(dates, n_steps, dt_s):
    """False for the first WARMUP_MIN of each run's FIRST day only.

    Blanking the first 30 min of every day would delete local midnight from
    every score in the corpus -- the coldest hours, where condensation and the
    wall term matter most -- so a candidate that failed only at midnight would
    never be charged for it. Days with a real predecessor inherit a warm EWMA
    and are scored in full."""
    m = np.ones((len(dates), n_steps), bool)
    warm = int(WARMUP_MIN * 60 / dt_s)
    for run in _runs(dates):
        m[run[0], :warm] = False
    return m


def load(split):
    z = np.load(CORPUS)
    dt_s = float(z['dt'])
    train = z[f'{split}_train']
    dates = z['dates']
    hist = {k: ewma(z[src], tau, dt_s, dates) for k, (src, tau) in
            EWMAS.items()}
    valid = z['valid'] & warmup_mask(dates, z['rh'].shape[1], dt_s)

    def pack(sel):
        b = {k: torch.tensor(z[k][sel]) for k in
             ('duty', 'temp', 'amb_ah', 'rh', 'amb_temp', 'amb_rh', 'precip',
              'solar', 'cloud', 'wind', 'pressure')}
        b['amb_t'] = b.pop('amb_temp')
        b.update({k: torch.tensor(v[sel]) for k, v in hist.items()})
        b['ah0'] = torch.tensor(z['ah'][sel][:, 0])
        b['valid'] = torch.tensor(valid[sel])
        b['dates'] = dates[sel]
        return b
    return pack(train), pack(~train), dt_s


def score(pred, b):
    """per-day rmse and bias on VALID samples only."""
    m = b['valid']
    err = (pred - b['rh']) * m
    n = m.sum(dim=1).clamp(min=1)
    rmse = torch.sqrt((err ** 2).sum(dim=1) / n)
    bias = err.sum(dim=1) / n
    return rmse, bias


def fit(name, tr, te, dt_s, steps, lr, seed):
    """dead_time is held FIXED (integer sample shift is not differentiable) and
    tau is fitted. Both are shared by every candidate, so the choice cannot
    reorder the ranking -- it only sets a common floor.
    ponytail: fixed 360 s dead time; grid-search it only if the winner's
    residual shows a consistent lead/lag."""
    torch.manual_seed(seed); np.random.seed(seed)
    model = CANDIDATES[name]()
    log_tau = torch.nn.Parameter(torch.tensor(np.log(600.0)))
    opt = torch.optim.Adam(list(model.parameters()) + [log_tau], lr=lr)
    t0 = time.time()
    for it in range(steps):
        opt.zero_grad()
        pred = rollout(model, log_tau.exp(), tr, dt_s)
        m = tr['valid']
        loss = (((pred - tr['rh']) ** 2) * m).sum() / m.sum()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(list(model.parameters()) + [log_tau], 10.0)
        opt.step()
        if it % max(1, steps // 8) == 0 or it == steps - 1:
            print(f'    [{name}] step {it:4d}  train rmse {loss.item()**.5:6.3f}  '
                  f'({time.time()-t0:5.1f}s)', flush=True)
    with torch.no_grad():
        r_tr, _ = score(rollout(model, log_tau.exp(), tr, dt_s), tr)
        r_te, b_te = score(rollout(model, log_tau.exp(), te, dt_s), te)
    return model, log_tau, r_tr, r_te, b_te


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--split', default='inter', choices=['inter', 'chrono'])
    ap.add_argument('--candidates', default='alice,bob,charlie,dave,eve,frank')
    ap.add_argument('--steps', type=int, default=300)
    ap.add_argument('--lr', type=float, default=0.05)
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--days', type=int, default=0, help='subsample train days (0=all)')
    ap.add_argument('--out', default='')
    a = ap.parse_args()

    tr, te, dt_s = load(a.split)
    if a.days:
        sel = np.linspace(0, len(tr['rh']) - 1, a.days).astype(int)
        tr = {k: (v[sel] if hasattr(v, '__len__') else v) for k, v in tr.items()}
    print(f'split={a.split}  train {len(tr["rh"])} days  test {len(te["rh"])} days  dt={dt_s}s')
    rows = []
    for name in a.candidates.split(','):
        print(f'  fitting {name}...', flush=True)
        model, log_tau, r_tr, r_te, b_te = fit(name, tr, te, dt_s, a.steps, a.lr, a.seed)
        row = dict(candidate=name, split=a.split, seed=a.seed,
                   n_params=sum(p.numel() for p in model.parameters()) + 1,
                   tau_s=float(log_tau.exp()),
                   train_rmse=float(r_tr.mean()),
                   test_rmse=float(r_te.mean()), test_rmse_med=float(r_te.median()),
                   test_rmse_p90=float(r_te.quantile(0.9)), test_bias=float(b_te.mean()),
                   test_worst_day=str(te['dates'][int(r_te.argmax())]),
                   test_worst_rmse=float(r_te.max()))
        rows.append(row)
        print(f'  {name:8s} test rmse mean {row["test_rmse"]:6.3f} med {row["test_rmse_med"]:6.3f} '
              f'p90 {row["test_rmse_p90"]:6.3f}  bias {row["test_bias"]:+.3f}  '
              f'worst {row["test_worst_day"]} {row["test_worst_rmse"]:.2f}', flush=True)
    print(f'\n{"candidate":10s} {"par":>4s} {"train":>7s} {"test":>7s} {"med":>7s} {"p90":>7s} {"bias":>7s}')
    for r in sorted(rows, key=lambda r: r['test_rmse']):
        print(f'{r["candidate"]:10s} {r["n_params"]:4d} {r["train_rmse"]:7.3f} '
              f'{r["test_rmse"]:7.3f} {r["test_rmse_med"]:7.3f} {r["test_rmse_p90"]:7.3f} '
              f'{r["test_bias"]:+7.3f}')
    if a.out:
        json.dump(rows, open(a.out, 'w'), indent=1)
        print(f'wrote {a.out}')


if __name__ == '__main__':
    main()
