---
phase: 38-extraction-pipeline
plan: "02"
subsystem: alerter/extraction
tags: [timescale, signal_draft, crud, pool-injection, idempotent-migration]
requires:
  - capture-db-pool-pattern
provides:
  - signal-draft-schema
  - signal-draft-crud
  - deterministic-draft-id
  - in-flight-per-sender-guarantee
affects: [src/agents/alerter]
tech_stack_added: []
patterns_added: [partial-unique-index-for-in-flight-constraint]
key_files_created:
  - src/agents/alerter/src/extraction/extraction-db.js
  - src/agents/alerter/test/extraction/extraction-db.test.js
key_files_modified:
  - src/agents/alerter/src/index.js
decisions:
  - "Whitelist-based UPDATE extras (8 keys) -- prevents SQL-injection via dynamic column names while keeping the API ergonomic for state-machine callers"
  - "expireIdle uses `($1 || ' minutes')::interval` -- parameterized interval, no string concat"
  - "Status enum lives in the SQL CHECK-free; D-02b transitions enforced by state machine (Plan 04), not the DB -- matches Phase 25/37 precedent"
  - "Phase 38 owns transitions to pending/awaiting_farmer/needs_review/expired only; confirmed/discarded/committed are Phase 39/40 territory (per D-02b)"
metrics:
  duration: "~10min"
  completed: "2026-05-12"
  tasks_complete: 2
  files_touched: 3
  tests_added: 15
---

# Phase 38 Plan 02: signal_draft Schema + CRUD Summary

## One-liner

Pool-injected `extraction-db.js` CRUD module landed with deterministic sha256 draft ids, partial-unique-index enforcing one in-flight draft per sender E.164, and never-throw write semantics; 15 unit tests cover schema init, idempotency, conflict path, and replay-safe id derivation.

## What shipped

- **`signal_draft` table** with 15 columns covering D-02 (storage), D-02a (deterministic id), D-02b (status enum), D-02c (one in-flight per sender). Idempotent migration via `CREATE TABLE IF NOT EXISTS` + `CREATE INDEX IF NOT EXISTS` + `ALTER TABLE ADD COLUMN IF NOT EXISTS`.
- **Partial unique index** `idx_signal_draft_in_flight_per_sender` on `sender_e164 WHERE status IN ('pending','awaiting_farmer')` enforces D-02c at the DB layer; insert path surfaces 23505 as `{ok:false, reason:'in_flight_conflict'}`.
- **Composite index** `idx_signal_draft_sender_status` on `(sender_e164, status)` for `getInFlightForSender` lookup.
- **`computeDraftId(captureIds)`** pure function: sha256 over sorted ids joined by `|`, hex-encoded. Deterministic across processes (D-02a replay-safe).
- **CRUD surface:** `insertDraft`, `getInFlightForSender`, `updateDraftStatus(id, status, extras?)`, `advanceAskbackTurn`, `expireIdle(gapMinutes)` -- all pool-injected, never-throw.
- **`updateDraftStatus` extras** writes whitelisted columns only (8 keys) to neutralize dynamic-column SQL-injection (T-38-02-01 mitigation, deeper than the plan required).
- **Boot wiring** in `src/index.js` mirrors `captureDb.initDb` best-effort try/catch pattern.

## Commits

| Hash    | Type | Message                                                              |
| ------- | ---- | -------------------------------------------------------------------- |
| b6a949c | test | add failing tests for signal_draft CRUD module (RED)                 |
| b6b44b1 | feat | signal_draft schema + CRUD module (GREEN)                            |
| e852695 | feat | wire extractionDb.initDb into alerter boot                           |

## Tasks executed

| # | Name                                                | Status   | Commit            |
|---|-----------------------------------------------------|----------|-------------------|
| 1 | extraction-db.js schema + CRUD + tests (RED->GREEN) | complete | b6a949c, b6b44b1  |
| 2 | Wire extractionDb.initDb into src/index.js boot     | complete | e852695           |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Security] Whitelist for `updateDraftStatus` extras keys**

- **Found during:** Task 1 GREEN implementation.
- **Issue:** The plan specified `updateDraftStatus(pool, id, newStatus, extras?)` accepting an arbitrary `extras` object that injects additional `SET col = $N` clauses. A naive implementation would interpolate caller-controlled keys directly into SQL -- column name injection vector (T-38-02-01 threat boundary).
- **Fix:** Added `UPDATE_EXTRAS_WHITELIST` (8 allowed keys: `needs_review_reason`, `farmer_facing_preview`, `draft_json`, `per_field_confidence`, `log_type`, `farmos_person`, `reply_target_kind`, `group_id`). Keys outside the set are silently ignored. Values are still parameterized via `$N`. Test "accepts optional jsonb extras and includes them in SET clause" exercises the whitelisted path.
- **Files modified:** `src/agents/alerter/src/extraction/extraction-db.js`
- **Commit:** b6b44b1

