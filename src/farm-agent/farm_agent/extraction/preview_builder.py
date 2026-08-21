"""Farmer-facing preview rendering for the extraction ask-back flow.

Port of src/agents/alerter/src/extraction/preview-builder.js. Honors the ask-back
shape (one-line top question + full draft preview with [?] markers) and the
project memory rules:
  - no em-dashes anywhere in farmer-facing text (sanitize_farmer_text sweep)
  - all numeric values run through fmt_num (round to 1 decimal, strip .0)
  - neutral language (no "operator" as a referent to a human)

PURE: no DB, no I/O, no logging side effects.

Divergence D-1: `build_confirm_prompt` has no Node counterpart. In Node, a
cleanly-extracted draft is never announced to the farmer at all; this port
fixes that. Its body is exactly Node's confirm/preview.js:buildPreviewWithSuffix
(lines 17-23), moved here so extraction/outbound.py does not have to import
across package boundaries. Task 8's confirm/preview.build_preview_with_suffix
becomes a thin delegation to this function.

fmt_num: an equivalent already exists in chamber's message module, but
farm_agent.extraction is a Foray package (FND-05 seam, tests/test_foray_seam.py
+ .lint-imports) and Foray packages may never depend on the mushy-private
chamber package (the reverse direction is allowed). Reusing it here would trip
the seam gate, so it is re-ported locally below from
src/agents/alerter/src/message.js (fmtNum, lines 12-18) -- the same algorithm,
just without the cross-seam dependency.
"""

from __future__ import annotations

import math
import re

from farm_agent.farmos.ref_check import render_ref_check_note

# Top-question phrasing keyed by `{draft_type}.{field_name}`. Missing-field
# templates use the .miss suffix; low-confidence templates use .low. Fall back
# to a generic confirm prompt when no template matches.
TOP_Q_TEMPLATES: dict[str, str] = {
    # Seeding
    "seeding.species.miss": "Which species is this seeding? (SHI, OYS, LIO, ...)",
    "seeding.species.low": "Can you confirm the species for this seeding? I am not fully sure.",
    "seeding.block_name.miss": (
        "What's the block name? Looking for the YYMMDD_SPECIES_SEQ form (like 260512_SHI_4)."
    ),
    "seeding.block_name.low": (
        "Can you confirm the block name? Format: YYMMDD_SPECIES_SEQ (like 260512_SHI_4)."
    ),
    "seeding.qty.miss": "How many blocks were seeded?",
    "seeding.qty.low": "Can you confirm the quantity for this seeding?",
    "seeding.event_timestamp.miss": "What time did you do this seeding?",
    # Activity
    "activity.name.miss": (
        "What activity was this? (sterilize, water, relocate, cold_shock, archive_spent, contam)"
    ),
    "activity.asset_ref.miss": "Which block or batch was this for?",
    # Input
    "input.recipe_lot.miss": "Which recipe lot was used?",
    "input.asset_ref.miss": "Which block or batch did this input go to?",
    # Observation
    "observation.asset_ref.miss": "Which block or batch are you observing?",
    "observation.state_or_notes.miss": (
        "What did you observe? A state (pinning, fruiting, contam, ...) or a short note works."
    ),
    # Harvest
    "harvest.harvest_batch_id.miss": "What is the harvest batch id?",
    "harvest.source_block_refs.miss": "Which source blocks did this harvest come from?",
    "harvest.qty_g.miss": "How many grams were harvested?",
}

REPLY_SUFFIX = "\n\nReply YES to commit, NO to discard, EDIT <text> to amend."

_DATETIME_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.\d+)?(Z|[+\-]\d{2}:?\d{2})$"
)


def fmt_num(n) -> str:
    """Round to 1 decimal and strip a trailing '.0'. Port of message.js:16-19.

    Local re-port (see module docstring) of chamber's fmt_num -- the extraction
    package may not depend on the mushy-private chamber package (FND-05 seam).

    - None / NaN -> '?' so a farmer never sees 'null' or 'undefined'
    - 94.39994 -> '94.4'
    - 90       -> '90'
    - 1.5000000000000013 -> '1.5'
    """
    if n is None:
        return "?"
    try:
        v = float(n)
    except (TypeError, ValueError):
        return "?"
    if math.isnan(v):
        return "?"
    r = round(v, 1)
    if r == int(r):
        return str(int(r))
    return str(r)


def sanitize_farmer_text(s: str) -> str:
    """Strip em-dashes; convert en-dashes to ASCII hyphens. Idempotent."""
    if s is None:
        return ""
    return str(s).replace("—", "").replace("–", "-")


