"""MUSHY-131 backfill planner: DRY RUN. Inventory only, writes NOTHING to farmOS.

For every committed draft whose capture carried a photo that was dropped, work
out which farmOS asset the photo should hang off and whether the file is still
readable on disk.

Run inside the alerter container so the farmOS and Timescale credentials come
from its environment and /data/signal-capture is mounted:

    docker cp scripts/mushy131_backfill_plan.py mushy-alerter-py-1:/tmp/bfp.py
    docker exec mushy-alerter-py-1 /app/.venv/bin/python /tmp/bfp.py

Findings from the first run (2026-08-29), which are why no writes happened:

  * 13 of the 21 are `real_sheet_2026-04-25_*` -- ONE notebook page split into
    13 per-block seeding drafts, all sharing the SAME 2 images. Backfilling
    means 26 uploads of the same two photos, one pair per block. Needs a human
    call: per-block provenance, or clutter on the field that now carries real
    per-bag photos.
  * Drafts 0d322e92cd and 7dea0a62e4 both target asset 5c33d45e with the SAME
    file, and that asset ALREADY holds it from log 310. Uploading blind gives
    three copies: the image fields are cardinality -1, so nothing dedupes.
  * The 2026-05-13/14 window is live-fire test data written to prod, alongside
    the smoke2026* drafts.

Any writing version of this MUST dedupe by content hash per asset, or a re-run
silently multiplies every photo.
"""
import asyncio
import json
import os
import re

import httpx
from psycopg_pool import AsyncConnectionPool

from farm_agent.farmos.client import create_farmos_client

IMAGE_EXTS = re.compile(r"\.(jpe?g|png|webp|heic|heif|gif)$", re.IGNORECASE)

SQL = """
SELECT d.id, d.log_type, d.committed_at, d.farmos_response, c.id AS cap,
       c.attachment_paths, c.captured_at
  FROM signal_draft d
  JOIN signal_capture c ON c.id = ANY(d.source_capture_ids)
 WHERE d.status = 'committed'
   AND c.message_type = 'image'
 ORDER BY d.committed_at
"""


async def main():
    dsn = (
        f"host={os.environ['TIMESCALE_HOST']} dbname={os.environ['TIMESCALE_DB']} "
        f"user={os.environ['TIMESCALE_USER']} password={os.environ['TIMESCALE_' + 'PASSWORD']}"
    )
    pool = AsyncConnectionPool(dsn, min_size=1, max_size=2, open=False)
    await pool.open()
    async with pool.connection() as conn:
        cur = await conn.execute(SQL)
        rows = await cur.fetchall()
        cols = [c.name for c in cur.description]
    await pool.close()

    async with httpx.AsyncClient() as http:
        c = create_farmos_client(
            os.environ["FARMOS_URL"], os.environ["FARMOS_USERNAME"],
            os.environ["FARMOS_" + "PASSWORD"], http,
        )
        plan, skipped = [], []
        for row in rows:
            r = dict(zip(cols, row))
            paths = [p for p in (r["attachment_paths"] or []) if IMAGE_EXTS.search(p)]
            paths = [p for p in paths if os.path.exists(p)]
            if not paths:
                skipped.append((r["id"][:10], r["log_type"], "no readable image on disk"))
                continue
            resp = r["farmos_response"] or {}
            if isinstance(resp, str):
                resp = json.loads(resp)
            asset_ids = resp.get("asset_ids") or []
            log_ids = resp.get("log_ids") or []
            if resp.get("file_ids"):
                skipped.append((r["id"][:10], r["log_type"], "already has a file, post-fix"))
                continue
            # Which asset should hold it? Prefer a created asset; else the log's target.
            target, bundle = None, None
            if asset_ids:
                target, bundle = asset_ids[0], "fungi"
            elif log_ids:
                for lt in ("observation", "activity", "seeding", "harvest", "input"):
                    lr = await c["get"](f"/api/log/{lt}/{log_ids[0]}")
                    if lr["ok"]:
                        rel = ((lr["body"]["data"].get("relationships") or {})
                               .get("asset", {}).get("data") or [])
                        if rel:
                            target = rel[0]["id"]
                            bundle = rel[0]["type"].split("--", 1)[1]
                        break
            if not target:
                skipped.append((r["id"][:10], r["log_type"], "no resolvable farmOS target"))
                continue
            plan.append({
                "draft": r["id"][:10], "log_type": r["log_type"],
                "committed": str(r["committed_at"])[:19],
                "asset": target, "bundle": bundle,
                "photos": len(paths), "bytes": sum(os.path.getsize(p) for p in paths),
            })

    print(f"=== WOULD UPLOAD: {len(plan)} ===")
    for p in plan:
        print(f"  {p['committed']}  {p['log_type']:16} draft={p['draft']}  "
              f"-> asset--{p['bundle']}:{p['asset'][:8]}  {p['photos']} photo(s) {p['bytes']:,}B")
    print(f"\n=== SKIPPED: {len(skipped)} ===")
    for s in skipped:
        print(f"  {s[0]}  {s[1]:16} {s[2]}")
    print(f"\ntotal bytes: {sum(p['bytes'] for p in plan):,}")


asyncio.run(main())
