"""farm_agent/farmos/commits/targets.py -- resolve a draft's asset refs (MUSHY-133).

Every lookup in the agent asked /api/asset/fungi and nothing else, so the farm
dog (asset--animal id 1, one of the oldest assets on the farm) could not be
observed: the commit failed as though she did not exist. 34 assets across
animal, plant, structure, group and land were invisible the same way.

Shared by commit_observation and commit_activity rather than copied into each,
because "the same block in two handlers, fixed in one" is how MUSHY-126,
MUSHY-128 and MUSHY-131 each happened.

Deliberately NOT used by seeding, harvest or input. Those resolve a ref to a
substrate BLOCK; letting them match an animal would attach a seeding log to a
dog. Their fungi-only resolve_qr is correct and stays.

ASCII-only. No em-dashes.
"""
from __future__ import annotations

from farm_agent.farmos import assets
from farm_agent.farmos.assets import find_asset_any_bundle
from farm_agent.farmos.qr import resolve_qr
from farm_agent.farmos.ref_check import strain_code_from_ref


def _status_from_lookup_error(error: str) -> int | None:
    """The HTTP status inside a lookup error string ("http_404", "http_network").

    Carried through so the commit watchdog can tell a retryable 500 from a
    terminal 403 instead of calling every one of them a dead server.
    """
    digits = (error or "").rsplit("_", 1)[-1]
    return int(digits) if digits.isdigit() else None


async def resolve_asset_targets(client: dict, refs: list) -> dict:
    """Resolve refs to (asset_id, bundle) pairs across every asset bundle.

    Order matters: resolve_qr first, so a QR sticker still resolves by id_tag
    and the fungi fast path is unchanged, then a name lookup across the other
    bundles.

    A lookup that could not REACH farmOS aborts with an error rather than
    reporting the ref absent. Treating "I could not look" as "not there" is what
    would let a caller mint a duplicate of an asset that already exists.

    Returns:
      {"ok": True,  "targets": [(asset_id, bundle)], "absent": [ref, ...]}
      {"ok": False, "reason": "http_<status|network>", "http_status": int|None}
    """
    targets: list = []
    absent: list = []

    for ref in refs:
        r = await resolve_qr(client, ref)
        if r.get("found") and r.get("asset_id"):
            targets.append((r["asset_id"], "fungi"))
            continue
        if r.get("error"):
            return {
                "ok": False,
                "reason": r["error"],
                "http_status": _status_from_lookup_error(r["error"]),
            }

        alt = await find_asset_any_bundle(client, ref)
        if alt.get("error"):
            return {
                "ok": False,
                "reason": alt["error"],
                "http_status": _status_from_lookup_error(alt["error"]),
            }
        if alt.get("found"):
            targets.append((alt["asset_id"], alt.get("bundle") or "fungi"))
        else:
            absent.append(ref)

    return {"ok": True, "targets": targets, "absent": absent}


async def mint_absent_blocks(client: dict, absent: list, draft_id: str, ctx: dict | None) -> dict:
    """Mint a fungi block for each absent ref that parses as a block name.

    MUSHY-126 (activity) and MUSHY-128 (observation): farmOS confirmed these
    refs are absent from every bundle, and the farmer already approved a
    confirmation that said "New in farmOS, will be created". Same gate as
    commit_seeding: the strain has to come from the ref itself, and
    create_missing_fungi_type stays off unless ctx turns it on, so an
    unrecognised strain code fails loudly rather than minting a junk taxonomy
    term. A ref that is not a block name is skipped, not invented.

    Returns:
      {"ok": True,  "targets": [(asset_id, "fungi"), ...]}
      {"ok": False, "reason": str, "http_status": int|None}
    """
    targets: list = []
    for ref in absent:
        strain = strain_code_from_ref(ref)
        if not strain:
            continue
        block_res = await assets.upsert_fungi_asset(client, {
            "name": ref,
            "fungi_type_name": strain,
            "fungi_xing_name": "block",
            "qr_codes": [ref],
            "draft_id": draft_id,
            "create_missing_fungi_type": bool(ctx and ctx.get("create_missing_fungi_type")),
        })
        if not block_res.get("ok"):
            return {
                "ok": False,
                "reason": block_res.get("reason") or "block_upsert_failed",
                "http_status": block_res.get("http_status"),
            }
        targets.append((block_res["asset_id"], "fungi"))
    return {"ok": True, "targets": targets}
