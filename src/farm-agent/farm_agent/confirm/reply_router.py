"""
confirm/reply_router.py -- inbound confirm-reply routing (the second dead seam, MUSHY-76).

Port of src/agents/alerter/src/receive-loop.js lines 226-414 (the routing layer
only -- the YES/NO/EDIT handling and the strain intercept live in
confirm/dispatch.py's route_confirm_reply / _handle_strain_intercept and are
reused here, not duplicated).

Before this module existed, route_confirm_reply had no caller anywhere in
farm_agent: the daemon created a draft, prompted the farmer, and then ignored
every YES/NO/EDIT reply -- every draft expired unacked. This module is the
missing routing layer that makes that logic reachable from the receive loop.

Provides:
  create_confirm_reply_router(...) -> {"try_route": async (envelope) -> bool}

try_route(envelope) returns True when it consumed the message (the caller must
NOT then hand it to the capture pipeline) and False on fall-through (NOOP /
no-text / no-active-draft), so the caller runs the normal capture pipeline.

Ordered behavior (Node line ranges):
  1. Guard (js:228): no text, no routing.
  2. record_reply (js:229-239): every CONSUMED path persists the raw inbound
     via capture_pipeline["record_reply_capture"] before returning True. This
     is the 2026-05-24 Node fix -- every confirm-branch path used to end in
     `continue`, skipping the SLOW PATH capture write, so follow-up replies
     never landed in signal_capture and vanished from the farmer's paper
     trail. Best-effort, never-throw. The NOOP fall-through does NOT call
     this -- capture.handle() persists it once, normally (no double-persist).
  3. Quote-first routing (js:240-276): resolve the quoted draft via
     find_draft_by_quoted_msg_ts. Sender-equality spoof guard (js:263-264):
     if the quoted draft belongs to a different farmer, do NOT route (log and
     fall through) -- a security control, not a nicety. awaiting_farmer /
     commit_failed -> route to this draft. Terminal statuses -> polite
     "already closed" ack, record, consume.
  4. Fallback to find_active_drafts_for_sender (js:278-312) when the quote did
     not pin a draft. >1 active draft with no quote resolution -> numbered
     disambiguation ask-back, record, consume. Otherwise take the first.
  5. Delegate to confirm.dispatch.route_confirm_reply for the strain
     intercept and YES/NO/EDIT handling.
  6. NOOP / strain-unknown fall through (js:412): return False.

T-50-04-01: sender spoof guard on quote resolution.
2026-05-23 hotfix: staleness filter lives in confirm_repo.find_active_drafts_for_sender.
T-61-13 (PII): mask_number() on any sender_e164 logged.
"""

from __future__ import annotations

import logging
import math
import re

import farm_agent.confirm.confirm_repo as _real_repo
from farm_agent.confirm.dispatch import FALL_THROUGH_SENTINEL, route_confirm_reply
from farm_agent.confirm.dispatch import _parse_yes_no_edit
from farm_agent.confirm.preview import (
    build_nothing_open,
    build_numbered_ask_back,
    build_quote_closed,
)
from farm_agent.signal_io import router as _router
from farm_agent.tenancy.tenant import mask_number

log = logging.getLogger(__name__)

_TERMINAL_STATUSES = {"committed", "discarded", "expired", "needs_review", "confirmed"}
_ROUTABLE_STATUSES = {"awaiting_farmer", "commit_failed"}


def _coerce_quote_ts(raw) -> int | None:
    """Mirror Node's `Number.isFinite(Number(x)) ? Number(x) : null`."""
    if raw is None:
        return None
    try:
        n = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(n):
        return None
    return int(n)


# MUSHY-84: a control word carries no farm data, so it must never be extracted.
# The test is deliberately stricter than _parse_yes_no_edit, which matches on the
# FIRST TOKEN only: "fixed the fan in FC1" starts with an _EDIT_TOKENS word and is
# a real log entry. Only a message that is nothing but a control word, or one
# explicitly prefixed "EDIT:", is treated as confirm-thread traffic.
_EDIT_PREFIX_RE = re.compile(r"^edit\s*:", re.IGNORECASE)


def _is_bare_control_word(text: str) -> bool:
    trimmed = (text or "").strip()
    if not trimmed:
        return False
    if _EDIT_PREFIX_RE.match(trimmed):
        return True
    if len(trimmed.split()) > 1:
        return False
    return _parse_yes_no_edit(trimmed) is not None


