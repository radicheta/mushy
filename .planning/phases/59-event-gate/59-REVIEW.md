---
phase: 59-event-gate
reviewed: 2026-06-24T00:00:00Z
depth: standard
files_reviewed: 7
files_reviewed_list:
  - src/farm-agent/farm_agent/gate/rules.py
  - src/farm-agent/farm_agent/gate/classifier.py
  - src/farm-agent/farm_agent/gate/event_gate.py
  - src/farm-agent/farm_agent/gate/prompts.py
  - src/farm-agent/farm_agent/gate/__init__.py
  - src/farm-agent/farm_agent/boot.py
  - src/farm-agent/farm_agent/capture/pipeline.py
findings:
  critical: 2
  warning: 1
  info: 1
  total: 4
status: fixed
---

# Phase 59: Code Review Report

**Reviewed:** 2026-06-24
**Depth:** standard
**Files Reviewed:** 7
**Status:** issues_found

## Summary

Seven files reviewed against the Node source of truth
(`src/agents/alerter/src/event-gate/`). The gate logic itself (classifier,
event_gate facade, prompts, __init__) is a faithful port with correct
fail-open semantics, proper prompt-injection mitigations (T-44-04-01), and
correct `with_options(timeout=)` wiring (D-03). No secrets are logged. PII
masking is consistent.

Two critical bugs were found. The first is a silent data loss: the
`extraction_gate` column written by Phase 59 is populated in the pipeline
`row` dict but never passed to the SQL INSERT in `capture_repo.py`. Every
gate decision is discarded on write. The second is a latent crash in
`rule_negative`: `sent_at` from `capture_history` returns a Python
`datetime`, but the port calls `.replace("Z", "+00:00")` on it, which
raises `AttributeError`. The pipeline's outer try/except absorbs it as a
gate-error fail-open, silently making `rule_negative` inert whenever
`last_bot_outbound` is provided. One warning covers the `last_bot_outbound
= None` hardcode in `pipeline.py` that currently masks both issues. One
info item covers a harmless redundancy in the ACK_RE comment.

---

## Critical Issues

### CR-01: `extraction_gate` is written to the row dict but never inserted -- column always NULL

**File:** `src/farm-agent/farm_agent/capture/pipeline.py:312` /
`src/farm-agent/farm_agent/capture/capture_repo.py:33-38`

**Issue:** `pipeline.py` sets `row["extraction_gate"] = gate_result.get("gate")` and
documents it as "Phase 59; VARCHAR(32), migration 007". Migration 007 adds
the column. However `capture_repo.py`'s `_INSERT_SQL` lists exactly 17
columns and the `params` tuple at lines 86-104 does NOT include
`extraction_gate` -- it hardcodes 17 values ending with `None` for
`corpus_context`. `insert_capture` never reads `row.get("extraction_gate")`
and never writes it. Every capture that goes through the gate will have
`extraction_gate = NULL` in the DB despite the classifier running
successfully. The live-fire smoke test (W10 holdout) and all post-hoc gate
queries will appear as if the gate was never called.

**Fix:** Add `extraction_gate` to `_INSERT_SQL` and append it to the params
tuple in `capture_repo.py`. The column is nullable so no schema
incompatibility:

```python
# capture_repo.py -- _INSERT_SQL: add extraction_gate as 18th column
_INSERT_SQL = """
INSERT INTO signal_capture
  (id, captured_at, sender, message_type, raw_text, attachment_paths,
   transcript, llm_session_tag, llm_reply, degraded,
   group_id, farmos_person, reply_target_kind,
   signal_msg_ts, quote_msg_ts, quote_author_e164, corpus_context,
   extraction_gate)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

# params tuple: add extraction_gate as last element (line ~104 in capture_repo.py)
        None,                                      # corpus_context -- ALWAYS None (T-58-02-02)
        row.get("extraction_gate"),                # VARCHAR(32) | None -- Phase 59
```

Also update the column-count comment from "17 columns" to "18 columns" and
add `extraction_gate str | None` to the row dict docstring.

---

### CR-02: `rule_negative` crashes with `AttributeError` when `sent_at` is a `datetime` object

**File:** `src/farm-agent/farm_agent/gate/rules.py:95-97`

