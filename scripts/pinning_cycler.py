#!/usr/bin/env python3
"""
pinning_cycler.py - drive condensation/evaporation cycles to induce pinning.

The v1.5 forcing primitives (force-condensation / force-evaporation) are
one-shot and auto-revert after a bounded duration; the scheduler can switch
named modes on a clock but cannot drive the force modes. This script is the
missing driver: it repeats a wet -> dry -> rest cycle over a multi-day
induction window by calling the bridge's existing /control endpoints.

Why this is safe to leave running unattended:
  - Each phase uses the bridge force-experiment endpoint, which auto-reverts
    to the prior mode after `duration_minutes`. If THIS process dies mid-wet,
    the mister cannot stay on past that bounded window -- it reverts to
    `pinning` on its own. The cycler adds rhythm, not a new failure mode.
  - Before cycling, it sets the chamber to `pinning` (wide band, defend low)
    so every force phase reverts INTO pinning between cycles, not back into
    flat-96% fruiting (which suppresses pinning).
  - SIGINT/SIGTERM -> cancel any active experiment, leave chamber in pinning.

This is an EXPERIMENT, not a known recipe. The default timings are starting
guesses for an oyster / cold-tolerant block in a cold outdoor tent; tune them
by eye as you watch the blocks. Every action is logged to JSONL for the paper
trail.

Examples:
  # See the schedule it WOULD run, fire nothing:
  python3 scripts/pinning_cycler.py --dry-run

  # Run a 5-day induction, 10 min mist / 30 min dry / 3 h rest per cycle:
  python3 scripts/pinning_cycler.py --days 5 --wet-min 10 --dry-min 30 --rest-min 180
"""

import argparse
import json
import os
import signal
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

DEFAULT_BRIDGE = "http://localhost:8081"
DEFAULT_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs", "pinning-cycler.jsonl")
PINNING_MODE = "pinning"
HARD_CAP_MIN = 120          # mirrors controller/bridge force-duration cap
SETTLE_SEC = 20             # buffer after a force phase so auto-revert lands
MAX_CONSECUTIVE_FAILURES = 5

_stop = False


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def log(logfile, event, **fields):
    rec = {"ts": now_iso(), "event": event, **fields}
    line = json.dumps(rec)
    print(line, flush=True)
    if logfile:
        with open(logfile, "a") as f:
            f.write(line + "\n")


def post(url, payload, timeout=10):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode() or "{}")


def get(url, timeout=10):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode() or "{}")


def set_mode(bridge, mode, logfile, dry_run):
    if dry_run:
        log(logfile, "would_set_mode", mode=mode)
        return True
    try:
        status, body = post(
            f"{bridge}/control/param",
            {"node": "fc_controller", "param": "active_mode", "value": mode},
        )
        ok = status == 200
        log(logfile, "set_mode", mode=mode, status=status, ok=ok, resp=body)
        return ok
    except urllib.error.URLError as e:
        log(logfile, "set_mode_error", mode=mode, error=str(e))
        return False


def experiment_active(bridge):
    try:
        _, body = get(f"{bridge}/control/experiment")
        return bool(body.get("active"))
    except urllib.error.URLError:
        return False


def cancel(bridge, logfile, dry_run):
    if dry_run:
        log(logfile, "would_cancel")
        return
    try:
        status, body = post(f"{bridge}/control/cancel-experiment", {})
        log(logfile, "cancel", status=status, resp=body)
    except urllib.error.URLError as e:
        log(logfile, "cancel_error", error=str(e))


def force_phase(bridge, name, minutes, logfile, dry_run):
    """Fire one force experiment. Returns True on accepted/started."""
    if dry_run:
        log(logfile, "would_force", name=name, minutes=minutes)
        return True
    # Defensive: never stack on top of a live experiment.
    if experiment_active(bridge):
        log(logfile, "unexpected_active_experiment_cancelling", before=name)
        cancel(bridge, logfile, dry_run)
        time.sleep(5)
    try:
        status, body = post(
            f"{bridge}/control/experiment",
            {"name": name, "duration_minutes": minutes},
        )
        ok = status == 200 and body.get("ok", True) is not False
        log(logfile, "force", name=name, minutes=minutes, status=status, ok=ok, resp=body)
        return ok
    except urllib.error.URLError as e:
        log(logfile, "force_error", name=name, minutes=minutes, error=str(e))
        return False


