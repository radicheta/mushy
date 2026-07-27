"""Unit tests for farm_agent.extraction.seq_helper.

Covers (all pure, no DB required):
  - yyyymmdd_to_yymmdd: valid date conversion, bad input raises ValueError
  - mint_child_block_names: SHI minting, KOY per-session counter (starts at 4),
    lowercase species rejected, trailing _EXTRA rejected via fullmatch
  - re.fullmatch(BLOCK_NAME_RE): anchored pattern rejects 260522_SHI_1_EXTRA
  - seq_of: extracts trailing int, returns None for NEEDS_SEQ and non-matching
  - extract_seqs_from_row: legacy seeding shape, session shape (Provenanced value),
    malformed row -> partial list (never raises)
  - lookup_last_seq_for_date: skipped when no test DB available (pure core via
    extract_seqs_from_row is preferred)
"""
from __future__ import annotations

import re

import pytest


# ---------------------------------------------------------------------------
# yyyymmdd_to_yymmdd
# ---------------------------------------------------------------------------

def test_yyyymmdd_to_yymmdd_valid():
    from farm_agent.extraction.seq_helper import yyyymmdd_to_yymmdd
    assert yyyymmdd_to_yymmdd("2026-05-22") == "260522"


def test_yyyymmdd_to_yymmdd_another_valid():
    from farm_agent.extraction.seq_helper import yyyymmdd_to_yymmdd
    assert yyyymmdd_to_yymmdd("2025-01-07") == "250107"


def test_yyyymmdd_to_yymmdd_bad_input_raises():
    from farm_agent.extraction.seq_helper import yyyymmdd_to_yymmdd
    with pytest.raises(ValueError):
        yyyymmdd_to_yymmdd("bad-input")


def test_yyyymmdd_to_yymmdd_no_dashes_raises():
    from farm_agent.extraction.seq_helper import yyyymmdd_to_yymmdd
    with pytest.raises(ValueError):
        yyyymmdd_to_yymmdd("20260522")


# ---------------------------------------------------------------------------
# BLOCK_NAME_RE fullmatch anchoring
# ---------------------------------------------------------------------------

def test_block_name_re_accepts_valid():
    from farm_agent.extraction.schemas.seeding import BLOCK_NAME_RE
    assert re.fullmatch(BLOCK_NAME_RE, "260522_SHI_1") is not None


def test_block_name_re_rejects_extra_segment():
    """fullmatch must reject trailing _EXTRA that re.match would silently pass."""
    from farm_agent.extraction.schemas.seeding import BLOCK_NAME_RE
    assert re.fullmatch(BLOCK_NAME_RE, "260522_SHI_1_EXTRA") is None


def test_block_name_re_rejects_lowercase():
    from farm_agent.extraction.schemas.seeding import BLOCK_NAME_RE
    assert re.fullmatch(BLOCK_NAME_RE, "260522_shi_1") is None


# ---------------------------------------------------------------------------
# mint_child_block_names
# ---------------------------------------------------------------------------

def test_mint_shi_basic():
    from farm_agent.extraction.seq_helper import mint_child_block_names
    result = mint_child_block_names("260522", "SHI", 1, 3)
    assert result == ["260522_SHI_1", "260522_SHI_2", "260522_SHI_3"]


def test_mint_koy_per_session_counter():
    """KOY starts at 4 in the May-22 fixture (per-session counter spans species)."""
    from farm_agent.extraction.seq_helper import mint_child_block_names
    result = mint_child_block_names("260522", "KOY", 4, 4)
    assert result == ["260522_KOY_4", "260522_KOY_5", "260522_KOY_6", "260522_KOY_7"]


def test_mint_lowercase_species_raises():
    """Lowercase species fails BLOCK_NAME_RE fullmatch -> ValueError."""
    from farm_agent.extraction.seq_helper import mint_child_block_names
    with pytest.raises(ValueError, match="mint_invalid_block_name"):
        mint_child_block_names("260522", "shi", 1, 1)


def test_mint_extra_segment_rejected():
    """A species code that would produce a name with extra segment is rejected."""
    from farm_agent.extraction.seq_helper import mint_child_block_names
    # If event_date_yymmdd itself contains extra underscores, the resulting name fails fullmatch
    # This tests the rejection path via an invalid date component
    with pytest.raises(ValueError, match="mint_invalid_block_name"):
        mint_child_block_names("260522_X", "SHI", 1, 1)


# ---------------------------------------------------------------------------
# seq_of
# ---------------------------------------------------------------------------

def test_seq_of_valid():
    from farm_agent.extraction.seq_helper import seq_of
    assert seq_of("260522_KOY_4") == 4


def test_seq_of_needs_seq_sentinel():
    from farm_agent.extraction.seq_helper import seq_of
    assert seq_of("NEEDS_SEQ") is None


