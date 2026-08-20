#!/usr/bin/env python3
"""farm-watchdog -- does the farm still WORK? (MUSHY-43)

Answers one question per capability, from outside the thing being checked:

  can the bot still send on Signal        (7.8-day silent deregistration)
  is farmOS actually serving              (3 days of HTTP 500 behind a healthy container)
  can a voice note become a transcript    (5.5 weeks of NULL transcripts)
  is chamber telemetry arriving           (the alerter was deaf 1.5 days)
  is the daily heartbeat still current      (same)
  are confirmed farm records written      (a 9-block session lost 17 days)
  is anything crash-looping or detached   (both, announced for 3 days, unread)

None of these is a liveness check, and that is the point: every failure above
happened to a component that was still running and still looked alive. Docker
reported four network-detached containers as `healthy` for three days, because
their healthchecks curl localhost inside the container, which succeeds when the
container has no network at all.

Exit codes:  0 all capabilities ok   1 something BROKEN   2 something UNKNOWN

  farm_watchdog.py                # human-readable
  farm_watchdog.py --json         # machine-readable, for a heartbeat payload
  farm_watchdog.py --notify       # push failures to ntfy (needs NTFY_URL)

Delivery is deliberately out-of-band: ntfy.sh, not Signal, because the single
most important thing this watches IS Signal. See the README.

ASCII-only. No em-dashes. Never raises: a watchdog that crashes is a watchdog
that lies.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import checks  # noqa: E402

BOT_NUMBER = os.environ.get("MUSHY_BOT_NUMBER", "+59891840205")
TIMEOUT = float(os.environ.get("WATCHDOG_TIMEOUT_S", "8"))

SIGNAL_URL = os.environ.get("SIGNAL_CLI_URL", "http://127.0.0.1:8085")
HTTP_PROBES = [
    ("farmos_prod", os.environ.get("FARMOS_PROD_URL", "http://10.68.155.50:8082/user/login")),
    ("farmos_dev", os.environ.get("FARMOS_DEV_URL", "http://10.68.155.50:18080/user/login")),
    ("bridge", os.environ.get("BRIDGE_HEALTH_URL", "http://127.0.0.1:8081/health")),
    ("mission_control", os.environ.get("MC_URL", "http://127.0.0.1:8080/")),
]
WHISPER_URL = os.environ.get("WHISPER_HEALTH_URL", "http://127.0.0.1:8090/health")

TIMESCALE_CONTAINER = os.environ.get("TIMESCALE_CONTAINER", "mushy-timescale-1")

STATE_FILE = Path(os.environ.get(
    "WATCHDOG_STATE_FILE", "/var/lib/mushy-watchdog/state.json"))
REMINDER_S = float(os.environ.get("WATCHDOG_REMINDER_H", "6")) * 3600


# ---------------------------------------------------------------------------
# Fact gathering. Every one of these returns None rather than raising, so a
# probe that cannot run is reported as UNKNOWN instead of taking the run down.
# ---------------------------------------------------------------------------

def _get(url: str):
    """(status, body_text) or (None, None)."""
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception:
        return None, None


def fetch_signal_accounts():
    status, body = _get(f"{SIGNAL_URL}/v1/accounts")
    if status != 200 or body is None:
        return None
    try:
        return json.loads(body)
    except ValueError:
        return None


def fetch_whisper():
    status, body = _get(WHISPER_URL)
    loaded = None
    if body:
        try:
            loaded = json.loads(body).get("model_loaded")
        except ValueError:
            pass
    return status, loaded


def psql(sql: str):
    """(readable, value) -- one scalar from the prod database.

    readable=False means the query could not run at all; value=None with
    readable=True means it ran and returned nothing. Keeping those apart is the
    difference between "no heartbeat was sent" and "the database did not
    answer", and reporting the second as the first is a false alarm.

    Goes through `docker exec` rather than a direct connection so the watchdog
    needs no database password of its own.
    """
    try:
        out = subprocess.run(
            ["docker", "exec", TIMESCALE_CONTAINER, "psql", "-U", "postgres",
             "-d", "postgres", "-Atc", sql],
            capture_output=True, text=True, timeout=TIMEOUT + 7,
        )
        if out.returncode != 0:
            return False, None
        value = out.stdout.strip()
        return True, (value if value else None)
    except Exception:
        return False, None


def fetch_containers():
    """[{name, restarting, networks}] or None."""
    try:
        out = subprocess.run(
            ["docker", "ps", "-a", "--format", "{{.Names}}\t{{.State}}"],
            capture_output=True, text=True, timeout=TIMEOUT + 7,
        )
        if out.returncode != 0:
            return None
        rows = []
        for line in out.stdout.splitlines():
            if not line.strip():
                continue
            name, _, state = line.partition("\t")
            if state.strip() in ("exited", "created"):
                continue        # deliberately stopped is not a fault here
            rows.append({"name": name.strip(), "restarting": state.strip() == "restarting"})
        if not rows:
            return None
        names = [r["name"] for r in rows]
        inspect = subprocess.run(
            ["docker", "inspect", "-f",
             "{{.Name}}\t{{len .NetworkSettings.Networks}}", *names],
            capture_output=True, text=True, timeout=TIMEOUT + 7,
        )
        counts = {}
        if inspect.returncode == 0:
            for line in inspect.stdout.splitlines():
                n, _, c = line.partition("\t")
                try:
                    counts[n.strip().lstrip("/")] = int(c.strip())
                except ValueError:
                    pass
        for r in rows:
            r["networks"] = counts.get(r["name"])
        return rows
    except Exception:
        return None


# ---------------------------------------------------------------------------

def run_checks() -> dict:
    results = [checks.check_signal_registration(fetch_signal_accounts(), BOT_NUMBER)]

    for name, url in HTTP_PROBES:
        status, _ = _get(url)
        results.append(checks.check_http(name, status))

    status, loaded = fetch_whisper()
    results.append(checks.check_whisper(status, loaded))

    _, age = psql("select extract(epoch from now() - max(time)) from telemetry;")
    results.append(checks.check_telemetry_fresh(float(age) if age else None))

    readable, hb_age = psql(
        "select extract(epoch from now() - max(sent_at)) from signal_outbound "
        "where intent = 'heartbeat' or body like '[HEARTBEAT]%';"
    )
    results.append(checks.check_heartbeat_recent(
        float(hb_age) if hb_age else None, readable=readable))

    _, degraded = psql(
        "select count(*) from signal_capture where degraded is true "
        "and captured_at > now() - interval '24 hours';"
    )
    results.append(checks.check_degraded_captures(int(degraded) if degraded else None))

    _, parked = psql(
        "select count(*) from signal_draft where status = 'commit_failed' "
        "and commit_failed_transport is true;"
    )
    results.append(checks.check_parked_drafts(int(parked) if parked else None))

    containers = fetch_containers()
    results.append(checks.check_restarting(containers))
    results.append(checks.check_networks_attached(containers))

    summary = checks.summarise(results)
    summary["checked_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return summary


def load_state(path: Path):
    """The previous run's failure set, or None if we have no usable memory.

    Unreadable, absent and corrupt all return None, which
    `checks.decide_notification` treats as "we cannot prove the farmer was
    already told" and therefore notifies. A de-duplicator must never cause the
    silence it exists to prevent (MUSHY-98's rule, same shape).
    """
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def save_state(path: Path, state: dict) -> None:
    """Atomically. A half-written state file must never be readable as memory."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(state))
        tmp.replace(path)
    except Exception as e:
        print(f"[watchdog] could not save state: {type(e).__name__}: {e}", file=sys.stderr)


def push(payload: dict) -> bool:
    """POST one notification. True only means ntfy accepted it.

    NOT that a human was told: ntfy creates topics on demand, so a push to a
    mistyped topic returns success too. The phone is the only proof.
    """
    url = os.environ.get("NTFY_URL", "").strip()
    if not url:
        print("[watchdog] NTFY_URL unset; not notifying", file=sys.stderr)
        return False
    req = urllib.request.Request(url, data=payload["body"].encode("utf-8"), headers={
        "Title": payload["title"],
        "Priority": payload["priority"],
        "Tags": payload["tags"],
    })
    try:
        urllib.request.urlopen(req, timeout=TIMEOUT)
        return True
    except Exception as e:
        print(f"[watchdog] notify failed: {type(e).__name__}: {e}", file=sys.stderr)
        return False


def notify(summary: dict, state_file: Path = STATE_FILE) -> bool:
    """Push only what is NEW: a fault appearing, or the all-clear (MUSHY-99).

    A standing fault is re-pushed at most once every WATCHDOG_REMINDER_H hours.
    Persistent faults are the normal case here, so pushing on every run at a
    15-minute cadence means 96 identical alerts a day, and a channel that buzzes
    every 15 minutes gets silenced. Correct and unmutable is still unusable.
    """
    now = datetime.now(timezone.utc).timestamp()
    decision = checks.decide_notification(
        summary, load_state(state_file), now, reminder_after_s=REMINDER_S)

    if not decision["notify"]:
        save_state(state_file, decision["state"])
        return False

    sent = push(checks.notification_payload(
        summary, decision["reason"], decision["recovered_from"]))

    new_state = dict(decision["state"])
    if not sent:
        # An undelivered push must not buy six hours of quiet. Leaving the
        # timestamp empty makes the next run treat this as still un-told and
        # retry, which is the fail-loud direction.
        new_state["notified_at"] = None
    save_state(state_file, new_state)
    return sent


def main() -> int:
    ap = argparse.ArgumentParser(description="Check that farm capabilities still work.")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--notify", action="store_true", help="push failures to ntfy")
    args = ap.parse_args()

    summary = run_checks()

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        for r in summary["checks"]:
            mark = {checks.OK: "ok  ", checks.BROKEN: "FAIL", checks.UNKNOWN: "????"}[r["state"]]
            print(f"  [{mark}] {r['check']}: {r['detail']}")
        print(f"\n  overall: {summary['state'].upper()}")

    if args.notify:
        notify(summary)

    return {checks.OK: 0, checks.BROKEN: 1, checks.UNKNOWN: 2}[summary["state"]]


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001 -- a watchdog that crashes is one that lies
        print(f"[watchdog] FATAL {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(2)
