---
phase: 61-confirm-loop
fixed_at: 2026-06-28T00:00:00Z
review_path: .planning/phases/61-confirm-loop/61-REVIEW.md
iteration: 1
findings_in_scope: 8
fixed: 8
skipped: 0
status: all_fixed
---

# Phase 61: Code Review Fix Report

**Fixed at:** 2026-06-28
**Source review:** .planning/phases/61-confirm-loop/61-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 8
- Fixed: 8
- Skipped: 0

## Fixed Issues

### CR-01: `update_draft_after_edit` missing `AND status='awaiting_farmer'` WHERE guard

**Files modified:** `src/farm-agent/farm_agent/confirm/confirm_repo.py`
**Commit:** d371703
**Applied fix:** Added `AND status='awaiting_farmer'` to the dynamically-built UPDATE WHERE
clause in `update_draft_after_edit`. This matches Node `confirm-db.js:222-230` and prevents
overwriting `draft_json`/`per_field_confidence`/`farmer_facing_preview` on already-confirmed,
discarded, or expired drafts. rowcount==0 on non-awaiting_farmer drafts now correctly signals
no-op (idempotency contract preserved). IN-01 rationale comment also added in the same commit.

---

### CR-02: `expire_draft` emits wrong event name for non-timeout reasons

**Files modified:** `src/farm-agent/farm_agent/confirm/confirm_repo.py`
**Commit:** d371703
**Applied fix:** Added `_event_name_map` dict in `expire_draft` to produce the correct event
name per reason:
- `'edit_cap_exceeded'` -> event `'edit_cap_exceeded'`
- `'superseded_by_newer_draft'` -> event `'superseded'`
- `'timeout_expired'` (or any other) -> event `'expired'`

Matches Node `confirm-db.js:148-180` exactly. Comment documents the mapping.

---

### CR-03: `find_awaiting_for_sender` excludes `commit_failed` drafts

**Files modified:** `src/farm-agent/farm_agent/confirm/confirm_repo.py`
**Commit:** d371703
**Applied fix:** Replaced `WHERE sender_e164=%s AND status='awaiting_farmer'` with
`WHERE sender_e164=%s AND status IN ('awaiting_farmer', 'commit_failed')` and added
ordering `CASE status WHEN 'awaiting_farmer' THEN 0 ELSE 1 END ASC, updated_at DESC`
so `awaiting_farmer` wins when both statuses coexist. Added the Phase 45 Plan 04 follow-on
comment verbatim, explaining why `commit_failed` must be included so EDIT replies on failed
commits reach the edit-handler instead of the capture pipeline.

---

### WR-01: `parse_strain_ask_back_reply` Path 2 tokenizes differently from Node

**Files modified:** `src/farm-agent/farm_agent/confirm/strain_ask_back.py`
**Commit:** 8747ab9
**Applied fix:** Path 2 now computes `rest = trimmed[len(tokens[0]):].lstrip(" ,").strip()`
(full remainder after "no" token) and tests `CODE_RE.match(rest)` against it. This mirrors
Node `strain-ask-back.js:61` exactly. "no KOY please" -> rest="KOY please" -> fails CODE_RE
($-anchor) -> unknown. "no KOY" / "no, KOY" -> rest="KOY" -> correction:KOY (unchanged).
Path 2 now always returns `{"kind": "unknown"}` when the rest fails CODE_RE (explicit return).

---

### WR-02: `send_discard_ack` sends ack unconditionally regardless of rowcount

**Files modified:** `src/farm-agent/farm_agent/confirm/dispatch.py`
**Commit:** c6a3818
**Applied fix:** `_handle_standard_confirm` now gates the `_ack_send("OK, discarded.")` call
on `res.get("rowcount") == 1`. When rowcount==0 (race lost -- draft already expired by
watchdog), no ack is sent, matching Node `_runTransition` behavior. Log line updated to
include rowcount for observability. Return dict unchanged.

---

### WR-03: `parse_strain_ask_back_reply` Path 3 bare-token check tests `tokens[0]`

**Files modified:** `src/farm-agent/farm_agent/confirm/strain_ask_back.py`
**Commit:** 8747ab9
**Applied fix:** Path 3 now tests `CODE_RE.match(text.strip())` against the full trimmed
string, removing the `len(tokens)==1` guard. Multi-word strings (e.g. "KOY extra") still
correctly fall through to unknown because the `$`-anchored CODE_RE rejects them. Single-word
inputs behave identically to before. This mirrors Node's `CODE_RE.test(trimmed)` directly.

---

### IN-01: `update_draft_after_edit` S608 suppression lacks rationale

**Files modified:** `src/farm-agent/farm_agent/confirm/confirm_repo.py`
**Commit:** d371703
**Applied fix:** Added inline comment before the f-string: `# noqa: S608 -- safe: sets[]
contains only literal column assignments; all values parameterized`. This documents why the
dynamic SQL is safe for future maintainers.

---

### IN-02: `confirm_watchdog_loop` logs no startup line

**Files modified:** `src/farm-agent/farm_agent/confirm/watchdog.py`
**Commit:** 8c8865d
**Applied fix:** Added `log.info("[watchdog] started: timeout=%dmin nudge=%dmin interval=%.0fms", ...)` 
at the top of `confirm_watchdog_loop` before the immediate tick, matching Node
`watchdog.js:76-79`. Values: `config.draft_pending_timeout_min`, computed `nudge_min`,
and `config.draft_watchdog_interval_ms`.

---

## Node mappings confirmed

- **expire_draft event names** (confirm-db.js:148-180):
  - `edit_cap_exceeded` -> `'edit_cap_exceeded'`
  - `superseded_by_newer_draft` -> `'superseded'`
  - `timeout_expired` (default) -> `'expired'`

- **findAwaitingForSender status set** (confirm-db.js:246-250):
  `IN ('awaiting_farmer', 'commit_failed')` with Phase 45 Plan 04 follow-on comment intact.
  Ordering: `awaiting_farmer` priority 0, `commit_failed` priority 1, then `updated_at DESC`.

- **parseStrainAskBackReply Path 2** (strain-ask-back.js:61):
  `rest = trimmed.slice(firstToken.length).replace(/^[\s,]+/, '').trim()` then
  `CODE_RE.test(rest)` -- full remainder, not single token.

- **parseStrainAskBackReply Path 3** (strain-ask-back.js:70):
  `CODE_RE.test(trimmed)` -- full trimmed string.

## Test results

Final run: **330 passed, 26 skipped** (was 325 passed, 22 skipped before fixes).
New tests added:
- `test_confirm_repo.py`: CR-01 (status guard), CR-02 (event names x3 reasons),
  CR-03 (commit_failed included + awaiting_farmer priority) -- all DB-gated, skip without :5434
- `test_strain_ask_back.py`: WR-01 (3 path-2 edge cases), WR-02 (2 discard ack gate tests)

---

_Fixed: 2026-06-28_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
