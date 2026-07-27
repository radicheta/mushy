"""Tests for farm_agent.farmos.commits.normalize (Phase 62-08).

Port of src/agents/alerter/test/farmos/normalize.test.js.
Covers common transforms, per-type transforms, idempotency, non-mutation,
and array non-aliasing.
"""
from __future__ import annotations

import math

import pytest

from farm_agent.farmos.commits.normalize import normalize


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def make_draft(log_type: str, draft_json: dict) -> dict:
    return {"id": "test-1", "log_type": log_type, "draft_json": draft_json}


# ---------------------------------------------------------------------------
# Common transforms
# ---------------------------------------------------------------------------

class TestCommonTransforms:
    def test_event_timestamp_iso_to_unix_seconds_floor(self):
        draft = make_draft("activity", {
            "name": "water",
            "asset_ref": "Q1",
            "event_timestamp": "2026-05-15T14:30:00.000Z",
        })
        out = normalize(draft)["draft_json"]
        assert isinstance(out["timestamp"], (int, float))
        # Expected: floor(parse("2026-05-15T14:30:00.000Z") / 1000)
        import datetime
        expected = math.floor(
            datetime.datetime.fromisoformat("2026-05-15T14:30:00+00:00").timestamp()
        )
        assert out["timestamp"] == expected

    def test_event_timestamp_skipped_when_timestamp_already_number(self):
        draft = make_draft("activity", {
            "timestamp": 9999999,
            "event_timestamp": "2026-05-15T14:30:00.000Z",
        })
        out = normalize(draft)["draft_json"]
        assert out["timestamp"] == 9999999

    def test_asset_ref_to_qr_codes_single_element(self):
        draft = make_draft("activity", {"name": "water", "asset_ref": "Q42", "timestamp": 1000})
        out = normalize(draft)["draft_json"]
        assert out["qr_codes"] == ["Q42"]

    def test_asset_ref_unknown_yields_empty_qr_codes(self):
        draft = make_draft("activity", {"name": "water", "asset_ref": "<UNKNOWN>", "timestamp": 1000})
        out = normalize(draft)["draft_json"]
        assert out["qr_codes"] == []

    def test_asset_ref_skipped_when_qr_codes_already_array(self):
        draft = make_draft("activity", {
            "name": "water", "asset_ref": "Q-old", "qr_codes": ["Q-new"], "timestamp": 1000,
        })
        out = normalize(draft)["draft_json"]
        assert out["qr_codes"] == ["Q-new"]

    def test_missing_both_timestamps_leaves_timestamp_absent(self):
        draft = make_draft("activity", {"name": "water", "asset_ref": "Q1"})
        out = normalize(draft)["draft_json"]
        assert "timestamp" not in out


# ---------------------------------------------------------------------------
# Activity: name -> activity_subtype
# ---------------------------------------------------------------------------

class TestActivityTransform:
    def test_name_copied_to_activity_subtype(self):
        draft = make_draft("activity", {"name": "relocate", "asset_ref": "Q1", "timestamp": 1000})
        out = normalize(draft)["draft_json"]
        assert out["activity_subtype"] == "relocate"

    def test_activity_subtype_already_present_not_overwritten(self):
        draft = make_draft("activity", {
            "name": "water", "activity_subtype": "sterilize", "qr_codes": ["Q1"], "timestamp": 1000,
        })
        out = normalize(draft)["draft_json"]
        assert out["activity_subtype"] == "sterilize"


# ---------------------------------------------------------------------------
# Harvest transforms
# ---------------------------------------------------------------------------

class TestHarvestTransform:
    def test_source_block_refs_to_source_qr_codes_verbatim(self):
        draft = make_draft("harvest", {
            "source_block_refs": ["260515_SHI_1", "260515_SHI_2"],
            "harvest_batch_id": "HBATCH-2026-05-15-SHI-001",
            "qty_g": 120,
            "timestamp": 1000,
        })
        out = normalize(draft)["draft_json"]
        assert out["source_qr_codes"] == ["260515_SHI_1", "260515_SHI_2"]

    def test_harvest_batch_id_to_harvest_batch_name(self):
        draft = make_draft("harvest", {
            "source_block_refs": ["260515_SHI_1"],
            "harvest_batch_id": "HBATCH-2026-05-15-SHI-001",
            "qty_g": 100,
            "timestamp": 1000,
        })
        out = normalize(draft)["draft_json"]
        assert out["harvest_batch_name"] == "HBATCH-2026-05-15-SHI-001"

    def test_qty_g_to_bags_single_synthesized_bag(self):
        draft = make_draft("harvest", {
            "source_block_refs": ["260515_SHI_1"],
            "harvest_batch_id": "HBATCH-001",
            "qty_g": 250,
            "timestamp": 1000,
        })
        out = normalize(draft)["draft_json"]
        assert isinstance(out.get("bags"), list)
        assert out["bags"] == [{"weight_grams": 250}]

    def test_when_qty_g_absent_bags_remain_absent(self):
        draft = make_draft("harvest", {
            "source_block_refs": ["260515_SHI_1"],
            "harvest_batch_id": "HBATCH-001",
            "timestamp": 1000,
        })
        out = normalize(draft)["draft_json"]
        assert "bags" not in out


