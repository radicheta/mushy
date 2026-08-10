#!/usr/bin/env python3
"""Validate the reconstructed control law against RECORDED fc.pid_output (MUSHY-59).

This deliberately does NOT run the chamber model. ``fc.pid_output`` is
recorded telemetry -- the raw, PRE-bias control-law output the real
controller published (see ``fc_controller.py`` ~line 1821:
``max(0, min(1, raw_pid_output))``). Feeding recorded RH into
``fc_core.sim.control_loop.ControlLoop`` (the SAME class ``run_closed_loop``
now uses -- see MUSHY-59's refactor of ``replay.py``) and comparing its
output against the recorded value isolates control-law reconstruction error
from plant-model error entirely: no chamber physics is involved on either
side of this comparison.

=== Data ===
Three Timescale topics, window [--start, --end):
  fc.humidity          RH, percent, native cadence ~2 s (SHT30 poll)
  fc.pid_output         0..1, native cadence <1 s (many duplicate/sub-second
                        timestamps -- ~48% of consecutive samples land in the
                        same wall-clock second)
  fc.humidity_target    the EFFECTIVE SETPOINT telemetry (NOT the control
                        band -- see below), same cadence as pid_output

fc.pid_output and fc.humidity_target are deduped onto a 1 Hz grid by taking
the LAST value recorded in each wall-clock second (``date_trunc('second', ...)``
+ ``array_agg(... ORDER BY time DESC))[1]``). fc.humidity is asof-joined onto
the same grid with a tolerance (``GAP_BREAK_S``, see below) -- SQL for all
three lives in ``_export_csvs()`` below and is executed via
``docker exec mushy-timescale-1 psql``.

=== Restarts, the 0.9585 anomaly, and why the control law does not need them ===
``fc.humidity_target`` is NOT the control band. Reading fc_controller.py:
  - the control law's band comes from static per-mode config
    (``BandSpec(mode.band_low, mode.band_high, mode.defend_side)``,
    ~line 1715), which does not move during the window (verified: p10/p90 of
    fc.humidity_target are exactly 0.885/0.915 every week);
  - ``fc.humidity_target`` instead publishes ``self._effective_setpoint``, a
    telemetry-only field that starts at the NOMINAL ``target_humidity``
    parameter (0.96) on controller boot and ramps toward the nearest band
    edge at a rate of (remaining delta)/30 per tick (``_ramp_setpoint_to_band``,
    ~line 1463). First tick after a restart: 0.96 - (0.96-0.915)/30 = 0.9585,
    exactly the anomaly value the reconnaissance flagged.
  - So the PID's own arithmetic is UNAFFECTED by the ramp -- it always reads
    the static band. What genuinely changes at a restart is the PID's
    internal state: ``fc_controller.__init__`` builds a fresh ``PID(...,
    auto_mode=False)`` (engaged after a short startup grace) with zero
    integral and ``self._d_filtered = 0.0`` (~line 376-398).

We still exclude every ``fc.humidity_target``-not-near-a-band-edge stretch
from the comparison (never hardcoding 0.9585 -- the exclusion is
"abs(target - 0.885) or abs(target - 0.915) > TOL_TARGET"), per the
ticket brief, because it is at minimum a marker of a state transition worth
being conservative around, and because in practice the ramp coincides with
restarts almost exactly (see the report's restart-vs-exclusion table).
Restarts themselves are detected independently and explicitly, the same way:
``fc.humidity_target > RESTART_THRESHOLD`` (0.92, safely above 0.915 + noise),
grouped into events by a >RESTART_GROUP_GAP_S (300 s) gap between flagged
seconds -- NOT by hardcoding the reconnaissance's list of 27 timestamps, so
this generalises to any window.

A segment whose FIRST second IS a restart-flagged second is "restart-
anchored": the real controller's PID was, at that instant, demonstrably in
the exact fresh state ``ControlLoop.__init__`` also produces (zero
integral, zero d_filtered). For these segments the replay uses ZERO
warm-up -- both sides start from the same known state, so discarding any
of it would throw away signal for no reason. Every other segment boundary
is a telemetry gap with unknown mid-stream state, so it gets the full
``WARMUP_S`` (6 h, ~12x the 1800 s integrator-decay time constant)
discarded. See ``--warmup-sweep`` for the sensitivity check this claim
rests on.

An earlier version of this script anchored restart segments at the END of
the excluded ramp stretch (where fc.humidity_target reconverges near a
band edge) rather than at the restart itself, and re-initialised a fresh
PID there. That is wrong: the control law runs on the STATIC band the
whole time (see above), so the real PID had already been accumulating
integral for the ~100-150 s the ramp takes to reconverge before the
replay's "fresh" state began -- a manufactured discontinuity, not a real
one. It showed up exactly where you'd expect: the worst errors in the
whole dataset (up to 0.057 absolute) landed in the tens of seconds right
after a restart's excluded stretch ended, in ``below_midpoint_feather``
where integral windup matters. Anchoring at the true restart instant and
replaying CONTINUOUSLY through the ramp (still excluding those seconds
from the metrics, per the brief) removes that manufactured gap.

=== Segmentation ===
Driving continuity (does the loop keep stepping with one ``ControlLoop``
instance, dt=1.0) breaks only at:
  - a real RH telemetry hole (fc.humidity absent beyond the GAP_BREAK_S
    asof tolerance) or a real fc.humidity_target hole (ffill beyond
    GAP_BREAK_S) -- unknown mid-gap state, full warm-up on the far side;
  - a restart-flagged second -- known fresh state, zero warm-up on the far
    side, and a NEW ``ControlLoop`` is created there even if the telemetry
    itself has no gap (the PID's own state still resets).
Within a continuous drive segment, brief (<= GAP_BREAK_S) recording-only
gaps in fc.pid_output do not break anything -- the real controller kept
running through a mere ingestion hiccup -- those seconds are simply
excluded from the METRICS (no ground truth to compare against) while the
loop keeps stepping through them on forward-filled RH. Metrics are ALSO
excluded, independent of drive continuity, for every second where
fc.humidity_target is not within TOL_TARGET of a band edge (the ramp
stretch itself) -- per the brief, even though the law is unaffected.

=== Output ===
  .planning/phases/999.33-digital-twin-chamber-sim/999.33-07-control-replay.csv
      time_utc,rh_pct,pid_recorded,pid_predicted,error,regime -- downsampled,
      min/max-preserving, DOWNSAMPLE_BUCKET_S buckets (each bucket emits its
      min-error and max-error rows, so extremes survive decimation).
  .planning/phases/999.33-digital-twin-chamber-sim/999.33-07-control-replay-48h.csv
      same columns, full 1 Hz resolution, one representative 48 h window.
  .planning/phases/999.33-digital-twin-chamber-sim/999.33-07-CONTROL-REPLAY.md
      metric tables + diagnosis.
"""
import argparse
import csv
import pickle
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / 'src' / 'chambers' / 'fc-core'))

