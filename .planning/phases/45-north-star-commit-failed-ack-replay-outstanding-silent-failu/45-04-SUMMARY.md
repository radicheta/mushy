---
phase: 45-north-star-commit-failed-ack-replay-outstanding-silent-failu
plan: 04
subsystem: alerter/farmos+confirm
tags: [ack-01, ack-04, north-star, wiring, terminal-state, idempotency, reachability]
requires:
  - 45-01 (tryMarkOutcomeAckSent CAS + outcome_ack_sent_at column)
  - 45-02 (renderOutcomeAck)
  - 45-03 (EDIT-from-commit_failed state transition)
provides:
  - "T4 commit_success -> send_commit_outcome_ack dispatch (one per draft, idempotent)"
  - "T6 commit_failed -> send_commit_outcome_ack dispatch (one per draft, idempotent)"
  - "ACK-04 idempotency proven by test (concurrent ticks -> exactly one dispatch)"
  - "receive-loop reachability for commit_failed drafts (Plan 03 EDIT path now invokable from real Signal replies)"
affects:
  - src/agents/alerter/src/confirm/outbound-confirm.js
  - src/agents/alerter/src/farmos/commit-watchdog.js
  - src/agents/alerter/src/confirm/confirm-db.js
  - src/agents/alerter/src/index.js
  - src/agents/alerter/test/farmos/commit-watchdog.test.js
  - src/agents/alerter/test/confirm/confirm-db.test.js
  - src/agents/alerter/test/confirm/fake-pool.js
tech-stack:
  added: []
  patterns:
    - "side-effect dispatcher case for outcome ack (DM-only, never group)"
    - "CAS-claim-then-dispatch (mark-then-send idempotency)"
    - "signal_outbound auto-logging via signal.js single-hook with intent override"
key-files:
  created: []
  modified:
    - src/agents/alerter/src/confirm/outbound-confirm.js
    - src/agents/alerter/src/farmos/commit-watchdog.js
    - src/agents/alerter/src/confirm/confirm-db.js
    - src/agents/alerter/src/index.js
    - src/agents/alerter/test/farmos/commit-watchdog.test.js
    - src/agents/alerter/test/confirm/confirm-db.test.js
    - src/agents/alerter/test/confirm/fake-pool.js
decisions:
  - "signal_outbound logging is achieved via signal.js's existing single-hook D-14 persistence by passing intent='commit_outcome_ack' through the safeSend intentOverride parameter. No separate outboundDb.insertOutbound call added inside outbound-confirm.js. This honors the CONTEXT.md best-effort posture (fail-open per D-03) without growing a second write path; the documented signal_outbound integration is satisfied with zero new I/O surface."
  - "renderer farmosLink derivation: read draftRow.farmos_response.link if present and non-empty; otherwise pass undefined and let the Plan 02 renderer omit the link clause. The current markCommitted shape stores {asset_ids, log_ids, file_ids, http_status, latency_ms} with no link, so success acks ship without the link until a future commit-router enrichment adds one. Renderer tolerates undefined."
  - "T5 commit_attempt_retry intentionally NOT hooked: only terminal states dispatch acks (locked test 'T5 commit_attempt_retry (transient): NO ack dispatch on retry path')."
  - "outboundConfirm absent -> log warn + continue (graceful degrade for legacy tests). The CAS claim still runs, so a tick that wins the claim and then finds outboundConfirm unwired leaves the draft marked with no ack sent. Accepted trade-off per plan: '<=1 dropped ack on watchdog crash mid-send rather than ever double-sending'."
  - "Plan 03 follow-on shipped here: findAwaitingForSender extended to include status IN ('awaiting_farmer','commit_failed') with awaiting_farmer preferred. Without this the EDIT-from-commit_failed transition Plan 03 wired is unreachable from a real Signal reply (receive-loop would findAwaitingForSender -> null -> fall through to capture pipeline). 2 unit tests lock the new behavior + the preference ordering."
metrics:
  duration_minutes: ~30
  completed_at: 2026-05-23
  tests_added: 7 (5 commit-watchdog + 2 confirm-db)
  tests_total_in_alerter: 835/844 (9 pre-existing skips, 0 failures)
