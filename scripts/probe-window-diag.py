"""Per-window probe diagnostics: why a window fits or rails (MUSHY-148).\n\nPrints each probe window's shape (RH rise, temp direction, relay ON time) next\nto its fit, then refits at C*0.75 and C*1.25 so the PER-WINDOW F/Q sensitivity\nto the assumed surface term is visible -- aggregate() only reports the median\nacross windows, which hides it (2026-08-31: median spread 1.08x while every\nwindow moved 2x-27x).\n\n  PYTHONPATH=src/chambers/fc-core .venv/bin/python scripts/probe-window-diag.py\n"""
import importlib.util, sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src' / 'chambers' / 'fc-core'))
spec = importlib.util.spec_from_file_location('fp', ROOT / 'scripts' / 'self-tune' / 'fit-probes.py')
fp = importlib.util.module_from_spec(spec); spec.loader.exec_module(fp)

from fc_core.sim.chamber_model import ChamberParams
from fc_core.sim.probe_fit import find_windows, fit_window
from fc_core.sim.psychrometrics import absolute_humidity_g_m3

now = datetime.now(timezone.utc)
t0w = now - timedelta(days=14)
w0, w1 = (t0w - timedelta(hours=1)).timestamp(), now.timestamp()
amb = fp.weather_series(*(fp.load(f'weather.{k}', w0, w1, table='weather')
                          for k in ('temperature', 'humidity', 'precipitation')), hold_until=w1)
t1 = min(now, amb.end); t0 = max(t0w, amb.start)
e0, e1 = t0.timestamp(), t1.timestamp()
DT = fp.DT
rh = fp.resample(fp.load('fc.humidity', e0, e1), e0, e1, DT)
temp = fp.resample(fp.load('fc.temperature', e0, e1), e0, e1, DT)
relay = fp.resample(fp.load('fc.humidifier', e0 - 86400, e1), e0, e1, DT, initial=0.0)
probe = fp.resample(fp.load('fc.probe', e0, e1), e0, e1, DT, initial=0.0)
ambient = []
t = e0
while t < e1:
    s = amb.at(datetime.fromtimestamp(t, tz=timezone.utc)); ambient.append(absolute_humidity_g_m3(s.temp_c, s.rh_pct)); t += DT
rh = [x * 100.0 if x <= 1.0 else x for x in rh]

wins = find_windows(DT, rh, temp, ambient, relay, probe)
base = ChamberParams()
print(f'{len(wins)} windows\n')
for i, w in enumerate(wins, 1):
    k = w.probe_start_idx
    on = sum(1 for r in w.relay if r > 0.5) * DT
    on_pre = sum(1 for r in w.relay[:k] if r > 0.5) * DT
    on_post = sum(1 for r in w.relay[k:] if r > 0.5) * DT
    post = w.rh[k:]
    rise = max(post) - w.rh[k]
    f = fit_window(w, base)
    print(f'--- window {i} ---')
    print(f'  len {len(w.rh)*DT/60:.0f} min, probe at +{k*DT/60:.0f} min')
    print(f'  RH  start {w.rh[k]:.2f}  min {min(w.rh):.2f}  max {max(w.rh):.2f}  end {w.rh[-1]:.2f}  rise-after-probe {rise:+.2f}')
    print(f'  T   {w.temp[0]:.2f} -> {w.temp[-1]:.2f}  (move {max(w.temp)-min(w.temp):.2f} C)')
    print(f'  relay ON total {on:.0f}s  (pre {on_pre:.0f}s / post {on_post:.0f}s)')
    print(f'  ambient AH {min(w.ambient_ah):.2f}..{max(w.ambient_ah):.2f}')
    print(f'  fit F={f.fill_g_per_h:.2f} Q={f.moisture_loss_m3_per_h:.3f} th={f.dead_time_s:.0f} tau={f.tau_s:.0f} rmse={f.rmse_pct:.3f} rej={f.rejected!r}')
    for scale in (0.75, 1.25):
        b = replace(base, surface_g_per_k=base.surface_g_per_k * scale)
        g = fit_window(w, b)
        fq = g.fill_g_per_h / g.moisture_loss_m3_per_h if g.moisture_loss_m3_per_h else float('nan')
        print(f'    C*{scale}: F={g.fill_g_per_h:.2f} Q={g.moisture_loss_m3_per_h:.3f} F/Q={fq:.1f} rmse={g.rmse_pct:.3f}')
    print()