def interruptible_sleep(seconds, logfile=None, what=None):
    """Sleep in 1s ticks so SIGTERM is responsive."""
    end = time.monotonic() + seconds
    while not _stop and time.monotonic() < end:
        time.sleep(min(1.0, end - time.monotonic()))


def handle_signal(signum, frame):
    global _stop
    _stop = True


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bridge", default=DEFAULT_BRIDGE, help="bridge base URL")
    p.add_argument("--days", type=float, default=5.0, help="total induction window (days)")
    p.add_argument("--wet-min", type=int, default=10, help="force-condensation minutes per cycle (0=skip)")
    p.add_argument("--dry-min", type=int, default=30, help="force-evaporation minutes per cycle (0=skip)")
    p.add_argument("--rest-min", type=int, default=180, help="rest (in pinning mode) minutes per cycle")
    p.add_argument("--max-cycles", type=int, default=0, help="stop after N cycles (0=unlimited; use for smoke tests)")
    p.add_argument("--logfile", default=DEFAULT_LOG, help="JSONL action log path")
    p.add_argument("--dry-run", action="store_true", help="print the schedule, fire nothing")
    args = p.parse_args()

    for label, val in (("wet-min", args.wet_min), ("dry-min", args.dry_min)):
        if val and not (1 <= val <= HARD_CAP_MIN):
            p.error(f"--{label} must be 0 or in [1, {HARD_CAP_MIN}]; got {val}")
    if args.rest_min < 0:
        p.error("--rest-min must be >= 0")

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    cycle_min = args.wet_min + args.dry_min + args.rest_min
    if cycle_min <= 0:
        p.error("at least one of wet/dry/rest must be > 0")
    total_sec = args.days * 86400
    est_cycles = int(total_sec // (cycle_min * 60)) if cycle_min else 0

    logfile = None if args.dry_run else args.logfile
    if logfile:
        os.makedirs(os.path.dirname(os.path.abspath(logfile)), exist_ok=True)
    log(logfile, "start",
        bridge=args.bridge, days=args.days, wet_min=args.wet_min,
        dry_min=args.dry_min, rest_min=args.rest_min,
        cycle_min=cycle_min, est_cycles=est_cycles, dry_run=args.dry_run)

    # Put the chamber in pinning so force phases revert into it (not flat fruiting).
    if not set_mode(args.bridge, PINNING_MODE, logfile, args.dry_run) and not args.dry_run:
        log(logfile, "abort", reason="could not set pinning mode")
        return 1

    if args.dry_run:
        # Walk one representative cycle so the operator sees the rhythm.
        log(logfile, "would_cycle_example",
            wet=f"force-condensation {args.wet_min}m",
            dry=f"force-evaporation {args.dry_min}m",
            rest=f"pinning {args.rest_min}m")
        log(logfile, "dry_run_done", est_cycles=est_cycles)
        return 0

    deadline = time.monotonic() + total_sec
    failures = 0
    cycle = 0
    while not _stop and time.monotonic() < deadline:
        if args.max_cycles and cycle >= args.max_cycles:
            break
        cycle += 1
        log(logfile, "cycle_begin", cycle=cycle)

        if args.wet_min > 0 and not _stop:
            ok = force_phase(args.bridge, "force-condensation", args.wet_min, logfile, False)
            failures = 0 if ok else failures + 1
            interruptible_sleep(args.wet_min * 60 + SETTLE_SEC)

        if args.dry_min > 0 and not _stop:
            ok = force_phase(args.bridge, "force-evaporation", args.dry_min, logfile, False)
            failures = 0 if ok else failures + 1
            interruptible_sleep(args.dry_min * 60 + SETTLE_SEC)

        if failures >= MAX_CONSECUTIVE_FAILURES:
            log(logfile, "abort", reason=f"{failures} consecutive bridge failures")
            break

        if args.rest_min > 0 and not _stop:
            log(logfile, "rest", minutes=args.rest_min)
            interruptible_sleep(args.rest_min * 60)

    # Cleanup: cancel anything in flight, leave chamber resting in pinning.
    if experiment_active(args.bridge):
        cancel(args.bridge, logfile, False)
    set_mode(args.bridge, PINNING_MODE, logfile, False)
    log(logfile, "stop", reason="signal" if _stop else "window_complete",
        cycles_run=cycle,
        note="left chamber in pinning; switch to fruiting once pins set")
    return 0


if __name__ == "__main__":
    sys.exit(main())
