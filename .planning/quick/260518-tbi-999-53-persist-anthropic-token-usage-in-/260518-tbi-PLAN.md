---
phase: 999.53-persist-anthropic-token-usage
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - src/agents/alerter/src/capture-db.js
  - src/agents/alerter/src/llm-client.js
  - src/agents/alerter/src/capture.js
  - src/agents/alerter/src/extraction/pipeline.js
  - src/agents/alerter/test/capture-db.test.js
  - src/agents/alerter/test/llm-client.test.js
  - src/agents/alerter/test/capture.test.js
  - src/agents/alerter/test/extraction/pipeline.test.js
autonomous: true
requirements:
  - 999.53

must_haves:
  truths:
    - "New captures land with non-NULL token counts in signal_capture"
    - "Extractor calls UPDATE signal_capture token cols by captureId on resolve"
    - "v_llm_cost_daily returns one row per UTC day with approx_usd populated"
    - "initDb is idempotent across re-runs (existing rows + columns survive)"
  artifacts:
    - path: "src/agents/alerter/src/capture-db.js"
      provides: "5 new nullable cols + v_llm_cost_daily view DDL in initDb"
      contains: "v_llm_cost_daily"
    - path: "src/agents/alerter/src/llm-client.js"
      provides: "compose() returns {ok,text,usage,model}"
    - path: "src/agents/alerter/src/capture.js"
      provides: "Step 7 UPDATE binds 5 new cols from compose result"
    - path: "src/agents/alerter/src/extraction/pipeline.js"
      provides: "Post-extractor UPDATE signal_capture by captureId with usage cols"
  key_links:
    - from: "src/agents/alerter/src/capture.js"
      to: "signal_capture"
      via: "UPDATE llm_reply + token cols"
      pattern: "UPDATE signal_capture SET llm_reply"
    - from: "src/agents/alerter/src/extraction/pipeline.js"
      to: "signal_capture"
      via: "UPDATE input_tokens, output_tokens, cache_*, model"
      pattern: "UPDATE signal_capture SET input_tokens"
---

<objective>
Persist Anthropic token usage in `signal_capture` for $/day cost visibility (backlog 999.53).

Purpose: We have no usage telemetry today; the credit-exhaust outage of 2026-05-17 was invisible. Every alerter LLM call site currently drops `msg.usage`, so prod spend can only be estimated from call counts.
Output: 5 new nullable columns on `signal_capture` + `v_llm_cost_daily` view; both alerter call sites (capture reply + extraction) write tokens + model back to the capture row.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/ROADMAP.md

@src/agents/alerter/src/capture-db.js
@src/agents/alerter/src/llm-client.js
@src/agents/alerter/src/capture.js
@src/agents/alerter/src/extraction/pipeline.js
@src/agents/alerter/src/extraction/extractor.js
@src/agents/alerter/test/capture-db.test.js
@src/agents/alerter/test/extraction/extractor.test.js

<interfaces>
Current shape of compose() in src/agents/alerter/src/llm-client.js (lines 64-86):
  returns { ok: true, text } | { ok: false, reason }
  needs to extend success branch to: { ok: true, text, usage: msg.usage, model: msg.model }
  where msg.usage = { input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens }

Current Step 7 UPDATE in src/agents/alerter/src/capture.js (lines 197-206):
  UPDATE signal_capture SET llm_reply = $1, degraded = $2 WHERE id = $3
  must extend to bind 5 new cols from r (compose result captured in Step 4).

extractor.js already returns usage on the result object (extractor.js:206 -- result.usage =
  { input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens }).
Model is fixed at 'claude-sonnet-4-6' (extractor.js:101) -- stamp it explicitly in the
pipeline UPDATE since the extractor result does not currently echo it back.

initDb pattern (capture-db.js:5-35) uses plain ALTER TABLE ... ADD COLUMN IF NOT EXISTS
per-query. The existing initDb test asserts pool.query.toHaveBeenCalledTimes(6); adding
5 new ALTERs + 1 CREATE VIEW will bump that to 12.

