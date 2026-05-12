---
phase: 38
plan: 05
subsystem: alerter / extraction
tags: [extraction, orchestration, pipeline, capture-hook]
requires: [38-01, 38-02, 38-03, 38-04]
provides:
  - extraction-pipeline-orchestrator
  - capture-to-extraction-fire-and-forget-seam
  - outbound-dispatcher-stub-for-plan-06
affects:
  - src/agents/alerter/src/capture.js
  - src/agents/alerter/src/index.js
tech-stack:
  added: []
  patterns:
    - factory-returns-handle
    - never-throw outbound envelope ({ok, reason})
    - fire-and-forget enqueue (.catch(logger.warn))
    - clock injection ({now: () => ms})
    - injected dispatcher (stub now, real Signal sends in Plan 06)
key-files:
  created:
    - src/agents/alerter/src/extraction/pipeline.js
    - src/agents/alerter/src/extraction/index.js
    - src/agents/alerter/test/extraction/integration.test.js
  modified:
    - src/agents/alerter/src/capture.js
    - src/agents/alerter/src/index.js
decisions:
  - Pipeline owns continuity resolution: LLM verdict (append/replace/start_new) overridden by forceStartNewIfIdle when prior draft is >= 30min stale (D-01a hard guard).
  - source_capture_ids extension is a sibling pool.query (raw SQL) because extraction-db.js whitelist intentionally excludes array column writes.
  - Pipeline persists draft FIRST (status=pending), then runs state-machine.transition, then UPDATES with terminal status + farmer_facing_preview before dispatcher fires (R8 ordering invariant).
  - Outbound dispatcher is an injected stub for Plan 05; Plan 06 swaps in the real signal-client send.
  - Capture.js gates the enqueue on farmosPerson != '(unassigned)' so unknown senders never enter the pipeline (T-38-05-02 mitigation).
metrics:
  completed: 2026-05-12
  tasks: 2
  files-touched: 5
---

# Phase 38 Plan 05: Extraction Pipeline Orchestrator + Capture Hook Summary

Compose Plans 02-04 into a single fire-and-forget pipeline that picks up every known-farmer signal_capture row, runs the extractor, persists the draft with the state-machine's verdict, and dispatches the side-effects through a swappable outbound stub.

## What shipped

**`src/agents/alerter/src/extraction/pipeline.js`** -- `createExtractionPipeline({pool, extractor, extractionDb, stateMachine, previewBuilder, config, logger, clock, outboundDispatcher})` returns `{enqueue(captureCtx)}`. The orchestration sequence:

1. `extractionDb.getInFlightForSender(pool, sender)` -- one in-flight draft per sender max (D-02c partial unique index).
2. `stateMachine.forceStartNewIfIdle(inFlight, nowMs, config.draftIdleGapMin)` -- 30min idle cap is the failsafe (D-01a).
3. `extractor.extract({captures, inFlightDraft})` -- LLM tool-use call. Returns `{ok, draft, continuity_decision, per_field_confidence}`.
4. Resolve continuity (LLM verdict, overridden by idle-cap): `append` (extend source_capture_ids on existing draft), `replace` (swap draft_json on existing draft), `start_new` (mark prior in-flight EXPIRED, insert fresh draft with deterministic computeDraftId).
5. `stateMachine.transition(...)` -- pure verdict: `awaiting_farmer | needs_review | expired` + ordered side-effect list (`send_ask_back | send_needs_review_ping | handoff_to_phase_39 | mark_expired | noop`).
6. Build farmer_facing_preview via `previewBuilder.buildPreview` when ask-back path; persist via `updateDraftStatus` with extras.
7. Atomic `advanceAskbackTurn` bump for `send_ask_back` transitions.
8. `outboundDispatcher.dispatch(sideEffect, draftRow)` in order. Plan 06 replaces the stub.

Never throws. Top-level try/catch returns `{ok:false, reason}` so capture.js's `.catch(logger.warn)` seam stays a no-op on the happy path.

**`src/agents/alerter/src/extraction/index.js`** -- barrel re-exports `createExtractionPipeline` plus the four submodules (extractionDb, stateMachine, previewBuilder, extractor) for convenient test wiring.

**`src/agents/alerter/src/capture.js`** -- step 3 hook: after the signal_capture INSERT and farmos_person resolution, fire-and-forget enqueue gated on `farmosPerson && farmosPerson !== '(unassigned)'`. Never awaited; errors caught by `.catch(logger.warn)`. Transcripts wrapped in an array for the pipeline's `transcripts[]` shape.