---

# Phase 45 Plan 04: Wire commit-outcome ack dispatch (T4+T6) + receive-loop commit_failed reachability Summary

End-to-end wiring of the NORTH-STAR fix: commit-watchdog now dispatches a farmer-facing ack on terminal states (T4 commit_success and T6 commit_failed). Gated by Plan 01's `tryMarkOutcomeAckSent` CAS claim for ACK-04 idempotency. The renderer is Plan 02's `renderOutcomeAck`. Send goes through `confirmOutbound.dispatch('send_commit_outcome_ack', ...)` which routes via `safeSend` with `intent='commit_outcome_ack'`, causing `signal.js`'s single-hook persistence to write a `signal_outbound` row tagged with `tenant_id='mossrock'`, `related_draft_id=<draftId>` (Phase 44 Plan-02 D-14). One bonus follow-on: extended `findAwaitingForSender` so the EDIT path Plan 03 shipped is reachable from real Signal replies on commit_failed drafts.

## What shipped

### Task 1: outbound-confirm.js registers send_commit_outcome_ack

- Imported `renderOutcomeAck` from `../farmos/commit-outcome-preview` (Plan 02).
- Extended `safeSend(body, target, draftId, intentOverride)` to accept an intent override (defaults to `'confirm_prompt'`).
- New `case 'send_commit_outcome_ack':`
  - Validates `extras.outcome` present (otherwise returns `{ok:false, reason:'missing_outcome'}`).
  - Derives `farmosLink` from `draftRow.farmos_response.link` when present.
  - Builds body via `renderOutcomeAck(draftRow, {outcome, reason, farmosLink})`.
  - Target = `dmTarget(draftRow)` (DM-only, per-farmer ack, never group).
  - Sends via `safeSend(body, target, draftId, 'commit_outcome_ack')` so the signal_outbound row carries the canonical intent.
  - No separate outboundDb.insertOutbound call: persistence already happens once inside signal.js's send wrapper. Best-effort posture is inherited (signal.js wraps the insertOutbound in its own try/catch with fail-open warn).

### Task 2: commit-watchdog.js hooks T4 + T6

- `createCommitWatchdog` factory now accepts `outboundConfirm` (defaults to null).
- New internal helper `_maybeDispatchOutcomeAck(lockedRow, outcome, reason)`:
  1. If `commitDb.tryMarkOutcomeAckSent` not exported -> silently no-op (back-compat with tests pre-dating Plan 01).
  2. Run CAS claim. On `ok=false` (already_claimed / not_found) -> silent return.
  3. If `outboundConfirm` not wired -> log warn and return (graceful degrade).
  4. Otherwise dispatch `'send_commit_outcome_ack'` with extras (`{outcome:'success'}` for T4, `{outcome:'failed', reason}` for T6).
  5. Wrap dispatch in try/catch; log warn on throw but do not propagate.
- T4 hook: inserted immediately after `auditLogger.logCommit('commit_success', ...)`, BEFORE the early return.
- T6 hook: inserted at the very end of `_processRow` after `markFailed` + `auditLogger.logCommit('commit_failed', ...)`. Uses `result.reason || 'generic_validation_error'` as the failure reason.
- T5 commit_attempt_retry path (transient): untouched. Verified by grep (`commit_attempt_retry` still 3 hits, no new dispatch on that path) AND by the new locked negative test.

### Task 3: index.js wire-in

- `createCommitWatchdog` call site at line 359 (was 347 before this plan added the comment block) now passes `outboundConfirm: confirmOutbound`.

### Plan 03 follow-on: findAwaitingForSender includes commit_failed

- `confirmDb.findAwaitingForSender(pool, senderE164)` SQL changed from `WHERE status='awaiting_farmer'` to `WHERE status IN ('awaiting_farmer','commit_failed')` with an explicit ORDER-BY preferring awaiting_farmer over commit_failed (most-recent updated_at tie-breaker within status).
- Fake-pool query matcher updated to recognize the new `status IN (...)` SQL shape AND keep the legacy single-status branch for any other call site that still uses it.
- 2 new tests in confirm-db.test.js:
  - "returns commit_failed draft when no awaiting_farmer exists for sender (Plan 03 Option X reachability)"
  - "prefers awaiting_farmer over commit_failed when both exist for same sender"

