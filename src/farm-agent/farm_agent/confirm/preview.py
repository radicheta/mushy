"""Confirm-loop farmer-facing string renderers.

Port of src/agents/alerter/src/confirm/preview.js. Style locks: no em-dashes
(sanitize_farmer_text sweep), all numbers via fmt_num, named address.

`build_preview_with_suffix` is a thin delegation to
`farm_agent.extraction.preview_builder.build_confirm_prompt` (Task 3), which
already owns the [?]-stripping, REPLY_SUFFIX append, and sanitize. Do not
duplicate that body here.
"""

from __future__ import annotations

import math

from farm_agent.extraction.preview_builder import (
    build_confirm_prompt,
    sanitize_farmer_text,
)


def _fmt_num(n) -> str:
    """Round to 1 decimal and strip a trailing '.0'. Same algorithm as
    extraction.preview_builder.fmt_num, used here for max_edit_turns / minutes.
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


def _truncate_id(draft_id) -> str:
    if not isinstance(draft_id, str):
        return ""
    return draft_id[:10]


def build_preview_with_suffix(
    *, draft: dict | None, per_field_confidence: dict | None, required_fields: list[str],
    threshold: float,
) -> str:
    """Thin delegation to extraction.preview_builder.build_confirm_prompt."""
    return build_confirm_prompt(
        draft=draft,
        per_field_confidence=per_field_confidence,
        required_fields=required_fields,
        threshold=threshold,
    )


def build_confirm_ack(draft_id: str) -> str:
    return sanitize_farmer_text(f"Locked in. Writing now. (draft {_truncate_id(draft_id)})")


def build_idempotent_ack() -> str:
    return sanitize_farmer_text("Already locked in. Check the previous message.")


def build_discard_ack() -> str:
    return sanitize_farmer_text("Discarded. Nothing written.")


def build_edit_cap_msg(max_edit_turns) -> str:
    return sanitize_farmer_text(
        f"I cannot get this right after {_fmt_num(max_edit_turns)} tries. "
        "Try splitting the message into smaller updates, or send NO to discard."
    )


def build_nudge(*, minutes_remaining=None, preview_summary=None) -> str:
    try:
        mins_raw = 0 if minutes_remaining is None else float(minutes_remaining)
        if math.isnan(mins_raw):
            mins_raw = 0
    except (TypeError, ValueError):
        mins_raw = 0
    mins_raw = max(0, round(mins_raw))
    body = (
        f"Still want to lock in this draft? Reply YES / NO / EDIT or it auto-expires "
        f"in {_fmt_num(mins_raw)} min."
    )
    if isinstance(preview_summary, str) and preview_summary.strip() != "":
        body += f"\n{preview_summary.strip()}"
    return sanitize_farmer_text(body)


def build_expired_note() -> str:
    return sanitize_farmer_text(
        "Draft expired. Nothing was written. Send a fresh message if you still want to log this."
    )


_STATUS_WORD = {
    "committed": "saved",
    "discarded": "discarded",
    "expired": "expired",
    "needs_review": "pending review",
    "confirmed": "saved",
}


def build_quote_closed(draft_row: dict | None) -> str:
    """Polite ack for a quote-reply targeting an already-terminal draft.

    Port of receive-loop.js:269-270 / outbound-confirm.js renderQuoteClosed
    (simplified: no per-log-type disambiguator, which lives in the unported
    farmos/commit-outcome-preview.js and is out of scope for this task).
    """
    row = draft_row or {}
    status_word = _STATUS_WORD.get(row.get("status"), "closed")
    return sanitize_farmer_text(f"That entry is already {status_word}.")


def build_numbered_ask_back(active_drafts: list[dict]) -> str:
    """Disambiguation prompt when >1 active draft exists and no quote pinned one.

    Port of receive-loop.js:299-310 / outbound-confirm.js renderNumberedAskBack
    (simplified: labels use the farmer_facing_preview first line rather than the
    unported log-type disambiguator). Capped at 5 entries.
    """
    rows = (active_drafts or [])[:5]
    lines = []
    for i, d in enumerate(rows, start=1):
        preview = ((d or {}).get("farmer_facing_preview") or "").strip()
        label = preview.splitlines()[0][:60] if preview else f"draft {_truncate_id((d or {}).get('id'))}"
        lines.append(f"{i}. {label}")
    body = "\n".join(
        ["Which one are you replying about?", *lines, "Reply with the number, or quote the original message."]
    )
    return sanitize_farmer_text(body)
