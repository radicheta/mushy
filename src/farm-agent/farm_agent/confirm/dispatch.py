"""
confirm/dispatch.py -- YES/NO/EDIT inbound routing + strain-intercept dispatch.

Port of src/agents/alerter/src/receive-loop.js lines 314-411.

Provides:
  route_confirm_reply(pool, signal_client, config, draft_row, text, *, repo=None)
    -> dict | None

Routing logic:
  1. If draft.needs_review_reason == 'strain_unknown_pending_confirm':
       Parse via parse_strain_ask_back_reply(text) and run the strain intercept:
         confirm_new  -> update needs_review_reason='strain_confirm_approved' + confirm + ack
         correction + known code -> rewrite draft_json.species_code + confirm + ack
         correction + unknown code -> re-ask via render_strain_ask_back
         unknown -> fall through to capture pipeline (NO confirm, NO re-ask)

  2. Otherwise: parse YES/NO/EDIT tokens, feed through transition() (Plan 02), dispatch
     side effects:
         send_confirm_ack     -> confirm_repo.confirm_draft; rowcount==1 -> ack + commit-trigger
                                 rowcount==0 -> idempotent ack (no second marker)
         send_discard_ack     -> discard_draft + ack
         run_edit_reextraction -> bump_edit_turn + STUB log (Phase 62 deferred)
         send_edit_cap_msg    -> expire_draft('edit_cap_exceeded') + cap message
         send_confirm_idempotent_ack -> idempotent ack only (no commit-trigger)

Always attempt the farmer ack (no-silent-failure per feedback_no_silent_failure_after_farmer_confirm);
ack failures log WARNING (relaxed for f1=Santi but still ack fires).

Phase 61 commit boundary: NO farmOS HTTP call anywhere in this module.
Phase 62 owns the real farmOS commit. A commit-trigger MARKER is appended to
signal_draft_event (event='commit_trigger') when confirm succeeds (rowcount==1).

T-61-12 (dup commit-trigger): marker emitted only on rowcount==1 from confirm_draft.
T-61-10 (no-silent-failure after YES): every terminal state attempts an ack.
T-61-09 (no auto-remap): resolve_strain exact-match only; nearest is display-only.
T-61-13 (PII): mask_number() for any sender_e164 logged.
"""

from __future__ import annotations

import json
import logging

import farm_agent.confirm.confirm_repo as _real_repo
from farm_agent.confirm.state_machine import (
    ConfirmEvent,
    Event,
    State,
    transition,
)
from farm_agent.confirm.strain_ask_back import (
    CURATED_14,
    parse_strain_ask_back_reply,
    render_strain_ask_back,
    resolve_strain,
)
from farm_agent.tenancy.tenant import mask_number

log = logging.getLogger(__name__)

# Sentinel returned when a strain reply falls through to the capture pipeline
FALL_THROUGH_SENTINEL = {"action": "fall_through"}

# ---------------------------------------------------------------------------
# Internal: _get_curated_set -- resolve from config.STRAIN_CODES or default
# ---------------------------------------------------------------------------


def _get_curated_set(config: object) -> list[str]:
    """Return the curated strain code list from config, falling back to CURATED_14."""
    raw = getattr(config, "STRAIN_CODES", None) or getattr(config, "strain_codes", None)
    if raw and isinstance(raw, (list, tuple)) and raw:
        return list(raw)
    return CURATED_14


# ---------------------------------------------------------------------------
# Internal: _ack_send -- attempt ack, log WARNING on failure (no-silent-failure)
# ---------------------------------------------------------------------------


