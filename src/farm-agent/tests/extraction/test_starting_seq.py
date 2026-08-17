"""starting_seq ask-back: prompt text, reply parsing, per-session SEQ minting."""

import pytest

from farm_agent.extraction.starting_seq import (
    build_starting_seq_ask_back_text,
    handle_starting_seq_reply,
    parse_starting_seq_reply,
)


@pytest.mark.parametrize("text,expected", [
    ("YES", {"kind": "yes"}),
    ("yes", {"kind": "yes"}),
    ("  Yes  ", {"kind": "yes"}),
    ("4", {"kind": "number", "value": 4}),
    ("  12 ", {"kind": "number", "value": 12}),
    ("maybe tomorrow", {"kind": "unclear"}),
    ("", {"kind": "unclear"}),
])
def test_parse_reply(text, expected):
    assert parse_starting_seq_reply(text) == expected


def test_ask_back_text_has_no_em_dash():
    out = build_starting_seq_ask_back_text(
        total_children=11, event_date="20260522", last_seq=3,
        last_block_name="260522_KOY_3", sender_name="Santi")
    assert "—" not in out


def test_ask_back_text_includes_the_hint_when_last_seq_known():
    out = build_starting_seq_ask_back_text(
        total_children=11, event_date="20260522", last_seq=3,
        last_block_name="260522_KOY_3", sender_name=None)
    assert "260522_KOY_3" in out


def test_ask_back_text_survives_unknown_last_seq():
    out = build_starting_seq_ask_back_text(
        total_children=11, event_date="20260522", last_seq=None,
        last_block_name=None, sender_name=None)
    assert isinstance(out, str) and out.strip() != ""


class FakeDb:
    def __init__(self, row):
        self.row = row
        self.updates = []

    async def get_draft_by_id(self, pool, draft_id):
        return self.row

    async def update_draft_status(self, pool, draft_id, status, extras=None):
        self.updates.append((draft_id, status, extras or {}))
        self.row["draft_json"] = (extras or {}).get("draft_json", self.row.get("draft_json"))
        return {"ok": True, "rowcount": 1}


class FakeDispatcher:
    def __init__(self):
        self.calls = []

    async def dispatch(self, effect, row):
        self.calls.append((effect, row))
        return {"ok": True}

    def __getitem__(self, key):
        # starting_seq.py calls outbound_dispatcher["dispatch"](...) -- dict
        # subscript is the locked convention across pipeline.py/batch_mode.py.
        # This is additive (not a shape the fake didn't already support) so
        # the dict-subscript call site is exercised, not attribute access.
        if key == "dispatch":
            return self.dispatch
        raise KeyError(key)


def _session_row():
    return {
        "id": "d1", "sender_e164": "+5989", "status": "awaiting_farmer",
        "source_capture_ids": ["cap1"], "reply_target_kind": "dm", "group_id": None,
        "draft_json": {
            # NOTE: event_date is "YYYY-MM-DD" (dashed) -- the real
            # seeding_session schema pattern (schemas/seeding_session.py:76),
            # not "YYYYMMDD". yyyymmdd_to_yymmdd requires the dashed form;
            # the undashed form raises ValueError and the mint would fail.
            "type": "seeding_session", "event_date": "2026-05-22",
            "needs_input": "starting_seq",
            "groups": [
                {"parent": {"value": "P1"}, "species": {"value": "KOY"},
                 "qty": {"value": 2}, "child_block_names": {"value": []}},
                {"parent": {"value": "P2"}, "species": {"value": "KOY"},
                 "qty": {"value": 3}, "child_block_names": {"value": []}},
            ],
        },
    }


async def test_numeric_reply_mints_seq_across_groups():
    """B5: SEQ is per-session. Group 2 continues from group 1, it does not restart."""
    db, d = FakeDb(_session_row()), FakeDispatcher()
    res = await handle_starting_seq_reply(
        draft_id="d1", reply_text="4", capture_ctx={},
        pool=None, extraction_db=db, outbound_dispatcher=d, log=None)
    assert res["ok"] is True
    groups = db.row["draft_json"]["groups"]
    assert [n[-1] for n in groups[0]["child_block_names"]["value"]] == ["4", "5"]
    assert [n[-1] for n in groups[1]["child_block_names"]["value"]] == ["6", "7", "8"]


async def test_reply_clears_needs_input():
    db, d = FakeDb(_session_row()), FakeDispatcher()
    await handle_starting_seq_reply(draft_id="d1", reply_text="4", capture_ctx={},
                                    pool=None, extraction_db=db, outbound_dispatcher=d, log=None)
    assert not db.row["draft_json"].get("needs_input")


async def test_second_reply_is_idempotent_noop():
    row = _session_row()
    row["draft_json"].pop("needs_input")
    db, d = FakeDb(row), FakeDispatcher()
    res = await handle_starting_seq_reply(draft_id="d1", reply_text="YES", capture_ctx={},
                                          pool=None, extraction_db=db, outbound_dispatcher=d, log=None)
    assert res == {"ok": True, "noop": True}
    assert db.updates == []


async def test_unclear_reply_redispatches_askback_without_minting():
    db, d = FakeDb(_session_row()), FakeDispatcher()
    res = await handle_starting_seq_reply(draft_id="d1", reply_text="dunno", capture_ctx={},
                                          pool=None, extraction_db=db, outbound_dispatcher=d, log=None)
    assert db.row["draft_json"]["groups"][0]["child_block_names"]["value"] == []
    assert any("askback" in effect for effect, _ in d.calls)


async def test_missing_draft_returns_reason():
    db, d = FakeDb(None), FakeDispatcher()
    res = await handle_starting_seq_reply(draft_id="nope", reply_text="4", capture_ctx={},
                                          pool=None, extraction_db=db, outbound_dispatcher=d, log=None)
    assert res["ok"] is False
