"""
test_signal_router.py -- Unit tests for farm_agent.signal_io.router.

Coverage (SIG-03 / SC#5):
- Whitelist gate: is_whitelisted returns True for signal_sender, signal_recipient,
  and entries in signal_additional_senders; False for unknown numbers.
- SC#5: resolve_farmer returns mapped slug for known number; "(unassigned)" for
  unknown-but-whitelisted — never None, never raises.
- DM vs group: classify_envelope distinguishes DM from group, excludes UPDATE/QUIT.
- Group triggers: collect_group_triggers detects mention/command/quote; DM → {"dm"}.
- Dual-shape: source and dm are read from both env["envelope"][...] and env[...] shapes.
"""

import pytest

from tests.conftest import TEST_ENV


# ---------------------------------------------------------------------------
# Helpers — build a minimal TenantConfig
# ---------------------------------------------------------------------------


def _config(**overrides):
    from farm_agent.tenancy.tenant import load as load_config  # noqa: PLC0415

    env = {
        **TEST_ENV,
        # Two entries in farmer map
        "SIGNAL_FARMER_MAP": "+10000000000:f1,+10000000001:f2",
        "SIGNAL_ADDITIONAL_SENDERS": "+10000000002",
    }
    env.update(overrides)
    return load_config(env)


def _dm_envelope(source, text="", group_id=None, group_type=None,
                 mentions=None, quote=None, use_outer_shape=False):
    """Build a signal envelope dict.

    use_outer_shape=False → env["envelope"]["dataMessage"] (primary shape)
    use_outer_shape=True  → env["dataMessage"] (fallback shape)
    """
    data_message = {"message": text}
    if group_id is not None:
        data_message["groupInfo"] = {"groupId": group_id, "type": group_type or "DELIVER"}
    if mentions is not None:
        data_message["mentions"] = mentions
    if quote is not None:
        data_message["quote"] = quote

    if use_outer_shape:
        return {"dataMessage": data_message, "source": source}
    return {"envelope": {"source": source, "dataMessage": data_message}}


# ---------------------------------------------------------------------------
# 1. Whitelist gate
# ---------------------------------------------------------------------------


def test_is_whitelisted_sender():
    """signal_sender is whitelisted."""
    from farm_agent.signal_io.router import is_whitelisted  # noqa: PLC0415

    cfg = _config()
    assert is_whitelisted(cfg.signal_sender, cfg) is True


def test_is_whitelisted_recipient():
    """signal_recipient is whitelisted."""
    from farm_agent.signal_io.router import is_whitelisted  # noqa: PLC0415

    cfg = _config()
    assert is_whitelisted(cfg.signal_recipient, cfg) is True


def test_is_whitelisted_additional_sender():
    """A number in signal_additional_senders is whitelisted."""
    from farm_agent.signal_io.router import is_whitelisted  # noqa: PLC0415

    cfg = _config()
    # "+10000000002" is in SIGNAL_ADDITIONAL_SENDERS
    assert is_whitelisted("+10000000002", cfg) is True


def test_is_whitelisted_unknown_rejected():
    """A number not in the whitelist returns False."""
    from farm_agent.signal_io.router import is_whitelisted  # noqa: PLC0415

    cfg = _config()
    assert is_whitelisted("+19999999999", cfg) is False


def test_is_whitelisted_empty_string_rejected():
    """An empty string is not whitelisted."""
    from farm_agent.signal_io.router import is_whitelisted  # noqa: PLC0415

    cfg = _config()
    assert is_whitelisted("", cfg) is False


# ---------------------------------------------------------------------------
# 2. SC#5: resolve_farmer — unknown → "(unassigned)", never None
# ---------------------------------------------------------------------------


def test_resolve_farmer_known():
    """A number present in signal_farmer_map resolves to its slug."""
    from farm_agent.signal_io.router import resolve_farmer  # noqa: PLC0415

    cfg = _config()
    # "+10000000000" → "f1" per the SIGNAL_FARMER_MAP above
    assert resolve_farmer("+10000000000", cfg) == "f1"


