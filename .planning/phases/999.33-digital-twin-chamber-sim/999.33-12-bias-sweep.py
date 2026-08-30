"""Twin sweep of humidifier_duty_bias on recorded days (MUSHY-65 sizing)."""
import importlib.util, sys, numpy as np
sys.path.insert(0, 'src/chambers/fc-core')
spec = importlib.util.spec_from_file_location('rcd', 'scripts/replay-chamber-day.py')
rcd = importlib.util.module_from_spec(spec); spec.loader.exec_module(rcd)
from fc_core.control_kernel import BandSpec
from fc_core.sim.chamber_model import ChamberParams
from fc_core.sim.pwm_sigma_delta import SigmaDeltaSimulator, SigmaDeltaConfig
from fc_core.sim.replay import run_closed_loop
REC = 'src/chambers/fc-core/fc_core/sim/data/ambient_-34.52_-55.10.recent.csv'
band = BandSpec(0.885, 0.915, 'both')

def load(tag, s, e, fix):
    rcd.DAY_START, rcd.DAY_END = s, e
    g = rcd.build_grid(rcd.export_csvs(rcd.CACHE_DIR / tag))
    return g, rcd.build_ambient_ah(g['full_idx'], allow_stale=True, fixture=fix)

wins = {'08-08': load('B-refitQ-FoverQ-C-day0808', '2026-08-08 00:00:00+00', '2026-08-09 00:00:00+00', None),
        '08-14': load('B-refitQ-FoverQ-C-day0814', '2026-08-14 00:00:00+00', '2026-08-15 00:00:00+00', REC)}
g, a = load('MUSHY-bias-week-0823-0830', '2026-08-23 00:00:00+00', '2026-08-30 00:00:00+00', REC)
for d, name in ((1, '08-24'), (2, '08-25'), (6, '08-29')):
    s = slice(d * 86400, (d + 1) * 86400)
    wins[name] = ({k: v[s] for k, v in g.items() if k in ('rh_pct', 'temp_c', 'duty_recorded')}, a[s])

print('day    bias   rms   min    max   inband  duty  relay/h   (recorded: rms min max inband duty)')
for name, (g, a) in wins.items():
    rh = np.asarray(g['rh_pct']); t = np.asarray(g['temp_c']); dr = np.asarray(g['duty_recorded'])
    rec = '%.2f %.2f %.2f %2.0f%% %.3f' % (np.sqrt(np.mean((rh - 90) ** 2)), rh.min(), rh.max(),
                                          100 * np.mean((rh >= 88.5) & (rh <= 91.5)), dr.mean())
    for b in (0.0, 0.08, 0.12, 0.15, 0.20):
        m = run_closed_loop(pwm=SigmaDeltaSimulator(SigmaDeltaConfig()), hours=len(t) / 3600,
                            params=ChamberParams(), band=band, rh0=float(rh[0]), dt=1.0,
                            ambient_ah_g_m3=lambda x: a[int(x)], temp_c=lambda x: t[int(x)], duty_bias=b)
        r = np.asarray(m.rh_series)
        print('%s  %.2f  %.3f %.2f %.2f  %2.0f%%  %.3f  %.1f   %s' % (
            name, b, np.sqrt(np.mean((r - 90) ** 2)), r.min(), r.max(),
            100 * np.mean((r >= 88.5) & (r <= 91.5)), m.duty_mean_commanded, m.relay_cycles_per_hour,
            rec if b == 0 else ''))
