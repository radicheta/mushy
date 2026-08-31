"""MUSHY-150: build the bake-off corpus once and cache it.

Produces day-aligned tensors on a 10 s grid for every usable day in
2026-04-11..2026-08-31, plus the split masks and the farmer-entry mask.
Every candidate is scored on exactly this, so the comparison cannot be
confounded by differences in data handling.

Day boundary is LOCAL midnight (UYT, UTC-3) so a rollout spans one whole
diurnal cycle rather than straddling two.

    .venv/bin/python scripts/bakeoff/prep.py
"""
import subprocess, sys, os
from datetime import datetime, timezone, timedelta
import numpy as np

sys.path.insert(0, 'src/chambers/fc-core')
from fc_core.sim.psychrometrics import absolute_humidity_g_m3

DT = 10.0
STEPS = int(86400 / DT)                     # 8640
UYT = timezone(timedelta(hours=-3))
START, END = '2026-04-11', '2026-09-01'
PIPE_TRANSIT_S = 6.0                        # farmer-measured 5-7 s (pwm_window.py)
OUT = 'scripts/bakeoff/corpus.npz'
MAX_MISSING = 0.20                          # drop a day with more gap than this


def q(sql):
    out = subprocess.run(
        ['docker', 'exec', 'mushy-timescale-1', 'psql', '-U', 'postgres', '-d', 'postgres',
         '-At', '-F', '\t', '-c', 'SET max_parallel_workers_per_gather=0; ' + sql],
        capture_output=True, text=True, check=True).stdout
    rows = [l.split('\t') for l in out.splitlines() if l.strip()]
    if not rows:
        return np.zeros(0), np.zeros(0)
    a = np.array(rows, dtype=float)
    return a[:, 0], a[:, 1]


def series(topic, table='telemetry'):
    return q(f"select extract(epoch from time), value from {table} "
             f"where topic='{topic}' and time >= '{START}' and time < '{END}' order by time")


def zoh(t, v, grid, default):
    """zero-order hold: value in force at each grid instant."""
    if len(t) == 0:
        return np.full(len(grid), default)
    i = np.searchsorted(t, grid, side='right') - 1
    out = np.where(i < 0, default, v[np.clip(i, 0, None)])
    return out


def interp_gap(t, v, grid, max_gap_s):
    """linear interpolation, but NaN wherever the nearest samples straddle a
    gap longer than max_gap_s -- so a sensor outage reads as missing rather
    than as a straight line drawn through it."""
    if len(t) == 0:
        return np.full(len(grid), np.nan)
    out = np.interp(grid, t, v, left=np.nan, right=np.nan)
    i = np.clip(np.searchsorted(t, grid), 1, len(t) - 1)
    out[(t[i] - t[i - 1]) > max_gap_s] = np.nan
    out[(grid < t[0]) | (grid > t[-1])] = np.nan
    return out


