---
phase: 54-backfill-harness-dev-farmos-smoke-20-pages
plan: 03
subsystem: alerter/backfill
tags: [v1.11, backfill, paid-llm, persistence, back-07]
requires: [bulk-backfill-short-circuit, summaries-log-writer]
provides: [extractor-onllmcall-observer, responses-jsonl-writer, run-id-collision-guard, cost-estimate-rate-table]
affects: [src/agents/alerter/scripts/, src/agents/alerter/src/extraction/]
tech_added: []
patterns: [opt-in-sidecar-observer, sync-fs-writes-per-call-for-evidence-durability, per-run-collision-guard]
files_created: []
files_modified:
  - src/agents/alerter/src/extraction/extractor.js
  - src/agents/alerter/test/extraction/extractor.test.js
  - src/agents/alerter/scripts/backfill-notebook.js
  - src/agents/alerter/scripts/backfill-notebook.test.js
key_decisions:
  - "Observer hook is opt-in via createExtractor({onLlmCall}); existing call sites (pipeline, eval harness) omit it and see zero behavior change. Live capture paths are untouched."
  - "callWithObserver wraps every client.messages.create — both initial and schema-retry — in a finally block so failed requests still fire the observer with error populated (T-54-09: lost-LLM-call-evidence mitigation)."
  - "Observer errors caught + logged warn; never propagate out of extract() (T-54-12)."
  - "Cost-rate constants documented inline with 2026-05-24 date: Sonnet 3/15 per MTok, Haiku 0.80/4.00 per MTok. Rate-drift correction is a deferred concern."
  - "runIdExistsGuard exits 6 if responses.jsonl already present in the runDir — honors [[feedback_never_overwrite_paid_live_api_results]]. Empty dirs allowed (manual retry after failed bootstrap)."
  - "fs.writeSync (synchronous) on every observation — guarantees evidence is on-disk before extract() returns. No buffered writes."
  - "Bootstrap ordering tightened: runIdExistsGuard → openResponsesJsonl → openSummariesLog → createFarmosClient → pipelineFactory(onLlmCall) → loop. responsesFd closed in the same finally as summariesFd."
metrics:
  duration_minutes: 22
  completed: 2026-05-24
  tasks_completed: 2
  files_changed: 4
---

# Phase 54 Plan 03: Extractor observer + responses.jsonl writer Summary

Wired an opt-in `onLlmCall(observation)` hook into createExtractor. The hook fires once per Anthropic call (both initial and schema-retry) with `{ts, captureId, model, input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens, latency_ms, raw_response, request_hash, error}`. Backfill harness installs the hook only when `--bulk-backfill` is active + non-dry-run; the observer serializes each observation as one JSON line into `<runDir>/responses.jsonl` (append-only, synchronous fs.writeSync). `runIdExistsGuard` refuses to start (exit 6) when the runDir already contains a `responses.jsonl`. Cost estimate (Sonnet 3/15, Haiku 0.80/4.00 per MTok) added to each line.

## Verification

- 55 hermetic tests in scripts/backfill-notebook.test.js (+8 vs Plan 02).
- 31 hermetic tests in extractor.test.js (+5 vs baseline) — covers happy-path observation shape, retry firing, observer-throw isolation, regression check (no onLlmCall = no behavior change), per-request hash uniqueness.
- Full alerter suite: 1213 pass / 9 skipped / 0 fail (+15 vs Plan 02).
- Observer fires for both initial + retry calls (verified hermetically).

## Deviations from Plan

- **[Rule 3 - Blocking issue] Bootstrap ordering fix**: plan implied runIdExistsGuard runs alongside other guards, but the pre-existing structure had pipeline bootstrap BEFORE responses.jsonl was opened. Restructured so runIdExistsGuard runs before any fd is opened or any factory invoked, and responses.jsonl/summaries.log fds are closed on every failure path. The pipelineFactory now receives `onLlmCall` so its extractor instance can attach the observer.

## Self-Check: PASSED
- FOUND: src/agents/alerter/src/extraction/extractor.js (onLlmCall + callWithObserver)
- FOUND: src/agents/alerter/scripts/backfill-notebook.js (Plan 03 helpers, runIdExistsGuard, responses.jsonl writer)