# ---------------------------------------------------------------------------
# Seeding: species -> species_code
# ---------------------------------------------------------------------------

class TestSeedingTransform:
    def test_species_copied_to_species_code_when_absent(self):
        draft = make_draft("seeding", {
            "species": "SHI",
            "block_name": "260515_SHI_1",
            "qty": 5,
            "timestamp": 1000,
        })
        out = normalize(draft)["draft_json"]
        assert out["species_code"] == "SHI"

    def test_species_code_already_present_not_overwritten(self):
        draft = make_draft("seeding", {
            "species": "SHI",
            "species_code": "MAI",
            "block_name": "260515_MAI_1",
            "qty": 3,
            "timestamp": 1000,
        })
        out = normalize(draft)["draft_json"]
        assert out["species_code"] == "MAI"

    def test_batch_name_and_parent_batch_name_stay_distinct(self):
        draft = make_draft("seeding", {
            "species": "DT",
            "block_name": "260515_DT_1",
            "qty": 2,
            "batch_name": "STERI-2026-05-15",
            "parent_batch_name": "260510_DT_3",
            "timestamp": 1000,
        })
        out = normalize(draft)["draft_json"]
        assert out["batch_name"] == "STERI-2026-05-15"
        assert out["parent_batch_name"] == "260510_DT_3"


# ---------------------------------------------------------------------------
# Input: recipe_lot prepended to notes (D-09)
# ---------------------------------------------------------------------------

class TestInputTransform:
    def test_recipe_lot_prepended_before_existing_notes(self):
        draft = make_draft("input", {
            "recipe_lot": "RB-2026-05",
            "asset_ref": "Q1",
            "notes": "some existing notes",
            "timestamp": 1000,
        })
        out = normalize(draft)["draft_json"]
        assert out["notes"] == "recipe_lot: RB-2026-05\nsome existing notes"

    def test_recipe_lot_prepended_when_notes_absent(self):
        draft = make_draft("input", {
            "recipe_lot": "RB-2026-05",
            "asset_ref": "Q1",
            "timestamp": 1000,
        })
        out = normalize(draft)["draft_json"]
        assert out["notes"] == "recipe_lot: RB-2026-05"

    def test_recipe_lot_field_deleted_from_output(self):
        draft = make_draft("input", {
            "recipe_lot": "RB-2026-05",
            "asset_ref": "Q1",
            "timestamp": 1000,
        })
        out = normalize(draft)["draft_json"]
        assert "recipe_lot" not in out


# ---------------------------------------------------------------------------
# Observation: state appended to notes
# ---------------------------------------------------------------------------

class TestObservationTransform:
    def test_state_appended_to_notes(self):
        draft = make_draft("observation", {
            "asset_ref": "Q1",
            "state": "pinning",
            "notes": "looking good",
            "timestamp": 1000,
        })
        out = normalize(draft)["draft_json"]
        assert out["notes"] == "looking good\nstate: pinning"

    def test_state_written_when_notes_absent(self):
        draft = make_draft("observation", {
            "asset_ref": "Q1",
            "state": "contaminated",
            "timestamp": 1000,
        })
        out = normalize(draft)["draft_json"]
        assert out["notes"] == "state: contaminated"

    def test_state_field_deleted_from_output(self):
        draft = make_draft("observation", {
            "asset_ref": "Q1",
            "state": "pinning",
            "timestamp": 1000,
        })
        out = normalize(draft)["draft_json"]
        assert "state" not in out


# ---------------------------------------------------------------------------
# Idempotency (SCHEMA-03): commit-shape input passes through unchanged
# ---------------------------------------------------------------------------

