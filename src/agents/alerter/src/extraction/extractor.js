'use strict';

// Phase 38 Plan 03 Task 2: extractor.js -- the heart of the extraction pipeline.
// Phase 39 D-03: farmerCorrection added to buildInitialUserContent for the EDIT loop.
//
// extract({captures, inFlightDraft}):
//   1. Build content blocks via multimodal.buildContentBlocks. Multimodal fusion
//      (EXT-03) happens here: text + transcript + image_paths all go in ONE call.
//   2. Build the Anthropic request with cached system + few-shot + a forced tool_use:
//      tools=[submit_extraction], tool_choice={type:'tool',name:'submit_extraction'}.
//   3. Call client.messages.create.
//   4. Find the tool_use block; Zod safeParse via validator.validateDraft against
//      the Submission schema.
//   5. On Zod failure (first attempt), send back a tool_result with is_error:true
//      so the model can fix its call. One retry max. Second failure returns
//      {ok:false, reason:'schema_invalid'}.
//   6. Never throws. SDK errors surface as {ok:false, reason}.
//
// V2: ANTHROPIC_API_KEY only crosses into `new Anthropic({ apiKey })`; never logged.

const crypto = require('crypto');
const Anthropic = require('@anthropic-ai/sdk');
const { Submission, SUBMISSION_JSON_SCHEMA } = require('./schemas');
const { validateDraft, buildToolResultRetry } = require('./validator');
const { buildContentBlocks } = require('./multimodal');
const { CACHEABLE_SYSTEM_BLOCKS, cacheableFewShot } = require('./prompts/system');

const TOOL_NAME = 'submit_extraction';
const TOOL_DESCRIPTION = 'Submit one farmOS draft with continuity decision and per-field confidence.';

function inlineTopLevelRef(schema) {
  // Plan 07 bug fix (Rule 1/3): zod-to-json-schema with a name arg emits
  // {$ref: '#/definitions/Foo', definitions: {Foo: {...}}}. Anthropic rejects
  // this with 400 "tools.0.custom.input_schema.type: Field required" because
  // input_schema must have `type` at the top level. Inline the named definition
  // while keeping `definitions` so nested $refs (e.g. for the discriminatedUnion
  // members) still resolve.
  if (!schema || typeof schema !== 'object' || !schema.$ref) return schema;
  const m = /^#\/definitions\/(.+)$/.exec(schema.$ref);
  if (!m || !schema.definitions || !schema.definitions[m[1]]) return schema;
  const inlined = { ...schema.definitions[m[1]], definitions: schema.definitions };
  delete inlined.$ref;
  return inlined;
}

function buildToolSpec() {
  return {
    name: TOOL_NAME,
    description: TOOL_DESCRIPTION,
    input_schema: inlineTopLevelRef(SUBMISSION_JSON_SCHEMA),
  };
}

function buildInitialUserContent({ captures, inFlightDraft, corpusContext, farmerCorrection }) {
  // Capture set -> a single user turn with: corpus context, in-flight summary, then per-capture text/transcript/images.
  // Plan 07 bug fix (Rule 1): close the last few-shot tool_use with a tool_result
  // block. Anthropic rejects 400 if any tool_use lacks an immediately-following
  // tool_result in the next user message.
  // Phase 53 BACK-03: last few-shot id is now tu_fewshot_6 (DT-tubs
  // physical_object_photo counter-example). tu_fewshot_3 and tu_fewshot_5 are
  // closed inline inside FEW_SHOT via leading tool_result blocks in the next
  // user turn (see prompts/system.js).
  const blocks = [];
  blocks.push({
    type: 'tool_result',
    tool_use_id: 'tu_fewshot_6',
    content: [{ type: 'text', text: 'accepted' }],
  });
  if (corpusContext && typeof corpusContext === 'object') {
    blocks.push({
      type: 'text',
      text: `corpus_context: ${JSON.stringify(corpusContext)}`,
    });
  }
  blocks.push({
    type: 'text',
    text: `In-flight draft: ${inFlightDraft ? JSON.stringify(inFlightDraft) : 'none'}`,
  });
  // Phase 39 D-03: append farmer-correction context only when present and non-empty.
  if (typeof farmerCorrection === 'string' && farmerCorrection.trim() !== '') {
    blocks.push({
      type: 'text',
      text: `Farmer correction: ${farmerCorrection.trim()}`,
    });
  }
  const captureList = Array.isArray(captures) ? captures : [];
  for (const cap of captureList) {
    const sub = buildContentBlocks({
      text: cap && cap.text,
      transcript: cap && cap.transcript,
      images: cap && cap.images,
    });
    for (const b of sub) blocks.push(b);
  }
  return blocks;
}

