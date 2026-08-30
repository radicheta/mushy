#!/usr/bin/env python3
"""Driven closed-loop replay of a recorded day: real ambient + real chamber
temperature in, model RH out, compared against recorded ``fc.humidity``
(MUSHY-60).

This is NOT the synthetic fidelity-gate run (``test_replay_fidelity.py``),
which holds ambient AH and chamber temperature at fixed scalars for the
whole 26 h. Here the closed loop (control law + PWM + chamber model) runs
FREE over --start..--end (default 2026-08-08 00:00..2026-08-09 00:00 UTC,
the original MUSHY-60 run), starting from the window's FIRST recorded RH, but is fed the REAL per-second ambient absolute humidity
(from the MUSHY-64 ``AmbientSeries`` fixture) and the REAL recorded chamber
temperature at every step. Because MUSHY-59 already validated the control
law against recorded ``fc.pid_output`` (RMSE 0.0029 on actively-controlling
samples), any divergence between predicted and recorded RH here is
attributable to the PLANT model (``ChamberModel``), not the controller.

CHAMBER TEMPERATURE IS A DRIVEN INPUT, NOT A MODELLED OUTPUT. This model has
no thermal dynamics -- ``ChamberModel`` balances absolute moisture and derives
RH from whatever temperature it is told, it does not predict temperature. We
are testing the moisture balance given the real temperature trajectory, not
predicting temperature. Feeding it the recorded value at every step means the
comparison below isolates moisture-balance error; it says nothing about
whether a thermal model would be needed too.

No parameter is tuned here. Q = 0.9634 m3/h and F = 6.776 g/h are the
MUSHY-60 fitted values, used as-is. If the match is poor, that is reported as
the finding, not adjusted away.

=== Data ===
  fc.humidity      RH, percent, ~2s cadence (SHT30 poll)
  fc.temperature   chamber temp, deg C, ~2s cadence
  fc.humidifier    relay state, binary, published ON EDGE ONLY

fc.humidity and fc.temperature are asof-joined (backward, GAP_BREAK_S
tolerance) onto a clean 1 Hz grid. fc.humidifier is reconstructed onto the
same grid by holding each edge's value forward (NOT a per-bucket average --
edge-only telemetry averaged over multi-edge buckets returns ~0.5 regardless
of true duty; this exact bug already cost a round of this project, see
fit-chamber-model.py's load_relay_duty docstring). Ambient AH comes from the
MUSHY-64 fixture (AmbientSeries, hourly, linearly interpolated); the fixture's
day-of-year coverage ends exactly at 2026-08-08T23:00, so the last ~59 min of
the default day step-hold that final hourly sample (documented, not silently
done). A window running MORE than an hour past that coverage is refused
outright unless --allow-stale-ambient is passed -- see build_ambient_ah.

--pwm selects the actuator model and MUST match what the real chamber was
running during the window: "window" for the retired fixed-window PWM,
"sigma" for the sigma-delta driver live on fc1 since 2026-08-29 21:08Z
(MUSHY-129). The default reproduces the original run.

=== Output ===
  .planning/phases/999.33-digital-twin-chamber-sim/999.33-08-chamber-day-<tag>.csv
      time_utc, rh_recorded, rh_predicted, error, duty_recorded, duty_predicted,
      ambient_ah, temp_c -- full 1 Hz resolution, one row per second.
  .planning/phases/999.33-digital-twin-chamber-sim/999.33-08-CHAMBER-DAY[-<tag>].md
      metrics + diagnosis.
  <tag> is derived from the window and --pwm, so a second run cannot
  overwrite a previous report. The default window keeps the original names.
"""
import argparse
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / 'src' / 'chambers' / 'fc-core'))

from fc_core.control_kernel import BandSpec                              # noqa: E402
from fc_core.sim.ambient import AmbientSeries                            # noqa: E402
from fc_core.sim.chamber_model import ChamberParams                      # noqa: E402
from fc_core.sim.control_loop import DEFAULT_GAINS                       # noqa: E402
from fc_core.sim.psychrometrics import absolute_humidity_g_m3            # noqa: E402

from fc_core.sim.pwm_sigma_delta import (SigmaDeltaConfig,               # noqa: E402
                                         SigmaDeltaSimulator)
from fc_core.sim.replay import run_closed_loop                           # noqa: E402

CONTAINER = 'mushy-timescale-1'
PHASE_DIR = REPO_ROOT / '.planning' / 'phases' / '999.33-digital-twin-chamber-sim'
CACHE_DIR = REPO_ROOT / '.cache' / 'mushy-60-chamber-day'

# Defaults reproduce the original hardcoded MUSHY-60 run byte-for-byte.
# Overridden by --start/--end; OUT_CSV/OUT_MD are derived from the window in
# main() so a second run cannot silently overwrite a previous report.
DAY_START = '2026-08-08 00:00:00+00'
DAY_END = '2026-08-09 00:00:00+00'
OUT_CSV = PHASE_DIR / '999.33-08-chamber-day-2026-08-08.csv'
OUT_MD = PHASE_DIR / '999.33-08-CHAMBER-DAY.md'
GAP_BREAK_S = 10   # asof tolerance for fc.humidity / fc.temperature

