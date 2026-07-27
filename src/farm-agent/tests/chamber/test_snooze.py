"""
tests/chamber/test_snooze.py -- snooze/mute grammar (port of snooze.js).

Parses UNTRUSTED inbound farmer text. The no-raise contract is load-bearing:
ReceiveLoop's per-envelope try/except is a backstop, not a licence to throw.
"""

import pytest

from farm_agent.chamber import snooze

NOW = 1_700_000_000_000
HOUR = 3_600_000


# ---------------------------------------------------------------------------
# STRICT grammar
# ---------------------------------------------------------------------------


def test_strict_parses_type_and_duration():
    r = snooze.parse_snooze_command("snooze rh 4h", NOW)
    assert r["ok"] is True
    assert r["alert_type"] == "rh"
    assert r["duration_ms"] == 4 * HOUR
    assert r["until_ms"] == NOW + 4 * HOUR


def test_strict_is_case_insensitive_and_trims():
    r = snooze.parse_snooze_command("  SNOOZE Pi 30m  ", NOW)
    assert r["ok"] is True
    assert r["alert_type"] == "pi"          # normalised to lowercase
    assert r["duration_ms"] == 30 * 60_000


@pytest.mark.parametrize(
    "alert_type", ["rh", "sensor", "pi", "humidifier", "sht30", "scd41", "all"]
)
def test_strict_accepts_every_whitelisted_type(alert_type):
    r = snooze.parse_snooze_command(f"snooze {alert_type} 1h", NOW)
    assert r["ok"] is True
    assert r["alert_type"] == alert_type


@pytest.mark.parametrize(
    "token,ms",
    [("30m", 1_800_000), ("1h", 3_600_000), ("2h", 7_200_000),
     ("4h", 14_400_000), ("8h", 28_800_000), ("24h", 86_400_000)],
)
def test_valid_durations_match_node_exactly(token, ms):
    assert snooze.VALID_DURATIONS[token] == ms
    r = snooze.parse_snooze_command(f"snooze all {token}", NOW)
    assert r["duration_ms"] == ms


# ---------------------------------------------------------------------------
# SIMPLE grammar (Phase 25 R4)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("word", ["snooze", "mute", "quiet", "  MUTE  "])
def test_simple_bare_keyword_mutes_everything_for_24h(word):
    r = snooze.parse_snooze_command(word, NOW)
    assert r["ok"] is True
    assert r["alert_type"] == "all"
    assert r["duration_ms"] == 86_400_000
    assert r["ack_text"] == "alerts muted for 24h"


# ---------------------------------------------------------------------------
# Rejection paths
# ---------------------------------------------------------------------------


def test_unknown_alert_type_gets_fuzzy_help():
    """snooze-prefixed but unparseable -> the help reply (snooze.js:58)."""
    r = snooze.parse_snooze_command("snooze co2 4h", NOW)
    assert r["ok"] is False
    assert "snooze rh 4h" in r["reply"]


def test_invalid_duration_gets_fuzzy_help():
    r = snooze.parse_snooze_command("snooze rh 7h", NOW)
    assert r["ok"] is False
    assert r["reply"] is not None


def test_mute_with_arguments_is_not_a_command(chamber_config):
    """PARITY QUIRK, pinned deliberately (snooze.js:15).

    STRICT anchors on the literal `snooze`, so "mute rh 2h" matches nothing:
    not STRICT (wrong keyword), not SIMPLE (which needs a BARE mute), not the
    ^snooze fuzzy branch. Node returns {ok: False, reply: None} and the text
    falls through to the capture pipeline as ordinary farmer speech.

    This is arguably a UX bug, but it is NOT on the Phase-64 intentional-delta
    list. Reproduce it. If the farmer is ever bitten, fix it in both stacks or
    file it as a delta -- do not silently diverge here.
    """
    r = snooze.parse_snooze_command("mute rh 2h", NOW)
    assert r["ok"] is False
    assert r["reply"] is None


def test_ordinary_text_is_not_a_command():
    r = snooze.parse_snooze_command("harvested 3 bags of shiitake today", NOW)
    assert r["ok"] is False
    assert r["reply"] is None


# ---------------------------------------------------------------------------
# V5 / T-63-05: no-raise contract on hostile input
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "hostile",
    [
        "",
        "   ",
        None,
        12345,
        [],
        {},
        "\x00\x01\x02",
        "🍄" * 500,
        "snooze " + "a" * 10_000,
        "snooze rh 4h; DROP TABLE signal_capture;--",
        "snooze rh 4h\nsnooze all 24h",
        "../../etc/passwd",
        "{{7*7}}",
    ],
)
def test_never_raises_on_hostile_input(hostile):
    """T-63-05: returns a dict, always. Never raises, never returns None."""
    r = snooze.parse_snooze_command(hostile, NOW)
    assert isinstance(r, dict)
    assert r["ok"] is False


def test_newline_injection_cannot_smuggle_a_second_command():
    """The regexes are anchored with $ -- a trailing newline command is not parsed."""
    r = snooze.parse_snooze_command("snooze rh 4h\nsnooze all 24h", NOW)
    assert r["ok"] is False
