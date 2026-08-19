"""farm_agent/farmos/farm_time.py -- the farm's calendar day (MUSHY-94).

A farm event is a DATE, not an instant. The farmer says "August 16"; the
extractor emits `2026-08-16T00:00:00Z`; farmOS stores a unix timestamp and
renders it in the site timezone (prod `system.date` has
timezone.default = "America/Montevideo", UTC-3).

Committing that date at UTC midnight therefore rendered it at 21:00 on the
PREVIOUS calendar day: the log named `inoc 2026-08-16` showed a timestamp of
2026-08-15. The name and its own timestamp contradicted each other on the same
row, and the name was the one that was right.

This module is the single place that answers two questions:

  * date -> instant  (`date_only_epoch`, `epoch_for_event_timestamp`)
  * instant -> date  (`ymd`)

Both go through `farm_tz()`, so a log's stored timestamp and its rendered name
cannot disagree about which day it was.

TZ, not a new variable: the alerter-py container already runs with
TZ=America/Montevideo (docker-compose.override.yml), and chamber/config.py
already reads it with the same default. Adding FARM_TIMEZONE would have created
a second source of truth for one fact.

The zone arrives by INJECTION. FND-02 (tests/test_tenancy.py) holds that only
tenant.py, boot.py and chamber/config.py may read process configuration
directly; the commit path is leaf code and reads none. boot calls configure()
once with the already-loaded TenantConfig.farm_timezone. Until it does, the
default applies, so a caller that never configures still gets the farm's real
zone rather than the UTC-midnight bug back.

ASCII-only. No em-dashes. Never-throws.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TZ = "America/Montevideo"

_tz_name = DEFAULT_TZ


def configure(tz_name: str) -> None:
    """Set the farm's timezone. Called once at boot from TenantConfig."""
    global _tz_name
    _tz_name = tz_name or DEFAULT_TZ


def farm_tz():
    """The timezone the farm's calendar day is measured in.

    Falls back to UTC on an unknown zone name rather than raising: a typo in the
    tenant's zone must not take the commit path down. UTC is the pre-MUSHY-94
    behaviour, so the failure mode is the old bug, not a lost log.
    """
    try:
        return ZoneInfo(_tz_name)
    except (ZoneInfoNotFoundError, ValueError, KeyError, OSError):
        return timezone.utc


def date_only_epoch(date_str) -> int | None:
    """"YYYY-MM-DD" -> unix seconds at LOCAL midnight. None if unparseable.

    None rather than a fallback to now(): a caller that wants "now" can say so,
    and silently dating a farm event to the moment it failed to parse is how a
    wrong date gets into the record without anyone noticing.
    """
    if not isinstance(date_str, str):
        return None
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return None
    return int(datetime.combine(d, time.min, tzinfo=farm_tz()).timestamp())


def epoch_for_event_timestamp(iso) -> int | None:
    """Extractor `event_timestamp` (ISO 8601) -> unix seconds. None if unparseable.

    Exact UTC midnight is the date-only marker. The extraction prompt asks for
    "ISO 8601 with timezone" on an event the farmer describes by day, and every
    example in it is `T00:00:00Z`; there is no separate date-only flag in the
    schema to read instead.

    Anything else is a real clock time the farmer gave us, and is data. It is
    returned unshifted -- including a timestamp that already carries a local
    offset, which is midnight in the farm's own zone and would land on the next
    day if shifted a second time.
    """
    if not isinstance(iso, str):
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if dt.utcoffset() == timedelta(0) and dt.time() == time.min:
        return date_only_epoch(dt.date().isoformat())
    return int(dt.timestamp())


def ymd(epoch) -> str:
    """Unix seconds -> "YYYY-MM-DD" on the farm's calendar.

    The naming half of the same defect: a log name rendered in UTC beside a
    timestamp rendered locally can disagree on the same row.
    """
    return datetime.fromtimestamp(epoch, tz=farm_tz()).strftime("%Y-%m-%d")
