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
         run_edit_reextraction -> real EDIT re-extraction (confirm/edit_handler.py):
                                 bumps edit_turn_count, re-extracts with the farmer's
                                 correction, updates the draft in place, resends preview
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
import re

import farm_agent.confirm.confirm_repo as _real_repo
import farm_agent.extraction.extraction_db as _real_extraction_db
from farm_agent.confirm.edit_handler import create_edit_handler
from farm_agent.confirm.preview import (
    build_confirm_ack,
    build_discard_ack,
    build_edit_cap_msg,
    build_idempotent_ack,
)
from farm_agent.confirm.state_machine import (
    ConfirmEvent,
    Event,
    State,
    transition,
)
from farm_agent.confirm.strain_ask_back import (
    get_curated_set as _get_curated_set,
    parse_strain_ask_back_reply,
    render_strain_ask_back,
    resolve_strain,
)
from farm_agent.extraction.starting_seq import handle_starting_seq_reply
from farm_agent.tenancy.tenant import mask_number

log = logging.getLogger(__name__)

# Sentinel returned when a strain reply falls through to the capture pipeline
FALL_THROUGH_SENTINEL = {"action": "fall_through"}

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
                build_confirm_ack(draft_id),
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
                build_idempotent_ack(),
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
                # Node dispatches send_confirm_ack for this path too
                # (receive-loop.js:354, same as confirm_new at :329) -> buildConfirmAck.
                await _ack_send(
                    signal_client,
                    build_confirm_ack(draft_id),
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
                    build_idempotent_ack(),
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


# MUSHY-92: the control verb is the leading run of letters, NOT the first
# whitespace-delimited token. Punctuation the farmer attaches to it ("edit:",
# the form the bot's own copy teaches, or a plain "yes.") is a separator. The
# lookahead keeps "fixed the fan" and "yesterday..." out -- a longer word that
# merely starts with a verb is a log entry, not a control word.
_LEADING_VERB_RE = re.compile(r"^([A-Za-z]+)(?=$|[\s:,.;!?])")
_VERB_SEPARATOR_RE = re.compile(r"^[\s:,.;!?]+")


def _split_leading_verb(text: str) -> tuple[str, str] | None:
    """Split a leading control verb from its remainder.

    Returns (verb lowercased, remainder with ORIGINAL casing) or None when the
    message does not open with a bare word.
    """
    trimmed = (text or "").strip()
    m = _LEADING_VERB_RE.match(trimmed)
    if m is None:
        return None
    remainder = _VERB_SEPARATOR_RE.sub("", trimmed[m.end() :]).strip()
    return m.group(1).lower(), remainder


def _parse_yes_no_edit(text: str) -> str | None:
    """Parse a simple YES/NO/EDIT reply. Returns 'yes', 'no', 'edit', or None."""
    if not text:
        return None
    split = _split_leading_verb(text)
    if split is None:
        return None
    first = split[0]
    if first in _YES_TOKENS:
        return "yes"
    if first in _NO_TOKENS:
        return "no"
    if first in _EDIT_TOKENS:
        return "edit"
    return None


def _extract_edit_text(text: str) -> str:
    """Correction text handed to the extractor. Port of confirm/parser.js:31-38.

    Node recognizes only the literal 'edit' token for stripping (not our other
    dispatch-level synonyms change/redo/fix, which are Python-only additions
    to _EDIT_TOKENS and fall through to the implicit-edit case below):

      - Leading 'edit' verb (case-insensitive): the correction is everything
        after the verb and any punctuation/whitespace separating it (MUSHY-92:
        'edit:' and 'edit: ' count), trimmed, with the remainder's ORIGINAL
        casing preserved.
      - 'EDIT' with nothing after it: the correction is '' (does NOT fall
        through to the whole body).
      - Anything else (implicit edit, e.g. 'change it to 750g' or a bare
        correction with no verb at all): the full trimmed body is the
        correction.

    A leading command verb is noise in the farmer_correction slot fed to the
    model as the farmer's own words -- production does not send it, so we
    must not either.
    """
    trimmed = (text or "").strip()
    if not trimmed:
        return ""
    split = _split_leading_verb(trimmed)
    if split is not None and split[0] == "edit":
        return split[1]
    return trimmed


async def _handle_standard_confirm(
    pool,
    signal_client,
    config,
    draft_row: dict,
    text: str,
    repo,
    *,
    extractor=None,
    extraction_db=None,
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
            if not res.get("ok"):
                # MUSHY-40: confirm_draft NEVER raises (T-61-05) -- on a DB error it
                # returns {"ok": False, "reason": ...} with NO "rowcount" key. Branching
                # on rowcount alone sent "Already recorded." here, telling the farmer
                # their entry was saved when nothing was written. The draft is still
                # awaiting_farmer, so retrying YES genuinely works.
                await _ack_send(
                    signal_client,
                    "Couldn't save that just now, the database didn't respond. "
                    "Nothing is lost. Reply YES again in a minute and it will go through.",
                    to=to,
                    related_draft_id=draft_id,
                    intent="confirm_failed_ack",
                )
                log.warning(
                    "[dispatch] confirm_draft failed draft_id=%s reason=%s",
                    draft_id, res.get("reason"),
                )
                return {"action": "confirm_failed", "ok": False, "reason": res.get("reason")}
            if res.get("rowcount") == 1:
                await _ack_send(
                    signal_client,
                    build_confirm_ack(draft_id),
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
                    build_idempotent_ack(),
                    to=to,
                    related_draft_id=draft_id,
                    intent="confirm_ack_idempotent",
                )
            return {"action": "confirmed", "rowcount": res.get("rowcount")}

        if effect == "send_confirm_idempotent_ack":
            # Dup-YES on already-confirmed draft
            await _ack_send(
                signal_client,
                build_idempotent_ack(),
                to=to,
                related_draft_id=draft_id,
                intent="confirm_ack_idempotent",
            )
            return {"action": "confirmed_idempotent"}

        if effect == "send_discard_ack":
            res = await repo.discard_draft(pool, draft_id)
            if not res.get("ok"):
                # MUSHY-40: same ok-vs-rowcount conflation as the confirm arm above.
                # A DB failure fell into the rowcount==0 arm, which deliberately sends
                # NOTHING -- so the farmer said NO, heard silence, and then got a
                # confusing expiry message 30 min later. rowcount==0 means "someone
                # else already transitioned it" (benign); ok=False means "the write
                # failed" (must be surfaced).
                await _ack_send(
                    signal_client,
                    "Couldn't discard that just now, the database didn't respond. "
                    "Reply NO again in a minute.",
                    to=to,
                    related_draft_id=draft_id,
                    intent="discard_failed_ack",
                )
                log.warning(
                    "[dispatch] discard_draft failed draft_id=%s reason=%s",
                    draft_id, res.get("reason"),
                )
                return {"action": "discard_failed", "ok": False, "reason": res.get("reason")}
            if res.get("rowcount") == 1:
                # Transition succeeded -- send factually-correct ack (no-silent-failure)
                await _ack_send(
                    signal_client,
                    build_discard_ack(),
                    to=to,
                    related_draft_id=draft_id,
                    intent="discard_ack",
                )
            else:
                # rowcount==0: race lost -- draft already expired/transitioned by watchdog.
                # Do not send a discard ack (would be factually wrong); send nothing
                # to match Node _runTransition behavior (no ack on rowcount=0 discard).
                pass
            log.info("[dispatch] discarded draft_id=%s rowcount=%s", draft_id, res.get("rowcount"))
            return {"action": "discarded", "rowcount": res.get("rowcount")}

        if effect == "run_edit_reextraction":
            # Real EDIT re-extraction (replaces the Phase 61 stub, which logged
            # a line and dropped the farmer's correction). bump_edit_turn is
            # owned by the handler now, not called separately here.
            handler = create_edit_handler(
                pool=pool,
                extractor=extractor,
                confirm_repo=repo,
                extraction_db=extraction_db or _real_extraction_db,
                config=config,
                log=log,
            )
            edit_res = await handler["handle_edit"](draft_row, _extract_edit_text(text))
            if edit_res.get("ok") and edit_res.get("side_effect") == "send_preview_resend":
                await _ack_send(
                    signal_client,
                    edit_res.get("new_preview") or "",
                    to=to,
                    related_draft_id=draft_id,
                    intent="edit_preview_resend",
                )
                log.info("[dispatch] edit re-extraction ok draft_id=%s", draft_id)
                return {"action": "edited", "ok": True}
            if edit_res.get("ok") and edit_res.get("side_effect") == "send_edit_cap_msg":
                await repo.expire_draft(pool, draft_id, "edit_cap_exceeded")
                await _ack_send(
                    signal_client,
                    build_edit_cap_msg(max_edit_turns),
                    to=to,
                    related_draft_id=draft_id,
                    intent="edit_cap_msg",
                )
                log.info("[dispatch] edit_cap_exceeded (post-handler) draft_id=%s", draft_id)
                return {"action": "edit_cap_exceeded"}
            if edit_res.get("ok"):
                # side_effect == "noop" -- draft no longer active (concurrent confirm/expire)
                return {"action": "edit_noop", "reason": edit_res.get("reason")}
            log.warning(
                "[dispatch] edit re-extraction failed draft_id=%s reason=%s",
                draft_id, edit_res.get("reason"),
            )
            return {"action": "edit_failed", "ok": False, "reason": edit_res.get("reason")}

        if effect == "send_edit_cap_msg":
            await repo.expire_draft(pool, draft_id, "edit_cap_exceeded")
            await _ack_send(
                signal_client,
                build_edit_cap_msg(max_edit_turns),
                to=to,
                related_draft_id=draft_id,
                intent="edit_cap_msg",
            )
            log.info("[dispatch] edit_cap_exceeded draft_id=%s", draft_id)
            return {"action": "edit_cap_exceeded"}

        if effect == "noop":
            return {"action": "noop", "reason": result.reason}

    return {"action": "noop", "reason": result.reason}


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
    extractor=None,
    extraction_db=None,
    outbound_dispatcher=None,
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
    extractor:
        {"extract": async fn} dict consumed by the EDIT re-extraction handler.
        Required only when a farmer reply triggers the run_edit_reextraction
        side effect; other reply kinds never touch it.
    extraction_db:
        Injected farm_agent.extraction.extraction_db module or fake; defaults
        to the real module. Used by the EDIT re-extraction handler to persist
        the corrected draft, and (D-3) by the starting-SEQ reply handler to
        re-fetch and update the draft.
    outbound_dispatcher:
        {"dispatch": async (effect, draft_row) -> dict} dict, dict-subscript
        shape only (matches pipeline.py / batch_mode.py / starting_seq.py).
        Required for the D-3 starting-SEQ intercept below to actually notify
        the farmer; no module-level default exists (there is no bare "real"
        outbound dispatcher -- it is built from a live signal_client).

    Returns a dict with at least an 'action' key, or None if no routing matched.
    The FALL_THROUGH_SENTINEL is returned for strain-intercept unknown replies --
    the caller should re-route into the capture pipeline.
    """
    if repo is None:
        repo = _real_repo

    # D-3: a draft awaiting a starting-SEQ answer is not awaiting a YES/NO/EDIT
    # confirmation, and a bare "4" must not be parsed as one. This MUST run
    # before the strain intercept and _parse_yes_no_edit -- a draft can only
    # be in one of these states, but the order still needs to be deterministic.
    # Task 7 ported handle_starting_seq_reply with no caller (Node never routed
    # to it either); this closes that gap so the farmer's answer actually lands.
    draft_json = draft_row.get("draft_json") or {}
    if (
        draft_json.get("type") == "seeding_session"
        and draft_json.get("needs_input") == "starting_seq"
    ):
        capture_ctx = {
            "sender_name": draft_row.get("sender_name"),
            "farmos_person": draft_row.get("farmos_person"),
            "reply_target_kind": draft_row.get("reply_target_kind"),
            "group_id": draft_row.get("group_id"),
        }
        return await handle_starting_seq_reply(
            draft_id=draft_row["id"],
            reply_text=text,
            capture_ctx=capture_ctx,
            pool=pool,
            extraction_db=extraction_db if extraction_db is not None else _real_extraction_db,
            outbound_dispatcher=outbound_dispatcher,
            log=log,
        )

    # Strain intercept: draft is awaiting farmer strain confirmation
    if draft_row.get("needs_review_reason") == "strain_unknown_pending_confirm":
        return await _handle_strain_intercept(pool, signal_client, config, draft_row, text, repo)

    # Standard YES/NO/EDIT routing
    return await _handle_standard_confirm(
        pool, signal_client, config, draft_row, text, repo,
        extractor=extractor, extraction_db=extraction_db,
    )
