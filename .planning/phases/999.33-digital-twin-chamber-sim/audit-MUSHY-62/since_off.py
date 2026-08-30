"""Pool every clean derivative point across all idle windows, bucket by minutes since the relay dropped, fit Q per bucket through the origin. Direct reconciliation with MUSHY-60 FIT-RESULTS 'Q is regime-dependent'."""
import sys, importlib.util
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
bins=[(1,3),(4,8),(9,16),(17,40),(41,120),(121,360),(361,100000)]
acc={b:[0.0,0.0,0,0.0] for b in bins}   # num, den, n, sum dT/dt
accH={b:{ 'cool':[0.0,0.0,0], 'warm':[0.0,0.0,0]} for b in bins}
for w0,w1 in wins:
    keep=[];ahi={};grad={};tmp={}
    for m in range(w0-w0%60,w1,60):
        s=grid.get(m)
        if s is None or s[0]>=fiw.SAT_RH: continue
        when=datetime.fromtimestamp(m,tz=timezone.utc)
        if when>amb.end: break
        a=amb.at(when); ahi[m]=ah(s[1],s[0]); grad[m]=ahi[m]-ah(a.temp_c,a.rh_pct); tmp[m]=s[1]; keep.append(m)
    if len(keep)<2*SM+10 or max(grad[m] for m in keep)<fiw.MIN_GRAD: continue
    for i in range(SM,len(keep)-SM):
        a,b=keep[i-SM],keep[i+SM]
        if b-a!=2*SM*60: continue
        y=(ahi[b]-ahi[a])/((b-a)/3600); x=-grad[keep[i]]; dT=(tmp[b]-tmp[a])/((b-a)/3600)
        since=(keep[i]-w0)/60
        for bb in bins:
            if bb[0]<=since<=bb[1]:
                acc[bb][0]+=x*y; acc[bb][1]+=x*x; acc[bb][2]+=1; acc[bb][3]+=dT
                h=accH[bb]['cool' if dT<-0.3 else 'warm']; h[0]+=x*y; h[1]+=x*x; h[2]+=1
                break
print("minutes since OFF   Q(m3/h)      n    mean dT/dt   | Q cooling(<-0.3C/h)  n | Q not-cooling  n")
for b in bins:
    num,den,n,sdt=acc[b]; c=accH[b]['cool']; w=accH[b]['warm']
    q=lambda a:(a[0]/a[1]*V if a[1] else float('nan'))
    print(f"{b[0]:>4d}-{b[1]:<6d}       {num/den*V if den else float('nan'):6.3f}   {n:6d}   {sdt/n if n else 0:+.2f} C/h   |  {q(c):6.3f}  {c[2]:6d} |  {q(w):6.3f}  {w[2]:6d}")
