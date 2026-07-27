"""
test_farmos_fidelity_gate.py -- Tests for the CSV fidelity gate (FWR-03 / D-06 / D-07).

Behaviours under test:
- block absent from CSV -> {"pass": False, "reason": "block_not_in_csv"} (pass-through, D-07)
- draft strain == CSV strain -> {"pass": True}
- draft strain != CSV strain -> hold with hold_status="fidelity_cross_check_unverified" + ask_back_msg
- ask_back_msg is non-empty and contains NO em-dash character
- load_fidelity_csv returns [] on missing file (non-fatal, D-07)
- load_fidelity_csv loads the fixture CSV correctly
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from farm_agent.farmos.fidelity_gate import (
    check_fidelity,
    load_fidelity_csv,
    render_fidelity_ask_back,
)

FIXTURE_CSV = Path(__file__).parent / "fixtures" / "farmos" / "fidelity_csv_sample.csv"


# ---------------------------------------------------------------------------
# load_fidelity_csv
# ---------------------------------------------------------------------------


def test_load_fidelity_csv_returns_list():
    rows = load_fidelity_csv(str(FIXTURE_CSV))
    assert isinstance(rows, list)
    assert len(rows) >= 1


def test_load_fidelity_csv_has_expected_columns():
    rows = load_fidelity_csv(str(FIXTURE_CSV))
    first = rows[0]
    assert "block_name" in first
    assert "strain_code" in first


def test_load_fidelity_csv_missing_file_returns_empty():
    rows = load_fidelity_csv("/nonexistent/path/does_not_exist.csv")
    assert rows == []


def test_load_fidelity_csv_poy_row_present():
    rows = load_fidelity_csv(str(FIXTURE_CSV))
    names = {r["block_name"] for r in rows}
    assert "260101_POY_1" in names


# ---------------------------------------------------------------------------
# check_fidelity: block absent from CSV (pass-through, D-07)
# ---------------------------------------------------------------------------


def test_check_fidelity_block_not_in_csv_passes_through():
    draft = {
        "block_name": "260999_XYZ_99",
        "draft_json": {"species_code": "XYZ"},
    }
    rows = load_fidelity_csv(str(FIXTURE_CSV))
    result = check_fidelity(draft, rows)
    assert result["pass"] is False
    assert result["reason"] == "block_not_in_csv"


def test_check_fidelity_empty_csv_rows_passes_through():
    draft = {
        "block_name": "260101_KOY_1",
        "draft_json": {"species_code": "KOY"},
    }
    result = check_fidelity(draft, [])
    assert result["pass"] is False
    assert result["reason"] == "block_not_in_csv"


# ---------------------------------------------------------------------------
# check_fidelity: agreement -> pass True
# ---------------------------------------------------------------------------


def test_check_fidelity_agreement_passes():
    draft = {
        "block_name": "260101_KOY_1",
        "draft_json": {"species_code": "KOY"},
    }
    rows = load_fidelity_csv(str(FIXTURE_CSV))
    result = check_fidelity(draft, rows)
    assert result["pass"] is True


def test_check_fidelity_agreement_shi_passes():
    draft = {
        "block_name": "260201_SHI_3",
        "draft_json": {"species_code": "SHI"},
    }
    rows = load_fidelity_csv(str(FIXTURE_CSV))
    result = check_fidelity(draft, rows)
    assert result["pass"] is True


# ---------------------------------------------------------------------------
# check_fidelity: disagreement -> hold (D-06)
# ---------------------------------------------------------------------------


def test_check_fidelity_mismatch_returns_hold_status():
    # draft says KOY but CSV says POY (260101_POY_1 row)
    draft = {
        "block_name": "260101_POY_1",
        "draft_json": {"species_code": "KOY"},
    }
    rows = load_fidelity_csv(str(FIXTURE_CSV))
    result = check_fidelity(draft, rows)
    assert result["pass"] is False
    assert result["reason"] == "strain_mismatch"
    assert result["hold_status"] == "fidelity_cross_check_unverified"
    assert result["draft_strain"] == "KOY"
    assert result["csv_strain"] == "POY"
    assert isinstance(result["ask_back_msg"], str)
    assert result["ask_back_msg"]  # non-empty


def test_check_fidelity_mismatch_poy_vs_koy():
    # The canonical POY-as-KOY scenario: block name is POY, draft extracted as KOY.
    draft = {
        "block_name": "260101_POY_1",
        "draft_json": {"species_code": "KOY"},
    }
    rows = load_fidelity_csv(str(FIXTURE_CSV))
    result = check_fidelity(draft, rows)
    assert result["hold_status"] == "fidelity_cross_check_unverified"
    assert result["draft_strain"] == "KOY"
    assert result["csv_strain"] == "POY"


def test_check_fidelity_mismatch_both_keys_present():
    draft = {
        "block_name": "260101_POY_1",
        "draft_json": {"species_code": "KOY"},
    }
    rows = load_fidelity_csv(str(FIXTURE_CSV))
    result = check_fidelity(draft, rows)
    assert "hold_status" in result
    assert "ask_back_msg" in result


# ---------------------------------------------------------------------------
# render_fidelity_ask_back: no em-dash, contains key info
# ---------------------------------------------------------------------------


def test_render_fidelity_ask_back_no_em_dash():
    msg = render_fidelity_ask_back("260101_POY_1", "KOY", "POY")
    assert "—" not in msg  # em-dash U+2014
    assert "–" not in msg  # en-dash U+2013


def test_render_fidelity_ask_back_contains_block_name():
    msg = render_fidelity_ask_back("260101_POY_1", "KOY", "POY")
    assert "260101_POY_1" in msg


def test_render_fidelity_ask_back_contains_both_strains():
    msg = render_fidelity_ask_back("260101_POY_1", "KOY", "POY")
    assert "KOY" in msg
    assert "POY" in msg


def test_render_fidelity_ask_back_is_non_empty():
    msg = render_fidelity_ask_back("260101_POY_1", "POY", "KOY")
    assert msg.strip()
