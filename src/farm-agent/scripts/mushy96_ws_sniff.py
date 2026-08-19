"""MUSHY-96: observe what the bridge actually sends on the chamber WS.

The alerter holds a stable connection but its heartbeat summary stays empty,
which means the frames arriving are not the ones the FSM recognises
(`humidity`, `temperature`, `co2`, ...). This prints the shape of whatever does
arrive, so the mismatch is read rather than guessed.

Read-only. Connects, samples, disconnects.

  docker exec mushy-alerter-py-1 /app/.venv/bin/python /tmp/mushy96/sniff.py [seconds]
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from collections import Counter

sys.path.insert(0, "/app")

import websockets  # noqa: E402

from farm_agent.tenancy.tenant import load as load_config  # noqa: E402


async def main() -> None:
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0
    from farm_agent.chamber.config import load as load_chamber

    tenant = load_config(os.environ)
    config = load_chamber(os.environ, tenant_config=tenant)
    url = config.bridge_ws_url
    print(f"connecting to {url} for {seconds}s")

    kinds: Counter = Counter()
    samples: dict = {}
    non_dict = 0

    try:
        sock = await websockets.connect(url, ping_interval=20, ping_timeout=90)
    except Exception as e:
        print(f"CONNECT FAILED: {type(e).__name__}: {e}")
        return

    async with sock:
        try:
            async with asyncio.timeout(seconds):
                async for raw in sock:
                    try:
                        msg = json.loads(raw)
                    except Exception:
                        non_dict += 1
                        continue
                    if not isinstance(msg, dict):
                        non_dict += 1
                        continue
                    key = msg.get("type") or f"<no type: keys={sorted(msg)[:6]}>"
                    kinds[key] += 1
                    samples.setdefault(key, msg)
        except (TimeoutError, asyncio.TimeoutError):
            pass

    print(f"\nframes by type over {seconds}s (non-dict/unparseable: {non_dict}):")
    for k, n in kinds.most_common(20):
        print(f"  {n:5d}  {k}")
    print("\none sample of each:")
    for k, m in list(samples.items())[:8]:
        print(f"  {k}: {json.dumps(m)[:220]}")

    fsm_types = {"humidity", "temperature", "co2", "sensor_health", "humidifier",
                 "pi_liveness", "mode_update", "globals_update", "overrides_update",
                 "sensor_freshness"}
    seen = set(kinds) & fsm_types
    print(f"\nFSM-recognised types seen: {sorted(seen) or 'NONE'}")


asyncio.run(main())
