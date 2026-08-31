"""MUSHY-147: open-loop plant check. Feed the RECORDED relay series into
ChamberModel with recorded temperature and real ambient, and compare predicted
RH against recorded RH. No controller in the path, so any divergence is the
PLANT."""
import subprocess, sys
from datetime import datetime, timezone
sys.path.insert(0, 'src/chambers/fc-core')
from dataclasses import replace
from fc_core.sim.chamber_model import ChamberModel, ChamberParams, CHAMBER_VOLUME_M3
from fc_core.sim.psychrometrics import absolute_humidity_g_m3

START, END, DT = sys.argv[1], sys.argv[2], 10.0

def q(sql):
    out = subprocess.run(['docker','exec','mushy-timescale-1','psql','-U','postgres','-d','postgres',
                          '-At','-F','\t','-c','SET max_parallel_workers_per_gather=0; '+sql],
                         capture_output=True, text=True, check=True).stdout
    return [(float(a), float(b)) for a, b in (l.split('\t') for l in out.splitlines() if l.strip())]

t0 = datetime.fromisoformat(START).replace(tzinfo=timezone.utc).timestamp()
t1 = datetime.fromisoformat(END).replace(tzinfo=timezone.utc).timestamp()
def series(topic, table='telemetry', pad=7200):
    return q(f"select extract(epoch from time), value from {table} where topic='{topic}' "
             f"and time >= to_timestamp({t0}-{pad}) and time <= to_timestamp({t1}) order by time")

rh_r, temp_r, relay_r = series('fc.humidity'), series('fc.temperature'), series('fc.humidifier')
wt, wh = series('weather.temperature','weather'), series('weather.humidity','weather')

def hold(rows, default=0.0):
    xs=[r[0] for r in rows]
    def f(t):
        if not rows or t < xs[0]: return default
        lo,hi=0,len(xs)-1
        while lo<hi:
            mid=(lo+hi+1)//2
            if xs[mid]<=t: lo=mid
            else: hi=mid-1
        return rows[lo][1]
    return f
rh_at, temp_at, relay_at = hold(rh_r,90.0), hold(temp_r,11.0), hold(relay_r,0.0)
whm=dict(wh); amb_at = hold([(ts, absolute_humidity_g_m3(tc, whm[ts])) for ts,tc in wt if ts in whm], 8.0)

FIT  = ChamberParams(fill_g_per_h=19.663523608913977, moisture_loss_m3_per_h=0.5976833669736378,
                     dead_time_s=122.20654905275174, tau_s=198.6267293000804, surface_g_per_k=2.77)
YAML = ChamberParams()

def run(p):
    ch = ChamberModel(p, rh0_pct=rh_at(t0), temp_c=temp_at(t0))
    err=[]; pred=[]
    t=t0
    while t < t1:
        pred.append(ch.rh); err.append(ch.rh - rh_at(t))
        ch.step(relay_at(t), DT, amb_at(t), temp_at(t))
        t += DT
    rmse=(sum(e*e for e in err)/len(err))**0.5
    return rmse, sum(err)/len(err), min(pred), max(pred)

rec=[v for ts,v in rh_r if t0<=ts<=t1]
duty=[relay_at(t0+i*DT) for i in range(int((t1-t0)/DT))]
print(f'{START}..{END}  recorded RH min {min(rec):.2f} max {max(rec):.2f} p2p {max(rec)-min(rec):.2f}')
print(f'recorded relay duty mean {sum(duty)/len(duty):.3f}   temp {temp_at(t0):.1f} -> {temp_at(t1-DT):.1f} C')
print(f'{"params":34s} {"rmse":>6s} {"bias":>7s} {"pred_min":>8s} {"pred_max":>8s}')
C2 = ChamberParams(fill_g_per_h=18.82, moisture_loss_m3_per_h=1.023,
                   dead_time_s=122.0, tau_s=199.0, surface_g_per_k=2.0)
AFT = ChamberParams(fill_g_per_h=18.82, moisture_loss_m3_per_h=18.82/14.1,
                    dead_time_s=122.0, tau_s=199.0, surface_g_per_k=2.0)
for name,p in (('fit C=2.77 (F 19.66 Q 0.598)',FIT),('yaml     (F 3.89  Q 0.553)',YAML),
               ('refit C=2.0 (F 18.82 Q 1.023)',C2),('C=2.0, Q from afternoon F/Q=14.1',AFT)):
    r,b,lo,hi = run(p)
    print(f'{name:34s} {r:6.2f} {b:+7.2f} {lo:8.2f} {hi:8.2f}')

# What Q would the recorded steady state imply, given F?
import statistics
mid = [(t0+i*DT) for i in range(int((t1-t0)/DT))]
ah_in = [absolute_humidity_g_m3(temp_at(t), rh_at(t)) for t in mid]
ah_amb= [amb_at(t) for t in mid]
deficit = statistics.mean(a-b for a,b in zip(ah_in,ah_amb))
d_mean = sum(duty)/len(duty)
print(f'\nmean AH inside {statistics.mean(ah_in):.2f} ambient {statistics.mean(ah_amb):.2f} '
      f'deficit {deficit:.2f} g/m3')
for F in (FIT.fill_g_per_h, YAML.fill_g_per_h):
    print(f'  steady-state Q implied by F={F:6.2f} and duty {d_mean:.3f}: {F*d_mean/deficit:.3f} m3/h')
