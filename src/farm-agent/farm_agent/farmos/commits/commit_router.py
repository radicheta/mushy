"""farm_agent/farmos/commits/commit_router.py -- Dispatch one signal_draft.log_type
to its commit handler after normalize().

Faithful Python port of src/agents/alerter/src/farmos/commits/commit-router.js
(Phase 40 D-03 / Phase 62-10).

Single guard on log_type validity (defense-in-depth). Uniform result envelope.
UnsupportedLogTypeError from a handler is folded into the unsupported envelope;
any other exception returns ok=False with the exception message.

No DB access. Pure dispatch over the injected farmOS client.

No em-dashes in source artifacts.
"""
from __future__ import annotations

import time

from farm_agent.farmos.commits.commit_activity import commit_activity
from farm_agent.farmos.commits.commit_harvest import commit_harvest
from farm_agent.farmos.commits.commit_input import commit_input
from farm_agent.farmos.commits.commit_observation import commit_observation
from farm_agent.farmos.commits.commit_seeding import commit_seeding
from farm_agent.farmos.commits.commit_seeding_session import commit_seeding_session
from farm_agent.farmos.commits.normalize import normalize
from farm_agent.farmos.logs import LOG_TYPES, UnsupportedLogTypeError

DISPATCH: dict = {
    "seeding": commit_seeding,
    "activity": commit_activity,
    "input": commit_input,
    "observation": commit_observation,
    "harvest": commit_harvest,
    "seeding_session": commit_seeding_session,
}


async def commit(client: dict, draft: dict | None, ctx: dict | None = None) -> dict:
    """Dispatch one signal_draft.log_type to its commit module.

    Applies normalize(draft) before dispatch. The original draft is NOT mutated.

    Returns {"ok": bool, "asset_ids": list, "log_ids": list, "file_ids": list,
             "attachments_failed": list, "latency_ms": int, "reason": str|None}
    """
    t0 = time.monotonic()

    log_type = (draft or {}).get("log_type")
    if not log_type or log_type not in LOG_TYPES:
        return {
            "ok": False,
            "reason": "unsupported_log_type",
            "log_type": log_type,
            "asset_ids": [],
            "log_ids": [],
            "file_ids": [],
            "latency_ms": int((time.monotonic() - t0) * 1000),
        }

    fn = DISPATCH[log_type]
    try:
        r = await fn(client, normalize(draft), ctx)
        return {
            "ok": bool(r.get("ok")),
            "asset_ids": r.get("asset_ids") or [],
            "log_ids": r.get("log_ids") or [],
            "file_ids": r.get("file_ids") or [],
            "attachments_failed": r.get("attachments_failed") or [],
            "latency_ms": int((time.monotonic() - t0) * 1000),
            "reason": r.get("reason"),
        }
    except UnsupportedLogTypeError as e:
        return {
            "ok": False,
            "reason": "unsupported_log_type",
            "log_type": getattr(e, "log_type", None),
            "asset_ids": [],
            "log_ids": [],
            "file_ids": [],
            "latency_ms": int((time.monotonic() - t0) * 1000),
        }
    except Exception as e:  # noqa: BLE001
        return {
            "ok": False,
            "reason": str(e) or "commit_error",
            "asset_ids": [],
            "log_ids": [],
            "file_ids": [],
            "latency_ms": int((time.monotonic() - t0) * 1000),
        }
