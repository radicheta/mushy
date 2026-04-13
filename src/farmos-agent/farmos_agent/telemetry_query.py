"""
TimescaleDB daily aggregation queries for the FarmOS daily report agent.

Uses parameterized SQL exclusively to prevent SQL injection (T-13-01).
Midnight boundaries are computed in local time and converted to UTC.
"""

import datetime
from zoneinfo import ZoneInfo

TELEMETRY_TOPICS = [
    'fc.co2',
    'fc.humidifier',
    'fc.humidity',
    'fc.temperature',
]

_AGGREGATION_SQL = """
SELECT
    topic,
    ROUND(AVG(value)::numeric, 2) AS avg,
    ROUND(MIN(value)::numeric, 2) AS min,
    ROUND(MAX(value)::numeric, 2) AS max,
    COUNT(*) AS samples
FROM telemetry
WHERE time >= %s
  AND time <  %s
  AND topic IN ('fc.humidity', 'fc.temperature', 'fc.co2', 'fc.humidifier')
GROUP BY topic
ORDER BY topic
"""


def query_daily_summary(
    db_conn,
    report_date: datetime.date,
    timezone_str: str = 'America/Toronto',
) -> dict:
    """
    Query TimescaleDB for daily aggregated telemetry over a midnight-to-midnight window.

    Computes the local midnight boundary for report_date in timezone_str,
    converts to UTC, and uses parameterized SQL with %s placeholders (T-13-01).

    Args:
        db_conn: psycopg2 connection (or compatible mock)
        report_date: the calendar date to aggregate (local time)
        timezone_str: IANA timezone string, default 'America/Toronto'

    Returns:
        dict keyed by topic with {'avg', 'min', 'max', 'samples'} values.
        Topics absent from DB results have None values for all keys.
    """
    tz = ZoneInfo(timezone_str)
    local_midnight = datetime.datetime(
        report_date.year,
        report_date.month,
        report_date.day,
        tzinfo=tz,
    )
    start_utc = local_midnight.astimezone(datetime.timezone.utc)
    end_utc = (local_midnight + datetime.timedelta(days=1)).astimezone(datetime.timezone.utc)

    # Initialize result dict with None for all expected topics
    result: dict = {
        topic: {'avg': None, 'min': None, 'max': None, 'samples': None}
        for topic in TELEMETRY_TOPICS
    }

    with db_conn.cursor() as cursor:
        cursor.execute(_AGGREGATION_SQL, (start_utc, end_utc))
        rows = cursor.fetchall()

    for row in rows:
        topic, avg, min_val, max_val, samples = row
        if topic in result:
            result[topic] = {
                'avg': float(avg) if avg is not None else None,
                'min': float(min_val) if min_val is not None else None,
                'max': float(max_val) if max_val is not None else None,
                'samples': int(samples) if samples is not None else None,
            }

    return result