class TestIdempotencyCommitShape:
    def test_activity_commit_shape_passes_through(self):
        commit_shape = {
            "activity_subtype": "relocate",
            "qr_codes": ["Q1"],
            "timestamp": 1700000000,
            "notes": "moved to shelf 3",
        }
        draft = make_draft("activity", dict(commit_shape))
        out = normalize(draft)["draft_json"]
        assert out == commit_shape

    def test_harvest_commit_shape_passes_through(self):
        commit_shape = {
            "source_qr_codes": ["260515_SHI_1"],
            "harvest_batch_name": "HBATCH-2026-05-15-SHI-001",
            "bags": [{"weight_grams": 200}],
            "timestamp": 1700000000,
        }
        draft = make_draft("harvest", dict(commit_shape))
        out = normalize(draft)["draft_json"]
        assert out == commit_shape

    def test_seeding_commit_shape_passes_through(self):
        commit_shape = {
            "species_code": "SHI",
            "block_name": "260515_SHI_1",
            "qr_codes": ["260515_SHI_1"],
            "qty": 5,
            "timestamp": 1700000000,
        }
        draft = make_draft("seeding", dict(commit_shape))
        out = normalize(draft)["draft_json"]
        assert out == commit_shape

    def test_input_commit_shape_passes_through(self):
        # When recipe_lot has already been prepended, no recipe_lot field remains
        commit_shape = {
            "qr_codes": ["Q1"],
            "notes": "recipe_lot: RB-2026-05\nIngredients:\n- oat 1kg",
            "input_ingredients": ["oat 1kg"],
            "timestamp": 1700000000,
        }
        draft = make_draft("input", dict(commit_shape))
        out = normalize(draft)["draft_json"]
        assert out == commit_shape

    def test_observation_commit_shape_passes_through(self):
        # state already in notes; no state field
        commit_shape = {
            "qr_codes": ["Q1"],
            "notes": "looking good\nstate: pinning",
            "timestamp": 1700000000,
        }
        draft = make_draft("observation", dict(commit_shape))
        out = normalize(draft)["draft_json"]
        assert out == commit_shape


# ---------------------------------------------------------------------------
# Idempotency on extractor-shape: normalizing twice == normalizing once (CR-01)
# ---------------------------------------------------------------------------

class TestIdempotencyExtractorShape:
    def test_input_normalize_twice_same_as_once(self):
        draft = make_draft("input", {"recipe_lot": "RB", "asset_ref": "Q1", "timestamp": 1000})
        pass1 = normalize(draft)
        pass2 = normalize(pass1)
        assert pass2["draft_json"]["notes"] == pass1["draft_json"]["notes"]
        assert "recipe_lot" not in pass2["draft_json"]

    def test_observation_normalize_twice_same_as_once(self):
        draft = make_draft("observation", {"state": "pinning", "asset_ref": "Q1", "timestamp": 1000})
        pass1 = normalize(draft)
        pass2 = normalize(pass1)
        assert pass2["draft_json"]["notes"] == pass1["draft_json"]["notes"]
        assert "state" not in pass2["draft_json"]


# ---------------------------------------------------------------------------
# Array non-aliasing (WR-01)
# ---------------------------------------------------------------------------

class TestArrayNonAliasing:
    def test_pushing_to_result_qr_codes_does_not_mutate_input(self):
        draft = make_draft("activity", {
            "qr_codes": ["Q1"],
            "activity_subtype": "water",
            "timestamp": 1000,
        })
        result = normalize(draft)
        result["draft_json"]["qr_codes"].append("Q2")
        assert draft["draft_json"]["qr_codes"] == ["Q1"]


# ---------------------------------------------------------------------------
# Non-mutation
# ---------------------------------------------------------------------------

class TestNonMutation:
    def test_returns_new_object_not_input(self):
        draft = make_draft("activity", {"name": "water", "asset_ref": "Q1", "timestamp": 1000})
        result = normalize(draft)
        assert result is not draft

    def test_input_draft_json_unchanged_after_normalize(self):
        dj = {"name": "water", "asset_ref": "Q1", "event_timestamp": "2026-05-15T14:30:00.000Z"}
        draft = make_draft("activity", dj)
        normalize(draft)
        # Original draft_json must not be mutated
        assert draft["draft_json"] is dj
        assert "qr_codes" not in dj
        assert "timestamp" not in dj
        assert "activity_subtype" not in dj
