"""MUSHY-94: a farm log shows the date the farmer actually said.

Date-only farm events were committed at UTC midnight. farmOS renders in the
farm's timezone (prod `system.date` has timezone.default = America/Montevideo,
UTC-3), so every one of them displayed at 21:00 on the PREVIOUS calendar day.
The farmer says "August 16", the log is named for August 16, and the timestamp
column next to that name reads August 15.

The fix stores a date-only event at LOCAL midnight, so the calendar date the
farmer stated is the calendar date that renders.

ASCII-only. No em-dashes.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from farm_agent.farmos import farm_time
from farm_agent.farmos.farm_time import (
    DEFAULT_TZ,
    configure,
    date_only_epoch,
    epoch_for_event_timestamp,
    farm_tz,
    ymd,
)


@pytest.fixture(autouse=True)
def _restore_zone():
    """farm_time holds process-wide state; do not leak a zone between cases."""
    previous = farm_time._tz_name
    yield
    configure(previous)


def _tz(name):
    configure(name)

# The exact prod rows from the ticket: logs 272/274/276, the Aug 16 inoc session.
_UTC_MIDNIGHT_AUG16 = 1786838400


def _renders_as(epoch: int) -> str:
    """The calendar date farmOS shows the farmer for this stored timestamp."""
    return datetime.fromtimestamp(epoch, tz=farm_tz()).strftime("%Y-%m-%d")


class TestFarmTz:
    def test_defaults_to_montevideo(self):
        configure(DEFAULT_TZ)
        assert str(farm_tz()) == "America/Montevideo"

    def test_honours_the_zone_the_tenant_configures(self):
        _tz("America/Toronto")
        assert str(farm_tz()) == "America/Toronto"

    def test_falls_back_to_utc_on_an_unknown_zone(self):
        """A typo in TZ must not take the commit path down."""
        _tz("Mars/Olympus_Mons")
        assert farm_tz() is timezone.utc

    def test_an_empty_zone_is_treated_as_unset(self):
        """Docker sets TZ= (empty) more often than it unsets it."""
        _tz("")
        assert str(farm_tz()) == "America/Montevideo"


class TestDateOnlyEpoch:
    def test_stored_at_local_midnight_not_utc_midnight(self):
        _tz("America/Montevideo")
        # 03:00Z is midnight in UYT.
        assert date_only_epoch("2026-08-16") == _UTC_MIDNIGHT_AUG16 + 3 * 3600

    def test_the_regression_the_ticket_was_filed_for(self):
        """The Aug 16 session displayed as Aug 15. It must display as Aug 16."""
        _tz("America/Montevideo")
        assert _renders_as(_UTC_MIDNIGHT_AUG16) == "2026-08-15"   # the bug
        assert _renders_as(date_only_epoch("2026-08-16")) == "2026-08-16"

    @pytest.mark.parametrize("tz_name", [
        "America/Montevideo",   # UTC-3, behind UTC: the farm today
        "America/Toronto",      # UTC-4/-5, the legacy alerter TZ
        "Asia/Tokyo",           # UTC+9, AHEAD of UTC: the case UTC midnight got right
        "UTC",
    ])
    def test_the_stated_date_is_the_rendered_date_in_any_zone(self, tz_name):
        _tz(tz_name)
        for date_str in ("2026-08-16", "2026-01-01", "2026-12-31"):
            assert _renders_as(date_only_epoch(date_str)) == date_str

    def test_survives_a_dst_transition(self):
        """Toronto springs forward on 2026-03-08; local midnight still exists."""
        _tz("America/Toronto")
        assert _renders_as(date_only_epoch("2026-03-08")) == "2026-03-08"

    def test_garbage_date_returns_none_rather_than_guessing(self):
        _tz("America/Montevideo")
        assert date_only_epoch("not-a-date") is None
        assert date_only_epoch("") is None
        assert date_only_epoch(None) is None


class TestEpochForEventTimestamp:
    """The extractor emits date-granular events as ISO strings at T00:00:00Z.

    Exact UTC midnight is the date-only marker: the prompt asks for a date and
    every example in it is midnight. A real clock time must survive untouched.
    """

    def test_utc_midnight_is_read_as_a_date_and_moved_to_local_midnight(self):
        _tz("America/Montevideo")
        got = epoch_for_event_timestamp("2026-08-16T00:00:00Z")
        assert _renders_as(got) == "2026-08-16"
        assert got == _UTC_MIDNIGHT_AUG16 + 3 * 3600

    def test_the_plus_zero_offset_spelling_is_the_same_marker(self):
        _tz("America/Montevideo")
        assert epoch_for_event_timestamp("2026-08-16T00:00:00+00:00") == \
            epoch_for_event_timestamp("2026-08-16T00:00:00Z")

    def test_a_real_clock_time_is_left_exactly_where_it_was(self):
        """If the farmer gave a time, that time is data. Do not shift it."""
        _tz("America/Montevideo")
        expected = int(datetime.fromisoformat("2026-05-15T14:30:00+00:00").timestamp())
        assert epoch_for_event_timestamp("2026-05-15T14:30:00.000Z") == expected

    def test_a_timestamp_already_carrying_a_local_offset_is_left_alone(self):
        """Already local midnight. Shifting again would land on the next day."""
        _tz("America/Montevideo")
        got = epoch_for_event_timestamp("2026-08-16T00:00:00-03:00")
        assert _renders_as(got) == "2026-08-16"
        assert got == _UTC_MIDNIGHT_AUG16 + 3 * 3600

    def test_unparseable_returns_none(self):
        _tz("America/Montevideo")
        assert epoch_for_event_timestamp("whenever") is None
        assert epoch_for_event_timestamp(None) is None


class TestYmd:
    def test_renders_in_the_farm_timezone_not_utc(self):
        """A log committed at 01:00Z belongs to the previous local day.

        This is the naming half of the same defect: a name rendered in UTC and
        a timestamp rendered locally can disagree on the same row.
        """
        _tz("America/Montevideo")
        one_am_utc_aug20 = 1787187600  # 2026-08-20T01:00:00Z = Aug 19 22:00 UYT
        assert ymd(one_am_utc_aug20) == "2026-08-19"

    def test_a_date_only_log_names_the_stated_date(self):
        _tz("America/Montevideo")
        assert ymd(date_only_epoch("2026-08-16")) == "2026-08-16"