def create_confirm_reply_router(
    *,
    pool,
    signal_client,
    config,
    capture_pipeline,
    confirm_repo=None,
    extraction_db=None,
    extractor=None,
    outbound_dispatcher=None,  # D-3 (MUSHY-76 task 8b): forwarded to route_confirm_reply for
                                # the starting-SEQ intercept only; every other path still sends
                                # direct via signal_client (dispatch.py's _ack_send pattern).
    log: logging.Logger | None = None,
) -> dict:
    """Factory returning {"try_route": async (envelope: dict) -> bool}."""
    repo = confirm_repo if confirm_repo is not None else _real_repo
    _log = log or globals()["log"]

    async def _record_reply(envelope: dict) -> None:
        """Best-effort, never-throw persist of the raw inbound (2026-05-24 fix)."""
        try:
            recorder = capture_pipeline.get("record_reply_capture") if capture_pipeline else None
            if recorder is None:
                return
            await recorder(envelope)
        except Exception as e:  # noqa: BLE001
            _log.warning("[confirm] reply persist error: %s", e)

    async def _send_quote_closed(draft_row: dict) -> None:
        target = draft_row.get("sender_e164")
        if not target:
            _log.warning("[confirm] send_quote_closed: no_target draft_id=%s", draft_row.get("id"))
            return
        try:
            await signal_client.send(
                build_quote_closed(draft_row),
                to=target,
                related_draft_id=draft_row.get("id"),
                intent="quote_closed",
            )
        except Exception as e:  # noqa: BLE001
            _log.warning("[confirm] quote_closed send failed: %s", e)

    async def _send_ask_back(active_drafts: list[dict], sender: str | None) -> None:
        if not sender:
            _log.warning("[confirm] send_ask_back: no_target")
            return
        if len(active_drafts) < 2:
            _log.warning("[confirm] send_ask_back: <2 drafts (%d); skipping", len(active_drafts))
            return
        try:
            await signal_client.send(
                build_numbered_ask_back(active_drafts),
                to=sender,
                intent="ask_back",
            )
        except Exception as e:  # noqa: BLE001
            _log.warning("[confirm] ask_back send failed: %s", e)

    async def try_route(envelope: dict) -> bool:
        classified = _router.classify_envelope(envelope or {})
        source = classified.get("source")
        dm = classified.get("dm") or {}
        text: str | None = dm.get("message") or None

        # 1. Guard (js:228): no text, no reply to route.
        if not text:
            return False

        # 3. Quote-first routing (js:240-276).
        quote = dm.get("quote") or {}
        quote_msg_ts_raw = quote.get("id") if quote.get("id") is not None else quote.get("timestamp")
        quote_msg_ts = _coerce_quote_ts(quote_msg_ts_raw)

        draft_row: dict | None = None
        quote_resolved = False
        if quote_msg_ts is not None:
            try:
                qr = await repo.find_draft_by_quoted_msg_ts(pool, quote_msg_ts)
            except Exception as e:  # noqa: BLE001
                _log.warning("[confirm] quote-resolve failed: %s", e)
                qr = None
            if qr:
                # T-50-04-01: sender-equality spoof guard. If the quoted draft
                # belongs to a different farmer, do NOT route -- treat as orphan.
                if qr.get("sender_e164") and qr.get("sender_e164") != source:
                    _log.warning("[confirm] quote spoof guard: draft sender mismatch (drop)")
                elif qr.get("status") in _ROUTABLE_STATUSES:
                    draft_row = qr
                    quote_resolved = True
                elif qr.get("status") in _TERMINAL_STATUSES:
                    await _send_quote_closed(qr)
                    await _record_reply(envelope)
                    return True
                # Other transitional statuses fall through to the active-draft path.

        # 4. Fallback to active-draft lookup (js:278-312).
        active_drafts: list[dict] = []
        if draft_row is None:
            try:
                active_drafts = await repo.find_active_drafts_for_sender(pool, source) or []
            except Exception as e:  # noqa: BLE001
                _log.warning("[confirm] active-drafts lookup failed sender=%s: %s", mask_number(source or ""), e)
                active_drafts = []
            if len(active_drafts) > 1 and not quote_resolved:
                await _send_ask_back(active_drafts, source)
                await _record_reply(envelope)
                return True
            draft_row = active_drafts[0] if active_drafts else None

        if draft_row is None:
            # MUSHY-84: nothing live to route to. A control word still must not
            # reach the extractor -- on Node a bare NO became a phantom draft
            # with asset_ref <UNKNOWN> that then asked the farmer a question
            # about itself, while the real draft stayed open and the farmer was
            # told "Discarded". Answer honestly instead. Free text falls through
            # to capture as normal, because a farmer logging new work must never
            # be answered with "that conversation is closed".
            if _is_bare_control_word(text):
                closed_row = None
                try:
                    closed_row = await repo.find_recent_terminal_draft_for_sender(pool, source)
                except Exception as e:  # noqa: BLE001
                    _log.warning("[confirm] recent-terminal lookup failed: %s", e)
                body = build_quote_closed(closed_row) if closed_row else build_nothing_open()
                _log.info(
                    "[confirm] control word with no live draft: answered closed (draft=%s)",
                    (closed_row or {}).get("id"),
                )
                try:
                    await signal_client.send(
                        body,
                        to=source,
                        related_draft_id=(closed_row or {}).get("id"),
                        intent="quote_closed",
                    )
                except Exception as e:  # noqa: BLE001
                    _log.warning("[confirm] closed-conversation reply failed: %s", e)
                await _record_reply(envelope)
                return True

            # No quote-pinned draft and no active draft -- nothing to route.
            return False

        # 5. Delegate to route_confirm_reply for the strain intercept + YES/NO/EDIT.
        result = await route_confirm_reply(
            pool, signal_client, config, draft_row, text,
            repo=repo, extractor=extractor, extraction_db=extraction_db,
            outbound_dispatcher=outbound_dispatcher,
        )

        # 6. NOOP / strain-unknown falls through -- do NOT record, let capture handle it.
        if result is None or result == FALL_THROUGH_SENTINEL:
            return False

        await _record_reply(envelope)
        return True

    return {"try_route": try_route}
