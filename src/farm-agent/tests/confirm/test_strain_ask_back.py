"""
tests/confirm/test_strain_ask_back.py -- Unit tests for strain_ask_back.py (SC-4).

Covers:
  - resolve_strain: curated-14 exact-match, unknown code, None input
  - nearest_known: Levenshtein display-only suggestion
  - parse_strain_ask_back_reply: four routing paths (confirm_new / correction / unknown)
  - render_strain_ask_back: ASCII-only output, no em-dashes, no emoji
  - SC-4 intercept cases: known code passes through (no ask-back), unknown code held,
    nonsense reply falls through (no confirm, no re-ask)

No DB, no asyncio required for pure-function tests.
SC-4 dispatch integration tests use async + FakeConfirmRepo + fake signal_client.
"""

from __future__ import annotations

import asyncio

import pytest


# ---------------------------------------------------------------------------
# resolve_strain
# ---------------------------------------------------------------------------

class TestResolveStrain:
    """Port of resolveStrain unit tests (strain-resolver.js)."""

    CURATED_14 = [
        "SHI", "SH2", "KOY", "MAI", "MALI", "KOS", "DT",
        "CAS", "CAZ", "WIN", "ALM", "MOR", "BP", "LIMA",
    ]

    def test_known_code_exact_match(self):
        from farm_agent.confirm.strain_ask_back import resolve_strain  # noqa: PLC0415
        result = resolve_strain("SHI", self.CURATED_14)
        assert result == {"known": True, "code": "SHI"}

    def test_known_code_lowercase_normalized(self):
        from farm_agent.confirm.strain_ask_back import resolve_strain  # noqa: PLC0415
        result = resolve_strain("shi", self.CURATED_14)
        assert result == {"known": True, "code": "SHI"}

    def test_known_code_with_whitespace(self):
        from farm_agent.confirm.strain_ask_back import resolve_strain  # noqa: PLC0415
        result = resolve_strain("  KOY  ", self.CURATED_14)
        assert result == {"known": True, "code": "KOY"}

    def test_unknown_code_returns_known_false(self):
        from farm_agent.confirm.strain_ask_back import resolve_strain  # noqa: PLC0415
        result = resolve_strain("POY", self.CURATED_14)
        assert result["known"] is False
        assert result["code"] == "POY"
        assert "nearest" in result
        # nearest is some curated code (display-only -- don't assert exact value)
        assert result["nearest"] in self.CURATED_14

    def test_none_input_returns_none_code(self):
        from farm_agent.confirm.strain_ask_back import resolve_strain  # noqa: PLC0415
        result = resolve_strain(None, self.CURATED_14)
        assert result == {"known": False, "code": None}

    def test_non_string_input(self):
        from farm_agent.confirm.strain_ask_back import resolve_strain  # noqa: PLC0415
        result = resolve_strain(123, self.CURATED_14)
        assert result == {"known": False, "code": None}

    def test_empty_string_returns_none_code(self):
        from farm_agent.confirm.strain_ask_back import resolve_strain  # noqa: PLC0415
        result = resolve_strain("", self.CURATED_14)
        assert result == {"known": False, "code": None}

    def test_unknown_empty_curated_set_no_nearest_key(self):
        from farm_agent.confirm.strain_ask_back import resolve_strain  # noqa: PLC0415
        result = resolve_strain("XYZ", [])
        assert result["known"] is False
        assert result["code"] == "XYZ"
        # no 'nearest' key when curated set is empty
        assert "nearest" not in result

    def test_all_curated_14_pass_through(self):
        from farm_agent.confirm.strain_ask_back import resolve_strain, CURATED_14  # noqa: PLC0415
        for code in CURATED_14:
            result = resolve_strain(code, CURATED_14)
            assert result["known"] is True, f"Expected {code} to be known"
            assert result["code"] == code


# ---------------------------------------------------------------------------
# nearest_known (Levenshtein, display-only)
# ---------------------------------------------------------------------------

