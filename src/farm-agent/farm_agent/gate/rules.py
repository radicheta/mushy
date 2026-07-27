"""
gate/rules.py -- Pure rule prefilter for the event gate.

Port of src/agents/alerter/src/event-gate/rules.js (rulePositive / ruleNegative).
No I/O, no async, no farm_agent imports. Module-level compiled regexes.

Design:
  rule_positive  -- fast-path obvious events (attachment, long text, strain code, block name)
  rule_negative  -- short ack within 30 min of attestation_kickoff

Security:
  T-59-02-01: no logging of env_ctx text/transcript (pure function, no I/O at all).
"""

from __future__ import annotations

import re
from datetime import datetime

# ---------------------------------------------------------------------------
# Module-level compiled regexes (verbatim from rules.js)
# ---------------------------------------------------------------------------

STRAIN_RE = re.compile(r"\b[A-Z]{2,4}\b")
BLOCK_RE = re.compile(r"\b\d{6}_[A-Z]{2,4}_\d+\b")

# re.fullmatch() anchors at both start and end, making the intent self-documenting.
# The $ in the pattern is retained for clarity (no behavior change).
ACK_RE = re.compile(r"^(ok|yes|got it|thanks|gracias|si|sí|👍)$", re.IGNORECASE)

# 30-minute window in milliseconds (verbatim from rules.js)
_WINDOW_MS = 30 * 60 * 1000


# ---------------------------------------------------------------------------
# rule_positive
# ---------------------------------------------------------------------------


def rule_positive(env_ctx: dict) -> dict:
    """Fast-path events from obvious signals. Port of rules.js:rulePositive.

    Decision order (mirrors Node verbatim):
      1. attachment -> image_or_audio
      2. body > 200 chars -> long_text
      3. STRAIN_RE match -> strain_code
      4. BLOCK_RE match -> block_name
      else -> {hit: False}

    body = env_ctx.get("text") or env_ctx.get("transcript") or ""
    (text OR transcript, not concatenation)
    """
    if (env_ctx.get("attachmentCount") or 0) > 0:
        return {"hit": True, "kind": "image_or_audio"}
    body = env_ctx.get("text") or env_ctx.get("transcript") or ""
    if len(body) > 200:
        return {"hit": True, "kind": "long_text"}
    if STRAIN_RE.search(body):
        return {"hit": True, "kind": "strain_code"}
    if BLOCK_RE.search(body):
        return {"hit": True, "kind": "block_name"}
    return {"hit": False}


# ---------------------------------------------------------------------------
# rule_negative
# ---------------------------------------------------------------------------


def rule_negative(
    env_ctx: dict,
    last_bot_outbound: dict | None,
    now_ms: int,
) -> dict:
    """Detect short acks within 30 min of attestation_kickoff. Port of rules.js:ruleNegative.

    Guards (all must pass to fire):
      1. last_bot_outbound exists and intent == 'attestation_kickoff'
      2. sent_at is present and parseable
      3. now_ms - sent_at_ms <= 30 * 60 * 1000  (within 30-minute window)
      4. body length < 40  (Pitfall 3: >= 40 does NOT fire negative rule)
      5. ACK_RE matches body fully (Pitfall 4: $ anchor required for re.match)

    Returns {hit: True, kind: 'short_ack_within_30m'} or {hit: False}.
    """
    if not last_bot_outbound or last_bot_outbound.get("intent") != "attestation_kickoff":
        return {"hit": False}

    sent_at = last_bot_outbound.get("sent_at")
    if not sent_at:
        return {"hit": False}

    # sent_at may be a timezone-aware datetime (psycopg3 materializes timestamptz
    # columns as aware datetime objects) or an ISO 8601 string (tests / JSON).
    if isinstance(sent_at, datetime):
        sent_at_ms = int(sent_at.timestamp() * 1000)
    else:
        # Pitfall 8: Python < 3.11 fromisoformat does not handle trailing 'Z'.
        # .replace("Z", "+00:00") is zero-cost insurance on all Python 3.x versions.
        sent_at_ms = int(
            datetime.fromisoformat(str(sent_at).replace("Z", "+00:00")).timestamp() * 1000
        )

    if now_ms - sent_at_ms > _WINDOW_MS:
        return {"hit": False}

    body = (env_ctx.get("text") or "").strip()

    # Pitfall 3: >= 40, NOT > 40.  A 40-char body is too long to be a short ack.
    if len(body) >= 40:
        return {"hit": False}

    if not ACK_RE.fullmatch(body):
        return {"hit": False}

    return {"hit": True, "kind": "short_ack_within_30m"}
