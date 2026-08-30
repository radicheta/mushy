#!/usr/bin/env python3
"""MUSHY-125: size the temperature-ramp feedforward on recorded days.

Drives the twin (control law + sigma-delta driver + chamber model) with the
REAL recorded chamber temperature and REAL ambient over a recorded window,
sweeping ``humidifier_temp_feedforward`` (a trim on the model-derived gain
(rh*V*dAH_sat/dT - C)/F; 1.0 = trust the model) and reporting how far RH
strays from the setpoint. Unlike replay-chamber-day.py this does NOT compare
against recorded RH -- a different control law is supposed to diverge from
it -- the yardstick is the setpoint. Recorded RH's own deviation is printed
as the "what the real controller achieved" reference.

Reuses replay-chamber-day.py's loaders and its cache (.cache/mushy-60-chamber-day/<tag>).

  .venv/bin/python scripts/sweep-temp-feedforward.py            # all windows
"""
import importlib.util
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / 'src' / 'chambers' / 'fc-core'))
spec = importlib.util.spec_from_file_location('rcd', REPO_ROOT / 'scripts' / 'replay-chamber-day.py')
rcd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rcd)

from fc_core.control_kernel import BandSpec, temp_feedforward_gain   # noqa: E402
from fc_core.sim import control_loop                                 # noqa: E402
from fc_core.sim.chamber_model import ChamberParams                  # noqa: E402
from fc_core.sim.control_loop import DEFAULT_GAINS, Gains            # noqa: E402
from fc_core.sim.pwm_sigma_delta import SigmaDeltaConfig, SigmaDeltaSimulator  # noqa: E402
from fc_core.sim.replay import run_closed_loop                       # noqa: E402

RECENT = str(REPO_ROOT / 'src/chambers/fc-core/fc_core/sim/data/ambient_-34.52_-55.10.recent.csv')
FRUITING = BandSpec(0.885, 0.915, 'both')
# 2026-05-04: the pid_calibration_notes.md canonical feedforward day (14-20 C,
# target 0.96, epoch b7ca1da7 gains, no integrator decay yet). OUTSIDE the
# twin's validated regime (RH near the saturation exclusion) -- read it for
# the sign and size of the effect at spring temperatures, not for fidelity.
MAY = BandSpec(0.945, 0.975, 'both')
MAY_GAINS = Gains(kp=0.35, ki=0.002, kd=4.0, derivative_filter_tau=10.0,
                  integrator_decay_tau=0.0, bypass_threshold=0.025)
WINDOWS = [
    # tag (cache dir), start, end, ambient fixture, band, target, gains
    ('B-refitQ-FoverQ-C-day0808', '2026-08-08 00:00:00+00', '2026-08-09 00:00:00+00', None, FRUITING, 0.90, DEFAULT_GAINS),
    ('B-refitQ-FoverQ-C-day0814', '2026-08-14 00:00:00+00', '2026-08-15 00:00:00+00', RECENT, FRUITING, 0.90, DEFAULT_GAINS),
    ('MUSHY-125-day0504', '2026-05-04 00:00:00+00', '2026-05-05 00:00:00+00', None, MAY, 0.96, MAY_GAINS),
]
TRIMS = [0.0, 0.5, 1.0, 1.5, 2.0]
TAUS = [300.0, 600.0, 1200.0]
OUT_MD = rcd.PHASE_DIR / '999.33-11-MUSHY-125-FEEDFORWARD.md'


def deviation(rh, target_pct, band):
    rh = np.asarray(rh)
    return dict(rms=float(np.sqrt(np.mean((rh - target_pct) ** 2))),
                lo=float(rh.min()), hi=float(rh.max()),
                in_band=float(np.mean((rh >= band.band_low * 100) & (rh <= band.band_high * 100))))


