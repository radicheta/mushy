"""
chamber/message.py -- farmer-facing message formatting. Port of message.js.

CHM-02 / D-04: every timestamp renders through ZoneInfo(config.timezone), which
defaults to America/Montevideo. The Node original called
`new Date(tsMs).toISOString().slice(11,16)` (message.js:50-52) -- always UTC --
while config.timezone sat unused and defaulted to America/Toronto anyway. Both
halves were wrong; both are fixed. This is a PRE-DECLARED intentional parity
delta for Phase 64.

Farmer-facing string rules: no em-dashes (feedback_no_em_dashes_in_artifacts),
1-decimal rounding (feedback_round_farmer_numbers), never a raw None.
"""

from __future__ import annotations

import math
from datetime import datetime
from zoneinfo import ZoneInfo

# message.js:3-10
ALERT_TITLES = {
    "pi": "Pi offline",
    "sensor": "Sensor ERROR",
    "rh": "RH out of band",
    "humidifier": "Humidifier stuck",
    "sht30": "Primary Humidity Sensor offline",
    "scd41": "CO2 Sensor offline",
}


def _js_round(x: float) -> int:
    """JS Math.round: half-UP. Python's round() is banker's (round(2.5) == 2)."""
    return math.floor(x + 0.5)


def fmt_num(n) -> str:
    """Round to 1 decimal and strip a trailing '.0'. Port of message.js:16-19.

    - None / NaN -> '?' so a farmer never sees 'null' or 'undefined'
    - 94.39994 -> '94.4'
    - 90       -> '90'
    - 1.5000000000000013 -> '1.5'

    Negative-zero note: Node evaluates String(+(-0.04).toFixed(1)); the unary +
    yields -0 and JS String(-0) is "0", so -0.04 renders "0" (NOT "-0"). Python's
    int(-0.0) is 0, so str(int(r)) reproduces that for free. Verified against node
    2026-07-25. -0.06 still renders "-0.1" -- the sign survives when the magnitude does.
    """
    if n is None:
        return "?"
    try:
        v = float(n)
    except (TypeError, ValueError):
        return "?"
    if math.isnan(v):
        return "?"
    r = round(v, 1)
    if r == int(r):
        return str(int(r))
    return str(r)


def fmt_duration(ms: float) -> str:
    """Elapsed ms as 'Xm YYs', or 'Xh YYm' at >= 60 min. Port of message.js:24-34.

    Example: 6_000 -> '0m 06s'; 95 min -> '1h 35m'.
    """
    total_sec = _js_round(ms / 1000)
    total_min = total_sec // 60
    sec = total_sec % 60
    if total_min < 60:
        return f"{total_min}m {sec:02d}s"
    hours = total_min // 60
    minutes = total_min % 60
    return f"{hours}h {minutes:02d}m"


def fmt_relative(past_ms: int, now_ms: int) -> str:
    """'12m ago' / '5s ago'. Port of message.js:40-46."""
    diff_sec = _js_round((now_ms - past_ms) / 1000)
    if diff_sec < 60:
        return f"{diff_sec}s ago"
    return f"{diff_sec // 60}m ago"


def hhmm(ts_ms: int, tz_name: str) -> str:
    """Render a UTC epoch-ms timestamp as zero-padded LOCAL HH:MM (the D-04 fix).

    Port of message.js:50-52, with the bug removed. Every farmer-facing call site
    MUST route through this -- never format via timezone.utc, never isoformat().

    Example: 2026-07-13T23:30:00Z with 'America/Montevideo' -> '20:30'.
    """
    return datetime.fromtimestamp(ts_ms / 1000, tz=ZoneInfo(tz_name)).strftime("%H:%M")