class TestNearestKnown:
    CURATED_14 = [
        "SHI", "SH2", "KOY", "MAI", "MALI", "KOS", "DT",
        "CAS", "CAZ", "WIN", "ALM", "MOR", "BP", "LIMA",
    ]

    def test_poy_nearest_is_in_curated_set(self):
        from farm_agent.confirm.strain_ask_back import nearest_known  # noqa: PLC0415
        near = nearest_known("POY", self.CURATED_14)
        assert near in self.CURATED_14

    def test_exact_match_distance_zero(self):
        from farm_agent.confirm.strain_ask_back import nearest_known  # noqa: PLC0415
        # KOY vs KOY -> distance 0, so KOY should be nearest
        near = nearest_known("KOY", self.CURATED_14)
        assert near == "KOY"

    def test_empty_curated_returns_none(self):
        from farm_agent.confirm.strain_ask_back import nearest_known  # noqa: PLC0415
        near = nearest_known("XYZ", [])
        assert near is None

    def test_tie_break_first_wins(self):
        from farm_agent.confirm.strain_ask_back import nearest_known  # noqa: PLC0415
        # "AA" vs ["AA", "AA"] -- first element wins on tie
        near = nearest_known("AA", ["AA", "BB"])
        assert near == "AA"


# ---------------------------------------------------------------------------
# parse_strain_ask_back_reply
# ---------------------------------------------------------------------------

class TestParseStrainAskBackReply:
    """Four routing paths per RESEARCH/PATTERNS verbatim."""

    def test_yes_confirm_new(self):
        from farm_agent.confirm.strain_ask_back import parse_strain_ask_back_reply  # noqa: PLC0415
        assert parse_strain_ask_back_reply("yes") == {"kind": "confirm_new"}

    def test_y_confirm_new(self):
        from farm_agent.confirm.strain_ask_back import parse_strain_ask_back_reply  # noqa: PLC0415
        assert parse_strain_ask_back_reply("y") == {"kind": "confirm_new"}

    def test_ok_confirm_new(self):
        from farm_agent.confirm.strain_ask_back import parse_strain_ask_back_reply  # noqa: PLC0415
        assert parse_strain_ask_back_reply("ok") == {"kind": "confirm_new"}

    def test_si_confirm_new(self):
        from farm_agent.confirm.strain_ask_back import parse_strain_ask_back_reply  # noqa: PLC0415
        assert parse_strain_ask_back_reply("si") == {"kind": "confirm_new"}

    def test_confirm_confirm_new(self):
        from farm_agent.confirm.strain_ask_back import parse_strain_ask_back_reply  # noqa: PLC0415
        assert parse_strain_ask_back_reply("confirm") == {"kind": "confirm_new"}

    def test_new_confirm_new(self):
        from farm_agent.confirm.strain_ask_back import parse_strain_ask_back_reply  # noqa: PLC0415
        assert parse_strain_ask_back_reply("new") == {"kind": "confirm_new"}

    def test_yes_uppercase_confirm_new(self):
        from farm_agent.confirm.strain_ask_back import parse_strain_ask_back_reply  # noqa: PLC0415
        assert parse_strain_ask_back_reply("YES") == {"kind": "confirm_new"}

    def test_no_koy_correction(self):
        from farm_agent.confirm.strain_ask_back import parse_strain_ask_back_reply  # noqa: PLC0415
        assert parse_strain_ask_back_reply("no, koy") == {"kind": "correction", "code": "KOY"}

    def test_no_koy_no_comma_correction(self):
        from farm_agent.confirm.strain_ask_back import parse_strain_ask_back_reply  # noqa: PLC0415
        assert parse_strain_ask_back_reply("no KOY") == {"kind": "correction", "code": "KOY"}

    def test_bare_code_correction(self):
        from farm_agent.confirm.strain_ask_back import parse_strain_ask_back_reply  # noqa: PLC0415
        assert parse_strain_ask_back_reply("koy") == {"kind": "correction", "code": "KOY"}

    def test_bare_code_uppercase_correction(self):
        from farm_agent.confirm.strain_ask_back import parse_strain_ask_back_reply  # noqa: PLC0415
        assert parse_strain_ask_back_reply("KOY") == {"kind": "correction", "code": "KOY"}

    def test_what_is_unknown(self):
        from farm_agent.confirm.strain_ask_back import parse_strain_ask_back_reply  # noqa: PLC0415
        assert parse_strain_ask_back_reply("what?") == {"kind": "unknown"}

    def test_garbage_text_unknown(self):
        from farm_agent.confirm.strain_ask_back import parse_strain_ask_back_reply  # noqa: PLC0415
        assert parse_strain_ask_back_reply("garbage text") == {"kind": "unknown"}

    def test_empty_string_unknown(self):
        from farm_agent.confirm.strain_ask_back import parse_strain_ask_back_reply  # noqa: PLC0415
        assert parse_strain_ask_back_reply("") == {"kind": "unknown"}

    def test_no_alone_is_unknown(self):
        # bare "no" without a following code -- falls through to unknown
        from farm_agent.confirm.strain_ask_back import parse_strain_ask_back_reply  # noqa: PLC0415
        result = parse_strain_ask_back_reply("no")
        # "no" alone is NOT a confirm_new; it's "no" without a code suffix
        # -> first token is 'no', no valid CODE after it -> unknown
        assert result == {"kind": "unknown"}

    def test_no_koy_extra_words_is_unknown(self):
        # WR-01: "no KOY that's wrong" -- full remainder "KOY that's wrong" fails CODE_RE
        # Python previously returned correction:KOY; must now return unknown (match Node)
        from farm_agent.confirm.strain_ask_back import parse_strain_ask_back_reply  # noqa: PLC0415
        result = parse_strain_ask_back_reply("no KOY that's wrong")
        assert result == {"kind": "unknown"}, (
            f"WR-01: 'no KOY that\\'s wrong' must return unknown (remainder has spaces), "
            f"got {result!r}"
        )

    def test_no_koy_please_is_unknown(self):
        # WR-01: "no KOY please" -- remainder "KOY please" has space -> unknown
        from farm_agent.confirm.strain_ask_back import parse_strain_ask_back_reply  # noqa: PLC0415
        result = parse_strain_ask_back_reply("no KOY please")
        assert result == {"kind": "unknown"}, (
            f"WR-01: 'no KOY please' must return unknown, got {result!r}"
        )

    def test_no_comma_koy_still_works(self):
        # WR-01 regression: "no, KOY" (single valid code after comma) must still be correction
        from farm_agent.confirm.strain_ask_back import parse_strain_ask_back_reply  # noqa: PLC0415
        result = parse_strain_ask_back_reply("no, koy")
        assert result == {"kind": "correction", "code": "KOY"}, (
            f"WR-01 regression: 'no, koy' must return correction:KOY, got {result!r}"
        )


