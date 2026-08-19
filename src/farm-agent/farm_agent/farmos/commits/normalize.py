"""farm_agent/farmos/commits/normalize.py -- Extractor->commit shape transformer.

Faithful Python port of src/agents/alerter/src/farmos/commits/normalize.js
(Phase 43 Plan 01 / Phase 62-08).

normalize(draft) is a PURE function: returns a NEW draft with draft_json
reshaped to commit-shape per log_type. Does NOT mutate its input.

Idempotent by design: each transform is guarded so that if the commit-shape
marker is already present (qr_codes, timestamp number, activity_subtype, etc.),
the transform is skipped. This satisfies SCHEMA-03 and means that once the
commit-router wires in normalize(), all existing commit-shape test fixtures
continue to pass through unchanged.

Decisions applied here (from 43-CONTEXT.md):
  D-01: pure function, new draft returned, no mutation
  D-03: common transforms (event_timestamp->timestamp, asset_ref->qr_codes)
  D-04: per-log_type switch
  D-05: harvest source_block_refs -> source_qr_codes verbatim (no regex filter)
  D-09: input recipe_lot PREPENDS to notes (not append)
  D-11: seeding batch_name vs parent_batch_name left distinct (no fold)
  D-12: harvest qty_g -> bags single-bag synth only when qty_g present AND bags absent

ASCII-only. No em-dashes.
"""
from __future__ import annotations

from farm_agent.farmos.farm_time import epoch_for_event_timestamp


def normalize(draft: dict) -> dict:
    """Pure function: returns a NEW draft with draft_json reshaped to commit-shape.

    Does NOT mutate the input draft or its draft_json. Returns a new dict with
    a freshly constructed draft_json. Idempotent: calling normalize(normalize(d))
    produces the same result as normalize(d).

    Args:
        draft: Signal draft dict with keys: id, log_type, draft_json.

    Returns:
        New draft dict with draft_json reshaped per log_type.
    """
    dj = dict(draft.get("draft_json") or {})

    # Shallow-copy arrays so downstream consumers cannot mutate the original
    # draft_json by pushing to a returned array field (D-01 non-aliasing).
    for key in ("qr_codes", "source_block_refs", "source_qr_codes", "bags", "input_ingredients"):
        if isinstance(dj.get(key), list):
            dj[key] = list(dj[key])

    # ------------------------------------------------------------------
    # Common transforms (all log_types)
    # ------------------------------------------------------------------

    # event_timestamp (ISO string) -> timestamp (unix seconds).
    # Guard: skip if timestamp already a number (idempotency).
    # MUSHY-94: a date-only event (exact UTC midnight, which is what the
    # extractor emits for a day the farmer named) resolves to LOCAL midnight,
    # so the date that renders is the date the farmer stated. A real clock time
    # is left where it is. See farmos/farm_time.py.
    if not isinstance(dj.get("timestamp"), (int, float)) and isinstance(dj.get("event_timestamp"), str):
        epoch = epoch_for_event_timestamp(dj["event_timestamp"])
        if epoch is not None:
            dj["timestamp"] = epoch

    # asset_ref (string) -> qr_codes (string[]). Filter <UNKNOWN> sentinel.
    # Guard: skip if qr_codes already an array (idempotency).
    if not isinstance(dj.get("qr_codes"), list) and isinstance(dj.get("asset_ref"), str):
        dj["qr_codes"] = [] if dj["asset_ref"] == "<UNKNOWN>" else [dj["asset_ref"]]

    # ------------------------------------------------------------------
    # Per-log_type transforms
    # ------------------------------------------------------------------
    log_type = draft.get("log_type")

    if log_type == "activity":
        # name -> activity_subtype.
        # Guard: skip if activity_subtype already present (idempotency).
        if not dj.get("activity_subtype") and isinstance(dj.get("name"), str):
            dj["activity_subtype"] = dj["name"]

    elif log_type == "harvest":
        # source_block_refs -> source_qr_codes (verbatim rename, D-05: no regex filter).
        # Guard: skip if source_qr_codes already an array (idempotency).
        if not isinstance(dj.get("source_qr_codes"), list) and isinstance(dj.get("source_block_refs"), list):
            dj["source_qr_codes"] = dj["source_block_refs"]

        # harvest_batch_id -> harvest_batch_name.
        # Guard: skip if harvest_batch_name already present (idempotency).
        if not dj.get("harvest_batch_name") and isinstance(dj.get("harvest_batch_id"), str):
            dj["harvest_batch_name"] = dj["harvest_batch_id"]

        # qty_g -> bags: single synthesized unnamed bag (D-12).
        # Guard: only when bags absent AND qty_g present (idempotency).
        if not isinstance(dj.get("bags"), list) and isinstance(dj.get("qty_g"), (int, float)):
            dj["bags"] = [{"weight_grams": dj["qty_g"]}]

    elif log_type == "seeding":
        # species -> species_code (only if species_code absent).
        # Guard: skip if species_code already present (idempotency).
        if not dj.get("species_code") and isinstance(dj.get("species"), str):
            dj["species_code"] = dj["species"]
        # batch_name and parent_batch_name: left as-is per D-11.

    elif log_type == "input":
        # recipe_lot PREPENDED to notes as "recipe_lot: <value>\n" (D-09).
        # Guard: skip if recipe_lot field absent (idempotency).
        # recipe_lot is deleted from out after use so a second normalize() call is a no-op.
        if isinstance(dj.get("recipe_lot"), str):
            prefix = "recipe_lot: " + dj["recipe_lot"]
            dj["notes"] = prefix + ("\n" + dj["notes"] if dj.get("notes") else "")
            del dj["recipe_lot"]

    elif log_type == "observation":
        # state appended to notes as "state: <value>".
        # Guard: skip if state field absent (idempotency).
        # state is deleted from out after use so a second normalize() call is a no-op.
        if isinstance(dj.get("state"), str) and dj["state"] != "":
            if dj.get("notes"):
                dj["notes"] = dj["notes"] + "\nstate: " + dj["state"]
            else:
                dj["notes"] = "state: " + dj["state"]
            del dj["state"]

    # No transforms needed for unknown log_types -- return as-is.
    return {**draft, "draft_json": dj}