function findToolUseBlock(msg) {
  if (!msg || !Array.isArray(msg.content)) return null;
  return msg.content.find((b) => b && b.type === 'tool_use' && b.name === TOOL_NAME) || null;
}

function createExtractor({
  apiKey,
  logger = console,
  model = 'claude-sonnet-4-6',
  // Plan 09 (2026-05-12): default bumped 2048 -> 16384. Multi-event paper-log
  // pages produce 10-25 drafts; each ~150-250 output tokens; at 2048 the model
  // silently truncates the tool_use input to {} and the validator returns
  // schema_invalid (no drafts/continuity/continuity_reason). The original
  // 2048 default came from single-event Plan 03 sizing -- Plan 07 missed this
  // because the 2-fixture cap hit pages small enough to fit. Plan 08's
  // eval-two.js seed already used 16384 for the same reason.
  maxTokens = 16384,
  client: injectedClient = null,
  // Phase 54 Plan 03: optional observer fired once per Anthropic call. Live
  // capture sites omit this; only the backfill harness installs it to persist
  // every paid response to <runDir>/responses.jsonl. Errors in the observer
  // are caught + logged warn; they never propagate out of extract().
  onLlmCall = null,
} = {}) {
  const client = injectedClient || new Anthropic({ apiKey, maxRetries: 2 });
  const toolSpec = buildToolSpec();

  // Wrap client.messages.create so the observer fires for both the initial
  // call and the schema-retry call without duplicating the try/catch logic.
  async function callWithObserver(req, captureId) {
    const t0 = Date.now();
    let resp;
    let err;
    try {
      resp = await client.messages.create(req);
    } catch (e) {
      err = e;
      throw e;
    } finally {
      if (typeof onLlmCall === 'function') {
        try {
          const usage = (resp && resp.usage) || {};
          const requestHash = crypto.createHash('sha256')
            .update(JSON.stringify({
              model: req.model,
              messages: req.messages,
              tools: req.tools,
              system: req.system,
            }))
            .digest('hex')
            .slice(0, 16);
          await onLlmCall({
            ts: new Date().toISOString(),
            model: req.model,
            input_tokens: usage.input_tokens || 0,
            output_tokens: usage.output_tokens || 0,
            cache_creation_input_tokens: usage.cache_creation_input_tokens || 0,
            cache_read_input_tokens: usage.cache_read_input_tokens || 0,
            latency_ms: Date.now() - t0,
            raw_response: resp || null,
            request_hash: requestHash,
            captureId: captureId || null,
            error: err ? (err.message || String(err)) : null,
          });
        } catch (obsErr) {
          logger.warn && logger.warn(`[extractor] onLlmCall observer threw: ${obsErr.message}`);
        }
      }
    }
    return resp;
  }

  return {
    async extract({ captures, inFlightDraft, corpusContext, farmerCorrection } = {}) {
      const captureId = Array.isArray(captures) && captures[0] && captures[0].captureId
        ? captures[0].captureId
        : null;
      try {
        const systemBlocks = CACHEABLE_SYSTEM_BLOCKS;
        const fewShot = cacheableFewShot();
        const userContent = buildInitialUserContent({ captures, inFlightDraft, corpusContext, farmerCorrection });
        const messages = [...fewShot, { role: 'user', content: userContent }];

        const baseReq = {
          model,
          max_tokens: maxTokens,
          system: systemBlocks,
          tools: [toolSpec],
          tool_choice: { type: 'tool', name: TOOL_NAME },
          messages,
        };

        let resp;
        try {
          resp = await callWithObserver(baseReq, captureId);
        } catch (e) {
          logger.warn && logger.warn(`[extractor] degraded: ${e.message}`);
          return { ok: false, reason: e.message };
        }

        const usage1 = resp && resp.usage ? resp.usage : null;

        let toolUse = findToolUseBlock(resp);
        if (!toolUse) {
          return { ok: false, reason: 'no_tool_use_in_response', usage: usage1 };
        }

        let parsed = validateDraft(toolUse.input, Submission);
        if (parsed.ok) {
          return packResult(parsed.draft, sumUsage([usage1]));
        }

        // Retry once with tool_result is_error=true.
        const assistantTurn = { role: 'assistant', content: resp.content };
        const retryUserTurn = {
          role: 'user',
          content: [buildToolResultRetry(toolUse.id, parsed.errors)],
        };
        const retryReq = {
          ...baseReq,
          messages: [...messages, assistantTurn, retryUserTurn],
        };

        let resp2;
        try {
          resp2 = await callWithObserver(retryReq, captureId);
        } catch (e) {
          logger.warn && logger.warn(`[extractor] retry degraded: ${e.message}`);
          return { ok: false, reason: e.message, usage: usage1 };
        }

        const usage2 = resp2 && resp2.usage ? resp2.usage : null;
        const usageSum = sumUsage([usage1, usage2]);

        const toolUse2 = findToolUseBlock(resp2);
        if (!toolUse2) {
          return { ok: false, reason: 'no_tool_use_in_response', usage: usageSum };
        }
        const parsed2 = validateDraft(toolUse2.input, Submission);
        if (parsed2.ok) {
          return packResult(parsed2.draft, usageSum);
        }
        logger.warn && logger.warn(`[extractor] schema_invalid after retry`);
        return { ok: false, reason: 'schema_invalid', errors: parsed2.errors, raw_first: toolUse && toolUse.input, raw_retry: toolUse2 && toolUse2.input, usage: usageSum };
      } catch (e) {
        logger.warn && logger.warn(`[extractor] degraded: ${e.message}`);
        return { ok: false, reason: e.message };
      }
    },
  };
}

