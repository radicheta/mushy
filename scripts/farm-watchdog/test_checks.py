"""MUSHY-43: the watchdog must not repeat the failures it exists to catch.

Every case here is anchored to a real incident. The point of the suite is less
"does the comparison work" than "does the verdict match what actually happened",
because each of these failures was survivable only because someone eventually
looked.

Run:  src/farm-agent/.venv/bin/python -m pytest scripts/farm-watchdog -q

ASCII-only. No em-dashes.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import checks  # noqa: E402

BOT = "+59891840205"


class TestSignalRegistration:
    def test_registered_is_ok(self):
        assert checks.check_signal_registration([BOT], BOT)["state"] == checks.OK

    def test_the_2026_07_19_outage(self):
        """`/v1/accounts` went to [] server-side. 7.8 days, nobody told."""
        r = checks.check_signal_registration([], BOT)
        assert r["state"] == checks.BROKEN
        assert "NOT registered" in r["detail"]

    def test_a_different_account_is_not_ours(self):
        assert checks.check_signal_registration(["+10000000000"], BOT)["state"] == checks.BROKEN

    def test_no_answer_is_unknown_not_broken(self):
        """signal-cli being unreachable is a different fault from being
        unregistered, and the recovery is different too."""
        assert checks.check_signal_registration(None, BOT)["state"] == checks.UNKNOWN


class TestHttpProbes:
    def test_200_is_ok(self):
        assert checks.check_http("farmos_prod", 200)["state"] == checks.OK

    def test_the_bone10_outage(self):
        """farmOS returned 500 on every request for three days while docker
        reported the container healthy."""
        r = checks.check_http("farmos_prod", 500)
        assert r["state"] == checks.BROKEN
        assert "500" in r["detail"]

    def test_no_response_is_broken(self):
        assert checks.check_http("bridge", None)["state"] == checks.BROKEN


class TestWhisper:
    def test_idle_with_no_model_is_healthy(self):
        """MUSHY-33: whisper unloads when idle. Paging on model_loaded=false
        would fire every time the reaper worked correctly."""
        assert checks.check_whisper(200, False)["state"] == checks.OK

    def test_loaded_is_also_healthy(self):
        assert checks.check_whisper(200, True)["state"] == checks.OK

    def test_unreachable_is_broken(self):
        """The 5.5-week outage: whisper stopped and voice notes died silently."""
        assert checks.check_whisper(None, None)["state"] == checks.BROKEN


class TestTelemetryFreshness:
    def test_current_is_ok(self):
        assert checks.check_telemetry_fresh(3)["state"] == checks.OK

    def test_stale_is_broken(self):
        r = checks.check_telemetry_fresh(3600)
        assert r["state"] == checks.BROKEN
        assert "3600s old" in r["detail"]

    def test_the_boundary_is_inclusive(self):
        assert checks.check_telemetry_fresh(600, max_age_sec=600)["state"] == checks.OK
        assert checks.check_telemetry_fresh(601, max_age_sec=600)["state"] == checks.BROKEN

    def test_unreadable_is_unknown(self):
        assert checks.check_telemetry_fresh(None)["state"] == checks.UNKNOWN


class TestHeartbeatRecent:
    """The heartbeat is due once a day, but not at midnight.

    The check this replaces asked "was one sent on today's calendar date". The
    farm's heartbeat_hour is 17:00 local, so from local midnight until 17:00
    the honest answer was "not yet" and the watchdog said BROKEN -- 68 pushes
    a night, every night. Age since the last heartbeat carries no such
    assumption, and needs no second copy of the alerter's schedule.
    """

    H = 3600

    def test_a_heartbeat_earlier_today_is_ok(self):
        assert checks.check_heartbeat_recent(3 * self.H)["state"] == checks.OK

    def test_the_nightly_false_alarm(self):
        """00:35 local, heartbeat sent 17:00 yesterday: 7.5h old, not a fault.

        This is the regression. Calendar-day comparison called this BROKEN
        because the date had rolled over.
        """
        r = checks.check_heartbeat_recent(7.5 * self.H)
        assert r["state"] == checks.OK

    def test_the_mushy97_deafness(self):
        """The alerter held a healthy socket and produced nothing for 1.5 days."""
        r = checks.check_heartbeat_recent(36 * self.H)
        assert r["state"] == checks.BROKEN
        assert "36" in r["detail"]

    def test_the_boundary_is_inclusive(self):
        assert checks.check_heartbeat_recent(25 * self.H)["state"] == checks.OK
        assert checks.check_heartbeat_recent(25 * self.H + 1)["state"] == checks.BROKEN

    def test_a_missed_heartbeat_is_caught_an_hour_after_it_was_due(self):
        """Grace is one hour: a heartbeat skipped at 17:00 is BROKEN by 18:00,
        not silent until the next midnight."""
        assert checks.check_heartbeat_recent(24 * self.H)["state"] == checks.OK
        assert checks.check_heartbeat_recent(26 * self.H)["state"] == checks.BROKEN

    def test_never_sent_is_broken(self):
        assert checks.check_heartbeat_recent(None)["state"] == checks.BROKEN


class TestDegradedCaptures:
    def test_none_is_ok(self):
        assert checks.check_degraded_captures(0)["state"] == checks.OK

    def test_any_degraded_capture_is_surfaced(self):
        """Waiting for a threshold is how 5.5 weeks happened."""
        r = checks.check_degraded_captures(1)
        assert r["state"] == checks.BROKEN
        assert "1 capture" in r["detail"]


class TestParkedDrafts:
    def test_none_is_ok(self):
        assert checks.check_parked_drafts(0)["state"] == checks.OK

    def test_the_mushy75_lost_session(self):
        r = checks.check_parked_drafts(1)
        assert r["state"] == checks.BROKEN
        assert "parked" in r["detail"]


class TestContainers:
    def test_steady_containers_are_ok(self):
        c = [{"name": "a", "restarting": False, "networks": 1}]
        assert checks.check_restarting(c)["state"] == checks.OK
        assert checks.check_networks_attached(c)["state"] == checks.OK

    def test_a_crash_looping_dependent_is_caught(self):
        """mushy-farmos-agent-1 sat Restarting for three days, logging the
        cause every 60s, while nothing watched restart counts."""
        c = [{"name": "mushy-farmos-agent-1", "restarting": True, "networks": 1}]
        r = checks.check_restarting(c)
        assert r["state"] == checks.BROKEN
        assert "mushy-farmos-agent-1" in r["detail"]

    def test_the_bone10_detached_containers(self):
        """These reported HEALTHY for three days. Their healthchecks curl
        localhost inside the container, which works with no network at all."""
        c = [{"name": "farmos-www-1", "restarting": False, "networks": 0}]
        r = checks.check_networks_attached(c)
        assert r["state"] == checks.BROKEN
        assert "farmos-www-1" in r["detail"]


class TestSummary:
    def _v(self, state, name="x"):
        return checks.verdict(name, state, "d")

    def test_all_ok(self):
        assert checks.summarise([self._v(checks.OK)])["state"] == checks.OK

    def test_broken_wins(self):
        s = checks.summarise([self._v(checks.OK, "a"), self._v(checks.BROKEN, "b")])
        assert s["state"] == checks.BROKEN
        assert s["broken"] == ["b"]

    def test_unknown_never_reads_as_ok(self):
        """A probe that could not run is not evidence the capability works.
        Conflating those two is the entire subject of this ticket."""
        s = checks.summarise([self._v(checks.OK, "a"), self._v(checks.UNKNOWN, "b")])
        assert s["state"] == checks.UNKNOWN
        assert s["unknown"] == ["b"]

    def test_unknown_does_not_mask_broken(self):
        s = checks.summarise([self._v(checks.UNKNOWN, "a"), self._v(checks.BROKEN, "b")])
        assert s["state"] == checks.BROKEN

    def test_alert_text_names_every_failure(self):
        s = checks.summarise([
            checks.verdict("signal_registration", checks.BROKEN, "not registered"),
            checks.verdict("whisper", checks.UNKNOWN, "no answer"),
            checks.verdict("bridge", checks.OK, "HTTP 200"),
        ])
        text = checks.alert_text(s)
        assert "BROKEN signal_registration" in text
        assert "UNKNOWN whisper" in text
        assert "bridge" not in text, "a healthy capability is not news"

    def test_alert_text_when_all_is_well(self):
        assert checks.alert_text(checks.summarise([self._v(checks.OK)])) == "all capabilities ok"


@pytest.mark.parametrize("fn,args", [
    (checks.check_signal_registration, (None, BOT)),
    (checks.check_http, ("x", None)),
    (checks.check_whisper, (None, None)),
    (checks.check_telemetry_fresh, (None,)),
    (checks.check_heartbeat_recent, (None,)),
    (checks.check_degraded_captures, (None,)),
    (checks.check_parked_drafts, (None,)),
    (checks.check_restarting, (None,)),
    (checks.check_networks_attached, (None,)),
])
def test_no_check_ever_returns_ok_on_missing_data(fn, args):
    """The failure mode this whole ticket is about: something that cannot see
    the truth reporting green."""
    assert fn(*args)["state"] != checks.OK


class TestAnUnreadableSourceIsNeverAFalseAlarm:
    """Found by negative-testing the live watchdog, not by reading the code.

    With the database unreachable, the heartbeat check reported BROKEN "no
    heartbeat has ever been sent" -- a false alarm, and precisely the
    conflation this ticket exists to stop. A watchdog that cries wolf when its
    own probe breaks trains the operator to ignore it, which is how you end up
    back at 7.8 silent days.
    """

    def test_unreadable_history_is_unknown(self):
        r = checks.check_heartbeat_recent(None, readable=False)
        assert r["state"] == checks.UNKNOWN
        assert "could not read" in r["detail"]

    def test_readable_and_never_sent_is_still_broken(self):
        """The real failure must survive the fix for the false alarm."""
        r = checks.check_heartbeat_recent(None, readable=True)
        assert r["state"] == checks.BROKEN

    def test_readable_defaults_to_true(self):
        assert checks.check_heartbeat_recent(3600)["state"] == checks.OK


# ---------------------------------------------------------------------------
# MUSHY-99: alert on change, not on every run
# ---------------------------------------------------------------------------

def _summary(**states):
    """A summary with one check per keyword, e.g. _summary(whisper=checks.BROKEN)."""
    return checks.summarise([checks.verdict(n, s, "detail") for n, s in states.items()])


def _prior(failures, notified_at=1000.0):
    return {"failures": failures, "notified_at": notified_at}


class TestNotifyOnChange:
    """The amplifier behind the 2026-08-20 night of buzzing.

    The heartbeat check's false alarm was one bug; `notify()` having no memory
    turned it into 68 identical high-priority pushes between midnight and
    morning. A channel that buzzes every 15 minutes gets silenced, and then the
    watchdog is worth nothing on the day it finds something new.
    """

    def test_a_new_fault_notifies_immediately(self):
        d = checks.decide_notification(_summary(whisper=checks.BROKEN), _prior({}), now=2000.0)
        assert d["notify"] is True
        assert d["reason"] == "entered"

    def test_the_same_standing_fault_does_not_notify_again(self):
        """96 identical pushes a day is what this ticket exists to stop."""
        prior = _prior({"whisper": checks.BROKEN})
        d = checks.decide_notification(_summary(whisper=checks.BROKEN), prior, now=1900.0)
        assert d["notify"] is False
        assert d["reason"] is None

    def test_a_standing_fault_is_repeated_after_the_reminder_interval(self):
        """Quiet must not become forgotten: a real fault still nags, slowly."""
        prior = _prior({"whisper": checks.BROKEN}, notified_at=1000.0)
        d = checks.decide_notification(
            _summary(whisper=checks.BROKEN), prior, now=1000.0 + 6 * 3600,
            reminder_after_s=6 * 3600)
        assert d["notify"] is True
        assert d["reason"] == "reminder"

    def test_a_second_fault_notifies_even_inside_the_quiet_window(self):
        """A NEW capability breaking is news, whatever else is already broken."""
        prior = _prior({"whisper": checks.BROKEN}, notified_at=1000.0)
        d = checks.decide_notification(
            _summary(whisper=checks.BROKEN, farmos_prod=checks.BROKEN), prior, now=1060.0)
        assert d["notify"] is True
        assert d["reason"] == "entered"

    def test_a_fault_changing_category_notifies(self):
        """broken -> unknown is a different fault, not the same one persisting."""
        prior = _prior({"signal_registration": checks.BROKEN})
        d = checks.decide_notification(
            _summary(signal_registration=checks.UNKNOWN), prior, now=1060.0)
        assert d["notify"] is True
        assert d["reason"] == "entered"

    def test_recovery_notifies_once(self):
        prior = _prior({"whisper": checks.BROKEN})
        d = checks.decide_notification(_summary(whisper=checks.OK), prior, now=1060.0)
        assert d["notify"] is True
        assert d["reason"] == "recovered"

    def test_a_healthy_farm_stays_silent(self):
        d = checks.decide_notification(_summary(whisper=checks.OK), _prior({}), now=99999.0)
        assert d["notify"] is False

    def test_the_new_state_carries_the_current_failures(self):
        d = checks.decide_notification(_summary(whisper=checks.BROKEN), _prior({}), now=2000.0)
        assert d["state"]["failures"] == {"whisper": checks.BROKEN}
        assert d["state"]["notified_at"] == 2000.0

    def test_a_suppressed_run_keeps_the_original_notify_time(self):
        """Otherwise the reminder clock resets every 15 minutes and never fires."""
        prior = _prior({"whisper": checks.BROKEN}, notified_at=1000.0)
        d = checks.decide_notification(_summary(whisper=checks.BROKEN), prior, now=1900.0)
        assert d["state"]["notified_at"] == 1000.0


class TestSilenceIsNeverAssumed:
    """Same rule as MUSHY-98's duplicate guard: a de-duplicator must never
    cause the failure it exists to prevent. If we cannot prove the farmer was
    already told, tell them.
    """

    def test_no_prior_state_notifies(self):
        d = checks.decide_notification(_summary(whisper=checks.BROKEN), None, now=2000.0)
        assert d["notify"] is True

    def test_an_unusable_prior_state_notifies(self):
        """A corrupt or half-written state file must not buy silence."""
        d = checks.decide_notification(_summary(whisper=checks.BROKEN), "garbage", now=2000.0)
        assert d["notify"] is True

    def test_a_missing_notify_time_notifies(self):
        prior = {"failures": {"whisper": checks.BROKEN}, "notified_at": None}
        d = checks.decide_notification(_summary(whisper=checks.BROKEN), prior, now=2000.0)
        assert d["notify"] is True


class TestNotificationPayload:
    def test_a_broken_capability_is_high_priority(self):
        p = checks.notification_payload(_summary(whisper=checks.BROKEN), "entered", {})
        assert p["priority"] == "high"
        assert "whisper" in p["body"]

    def test_an_unknown_only_run_is_not_high_priority(self):
        """"I could not see" must not shout as loudly as "it is broken"."""
        p = checks.notification_payload(_summary(whisper=checks.UNKNOWN), "entered", {})
        assert p["priority"] != "high"

    def test_a_reminder_says_it_is_still_broken(self):
        p = checks.notification_payload(_summary(whisper=checks.BROKEN), "reminder", {})
        assert "still" in p["title"].lower()

    def test_recovery_names_what_recovered(self):
        p = checks.notification_payload(
            _summary(whisper=checks.OK), "recovered", {"whisper": checks.BROKEN})
        assert "whisper" in p["body"]
        assert p["priority"] != "high"
