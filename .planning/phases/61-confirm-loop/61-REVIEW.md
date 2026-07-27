---
phase: 61-confirm-loop
reviewed: 2026-06-28T00:00:00Z
depth: standard
files_reviewed: 8
files_reviewed_list:
  - src/farm-agent/farm_agent/confirm/state_machine.py
  - src/farm-agent/farm_agent/confirm/confirm_repo.py
  - src/farm-agent/farm_agent/confirm/watchdog.py
  - src/farm-agent/farm_agent/confirm/strain_ask_back.py
  - src/farm-agent/farm_agent/confirm/dispatch.py
  - src/farm-agent/farm_agent/confirm/__init__.py
  - src/farm-agent/farm_agent/boot.py
  - src/farm-agent/farm_agent/tenancy/tenant.py
findings:
  critical: 3
  warning: 3
  info: 2
  total: 8
status: fixed
---

# Phase 61: Code Review Report

**Reviewed:** 2026-06-28
**Depth:** standard
**Files Reviewed:** 8
**Status:** findings_found

## Summary

Phase 61 is a JS->Python port of the Node confirm loop. The FSM (state_machine.py)
is a faithful, well-ordered port. The boot wiring, watchdog loop structure, SQL
guards on confirm/discard/nudge, never-throws pattern, PII masking, and
CancelledError propagation are all correct. Three correctness defects were
found: a missing status guard in `update_draft_after_edit`, a wrong event name
emitted by `expire_draft` for non-timeout reasons, and a scoping gap in
`find_awaiting_for_sender` that silently drops the `commit_failed` path the
Node source intentionally handles. Two further divergences in the strain reply
parser and one no-ack gap in discard rounding out the warnings.

---

## Critical Issues

### CR-01: `update_draft_after_edit` missing `AND status='awaiting_farmer'` WHERE guard

**File:** `src/farm-agent/farm_agent/confirm/confirm_repo.py:291`

**Issue:** The dynamically-built UPDATE for edit reextraction uses only
`WHERE id=%s`. The Node source (`confirm-db.js:222-230`) uses
`WHERE id=$1 AND status='awaiting_farmer'`. Without the status guard, this
UPDATE will happily overwrite `draft_json`, `per_field_confidence`, and
`farmer_facing_preview` on a draft that has already been confirmed, discarded,
or expired -- corrupting the terminal record's data. It also breaks the
Node-intended idempotency contract (rowcount=0 on a non-awaiting_farmer draft).

**Fix:**
```python
# confirm_repo.py line 291 -- add status guard to match Node
sql = f"UPDATE signal_draft SET {', '.join(sets)} WHERE id=%s AND status='awaiting_farmer'"  # noqa: S608
```

---

### CR-02: `expire_draft` emits wrong event name for `superseded_by_newer_draft` and `edit_cap_exceeded`

**File:** `src/farm-agent/farm_agent/confirm/confirm_repo.py:197`

**Issue:** `expire_draft` always appends an event named `"expired"` regardless of
the `reason` parameter (line 197: `await append_event(conn, draft_id, "expired", ...)`).

The Node source (`confirm-db.js:148-180`) emits three distinct event names:
- `reason='edit_cap_exceeded'` -> event name `'edit_cap_exceeded'`
- `reason='superseded_by_newer_draft'` -> event name `'superseded'`
- `reason='timeout_expired'` (or default) -> event name `'expired'`

Downstream consumers (Phase 62 commit watchdog, audit queries) that filter
`signal_draft_event.event` for `'superseded'` or `'edit_cap_exceeded'` will
miss these rows entirely. Phase 62 expressly reads the event log to detect
commit-trigger vs suppressed paths.

**Fix:**
```python
# In expire_draft, replace the hardcoded "expired" event name:
event_name_map = {
    "edit_cap_exceeded": "edit_cap_exceeded",
    "superseded_by_newer_draft": "superseded",
}
event_name = event_name_map.get(reason, "expired")

async with conn.transaction():
    result = await conn.execute(sql, (reason, draft_id))
    if result.rowcount == 1:
        await append_event(conn, draft_id, event_name, {"terminal_reason": reason})
```

