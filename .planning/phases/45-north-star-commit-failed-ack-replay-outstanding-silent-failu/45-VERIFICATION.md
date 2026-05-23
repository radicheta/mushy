---
phase: 45-north-star-commit-failed-ack-replay-outstanding-silent-failu
verified: 2026-05-23T00:00:00Z
status: human_needed
score: 11/11 code-side must-haves verified (Plans 01-04); 2 requirements (ACK-02, ACK-03) deferred to Plan 05 live-fire UAT
scope: code-side only (Plans 01, 02, 03, 04). Plan 05 (`autonomous: false`) is the live-fire ship-gate and requires prod deploy + Signal interactions with Vikki and Santi.
human_verification:
  - test: "Plan 05 Task 2 pre-flight (in-prod state checks)"
    expected: "(a) docker exec mushy-alerter-1 grep -c send_commit_outcome_ack /app/src/farmos/commit-watchdog.js >=2. (b) signal_draft has outcome_ack_sent_at column on prod. (c) Drafts b8a1e586... and 1fb28e70... still status=commit_failed with outcome_ack_sent_at IS NULL. (d) Dry-run of backfill script renders English, no em-dashes, named address, correct reason phrase."
    why_human: "Requires prod deploy of Plan 04 commit + prod psql + dry-run execution against the live prod alerter DB."
  - test: "Plan 05 Task 3 — live-fire replay draft b8a1e586... (Vikki Rambo)"
    expected: "Backfill script dispatches a single send_commit_outcome_ack via deployed outboundConfirm; Vikki receives a Signal DM containing the failure ack. JSONL written with phases pre/dispatch/post/alerter_log_grep."
    why_human: "Sends a real Signal message to a real farmer. ACK-02 ship-gate."
  - test: "Plan 05 Task 4 — Vikki farmer-paste verification"
    expected: "Vikki pastes back verbatim Signal text; matches rendered body within +/-5 chars; named address 'Vikki,'; reason phrase 'couldn't match a block'; closing 'Send EDIT to fix or NO to drop.'"
    why_human: "Farmer-side attribution per [[feedback_verify_signal_send_attribution]] — only the farmer can confirm receipt of the message."
  - test: "Plan 05 Task 5 — live-fire replay draft 1fb28e70... (Santi LIMA) + idempotency recheck on both drafts"
    expected: "Santi gets dispatched ack. Re-running script on both drafts emits {phase: idempotency_recheck, result: already_sent_skip} and NO second dispatch in alerter logs. ACK-03 + ACK-04 (c) live-fire proof."
    why_human: "Real Signal send to real farmer + cross-check that the deployed CAS primitive prevents double-send under repeat invocation."
  - test: "Plan 05 Task 6 — Santi farmer-paste verification + final NORTH-STAR audit"
    expected: "Santi paste matches rendered body. Prod query: SELECT COUNT(*) FROM signal_draft WHERE status='commit_failed' AND outcome_ack_sent_at IS NULL = 0."
    why_human: "Closes NORTH-STAR violation in prod data; cannot be verified without prod DB + farmer round-trip."
---

# Phase 45: NORTH-STAR commit_failed ack + replay outstanding silent-failure drafts — Verification Report

**Phase Goal:** Every terminal state in the confirm/commit state machine must produce a farmer-facing reply — success AND failure paths. Closes the 2026-05-15 NORTH-STAR violation (Vikki Rambo `commit_failed` on `observation_requires_target` went unreplied after farmer YES).

**Verified:** 2026-05-23
**Status:** `human_needed` — code-side (Plans 01-04) fully verified; Plan 05 live-fire UAT pending farmer interaction.
**Score (code-side):** 11/11 must-have truths verified across Plans 01-04. All artifacts present, substantive, wired, and tests green.

## Scope of this verification

Code-side only. Plan 05 (`autonomous: false`, depends_on: [45-04]) requires:
- Plan 04 deployed to prod alerter container.
- Backfill script run against prod signal_draft.
- Signal-paste verification from Vikki and Santi.
- Final prod-side silent-failure audit.

The user must execute the "Human Verification Required" checklist below before this phase is fully closed.

## Goal Achievement (Code-Side)

### Observable Truths