**Issue:** `sent_at = last_bot_outbound.get("sent_at")` receives the value as
returned by `capture_history.select_recent_outbound_by_recipient`. That
function executes a raw psycopg3 query against a `timestamptz` column;
psycopg3 materializes `timestamptz` as an aware `datetime` object, not a
string. Line 96 then calls `sent_at.replace("Z", "+00:00")` -- `datetime`
has no `.replace` method that takes string arguments like that (it only
accepts keyword arguments for field replacement). This raises
`AttributeError: 'datetime' object has no attribute 'replace'` at runtime.

The Node source uses `new Date(lastBotOutbound.sent_at).getTime()` which
accepts both ISO strings and Date objects. The Python port handles only ISO
strings.

Currently `pipeline.py:279` always passes `None` for `last_bot_outbound`,
so this is latent. The moment any caller wires in real history (Phase 59+),
`rule_negative` will silently fail for every in-window ack -- they will
fall through to the Haiku classifier instead of being fast-rejected, costing
real API calls and producing incorrect `haiku_*` gate values for what should
be `skipped_rule_neg`.

The pipeline's gate try/except (line 287) will absorb the AttributeError as
a generic gate error and log a WARNING with `err=` -- the failure will not
be silent if `last_bot_outbound` is ever non-None, but the warning message
will not identify which rule failed or that `rule_negative` is broken.

**Fix:** Handle both `datetime` and `str` for `sent_at`:

```python
# rules.py lines 93-97 -- replace the fromisoformat block
    sent_at = last_bot_outbound.get("sent_at")
    if not sent_at:
        return {"hit": False}

    # sent_at may be a timezone-aware datetime (from psycopg3 timestamptz)
    # or an ISO 8601 string (from tests / serialized JSON).
    if isinstance(sent_at, datetime):
        sent_at_ms = int(sent_at.timestamp() * 1000)
    else:
        # Pitfall 8: Python < 3.11 fromisoformat does not handle trailing 'Z'.
        sent_at_ms = int(
            datetime.fromisoformat(str(sent_at).replace("Z", "+00:00")).timestamp() * 1000
        )
```

---

## Warnings

### WR-01: `last_bot_outbound` hardcoded to `None` -- `rule_negative` never fires in production

**File:** `src/farm-agent/farm_agent/capture/pipeline.py:279`

**Issue:** The gate call is:
```python
gate_result = await gate["classify"](env_ctx, None, int(time.time() * 1000))
```
`last_bot_outbound` is always `None`. `rule_negative` will always return
`{"hit": False}` immediately at its first guard (line 86 of rules.py).
Short acks within 30 minutes of an `attestation_kickoff` are never
fast-rejected; they go through the Haiku classifier, burning tokens and
adding latency.

This is documented nowhere in the `pipeline.py` source -- the comment on
line 155 says `last_bot_outbound` is the "Last outbound bot message" but
does not note that it is intentionally stubbed out. If this is a deliberate
Phase 59 deferral, a `# TODO(Phase 60): wire last_bot_outbound from
capture_history` comment is needed so the omission is not mistaken for a
complete implementation.

**Fix:** If wiring is deferred, add a `# TODO` comment at line 279
documenting the intent. When wiring, also fix CR-02 first. The call becomes:

```python
# Fetch last bot outbound for rule_negative ack-window (Phase 60).
# last_bot = await get_last_bot_outbound(pool, source, config, now_ms - _30M_MS)
gate_result = await gate["classify"](env_ctx, last_bot, int(time.time() * 1000))
```

---

## Info

### IN-01: ACK_RE comment overstates the problem -- `re.match` already anchors at the start

**File:** `src/farm-agent/farm_agent/gate/rules.py:27-29`

**Issue:** The comment reads "re.match anchors at start but NOT end. The
explicit $ is required so 'ok then let me explain' does NOT match." This is
correct about needing `$`, but the comment on line 108 says "Pitfall 4:
ACK_RE has explicit $ anchor; re.match only anchors at start." The comment
is accurate but slightly misleading -- the canonical way to write a
full-string match in Python is `re.fullmatch()` (Python 3.4+), which makes
the intent self-documenting and eliminates the two-pitfall explanation:

```python
# Simpler and self-documenting:
if not ACK_RE.fullmatch(body):
    return {"hit": False}
```

This is an info-level observation only; the existing `re.match` + `$` is
correct and matches the behavior of Node's `ACK_RE.test(body)`.

---

_Reviewed: 2026-06-24_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

**Summary: 2 Critical, 1 Warning, 1 Info**
