---
date: 2026-05-17
phase: 45
task: NORTH-STAR commit_failed reply audit + sketch
reference: .planning/notes/2026-05-17-northstar-commit-failed-reply.md, feedback_no_silent_failure_after_farmer_confirm
status: read-only analysis + sketch (ready for Phase 45 planning)
---

# NORTH-STAR Ack Sketch: commit_failed Silent Failure Fix

## 1. Terminal State Map (commit-watchdog.js)

Audit of `/mnt/slime-kingdom/opt/mushy/src/agents/alerter/src/farmos/commit-watchdog.js` line 34-88 (_processRow):

| # | State Path | Status Code | Farmer Ack Today | Needs Fix |
|---|---|---|---|---|
| T1 | No-op idempotent (cache hit) | commit_idempotent_noop (L38) | none | no |
| T2 | Backoff gate skip | (pre-lock return L53) | none | no |
| T3 | Lock race lost | (return L59) | none | no |
| T4 | **Commit success** | commit_success (L76) | none (logged only) | **YES (new)** |
| T5 | Transient error + retries left | commit_attempt_retry (L82) | none | no (transient) |
| T6 | **Commit failed (terminal)** | commit_failed (L87) | **SILENT** | **YES (NORTH-STAR violation)** |
| T7 | Stale lock release | commit_stale_released (L95) | none | no (operator signal) |

**Finding:** Only T4 and T6 require farmer replies. T6 (`commit_failed` at line 86-87) is the known NORTH-STAR violation. T4 (`commit_success`) should also ack for symmetry.

## 2. Commit Attempt Site & Fix Location

**File:** `/mnt/slime-kingdom/opt/mushy/src/agents/alerter/src/farmos/commit-watchdog.js`

**Lines 34-88** (_processRow method):
- Line 66: `const result = await commitRouter.commit(...)`
- Line 68-77: Success path (has logging, no farmer reply)
- Line 80-84: Transient retry path (has logging, no farmer reply)
- Line 86-87: **Terminal failure path (SILENT)** — this is where the fix hooks

**Smallest fix anatomy:**
1. After line 76 (commit_success log): hook `confirmOutbound.dispatch('send_commit_outcome_ack', row)` with outcome='success'
2. After line 87 (commit_failed log): hook `confirmOutbound.dispatch('send_commit_outcome_ack', row)` with outcome='failed', reason from result
3. Add idempotency gate: before sending, call `tryMarkOutcomeAckSent(draftId)` to claim the ack slot
4. Plumb `confirmOutbound` into createCommitWatchdog at `index.js:308-317` (currently missing)

**Idempotency:** `signal_draft.outcome_ack_sent_at timestamptz` (new column via migration). Mark-then-send: claim with UPDATE WHERE outcome_ack_sent_at IS NULL, then send. If claim returns null (another tick already won the race), exit. If send fails, draft stays marked (accept one dropped ack to prevent double-send).

## 3. Message Strategy

Reuse `confirmOutbound.dispatch` mechanism (already handles Signal send, audit, retries, pacing). New side-effect: `send_commit_outcome_ack` with extras={outcome, reason, draftId}.

**Template shape (from notes):**
- Success: "Saved {log_type} for {target}. Open in farmOS: {link}"
- Failure: "Couldn't save {log_type}: {reason in farmer vocab}. Send EDIT to fix or NO to drop."

Reason->farmer-vocab map (8 failure codes):
- observation_requires_target -> "Couldn't match a block"
- schema_invalid -> "Data format issue"
- farmos_unreachable -> "Farm server down"
- (others per notes section 3)

**Style locks:** No em-dashes (sanitizeFarmerText), round numbers (fmtNum), named address. English-only for same-week patch; multi-language deferred to v1.7.x.

## 4. Optional State-Machine Change

**Option X (recommended):** Add transition `commit_failed -> EDIT -> awaiting_farmer` in `confirm/edit-handler.js` (~30 LOC) so the ack's "Send EDIT to fix" affordance is truthful. Requires 1 edit-handler test.

**Option Y (fallback):** Soften ack phrasing to "Reply EDIT and I'll re-extract" without promising same EDIT verb. Requires 0 code changes; degrades semantic clarity.

## 5. Implementation Scope

**Files touched:**
- `/mnt/slime-kingdom/opt/mushy/src/agents/alerter/src/farmos/commit-watchdog.js` (T4+T6 dispatch hooks)
- `/mnt/slime-kingdom/opt/mushy/src/agents/alerter/src/farmos/commit-outcome-preview.js` (NEW: 150 LOC + 13 snapshots)
- `/mnt/slime-kingdom/opt/mushy/src/agents/alerter/src/farmos/commit-db.js` (tryMarkOutcomeAckSent helper + migration ~15 LOC)
- `/mnt/slime-kingdom/opt/mushy/src/agents/alerter/src/index.js:308-317` (wire confirmOutbound into createCommitWatchdog, 1 line)
- `/mnt/slime-kingdom/opt/mushy/src/agents/alerter/src/confirm/edit-handler.js` (Option X: ~30 LOC + 2 tests)
- Test: `test/farmos/commit-watchdog.test.js` (3 integration tests for T4 + T6 paths)
- Test: `test/farmos/commit-outcome-preview.test.js` (NEW: 13 snapshot tests)
- Test: `test/confirm/edit-handler.test.js` (Option X: 2 new tests)

**Size estimate:** M (~1.5 days) — 5 tasks, each ~3-5 hours. Ship as v1.7.x bug-fix.

**Dependencies:** None (confirmOutbound already built in index.js; only needs plumbing). No schema breaking changes.

## 6. Idempotency Proof Sketch

Scenario: watchdog crashes mid-send after claiming the ack slot.
1. First tick: tryMarkOutcomeAckSent returns draft_id (claim won)
2. Send fails (Signal down)
3. Restart: draft still status='committed', outcome_ack_sent_at IS NOT NULL
4. Second tick: tryMarkOutcomeAckSent returns null (claim lost)
5. Exit silently (draft already marked; another process won the race or already sent)

Scenario: concurrent ticks on same draft.
1. Tick A: tryMarkOutcomeAckSent wins (outcome_ack_sent_at := now)
2. Tick B: tryMarkOutcomeAckSent loses (null return)
3. Tick B exits; only Tick A sends

Walks 9 scenarios per notes section 4 — all converge to zero double-sends.

## 7. Backfill Path

Two live 2026-05-15 silent failures need acks:
- Vikki Rambo `b8a1e586...` (observation_requires_target)
- Santi LIMA `1fb28e70` (unknown, likely similar)

After shipping the fix, replay both with the new render + dispatch path as integration tests + live-fire UAT. Doubles as proof that ack infrastructure works end-to-end.

## 8. Open Questions (Phase 45 scope)

1. Confirm Option X (add commit_failed -> EDIT transition) vs Option Y (soften ack phrasing)? Recommend X for semantic clarity.
2. Ship order: this fix BEFORE schema normalizer (Option A from 2026-05-16-schema-audit.md) so normalizer behavior is observable from farmer side.
3. Operator-side alert on commit_failed (per feedback_alerter_needs_meta_watchdog)? Could fold into plumbing but defer to Phase 46.

---

**Ready for Phase 45 planning. No blockers. Sketch is implementation-ready.**
