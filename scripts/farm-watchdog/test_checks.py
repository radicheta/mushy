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


class TestHeartbeatToday:
    def test_sent_today_is_ok(self):
        assert checks.check_heartbeat_today("2026-08-19", "2026-08-19")["state"] == checks.OK

    def test_the_mushy97_deafness(self):
        """The alerter held a healthy socket and produced nothing for 1.5 days."""
        r = checks.check_heartbeat_today("2026-08-17", "2026-08-19")
        assert r["state"] == checks.BROKEN
        assert "2026-08-17" in r["detail"]

    def test_never_sent_is_broken(self):
        assert checks.check_heartbeat_today(None, "2026-08-19")["state"] == checks.BROKEN

    def test_a_clock_skew_into_tomorrow_is_not_a_fault(self):
        """Comparing >= rather than == so a late-night boundary does not page."""
        assert checks.check_heartbeat_today("2026-08-20", "2026-08-19")["state"] == checks.OK


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
    (checks.check_heartbeat_today, (None, "2026-08-19")),
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

    With the database unreachable, heartbeat_today reported BROKEN "no
    heartbeat has ever been sent" -- a false alarm, and precisely the
    conflation this ticket exists to stop. A watchdog that cries wolf when its
    own probe breaks trains the operator to ignore it, which is how you end up
    back at 7.8 silent days.
    """

    def test_unreadable_history_is_unknown(self):
        r = checks.check_heartbeat_today(None, "2026-08-19", readable=False)
        assert r["state"] == checks.UNKNOWN
        assert "could not read" in r["detail"]

    def test_readable_and_never_sent_is_still_broken(self):
        """The real failure must survive the fix for the false alarm."""
        r = checks.check_heartbeat_today(None, "2026-08-19", readable=True)
        assert r["state"] == checks.BROKEN

    def test_readable_defaults_to_true(self):
        assert checks.check_heartbeat_today("2026-08-19", "2026-08-19")["state"] == checks.OK
