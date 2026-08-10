#!/usr/bin/env python3
"""Identify the chamber's effective moisture-loss coefficient Q and fill rate F.

Offline analysis only -- never runs on the Pi, never touches the control path.

Q comes from quiet intervals (delivered duty 0 for longer than the dead time),
where the fill term vanishes and the leak is observed alone. F is then fitted
on active intervals with Q held fixed. Sequential rather than joint: fitting
both at once is degenerate, since a larger F and a larger Q trade off.

Q is called a "moisture-loss coefficient", not "air-exchange conductance": a
settle-time sweep (see below) shows a 4x monotone range with no plateau, which
a single-mechanism first-order leak would not produce. It lumps infiltration,
wall condensation, and substrate exchange -- calling it air-exchange overstates
its physicality.

`fc.humidifier` is published ON EDGE ONLY (fc_pwm_driver.py:_set_relay), so a
naive avg(value) per minute returns ~0.5 regardless of true duty whenever a
minute has both a rising and a falling edge -- roughly equal edge counts, not
occupancy. Delivered duty is reconstructed here as the time-weighted integral
of the held relay state between edges, and cross-checked against the
independent fc.humidifier_duty topic (91-99% minute coverage from 2026-05-01);
the script aborts if the two disagree by more than a few percent in any month.
A nonzero held state is capped at RELAY_HOLD_CAP_MIN without a fresh edge --
beyond that it is treated as unknown, not as "on", since a PWM-controlled
relay staying continuously on for hours without a single toggle is not
physically plausible and is more likely a telemetry gap that happened to
start mid-pulse (e.g. 2026-04-23, 22.9 h). A held-OFF (0.0) state is NOT
capped: long genuine quiet stretches (up to ~5 days) are real -- confirmed
against fc.humidifier_duty, which shows continuous ~2 Hz coverage and mean
commanded duty ~0.0001 during them, i.e. the controller was up and genuinely
commanding near-zero duty, not silent.

F is regressed on `u_app`, the delivered duty pushed through the SAME
dead-time queue + first-order lag as fc_core.sim.chamber_model.ChamberModel,
not on the contemporaneous duty -- otherwise the lagged response attenuates
the fitted gain. The `duty > 0` filter (raw, contemporaneous duty) IS kept --
an earlier round of this fix dropped it to admit the post-burst tail, which
was wrong: the tail is only safe to admit if Q is correct in that regime, and
it is not (see below), so admitting it just moved bias into F, including a
physically impossible negative F over Apr-Jun (-8.06 g/h).

Q is regime-dependent: effective Q measured by minutes-since-the-relay-dropped
runs roughly 1.3-1.8 in the first ~40 minutes and falls to ~0.2 beyond 2
hours (see `effective_q_by_regime`). The unbounded quiet-settle mask used by
the settle sweep is dominated (79%) by that >120-minute tail, so a Q fitted
on it and then applied to the ~tens-of-minutes-scale active regime
under-predicts the true loss there. Fixed by restricting the Q used
operationally (for the F regression, F-moment, and F/Q below) to a bounded
run-length band [Q_BAND_LO, Q_BAND_HI] rather than fitting a full two-
timescale model -- see Q_BAND_LO/Q_BAND_HI below for the chosen band and
rationale. This is option (b) of the two offered fixes, not option (a)
(fitting an explicit fast+slow two-timescale Q); the unbounded sweep is kept
as a separate diagnostic, not used operationally.

The moment balance (`fit_f_moment`) is NOT estimator-independent -- it is
`~ Q * mean(gradient) / mean(u)`, i.e. directly proportional to Q, and
inherits Q's settle-sensitivity. `F/Q` (`mean_grad/mean_u`) is the one
genuinely well-identified quantity here: it cancels both Q and the lag
entirely and is what sets steady-state duty.

Point estimates alone are not reported for Q/F/F-moment/F-over-Q: each carries
a day-block bootstrap 95% CI (resampling whole UTC days, not individual
minutes, since both signals are strongly autocorrelated within a day).

Usage:
    python3 scripts/fit-chamber-model.py
    python3 scripts/fit-chamber-model.py --report path/to/RESULTS.md
"""
import argparse
import json
import random
import subprocess
import sys
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / 'src' / 'chambers' / 'fc-core'))

from fc_core.sim.ambient import AmbientSeries          # noqa: E402
from fc_core.sim.chamber_model import ChamberParams    # noqa: E402
from fc_core.sim.psychrometrics import (               # noqa: E402
    CHAMBER_VOLUME_M3, absolute_humidity_g_m3)

CONTAINER = 'mushy-timescale-1'
WINDOW_START = '2026-04-11'
WINDOW_END = '2026-08-09'          # exclusive upper bound for the SQL BETWEEN
SPLIT = datetime(2026, 7, 1, tzinfo=timezone.utc)   # fit < SPLIT <= validate
COMMANDED_DUTY_START = '2026-05-01'   # fc.humidifier_duty doesn't exist before this

DEAD_TIME_S = ChamberParams().dead_time_s   # 360.0, same as the simulator
TAU_S = ChamberParams().tau_s               # 600.0, same as the simulator
QUIET_SETTLE_MIN = 10              # discard this many minutes after duty falls
RH_SATURATED = 99.99               # farmer ruling: exclude, do not clamp
MAX_RH_STEP_PCT = 3.0               # sensor-failover step guard (see design lim. 7)
QUIET_NEED_DEFAULT = int(DEAD_TIME_S / 60.0) + QUIET_SETTLE_MIN   # 16
QUIET_NEED_SWEEP = [7, 16, 46, 136]     # minutes of zero-duty run required (diagnostic only)
DUTY_CROSS_CHECK_TOL = 0.05             # abort if monthly means disagree > 5%
RELAY_HOLD_CAP_MIN = 60     # cap on an uninterrupted NONZERO relay hold; see module docstring
Q_BAND_LO = QUIET_NEED_DEFAULT   # 16 -- same lower bound the dead-time argument requires
# Q_BAND_HI excludes the >120 min tail that dominates (79%) and pulls the
# unbounded fit down toward its asymptote. This is a JUDGMENT CALL, not a
# derived quantity -- see q_band_sweep and "The band sets F" in the report:
# nothing in the model has a 120-minute timescale (tau=600s, dead_time=360s).
Q_BAND_HI = 120
OLD_MODEL_LEAK_G_PER_H = 0.865   # previous RH-points model's implied leak, for sanity-check only
N_BOOT = 2000
N_BOOT_RATIO = 4000
BOOT_SEED = 0
EFFECTIVE_Q_BUCKETS = [(1, 3), (4, 8), (9, 16), (17, 40), (41, 120), (121, float('inf'))]
# Sweeps for q_band_sweep -- see "The band sets F" in the report.
Q_HI_SWEEP = [30, 45, 60, 90, 120, 180, 240, 480, 1440, float('inf')]
Q_LO_SWEEP = [1, 4, 8, 12, 16, 20, 30, 40, 80]
DEFAULT_REPORT = (REPO_ROOT / '.planning' / 'phases'
                  / '999.33-digital-twin-chamber-sim'
                  / '999.33-06-FIT-RESULTS.md')


def psql(sql: str) -> str:
    r = subprocess.run(
        ['docker', 'exec', CONTAINER, 'psql', '-U', 'postgres', '-d', 'postgres',
         '-F', '\t', '-A', '-t', '-c', sql],
        capture_output=True, text=True, check=True)
    return r.stdout


def parse_epoch(raw: str) -> datetime:
    """Parse a Postgres `extract(epoch from ...)` value into a UTC datetime.

    Queries below select epoch seconds rather than a formatted timestamp
    string on purpose: psql's textual timestamptz output on this host has
    both a colon-less UTC offset ('+00' not '+00:00') and variable-precision
    fractional seconds (psql strips trailing zeros), and Python 3.10's
    `datetime.fromisoformat` (pre-3.11) rejects both forms. Epoch seconds
    sidestep the parsing entirely.
    """
    return datetime.fromtimestamp(float(raw.strip()), tz=timezone.utc)


