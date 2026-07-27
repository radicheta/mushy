"""
tests/chamber/test_deps.py -- Phase 63 CHM-01/CHM-02 dependency smoke.

Proves the two chamber-only runtime deps are installed AND functional:
  - websockets: the bridge WS client transport (Plan 06)
  - tzdata:     the IANA zone database backing ZoneInfo (D-04 / CHM-02)

The tzdata assertion deliberately checks ZoneInfo RESOLUTION, not `import tzdata`.
zoneinfo falls back to the system tz database, so on a dev host with
/usr/share/zoneinfo an import-only test passes whether or not the dependency is
declared -- and then ZoneInfoNotFoundError lands in the slim container instead.
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def test_websockets_importable():
    """Plan 06's WS bridge client transport is available."""
    import websockets  # noqa: PLC0415

    assert hasattr(websockets, "connect")


def test_montevideo_zone_resolves():
    """D-04: America/Montevideo must resolve, not raise ZoneInfoNotFoundError."""
    tz = ZoneInfo("America/Montevideo")
    assert str(tz) == "America/Montevideo"


def test_montevideo_offset_is_utc_minus_3():
    """UYT is UTC-3 year-round (Uruguay abolished DST in 2015). Pins SC2 arithmetic.

    2026-07-25 12:00 UTC must render as 09:00 local.
    """
    utc_noon = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
    local = utc_noon.astimezone(ZoneInfo("America/Montevideo"))
    assert local.hour == 9
    assert local.utcoffset().total_seconds() == -3 * 3600
