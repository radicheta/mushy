"""Per-window diagnostics for the idle-window Q fit, with a skip-first-N-min sweep."""
import sys, csv, importlib.util
from datetime import datetime, timezone
sys.path.insert(0,'src/chambers/fc-core')
spec=importlib.util.spec_from_file_location('fiw','scripts/fit-idle-windows.py'); fiw=importlib.util.module_from_spec(spec); spec.loader.exec_module(fiw)
from fc_core.sim.ambient import AmbientSeries
from fc_core.sim.psychrometrics import CHAMBER_VOLUME_M3, absolute_humidity_g_m3 as ah
SM=fiw.SMOOTH_MIN
amb=AmbientSeries.from_csv('src/chambers/fc-core/fc_core/sim/data/ambient_-34.52_-55.10.recent.csv')
start,end='2026-04-11','2026-08-31'
t0=int(datetime.fromisoformat(start).replace(tzinfo=timezone.utc).timestamp()); t1=int(datetime.fromisoformat(end).replace(tzinfo=timezone.utc).timestamp())
edges=fiw.load_edges(start,end); grid=fiw.load_minutes(start,end)
wins=[w for w in fiw.idle_windows(edges,t0,t1) if w[1]-w[0]>=3600]

def fit(w0,w1,skip_min):
    ws=w0+skip_min*60
    mins=range(ws-ws%60,w1,60)
    ahi,grad,keep,temp,aho={}, {}, [], {}, {}
    for m in mins:
        s=grid.get(m)
        if s is None: continue
        rh,t=s
        if rh>=fiw.SAT_RH: continue
        when=datetime.fromtimestamp(m,tz=timezone.utc)
        if when>amb.end: return None
        a=amb.at(when)
        ahi[m]=ah(t,rh); aho[m]=ah(a.temp_c,a.rh_pct); grad[m]=ahi[m]-aho[m]; temp[m]=t; keep.append(m)
    if len(keep)<2*SM+10 or max(grad[m] for m in keep)<fiw.MIN_GRAD: return None
    num=den=0.0; pts=[]
    for i in range(SM,len(keep)-SM):
        a,b=keep[i-SM],keep[i+SM]
        if b-a!=2*SM*60: continue
        y=(ahi[b]-ahi[a])/((b-a)/3600); x=-grad[keep[i]]
        num+=x*y; den+=x*x; pts.append((x,y))
    if len(pts)<10 or den<=0: return None
    slope=num/den; ssr=sum((y-slope*x)**2 for x,y in pts); sst=sum(y*y for _,y in pts)
    k0,k1=keep[0],keep[-1]; hrs=(k1-k0)/3600
    return dict(q=slope*CHAMBER_VOLUME_M3, r2=1-ssr/sst if sst else float('nan'), n=len(pts),
        hours=(w1-w0)/3600, grad0=grad[k0], grad1=grad[k1], dahi=ahi[k1]-ahi[k0], daho=aho[k1]-aho[k0],
        temp0=temp[k0], dT=temp[k1]-temp[k0], dTdt=(temp[k1]-temp[k0])/hrs if hrs else 0, tmean=sum(temp[m] for m in keep)/len(keep),
        start=datetime.fromtimestamp(w0,tz=timezone.utc).isoformat())

for skip in (0,15,30,60):
    rows=[r for w0,w1 in wins if (r:=fit(w0,w1,skip))]
    with open(f'{sys.argv[1]}/idle_windows_skip{skip}.csv','w',newline='') as f:
        wr=csv.DictWriter(f,fieldnames=list(rows[0].keys())); wr.writeheader(); wr.writerows(rows)
    import statistics as st
    good=[r for r in rows if r['r2']>=0.7]; bad=[r for r in rows if r['r2']<0.7]
    print(f"skip {skip:3d} min: n={len(rows)}  well-fit n={len(good)} Q med {st.median(r['q'] for r in good):.3f} len med {st.median(r['hours'] for r in good):.2f}h | poor n={len(bad)} Q med {st.median(r['q'] for r in bad):.3f} | all Q med {st.median(r['q'] for r in rows):.3f}")
