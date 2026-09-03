"""MUSHY-150 duty probe 48b/48c coverage: usable minutes, gain by RH band, sine lock-in.
Inputs: a dir with duty-probe-probe48{b,c}.csv and <topic>.csv exports (epoch,value)
for fc.humidifier_duty fc.humidity fc.temperature weather.temperature weather.humidity.
    .venv/bin/python scripts/bakeoff/probe_coverage.py <dir>
RH in Timescale is PERCENT."""
import csv, sys, datetime as dt
import numpy as np
sys.path.insert(0, '/mnt/slime-kingdom/opt/mushy/src/chambers/fc-core')
from fc_core.sim.psychrometrics import absolute_humidity_g_m3 as ah

S = sys.argv[1].rstrip('/') + '/'  # dir with duty-probe-*.csv + Timescale exports (see docstring)
ah = np.vectorize(ah)

def load(t):
    a = np.loadtxt(S + t + '.csv', delimiter=',')
    return a[:, 0], a[:, 1]

def iso(s): return dt.datetime.fromisoformat(s.replace('Z', '+00:00')).timestamp()
def fmt(ts): return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime('%m-%d %H:%MZ')

# ---- commanded schedule (ZOH) ------------------------------------------------
rows = []
for lab, end in (('probe48b', '2026-09-02T20:08:00Z'), ('probe48c', '2026-09-03T11:58:49Z')):
    r = list(csv.DictReader(open(S + f'duty-probe-{lab}.csv')))
    for x in r: rows.append((iso(x['iso']), float(x['duty']), x['phase'], lab))
    rows.append((iso(end), np.nan, 'end', lab))
rows.sort()
ct = np.array([r[0] for r in rows]); cd = np.array([r[1] for r in rows]); cp = [r[2] for r in rows]

DT = 10.0
t = np.arange(iso('2026-09-01T20:10:00Z'), iso('2026-09-03T12:00:00Z'), DT)
idx = np.searchsorted(ct, t, side='right') - 1
cmd = np.where(idx >= 0, cd[np.clip(idx, 0, None)], np.nan)
phase = np.array([cp[i] if i >= 0 else 'none' for i in idx])
forced = ~np.isnan(cmd)
# guard minutes: from an override row until the next hold/ramp/sine row
guard = np.zeros_like(t, bool)
for i, r in enumerate(rows):
    if r[2].endswith('override'):
        j = i + 1
        while j < len(rows) and rows[j][2].endswith('override'): j += 1
        guard |= (t >= r[0]) & (t < rows[j][0])

# ---- measured ----------------------------------------------------------------
dt_, dv = load('fc.humidifier_duty'); duty = np.interp(t, dt_, dv)
ht, hv = load('fc.humidity');        rh = np.interp(t, ht, hv) / 100
tt, tv = load('fc.temperature');     T = np.interp(t, tt, tv)
wt, wv = load('weather.temperature'); wh, whv = load('weather.humidity')
Tout = np.interp(t, wt, wv); RHout = np.interp(t, wh, whv)
ah_in = ah(T, rh * 100); ah_out = ah(Tout, RHout); ah_sat = ah(T, 100.0)
gap_sat = ah_sat - ah_out          # room left for the outside air to "pull"