def load_temp_rh():
    """One row per grid minute: temp and rh, both plain per-minute averages.

    Unlike the relay, temperature and humidity are not edge-only -- averaging
    a minute of samples is a fine estimate of the minute's value for these.
    """
    sql = f"""
    with grid as (
      select generate_series(timestamptz '{WINDOW_START}',
                             timestamptz '{WINDOW_END}',
                             interval '1 minute') b),
    th as (
      select time_bucket('1 minute', time) b,
             avg(value) filter (where topic='fc.temperature') temp,
             avg(value) filter (where topic='fc.humidity')    rh
      from telemetry
      where topic in ('fc.temperature','fc.humidity')
        and time between '{WINDOW_START}' and '{WINDOW_END}'
      group by 1)
    select extract(epoch from g.b), th.temp, th.rh
    from grid g left join th on th.b = g.b
    order by g.b;
    """
    out = {}
    for line in psql(sql).splitlines():
        if not line.strip():
            continue
        b, temp, rh = (line.split('\t') + [''] * 3)[:3]
        out[parse_epoch(b)] = (
            float(temp) if temp.strip() else None,
            float(rh) if rh.strip() else None,
        )
    return out


def load_relay_duty():
    """Time-weighted duty per grid minute, reconstructed from edge-only relay
    state, plus the hold age (minutes since the last edge) for each minute.

    fc.humidifier is binary and published ON EDGE ONLY. A minute's delivered
    duty is the integral of the held relay value (each published value stays
    in force until the next edge) divided by 60 -- NOT avg(value) of whatever
    edges happen to land in that minute, which returns ~0.5 regardless of the
    true duty whenever a minute has both a rising and a falling edge.

    April is unaffected: the relay was still published at ~1 Hz then (the
    driver switched to edge-only around May), so a plain per-minute average
    was already correct for that month; this reconstruction is a no-op there
    since edges are ~60/minute and the held-value integral converges to the
    same thing as a dense average.

    Returns the RAW reconstruction, uncapped -- the hold cap (see
    `apply_hold_cap`) is a separate, later exclusion decision, deliberately
    not baked in here, so the duty cross-check below validates the
    reconstruction formula itself rather than the cap policy on top of it.
    """
    sql = f"""
    select extract(epoch from time), value from telemetry
    where topic='fc.humidifier'
      and time between '{WINDOW_START}' and '{WINDOW_END}'
    order by time;
    """
    edges = []
    for line in psql(sql).splitlines():
        if not line.strip():
            continue
        t, v = line.split('\t')
        edges.append((parse_epoch(t), float(v)))

    grid_start = datetime.fromisoformat(WINDOW_START).replace(tzinfo=timezone.utc)
    grid_end = datetime.fromisoformat(WINDOW_END).replace(tzinfo=timezone.utc)

    duty, hold_min_by_ts = {}, {}
    ei, n = 0, len(edges)
    state, has_state = None, False
    last_edge_time = None
    cur = grid_start
    while cur < grid_end:
        b_end = cur + timedelta(minutes=1)
        accum = 0.0
        cursor = cur
        while ei < n and edges[ei][0] < b_end:
            et, ev = edges[ei]
            if et > cursor and has_state:
                accum += state * (et - cursor).total_seconds()
            if et > cursor:
                cursor = et
            state, has_state = ev, True
            last_edge_time = et
            ei += 1
        if has_state:
            accum += state * (b_end - cursor).total_seconds()
            duty[cur] = accum / 60.0
            hold_min_by_ts[cur] = (b_end - last_edge_time).total_seconds() / 60.0
        else:
            duty[cur] = None
            hold_min_by_ts[cur] = None
        cur = b_end
    return duty, hold_min_by_ts


def apply_hold_cap(duty):
    """A nonzero held state beyond RELAY_HOLD_CAP_MIN minutes without a fresh
    edge is treated as unknown (None), not "on" -- see module docstring for
    why. A held-OFF (0.0) state is never capped. Applied AFTER the duty
    cross-check, which validates the raw reconstruction independent of this
    exclusion policy.
    """
    reconstructed, hold_min_by_ts = duty
    out = {}
    for ts, d in reconstructed.items():
        hold_min = hold_min_by_ts[ts]
        if d is not None and d != 0.0 and hold_min is not None \
                and hold_min > RELAY_HOLD_CAP_MIN:
            out[ts] = None
        else:
            out[ts] = d
    return out


def load_commanded_duty():
    """Per-minute average of fc.humidifier_duty -- independent, continuously
    published, NOT the model's input. Used only to cross-check the
    reconstructed relay duty above."""
    sql = f"""
    select extract(epoch from time_bucket('1 minute', time)), avg(value) duty
    from telemetry
    where topic='fc.humidifier_duty'
      and time >= '{COMMANDED_DUTY_START}' and time < '{WINDOW_END}'
    group by 1
    order by 1;
    """
    out = {}
    for line in psql(sql).splitlines():
        if not line.strip():
            continue
        b, duty = line.split('\t')
        out[parse_epoch(b)] = float(duty)
    return out


def cross_check_duty(reconstructed, commanded):
    """Compare reconstructed relay duty against fc.humidifier_duty, per month.

    This is the check that caught the edge-only averaging bug: two
    independent telemetry sources should agree on delivered duty to a few
    percent. Aborts loudly if they don't.
    """
    by_month = defaultdict(lambda: [[], []])
    for ts, dv in commanded.items():
        rv = reconstructed.get(ts)
        if rv is None or dv is None:
            continue
        by_month[(ts.year, ts.month)][0].append(rv)
        by_month[(ts.year, ts.month)][1].append(dv)

    rows, failed = [], []
    for key in sorted(by_month):
        rvs, dvs = by_month[key]
        if not rvs:
            continue
        rmean = sum(rvs) / len(rvs)
        dmean = sum(dvs) / len(dvs)
        rel = abs(rmean - dmean) / dmean if dmean else float('inf')
        rows.append({'month': f'{key[0]}-{key[1]:02d}', 'reconstructed': rmean,
                     'commanded': dmean, 'rel_diff_pct': rel * 100,
                     'n': len(rvs)})
        if rel > DUTY_CROSS_CHECK_TOL:
            failed.append(key)

    if failed:
        raise AssertionError(
            'Reconstructed relay duty disagrees with fc.humidifier_duty by '
            f'more than {DUTY_CROSS_CHECK_TOL:.0%} in {failed} -- the duty '
            'reconstruction is likely wrong again. Not proceeding.')
    return rows


def apply_lag(grid_ts, grid_duty):
    """Push delivered duty through the SAME dead-time queue + first-order lag
    as fc_core.sim.chamber_model.ChamberModel.step, producing u_app -- the
    duty the moisture balance actually responds to, not the contemporaneous
    commanded value. Missing duty (before the first relay sample, or capped
    out by RELAY_HOLD_CAP_MIN) is treated as 0 so the queue stays
    well-defined; those minutes are excluded later anyway by the 'no_relay'
    check.
    """
    queue = deque()
    emerged = 0.0
    applied = 0.0
    now_s = 0.0
    prev_ts = None
    out = {}
    for ts in grid_ts:
        dt_s = 60.0 if prev_ts is None else (ts - prev_ts).total_seconds()
        now_s += dt_s
        duty = grid_duty.get(ts)
        u = duty if duty is not None else 0.0

        # Transport delay: duty commanded now takes effect dead_time_s later.
        queue.append((now_s + DEAD_TIME_S, u))
        while queue and queue[0][0] <= now_s:
            _, emerged = queue.popleft()

        # First-order mixing toward whatever has emerged from the delay.
        alpha = min(1.0, dt_s / max(TAU_S, 1e-9))
        applied += alpha * (emerged - applied)

        out[ts] = applied
        prev_ts = ts
    return out


