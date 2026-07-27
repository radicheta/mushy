"""
tests/chamber/test_message.py -- farmer-facing formatting (port of message.js).

CHM-02 / SC2 lives here: test_hhmm_renders_montevideo_not_utc is the literal proof
that the Toronto-since-Phase-13 / actually-UTC bug is closed.
"""

import pytest

from farm_agent.chamber import message

# 2026-07-13T23:30:00Z -- 20:30 in America/Montevideo (UTC-3). Verified 2026-07-25.
TS_2330Z = 1_783_985_400_000
# 2026-07-13T12:15:00Z -- 09:15 Montevideo (the zero-padding case)
TS_0915 = 1_783_944_900_000
MIN = 60_000


# ---------------------------------------------------------------------------
# CHM-02 / SC2 -- the TZ fix
# ---------------------------------------------------------------------------


def test_hhmm_renders_montevideo_not_utc():
    """SC2: the farmer sees local time.

    message.js:50-52 did new Date(tsMs).toISOString().slice(11,16) -- always UTC,
    ignoring config.timezone entirely. The != assertion is the negative control:
    without it, a still-broken UTC implementation could pass by coincidence on a
    machine whose clock happened to line up.
    """
    assert message.hhmm(TS_2330Z, "America/Montevideo") == "20:30"
    assert message.hhmm(TS_2330Z, "America/Montevideo") != "23:30"


def test_hhmm_honours_a_different_zone():
    """The zone is a parameter, not a constant -- D-04 keeps the knob."""
    assert message.hhmm(TS_2330Z, "UTC") == "23:30"


def test_hhmm_is_zero_padded():
    """Single-digit hours keep the leading zero (strftime %H, like Node's slice)."""
    assert message.hhmm(TS_0915, "America/Montevideo") == "09:15"


def test_problem_body_renders_local_time(chamber_config):
    """The pi-offline template embeds hhmm -- it must be local too, not just the helper."""
    cfg = chamber_config()
    body = message.format_problem(
        alert_type="pi",
        severity="CRITICAL",
        fields={"last_seen_ms": TS_2330Z, "last_known": {"rh": 91.2, "ts_ms": TS_2330Z}},
        config=cfg,
        now_ms=TS_2330Z + 5 * MIN,
    )
    assert "20:30" in body
    assert "23:30" not in body


# ---------------------------------------------------------------------------
# fmt_num -- message.js:16-19
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        (94.39994, "94.4"),      # rounds to 1dp
        (90, "90"),              # integral -> no ".0"
        (90.0, "90"),
        (1.5000000000000013, "1.5"),
        (0, "0"),
        # PARITY CORRECTION (verified against node 2026-07-25): the plan predicted
        # "-0" here, but String(+(-0.04).toFixed(1)) is "0" -- JS String(-0) === "0".
        # Node really renders "0"; -0.06 is the case that keeps its sign ("-0.1").
        (-0.04, "0"),
        (-0.06, "-0.1"),
        (None, "?"),
        (float("nan"), "?"),
    ],
)
def test_fmt_num_parity(value, expected):
    assert message.fmt_num(value) == expected


def test_fmt_num_never_leaks_none_to_farmer():
    """Guard: no farmer-facing string may contain 'None' or 'null'."""
    for bad in (None, float("nan")):
        out = message.fmt_num(bad)
        assert "None" not in out and "null" not in out


# ---------------------------------------------------------------------------
# fmt_duration / fmt_relative -- message.js:24-46
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ms,expected",
    [
        (0, "0m 00s"),
        (6_000, "0m 06s"),          # the 2026-05-12 flap message shape
        (65_000, "1m 05s"),
        (59 * MIN, "59m 00s"),
        (60 * MIN, "1h 00m"),       # switches format at 60 min
        (95 * MIN, "1h 35m"),
        (25 * 60 * MIN, "25h 00m"),
    ],
)
def test_fmt_duration_parity(ms, expected):
    assert message.fmt_duration(ms) == expected


def test_fmt_duration_uses_js_half_up_rounding():
    """JS Math.round(1500/1000)==2. Python round(1.5)==2 but round(2.5)==2 (banker's).

    2500 ms must render 3s, not 2s.
    """
    assert message.fmt_duration(2_500) == "0m 03s"


@pytest.mark.parametrize(
    "delta_ms,expected",
    [(5_000, "5s ago"), (59_000, "59s ago"), (60_000, "1m ago"), (12 * MIN, "12m ago")],
)
def test_fmt_relative_parity(delta_ms, expected):
    now = 10_000_000
    assert message.fmt_relative(now - delta_ms, now) == expected


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


def test_problem_includes_dashboard_url_exactly_once(chamber_config):
    cfg = chamber_config()
    body = message.format_problem(
        alert_type="rh",
        severity="WARN",
        fields={"value": 84.2, "first_oob_ms": 10_000_000 - 12 * MIN},
        config=cfg,
        now_ms=10_000_000,
    )
    assert body.count(cfg.dashboard_url) == 1
    assert "84.2" in body
    assert "12m ago" in body


def test_recovery_reports_duration(chamber_config):
    cfg = chamber_config()
    body = message.format_recovery(
        alert_type="rh", fields={"value": 90.1}, duration_ms=95 * MIN, config=cfg
    )
    assert "RECOVERY" in body
    assert "1h 35m" in body


def test_no_em_dashes_in_any_farmer_string(chamber_config):
    """feedback_no_em_dashes_in_artifacts: em-dash is an LLM tell; farm strings use ? / --."""
    cfg = chamber_config()
    bodies = [
        message.format_problem(
            alert_type="rh", severity="WARN",
            fields={"value": 84.2, "first_oob_ms": None}, config=cfg, now_ms=10_000_000,
        ),
        message.format_recovery(
            alert_type="rh", fields={"value": 90.1}, duration_ms=MIN, config=cfg
        ),
        message.format_heartbeat(
            summary={"rh": 91.0, "temp": 21.0, "co2": 800,
                     "humidifier": "OFF", "humidifier_cycles": 4, "pi_last_seen_sec": 3},
            config=cfg, now_ms=10_000_000,
        ),
    ]
    for b in bodies:
        assert "—" not in b and "–" not in b