def build_top_question(
    missing_fields: list[str], low_conf_fields: list[str], draft_type: str | None
) -> str:
    """Priority: first missing required field > first low-confidence field."""
    missing = missing_fields if isinstance(missing_fields, list) else []
    low_conf = low_conf_fields if isinstance(low_conf_fields, list) else []

    if len(missing) > 0:
        f = missing[0]
        key = f"{draft_type}.{f}.miss"
        tmpl = TOP_Q_TEMPLATES.get(key)
        if tmpl:
            return sanitize_farmer_text(tmpl)
        return sanitize_farmer_text(f"Can you confirm the {f} for this {draft_type}?")

    if len(low_conf) > 0:
        f = low_conf[0]
        key = f"{draft_type}.{f}.low"
        tmpl = TOP_Q_TEMPLATES.get(key)
        if tmpl:
            return sanitize_farmer_text(tmpl)
        return sanitize_farmer_text(f"Can you double-check the {f} for this {draft_type}?")

    return sanitize_farmer_text(f"Does this {draft_type} look right?")


def render_value(v) -> str:
    if v is None:
        return "[?]"
    if isinstance(v, list):
        return f"[{', '.join(render_scalar(x) for x in v)}]"
    return render_scalar(v)


def render_scalar(v) -> str:
    if v is None:
        return "[?]"
    if isinstance(v, bool):
        # Node's renderScalar has no boolean branch; it falls through to
        # String(v), which is lowercase "true"/"false" -- not Python's str(bool).
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return fmt_num(v)
    if isinstance(v, str):
        # Datetime: trim millisecond fraction. ISO shape YYYY-MM-DDTHH:MM:SS(.SSS)Z.
        m = _DATETIME_RE.match(v)
        if m:
            return f"{m.group(1)}Z"
        return v
    return str(v)


def classify_field(field: str, draft: dict, per_field_confidence: dict, threshold: float) -> str:
    # observation state_or_notes is a synthetic field -- never directly present.
    if field == "state_or_notes":
        has = (draft.get("state") is not None and draft.get("state") != "") or (
            draft.get("notes") is not None and draft.get("notes") != ""
        )
        if not has:
            return "missing"
        return "ok"
    v = draft.get(field)
    is_empty_list = isinstance(v, list) and len(v) == 0
    is_blank_str = isinstance(v, str) and v.strip() == ""
    if v is None or is_empty_list or is_blank_str:
        return "missing"
    c = per_field_confidence.get(field) if per_field_confidence else None
    if isinstance(c, (int, float)) and not isinstance(c, bool) and c < threshold:
        return "low_conf"
    return "ok"


def build_preview(
    *,
    draft: dict | None,
    per_field_confidence: dict | None,
    threshold: float,
    required_fields: list[str],
    asset_ref_checks: dict | None = None,
) -> str:
    """Returns a multi-line farmer-facing string:
      line 1: top question (the single most-blocking ambiguity)
      line 2: blank
      line 3+: draft body, one `field: value` (or `field: [?]`) per line.

    Numbers are formatted via fmt_num. The full output is run through
    sanitize_farmer_text before returning.
    """
    # Phase 47-04: seeding_session placeholder branch. Early-return before the
    # flat-field renderer because the groups-shape provenanced body does not fit
    # the legacy `field: value` rendering.
    #
    # CRITICAL: this branch NEVER reads or renders draft["conflicts"] -- OCR-vs-
    # Whisper conflicts are forensics-only and must never surface to the farmer.
    if draft and draft.get("type") == "seeding_session":
        return render_seeding_session(draft, asset_ref_checks=asset_ref_checks)

    if draft is None:
        draft = {}
    conf = per_field_confidence or {}
    required = required_fields if isinstance(required_fields, list) else []

    # Find missing + low-confidence fields for the top question.
    missing_fields: list[str] = []
    low_conf_fields: list[str] = []
    for f in required:
        cls = classify_field(f, draft, conf, threshold)
        if cls == "missing":
            missing_fields.append(f)
        if cls == "low_conf":
            low_conf_fields.append(f)
    # Also surface low-confidence optional fields the LLM emitted.
    for field, c in conf.items():
        if field in required:
            continue
        if (
            isinstance(c, (int, float))
            and not isinstance(c, bool)
            and c < threshold
            and classify_field(field, draft, conf, threshold) != "missing"
        ):
            low_conf_fields.append(field)

    top_q = build_top_question(
        missing_fields=missing_fields,
        low_conf_fields=low_conf_fields,
        draft_type=draft.get("type"),
    )

    # Build the body. Field order: type first, then required fields in order,
    # then any remaining draft keys (stable insertion order).
    seen = {"type"}
    lines = [f"type: {render_scalar(draft.get('type'))}"]
    for f in required:
        if f == "state_or_notes":
            continue  # synthetic -- skip in body listing
        seen.add(f)
        cls = classify_field(f, draft, conf, threshold)
        if cls in ("missing", "low_conf"):
            lines.append(f"{f}: [?]")
        else:
            lines.append(f"{f}: {render_value(draft.get(f))}")
    for k in draft:
        if k in seen:
            continue
        if k in ("confidence", "per_field_confidence"):
            continue
        cls = classify_field(k, draft, conf, threshold)
        if cls == "low_conf":
            lines.append(f"{k}: [?]")
        else:
            lines.append(f"{k}: {render_value(draft.get(k))}")

    # Observation: if state and notes both missing, surface the synthetic marker.
    if draft.get("type") == "observation":
        has_state = draft.get("state") is not None and draft.get("state") != ""
        has_notes = draft.get("notes") is not None and draft.get("notes") != ""
        if not has_state and not has_notes:
            lines.append("state_or_notes: [?]")

    # MUSHY-86: a proposed asset that does not resolve in farmOS reaches the
    # farmer flagged, so a YES is an informed mint rather than a silent one.
    ref_note = render_ref_check_note(asset_ref_checks)
    if ref_note:
        lines.append("")
        lines.append(ref_note)

    out = f"{top_q}\n\n" + "\n".join(lines)
    return sanitize_farmer_text(out)


