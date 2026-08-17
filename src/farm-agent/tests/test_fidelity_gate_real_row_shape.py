"""MUSHY-39 -- the fidelity gate must read block_name from where it actually lives.

check_fidelity read draft["block_name"], but signal_draft HAS NO block_name column
(verified against the live schema: id, sender_e164, log_type, draft_json, ... and
no block_name). So on every real row it resolved to "" -> "block_not_in_csv" ->
pass-through. The v1.11 POY->KOY misattribution guard (T-62-09) was dead in
production, and the existing tests hid it by passing a hand-built dict with a
top-level block_name that no production row ever has.

Canonical location is draft_json.block_name -- the seeding extraction schema
requires it and commit-seeding.js:47 reads `dj.block_name`.
"""

import pytest

from farm_agent.farmos.fidelity_gate import check_fidelity

# The POY-as-KOY misread that motivated the guard (memory:
# project_backfill_extraction_fidelity_38pct_silent_misattribution).
CSV = [{"block_name": "250522_POY_4", "strain_code": "POY"}]


def _real_draft_row(block_name: str = "250522_POY_4", species: str = "KOY") -> dict:
    """A row shaped like signal_draft actually is -- no top-level block_name."""
    return {
        "id": "draft-real",
        "sender_e164": "+59899000001",
        "status": "confirmed",
        "log_type": "seeding",
        "draft_json": {"block_name": block_name, "species_code": species, "qty": 5},
        "per_field_confidence": {},
        "commit_attempt_count": 0,
        "origin": "python",
    }


def test_mismatch_is_caught_on_a_real_row_shape():
    """The whole point of the gate: POY in CSV vs KOY in draft must HOLD."""
    result = check_fidelity(_real_draft_row(), CSV)

    assert result.get("reason") == "strain_mismatch", (
        f"MUSHY-39: gate passed a POY/KOY mismatch on a production row shape: {result}"
    )
    assert result["draft_strain"] == "KOY"
    assert result["csv_strain"] == "POY"
    assert result["hold_status"] == "fidelity_cross_check_unverified"
    assert "250522_POY_4" in result["ask_back_msg"]


def test_agreement_on_a_real_row_shape_passes():
    """Guard the other direction: a matching strain must still pass cleanly."""
    result = check_fidelity(_real_draft_row(species="POY"), CSV)
    assert result.get("pass") is True, f"matching strain should pass, got {result}"


def test_block_absent_from_csv_still_passes_through():
    """D-07 preserved: CSV is non-authoritative, absence is not a hard reject."""
    result = check_fidelity(_real_draft_row(block_name="250523_SHI_1"), CSV)
    assert result.get("reason") == "block_not_in_csv"


def test_top_level_block_name_still_honoured():
    """Back-compat: callers that already flatten block_name keep working."""
    row = _real_draft_row()
    row["block_name"] = row["draft_json"].pop("block_name")
    result = check_fidelity(row, CSV)
    assert result.get("reason") == "strain_mismatch", (
        f"flattened block_name must still be read: {result}"
    )


@pytest.mark.parametrize("dj", [None, {}, {"species_code": "KOY"}])
def test_missing_block_name_is_a_safe_pass_through(dj):
    """No block reference anywhere -> pass-through, never a crash."""
    row = _real_draft_row()
    row["draft_json"] = dj
    result = check_fidelity(row, CSV)
    assert result.get("reason") == "block_not_in_csv"
