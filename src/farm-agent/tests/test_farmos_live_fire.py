"""
tests/test_farmos_live_fire.py -- Dev farmOS :18080 live-fire test.

OPERATOR-RUN ONLY. Skipped by default.
Requires: FWR_LIVE_FIRE=1 + FARMOS_URL + FARMOS_USERNAME + FARMOS_PASSWORD.
Never runs in CI.

Purpose:
  Run the Python commit path against dev farmOS :18080 and assert:

  SC2: double-run -> 0 duplicate asset--fungi created on the second run
       (upsert-by-name stable identity; name-filter count == 1 after both runs)
  SC3: uploaded image appears on the asset's image field in dev farmOS
  SC4: a strain-mismatch draft is held as fidelity_cross_check_unverified
       and creates 0 assets in dev farmOS

T-62-34 guard: FARMOS_URL must contain ':18080' before any write.
T-62-35: paper-trail stores uuids only, never creds.
T-62-36: unique timestamped block_name per run prevents dirty-state masking.

Usage:
  export FARMOS_URL=http://<dev-host>:18080
  export FARMOS_USERNAME=<dev-mushy-bot-username>
  export FARMOS_PASSWORD=<dev-mushy-bot-password>
  export FWR_LIVE_FIRE=1
  cd src/farm-agent && uv run pytest tests/test_farmos_live_fire.py -q -m live_fire

Reference:
  .planning/phases/62-farmos-write-path/62-12-PLAN.md
"""

from __future__ import annotations

import datetime
import json
import os
import urllib.parse
from pathlib import Path

import httpx
import pytest

from farm_agent.farmos.assets import _clear_cache
from farm_agent.farmos.client import create_farmos_client
from farm_agent.farmos.commits.commit_router import commit
from farm_agent.farmos.fidelity_gate import check_fidelity
from farm_agent.farmos.files import upload_field_attachment

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "farmos"
_SEEDING_DRAFT_PATH = _FIXTURE_DIR / "live_fire_seeding_draft.json"

# Reuse the committed paper-log.jpg from the extraction fixture set.
_TEST_IMAGE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "extraction"
    / "seeding-session-may22"
    / "paper-log.jpg"
)

# ---------------------------------------------------------------------------
# Live-fire skip guard (mirrors test_gate_live_fire.py opt-in pattern)
# ---------------------------------------------------------------------------