# ---------------------------------------------------------------------------
# render_strain_ask_back
# ---------------------------------------------------------------------------

class TestRenderStrainAskBack:
    """ASCII-only, no em-dashes, no emoji."""

    def test_with_nearest_three_lines(self):
        from farm_agent.confirm.strain_ask_back import render_strain_ask_back  # noqa: PLC0415
        text = render_strain_ask_back("POY", "KOY")
        lines = text.strip().split("\n")
        assert len(lines) == 3
        assert "POY" in lines[0]
        assert "KOY" in lines[1]
        assert "KOY" in lines[2]

    def test_without_nearest_two_lines(self):
        from farm_agent.confirm.strain_ask_back import render_strain_ask_back  # noqa: PLC0415
        text = render_strain_ask_back("POY", None)
        lines = text.strip().split("\n")
        assert len(lines) == 2
        assert "POY" in lines[0]

    def test_ascii_only_no_em_dash(self):
        from farm_agent.confirm.strain_ask_back import render_strain_ask_back  # noqa: PLC0415
        text = render_strain_ask_back("POY", "KOY")
        # No em-dash (U+2014) or en-dash (U+2013)
        assert "—" not in text, "em-dash found in render output"
        assert "–" not in text, "en-dash found in render output"
        # ASCII double-dash separator must be present
        assert "--" in text

    def test_no_emoji(self):
        from farm_agent.confirm.strain_ask_back import render_strain_ask_back  # noqa: PLC0415
        text = render_strain_ask_back("POY", "KOY")
        # Any character above U+007F that is not a standard ASCII-extended Latin char
        # would indicate an emoji or special unicode. Simple check: all codepoints <= 127
        non_ascii = [c for c in text if ord(c) > 127]
        assert not non_ascii, f"Non-ASCII chars found: {non_ascii}"

    def test_seen_code_uppercased(self):
        from farm_agent.confirm.strain_ask_back import render_strain_ask_back  # noqa: PLC0415
        text = render_strain_ask_back("poy", "KOY")
        assert "POY" in text

    def test_nearest_uppercased(self):
        from farm_agent.confirm.strain_ask_back import render_strain_ask_back  # noqa: PLC0415
        text = render_strain_ask_back("POY", "koy")
        assert "KOY" in text


