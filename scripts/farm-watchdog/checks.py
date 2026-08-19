"""farm-watchdog checks -- does each CAPABILITY still work? (MUSHY-43)

Every check here was derived from a failure that actually happened and that
nobody noticed:

  signal registration   7.8 days silent (2026-07-19, SPQR deregistration)
  farmOS reachable      3 days of HTTP 500 (BONE-10, containers network-detached)
  whisper transcribing  5.5 weeks of voice notes stored with NULL transcripts
  telemetry arriving    the chamber alerter was DEAF for 1.5 days (MUSHY-97)
  parked farm records   a confirmed 9-block session lost 17 days (MUSHY-75)
  container restarting  a crash-looping dependent logged the cause for 3 days

The framing that ties them together, and the reason none of these is a liveness
check: **every one of those components was still running and still looked
alive.** Four of the five network-detached containers reported `healthy` for
three days, because their healthchecks curl localhost INSIDE the container,
which succeeds perfectly when the container has no network at all. Docker health
status is not a health signal here; it is actively misleading. So a check earns
its place only by asking whether a capability still produces its result.

This module is PURE: it turns already-gathered facts into verdicts. Everything
that touches the network, docker or the database lives in farm_watchdog.py, so
the judgement calls are testable without a farm.

ASCII-only. No em-dashes.
"""

from __future__ import annotations

OK = "ok"
BROKEN = "broken"
UNKNOWN = "unknown"


def verdict(name: str, state: str, detail: str) -> dict:
    return {"check": name, "state": state, "detail": detail}


# ---------------------------------------------------------------------------
# Signal -- the 7.8-day outage
# ---------------------------------------------------------------------------

def check_signal_registration(accounts, expected_number: str) -> dict:
    """The bot account must still be registered.

    Signal's servers unregistered the account server-side on 2026-07-19 and
    `/v1/accounts` went to `[]`. The container stayed up and healthy throughout;
    this endpoint is the only thing that told the truth.
    """
    if accounts is None:
        return verdict("signal_registration", UNKNOWN, "signal-cli did not answer")
    if not isinstance(accounts, list):
        return verdict("signal_registration", UNKNOWN, f"unexpected shape: {accounts!r}")
    if expected_number in accounts:
        return verdict("signal_registration", OK, expected_number)
    return verdict(
        "signal_registration", BROKEN,
        f"{expected_number} NOT registered (accounts={accounts}); "
        "re-registration needs a current signal-cli, see MUSHY-43",
    )


# ---------------------------------------------------------------------------
# HTTP capability probes -- from OUTSIDE the container
# ---------------------------------------------------------------------------

def check_http(name: str, status, expected: int = 200) -> dict:
    """A real path, probed from outside the box that serves it.

    "Is the container up" answered yes through three days of farmOS 500s.
    """
    if status is None:
        return verdict(name, BROKEN, "no response")
    if status == expected:
        return verdict(name, OK, f"HTTP {status}")
    return verdict(name, BROKEN, f"HTTP {status}, expected {expected}")


def check_whisper(status, model_loaded) -> dict:
    """Reachable is the capability; loaded is not.

    Since MUSHY-33 whisper unloads its model when idle, so `model_loaded: false`
    with a 200 is the NORMAL resting state. Treating it as a fault would page
    the operator every time the reaper did its job.
    """
    if status is None:
        return verdict("whisper", BROKEN, "no response")
    if status != 200:
        return verdict("whisper", BROKEN, f"HTTP {status}")
    return verdict("whisper", OK, f"reachable, model_loaded={model_loaded}")


# ---------------------------------------------------------------------------
# Capability checks that read the record, not the process
# ---------------------------------------------------------------------------

def check_telemetry_fresh(age_sec, max_age_sec: int = 600) -> dict:
    """Chamber telemetry is still landing in the database."""
    if age_sec is None:
        return verdict("telemetry_fresh", UNKNOWN, "could not read telemetry")
    if age_sec <= max_age_sec:
        return verdict("telemetry_fresh", OK, f"{int(age_sec)}s old")
    return verdict(
        "telemetry_fresh", BROKEN,
        f"newest telemetry is {int(age_sec)}s old (limit {max_age_sec}s)",
    )