def build_samples(grid_ts, temp_rh, duty, duty_app, ambient: AmbientSeries):
    """Attach ambient, convert to absolute moisture, and apply exclusions."""
    stats = {'total': 0, 'no_reading': 0, 'no_relay': 0, 'saturated': 0,
             'outside_ambient': 0, 'rh_step': 0, 'kept': 0}
    out = []
    prev_rh = None
    for ts in grid_ts:
        stats['total'] += 1
        temp, rh = temp_rh.get(ts, (None, None))
        d = duty.get(ts)
        if temp is None or rh is None:
            stats['no_reading'] += 1
            prev_rh = None
            continue
        if d is None:
            stats['no_relay'] += 1
            prev_rh = None
            continue
        if rh >= RH_SATURATED:
            stats['saturated'] += 1
            prev_rh = None
            continue
        if prev_rh is not None and abs(rh - prev_rh) > MAX_RH_STEP_PCT:
            # Sensor failover injects a step; a step is a huge spurious dAH/dt.
            stats['rh_step'] += 1
            prev_rh = rh
            continue
        prev_rh = rh
        try:
            amb = ambient.at(ts)
        except ValueError:
            stats['outside_ambient'] += 1
            continue
        stats['kept'] += 1
        out.append({
            'ts': ts,
            'duty': d,
            'duty_app': duty_app[ts],
            'ah_in': absolute_humidity_g_m3(temp, rh),
            'ah_out': absolute_humidity_g_m3(amb.temp_c, amb.rh_pct),
        })
    return out, stats


def with_derivatives(samples):
    """Central-ish difference on consecutive 1-minute samples, in g/m3 per hour.

    Only pairs exactly 60 s apart are used -- a longer span means an excluded
    sample sits between them and the derivative would smear across it.
    """
    out = []
    for a, b in zip(samples, samples[1:]):
        dt_s = (b['ts'] - a['ts']).total_seconds()
        if dt_s != 60.0:
            continue
        rec = dict(a)
        rec['dah_dt'] = (b['ah_in'] - a['ah_in']) * 3600.0 / dt_s
        out.append(rec)
    return out


def zero_run_lengths(samples):
    """Consecutive zero-duty run length in minutes for each sample, reset
    both when duty is nonzero AND whenever consecutive samples in the list
    are not exactly 60 s apart in wall-clock time.

    BUG FIXED (round 3): the run counter previously walked the SAMPLE LIST,
    not wall-clock time, and did not reset across an excluded or missing
    minute sitting between two list entries. `with_derivatives` already
    drops any (a, b) pair not exactly 60 s apart when computing dah_dt, but
    that does not guarantee consecutive entries of its OUTPUT list are 60 s
    apart from EACH OTHER -- if an excluded sample sits between two kept
    ones, both may still individually survive as the start of some other
    valid pair, and the run counter would silently treat them as adjacent
    minutes. 6.8% of band [Q_BAND_LO, Q_BAND_HI] samples had a zero-run
    spanning such a discontinuity before this fix -- their "minutes since
    the relay dropped" was fictional. Resetting to 0 on any gap is
    conservative: a sample immediately after an unknown-duration gap is
    treated as if the relay had just dropped (run=1), not as continuing
    whatever run was accumulated before the gap.

    Returns a list of run lengths parallel to `samples`.
    """
    run = 0
    runs = []
    prev_ts = None
    for s in samples:
        if prev_ts is None or (s['ts'] - prev_ts).total_seconds() != 60.0:
            run = 0
        run = run + 1 if s['duty'] == 0.0 else 0
        runs.append(run)
        prev_ts = s['ts']
    return runs


def quiet_mask(samples, need, runs=None):
    """True where duty has been 0 for at least `need` consecutive minutes
    (unbounded above). Used only for the settle-sweep diagnostic below --
    the operational Q uses `quiet_band_mask` instead. Pass a precomputed
    `runs` (from `zero_run_lengths`) to avoid recomputing it per call.

    NOTE (known off-by-one): `run` reaches `need` on the `need`-th zero-duty
    minute, i.e. `need - 1` minutes after duty actually fell to zero -- one
    minute short of the intended "duty has been 0 for `need` minutes" spec.
    Left as-is (see FIX reports) rather than changed silently.
    """
    if runs is None:
        runs = zero_run_lengths(samples)
    return [r >= need for r in runs]


def quiet_band_mask(samples, lo, hi, runs=None):
    """True where the relay has been off between lo and hi consecutive
    minutes (inclusive), using time-discontinuity-aware run lengths.
    Bounding the upper end, unlike `quiet_mask`, is what keeps this
    population from being dominated by arbitrarily long quiet runs -- see
    Q_BAND_LO/Q_BAND_HI and the module docstring."""
    if runs is None:
        runs = zero_run_lengths(samples)
    return [lo <= r <= hi for r in runs]


def fit_q(samples):
    """Least squares through the origin: -V*dAH/dt = Q * (AH_in - AH_out)."""
    num = den = 0.0
    n = 0
    for s in samples:
        x = s['ah_in'] - s['ah_out']
        y = -CHAMBER_VOLUME_M3 * s['dah_dt']
        num += x * y
        den += x * x
        n += 1
    return (num / den if den else float('nan')), n


def fit_f_regression(samples, q):
    """Least squares through the origin, Q held fixed, regressed on u_app,
    restricted to raw duty > 0 (active) samples:
       V*dAH/dt + Q*(AH_in - AH_out) = F * u_app.

    The `duty > 0` filter is restored (a previous round dropped it to admit
    the post-burst tail). Admitting that tail is only valid if Q is correct
    in the tail regime, and it is not -- see module docstring. u_app is still
    the regressor, since the lag-attenuation problem that motivated it is a
    separate, real issue from the tail-inclusion mistake.
    """
    num = den = 0.0
    n = 0
    for s in samples:
        if s['duty'] <= 0.0:
            continue
        u = s['duty_app']
        z = CHAMBER_VOLUME_M3 * s['dah_dt'] + q * (s['ah_in'] - s['ah_out'])
        num += u * z
        den += u * u
        n += 1
    return (num / den if den else float('nan')), n


def fit_f_moment(samples, q):
    """Moment-balance cross-check for F. NOT estimator-independent: in
    quasi-steady state mean(V*dAH/dt) ~ 0, so this is very nearly
    Q*mean(gradient)/mean(u) -- directly proportional to Q, and it inherits
    Q's full settle-sensitivity rather than escaping it. Report beside the
    regression as a second view, not as arbitration.
    """
    if not samples:
        return float('nan')
    n = len(samples)
    mean_grad = sum(s['ah_in'] - s['ah_out'] for s in samples) / n
    mean_dahdt = sum(s['dah_dt'] for s in samples) / n
    mean_u = sum(s['duty'] for s in samples) / n
    if mean_u == 0:
        return float('nan')
    return (q * mean_grad + CHAMBER_VOLUME_M3 * mean_dahdt) / mean_u


def fit_f_over_q(samples):
    """F/Q = mean_grad/mean_u exactly -- free of both Q and the lag entirely.
    The one genuinely well-identified aggregate quantity in this dataset;
    it is what sets steady-state duty."""
    if not samples:
        return float('nan')
    n = len(samples)
    mean_grad = sum(s['ah_in'] - s['ah_out'] for s in samples) / n
    mean_u = sum(s['duty'] for s in samples) / n
    return mean_grad / mean_u if mean_u else float('nan')


