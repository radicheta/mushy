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
import argparse, json, os, time
import numpy as np
import torch
import torch.nn as nn

# Exogenous per-step channels handed to the candidates. History is carried by
# fixed-timescale EWMAs of DRIVERS ONLY -- never of AH, which is the target.
CHANNELS = ('amb_t', 'amb_rh', 'precip', 'solar', 'cloud', 'wind', 'pressure',
            't_ew5', 't_ew30', 't_ew60', 'u_ew5', 'u_ew30', 'u_ew60',
            'a_ew30', 'a_ew60', 's_ew30', 's_ew60')

V = 5.76                        # chamber volume m3
HORIZONS = (5.0, 15.0, 45.0)    # minutes -- the horizons the controller acts on
TAU_LO, TAU_HI = 60.0, 1800.0   # duty mixing lag is bounded to PHYSICAL values
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


def windows(b, dt_s, mins, stride_min=30, cap=0, seed=0):
    """[days, T] -> [windows, H]. Each window carries its own initial AH, so a
    fit is scored on where the chamber goes NEXT, not on a whole day."""
    H, S = int(mins * 60 / dt_s), int(stride_min * 60 / dt_s)
    ah = b['rh'] / 100.0 * ah_sat(b['temp'])
    st = [(i, t) for i in range(len(b['rh']))
          for t in range(0, b['rh'].shape[1] - H, S)
          if bool(b['valid'][i, t:t + H].all())]
    if cap and len(st) > cap:                       # deterministic subsample:
        rs = np.random.RandomState(seed)            # full-batch gradient, so no
        st = [st[j] for j in sorted(rs.choice(len(st), cap, replace=False))]
    i, t = (torch.tensor(x) for x in zip(*st))
    take = lambda v: torch.stack([v[a, c:c + H] for a, c in zip(i, t)])
    w = {k: take(b[k]) for k in ('duty', 'temp', 'rh', 'valid', 'amb_ah') + CHANNELS}
    w['ah0'], w['ah'] = ah[i, t], take(ah)
    w['dates'] = np.array([f'{b["dates"][a]}+{int(c*dt_s/60):04d}m' for a, c in zip(i, t)])
    w['day'] = i.clone()                        # source day, for a leak-free split
    w['gap'] = (w['ah'] - w['amb_ah']).mean(1)
    return w


def horizon_mse(pred_ah, w, ks):
    """MSE on ABSOLUTE HUMIDITY at each horizon. AH not RH: RH divides by a
    temperature-dependent number, so scoring RH lets temperature errors and
    moisture errors cancel. AT the horizon, not averaged over the window --
    the average is dominated by the first minutes, where any model started
    from truth is trivially right."""
    return [((pred_ah[:, k - 1] - w['ah'][:, k - 1]) ** 2).mean() for k in ks]


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