---

### CR-03: `find_awaiting_for_sender` excludes `commit_failed` drafts -- breaks EDIT-from-commit_failed path

**File:** `src/farm-agent/farm_agent/confirm/confirm_repo.py:94-103`

**Issue:** `_AWAITING_FOR_SENDER_SQL` filters `WHERE sender_e164=%s AND status='awaiting_farmer'`.

The Node `findAwaitingForSender` (`confirm-db.js:236-260`) was intentionally
extended with a comment:
> "Phase 45 Plan 04 follow-on: include commit_failed in the active-draft lookup
> so EDIT replies from a farmer on a failed commit actually reach the edit-handler"

Without `commit_failed` in scope, a farmer whose draft is in `commit_failed`
status who replies "edit" will match no awaiting draft, and the reply falls
through to the capture pipeline -- silently creating a new observation instead
of re-extracting the failed one. This is a data-integrity regression vs Node.

**Fix:**
```python
_AWAITING_FOR_SENDER_SQL = """
SELECT id, status, sender_e164, edit_turn_count, nudge_sent_at,
       confirmed_at, discarded_at, expired_at, terminal_reason,
       needs_review_reason, draft_json, per_field_confidence,
       farmer_facing_preview, updated_at, reply_target_kind, group_id
  FROM signal_draft
 WHERE sender_e164=%s
   AND status IN ('awaiting_farmer', 'commit_failed')
 ORDER BY CASE status WHEN 'awaiting_farmer' THEN 0 ELSE 1 END ASC,
          updated_at DESC
 LIMIT 1
"""
```

---

## Warnings

### WR-01: `parse_strain_ask_back_reply` Path 2 ("no CODE") tokenizes differently from Node

**File:** `src/farm-agent/farm_agent/confirm/strain_ask_back.py:175-178`

**Issue:** The Node parser (`strain-ask-back.js:59-66`) extracts the rest after
"no" as:
```js
const rest = trimmed.slice(firstToken.length).replace(/^[\s,]+/, '').trim();
if (rest && CODE_RE.test(rest)) { ... }
```
It tests CODE_RE against the *entire remainder* of the string after "no". So
`"no KOY please"` would have `rest = "KOY please"` which fails CODE_RE (has a
space), correctly returning `unknown`. The Python code at line 177 takes
`tokens[1].strip(",")` -- a single token -- and tests that. For `"no KOY please"`,
Python would return `correction: KOY`. This is a behavioral divergence: Node
returns `unknown`, Python returns `correction`.

For the realistic single-word case (`"no KOY"`) they agree. The divergence
matters for freeform replies like `"no KOY that's wrong"` where Node correctly
falls through to `unknown` (triggering re-ask) but Python extracts `KOY`.

**Fix:** Mirror Node by checking the full remainder:
```python
if first == "no":
    rest = text.strip()[len(tokens[0]):].lstrip(" ,").strip()
    if rest and CODE_RE.match(rest):
        return {"kind": "correction", "code": rest.upper()}
    return {"kind": "unknown"}
```

---

### WR-02: `discard_draft` does not check rowcount before sending ack -- sends ack even on race loss

**File:** `src/farm-agent/farm_agent/confirm/dispatch.py:321-329`

**Issue:** The `send_discard_ack` branch in `_handle_standard_confirm` calls
`discard_draft` and then unconditionally sends the ack, regardless of whether
`rowcount == 1` or `0`:

```python
if effect == "send_discard_ack":
    res = await repo.discard_draft(pool, draft_id)
    await _ack_send(signal_client, "OK, discarded.", ...)  # always fires
```

The Node `_runTransition` returns `rowCount`; the Node receive-loop dispatches
the ack only when the transition succeeds. When `rowcount == 0` (race lost --
draft already transitioned by the watchdog), the farmer receives a spurious
"OK, discarded." for an entry that was actually expired. This is a no-silent-failure
violation for the NO path: the ack text is factually wrong.

