"""
capture/replay.py -- re-drive stored captures through the real pipeline (MUSHY-87).

When extraction improves there is no supported way to redo a capture that is
already on disk: the only entry point is the live signal-cli receive loop, so a
mis-extracted session could only be redone by asking the farmer to send it
again. That is the bookkeeping tax the project exists to remove.

Two decisions taken with Don Santiago on 2026-08-19 shape this module:

  * **Replay collision** -- draft ids are a deterministic hash of the capture
    ids and `insert_draft` is a plain INSERT, so a replayed capture always
    collides with its own live draft. `replay_scoped_db` hashes in a replay
    marker instead of deleting anything; `source_capture_ids` still names the
    originals, so the superseded row and the replay both stay readable.
  * **Replay sends** -- a replay is usually fixing your own extraction, so an
    unexpected DM about a session the farmer already logged is noise. The CLI
    dry-runs by default and only dispatches behind an explicit flag.

The date anchor is the capture's own `captured_at`, never the replay clock
(MUSHY-83): `extraction.pipeline._capture_date_iso` already prefers
`captured_at_ms`, so building the ctx from the stored row is enough.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

_SELECT_BY_IDS_SQL = """
SELECT id, captured_at, sender, raw_text, transcript, attachment_paths,
       farmos_person, reply_target_kind, group_id
  FROM signal_capture
 WHERE id = ANY(%s)
 ORDER BY captured_at ASC
"""


def _captured_at_ms(value: Any) -> int:
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    return int(value)


def build_capture_ctx(row: dict) -> dict:
    """Rebuild the ctx `extraction_pipeline.enqueue` expects from a stored row.

    Mirrors the live ctx assembled in capture/pipeline.py, with `captured_at_ms`
    taken from the row so extraction anchors to when the farmer sent it.
    """
    transcript = row.get("transcript")
    return {
        "capture_id": row["id"],
        "sender": row["sender"],
        "farmos_person": row.get("farmos_person"),
        "text": row.get("raw_text") or None,
        "transcripts": [transcript] if transcript else [],
        "attachment_paths": row.get("attachment_paths") or [],
        "reply_target_kind": row.get("reply_target_kind"),
        "group_id": row.get("group_id"),
        "captured_at_ms": _captured_at_ms(row["captured_at"]),
        "corpus_context": None,
    }


class _ReplayScopedDb:
    """extraction_db with replay-scoped draft ids; every other attribute is the real one."""

    def __init__(self, base: Any, marker: str) -> None:
        self._base = base
        self._marker = marker
        self._minted: set[str] = set()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._base, name)

    def compute_draft_id(self, capture_ids: list[str], draft_index: int | None = None) -> str:
        keyed = "|".join(sorted(capture_ids)) + f"#replay:{self._marker}"
        if draft_index not in (None, 0):
            keyed = f"{keyed}#{draft_index}"
        draft_id = hashlib.sha256(keyed.encode()).hexdigest()
        self._minted.add(draft_id)
        return draft_id

    async def get_in_flight_for_sender(self, pool: Any, sender_e164: str) -> dict | None:
        """Hide drafts this replay did not create.

        A capture replayed inside the idle gap would otherwise land on the very
        draft it is superseding -- the pipeline would append to it, which is the
        destructive outcome the replay-scoped id exists to avoid. Drafts minted
        by this run stay visible, so a multi-capture session still fuses.
        """
        row = await self._base.get_in_flight_for_sender(pool, sender_e164)
        if row and row.get("id") in self._minted:
            return row
        return None


def replay_scoped_db(base: Any, marker: str) -> _ReplayScopedDb:
    """Wrap the extraction_db module so replayed drafts get their own ids."""
    return _ReplayScopedDb(base, marker)


async def fetch_captures(pool: Any, capture_ids: list[str]) -> list[dict]:
    """Read the named signal_capture rows, oldest first."""
    async with pool.connection() as conn:
        cursor = await conn.execute(_SELECT_BY_IDS_SQL, (list(capture_ids),))
        columns = [d.name for d in cursor.description]
        return [dict(zip(columns, r)) for r in await cursor.fetchall()]


async def replay_captures(
    *,
    rows: list[dict],
    enqueue: Callable[[dict], Awaitable[dict]],
    apply: bool,
    log: logging.Logger | None = None,
) -> list[dict]:
    """Re-drive `rows` through `enqueue` in captured_at order.

    Without `apply` nothing is enqueued: the returned list is the plan.
    """
    _log = log or logger
    ordered = sorted(rows, key=lambda r: _captured_at_ms(r["captured_at"]))

    results = []
    for row in ordered:
        ctx = build_capture_ctx(row)
        if not apply:
            results.append({"capture_id": ctx["capture_id"], "applied": False, "result": None})
            continue
        _log.info("[replay] enqueue capture_id=%s", ctx["capture_id"])
        results.append({
            "capture_id": ctx["capture_id"],
            "applied": True,
            "result": await enqueue(ctx),
        })
    return results