from fc_core.control_kernel import BandSpec, project_error_pct     # noqa: E402
from fc_core.sim.control_loop import ControlLoop, DEFAULT_GAINS    # noqa: E402

CONTAINER = 'mushy-timescale-1'
PHASE_DIR = REPO_ROOT / '.planning' / 'phases' / '999.33-digital-twin-chamber-sim'
OUT_CSV = PHASE_DIR / '999.33-07-control-replay.csv'
OUT_CSV_48H = PHASE_DIR / '999.33-07-control-replay-48h.csv'
OUT_MD = PHASE_DIR / '999.33-07-CONTROL-REPLAY.md'

# Live fc1 values (reconnaissance, read 2026-08-09).
BAND = BandSpec(band_low=0.885, band_high=0.915, defend_side='both')
TARGET = 0.90
GAINS = DEFAULT_GAINS

TOL_TARGET = 0.0015          # near-band-edge tolerance on fc.humidity_target
GAP_BREAK_S = 10             # real-hole threshold: RH asof tol, target ffill limit
RESTART_THRESHOLD = 0.92     # fc.humidity_target above this -> mid-ramp
RESTART_GROUP_GAP_S = 300    # group restart-flagged seconds into events
WARMUP_S = 6 * 3600          # base warm-up for non-restart-anchored segments
WARMUP_SWEEP_S = [1 * 3600, 3 * 3600, 6 * 3600, 12 * 3600]
DOWNSAMPLE_BUCKET_S = 60     # 1-minute buckets, min+max error preserved
REPRESENTATIVE_48H_START = '2026-07-20 00:00:00+00'  # mid-window, restart-free stretch


