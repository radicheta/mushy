import sys, importlib.util, numpy as np
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
rows=[]; moh_T=np.zeros(60); moh_A=np.zeros(60); moh_n=np.zeros(60)
for w0,w1 in wins:
    keep=[];ahi={};grad={};tmp={};tdiff={}
    for m in range(w0-w0%60,w1,60):
        s=grid.get(m)
        if s is None or s[0]>=fiw.SAT_RH: continue
        when=datetime.fromtimestamp(m,tz=timezone.utc)
        if when>amb.end: break
        a=amb.at(when); ahi[m]=ah(s[1],s[0]); grad[m]=ahi[m]-ah(a.temp_c,a.rh_pct); tmp[m]=s[1]; tdiff[m]=s[1]-a.temp_c; keep.append(m)
    if len(keep)<2*SM+10 or max(grad[m] for m in keep)<fiw.MIN_GRAD: continue
    for i in range(SM,len(keep)-SM):
        a,b=keep[i-SM],keep[i+SM]
        if b-a!=2*SM*60: continue
        hrs=(b-a)/3600; k=keep[i]
        rows.append((-grad[k],(tmp[b]-tmp[a])/hrs,(ahi[b]-ahi[a])/hrs,tdiff[k],(k-w0)/60, datetime.fromtimestamp(k,tz=timezone.utc).hour))
    # minute-of-hour stack: detrend with a 61-min centred running mean
    ks=np.array(keep); T=np.array([tmp[k] for k in keep]); A=np.array([ahi[k] for k in keep])
    if len(ks)<180: continue
    for i in range(30,len(ks)-30):
        if ks[i+30]-ks[i-30]!=3600: continue
        mo=(ks[i]//60)%60
        moh_T[mo]+=T[i]-T[i-30:i+31].mean(); moh_A[mo]+=A[i]-A[i-30:i+31].mean(); moh_n[mo]+=1
r=np.array(rows); X=r[:,:2]; Y=r[:,2]; td=r[:,3]; since=r[:,4]; hour=r[:,5]
def fit(A,y):
    c,*_=np.linalg.lstsq(A,y,rcond=None); return c,1-((y-A@c)**2).sum()/(y**2).sum()
print("split by chamber-minus-ambient TEMPERATURE (vent would flip C's sign; condensation would not)")
for label,mask in (("chamber WARMER than outside (Tin-Tout > +0.5)",td>0.5),("chamber COLDER than outside (Tin-Tout < -0.5)",td<-0.5),("|Tin-Tout|<=0.5",np.abs(td)<=0.5)):
    m=mask&(since>=30); c,r2=fit(X[m],Y[m]); c1,r1=fit(X[m][:,:1],Y[m])
    print(f"  {label:48s} n={m.sum():6d}  Q={c[0]*V:6.3f} C={c[1]*V:6.3f} R2={r2:.3f}   (1-param Q={c1[0]*V:.3f} R2={r1:.3f})")
print("\nsplit by sign of dT/dt (condensation on cooling vs re-evaporation on warming: same C if reversible)")
for label,mask in (("cooling dT/dt<-0.2",X[:,1]<-0.2),("warming dT/dt>+0.2",X[:,1]>0.2),("steady |dT/dt|<=0.2",np.abs(X[:,1])<=0.2)):
    m=mask&(since>=30); c,r2=fit(X[m],Y[m])
    print(f"  {label:24s} n={m.sum():6d}  Q={c[0]*V:6.3f} C={c[1]*V:6.3f} R2={r2:.3f}")
print("\nsteady-only 1-param Q (|dT/dt|<=0.1 C/h, since OFF>=30):",end=' ')
m=(np.abs(X[:,1])<=0.1)&(since>=30); c1,r1=fit(X[m][:,:1],Y[m]); print(f"Q={c1[0]*V:.3f} R2={r1:.3f} n={m.sum()}")
print("\nminute-of-hour stack of detrended chamber temp / AH inside idle windows (vent on a wall-clock timer would show here):")
print(" min   dT(mC)   dAH(mg/m3)  n")
for mo in range(0,60,3):
    print(f" {mo:3d}  {1000*moh_T[mo]/moh_n[mo]:+7.1f}   {1000*moh_A[mo]/moh_n[mo]:+8.2f}  {int(moh_n[mo])}")
print("range of stacked dT (mC): %.1f   range of stacked dAH (mg/m3): %.2f"%(1000*(moh_T/moh_n).ptp(),1000*(moh_A/moh_n).ptp()))
