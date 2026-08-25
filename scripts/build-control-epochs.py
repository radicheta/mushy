#!/usr/bin/env python3
"""Reconstruct WHAT THE CONTROLLER WAS ACTUALLY RUNNING, epoch by epoch (MUSHY-58).

Later replay steps need to know the control law and its effective parameters at
any given moment in 2026-05-01..now. Neither source can answer that alone:

  * git knows the law and the declared config, but a commit is when it was
    PUSHED, not when fc1 ran it -- and it cannot see a runtime ``set_mode`` or a
    live ``ros2 param set`` at all;
  * telemetry knows what the running controller published, but not which code
    produced it.

So this merges both, and -- importantly -- says which source each field came
from and how confident it is. Where the two cannot pin something down, the row
says so and we move on; a low-confidence epoch is more useful than a confident
guess.

=== The two sources ===

GIT: ``origin/fc1/prod`` (the DEPLOYED branch -- ``main`` runs ~256 commits
ahead and is not what the chamber ran). Every commit touching CONTROL_PATHS
opens a candidate epoch; ``fc_config.yaml`` is parsed at that commit for the
declared parameters (parsed, never transcribed -- see ``parse_config``).

TELEMETRY: ``fc.humidity_target``, per-minute. This is the EFFECTIVE SETPOINT,
not the control band (see ``replay-control-law.py``'s header for the full
derivation). Two things are readable from it:

  * force modes -- ``force-condensation`` publishes target 1.0 and
    ``force-evaporation`` publishes 0.0, both far outside any fruiting band.
    These are runtime ``set_mode`` calls, invisible to git, and they ran for
    parts of three weeks in June (and the pinning cycler drives more).
  * controller restarts -- on boot the setpoint starts at the NOMINAL
    ``target_humidity`` parameter and ramps toward the nearest band edge, so a
    restart shows as a brief excursion above ``band_high``.

``fc.pid_output`` (pre-bias) vs ``fc.humidifier_duty`` (post-bias) gives the
effective duty bias per epoch.

=== The restart anchor, and where it stops working ===

An epoch's real start is the first controller restart at-or-after its commit,
not the commit itself. But the ramp that makes a restart visible only exists
when the nominal target sits OUTSIDE the band, and before 2026-06-27 it did
not: nominal was 0.96 with band [0.945, 0.975], so boot landed in-band and
published no transient. From 814e3652 (2026-06-27) the band moved to
[0.885, 0.915] while nominal stayed 0.96, and the ramp became visible (first
tick 0.96 - (0.96-0.915)/30 = 0.9585, the value that shows up in the data from
that week onward).

Consequence, stated rather than hidden: epochs before 2026-06-27 are anchored
at ``commit`` with ``confidence: low`` -- the deploy lag is unknown and could be
hours or days. After it they are anchored at ``restart`` with
``confidence: high``. This is not worth chasing further; the replay steps that
consume this can weight epochs by confidence.

=== Output ===
  .planning/phases/999.33-digital-twin-chamber-sim/999.33-09-control-epochs.json

Run:  python3 scripts/build-control-epochs.py [--refresh]
"""
import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PHASE_DIR = REPO_ROOT / '.planning' / 'phases' / '999.33-digital-twin-chamber-sim'
OUT_JSON = PHASE_DIR / '999.33-09-control-epochs.json'
CACHE_DIR = REPO_ROOT / '.cache' / 'mushy-58-epochs'

CONTAINER = 'mushy-timescale-1'
BRANCH = 'origin/fc1/prod'
CONFIG_PATH = 'src/chambers/fc-core/config/fc_config.yaml'
CONTROL_PATHS = [
    'src/chambers/fc-core/fc_core/fc_controller.py',
    # Not on fc1/prod at all -- control_kernel.py is a main-line refactor that has
    # never deployed. Listed so this keeps working when it does; contributes
    # nothing today, deliberately.
    'src/chambers/fc-core/fc_core/control_kernel.py',
    'src/chambers/fc-core/fc_core/fc_pwm_driver.py',
    CONFIG_PATH,
]

WINDOW_START = datetime(2026, 5, 1, tzinfo=timezone.utc)   # telemetry coverage starts here