def psql_copy(sql: str, out_path: Path) -> None:
    with open(out_path, 'wb') as f:
        subprocess.run(
            ['docker', 'exec', CONTAINER, 'psql', '-U', 'postgres', '-d', 'postgres',
             '-At', '-F', ',', '-c', sql],
            stdout=f, check=True)


def export_csvs(start: str, end: str, cache_dir: Path) -> dict:
    cache_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        'pid': cache_dir / 'pid_output_1hz.csv',
        'target': cache_dir / 'humidity_target_1hz.csv',
        'rh': cache_dir / 'humidity_raw.csv',
    }
    if all(p.exists() for p in paths.values()):
        return paths

    print(f'Exporting telemetry {start} .. {end} from {CONTAINER} ...', file=sys.stderr)
    psql_copy(f"""
        COPY (
          SELECT extract(epoch from t)::bigint AS t, value
          FROM (
            SELECT date_trunc('second', time) AS t,
                   (array_agg(value ORDER BY time DESC))[1] AS value
            FROM telemetry
            WHERE topic='fc.pid_output' AND time >= '{start}' AND time < '{end}'
            GROUP BY 1
          ) s ORDER BY t
        ) TO STDOUT WITH CSV
    """, paths['pid'])
    psql_copy(f"""
        COPY (
          SELECT extract(epoch from t)::bigint AS t, value
          FROM (
            SELECT date_trunc('second', time) AS t,
                   (array_agg(value ORDER BY time DESC))[1] AS value
            FROM telemetry
            WHERE topic='fc.humidity_target' AND time >= '{start}' AND time < '{end}'
            GROUP BY 1
          ) s ORDER BY t
        ) TO STDOUT WITH CSV
    """, paths['target'])
    psql_copy(f"""
        COPY (
          SELECT extract(epoch from time)::double precision AS t, value
          FROM telemetry
          WHERE topic='fc.humidity' AND time >= '{start}' AND time < '{end}'
          ORDER BY time
        ) TO STDOUT WITH CSV
    """, paths['rh'])
    return paths


def build_grid(paths: dict):
    pid = pd.read_csv(paths['pid'], header=None, names=['t', 'pid'])
    tgt = pd.read_csv(paths['target'], header=None, names=['t', 'target'])
    rh_raw = pd.read_csv(paths['rh'], header=None, names=['t', 'rh_pct'])

    t0, t1 = int(pid.t.min()), int(pid.t.max())
    full_idx = np.arange(t0, t1 + 1, dtype=np.int64)

    pid_s = pd.Series(pid.pid.values, index=pid.t.values).reindex(full_idx)
    tgt_s = pd.Series(tgt.target.values, index=tgt.t.values).reindex(full_idx)

    rh_sorted = rh_raw.sort_values('t').copy()
    rh_sorted['t'] = rh_sorted['t'].astype(np.float64)
    grid_df = pd.DataFrame({'t': full_idx.astype(np.float64)})
    merged = pd.merge_asof(grid_df, rh_sorted[['t', 'rh_pct']], on='t',
                            direction='backward', tolerance=GAP_BREAK_S)
    rh_s = pd.Series(merged.rh_pct.values, index=full_idx)

    tgt_ffill = tgt_s.ffill(limit=GAP_BREAK_S)
    near_low = (tgt_ffill - BAND.band_low).abs() < TOL_TARGET
    near_high = (tgt_ffill - BAND.band_high).abs() < TOL_TARGET
    target_ok = (near_low | near_high)

    # DRIVING continuity does NOT require target_ok: fc_controller.py ~line
    # 1715 builds the control-law band from static per-mode config
    # (BandSpec(mode.band_low, mode.band_high, mode.defend_side)), never from
    # the ramping effective_setpoint that fc.humidity_target actually
    # publishes -- so the ramp after a restart does not perturb the law, and
    # replaying through it (rather than treating it as a discontinuity)
    # keeps the PID's own state faithful to what the real controller carried.
    # Only real telemetry holes force a drive break; target_ok gates METRICS
    # only (see metrics_valid below), per the brief's explicit instruction to
    # exclude ramp-affected samples from the comparison even though the law
    # itself is unaffected.
    drive_valid = (rh_s.notna() & tgt_ffill.notna()).values
    metrics_valid = drive_valid & target_ok.values & pid_s.notna().values

    return dict(full_idx=full_idx, pid=pid_s.values, target=tgt_s.values,
                rh_pct=rh_s.values, drive_valid=drive_valid, metrics_valid=metrics_valid)