function packResult(submission, usage) {
  // Plan 08: multi-draft shape. Submission = {drafts: [{draft, per_field_confidence}], continuity, continuity_reason}.
  // Back-compat: also expose .draft/.per_field_confidence as the first element when drafts.length === 1
  // so call sites that still want the single-event view keep working until pipeline.js / state-machine.js are rewired.
  const drafts = Array.isArray(submission.drafts) ? submission.drafts : [];
  const first = drafts[0] || null;
  return {
    ok: true,
    drafts,
    continuity_decision: submission.continuity,
    continuity_reason: submission.continuity_reason,
    // Legacy fields (single-event view).
    draft: first ? first.draft : null,
    per_field_confidence: first ? first.per_field_confidence : null,
    // Phase 53 BACK-03: optional capture_kind passes through to callers
    // (analytics + future routing refinement). Omitted -> null. Routing
    // (BACK-02) does NOT consume this today -- back-compat lock.
    capture_kind: submission.capture_kind != null ? submission.capture_kind : null,
    usage: usage || null,
  };
}

function sumUsage(list) {
  const out = { input_tokens: 0, output_tokens: 0, cache_creation_input_tokens: 0, cache_read_input_tokens: 0 };
  let any = false;
  for (const u of list || []) {
    if (!u) continue;
    any = true;
    out.input_tokens += u.input_tokens || 0;
    out.output_tokens += u.output_tokens || 0;
    out.cache_creation_input_tokens += u.cache_creation_input_tokens || 0;
    out.cache_read_input_tokens += u.cache_read_input_tokens || 0;
  }
  return any ? out : null;
}

module.exports = {
  createExtractor,
  _internal: {
    buildInitialUserContent,
    findToolUseBlock,
    buildToolSpec,
    TOOL_NAME,
  },
};
