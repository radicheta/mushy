"""
chamber/snooze.py -- snooze/mute command grammar. Port of src/agents/alerter/src/snooze.js.

Grammar PARSING only. Trigger DETECTION (does this text look like a command at all)
already happened upstream in signal_io.router._COMMAND_RE, and sender whitelisting
happened in ReceiveLoop.tick. This module adds no ingestion path (T-63-06).

The regexes are ported verbatim, anchored at both ends. Do not loosen them for
convenience: they are the V5 input-validation boundary for untrusted farmer text.
"""

from __future__ import annotations

import re

# snooze.js:3
VALID_ALERT_TYPES = ["rh", "sensor", "pi", "humidifier", "sht30", "scd41", "all"]

# snooze.js:5-12
VALID_DURATIONS = {
    "30m": 30 * 60_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "8h": 28_800_000,
    "24h": 86_400_000,
}

# snooze.js:15 -- strict whitelist, anchored start/end, no extra content allowed.
# NOTE the literal `snooze`: "mute rh 2h" deliberately does NOT match (see the
# pinned parity test in tests/chamber/test_snooze.py).
STRICT = re.compile(
    r"^snooze\s+(rh|sensor|pi|humidifier|sht30|scd41|all)\s+(30m|1h|2h|4h|8h|24h)\s*$",
    re.IGNORECASE,
)

# snooze.js:18 -- Phase 25 R4: a BARE snooze/mute/quiet means 24h, all types.
SIMPLE = re.compile(r"^\s*(snooze|mute|quiet)\s*$", re.IGNORECASE)

# snooze.js:58 -- snooze-prefixed but malformed gets the help reply.
_SNOOZE_PREFIX = re.compile(r"^snooze\b", re.IGNORECASE)

_FUZZY_REPLY = (
    "Sorry, didn't get that. Try: snooze rh 4h\n"
    "Valid alert types: rh, sensor, pi, humidifier, sht30, scd41, all\n"
    "Valid durations: 30m, 1h, 2h, 4h, 8h, 24h"
)


def parse_snooze_command(text, now_ms: int) -> dict:
    """Parse a snooze/mute command. Port of snooze.js:35-61.

    Returns one of:
      {"ok": True, "alert_type": str, "duration_ms": int, "until_ms": int, ...}
      {"ok": False, "reply": str}    -- snooze-prefixed but malformed: send help
      {"ok": False, "reply": None}   -- not a command: fall through to capture

    Never raises and never returns None, whatever the input (T-63-05). A
    non-string (or unstringable) input is simply "not a command".
    """
    if not isinstance(text, str):
        return {"ok": False, "reply": None}
    t = text.strip()

    # R4 simple grammar: bare snooze/mute/quiet -> 24h all-types mute, with ack.
    if SIMPLE.match(t):
        duration_ms = VALID_DURATIONS["24h"]
        return {
            "ok": True,
            "alert_type": "all",
            "duration_ms": duration_ms,
            "until_ms": now_ms + duration_ms,
            "ack_text": "alerts muted for 24h",
        }

    m = STRICT.match(t)
    if m:
        alert_type = m.group(1).lower()
        duration_ms = VALID_DURATIONS[m.group(2).lower()]
        return {
            "ok": True,
            "alert_type": alert_type,
            "duration_ms": duration_ms,
            "until_ms": now_ms + duration_ms,
        }

    if _SNOOZE_PREFIX.match(t):
        return {"ok": False, "reply": _FUZZY_REPLY}

    # Anything else -- let the receive loop fan out to the capture pipeline.
    return {"ok": False, "reply": None}