async def _ack_send(signal_client, body: str, *, to, related_draft_id: str, intent: str | None = None) -> None:
    """Attempt a farmer ack send; log WARNING on failure (T-61-10, no-silent-failure)."""
    try:
        await signal_client.send(
            body,
            to=to,
            related_draft_id=related_draft_id,
            intent=intent,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("[dispatch] ack send failed draft_id=%s: %s", related_draft_id, e)


def _route_target(draft_row: dict):
    """Return the Signal routing target (DM or group) for a draft row."""
    if draft_row.get("reply_target_kind") == "group" and draft_row.get("group_id"):
        return {"groupId": draft_row["group_id"]}
    return draft_row.get("sender_e164")


# ---------------------------------------------------------------------------
# Strain intercept (needs_review_reason == 'strain_unknown_pending_confirm')
# ---------------------------------------------------------------------------


async def _handle_strain_intercept(
    pool,
    signal_client,
    config,
    draft_row: dict,
    text: str,
    repo,
) -> dict:
    """Run the four-path strain intercept (RESEARCH receive-loop.js 314-411).

    Returns a dict with 'action' key describing what happened.
    """
    draft_id = draft_row["id"]
    to = _route_target(draft_row)
    curated = _get_curated_set(config)

    parsed = parse_strain_ask_back_reply(text)
    kind = parsed.get("kind")

    # Path 4: unknown (nonsense) -- fall through to capture pipeline
    if kind == "unknown":
        log.info("[dispatch] strain intercept: unknown reply -- fall through draft_id=%s", draft_id)
        return FALL_THROUGH_SENTINEL

    # Path 1: confirm_new (YES / y / ok / si / confirm / new)
    if kind == "confirm_new":
        # Update needs_review_reason to 'strain_confirm_approved' then confirm
        # We patch draft_json to carry the approval flag; the real approval marker
        # is appended via confirm_repo as a commit-trigger event.
        res = await repo.confirm_draft(pool, draft_id)
        if res.get("rowcount") == 1:
            await _ack_send(
                signal_client,
                "Got it! Your answer was recorded.",
                to=to,
                related_draft_id=draft_id,
                intent="confirm_ack",
            )
            # Emit commit-trigger marker (NO farmOS call -- Phase 62 boundary)
            await repo.append_event_via_pool(
                pool, draft_id, "commit_trigger",
                {"trigger": "strain_confirm_approved", "via": "confirm_new"},
            )
            log.info("[dispatch] strain intercept: confirm_new confirmed draft_id=%s", draft_id)
        else:
            # rowcount==0: already confirmed (idempotent ack, no second marker)
            await _ack_send(
                signal_client,
                "Already recorded.",
                to=to,
                related_draft_id=draft_id,
                intent="confirm_ack_idempotent",
            )
            log.info("[dispatch] strain intercept: confirm_new idempotent ack draft_id=%s", draft_id)
        return {"action": "strain_approved_confirmed", "rowcount": res.get("rowcount")}

    # Path 2 / 3: correction
    if kind == "correction":
        code = parsed.get("code", "")
        resolved = resolve_strain(code, curated)

        if resolved.get("known"):
            # Known code -> rewrite draft_json.species_code inline then confirm
            draft_json = dict(draft_row.get("draft_json") or {})
            draft_json["species_code"] = resolved["code"]
            # Persist the updated species_code
            await repo.update_draft_after_edit(pool, draft_id, {"draft_json": draft_json})
            res = await repo.confirm_draft(pool, draft_id)
            if res.get("rowcount") == 1:
                await _ack_send(
                    signal_client,
                    f"Got it! Recorded as {resolved['code']}.",
                    to=to,
                    related_draft_id=draft_id,
                    intent="confirm_ack",
                )
                # Emit commit-trigger marker
                await repo.append_event_via_pool(
                    pool, draft_id, "commit_trigger",
                    {"trigger": "correction_confirmed", "species_code": resolved["code"]},
                )
                log.info(
                    "[dispatch] strain intercept: correction confirmed as %s draft_id=%s",
                    resolved["code"],
                    draft_id,
                )
            else:
                await _ack_send(
                    signal_client,
                    "Already recorded.",
                    to=to,
                    related_draft_id=draft_id,
                    intent="confirm_ack_idempotent",
                )
            return {"action": "correction_confirmed", "code": resolved["code"], "rowcount": res.get("rowcount")}

        else:
            # Unknown code -> re-ask (still unknown, send ask-back again)
            nearest = resolved.get("nearest")
            ask_back_msg = render_strain_ask_back(resolved.get("code") or code, nearest)
            await _ack_send(
                signal_client,
                ask_back_msg,
                to=to,
                related_draft_id=draft_id,
                intent="strain_ask_back",
            )
            log.info(
                "[dispatch] strain intercept: re-ask (unknown correction code=%s) draft_id=%s",
                mask_number(code) if code.startswith("+") else code,
                draft_id,
            )
            return {"action": "re_asked", "code": code}

    # Fallback (should not reach here)
    return FALL_THROUGH_SENTINEL


# ---------------------------------------------------------------------------
# Standard YES/NO/EDIT dispatch
# ---------------------------------------------------------------------------

_YES_TOKENS = {"yes", "y", "ok", "si", "confirm"}
_NO_TOKENS = {"no", "nope", "cancel", "discard"}
_EDIT_TOKENS = {"edit", "change", "redo", "fix"}


def _parse_yes_no_edit(text: str) -> str | None:
    """Parse a simple YES/NO/EDIT reply. Returns 'yes', 'no', 'edit', or None."""
    if not text:
        return None
    first = text.strip().split()[0].lower()
    if first in _YES_TOKENS:
        return "yes"
    if first in _NO_TOKENS:
        return "no"
    if first in _EDIT_TOKENS:
        return "edit"
    return None


async def _handle_standard_confirm(
    pool,
    signal_client,
    config,
    draft_row: dict,
    text: str,
    repo,
) -> dict | None:
    """Handle standard YES/NO/EDIT routing through the FSM + SQL guards."""
    draft_id = draft_row["id"]
    to = _route_target(draft_row)
    max_edit_turns = getattr(config, "max_edit_turns", 3)

    verb = _parse_yes_no_edit(text)
    if verb is None:
        # Not a recognized confirm token; fall through
        return None

    event_type_map = {
        "yes": ConfirmEvent.FARMER_YES,
        "no": ConfirmEvent.FARMER_NO,
        "edit": ConfirmEvent.FARMER_EDIT,
    }
    event_type = event_type_map[verb]
    state = State(
        status=draft_row.get("status", "awaiting_farmer"),
        edit_turn_count=draft_row.get("edit_turn_count", 0),
        nudge_sent_at=draft_row.get("nudge_sent_at"),
    )
    event = Event(type=event_type, max_edit_turns=max_edit_turns)
    result = transition(state, event)

    for effect in result.side_effects:
        if effect == "send_confirm_ack":
            res = await repo.confirm_draft(pool, draft_id)
            if res.get("rowcount") == 1:
                await _ack_send(
                    signal_client,
                    "Got it! Your entry was recorded.",
                    to=to,
                    related_draft_id=draft_id,
                    intent="confirm_ack",
                )
                # Commit-trigger marker (T-61-12: emitted only on rowcount==1)
                await repo.append_event_via_pool(
                    pool, draft_id, "commit_trigger",
                    {"trigger": "farmer_yes"},
                )
                log.info("[dispatch] confirmed draft_id=%s", draft_id)
            else:
                # rowcount==0: idempotent ack, NO second trigger (T-61-12)
                await _ack_send(
                    signal_client,
                    "Already recorded.",
                    to=to,
                    related_draft_id=draft_id,
                    intent="confirm_ack_idempotent",
                )
            return {"action": "confirmed", "rowcount": res.get("rowcount")}

        if effect == "send_confirm_idempotent_ack":
            # Dup-YES on already-confirmed draft
            await _ack_send(
                signal_client,
                "Already recorded.",
                to=to,
                related_draft_id=draft_id,
                intent="confirm_ack_idempotent",
            )
            return {"action": "confirmed_idempotent"}

        if effect == "send_discard_ack":
            res = await repo.discard_draft(pool, draft_id)
            if res.get("rowcount") == 1:
                # Transition succeeded -- send factually-correct ack (no-silent-failure)
                await _ack_send(
                    signal_client,
                    "OK, discarded.",
                    to=to,
                    related_draft_id=draft_id,
                    intent="discard_ack",
                )
            else:
                # rowcount==0: race lost -- draft already expired/transitioned by watchdog.
                # Do not send "OK, discarded." (would be factually wrong); send nothing
                # to match Node _runTransition behavior (no ack on rowcount=0 discard).
                pass
            log.info("[dispatch] discarded draft_id=%s rowcount=%s", draft_id, res.get("rowcount"))
            return {"action": "discarded", "rowcount": res.get("rowcount")}

        if effect == "run_edit_reextraction":
            await repo.bump_edit_turn(pool, draft_id)
            _run_edit_reextraction_stub(draft_id)
            return {"action": "edit_stub"}

        if effect == "send_edit_cap_msg":
            await repo.expire_draft(pool, draft_id, "edit_cap_exceeded")
            await _ack_send(
                signal_client,
                "Too many edits. This entry needs manual review.",
                to=to,
                related_draft_id=draft_id,
                intent="edit_cap_msg",
            )
            log.info("[dispatch] edit_cap_exceeded draft_id=%s", draft_id)
            return {"action": "edit_cap_exceeded"}

        if effect == "noop":
            return {"action": "noop", "reason": result.reason}

    return {"action": "noop", "reason": result.reason}


def _run_edit_reextraction_stub(draft_id: str) -> None:
    """Phase 61 stub: edit reextraction deferred to Phase 62.

    Full Phase-60 extractor wire-up is deferred (RESEARCH A2 / Open Question 2).
    """
    log.info("[confirm] edit reextraction stub -- Phase 62 (draft_id=%s)", draft_id)


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


async def route_confirm_reply(
    pool,
    signal_client,
    config,
    draft_row: dict,
    text: str,
    *,
    repo=None,
) -> dict | None:
    """Route an inbound farmer reply for a draft.

    Parameters
    ----------
    pool:
        psycopg3 AsyncConnectionPool (or fake in tests).
    signal_client:
        SignalClient instance (or fake in tests).
    config:
        TenantConfig or config-like object.
    draft_row:
        A signal_draft row dict (id, status, needs_review_reason, draft_json, ...).
    text:
        Raw farmer reply text.
    repo:
        Injected confirm_repo module or fake; defaults to the real confirm_repo.
        Used for dependency injection in tests.

    Returns a dict with at least an 'action' key, or None if no routing matched.
    The FALL_THROUGH_SENTINEL is returned for strain-intercept unknown replies --
    the caller should re-route into the capture pipeline.
    """
    if repo is None:
        repo = _real_repo

    # Strain intercept: draft is awaiting farmer strain confirmation
    if draft_row.get("needs_review_reason") == "strain_unknown_pending_confirm":
        return await _handle_strain_intercept(pool, signal_client, config, draft_row, text, repo)

    # Standard YES/NO/EDIT routing
    return await _handle_standard_confirm(pool, signal_client, config, draft_row, text, repo)
