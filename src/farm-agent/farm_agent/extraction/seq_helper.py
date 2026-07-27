"""farm_agent/extraction/seq_helper.py -- SEQ helpers for B5 block-name minting.

Port of src/agents/alerter/src/extraction/seq-helper.js.

Two pure helpers (yyyymmdd_to_yymmdd, mint_child_block_names) and DB helpers
(lookup_last_seq_for_date) consumed by the extraction pipeline.

Design notes:
  - lookup_last_seq_for_date tolerates legacy seeding.block_name AND
    seeding_session.groups[].child_block_names, returning the MAX SEQ
    across all species (per-session counter spans species within a date).
  - Parse failures on individual rows are swallowed (skip-on-error).
  - NEEDS_SEQ sentinel is explicitly excluded from SEQ parsing.
  - mint_child_block_names uses re.fullmatch (NOT re.match) so a trailing
    _EXTRA segment is rejected (T-60-02-01).
"""

from __future__ import annotations

import logging
import re

from farm_agent.extraction.schemas.seeding import BLOCK_NAME_RE

logger = logging.getLogger(__name__)

EVENT_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def yyyymmdd_to_yymmdd(event_date: str) -> str:
    """Convert "YYYY-MM-DD" to "YYMMDD" string.

    Raises:
        ValueError: if event_date does not match YYYY-MM-DD
    """
    m = EVENT_DATE_RE.match(event_date)
    if not m:
        raise ValueError(f"yyyymmdd_to_yymmdd: bad event_date '{event_date}' (want YYYY-MM-DD)")
    return f"{m.group(1)[2:]}{m.group(2)}{m.group(3)}"


def mint_child_block_names(
    event_date_yymmdd: str,
    species_code: str,
    start_seq: int,
    qty: int,
) -> list[str]:
    """Build qty consecutive block names: {YYMMDD}_{SPECIES}_{seq}.

    Each name is validated with re.fullmatch(BLOCK_NAME_RE); raises ValueError
    on any mismatch so lowercase species, extra segments, or malformed dates
    are caught immediately (T-60-02-01).

    Args:
        event_date_yymmdd: six-digit date string e.g. "260522"
        species_code: uppercase species code e.g. "SHI"
        start_seq: first sequence number (inclusive)
        qty: number of consecutive names to mint

    Returns:
        list of validated block name strings

    Raises:
        ValueError: if any minted name fails BLOCK_NAME_RE fullmatch
    """
    out = []
    for i in range(qty):
        name = f"{event_date_yymmdd}_{species_code}_{start_seq + i}"
        if re.fullmatch(BLOCK_NAME_RE, name) is None:
            raise ValueError(f"mint_invalid_block_name: {name}")
        out.append(name)
    return out


def seq_of(block_name: str | None) -> int | None:
    """Extract trailing SEQ integer from a canonical B5 block name.

    Returns None for the NEEDS_SEQ sentinel, non-matching strings, or None input.
    """
    if not isinstance(block_name, str):
        return None
    if block_name == "NEEDS_SEQ":
        return None
    if re.fullmatch(BLOCK_NAME_RE, block_name) is None:
        return None
    idx = block_name.rfind("_")
    if idx < 0:
        return None
    try:
        n = int(block_name[idx + 1:])
    except (ValueError, TypeError):
        return None
    return n


def extract_seqs_from_row(draft_json: dict | None) -> list[int]:
    """Extract all SEQ integers from a draft_json dict.

    Handles:
      - type == "seeding": reads block_name at top level
      - type == "seeding_session": walks groups[].child_block_names (Provenanced
        shape {"value": [...]} and bare list)

    Never raises; returns a partial list on any per-row exception.
    NEEDS_SEQ sentinel is excluded (seq_of returns None for it).
    """
    if not draft_json or not isinstance(draft_json, dict):
        return []
    seqs: list[int] = []
    try:
        dtype = draft_json.get("type")
        if dtype == "seeding":
            s = seq_of(draft_json.get("block_name"))
            if s is not None:
                seqs.append(s)
        elif dtype == "seeding_session":
            groups = draft_json.get("groups")
            if not isinstance(groups, list):
                groups = []
            for g in groups:
                try:
                    if not g or not isinstance(g, dict):
                        continue
                    cbn = g.get("child_block_names")
                    if cbn is None:
                        continue
                    # Support Provenanced shape {"value": [...]} and bare list.
                    # Extension vs Node: Node only handles {"value": [...]}; bare list
                    # is defensive-only for Python-native callers that skip provenance
                    # wrapping. The model schema requires the provenanced shape.
                    if isinstance(cbn, dict):
                        values = cbn.get("value", [])
                    elif isinstance(cbn, list):
                        values = cbn
                    else:
                        continue
                    for v in values or []:
                        s = seq_of(v)
                        if s is not None:
                            seqs.append(s)
                except Exception:  # noqa: BLE001
                    # skip-on-error: one malformed group must not crash the lookup
                    continue
    except Exception:  # noqa: BLE001
        return seqs
    return seqs


async def lookup_last_seq_for_date(
    pool,
    event_date: str,
    log=None,
) -> dict:
    """Query signal_draft for the maximum SEQ already minted on a given date.

    Walks both legacy seeding.block_name and seeding_session.groups[].
    child_block_names to find the MAX SEQ across all species (per-session
    counter spans species within a date).

    Args:
        pool: psycopg3 async connection pool
        event_date: "YYYY-MM-DD" format
        log: optional logger; defaults to module logger

    Returns:
        {ok: True, last_seq: int | None, source: str}  on success
        {ok: False, reason: str}                        on any error (fail-open)

    Note on key naming: Node's lookupLastSeqForDate returns {"lastSeq": ...}
    (camelCase). This Python port uses snake_case ("last_seq") per Python
    convention. The Phase-61 ask-back consumer MUST access result["last_seq"],
    NOT result["lastSeq"] (which would return None silently).
    """
    _log = log or logger
    if not isinstance(event_date, str) or not EVENT_DATE_RE.match(event_date):
        return {"ok": False, "reason": "bad_event_date"}
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT draft_json FROM signal_draft
                    WHERE status IN ('committed', 'awaiting_farmer', 'confirmed', 'pending')
                      AND draft_json->>'event_date' = %s
                    """,
                    (event_date,),
                )
                rows = await cur.fetchall()
        max_seq: int | None = None
        for row in rows:
            draft_json = row[0]
            for s in extract_seqs_from_row(draft_json):
                if max_seq is None or s > max_seq:
                    max_seq = s
        return {
            "ok": True,
            "last_seq": max_seq,
            "source": "none" if max_seq is None else "signal_draft",
        }
    except Exception as e:  # noqa: BLE001
        _log.warning("[seq-helper] lookup failed: %s", e)
        return {"ok": False, "reason": str(e)}