def test_resolve_farmer_unknown_unassigned():
    """SC#5: an unknown-but-whitelisted number resolves to '(unassigned)', not None."""
    from farm_agent.signal_io.router import resolve_farmer  # noqa: PLC0415

    cfg = _config()
    result = resolve_farmer("+19999999999", cfg)
    assert result == "(unassigned)"
    assert result is not None


def test_resolve_farmer_never_raises():
    """resolve_farmer never raises, even for completely invalid input."""
    from farm_agent.signal_io.router import resolve_farmer  # noqa: PLC0415

    cfg = _config()
    result = resolve_farmer("", cfg)
    assert result == "(unassigned)"


# ---------------------------------------------------------------------------
# 3. DM vs group classification
# ---------------------------------------------------------------------------


def test_classify_envelope_dm_no_group():
    """No groupInfo → is_group=False."""
    from farm_agent.signal_io.router import classify_envelope  # noqa: PLC0415

    env = _dm_envelope("+10000000000", text="hello")
    result = classify_envelope(env)
    assert result["is_group"] is False
    assert result["group_id"] is None


def test_classify_envelope_group_deliver():
    """groupId present with type DELIVER → is_group=True."""
    from farm_agent.signal_io.router import classify_envelope  # noqa: PLC0415

    env = _dm_envelope("+10000000000", group_id="abc123", group_type="DELIVER")
    result = classify_envelope(env)
    assert result["is_group"] is True
    assert result["group_id"] == "abc123"


def test_classify_envelope_group_update_not_group():
    """groupId present but type=UPDATE → is_group=False (Risk #11)."""
    from farm_agent.signal_io.router import classify_envelope  # noqa: PLC0415

    env = _dm_envelope("+10000000000", group_id="abc123", group_type="UPDATE")
    result = classify_envelope(env)
    assert result["is_group"] is False


def test_classify_envelope_group_quit_not_group():
    """groupId present but type=QUIT → is_group=False (Risk #11)."""
    from farm_agent.signal_io.router import classify_envelope  # noqa: PLC0415

    env = _dm_envelope("+10000000000", group_id="abc123", group_type="QUIT")
    result = classify_envelope(env)
    assert result["is_group"] is False


def test_classify_envelope_source():
    """classify_envelope includes source in returned dict."""
    from farm_agent.signal_io.router import classify_envelope  # noqa: PLC0415

    env = _dm_envelope("+10000000000", text="hi")
    result = classify_envelope(env)
    assert result["source"] == "+10000000000"


# ---------------------------------------------------------------------------
# 4. Group trigger collection
# ---------------------------------------------------------------------------

BOT_PHONE = "+10000000000"  # signal_sender in TEST_ENV


def test_triggers_dm_context():
    """DM envelope (no group) → triggers == {"dm"}."""
    from farm_agent.signal_io.router import collect_group_triggers  # noqa: PLC0415

    env = _dm_envelope("+10000000001", text="hello")
    assert collect_group_triggers(env, BOT_PHONE) == {"dm"}


def test_triggers_mention():
    """Mention of bot_phone in mentions list → 'mention' trigger."""
    from farm_agent.signal_io.router import collect_group_triggers  # noqa: PLC0415

    env = _dm_envelope(
        "+10000000001",
        group_id="g1",
        mentions=[{"number": BOT_PHONE, "start": 0, "length": 10}],
    )
    triggers = collect_group_triggers(env, BOT_PHONE)
    assert "mention" in triggers


def test_triggers_command_mute():
    """'mute' command keyword → 'command' trigger."""
    from farm_agent.signal_io.router import collect_group_triggers  # noqa: PLC0415

    env = _dm_envelope("+10000000001", group_id="g1", text="mute")
    assert "command" in collect_group_triggers(env, BOT_PHONE)


def test_triggers_command_snooze():
    """'snooze' command keyword → 'command' trigger."""
    from farm_agent.signal_io.router import collect_group_triggers  # noqa: PLC0415

    env = _dm_envelope("+10000000001", group_id="g1", text="snooze 30m")
    assert "command" in collect_group_triggers(env, BOT_PHONE)


def test_triggers_command_with_at_mention_prefix():
    """'@bot snooze' (mention prefix before command) → 'command' trigger."""
    from farm_agent.signal_io.router import collect_group_triggers  # noqa: PLC0415

    env = _dm_envelope("+10000000001", group_id="g1", text="@mushy snooze 1h")
    assert "command" in collect_group_triggers(env, BOT_PHONE)