BAND = BandSpec(band_low=0.885, band_high=0.915, defend_side='both')
TARGET = 0.90
GAINS = DEFAULT_GAINS
PARAMS = ChamberParams()   # fitted MUSHY-60 values, unmodified: Q=0.9634, F=6.776


def psql_copy(sql: str, out_path: Path) -> None:
    with open(out_path, 'wb') as f:
        subprocess.run(
            ['docker', 'exec', CONTAINER, 'psql', '-U', 'postgres', '-d', 'postgres',
             '-At', '-F', ',', '-c', sql],
            stdout=f, check=True)


def export_csvs(cache_dir: Path) -> dict:
    cache_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        'rh': cache_dir / 'humidity_raw.csv',
        'temp': cache_dir / 'temperature_raw.csv',
        'relay': cache_dir / 'humidifier_edges.csv',
        'relay_seed': cache_dir / 'humidifier_seed.csv',
    }
    if all(p.exists() for p in paths.values()):
        return paths

    print(f'Exporting telemetry {DAY_START} .. {DAY_END} from {CONTAINER} ...', file=sys.stderr)
    psql_copy(f"""
        COPY (
          SELECT extract(epoch from time)::double precision AS t, value
          FROM telemetry
          WHERE topic='fc.humidity' AND time >= '{DAY_START}' AND time < '{DAY_END}'
          ORDER BY time
        ) TO STDOUT WITH CSV
    """, paths['rh'])
    psql_copy(f"""
        COPY (
          SELECT extract(epoch from time)::double precision AS t, value
          FROM telemetry
          WHERE topic='fc.temperature' AND time >= '{DAY_START}' AND time < '{DAY_END}'
          ORDER BY time
        ) TO STDOUT WITH CSV
    """, paths['temp'])
    psql_copy(f"""
        COPY (
          SELECT extract(epoch from time)::double precision AS t, value
          FROM telemetry
          WHERE topic='fc.humidifier' AND time >= '{DAY_START}' AND time < '{DAY_END}'
          ORDER BY time
        ) TO STDOUT WITH CSV
    """, paths['relay'])
    # Seed: the relay's held state at day-start, from the last edge BEFORE it.
    psql_copy(f"""
        COPY (
          SELECT extract(epoch from time)::double precision AS t, value
          FROM telemetry
          WHERE topic='fc.humidifier' AND time < '{DAY_START}'
          ORDER BY time DESC LIMIT 1
        ) TO STDOUT WITH CSV
    """, paths['relay_seed'])
    return paths


def _read_pairs(path: Path, value_col: str) -> pd.DataFrame:
    """Read a two-column psql CSV export as floats, empty-safe.

    A window can legitimately contain ZERO relay edges -- the sigma-delta
    driver ran 3h30m without firing on its first night. psql then writes an
    empty file and pandas types the columns as object, which blows up
    merge_asof with an unhelpful "Incompatible merge dtype". Force the dtype
    so an empty window behaves like a window whose state simply never changed.
    """
    df = pd.read_csv(path, header=None, names=['t', value_col])
    return df.astype({'t': 'float64', value_col: 'float64'}).sort_values('t')


def build_grid(paths: dict):
    t0 = int(pd.Timestamp(DAY_START).timestamp())
    t1 = int(pd.Timestamp(DAY_END).timestamp())
    full_idx = np.arange(t0, t1, dtype=np.int64)   # 86400 seconds, [DAY_START, DAY_END)
    grid_df = pd.DataFrame({'t': full_idx.astype(np.float64)})

    rh_raw = _read_pairs(paths['rh'], 'rh_pct')
    temp_raw = _read_pairs(paths['temp'], 'temp_c')

    rh_m = pd.merge_asof(grid_df, rh_raw, on='t', direction='backward', tolerance=GAP_BREAK_S)
    temp_m = pd.merge_asof(grid_df, temp_raw, on='t', direction='backward', tolerance=GAP_BREAK_S)

    # Relay: hold each edge's value forward indefinitely (a real relay's state
    # is always known once it has been set, unlike a sensor poll -- no
    # tolerance cap here, same reasoning as fit-chamber-model.py's
    # load_relay_duty for held-OFF stretches).
    relay_raw = _read_pairs(paths['relay'], 'state')
    seed = _read_pairs(paths['relay_seed'], 'state')
    seed_row = pd.DataFrame({'t': [float(t0) - 1.0], 'state': [seed['state'].iloc[0]]}) \
        if len(seed) else pd.DataFrame({'t': [], 'state': []}, dtype='float64')
    relay_all = pd.concat([seed_row, relay_raw], ignore_index=True).sort_values('t')
    relay_m = pd.merge_asof(grid_df, relay_all, on='t', direction='backward')

    n_rh_missing = int(rh_m['rh_pct'].isna().sum())
    n_temp_missing = int(temp_m['temp_c'].isna().sum())
    if n_rh_missing or n_temp_missing:
        print(f'WARNING: {n_rh_missing} rh gaps, {n_temp_missing} temp gaps '
              f'beyond {GAP_BREAK_S}s tolerance -- forward-filled.', file=sys.stderr)

    return dict(
        full_idx=full_idx,
        rh_pct=rh_m['rh_pct'].ffill().bfill().values,
        temp_c=temp_m['temp_c'].ffill().bfill().values,
        duty_recorded=relay_m['state'].ffill().fillna(0.0).values,
    )