def find_restarts(full_idx, target):
    flag = np.nan_to_num(target, nan=0.0) > RESTART_THRESHOLD
    secs = full_idx[flag]
    if len(secs) == 0:
        return np.array([]), np.array([])
    gaps = np.diff(secs)
    group_id = np.concatenate(([0], np.cumsum(gaps > RESTART_GROUP_GAP_S)))
    n = group_id[-1] + 1
    starts = np.array([secs[group_id == g][0] for g in range(n)])
    ends = np.array([secs[group_id == g][-1] for g in range(n)])
    return starts, ends


def find_runs(mask):
    d = np.diff(np.concatenate(([0], mask.astype(int), [0])))
    starts = np.where(d == 1)[0]
    ends = np.where(d == -1)[0]  # exclusive position index
    return starts, ends  # positions into the grid array


def classify_regime(rh_frac: float) -> str:
    """Tag which control-law branch a given RH would take. Pure function of
    RH + the static band/target/bypass_threshold -- mirrors ControlLoop.step
    without touching PID state, so it is safe to call for labelling alone."""
    projected = project_error_pct(rh_frac, BAND)
    if projected is None:
        return 'freeze'
    if BAND.defend_side == 'low':
        nearest = BAND.band_low
    elif BAND.defend_side == 'high':
        nearest = BAND.band_high
    else:
        nearest = BAND.band_low if rh_frac <= TARGET else BAND.band_high
    edge_pct = abs(rh_frac - nearest) * 100.0
    bypass_pct = GAINS.bypass_threshold * 100.0
    if edge_pct > bypass_pct and rh_frac < nearest:
        return 'mode_c_bypass'
    if rh_frac < BAND.midpoint:
        return 'below_midpoint_feather'
    if rh_frac > BAND.band_high:
        return 'above_band_high'
    return 'in_band'


def replay_segment(t_start_pos, t_end_pos, grid, warmup_s: float):
    """Replay one continuous drive-valid run. Returns arrays for the
    post-warmup, metrics-valid seconds only: t, rh_pct, pid_recorded,
    pid_predicted, regime."""
    control = ControlLoop(BAND, gains=GAINS, target=TARGET)
    n = t_end_pos - t_start_pos
    out_t, out_rh, out_recorded, out_predicted, out_regime = [], [], [], [], []
    warmup_ticks = int(warmup_s)  # dt=1.0 always
    for i in range(n):
        pos = t_start_pos + i
        rh_pct = grid['rh_pct'][pos]
        rh_frac = rh_pct / 100.0
        duty, raw = control.step(rh_frac, 1.0)
        if i < warmup_ticks:
            continue
        if not grid['metrics_valid'][pos]:
            continue
        out_t.append(grid['full_idx'][pos])
        out_rh.append(rh_pct)
        out_recorded.append(grid['pid'][pos])
        out_predicted.append(raw)
        out_regime.append(classify_regime(rh_frac))
    return out_t, out_rh, out_recorded, out_predicted, out_regime


def _restart_positions(full_idx, restart_starts):
    """Grid positions of each restart's first flagged second, for splitting a
    drive-valid run even when the data itself has no gap there (the PID
    state still resets at that instant -- see build_grid's docstring note)."""
    return np.searchsorted(full_idx, restart_starts)