# ---------------------------------------------------------------------------
# SC-4 intercept integration (async, uses dispatch.route_confirm_reply)
# ---------------------------------------------------------------------------

class FakeSignalClient:
    """Records send() calls for assertion. Never raises."""

    def __init__(self) -> None:
        self.sends: list[dict] = []

    async def send(self, body: str, *, to=None, related_draft_id=None, intent=None, **kwargs) -> dict:
        self.sends.append({"body": body, "to": to, "related_draft_id": related_draft_id, "intent": intent})
        return {"ok": True, "timestamp": 1234567890}


class FakeConfirmRepoForDispatch:
    """Targeted fake for dispatch SC-4 tests.

    confirm_draft: records call, returns rowcount=1 by default.
    mark_nudge_sent: not called in SC-4 tests.
    """

    def __init__(self) -> None:
        self.confirm_calls: list[str] = []
        self.update_calls: list[dict] = []
        self._confirm_rowcount: int = 1

    async def confirm_draft(self, pool, draft_id: str) -> dict:
        self.confirm_calls.append(draft_id)
        return {"ok": True, "rowcount": self._confirm_rowcount}

    async def discard_draft(self, pool, draft_id: str) -> dict:
        return {"ok": True, "rowcount": 1}

    async def expire_draft(self, pool, draft_id: str, reason: str) -> dict:
        return {"ok": True, "rowcount": 1}

    async def mark_nudge_sent(self, pool, draft_id: str) -> dict:
        return {"ok": True, "rowcount": 1}

    async def bump_edit_turn(self, pool, draft_id: str) -> dict:
        return {"ok": True, "edit_turn_count": 1, "rowcount": 1}

    async def find_awaiting_for_sender(self, pool, sender_e164: str):
        return None

    async def find_nudge_candidates(self, pool, nudge_min: int) -> list:
        return []

    async def find_expire_candidates(self, pool, timeout_min: int) -> list:
        return []

    async def update_draft_after_edit(self, pool, draft_id: str, fields: dict) -> dict:
        self.update_calls.append({"draft_id": draft_id, "fields": fields})
        return {"ok": True, "rowcount": 1}

    async def append_event_via_pool(self, pool, draft_id: str, event: str, payload) -> dict:
        return {"ok": True, "seq": 1}


def _make_draft_row(
    draft_id: str = "draft-abc",
    status: str = "awaiting_farmer",
    needs_review_reason: str = "strain_unknown_pending_confirm",
    species_code: str = "POY",
    edit_turn_count: int = 0,
    nudge_sent_at=None,
) -> dict:
    return {
        "id": draft_id,
        "status": status,
        "sender_e164": "+59899000001",
        "edit_turn_count": edit_turn_count,
        "nudge_sent_at": nudge_sent_at,
        "confirmed_at": None,
        "discarded_at": None,
        "expired_at": None,
        "terminal_reason": None,
        "needs_review_reason": needs_review_reason,
        "draft_json": {"species_code": species_code, "quantity": 5},
        "per_field_confidence": {},
        "farmer_facing_preview": "5 bags",
        "updated_at": None,
        "reply_target_kind": "dm",
        "group_id": None,
    }


def _make_config():
    """Minimal config-like object for dispatch tests."""
    from types import SimpleNamespace  # noqa: PLC0415
    return SimpleNamespace(
        draft_pending_timeout_min=30,
        draft_nudge_fraction=0.8,
        draft_watchdog_interval_ms=60000,
        max_edit_turns=3,
        signal_group_id=None,
        # STRAIN_CODES not set -> dispatch should use CURATED_14 default
    )


