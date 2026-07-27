"""
gate/event_gate.py -- Event-gate facade.

Port of src/agents/alerter/src/event-gate/index.js (createEventGate).

Provides:
  create_event_gate(haiku_classifier, log=None) -> {"classify": classify}

Decision flow (verbatim from Node index.js D-02 mandatory order):
  1. rule_positive hit  -> {gate:'fast_event',       allow_extract:True,  allow_convo:True}
  2. rule_negative hit  -> {gate:'skipped_rule_neg', allow_extract:False, allow_convo:False}
  3. await haiku_classifier["classify"](env_ctx)
     - not r or not r.get("ok") -> {gate:'forced',       allow_extract:True,  allow_convo:True} (D-03 fail-OPEN)
     - r.get("is_event") is True OR confidence < 0.7  -> {gate:'haiku_event',    allow_extract:True,  allow_convo:True}
     - else -> {gate:'haiku_chitchat', allow_extract:False, allow_convo:False}

Gate enum (D-04): skipped_rule_neg | fast_event | haiku_event | haiku_chitchat | forced

Python translation notes (from 59-PATTERNS.md):
  - r.get("is_event") is True  (strict identity, not truthiness)
  - isinstance(r.get("confidence"), (int, float)) and r.get("confidence") < 0.7
  - not r or not r.get("ok")  (mirrors JS !r || !r.ok)

Foray island: imports only from farm_agent.gate (leaf units).
"""

from __future__ import annotations

import logging

from farm_agent.gate.rules import rule_negative, rule_positive

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Gate enum constants (D-04)
# ---------------------------------------------------------------------------

GATE_FAST_EVENT = "fast_event"
GATE_SKIPPED_RULE_NEG = "skipped_rule_neg"
GATE_FORCED = "forced"
GATE_HAIKU_EVENT = "haiku_event"
GATE_HAIKU_CHITCHAT = "haiku_chitchat"


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_event_gate(
    haiku_classifier: dict,
    log: logging.Logger | None = None,
) -> dict:
    """Factory returning {"classify": classify}.

    Port of createEventGate({haikuClassifier, rules, logger}) from index.js.

    Args:
        haiku_classifier: {"classify": async(env_ctx) -> {ok,...}} dict from
                          create_haiku_classifier().  The gate composes the rules
                          module functions internally (rule_positive / rule_negative
                          are imported at module level -- mirrors the Node facade
                          receiving `rules` as an injected dep).
        log:              Optional logger; defaults to module logger.

    Returns:
        {"classify": async classify(env_ctx, last_bot_outbound, now_ms) -> gate_result}
    """
    _log = log or logger

    async def classify(
        env_ctx: dict,
        last_bot_outbound: dict | None,
        now_ms: int,
    ) -> dict:
        """Apply the event-gate decision flow.

        Reproduces src/agents/alerter/src/event-gate/index.js classify() verbatim.

        Args:
            env_ctx:           {"text", "transcript", "attachmentCount"} capture context.
            last_bot_outbound: Last outbound bot message (for rule_negative ack-window check).
                               None = no prior bot message in this session.
            now_ms:            Current epoch in milliseconds.

        Returns:
            {gate, allow_extract, allow_convo}  -- never raises (fail-open).
        """
        # --- Step 1: rule_positive fast-path ---
        pos = rule_positive(env_ctx)
        if pos.get("hit"):
            return {
                "gate": GATE_FAST_EVENT,
                "allow_extract": True,
                "allow_convo": True,
            }

        # --- Step 2: rule_negative fast-path ---
        neg = rule_negative(env_ctx, last_bot_outbound, now_ms)
        if neg.get("hit"):
            return {
                "gate": GATE_SKIPPED_RULE_NEG,
                "allow_extract": False,
                "allow_convo": False,
            }

        # --- Step 3: Haiku classifier ---
        r = await haiku_classifier["classify"](env_ctx)

        # D-03 fail-OPEN: !r || !r.ok -> forced (allow_extract=True)
        if not r or not r.get("ok"):
            _log.warning(
                "[event-gate] classifier degraded -- fail-open (forced); reason=%s",
                r.get("reason") if r else "no_response",
            )
            return {
                "gate": GATE_FORCED,
                "allow_extract": True,
                "allow_convo": True,
            }

        # is_event === true OR confidence < 0.7 (verbatim from index.js)
        is_event = r.get("is_event") is True
        confidence = r.get("confidence")
        confidence_below_floor = (
            isinstance(confidence, (int, float)) and confidence < 0.7
        )

        if is_event or confidence_below_floor:
            return {
                "gate": GATE_HAIKU_EVENT,
                "allow_extract": True,
                "allow_convo": True,
            }

        return {
            "gate": GATE_HAIKU_CHITCHAT,
            "allow_extract": False,
            "allow_convo": False,
        }

    return {"classify": classify}