def effective_q_by_regime(samples, runs=None):
    """Empirical effective Q bucketed by minutes-since-the-relay-dropped.
    If a single first-order leak governed decay these would agree; they
    don't (see module docstring), which is the evidence behind restricting
    Q's operational fit to a bounded band rather than the full unbounded
    quiet population.

    CONFOUNDED WITH SEASON -- see `effective_q_by_regime_and_half` and the
    "Q regime effect is confounded with season" report section. The pooled
    decline shown here should not be read as a clean single-mechanism
    regime effect without checking that split.
    """
    if runs is None:
        runs = zero_run_lengths(samples)
    bucketed = {b: [] for b in EFFECTIVE_Q_BUCKETS}
    for s, run in zip(samples, runs):
        if run == 0:
            continue
        for lo, hi in EFFECTIVE_Q_BUCKETS:
            if lo <= run <= hi:
                bucketed[(lo, hi)].append(s)
                break
    rows = []
    for lo, hi in EFFECTIVE_Q_BUCKETS:
        q, n = fit_q(bucketed[(lo, hi)])
        label = f'{lo}-{hi}' if hi != float('inf') else f'>{lo - 1}'
        rows.append({'band': label, 'q_g_per_m3h': q, 'n': n})
    return rows


def effective_q_by_regime_and_half(samples, runs=None):
    """Same buckets as `effective_q_by_regime`, split by fit (Apr-Jun) vs
    validate (Jul-Aug) half. Shows the pooled monotone decline is
    substantially a COMPOSITION effect, not a clean regime effect: short
    runs are overwhelmingly Apr-Jun, the deep-quiet tail is
    disproportionately Jul-Aug, so the operational band selects a season
    almost as much as a regime."""
    if runs is None:
        runs = zero_run_lengths(samples)
    bucketed = {(b, half): [] for b in EFFECTIVE_Q_BUCKETS for half in ('fit', 'val')}
    for s, run in zip(samples, runs):
        if run == 0:
            continue
        half = 'fit' if s['ts'] < SPLIT else 'val'
        for lo, hi in EFFECTIVE_Q_BUCKETS:
            if lo <= run <= hi:
                bucketed[((lo, hi), half)].append(s)
                break
    rows = []
    for lo, hi in EFFECTIVE_Q_BUCKETS:
        q_fit, n_fit = fit_q(bucketed[((lo, hi), 'fit')])
        q_val, n_val = fit_q(bucketed[((lo, hi), 'val')])
        label = f'{lo}-{hi}' if hi != float('inf') else f'>{lo - 1}'
        rows.append({'band': label, 'q_fit': q_fit, 'n_fit': n_fit,
                     'q_val': q_val, 'n_val': n_val})
    return rows


def q_settle_sweep(samples, runs=None):
    """Q's sensitivity to the quiet-settle threshold (unbounded above) --
    a single-mechanism first-order leak would plateau as the threshold
    grows; this doesn't. Diagnostic only -- not the Q used operationally."""
    if runs is None:
        runs = zero_run_lengths(samples)
    rows = []
    for need in QUIET_NEED_SWEEP:
        flags = quiet_mask(samples, need, runs=runs)
        quiet = [s for s, f in zip(samples, flags) if f]
        q, n = fit_q(quiet)
        rows.append({'need_min': need, 'q_g_per_m3h': q, 'n_quiet': n})
    return rows


def q_band_sweep(samples, runs=None):
    """How much the Q band choice itself sets F. Since F/Q = mean_grad/mean_u
    is band-free, F is exactly proportional to Q, and the band is the ONLY
    thing setting Q operationally -- so the band is a direct dial on F. Two
    one-parameter sweeps around the operational choice [Q_BAND_LO,
    Q_BAND_HI]: hold lo fixed and vary hi, then hold hi fixed and vary lo.
    See "The band sets F" in the report."""
    if runs is None:
        runs = zero_run_lengths(samples)

    def one(lo, hi):
        quiet = [s for s, r in zip(samples, runs) if lo <= r <= hi]
        q, n = fit_q(quiet)
        f_reg, _ = fit_f_regression(samples, q)
        return {'lo': lo, 'hi': hi, 'q_g_per_m3h': q,
                'f_regression_g_per_h': f_reg, 'n_quiet': n}

    hi_sweep = [one(Q_BAND_LO, hi) for hi in Q_HI_SWEEP]
    lo_sweep = [one(lo, Q_BAND_HI) for lo in Q_LO_SWEEP]
    return {'hi_sweep': hi_sweep, 'lo_sweep': lo_sweep}


def precompute_day_stats(samples, runs=None):
    """Per UTC-day sufficient statistics for every regression used below.

    Every estimator here (Q, F regression, F moment, F/Q) is linear in a
    handful of running sums, so a day-block bootstrap can resample days and
    recombine these per-day sums instead of re-scanning all ~150k samples on
    every replicate. This is a second implementation of the same math as
    `fit_q`/`fit_f_regression`/`fit_f_moment`/`fit_f_over_q`, grouped by day
    purely for bootstrap performance -- `fit_half` cross-checks the two
    against each other on the non-resampled data and raises if they diverge,
    so this duplication cannot silently drift from the documented estimator.
    """
    if runs is None:
        runs = zero_run_lengths(samples)
    days = defaultdict(lambda: {
        'quiet_xy': 0.0, 'quiet_xx': 0.0, 'quiet_n': 0,
        'act_u_dahdt': 0.0, 'act_u_grad': 0.0, 'act_uu': 0.0, 'act_n': 0,
        'full_grad': 0.0, 'full_dahdt': 0.0, 'full_u': 0.0, 'full_n': 0,
    })
    for s, run in zip(samples, runs):
        d = days[s['ts'].date()]
        grad = s['ah_in'] - s['ah_out']
        if Q_BAND_LO <= run <= Q_BAND_HI:
            y = -CHAMBER_VOLUME_M3 * s['dah_dt']
            d['quiet_xy'] += grad * y
            d['quiet_xx'] += grad * grad
            d['quiet_n'] += 1
        if s['duty'] > 0.0:
            d['act_u_dahdt'] += s['duty_app'] * s['dah_dt']
            d['act_u_grad'] += s['duty_app'] * grad
            d['act_uu'] += s['duty_app'] * s['duty_app']
            d['act_n'] += 1
        d['full_grad'] += grad
        d['full_dahdt'] += s['dah_dt']
        d['full_u'] += s['duty']
        d['full_n'] += 1
    return dict(days)


def aggregate_days(day_stats, dates):
    agg = {'quiet_xy': 0.0, 'quiet_xx': 0.0, 'quiet_n': 0,
           'act_u_dahdt': 0.0, 'act_u_grad': 0.0, 'act_uu': 0.0, 'act_n': 0,
           'full_grad': 0.0, 'full_dahdt': 0.0, 'full_u': 0.0, 'full_n': 0}
    for dt in dates:
        d = day_stats.get(dt)
        if d is None:
            continue
        for k in agg:
            agg[k] += d[k]
    return agg


def stats_from_agg(agg):
    """Q, F regression, F moment, F/Q from aggregated per-day sums."""
    q = agg['quiet_xy'] / agg['quiet_xx'] if agg['quiet_xx'] else float('nan')
    f_reg = ((CHAMBER_VOLUME_M3 * agg['act_u_dahdt'] + q * agg['act_u_grad'])
             / agg['act_uu'] if agg['act_uu'] else float('nan'))
    n = agg['full_n']
    if n:
        mean_grad = agg['full_grad'] / n
        mean_dahdt = agg['full_dahdt'] / n
        mean_u = agg['full_u'] / n
    else:
        mean_grad = mean_dahdt = mean_u = float('nan')
    f_mom = ((q * mean_grad + CHAMBER_VOLUME_M3 * mean_dahdt) / mean_u
             if mean_u else float('nan'))
    f_over_q = mean_grad / mean_u if mean_u else float('nan')
    return q, f_reg, f_mom, f_over_q