@pytest.mark.asyncio
async def test_sc4_known_curated_code_confirm_path():
    """SC-4: a known curated-14 code on a strain_unknown draft confirms directly (no ask-back)."""
    from farm_agent.confirm.dispatch import route_confirm_reply  # noqa: PLC0415

    fake_repo = FakeConfirmRepoForDispatch()
    fake_signal = FakeSignalClient()
    config = _make_config()
    pool = object()  # not used by the fake repo

    # Draft awaiting strain confirmation; farmer replies with a known code "KOY"
    draft = _make_draft_row(species_code="POY")

    result = await route_confirm_reply(pool, fake_signal, config, draft, "koy", repo=fake_repo)

    # confirm_draft must have been called (SC-4: known code -> confirm path)
    assert fake_repo.confirm_calls, "confirm_draft was not called for known curated code"
    # No re-ask send -- an ask-back message was NOT sent as the first message
    # (an ack IS expected but not an ask-back)
    sends = fake_signal.sends
    assert sends, "no ack send after confirm"
    # The result should indicate a confirm happened, not a re-ask
    assert result is not None
    assert result.get("action") in ("confirmed", "correction_confirmed"), (
        f"Expected confirm action, got: {result}"
    )


@pytest.mark.asyncio
async def test_sc4_unknown_code_sends_ask_back():
    """SC-4: an unknown code on a strain_unknown draft sends ask-back and holds the draft."""
    from farm_agent.confirm.dispatch import route_confirm_reply  # noqa: PLC0415

    fake_repo = FakeConfirmRepoForDispatch()
    fake_signal = FakeSignalClient()
    config = _make_config()
    pool = object()

    # Farmer replies with a code that is NOT in curated-14
    draft = _make_draft_row(species_code="POY")

    result = await route_confirm_reply(pool, fake_signal, config, draft, "POY", repo=fake_repo)

    # confirm_draft must NOT have been called
    assert not fake_repo.confirm_calls, "confirm_draft should NOT be called for unknown code"
    # An ask-back send must have been made
    assert fake_signal.sends, "no ask-back send for unknown code"
    assert result is not None
    assert result.get("action") == "re_asked"


@pytest.mark.asyncio
async def test_sc4_nonsense_reply_falls_through():
    """SC-4: a nonsense reply falls through (no confirm, no re-ask) -> action='fall_through'."""
    from farm_agent.confirm.dispatch import route_confirm_reply  # noqa: PLC0415

    fake_repo = FakeConfirmRepoForDispatch()
    fake_signal = FakeSignalClient()
    config = _make_config()
    pool = object()

    draft = _make_draft_row(species_code="POY")

    result = await route_confirm_reply(pool, fake_signal, config, draft, "what?", repo=fake_repo)

    # confirm_draft must NOT be called
    assert not fake_repo.confirm_calls, "confirm_draft should NOT be called on nonsense reply"
    # No ask-back re-send
    assert not fake_signal.sends, "no send should happen on unknown/fall-through reply"
    assert result is not None
    assert result.get("action") == "fall_through"


@pytest.mark.asyncio
async def test_sc4_yes_on_strain_unknown_draft_confirm_new():
    """SC-4: farmer YES on a strain_unknown draft -> confirm_new path -> confirm + ack."""
    from farm_agent.confirm.dispatch import route_confirm_reply  # noqa: PLC0415

    fake_repo = FakeConfirmRepoForDispatch()
    fake_signal = FakeSignalClient()
    config = _make_config()
    pool = object()

    draft = _make_draft_row(species_code="POY")

    result = await route_confirm_reply(pool, fake_signal, config, draft, "YES", repo=fake_repo)

    # confirm_draft must be called (YES -> confirm_new)
    assert fake_repo.confirm_calls, "confirm_draft was not called on YES for strain_unknown draft"
    assert fake_signal.sends, "ack send expected after YES confirm"
    assert result is not None
    assert result.get("action") in ("confirmed", "strain_approved_confirmed")


# ---------------------------------------------------------------------------
# WR-02: discard ack only sent when rowcount==1
# ---------------------------------------------------------------------------