def delivered_duty(t_relay, v_relay, grid):
    """Relay state -> duty actually leaving the outlet, at 1 s then binned to
    the grid. The first PIPE_TRANSIT_S of every pulse delivers nothing
    (MUSHY-116): a train of short pulses delivers far less than its nominal
    duty, which is why commanded duty must never be used here."""
    if len(t_relay) == 0:
        return np.zeros(len(grid))
    s0, s1 = int(grid[0]), int(grid[-1] + DT)
    sec = np.arange(s0, s1, 1.0)
    on = zoh(t_relay, v_relay, sec, 0.0) > 0.5
    # elapsed seconds since this pulse began; 0 while off
    idx = np.arange(len(on))
    starts = np.where(on & ~np.concatenate([[False], on[:-1]]))[0]
    elapsed = np.zeros(len(on))
    if len(starts):
        j = np.searchsorted(starts, idx, side='right') - 1
        elapsed = np.where(on & (j >= 0), idx - starts[np.clip(j, 0, None)], 0.0)
    delivered = np.where(on & (elapsed >= PIPE_TRANSIT_S), 1.0, 0.0)
    # bin 1 s -> DT s
    k = int(DT)
    n = (len(delivered) // k) * k
    return delivered[:n].reshape(-1, k).mean(axis=1)[:len(grid)]


def entry_mask(grid):
    """Farmer-entry windows, from CO2 excursions >= ENTRY_PPM above a local
    rolling median. See the MUSHY-150 comment of 2026-08-31: a k*MAD rule
    fires overwhelmingly on sensor noise (MAD is only 1.4 ppm), and only
    excursions >= 60 ppm carry a working-hours signature. Absolute threshold
    over a LOCAL baseline, because ASC re-baselines the sensor continuously
    (MUSHY-114) and any fixed ppm cut drifts out from under you."""
    # Farmer's rule (2026-08-31): a flat 30 min per entry, 5 min before the
    # excursion starts to 25 min after. Anchored on ONSET, not on the peak --
    # CO2 peaks near the END of a visit, so peak-anchoring would miss the
    # entry itself, which is the part the "5 min before" is there to catch.
    ENTRY_PPM, HALF_W, PRE_MIN, POST_MIN = 60.0, 30, 5, 25
    t, v = series('fc.co2')
    if len(t) == 0:
        return np.zeros(len(grid), bool), 0
    m0 = int(t[0] // 60)
    n = int(t[-1] // 60) - m0 + 1
    minute = np.full(n, np.nan)
    minute[(t // 60 - m0).astype(int)] = v          # last sample in each minute
    pad = HALF_W
    xp = np.concatenate([np.full(pad, np.nan), minute, np.full(pad, np.nan)])
    base = np.nanmedian(np.lib.stride_tricks.sliding_window_view(xp, 2 * pad + 1), axis=1)
    resid = minute - base
    hit = np.where(np.nan_to_num(resid, nan=-1e9) > 3 * 1.4826 * np.nanmedian(np.abs(resid)))[0]
    mask = np.zeros(len(grid), bool)
    n_ev = 0
    long_tails = []
    if len(hit):
        for grp in np.split(hit, np.where(np.diff(hit) > 20)[0] + 1):
            if resid[grp].max() < ENTRY_PPM:
                continue
            n_ev += 1
            a = (m0 + grp[0] - PRE_MIN) * 60.0
            b = (m0 + grp[0] + POST_MIN) * 60.0
            over = max(0, (grp[-1] - grp[0]) - POST_MIN)
            if over:
                long_tails.append(over)
            mask |= (grid >= a) & (grid <= b)
    if long_tails:
        print(f'  NOTE {len(long_tails)}/{n_ev} entries stay above threshold past '
              f'+{POST_MIN} min (worst +{max(long_tails)} min) and are only '
              f'partly masked by the flat window')
    return mask, n_ev


def main():
    print('querying...')
    t_rh, v_rh = series('fc.humidity')
    t_tp, v_tp = series('fc.temperature')
    t_rl, v_rl = series('fc.humidifier')
    t_wt, v_wt = series('weather.temperature', 'weather')
    t_wh, v_wh = series('weather.humidity', 'weather')
    t_wp, v_wp = series('weather.precipitation', 'weather')
    print(f'  rh {len(t_rh)}  temp {len(t_tp)}  relay {len(t_rl)}  weather {len(t_wt)}')

    d0 = datetime.fromisoformat(START).replace(tzinfo=UYT)
    d1 = datetime.fromisoformat(END).replace(tzinfo=UYT)
    n_days = (d1 - d0).days
    base = np.arange(STEPS) * DT

    # ambient absolute humidity, hourly -> interpolated
    wh = dict(zip(t_wh, v_wh))
    pairs = [(ts, tc, wh[ts]) for ts, tc in zip(t_wt, v_wt) if ts in wh]
    common = np.array([p[0] for p in pairs])
    amb_ah = np.array([absolute_humidity_g_m3(p[1], p[2]) for p in pairs])

    grid_all = np.concatenate([d0.timestamp() + i * 86400 + base for i in range(n_days)])
    mask_entry_all, n_ev = entry_mask(grid_all)
    print(f'  farmer-entry events >=60 ppm: {n_ev}, masking {mask_entry_all.mean():.2%} of the grid')

    RH = interp_gap(t_rh, v_rh, grid_all, 300)
    TP = interp_gap(t_tp, v_tp, grid_all, 300)
    AMB = interp_gap(common, amb_ah, grid_all, 7200)
    AMBT = interp_gap(t_wt, v_wt, grid_all, 7200)
    PRECIP = zoh(t_wp, v_wp, grid_all, 0.0)
    DUTY = delivered_duty(t_rl, v_rl, grid_all)

    AH = np.full(len(grid_all), np.nan)
    ok = np.isfinite(RH) & np.isfinite(TP)
    AH[ok] = [absolute_humidity_g_m3(a, b) for a, b in zip(TP[ok], RH[ok])]

    def days(x):
        return x.reshape(n_days, STEPS)

    RHd, TPd, AMBd, DUTYd, AHd = days(RH), days(TP), days(AMB), days(DUTY), days(AH)
    AMBTd, PRECIPd = days(AMBT), days(PRECIP)
    ENTd = days(mask_entry_all)
    valid = (np.isfinite(RHd) & np.isfinite(TPd) & np.isfinite(AMBd)
             & np.isfinite(AHd) & np.isfinite(AMBTd))
    keep = (~valid).mean(axis=1) <= MAX_MISSING
    # a day is only usable if its FIRST sample is real -- the rollout
    # initialises from it
    keep &= valid[:, 0]
    print(f'  usable days {keep.sum()} / {n_days}')

    dates = np.array([(d0 + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(n_days)])
    idx = np.where(keep)[0]
    months = np.array([int(dates[i][5:7]) for i in idx])
    dom = np.array([int(dates[i][8:10]) for i in idx])

    # chronological split: fit 04-06, score 07-08
    chrono_train = months <= 6
    # interleaved: 3 weeks train / 1 week test per month, held-out week
    # ROTATES by month so it cannot alias with anything monthly-periodic
    week = np.minimum((dom - 1) // 7, 3)
    test_week = (months - 4) % 4
    inter_train = week != test_week

    np.savez_compressed(
        OUT,
        dates=dates[idx], month=months,
        rh=np.nan_to_num(RHd[idx]), temp=np.nan_to_num(TPd[idx]),
        amb_ah=np.nan_to_num(AMBd[idx]), duty=DUTYd[idx], ah=np.nan_to_num(AHd[idx]),
        amb_temp=np.nan_to_num(AMBTd[idx]), precip=PRECIPd[idx],
        valid=valid[idx] & ~ENTd[idx],
        chrono_train=chrono_train, inter_train=inter_train, dt=DT)
    sz = os.path.getsize(OUT) / 1e6
    print(f'wrote {OUT} ({sz:.1f} MB): {len(idx)} days x {STEPS} steps')
    print(f'  chronological  train {chrono_train.sum():3d}  test {(~chrono_train).sum():3d}')
    print(f'  interleaved    train {inter_train.sum():3d}  test {(~inter_train).sum():3d}')
    print(f'  scored samples dropped by masks: {1 - (valid[idx] & ~ENTd[idx]).mean():.2%}')


if __name__ == '__main__':
    main()
