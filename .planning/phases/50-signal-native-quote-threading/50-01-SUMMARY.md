---
phase: 50-signal-native-quote-threading
plan: 01
subsystem: alerter/schema
tags: [schema, signal, quote-threading, idempotent-migration]
requires: []
provides:
  - signal_outbound.signal_msg_ts column (bigint, nullable)
  - idx_signal_outbound_msg_ts partial index (WHERE signal_msg_ts IS NOT NULL)
  - signal_capture.signal_msg_ts column (bigint, nullable)
  - signal_capture.quote_msg_ts column (bigint, nullable)
  - signal_capture.quote_author_e164 column (text, nullable)
affects:
  - Plan 02 (signal.js send + outbound persist) -- writes signal_outbound.signal_msg_ts
  - Plan 03 (outbound-confirm dispatch) -- reads signal_capture.signal_msg_ts
  - Plan 04 (receive-loop persist + quote-resolver) -- writes signal_capture.{signal_msg_ts, quote_msg_ts, quote_author_e164}; reads signal_outbound via idx_signal_outbound_msg_ts
tech-stack:
  added: []
  patterns:
    - Idempotent boot-time migration via ALTER TABLE ... ADD COLUMN IF NOT EXISTS (Phase 37 / Phase 44 D-04 precedent)
    - Partial index on nullable column (small footprint until Plan 02 starts writing)
key-files:
  created: []
  modified:
    - src/agents/alerter/src/outbound-db.js
    - src/agents/alerter/src/capture-db.js
    - src/agents/alerter/test/outbound-db.test.js
    - src/agents/alerter/test/capture-db.test.js
decisions:
  - Quote-resolution index lives on signal_outbound (the lookup side), not signal_capture
  - No data backfill; pre-existing rows remain NULL and resolve via the existing most-recent-active fallback
metrics:
  duration: ~10 min
  completed: 2026-05-23
---

# Phase 50 Plan 01: Schema bedrock for Signal-native quote threading -- Summary

Idempotent ALTERs land four new columns and one partial index across `signal_outbound` and `signal_capture` so Plans 02-04 can persist and resolve Signal-native msg timestamps without a follow-up migration.

## Schema additions

| Table           | Column              | Type   | Owned by    |
|-----------------|---------------------|--------|-------------|
| signal_outbound | signal_msg_ts       | bigint | Plan 02 writer |
| signal_capture  | signal_msg_ts       | bigint | Plan 04 writer |
| signal_capture  | quote_msg_ts        | bigint | Plan 04 writer |
| signal_capture  | quote_author_e164   | text   | Plan 04 writer |

Partial index:

```sql
CREATE INDEX IF NOT EXISTS idx_signal_outbound_msg_ts
  ON signal_outbound (signal_msg_ts)
  WHERE signal_msg_ts IS NOT NULL;
```

The partial `WHERE` keeps the index empty until Plan 02 starts populating the column on every send; mitigation for threat T-50-01-02 (insertOutbound write-path slowdown).

## Idempotency proof

Both `initDb` functions use `ADD COLUMN IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS`. The unit tests run `initDb` twice and assert the second invocation issues the same shape of queries with no exception (`outbound-db.test.js`: 9 -> 18 calls; `capture-db.test.js`: 16 -> 32 calls). Postgres treats both forms as no-ops on the second run.

## Tasks

| Task | Type        | Commits                  | Outcome |
|------|-------------|--------------------------|---------|
| 1    | auto (tdd)  | `0b0bca7` test, `2f8103c` feat | signal_outbound.signal_msg_ts column + partial index landed |
| 2    | auto (tdd)  | `fa7c7a3` test, `e17420b` feat | signal_capture x3 columns landed |

## Verification (plan-stated gates)

- `npx jest test/outbound-db.test.js` -- 9/9 green (column + index + back-compat + idempotency).
- `npx jest test/capture-db.test.js` -- 8/8 green (three columns + back-compat + idempotency).
- Full alerter suite (`npx jest` in src/agents/alerter): 967/967 passed (+ 9 skipped). No regression from the call-count changes.
- `grep -c "signal_msg_ts" src/agents/alerter/src/outbound-db.js` -> 2 (ALTER + CREATE INDEX). Plan required >=2.
- `grep -cE "signal_msg_ts|quote_msg_ts|quote_author_e164" src/agents/alerter/src/capture-db.js` -> 6 (three ALTERs + three doc-comment mentions in the same block).
- `insertOutbound` and `insertCapture` signatures unchanged. Plans 02 and 04 own those edits.

## Deviations from Plan

None. Plan executed exactly as written; both tasks landed in RED -> GREEN sequence with no refactor step (additive ALTERs have nothing to clean up).

## Non-changes (explicit per plan output spec)

- `insertOutbound` parameter list and INSERT column list: unchanged. Plan 02 will add `signal_msg_ts` to the writer.
- `insertCapture` parameter list and INSERT column list: unchanged. Plan 04 will add the three columns to the writer.
- No backfill of historical rows. Existing `signal_outbound` rows have NULL `signal_msg_ts` and remain quote-unresolvable, which is fine per CONTEXT decision -- they are already-acked.

## Known Stubs

None. Columns are intentionally NULL until Plan 02 and Plan 04 wire their writers; this is documented above as the contract handoff, not a stub.

## Threat Flags

None. Schema additions match the threat register; no new exposure surface beyond what `[[STRIDE T-50-01-03]]` already accepted (quote_author_e164 is the same posture as existing signal_capture.sender).

## Self-Check: PASSED

- File `src/agents/alerter/src/outbound-db.js` modified: FOUND (commit 2f8103c).
- File `src/agents/alerter/src/capture-db.js` modified: FOUND (commit e17420b).
- File `src/agents/alerter/test/outbound-db.test.js` modified: FOUND (commit 0b0bca7).
- File `src/agents/alerter/test/capture-db.test.js` modified: FOUND (commit fa7c7a3).
- Commits 0b0bca7, 2f8103c, fa7c7a3, e17420b: all present in `git log --oneline`.
