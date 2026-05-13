---
phase: 39-farmer-confirmation-loop
status: passed
verified_at: 2026-05-13
verifier: gsd-executor (Opus 4.7 1M)
ship_gate: real-prod fixture loaded (D-09a)
test_totals: 538 / 539 alerter suite PASS (1 pre-existing pre-Phase-39 failure on test/config.test.js dashboardUrl drift, unrelated)
---

# Phase 39 verification

Goal-backward sweep against the 5 ROADMAP success criteria.

## Success Criteria

### SC#1: After extraction, farmer receives a human-readable draft summary with YES/NO/EDIT reply instructions

**Verdict:** PASS (verified by automated integration test)

- Renderer (`src/agents/alerter/src/confirm/preview.js` `buildPreviewWithSuffix`) appends `Reply YES to commit, NO to discard, EDIT <text> to amend.` to the Phase 38 preview body and strips `[?]` markers.
- Style locks asserted: no em-dashes, no en-dashes, no `operator` referent (`test/confirm/preview.test.js`).
- Integration scenario 4 confirms the outbound message after an EDIT contains the reply-instruction suffix.

### SC#2: Sending YES once commits the draft; a second YES does not produce a duplicate write in farmOS

**Verdict:** PASS

- Idempotency lives at the state-machine layer (D-02): atomic `UPDATE ... WHERE status='awaiting_farmer' RETURNING id`; rowCount=0 on duplicate = soft re-affirm `send_confirm_idempotent_ack`.
- Integration scenarios 1 and 3 (confirm-db.test.js + integration.test.js).
- Phase 40 will layer its own farmOS idempotency key on top of `draft.id`; Phase 39's responsibility (preventing a second `confirmed` transition) is closed.

### SC#3: NO discards the draft; bot confirms discard; original transcript remains in the Phase 25 capture store for audit

**Verdict:** PASS

- `confirmDb.discardDraft` issues a single conditional UPDATE; outbound `send_discard_ack` body is `"Discarded. Nothing written."`.
- No INSERT/UPDATE/DELETE against signal_capture rows in the discard path (audited via the fake pool, integration scenario 2).
- Phase 38's signal_capture table remains append-only.

### SC#4: EDIT with correction text produces a revised draft; EDIT is accepted at least 3 times before the bot escalates

**Verdict:** PASS

- `edit-handler.js` re-invokes the Phase 38 extractor with `farmerCorrection` plumbed into `buildInitialUserContent` (D-03).
- Cap = 3 (env-configurable `MAX_EDIT_TURNS`). On the 4th EDIT, status flips to `needs_review` with terminal_reason=`edit_cap_exceeded` and the bot sends the cap message.
- Regression test locks the byte-identical behavior of `buildInitialUserContent` when `farmerCorrection` is null/undefined/empty/whitespace (Phase 38 Plan 09 PASS attestation preserved).
- Integration scenarios 4 (one EDIT) and 5 (3 EDITs then cap).

### SC#5: A draft with no response for 30 min gets one ping, then auto-discards with a note; it never auto-commits

**Verdict:** PASS

- Watchdog polls every `DRAFT_WATCHDOG_INTERVAL_MS` (default 60s). At 0.8 * timeout (default 24min), one nudge fires per draft (markNudgeSent's conditional WHERE prevents double-nudge across restarts). At full timeout, status -> `expired` with terminal_reason=`timeout_expired` and the `Draft expired. Nothing was written.` note goes out.
- Never auto-confirms: the state-machine only emits `confirmed` on FARMER_YES. EXPIRE_DUE yields `expired`, not `confirmed` (state-machine.test.js + integration scenarios 6, 7).
- D-04d restart safety: watchdog first tick is awaited before scheduling setInterval (watchdog.test.js).

## Real-prod ship-gate (D-09a)

- Fixture `src/agents/alerter/test/confirm/fixtures/prod-draft-awaiting.json` is derived from `/mnt/mossrock/shared/mushdatadump-prod/2026-05-12_inoc_santi/` (real f1 session). Phone number redacted to synthetic `+15550001234`; `_provenance` block records the substitutions.
- Integration scenario 9 (a/b/c) runs YES, NO, and EDIT (mocked re-extract) through the wired alerter against this fixture. All three pass.
- Curated-only PASS would NOT be sufficient per memory `feedback_real_data_before_ship_gate_pass`. Phase 38 retraction (2026-05-12) is the precedent being honored.

## Style locks

- `grep -rnP '\x{2014}' src/agents/alerter/src/confirm/ .planning/phases/39-farmer-confirmation-loop/39-RUNBOOK.md .planning/phases/39-farmer-confirmation-loop/39-EVAL-REPORT.md` returns empty.
- `fmtNum()` is applied to every farmer-facing number (cap-message count, nudge minutes-remaining).
- Farmer-facing messages address the farmer as "you" (implicit); operator-facing messages address Don Santiago by name (Phase 38 pattern reused unchanged).

## Compose passthrough

`docker-compose.override.yml` adds (Plan 02):
- `DRAFT_PENDING_TIMEOUT_MIN=${DRAFT_PENDING_TIMEOUT_MIN:-30}`
- `DRAFT_NUDGE_FRACTION=${DRAFT_NUDGE_FRACTION:-0.8}`
- `DRAFT_WATCHDOG_INTERVAL_MS=${DRAFT_WATCHDOG_INTERVAL_MS:-60000}`
- `MAX_EDIT_TURNS=${MAX_EDIT_TURNS:-3}`

Memory `feedback_compose_env_passthrough_not_envfile.md` rule satisfied: code reader + container env passthrough shipped in the same plan.

## Deferred / human-needed items

1. **Live-farmer Signal UAT** (`39-RUNBOOK.md`): operator-deferred per Phase 25/37 pattern. Don Santiago dry-runs first, then promotes to farmer #1 / farmer #2. Not blocking ship.
2. **Group-thread confirm replies** (D-06a): out of scope for v1.7. 999.20 sub-part (b).
3. **Live LLM smoke for EDIT loop**: not run as part of Plan 07 (integration tests mock the extractor). If desired, results land in a per-call unique JSONL path per `feedback_persist_paid_results_default`.
4. **2026-05-12 prod session degraded** on the live alerter (whisper 500, schema_invalid after retry). Fixture is hand-reconstructed from the audio narration. When the next clean prod session arrives, refresh via the README procedure.

## Commits

```
ae31c9e plan(39-01): confirm-db.js + idempotent migration + transition helpers
62ffe13 plan(39-02): config knobs + compose passthrough for Phase 39 timeouts and edit cap
<sha>   plan(39-03): pure-function reply parser for YES/NO/EDIT/NOOP classification
<sha>   plan(39-04): confirm-loop state-machine + farmer-text renderer
<sha>   plan(39-05): EDIT re-extraction handler + extractor farmerCorrection plumbing
<sha>   plan(39-06): outbound dispatcher + watchdog + receive-loop branch + startup wiring
735ec54 plan(39-07): integration tests + prod-fixture ship-gate + RUNBOOK + EVAL-REPORT
```

(Use `git log --oneline | head -10` for the canonical list including this VERIFICATION commit.)

## Verdict

**PASS**. All 5 ROADMAP success criteria covered by passing automated tests; D-09a real-prod-fixture ship-gate exercised. Live-farmer UAT deferred to operator per phase convention; not a blocker for the ship attestation. The orchestrator owns the phase transition.