def test_triggers_command_ufffc_marker():
    """U+FFFC (Signal iOS mention-attachment marker) before command → 'command' trigger."""
    from farm_agent.signal_io.router import collect_group_triggers  # noqa: PLC0415

    # U+FFFC = "￼"
    env = _dm_envelope("+10000000001", group_id="g1", text="￼ mute")
    assert "command" in collect_group_triggers(env, BOT_PHONE)


def test_triggers_command_force_slash():
    """'/force-' slash command → 'command' trigger."""
    from farm_agent.signal_io.router import collect_group_triggers  # noqa: PLC0415

    env = _dm_envelope("+10000000001", group_id="g1", text="/force-fruiting")
    assert "command" in collect_group_triggers(env, BOT_PHONE)


def test_triggers_command_cancel_slash():
    """'/cancel-' slash command → 'command' trigger."""
    from farm_agent.signal_io.router import collect_group_triggers  # noqa: PLC0415

    env = _dm_envelope("+10000000001", group_id="g1", text="/cancel-experiment")
    assert "command" in collect_group_triggers(env, BOT_PHONE)


def test_triggers_quote_author():
    """quote.author == bot_phone → 'quote' trigger."""
    from farm_agent.signal_io.router import collect_group_triggers  # noqa: PLC0415

    env = _dm_envelope(
        "+10000000001",
        group_id="g1",
        quote={"author": BOT_PHONE, "timestamp": 1234, "message": "prev"},
    )
    assert "quote" in collect_group_triggers(env, BOT_PHONE)


def test_triggers_quote_author_number():
    """quote.authorNumber == bot_phone → 'quote' trigger (cross-version field drift)."""
    from farm_agent.signal_io.router import collect_group_triggers  # noqa: PLC0415

    env = _dm_envelope(
        "+10000000001",
        group_id="g1",
        quote={"authorNumber": BOT_PHONE, "timestamp": 1234, "message": "prev"},
    )
    assert "quote" in collect_group_triggers(env, BOT_PHONE)


def test_triggers_no_trigger_in_group():
    """Group message with no mention/command/quote → empty set (no 'dm')."""
    from farm_agent.signal_io.router import collect_group_triggers  # noqa: PLC0415

    env = _dm_envelope("+10000000001", group_id="g1", text="hello everyone")
    triggers = collect_group_triggers(env, BOT_PHONE)
    assert triggers == set()
    assert "dm" not in triggers


# ---------------------------------------------------------------------------
# 5. Dual-shape source/dm read
# ---------------------------------------------------------------------------


def test_extract_source_primary_shape():
    """env["envelope"]["source"] is extracted correctly (primary shape)."""
    from farm_agent.signal_io.router import extract_source  # noqa: PLC0415

    env = {"envelope": {"source": "+10000000000", "dataMessage": {}}}
    assert extract_source(env) == "+10000000000"


def test_extract_source_missing_returns_none():
    """Missing source returns None (caller must handle)."""
    from farm_agent.signal_io.router import extract_source  # noqa: PLC0415

    env = {"envelope": {}}
    assert extract_source(env) is None


def test_classify_envelope_dual_shape_outer():
    """Fallback shape: env["dataMessage"] is read when env["envelope"]["dataMessage"] absent."""
    from farm_agent.signal_io.router import classify_envelope  # noqa: PLC0415

    env = _dm_envelope("+10000000000", group_id="g1", use_outer_shape=True)
    # In outer shape the source is at env["source"], not env["envelope"]["source"]
    # classify_envelope should still parse groupInfo from the fallback dm
    result = classify_envelope(env)
    assert result["is_group"] is True
    assert result["group_id"] == "g1"


def test_collect_triggers_dual_shape_outer():
    """collect_group_triggers reads dataMessage from fallback outer shape."""
    from farm_agent.signal_io.router import collect_group_triggers  # noqa: PLC0415

    env = _dm_envelope(
        "+10000000001",
        group_id="g1",
        text="mute",
        use_outer_shape=True,
    )
    assert "command" in collect_group_triggers(env, BOT_PHONE)