@pytest.mark.live_fire
@pytest.mark.skipif(
    not os.environ.get("FWR_LIVE_FIRE")
    or not os.environ.get("FARMOS_URL")
    or not os.environ.get("FARMOS_USERNAME")
    or not os.environ.get("FARMOS_PASSWORD"),
    reason=(
        "live-fire: requires FWR_LIVE_FIRE=1 + FARMOS_URL + "
        "FARMOS_USERNAME + FARMOS_PASSWORD"
    ),
)
@pytest.mark.asyncio
async def test_farmos_live_fire_dedup_image_fidelity() -> None:
    """Live-fire SC2 + SC3 + SC4 against dev farmOS :18080.

    SC2: second commit run creates 0 duplicate asset--fungi.
    SC3: uploaded image appears on asset image field.
    SC4: strain-mismatch draft held as fidelity_cross_check_unverified; 0 assets created.
    """
    farmos_url = os.environ["FARMOS_URL"]
    username = os.environ["FARMOS_USERNAME"]
    password = os.environ["FARMOS_PASSWORD"]

    # T-62-34: guard -- must target dev :18080, never prod :8082.
    assert ":18080" in farmos_url, (
        f"T-62-34 GUARD FAILED: FARMOS_URL must target dev :18080, got: {farmos_url!r}. "
        "Never run this live-fire against prod :8082."
    )

    # T-62-36: unique block_name per run to prevent dirty-state masking.
    run_ts = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    block_name = f"LF_{run_ts}_SHI_1"

    # Load and patch seeding draft fixture with unique block_name.
    base_draft = json.loads(_SEEDING_DRAFT_PATH.read_text())
    draft: dict = {
        **base_draft,
        "block_name": block_name,
        "draft_json": {
            **base_draft["draft_json"],
            "block_name": block_name,
        },
    }

    # Paper-trail dir (T-62-35: uuids only, never creds).
    trail_dir = Path(__file__).parent.parent / "live-fire-trails"
    trail_dir.mkdir(exist_ok=True)
    trail_path = trail_dir / f"lf_{run_ts}.jsonl"

    # Accumulate trail entries as we go so partial data is written on failure.
    trail: dict = {"run_ts": run_ts, "block_name": block_name}

    async with httpx.AsyncClient() as http:
        client = create_farmos_client(farmos_url, username, password, http)

        # -------------------------------------------------------------------
        # Run A: commit seeding draft
        # -------------------------------------------------------------------
        result_a = await commit(client, draft)
        assert result_a["ok"], (
            f"Run A commit failed: reason={result_a.get('reason')!r} "
            f"latency={result_a.get('latency_ms')}ms"
        )
        assert result_a["asset_ids"], (
            f"Run A: expected at least one asset_id in result, got: {result_a}"
        )
        asset_id = result_a["asset_ids"][0]
        trail["run_a_asset_id"] = asset_id
        trail["run_a_asset_ids"] = result_a["asset_ids"]

        # Name-filter count after Run A -- must be exactly 1.
        enc = urllib.parse.quote(block_name, safe="")
        count_r_a = await client["get"](f"/api/asset/fungi?filter[name][value]={enc}")
        assert count_r_a["ok"], f"Run A name-filter GET failed: {count_r_a}"
        data_a = (count_r_a.get("body") or {}).get("data") or []
        assert len(data_a) == 1, (
            f"Run A: expected 1 asset for block_name={block_name!r}, got {len(data_a)}"
        )

        # -------------------------------------------------------------------
        # SC3: upload image to asset image field; verify field is non-empty
        # -------------------------------------------------------------------
        assert _TEST_IMAGE_PATH.exists(), (
            f"Test image not found: {_TEST_IMAGE_PATH}. "
            "The paper-log.jpg fixture must be present in the repo."
        )
        img_r = await upload_field_attachment(
            client,
            "/api/asset/fungi",
            asset_id,
            "image",
            str(_TEST_IMAGE_PATH),
        )
        assert img_r["ok"], (
            f"SC3: image upload failed: {img_r}"
        )
        file_id = img_r.get("file_id")
        assert file_id, f"SC3: upload succeeded but returned no file_id: {img_r}"
        trail["file_id"] = file_id

        # GET asset and verify image relationship contains the uploaded file uuid.
        asset_r = await client["get"](f"/api/asset/fungi/{asset_id}")
        assert asset_r["ok"], f"SC3: GET asset/{asset_id} failed: {asset_r}"
        asset_data = (asset_r.get("body") or {}).get("data") or {}
        image_rel = (asset_data.get("relationships") or {}).get("image") or {}
        image_field_data = image_rel.get("data")
        assert image_field_data, (
            f"SC3 FAILED: asset {asset_id} image relationship is empty after upload. "
            f"file_id={file_id!r}"
        )
        # data may be a list (multi-value) or a single object.
        items = image_field_data if isinstance(image_field_data, list) else [image_field_data]
        image_ids_on_asset = [item.get("id") for item in items if isinstance(item, dict)]
        assert file_id in image_ids_on_asset, (
            f"SC3 FAILED: uploaded file_id {file_id!r} not found in asset image field. "
            f"image_ids_on_asset={image_ids_on_asset}"
        )

        # -------------------------------------------------------------------
        # Run B: clear cache, re-commit same draft (SC2 -- assert 0 duplicates)
        # -------------------------------------------------------------------
        _clear_cache()
        result_b = await commit(client, draft)
        assert result_b["ok"], (
            f"Run B commit failed: reason={result_b.get('reason')!r} "
            f"latency={result_b.get('latency_ms')}ms"
        )
        trail["run_b_asset_ids"] = result_b["asset_ids"]

        # Re-query name filter after Run B -- must still be exactly 1.
        _clear_cache()
        count_r_b = await client["get"](f"/api/asset/fungi?filter[name][value]={enc}")
        assert count_r_b["ok"], f"Run B name-filter GET failed: {count_r_b}"
        data_b = (count_r_b.get("body") or {}).get("data") or []
        assert len(data_b) == 1, (
            f"SC2 FAILED: second run created duplicate(s). "
            f"Expected 1 asset for block_name={block_name!r}, got {len(data_b)}"
        )

        # -------------------------------------------------------------------
        # SC4: strain-mismatch draft -- fidelity gate must hold; 0 assets created
        # -------------------------------------------------------------------
        mismatch_block = f"LF_{run_ts}_MISMATCH"
        mismatch_draft: dict = {
            "log_type": "seeding",
            "id": "lf-mismatch-001",
            "block_name": mismatch_block,
            "draft_json": {
                "block_name": mismatch_block,
                "species_code": "SHI",   # draft says SHI
                "timestamp": base_draft["draft_json"]["timestamp"],
                "notes": "live-fire fidelity mismatch test",
            },
        }
        # In-memory CSV says this block maps to KOY -- contradicts SHI in draft.
        fidelity_rows = [{"block_name": mismatch_block, "strain_code": "KOY"}]
        fidelity_result = check_fidelity(mismatch_draft, fidelity_rows)

        assert fidelity_result.get("reason") == "strain_mismatch", (
            f"SC4: check_fidelity did not detect mismatch. "
            f"result={fidelity_result}"
        )
        assert fidelity_result.get("hold_status") == "fidelity_cross_check_unverified", (
            f"SC4: expected hold_status='fidelity_cross_check_unverified', "
            f"got: {fidelity_result.get('hold_status')!r}"
        )
        trail["mismatch_block"] = mismatch_block
        trail["fidelity_hold_status"] = fidelity_result.get("hold_status")

        # Simulate watchdog: fidelity holds the draft -> do NOT call commit_router.
        # Verify no asset exists in dev farmOS for the mismatch block_name.
        enc_mm = urllib.parse.quote(mismatch_block, safe="")
        mm_count_r = await client["get"](f"/api/asset/fungi?filter[name][value]={enc_mm}")
        assert mm_count_r["ok"], (
            f"SC4: mismatch name-filter GET failed: {mm_count_r}"
        )
        mm_data = (mm_count_r.get("body") or {}).get("data") or []
        assert len(mm_data) == 0, (
            f"SC4 FAILED: fidelity-held mismatch draft produced {len(mm_data)} asset(s) "
            f"for block_name={mismatch_block!r} (expected 0)"
        )

    # -------------------------------------------------------------------
    # Paper trail (T-62-35: uuids only, never creds)
    # -------------------------------------------------------------------
    with open(trail_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(trail) + "\n")

    print(
        f"\n[live-fire] run_ts={run_ts}"
        f"\n[live-fire] SC2 PASS: block_name={block_name!r} -> 1 asset after 2 runs"
        f"\n[live-fire] SC3 PASS: file_id={file_id!r} on asset {asset_id!r} image field"
        f"\n[live-fire] SC4 PASS: mismatch held as "
        f"{fidelity_result.get('hold_status')!r}, 0 assets in dev farmOS"
        f"\n[live-fire] paper-trail -> {trail_path}"
    )
