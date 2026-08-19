"""MUSHY-94 backfill, step 2 of 2: REWRITE. Edits committed farm history.

Moves a log that sits at exact UTC midnight to LOCAL midnight of the SAME
calendar date, so it renders on the day its name already claims. Pre-e57c3b8
the commit path stored date-only farm events at 00:00Z, which America/Montevideo
renders at 21:00 the previous day.

Authorised by Don Santiago 2026-08-19, with the explicit condition that a log
carrying a real clock time is LEFT ALONE. The survey found the two sets are
disjoint by author: all 146 UTC-midnight logs are mushy-committed, and none of
the 116 human-created logs sit at UTC midnight.

Safety:
  * DRY RUN unless --apply is passed (the MUSHY-87 replay decision, same shape).
  * Re-reads every patched log and compares against the intended value. A 200
    is not taken as evidence.
  * Appends a receipt per log BEFORE and AFTER, so an interrupted run is
    resumable and every edit has a paper trail with the old value.
  * Skips any log whose CURRENT timestamp is no longer UTC midnight, so a
    re-run cannot double-shift.

  docker exec mushy-alerter-py-1 /app/.venv/bin/python \
      /tmp/mushy94/rewrite.py /tmp/mushy94/survey.jsonl /tmp/mushy94/receipts.jsonl [--apply] [--limit N]
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, "/app")

from farm_agent.farmos.client import create_farmos_client  # noqa: E402
from farm_agent.tenancy.tenant import load as load_config  # noqa: E402

DAY = 86400


async def main() -> None:
    survey_path, receipts_path = sys.argv[1], sys.argv[2]
    apply = "--apply" in sys.argv
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    config = load_config(os.environ)
    tz = ZoneInfo(config.farm_timezone)

    rows = [json.loads(line) for line in open(survey_path)]
    todo = [r for r in rows if r["utc_midnight"] and r["mushy"]]
    if limit:
        todo = todo[:limit]

    # Already-processed ids, so an interrupted run resumes instead of redoing.
    done: set[str] = set()
    if os.path.exists(receipts_path):
        for line in open(receipts_path):
            rec = json.loads(line)
            if rec.get("phase") == "verified":
                done.add(rec["id"])
    todo = [r for r in todo if r["id"] not in done]

    print(f"mode         : {'APPLY -- editing farm history' if apply else 'DRY RUN'}")
    print(f"candidates   : {len(todo)} (already verified this run-set: {len(done)})")
    print()

    import httpx
    ok = failed = skipped = 0
    async with httpx.AsyncClient(timeout=60.0) as http:
        client = create_farmos_client(
            farmos_url=config.farmos_url,
            username=config.farmos_username,
            password=config.farmos_password,
            http=http,
            timeout_ms=60000,
        )
        receipts = open(receipts_path, "a")

        for r in todo:
            bundle, uuid, old_ts = r["bundle"], r["id"], r["timestamp"]
            date_utc = datetime.fromtimestamp(old_ts, tz=timezone.utc).date()
            new_ts = int(datetime.combine(date_utc, time.min, tzinfo=tz).timestamp())

            label = f"{bundle}/{r['drupal_id']} {r['name']!r}"
            shows_now = datetime.fromtimestamp(old_ts, tz=tz).strftime("%Y-%m-%d")
            shows_then = datetime.fromtimestamp(new_ts, tz=tz).strftime("%Y-%m-%d")

            if new_ts == old_ts:
                print(f"  SKIP  {label}: local midnight already equals UTC midnight")
                skipped += 1
                continue

            if not apply:
                print(f"  would move {label}: renders {shows_now} -> {shows_then}")
                continue

            # Re-read first: never patch off a stale snapshot, and never
            # double-shift a log a previous run already moved.
            cur = await client["get"](f"/api/log/{bundle}/{uuid}")
            if not cur.get("ok"):
                print(f"  FAIL  {label}: re-read status={cur.get('status')}")
                failed += 1
                continue
            cur_ts = (cur["body"]["data"]["attributes"] or {}).get("timestamp")
            if isinstance(cur_ts, str):
                cur_ts = int(datetime.fromisoformat(cur_ts.replace("Z", "+00:00")).timestamp())
            if int(cur_ts) % DAY != 0:
                print(f"  SKIP  {label}: no longer at UTC midnight (now {cur_ts})")
                skipped += 1
                continue

            receipts.write(json.dumps({
                "phase": "before", "id": uuid, "bundle": bundle,
                "drupal_id": r["drupal_id"], "name": r["name"],
                "old_timestamp": int(cur_ts), "new_timestamp": new_ts,
                "rendered_before": shows_now, "rendered_after": shows_then,
            }) + "\n")
            receipts.flush()

            resp = await client["patch"](f"/api/log/{bundle}/{uuid}", {
                "data": {"type": f"log--{bundle}", "id": uuid,
                         "attributes": {"timestamp": new_ts}},
            })
            if not resp.get("ok"):
                print(f"  FAIL  {label}: patch status={resp.get('status')}")
                failed += 1
                continue

            # Verify by re-reading. A 200 is not evidence the value landed.
            back = await client["get"](f"/api/log/{bundle}/{uuid}")
            got = (back.get("body", {}).get("data", {}).get("attributes") or {}).get("timestamp")
            if isinstance(got, str):
                got = int(datetime.fromisoformat(got.replace("Z", "+00:00")).timestamp())
            if int(got) != new_ts:
                print(f"  FAIL  {label}: verify mismatch got={got} want={new_ts}")
                failed += 1
                continue

            receipts.write(json.dumps({
                "phase": "verified", "id": uuid, "bundle": bundle,
                "drupal_id": r["drupal_id"], "name": r["name"],
                "old_timestamp": int(cur_ts), "new_timestamp": new_ts,
                "rendered_before": shows_now, "rendered_after": shows_then,
            }) + "\n")
            receipts.flush()
            ok += 1
            print(f"  OK    {label}: {shows_now} -> {shows_then}")

        receipts.close()

    print()
    print(f"verified {ok}, failed {failed}, skipped {skipped}")
    if not apply:
        print("DRY RUN -- nothing was modified. Re-run with --apply.")


asyncio.run(main())
