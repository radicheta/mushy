"""dAH/dt = -(Q/V)*grad + (C/V)*dT/dt   fitted on idle points. Pooled + per window."""
import sys, importlib.util, numpy as np, csv
from datetime import datetime, timezone
sys.path.insert(0,'src/chambers/fc-core')
spec=importlib.util.spec_from_file_location('fiw','scripts/fit-idle-windows.py'); fiw=importlib.util.module_from_spec(spec); spec.loader.exec_module(fiw)
from fc_core.sim.ambient import AmbientSeries
from fc_core.sim.psychrometrics import CHAMBER_VOLUME_M3 as V, absolute_humidity_g_m3 as ah
SM=fiw.SMOOTH_MIN
amb=AmbientSeries.from_csv('src/chambers/fc-core/fc_core/sim/data/ambient_-34.52_-55.10.recent.csv')
start,end='2026-04-11','2026-08-31'
t0=int(datetime.fromisoformat(start).replace(tzinfo=timezone.utc).timestamp()); t1=int(datetime.fromisoformat(end).replace(tzinfo=timezone.utc).timestamp())
edges=fiw.load_edges(start,end); grid=fiw.load_minutes(start,end)
wins=[w for w in fiw.idle_windows(edges,t0,t1) if w[1]-w[0]>=3600]
X=[];Y=[];W=[];per=[]
for wi,(w0,w1) in enumerate(wins):
    keep=[];ahi={};grad={};tmp={}
    for m in range(w0-w0%60,w1,60):
        s=grid.get(m)
        if s is None or s[0]>=fiw.SAT_RH: continue
        when=datetime.fromtimestamp(m,tz=timezone.utc)
        if when>amb.end: break
        a=amb.at(when); ahi[m]=ah(s[1],s[0]); grad[m]=ahi[m]-ah(a.temp_c,a.rh_pct); tmp[m]=s[1]; keep.append(m)
    if len(keep)<2*SM+10 or max(grad[m] for m in keep)<fiw.MIN_GRAD: continue
    rows=[]
    for i in range(SM,len(keep)-SM):
        a,b=keep[i-SM],keep[i+SM]
        if b-a!=2*SM*60: continue
        hrs=(b-a)/3600
        rows.append((-grad[keep[i]], (tmp[b]-tmp[a])/hrs, (ahi[b]-ahi[a])/hrs, (keep[i]-w0)/60))
    if len(rows)<10: continue
    r=np.array(rows); X.append(r[:,:2]); Y.append(r[:,2]); W.append(np.full(len(r),wi)); per.append((w0,w1,r))
X=np.vstack(X);Y=np.concatenate(Y);since=np.concatenate([p[2][:,3] for p in per])
def fit(A,y):
    c,res,*_=np.linalg.lstsq(A,y,rcond=None); pred=A@c; return c,1-((y-pred)**2).sum()/(y**2).sum()
for label,mask in (('all points',np.ones(len(Y),bool)),('since OFF >= 30 min',since>=30),('since OFF 30..360 min',(since>=30)&(since<=360))):
    x=X[mask];y=Y[mask]
    c1,r1=fit(x[:,:1],y); c2,r2=fit(x,y); c3,r3=fit(x[:,1:],y)
    print(f"{label:24s} n={mask.sum():6d} | 1-param Q={c1[0]*V:.3f} R2={r1:.3f} | 2-param Q={c2[0]*V:.3f} C={c2[1]*V:.3f} g/m3/K R2={r2:.3f} | dT-only C={c3[0]*V:.3f} R2={r3:.3f}")
# per-window: how many windows does the 2-param model describe (R2>=0.7)?
g1=g2=0; qs=[];cs=[]
for w0,w1,r in per:
    c1,r1=fit(r[:,:1],r[:,2]); c2,r2=fit(r[:,:2],r[:,2]); g1+=r1>=0.7; g2+=r2>=0.7; qs.append(c2[0]*V); cs.append(c2[1]*V)
print(f"per-window R2>=0.7: 1-param {g1}/{len(per)}   2-param {g2}/{len(per)}   2-param Q median {np.median(qs):.3f}  C median {np.median(cs):.3f}")
# physical scale: dAH_sat/dT at 10C, 90% RH
print("dAH_sat/dT @10C:",(ah(10.5,100)-ah(9.5,100)),"g/m3/K ; x0.9 =",0.9*(ah(10.5,100)-ah(9.5,100)))
np.save(sys.argv[1]+'/two_reg_XY.npy',np.column_stack([X,Y,since]))
