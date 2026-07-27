"""
Unit tests for farm_agent.gate.rules -- rule_positive / rule_negative.

Port-fidelity tests:
  - test_rule_negative_40char_body_does_not_fire  (Pitfall 3: >= 40, not > 40)
  - test_rule_negative_phantom_ack_does_not_fire  (Pitfall 4: ACK_RE $ anchor)
  - test_rule_negative_outside_30min_does_not_fire
  - test_rule_negative_sent_at_datetime_fires     (CR-02: psycopg3 returns datetime, not str)

All tests are synchronous (rules are pure functions, no I/O).
"""

import datetime as dt

import pytest

from farm_agent.gate.rules import rule_negative, rule_positive

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW_MS = 1_700_000_000_000  # 2023-11-14T22:13:20+00:00
_SENT_AT_30MIN_AGO = "2023-11-14T21:43:20+00:00"  # exactly 30 min before _NOW_MS
_SENT_AT_29MIN_AGO = "2023-11-14T21:44:20+00:00"  # 29 min before _NOW_MS
_SENT_AT_31MIN_AGO = "2023-11-14T21:42:20+00:00"  # 31 min before _NOW_MS


def _kickoff(sent_at: str = _SENT_AT_29MIN_AGO) -> dict:
    return {"intent": "attestation_kickoff", "sent_at": sent_at}


# ---------------------------------------------------------------------------
# rule_positive: hit paths
# ---------------------------------------------------------------------------


def test_rule_positive_attachment():
    """attachmentCount > 0 -> {hit: True, kind: 'image_or_audio'}."""
    result = rule_positive({"attachmentCount": 1, "text": "hi"})
    assert result["hit"] is True
    assert result["kind"] == "image_or_audio"


def test_rule_positive_attachment_overrides_text():
    """Attachment check fires first even if body is short."""
    result = rule_positive({"attachmentCount": 2, "text": "ok"})
    assert result["hit"] is True
    assert result["kind"] == "image_or_audio"


def test_rule_positive_long_text():
    """text length > 200 -> {hit: True, kind: 'long_text'}."""
    result = rule_positive({"text": "a" * 201})
    assert result["hit"] is True
    assert result["kind"] == "long_text"


def test_rule_positive_long_text_uses_transcript_fallback():
    """Falls back to transcript when text is absent."""
    result = rule_positive({"transcript": "b" * 201})
    assert result["hit"] is True
    assert result["kind"] == "long_text"


def test_rule_positive_exactly_200_chars_is_not_long():
    """body length == 200 does NOT trigger long_text (requires > 200)."""
    result = rule_positive({"text": "a" * 200})
    # Could still hit strain_code if 'A' repeated 200x -- no uppercase single letter pattern
    # 'a' * 200 has no uppercase, so check that it's not long_text
    assert result.get("kind") != "long_text"


def test_rule_positive_strain_code():
    """text matching STRAIN_RE -> {hit: True, kind: 'strain_code'}."""
    result = rule_positive({"text": "SHI just came in"})
    assert result["hit"] is True
    assert result["kind"] == "strain_code"


def test_rule_positive_strain_code_4char():
    """4-char uppercase strain code is also matched."""
    result = rule_positive({"text": "LIMA batch ready"})
    assert result["hit"] is True
    assert result["kind"] == "strain_code"


def test_rule_positive_block_name():
    """text matching BLOCK_RE -> {hit: True, kind: 'block_name'}."""
    result = rule_positive({"text": "260522_KOY_7 looking good"})
    assert result["hit"] is True
    assert result["kind"] == "block_name"


def test_rule_positive_no_hit():
    """Plain text with no recognizable patterns -> {hit: False}."""
    result = rule_positive({"text": "hola"})
    assert result["hit"] is False


def test_rule_positive_empty_env_ctx():
    """Empty env_ctx -> {hit: False}."""
    result = rule_positive({})
    assert result["hit"] is False


def test_rule_positive_body_is_text_not_concat():
    """Body is text OR transcript, not concatenation.

    If text alone is <= 200 and has no patterns, should not fire on transcript
    having patterns when text is present.
    """
    # text = "hello" (no patterns, len 5), transcript = "SHI batch" (has strain)
    # rule_positive picks text first (not transcript) -- so strain_code should fire
    # because body = env_ctx.get("text") or env_ctx.get("transcript") or ""
    # body = "hello" (falsy? No -- "hello" is truthy) => body = "hello"
    # "hello" has no strain/block pattern, not > 200, no attachment -> hit: False
    result = rule_positive({"text": "hello", "transcript": "SHI batch"})
    # text is truthy, so transcript is not used
    assert result["hit"] is False


def test_rule_positive_uses_transcript_when_no_text():
    """When text is absent or empty, falls back to transcript."""
    result = rule_positive({"transcript": "KOY is ready"})
    assert result["hit"] is True
    assert result["kind"] == "strain_code"