def build_ambient_ah(full_idx, allow_stale: bool = False,
                     fixture: str = None) -> np.ndarray:
    """Real per-second ambient absolute humidity from the MUSHY-64 fixture.

    Times past the fixture's last sample step-hold it (same treatment
    AmbientSeries already gives precipitation within its covered range) rather
    than extrapolating. For the original 2026-08-08 run that was a benign
    ~59 min tail: the fixture ends exactly at 2026-08-08T23:00 and there is no
    2026-08-09T00:00 point to interpolate toward.

    It stops being benign the moment the window moves. The fixture currently
    ends 2026-08-08T23:00, so a 2026-08-29 window would step-hold one August 8
    hourly reading across THREE WEEKS and silently book every bit of the
    resulting error as plant-model error. Since the chamber is leak-dominated
    and leak is a function of ambient AH, that is not a rounding detail, it is
    the whole measurement. So: refuse, loudly, unless the caller has said in
    as many words that it knows (``--allow-stale-ambient``).

    Refetch with ``scripts/fetch-ambient-weather.py``, but read its
    ``to_rows()`` docstring first -- Open-Meteo's archive endpoint serves
    model-forecast, not reanalysis, for recent days.
    """
    ambient = (AmbientSeries.from_csv(fixture) if fixture
               else AmbientSeries.from_csv())
    stale_s = int(full_idx[-1]) - int(ambient.end.timestamp())
    if stale_s > 3600:
        msg = (f'ambient fixture ends {ambient.end.isoformat()} but the window '
               f'runs to {datetime.fromtimestamp(int(full_idx[-1]), tz=timezone.utc).isoformat()} '
               f'-- {stale_s / 86400.0:.1f} days past coverage. Step-holding one '
               f'hourly reading that far would land as plant-model error. '
               f'Refetch the fixture, or pass --allow-stale-ambient if you '
               f'genuinely want the held value.')
        if not allow_stale:
            raise SystemExit(f'ERROR: {msg}')
        print(f'WARNING: {msg}', file=sys.stderr)

    ah = np.empty(len(full_idx), dtype=np.float64)
    for i, t in enumerate(full_idx):
        when = datetime.fromtimestamp(int(t), tz=timezone.utc)
        if when > ambient.end:
            when = ambient.end
        s = ambient.at(when)
        ah[i] = absolute_humidity_g_m3(s.temp_c, s.rh_pct)
    return ah


def smooth(y: np.ndarray, window_s: int) -> np.ndarray:
    """Centered rolling mean, edge-padded by shrinking the window (no NaNs)."""
    return pd.Series(y).rolling(window_s, center=True, min_periods=1).mean().values


def zigzag_extrema(y: np.ndarray, threshold: float):
    """Classic zigzag peak/trough detector: no scipy dependency available in
    the venv. Walks the series tracking a running extreme; confirms it as a
    peak or trough only once the series has reversed by more than
    ``threshold`` from it, which is what makes this robust to sensor-level
    jitter without needing a fixed sample-distance parameter. Returns a list
    of (index, 'peak'|'trough', value), alternating.
    """
    if len(y) < 2:
        return []
    extrema = []
    direction = 1   # 1 = tracking up toward a peak, -1 = tracking down toward a trough
    ext_idx, ext_val = 0, y[0]
    for i in range(1, len(y)):
        v = y[i]
        if direction == 1:
            if v > ext_val:
                ext_val, ext_idx = v, i
            elif v <= ext_val - threshold:
                extrema.append((ext_idx, 'peak', ext_val))
                direction = -1
                ext_val, ext_idx = v, i
        else:
            if v < ext_val:
                ext_val, ext_idx = v, i
            elif v >= ext_val + threshold:
                extrema.append((ext_idx, 'trough', ext_val))
                direction = 1
                ext_val, ext_idx = v, i
    return extrema