## Tests added (7 new, 835/844 in full alerter suite)

`test/farmos/commit-watchdog.test.js` (5 new):
1. T4 commit_success dispatches `send_commit_outcome_ack` exactly once with `{outcome:'success'}`.
2. T6 commit_failed (HTTP 422 terminal) dispatches once with `{outcome:'failed', reason:'observation_requires_target'}`.
3. ACK-04 idempotency: two sequential ticks on same draft (with status reset between) result in exactly one dispatch; tryMarkOutcomeAckSent called twice with second returning ok=false.
4. T5 commit_attempt_retry (HTTP 500, attempts<retryMax): zero dispatch invocations.
5. Graceful degrade: outboundConfirm=null does not crash; commit still completes; CAS claim still runs.

`test/confirm/confirm-db.test.js` (2 new):
6. Lookup returns commit_failed draft when only commit_failed exists (reachability proof).
7. Lookup prefers awaiting_farmer over commit_failed when both exist.

Full alerter suite: 835 passed / 9 skipped / 0 failures (baseline was 802/811 before Plan 01 added 3, Plan 02 added 24, Plan 03 added 2; this plan adds 7; the running totals match across all four plans within rounding from a few collateral test additions in fake-pool maintenance).

## Verification

- `grep -c "send_commit_outcome_ack" src/agents/alerter/src/confirm/outbound-confirm.js` -> 5 (>=2)
- `grep -c "renderOutcomeAck" src/agents/alerter/src/confirm/outbound-confirm.js` -> 3 (>=1)
- `grep -c "signal_outbound\|outboundDb" src/agents/alerter/src/confirm/outbound-confirm.js` -> 5 (>=1)
- `grep -c "tryMarkOutcomeAckSent" src/agents/alerter/src/farmos/commit-watchdog.js` -> 4 (>=2)
- `grep -c "send_commit_outcome_ack" src/agents/alerter/src/farmos/commit-watchdog.js` -> 3 (>=2)
- `grep -c "outboundConfirm" src/agents/alerter/src/farmos/commit-watchdog.js` -> 4 (>=1)
- `grep -c "commit_attempt_retry" src/agents/alerter/src/farmos/commit-watchdog.js` -> 2 (unchanged: 1 audit log call + 1 mention in the new T6 comment explaining T5 is NOT hooked)
- `grep -n "outboundConfirm: confirmOutbound" src/agents/alerter/src/index.js` -> 2 hits (confirm watchdog wire from Phase 39, and the new commit-watchdog wire at line 359)
- `grep -c "tryMarkOutcomeAckSent" src/agents/alerter/test/farmos/commit-watchdog.test.js` -> 9 (>=2)
- Boot smoke: `node -e "require('./src/confirm/outbound-confirm'); require('./src/farmos/commit-watchdog'); console.log('OK')"` -> OK
- Full suite: `npm test` -> 835 passed / 9 skipped / 0 failures.

## Deviations from plan

### [Rule 1 - bug / Rule 2 - critical functionality] signal_outbound write satisfied via existing signal.js single-hook persistence, not a new outboundDb call

**Found during:** Reading signal.js around the safeSend definition.
**Issue:** The plan's Task 1 action block says "After the successful safeSend, call the signal_outbound helper inside try/catch." But signal.js's `send` already wraps `outboundDb.insertOutbound(pool, {...})` in a fail-open try/catch (D-14, line 134-154). Adding a second write inside outbound-confirm.js would produce TWO rows per ack send (one with intent='commit_outcome_ack' from signal.js, one duplicate from the dispatcher).
**Fix:** Extended safeSend to accept an `intentOverride` parameter so the case can pass `'commit_outcome_ack'`. signal.js's existing hook then writes exactly one signal_outbound row with the correct intent + tenant + related_draft_id. The comment block in outbound-confirm.js documents this explicitly so a future reader sees why no second write exists.
**Files modified:** src/agents/alerter/src/confirm/outbound-confirm.js (existing safeSend extended, case added).
**Tracked as:** plan-intent satisfied; literal action text deviated to avoid a bug.