| #  | Truth (source plan) | Status | Evidence |
|----|---------------------|--------|----------|
| 1  | `signal_draft.outcome_ack_sent_at timestamptz` shipped at boot (P01) | VERIFIED | `commit-db.js:39` `ALTER TABLE signal_draft ADD COLUMN IF NOT EXISTS outcome_ack_sent_at timestamptz` inside `initDb` (renamed from plan's `initCommitSchema` — documented deviation, function identity preserved). |
| 2  | `tryMarkOutcomeAckSent(pool, draftId)` returns 3 distinct shapes — `{ok:true,...}`, `{ok:false, reason:'already_claimed'}`, `{ok:false, reason:'not_found'}` (P01) | VERIFIED | `commit-db.js:191-210`. SELECT-1 existence probe (line 192-195) disambiguates not_found from already_claimed before the CAS UPDATE. CAS uses `WHERE id=$1 AND outcome_ack_sent_at IS NULL RETURNING`. Deviation from plan's "single-statement CAS" is necessary — `rowCount=0` alone cannot distinguish the two failure shapes. Plan-intent preserved. |
| 3  | Concurrent CAS calls converge to exactly one winner (P01) | VERIFIED | SQL semantics + test `tryMarkOutcomeAckSent` 3 unit tests in commit-db.test.js. Behavior locked: first call rowCount=1, second rowCount=0. Mirrored by integration test in commit-watchdog.test.js (truth #5 below). |
| 4  | Renderer module exists, exports `renderOutcomeAck`, `reasonMap`, `reasonFor`; 13 templates pinned (P02) | VERIFIED | `commit-outcome-preview.js` (130 LOC). Imports `sanitizeFarmerText`, `fmtNum`. Tests file: 24 tests, 13 snapshots pinned, all green. Style-lock loops assert no em-dash/en-dash; fallback test proves bare error codes never leak. |
| 5  | 8 failure reason codes mapped to farmer vocab; unknown codes fall back to generic_validation_error (P02) | VERIFIED | `commit-outcome-preview.js:20-29` reasonMap (frozen 8 keys); `reasonFor()` at line 31-36 returns fallback. Test "unknown reason code in failed render uses fallback phrasing, never bare code" passes. |
| 6  | Drafts with status=commit_failed accept EDIT and transition to awaiting_farmer; existing rejections preserved (P03) | VERIFIED | `edit-handler.js:40` adds `commit_failed` to allowed states; `edit-handler.js:49-66` inline `UPDATE ... WHERE id=$1 AND status='commit_failed'` flip. Mirrors existing awaiting_farmer path (extractor → bumpEditTurn → updateDraftAfterEdit → send_preview_resend). 2 new tests in edit-handler.test.js (happy path + still-rejected loop over confirmed/committed/discarded). |
| 7  | T4 commit_success dispatches `send_commit_outcome_ack` exactly once (P04) | VERIFIED | `commit-watchdog.js:108` calls `_maybeDispatchOutcomeAck(lockedRow, 'success')` immediately after `auditLogger.logCommit('commit_success', ...)`, before the early `return`. Test "T4 commit_success dispatches send_commit_outcome_ack exactly once" passes. |
| 8  | T6 commit_failed (terminal) dispatches once with outcome=failed+reason (P04) | VERIFIED | `commit-watchdog.js:122-123` after `markFailed` + `auditLogger.logCommit('commit_failed', ...)`. Failure reason: `result.reason || 'generic_validation_error'`. Locked test for HTTP 422 terminal failure with reason='observation_requires_target'. |
| 9  | Two concurrent ticks on same draft → exactly one ack sent (ACK-04) (P04) | VERIFIED | `_maybeDispatchOutcomeAck` gates on CAS claim at `commit-watchdog.js:46`. Test "ACK-04 idempotency: two sequential ticks ... exactly one dispatch" passes. |
| 10 | T5 commit_attempt_retry does NOT dispatch (P04) | VERIFIED | `commit-watchdog.js:112-116` retry branch returns without invoking `_maybeDispatchOutcomeAck`. Only T4 (line 108) and T6 (line 123) hook. Negative test "T5 commit_attempt_retry (transient): no dispatch" passes. |
| 11 | Every ack send writes a signal_outbound row with intent='commit_outcome_ack', tenant_id='mossrock', related_draft_id=draftId (P04 + Phase 44 D-14) | VERIFIED (via deviation) | Achieved via `safeSend(..., 'commit_outcome_ack')` at `outbound-confirm.js:146`. signal.js's existing D-14 single-hook persistence writes ONE row per send tagged with the intent override. No double-write (confirmed by absence of any second `outboundDb.insertOutbound` call in outbound-confirm.js). Deviation documented in 45-04-SUMMARY.md. |

**Score:** 11/11 code-side truths verified.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/agents/alerter/src/farmos/commit-db.js` | outcome_ack_sent_at migration + tryMarkOutcomeAckSent helper | VERIFIED | Migration at line 39, helper at lines 191-210, exported at line 222. |
| `src/agents/alerter/src/farmos/commit-outcome-preview.js` | renderOutcomeAck + reasonMap + reasonFor | VERIFIED | 130 LOC, pure functions, 24 tests green, 13 snapshots pinned. |
| `src/agents/alerter/src/confirm/edit-handler.js` | Option X transition `commit_failed → awaiting_farmer` | VERIFIED | JS state guard at line 40; inline UPDATE at lines 49-66 with race-aware rowCount=0 handling. |
| `src/agents/alerter/src/farmos/commit-watchdog.js` | T4 + T6 dispatch hooks gated by CAS claim | VERIFIED | `_maybeDispatchOutcomeAck` helper at lines 39-62; T4 hook at line 108; T6 hook at line 123; outboundConfirm accepted at line 24 (defaults to null for legacy tests). |
| `src/agents/alerter/src/confirm/outbound-confirm.js` | send_commit_outcome_ack case + safeSend intentOverride | VERIFIED | renderOutcomeAck imported line 22; case at lines 122-151; safeSend extended at line 41-50 to accept intentOverride. |
| `src/agents/alerter/src/confirm/confirm-db.js` | findAwaitingForSender includes commit_failed for receive-loop reachability | VERIFIED | Query at line 249: `status IN ('awaiting_farmer','commit_failed')` with explicit ORDER BY preference. Bonus follow-on Plan 04 shipped beyond plan scope but logically required for the EDIT-from-commit_failed path to be reachable from real Signal replies. |
| `src/agents/alerter/src/index.js` | outboundConfirm passed into createCommitWatchdog | VERIFIED | Line 359 `outboundConfirm: confirmOutbound,` inside the createCommitWatchdog call site (matches sketch + deviation note re drift from line 347-356). |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| commit-watchdog.js | commit-db.js tryMarkOutcomeAckSent | `commitDb.tryMarkOutcomeAckSent(pool, lockedRow.id)` | WIRED | Line 46. Claim gates dispatch. |
| commit-watchdog.js | outbound-confirm.js | `outboundConfirm.dispatch('send_commit_outcome_ack', lockedRow, extras)` | WIRED | Line 58. Graceful degrade if outboundConfirm null (line 52). |
| outbound-confirm.js | commit-outcome-preview.js | `require('../farmos/commit-outcome-preview')` + `renderOutcomeAck(...)` | WIRED | Line 22 import + line 141 call. |
| outbound-confirm.js | signal_outbound (Phase 44 table) | safeSend → signal.js D-14 single-hook persistence with `intent: 'commit_outcome_ack'` | WIRED (via deviation) | Line 146 `safeSend(body, dm, draftId, 'commit_outcome_ack')`. signal.js writes exactly one row; no double-write from outbound-confirm. |
| index.js | commit-watchdog.js | `outboundConfirm: confirmOutbound` kwarg | WIRED | Line 359. |
| confirm-db.findAwaitingForSender | receive-loop.js (EDIT path on commit_failed drafts) | SQL extended to include commit_failed | WIRED | Line 249. 2 new tests lock the IN-list behavior + preference ordering. |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full alerter test suite green | `cd src/agents/alerter && npm test` | 835 passed / 9 skipped / 0 failures across 64 suites; 13 snapshots passed | PASS |
| outbound-confirm + commit-watchdog load without syntax error | `node -e "require('./src/confirm/outbound-confirm'); require('./src/farmos/commit-watchdog')"` (per 45-04-SUMMARY) | OK | PASS (per SUMMARY verification block; not re-run as suite covers it) |
| Snapshot file has 13 entries (Plan 02) | `ls test/farmos/__snapshots__/commit-outcome-preview.test.js.snap` + suite output `Snapshots: 13 passed` | 13 | PASS |
| ACK-02 / ACK-03 live-fire | (requires prod deploy + farmer Signal) | n/a | SKIP — routed to human verification |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| ACK-01 | 02, 03, 04 | No terminal state in confirm/commit machine is silent post-YES (enumerated and tested) | SATISFIED (code-side) | T4 + T6 hooks present in commit-watchdog.js; T5 confirmed not-hooked by negative test; 5 commit-watchdog tests + 24 renderer tests + 9 edit-handler tests cover the enumeration. Live-fire confirmation pending Plan 05. |
| ACK-02 | 05 | Replay of draft b8a1e586... (Vikki Rambo) produces English failure ack | NEEDS HUMAN | Plan 05 is `autonomous: false`. Requires Signal-paste verification from Vikki. |
| ACK-03 | 05 | Replay of draft 1fb28e70... (Santi LIMA) likewise | NEEDS HUMAN | Plan 05 is `autonomous: false`. Requires Signal-paste verification from Santi. |
| ACK-04 | 01, 04 | Idempotency: retried commit does not double-send the ack | SATISFIED (code-side) | CAS primitive (commit-db.js) + integration test "two sequential ticks ... exactly one dispatch" + crash-after-claim leaves draft marked (truth #9 + test 3 in commit-watchdog.test.js). Repeat-invocation (case c) live-fire proof pending Plan 05. |

### Spot-Check of SUMMARY-Claimed Deviations

| Deviation | Claim | Verified? |
|-----------|-------|-----------|
| P01: tryMarkOutcomeAckSent uses SELECT-1 probe + CAS UPDATE for 3 return shapes | Required because pure CAS rowCount=0 cannot distinguish not_found from already_claimed | VERIFIED at commit-db.js:192-209. Implementation matches description; necessary for the contract. |
| P01: function name `initDb` not `initCommitSchema` | Plan text used outdated name | VERIFIED — `initDb` at commit-db.js, no rename done (correct surgical choice). |
| P04: signal_outbound write via signal.js D-14 hook with intentOverride, not a duplicate write in outbound-confirm | Avoids double-row per ack | VERIFIED — outbound-confirm.js:146 passes `'commit_outcome_ack'` as intentOverride to safeSend; no `outboundDb.insertOutbound` call exists inside the `send_commit_outcome_ack` case. |
| P04: farmosLink optional/undefined tolerated | Plan 02 renderer must accept undefined farmosLink | VERIFIED at commit-outcome-preview.js:95-96 — only appends link clause when `typeof opts.farmosLink === 'string' && opts.farmosLink.trim() !== ''`. outbound-confirm.js:132-136 leaves farmosLink undefined when farmos_response.link absent. |
| P04: T5 commit_attempt_retry NOT hooked | Only terminal states dispatch acks | VERIFIED — commit-watchdog.js:112-116 retry branch returns without calling _maybeDispatchOutcomeAck. Negative test locks this. |
| P04 bonus: findAwaitingForSender extended to include commit_failed | Plan 03's EDIT path was code-reachable but unreachable from real Signal replies without this | VERIFIED at confirm-db.js:249 — `status IN ('awaiting_farmer','commit_failed')` with preference ordering. 2 unit tests in confirm-db.test.js. |

### Anti-Patterns Found

None blocking. No TBD/FIXME/XXX markers introduced by this phase in the modified files. No empty implementations. No hardcoded empty data in user-visible render paths.

Notes (informational):
- `outcome_ack_sent_at` is not indexed. Per Plan 01 design decision: "the column is queried only via the CAS UPDATE in Task 2, never scanned." Acceptable.
- Graceful-degrade path (`outboundConfirm not wired`) marks the draft via CAS but does not send. Documented trade-off: ≤1 dropped ack rather than ever double-sending. Acceptable per CONTEXT.md decision.
- One known gap that is explicitly Plan 05 scope: Plan 04 deployment to prod alerter container is required before Plan 05 can run. SUMMARY 04 references this in its "Next: deploy + Plan 05 live-fire" closing note.

## Human Verification Required

Plan 05 (`autonomous: false`, depends_on: [45-04]) is the ship-gate. The user must execute the following before the phase can be marked closed.

### 1. Plan 05 pre-flight (in-prod state checks)

**Test:**
- Deploy Plan 04 changes to prod alerter container (commit SHA recorded by Plan 04).
- `docker exec mushy-alerter-1 grep -c send_commit_outcome_ack /app/src/farmos/commit-watchdog.js` → expect ≥2.
- `docker exec mushy-timescale-1 psql -U postgres -d alerter -c "\d signal_draft" | grep outcome_ack_sent_at` → expect 1 line.
- `docker exec mushy-timescale-1 psql -U postgres -d alerter -c "SELECT id, status, commit_failed_reason, outcome_ack_sent_at, sender_e164 FROM signal_draft WHERE id LIKE 'b8a1e586%' OR id LIKE '1fb28e70%';"` → both rows present, status=commit_failed, outcome_ack_sent_at IS NULL.
- Run backfill script in dry-run mode against both drafts; inspect rendered bodies.

**Expected:** English text, no em-dashes, named address ("Vikki," / "Santi" or "Don Santiago"), reason phrase = "couldn't match a block" for Vikki's observation_requires_target draft, closing affordance "Send EDIT to fix or NO to drop."

**Why human:** Requires prod deploy + access to prod psql + execution of script against live prod DB.

### 2. Plan 05 live-fire — Vikki Rambo draft b8a1e586...

**Test:** Run `node scripts/phase-45-backfill-outcome-acks.js --draft-id <full-vikki-id>` (NO dry-run flag) appending to 45-05-live-fire-vikki-rambo.jsonl.

**Expected:** JSONL with phase=pre, dispatch, post entries. `docker logs mushy-alerter-1 --since 5m | grep send_commit_outcome_ack` shows one dispatch line. outcome_ack_sent_at column flips from NULL to a timestamp for Vikki's draft.

**Why human:** Sends a real Signal DM to a real farmer. ACK-02 ship-gate per [[feedback_real_data_before_ship_gate_pass]].

### 3. Plan 05 — Vikki farmer-paste verification

**Test:** Ping Vikki on Signal asking her to paste back the bot's message; record verbatim into JSONL `phase: farmer_paste`.

**Expected:** Paste matches the rendered body the script logged (length within ±5 chars, named address "Vikki,", "couldn't match a block", "Send EDIT to fix or NO to drop.").

**Why human:** Farmer-side attribution per [[feedback_verify_signal_send_attribution]] — only the farmer can confirm receipt.

### 4. Plan 05 live-fire — Santi LIMA draft 1fb28e70... + idempotency recheck on both

**Test:** Same as #2 for Santi. Then re-run script on BOTH drafts to prove repeat-invocation idempotency (ACK-04 case c).

**Expected:** Santi dispatch line appears in alerter logs. Re-runs emit `{phase: idempotency_recheck, result: already_sent_skip}` and NO new dispatch lines (grep count = 1 per draft over the 5-minute window).

**Why human:** Real Signal send + prod-side cross-check that the deployed CAS prevents double-send.

### 5. Plan 05 — Santi farmer-paste verification + final NORTH-STAR audit

**Test:** Santi pastes back the message; verify against rendered body. Then `docker exec mushy-timescale-1 psql -U postgres -d alerter -c "SELECT COUNT(*) FROM signal_draft WHERE status='commit_failed' AND outcome_ack_sent_at IS NULL;"`.

**Expected:** Count = 0 in prod. Both 2026-05-15 silent failures closed.

**Why human:** Final prod-data audit + Santi Signal round-trip.

## Gaps Summary

No code-side gaps. All 11 must-have truths across Plans 01-04 are VERIFIED. All artifacts exist, are substantive (renderer 130 LOC, helpers exported), are wired (imports + dispatch + CAS gating verified), and data flows (real DB queries in helpers, real signal send via safeSend → signal.js single-hook write). Full alerter test suite is 835 passed / 9 skipped / 0 failures. 13 snapshots pinned.

The only remaining work is Plan 05 live-fire UAT — explicitly marked `autonomous: false` in its frontmatter — which requires:
1. Deploy of Plan 04 commits to prod alerter container.
2. Execution of the backfill script against prod signal_draft.
3. Two Signal-paste round-trips with Vikki and Santi.
4. Final prod-side silent-failure audit (expected COUNT(*) = 0).

These are the standard end-of-phase human checkpoints the planner deliberately deferred from inline `checkpoint:human-verify` blocks to avoid the executor cold-start cost. They are listed above as "Human Verification Required" items.

---

_Verified: 2026-05-23_
_Verifier: Claude (gsd-verifier)_
_Mode: code-side verification (Plans 01-04); Plan 05 routed to human_