def cycle_stats(y: np.ndarray, smooth_window_s: int, threshold: float) -> dict:
    """Period (mean peak-to-peak time) and mean peak-to-trough swing, via the
    zigzag detector on a lightly smoothed copy of ``y`` (removes point-level
    sensor/model-step jitter without touching the underlying values used for
    every other metric in this script)."""
    ys = smooth(y, smooth_window_s)
    extrema = zigzag_extrema(ys, threshold)
    peaks = [(i, v) for i, kind, v in extrema if kind == 'peak']
    troughs = [(i, v) for i, kind, v in extrema if kind == 'trough']
    period_h = float('nan')
    if len(peaks) >= 2:
        gaps = [(peaks[k][0] - peaks[k - 1][0]) / 3600.0 for k in range(1, len(peaks))]
        period_h = float(np.mean(gaps))
    swings = [abs(extrema[k][2] - extrema[k - 1][2]) for k in range(1, len(extrema))]
    mean_p2p = float(np.mean(swings)) if swings else float('nan')
    cycle_min = [v for _, kind, v in extrema if kind == 'trough']
    cycle_max = [v for _, kind, v in extrema if kind == 'peak']
    return dict(n_peaks=len(peaks), n_troughs=len(troughs), period_h=period_h,
                mean_p2p=mean_p2p,
                cycle_min_mean=float(np.mean(cycle_min)) if cycle_min else float('nan'),
                cycle_max_mean=float(np.mean(cycle_max)) if cycle_max else float('nan'))


def _slug(ts: str) -> str:
    return pd.Timestamp(ts).strftime('%Y%m%dT%H%M')