def run_all_segments(grid, restart_starts, restart_ends, warmup_s=WARMUP_S, verbose=True):
    drive_starts, drive_ends = find_runs(grid['drive_valid'])
    restart_pos = set(_restart_positions(grid['full_idx'], restart_starts).tolist())

    # Split each drive-valid run additionally at any restart position that
    # falls strictly inside it -- the real controller's PID resets there
    # even though the telemetry itself is continuous through the ramp.
    starts, ends, anchored_flags = [], [], []
    for ds, de in zip(drive_starts, drive_ends):
        cuts = sorted(p for p in restart_pos if ds < p < de)
        bounds = [ds] + cuts + [de]
        for i in range(len(bounds) - 1):
            s, e = bounds[i], bounds[i + 1]
            starts.append(s)
            ends.append(e)
            anchored_flags.append(s in restart_pos)
    starts = np.array(starts)
    ends = np.array(ends)
    lengths = ends - starts

    all_t, all_rh, all_rec, all_pred, all_reg, all_anchored = [], [], [], [], [], []
    n_anchored, n_full_warmup, n_skipped_short = 0, 0, 0
    skipped_s = 0
    for s, e, anchored in zip(starts, ends, anchored_flags):
        seg_warmup = 0.0 if anchored else warmup_s
        if (e - s) <= seg_warmup:
            n_skipped_short += 1
            skipped_s += (e - s)
            continue
        if anchored:
            n_anchored += 1
        else:
            n_full_warmup += 1
        t, rh, rec, pred, reg = replay_segment(s, e, grid, seg_warmup)
        all_t.extend(t)
        all_rh.extend(rh)
        all_rec.extend(rec)
        all_pred.extend(pred)
        all_reg.extend(reg)
        all_anchored.extend([anchored] * len(t))
    if verbose:
        print(f'segments: {len(starts)} total, {n_anchored} restart-anchored (0 warmup), '
              f'{n_full_warmup} full-warmup ({warmup_s/3600:.0f}h), '
              f'{n_skipped_short} too short to warm up ({skipped_s}s dropped)', file=sys.stderr)
    df = pd.DataFrame({
        't': all_t, 'rh_pct': all_rh, 'pid_recorded': all_rec,
        'pid_predicted': all_pred, 'regime': all_reg, 'restart_anchored': all_anchored,
    })
    df['error'] = df['pid_predicted'] - df['pid_recorded']
    return df, dict(n_segments=len(starts), n_anchored=n_anchored,
                     n_full_warmup=n_full_warmup, n_skipped_short=n_skipped_short,
                     skipped_s=skipped_s, seg_lengths=lengths)


def metrics_table(df: pd.DataFrame) -> dict:
    err = df['error'].abs()
    return dict(
        n=len(df),
        rmse=float(np.sqrt((df['error'] ** 2).mean())) if len(df) else float('nan'),
        mae=float(err.mean()) if len(df) else float('nan'),
        max_abs=float(err.max()) if len(df) else float('nan'),
        median=float(df['error'].median()) if len(df) else float('nan'),
        frac_01=float((err <= 0.01).mean()) if len(df) else float('nan'),
        frac_05=float((err <= 0.05).mean()) if len(df) else float('nan'),
        frac_10=float((err <= 0.10).mean()) if len(df) else float('nan'),
        corr=float(df['pid_recorded'].corr(df['pid_predicted'])) if len(df) > 1 else float('nan'),
    )


