"""farm_agent/farmos/commit_recovery.py -- retry a transport-parked commit (MUSHY-75).

A commit that fails on transport exhausts its attempts and lands in
commit_failed. Nothing ever looks at it again. Draft 1192a845a7 sat there for 17
days: a confirmed 9-block seeding session simply absent from the farm record.

The obvious fix -- reset the attempt count once farmOS answers again -- is
wrong, and the two real cases prove it. 84d75743ae had already been written by
the Node agent before it was parked, so a blind requeue would have duplicated
four blocks; 1192a845a7 had not been written at all. Reachability cannot tell
those apart. Only farmOS can.

So the gate is an EXISTENCE check, and it doubles as the reachability check: a
lookup that cannot reach farmOS is explicitly not a miss (see
assets.find_asset_by_name), so a dead server requeues nothing.

Scope is deliberately narrow. A general "has this draft already been written" is
upsert-by-identity, which is Phase 51 and a separate milestone. Seeding drafts
carry explicit block names that ARE their identity in farmOS, so those recover
on their own; every other shape is logged and left for a human rather than
guessed at.

ASCII-only. No em-dashes. Never-throws.
"""

from __future__ import annotations

import logging

log = logging.getLogger("farm_agent.farmos.commit_recovery")

# Draft ids already reported as having no recoverable identity (MUSHY-126).
# The watchdog re-lists every parked draft each tick, and a draft this check
# rejects will be rejected identically forever, so without this the same line
# lands in the log every 30 seconds for as long as the row exists. Process-local
# on purpose: a restart is exactly when an operator wants to see it again.
_REPORTED_UNRECOVERABLE: set = set()


def expected_block_names(row: dict | None) -> list[str]:
    """The farmOS asset names this draft would create, or [] if it has none.

    An empty list means "no stable identity to check", which disqualifies the
    draft from automatic recovery. That is the honest answer for an observation
    or an activity, whose farmOS identity is not derivable from the draft.
    """
    dj = (row or {}).get("draft_json") or {}
    if not isinstance(dj, dict):
        return []
    kind = dj.get("type") or (row or {}).get("log_type")

    if kind == "seeding_session":
        names: list[str] = []
        for group in dj.get("groups") or []:
            value = ((group or {}).get("child_block_names") or {}).get("value") or []
            names += [n.strip() for n in value if isinstance(n, str) and n.strip()]
        return names

    if kind == "seeding":
        block = dj.get("block_name")
        return [block.strip()] if isinstance(block, str) and block.strip() else []

    return []


async def already_in_farmos(find_asset_by_name, names: list[str]) -> dict:
    """Has any of these blocks already been written?

    Returns {"ok": True, "exists": bool}, or {"ok": False} when farmOS could not
    be reached -- which is NOT the same as "nothing is there", and is exactly
    the confusion that would double-commit a session.

    One hit is enough. A partially written session must not be re-driven either.
    """
    for name in names:
        result = await find_asset_by_name(name)
        if result.get("error"):
            return {"ok": False}
        if result.get("found"):
            return {"ok": True, "exists": True}
    return {"ok": True, "exists": False}


async def recover_transport_parked(pool, find_asset_by_name, db, signal_client) -> int:
    """Requeue transport-parked drafts that farmOS confirms are absent.

    Returns the number requeued. Never raises: this runs inside the commit
    watchdog tick and must not take the loop down.

    Sends nothing to the farmer. A requeued draft goes back through the normal
    commit path, which acks on its own outcome.
    """
    try:
        rows = await db.find_transport_parked(pool)
    except Exception as e:  # noqa: BLE001
        log.warning("[commit_recovery] could not list parked drafts: %s", e)
        return 0

    requeued = 0
    for row in rows or []:
        draft_id = (row or {}).get("id")
        names = expected_block_names(row)
        if not names:
            if draft_id not in _REPORTED_UNRECOVERABLE:
                _REPORTED_UNRECOVERABLE.add(draft_id)
                log.info(
                    "[commit_recovery] draft_id=%s log_type=%s has no stable farmOS "
                    "identity; left parked for a human (logged once per process)",
                    draft_id, (row or {}).get("log_type"),
                )
            continue

        try:
            probe = await already_in_farmos(find_asset_by_name, names)
        except Exception as e:  # noqa: BLE001
            log.warning("[commit_recovery] probe threw draft_id=%s: %s", draft_id, e)
            continue

        if not probe.get("ok"):
            # farmOS is still unreachable. Every remaining probe would fail the
            # same way, so stop rather than hammer a dead server.
            log.info("[commit_recovery] farmOS unreachable; %d draft(s) stay parked", len(rows))
            break

        if probe.get("exists"):
            log.warning(
                "[commit_recovery] draft_id=%s is parked but its blocks are ALREADY "
                "in farmOS; not requeued (needs reconciling, not rewriting)",
                draft_id,
            )
            continue

        result = await db.requeue_parked(pool, draft_id)
        if result.get("ok") and result.get("rowcount"):
            requeued += 1
            log.warning(
                "[commit_recovery] requeued transport-parked draft_id=%s (%d block(s) "
                "confirmed absent from farmOS)",
                draft_id, len(names),
            )

    return requeued