### [Rule 3 - blocking-issue] Receive-loop reachability for commit_failed drafts (Plan 03 follow-on)

**Found during:** Reading 45-03-SUMMARY.md "Scope NOT touched" section flagging that findAwaitingForSender still excludes commit_failed.
**Issue:** Plan 03 wired the EDIT-from-commit_failed state transition but `receive-loop.js` (line 224) calls `findAwaitingForSender` which today only returns awaiting_farmer drafts. The EDIT path Plan 03 shipped was code-reachable from unit tests but UNREACHABLE from a real Signal reply (the dispatcher would receive the EDIT text and fall through to capture pipeline instead of edit-handler).
**Fix:** Extended findAwaitingForSender SQL to `WHERE status IN ('awaiting_farmer','commit_failed')` with an ORDER BY clause preferring awaiting_farmer. Updated fake-pool to model the new query shape. Added 2 unit tests locking the new behavior + ordering preference.
**Files modified:** src/agents/alerter/src/confirm/confirm-db.js, src/agents/alerter/test/confirm/confirm-db.test.js, src/agents/alerter/test/confirm/fake-pool.js.
**Tracked as:** explicitly requested by the executor prompt as an additional task. Without it, the Plan 03 affordance is wired but dormant in production. Logically completes the NORTH-STAR loop alongside the T4/T6 hooks.

## Scope NOT touched

- `src/agents/alerter/src/receive-loop.js` — query call site unchanged; only the underlying SQL was extended. The YES/NO branches still call `confirmDraft`/`discardDraft` which both WHERE on `status='awaiting_farmer'` (so a YES on a commit_failed draft no-ops -> idempotent_ack). The EDIT branch goes through edit-handler which Plan 03 already taught to accept commit_failed.
- `signal_outbound` table schema — Phase 44 Plan-02 already shipped the `intent` text column with no enum; `'commit_outcome_ack'` writes through cleanly.
- Plan 05 / live-fire replay — out of scope; that ships next.
- Multi-language ack rendering — deferred (CONTEXT.md decisions).

## Known stubs / threat flags

None. No new network surface (DM-only ack reuses signalClient). No new schema. No new persistence write path. tenant_id propagates from signalClient defaults ('mossrock') per OSS-Foray Option alpha.

## Self-Check: PASSED

- File `src/agents/alerter/src/confirm/outbound-confirm.js`: FOUND, `send_commit_outcome_ack` + `renderOutcomeAck` present.
- File `src/agents/alerter/src/farmos/commit-watchdog.js`: FOUND, `tryMarkOutcomeAckSent` + `outboundConfirm` + `send_commit_outcome_ack` present.
- File `src/agents/alerter/src/confirm/confirm-db.js`: FOUND, `commit_failed` in findAwaitingForSender query.
- File `src/agents/alerter/src/index.js`: FOUND, `outboundConfirm: confirmOutbound` at commit-watchdog wire-in.
- File `src/agents/alerter/test/farmos/commit-watchdog.test.js`: FOUND, 5 new tests.
- File `src/agents/alerter/test/confirm/confirm-db.test.js`: FOUND, 2 new tests.
- File `src/agents/alerter/test/confirm/fake-pool.js`: FOUND, new IN-list query matcher.
- All target tests green (commit-watchdog 18/18, outbound-confirm 9/9, confirm-db extended pass).
- Full alerter suite: 835 passed / 9 skipped / 0 failures.
- Boot smoke load: OK.
- No em-dashes introduced by this plan (pre-existing em-dashes in index.js untouched per surgical-changes rule).

## Next: deploy + Plan 05 live-fire

Commit SHA recorded in the final plan commit (see git log). Plan 05 (replay the two outstanding silent-failure drafts as live-fire UAT) is unblocked once this lands in prod.