class FakeConfirmRepoDiscard:
    """Fake repo for WR-02 dispatch test. discard_draft returns configurable rowcount."""

    def __init__(self, discard_rowcount: int = 1) -> None:
        self._discard_rowcount = discard_rowcount
        self.discard_calls: list[str] = []

    async def confirm_draft(self, pool, draft_id: str) -> dict:
        return {"ok": True, "rowcount": 1}

    async def discard_draft(self, pool, draft_id: str) -> dict:
        self.discard_calls.append(draft_id)
        return {"ok": True, "rowcount": self._discard_rowcount}

    async def expire_draft(self, pool, draft_id: str, reason: str) -> dict:
        return {"ok": True, "rowcount": 1}

    async def mark_nudge_sent(self, pool, draft_id: str) -> dict:
        return {"ok": True, "rowcount": 1}

    async def bump_edit_turn(self, pool, draft_id: str) -> dict:
        return {"ok": True, "edit_turn_count": 1, "rowcount": 1}

    async def update_draft_after_edit(self, pool, draft_id: str, fields: dict) -> dict:
        return {"ok": True, "rowcount": 1}

    async def append_event_via_pool(self, pool, draft_id: str, event: str, payload) -> dict:
        return {"ok": True, "seq": 1}


def _make_standard_draft_row(draft_id: str = "draft-discard-test") -> dict:
    """Minimal awaiting_farmer draft row for standard YES/NO/EDIT dispatch tests."""
    return {
        "id": draft_id,
        "status": "awaiting_farmer",
        "sender_e164": "+59899000099",
        "edit_turn_count": 0,
        "nudge_sent_at": None,
        "confirmed_at": None,
        "discarded_at": None,
        "expired_at": None,
        "terminal_reason": None,
        "needs_review_reason": None,  # standard path, not strain intercept
        "draft_json": {"species_code": "SHI"},
        "per_field_confidence": {},
        "farmer_facing_preview": "5 bags",
        "updated_at": None,
        "reply_target_kind": "dm",
        "group_id": None,
    }


@pytest.mark.asyncio
async def test_wr02_discard_ack_sent_on_rowcount_1():
    """WR-02: discard ack IS sent when discard_draft rowcount==1 (transition succeeded)."""
    from farm_agent.confirm.dispatch import route_confirm_reply  # noqa: PLC0415

    fake_signal = FakeSignalClient()
    fake_repo = FakeConfirmRepoDiscard(discard_rowcount=1)
    config = _make_config()
    pool = object()
    draft = _make_standard_draft_row()

    result = await route_confirm_reply(pool, fake_signal, config, draft, "no", repo=fake_repo)

    assert fake_repo.discard_calls, "discard_draft was not called"
    assert result is not None
    assert result.get("action") == "discarded"
    assert result.get("rowcount") == 1
    # Ack must have been sent
    ack_sends = [s for s in fake_signal.sends if s.get("intent") == "discard_ack"]
    assert ack_sends, (
        "WR-02: 'OK, discarded.' ack must be sent when rowcount==1"
    )
    assert any("discarded" in s["body"].lower() for s in ack_sends), (
        f"WR-02: discard ack body expected to mention 'discarded', got: {[s['body'] for s in ack_sends]}"
    )


@pytest.mark.asyncio
async def test_wr02_discard_ack_not_sent_on_rowcount_0():
    """WR-02: no discard ack when discard_draft rowcount==0 (race lost -- draft already expired).

    Sending 'OK, discarded.' when the discard did not actually happen is a
    no-silent-failure violation (factually wrong ack text).
    """
    from farm_agent.confirm.dispatch import route_confirm_reply  # noqa: PLC0415

    fake_signal = FakeSignalClient()
    fake_repo = FakeConfirmRepoDiscard(discard_rowcount=0)
    config = _make_config()
    pool = object()
    draft = _make_standard_draft_row()

    result = await route_confirm_reply(pool, fake_signal, config, draft, "no", repo=fake_repo)

    assert fake_repo.discard_calls, "discard_draft was not called"
    assert result is not None
    assert result.get("action") == "discarded"
    assert result.get("rowcount") == 0
    # 'OK, discarded.' ack must NOT have been sent (would be factually wrong)
    discard_acks = [s for s in fake_signal.sends if "discarded" in s.get("body", "").lower()]
    assert not discard_acks, (
        f"WR-02: 'OK, discarded.' must NOT be sent when rowcount==0 (race lost). "
        f"Got sends: {fake_signal.sends}"
    )
