# Phase 45: NORTH-STAR commit_failed ack + replay outstanding silent-failure drafts — Context

**Gathered:** 2026-05-23
**Status:** Ready for planning
**Mode:** Auto (`--auto`); decisions pre-locked in `.planning/notes/2026-05-17-northstar-*.md`

<domain>
## Phase Boundary

Every terminal state in the confirm/commit state machine MUST produce a farmer-facing reply — success AND failure paths. Closes the 2026-05-15 NORTH-STAR violation (Vikki Rambo `commit_failed` on `observation_requires_target` went unreplied after farmer YES). After shipping the fix, replay the two outstanding silent-failure drafts as live-fire UAT.

In scope:
- T4 `commit_success` → new structured farmer ack (today: logged-only).
- T6 `commit_failed` (terminal) → new farmer ack (today: SILENT — the NORTH-STAR violation).
- Reuse `confirmOutbound.dispatch` as the send mechanism (already handles Signal send, audit, retries, pacing).
- New renderer `commit-outcome-preview.js` with 5 log_types × 2 outcomes (10) + 3 farm-level no-target variants.
- `signal_draft.outcome_ack_sent_at timestamptz` for mark-then-send idempotency.
- State transition `commit_failed → EDIT → awaiting_farmer` so the failure ack's "Send EDIT to fix" affordance is truthful (Option X).
- Backfill / live-fire UAT: replay drafts `b8a1e586…` (Vikki Rambo, observation_requires_target) + `1fb28e70…` (Santi LIMA) through the fixed path.

Out of scope (deferred):
- Multi-language ack rendering (English-only for same-week patch; multi-language deferred to v1.7.x or later).
- Operator-side meta-watchdog alert on commit_failed (per `[[feedback_alerter_needs_meta_watchdog]]`) — deferred.
- Schema normalizer (Option A) already shipped in Phase 43 (`6c4ec9b8`-era schema-normalizer landed 2026-05-16). No order dependency remains.
- Logging acks into the new `signal_outbound` table — Phase 44 shipped 2026-05-23; this phase MAY log into `signal_outbound` if cheap, but it is not a ship-gate (see decisions below).
</domain>

<decisions>
## Implementation Decisions

### Send mechanism
**Reuse `confirmOutbound.dispatch` with a new side-effect kind `send_commit_outcome_ack`.**
Why: already handles Signal send, audit logging, retry, pacing, sanitizeFarmerText, fmtNum. No need to grow a second send path.
Locks: `[[feedback_no_em_dashes_in_artifacts]]`, `[[feedback_round_farmer_numbers]]`.

### Idempotency
**New column `signal_draft.outcome_ack_sent_at timestamptz`. Mark-then-send semantics.**
Sequence: `tryMarkOutcomeAckSent(draftId)` (conditional UPDATE WHERE outcome_ack_sent_at IS NULL RETURNING draft_id) → if null exit; else render → dispatch. On send failure, draft stays marked.
Trade: accept ≤1 dropped ack on watchdog crash mid-send rather than ever double-sending. 9 concurrency scenarios walked in the sketch — all converge to zero double-sends.

### State machine: commit_failed → EDIT (Option X)
**Add transition `commit_failed → EDIT → awaiting_farmer` in `confirm/edit-handler.js`.**
Why: the failure ack copy says "Send EDIT to fix"; the affordance must be truthful. ~30 LOC + 2 tests. Re-runs Phase 38 extractor on `farmerCorrection`, mirroring the existing EDIT path from `awaiting_farmer`.
Rejected alternative (Option Y): soften phrasing to "Reply EDIT and I'll re-extract" — degrades EDIT verb's semantic clarity.

### Language
**English-only for same-week patch.**
Why: prod traffic this week is English (Don Santiago, Vikki Rambo — Vikki English-first per `[[farmer-language-stacks]]`). Multi-language is a v1.7.x follow-on; not a ship-gate.