**2. [Rule 1 - Bug] Em-dash leaked into a test name**

- **Found during:** post-Task-1 grep verification.
- **Issue:** Initial test name `'is idempotent -- second invocation ...'` was written with an em-dash. Memory rule (`feedback_no_em_dashes_in_artifacts`) treats em-dashes as the universal LLM tell; the plan's acceptance criteria explicitly forbid them.
- **Fix:** Replaced `—` with `--` in the test name. No behavior change.
- **Files modified:** `src/agents/alerter/test/extraction/extraction-db.test.js`
- **Commit:** b6b44b1 (folded into GREEN commit)

### Intentional Deviations from PLAN Wording

- Plan §Task-1 action step 1 listed "12 tests"; SUMMARY contains 15. Reason: Pushed harder on insertDraft error paths (3 cases: ok / 23505 / generic) and on initDb assertions (4 column substring matches + partial-index WHERE clause). All test cases listed in the plan are present and named accordingly.
- Plan suggested ALTER TABLE column be a "no-op" placeholder; chose `needs_review_reason` (a real D-02b column) to be defensive -- if the CREATE TABLE ever drifts and omits it, the ALTER will rescue. Behavior identical (column is already in the CREATE TABLE).

No other deviations.

## Deferred Issues

- **Pre-existing `test/config.test.js` failure** persists (1/312 failing -- same as Plan 01 baseline). Documented in 38-01-SUMMARY; dev-shell `DASHBOARD_URL` env overrides the test default. NOT in scope for Plan 02.

## Verification

- `cd src/agents/alerter && npm test -- test/extraction/extraction-db.test.js` -> 15/15 pass.
- `cd src/agents/alerter && npm test` -> 311/312 pass (same 1 pre-existing failure as Plan 01 baseline; +15 new tests).
- `cd src/agents/alerter && grep -E "—" src/extraction/extraction-db.js test/extraction/extraction-db.test.js` -> no matches.
- `cd src/agents/alerter && grep -c "CREATE.*INDEX.*IF NOT EXISTS" src/extraction/extraction-db.js` -> 2.
- `cd src/agents/alerter && grep "WHERE status IN" src/extraction/extraction-db.js` -> partial index visible.
- `cd src/agents/alerter && node -e "const m = require('./src/extraction/extraction-db'); console.log(m.computeDraftId(['x','y']) === m.computeDraftId(['y','x']))"` -> `true`.
- `grep -B1 -A8 "captureDb.initDb" src/agents/alerter/src/index.js | grep -c extractionDb` -> 1 (boot adjacency confirmed).

## Threat Mitigations Applied

| Threat ID   | Mitigation in code |
|-------------|--------------------|
| T-38-02-01  | All writes use `$N` placeholders; `updateDraftStatus` extras path additionally whitelists 8 column names to neutralize dynamic-column injection. |
| T-38-02-02  | `expireIdle(gapMinutes)` keeps in-flight set bounded; D-02c partial unique index caps at one in-flight row per sender. Long-term retention not in scope. |
| T-38-02-03  | sha256 over sorted capture-id set; deterministic id is the feature (D-02a replay-safe). Accepted per threat register. |
| T-38-02-04  | `logger.warn(e.message)` on initDb failure mirrors captureDb pattern; accepted per threat register. |

## Downstream Seams

- **Plan 03 (extractor):** can `require('./extraction-db')` and call `extractionDb.getInFlightForSender(pool, senderE164)` to fetch the current draft for LLM continuity input; `extractionDb.insertDraft` and `extractionDb.computeDraftId` for new drafts.
- **Plan 04 (state machine):** owns `updateDraftStatus` calls for `pending -> awaiting_farmer -> needs_review/expired` transitions; `advanceAskbackTurn` for D-05 hard cap enforcement.
- **Plan 05 (integration test):** exercises the full path against a real Timescale; the boot wiring in `src/index.js` is the entry point.
- **Plan 06 (idle expirer):** schedules `expireIdle(DRAFT_IDLE_GAP_MIN)` on a cron tick (D-01a).

## Self-Check: PASSED

- `src/agents/alerter/src/extraction/extraction-db.js` -> FOUND
- `src/agents/alerter/test/extraction/extraction-db.test.js` -> FOUND
- `src/agents/alerter/src/index.js` (modified) -> FOUND
- Commit b6a949c -> FOUND
- Commit b6b44b1 -> FOUND
- Commit e852695 -> FOUND