def format_problem(*, alert_type: str, severity: str, fields: dict, config, now_ms: int) -> str:
    """PROBLEM message. Port of message.js:65-111. Includes dashboard_url exactly once."""
    title = ALERT_TITLES.get(alert_type, alert_type)
    body = f"[PROBLEM · {severity}] FC-1 · {title}\n"

    if alert_type == "rh":
        body += (
            f"Now: {fmt_num(fields.get('value'))}% · "
            f"target {fmt_num(config.rh_target)}±{fmt_num(config.rh_band)}%\n"
        )
        if fields.get("first_oob_ms") is not None:
            body += f"First OOB: {fmt_relative(fields['first_oob_ms'], now_ms)}\n"

    elif alert_type == "pi":
        # Phase 46 D-05/D-06: chamber-level framing. The farmer needs "FC-1 is dark,
        # chamber uncontrolled" up front, not a per-sensor reading.
        last_known = fields.get("last_known")
        last_seen_ms = fields.get("last_seen_ms")
        if last_known is not None and last_known.get("ts_ms") is not None:
            age_min = _js_round((now_ms - last_known["ts_ms"]) / 60_000)
        elif last_seen_ms is not None:
            age_min = _js_round((now_ms - last_seen_ms) / 60_000)
        else:
            age_min = None
        age_str = f"{age_min}m" if age_min is not None else "?"
        if last_known is not None:
            body += (
                f"FC-1 offline ?? no telemetry {age_str}. chamber uncontrolled. "
                f"last RH {fmt_num(last_known.get('rh'))}% @ "
                f"{hhmm(last_known['ts_ms'], config.timezone)}.\n"
            )
        else:
            body += (
                f"FC-1 offline ?? no telemetry {age_str}. chamber uncontrolled. "
                "no recent samples.\n"
            )

    elif alert_type in ("sht30", "scd41"):
        # Backlog 999.18: last_seen_ms is bootstrapped from alerter boot, not the real
        # outage onset, so any number printed here would mislead. Deliberately no body
        # line until fc_controller publishes a true wall-clock last-fresh timestamp.
        pass

    elif alert_type == "sensor":
        if fields and fields.get("message"):
            body += f"{fields['message']}\n"

    elif alert_type == "humidifier":
        on_since = (fields or {}).get("on_since_ms")
        rh_at_on = (fields or {}).get("rh_at_on")
        current_rh = (fields or {}).get("current_rh")
        if on_since is not None:
            body += f"On for: {fmt_duration(now_ms - on_since)}\n"
        if rh_at_on is not None and current_rh is not None:
            body += f"RH at ON: {fmt_num(rh_at_on)}% · Now: {fmt_num(current_rh)}%\n"

    return body + f"Open: {config.dashboard_url}"


def format_recovery(*, alert_type: str, fields: dict, duration_ms: int | None, config) -> str:
    """RECOVERY message. Port of message.js:122-136."""
    title = ALERT_TITLES.get(alert_type, alert_type)
    body = f"[RECOVERY] FC-1 · {title} back\n"
    if alert_type == "rh" and fields and fields.get("value") is not None:
        body += f"Now: {fmt_num(fields['value'])}%\n"
    if duration_ms is not None:
        body += f"Was OOB for {fmt_duration(duration_ms)}\n"
    return body + f"Open: {config.dashboard_url}"


def format_heartbeat(*, summary: dict, config, now_ms: int) -> str:
    """Daily HEARTBEAT message. Port of message.js:143-153."""
    co2 = summary.get("co2")
    body = "[HEARTBEAT] FC-1 watchdog alive\n"
    body += (
        f"RH: {fmt_num(summary.get('rh'))}%  ·  "
        f"Temp: {fmt_num(summary.get('temp'))}°C  ·  "
        f"CO2: {'?' if co2 is None else co2} ppm\n"
    )
    body += (
        f"Humidifier: {summary.get('humidifier')} "
        f"(cycled {summary.get('humidifier_cycles')}× in last 24h)\n"
    )
    if summary.get("pi_last_seen_sec") is not None:
        body += f"Pi last seen: {summary['pi_last_seen_sec']} seconds ago\n"
    return body + f"Open: {config.dashboard_url}"
