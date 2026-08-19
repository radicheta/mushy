"""MUSHY-94 backfill, step 1 of 2: SURVEY. Read-only.

Enumerates every log in prod farmOS and classifies it by whether its timestamp
sits at exact UTC midnight -- the fingerprint of the pre-e57c3b8 commit path,
which stored a date-only farm event at 00:00Z and so rendered it a day early in
America/Montevideo.

Writes a full snapshot to JSONL. Nothing is modified here; the rewrite is a
separate script that reads this snapshot.

Run inside the alerter-py container so farmOS credentials come from the already
loaded TenantConfig:

  docker exec mushy-alerter-py-1 /app/.venv/bin/python \
      /app/scripts/mushy94_survey.py /app/out/mushy94-survey.jsonl
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, "/app")

from farm_agent.farmos.client import create_farmos_client  # noqa: E402
from farm_agent.tenancy.tenant import load as load_config  # noqa: E402

# Every log bundle the agent has ever written, plus the stock ones a human may
# have created by hand, so the survey sees the whole record and not just ours.
LOG_TYPES = [
    "activity", "seeding", "harvest", "input", "observation",
    "lab_test", "maintenance", "medical", "purchase", "sale", "transplanting",
]

DAY = 86400


async def main() -> None:
    out_path = sys.argv[1]
    config = load_config(os.environ)
    tz = ZoneInfo(config.farm_timezone)

    import httpx
    async with httpx.AsyncClient(timeout=60.0) as http:
        client = create_farmos_client(
            farmos_url=config.farmos_url,
            username=config.farmos_username,
            password=config.farmos_password,
            http=http,
            timeout_ms=60000,
        )

        rows: list[dict] = []
        for lt in LOG_TYPES:
            # sort by id: without a stable sort farmOS paginates inconsistently
            # and the first run of this both duplicated 28 rows and HID 28 others.
            path = f"/api/log/{lt}?page[limit]=200&sort=drupal_internal__id"
            while path:
                r = await client["get"](path)
                if not r.get("ok"):
                    print(f"[{lt}] SKIP status={r.get('status')}", file=sys.stderr)
                    break
                body = r.get("body") or {}
                for item in body.get("data") or []:
                    attrs = item.get("attributes") or {}
                    ts = attrs.get("timestamp")
                    if isinstance(ts, str):
                        try:
                            ts = int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp())
                        except ValueError:
                            ts = None
                    if not isinstance(ts, (int, float)):
                        continue
                    ts = int(ts)
                    notes = ((attrs.get("notes") or {}) or {}).get("value") or ""
                    rows.append({
                        "type": item.get("type"),
                        "bundle": lt,
                        "id": item.get("id"),
                        "drupal_id": attrs.get("drupal_internal__id"),
                        "name": attrs.get("name"),
                        "timestamp": ts,
                        "utc": datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                        "local": datetime.fromtimestamp(ts, tz=tz).strftime("%Y-%m-%d %H:%M:%S"),
                        "utc_midnight": ts % DAY == 0,
                        "mushy": "mushy:draft:" in notes,
                        "status": attrs.get("status"),
                    })
                nxt = ((body.get("links") or {}).get("next") or {}).get("href")
                path = nxt if nxt else None

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")

    at_midnight = [r for r in rows if r["utc_midnight"]]
    other = [r for r in rows if not r["utc_midnight"]]
    print(f"total logs                  : {len(rows)}")
    print(f"at exact UTC midnight       : {len(at_midnight)}   <- candidates")
    print(f"  of those, mushy-committed : {sum(1 for r in at_midnight if r['mushy'])}")
    print(f"  of those, NOT mushy       : {sum(1 for r in at_midnight if not r['mushy'])}")
    print(f"carrying a real clock time  : {len(other)}   <- leave alone")
    print(f"  of those, mushy-committed : {sum(1 for r in other if r['mushy'])}")
    print()
    print("by bundle (candidates):")
    counts: dict[str, int] = {}
    for r in at_midnight:
        counts[r["bundle"]] = counts.get(r["bundle"], 0) + 1
    for k, v in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {k:<16} {v}")
    print()
    print("NOT-mushy logs at UTC midnight (would be edited too -- inspect):")
    for r in at_midnight:
        if not r["mushy"]:
            print(f"  {r['bundle']}/{r['drupal_id']} {r['utc']}  {r['name']!r}")
    print()
    print(f"snapshot -> {out_path}")


asyncio.run(main())
