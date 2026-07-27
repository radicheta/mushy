"""FND-04: JSON-Schema parity gate.

Structural-diff parity test: Submission.model_json_schema() must equal the
committed Node zod-to-json-schema fixture after normalization.

normalize_schema() handles cosmetic differences between zod-to-json-schema 3.x
(draft-7, 'definitions' key) and pydantic v2 ('$defs' key, adds 'title' fields):

  1. $defs -> definitions key rename
  2. #/$defs/ -> #/definitions/ in $ref paths
  3. Inline all $ref references (pydantic puts models in $defs; fixture inlines them
     because zod does not produce named definitions for anonymous objects)
  4. Strip 'title', 'description', 'default' keys (pydantic adds these; zod does not)
  5. Sort 'required' arrays (ordering may differ between pydantic and zod)
  6. Remove top-level '$schema' key (zod adds this; pydantic does not)
  7. Remove 'definitions'/'$defs' section after inlining (no longer needed)

The fixture is ground truth.  The models adapt to match it, never the reverse.
"""

import json
from pathlib import Path

import pytest

from farm_agent.extraction.schemas.submission import SUBMISSION_JSON_SCHEMA
from farm_agent.extraction.schemas.observation import ObservationLog

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "submission_json_schema.json"


def _resolve_ref(ref: str, root: dict) -> dict:
    """Resolve a JSON Pointer $ref string against the root schema."""
    # Strip leading '#/'
    parts = ref.lstrip("#/").split("/")
    node = root
    for p in parts:
        if isinstance(node, list):
            node = node[int(p)]
        else:
            node = node[p]
    return node


def _inline_refs(node, root: dict, seen_refs: frozenset = frozenset()) -> dict:
    """Recursively inline all $ref occurrences.

    Tracks already-seen refs to avoid infinite recursion on circular schemas
    (the fixture does not have circular refs, but this is defensive).
    """
    if isinstance(node, dict):
        if "$ref" in node and len(node) == 1:
            # Pure $ref (no sibling keys) — inline it
            ref = node["$ref"]
            if ref in seen_refs:
                # Circular — return as-is to avoid infinite loop
                return node
            resolved = _resolve_ref(ref, root)
            return _inline_refs(resolved, root, seen_refs | {ref})
        else:
            return {k: _inline_refs(v, root, seen_refs) for k, v in node.items()}
    elif isinstance(node, list):
        return [_inline_refs(item, root, seen_refs) for item in node]
    else:
        return node


def normalize_schema(schema: dict) -> dict:
    """Normalize cosmetic differences between pydantic v2 and zod-to-json-schema output.

    Handles:
    1. Rename $defs -> definitions and fix $ref paths
    2. Handle top-level $ref (zod fixture wraps root in {$ref, definitions, $schema})
    3. Inline all $ref references recursively
    4. Strip cosmetic keys: title, description, default, $schema
    5. Remove definitions/$defs section (all refs are now inlined)
    6. Sort required arrays
    """
    # Step 1: Rename $defs -> definitions and update $ref paths
    s = json.dumps(schema)
    s = s.replace('"$defs"', '"definitions"')
    s = s.replace("#/$defs/", "#/definitions/")
    obj = json.loads(s)

    # Step 2: Handle top-level $ref (zod fixture pattern: {$ref, definitions, $schema})
    # When the root has a $ref alongside other keys, resolve the $ref to get the
    # real root object, then inline all remaining $refs within it.
    if "$ref" in obj and "definitions" in obj:
        root_ref = obj["$ref"]
        resolved = _resolve_ref(root_ref, obj)
        # Start with the resolved object and inline remaining $refs
        obj = _inline_refs(resolved, obj)
    else:
        # Pydantic output: inline $refs from $defs within the object itself
        obj = _inline_refs(obj, obj)

    # Step 3 & 4 & 5 & 6: Strip cosmetic keys, remove definitions, sort required
    obj = _clean_node(obj)

    return obj


def _clean_node(node):
    """Recursively strip cosmetic keys and sort required arrays."""
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            # Strip cosmetic/structural noise
            if k in ("title", "description", "default", "$schema", "definitions", "$defs"):
                continue
            # Strip top-level $ref (fixture has $ref+definitions at root;
            # after inlining the $ref is no longer needed)
            if k == "$ref":
                continue
            out[k] = _clean_node(v)
        # Sort required arrays for stable comparison
        if "required" in out and isinstance(out["required"], list):
            out["required"] = sorted(out["required"])
        return out
    elif isinstance(node, list):
        return [_clean_node(item) for item in node]
    else:
        return node


def _load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text())