def downsample_min_max(df: pd.DataFrame, bucket_s: int) -> pd.DataFrame:
    """Keep both the min-error and max-error row in every bucket_s window."""
    b = (df['t'] // bucket_s).astype(np.int64)
    rows = []
    for _, g in df.groupby(b):
        rows.append(g.loc[g['error'].idxmin()])
        if len(g) > 1:
            rows.append(g.loc[g['error'].idxmax()])
    out = pd.DataFrame(rows).drop_duplicates(subset=['t']).sort_values('t')
    return out


def write_csv(df: pd.DataFrame, path: Path, header_comment: str) -> None:
    with open(path, 'w', newline='') as f:
        f.write(header_comment)
        writer = csv.writer(f)
        writer.writerow(['time_utc', 'rh_pct', 'pid_recorded', 'pid_predicted', 'error', 'regime'])
        for _, row in df.iterrows():
            ts = datetime.fromtimestamp(int(row['t']), tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            writer.writerow([ts, f"{row['rh_pct']:.4f}", f"{row['pid_recorded']:.6f}",
                              f"{row['pid_predicted']:.6f}", f"{row['error']:.6f}", row['regime']])


def per_day(df: pd.DataFrame) -> pd.DataFrame:
    day = df['t'].apply(lambda t: datetime.fromtimestamp(int(t), tz=timezone.utc).strftime('%Y-%m-%d'))
    rows = []
    for d, g in df.groupby(day):
        m = metrics_table(g)
        rows.append({'day': d, 'n': m['n'], 'rmse': m['rmse'], 'mae': m['mae'],
                     'max_abs': m['max_abs']})
    return pd.DataFrame(rows).sort_values('day')


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--start', default='2026-06-29')
    ap.add_argument('--end', default='2026-08-09')
    ap.add_argument('--cache-dir', default=str(REPO_ROOT / '.cache' / 'mushy-59-replay'))
    ap.add_argument('--warmup-sweep', action='store_true',
                     help='Also run the 1h/3h/6h/12h warm-up sensitivity sweep '
                          '(re-replays the long non-restart-anchored segments '
                          'once per warm-up value -- slower).')
    args = ap.parse_args()

    cache_dir = Path(args.cache_dir)
    paths = export_csvs(args.start, args.end, cache_dir)
    grid = build_grid(paths)
    restart_starts, restart_ends = find_restarts(grid['full_idx'], grid['target'])

    df, seg_info = run_all_segments(grid, restart_starts, restart_ends)

    overall = metrics_table(df)
    by_regime = {r: metrics_table(g) for r, g in df.groupby('regime')}
    by_anchor = {a: metrics_table(g) for a, g in df.groupby('restart_anchored')}
    daily = per_day(df)

    warmup_sweep_results = None
    if args.warmup_sweep:
        warmup_sweep_results = {}
        for w in WARMUP_SWEEP_S:
            df_w, _ = run_all_segments(grid, restart_starts, restart_ends, warmup_s=w, verbose=False)
            warmup_sweep_results[w] = metrics_table(df_w)
            print(f'warmup={w/3600:.0f}h -> RMSE={warmup_sweep_results[w]["rmse"]:.4f}', file=sys.stderr)

    # --- CSV outputs ---
    PHASE_DIR.mkdir(parents=True, exist_ok=True)
    down = downsample_min_max(df, DOWNSAMPLE_BUCKET_S)
    header = (f'# MUSHY-59 control-law replay, downsampled: {DOWNSAMPLE_BUCKET_S}s buckets, '
              f'min+max |error| row kept per bucket (never naive sampling -- extremes are '
              f'the interesting part). Window {args.start}..{args.end}. '
              f'{len(df)} raw seconds -> {len(down)} rows.\n')
    write_csv(down, OUT_CSV, header)

    rep_start = int(pd.Timestamp(REPRESENTATIVE_48H_START).timestamp())
    rep_end = rep_start + 48 * 3600
    rep_df = df[(df['t'] >= rep_start) & (df['t'] < rep_end)]
    header48 = (f'# MUSHY-59 control-law replay, FULL 1Hz resolution, representative window '
                f'{REPRESENTATIVE_48H_START} + 48h ({len(rep_df)} rows).\n')
    write_csv(rep_df, OUT_CSV_48H, header48)

    print(f'wrote {OUT_CSV} ({len(down)} rows) and {OUT_CSV_48H} ({len(rep_df)} rows)', file=sys.stderr)

    # dump intermediate state for the report-writing pass
    with open(cache_dir / 'results.pkl', 'wb') as f:
        pickle.dump(dict(overall=overall, by_regime=by_regime, by_anchor=by_anchor,
                          daily=daily, seg_info=seg_info, warmup_sweep=warmup_sweep_results,
                          n_grid=len(grid['full_idx']),
                          n_drive_valid=int(grid['drive_valid'].sum()),
                          n_metrics_valid=int(grid['metrics_valid'].sum()),
                          n_restarts=len(restart_starts), restart_starts=restart_starts,
                          restart_ends=restart_ends, args=vars(args)), f)
    print(f'wrote {cache_dir / "results.pkl"}', file=sys.stderr)


if __name__ == '__main__':
    main()