**`src/agents/alerter/src/index.js`** -- boot constructs a fresh `createExtractor` instance (separate from the alerter-reply `llmClient`), the `outboundDispatcher` stub (Plan 06 replaces), and the `extractionPipeline`. Thread `extractionPipeline` into `createCapturePipeline`.

## Tests

`test/extraction/integration.test.js` -- 8 cases, all green (R1..R8 from plan):

- R1: new sender + ask-back required -> insert + UPDATE awaiting_farmer + `send_ask_back` dispatch
- R2: new sender + complete draft -> UPDATE awaiting_farmer (state-machine emits handoff when askBack==false) + `handoff_to_phase_39` dispatch
- R3: 35min idle -> forceStartNewIfIdle expires prior + inserts new
- R4: 5min ago + LLM 'append' -> UPDATE existing draft (no INSERT)
- R5: extractor `ok:false` -> pipeline `ok:false`, no draft persisted
- R6: 3rd ask-back turn cap -> UPDATE needs_review + `send_needs_review_ping` dispatch
- R7: pool.query throws -> enqueue NEVER throws upward, returns `ok:false`
- R8: farmer_facing_preview persisted via UPDATE before dispatch fires (invocation-order assertion)

Full alerter suite: **387/388 green** (1 pre-existing config.test.js dashboardUrl failure tolerated per plan).

## Deviations from Plan

None of substance. Two minor implementation notes:

1. **source_capture_ids extension uses raw SQL** instead of `updateDraftStatus({source_capture_ids: [...]})` because the extraction-db.js whitelist intentionally rejects array column writes. The pipeline issues a sibling `UPDATE signal_draft SET source_capture_ids = $2 WHERE id = $1` after the whitelist-driven UPDATE. Not a deviation -- the plan didn't constrain the mechanism.
2. **clock injection shape** is `{now: () => ms}` per plan; index.js boot wraps the existing `clock` (which is `Date.now` -- a function) as `{now: () => clock()}` to match the pipeline's expected interface. Both shapes coexist cleanly.

No auth gates, no Rule-1/2/3 fixes triggered.

## Verification

- `cd src/agents/alerter && npx jest test/extraction/integration.test.js` -- 8/8 green
- `cd src/agents/alerter && npm test` -- 387/388 green (1 pre-existing config failure)
- `cd src/agents/alerter && grep "extractionPipeline.enqueue" src/capture.js | grep ".catch"` -- match found (fire-and-forget pattern)
- `cd src/agents/alerter && grep "createExtractionPipeline" src/index.js` -- 2 matches (import + construction)
- `cd src/agents/alerter && grep -c "try" src/extraction/pipeline.js` -- 7 (top-level + per-step)
- `cd src/agents/alerter && grep "ok: false" src/extraction/pipeline.js | wc -l` -- 9 (never-throw envelopes)
- Smoke boot: `timeout 5 node -e "...require('./src/index')"` -- exit=0
- New code added by this plan contains zero em-dashes (`git diff HEAD~3 -- src/capture.js src/index.js | grep "^+" | grep "—"` -- empty). Pre-existing em-dashes in unrelated comments + the Phase-25 farmer-facing degraded reply line are out of scope.

## Commits

- `55baf53` test(38-05): extraction pipeline orchestration (RED)
- `862a73a` feat(38-05): extraction pipeline orchestrator (GREEN)
- `6dddae5` feat(38-05): wire extraction pipeline into capture path

## What's next

Plan 06 replaces the `outboundDispatcher.dispatch` stub with real `signalClient.send` calls that:
- For `send_ask_back`: send the `farmer_facing_preview` text to the routed reply target (DM or group).
- For `send_needs_review_ping`: notify the operator (Santi) that a draft hit the ask-back cap.
- For `handoff_to_phase_39`: no-op in alerter (Phase 39 polls the `signal_draft` table directly for `awaiting_farmer + askBack==false` rows).

## Self-Check: PASSED

- `src/agents/alerter/src/extraction/pipeline.js` -- FOUND
- `src/agents/alerter/src/extraction/index.js` -- FOUND
- `src/agents/alerter/test/extraction/integration.test.js` -- FOUND
- `src/agents/alerter/src/capture.js` -- modified (extractionPipeline hook)
- `src/agents/alerter/src/index.js` -- modified (pipeline construction)
- commit `55baf53` -- FOUND
- commit `862a73a` -- FOUND
- commit `6dddae5` -- FOUND