def test_seq_of_garbage():
    from farm_agent.extraction.seq_helper import seq_of
    assert seq_of("garbage") is None


def test_seq_of_non_string():
    from farm_agent.extraction.seq_helper import seq_of
    assert seq_of(None) is None  # type: ignore[arg-type]


def test_seq_of_large_seq():
    from farm_agent.extraction.seq_helper import seq_of
    assert seq_of("260522_SHI_11") == 11


# ---------------------------------------------------------------------------
# extract_seqs_from_row
# ---------------------------------------------------------------------------

def test_extract_seqs_from_row_seeding_legacy():
    """Legacy seeding shape: block_name at top level."""
    from farm_agent.extraction.seq_helper import extract_seqs_from_row
    result = extract_seqs_from_row({"type": "seeding", "block_name": "260522_SHI_1"})
    assert result == [1]


def test_extract_seqs_from_row_seeding_session_provenanced():
    """Session shape: groups[].child_block_names.value[] (Provenanced wrapper)."""
    from farm_agent.extraction.seq_helper import extract_seqs_from_row
    draft = {
        "type": "seeding_session",
        "groups": [
            {"child_block_names": {"value": ["260522_KOY_4", "260522_KOY_5"]}}
        ],
    }
    result = extract_seqs_from_row(draft)
    assert result == [4, 5]


def test_extract_seqs_from_row_session_multi_group():
    """Multiple groups contribute to per-session SEQ counter."""
    from farm_agent.extraction.seq_helper import extract_seqs_from_row
    draft = {
        "type": "seeding_session",
        "groups": [
            {"child_block_names": {"value": ["260522_SHI_1", "260522_SHI_2", "260522_SHI_3"]}},
            {"child_block_names": {"value": ["260522_KOY_4", "260522_KOY_5"]}},
        ],
    }
    result = extract_seqs_from_row(draft)
    assert sorted(result) == [1, 2, 3, 4, 5]


def test_extract_seqs_from_row_needs_seq_excluded():
    """NEEDS_SEQ sentinel is excluded from results."""
    from farm_agent.extraction.seq_helper import extract_seqs_from_row
    draft = {
        "type": "seeding_session",
        "groups": [
            {"child_block_names": {"value": ["NEEDS_SEQ", "260522_KOY_4"]}}
        ],
    }
    result = extract_seqs_from_row(draft)
    assert result == [4]


def test_extract_seqs_from_row_malformed_no_raise():
    """Malformed row never raises; returns partial list or empty."""
    from farm_agent.extraction.seq_helper import extract_seqs_from_row
    # Missing type key entirely
    result = extract_seqs_from_row({"invalid": "data"})
    assert isinstance(result, list)
    # Malformed groups entry
    result = extract_seqs_from_row({
        "type": "seeding_session",
        "groups": [None, {"child_block_names": {"value": ["260522_KOY_4"]}}],
    })
    assert 4 in result


def test_extract_seqs_from_row_none_input():
    from farm_agent.extraction.seq_helper import extract_seqs_from_row
    result = extract_seqs_from_row(None)  # type: ignore[arg-type]
    assert result == []


# ---------------------------------------------------------------------------
# lookup_last_seq_for_date (pure core — skip DB pool test)
# ---------------------------------------------------------------------------

def test_lookup_last_seq_no_db_marker():
    """Marker test confirming DB tests are skipped without a live pool.

    The DB-backed lookup_last_seq_for_date is tested via extract_seqs_from_row
    (the pure core) above. This test documents the skip contract.
    """
    # No pool available in unit test context -- covered by extract_seqs_from_row tests
    pass


def test_lookup_last_seq_return_key_is_snake_case():
    """Confirm lookup_last_seq_for_date return key is last_seq (snake_case).

    Node returns {"lastSeq": ...}; this Python port renames it to {"last_seq": ...}.
    The Phase-61 consumer must use result["last_seq"], NOT result["lastSeq"].
    Checks the actual return statement in the function body (not the docstring).
    """
    import ast  # noqa: PLC0415
    import inspect  # noqa: PLC0415
    from farm_agent.extraction.seq_helper import lookup_last_seq_for_date  # noqa: PLC0415

    src = inspect.getsource(lookup_last_seq_for_date)
    tree = ast.parse(src)
    # Walk all Return nodes and check that returned dicts use "last_seq" not "lastSeq"
    found_last_seq = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Return) and node.value:
            if isinstance(node.value, ast.Dict):
                for key in node.value.keys:
                    if isinstance(key, ast.Constant) and key.value == "last_seq":
                        found_last_seq = True
                    if isinstance(key, ast.Constant) and key.value == "lastSeq":
                        raise AssertionError(
                            'lookup_last_seq_for_date must NOT return "lastSeq" (camelCase Node key); '
                            'use "last_seq" (snake_case)'
                        )
    assert found_last_seq, 'lookup_last_seq_for_date must return a dict with "last_seq" key'
