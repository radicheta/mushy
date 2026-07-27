"""
gate/classifier.py -- Never-throws Haiku 4.5 classifier factory.

Port of src/agents/alerter/src/event-gate/haiku-classifier.js (createHaikuClassifier).

Provides:
  create_haiku_classifier(client, model, max_tokens, timeout_ms, log) -> {"classify": classify}

Design decisions (from 59-CONTEXT.md):
  D-01: Forced tool classify_capture -- prevents free-form prose responses.
  D-02: Fail-open on any error -- classifier never blocks capture pipeline.
  D-03: with_options(timeout=_timeout_s) -- timeout is a transport option, NOT a body param
         (same live-fire bug Node hit 2026-05-23: AbortSignal in body -> 400).
  D-04: pydantic model_validate replaces Node's zod.safeParse.

Security:
  T-44-04-01: farmer text goes into a SEPARATE messages[] entry (compact JSON),
               never concatenated into CACHEABLE_SYSTEM_BLOCKS.
  T-59-02-01: WARNING logs only the exception/reason -- never env_ctx text/transcript.
  T-59-02-02: injected client owns the api_key; classifier never references it.
"""

from __future__ import annotations

import json
import logging

import anthropic
from pydantic import BaseModel, Field, ValidationError

from farm_agent.gate.prompts import CACHEABLE_SYSTEM_BLOCKS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level constants (verbatim from haiku-classifier.js)
# ---------------------------------------------------------------------------

TOOL_NAME = "classify_capture"
TOOL_DESCRIPTION = "Classify whether this capture is an event worth extracting."

TOOL_DEF = {
    "name": TOOL_NAME,
    "description": TOOL_DESCRIPTION,
    "input_schema": {
        "type": "object",
        "properties": {
            "is_event": {"type": "boolean"},
            "kind": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": ["is_event", "kind", "confidence"],
        "additionalProperties": False,
    },
}


class Classification(BaseModel):
    """Pydantic model replacing Node's zod schema (zod.safeParse → model_validate).

    confidence is range-validated [0, 1] (T-59-02-03).
    """

    is_event: bool
    kind: str
    confidence: float = Field(ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def build_classifier_input(env_ctx: dict) -> list[dict]:
    """Build the user message content list for the Anthropic messages API.

    Returns a single compact-JSON text block.  Farmer text is a SEPARATE messages
    entry -- never concatenated into the system prompt (T-44-04-01 mitigation).
    """
    payload = {
        "text": env_ctx.get("text"),            # None when absent
        "transcript": env_ctx.get("transcript"), # None when absent
        "attachmentCount": env_ctx.get("attachmentCount") or 0,
    }
    return [{"type": "text", "text": json.dumps(payload)}]


def find_tool_use_block(response) -> object | None:
    """Return the first classify_capture tool_use block, or None.

    Pitfall 5: block.type / block.name / block.input are attribute access
    on pydantic response objects, NOT dict keys.
    """
    if not response or not hasattr(response, "content"):
        return None
    for block in response.content:
        if block.type == "tool_use" and block.name == TOOL_NAME:
            return block
    return None


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_haiku_classifier(
    client: anthropic.AsyncAnthropic,
    model: str = "claude-haiku-4-5-20251001",
    max_tokens: int = 100,
    timeout_ms: int = 2000,
    log: logging.Logger | None = None,
) -> dict:
    """Factory returning {"classify": classify}. Port of createHaikuClassifier().

    Holds the injected AsyncAnthropic in the closure (mirror transcribe_client --
    do NOT create a client per call; one shared instance for the daemon lifetime).

    Args:
        client:      Injected AsyncAnthropic (api_key managed externally, never logged).
        model:       Haiku model ID (verbatim from Node; not a floating alias).
        max_tokens:  Maximum tokens in response (100 is sufficient for forced tool output).
        timeout_ms:  Per-request timeout in milliseconds (2000ms default, passed via
                     with_options -- NOT as a body kwarg; Pitfall 1 / D-03).
        log:         Optional logger; defaults to module logger.

    Returns:
        {"classify": async_fn} where async_fn: (env_ctx) -> {ok:True,...} | {ok:False,...}
    """
    _log = log or logger
    _timeout_s = timeout_ms / 1000

    async def classify(env_ctx: dict) -> dict:
        """Classify a capture via Haiku forced tool-use. Never raises (D-02 fail-open).

        Returns (NEVER raises):
          {ok: True, is_event, kind, confidence, usage}  on success
          {ok: False, reason, fallthrough: 'forced'}      on any failure

        Security: env_ctx text/transcript MUST NOT appear in log output (T-59-02-01).
        """
        try:
            # D-03 / Pitfall 1: timeout goes through with_options(), NOT inside
            # messages.create() kwargs -- the API strict-validates the body and
            # would return 400 "timeout: Extra inputs are not permitted" otherwise.
            resp = await client.with_options(timeout=_timeout_s).messages.create(
                model=model,
                max_tokens=max_tokens,
                system=CACHEABLE_SYSTEM_BLOCKS,
                tools=[TOOL_DEF],
                tool_choice={"type": "tool", "name": TOOL_NAME},
                messages=[{"role": "user", "content": build_classifier_input(env_ctx)}],
            )
        except Exception as e:  # noqa: BLE001 -- never raise from classify (D-02 fail-open)
            _log.warning("[haiku-classifier] degraded: %s", e)
            return {"ok": False, "reason": str(e), "fallthrough": "forced"}

        block = find_tool_use_block(resp)
        if block is None:
            return {"ok": False, "reason": "no_tool_use_in_response", "fallthrough": "forced"}

        # Pitfall 5: block.input is a plain dict (not a pydantic model); validate with pydantic.
        try:
            parsed = Classification.model_validate(block.input)
        except ValidationError as e:
            _log.warning("[haiku-classifier] schema_invalid: %s", e)
            return {"ok": False, "reason": "schema_invalid", "fallthrough": "forced"}

        return {
            "ok": True,
            "is_event": parsed.is_event,
            "kind": parsed.kind,
            "confidence": parsed.confidence,
            "usage": getattr(resp, "usage", None),
        }

    return {"classify": classify}
