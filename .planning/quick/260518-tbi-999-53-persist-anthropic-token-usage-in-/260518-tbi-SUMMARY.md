---
phase: 999.53-persist-anthropic-token-usage
plan: 01
quick_task: 260518-tbi
type: execute
tags: [alerter, cost-visibility, anthropic, signal_capture, observability]
requires:
  - signal_capture table (Phase 25, Phase 37 D-14/D-15 routing cols)
  - llm-client.compose() (Phase 25-04 R5)
  - extraction pipeline (Phase 38 Plan 05)
provides:
  - 5 nullable token/model cols on signal_capture
  - v_llm_cost_daily aggregating per UTC day with sonnet-4-6 pricing
  - capture-path Step 7 UPDATE binds token usage
  - extraction-path post-resolve UPDATE binds token usage
affects:
  - src/agents/alerter/src/capture-db.js
  - src/agents/alerter/src/llm-client.js
  - src/agents/alerter/src/capture.js
  - src/agents/alerter/src/extraction/pipeline.js
key-files:
  created:
    - src/agents/alerter/test/extraction/pipeline.test.js
  modified:
    - src/agents/alerter/src/capture-db.js
    - src/agents/alerter/src/llm-client.js
    - src/agents/alerter/src/capture.js
    - src/agents/alerter/src/extraction/pipeline.js
    - src/agents/alerter/test/capture-db.test.js
    - src/agents/alerter/test/llm-client.test.js
    - src/agents/alerter/test/capture.test.js
decisions:
  - Stamp model='claude-sonnet-4-6' literal in pipeline.js UPDATE (extractor does not echo model back); matches extractor.js:101 default
  - usage:null skips UPDATE entirely on extraction path (avoid all-null writes that would dirty v_llm_cost_daily counts)
  - UPDATE failure on extraction path is logged + swallowed via logger.warn; pipeline result stays ok:true (consistent with rest of pipeline's never-degrade-on-side-effect policy)
  - capture.js Step 7 stays gated on llmOk (compose ok:false still skips UPDATE)
metrics:
  duration: 12min
  tasks: 3
  files: 7
  completed: 2026-05-18
---

# Phase 999.53 Plan 01: Persist Anthropic Token Usage Summary

One-line: 5 nullable token/model cols + v_llm_cost_daily view on signal_capture, with both alerter LLM call sites (capture reply + extraction) writing tokens + model back so $/day spend becomes a single SELECT instead of a call-count estimate.

## What shipped

**Schema (Task 1, commit 2f23b9e)**
- 5 new nullable cols on signal_capture: input_tokens int, output_tokens int, cache_creation_input_tokens int, cache_read_input_tokens int, model text
- CREATE OR REPLACE VIEW v_llm_cost_daily per UTC day with sum() of each token col, count(*) of calls, and approx_usd computed from sonnet-4-6 pricing ($3 / $15 / $3.75 / $0.30 per MTok)
- initDb query count: 6 -> 12; idempotent across re-runs (24 queries over two invocations, same shape)

**Capture path (Task 2, commit 75c91ac)**
- llm-client.compose() success branch now returns {ok, text, usage, model} (was {ok, text}); usage is msg.usage pass-through; model falls back to configured model when SDK omits
- capture.js carries llmUsage + llmModel from compose result into Step 7 UPDATE
- Step 7 UPDATE rewritten to 8-param form: llm_reply, degraded, 4 token cols, model, id; missing/partial usage binds null without throwing
- Degraded LLM path (compose ok:false) preserves prior behavior: no UPDATE issued

**Extraction path (Task 3, commit a3ec164)**
- pipeline.js stamps usage on signal_capture by captureId immediately after extractor.extract() resolves ok:true with non-null usage; runs before continuity branching so both legacy single-draft and batch (Plan 08 multi-draft) paths get the stamp
- Best-effort: UPDATE failure logged via logger.warn and swallowed; pipeline still returns ok:true
- usage:null skips the UPDATE (avoid dirtying v_llm_cost_daily with all-null rows)
- ok:false (degraded extractor) skips the UPDATE

## Verification

- Task 1: `npx jest test/capture-db.test.js` -- 7/7 pass
- Task 2: `npx jest test/llm-client.test.js test/capture.test.js` -- 28/28 pass
- Task 3: `npx jest test/extraction/pipeline.test.js test/extraction/pipeline-image-wire.test.js` -- 6/6 pass (Plan 09 image-wire regression guard still green)
- Full suite: `npx jest` -- 702 passed, 8 skipped, 0 failed (57 of 58 suites; one suite skipped pre-existing)

## Manual sanity (post-deploy, NOT in this plan)

After the next alerter container restart picks up these changes:

```
psql -d telemetry -c "\d signal_capture"   # verify 5 new cols + model
psql -d telemetry -c "SELECT * FROM v_llm_cost_daily LIMIT 5;"
```

The view returns one row per UTC day for days where at least one new capture has been processed by the updated alerter. Backfill of the 64 existing NULL rows is out of scope per ROADMAP 999.53.

## Deviations from Plan

**1. [Rule 1 - test regex bug] Initial capture.test.js assertions failed to match Step 7 UPDATE**
- **Found during:** Task 2 GREEN re-run
- **Issue:** The plan-suggested regex `/UPDATE signal_capture SET llm_reply/` doesn't match because the new multi-line UPDATE has whitespace (newline + indent) between `signal_capture` and `SET`.
- **Fix:** Tightened the regex to `/UPDATE signal_capture\s+SET llm_reply/` (and the symmetric `\s+SET input_tokens` in pipeline.test.js)
- **Files modified:** src/agents/alerter/test/capture.test.js, src/agents/alerter/test/extraction/pipeline.test.js
- **Commit:** rolled into 75c91ac (Task 2) and a3ec164 (Task 3)

No other deviations. No architectural changes required. No auth gates encountered.

## Out of scope (per ROADMAP 999.53)

- Backfill of 64 existing NULL signal_capture rows (the report-style $5.26 estimate already covers them)
- Cost-threshold alerting (separate conversation)
- Per-farmer cost breakdown view (ad-hoc `GROUP BY sender` works against the new cols)
- Separate extraction_runs table (deferred until extractor grows multiple call sites)

## Self-Check: PASSED

Files verified to exist:
- FOUND: src/agents/alerter/src/capture-db.js (5 ALTERs + v_llm_cost_daily DDL)
- FOUND: src/agents/alerter/src/llm-client.js (success branch returns usage + model)
- FOUND: src/agents/alerter/src/capture.js (Step 7 8-param UPDATE)
- FOUND: src/agents/alerter/src/extraction/pipeline.js (post-resolve usage stamp)
- FOUND: src/agents/alerter/test/extraction/pipeline.test.js (5 new tests)

Commits verified via `git log --oneline -5`:
- FOUND: 2f23b9e feat(999.53-01): add 5 token cols + v_llm_cost_daily view
- FOUND: 75c91ac feat(999.53-02): capture path persists Anthropic token usage on Step 7 UPDATE
- FOUND: a3ec164 feat(999.53-03): extraction pipeline stamps token usage on signal_capture by captureId