# The 2026-06-27 band change is what makes restarts visible; see module docstring.
RESTART_VISIBLE_FROM = datetime(2026, 6, 27, tzinfo=timezone.utc)
RESTART_MARGIN = 0.005          # above band_high by this much -> mid-ramp
RESTART_GROUP_GAP_MIN = 5       # group restart-flagged minutes into one event
FORCE_MIN_MINUTES = 3           # shorter force runs are treated as noise
FORCE_HI = 0.999                # target at/above this -> force-condensation
FORCE_LO = 0.001                # target at/below this -> force-evaporation


# --------------------------------------------------------------------------
# git side
# --------------------------------------------------------------------------

def git(*args: str) -> str:
    return subprocess.run(['git', '-C', str(REPO_ROOT), *args],
                          capture_output=True, text=True, check=True).stdout


# fc_config.yaml is a flat ROS2 parameter block: `key: value  # comment`, with
# literal dotted keys like `modes.fruiting.band_low`. A line scan reads it
# exactly; PyYAML would be a new dependency in this venv for no extra fidelity.
CONFIG_LINE = re.compile(r'^\s*([A-Za-z_][\w.\-]*):\s*([^#\n]*?)\s*(?:#.*)?$')


def parse_config(sha: str) -> dict:
    """Flat key -> value for fc_config.yaml at `sha`. Values stay strings."""
    try:
        text = git('show', f'{sha}:{CONFIG_PATH}')
    except subprocess.CalledProcessError:
        return {}
    out = {}
    for line in text.splitlines():
        m = CONFIG_LINE.match(line)
        if m and m.group(2):
            out[m.group(1)] = m.group(2)
    return out


def as_float(cfg: dict, key: str):
    try:
        return float(cfg[key])
    except (KeyError, ValueError):
        return None


def declared_params(cfg: dict) -> dict:
    """The fruiting band + gains as the config DECLARES them at one commit.

    Before the `modes` block landed (5ea5cfee, 2026-05-11) the band was implicit:
    target +/- humidity_tolerance. After it, the per-mode keys are authoritative.
    """
    target = as_float(cfg, 'modes.fruiting.target_humidity')
    band_low = as_float(cfg, 'modes.fruiting.band_low')
    band_high = as_float(cfg, 'modes.fruiting.band_high')
    defend = cfg.get('modes.fruiting.defend_side')

    if band_low is None or band_high is None:
        target = as_float(cfg, 'target_humidity')
        tol = as_float(cfg, 'humidity_tolerance')
        if target is not None and tol is not None:
            band_low, band_high = round(target - tol, 6), round(target + tol, 6)
            defend = defend or 'both'

    return {
        'mode': cfg.get('active_mode', 'fruiting'),
        'target': target,
        'band_low': band_low,
        'band_high': band_high,
        'defend_side': defend,
        'kp': as_float(cfg, 'pid_kp'),
        'ki': as_float(cfg, 'pid_ki'),
        'kd': as_float(cfg, 'pid_kd'),
        'derivative_filter_tau': as_float(cfg, 'pid_derivative_filter_tau'),
        'integrator_decay_tau': as_float(cfg, 'pid_integrator_decay_tau'),
        'bypass_threshold': as_float(cfg, 'bypass_threshold'),
        'pwm_window_seconds': as_float(cfg, 'pwm_window_seconds'),
    }


def git_commits() -> list:
    """Control-path commits on the deployed branch, oldest first.

    --first-parent is load-bearing, not tidiness. Without it `git log` returns
    every commit from every merged side branch ordered by COMMITTER DATE, which
    is not the order the deployed branch passed through: e.g. ba7c1fa5 (27-02)
    committed 7 min after 8aebffeb (27-01) is not its descendant, and its config
    has no pid_kp at all. Following first parents gives the sequence of states
    the branch tip actually held -- which is the only sequence fc1 could deploy.
    (61 commits touch these paths; 41 are on the first-parent line.)

    Includes the last commit BEFORE the window so the window opens with the
    config that was actually running on 2026-05-01, not with a gap.
    """
    log = git('log', '--first-parent', '--reverse', '--format=%H|%cI',
              BRANCH, '--', *CONTROL_PATHS)
    commits = []
    for line in log.strip().splitlines():
        sha, iso = line.split('|')
        commits.append({'sha': sha, 'time': datetime.fromisoformat(iso).astimezone(timezone.utc)})

    in_window = [c for c in commits if c['time'] >= WINDOW_START]
    before = [c for c in commits if c['time'] < WINDOW_START]
    if before:
        in_window.insert(0, before[-1])
    return in_window


