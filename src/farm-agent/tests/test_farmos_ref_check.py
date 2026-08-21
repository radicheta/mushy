"""
tests/test_farmos_ref_check.py -- Unit tests for farmos/ref_check.py (MUSHY-86).

TDD RED: written before the module exists.

Behaviors covered:
  collect_asset_refs pulls the proposed refs out of every draft shape that has one
  check_asset_refs resolves a ref that exists in farmOS
  ... reports one that does not as new-and-will-be-minted
  ... reports an UNREACHABLE farmOS as unchecked, never as new (the whole point)
  ... surfaces near-miss candidates for a ref that does not resolve
  ... does not spend a lookup hunting near-misses for a ref that resolved
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_cached_assets():
    """assets.py LRU-caches name -> id; a stale hit would mask a real lookup."""
    from farm_agent.farmos import assets

    assets._clear_cache()
    yield
    assets._clear_cache()


def _prov(value):
    return {"value": value, "confidence": 0.9, "sources": ["bag_label_photo"]}


# ---------------------------------------------------------------------------
# collect_asset_refs
# ---------------------------------------------------------------------------


def test_collect_asset_refs_reads_the_single_ref_shapes():
    """observation / activity / input all carry one asset_ref."""
    from farm_agent.farmos.ref_check import collect_asset_refs

    for draft_type in ("observation", "activity", "input"):
        draft = {"type": draft_type, "asset_ref": "260530_KOS_7"}
        assert collect_asset_refs(draft) == ["260530_KOS_7"]


def test_collect_asset_refs_reads_harvest_source_blocks():
    """harvest points at a list of source blocks, all of which are claims."""
    from farm_agent.farmos.ref_check import collect_asset_refs

    draft = {"type": "harvest", "source_block_refs": ["260530_KOS_7", "260530_KOS_8"]}

    assert collect_asset_refs(draft) == ["260530_KOS_7", "260530_KOS_8"]


def test_collect_asset_refs_reads_seeding_session_parents():
    """The 2026-08-18 misread was a seeding_session parent, under a provenance wrapper."""
    from farm_agent.farmos.ref_check import collect_asset_refs

    draft = {
        "type": "seeding_session",
        "groups": [
            {"parent": _prov("260530_KOY_7")},
            {"parent": _prov("260606_DT_3")},
        ],
    }

    assert collect_asset_refs(draft) == ["260530_KOY_7", "260606_DT_3"]


def test_collect_asset_refs_reads_an_optional_seeding_parent():
    """seeding's parent_batch_name is optional -- present is a claim, absent is not."""
    from farm_agent.farmos.ref_check import collect_asset_refs

    assert collect_asset_refs(
        {"type": "seeding", "parent_batch_name": "260530_KOS_7"}
    ) == ["260530_KOS_7"]
    assert collect_asset_refs({"type": "seeding"}) == []


def test_collect_asset_refs_deduplicates_but_keeps_order():
    """One lookup per distinct ref, reported in the order the farmer will read them."""
    from farm_agent.farmos.ref_check import collect_asset_refs

    draft = {
        "type": "seeding_session",
        "groups": [
            {"parent": _prov("260530_KOS_8")},
            {"parent": _prov("260530_KOS_7")},
            {"parent": _prov("260530_KOS_8")},
        ],
    }

    assert collect_asset_refs(draft) == ["260530_KOS_8", "260530_KOS_7"]


# ---------------------------------------------------------------------------
# check_asset_refs
# ---------------------------------------------------------------------------


def _client(routes: dict):
    """Fake farmOS client: maps request path substrings to canned responses."""

    async def get(path: str):
        for needle, response in routes.items():
            if needle in path:
                return response
        return {"ok": True, "body": {"data": []}}

    return {"get": get}


def _found(name: str):
    return {"ok": True, "body": {"data": [{"id": "uuid-" + name, "attributes": {"name": name}}]}}


