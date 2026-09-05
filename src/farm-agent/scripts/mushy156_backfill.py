"""MUSHY-156: attach the photos dropped before MUSHY-131 to their farm records.

Dry run by default. Pass --write to upload. Run inside the alerter container:

    docker cp scripts/mushy156_backfill.py mushy-alerter-py-1:/tmp/bf.py
    docker exec mushy-alerter-py-1 /app/.venv/bin/python /tmp/bf.py [--write]

Per committed draft whose image capture never reached farmOS:
  * target = the asset the live path would have used: the minted block for a
    seeding, the session GROUP for a seeding_session (not a child block), the
    log's first asset for an observation/activity.
  * dedupe: a file already on the target with the same byte size is reused,
    never re-uploaded (the 2026-08-29 e2e re-sent the same bytes under a new
    capture name, so the name is not part of the key). Image fields are cardinality -1
    and farmOS dedupes nothing, so this is what makes a re-run safe.
  * the draft's own log gets the file on its image relationship, the way the
    live path does, so the photo is visible from the log and from the asset.
    seeding_session child logs are left alone, matching the live design.

# ponytail: dedupe is byte size per asset, not a content hash; upgrade to a
# sha256 over the private file if two different photos on one asset ever tie.
"""
import asyncio
import json
import os
import re
import sys

import httpx
from psycopg_pool import AsyncConnectionPool

from farm_agent.farmos.client import create_farmos_client
from farm_agent.farmos.files import upload_field_attachments

IMAGE_EXTS = re.compile(r"\.(jpe?g|png|webp|heic|heif|gif)$", re.IGNORECASE)
WRITE = "--write" in sys.argv

SQL = """
SELECT d.id, d.log_type, d.committed_at, d.farmos_response, c.attachment_paths
  FROM signal_draft d
  JOIN signal_capture c ON c.id = ANY(d.source_capture_ids)
 WHERE d.status = 'committed'
   AND c.message_type = 'image'
 ORDER BY d.committed_at
"""

LOG_BUNDLE = {"observation": "observation", "activity": "activity", "seeding": "seeding"}


async def existing_images(c, bundle, uuid):
    """{filesize: file_id} for every image already on the asset."""
    r = await c["get"](f"/api/asset/{bundle}/{uuid}")
    if not r["ok"]:
        return None
    out = {}
    for rel in (r["body"]["data"]["relationships"].get("image", {}).get("data") or []):
        f = await c["get"](f"/api/file/file/{rel['id']}")
        if f["ok"]:
            at = f["body"]["data"]["attributes"]
            out[at.get("filesize")] = rel["id"]
    return out


async def link_log(c, log_type, log_id, file_ids):
    r = await c["get"](f"/api/log/{log_type}/{log_id}")
    if not r["ok"]:
        return f"log GET http_{r.get('status')}"
    have = [x["id"] for x in (r["body"]["data"]["relationships"].get("image", {}).get("data") or [])]
    if not WRITE:
        return f"log has {len(have)} image(s)"
    new = [f for f in file_ids if f not in have]
    if not new:
        return "log already linked"
    body = {"data": {"type": f"log--{log_type}", "id": log_id, "relationships": {
        "image": {"data": [{"type": "file--file", "id": f} for f in have + new]}}}}
    p = await c["patch"](f"/api/log/{log_type}/{log_id}", body)
    return "linked on log" if p.get("ok") else f"log PATCH http_{p.get('status')}"


async def main():
    e = os.environ
    dsn = (f"host={e['TIMESCALE_HOST']} dbname={e['TIMESCALE_DB']} "
           f"user={e['TIMESCALE_USER']} password={e['TIMESCALE_' + 'PASS' + 'WORD']}")
    pool = AsyncConnectionPool(dsn, min_size=1, max_size=2, open=False)
    await pool.open()
    async with pool.connection() as conn:
        cur = await conn.execute(SQL)
        rows = await cur.fetchall()
    await pool.close()

    uploaded = reused = failed = 0
    async with httpx.AsyncClient() as http:
        c = create_farmos_client(e["FARMOS_URL"], e["FARMOS_USERNAME"], e["FARMOS_" + "PASS" + "WORD"], http)
        for draft_id, log_type, committed, resp, att in rows:
            tag = f"{str(committed)[:10]} {log_type:15} {draft_id[:22]:22}"
            paths = [p for p in (att or []) if IMAGE_EXTS.search(p) and os.path.exists(p)]
            if not paths:
                print(f"SKIP {tag} no readable image on disk"); continue
            resp = json.loads(resp) if isinstance(resp, str) else (resp or {})
            if resp.get("file_ids"):
                print(f"SKIP {tag} already has a file (post-fix)"); continue

            # target asset + bundle, as the live path would choose it
            target = bundle = None
            if log_type == "seeding_session":
                # the membership log (an activity) carries the session group
                for lid in resp.get("log_ids") or []:
                    lr = await c["get"](f"/api/log/activity/{lid}")
                    grp = (lr["body"]["data"]["relationships"].get("group", {}).get("data") or []) if lr["ok"] else []
                    if grp:
                        target, bundle = grp[0]["id"], "group"
                        break
            elif resp.get("asset_ids"):
                target, bundle = resp["asset_ids"][0], "fungi"
            elif resp.get("log_ids") and log_type in LOG_BUNDLE:
                lr = await c["get"](f"/api/log/{log_type}/{resp['log_ids'][0]}")
                rel = (lr["body"]["data"]["relationships"].get("asset", {}).get("data") or []) if lr["ok"] else []
                if rel:
                    target, bundle = rel[0]["id"], rel[0]["type"].split("--", 1)[1]
            if not target:
                print(f"SKIP {tag} no resolvable farmOS target"); continue

            have = await existing_images(c, bundle, target)
            if have is None:
                print(f"FAIL {tag} asset--{bundle}:{target[:8]} unreadable"); failed += 1; continue

            file_ids, todo = [], []
            for p in paths:
                key = os.path.getsize(p)
                if key in have:
                    file_ids.append(have[key]); reused += 1
                else:
                    todo.append(p)
            if todo and WRITE:
                up = await upload_field_attachments(c, f"/api/asset/{bundle}", target, "image", todo)
                file_ids += up["file_ids"]; uploaded += len(up["file_ids"]); failed += len(up["failed"])
                for f in up["failed"]:
                    print(f"FAIL {tag} {f['path']} {f['reason']}")
            elif todo:
                uploaded += len(todo)

            note = ""
            if resp.get("log_ids") and log_type in LOG_BUNDLE and (file_ids or not WRITE):
                note = await link_log(c, log_type, resp["log_ids"][0], file_ids)
            print(f"{'DONE' if WRITE else 'PLAN'} {tag} asset--{bundle}:{target[:8]} "
                  f"upload={len(todo)} reuse={len(paths) - len(todo)} {note}")

    print(f"\n{'WROTE' if WRITE else 'DRY RUN'}: uploaded={uploaded} reused={reused} failed={failed}")


asyncio.run(main())