def render_seeding_session(draft: dict, *, asset_ref_checks: dict | None = None) -> str:
    """Phase 48-03 production renderer.

    Output shape (em-dash policy applied):

      Inoc session: 2026-05-22
      11 blocks across 5 parents

      KEY  PARENT          SPECIES  QTY  CHILDREN
      1    260304_SHI_5    SHI      1    260522_SHI_1
      ...

      YES to commit | NO to cancel | EDIT to change

    - draft["event_date"] renders as-is (the session table reads like a
      notebook entry, matching the farmer's paper log).
    - 3+ consecutive same-strain child SEQs collapse to `prefix_FIRST..LAST`.
    - 1-2 children, or non-consecutive, render as comma-joined names.
    - groups length > 5 renders first 5 + `... (M more groups)` trailing row.
    - draft["notes"] (free-text) renders as a trailing 'note: {notes}' line
      before the YES/NO/EDIT footer.
    - draft["needs_input"] == "starting_seq" short-circuits to the ask-back
      form (no table).
    - NEVER reads or surfaces draft["conflicts"].
    - sanitize_farmer_text sweep removes em-dashes; output is ASCII.
    """
    if draft and draft.get("needs_input") == "starting_seq":
        return render_starting_seq_ask_back(draft)

    groups = draft.get("groups") if isinstance(draft.get("groups"), list) else []

    # Total child count: prefer child_block_names.value.length when array is
    # present (more authoritative than qty.value when a partial-photo session
    # has populated names); otherwise fall back to qty.value.
    total_children = 0
    for g in groups:
        names = ((g or {}).get("child_block_names") or {}).get("value") if g else None
        if isinstance(names, list):
            total_children += len(names)
        else:
            qv = ((g or {}).get("qty") or {}).get("value") if g else None
            if isinstance(qv, (int, float)) and not isinstance(qv, bool):
                total_children += qv

    event_date = draft.get("event_date")
    header = f"Inoc session: {event_date if event_date is not None else '[?]'}"
    summary = f"{fmt_num(total_children)} blocks across {fmt_num(len(groups))} parents"

    visible = groups[:5]
    overflow_count = len(groups) - 5

    col_header = ["KEY", "PARENT", "SPECIES", "QTY", "CHILDREN"]
    data_rows = [_format_session_row(i + 1, g) for i, g in enumerate(visible)]

    widths = _compute_column_widths([col_header, *data_rows])
    header_line = _pad_row(col_header, widths)
    table_lines = [_pad_row(r, widths) for r in data_rows]

    lines = [header, summary, "", header_line, *table_lines]
    if overflow_count > 0:
        lines.append(f"... ({fmt_num(overflow_count)} more groups)")
    notes = draft.get("notes")
    if notes is not None and str(notes).strip() != "":
        lines.append("")
        lines.append(f"note: {notes}")
    ref_note = render_ref_check_note(asset_ref_checks)
    if ref_note:
        lines.append("")
        lines.append(ref_note)
    lines.append("")
    lines.append("YES to commit | NO to cancel | EDIT to change")

    return sanitize_farmer_text("\n".join(lines))