### Ack templates
**5 log_types × 2 outcomes = 10 templates + 3 farm-level "no-target" variants.**
Shape:
- Success: `"Saved {log_type} for {target}. Open in farmOS: {link}"`
- No-target success (farm-level): `"Saved as a general farm note since I couldn't match a specific block. Send EDIT to attach a block if you want."`
- Failure: `"Couldn't save {log_type}: {reason in farmer vocab}. Send EDIT to fix or NO to drop."`

Reason → farmer-vocab map (8 codes): `observation_requires_target`, `no_target_asset_for_activity`, `asset_not_found`, `duplicate_log`, `farmos_unreachable`, `schema_invalid`, `taxonomy_term_missing`, `generic_validation_error`. Render via `sanitizeFarmerText` + `fmtNum`. No em-dashes. Named address.

### signal_outbound integration (light)
**Log every ack send to the Phase 44 `signal_outbound` table (intent = `commit_outcome_ack`, related_draft_id = draftId, tenant_id = `mossrock`).**
Why: Phase 44 shipped; logging acks there gives Phase 37 prompt's `lastBotOutbound` awareness of our own outbound traffic and bolsters the OSS-Foray Option α tenant-aware-from-day-one rule. Not a ship-gate — if it adds risk, defer.
Locks: `[[project_2026_05_17_oss_foray_alpha_lock.md]]`.

### Backfill / live-fire UAT
**Replay drafts `b8a1e586…` (Vikki Rambo) + `1fb28e70…` (Santi LIMA) through the fixed render+dispatch path. Doubles as integration test fixture AND the actual farmer ack that closes the 2026-05-15 NORTH-STAR violation in production.**
Backfill MUST be idempotent (uses same `outcome_ack_sent_at` claim) so a retry does not double-send.
Live-fire is the ship-gate (per `[[feedback_unit_tests_dont_catch_wiring]]` + `[[feedback_real_data_before_ship_gate_pass]]`).

### Persist live-fire results
**Save pre-fix vs post-fix transcripts as named siblings under `.planning/phases/45-…/`** per `[[feedback_keep_paper_trail_of_intermediates]]` + `[[feedback_persist_paid_results_default]]`.

