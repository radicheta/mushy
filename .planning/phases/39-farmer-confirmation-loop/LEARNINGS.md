---
phase: 39-farmer-confirmation-loop
extracted: 2026-05-13
status: shipped (PASS verification 2026-05-13; live-farmer UAT operator-deferred)
---

# Phase 39 Learnings -- Farmer Confirmation Loop

## Decisions made

- **D-01:** First-token classifier on lowercased trimmed body (YES/Y/OK/SI/SÍ -> confirm; NO/N/CANCEL/STOP -> discard; anything else with content -> EDIT). Empty body / pure sticker = no-op. Multi-language for free at minimal cost.
- **D-02:** Idempotency at the state-machine layer, not at farmOS. Atomic `UPDATE ... WHERE status='awaiting_farmer' RETURNING id`; rowCount=0 = idempotent ack. Phase 40 layers its own farmOS-side key on top.
- **D-02a:** Duplicate YES gets a soft re-affirm ("Already locked in -- check the previous message"), not silence. Avoids farmer thinking the bot dropped the YES.
- **D-03 / D-03a:** EDIT re-invokes Phase 38 extractor with `farmerCorrection` as extra context; updated-in-place (no new row); cap = 3 (`MAX_EDIT_TURNS`); 4th edit -> `needs_review` with terminal_reason=`edit_cap_exceeded`.
- **D-03b:** Phase 38 ask-back budget (3) and Phase 39 EDIT budget (3) are independent counters. Farmer gets both budgets.
- **D-04 / D-04a / D-04b:** Timeout = 30min from `updated_at`. Nudge once at 0.8x timeout (24min) with `nudge_sent_at` guard. Full timeout -> `expired`, never auto-`confirmed`.
- **D-04c / D-04d:** Watchdog is a single periodic poller (every 60s), not per-draft setTimeout. Survives restarts because state lives in Timescale. Initial tick is awaited at boot, not just scheduled.
- **D-05:** One renderer shared with Phase 38's preview builder, minus `[?]` markers. "Reply YES / NO / EDIT <text>" suffix appended by `confirm/preview.js`.
- **D-06 / D-06a:** Reply target inherited from `signal_capture.reply_target_kind` (Phase 37); even group-originated drafts get DM confirms (group-thread confirms deferred to 999.20).
- **D-07a:** Append-only `signal_draft_event` table; every transition writes one row keyed by `(draft_id, seq)`.
- **D-09a:** Real-prod fixture mandatory (per Phase 38 lesson). Fixture derived from `2026-05-12_inoc_santi/` with synthetic phone + `_provenance` block.

## Lessons learned

- **The real-prod-fixture rule from Phase 38 was applied prophylactically here** and surfaced no new bugs. Lesson held: curated unit tests pass != production works, but the practice is cheap insurance.
- **`buildInitialUserContent` regression test was worth its weight in gold.** EDIT re-invokes Phase 38's extractor with a new arg (`farmerCorrection`). The byte-identical regression test when `farmerCorrection` is null/undefined/empty/whitespace preserves Phase 38's Plan 09 PASS attestation. Without it, a subtle change here could silently break Phase 38's 95.8% schema conformance.
- **Watchdog restart-safety matters in practice.** fc-core/alerter restarted 6+ times in the prior week; a draft that nudges or expires correctly across a restart is an observable property the operator hits during dogfooding, not an edge case.
- **Compose env passthrough was caught in same commit as code change.** Plan 02 added 4 env vars to both `config.js` and `docker-compose.override.yml`. Memory `feedback_compose_env_passthrough_not_envfile` (forged Phase 36/37) honored prophylactically.

## Patterns worth reusing

- **State-machine idempotency via conditional UPDATE + RETURNING.** `UPDATE signal_draft SET status='confirmed' WHERE id=$1 AND status='awaiting_farmer' RETURNING id`; rowCount=0 is the idempotent path. No app-layer locking, no read-then-write race.
- **Polling watchdog over per-row timer.** Survives restarts. State lives in DB, not memory.
- **Append-only event log keyed by `(parent_id, seq)`.** `signal_draft_event` mirrors `signal_capture` shape. Phase 40 audit query joins on this.
- **Discriminated parser return shape:** `{ ok: true, action, ... } | { ok: false, reply }` (forged in `snooze.js`, reused for confirm-loop parser).
- **Layered idempotency** -- state-machine layer (Phase 39) PLUS farmOS-key layer (Phase 40). Each layer is closed at its own seam; the next phase doesn't have to trust the prior one absolutely.
- **DM-on-confirm even for group-originated drafts** -- avoids the 999.20 group-spam anti-pattern that bit Phase 36 receive verification. "Locked in" is personal; group ack is a UX question, not a state-machine question.

## Surprises

- **538/539 alerter suite green at verification** -- only one failing test (pre-existing `test/config.test.js` dashboardUrl drift carried since 37-01) was unrelated. Cleaner integration than expected for a phase that touches 6 modules + 4 new env vars.
- **9 integration scenarios all green in one shot.** The Phase 38 modular state-machine paid off: each scenario was scripted independently against the real DB + mocked Signal + mocked extractor.
- **No live LLM smoke run despite EDIT being a real LLM round-trip.** Integration tests mock the extractor. The "live LLM smoke" for the EDIT loop is filed as a stretch / next-real-session item, not a blocker.

## Open threads

- **Live-farmer Signal UAT** -- operator-deferred per Phase 25/37 pattern. Don Santiago dry-runs first, then promotes to farmers #1/#2. Not blocking ship.
- **Group-thread confirm replies** (D-06a) -- out of scope for v1.7; 999.20 sub-part (b).
- **Live LLM smoke for EDIT loop** -- if run, results land in per-call unique JSONL path per `feedback_persist_paid_results_default`.
- **2026-05-12 prod session degraded** on the live alerter (whisper 500, schema_invalid after retry). Fixture is hand-reconstructed from audio narration; refresh on next clean session.

## Commits referenced

- `ae31c9e` (Plan 01) -- confirm-db.js + idempotent migration
- `62ffe13` (Plan 02) -- config knobs + compose passthrough
- `735ec54` (Plan 07) -- integration tests + prod-fixture ship-gate + RUNBOOK