**Fix:**
```python
if effect == "send_discard_ack":
    res = await repo.discard_draft(pool, draft_id)
    if res.get("rowcount") == 1:
        await _ack_send(signal_client, "OK, discarded.", to=to,
                        related_draft_id=draft_id, intent="discard_ack")
    else:
        await _ack_send(signal_client, "Already processed -- nothing to discard.", to=to,
                        related_draft_id=draft_id, intent="discard_ack_idempotent")
    log.info("[dispatch] discarded draft_id=%s rowcount=%s", draft_id, res.get("rowcount"))
    return {"action": "discarded", "rowcount": res.get("rowcount")}
```

---

### WR-03: `strain_ask_back.py` Path 3 bare-token check tests `tokens[0]` but Node tests full `trimmed`

**File:** `src/farm-agent/farm_agent/confirm/strain_ask_back.py:182-183`

**Issue:** Node Path 3 (`strain-ask-back.js:70-72`):
```js
if (CODE_RE.test(trimmed)) {
  return { kind: 'correction', code: trimmed.toUpperCase() };
}
```
It tests CODE_RE against the full trimmed string (no prior multi-token guard).
This means a multi-word string like `"KOY extra"` fails (spaces fail `^...$`)
and correctly falls to `unknown`. The Python version guards with `len(tokens) == 1`
first. These produce the same outcome for well-formed inputs. However, the
explicit guard in Python prevents the `len(tokens) == 1 and tokens[0].lower() != "no"`
branch from being reached on a string that IS a bare code, because `len(tokens)`
is checked before `CODE_RE`. For the single-token "KOY" case they agree.

The subtler divergence: Python's `tokens[0]` after `split()` strips ALL
whitespace sequences, so leading/trailing tabs are handled. Node's `CODE_RE.test(trimmed)`
tests the already-`trim()`-ed full string. For single-token inputs these are
functionally equivalent. This is a low-risk divergence but worth noting for
future maintenance.

**Fix (optional):** Mirror Node's structure for clarity:
```python
# Path 3: bare single token matches CODE_RE (same as Node: test full trimmed)
trimmed = text.strip()
if CODE_RE.match(trimmed) and trimmed.lower() != "no":
    return {"kind": "correction", "code": trimmed.upper()}
```

---

## Info

### IN-01: `update_draft_after_edit` dynamic SQL uses f-string (S608 suppressed without explanation)

**File:** `src/farm-agent/farm_agent/confirm/confirm_repo.py:291`

**Issue:** The `# noqa: S608` suppresses the bandit "possible SQL injection"
warning, but the suppression comment only says `S608` with no rationale. The
SQL construction IS safe (only controlled column names from `sets`, and the
value is the parameterized `draft_id` appended last), but the noqa annotation
should document why:
```python
# noqa: S608 -- safe: sets[] contains only literal column assignments; all values parameterized
```
Worth annotating explicitly given this codebase's attention to injection guards.

---

### IN-02: `confirm_watchdog_loop` logs no startup line -- harder to confirm task started

**File:** `src/farm-agent/farm_agent/confirm/watchdog.py:192-224`

**Issue:** The Node watchdog `start()` logs:
```
[watchdog] started: timeout=Xmin nudge=Xmin interval=Xms
```
at startup (`watchdog.js:76-79`). The Python `confirm_watchdog_loop` emits no
startup log. At boot time the only evidence the task started is from
`boot.py`'s `create_task` call, which is not itself logged. When diagnosing
a missed nudge or expiry, operators have no log line confirming the watchdog
is running with the expected config values.

**Fix:**
```python
# After computing interval and nudge_min, before the immediate tick:
log.info(
    "[watchdog] started: timeout=%dmin nudge=%dmin interval=%.0fms",
    config.draft_pending_timeout_min,
    round(config.draft_pending_timeout_min * config.draft_nudge_fraction),
    config.draft_watchdog_interval_ms,
)
```

---

_Reviewed: 2026-06-28_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

**Finding count: 3 Critical, 3 Warning, 2 Info (8 total)**
