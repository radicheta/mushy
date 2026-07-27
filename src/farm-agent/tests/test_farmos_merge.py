"""Tests for farm_agent.farmos.merge (Phase 62-03).

Cross-language golden fixture: every case asserts Python merge_asset_fields output
deep-equals the captured Node merge.js output.
"""
from __future__ import annotations

import json
import pathlib
import pytest

from farm_agent.farmos.merge import (
    IdentityMutationError,
    STABLE_NOTES_SEPARATOR,
    merge_asset_fields,
)

FIXTURE_PATH = pathlib.Path(__file__).parent / "fixtures" / "farmos" / "merge_golden.json"


def load_golden():
    with FIXTURE_PATH.open() as f:
        return json.load(f)


GOLDEN = load_golden()
GOLDEN_BY_ID = {c["id"]: c for c in GOLDEN}


# ---------------------------------------------------------------------------
# Cross-language golden fixture tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "case",
    [c for c in GOLDEN if c.get("thrown") is None],
    ids=[c["id"] for c in GOLDEN if c.get("thrown") is None],
)
def test_golden_merge_parity(case):
    """Python merge_asset_fields deep-equals Node merge.js output for each golden case."""
    result = merge_asset_fields(case["existing"], case["incoming"])
    assert result["merged"] == case["merged"], (
        f"[{case['id']}] merged mismatch"
    )
    assert result["conflicts"] == case["conflicts"], (
        f"[{case['id']}] conflicts mismatch"
    )


def test_golden_identity_mutation_name():
    """Golden fixture: name mutation raises IdentityMutationError with correct attrs."""
    case = GOLDEN_BY_ID["identity_mutation_name"]
    thrown = case["thrown"]
    with pytest.raises(IdentityMutationError) as exc_info:
        merge_asset_fields(case["existing"], case["incoming"])
    err = exc_info.value
    assert err.field == thrown["field"]
    assert err.existing == thrown["existing"]
    assert err.incoming == thrown["incoming"]
    assert str(err) == thrown["message"]


# ---------------------------------------------------------------------------
# Behavioural unit tests (mirror merge.test.js)
# ---------------------------------------------------------------------------


def _asset(**overrides):
    """Build a base asset--fungi dict, mirroring merge.test.js asset()."""
    base = {
        "id": "a1",
        "type": "asset--fungi",
        "attributes": {"name": "X", "notes": {"value": "", "format": "plain_text"}},
        "relationships": {
            "parent": {"data": []},
            "qr_codes": {"data": []},
            "farm_id_tag": {"data": []},
            "fungi_type": {"data": None},
            "fungi_xing": {"data": None},
        },
    }
    out = {**base, **overrides}
    out["attributes"] = {**base["attributes"], **overrides.get("attributes", {})}
    out["relationships"] = {**base["relationships"], **overrides.get("relationships", {})}
    return out


def test_array_ref_union_preserves_existing_first_order():
    existing = _asset(relationships={"parent": {"data": [{"id": "p1", "type": "asset--fungi"}]}})
    incoming = _asset(relationships={"parent": {"data": [{"id": "p2", "type": "asset--fungi"}]}})
    result = merge_asset_fields(existing, incoming)
    assert result["merged"]["relationships"]["parent"]["data"] == [
        {"id": "p1", "type": "asset--fungi"},
        {"id": "p2", "type": "asset--fungi"},
    ]
    assert result["conflicts"] == []


def test_array_ref_union_dedup_drops_duplicate_ids():
    existing = _asset(
        relationships={
            "parent": {
                "data": [
                    {"id": "p1", "type": "asset--fungi"},
                    {"id": "p2", "type": "asset--fungi"},
                ]
            }
        }
    )
    incoming = _asset(
        relationships={
            "parent": {
                "data": [
                    {"id": "p2", "type": "asset--fungi"},
                    {"id": "p3", "type": "asset--fungi"},
                ]
            }
        }
    )
    result = merge_asset_fields(existing, incoming)
    assert [r["id"] for r in result["merged"]["relationships"]["parent"]["data"]] == [
        "p1",
        "p2",
        "p3",
    ]
    assert result["conflicts"] == []


