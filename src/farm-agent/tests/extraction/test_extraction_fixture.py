"""May-22 fixture replay test + FND-04 schema parity re-verify.

SC-1: Direct schema parity -- validate expected-draft.json through Submission.model_validate
      to prove the fixture conforms to the real ported schema.

SC-2: Extractor replay -- mocked tool_use returning the fixture's Submission dict;
      assert 1 seeding_session / 5 groups / 11 children / exact block names / per-field provenance.

SC-4: FND-04 parity re-verify -- build_tool_spec()["input_schema"] is SUBMISSION_JSON_SCHEMA
      (identity), so the extractor's schema is the same object the FND-04 gate already passes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from farm_agent.extraction.schemas.submission import SUBMISSION_JSON_SCHEMA, Submission
from tests.conftest import FakeAnthropicClientForExtractor

FIXTURE_DIR = (
    Path(__file__).parent.parent / "fixtures" / "extraction" / "seeding-session-may22"
)

EXPECTED_CHILD_NAMES = [
    "260522_SHI_1",
    "260522_SHI_2",
    "260522_SHI_3",
    "260522_KOY_4",
    "260522_KOY_5",
    "260522_KOY_6",
    "260522_KOY_7",
    "260522_KOY_8",
    "260522_KOY_9",
    "260522_KOY_10",
    "260522_KOY_11",
]


def _load_expected_draft() -> dict:
    """Load the bare SeedingSession draft from the fixture file."""
    return json.loads((FIXTURE_DIR / "expected-draft.json").read_text())


def _build_submission_dict(draft: dict) -> dict:
    """Wrap a bare draft into a valid Submission envelope dict."""
    return {
        "drafts": [
            {
                "draft": draft,
                "per_field_confidence": {
                    "event_date": 0.98,
                    "groups": 0.95,
                },
            }
        ],
        "continuity": "start_new",
        "continuity_reason": "New seeding session",
        "capture_kind": "voice_note",
    }


# ---------------------------------------------------------------------------
# SC-1: Direct schema parity via model_validate
# ---------------------------------------------------------------------------


def test_fixture_validates_against_submission_schema():
    """Validate the May-22 expected-draft.json fixture through Submission.model_validate.

    This proves the fixture conforms to the real ported Python schema (FND-04 anchor).
    Any schema mismatch here means the port diverged from the locked fixture.
    """
    draft = _load_expected_draft()
    submission_dict = _build_submission_dict(draft)

    # Must not raise
    submission = Submission.model_validate(submission_dict)

    # Spot-check structure
    assert len(submission.drafts) == 1
    first_draft = submission.drafts[0].draft
    assert first_draft.type == "seeding_session"
    assert len(first_draft.groups) == 5


# ---------------------------------------------------------------------------
# SC-2: Extractor replay with mocked tool_use
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extractor_replay_may22_fixture():
    """Replay the May-22 fixture through create_extractor with a mocked tool_use.

    Asserts:
    - result["ok"] is True
    - draft type is "seeding_session"
    - 5 groups
    - 11 children total
    - exact child block names (child names, NOT parent attribution -- parents are
      intentionally ambiguous in the source audio)
    - per-field provenance present on each group field
    """
    from farm_agent.extraction.extractor import create_extractor  # noqa: PLC0415

    draft = _load_expected_draft()
    submission_dict = _build_submission_dict(draft)

    client = FakeAnthropicClientForExtractor([{"tool_input": submission_dict}])
    extractor = create_extractor(client=client)

    result = await extractor["extract"](
        captures=[
            {
                "text": "May 22 inoc session",
                "transcript": None,
                "images": [],
            }
        ]
    )

    assert result["ok"] is True, f"extract failed: {result.get('reason')}"

    first_draft_submission = result["drafts"][0]
    assert isinstance(first_draft_submission, dict)
    seeding_session = first_draft_submission["draft"]
    assert isinstance(seeding_session, dict), (
        "pack_result must hand downstream plain dicts, not pydantic models"
    )

    # Type check
    assert seeding_session["type"] == "seeding_session"

    # 5 groups
    assert len(seeding_session["groups"]) == 5, (
        f"Expected 5 groups, got {len(seeding_session['groups'])}"
    )

    # 11 children total across all groups
    all_child_names = []
    for group in seeding_session["groups"]:
        child_block_names_field = group["child_block_names"]
        # child_block_names is Provenanced[list[ChildBlockNameOrSentinel]]
        names = child_block_names_field["value"]
        all_child_names.extend(names)

    assert len(all_child_names) == 11, (
        f"Expected 11 children, got {len(all_child_names)}: {all_child_names}"
    )

    # Exact child block names (assert names, NOT parent attribution -- see CONTEXT.md)
    assert all_child_names == EXPECTED_CHILD_NAMES, (
        f"Child block names mismatch.\n"
        f"Expected: {EXPECTED_CHILD_NAMES}\n"
        f"Got:      {all_child_names}"
    )

    # Per-field provenance present on each group field
    for i, group in enumerate(seeding_session["groups"]):
        assert "value" in group["parent"], f"Group {i}: parent.value missing"
        assert "confidence" in group["parent"], f"Group {i}: parent.confidence missing"
        assert "sources" in group["parent"], f"Group {i}: parent.sources missing"

        assert "value" in group["species"], f"Group {i}: species.value missing"
        assert "value" in group["qty"], f"Group {i}: qty.value missing"
        assert "value" in group["child_block_names"], f"Group {i}: child_block_names.value missing"

        # confidence must be in [0, 1]
        assert 0.0 <= group["parent"]["confidence"] <= 1.0, (
            f"Group {i}: parent.confidence={group['parent']['confidence']} out of range"
        )


# ---------------------------------------------------------------------------
# SC-4: FND-04 parity re-verify -- build_tool_spec() uses SUBMISSION_JSON_SCHEMA
# ---------------------------------------------------------------------------


def test_build_tool_spec_uses_submission_json_schema():
    """build_tool_spec()["input_schema"] must be identical to SUBMISSION_JSON_SCHEMA.

    This proves the extractor passes the same schema object that the FND-04 parity
    test already verified against the Node fixture. No structural drift possible.
    """
    from farm_agent.extraction.extractor import build_tool_spec  # noqa: PLC0415

    spec = build_tool_spec()
    assert spec["input_schema"] is SUBMISSION_JSON_SCHEMA, (
        "build_tool_spec() must pass SUBMISSION_JSON_SCHEMA directly as input_schema "
        "(identity check -- same object, not a copy)"
    )
    assert spec["name"] == "submit_extraction"


def test_fnd04_parity_still_passes():
    """Re-verify FND-04: Submission.model_json_schema() structural diff is clean.

    Calls the existing normalize_schema + structural comparison from test_schema_parity.py.
    This re-verifies the gate against the real extractor's Submission schema without
    duplicating the full diff logic.
    """
    import json  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415
    from tests.test_schema_parity import normalize_schema  # noqa: PLC0415

    fixture_path = Path(__file__).parent.parent / "fixtures" / "submission_json_schema.json"
    fixture = json.loads(fixture_path.read_text())

    norm_fixture = normalize_schema(fixture)
    norm_actual = normalize_schema(SUBMISSION_JSON_SCHEMA)

    assert norm_actual == norm_fixture, (
        "FND-04 parity FAILED after extractor schema import.\n"
        f"Fixture keys: {sorted(norm_fixture.keys())}\n"
        f"Actual keys:  {sorted(norm_actual.keys())}"
    )
