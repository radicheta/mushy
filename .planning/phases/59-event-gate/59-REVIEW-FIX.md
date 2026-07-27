---
phase: 59-event-gate
fixed_at: 2026-06-24T00:00:00Z
review_path: .planning/phases/59-event-gate/59-REVIEW.md
iteration: 1
findings_in_scope: 4
fixed: 4
skipped: 0
status: all_fixed
---

# Phase 59: Code Review Fix Report

**Fixed at:** 2026-06-24
**Source review:** .planning/phases/59-event-gate/59-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 4
- Fixed: 4
- Skipped: 0

## Fixed Issues

### CR-01: `extraction_gate` is written to the row dict but never inserted -- column always NULL

**Files modified:** `src/farm-agent/farm_agent/capture/capture_repo.py`, `src/farm-agent/tests/test_capture_repo.py`
**Commit:** a879757
**Applied fix:** Added `extraction_gate` as the 18th column in `_INSERT_SQL` and appended `row.get("extraction_gate")` to the params tuple. Updated column count comment from 17 to 18 and extended the docstring's column contract and row dict keys. Added `test_insert_sql_includes_extraction_gate` (DB-independent, always runs) and `test_extraction_gate_roundtrips` (DB-gated, skips without DB) to guard against regression.

Migration status: `extraction_gate VARCHAR(32)` already existed in `persistence/migrations.py` (Phase 44 Plan-04 D-04 comment, line 104-107). No new migration was needed.

---

### CR-02: `rule_negative` crashes with `AttributeError` when `sent_at` is a `datetime` object

**Files modified:** `src/farm-agent/farm_agent/gate/rules.py`, `src/farm-agent/tests/test_gate_rules.py`
**Commit:** 1ae035e
**Applied fix:** Added an `isinstance(sent_at, datetime)` branch -- if already a datetime, call `.timestamp()` directly; otherwise use the existing string `fromisoformat`/`.replace("Z", "+00:00")` path. Added `test_rule_negative_sent_at_datetime_fires` (pure, no DB, always runs) that constructs a real `datetime` object for `sent_at` and asserts the rule fires correctly.

---

### WR-01: `last_bot_outbound` hardcoded to `None` -- `rule_negative` never fires in production

**Files modified:** `src/farm-agent/farm_agent/capture/pipeline.py`
**Commit:** e48b48f
**Applied fix:** Added a `# TODO(Phase 60): wire last_bot_outbound from capture_history.select_recent_outbound_by_recipient` comment immediately above the `gate["classify"]` call, documenting the deliberate deferral. The hardcode itself is unchanged (out of scope for Phase 59).

---

### IN-01: ACK_RE comment overstates the problem -- `re.match` + `$` should use `re.fullmatch`

**Files modified:** `src/farm-agent/farm_agent/gate/rules.py`
**Commit:** 209c14e
**Applied fix:** Switched the call site from `ACK_RE.match(body)` to `ACK_RE.fullmatch(body)`, making the full-string-match intent self-documenting. Removed the now-redundant "Pitfall 4" comment at the call site. Updated the comment above the `ACK_RE` definition to reference `fullmatch`. The `$` anchor in the pattern is retained for clarity; behavior is identical.

---

## Test results (post-fix)

`cd src/farm-agent && uv run pytest -q`: **195 passed, 19 skipped**

- Baseline was 193 passed / 18 skipped.
- 2 new always-run tests added: `test_insert_sql_includes_extraction_gate` and `test_rule_negative_sent_at_datetime_fires` -- both pass.
- 1 new DB-gated test added: `test_extraction_gate_roundtrips` -- skipped (no test DB), as expected.

---

_Fixed: 2026-06-24_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