# ---------------------------------------------------------------------------
# rule_negative: hit path
# ---------------------------------------------------------------------------


def test_rule_negative_short_ack_fires():
    """'ok' within 30min of attestation_kickoff -> {hit: True, kind: 'short_ack_within_30m'}."""
    result = rule_negative({"text": "ok"}, _kickoff(), _NOW_MS)
    assert result["hit"] is True
    assert result["kind"] == "short_ack_within_30m"


def test_rule_negative_emoji_ack_fires():
    """Thumbs-up emoji is an ack."""
    result = rule_negative({"text": "\U0001f44d"}, _kickoff(), _NOW_MS)
    assert result["hit"] is True


def test_rule_negative_gracias_fires():
    """'gracias' is an ack."""
    result = rule_negative({"text": "gracias"}, _kickoff(), _NOW_MS)
    assert result["hit"] is True


# ---------------------------------------------------------------------------
# rule_negative: miss paths
# ---------------------------------------------------------------------------


def test_rule_negative_no_last_bot_outbound():
    """No lastBotOutbound -> hit: False."""
    result = rule_negative({"text": "ok"}, None, _NOW_MS)
    assert result["hit"] is False


def test_rule_negative_wrong_intent():
    """Intent != attestation_kickoff -> hit: False."""
    outbound = {"intent": "some_other_intent", "sent_at": _SENT_AT_29MIN_AGO}
    result = rule_negative({"text": "ok"}, outbound, _NOW_MS)
    assert result["hit"] is False


def test_rule_negative_outside_30min_does_not_fire():
    """Ack that arrives > 30 min after attestation_kickoff -> hit: False (Pitfall 8)."""
    result = rule_negative({"text": "ok"}, _kickoff(_SENT_AT_31MIN_AGO), _NOW_MS)
    assert result["hit"] is False


def test_rule_negative_exactly_30min_boundary():
    """Exactly 30 min = boundary: nowMs - sentAtMs == 30*60*1000 is NOT > window, so hit: True."""
    # _SENT_AT_30MIN_AGO: nowMs - sentAtMs == 1_800_000 (exactly 30min)
    # condition: > 30*60*1000 -> False (== is not >), so we proceed
    result = rule_negative({"text": "ok"}, _kickoff(_SENT_AT_30MIN_AGO), _NOW_MS)
    # Exactly 30min is NOT outside the window, so rule fires
    assert result["hit"] is True


def test_rule_negative_40char_body_does_not_fire():
    """Pitfall 3: body of exactly 40 chars -> hit: False (>= 40, not > 40)."""
    body_40 = "a" * 40
    assert len(body_40) == 40
    result = rule_negative({"text": body_40}, _kickoff(), _NOW_MS)
    assert result["hit"] is False


def test_rule_negative_39char_body_no_ack():
    """39-char body that doesn't match ack pattern -> hit: False."""
    result = rule_negative({"text": "a" * 39}, _kickoff(), _NOW_MS)
    assert result["hit"] is False


def test_rule_negative_phantom_ack_does_not_fire():
    """Pitfall 4: 'ok then let me explain' starts with 'ok' but $ anchor prevents match."""
    result = rule_negative({"text": "ok then let me explain"}, _kickoff(), _NOW_MS)
    assert result["hit"] is False


def test_rule_negative_ack_case_insensitive():
    """ACK_RE is case-insensitive: 'OK' is an ack."""
    result = rule_negative({"text": "OK"}, _kickoff(), _NOW_MS)
    assert result["hit"] is True


def test_rule_negative_sent_at_z_suffix():
    """Pitfall 8: sent_at with Z suffix is parsed correctly."""
    outbound = {"intent": "attestation_kickoff", "sent_at": "2023-11-14T21:54:20Z"}
    result = rule_negative({"text": "yes"}, outbound, _NOW_MS)
    assert result["hit"] is True


def test_rule_negative_missing_sent_at():
    """If sent_at is missing from last_bot_outbound -> hit: False."""
    outbound = {"intent": "attestation_kickoff"}
    result = rule_negative({"text": "ok"}, outbound, _NOW_MS)
    assert result["hit"] is False


def test_rule_negative_sent_at_datetime_fires():
    """CR-02: sent_at as a timezone-aware datetime (psycopg3 timestamptz) must not crash.

    Before the fix, sent_at.replace("Z", "+00:00") raised AttributeError because
    datetime.replace() takes keyword args, not positional string args.
    After the fix, the datetime branch is taken directly and rule fires correctly.
    """
    # Build a datetime equivalent to _SENT_AT_29MIN_AGO ("2023-11-14T21:44:20+00:00")
    sent_at_dt = dt.datetime(2023, 11, 14, 21, 44, 20, tzinfo=dt.timezone.utc)
    outbound = {"intent": "attestation_kickoff", "sent_at": sent_at_dt}
    result = rule_negative({"text": "ok"}, outbound, _NOW_MS)
    assert result["hit"] is True
    assert result["kind"] == "short_ack_within_30m"