def _get_seeding_fragment(fixture: dict) -> dict:
    """Extract the seeding member (anyOf[0]) from the fixture."""
    submission = fixture["definitions"]["Submission"]
    drafts_items = submission["properties"]["drafts"]["items"]
    return drafts_items["properties"]["draft"]["anyOf"][0]


# ---------------------------------------------------------------------------
# Task 1 (Spike): seeding-fragment parity
# ---------------------------------------------------------------------------


def test_seeding_fragment_parity():
    """Spike: normalized seeding log matches fixture fragment.

    Pitfall 2 verdict: pydantic v2 emits exclusiveMinimum:0 (numeric, draft-7 form)
    for int Field(gt=0). No normalizer adjustment needed for this.
    """
    fixture = _load_fixture()
    seeding_fixture = _get_seeding_fragment(fixture)

    actual_schema = SUBMISSION_JSON_SCHEMA

    # Normalize both
    norm_fixture_seeding = normalize_schema(seeding_fixture)

    norm_actual = normalize_schema(actual_schema)

    # Navigate to draft field in normalized actual schema.
    # In the spike (single-member Union), pydantic emits draft directly (no anyOf).
    # In Task 2 (6-member Union), pydantic emits anyOf and we take member 0.
    draft_field = (
        norm_actual.get("properties", {})
        .get("drafts", {})
        .get("items", {})
        .get("properties", {})
        .get("draft", {})
    )
    # If anyOf present (Task 2), take first member; otherwise the field IS the seeding object
    if "anyOf" in draft_field:
        actual_seeding = draft_field["anyOf"][0]
    else:
        actual_seeding = draft_field

    assert actual_seeding == norm_fixture_seeding, (
        f"Seeding fragment mismatch.\n"
        f"Fixture:  {json.dumps(norm_fixture_seeding, indent=2)}\n"
        f"Actual:   {json.dumps(actual_seeding, indent=2)}"
    )


# ---------------------------------------------------------------------------
# Task 2: full parity tests
# ---------------------------------------------------------------------------


def test_submission_schema_matches_fixture():
    """Full structural diff: normalized Submission schema == normalized fixture.

    The fixture top-level has $ref + definitions wrapping the Submission object.
    Pydantic emits the Submission type:object directly at the root.
    normalize_schema() inlines all $refs so both reduce to the same inline structure.
    """
    fixture = _load_fixture()
    actual = SUBMISSION_JSON_SCHEMA

    # The fixture has top-level: {$ref: '#/definitions/Submission', definitions: {...}}
    # normalize_schema inlines the $ref -> the Submission object, then cleans up.
    # pydantic output is already the Submission object inline.
    norm_fixture = normalize_schema(fixture)
    norm_actual = normalize_schema(actual)

    assert norm_actual == norm_fixture, (
        f"Full schema mismatch.\n"
        f"Fixture keys: {sorted(norm_fixture.keys())}\n"
        f"Actual keys:  {sorted(norm_actual.keys())}\n"
        f"Fixture: {json.dumps(norm_fixture, indent=2)}\n"
        f"Actual:  {json.dumps(norm_actual, indent=2)}"
    )


def test_all_models_forbid_extra():
    """Every schema object with 'properties' must have additionalProperties:false."""
    actual = SUBMISSION_JSON_SCHEMA
    violations = []
    _check_additional_properties(actual, path="root", violations=violations)
    assert not violations, (
        "Models missing extra='forbid' (additionalProperties:false):\n"
        + "\n".join(violations)
    )


def test_observation_requires_state_or_notes():
    """ObservationLog with both state and notes None raises ValueError."""
    with pytest.raises(Exception):
        ObservationLog(
            type="observation",
            asset_ref="block_ref",
            state=None,
            notes=None,
            event_timestamp="2025-06-14T10:00:00Z",
            confidence={},
        )

    # Passes when state is set
    log = ObservationLog(
        type="observation",
        asset_ref="block_ref",
        state="healthy",
        notes=None,
        event_timestamp="2025-06-14T10:00:00Z",
        confidence={},
    )
    assert log.state == "healthy"

    # Passes when notes is set
    log2 = ObservationLog(
        type="observation",
        asset_ref="block_ref",
        state=None,
        notes="looking good",
        event_timestamp="2025-06-14T10:00:00Z",
        confidence={},
    )
    assert log2.notes == "looking good"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _check_additional_properties(node, path: str, violations: list[str]) -> None:
    """Recursively check that every object with 'properties' has additionalProperties:false."""
    if isinstance(node, dict):
        if "properties" in node:
            if node.get("additionalProperties") is not False:
                violations.append(path)
        for k, v in node.items():
            _check_additional_properties(v, f"{path}.{k}", violations)
    elif isinstance(node, list):
        for i, item in enumerate(node):
            _check_additional_properties(item, f"{path}[{i}]", violations)