def check_heartbeat_today(last_heartbeat_day, today: str, readable: bool = True) -> dict:
    """The farm's daily report actually reached the farmer.

    This is the capability proxy for "the alerter can hear the chamber". A deaf
    alerter (MUSHY-97) holds a healthy socket, reports healthy, and quietly
    produces nothing -- the heartbeat is the only externally visible thing it
    must produce every day. 24h resolution is coarse, but the failure it catches
    ran undetected for a day and a half.
    """
    if not readable:
        # "the database did not answer" is not "the farmer got no heartbeat".
        # Conflating those two is the exact failure this ticket exists to stop,
        # and an unreadable DB reported as BROKEN is a false alarm that trains
        # the operator to ignore the watchdog.
        return verdict("heartbeat_today", UNKNOWN, "could not read send history")
    if last_heartbeat_day is None:
        return verdict("heartbeat_today", BROKEN, "no heartbeat has ever been sent")
    if last_heartbeat_day >= today:
        return verdict("heartbeat_today", OK, last_heartbeat_day)
    return verdict(
        "heartbeat_today", BROKEN,
        f"last heartbeat was {last_heartbeat_day}, expected {today}",
    )


def check_degraded_captures(count, window_h: int = 24) -> dict:
    """Voice notes are becoming transcripts.

    Whisper was down 5.5 weeks. Every note was stored `degraded=true` with a
    NULL transcript and the farmer was never told. One degraded capture is a
    blip; any at all inside a day is worth surfacing, because the alternative is
    finding out in five weeks.
    """
    if count is None:
        return verdict("voice_notes_transcribing", UNKNOWN, "could not read captures")
    if count == 0:
        return verdict("voice_notes_transcribing", OK, f"0 degraded in {window_h}h")
    return verdict(
        "voice_notes_transcribing", BROKEN,
        f"{count} capture(s) stored degraded in the last {window_h}h",
    )


def check_parked_drafts(count) -> dict:
    """Confirmed farm records are not sitting unwritten.

    MUSHY-75: a 9-block seeding session sat in commit_failed at the retry cap
    for 17 days. The farmer had confirmed it; nothing ever retried it.
    """
    if count is None:
        return verdict("no_parked_records", UNKNOWN, "could not read drafts")
    if count == 0:
        return verdict("no_parked_records", OK, "0 parked")
    return verdict(
        "no_parked_records", BROKEN,
        f"{count} confirmed record(s) parked in commit_failed at the retry cap",
    )


# ---------------------------------------------------------------------------
# Container checks -- restart loops, not health status
# ---------------------------------------------------------------------------

def check_restarting(containers) -> dict:
    """Anything stuck restarting.

    The cheapest high-value check on the list: the farmOS outage announced
    itself for three days through a crash-looping dependent that logged the
    correct error every 60s, and nobody was watching restart counts.
    """
    if containers is None:
        return verdict("no_restart_loops", UNKNOWN, "could not read docker state")
    bad = [c["name"] for c in containers if c.get("restarting")]
    if not bad:
        return verdict("no_restart_loops", OK, f"{len(containers)} container(s) steady")
    return verdict("no_restart_loops", BROKEN, "restarting: " + ", ".join(sorted(bad)))


def check_networks_attached(containers) -> dict:
    """Containers still have a network.

    BONE-10: five containers came up network-detached after a cold start and
    reported `healthy` for three days, because their healthchecks curl localhost
    inside the container, which works fine with no network at all.
    """
    if containers is None:
        return verdict("networks_attached", UNKNOWN, "could not read docker state")
    detached = [c["name"] for c in containers if c.get("networks") == 0]
    if not detached:
        return verdict("networks_attached", OK, f"{len(containers)} container(s) attached")
    return verdict(
        "networks_attached", BROKEN,
        "network-detached (docker will still call these healthy): "
        + ", ".join(sorted(detached)),
    )


# ---------------------------------------------------------------------------
# Roll-up
# ---------------------------------------------------------------------------

def summarise(results: list[dict]) -> dict:
    """Overall verdict. UNKNOWN never masks a BROKEN, and never counts as OK.

    A check that could not run is reported as its own category rather than
    quietly passing, because "the probe failed" and "the capability works" are
    the two things this whole ticket exists to stop conflating.
    """
    broken = [r for r in results if r["state"] == BROKEN]
    unknown = [r for r in results if r["state"] == UNKNOWN]
    if broken:
        state = BROKEN
    elif unknown:
        state = UNKNOWN
    else:
        state = OK
    return {
        "state": state,
        "broken": [r["check"] for r in broken],
        "unknown": [r["check"] for r in unknown],
        "checks": results,
    }


def alert_text(summary: dict) -> str:
    """One line per failing capability, for a push notification."""
    lines = []
    for r in summary["checks"]:
        if r["state"] == BROKEN:
            lines.append(f"BROKEN {r['check']}: {r['detail']}")
    for r in summary["checks"]:
        if r["state"] == UNKNOWN:
            lines.append(f"UNKNOWN {r['check']}: {r['detail']}")
    return "\n".join(lines) or "all capabilities ok"
