"""
signal_io/router.py — attribution-sensitive envelope routing primitives (SIG-03 / SC#5).

Pure-function module (mirror tenancy/tenant.py style): receives TenantConfig by
injection; config is the sole env-reader (FND-02).

Ports the whitelist gate, DM-vs-group classification, group-trigger collection,
and (unassigned) farmer-map resolution from receive-loop.js:14-29, 124-156 and
capture.js:86.

SCOPE BOUNDARY: message.js is the alert formatter (Phase 63 chamber/message.py),
NOT routing. This module ports ONLY the attribution skeleton. The confirm/snooze/
experiment/capture dispatch branches (receive-loop.js:184+) are later phases.

T-57-03-01: whitelist gate BEFORE any branch (V4 access control, R7).
T-57-03-03: log lines must use mask_number — never the full e164.
T-57-03-04: this module contains only pure functions; loop-never-dies is enforced
             by receive_loop.py's per-envelope try/except.
"""

from __future__ import annotations

import re

from farm_agent.tenancy.tenant import TenantConfig, mask_number  # noqa: F401 (mask_number re-exported)

# ---------------------------------------------------------------------------
# Whitelist (T-17-02 / R7 / T-57-03-01)
# ---------------------------------------------------------------------------

# Command regex — mirrors receive-loop.js:24-25.
# Accepts optional U+FFFC (Signal iOS mention-attachment marker) and optional
# "@mention " prefix before the keyword. After Attestation D live finding
# 2026-05-11 (noted in receive-loop.js:22-23).
_COMMAND_RE = re.compile(
    r"^\s*￼?\s*(?:@\S+\s+)?(mute|snooze|quiet)\b",
    re.IGNORECASE,
)
_SLASH_COMMAND_RE = re.compile(r"^/(force-|cancel-)", re.IGNORECASE)


def allowed_senders(config: TenantConfig) -> set[str]:
    """Build the whitelist set from TenantConfig (T-17-02 / R7).

    Mirrors receive-loop.js:126-128:
        new Set([config.signalSender, config.signalRecipient,
                 ...(config.signalAdditionalSenders || [])].filter(Boolean))
    """
    return {
        s
        for s in (
            [config.signal_sender, config.signal_recipient]
            + list(config.signal_additional_senders or [])
        )
        if s
    }


def is_whitelisted(source: str, config: TenantConfig) -> bool:
    """Return True iff source is in the sender whitelist (T-57-03-01)."""
    return source in allowed_senders(config)


# ---------------------------------------------------------------------------
# Source extraction
# ---------------------------------------------------------------------------


def extract_source(env: dict) -> str | None:
    """Extract the sender phone number from an envelope dict.

    Primary shape: env["envelope"]["source"]
    Returns None when absent (caller must skip the envelope).
    """
    return env.get("envelope", {}).get("source") or None


# ---------------------------------------------------------------------------
# DM vs group classification
# ---------------------------------------------------------------------------


def _read_dm(env: dict) -> dict:
    """Defensive dual-shape dataMessage read.

    Mirrors receive-loop.js:16:
        env?.envelope?.dataMessage || env?.dataMessage || {}
    """
    return (
        env.get("envelope", {}).get("dataMessage")
        or env.get("dataMessage")
        or {}
    )


def classify_envelope(env: dict) -> dict:
    """Classify an envelope into DM or group context.

    Returns a dict with keys:
        source      : str | None  — sender phone
        dm          : dict        — dataMessage (dual-shape read)
        group_id    : str | None  — groupInfo.groupId or None
        group_type  : str | None  — groupInfo.type or None
        is_group    : bool        — True iff groupId present AND type not in UPDATE/QUIT

    Mirrors receive-loop.js:149-155 (Risk #11: UPDATE/QUIT treated as non-group).
    """
    source = extract_source(env)
    dm = _read_dm(env)
    group_info = dm.get("groupInfo") or {}
    group_id = group_info.get("groupId") or None
    group_type = group_info.get("type") or None
    is_group = bool(group_id) and group_type not in ("UPDATE", "QUIT")
    return {
        "source": source,
        "dm": dm,
        "group_id": group_id,
        "group_type": group_type,
        "is_group": is_group,
    }


# ---------------------------------------------------------------------------
# Group trigger collection
# ---------------------------------------------------------------------------


def collect_group_triggers(env: dict, bot_phone: str) -> set[str]:
    """Collect group triggers for an envelope.

    For DM envelopes (no groupInfo / UPDATE / QUIT): returns {"dm"}.
    For group envelopes: returns a subset of {"mention", "command", "quote"}.

    Ports receive-loop.js:14-29 (collectGroupTriggers) verbatim:
    - mention: any mention.number == bot_phone
    - command: text matches mute/snooze/quiet (with optional @mention prefix and
               U+FFFC tolerance) OR /force-* or /cancel-* slash command
    - quote:   quote.author or quote.authorNumber == bot_phone
               (Risk #9: accept both field names for cross-version drift)

    DM context (no group) mirrors receive-loop.js:154:
        triggers = isGroup ? collectGroupTriggers(env, botPhone) : new Set(['dm'])
    """
    dm = _read_dm(env)
    group_info = dm.get("groupInfo") or {}
    group_id = group_info.get("groupId") or None
    group_type = group_info.get("type") or None
    is_group = bool(group_id) and group_type not in ("UPDATE", "QUIT")

    if not is_group:
        return {"dm"}

    out: set[str] = set()
    text = dm.get("message") or ""

    # mention trigger
    mentions = dm.get("mentions") or []
    if any(m and m.get("number") == bot_phone for m in mentions):
        out.add("mention")

    # command trigger (receive-loop.js:24-25)
    if _COMMAND_RE.match(text) or _SLASH_COMMAND_RE.match(text):
        out.add("command")

    # quote trigger (Risk #9: accept author or authorNumber)
    q = dm.get("quote") or {}
    if (q.get("author") or q.get("authorNumber")) == bot_phone:
        out.add("quote")

    return out


# ---------------------------------------------------------------------------
# Farmer-map resolution (SC#5)
# ---------------------------------------------------------------------------


def resolve_farmer(source: str, config: TenantConfig) -> str:
    """Resolve a sender phone to a farmer slug (SC#5).

    Ports capture.js:86:
        const farmosPerson = signalFarmerMap.get(source) ?? '(unassigned)';

    Unknown-but-whitelisted senders resolve to '(unassigned)' and are NOT
    dropped. Never returns None. Never raises.
    """
    return config.signal_farmer_map.get(source) or "(unassigned)"