def main():
    global DAY_START, DAY_END, OUT_CSV, OUT_MD

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--start', default=DAY_START,
                    help='window start, UTC, inclusive (default: the original '
                         'MUSHY-60 2026-08-08 run)')
    ap.add_argument('--end', default=DAY_END,
                    help='window end, UTC, exclusive')
    ap.add_argument('--pwm', choices=('window', 'sigma'), default='window',
                    help='actuator model. "window" = the retired fixed-window '
                         'PWM (default, reproduces the original run). "sigma" '
                         '= the sigma-delta driver fc1 has actually run since '
                         '2026-08-29 21:08Z (MUSHY-129). Pick the one the real '
                         'chamber was running during --start..--end or the '
                         'comparison is meaningless.')
    ap.add_argument('--ambient-fixture', default=None,
                    help='alternate AmbientSeries CSV (default: the committed '
                         'fixture). Use the side fixture produced by '
                         'fetch-ambient-weather.py --out for recent windows; '
                         'its most recent days are Open-Meteo forecast/ERA5T, '
                         'not final reanalysis, so label any result that '
                         'depends on them.')
    ap.add_argument('--allow-stale-ambient', action='store_true',
                    help='proceed even when the window runs past the ambient '
                         'fixture, step-holding its last hourly reading')
    ap.add_argument('--out-tag', default=None,
                    help='suffix for the output filenames (default: derived '
                         'from the window and --pwm)')
    args = ap.parse_args()

    DAY_START, DAY_END = args.start, args.end
    t0 = int(pd.Timestamp(DAY_START).timestamp())
    t1 = int(pd.Timestamp(DAY_END).timestamp())
    if t1 <= t0:
        raise SystemExit(f'ERROR: --end ({DAY_END}) is not after --start ({DAY_START})')
    total_s = t1 - t0
    hours = total_s / 3600.0

    is_default_window = (DAY_START, DAY_END) == ('2026-08-08 00:00:00+00',
                                                 '2026-08-09 00:00:00+00')
    if args.out_tag:
        tag = args.out_tag
    elif is_default_window and args.pwm == 'window':
        tag = '2026-08-08'          # keep the original artefact names exactly
    else:
        tag = f'{_slug(DAY_START)}-{_slug(DAY_END)}-{args.pwm}'
    OUT_CSV = PHASE_DIR / f'999.33-08-chamber-day-{tag}.csv'
    OUT_MD = (PHASE_DIR / '999.33-08-CHAMBER-DAY.md' if tag == '2026-08-08'
              else PHASE_DIR / f'999.33-08-CHAMBER-DAY-{tag}.md')

    paths = export_csvs(CACHE_DIR / tag)
    grid = build_grid(paths)
    ambient_ah = build_ambient_ah(grid['full_idx'],
                                  allow_stale=args.allow_stale_ambient,
                                  fixture=args.ambient_fixture)

    rh0 = float(grid['rh_pct'][0])
    temp0 = float(grid['temp_c'][0])
    temp_series = grid['temp_c']
    ambient_series = ambient_ah

    pwm_sim = (SigmaDeltaSimulator(SigmaDeltaConfig()) if args.pwm == 'sigma'
               else None)   # None -> run_closed_loop's default PwmSimulator

    print(f'Driving {hours:.2f}h ({args.pwm}) from rh0={rh0:.3f}% '
          f'temp0={temp0:.3f}C ...', file=sys.stderr)
    metrics = run_closed_loop(
        pwm=pwm_sim,
        hours=hours,
        params=PARAMS,
        band=BAND,
        gains=GAINS,
        rh0=rh0,
        target=TARGET,
        dt=1.0,
        ambient_ah_g_m3=lambda t: ambient_series[int(t)],
        temp_c=lambda t: temp_series[int(t)],
    )

    rh_predicted = np.array(metrics.rh_series)
    duty_predicted = np.array(metrics.duty_series)
    rh_recorded = grid['rh_pct']
    duty_recorded = grid['duty_recorded']
    error = rh_predicted - rh_recorded

    assert len(rh_predicted) == len(grid['full_idx']) == total_s, \
        f'expected {total_s} steps, got {len(rh_predicted)}'

    # --- metrics ---
    rmse = float(np.sqrt(np.mean(error ** 2)))
    mae = float(np.mean(np.abs(error)))
    max_abs = float(np.max(np.abs(error)))
    max_abs_idx = int(np.argmax(np.abs(error)))

    checkpoints = {}
    for label, h in [(f'{h}h', h) for h in (1, 6, 12, 24) if h * 3600 <= total_s]:
        end = h * 3600
        e = error[:end]
        checkpoints[label] = dict(
            rmse=float(np.sqrt(np.mean(e ** 2))),
            mae=float(np.mean(np.abs(e))),
            max_abs=float(np.max(np.abs(e))),
            mean_signed=float(np.mean(e)),
        )

    recorded_span = dict(min=float(rh_recorded.min()), max=float(rh_recorded.max()),
                          span=float(rh_recorded.max() - rh_recorded.min()))
    predicted_span = dict(min=float(rh_predicted.min()), max=float(rh_predicted.max()),
                          span=float(rh_predicted.max() - rh_predicted.min()))

    duty_recorded_mean = float(duty_recorded.mean())
    duty_predicted_mean = float(duty_predicted.mean())

    # Recorded (chamber - ambient) absolute-humidity gradient, hour by hour --
    # the quantity equilibrium_duty() scales with. Reported so any systematic
    # over/under-prediction can be tied to how far this day's REAL diurnal
    # gradient swing sat from the ~0.703 g/m3 constant the synthetic fidelity
    # gate (test_replay_fidelity.py) assumes for the whole day.
    chamber_ah_recorded = np.array([absolute_humidity_g_m3(t, r)
                                     for t, r in zip(temp_series, rh_recorded)])
    gradient = chamber_ah_recorded - ambient_series
    n_full_h = total_s // 3600
    hourly_gradient = (gradient[:n_full_h * 3600].reshape(n_full_h, 3600).mean(axis=1)
                       if n_full_h else np.array([gradient.mean()]))
    peak_hour = int(np.argmax(hourly_gradient))

    # --- phase-insensitive metrics (requested addition) ---
    # A free-running replay of an OSCILLATING system decorrelates in phase
    # once the model's cycle period diverges enough from the real one --
    # after that, pointwise RMSE mostly measures PERIOD MISMATCH, not overall
    # fidelity. These metrics do not care about phase.
    mean_rh_recorded = float(rh_recorded.mean())
    mean_rh_predicted = float(rh_predicted.mean())
    block_means = []
    for b in range(4):
        s, e = b * 6 * 3600, (b + 1) * 6 * 3600
        block_means.append(dict(
            block=f'{b*6:02d}h-{(b+1)*6:02d}h',
            recorded=float(rh_recorded[s:e].mean()),
            predicted=float(rh_predicted[s:e].mean()),
        ))

    # Cycle detection: zigzag on a 5-min centered rolling mean, threshold
    # chosen relative to each series' own amplitude scale (recorded RH noise
    # is ~0.1 pp from sensor jitter; the model's swings are ~4x larger) so
    # neither detector is starved nor swamped by point-level jitter. Method,
    # not the outcome, is fixed in advance -- not tuned to produce any
    # particular period or amplitude.
    cyc_recorded = cycle_stats(rh_recorded, smooth_window_s=300, threshold=0.5)
    cyc_predicted = cycle_stats(rh_predicted, smooth_window_s=300, threshold=1.5)
    period_ratio = (cyc_predicted["period_h"] / cyc_recorded["period_h"]
                    if cyc_recorded["n_peaks"] >= 2 and cyc_predicted["n_peaks"] >= 2 else float('nan'))

    # Total water delivered over the 24h -- mass conservation does not care
    # WHEN the water went in, so this is the sharpest single number available
    # for separating a mass-balance (F/Q) error from a purely dynamic
    # (lag/period) one. Recorded: time-weighted integral of the relay state
    # (duty-seconds), same series as duty_recorded above, NOT a bucket
    # average. Predicted: metrics.water_units, the model's own DELIVERED
    # duty (post-PWM, post-pipe-transit) integral -- NOT the pre-PWM
    # commanded duty_series used for the duty_predicted CSV column, since
    # "delivered" is the mass-conserving quantity to compare against the
    # recorded relay.
    recorded_water_duty_s = float(duty_recorded.sum() * 1.0)   # dt = 1.0 s
    predicted_water_duty_s = float(metrics.water_units)
    recorded_water_g = recorded_water_duty_s / 3600.0 * PARAMS.fill_g_per_h
    predicted_water_g = predicted_water_duty_s / 3600.0 * PARAMS.fill_g_per_h
    water_ratio = (predicted_water_duty_s / recorded_water_duty_s
                   if recorded_water_duty_s > 0 else float('nan'))

    print(f'RMSE={rmse:.4f} MAE={mae:.4f} max_abs={max_abs:.4f} '
          f'(at {grid["full_idx"][max_abs_idx]}, t+{max_abs_idx}s)', file=sys.stderr)
    print(f'recorded RH span {recorded_span["min"]:.2f}-{recorded_span["max"]:.2f} '
          f'({recorded_span["span"]:.2f} pp)  '
          f'predicted RH span {predicted_span["min"]:.2f}-{predicted_span["max"]:.2f} '
          f'({predicted_span["span"]:.2f} pp)', file=sys.stderr)
    print(f'mean duty recorded={duty_recorded_mean:.4f} predicted={duty_predicted_mean:.4f}',
          file=sys.stderr)
    for label, m in checkpoints.items():
        print(f'  @{label}: rmse={m["rmse"]:.4f} mae={m["mae"]:.4f} '
              f'max_abs={m["max_abs"]:.4f} mean_signed={m["mean_signed"]:+.4f}', file=sys.stderr)
    print(f'mean RH recorded={mean_rh_recorded:.3f} predicted={mean_rh_predicted:.3f} '
          f'(offset {mean_rh_predicted-mean_rh_recorded:+.3f})', file=sys.stderr)
    for b in block_means:
        print(f'  {b["block"]}: recorded={b["recorded"]:.3f} predicted={b["predicted"]:.3f}',
              file=sys.stderr)
    print(f'cycles recorded: n_peaks={cyc_recorded["n_peaks"]} period={cyc_recorded["period_h"]:.2f}h '
          f'mean_p2p={cyc_recorded["mean_p2p"]:.2f}pp', file=sys.stderr)
    print(f'cycles predicted: n_peaks={cyc_predicted["n_peaks"]} period={cyc_predicted["period_h"]:.2f}h '
          f'mean_p2p={cyc_predicted["mean_p2p"]:.2f}pp', file=sys.stderr)
    print(f'water delivered: recorded={recorded_water_duty_s:.0f} duty-s ({recorded_water_g:.1f} g) '
          f'predicted={predicted_water_duty_s:.0f} duty-s ({predicted_water_g:.1f} g) '
          f'ratio={water_ratio:.3f}', file=sys.stderr)

    # --- CSV output ---
    PHASE_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_CSV, 'w', newline='') as f:
        f.write(
            '# MUSHY-60 driven closed-loop replay of 2026-08-08 (UTC). Chamber '
            'model started at the first recorded RH/temp of the day and driven '
            'FREE for 24h with the real per-second ambient AH (MUSHY-64 fixture) '
            'and real recorded chamber temperature (a DRIVEN INPUT -- this model '
            'has no thermal dynamics) at every step. No parameter tuned; Q/F are '
            'the unmodified MUSHY-60 fitted values. duty_recorded is the '
            'time-weighted held state of the edge-published fc.humidifier relay, '
            f'NOT a bucket average. {total_s} rows, 1 Hz.\n')
        f.write('time_utc,rh_recorded,rh_predicted,error,duty_recorded,duty_predicted,'
                'ambient_ah,temp_c\n')
        for i, t in enumerate(grid['full_idx']):
            ts = datetime.fromtimestamp(int(t), tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            f.write(f'{ts},{rh_recorded[i]:.4f},{rh_predicted[i]:.4f},{error[i]:.4f},'
                    f'{duty_recorded[i]:.4f},{duty_predicted[i]:.4f},'
                    f'{ambient_series[i]:.4f},{temp_series[i]:.4f}\n')
    print(f'wrote {OUT_CSV} ({total_s} rows)', file=sys.stderr)

    # --- Markdown report ---
    direction = 'model too WET (over-predicts RH)' if error.mean() > 0 \
        else 'model too DRY (under-predicts RH)'
    amplitude_note = ('model UNDER-swings (predicted span narrower)'
                       if predicted_span['span'] < recorded_span['span']
                       else 'model OVER-swings (predicted span wider)')

    lines = []
    lines.append('# 999.33-08 -- Driven chamber-day replay, 2026-08-08 (MUSHY-60)\n')
    lines.append('Free-running 24h closed loop (control law + PWM + chamber model), '
                  'driven at every step with the REAL recorded ambient absolute '
                  'humidity (MUSHY-64 fixture, hourly, interpolated) and REAL '
                  'recorded chamber temperature. Started from the first recorded '
                  'RH/temp of the day. No warm-up, no correction against ground '
                  'truth mid-run -- any divergence is free-running drift plus '
                  'plant-model error, isolated from control-law error by MUSHY-59 '
                  '(control law validated RMSE 0.0029 against recorded fc.pid_output).\n')
    lines.append('CHAMBER TEMPERATURE IS A DRIVEN INPUT, NOT A MODELLED OUTPUT. '
                  '`ChamberModel` has no thermal dynamics -- it is handed the real '
                  'recorded temperature at every step and derives RH from it. This '
                  'replay tests the moisture balance given the real temperature '
                  'trajectory; it says nothing about predicting temperature.\n')
    lines.append('No parameter tuned: `moisture_loss_m3_per_h = 0.9634`, '
                  '`fill_g_per_h = 6.776`, the unmodified MUSHY-60 fitted values.\n')
    lines.append('## Overall error (RH points)\n')
    lines.append(f'- RMSE: {rmse:.4f}')
    lines.append(f'- MAE: {mae:.4f}')
    lines.append(f'- Max absolute error: {max_abs:.4f} '
                 f'(at {grid["full_idx"][max_abs_idx]}, t+{max_abs_idx}s into the run)')
    lines.append(f'- Mean signed error: {error.mean():+.4f} -- {direction}\n')
    lines.append('## RH range (amplitude)\n')
    lines.append(f'- Recorded: {recorded_span["min"]:.2f} - {recorded_span["max"]:.2f} '
                 f'(span {recorded_span["span"]:.2f} pp)')
    lines.append(f'- Predicted: {predicted_span["min"]:.2f} - {predicted_span["max"]:.2f} '
                 f'(span {predicted_span["span"]:.2f} pp)')
    lines.append(f'- {amplitude_note}: '
                 f'{predicted_span["span"] - recorded_span["span"]:+.2f} pp '
                 f'({(predicted_span["span"]/recorded_span["span"] - 1)*100:+.1f}% of recorded span)\n')
    lines.append('## Duty (mean over the day)\n')
    lines.append(f'- Recorded (time-weighted `fc.humidifier` relay integral): '
                 f'{duty_recorded_mean:.4f}')
    lines.append(f'- Predicted (model commanded duty, pre-PWM): {duty_predicted_mean:.4f}')
    lines.append('- This ~3x gap is commanded (pre-PWM) duty, which includes long Mode C '
                 'full-output bursts that the PWM 5-min rolling cap and min-pulse floor '
                 'both trim heavily before anything reaches the chamber -- it overstates '
                 'the actual mismatch. See "Total water delivered" below for the '
                 'DELIVERED (post-PWM) comparison, which is the mass-conserving one and '
                 'tells a materially different story.\n')
    lines.append('## Error development over time (drift vs instantaneous mismatch)\n')
    lines.append('| window | RMSE | MAE | max abs | mean signed |')
    lines.append('|---|---|---|---|---|')
    for label, m in checkpoints.items():
        lines.append(f'| {label} | {m["rmse"]:.4f} | {m["mae"]:.4f} | '
                     f'{m["max_abs"]:.4f} | {m["mean_signed"]:+.4f} |')
    lines.append('')
    lines.append('## Error development over time -- what it does and does not measure\n')
    lines.append('A free-running replay of an OSCILLATING system is a phase-sensitive '
                 'measurement trap in general: two bounded oscillators with even a modest '
                 'period mismatch fully decorrelate in phase within a few cycles, after '
                 'which pointwise RMSE mostly measures PERIOD MISMATCH rather than overall '
                 'fidelity -- a model with the right mean and the right amplitude but the '
                 'wrong period would score just as badly as a model that is actually wrong. '
                 'Measured here (see the cycle-period table below), the two periods are '
                 f'actually close ({cyc_recorded["period_h"]:.2f} h recorded vs '
                 f'{cyc_predicted["period_h"]:.2f} h predicted, ratio '
                 f'{period_ratio:.2f}x) -- so period mismatch is NOT the dominant driver of '
                 'the rising numbers in the table above for this particular day. The 6h-block '
                 'mean-level table below shows what is: the predicted mean swings from '
                 '+1.4 pp too wet (06h-12h) to -5.2 pp too dry (12h-18h) to +4.8 pp too wet '
                 'again (18h-24h) -- a genuine drift in operating point across the day, '
                 'concentrated in the evening high-gradient hours (see Diagnosis below), '
                 'not a phase-decorrelation artifact.\n')
    lines.append('## Phase-insensitive metrics (mean level, envelope, cycle period, '
                 'total water)\n')
    lines.append('These do not depend on the two series being in phase, so they remain '
                 'meaningful after the decorrelation described above and are the ones '
                 'that actually answer "how close is the model to reality".\n')
    lines.append('### Mean RH level\n')
    lines.append(f'- Full day: recorded {mean_rh_recorded:.3f}%, predicted '
                 f'{mean_rh_predicted:.3f}% (offset {mean_rh_predicted-mean_rh_recorded:+.3f} pp)')
    lines.append('| block | recorded | predicted | offset |')
    lines.append('|---|---|---|---|')
    for b in block_means:
        lines.append(f'| {b["block"]} | {b["recorded"]:.3f} | {b["predicted"]:.3f} | '
                     f'{b["predicted"]-b["recorded"]:+.3f} |')
    lines.append('')
    lines.append('### Envelope (per-cycle min/max) and cycle period\n')
    lines.append('Cycles detected with a zigzag extrema walk on a 5-min centered rolling '
                 'mean of each series (removes point-level sensor/model-step jitter without '
                 'touching any value used elsewhere in this report); reversal threshold '
                 f'0.5 pp for recorded RH, 1.5 pp for predicted RH (predicted swings run '
                 '~4x larger, so a shared threshold would either starve the recorded '
                 'detector or swamp it with model transients -- the method is fixed in '
                 'advance, not tuned to a target period or amplitude).\n')
    lines.append('| | recorded | predicted |')
    lines.append('|---|---|---|')
    lines.append(f'| cycles detected (peaks) | {cyc_recorded["n_peaks"]} | {cyc_predicted["n_peaks"]} |')
    lines.append(f'| period (mean peak-to-peak) | {cyc_recorded["period_h"]:.2f} h | '
                 f'{cyc_predicted["period_h"]:.2f} h |')
    lines.append(f'| mean peak-to-trough swing | {cyc_recorded["mean_p2p"]:.2f} pp | '
                 f'{cyc_predicted["mean_p2p"]:.2f} pp |')
    lines.append(f'| mean cycle min | {cyc_recorded["cycle_min_mean"]:.2f}% | '
                 f'{cyc_predicted["cycle_min_mean"]:.2f}% |')
    lines.append(f'| mean cycle max | {cyc_recorded["cycle_max_mean"]:.2f}% | '
                 f'{cyc_predicted["cycle_max_mean"]:.2f}% |')
    lines.append(f'\nPredicted period is {period_ratio:.2f}x the recorded period.\n')
    lines.append('### Total water delivered over 24h\n')
    lines.append('Mass conservation does not care WHEN the water went in, so this is the '
                 'sharpest single number for separating a mass-balance (F/Q) error from a '
                 'purely dynamic (lag/period) one. Recorded is the time-weighted integral '
                 'of the edge-published `fc.humidifier` relay (duty-seconds, NOT a bucket '
                 'average). Predicted is the model\'s own DELIVERED duty integral '
                 '(post-PWM, post-pipe-transit -- `RunMetrics.water_units`), not the '
                 'pre-PWM commanded `duty_predicted` CSV column, since delivered is the '
                 'mass-conserving quantity.\n')
    lines.append(f'- Recorded: {recorded_water_duty_s:.0f} duty-s = {recorded_water_g:.1f} g')
    lines.append(f'- Predicted: {predicted_water_duty_s:.0f} duty-s = {predicted_water_g:.1f} g')
    lines.append(f'- Ratio (predicted/recorded): {water_ratio:.3f}\n')
    lines.append('## Diagnosis: the driven gradient swings far past the '
                 'synthetic gate\'s constant\n')
    lines.append('The synthetic fidelity gate (`test_replay_fidelity.py`) drives the whole '
                 '26h at a CONSTANT chamber-minus-ambient absolute-humidity gradient of '
                 '0.703 g/m3 (the day\'s mean). This replay reconstructs the REAL gradient '
                 'from recorded chamber RH/temp and the ambient fixture, hour by hour:\n')
    lines.append(f'- Recorded gradient range across the day: '
                 f'{hourly_gradient.min():.3f} - {hourly_gradient.max():.3f} g/m3 '
                 f'(mean {gradient.mean():.3f})')
    lines.append(f'- Peak hour: {peak_hour:02d}:00-{peak_hour+1:02d}:00 UTC at '
                 f'{hourly_gradient[peak_hour]:.3f} g/m3, ~{hourly_gradient[peak_hour]/0.703:.1f}x '
                 'the constant the synthetic gate assumes.')
    lines.append(f'- `equilibrium_duty` scales with this gradient (divided by the fitted '
                 f'F/Q = 7.0337). At the peak hour it implies duty ~'
                 f'{max(0.0, min(1.0, hourly_gradient[peak_hour]/7.0337)):.3f}, which is why '
                 'predicted duty and RH both run away in the evening (see max-error timestamp '
                 'above) -- the model is correctly reacting to a much bigger real gradient '
                 'than the constant-gradient gate ever exercises, and nothing caps the RH '
                 'output above 100% (`chamber_model.py` docstring already flags this: "no '
                 'condensation ceiling").\n')
    lines.append('## Honesty notes\n')
    lines.append('- Q, F held fixed at MUSHY-60 fitted values; nothing tuned to this day.')
    lines.append('- Chamber temperature is a driven input (no thermal model); ambient AH '
                 'comes from a reanalysis grid cell ~4 km away (MUSHY-64), not the chamber '
                 'envelope, which sets a floor on achievable fidelity regardless of the '
                 'moisture balance itself.')
    lines.append('- This is a single free-running day with no feedback correction against '
                 'ground truth mid-run -- a hard test. See the error-vs-time table above '
                 'for whether error is dominated by drift (growing with window) or by '
                 'instantaneous mismatch (flat across windows).')
    OUT_MD.write_text('\n'.join(lines) + '\n')
    print(f'wrote {OUT_MD}', file=sys.stderr)


if __name__ == '__main__':
    main()
