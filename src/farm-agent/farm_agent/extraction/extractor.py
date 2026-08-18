"""
extraction/extractor.py -- Never-throws Sonnet extractor factory.

Port of src/agents/alerter/src/extraction/extractor.js (createExtractor).

Provides:
  create_extractor(client, model, max_tokens, on_llm_call, log) -> {"extract": extract}

Design decisions (from 60-CONTEXT.md):
  Area-1: Forced tool submit_extraction -- prevents free-form prose responses.
  Area-3: Fail-open on any error -- extractor never throws; every failure path returns
          {ok:False, reason} so the pipeline can produce a needs_review draft.
  Pitfall-9: with_options(timeout=_timeout_s) -- timeout is a transport option, NOT a
          body param (same live-fire bug Node hit; body kwarg -> 400).
  Pitfall-8: tu_fewshot_6 closer -- the first user-turn block MUST be a tool_result
          closing the last few-shot assistant tool_use. Anthropic 400s without it.
  Pitfall-1: block.id (NOT block.name) is used in tool_result retry turn's tool_use_id.
  Pitfall-5: second ValidationError must NOT propagate; catch and return {ok:False,...}.

Security:
  T-44-04-01: farmer text/transcript/image go into messages[] ONLY -- never concatenated
              into CACHEABLE_SYSTEM_BLOCKS (system prompt stays static).
  T-60-03-01: extra='forbid' on every nested model; invalid tool_use.input triggers retry
              then {ok:False}; never trusted raw.
  T-56-06-01: injected client owns the api_key; extractor never references or logs it.
  T-59-02-01: WARNING logs contain only exception/reason strings -- never farmer content.
  T-60-03-02: per-request timeout via client.with_options(timeout=...).
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import decimal
import inspect
import json
import logging
import uuid

import anthropic
from pydantic import ValidationError

from farm_agent.extraction.multimodal import build_content_blocks
from farm_agent.extraction.prompts import CACHEABLE_SYSTEM_BLOCKS, cacheable_few_shot
from farm_agent.extraction.schemas.submission import SUBMISSION_JSON_SCHEMA, Submission

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

TOOL_NAME = "submit_extraction"
TOOL_DESCRIPTION = (
    "Submit the structured extraction result for this farm operation capture. "
    "Call this tool exactly once with the complete structured draft."
)

# Timeout mirrors the Node extractor (60 000ms) -- longer than the gate (2 000ms)
# because multi-event seeding sessions can produce large responses.
_DEFAULT_TIMEOUT_MS = 60_000


# ---------------------------------------------------------------------------
# JSON serialization of raw DB rows (MUSHY-76)
# ---------------------------------------------------------------------------


def json_default(o):
    """`default=` hook for json.dumps over raw psycopg rows.

    The in-flight draft handed to build_initial_user_content() is a RAW
    signal_draft row (extraction_db.get_in_flight_for_sender zips
    cursor.description over the tuple), so created_at / updated_at /
    confirmed_at / expired_at / nudge_sent_at arrive as python datetimes and
    plain json.dumps raises TypeError before the model is ever called.

    Node is the shape source of truth: `pg` hands JSON.stringify JS Dates
    (-> ISO-8601 strings), numerics and uuids as strings. This mirrors that:

      datetime / date / time -> .isoformat()   (matches JS Date -> ISO-8601)
      Decimal                -> str            (matches pg numeric -> JS string)
      UUID                   -> str            (matches pg uuid  -> JS string)

    DELIBERATELY NOT HANDLED -- these raise TypeError rather than being coerced:
      bytes / memoryview (bytea), timedelta (interval), sets, model objects.
    A `default=str` catch-all would silently turn structured values into
    garbage prose that the model then reasons over as if it were data. There is
    no bytea or interval column on signal_draft, so a raise here means a real
    schema change nobody accounted for -- fail loudly (the extractor's outer
    fail-open still turns it into {ok:False}) rather than quietly mislead.
    """
    if isinstance(o, (_dt.datetime, _dt.date, _dt.time)):
        return o.isoformat()
    if isinstance(o, decimal.Decimal):
        return str(o)
    if isinstance(o, uuid.UUID):
        return str(o)
    raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")


def _dumps(obj) -> str:
    """json.dumps with the row-aware default hook. Use at every dumps site here."""
    return json.dumps(obj, default=json_default)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def build_tool_spec() -> dict:
    """Build the tool spec dict for the Anthropic messages API.

    Passes SUBMISSION_JSON_SCHEMA DIRECTLY as input_schema.  Pydantic v2 already
    emits type:object at the root -- no inlineTopLevelRef wrapper needed (unlike
    the Node zod-to-json-schema approach).
    """
    return {
        "name": TOOL_NAME,
        "description": TOOL_DESCRIPTION,
        "input_schema": SUBMISSION_JSON_SCHEMA,
    }


def find_tool_use_block(response) -> object | None:
    """Return the first submit_extraction tool_use block, or None.

    Pitfall 7: block.type / block.name / block.id / block.input are ATTRIBUTE
    access on pydantic response objects, NOT dict keys.
    """
    if not response or not hasattr(response, "content"):
        return None
    for block in response.content:
        if block.type == "tool_use" and block.name == TOOL_NAME:
            return block
    return None


def build_initial_user_content(
    captures: list[dict],
    in_flight_draft=None,
    corpus_context=None,
    farmer_correction: str | None = None,
) -> list[dict]:
    """Build the user message content list for the extraction call.

    Pitfall 8: The FIRST block MUST be a tool_result closing tu_fewshot_6.
    Anthropic 400s when any tool_use in an assistant turn lacks a following
    tool_result in the next user turn.

    Security T-44-04-01: farmer text/transcript/image enter via messages[] only.
    Never concatenated into CACHEABLE_SYSTEM_BLOCKS.
    """
    blocks: list[dict] = []

    # Mandatory: close the last few-shot assistant tool_use (tu_fewshot_6)
    blocks.append({
        "type": "tool_result",
        "tool_use_id": "tu_fewshot_6",
        "content": [{"type": "text", "text": "accepted"}],
    })

    # Optional corpus context block (isinstance guard mirrors Node typeof === 'object')
    if corpus_context is not None and isinstance(corpus_context, dict):
        blocks.append({
            "type": "text",
            "text": f"corpus_context: {_dumps(corpus_context)}",
        })

    # In-flight draft block (always present; "none" when absent)
    blocks.append({
        "type": "text",
        "text": f"In-flight draft: {_dumps(in_flight_draft) if in_flight_draft is not None else 'none'}",
    })

    # Optional farmer correction block
    if farmer_correction and farmer_correction.strip():
        blocks.append({
            "type": "text",
            "text": f"Farmer correction: {farmer_correction.strip()}",
        })

    # Per-capture content blocks (text, transcript, image blocks)
    for cap in captures:
        for block in build_content_blocks(
            text=cap.get("text"),
            transcript=cap.get("transcript"),
            images=cap.get("images") or [],
        ):
            blocks.append(block)

    return blocks


def sum_usage(usages: list) -> dict | None:
    """Sum token counts across multiple usage objects (initial + retry calls).

    Mirrors Node sumUsage: returns None when ALL usages in the list are null
    (tracks an `any_data` flag). Returns a zeroed dict only when at least one
    non-null usage was present -- so downstream `result["usage"] is None` checks
    correctly detect "no usage data recorded" on failure/degraded paths.

    Uses attribute access with defaults of 0 for missing fields.
    """
    total: dict[str, int] = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }
    any_data = False
    for u in usages:
        if u is None:
            continue
        any_data = True
        for key in total:
            total[key] += getattr(u, key, 0)
    return total if any_data else None


def pack_result(submission: Submission, usage: dict) -> dict:
    """Expand a validated Submission into the canonical extractor result dict.

    Mirrors Node's packResult (extractor.js lines 250-270).

    Node's packResult returns the zod-validated tool input as PLAIN JS objects, and
    every consumer in this port (pipeline, batch_mode, starting_seq, preview_builder,
    state_machine, seq_helper) was written against that shape -- they do dict access
    (draft.get("type"), draft["groups"]).  So the pydantic models MUST be dumped to
    plain python data here, at the boundary, not handled downstream.

    mode="json" so nested models, enums and any date-like fields come out as
    JSON-safe primitives: draft_json is a jsonb column written via
    psycopg.types.json.Jsonb(...), which cannot adapt a BaseModel either.
    """
    dumped = submission.model_dump(mode="json")
    drafts: list[dict] = list(dumped.get("drafts") or [])
    first = drafts[0] if drafts else None
    return {
        "ok": True,
        "drafts": drafts,
        "continuity_decision": dumped.get("continuity"),
        "continuity_reason": dumped.get("continuity_reason"),
        "draft": first.get("draft") if first is not None else None,
        "per_field_confidence": first.get("per_field_confidence") if first is not None else None,
        "capture_kind": dumped.get("capture_kind"),
        "usage": usage,
    }


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_extractor(
    client: anthropic.AsyncAnthropic,
    model: str = "claude-sonnet-4-6",
    max_tokens: int = 16384,
    on_llm_call=None,
    log: logging.Logger | None = None,
) -> dict:
    """Factory returning {"extract": extract}. Port of createExtractor().

    Holds the injected AsyncAnthropic in the closure. Do NOT create a second
    client per call; share the single daemon-lifetime singleton.

    Args:
        client:      Injected AsyncAnthropic (api_key managed externally, never logged).
        model:       Sonnet model ID (verbatim from Node extraction extractor).
        max_tokens:  Maximum tokens in response (16384 for multi-event pages).
        on_llm_call: Optional observer called after each LLM call with (req, resp).
                     Accepts both sync and async callables. Observer errors are
                     caught + warn-logged, never propagated.
        log:         Optional logger; defaults to module logger.

    Returns:
        {"extract": async_fn} where async_fn never raises.
    """
    _log = log or logger
    _timeout_s = _DEFAULT_TIMEOUT_MS / 1000

    async def _call_with_observer(req: dict, _capture_id: str | None = None):
        """Wrap client.with_options(timeout=...).messages.create(**req).

        Fires on_llm_call observer in a finally block (both initial and retry calls),
        mirroring Node's callWithObserver which fires onLlmCall in finally so timed-out
        or errored calls that consumed tokens are still recorded. Observer receives an
        `error` field (str|None) so the backfill harness can log partial-response costs.

        Observer errors are caught + warn-logged, never propagated (mirror Node).
        Uses inspect.iscoroutinefunction to decide await, not iscoroutine(result).
        """
        resp = None
        exc = None
        try:
            # Pitfall 9: timeout via with_options, NEVER as a body kwarg
            resp = await client.with_options(timeout=_timeout_s).messages.create(**req)
            return resp
        except Exception as e:  # noqa: BLE001
            exc = e
            raise
        finally:
            if on_llm_call is not None:
                try:
                    if inspect.iscoroutinefunction(on_llm_call):
                        await on_llm_call(req, resp, exc)
                    else:
                        on_llm_call(req, resp, exc)
                except Exception as obs_err:  # noqa: BLE001
                    _log.warning("[extractor] observer error: %s", obs_err)

    async def extract(
        captures: list[dict],
        in_flight_draft=None,
        corpus_context=None,
        farmer_correction: str | None = None,
    ) -> dict:
        """Extract a structured draft from captures via Sonnet forced tool-use.

        Never raises (fail-open). Every failure path returns {ok:False, reason:...}.

        Returns (NEVER raises):
          {ok:True, drafts, continuity_decision, continuity_reason, draft,
           per_field_confidence, capture_kind, usage}  on success
          {ok:False, reason:str | "no_tool_use_in_response" | "schema_invalid",
           ...}  on any failure

        Security T-59-02-01: farmer content MUST NOT appear in log output.
        """
        try:
            user_content = build_initial_user_content(
                captures=captures,
                in_flight_draft=in_flight_draft,
                corpus_context=corpus_context,
                farmer_correction=farmer_correction,
            )
            messages = [
                *cacheable_few_shot(),
                {"role": "user", "content": user_content},
            ]
            base_req: dict = {
                "model": model,
                "max_tokens": max_tokens,
                "system": CACHEABLE_SYSTEM_BLOCKS,
                "tools": [build_tool_spec()],
                "tool_choice": {"type": "tool", "name": TOOL_NAME},
                "messages": messages,
            }

            # ---------------------------------------------------------------
            # First LLM call
            # ---------------------------------------------------------------
            try:
                resp = await _call_with_observer(base_req)
            except Exception as e:  # noqa: BLE001
                _log.warning("[extractor] first call degraded: %s", e)
                return {"ok": False, "reason": str(e)}

            block = find_tool_use_block(resp)
            if block is None:
                return {"ok": False, "reason": "no_tool_use_in_response"}

            # ---------------------------------------------------------------
            # Validate first response
            # ---------------------------------------------------------------
            first_validation_error: str | None = None
            try:
                submission = Submission.model_validate(block.input)
                return pack_result(submission, sum_usage([getattr(resp, "usage", None)]))
            except ValidationError as ve:
                first_validation_error = str(ve)
                _log.warning("[extractor] first validation failed, retrying: %s", ve)

            # ---------------------------------------------------------------
            # Retry: one tool_result is_error=True turn (Pitfall 1: block.id not block.name)
            # ---------------------------------------------------------------
            assistant_turn = {"role": "assistant", "content": resp.content}
            retry_user_turn = {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,  # block.id, NOT block.name (Pitfall 1)
                        "is_error": True,
                        "content": first_validation_error,
                    }
                ],
            }
            retry_req = {
                **base_req,
                "messages": [*messages, assistant_turn, retry_user_turn],
            }

            try:
                resp2 = await _call_with_observer(retry_req)
            except Exception as e2:  # noqa: BLE001
                _log.warning("[extractor] retry call degraded: %s", e2)
                return {"ok": False, "reason": str(e2)}

            block2 = find_tool_use_block(resp2)
            if block2 is None:
                return {"ok": False, "reason": "no_tool_use_in_response"}

            # ---------------------------------------------------------------
            # Validate retry response (Pitfall 5: MUST catch, never propagate)
            # ---------------------------------------------------------------
            try:
                submission2 = Submission.model_validate(block2.input)
                combined_usage = sum_usage([
                    getattr(resp, "usage", None),
                    getattr(resp2, "usage", None),
                ])
                return pack_result(submission2, combined_usage)
            except ValidationError as e2:  # noqa: BLE001 -- Pitfall 5: must not propagate
                return {
                    "ok": False,
                    "reason": "schema_invalid",
                    "errors": e2.errors(),
                    "raw_first": block.input,
                    "raw_retry": block2.input,
                }

        except Exception as e:  # noqa: BLE001 -- outer fail-open guard
            _log.warning("[extractor] degraded: %s", e)
            return {"ok": False, "reason": str(e)}

    return {"extract": extract}
