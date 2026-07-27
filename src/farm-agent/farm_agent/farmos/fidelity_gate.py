"""
farmos/fidelity_gate.py -- CSV fidelity gate (FWR-03 / D-06 / D-07 / T-62-09).

Port of v1.11 Node buildCsvBudget / fidelity_cross_check_unverified logic.

Provides:
  load_fidelity_csv(path)          -- load CSV rows; returns [] on missing/bad file (D-07)
  check_fidelity(draft, csv_rows)  -- pure gate; returns pass/hold/pass-through result
  render_fidelity_ask_back(...)    -- ASCII farmer ask-back (no em-dash)

D-06: disagreement HOLDS draft as "fidelity_cross_check_unverified" AND emits a farmer
      ask-back (never a silent hold).
D-07: CSV is NON-authoritative. A block absent from the CSV is a no-op pass-through
      (never a hard-reject). Disagreement FLAGS/holds for human review.
T-62-09: POY is never silently resolved to KOY; the gate surfaces disagreements.
T-62-10: Over-trusting the CSV (hard-reject) is mitigated by the pass-through rule.
T-62-11: Missing/malformed CSV returns [] so absent rows pass through.

ASCII-only output. No em-dashes (use --). No emoji.
"""

from __future__ import annotations

import csv
import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CSV loader (D-07: non-fatal on missing/bad file)
# ---------------------------------------------------------------------------


def load_fidelity_csv(path: str) -> list[dict]:
    """Load CSV rows from path into a list of dicts (keyed by header names).

    Expected columns: block_name, strain_code.

    Returns [] on:
    - Missing file
    - Empty file
    - CSV parse failure

    Non-fatal (CSV is non-authoritative, D-07 / T-62-11). Called at boot by
    the commit watchdog; pure function relative to file I/O.
    """
    if not path:
        return []
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            return [dict(row) for row in reader]
    except FileNotFoundError:
        logger.debug("[fidelity_gate] CSV not found at %s -- absent rows pass through", path)
        return []
    except Exception as e:  # noqa: BLE001
        logger.warning("[fidelity_gate] CSV load failed (%s): %s -- absent rows pass through", path, e)
        return []


# ---------------------------------------------------------------------------
# Ask-back renderer (ASCII-only, no em-dash)
# ---------------------------------------------------------------------------


def render_fidelity_ask_back(block_name: str, draft_strain: str, csv_strain: str) -> str:
    """Render the farmer-facing fidelity ask-back message.

    ASCII-only, no em-dash (use --), no emoji.
    Names the block and both strains; asks which is correct.

    Mirror tone of confirm/strain_ask_back.py render_strain_ask_back.
    """
    return "\n".join([
        f"Block '{block_name}': draft says strain {draft_strain}, CSV says {csv_strain}.",
        "Which is correct? Reply with the correct strain code, or YES to keep the draft value.",
    ])


# ---------------------------------------------------------------------------
# Gate: pure function (no I/O)
# ---------------------------------------------------------------------------


def _extract_draft_strain(draft: dict) -> str | None:
    """Extract the strain/species code from a draft dict.

    Checks draft_json.species_code first, then species, strain, fungi_type.
    Returns None if no strain code found.
    """
    dj = draft.get("draft_json") or {}
    for key in ("species_code", "species", "strain", "fungi_type"):
        v = dj.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip().upper()
    return None


def check_fidelity(draft: dict, csv_rows: list[dict]) -> dict:
    """Compare draft block_name strain against the CSV source.

    Pure function (no I/O). csv_rows comes from load_fidelity_csv().

    Returns one of:

    {"pass": True}
        Agreement: draft strain matches CSV strain for this block.

    {"pass": False, "reason": "block_not_in_csv"}
        Block not found in CSV -- no-op pass-through (D-07: CSV is non-authoritative;
        absence from CSV is NOT a hard-reject).

    {"pass": False,
     "reason": "strain_mismatch",
     "draft_strain": str,
     "csv_strain": str,
     "hold_status": "fidelity_cross_check_unverified",
     "ask_back_msg": str}
        Disagreement -- hold draft as fidelity_cross_check_unverified and emit
        farmer ask-back (D-06; never a silent hold).
    """
    block_name = (draft.get("block_name") or "").strip()

    # Build a lookup table from the CSV rows for this call.
    # block_name is the key; strain_code is the expected value.
    csv_index: dict[str, str] = {}
    for row in (csv_rows or []):
        name = (row.get("block_name") or "").strip()
        code = (row.get("strain_code") or "").strip().upper()
        if name:
            csv_index[name] = code

    # Block absent from CSV -> pass-through (D-07)
    if not block_name or block_name not in csv_index:
        return {"pass": False, "reason": "block_not_in_csv"}

    csv_strain = csv_index[block_name]
    draft_strain = _extract_draft_strain(draft)

    # No extractable draft strain -> treat as absent (safe pass-through; nothing to compare)
    if draft_strain is None:
        return {"pass": False, "reason": "block_not_in_csv"}

    # Agreement
    if draft_strain == csv_strain:
        return {"pass": True}

    # Disagreement -> hold + ask-back (D-06 / T-62-09)
    ask_back_msg = render_fidelity_ask_back(block_name, draft_strain, csv_strain)
    return {
        "pass": False,
        "reason": "strain_mismatch",
        "draft_strain": draft_strain,
        "csv_strain": csv_strain,
        "hold_status": "fidelity_cross_check_unverified",
        "ask_back_msg": ask_back_msg,
    }
