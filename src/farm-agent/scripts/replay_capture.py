"""MUSHY-87: re-drive stored captures through the real extraction pipeline.

When extraction improves, this is how a capture already on disk gets a corrected
draft -- instead of asking the farmer to re-photograph and re-record a session
they logged once already.

    # what would happen (no extractor call, no writes, no sends)
    .venv/bin/python scripts/replay_capture.py 01J0... 01J0...

    # re-extract and write a replay-scoped draft; preview is printed, not sent
    .venv/bin/python scripts/replay_capture.py --apply 01J0...

    # ... and actually message the farmer
    .venv/bin/python scripts/replay_capture.py --apply --send 01J0...

Two safety defaults, per the 2026-08-19 decisions:

  * The replayed draft gets its own id (`--run-id`, default a UTC stamp) and the
    superseded row is left alone. `source_capture_ids` still names the originals.
  * Sends are off unless `--send` is passed. A replay is usually fixing your own
    extraction, and an unexpected DM about an already-logged session is noise.

Multiple captures replay in `captured_at` order, so continuity and multimodal
fusion behave as they did live. The extraction date anchor is each capture's own
`captured_at`, never the replay clock.

One thing `--apply` cannot make safe: the draft it writes is a real
`awaiting_farmer` row, so it becomes that sender's in-flight draft. The replay
will not append to the draft it is superseding (see `replay_scoped_db`), but the
farmer's *next* real capture can append to the replay. Do not replay someone's
captures while they are mid-conversation with the bot.

Run it inside the container to reach the live DB, farmOS and signal-cli:

    docker exec mushy-alerter-py-1 /app/.venv/bin/python \\
        /app/scripts/replay_capture.py 01J0...
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import anthropic  # noqa: E402
import httpx  # noqa: E402

from farm_agent.capture.replay import (  # noqa: E402
    fetch_captures,
    replay_captures,
    replay_scoped_db,
)
from farm_agent.extraction import extraction_db  # noqa: E402
from farm_agent.extraction import preview_builder as extraction_preview_builder  # noqa: E402
from farm_agent.extraction.extractor import create_extractor  # noqa: E402
from farm_agent.extraction.outbound import create_outbound_dispatcher  # noqa: E402
from farm_agent.extraction.pipeline import create_extraction_pipeline  # noqa: E402
from farm_agent.farmos.farm_time import configure as configure_farm_timezone  # noqa: E402
from farm_agent.persistence import outbound_repo  # noqa: E402
from farm_agent.persistence.pool import build_pool  # noqa: E402
from farm_agent.signal_io.client import SignalClient  # noqa: E402
from farm_agent.tenancy.tenant import load as load_config  # noqa: E402

log = logging.getLogger("replay")


class _PrintingSignalClient:
    """Stands in for SignalClient so a replay shows the preview instead of sending it.

    The preview is still built by the real dispatcher and preview_builder, so what
    is printed is the message the farmer would have received, byte for byte.
    """

    async def send(self, body, to=None, **kwargs):
        print("\n--- would send " + f"(to={to}, intent={kwargs.get('intent')}) ---")
        print(body)
        print("--- end ---\n")
        return {"ok": True, "dry_run": True}


def _parse_args(argv):
    p = argparse.ArgumentParser(description="Replay stored captures (MUSHY-87)")
    p.add_argument("capture_ids", nargs="+", help="signal_capture ids to replay")
    p.add_argument("--apply", action="store_true", help="actually re-extract and write drafts")
    p.add_argument("--send", action="store_true", help="dispatch the preview to the farmer")
    p.add_argument(
        "--run-id",
        default=None,
        help="replay marker mixed into the draft id (default: a UTC stamp)",
    )
    return p.parse_args(argv)


async def main(argv=None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    config = load_config(os.environ)
    configure_farm_timezone(config.farm_timezone)
    pool = await build_pool(config)

    rows = await fetch_captures(pool, args.capture_ids)
    found = {r["id"] for r in rows}
    for missing in [cid for cid in args.capture_ids if cid not in found]:
        log.warning("no signal_capture row for %s -- skipped", missing)
    if not rows:
        log.error("nothing to replay")
        return 1

    print(f"replay run-id  : {run_id}")
    print(f"captures       : {len(rows)} (captured_at order)")
    print(f"write drafts   : {args.apply}")
    print(f"send to farmer : {args.send}")

    async with httpx.AsyncClient() as http:
        signal_client = (
            SignalClient(config=config, http=http, outbound_repo=outbound_repo, pool=pool)
            if args.send
            else _PrintingSignalClient()
        )
        extractor = create_extractor(
            client=anthropic.AsyncAnthropic(api_key=config.anthropic_api_key, max_retries=2)
        )
        pipeline = create_extraction_pipeline(
            pool=pool,
            extractor=extractor,
            config=config,
            extraction_db=replay_scoped_db(extraction_db, run_id),
            outbound_dispatcher=create_outbound_dispatcher(
                signal_client=signal_client,
                config=config,
                preview_builder=extraction_preview_builder,
                operator_recipient=config.signal_recipient,
                log=log,
            ),
            log=log,
        )

        results = await replay_captures(
            rows=rows, enqueue=pipeline["enqueue"], apply=args.apply, log=log
        )

    for r in results:
        print(f"{r['capture_id']}  applied={r['applied']}  {r['result'] or ''}")
    if not args.apply:
        print("\ndry run -- nothing extracted, written or sent. Re-run with --apply.")

    await pool.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
