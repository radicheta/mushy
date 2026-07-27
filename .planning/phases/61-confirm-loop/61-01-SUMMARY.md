---
phase: 61-confirm-loop
plan: "01"
subsystem: confirm-loop
tags: [dao, psycopg3, sql-guards, tenancy, tests]
dependency_graph:
  requires: [phase-56-migrations]
  provides: [confirm_repo-dao, TenantConfig-nudge-fields, tests-confirm-scaffold]
  affects: [farm_agent.confirm, farm_agent.tenancy.tenant, tests.conftest]
tech_stack:
  added: []
  patterns: [never-throws-dao, sql-conditional-update-guard, db-gated-test-skip]
key_files:
  created:
    - src/farm-agent/farm_agent/confirm/__init__.py
    - src/farm-agent/farm_agent/confirm/confirm_repo.py
    - src/farm-agent/tests/confirm/__init__.py
    - src/farm-agent/tests/confirm/test_confirm_repo.py
  modified:
    - src/farm-agent/farm_agent/tenancy/tenant.py
    - src/farm-agent/tests/conftest.py
decisions:
  - "SQL conditional-UPDATE guards (WHERE...RETURNING id + rowcount check) are the sole correctness mechanism for dup-YES and nudge-race -- not app-level locking"
  - "mark_nudge_sent uses no transaction (pool.connection only) matching Node behavior where markNudgeSent is a plain pool query"
  - "expire_draft branches on reason: edit_cap_exceeded -> needs_review (no expired_at); others -> expired (with expired_at)"
metrics:
  duration: "~10 minutes"
  completed: "2026-06-28"
  tasks_completed: 3
  tasks_total: 3
  files_created: 4
  files_modified: 2
---

# Phase 61 Plan 01: Confirm Repo Foundation Summary

Port of the Node confirm-db.js SQL guards to a Python never-throws DAO, TenantConfig nudge/edit-turns config fields, and DB-gated idempotency + race tests.

## What Was Built

**confirm_repo.py** -- Port of `src/agents/alerter/src/confirm/confirm-db.js`. Never-throws DAO (mirrors capture_repo.py pattern) with 11 public functions over signal_draft and signal_draft_event. All three SQL conditional-UPDATE guards are verbatim from Node ($1 -> %s):

- `confirm_draft`: `WHERE id=%s AND status='awaiting_farmer' RETURNING id`; wraps in conn.transaction() + append_event on rowcount==1.
- `mark_nudge_sent`: `WHERE id=%s AND nudge_sent_at IS NULL RETURNING id`; pool-level only (no transaction).
- `expire_draft`: two variants -- `edit_cap_exceeded` -> needs_review (no expired_at), others -> expired (with expired_at).
- Interval predicates: `(%s || ' minutes')::interval` with str(n) per established codebase pattern.
- mask_number applied to any sender_e164 in logs (T-61-04).

**TenantConfig additions** -- `draft_nudge_fraction: float` (default 0.8 via DRAFT_NUDGE_FRACTION) and `max_edit_turns: int` (default 3 via MAX_EDIT_TURNS). Parsed using existing `_parse_float_env`/`_parse_int_env` helpers. TEST_ENV updated with both values.

**tests/confirm/test_confirm_repo.py** -- DB-gated tests (skip without postgres:14 on :5434):
- `test_dup_yes_idempotency` (SC-2): inserts awaiting_farmer row; calls confirm_draft twice; asserts first rowcount==1, second==0; asserts exactly one signal_draft_event with event='confirmed'.
- `test_concurrent_nudge_race` (SC-3): inserts row with nudge_sent_at NULL; asyncio.gather two mark_nudge_sent calls DIRECTLY (bypasses any asyncio.Lock to test the SQL guard); asserts sorted([r1['rowcount'], r2['rowcount']]) == [0, 1].

**FakeConfirmRepo** added to conftest.py with fake_confirm_repo fixture. All confirm methods record calls, return {ok:True, rowcount:1} by default; find_* return [] or None.

## Deviations from Plan

None -- plan executed exactly as written.

## Known Stubs

None -- no placeholder data or TODO stubs in the created files.

## Threat Flags

None -- no new network endpoints or auth paths introduced. confirm_repo.py makes no farmOS/HTTP calls (scope boundary per Phase 61 plan).

## Self-Check: PASSED

| Check | Result |
|-------|--------|
| src/farm-agent/farm_agent/confirm/confirm_repo.py | FOUND |
| src/farm-agent/farm_agent/confirm/__init__.py | FOUND |
| src/farm-agent/tests/confirm/test_confirm_repo.py | FOUND |
| commit 3711229 (TenantConfig fields) | FOUND |
| commit 0340553 (confirm_repo.py) | FOUND |
| commit 87f8d39 (tests scaffold) | FOUND |