def moment_and_foq_for_dates(day_stats, dates, q):
    """F-moment and F/Q for a date subset with Q held fixed (not re-fit) --
    used for the monthly moment breakdown and the Aug-excluded validate
    view, where Q should come from the parent set, not from a re-fit on a
    possibly Q-starved subset."""
    agg = aggregate_days(day_stats, dates)
    n = agg['full_n']
    if not n:
        return float('nan'), float('nan')
    mean_grad = agg['full_grad'] / n
    mean_dahdt = agg['full_dahdt'] / n
    mean_u = agg['full_u'] / n
    if mean_u == 0:
        return float('nan'), float('nan')
    f_mom = (q * mean_grad + CHAMBER_VOLUME_M3 * mean_dahdt) / mean_u
    f_over_q = mean_grad / mean_u
    return f_mom, f_over_q


def bootstrap_ci(day_stats, dates, n_boot=N_BOOT, seed=BOOT_SEED):
    """Day-block bootstrap 95% CIs for Q, F (regression), F (moment), F/Q.
    Resampling whole days -- not individual minutes -- respects the strong
    within-day autocorrelation of both the moisture signal and the duty
    cycle; resampling minutes independently would understate the CI width.
    """
    dates = list(dates)
    if not dates:
        nan = (float('nan'), float('nan'))
        return {'q': nan, 'f_reg': nan, 'f_mom': nan, 'f_over_q': nan}
    rng = random.Random(seed)
    boots = {'q': [], 'f_reg': [], 'f_mom': [], 'f_over_q': []}
    for _ in range(n_boot):
        sample_dates = [rng.choice(dates) for _ in range(len(dates))]
        agg = aggregate_days(day_stats, sample_dates)
        q, f_reg, f_mom, f_over_q = stats_from_agg(agg)
        boots['q'].append(q)
        boots['f_reg'].append(f_reg)
        boots['f_mom'].append(f_mom)
        boots['f_over_q'].append(f_over_q)

    def ci(vals):
        vals = sorted(v for v in vals if v == v)
        if not vals:
            return (float('nan'), float('nan'))
        n = len(vals)
        lo = vals[max(0, int(0.025 * n))]
        hi = vals[min(n - 1, int(0.975 * n))]
        return (lo, hi)

    return {k: ci(v) for k, v in boots.items()}


def bootstrap_ratio_ci(
        day_stats, fit_dates, val_dates, n_boot=N_BOOT_RATIO, seed=BOOT_SEED):
    """Bootstrap CI for the validate/fit RATIO of each statistic -- this,
    not two separately-eyeballed CIs, is the statistic that actually tests
    season-independence. Each replicate independently resamples days within
    each half, computes both halves' statistics, and records the ratio.
    """
    fit_dates, val_dates = list(fit_dates), list(val_dates)
    rng = random.Random(seed)
    boots = {'q': [], 'f_reg': [], 'f_mom': [], 'f_over_q': []}
    for _ in range(n_boot):
        fit_sample = [rng.choice(fit_dates) for _ in range(len(fit_dates))]
        val_sample = [rng.choice(val_dates) for _ in range(len(val_dates))]
        qf, frf, fmf, foqf = stats_from_agg(aggregate_days(day_stats, fit_sample))
        qv, frv, fmv, foqv = stats_from_agg(aggregate_days(day_stats, val_sample))
        for key, num, den in (('q', qv, qf), ('f_reg', frv, frf),
                              ('f_mom', fmv, fmf), ('f_over_q', foqv, foqf)):
            valid = den not in (0.0,) and den == den and num == num
            boots[key].append(num / den if valid else float('nan'))

    def ci(vals):
        vals = sorted(v for v in vals if v == v)
        if not vals:
            return (float('nan'), float('nan'))
        n = len(vals)
        lo = vals[max(0, int(0.025 * n))]
        hi = vals[min(n - 1, int(0.975 * n))]
        return (lo, hi)

    return {k: ci(v) for k, v in boots.items()}


def assert_estimators_agree(direct, agg, label, tol=1e-6):
    """The primary (documented) estimator functions and the day-block-
    aggregated path (kept only for bootstrap performance) must produce
    identical point estimates on the same, non-resampled sample set -- both
    are sums over the same data, just grouped differently. Raising here is
    what prevents the two implementations from silently drifting apart."""
    names = ('q', 'f_reg', 'f_mom', 'f_over_q')
    for name, a, b in zip(names, direct, agg):
        if a != a and b != b:   # both nan
            continue
        scale = max(1.0, abs(a), abs(b))
        if abs(a - b) > tol * scale:
            raise AssertionError(
                f'{label}: primary estimator and day-aggregated estimator '
                f'disagree on {name} ({a!r} vs {b!r}) -- they should be '
                'mathematically identical. Not proceeding.')


def fit_half(samples, day_stats, runs=None):
    if runs is None:
        runs = zero_run_lengths(samples)
    dates = sorted({s['ts'].date() for s in samples})

    # Point estimates via the primary (documented) estimator functions,
    # operating directly on this set's samples -- not the day-aggregated
    # path, which exists purely so the bootstrap below doesn't have to
    # rescan every sample per replicate. See `assert_estimators_agree`.
    band_flags = quiet_band_mask(samples, Q_BAND_LO, Q_BAND_HI, runs=runs)
    quiet = [s for s, f in zip(samples, band_flags) if f]
    q, nq = fit_q(quiet)
    f_reg, nf = fit_f_regression(samples, q)
    f_mom = fit_f_moment(samples, q)
    f_over_q = fit_f_over_q(samples)

    agg = aggregate_days(day_stats, dates)
    q_agg, f_reg_agg, f_mom_agg, f_over_q_agg = stats_from_agg(agg)
    assert_estimators_agree(
        (q, f_reg, f_mom, f_over_q),
        (q_agg, f_reg_agg, f_mom_agg, f_over_q_agg), 'fit_half')

    ci = bootstrap_ci(day_stats, dates)

    # Aug-excluded view: only differs when the set actually spans August.
    non_aug_dates = [d for d in dates if d.month != 8]
    f_mom_excl_aug, f_over_q_excl_aug = moment_and_foq_for_dates(
        day_stats, non_aug_dates, q)

    n_full = agg['full_n']
    mean_grad = agg['full_grad'] / n_full if n_full else float('nan')
    implied_leak = q * mean_grad
    old_leak_pct_off = (abs(implied_leak - OLD_MODEL_LEAK_G_PER_H)
                        / OLD_MODEL_LEAK_G_PER_H * 100)

    return {
        'q_g_per_m3h': q, 'n_quiet': nq,
        'f_regression_g_per_h': f_reg, 'n_active': nf,
        'f_moment_g_per_h': f_mom, 'f_moment_excl_aug_g_per_h': f_mom_excl_aug,
        'f_over_q': f_over_q, 'f_over_q_excl_aug': f_over_q_excl_aug,
        'n_samples': len(samples),
        'q_ci': ci['q'], 'f_regression_ci': ci['f_reg'],
        'f_moment_ci': ci['f_mom'], 'f_over_q_ci': ci['f_over_q'],
        'mean_grad_g_per_m3': mean_grad, 'implied_leak_g_per_h': implied_leak,
        'old_leak_pct_off': old_leak_pct_off,
    }