@pytest.mark.asyncio
async def test_a_ref_that_resolves_is_reported_as_existing():
    from farm_agent.farmos.ref_check import check_asset_refs

    client = _client({"260530_KOS_7": _found("260530_KOS_7")})

    result = await check_asset_refs(client, ["260530_KOS_7"])

    assert result["260530_KOS_7"]["status"] == "exists"


@pytest.mark.asyncio
async def test_a_ref_that_does_not_resolve_is_reported_as_new():
    from farm_agent.farmos.ref_check import check_asset_refs

    result = await check_asset_refs(_client({}), ["260412_WIN_11"])

    assert result["260412_WIN_11"]["status"] == "new"


@pytest.mark.asyncio
async def test_an_unreachable_farmos_is_unchecked_not_new():
    """A farmOS outage must never render as 'this asset is new and will be minted'."""
    from farm_agent.farmos.ref_check import check_asset_refs

    client = _client({"filter[name][value]": {"ok": False, "status": 500}})

    result = await check_asset_refs(client, ["260530_KOS_7"])

    assert result["260530_KOS_7"]["status"] == "unchecked"


@pytest.mark.asyncio
async def test_a_new_ref_surfaces_its_near_misses():
    """KOY did not resolve; KOS at the same date did. Show the farmer the candidate."""
    from farm_agent.farmos.ref_check import check_asset_refs

    async def get(path: str):
        if "operator" in path:  # the prefix sweep
            return {
                "ok": True,
                "body": {"data": [
                    {"id": "u1", "attributes": {"name": "260530_KOS_7"}},
                    {"id": "u2", "attributes": {"name": "260530_MAI_2"}},
                ]},
            }
        return {"ok": True, "body": {"data": []}}  # exact lookup misses

    result = await check_asset_refs({"get": get}, ["260530_KOY_7"])

    assert result["260530_KOY_7"]["status"] == "new"
    assert result["260530_KOY_7"]["near_misses"] == ["260530_KOS_7"]


@pytest.mark.asyncio
async def test_a_resolved_ref_does_not_trigger_a_near_miss_sweep():
    """No point paying for a candidate sweep when the ref is already right."""
    from farm_agent.farmos.ref_check import check_asset_refs

    paths = []

    async def get(path: str):
        paths.append(path)
        return _found("260530_KOS_7")

    await check_asset_refs({"get": get}, ["260530_KOS_7"])

    assert not any("operator" in p for p in paths)


# ---------------------------------------------------------------------------
# render_ref_check_note -- what the farmer actually reads
# ---------------------------------------------------------------------------


def test_all_refs_resolving_adds_nothing_to_the_preview():
    """A check that found nothing wrong must not cost the farmer a line."""
    from farm_agent.farmos.ref_check import render_ref_check_note

    assert render_ref_check_note({"260530_KOS_7": {"status": "exists", "near_misses": []}}) == ""


def test_a_new_ref_is_announced_as_will_be_created():
    """Minting is correct behaviour, but the farmer should know it is happening."""
    from farm_agent.farmos.ref_check import render_ref_check_note

    note = render_ref_check_note({"260412_WIN_11": {"status": "new", "near_misses": []}})

    assert note == "New in farmOS, will be created: 260412_WIN_11"


def test_a_near_miss_is_offered_as_a_question():
    """The whole point: KOY reaches the farmer next to the KOS that does exist."""
    from farm_agent.farmos.ref_check import render_ref_check_note

    note = render_ref_check_note(
        {"260530_KOY_7": {"status": "new", "near_misses": ["260530_KOS_7"]}}
    )

    assert note == "New in farmOS, will be created: 260530_KOY_7 (did you mean 260530_KOS_7?)"


def test_an_unchecked_ref_is_never_announced_as_will_be_created():
    """A farmOS outage says 'could not check', not a confident lie about minting."""
    from farm_agent.farmos.ref_check import render_ref_check_note

    note = render_ref_check_note({"260530_KOS_7": {"status": "unchecked", "near_misses": []}})

    assert note == "Could not check farmOS: 260530_KOS_7"
    assert "will be created" not in note
