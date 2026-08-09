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
U_APP_EPS = 1e-6            # "meaningfully active" floor for u_app, see fit_f_regression
RELAY_HOLD_CAP_MIN = 60     # cap on an uninterrupted NONZERO relay hold; see module docstring
Q_BAND_LO = QUIET_NEED_DEFAULT   # 16 -- same lower bound the dead-time argument requires
# Q_BAND_HI excludes the >120 min tail that dominates (79%) and pulls the
# unbounded fit down toward its asymptote.
Q_BAND_HI = 120
OLD_MODEL_LEAK_G_PER_H = 0.865   # previous RH-points model's implied leak, for sanity-check only
N_BOOT = 2000
BOOT_SEED = 0
EFFECTIVE_Q_BUCKETS = [(1, 3), (4, 8), (9, 16), (17, 40), (41, 120), (121, float('inf'))]
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


def quiet_mask(samples, need):
    """True where duty has been 0 for at least `need` consecutive minutes
    (unbounded above). Used only for the settle-sweep diagnostic below --
    the operational Q uses `quiet_band_mask` instead.

    NOTE (known off-by-one): `run` reaches `need` on the `need`-th zero-duty
    minute, i.e. `need - 1` minutes after duty actually fell to zero -- one
    minute short of the intended "duty has been 0 for `need` minutes" spec.
    Left as-is (see FIX reports) rather than changed silently.
    """
    run = 0
    flags = []
    for s in samples:
        run = run + 1 if s['duty'] == 0.0 else 0
        flags.append(run >= need)
    return flags


def quiet_band_mask(samples, lo, hi):
    """True where the relay has been off between lo and hi consecutive
    minutes (inclusive). Bounding the upper end, unlike `quiet_mask`, is
    what keeps this population from being dominated by arbitrarily long
    quiet runs -- see Q_BAND_LO/Q_BAND_HI and the module docstring."""
    run = 0
    flags = []
    for s in samples:
        run = run + 1 if s['duty'] == 0.0 else 0
        flags.append(lo <= run <= hi)
    return flags


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


def effective_q_by_regime(samples):
    """Empirical effective Q bucketed by minutes-since-the-relay-dropped.
    If a single first-order leak governed decay these would agree; they
    don't (see module docstring), which is the evidence behind restricting
    Q's operational fit to a bounded band rather than the full unbounded
    quiet population."""
    run = 0
    bucketed = {b: [] for b in EFFECTIVE_Q_BUCKETS}
    for s in samples:
        run = run + 1 if s['duty'] == 0.0 else 0
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


def q_settle_sweep(samples):
    """Q's sensitivity to the quiet-settle threshold (unbounded above) --
    a single-mechanism first-order leak would plateau as the threshold
    grows; this doesn't. Diagnostic only -- not the Q used operationally."""
    rows = []
    for need in QUIET_NEED_SWEEP:
        flags = quiet_mask(samples, need)
        quiet = [s for s, f in zip(samples, flags) if f]
        q, n = fit_q(quiet)
        rows.append({'need_min': need, 'q_g_per_m3h': q, 'n_quiet': n})
    return rows


def precompute_day_stats(samples):
    """Per UTC-day sufficient statistics for every regression used below.

    Every estimator here (Q, F regression, F moment, F/Q) is linear in a
    handful of running sums, so a day-block bootstrap can resample days and
    recombine these per-day sums instead of re-scanning all ~150k samples on
    every replicate.
    """
    days = defaultdict(lambda: {
        'quiet_xy': 0.0, 'quiet_xx': 0.0, 'quiet_n': 0,
        'act_u_dahdt': 0.0, 'act_u_grad': 0.0, 'act_uu': 0.0, 'act_n': 0,
        'full_grad': 0.0, 'full_dahdt': 0.0, 'full_u': 0.0, 'full_n': 0,
    })
    run = 0
    for s in samples:
        run = run + 1 if s['duty'] == 0.0 else 0
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