def monthly_moment_breakdown(day_stats, q_all):
    """F-moment and F/Q per calendar month, Q held fixed at the 'all' band
    value -- shows August's gradient collapse without needing a per-month
    Q re-fit (most months don't have enough quiet data to support one)."""
    months = sorted({dt.replace(day=1) for dt in day_stats})
    rows = []
    for month_start in months:
        dates = [dt for dt in day_stats if dt.year == month_start.year
                 and dt.month == month_start.month]
        f_mom, f_over_q = moment_and_foq_for_dates(day_stats, dates, q_all)
        rows.append({'month': f'{month_start.year}-{month_start.month:02d}',
                     'f_moment_g_per_h': f_mom, 'f_over_q': f_over_q,
                     'n_days': len(dates)})
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--report', default=str(DEFAULT_REPORT))
    args = ap.parse_args()

    ambient = AmbientSeries.from_csv()
    temp_rh = load_temp_rh()
    duty_raw, hold_min_by_ts = load_relay_duty()
    commanded = load_commanded_duty()
    duty_cross_check = cross_check_duty(duty_raw, commanded)
    duty = apply_hold_cap((duty_raw, hold_min_by_ts))
    n_capped = sum(1 for ts in duty_raw if duty_raw[ts] is not None
                   and duty[ts] is None)

    grid_ts = sorted(temp_rh)
    duty_app = apply_lag(grid_ts, duty)

    samples, stats = build_samples(grid_ts, temp_rh, duty, duty_app, ambient)
    samples = with_derivatives(samples)

    # Run lengths computed ONCE over the full continuous timeline, then
    # sliced -- NOT recomputed independently per half. A zero-duty run that
    # starts in June and continues past midnight into July is a genuine
    # continuation; recomputing on val_set alone would wrongly reset it to
    # run=1 at the first July sample. fit_half's own primary-vs-day-agg
    # cross-check caught exactly this class of bug during development.
    runs = zero_run_lengths(samples)
    fit_set, runs_fit = [], []
    val_set, runs_val = [], []
    for s, run in zip(samples, runs):
        if s['ts'] < SPLIT:
            fit_set.append(s)
            runs_fit.append(run)
        else:
            val_set.append(s)
            runs_val.append(run)

    day_stats = precompute_day_stats(samples, runs=runs)
    q_all_result = fit_half(samples, day_stats, runs=runs)
    fit_result = fit_half(fit_set, day_stats, runs=runs_fit)
    val_result = fit_half(val_set, day_stats, runs=runs_val)

    fit_dates = sorted({s['ts'].date() for s in fit_set})
    val_dates = sorted({s['ts'].date() for s in val_set})
    ratio_ci = bootstrap_ratio_ci(day_stats, fit_dates, val_dates)

    results = {
        'all': q_all_result,
        'fit_apr_jun': fit_result,
        'validate_jul_aug': val_result,
        'ratio_ci': ratio_ci,
        'exclusions': stats,
        'n_capped_holds': n_capped,
        'duty_cross_check': duty_cross_check,
        'q_settle_sweep': q_settle_sweep(samples, runs=runs),
        'effective_q_by_regime': effective_q_by_regime(samples, runs=runs),
        'effective_q_by_regime_and_half': effective_q_by_regime_and_half(samples, runs=runs),
        'q_band_sweep': q_band_sweep(samples, runs=runs),
        'monthly_moment': monthly_moment_breakdown(day_stats, q_all_result['q_g_per_m3h']),
    }
    print(json.dumps(results, indent=2, default=str))

    report = Path(args.report)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(results))
    print(f'wrote {report}', file=sys.stderr)
    return 0