# ---- 1. did the chamber run what was commanded? ------------------------------
mn = ((t - t[0]) // 60).astype(int)
def per_min(x, f=np.nanmean):
    return np.array([f(x[mn == k]) for k in range(mn.max() + 1)])
m_cmd, m_duty = per_min(cmd), per_min(duty)
m_forced = per_min(forced.astype(float)) == 1
m_trans = per_min(cmd, np.nanstd) > 1e-6
ok = m_forced & ~m_trans
mism = ok & (np.abs(m_cmd - m_duty) > 0.02)
print(f'forced minutes {ok.sum()}  commanded-vs-actual mismatches >0.02: {mism.sum()}')
if mism.sum():
    for k in np.where(mism)[0][:10]:
        print('  ', fmt(t[0] + 60 * k), f'cmd {m_cmd[k]:.3f} actual {m_duty[k]:.3f}')

# ---- 2. usable minutes --------------------------------------------------------
sat97, sat95 = rh >= 0.97, rh >= 0.95
restart = (t >= iso('2026-09-03T06:39:00Z')) & (t < iso('2026-09-03T06:48:00Z'))  # fc-core restarted twice; chamber was on PID then duty 1.0
usable = forced & ~guard & ~sat97 & ~restart
print('\nhours: forced %.1f  guard %.1f  RH>=0.97 %.1f  RH>=0.95 %.1f  USABLE(<0.97,no guard) %.1f  usable(<0.95) %.1f' % tuple(
    x.sum() * DT / 3600 for x in (forced, forced & guard, forced & sat97, forced & sat95, usable, usable & ~sat95)))
for lab in ('probe48b', 'probe48c'):
    m = np.array([r == lab for r in [rows[i][3] if i >= 0 else '' for i in idx]]) & forced
    print(f'  {lab}: forced {m.sum()*DT/3600:.1f} h, usable {(m&usable).sum()*DT/3600:.1f} h, RH>=0.97 {(m&sat97).sum()*DT/3600:.1f} h')

# saturated stretches
edges = np.diff(np.r_[0, (forced & sat97).astype(int), 0])
for a, b in zip(np.where(edges == 1)[0], np.where(edges == -1)[0]):
    if (b - a) * DT > 1800:
        print(f'  saturated {fmt(t[a])} -> {fmt(t[b-1])}  ({(b-a)*DT/3600:.1f} h)  T {T[a:b].min():.1f}-{T[a:b].max():.1f}  mean cmd duty {np.nanmean(cmd[a:b]):.2f}')

# ---- 3. coverage of duty x conditions in usable minutes -----------------------
print('\nCOVERAGE (usable minutes)')
bins = [(-0.001, 0.001, 'duty 0'), (0.001, 0.1, '0-0.1'), (0.1, 0.2, '0.1-0.2'), (0.2, 0.35, '0.2-0.35'), (0.35, 0.999, '0.35-1'), (0.999, 1.001, 'duty 1')]
for lo, hi, name in bins:
    m = usable & (cmd > lo) & (cmd <= hi)
    if m.sum(): print(f'  {name:9s} {m.sum()*DT/60:6.0f} min   RH {rh[m].min():.3f}-{rh[m].max():.3f}  T {T[m].min():.1f}-{T[m].max():.1f}')
for name, x in (('T_in', T), ('T_out', Tout), ('RH_out', RHout), ('AH_in', ah_in), ('AH_out', ah_out), ('AHsat_in - AH_out', gap_sat), ('AH_in - AH_out', ah_in - ah_out)):
    print(f'  {name:18s} usable: {np.percentile(x[usable],5):6.2f} .. {np.percentile(x[usable],95):6.2f}   all forced: {x[forced].min():6.2f} .. {x[forced].max():6.2f}')

print('\nUSABLE MINUTES by RH band x duty bin')
for lo_r, hi_r in ((0.80, 0.90), (0.90, 0.95), (0.95, 0.97)):
    row = []
    for lo, hi, name in bins:
        mm = usable & (cmd > lo) & (cmd <= hi) & (rh >= lo_r) & (rh < hi_r)
        row.append(f'{name} {mm.sum()*DT/60:4.0f}')
    print(f'  RH {lo_r:.2f}-{hi_r:.2f}: ' + ' | '.join(row))

# ---- 4. hold segments: RH slope vs duty ---------------------------------------
print('\nHOLD SEGMENTS: RH slope (pts/10min) after 3 min dead time, usable only')
segs = []
for i, r in enumerate(rows[:-1]):
    if r[2] != 'hold': continue
    a, b = r[0] + 180, rows[i + 1][0]
    m = (t >= a) & (t < b) & usable
    if m.sum() * DT < 300: continue
    x = (t[m] - a) / 600; y = rh[m] * 100
    slope = np.polyfit(x, y, 1)[0]
    segs.append((r[1], slope, T[m].mean(), gap_sat[m].mean(), rh[m].mean(), (b - a) / 60))
segs = np.array(segs)
print(f'  n={len(segs)}  duty levels: {np.unique(np.round(segs[:,0],2)).size}  duty range {segs[:,0].min():.2f}-{segs[:,0].max():.2f}')
d, s = segs[:, 0], segs[:, 1]
X = np.c_[np.ones_like(d), d]
b_, res, *_ = np.linalg.lstsq(X, s, rcond=None)
r = np.corrcoef(d, s)[0, 1]
print(f'  slope = {b_[0]:+.2f} + {b_[1]:+.2f}*duty   r={r:.2f}  (n={len(d)})')
for lo, hi in ((0, 0.1), (0.1, 0.2), (0.2, 0.36), (0.36, 1.01)):
    m = (d > lo - 1e-9) & (d <= hi) if lo else (d <= hi)
    if m.sum(): print(f'    duty {lo:.2f}-{hi:.2f}: n={m.sum():2d}  mean slope {s[m].mean():+.2f}  sd {s[m].std():.2f}')
# same, excluding rails, with gap as a second regressor
m = d < 0.99
X = np.c_[np.ones(m.sum()), d[m], segs[m, 3]]
b2, *_ = np.linalg.lstsq(X, s[m], rcond=None)
pred = X @ b2; r2 = 1 - ((s[m] - pred) ** 2).sum() / ((s[m] - s[m].mean()) ** 2).sum()
print(f'  no rails, + gap term: slope = {b2[0]:+.2f} + {b2[1]:+.2f}*duty {b2[2]:+.2f}*gap   R2={r2:.2f} (n={m.sum()})')
# by mean RH of the segment (saturation proximity)
for lo, hi in ((0, 0.90), (0.90, 0.95), (0.95, 0.97)):
    m = (segs[:, 4] >= lo) & (segs[:, 4] < hi) & (d < 0.99)
    if m.sum() > 3:
        rr = np.corrcoef(d[m], s[m])[0, 1]; bb = np.polyfit(d[m], s[m], 1)[0]
        print(f'    segment RH {lo:.2f}-{hi:.2f}: n={m.sum():2d}  gain {bb:+.2f}/duty  r={rr:.2f}  duty levels {np.unique(np.round(d[m],2)).size}  duty 0-0.1 n={(d[m]<=0.1).sum()} 0.1-0.2 n={((d[m]>0.1)&(d[m]<=0.2)).sum()} 0.2-0.35 n={((d[m]>0.2)&(d[m]<=0.35)).sum()}')

# ---- 5. sine blocks: lock-in --------------------------------------------------
print('\nSINE BLOCKS: lock-in at the drive period (RH pts per unit duty, phase lag)')
blocks = []
cur = None
for i, r in enumerate(rows):
    if r[2].startswith('sine'):
        if cur is None or cur[2] != r[2]: cur = [r[0], None, r[2]]; blocks.append(cur)
        cur[1] = rows[i + 1][0]
    else: cur = None
for a, b, kind in blocks:
    m = (t >= a) & (t < b)
    x = t[m] - a; y = rh[m] * 100; u = cmd[m]
    up = np.where(np.diff((u > u.mean()).astype(int)) == 1)[0]
    P = np.mean(np.diff(x[up])) if len(up) > 1 else 60.0 * int(kind.split('-')[1])
    # detrend RH with a quadratic (thermal drift), duty with mean
    y = y - np.polyval(np.polyfit(x, y, 2), x); u = u - u.mean()
    def lockin(sig, per):
        w = 2 * np.pi / per
        return (sig * np.exp(-1j * w * x)).mean() * 2
    Yf, Uf = lockin(y, P), lockin(u, P)
    gain = abs(Yf) / abs(Uf); lag = -np.angle(Yf / Uf) / (2 * np.pi) * P / 60
    noise = np.mean([abs(lockin(y, P * f)) for f in (0.7, 0.8, 1.25, 1.4)])
    print(f'  {fmt(a)} {kind:7s} {(b-a)/3600:.1f} h P={P/60:.0f}min  RH {rh[m].min():.3f}-{rh[m].max():.3f} sat97 {sat97[m].mean()*100:3.0f}%  guard {guard[m].mean()*100:3.0f}%'
          f'  |RH@f| {abs(Yf):.2f} pts (off-f {noise:.2f})  gain {gain:.1f} pts/duty  lag {lag:.1f} min')

print('\nUSABLE MINUTES by local hour (UTC-3), and by RH<0.90')
hl = ((t / 3600 - 3) % 24).astype(int)
for h0 in range(0, 24, 3):
    m = usable & (hl >= h0) & (hl < h0 + 3); m9 = m & (rh < 0.90)
    print(f'  {h0:02d}-{h0+3:02d}h: usable {m.sum()*DT/60:4.0f} min  RH<0.90 {m9.sum()*DT/60:4.0f} min  T {T[m].min() if m.sum() else 0:.1f}-{T[m].max() if m.sum() else 0:.1f}')
print('\nsine row cadence (s) per block:')
for a, b, kind in blocks:
    rr = [r[0] for r in rows if a <= r[0] < b and r[2] == kind]
    print(f'  {fmt(a)} {kind}: {len(rr)} rows, mean step {np.mean(np.diff(rr)):.1f} s, span {(rr[-1]-rr[0])/3600:.2f} h')