### Wiring point
`createCommitWatchdog` call site is now at `src/agents/alerter/src/index.js:347-356` (drifted from the sketch's `308-317` after Phase 44 added signal_outbound plumbing). Add `outboundConfirm: confirmOutbound` to the kwargs.
</decisions>

<canonical_refs>
## Canonical References (MUST read before planning)

- `.planning/notes/2026-05-17-northstar-commit-failed-reply.md` — full design pass (terminal-state map T1-T9, reuse decisions, plan sketch S1+M1+M2+M3+S2 with size estimates)
- `.planning/notes/2026-05-17-northstar-ack-sketch.md` — implementation-ready sketch (commit-watchdog.js line-by-line audit, file-path index, idempotency proof sketch)
- `.planning/notes/2026-05-16-schema-audit.md` — pairing context (Option A normalizer Phase 43 — already shipped)
- `.planning/notes/2026-05-17-oss-foray-decision.md` — tenant-aware lock for any new schema (`outcome_ack_sent_at` is a column add on existing table; no tenant_id owed)
- Memory: `[[feedback_no_silent_failure_after_farmer_confirm]]` — the rule this phase implements
- Memory: `[[feedback_hard_rules_relaxed_when_farmer_is_santi]]` — rule still binds for Vikki/Selina; Santi-only relaxation does NOT cover this fix
- Memory: `[[project_2026_05_15_vikki_rambo_unscripted_run.md]]` — origin incident
- Memory: `[[feedback_keep_paper_trail_of_intermediates]]` + `[[feedback_persist_paid_results_default]]` — live-fire artifact persistence
- Memory: `[[feedback_unit_tests_dont_catch_wiring]]` — live-fire is the real ship-gate
- Memory: `[[feedback_no_em_dashes_in_artifacts]]` + `[[feedback_round_farmer_numbers]]` — copy style locks

## ROADMAP-named requirements

ACK-01 — no terminal state in the confirm/commit machine is silent post-YES (enumerated and tested)
ACK-02 — replay of draft `b8a1e586…` (Vikki Rambo) produces an English-default farmer-facing reply on the failure path
ACK-03 — replay of draft `1fb28e70…` (Santi LIMA) likewise
ACK-04 — idempotency: a retried commit does not double-send the ack
</canonical_refs>

<code_context>
## Existing Code Insights

**Wire-in point (1 line):** `src/agents/alerter/src/index.js:347-356`
The `createCommitWatchdog({...})` call is missing `outboundConfirm`. Add it.

**Terminal-state hook points:** `src/agents/alerter/src/farmos/commit-watchdog.js`
- L76 (commit_success — T4): hook `confirmOutbound.dispatch('send_commit_outcome_ack', row, {outcome:'success'})`
- L87 (commit_failed — T6): hook with `{outcome:'failed', reason}`
- L82 (commit_attempt_retry): NO hook — transient.

**New files:**
- `src/agents/alerter/src/farmos/commit-outcome-preview.js` — renderer (~150 LOC + 13 snapshot tests).
- Migration for `signal_draft.outcome_ack_sent_at timestamptz`.

**Touched:**
- `src/agents/alerter/src/farmos/commit-db.js` — add `tryMarkOutcomeAckSent(draftId)` helper.
- `src/agents/alerter/src/confirm/edit-handler.js` — Option X transition `commit_failed → EDIT → awaiting_farmer` (~30 LOC + 2 tests).
- `src/agents/alerter/src/confirm/outbound-confirm.js` — register `send_commit_outcome_ack` side-effect kind.

**Reuse helpers:** `sanitizeFarmerText`, `fmtNum`, `confirmOutbound.dispatch`.

**Existing tests to read for shape:**
- `src/agents/alerter/test/farmos/commit-watchdog.test.js` — extend with T4 + T6 ack assertions.
- `src/agents/alerter/test/confirm/edit-handler.test.js` — extend with Option X cases.
- Snapshot test convention seen in Phase 39/43 — use for the 13 ack templates.

**Phase 44 plumbing now available:** `signal_outbound` table with `tenant_id`, `intent`, `related_draft_id` TEXT columns (per commit `44e96b7`-era schema). Acks can be logged here.
</code_context>

<specifics>
## Specific Ideas

- Plan size: M (~1.5 days), 5 tasks: S1 (migration), M1 (templates+renderer), M2 (EDIT transition), M3 (wiring + dispatch hooks), S2 (integration tests + backfill replay).
- Each plan should be vertical-slice-shippable where possible (S1 ships alone; M1 ships alone with snapshot tests; M3 is where the user-visible behavior lights up).
- The two replay drafts are real production drafts in the live `signal_draft` table — handle as a one-time backfill task, NOT a recurring catch-up sweep (out of scope).
- Live-fire ship-gate: send the two real acks to the two real farmers (Vikki, Santi) and get farmer-paste verification per `[[feedback_verify_signal_send_attribution]]`.
- ACK-04 idempotency test must cover: (a) two concurrent watchdog ticks on same draft, (b) crash-after-claim-before-send, (c) repeat backfill invocation.
</specifics>

<deferred>
## Deferred Ideas

- Multi-language ack rendering (Vikki/Selina language stacks per `[[farmer-language-stacks]]`).
- Operator-side meta-watchdog alert on commit_failed (per `[[feedback_alerter_needs_meta_watchdog]]`).
- Generalized "any terminal state needs ack" framework — this phase covers commit_success + commit_failed only.
- Alerter TZ Montevideo + hhmm() local-time rendering (already on backlog from Phase 46).
</deferred>
