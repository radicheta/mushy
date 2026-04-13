"""Unit tests for farmos_agent.telemetry_query."""

import datetime
from unittest.mock import MagicMock, patch
import pytest

from farmos_agent.telemetry_query import query_daily_summary, TELEMETRY_TOPICS


def _make_db_conn(rows):
    """Build a mock psycopg2 connection returning the given rows."""
    cursor = MagicMock()
    cursor.fetchall.return_value = rows
    cursor.__enter__ = MagicMock(return_value=cursor)
    cursor.__exit__ = MagicMock(return_value=False)
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn, cursor


# ---------------------------------------------------------------------------
# Basic structure
# ---------------------------------------------------------------------------

def test_query_daily_summary_all_topics(sample_telemetry_rows):
    """Returns a dict keyed by all 4 expected topics with numeric values."""
    conn, _ = _make_db_conn(sample_telemetry_rows)
    result = query_daily_summary(conn, datetime.date(2026, 4, 12))

    assert set(result.keys()) == set(TELEMETRY_TOPICS)
    assert result['fc.humidity']['avg'] == pytest.approx(82.3, abs=0.01)
    assert result['fc.temperature']['avg'] == pytest.approx(21.4, abs=0.01)
    assert result['fc.co2']['avg'] == pytest.approx(845.0, abs=0.01)
    assert result['fc.humidifier']['avg'] == pytest.approx(0.45, abs=0.01)


def test_query_daily_summary_missing_topic():
    """Topics absent from DB rows have None values for all keys."""
    rows = [
        ('fc.co2',        845.00, 620.00, 1180.00, 1440),
        ('fc.humidifier', 0.45,   0.00,   1.00,    1440),
        ('fc.temperature', 21.4,  19.8,   23.1,    1440),
        # fc.humidity intentionally omitted
    ]
    conn, _ = _make_db_conn(rows)
    result = query_daily_summary(conn, datetime.date(2026, 4, 12))

    assert result['fc.humidity']['avg'] is None
    assert result['fc.humidity']['min'] is None
    assert result['fc.humidity']['max'] is None
    assert result['fc.humidity']['samples'] is None


# ---------------------------------------------------------------------------
# SQL safety
# ---------------------------------------------------------------------------

def test_parameterized_sql(sample_telemetry_rows):
    """cursor.execute is called with %s placeholders, not string interpolation."""
    conn, cursor = _make_db_conn(sample_telemetry_rows)
    query_daily_summary(conn, datetime.date(2026, 4, 12))

    assert cursor.execute.called
    args = cursor.execute.call_args[0]
    sql = args[0]
    params = args[1]
    # Must use parameterized placeholders
    assert '%s' in sql
    # Must pass two UTC datetime params (start and end)
    assert len(params) == 2
    assert isinstance(params[0], datetime.datetime)
    assert isinstance(params[1], datetime.datetime)
    assert params[0].tzinfo is not None
    assert params[1].tzinfo is not None


# ---------------------------------------------------------------------------
# Timezone boundary
# ---------------------------------------------------------------------------

def test_midnight_boundary_toronto(sample_telemetry_rows):
    """For America/Toronto (UTC-4 in summer), 2026-04-12 midnight = 2026-04-12T04:00Z."""
    conn, cursor = _make_db_conn(sample_telemetry_rows)
    query_daily_summary(conn, datetime.date(2026, 4, 12), timezone_str='America/Toronto')

    args = cursor.execute.call_args[0]
    start_utc, end_utc = args[1]

    # America/Toronto is UTC-4 during EDT (April 12 is in EDT)
    expected_start = datetime.datetime(2026, 4, 12, 4, 0, 0, tzinfo=datetime.timezone.utc)
    expected_end = datetime.datetime(2026, 4, 13, 4, 0, 0, tzinfo=datetime.timezone.utc)

    assert start_utc == expected_start
    assert end_utc == expected_end


def test_window_spans_exactly_24_hours(sample_telemetry_rows):
    """end_utc - start_utc is exactly 24 hours regardless of timezone."""
    conn, cursor = _make_db_conn(sample_telemetry_rows)
    query_daily_summary(conn, datetime.date(2026, 4, 12), timezone_str='America/Toronto')

    args = cursor.execute.call_args[0]
    start_utc, end_utc = args[1]
    delta = end_utc - start_utc
    assert delta == datetime.timedelta(days=1)
