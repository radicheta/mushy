"""MUSHY-147: is the fitted F an artefact of the surface term C being carried,
not fitted, while every night probe window is cooling?"""
import importlib.util, sys
sys.path.insert(0,'src/chambers/fc-core')
from dataclasses import replace
from fc_core.sim.chamber_model import ChamberParams
from fc_core.sim.probe_fit import fit_window
spec=importlib.util.spec_from_file_location('fp','scripts/self-tune/fit-probes.py')
fp=importlib.util.module_from_spec(spec); spec.loader.exec_module(fp)

import datetime as dt
now=dt.datetime.now(dt.timezone.utc); t0=now-dt.timedelta(days=1); t1=now
w0,w1=(t0-dt.timedelta(hours=1)).timestamp(), t1.timestamp()
amb=fp.weather_series(*(fp.load(f'weather.{k}',w0,w1,table='weather')
                        for k in ('temperature','humidity','precipitation')), hold_until=w1)
e0,e1=max(t0.timestamp(),amb.start.timestamp()), min(t1.timestamp(),amb.end.timestamp())
rh=fp.resample(fp.load('fc.humidity',e0,e1),e0,e1,fp.DT)
temp=fp.resample(fp.load('fc.temperature',e0,e1),e0,e1,fp.DT)
relay=fp.resample(fp.load('fc.humidifier',e0-86400,e1),e0,e1,fp.DT,initial=0.0)
probe=fp.resample(fp.load('fc.probe',e0,e1),e0,e1,fp.DT,initial=0.0)
rh=[x*100.0 if x<=1.0 else x for x in rh]
ambient=[]; t=e0
while t<e1:
    s=amb.at(dt.datetime.fromtimestamp(t,tz=dt.timezone.utc))
    ambient.append(fp.absolute_humidity_g_m3(s.temp_c,s.rh_pct)); t+=fp.DT
from fc_core.sim.probe_fit import find_windows
wins=find_windows(fp.DT,rh,temp,ambient,relay,probe)
print(f'{len(wins)} probe windows; temp span per window: '
      + ', '.join(f'{max(w.temp)-min(w.temp):.2f} C' for w in wins))
print(f'\n{"C (g/K)":>8s} ' + ' '.join(f'{"F"+str(i):>7s} {"Q"+str(i):>6s} {"F/Q"+str(i):>6s} {"rmse":>6s}'
                                        for i in range(len(wins))))
for C in (0.0, 1.0, 2.0, 2.77, 4.0, 6.0):
    base=replace(ChamberParams(), surface_g_per_k=C)
    row=f'{C:8.2f} '
    for w in wins:
        f=fit_window(w, base)
        row += f'{f.fill_g_per_h:7.2f} {f.moisture_loss_m3_per_h:6.3f} ' \
               f'{f.fill_g_per_h/f.moisture_loss_m3_per_h:6.1f} {f.rmse_pct:6.3f} '
    print(row)
print('\nafternoon steady state implies F/Q = 14.1; 60 d quasi hinted 7.9; yaml is 7.03')
