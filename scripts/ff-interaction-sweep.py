"""MUSHY-145: does a self-tune push that writes fill_g_per_h move the MUSHY-125
temperature feedforward under the farmer's feet?

PLANT is held at the fitted (best-estimate-true) chamber in every arm; only
what the CONTROLLER BELIEVES (params_belief) and the trim change. That is the
question: F is a divisor in temp_feedforward_gain, so writing F rewrites the
feedforward even though nobody asked to change it.

Driven with the REAL recorded chamber temperature and REAL ambient over an
afternoon ramp, the regime where MUSHY-125 oscillated.
"""
import subprocess, sys
from datetime import datetime, timezone
sys.path.insert(0, 'src/chambers/fc-core')
from dataclasses import replace
from fc_core.sim.chamber_model import ChamberParams
from fc_core.sim.replay import run_closed_loop, DEFAULT_BAND
from fc_core.sim.control_loop import Gains
from fc_core.sim.pwm_sigma_delta import SigmaDeltaSimulator, SigmaDeltaConfig
from fc_core.control_kernel import temp_feedforward_gain
from fc_core.sim.psychrometrics import absolute_humidity_g_m3

START, END = sys.argv[1], sys.argv[2]

def q(sql):
    out = subprocess.run(['docker','exec','mushy-timescale-1','psql','-U','postgres','-d',
                          'postgres','-At','-F','\t','-c','SET max_parallel_workers_per_gather=0; '+sql],
                         capture_output=True, text=True, check=True).stdout
    return [(float(a), float(b)) for a, b in (l.split('\t') for l in out.splitlines() if l.strip())]

t0 = datetime.fromisoformat(START).replace(tzinfo=timezone.utc).timestamp()
t1 = datetime.fromisoformat(END).replace(tzinfo=timezone.utc).timestamp()

def series(topic, table='telemetry'):
    return q(f"select extract(epoch from time), value from {table} where topic='{topic}' "
             f"and time >= to_timestamp({t0}-3600) and time <= to_timestamp({t1}) order by time")

temp_rows = series('fc.temperature')
rh_rows = series('fc.humidity')
wt = series('weather.temperature', 'weather')
wh = series('weather.humidity', 'weather')

def hold(rows):
    """sample-and-hold lookup on elapsed seconds from t0"""
    xs = [r[0] for r in rows]
    def f(elapsed):
        t = t0 + elapsed
        lo, hi = 0, len(xs) - 1
        if t <= xs[0]: return rows[0][1]
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if xs[mid] <= t: lo = mid
            else: hi = mid - 1
        return rows[lo][1]
    return f

temp_at = hold(temp_rows)
wh_map = dict(wh)
amb_rows = [(ts, absolute_humidity_g_m3(tc, wh_map[ts])) for ts, tc in wt if ts in wh_map]
amb_at = hold(amb_rows)

# Plant: tonight's fit (MUSHY-138, n=2). C is carried, not fitted.
PLANT = ChamberParams(fill_g_per_h=19.663523608913977,
                      moisture_loss_m3_per_h=0.5976833669736378,
                      dead_time_s=122.20654905275174,
                      tau_s=198.6267293000804,
                      surface_g_per_k=2.77)
YAML_BELIEF = ChamberParams()          # F=3.890, what fc1 believes today
hours = (t1 - t0) / 3600.0
rh0 = next(v for ts, v in rh_rows if ts >= t0)

# Trim that preserves today's effective feedforward at the window's operating point.
tmid = temp_at(hours * 1800)
g_old = temp_feedforward_gain(0.90, tmid, YAML_BELIEF.fill_g_per_h, 2.77)
g_new = temp_feedforward_gain(0.90, tmid, PLANT.fill_g_per_h, 2.77)
rescaled = 0.4 * g_old / g_new
print(f'window {START}..{END}  {hours:.1f} h  rh0={rh0:.2f}  temp@mid={tmid:.2f} C')
print(f'FF gain duty per (C/h): believing F=3.89 -> {g_old:.4f}, believing F=19.66 -> {g_new:.4f}'
      f'  (ratio {g_old/g_new:.2f}x)')
print(f'trim preserving effective FF: 0.4 -> {rescaled:.2f}\n')

LIVE = Gains(kp=0.36, ki=0.001, kd=4.0, derivative_filter_tau=60.0,
             integrator_decay_tau=300.0, bypass_threshold=0.05)

ARMS = [
    ('a today   F_belief=3.89  trim=0.40', YAML_BELIEF, 0.4),
    ('b pushed  F_belief=19.66 trim=0.40', PLANT, 0.4),
    ('c pushed  F_belief=19.66 trim=%.2f' % rescaled, PLANT, rescaled),
    ('d pushed  F_belief=19.66 trim=0    ', PLANT, 0.0),
]
print(f'{"arm":38s} {"rh_min":>7s} {"rh_max":>7s} {"p2p":>6s} {"mean":>6s} '
      f'{"duty":>6s} {"cyc/h":>6s} {"min<88.5":>9s}')
for label, belief, trim in ARMS:
    m = run_closed_loop(hours, params=PLANT, band=DEFAULT_BAND, gains=LIVE, rh0=rh0,
                        temp_ff_gain=trim, params_belief=belief,
                        ambient_ah_g_m3=amb_at, temp_c=temp_at,
                        pwm=SigmaDeltaSimulator(SigmaDeltaConfig()), dt=1.0)
    below = sum(1 for v in m.rh_series if v < 88.5) / 60.0
    print(f'{label:38s} {m.rh_min:7.2f} {m.rh_max:7.2f} {m.rh_p2p:6.2f} {m.rh_mean:6.2f} '
          f'{m.duty_mean_commanded:6.3f} {m.relay_cycles_per_hour:6.1f} {below:8.0f}m')

rec = [v for ts, v in rh_rows if t0 <= ts <= t1]
print(f'\nRECORDED over the same window: min {min(rec):.2f} max {max(rec):.2f} '
      f'p2p {max(rec)-min(rec):.2f} mean {sum(rec)/len(rec):.2f}')