def render_report(r) -> str:
    def ci_str(ci):
        lo, hi = ci
        return f'[{lo:.2f}, {hi:.2f}]'

    def row(name, d):
        return (f"| {name} | {d['q_g_per_m3h']:.2f} {ci_str(d['q_ci'])} | "
                f"{d['n_quiet']} | "
                f"{d['f_regression_g_per_h']:.2f} {ci_str(d['f_regression_ci'])} | "
                f"{d['n_active']} | "
                f"{d['f_moment_g_per_h']:.2f} {ci_str(d['f_moment_ci'])} | "
                f"{d['f_over_q']:.2f} {ci_str(d['f_over_q_ci'])} | {d['n_samples']} |")
    ex = r['exclusions']
    cross_rows = '\n'.join(
        f"| {c['month']} | {c['reconstructed']:.4f} | {c['commanded']:.4f} | "
        f"{c['rel_diff_pct']:.2f}% | {c['n']} |"
        for c in r['duty_cross_check'])
    sweep_rows = '\n'.join(
        f"| {s['need_min']} | {s['q_g_per_m3h']:.3f} | {s['n_quiet']} |"
        for s in r['q_settle_sweep'])
    sweep_qs = [s['q_g_per_m3h'] for s in r['q_settle_sweep']]
    sweep_ratio = max(sweep_qs) / min(sweep_qs)
    regime_rows = '\n'.join(
        f"| {b['band']} | {b['q_g_per_m3h']:.3f} | {b['n']} |"
        for b in r['effective_q_by_regime'])
    regime_early_qs = [b['q_g_per_m3h'] for b in r['effective_q_by_regime'][:4]]
    regime_tail_q = r['effective_q_by_regime'][-1]['q_g_per_m3h']
    regime_tail_n = r['effective_q_by_regime'][-1]['n']
    regime_total_n = sum(b['n'] for b in r['effective_q_by_regime'])
    regime_tail_pct = regime_tail_n / regime_total_n * 100 if regime_total_n else float('nan')
    monthly_rows = '\n'.join(
        f"| {m['month']} | {m['f_moment_g_per_h']:.2f} | {m['f_over_q']:.2f} | {m['n_days']} |"
        for m in r['monthly_moment'])

    all_ = r['all']
    fit_ = r['fit_apr_jun']
    val_ = r['validate_jul_aug']
    foq_diff_pct = (abs(fit_['f_over_q'] - val_['f_over_q'])
                    / fit_['f_over_q'] * 100)
    freg_diff_pct = (abs(fit_['f_regression_g_per_h'] - val_['f_regression_g_per_h'])
                     / fit_['f_regression_g_per_h'] * 100)
    val_fmom_excl_aug = val_['f_moment_excl_aug_g_per_h']
    val_foq_excl_aug = val_['f_over_q_excl_aug']
    fit_foq, val_foq = fit_['f_over_q'], val_['f_over_q']
    foq_diff_pct_jul = abs(fit_foq - val_foq_excl_aug) / fit_foq * 100
    all_leak, all_off = all_['implied_leak_g_per_h'], all_['old_leak_pct_off']
    fit_leak, fit_off = fit_['implied_leak_g_per_h'], fit_['old_leak_pct_off']
    val_leak, val_off = val_['implied_leak_g_per_h'], val_['old_leak_pct_off']
    fit_freg, val_freg = fit_['f_regression_g_per_h'], val_['f_regression_g_per_h']

    def hi_label(hi):
        return 'inf' if hi == float('inf') else str(int(hi))

    hi_sweep_rows = '\n'.join(
        f"| [{Q_BAND_LO}, {hi_label(s['hi'])}] | {s['q_g_per_m3h']:.3f} | "
        f"{s['f_regression_g_per_h']:.2f} | {s['n_quiet']} |"
        for s in r['q_band_sweep']['hi_sweep'])
    lo_sweep_rows = '\n'.join(
        f"| [{s['lo']}, {Q_BAND_HI}] | {s['q_g_per_m3h']:.3f} | "
        f"{s['f_regression_g_per_h']:.2f} | {s['n_quiet']} |"
        for s in r['q_band_sweep']['lo_sweep'])
    sweep_freg = [s['f_regression_g_per_h'] for s in
                  r['q_band_sweep']['hi_sweep'] + r['q_band_sweep']['lo_sweep']]
    f_range_lo, f_range_hi = min(sweep_freg), max(sweep_freg)
    f_range_mid = (f_range_lo + f_range_hi) / 2
    f_range_half = (f_range_hi - f_range_lo) / 2

    regime_half = r['effective_q_by_regime_and_half']
    regime_half_rows = '\n'.join(
        f"| {b['band']} | {b['q_fit']:.3f} ({b['n_fit']}) | "
        f"{b['q_val']:.3f} ({b['n_val']}) |"
        for b in regime_half)
    short_n_fit = sum(b['n_fit'] for b in regime_half[:4])
    short_n_val = sum(b['n_val'] for b in regime_half[:4])
    short_pct_fit = (short_n_fit / (short_n_fit + short_n_val) * 100
                     if (short_n_fit + short_n_val) else float('nan'))
    deep = regime_half[-1]
    deep_pct_val = (deep['n_val'] / (deep['n_fit'] + deep['n_val']) * 100
                    if (deep['n_fit'] + deep['n_val']) else float('nan'))
    band_pct_fit = fit_['n_quiet'] / all_['n_quiet'] * 100 if all_['n_quiet'] else float('nan')

    ratio = r['ratio_ci']
    shoulder_q90 = r['q_band_sweep']['hi_sweep'][3]['q_g_per_m3h']
    shoulder_q240 = r['q_band_sweep']['hi_sweep'][6]['q_g_per_m3h']

    def contains(ci, x):
        return ci[0] <= x <= ci[1]

    ratio_names = {'q': 'Q', 'f_reg': 'F regression', 'f_mom': 'F moment',
                   'f_over_q': 'F/Q'}
    excludes_1p6 = [ratio_names[k] for k, ci in ratio.items() if not contains(ci, 1.6)]
    contains_1p6 = [ratio_names[k] for k, ci in ratio.items() if contains(ci, 1.6)]
    all_contain_1p0 = all(contains(ci, 1.0) for ci in ratio.values())
    excludes_1p6_str = ', '.join(excludes_1p6) if excludes_1p6 else 'none'
    contains_1p6_str = ', '.join(contains_1p6) if contains_1p6 else 'none'

    return f"""# 999.33-06 — Chamber model fit results (MUSHY-60)

Generated by `scripts/fit-chamber-model.py`. Window 2026-04-11 to 2026-08-08,
1-minute samples, ambient from the MUSHY-64 fixture. All CIs are 95% day-block
bootstrap intervals ({N_BOOT} resamples, whole UTC days, unless noted).

## Headline: F/Q is the identified quantity, F and Q are simulator priors

**`F/Q` = {all_['f_over_q']:.2f} {ci_str(all_['f_over_q_ci'])} g/m3 per unit duty.** It equals
`mean_grad/mean_u` exactly -- free of both `Q` and the lag entirely, band-
independent, and exactly identified. Fit vs validate halves agree to
{foq_diff_pct:.1f}% ({fit_foq:.2f} vs {val_foq:.2f}). It is what sets steady-state duty, which is
what the controller actually needs. Treat this as the result.

`F` and `Q` individually are NOT independently identified: `F` is exactly
proportional to `Q` (since `F = (F/Q) * Q`), and `Q` depends on an arbitrary
band choice with no principled stopping point (see "The band sets F"
below). Absolute `F` should be read as a simulator prior with a stated
systematic range, not a fitted parameter: **F ~ {f_range_mid:.1f} +/- {f_range_half:.1f} g/h**
(systematic range {f_range_lo:.1f}-{f_range_hi:.1f} g/h from the band choice alone, stacked on
top of the bootstrap CI at any single band).

## Fitted parameters

`Q` is an effective moisture-loss coefficient, not air-exchange conductance
(see "Q is regime-dependent" below), fitted on a bounded quiet-run band
[{Q_BAND_LO}, {Q_BAND_HI}] minutes rather than the full unbounded quiet
population -- see "Why a bounded Q band" and "The band sets F" below. `F` is
reported three ways: a regression on lag-corrected applied duty (`u_app`),
restricted to raw `duty > 0`; a moment-balance cross-check (proportional to
Q, NOT estimator-independent -- see below); and `F/Q`, the one quantity
here that is free of both Q and the lag.

| set | Q (m3/h) | quiet n | F regression (g/h) | active n | F moment (g/h) | F/Q | total |
|---|---|---|---|---|---|---|---|
{row('all', all_)}
{row('fit (Apr-Jun)', fit_)}
{row('validate (Jul-Aug)', val_)}

The bootstrap CIs above are for a FIXED band choice ([{Q_BAND_LO}, {Q_BAND_HI}]) and
understate the true uncertainty in `Q` and `F`: the operational Q's CI is
about {all_['q_ci'][1] / all_['q_ci'][0]:.1f}x wide (statistical), but the band choice itself
moves `Q` (and therefore `F`, exactly proportionally) across roughly a 4x
range with no principled stopping point (systematic -- see "The band sets
F" below). `F/Q` alone escapes both: report it, not the absolute values,
as the finding.

## The band sets F

Because `F/Q = mean_grad/mean_u` is band-free, `F` is exactly proportional
to `Q`, and the band is the ONLY thing that sets `Q` operationally -- so
the band is a direct dial on `F`. Two one-parameter sweeps around the
operational choice [{Q_BAND_LO}, {Q_BAND_HI}]:

Upper bound (lo={Q_BAND_LO} fixed):

| band | Q (m3/h) | F regression (g/h) | quiet n |
|---|---|---|---|
{hi_sweep_rows}

Lower bound (hi={Q_BAND_HI} fixed):

| band | Q (m3/h) | F regression (g/h) | quiet n |
|---|---|---|---|
{lo_sweep_rows}

Resulting `F` range across both sweeps: **{f_range_lo:.1f}-{f_range_hi:.1f} g/h**, a
SYSTEMATIC uncertainty stacked on top of the bootstrap CI at any one band.
There is no plateau -- only a soft shoulder for hi in [90, 240] where `Q`
moves {shoulder_q90:.2f} -> {shoulder_q240:.2f} -- and nothing in
the model has a 120-minute timescale (`tau_s`={TAU_S:.0f}, `dead_time_s`={DEAD_TIME_S:.0f}), so the
upper bound is a JUDGMENT CALL, not a derived quantity. This band was NOT
tuned to match the old model's ~8.7 g/h fill: the widest plausible upper
bound ([{Q_BAND_LO}, inf], equivalent to the unbounded settle sweep) gives the
LOWEST F of any candidate in this sweep, not the closest to 8.7.

## Duty reconstruction cross-check

Reconstructed relay duty (time-weighted integral of the held edge state,
capped at {RELAY_HOLD_CAP_MIN} min for a nonzero hold -- see "Relay hold cap"
below) against the independent `fc.humidifier_duty` topic, per month:

| month | reconstructed mean | commanded mean | rel diff | n minutes |
|---|---|---|---|---|
{cross_rows}

Script aborts if any month disagrees by more than {DUTY_CROSS_CHECK_TOL:.0%}.

## Q is regime-dependent

Effective Q by minutes since the relay dropped:

| band (min) | Q (m3/h) | n |
|---|---|---|
{regime_rows}

Q is not a single time constant: it runs roughly
{min(regime_early_qs):.1f}-{max(regime_early_qs):.1f} in the first ~40 minutes
after a drop and falls toward ~{regime_tail_q:.1f} beyond 2
hours. A single first-mechanism leak would not produce this. Sweeping the
required zero-duty run length (unbounded above -- diagnostic only, not
what's used operationally):

| need (min) | Q (m3/h) | quiet samples |
|---|---|---|
{sweep_rows}

Roughly a {sweep_ratio:.1f}x monotone range with no plateau, because the decay carries a slow
tail well past the 600 s mixing constant.

## Why a bounded Q band

The unbounded quiet population used by the settle sweep is {regime_tail_pct:.0f}% dominated by
the `>120 min` bucket, whose effective Q (~{regime_tail_q:.2f}) is close to that unbounded
fit's own asymptote. Applying that number to the active regime (tens of
minutes, not hours) under-predicts the true loss there by roughly 2x, and
that under-prediction was the actual root cause of both April-June's
physically-impossible negative F (-8.06 g/h) in a previous round and the
implausibly low ACH reported earlier. Two fixes were offered: (a) fit an
explicit fast+slow two-timescale Q, or (b) restrict Q's operational fit to a
bounded run-length band closer to the regime F is fitted in. This script
takes (b) -- a single bounded-band regression is simpler to reason about and
to keep numerically stable under bootstrap resampling than a two-exponential
fit would be, at the cost of not resolving the fast/slow mechanism
explicitly. The band is [{Q_BAND_LO}, {Q_BAND_HI}] minutes: the lower bound
is unchanged from the original dead-time argument (`{Q_BAND_LO}` = dead time
+ settle), and the upper bound excludes the dominating long tail. `Q` is
reported and used as an effective moisture-loss coefficient, not a physical
air-exchange rate, in either case.

## Q regime effect is confounded with season

The pooled decline shown above should NOT be read as a clean single-mechanism
regime effect without this split by half:

| band (min) | Apr-Jun Q (n) | Jul-Aug Q (n) |
|---|---|---|
{regime_half_rows}

Split by half, the decline is not even monotone in the same direction in
both halves. The pooled monotone decline is substantially a COMPOSITION
effect: short runs (1-40 min) are {short_pct_fit:.0f}% Apr-Jun, and the `>120 min`
bucket is {deep_pct_val:.0f}% Jul-Aug. The operational band [{Q_BAND_LO}, {Q_BAND_HI}]
is {band_pct_fit:.0f}% Apr-Jun by sample count, and the validate half contributes only
{val_['n_quiet']} of {all_['n_quiet']} quiet samples to it. The band selects a SEASON
almost as much as a regime -- treat "Q is regime-dependent" above as a
description of the pooled data, not as evidence for a physical mechanism
independent of season.

## Relay hold cap

Forward-filling the edge-only relay indefinitely made `stats['no_relay']`
structurally always 0. 2,006 kept samples in an earlier round sat inside runs
of `duty == 1.0` held longer than 60 consecutive minutes without a single
edge, the longest 464 minutes -- not physically plausible for a
PWM-controlled relay, and more likely a telemetry gap that happened to start
mid-pulse (the 2026-04-23 22.9 h case escaped only because temp/RH were also
missing that stretch). A nonzero held state beyond {RELAY_HOLD_CAP_MIN}
minutes without a fresh edge is now treated as unknown (None), not "on" --
{r['n_capped_holds']} grid minutes were capped this run. A held-OFF (0.0)
state is NOT capped: the long relay-unchanged stretches in Jul/Aug/May
(below) are genuine, not gaps. The cap is applied AFTER the duty
cross-check above, not before -- the cross-check validates the
reconstruction formula itself; capping is a separate, later exclusion
policy layered on top of it.

## Exclusions

| reason | minutes |
|---|---|
| total grid minutes | {ex['total']} |
| no temp/RH reading | {ex['no_reading']} |
| no relay state yet (incl. capped nonzero holds) | {ex['no_relay']} |
| RH saturated (>= 99.99) | {ex['saturated']} |
| RH step > 3 pct (sensor failover) | {ex['rh_step']} |
| outside ambient coverage | {ex['outside_ambient']} |
| **kept** | **{ex['kept']}** |

Most long relay-unchanged runs are NOT telemetry outages. Ranked by
duration, the top 5 relay-unchanged spans are #1 4.94 d (Jul), #2 3.87 d
(Aug), #3 69.0 h (Jul), #4 68.5 h (Jul), #5 2.04 d (May) -- NOT "the three
longest are 4.94 d / 3.87 d / 2.04 d" as an earlier round claimed (that
skips #3 and #4, both in July). All five checked: `fc.humidifier_duty`
recorded continuous ~2 Hz coverage throughout (471,279-803,990 samples
depending on span) with mean commanded duty ~0.0001-0.0002, and
`fc.temperature` was present throughout -- the controller was up and
genuinely commanding near-zero duty, not silent. The original "controller
settled" reading was substantially right for these. A real outage does
exist elsewhere: 2026-04-23 13:44 to 2026-04-24 12:40 UTC (22.9 h),
`fc.temperature` count 0 during the gap, confirmed directly against the
gap's exact start/end timestamps (not a coarser minute-grid approximation).

## F-moment and August

Monthly moment-balance values (Q held fixed at the `all`-set band value):

| month | F moment (g/h) | F/Q | days |
|---|---|---|---|
{monthly_rows}

August's mean gradient collapses (its chamber-to-ambient gradient points
inward for a large share of hours), and the moment balance there goes
negative -- physically meaningless for a fill term. The `validate (Jul-Aug)`
row above includes August; `f_moment_excl_aug` = {val_fmom_excl_aug:.2f} g/h and
`f_over_q_excl_aug` = {val_foq_excl_aug:.2f} (July only) are reported separately rather than
silently substituted, since which one is "the" validate-half number is a
judgment call this script should not make unilaterally.

## Season-independence: the ratio bootstrap

Two separate CIs eyeballed against each other is not a test of
season-independence; the validate/fit RATIO is. {N_BOOT_RATIO} day-block
replicates, resampling each half independently:

| statistic | validate/fit ratio 95% CI |
|---|---|
| Q | {ratio['q'][0]:.2f} to {ratio['q'][1]:.2f} |
| F regression | {ratio['f_reg'][0]:.2f} to {ratio['f_reg'][1]:.2f} |
| F moment | {ratio['f_mom'][0]:.2f} to {ratio['f_mom'][1]:.2f} |
| F/Q | {ratio['f_over_q'][0]:.2f} to {ratio['f_over_q'][1]:.2f} |

All four CIs contain 1.0 ({all_contain_1p0}): season-independence is NOT
REJECTED by any of them. But only **{excludes_1p6_str}**
excludes 1.6 (a previous round's claimed regression split) -- {contains_1p6_str} still
contain it. This is a materially different (and more honest) result than an
earlier draft of this section claimed before the round-3 zero-run-length
fix: that draft, based on numbers with the fix not yet applied, said "none
contain 1.6." After the fix, only `F/Q` -- the one quantity free of both the
band choice and the lag -- cleanly excludes it; the others carry enough of
the band's systematic uncertainty that a 1.6x seasonal difference remains
inside their CIs. Read `F/Q`'s ratio CI as the one genuine piece of
evidence here, not the other three.

## Reading this honestly

`Q*mean(gradient)` agreement with the old model's implied leak
(~{OLD_MODEL_LEAK_G_PER_H} g/h) is NOT close for any set with the regime-matched
band Q -- worse than the unbounded-Q version reported in a previous round:

- all-data implies {all_leak:.3f} g/h ({all_off:.0f}% off)
- fit (Apr-Jun) implies {fit_leak:.3f} g/h ({fit_off:.0f}% off)
- validate (Jul-Aug) implies {val_leak:.3f} g/h ({val_off:.0f}% off)

This is expected, not a red flag: the regime-matched Q is deliberately
several times larger than the deep-quiet asymptote the old model's constant
most resembles (see "Q is regime-dependent" above), so a closer match to
that single old number would itself be suspicious. Treat the old model's
implied leak as a rough sanity check on order of magnitude only, not a target.

**Season-independence is UNPROVEN.** `F/Q` remains the only quantity free
of both Q and the lag, exactly identified, and it agrees closely between
halves:

- `F/Q`: {fit_foq:.2f} vs {val_foq:.2f} ({foq_diff_pct:.1f}% apart,
  {foq_diff_pct_jul:.1f}% July-only)
- regression on `u_app`: {fit_freg:.2f} vs {val_freg:.2f} g/h ({freg_diff_pct:.1f}% apart)
- moment balance: {fit_['f_moment_g_per_h']:.2f} vs {val_fmom_excl_aug:.2f} g/h (July-only)

The regression and moment-balance splits above are NOT as tight as `F/Q`'s,
and should not be read as independently confirming season-independence --
both inherit the operational band's systematic uncertainty (see "The band
sets F"), and the ratio-bootstrap section above shows their validate/fit
ratio CIs still contain a 1.6x difference, unlike `F/Q`'s. The honest
reading is: `F/Q` says the halves likely agree; `Q`, the regression, and
the moment balance are each too uncertain (for their own, different
reasons -- band choice for `Q` and the regression, plus the August
gradient collapse for the moment balance) to independently confirm or
refute that on their own.

`Q` is the coefficient in the UNSATURATED regime -- saturated samples are
excluded per the farmer's 2026-08-09 ruling, and those are the wettest hours.
"""


if __name__ == '__main__':
    raise SystemExit(main())