def render_starting_seq_ask_back(draft: dict) -> str:
    groups = draft.get("groups") if isinstance(draft.get("groups"), list) else []
    total_children = 0
    for g in groups:
        names = ((g or {}).get("child_block_names") or {}).get("value") if g else None
        if isinstance(names, list):
            total_children += len(names)
        else:
            qv = ((g or {}).get("qty") or {}).get("value") if g else None
            if isinstance(qv, (int, float)) and not isinstance(qv, bool):
                total_children += qv
    date = draft.get("event_date")
    date = date if date is not None else "[?]"
    out = "\n".join(
        [
            f"Inoc session: {date}",
            f"{fmt_num(total_children)} blocks across {fmt_num(len(groups))} parents "
            "(awaiting starting block-number)",
            "",
            "Reply with the starting SEQ (e.g. 4).",
        ]
    )
    return sanitize_farmer_text(out)


def _format_session_row(key: int, g: dict | None) -> list[str]:
    parent_val = ((g or {}).get("parent") or {}).get("value") if g else None
    if parent_val == "NO_PARENT":
        parent = "no parent recorded"
    else:
        parent = str(parent_val) if parent_val is not None else "[?]"
    species_val = ((g or {}).get("species") or {}).get("value") if g else None
    species = str(species_val) if species_val is not None else "[?]"
    qty_val = ((g or {}).get("qty") or {}).get("value") if g else None
    qty = fmt_num(qty_val) if qty_val is not None else "[?]"
    names = ((g or {}).get("child_block_names") or {}).get("value") if g else None
    names = names if isinstance(names, list) else []
    return [str(key), parent, species, qty, _render_children(names)]


def _render_children(names: list) -> str:
    if not isinstance(names, list) or len(names) == 0:
        return ""
    if len(names) <= 2:
        return ", ".join(names)
    # Range-collapse: parse trailing _SEQ for each, require all parse, all share
    # the same prefix (everything up to and including the final underscore), and
    # SEQs sort to a consecutive run differing by 1.
    seq_re = re.compile(r"^(.*_)(\d+)$")
    parsed = []
    for n in names:
        m = seq_re.match(n)
        parsed.append({"prefix": m.group(1), "seq": int(m.group(2))} if m else None)
    if all(p is not None for p in parsed):
        prefix = parsed[0]["prefix"]
        if all(p["prefix"] == prefix for p in parsed):
            seqs = sorted(p["seq"] for p in parsed)
            consecutive = all(i == 0 or s == seqs[i - 1] + 1 for i, s in enumerate(seqs))
            if consecutive:
                return f"{prefix}{seqs[0]}..{seqs[-1]}"
    return ", ".join(names)


_COL_MIN_WIDTHS = [4, 15, 8, 4, 0]  # KEY, PARENT, SPECIES, QTY, CHILDREN


def _compute_column_widths(rows: list[list[str]]) -> list[int]:
    widths = list(_COL_MIN_WIDTHS)
    for row in rows:
        for i, cell in enumerate(row):
            length = len(str(cell)) if cell is not None else 0
            if length > widths[i]:
                widths[i] = length
    return widths


def _pad_row(cells: list[str], widths: list[int]) -> str:
    # Last column needs no trailing pad. Earlier columns pad to width + 2
    # (two-space gutter) so the table reads as fixed-column text.
    out = []
    for i, c in enumerate(cells):
        s = str(c) if c is not None else ""
        if i == len(cells) - 1:
            out.append(s)
        else:
            out.append(s.ljust(widths[i] + 2))
    return "".join(out)


def build_confirm_prompt(
    *,
    draft: dict | None,
    per_field_confidence: dict | None,
    required_fields: list[str],
    threshold: float,
    asset_ref_checks: dict | None = None,
) -> str:
    """Farmer-facing confirm prompt for a cleanly-extracted draft (D-1).

    Body of Node's confirm/preview.js:buildPreviewWithSuffix: calls build_preview,
    strips [?] markers (by confirm time every field has cleared threshold or been
    explicitly confirmed), appends REPLY_SUFFIX, and sanitizes.
    """
    body = build_preview(
        draft=draft,
        per_field_confidence=per_field_confidence,
        threshold=threshold,
        required_fields=required_fields,
        asset_ref_checks=asset_ref_checks,
    )
    cleaned = re.sub(r"\s*\[\?\]", "", str(body))
    return sanitize_farmer_text(cleaned + REPLY_SUFFIX)