# --------------------------------------------------------------------------
# telemetry side
# --------------------------------------------------------------------------

def psql(sql: str) -> str:
    # max_parallel_workers_per_gather=0 is REQUIRED: the container's /dev/shm is
    # too small for parallel workers on these ~17M-row topics, and the failure
    # reads "could not resize shared memory segment ... No space left on device",
    # which sends you looking at disk. It is not disk.
    full = f'set max_parallel_workers_per_gather=0; {sql}'
    return subprocess.run(
        ['docker', 'exec', CONTAINER, 'psql', '-U', 'postgres', '-d', 'postgres',
         '-At', '-F', ',', '-c', full],
        capture_output=True, text=True, check=True).stdout


def cached(name: str, sql: str, refresh: bool) -> list:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f'{name}.csv'
    if refresh or not path.exists():
        print(f'  querying {name} (minutes, this takes a while) ...', file=sys.stderr)
        path.write_text(psql(sql))
    rows = []
    for line in path.read_text().strip().splitlines():
        if line:
            rows.append(line.split(','))
    return rows


# psql renders timestamptz in the SESSION timezone with a '+00'-style offset,
# which datetime.fromisoformat rejects before 3.11. Emitting explicit UTC in the
# query settles both the parsing and the "which timezone is this grid in"
# question at once -- worth doing given how often that has bitten this repo.
UTC_MINUTE = """to_char(date_trunc('minute', time) at time zone 'UTC',
                      'YYYY-MM-DD"T"HH24:MI:SS')"""