Pricing for sonnet-4-6 per backlog: input=$3/MTok, output=$15/MTok,
cache_creation=$3.75/MTok, cache_read=$0.30/MTok.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Schema -- add 5 nullable cols + v_llm_cost_daily view in initDb</name>
  <files>src/agents/alerter/src/capture-db.js, src/agents/alerter/test/capture-db.test.js</files>
  <behavior>
    - initDb issues 5 new ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS statements: input_tokens int, output_tokens int, cache_creation_input_tokens int, cache_read_input_tokens int, model text
    - initDb issues a CREATE OR REPLACE VIEW v_llm_cost_daily DDL aggregating per UTC day: sum of each token col, count(*), and approx_usd computed as (input_tokens*3 + output_tokens*15 + cache_creation_input_tokens*3.75 + cache_read_input_tokens*0.30) / 1000000.0
    - initDb total query count rises from 6 to 12 (3 existing index/table + 3 existing ALTERs + 5 new ALTERs + 1 view = 12)
    - initDb is idempotent across re-invocations (second run also issues 12 with the same shape)
  </behavior>
  <action>
    Extend `initDb` in src/agents/alerter/src/capture-db.js with 5 `ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS` calls (input_tokens int, output_tokens int, cache_creation_input_tokens int, cache_read_input_tokens int, model text) following the existing per-query pattern at lines 32-34. Then add a single `CREATE OR REPLACE VIEW v_llm_cost_daily AS SELECT date_trunc('day', captured_at) AS day, count(*) AS n_calls, sum(input_tokens) AS input_tokens, sum(output_tokens) AS output_tokens, sum(cache_creation_input_tokens) AS cache_creation_input_tokens, sum(cache_read_input_tokens) AS cache_read_input_tokens, (coalesce(sum(input_tokens),0)*3 + coalesce(sum(output_tokens),0)*15 + coalesce(sum(cache_creation_input_tokens),0)*3.75 + coalesce(sum(cache_read_input_tokens),0)*0.30) / 1000000.0 AS approx_usd FROM signal_capture WHERE input_tokens IS NOT NULL GROUP BY day ORDER BY day DESC`. Use plain `pool.query(...)` -- no DO-block, no transaction (matches the existing pattern, per the file comment "signal_capture is a regular table, not a hypertable").

    Update src/agents/alerter/test/capture-db.test.js: bump `toHaveBeenCalledTimes(6)` to `12` in both the first-run and `12 -> 24` in the idempotency tests; add `expect(allSql).toMatch(...)` lines for each of the 5 new ADD COLUMN statements and one for `CREATE OR REPLACE VIEW v_llm_cost_daily`. Do NOT touch the insertCapture test -- that path stays at 13 params (per 999.53 out-of-scope: no backfill).

    Use plain `--` separators in any new comments (no em-dashes per project memory feedback_no_em_dashes_in_artifacts).
  </action>
  <verify>
    <automated>cd src/agents/alerter && npx jest test/capture-db.test.js --no-coverage</automated>
  </verify>
  <done>capture-db.test.js passes; initDb issues 12 queries first run and 24 over two runs; allSql contains all 5 new ADD COLUMN lines + CREATE OR REPLACE VIEW v_llm_cost_daily.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Capture-path -- llm-client returns usage; Step 7 UPDATE binds 5 new cols</name>
  <files>src/agents/alerter/src/llm-client.js, src/agents/alerter/src/capture.js, src/agents/alerter/test/llm-client.test.js, src/agents/alerter/test/capture.test.js</files>
  <behavior>
    - llm-client.compose() success returns {ok:true, text, usage, model} where usage is msg.usage passed through verbatim and model is msg.model (or the configured model fallback)
    - llm-client.compose() failure shape unchanged: {ok:false, reason}
    - When llmOk in capture.js Step 7, the UPDATE binds input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens, model from the compose result
    - When usage missing/partial (e.g. SDK returned no usage field), the UPDATE binds null for missing cols (no throw)
  </behavior>
  <action>
    In src/agents/alerter/src/llm-client.js compose() (line 77-79): change the success return from `return { ok: true, text }` to `return { ok: true, text, usage: msg.usage || null, model: msg.model || model }`. Do NOT log usage (V2 contract: API key never logged; usage itself is non-sensitive but keep the success path quiet to match existing style).

    In src/agents/alerter/src/capture.js around line 168-176, capture the full compose result so Step 7 can read usage/model: change `const r = await llmClient.compose(...)` already captures it. Carry `r.usage` and `r.model` into the Step 7 block (store in `let llmUsage = null, llmModel = null;` initialized before Step 4, set inside `if (r.ok)`).

    Rewrite Step 7 UPDATE (lines 197-206) to:
      `UPDATE signal_capture SET llm_reply = $1, degraded = $2, input_tokens = $3, output_tokens = $4, cache_creation_input_tokens = $5, cache_read_input_tokens = $6, model = $7 WHERE id = $8`
    Bind `[replyText, degraded, llmUsage?.input_tokens ?? null, llmUsage?.output_tokens ?? null, llmUsage?.cache_creation_input_tokens ?? null, llmUsage?.cache_read_input_tokens ?? null, llmModel, id]`.

    Test updates:
    - test/llm-client.test.js: extend the existing success-path test to assert the returned object includes `usage` (pass-through of the mocked msg.usage) and `model`. Mock msg should already include `usage: {input_tokens, output_tokens, ...}` and `model`; if not, add those fields to the mock.
    - test/capture.test.js: in the happy-path test (where llmClient.compose returns ok:true), set `compose.mockResolvedValue({ ok: true, text: '...', usage: { input_tokens: 100, output_tokens: 50, cache_creation_input_tokens: 0, cache_read_input_tokens: 0 }, model: 'claude-sonnet-4-6' })`. Assert that pool.query was called with an UPDATE matching `/UPDATE signal_capture SET llm_reply.*input_tokens.*output_tokens.*model/` and that params include `100, 50, 0, 0, 'claude-sonnet-4-6'`.
    - In the degraded R6 test (compose returns ok:false), assert the UPDATE is NOT invoked (current behavior preserved: Step 7 is gated on `llmOk`).

    No em-dashes anywhere in new code/comments/test strings.
  </action>
  <verify>
    <automated>cd src/agents/alerter && npx jest test/llm-client.test.js test/capture.test.js --no-coverage</automated>
  </verify>
  <done>Both test files pass; llm-client unit asserts {ok,text,usage,model}; capture.test asserts the new 8-param UPDATE and that null/missing usage fields bind as null without throwing.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: Extraction-path -- pipeline UPDATEs signal_capture by captureId with usage on resolve</name>
  <files>src/agents/alerter/src/extraction/pipeline.js, src/agents/alerter/test/extraction/pipeline.test.js</files>
  <behavior>
    - When extractor.extract() resolves with ok:true and usage non-null, pipeline issues `UPDATE signal_capture SET input_tokens=$1, output_tokens=$2, cache_creation_input_tokens=$3, cache_read_input_tokens=$4, model=$5 WHERE id=$6` with captureId from captureCtx
    - Model bound as 'claude-sonnet-4-6' (matches extractor.js default; stamped here since extractor result does not echo model)
    - When extractor returns ok:false, no UPDATE is issued (degraded path does not stamp partial usage)
    - When extractor returns ok:true but usage is null/undefined, no UPDATE is issued (avoid writing all-nulls)
    - UPDATE failure logged via logger.warn and swallowed (best-effort, never throws -- consistent with the rest of the pipeline)
  </behavior>
  <action>
    In src/agents/alerter/src/extraction/pipeline.js, immediately after the extractor call resolves successfully (after line 214, inside the try block, before the draftsArr branching at line 221), add a best-effort usage-persistence block:

    ```
    // 999.53: stamp token usage on the originating signal_capture row.
    // Best-effort; failure logged + swallowed so the extraction pipeline never
    // degrades on a usage-only write hiccup.
    if (extractResult.usage) {
      const u = extractResult.usage;
      try {
        await pool.query(
          `UPDATE signal_capture
             SET input_tokens = $1,
                 output_tokens = $2,
                 cache_creation_input_tokens = $3,
                 cache_read_input_tokens = $4,
                 model = $5
           WHERE id = $6`,
          [
            u.input_tokens ?? null,
            u.output_tokens ?? null,
            u.cache_creation_input_tokens ?? null,
            u.cache_read_input_tokens ?? null,
            'claude-sonnet-4-6',
            captureId,
          ],
        );
      } catch (e) {
        logger.warn && logger.warn(`[extraction] usage stamp failed: ${e.message}`);
      }
    }
    ```

    (Plan content note: the fenced block above is the literal source to write into pipeline.js, not a code excerpt for the planner -- emit it verbatim into the file.)

    Add a new test file `src/agents/alerter/test/extraction/pipeline.test.js` if one does not exist; if it does, append. Tests:
    - When extractor returns ok:true + usage object + drafts.length===1, pool.query is called at least once with SQL matching `/UPDATE signal_capture SET input_tokens/` and params include the captureId.
    - When extractor returns ok:true + usage:null, no such UPDATE is issued.
    - When extractor returns ok:false, no such UPDATE is issued.

    Use minimal stub injections for extractor/extractionDb/stateMachine/previewBuilder/config (mirror style of test/extraction/extractor.test.js mocks and pipeline-image-wire.test.js if it exists -- check imports there for the createExtractionPipeline call shape).

    No em-dashes in any new code or assertions.
  </action>
  <verify>
    <automated>cd src/agents/alerter && npx jest test/extraction/pipeline.test.js test/extraction/pipeline-image-wire.test.js --no-coverage</automated>
  </verify>
  <done>New pipeline tests pass; usage-stamp UPDATE fires on ok+usage, is skipped on ok+no-usage and on failure; existing pipeline-image-wire test still passes (regression guard).</done>
</task>

</tasks>

<verification>
Full alerter suite green:
```
cd src/agents/alerter && npx jest --no-coverage
```
Manual sanity (post-deploy, NOT in this plan): `psql -d telemetry -c "SELECT * FROM v_llm_cost_daily LIMIT 5;"` returns at least one row once a new capture lands.
</verification>

<success_criteria>
- All 3 task `<automated>` commands pass green
- Full `npx jest` suite in src/agents/alerter passes (no regressions in the other 700+ tests)
- New cols + view present in capture-db.js source; both call sites (capture.js Step 7, pipeline.js post-extractor) issue the new UPDATEs
- No em-dashes introduced in any file touched by this plan
- Acceptance per ROADMAP 999.53: new captures land with non-NULL token counts; `SELECT * FROM v_llm_cost_daily;` returns per-day $/cost rows (verified post-deploy, not in plan-time CI)
</success_criteria>

<output>
Create `.planning/quick/260518-tbi-999-53-persist-anthropic-token-usage-in-/260518-tbi-SUMMARY.md` when done.
</output>
