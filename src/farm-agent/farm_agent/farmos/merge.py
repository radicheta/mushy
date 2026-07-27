"""Pure merge for asset--fungi fields (Phase 62-03).

Byte-identical Python port of src/agents/alerter/src/farmos/merge.js.

Rules:
  - identity scalars (name, type): throw IdentityMutationError on mutation
  - array-ref fields (parent / qr_codes / farm_id_tag): set-union by id
  - scalar rels (fungi_type / fungi_xing): null=take, equal=noop, differ=conflict-keep-existing
  - scalar attrs (status): same scalar rule as scalar rels
  - notes: split on STABLE_NOTES_SEPARATOR, strip, dedup preserving order, rejoin

Cross-ref: 62-03-PLAN.md; merge.js Phase 51 UPSERT-03.
"""
from __future__ import annotations

import copy

STABLE_NOTES_SEPARATOR = "\n---\n"

ARRAY_REF_FIELDS = ["parent", "qr_codes", "farm_id_tag"]
SCALAR_REL_FIELDS = ["fungi_type", "fungi_xing"]
SCALAR_ATTR_FIELDS = ["status"]


class IdentityMutationError(Exception):
    """Raised when an incoming asset tries to change a name-based identity scalar."""

    def __init__(self, field: str, existing, incoming):
        super().__init__("identity_mutation:" + field)
        self.field = field
        self.existing = existing
        self.incoming = incoming


def _union_array_ref(existing_data, incoming_data):
    """Set-union by id, existing-first, preserving insertion order. Mirrors unionArrayRef."""
    existing_arr = existing_data if isinstance(existing_data, list) else []
    incoming_arr = incoming_data if isinstance(incoming_data, list) else []
    by_id = {}
    for ref in existing_arr:
        if ref and ref.get("id") is not None and ref["id"] not in by_id:
            by_id[ref["id"]] = ref
    for ref in incoming_arr:
        if ref and ref.get("id") is not None and ref["id"] not in by_id:
            by_id[ref["id"]] = ref
    return list(by_id.values())


def _merge_notes(existing_notes, incoming_notes):
    """Split-dedup-join on STABLE_NOTES_SEPARATOR. Mirrors mergeNotes."""
    existing_value = (existing_notes or {}).get("value", "") or ""
    incoming_value = (incoming_notes or {}).get("value", "") or ""
    sep = STABLE_NOTES_SEPARATOR
    entries = [s.strip() for s in existing_value.split(sep) if s.strip()]
    for entry in (s.strip() for s in incoming_value.split(sep) if s.strip()):
        if entry not in entries:
            entries.append(entry)
    return {"value": sep.join(entries), "format": "plain_text"}


def merge_asset_fields(existing: dict, incoming: dict) -> dict:
    """Merge incoming asset fields into existing, returning {"merged": dict, "conflicts": list}.

    Byte-identical semantics to Node mergeAssetFields.
    Raises IdentityMutationError if incoming mutates name or type.
    Never mutates either input dict.
    """
    # Identity check: name
    existing_name = (existing or {}).get("attributes", {}).get("name") if existing else None
    incoming_name = (incoming or {}).get("attributes", {}).get("name") if incoming else None
    if incoming_name is not None and existing_name != incoming_name:
        raise IdentityMutationError("name", existing_name, incoming_name)

    # Identity check: type
    if (
        incoming
        and incoming.get("type") is not None
        and existing
        and existing.get("type") != incoming.get("type")
    ):
        raise IdentityMutationError("type", existing.get("type"), incoming.get("type"))

    merged = copy.deepcopy(existing)
    conflicts = []

    # Array-ref set-union by id
    if incoming and incoming.get("relationships"):
        for field in ARRAY_REF_FIELDS:
            incoming_rel = incoming["relationships"].get(field)
            if incoming_rel is None:
                continue
            existing_rel = (merged.get("relationships") or {}).get(field) or {"data": []}
            unioned = _union_array_ref(existing_rel.get("data"), incoming_rel.get("data"))
            if "relationships" not in merged or merged["relationships"] is None:
                merged["relationships"] = {}
            merged["relationships"][field] = {"data": unioned}

    # Scalar singleton relationships: null=take, equal=noop, differ=conflict-keep-existing
    if incoming and incoming.get("relationships"):
        for field in SCALAR_REL_FIELDS:
            if field not in incoming["relationships"]:
                continue
            incoming_rel = incoming["relationships"][field]
            incoming_id = (incoming_rel or {}).get("data", {}) or {}
            incoming_id = incoming_id.get("id") if isinstance(incoming_id, dict) else None
            existing_rel = (merged.get("relationships") or {}).get(field)
            existing_id = (existing_rel or {}).get("data", {}) or {}
            existing_id = existing_id.get("id") if isinstance(existing_id, dict) else None
            if existing_id is None and incoming_id is not None:
                merged["relationships"][field] = {"data": incoming_rel["data"]}
            elif existing_id is not None and incoming_id is not None and existing_id != incoming_id:
                conflicts.append(
                    {
                        "field": field,
                        "existing": existing_id,
                        "incoming": incoming_id,
                        "kind": "scalar_conflict",
                    }
                )
                # merged retains existing (never silent overwrite)
            # equal or incoming-null -> noop

    # Scalar attributes (non-identity): same null=take / equal=noop / differ=conflict rule
    if incoming and incoming.get("attributes"):
        for field in SCALAR_ATTR_FIELDS:
            if field not in incoming["attributes"]:
                continue
            incoming_val = incoming["attributes"][field]
            existing_val = (merged.get("attributes") or {}).get(field)
            if existing_val is None and incoming_val is not None:
                merged["attributes"][field] = incoming_val
            elif existing_val is not None and incoming_val is not None and existing_val != incoming_val:
                conflicts.append(
                    {
                        "field": field,
                        "existing": existing_val,
                        "incoming": incoming_val,
                        "kind": "scalar_conflict",
                    }
                )

    # Notes: split-dedup-join, marker-preserving
    if incoming and incoming.get("attributes") and "notes" in incoming["attributes"]:
        merged_notes_existing = (merged.get("attributes") or {}).get("notes")
        merged["attributes"]["notes"] = _merge_notes(merged_notes_existing, incoming["attributes"]["notes"])

    return {"merged": merged, "conflicts": conflicts}
