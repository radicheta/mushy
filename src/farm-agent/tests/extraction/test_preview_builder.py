"""Rendering parity for the extraction preview builder. Pure strings."""

from farm_agent.extraction.preview_builder import (
    REPLY_SUFFIX,
    build_confirm_prompt,
    build_preview,
    build_top_question,
    classify_field,
    render_seeding_session,
    render_value,
    sanitize_farmer_text,
)


def test_sanitize_strips_em_dashes():
    out = sanitize_farmer_text("harvest — 500 g")
    assert "—" not in out


def test_sanitize_is_idempotent():
    once = sanitize_farmer_text("a — b")
    assert sanitize_farmer_text(once) == once


def test_preview_marks_low_confidence_fields():
    draft = {"type": "harvest", "harvest_batch_id": "H1", "qty_g": 500,
             "source_block_refs": ["b1"], "event_timestamp": "2026-05-22T10:00:00Z"}
    out = build_preview(draft=draft, per_field_confidence={"qty_g": 0.3},
                        threshold=0.7, required_fields=["qty_g"])
    assert "[?]" in out


def test_preview_omits_marker_when_confident():
    draft = {"type": "harvest", "harvest_batch_id": "H1", "qty_g": 500,
             "source_block_refs": ["b1"], "event_timestamp": "2026-05-22T10:00:00Z"}
    out = build_preview(draft=draft, per_field_confidence={"qty_g": 0.95},
                        threshold=0.7, required_fields=["qty_g"])
    assert "[?]" not in out


def test_preview_never_contains_em_dash():
    draft = {"type": "harvest", "harvest_batch_id": "H — 1", "qty_g": 500,
             "source_block_refs": ["b1"], "event_timestamp": "t"}
    out = build_preview(draft=draft, per_field_confidence={},
                        threshold=0.7, required_fields=[])
    assert "—" not in out


def test_preview_on_none_draft_does_not_raise():
    out = build_preview(draft=None, per_field_confidence=None,
                        threshold=0.7, required_fields=[])
    assert isinstance(out, str)


def test_top_question_prefers_missing_over_low_conf():
    # harvest.qty_g.miss template (verbatim from Node preview-builder.js:36)
    # phrases the question in grams, not "qty" -- assert the actual template,
    # not a paraphrase of the field name.
    q = build_top_question(missing_fields=["qty_g"], low_conf_fields=["notes"],
                           draft_type="harvest")
    assert q == "How many grams were harvested?"


def test_seeding_session_table_columns_align():
    draft = {
        "type": "seeding_session",
        "event_date": "20260522",
        "groups": [
            {"parent": {"value": "KOY"}, "species": {"value": "KOY"},
             "qty": {"value": 3}, "child_block_names": {"value": ["a", "b", "c"]}},
            {"parent": {"value": "SHIITAKE-LONG"}, "species": {"value": "SHI"},
             "qty": {"value": 11}, "child_block_names": {"value": []}},
        ],
    }
    out = render_seeding_session(draft)
    lines = [ln for ln in out.splitlines() if "|" in ln]
    widths = {len(ln) for ln in lines}
    assert len(widths) == 1, f"table rows are ragged: {widths}"


def test_render_value_none_is_marker():
    assert render_value(None) == "[?]"


def test_render_value_number_uses_fmt_num():
    assert render_value(500.0) == "500"
    assert render_value(94.39994) == "94.4"


def test_render_value_list_joins_scalars():
    assert render_value(["b1", "b2"]) == "[b1, b2]"


def test_classify_field_missing_empty_string():
    draft = {"qty_g": ""}
    assert classify_field("qty_g", draft, {}, 0.7) == "missing"


def test_classify_field_low_conf():
    draft = {"qty_g": 500}
    assert classify_field("qty_g", draft, {"qty_g": 0.3}, 0.7) == "low_conf"


def test_classify_field_ok():
    draft = {"qty_g": 500}
    assert classify_field("qty_g", draft, {"qty_g": 0.9}, 0.7) == "ok"


def test_build_confirm_prompt_strips_question_marks_and_appends_suffix():
    draft = {"type": "harvest", "harvest_batch_id": "H1", "qty_g": 500,
             "source_block_refs": ["b1"], "event_timestamp": "2026-05-22T10:00:00Z"}
    out = build_confirm_prompt(draft=draft, per_field_confidence={"qty_g": 0.3},
                               threshold=0.7, required_fields=["qty_g"])
    assert "[?]" not in out
    assert out.endswith(REPLY_SUFFIX)


def test_build_confirm_prompt_never_contains_em_dash():
    draft = {"type": "harvest", "harvest_batch_id": "H — 1", "qty_g": 500,
             "source_block_refs": ["b1"], "event_timestamp": "t"}
    out = build_confirm_prompt(draft=draft, per_field_confidence={},
                               threshold=0.7, required_fields=[])
    assert "—" not in out


def test_fmt_num_matches_the_chamber_implementation():
    """The Foray seam forbids extraction importing chamber, so fmt_num is
    duplicated. Tests are not bound by the seam, so pin the two together:
    if either copy changes behaviour, this fails."""
    from farm_agent.chamber.message import fmt_num as chamber_fmt_num
    from farm_agent.extraction.preview_builder import fmt_num as extraction_fmt_num

    cases = [None, float("nan"), 0, -0.04, -0.06, 90, 94.39994, 1.5000000000000013,
             2.5, 0.05, 1234.567, "not a number", "12.34"]
    for c in cases:
        assert extraction_fmt_num(c) == chamber_fmt_num(c), f"drift on {c!r}"
