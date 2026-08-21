"""
farmos/ref_check.py -- do the proposed asset refs actually exist? (MUSHY-86)

The extractor proposes asset names from handwritten labels and audio, and
nothing between extraction and the confirm prompt consults farmOS. So a misread
character reaches the farmer as a confident-looking row, and a YES mints a
near-duplicate asset.

Observed live 2026-08-18: a bag label was read as `260530_KOY_7` and the model
defended it ("photo clearly shows KOY"). The asset is `260530_KOS_7`. Both KOY
and KOS are valid strains, so the strain resolver had nothing to say -- the
failure is at the asset-instance level, which nothing validated.

Three outcomes, and the third is the point:

  exists     -- resolved in farmOS, show it plainly
  new        -- did not resolve; it will be minted on commit, which is correct
                per "the farmer is reality's source of truth", but say so
  unchecked  -- farmOS could not be reached

`unchecked` must never collapse into `new`. Telling the farmer "this will be
created" during a farmOS outage is a confident lie, and BONE-10 is three days of
evidence that this farm's components fail while still looking alive.
"""

from __future__ import annotations

import logging
import re
import urllib.parse

from farm_agent.farmos.assets import find_asset_by_name

logger = logging.getLogger(__name__)

# Block names look like 260530_KOS_7 -- YYMMDD, strain code, sequence.
_BLOCK_NAME_RE = re.compile(r"^(\d{6})_([A-Z0-9]{2,5})_(\d+)$")

_MAX_NEAR_MISSES = 3
_MAX_EDIT_DISTANCE = 2


def _ref_values(draft: dict) -> list:
    """Every asset ref this draft shape can carry, in reading order."""
    draft_type = draft.get("type")

    if draft_type == "seeding_session":
        return [
            (group or {}).get("parent", {}).get("value")
            for group in draft.get("groups") or []
        ]
    if draft_type == "harvest":
        return list(draft.get("source_block_refs") or [])
    if draft_type == "seeding":
        return [draft.get("parent_batch_name")]
    return [draft.get("asset_ref")]


def collect_asset_refs(draft: dict | None) -> list[str]:
    """Distinct, non-empty asset refs proposed by a draft, in reading order."""
    out: list[str] = []
    for value in _ref_values(draft or {}):
        if isinstance(value, str) and value and value not in out:
            out.append(value)
    return out


def _edit_distance(a: str, b: str) -> int:
    """Levenshtein, iterative two-row. Short block names only."""
    if a == b:
        return 0
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            current.append(
                min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb))
            )
        previous = current
    return previous[-1]


def rank_near_misses(ref: str, candidates: list[str]) -> list[str]:
    """Candidate names close enough to `ref` to be worth showing, closest first."""
    scored = [
        (_edit_distance(ref, c), c)
        for c in candidates
        if c != ref and _edit_distance(ref, c) <= _MAX_EDIT_DISTANCE
    ]
    scored.sort(key=lambda pair: (pair[0], pair[1]))
    return [name for _, name in scored[:_MAX_NEAR_MISSES]]


async def _same_date_candidates(client: dict, ref: str) -> list[str]:
    """Names sharing this ref's date prefix -- the pool a misread strain hides in."""
    match = _BLOCK_NAME_RE.match(ref)
    if not match:
        return []
    prefix = urllib.parse.quote(match.group(1) + "_", safe="")
    r = await client["get"](
        f"/api/asset/fungi?filter[name][operator]=CONTAINS&filter[name][value]={prefix}"
    )
    if not r.get("ok"):
        return []
    return [
        (item.get("attributes") or {}).get("name")
        for item in (r.get("body") or {}).get("data") or []
        if (item.get("attributes") or {}).get("name")
    ]


def render_ref_check_note(checks: dict | None) -> str:
    """The farmer-facing summary of a ref check. Empty when nothing needs saying.

    Only the two outcomes that change what the farmer should do are rendered.
    A resolved ref costs no line: this has to inform a confirmation, not add a
    bookkeeping step to it.
    """
    new_parts: list[str] = []
    unchecked: list[str] = []
    for ref, result in (checks or {}).items():
        status = (result or {}).get("status")
        if status == "new":
            near = (result or {}).get("near_misses") or []
            suffix = f" (did you mean {', '.join(near)}?)" if near else ""
            new_parts.append(f"{ref}{suffix}")
        elif status == "unchecked":
            unchecked.append(ref)

    lines = []
    if new_parts:
        lines.append("New in farmOS, will be created: " + ", ".join(new_parts))
    if unchecked:
        lines.append("Could not check farmOS: " + ", ".join(unchecked))
    return "\n".join(lines)


async def check_asset_refs(client: dict, refs: list[str]) -> dict:
    """Resolve each ref against farmOS.

    Returns {ref: {"status": "exists"|"new"|"unchecked", "near_misses": [...]}}.
    Never raises: an unexpected failure degrades to `unchecked`, which the
    preview renders as "could not check", never as "will be created".
    """
    out: dict = {}
    for ref in refs:
        try:
            found = await find_asset_by_name(client, ref)
        except Exception as e:  # noqa: BLE001 -- a check failure is not a miss
            logger.warning("[ref_check] lookup threw for %s: %s", ref, e)
            out[ref] = {"status": "unchecked", "near_misses": []}
            continue

        if found.get("found"):
            out[ref] = {"status": "exists", "near_misses": []}
            continue
        if found.get("error"):
            out[ref] = {"status": "unchecked", "near_misses": []}
            continue

        try:
            candidates = await _same_date_candidates(client, ref)
        except Exception as e:  # noqa: BLE001 -- near-misses are a nicety, not the verdict
            logger.warning("[ref_check] candidate sweep threw for %s: %s", ref, e)
            candidates = []
        out[ref] = {"status": "new", "near_misses": rank_near_misses(ref, candidates)}
    return out
