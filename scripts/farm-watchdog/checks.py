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


def check_heartbeat_recent(age_sec, max_age_h: int = 25, readable: bool = True) -> dict:
    """The farm's daily report actually reached the farmer.

    This is the capability proxy for "the alerter can hear the chamber". A deaf
    alerter (MUSHY-97) holds a healthy socket, reports healthy, and quietly
    produces nothing -- the heartbeat is the only externally visible thing it
    must produce every day.

    Measured as age, not as "was one sent on today's date". The heartbeat is due
    at heartbeat_hour (17:00 local), so a calendar-day comparison called every
    night BROKEN from midnight until 17:00 -- 68 false pushes a night, which is
    how a watchdog gets muted. Age also keeps the alerter's schedule in one
    place: nothing here has to know what the hour is, and nothing drifts when it
    changes. 25h is a day plus an hour of grace for restarts and jitter, so a
    genuinely skipped heartbeat is BROKEN an hour after it was due.
    """
    if not readable:
        # "the database did not answer" is not "the farmer got no heartbeat".
        # Conflating those two is the exact failure this ticket exists to stop,
        # and an unreadable DB reported as BROKEN is a false alarm that trains
        # the operator to ignore the watchdog.
        return verdict("heartbeat_recent", UNKNOWN, "could not read send history")
    if age_sec is None:
        return verdict("heartbeat_recent", BROKEN, "no heartbeat has ever been sent")
    hours = age_sec / 3600
    if hours <= max_age_h:
        return verdict("heartbeat_recent", OK, f"{hours:.1f}h ago")
    return verdict(
        "heartbeat_recent", BROKEN,
        f"last heartbeat was {hours:.1f}h ago (limit {max_age_h}h)",
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


# ---------------------------------------------------------------------------
# MUSHY-99 -- alert on change, not on every run
#
# The 2026-08-20 night of buzzing was two faults, not one. The heartbeat check
# asking the wrong question was the bug; `notify()` having no memory of what it
# had already said was the amplifier that turned it into 68 identical
# high-priority pushes before morning. Fixing only the bug leaves the amplifier
# in place for the next one, and persistent faults are the normal case here.
#
# So: push when a capability ENTERS broken or unknown, push once when it
# recovers, and otherwise re-push a standing fault at most once every few
# hours. Comparing the whole failure set (not just the overall state) is what
# makes "a second capability broke while the first was still broken" news.
# ---------------------------------------------------------------------------

REMINDER_AFTER_S = 6 * 3600


def failing(summary: dict) -> dict:
    """{check_name: state} for every capability that is not ok."""
    return {r["check"]: r["state"] for r in summary["checks"] if r["state"] != OK}


def decide_notification(summary, prior, now, reminder_after_s=REMINDER_AFTER_S) -> dict:
    """Should this run push, and why?

    `prior` is the state written by the previous run, or None. Anything that is
    not a usable state dict is treated as no prior state at all: an absent,
    half-written or corrupt file must never buy silence. Same rule as MUSHY-98's
    duplicate guard -- a de-duplicator that fails closed causes exactly the
    silence it exists to prevent.
    """
    current = failing(summary)

    previous, notified_at = {}, None
    if isinstance(prior, dict):
        if isinstance(prior.get("failures"), dict):
            previous = prior["failures"]
        if isinstance(prior.get("notified_at"), (int, float)):
            notified_at = float(prior["notified_at"])

    if current != previous:
        reason = "entered" if current else "recovered"
    elif current and (notified_at is None or now - notified_at >= reminder_after_s):
        reason = "reminder"
    else:
        reason = None

    return {
        "notify": reason is not None,
        "reason": reason,
        "recovered_from": previous,
        # A suppressed run must NOT touch notified_at, or the reminder clock
        # restarts every 15 minutes and the slow nag never fires.
        "state": {
            "failures": current,
            "notified_at": now if reason else notified_at,
        },
    }


def notification_payload(summary: dict, reason: str, recovered_from: dict) -> dict:
    """Title, priority and body for one push."""
    if reason == "recovered":
        names = ", ".join(sorted(recovered_from)) or "everything"
        return {
            "title": "mushy: recovered",
            "priority": "default",
            "tags": "white_check_mark",
            "body": f"recovered: {names}\nall capabilities ok",
        }

    broken = summary["broken"]
    n = len(broken) or len(summary["unknown"])
    word = "broken" if broken else "unreadable"
    still = "still " if reason == "reminder" else ""
    return {
        "title": f"mushy: {still}{n} capability(ies) {word}",
        "priority": "high" if broken else "default",
        "tags": "warning",
        "body": alert_text(summary),
    }