def test_identity_mutation_error_raised_on_name_change():
    existing = _asset(attributes={"name": "X"})
    incoming = _asset(attributes={"name": "Y"})
    with pytest.raises(IdentityMutationError) as exc_info:
        merge_asset_fields(existing, incoming)
    err = exc_info.value
    assert err.field == "name"
    assert err.existing == "X"
    assert err.incoming == "Y"


def test_identity_mutation_error_raised_on_type_change():
    existing = _asset()
    incoming = {**_asset(), "type": "asset--plant"}
    with pytest.raises(IdentityMutationError) as exc_info:
        merge_asset_fields(existing, incoming)
    err = exc_info.value
    assert err.field == "type"


def test_scalar_rel_equal_is_noop():
    existing = _asset(
        relationships={"fungi_type": {"data": {"id": "ft-shi", "type": "taxonomy_term--fungi_type"}}}
    )
    incoming = _asset(
        relationships={"fungi_type": {"data": {"id": "ft-shi", "type": "taxonomy_term--fungi_type"}}}
    )
    result = merge_asset_fields(existing, incoming)
    assert result["conflicts"] == []
    assert result["merged"]["relationships"]["fungi_type"]["data"]["id"] == "ft-shi"


def test_scalar_rel_differ_surfaces_conflict_and_retains_existing():
    existing = _asset(
        relationships={"fungi_type": {"data": {"id": "ft-shi", "type": "taxonomy_term--fungi_type"}}}
    )
    incoming = _asset(
        relationships={"fungi_type": {"data": {"id": "ft-koy", "type": "taxonomy_term--fungi_type"}}}
    )
    result = merge_asset_fields(existing, incoming)
    assert len(result["conflicts"]) == 1
    assert result["conflicts"][0] == {
        "field": "fungi_type",
        "existing": "ft-shi",
        "incoming": "ft-koy",
        "kind": "scalar_conflict",
    }
    # merged retains existing
    assert result["merged"]["relationships"]["fungi_type"]["data"]["id"] == "ft-shi"


def test_scalar_rel_null_take():
    existing = _asset(relationships={"fungi_type": {"data": None}})
    incoming = _asset(
        relationships={"fungi_type": {"data": {"id": "ft-shi", "type": "taxonomy_term--fungi_type"}}}
    )
    result = merge_asset_fields(existing, incoming)
    assert result["merged"]["relationships"]["fungi_type"]["data"]["id"] == "ft-shi"
    assert result["conflicts"] == []


def test_notes_dedup_splits_on_separator_and_appends_new():
    existing = _asset(
        attributes={"name": "X", "notes": {"value": "entry_A\n---\nentry_B", "format": "plain_text"}}
    )
    incoming = _asset(
        attributes={"name": "X", "notes": {"value": "entry_B\n---\nentry_C", "format": "plain_text"}}
    )
    result = merge_asset_fields(existing, incoming)
    assert result["merged"]["attributes"]["notes"]["value"] == "entry_A\n---\nentry_B\n---\nentry_C"
    assert STABLE_NOTES_SEPARATOR == "\n---\n"


def test_stub_marker_survives_merge_unstripped():
    existing = _asset(
        attributes={
            "name": "X",
            "notes": {"value": "STUB - awaits 2025-paper-scan backfill", "format": "plain_text"},
        }
    )
    incoming = _asset(
        attributes={"name": "X", "notes": {"value": "real inoc 2026-05-22", "format": "plain_text"}}
    )
    result = merge_asset_fields(existing, incoming)
    notes_value = result["merged"]["attributes"]["notes"]["value"]
    assert "STUB - awaits 2025-paper-scan backfill" in notes_value
    assert "real inoc 2026-05-22" in notes_value


def test_existing_not_mutated_by_merge():
    """merge_asset_fields must not mutate the existing dict (uses deepcopy)."""
    existing = _asset(
        relationships={"parent": {"data": [{"id": "p1", "type": "asset--fungi"}]}}
    )
    incoming = _asset(
        relationships={"parent": {"data": [{"id": "p2", "type": "asset--fungi"}]}}
    )
    original_parent_data = list(existing["relationships"]["parent"]["data"])
    merge_asset_fields(existing, incoming)
    assert existing["relationships"]["parent"]["data"] == original_parent_data


def test_stable_notes_separator_constant():
    assert STABLE_NOTES_SEPARATOR == "\n---\n"