def fit(name, tr, te, dt_s, steps, lr, seed, ckpt_path='', every=25, va=None):
    """Trains on the MULTI-HORIZON skill score: mean over 5/15/45 min of the
    MSE divided by the persistence MSE at that horizon. Normalising by
    persistence keeps the horizons comparable -- unnormalised, 45 min carries
    ~60x the squared error and would be the only term that mattered.

    dead_time is held FIXED (an integer sample shift is not differentiable).
    tau is fitted but BOUNDED to 60-1800 s via a sigmoid, so it stays a mixing
    lag. Unbounded it was not a time constant at all: candidates drove it from
    89 s to 4094 h and used it as a gain knob to disconnect the humidifier.

    EARLY STOPPING on a held-out slice of train. Without it the comparison is
    rigged: the physics candidates get strong inductive bias for free while the
    neural ones get no regulariser at all, so they train straight past the
    optimum. Measured: eve reached train 0.2183 against alice's 0.3127 and
    still lost on test, and both were STILL DESCENDING at step 999. Fitting
    better and generalising worse is overfitting, not an optimiser failure, and
    candidate 6 cannot be the intended UPPER BOUND on available accuracy while
    nothing stops it."""
    torch.manual_seed(seed); np.random.seed(seed)
    model = CANDIDATES[name]()
    log_tau = torch.nn.Parameter(torch.tensor(-0.7985))     # sigmoid -> 600 s
    tau_of = lambda r: TAU_LO + (TAU_HI - TAU_LO) * torch.sigmoid(r)
    opt = torch.optim.Adam(list(model.parameters()) + [log_tau], lr=lr)
    ks = [int(h * 60 / dt_s) for h in HORIZONS]
    base = [float(b) for b in horizon_mse(
        tr['ah0'][:, None].expand_as(tr['ah']), tr, ks)]     # persistence

    # Resume: the loop is fully deterministic (no dropout, no minibatch
    # sampling -- the seed only picks the init), so restarting from a
    # checkpoint gives the same trajectory as an uninterrupted run.
    start = 0
    if ckpt_path and os.path.exists(ckpt_path):
        ck = torch.load(ckpt_path, weights_only=False)
        if ck['name'] == name and ck['seed'] == seed:
            model.load_state_dict(ck['model'])
            with torch.no_grad():
                log_tau.copy_(ck['log_tau'])
            opt.load_state_dict(ck['opt'])
            start = ck['it']
            print(f'    [{name}] resumed from {ckpt_path} at step {start}', flush=True)

    def save(it):
        if not ckpt_path:
            return
        # atomic: a power cut mid-write must not leave a corrupt checkpoint,
        # which is the exact failure this whole mechanism exists for.
        torch.save(dict(name=name, seed=seed, it=it, model=model.state_dict(),
                        log_tau=log_tau.detach().clone(), opt=opt.state_dict()),
                   ckpt_path + '.tmp')
        os.replace(ckpt_path + '.tmp', ckpt_path)

    best = (float('inf'), None)         # (val loss, state) -- restored at the end
    vloss = lambda: float(sum(
        e / b for e, b in zip(horizon_mse(
            rollout(model, tau_of(log_tau), va, dt_s) / 100.0 * ah_sat(va['temp']),
            va, ks), base)) / len(ks))

    t0 = time.time()
    for it in range(start, steps):
        opt.zero_grad()
        ah = rollout(model, tau_of(log_tau), tr, dt_s) / 100.0 * ah_sat(tr['temp'])
        loss = sum(e / b for e, b in zip(horizon_mse(ah, tr, ks), base)) / len(ks)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(list(model.parameters()) + [log_tau], 10.0)
        opt.step()
        if it % max(1, steps // 8) == 0 or it == steps - 1:
            print(f'    [{name}] step {it:4d}  train skill {loss.item():6.4f}  '
                  f'tau {float(tau_of(log_tau).detach()):6.0f}s  ({time.time()-t0:5.1f}s)', flush=True)
        if va is not None and (it % every == every - 1 or it == steps - 1):
            with torch.no_grad():
                v = vloss()
            if v < best[0]:
                best = (v, {k: t.detach().clone() for k, t in model.state_dict().items()},
                        log_tau.detach().clone(), it)
        if it % every == every - 1 or it == steps - 1:
            save(it + 1)
    if best[1] is not None:
        model.load_state_dict(best[1])
        with torch.no_grad():
            log_tau.copy_(best[2])
        print(f'    [{name}] early stop: best val {best[0]:.4f} at step {best[3]}'
              f' of {steps}', flush=True)
    with torch.no_grad():
        f = lambda w: [float(x) ** .5 for x in horizon_mse(
            rollout(model, tau_of(log_tau), w, dt_s) / 100.0 * ah_sat(w['temp']), w, ks)]
        return model, float(tau_of(log_tau).detach()), f(tr), f(te), te


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--split', default='inter', choices=['inter', 'chrono'])
    ap.add_argument('--candidates', default='alice,bob,charlie,dave,eve,frank')
    ap.add_argument('--steps', type=int, default=300)
    ap.add_argument('--lr', type=float, default=0.05)
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--train-windows', type=int, default=0,
                    help='0 = every window. A cap is a COMPUTE knob, not a claim '
                         'about the data: 1024 was an arbitrary early choice that '
                         'starved the high-capacity candidates')
    ap.add_argument('--out', default='')
    a = ap.parse_args()

    tr_d, te_d, dt_s = load(a.split)
    H = max(HORIZONS)
    allw = windows(tr_d, dt_s, H, cap=a.train_windows, seed=a.seed)
    # 80/20 fit/validation split BY DAY, deterministic per seed. Splitting by
    # window index LEAKS: windows are 45 min long taken every 30 min, so a
    # validation window would share half its samples with a fitting window and
    # start 30 min away from it. Validation then reads optimistic, early
    # stopping stops too late, and the mechanism under-regularises exactly the
    # candidates it exists to protect.
    n = len(allw['ah'])
    days = np.unique(allw['day'].numpy())
    rs = np.random.RandomState(1000 + a.seed)
    vdays = set(rs.choice(days, max(1, len(days) // 5), replace=False).tolist())
    vm = np.array([d in vdays for d in allw['day'].numpy()])
    cut = lambda m: {k: (v[m] if hasattr(v, '__len__') and len(v) == n else v)
                     for k, v in allw.items()}
    tr, va = cut(~vm), cut(vm)
    te = windows(te_d, dt_s, H)
    print(f'  fit {len(tr["ah"])} windows ({len(days)-len(vdays)} days) / '
          f'validate {len(va["ah"])} ({len(vdays)} days)')
    ks = [int(h * 60 / dt_s) for h in HORIZONS]
    hz = ''.join(f'{h:.0f}min'.rjust(14) for h in HORIZONS)
    print(f'split={a.split}  train {len(tr["ah"])} windows (of {len(tr_d["rh"])} days)  '
          f'test {len(te["ah"])} windows  dt={dt_s}s')

    # BASELINES FIRST. A candidate that does not clear these is not a model --
    # under the previous day-averaged objective none of them did, and nothing
    # in the harness said so.
    base = [float(x) ** .5 for x in horizon_mse(
        te['ah0'][:, None].expand_as(te['ah']), te, ks)]
    s_ = float((te['ah'] * ah_sat(te['temp']) * te['valid']).sum()
               / ((ah_sat(te['temp']) ** 2 * te['valid']).sum()))
    sat = [float(x) ** .5 for x in horizon_mse(s_ * ah_sat(te['temp']), te, ks)]
    show = lambda n, e, p='': print(
        f'  {n:22s}{p:>6s}' + ''.join(f'{v:8.4f}{v/b:6.2f}' for v, b in zip(e, base)))
    print(f'\n  {"":22s}{"par":>6s}{hz}   (err g/m3 AH, then skill vs persistence)')
    show('BASELINE persistence', base)
    show(f'BASELINE {s_:.3f}*AHsat', sat)

    rows = [dict(candidate='_baseline_persistence', split=a.split, seed=a.seed,
                 n_params=0, test_err=base),
            dict(candidate='_baseline_saturation', split=a.split, seed=a.seed,
                 n_params=1, test_err=sat)]
    for name in a.candidates.split(','):
        print(f'  fitting {name}...', flush=True)
        ckpt = f'{a.out}.{name}.ckpt' if a.out else ''
        model, tau_s, e_tr, e_te, _ = fit(name, tr, te, dt_s, a.steps,
                                          a.lr, a.seed, ckpt, va=va)
        rows.append(dict(candidate=name, split=a.split, seed=a.seed,
                         n_params=sum(p.numel() for p in model.parameters()) + 1,
                         tau_s=tau_s, horizons_min=list(HORIZONS),
                         train_err=e_tr, test_err=e_te,
                         skill=[t / b for t, b in zip(e_te, base)],
                         skill_worst=max(t / b for t, b in zip(e_te, base))))
        show(name, e_te, str(rows[-1]['n_params']))
        print(f'    tau={tau_s:.0f}s  worst-horizon skill {rows[-1]["skill_worst"]:.3f}',
              flush=True)

    # ranked on the WORST horizon: a good model is good at all three, and a
    # model can fake one horizon (near-persistence at 5 min, slow drift at 45).
    print(f'\n  ranked by worst-horizon skill (lower is better, <1 beats persistence)')
    for r in sorted((r for r in rows if 'skill' in r), key=lambda r: r['skill_worst']):
        print(f'    {r["candidate"]:10s} {r["n_params"]:5d}  '
              f'{"  ".join(f"{x:.3f}" for x in r["skill"])}   worst {r["skill_worst"]:.3f}')
    if a.out:
        json.dump(rows, open(a.out, 'w'), indent=1)
        print(f'wrote {a.out}')


if __name__ == '__main__':
    main()