def parse_ts(s: str) -> datetime:
    return datetime.strptime(s, '%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc)


def load_target_minutes(refresh: bool) -> list:
    """(minute, last, max) of fc.humidity_target, one row per minute."""
    rows = cached('humidity_target_minutes', f"""
        select {UTC_MINUTE} as m,
               last(value, time) as v_last,
               max(value) as v_max
        from telemetry
        where topic = 'fc.humidity_target' and time >= '2026-05-01'
        group by 1 order by 1
    """, refresh)
    out = []
    for m, v_last, v_max in rows:
        out.append((parse_ts(m),
                    float(v_last), float(v_max)))
    return out


def load_duty_minutes(refresh: bool) -> dict:
    """minute -> (mean pid_output, mean humidifier_duty) where both exist.

    pid_output is the PRE-bias control-law output; humidifier_duty is what was
    actually commanded. Their difference is the effective duty bias.
    """
    rows = cached('duty_minutes', f"""
        select {UTC_MINUTE} as m,
               avg(value) filter (where topic = 'fc.pid_output') as pid,
               avg(value) filter (where topic = 'fc.humidifier_duty') as duty
        from telemetry
        where topic in ('fc.pid_output', 'fc.humidifier_duty')
          and time >= '2026-05-01'
        group by 1 order by 1
    """, refresh)
    out = {}
    for m, pid, duty in rows:
        if pid and duty:
            out[parse_ts(m)] = (float(pid), float(duty))
    return out


def classify(v: float) -> str:
    if v > 1.0 or v < 0.0:
        return 'invalid'          # out-of-range telemetry; see the report
    if v >= FORCE_HI:
        return 'force-condensation'
    if v <= FORCE_LO:
        return 'force-evaporation'
    return 'normal'


FORCE_MODES = ('force-condensation', 'force-evaporation')


def force_windows(minutes: list) -> list:
    """Contiguous runs of a force mode, >= FORCE_MIN_MINUTES long.

    Only the two force modes qualify. 'invalid' stretches are NOT windows --
    out-of-range telemetry says the value is untrustworthy, not that a mode ran.
    """
    windows, run_class, run_start, prev = [], None, None, None

    def close():
        if run_class in FORCE_MODES:
            span = (prev - run_start).total_seconds() / 60 + 1
            if span >= FORCE_MIN_MINUTES:
                windows.append({'mode': run_class, 'start': run_start,
                                'end': prev + timedelta(minutes=1)})

    for ts, v_last, _ in minutes:
        cls = classify(v_last)
        broken = prev is not None and (ts - prev) > timedelta(minutes=1)
        if cls != run_class or broken:
            close()
            run_class, run_start = cls, ts
        prev = ts
    close()
    return windows


def restart_events(minutes: list, band_high_at) -> list:
    """Minutes where the setpoint ramp says the controller just booted.

    Only meaningful once nominal target sits outside the band -- before that a
    restart published nothing distinguishable. See the module docstring.
    """
    flagged = []
    for ts, v_last, v_max in minutes:
        if ts < RESTART_VISIBLE_FROM or classify(v_last) != 'normal':
            continue
        bh = band_high_at(ts)
        if bh is not None and v_max > bh + RESTART_MARGIN:
            flagged.append(ts)

    events, prev = [], None
    for ts in flagged:
        if prev is None or (ts - prev) > timedelta(minutes=RESTART_GROUP_GAP_MIN):
            events.append(ts)
        prev = ts
    return events


def measure_duty_bias(duty_minutes: dict, start: datetime, end: datetime):
    """Median (duty - pid_output) over an epoch, on actively-controlling minutes.

    Excluded: minutes where pid_output is pinned at 0 or 1, where the bias is
    unobservable because the commanded duty saturates regardless.
    """
    deltas = sorted(duty - pid
                    for ts, (pid, duty) in duty_minutes.items()
                    if start <= ts < end and 0.01 < pid < 0.99)
    if len(deltas) < 30:
        return None, len(deltas)
    return round(deltas[len(deltas) // 2], 4), len(deltas)


# --------------------------------------------------------------------------
# merge
# --------------------------------------------------------------------------

def build_epochs(commits: list, minutes: list, duty_minutes: dict, now: datetime) -> tuple:
    """Git epochs anchored to restarts, then carved by telemetry force windows."""
    for c in commits:
        c['config'] = declared_params(parse_config(c['sha']))

    def band_high_at(ts):
        current = None
        for c in commits:
            if c['time'] <= ts:
                current = c
        return current['config']['band_high'] if current else None

    restarts = restart_events(minutes, band_high_at)
    unreached = []

    # Anchor each commit at the first restart after it, when that is knowable.
    for c in commits:
        after = [r for r in restarts if r >= c['time']]
        if c['time'] < RESTART_VISIBLE_FROM:
            c['effective_from'] = max(c['time'], WINDOW_START)
            c['anchor'], c['confidence'] = 'commit', 'low'
        elif after:
            c['effective_from'] = after[0]
            c['anchor'], c['confidence'] = 'restart', 'high'
        else:
            # Pushed but no restart since: the chamber may never have run it.
            c['effective_from'] = c['time']
            c['anchor'], c['confidence'] = 'commit', 'unreached'
            unreached.append(c['sha'][:8])

    # Later anchors can land before earlier ones (a restart picks up several
    # commits at once); keep the timeline monotonic and drop the shadowed ones.
    epochs, ordered = [], sorted(commits, key=lambda c: c['effective_from'])
    for i, c in enumerate(ordered):
        start = max(c['effective_from'], WINDOW_START)
        end = ordered[i + 1]['effective_from'] if i + 1 < len(ordered) else now
        if end <= start:
            continue
        bias, n = measure_duty_bias(duty_minutes, start, end)
        epochs.append({
            'effective_from': start, 'effective_to': end,
            'law_sha': c['sha'][:8], 'commit_time': c['time'],
            'anchor': c['anchor'], 'confidence': c['confidence'],
            'deploy_lag_hours': round((start - c['time']).total_seconds() / 3600, 2),
            'source': 'git+telemetry' if c['anchor'] == 'restart' else 'git',
            'duty_bias': bias, 'duty_bias_samples': n,
            **c['config'],
        })

    epochs = carve_force_windows(epochs, force_windows(minutes))
    return epochs, restarts, unreached


def carve_force_windows(epochs: list, windows: list) -> list:
    """Split git epochs wherever telemetry shows a force mode was running.

    A force mode is a runtime set_mode: the code is unchanged (law_sha and gains
    carry through) but the band and target are not what the config declares.
    """
    out = []
    for e in epochs:
        pieces, cursor = [], e['effective_from']
        for w in windows:
            if w['end'] <= e['effective_from'] or w['start'] >= e['effective_to']:
                continue
            start = max(w['start'], e['effective_from'])
            end = min(w['end'], e['effective_to'])
            if start > cursor:
                pieces.append({**e, 'effective_from': cursor, 'effective_to': start})
            pieces.append({**e, 'effective_from': start, 'effective_to': end,
                           'mode': w['mode'],
                           'target': 1.0 if w['mode'] == 'force-condensation' else 0.0,
                           'band_low': 0.0, 'band_high': 1.0,
                           'source': 'telemetry',
                           'confidence': 'high',
                           'anchor': 'telemetry'})
            cursor = end
        if cursor < e['effective_to']:
            pieces.append({**e, 'effective_from': cursor, 'effective_to': e['effective_to']})
        out.extend(pieces or [e])
    return out


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def serialise(epochs: list, restarts: list, unreached: list, minutes: list) -> dict:
    invalid = [(ts, v) for ts, v, _ in minutes if classify(v) == 'invalid']
    return {
        'ticket': 'MUSHY-58',
        'generated_from': {'branch': BRANCH, 'window_start': iso(WINDOW_START)},
        'notes': [
            'effective_from is the RESTART that put this code in service where that '
            'is detectable, otherwise the commit time. See anchor/confidence.',
            'confidence=low: before 2026-06-27 the nominal setpoint sat inside the '
            'band, so controller restarts published no detectable ramp and the '
            'deploy lag is unknown.',
            'confidence=unreached: pushed to the deployed branch with no controller '
            'restart after it -- this code may never have run on the chamber.',
            'Gains are as the config declared them; nothing here verifies them '
            'against telemetry.',
            'duty_bias is MEASURED (median of fc.humidifier_duty - fc.pid_output on '
            'unsaturated minutes) and is 0.0 for every epoch. That is a real result, '
            'not a stub: duty_bias_factor (MUSHY-57) exists only on main, and '
            'control_kernel.py has never been on fc1/prod, so the chamber has run no '
            'feedforward bias anywhere in this window.',
        ],
        'restarts_detected': len(restarts),
        # Consumers need these directly: a restart resets the PID's integral and
        # derivative filter, so a replay must re-init its ControlLoop at each one
        # rather than driving straight through. Only the FIRST restart after a
        # commit opens an epoch; these are all of them.
        'restarts': [iso(r) for r in restarts],
        'commits_never_reached_chamber': unreached,
        'out_of_range_target_minutes': {
            'count': len(invalid),
            'max_value': max((v for _, v in invalid), default=None),
            'first': iso(invalid[0][0]) if invalid else None,
            'last': iso(invalid[-1][0]) if invalid else None,
            'note': 'fc.humidity_target outside [0,1]; these minutes are classified '
                    '"invalid" and never used to infer a mode.',
        },
        'epochs': [
            {**e,
             'effective_from': iso(e['effective_from']),
             'effective_to': iso(e['effective_to']),
             'commit_time': iso(e['commit_time'])}
            for e in epochs
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--refresh', action='store_true', help='re-query telemetry')
    args = ap.parse_args()

    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)

    print('reading git ...', file=sys.stderr)
    commits = git_commits()
    print(f'  {len(commits)} control-path commits on {BRANCH}', file=sys.stderr)

    print('reading telemetry ...', file=sys.stderr)
    minutes = load_target_minutes(args.refresh)
    duty_minutes = load_duty_minutes(args.refresh)
    print(f'  {len(minutes)} minutes of fc.humidity_target', file=sys.stderr)

    epochs, restarts, unreached = build_epochs(commits, minutes, duty_minutes, now)

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(serialise(epochs, restarts, unreached, minutes),
                                   indent=2) + '\n')

    print(f'\n{len(epochs)} epochs -> {OUT_JSON.relative_to(REPO_ROOT)}')
    print(f'{len(restarts)} restarts detected; {len(unreached)} commits never reached the chamber')
    for e in epochs:
        print(f"  {iso(e['effective_from'])} .. {iso(e['effective_to'])}  {e['law_sha']}  "
              f"{e['mode']:<19} band[{e['band_low']}, {e['band_high']}]  "
              f"kp={e['kp']} ki={e['ki']}  {e['anchor']}/{e['confidence']}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
