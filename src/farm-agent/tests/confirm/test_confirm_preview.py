"""Confirm-loop farmer copy. Exact strings; these are what the farmer reads."""

import pytest

from farm_agent.confirm.preview import (
    build_confirm_ack,
    build_discard_ack,
    build_edit_cap_msg,
    build_expired_note,
    build_idempotent_ack,
    build_nudge,
    build_preview_with_suffix,
)


def test_confirm_ack_truncates_draft_id_to_10():
    assert build_confirm_ack("a" * 64) == "Locked in. Writing now. (draft " + "a" * 10 + ")"


def test_idempotent_ack():
    assert build_idempotent_ack() == "Already locked in. Check the previous message."


def test_discard_ack():
    assert build_discard_ack() == "Discarded. Nothing written."


def test_nudge_rounds_minutes():
    out = build_nudge(minutes_remaining=6.4)
    assert "6 min" in out


def test_nudge_clamps_negative_to_zero():
    assert "0 min" in build_nudge(minutes_remaining=-5)


def test_nudge_handles_missing_minutes():
    assert "0 min" in build_nudge()


def test_nudge_appends_preview_summary():
    out = build_nudge(minutes_remaining=6, preview_summary="harvest 500 g")
    assert out.endswith("harvest 500 g")


def test_nudge_ignores_blank_preview_summary():
    out = build_nudge(minutes_remaining=6, preview_summary="   ")
    assert out.rstrip().endswith("min.")


def test_edit_cap_msg_exact_string():
    assert build_edit_cap_msg(3) == (
        "I cannot get this right after 3 tries. Try splitting the message into "
        "smaller updates, or send NO to discard."
    )


def test_expired_note():
    assert build_expired_note() == (
        "Draft expired. Nothing was written. Send a fresh message if you still want to log this."
    )


def test_preview_with_suffix_strips_question_markers():
    draft = {"type": "harvest", "harvest_batch_id": "H1", "qty_g": 500,
             "source_block_refs": ["b1"], "event_timestamp": "t"}
    out = build_preview_with_suffix(draft=draft, per_field_confidence={"qty_g": 0.1},
                                    required_fields=["qty_g"], threshold=0.7)
    assert "[?]" not in out
    assert out.endswith("Reply YES to commit, NO to discard, EDIT <text> to amend.")


@pytest.mark.parametrize("fn,args", [
    (build_confirm_ack, ("x" * 12,)),
    (build_idempotent_ack, ()),
    (build_discard_ack, ()),
    (build_expired_note, ()),
    (build_edit_cap_msg, (3,)),
])
def test_no_em_dashes_anywhere(fn, args):
    assert "—" not in fn(*args)