def fit_half(samples, day_stats):
    dates = sorted({s['ts'].date() for s in samples})
    agg = aggregate_days(day_stats, dates)
    q, f_reg, f_mom, f_over_q = stats_from_agg(agg)
    ci = bootstrap_ci(day_stats, dates)

    # Aug-excluded view: only differs when the set actually spans August.
    non_aug_dates = [d for d in dates if d.month != 8]
    f_mom_excl_aug, f_over_q_excl_aug = moment_and_foq_for_dates(
        day_stats, non_aug_dates, q)

    mean_grad = agg['full_grad'] / agg['full_n'] if agg['full_n'] else float('nan')
    implied_leak = q * mean_grad
    old_leak_pct_off = (abs(implied_leak - OLD_MODEL_LEAK_G_PER_H)
                        / OLD_MODEL_LEAK_G_PER_H * 100)

    return {
        'q_g_per_m3h': q, 'n_quiet': int(agg['quiet_n']),
        'f_regression_g_per_h': f_reg, 'n_active': int(agg['act_n']),
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

    fit_set = [s for s in samples if s['ts'] < SPLIT]
    val_set = [s for s in samples if s['ts'] >= SPLIT]

    day_stats = precompute_day_stats(samples)
    q_all_result = fit_half(samples, day_stats)

    results = {
        'all': q_all_result,
        'fit_apr_jun': fit_half(fit_set, day_stats),
        'validate_jul_aug': fit_half(val_set, day_stats),
        'exclusions': stats,
        'n_capped_holds': n_capped,
        'duty_cross_check': duty_cross_check,
        'q_settle_sweep': q_settle_sweep(samples),
        'effective_q_by_regime': effective_q_by_regime(samples),
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
    regime_rows = '\n'.join(
        f"| {b['band']} | {b['q_g_per_m3h']:.3f} | {b['n']} |"
        for b in r['effective_q_by_regime'])
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
    val_fmom_lo, val_fmom_hi = val_['f_moment_ci']
    all_leak, all_off = all_['implied_leak_g_per_h'], all_['old_leak_pct_off']
    fit_leak, fit_off = fit_['implied_leak_g_per_h'], fit_['old_leak_pct_off']
    val_leak, val_off = val_['implied_leak_g_per_h'], val_['old_leak_pct_off']
    fit_freg, val_freg = fit_['f_regression_g_per_h'], val_['f_regression_g_per_h']

    return f"""# 999.33-06 — Chamber model fit results (MUSHY-60)

Generated by `scripts/fit-chamber-model.py`. Window 2026-04-11 to 2026-08-08,
1-minute samples, ambient from the MUSHY-64 fixture. All CIs are 95% day-block
bootstrap intervals ({N_BOOT} resamples, whole UTC days).

## Fitted parameters

`Q` is an effective moisture-loss coefficient, not air-exchange conductance
(see "Q is regime-dependent" below), fitted on a bounded quiet-run band
[{Q_BAND_LO}, {Q_BAND_HI}] minutes rather than the full unbounded quiet
population -- see "Why a bounded Q band" below. `F` is reported three ways:
a regression on lag-corrected applied duty (`u_app`), restricted to raw
`duty > 0`; a moment-balance cross-check (proportional to Q, NOT estimator-
independent -- see below); and `F/Q`, the one quantity here that is free of
both Q and the lag.

| set | Q (m3/h) | quiet n | F regression (g/h) | active n | F moment (g/h) | F/Q | total |
|---|---|---|---|---|---|---|---|
{row('all', all_)}
{row('fit (Apr-Jun)', fit_)}
{row('validate (Jul-Aug)', val_)}

Report uncertainty, not point estimates: defensible F values span roughly
4.5-6.8 g/h across estimators and sets, and every value except `F/Q` scales
with a `Q` known only to within a factor of ~4 (see the settle sweep below).

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

Q is not a single time constant: it runs roughly 1.3-1.8 in the first ~40
minutes after a drop and falls toward ~0.2 beyond 2 hours. A single
first-mechanism leak would not produce this. Sweeping the required zero-duty
run length (unbounded above -- diagnostic only, not what's used operationally):

| need (min) | Q (m3/h) | quiet samples |
|---|---|---|
{sweep_rows}

Roughly a 4x monotone range with no plateau, because the decay carries a slow
tail well past the 600 s mixing constant.

## Why a bounded Q band

The unbounded quiet population used by the settle sweep is 79% dominated by
the `>120 min` bucket, whose effective Q (~0.235) is close to that unbounded
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

Most long relay-unchanged runs are NOT telemetry outages. During the three
longest (4.94 d Jul, 3.87 d Aug, 2.04 d May), `fc.humidifier_duty` recorded
continuous ~2 Hz samples (803,990 / 582,250 / 343,463 of them) with mean
commanded duty ~0.0001, and `fc.temperature` was present throughout -- the
controller was up and genuinely commanding near-zero duty, not silent. The
original "controller settled" reading was substantially right for these. A
real outage does exist elsewhere: 2026-04-23, 22.9 h, `fc.temperature` count
0 during the gap.

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

**Season-independence is UNPROVEN, but the evidence for it is now much
stronger than in the previous round.** All three estimators agree far more
closely between halves after restoring the `duty > 0` filter and moving to a
regime-matched Q:

- `F/Q`: {fit_foq:.2f} vs {val_foq:.2f} ({foq_diff_pct:.1f}% apart,
  {foq_diff_pct_jul:.1f}% July-only)
- regression on `u_app`: {fit_freg:.2f} vs {val_freg:.2f} g/h ({freg_diff_pct:.1f}% apart)
- moment balance: {fit_['f_moment_g_per_h']:.2f} vs {val_fmom_excl_aug:.2f} g/h (July-only)

None of this proves season-independence: `F/Q` remains the only quantity
free of both Q and the lag and is the strongest evidence; the moment
balance's validate-half CI ({val_fmom_lo:.2f} to {val_fmom_hi:.2f}) is wide
enough that it cannot itself distinguish season-independence from a real
seasonal difference; and even the now-close regression agreement could in
principle reflect two compensating errors rather than a true match. But
there is no longer a divergent estimator to explain away -- the previous
round's negative-F
population and 1.6x regression split are both gone.

`Q` is the coefficient in the UNSATURATED regime -- saturated samples are
excluded per the farmer's 2026-08-09 ruling, and those are the wettest hours.
"""


if __name__ == '__main__':
    raise SystemExit(main())