def run(tag, start, end, fixture, band, target, gains, trim, tau):
    rcd.DAY_START, rcd.DAY_END = start, end
    grid = rcd.build_grid(rcd.export_csvs(rcd.CACHE_DIR / tag))
    ambient = rcd.build_ambient_ah(grid['full_idx'], allow_stale=True, fixture=fixture)
    temp = grid['temp_c']
    control_loop.TempRateEstimator.__init__.__defaults__ = (tau,)   # sweep hook, throwaway
    m = run_closed_loop(
        pwm=SigmaDeltaSimulator(SigmaDeltaConfig()), hours=len(temp) / 3600.0,
        params=ChamberParams(), band=band, gains=gains, target=target, rh0=float(grid['rh_pct'][0]),
        dt=1.0, ambient_ah_g_m3=lambda t: ambient[int(t)], temp_c=lambda t: temp[int(t)],
        temp_ff_gain=trim)
    return m, grid


def main():
    lines = ['# 999.33-11 -- Temperature-ramp feedforward sized on recorded days (MUSHY-125)', '',
             'Twin driven with REAL recorded chamber temperature and REAL ambient; control law + '
             'sigma-delta driver (what fc1 runs since 2026-08-29) + chamber model run free from the '
             "window's first recorded RH. Yardstick is the SETPOINT, not recorded RH. `recorded` row "
             '= what the real (window-PWM, no feedforward) controller achieved that day. '
             'trim scales the model gain (rh*V*dAH_sat/dT - C)/F, 1.0 = model; tau is the rate filter.', '']
    for tag, start, end, fixture, band, target, gains in WINDOWS:
        tp = target * 100
        lines += [f'## {start[:10]} ({tag})', '',
                  '| trim | tau s | RH rms from setpoint | min | max | in-band | mean duty | relay/h |',
                  '|---|---|---|---|---|---|---|---|']
        print(f'== {start[:10]}', file=sys.stderr)
        first = None
        for trim in TRIMS:
            m, grid = run(tag, start, end, fixture, band, target, gains, trim, 600.0)
            if first is None:
                first = grid
                d = deviation(grid['rh_pct'], tp, band)
                t = grid['temp_c']
                lines.append(f"| recorded | - | {d['rms']:.3f} | {d['lo']:.2f} | {d['hi']:.2f} | "
                             f"{d['in_band']:.0%} | {float(np.mean(grid['duty_recorded'])):.3f} | - |")
                p = ChamberParams()
                lines.append(f'| model gain, duty per C/h: {temp_feedforward_gain(target, float(t.min()), p.fill_g_per_h, p.surface_g_per_k):.3f} '
                             f'@{t.min():.1f}C .. {temp_feedforward_gain(target, float(t.max()), p.fill_g_per_h, p.surface_g_per_k):.3f} @{t.max():.1f}C '
                             f'| | | | | | | |')
            d = deviation(m.rh_series, tp, band)
            row = (f"| {trim} | 600 | {d['rms']:.3f} | {d['lo']:.2f} | {d['hi']:.2f} | "
                   f"{d['in_band']:.0%} | {m.duty_mean_commanded:.3f} | {m.relay_cycles_per_hour:.1f} |")
            print(row, file=sys.stderr)
            lines.append(row)
        for tau in TAUS:
            if tau == 600.0:
                continue
            m, _ = run(tag, start, end, fixture, band, target, gains, 1.0, tau)
            d = deviation(m.rh_series, tp, band)
            row = (f"| 1.0 | {tau:.0f} | {d['rms']:.3f} | {d['lo']:.2f} | {d['hi']:.2f} | "
                   f"{d['in_band']:.0%} | {m.duty_mean_commanded:.3f} | {m.relay_cycles_per_hour:.1f} |")
            print(row, file=sys.stderr)
            lines.append(row)
        lines.append('')
    OUT_MD.write_text('\n'.join(lines) + '\n')
    print(f'wrote {OUT_MD}', file=sys.stderr)


if __name__ == '__main__':
    main()
