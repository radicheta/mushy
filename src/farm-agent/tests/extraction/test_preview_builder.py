"""Rendering parity for the extraction preview builder. Pure strings."""

from farm_agent.extraction.preview_builder import (
    REPLY_SUFFIX,
    build_confirm_prompt,
    build_preview,
    build_top_question,
    classify_field,
    render_scalar,
    render_seeding_session,
    render_starting_seq_ask_back,
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
    # The prior version of this test filtered rows on `"|" in ln`, but the
    # table itself is padded with a two-space gutter (_pad_row) and never
    # contains "|" -- only the constant footer line does. That made the
    # filtered list a single element and the assertion vacuous regardless of
    # whether padding worked. This version locates the real header + data
    # rows by position and checks their alignment directly.
    draft = {
        "type": "seeding_session",
        "event_date": "2026-05-22",
        "groups": [
            {"parent": {"value": "KOY"}, "species": {"value": "KOY"},
             "qty": {"value": 3}, "child_block_names": {"value": ["a", "b", "c"]}},
            {"parent": {"value": "SHIITAKE-LONG"}, "species": {"value": "SHI"},
             "qty": {"value": 11}, "child_block_names": {"value": []}},
        ],
    }
    out = render_seeding_session(draft)
    lines = out.splitlines()
    # Layout: [header, summary, "", col_header, row1, row2, "", footer].
    # The column header + one data row per group start right after the blank
    # line following the summary line.
    table_start = 3
    table_lines = lines[table_start : table_start + 1 + len(draft["groups"])]
    assert len(table_lines) == 3

    # CHILDREN is the last column and is deliberately left unpadded (see
    # _pad_row's comment: "Last column needs no trailing pad"), so only the
    # KEY/PARENT/SPECIES/QTY *prefix* is guaranteed to line up across rows --
    # not the full line length, which varies with CHILDREN's content. The
    # fixture's CHILDREN text is known ahead of time (no range-collapse: "a",
    # "b", "c" have no trailing "_SEQ", and group 2 has none), so stripping
    # it off each line isolates the padded prefix for comparison.
    last_col_text = ["CHILDREN", "a, b, c", ""]
    prefix_lengths = {
        len(ln) - len(tail) for ln, tail in zip(table_lines, last_col_text, strict=True)
    }
    assert len(prefix_lengths) == 1, f"table columns are ragged: {table_lines!r}"


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


def test_render_scalar_bool_lowercase_matches_node():
    # Node's renderScalar has no boolean branch; it falls through to
    # String(v), which is lowercase "true"/"false". Python's str(bool) would
    # give "True"/"False" -- pin the Node-matching lowercase form.
    assert render_scalar(True) == "true"
    assert render_scalar(False) == "false"


def test_render_starting_seq_ask_back_matches_node():
    draft = {"event_date": "2026-05-22", "groups": [{"qty": {"value": 3}}, {"qty": {"value": 2}}]}
    out = render_starting_seq_ask_back(draft)
    assert out == (
        "Inoc session: 2026-05-22\n"
        "5 blocks across 2 parents (awaiting starting block-number)\n\n"
        "Reply with the starting SEQ (e.g. 4)."
    )


def test_render_starting_seq_ask_back_missing_date_fallback():
    draft = {"groups": [{"qty": {"value": 3}}]}
    out = render_starting_seq_ask_back(draft)
    assert out.startswith("Inoc session: [?]\n")


def test_render_seeding_session_missing_date_fallback():
    draft = {"type": "seeding_session", "groups": [{"qty": {"value": 1}}]}
    out = render_seeding_session(draft)
    assert out.startswith("Inoc session: [?]\n")


def test_seeding_session_overflow_more_groups():
    groups = [
        {"parent": {"value": f"P{i}"}, "species": {"value": "SHI"}, "qty": {"value": 1}}
        for i in range(7)
    ]
    draft = {"type": "seeding_session", "event_date": "20260101", "groups": groups}
    out = render_seeding_session(draft)
    lines = out.splitlines()
    assert "... (2 more groups)" in lines
    # Only the first 5 groups render as table rows (KEY 1..5); group 6/7 do not.
    assert "6" not in [ln.split()[0] for ln in lines if ln[:1].isdigit()]


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


# ---------------------------------------------------------------------------
# MUSHY-86: asset-ref existence surfaced in the preview
# ---------------------------------------------------------------------------


def test_flat_preview_warns_that_a_proposed_asset_does_not_exist():
    """An unresolvable asset_ref reaches the farmer flagged, not as a plain row."""
    from farm_agent.extraction.preview_builder import build_preview

    out = build_preview(
        draft={"type": "observation", "asset_ref": "260530_KOY_7", "notes": "pinning"},
        per_field_confidence={},
        threshold=0.7,
        required_fields=["asset_ref", "event_timestamp"],
        asset_ref_checks={
            "260530_KOY_7": {"status": "new", "near_misses": ["260530_KOS_7"]}
        },
    )

    assert "New in farmOS, will be created: 260530_KOY_7 (did you mean 260530_KOS_7?)" in out


def test_flat_preview_is_unchanged_when_every_ref_resolves():
    """The check must be invisible when it finds nothing wrong."""
    from farm_agent.extraction.preview_builder import build_preview

    kwargs = dict(
        draft={"type": "observation", "asset_ref": "260530_KOS_7", "notes": "pinning"},
        per_field_confidence={},
        threshold=0.7,
        required_fields=["asset_ref", "event_timestamp"],
    )

    assert build_preview(**kwargs) == build_preview(
        **kwargs, asset_ref_checks={"260530_KOS_7": {"status": "exists", "near_misses": []}}
    )


def test_session_preview_warns_above_the_commit_footer():
    """The 2026-08-18 misread was a session parent, so the table renderer needs it too."""
    from farm_agent.extraction.preview_builder import render_seeding_session

    out = render_seeding_session(
        {
            "type": "seeding_session",
            "event_date": "2026-05-30",
            "groups": [{
                "parent": {"value": "260530_KOY_7", "confidence": 0.9, "sources": ["audio"]},
                "species": {"value": "KOY", "confidence": 0.9, "sources": ["audio"]},
                "qty": {"value": 4, "confidence": 0.9, "sources": ["audio"]},
                "child_block_names": {
                    "value": ["260601_KOY_1"], "confidence": 0.9, "sources": ["audio"],
                },
            }],
        },
        asset_ref_checks={
            "260530_KOY_7": {"status": "new", "near_misses": ["260530_KOS_7"]}
        },
    )

    assert "did you mean 260530_KOS_7?" in out
    assert out.index("did you mean") < out.index("YES to commit")


def test_confirm_prompt_carries_the_ref_warning_through():
    """The clean-extraction path is where the 2026-08-18 KOY row reached the farmer."""
    from farm_agent.extraction.preview_builder import build_confirm_prompt

    out = build_confirm_prompt(
        draft={"type": "observation", "asset_ref": "260530_KOY_7", "notes": "pinning"},
        per_field_confidence={},
        threshold=0.7,
        required_fields=["asset_ref", "event_timestamp"],
        asset_ref_checks={
            "260530_KOY_7": {"status": "new", "near_misses": ["260530_KOS_7"]}
        },
    )

    assert "did you mean 260530_KOS_7?" in out


def test_low_confidence_field_shows_its_value_and_marker():
    """MUSHY-132: an ask-back must show the value it is asking about."""
    draft = {"type": "harvest", "harvest_batch_id": "H1", "qty_g": 500,
             "source_block_refs": ["b1"], "event_timestamp": "2026-05-22T10:00:00Z"}
    out = build_preview(draft=draft, per_field_confidence={"qty_g": 0.3},
                        threshold=0.7, required_fields=["qty_g"])
    assert "qty_g: 500 [?]" in out


def test_confirm_prompt_keeps_low_confidence_value():
    """MUSHY-132: stripping [?] at confirm time must not blank the field."""
    draft = {"type": "harvest", "harvest_batch_id": "H1", "qty_g": 500,
             "source_block_refs": ["b1"], "event_timestamp": "2026-05-22T10:00:00Z"}
    out = build_confirm_prompt(draft=draft, per_field_confidence={"qty_g": 0.3},
                               threshold=0.7, required_fields=["qty_g"])
    assert "qty_g: 500" in out
    assert "[?]" not in out


def test_missing_field_still_renders_bare_marker():
    draft = {"type": "harvest", "harvest_batch_id": "H1", "qty_g": None,
             "source_block_refs": ["b1"], "event_timestamp": "2026-05-22T10:00:00Z"}
    out = build_preview(draft=draft, per_field_confidence={}, threshold=0.7,
                        required_fields=["qty_g"])
    assert "qty_g: [?]" in out
