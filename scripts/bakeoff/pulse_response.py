"""MUSHY-150: does a fitted candidate reproduce the measured per-pulse RH bump on
the open-loop probe days (<90% RH)? Measured +0.31 pts/min at lag 150 s; the
physics candidates give +0.06. Run with BAKEOFF_CORPUS=scripts/bakeoff/corpus-probe.npz."""
import sys, glob, re, numpy as np, torch
sys.path.insert(0,'scripts/bakeoff')
from run import CANDIDATES, TAU_LO, TAU_HI, ah_sat, load, rollout, windows, HORIZONS
tr_d, te_d, dt_s = load('chrono')
te = windows(te_d, dt_s, max(HORIZONS))
day = np.array([d.split('+')[0] for d in te['dates']])
m = np.isin(day, ('2026-09-01','2026-09-02')) & (te['rh'][:,0] < 90).numpy()
n=len(te['ah']); w = {k:(v[m] if hasattr(v,'__len__') and len(v)==n else v) for k,v in te.items()}
u = w['duty'].numpy(); rh = w['rh'].numpy()
def onoff(series, lag_s):
    k=int(lag_s/dt_s); d=np.gradient(series, dt_s, axis=1)*60   # pts/min
    on=u[:, :series.shape[1]-k]>0.5; dd=d[:, k:]
    return dd[on].mean(), dd[~on].mean()
print(f'probe<90 windows: {m.sum()}   ACTUAL dRH/dt at lag 150s: on={onoff(rh,150)[0]:+.3f} off={onoff(rh,150)[1]:+.3f} pts/min')
for ck in sorted(glob.glob('scripts/bakeoff/results/chrono-*-s0.json.*.ckpt')):
    name=re.search(r'chrono-(\w+)-s0',ck).group(1); c=torch.load(ck,weights_only=False)
    model=CANDIDATES[name](); model.load_state_dict(c['model']); tau=TAU_LO+(TAU_HI-TAU_LO)*torch.sigmoid(c['log_tau'])
    with torch.no_grad(): pred=rollout(model,tau,w,dt_s).numpy()
    p={k:round(float(v),3) for k,v in model.state_dict().items() if v.numel()==1}
    F = np.exp(p['logF']) if 'logF' in p else float('nan')
    on,off = onoff(pred,150)
    print(f'  {name:8s} tau={float(tau):4.0f}s dead={float(model.delay_s()):3.0f}s F={F:5.2f} g/h  Q={np.exp(p.get("logQ",np.nan)):.2f} C={p.get("C","-")}   MODEL dRH/dt on={on:+.3f} off={off:+.3f}   on-off model {on-off:+.3f} vs actual {onoff(rh,150)[0]-onoff(rh,150)[1]:+.3f}')
