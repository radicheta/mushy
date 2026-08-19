"""
farm_agent/farmos/activity_logs.py -- log--activity with is_group_assignment=True.

Port of src/agents/alerter/src/farmos/activityLogs.js (Phase 52 Plan 02 / Phase 62-09).

Per farmos team correction (2026-05-24 design note): there is NO log--group
bundle in stock farmOS. The canonical membership-assignment pattern is a
log--activity with attributes.is_group_assignment=True plus relationships:
asset[]=childIds, group[]=[sessionGroupId].

CREATION-ONLY for v1.10.1 -- no upsert/merge/lookup. Duplicate calls on
retry are acceptable (both logs reference the same children + group, no
semantic harm). Phase 51's upsert-by-stable-identity layer (separate
milestone) will dedupe these later.

ASCII-only. No em-dashes. Never-throws.
"""

from __future__ import annotations

import math
import time

from farm_agent.farmos.farm_time import date_only_epoch


def epoch_seconds_for_date(date_str: str) -> int:
    """Parse YYYY-MM-DD as LOCAL midnight; return Unix epoch seconds.

    Port of epochSecondsForDate() from activityLogs.js.
    Falls back to now() on parse failure (mirrors JS Date.parse NaN path).

    MUSHY-94: was UTC midnight, which farmOS rendered at 21:00 the previous day
    for a farm running UTC-3. The date the farmer stated is now the date that
    renders. See farmos/farm_time.py.
    """
    epoch = date_only_epoch(date_str)
    if epoch is None:
        return math.floor(time.time())
    return epoch


async def create_group_assignment_log(client: dict, opts: dict) -> dict:
    """POST a log--activity with is_group_assignment=True.

    Port of createGroupAssignmentLog() from activityLogs.js.

    Returns {"ok": True, "log_id": str, "http_status": int} on success,
    or {"ok": False, "reason": str, "http_status": int?} on failure.
    """
    child_ids = opts.get("child_ids") or []
    session_group_id = opts.get("session_group_id")
    event_date = opts.get("event_date")
    name = opts.get("name")
    draft_id = opts.get("draft_id")
    notes = opts.get("notes") or None

    note_value = (notes + "\n" if notes else "") + "mushy:draft:" + str(draft_id)
    timestamp = epoch_seconds_for_date(event_date)

    payload = {
        "data": {
            "type": "log--activity",
            "attributes": {
                "name": name,
                "timestamp": timestamp,
                "status": "done",
                "is_group_assignment": True,
                "notes": {"value": note_value, "format": "plain_text"},
            },
            "relationships": {
                "asset": {
                    "data": [{"type": "asset--fungi", "id": cid} for cid in child_ids]
                },
                "group": {
                    "data": [{"type": "asset--group", "id": session_group_id}]
                },
            },
        },
    }

    r = await client["post"]("/api/log/activity", payload)
    if not r["ok"]:
        return {
            "ok": False,
            "reason": "http_" + (str(r.get("status")) if r.get("status") else "network"),
            "http_status": r.get("status"),
        }
    log_id = ((r.get("body") or {}).get("data") or {}).get("id")
    if not log_id:
        return {
            "ok": False,
            "reason": "no_log_id_in_response",
            "http_status": r.get("status"),
        }
    return {"ok": True, "log_id": log_id, "http_status": r.get("status")}


async def delete_activity_log(client: dict, log_id: str) -> dict:
    """DELETE /api/log/activity/<id>.

    Port of deleteActivityLog() from activityLogs.js.
    Returns {"ok": True, "http_status": int} or {"ok": False, "reason": str}.
    Never raises.
    """
    if not log_id:
        return {"ok": False, "reason": "missing_log_id"}
    if not callable(client.get("delete")):
        return {"ok": False, "reason": "client_delete_unavailable"}
    r = await client["delete"]("/api/log/activity/" + log_id)
    if not r["ok"]:
        return {
            "ok": False,
            "reason": "http_" + (str(r.get("status")) if r.get("status") else "network"),
            "http_status": r.get("status"),
        }
    return {"ok": True, "http_status": r.get("status")}
