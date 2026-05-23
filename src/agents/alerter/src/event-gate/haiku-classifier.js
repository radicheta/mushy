'use strict';

// Phase 44 Plan-04 Task 4.2: Haiku 4.5 classifier (forced tool_use + cache + fail-open).
//
// createHaikuClassifier({apiKey, logger, model, maxTokens, timeoutMs, client}) → {classify(envCtx)}
//
// On success: {ok:true, is_event, kind, confidence}
// On any error / timeout / shape failure: {ok:false, reason, fallthrough:'forced'} (D-03)
//
// Security V14: ANTHROPIC_API_KEY never crosses into logger output.

const Anthropic = require('@anthropic-ai/sdk');
const { z } = require('zod');
const { CACHEABLE_SYSTEM_BLOCKS } = require('./prompts');

const TOOL_NAME = 'classify_capture';
const TOOL_DESCRIPTION = 'Classify whether this capture is an event worth extracting.';

const TOOL_SCHEMA = {
  type: 'object',
  properties: {
    is_event: { type: 'boolean' },
    kind: { type: 'string' },
    confidence: { type: 'number', minimum: 0, maximum: 1 },
  },
  required: ['is_event', 'kind', 'confidence'],
  additionalProperties: false,
};

const Classification = z.object({
  is_event: z.boolean(),
  kind: z.string(),
  confidence: z.number().min(0).max(1),
});

function findToolUseBlock(msg) {
  if (!msg || !Array.isArray(msg.content)) return null;
  return msg.content.find((b) => b && b.type === 'tool_use' && b.name === TOOL_NAME) || null;
}

function buildClassifierInput(envCtx) {
  // Minimal compact JSON — the farmer message is a SEPARATE messages[].content
  // block, never concatenated into the system prompt (threat T-44-04-01 mitigation).
  return [
    {
      type: 'text',
      text: JSON.stringify({
        text: envCtx && envCtx.text != null ? envCtx.text : null,
        transcript: envCtx && envCtx.transcript != null ? envCtx.transcript : null,
        attachmentCount: envCtx && typeof envCtx.attachmentCount === 'number' ? envCtx.attachmentCount : 0,
      }),
    },
  ];
}

function createHaikuClassifier({
  apiKey,
  logger = console,
  model = 'claude-haiku-4-5-20251001',
  maxTokens = 100,
  timeoutMs = 2000,
  client: injectedClient = null,
} = {}) {
  const client = injectedClient || new Anthropic({ apiKey, maxRetries: 2 });

  return {
    async classify(envCtx) {
      const baseReq = {
        model,
        max_tokens: maxTokens,
        system: CACHEABLE_SYSTEM_BLOCKS,
        tools: [{
          name: TOOL_NAME,
          description: TOOL_DESCRIPTION,
          input_schema: TOOL_SCHEMA,
        }],
        tool_choice: { type: 'tool', name: TOOL_NAME },
        messages: [{ role: 'user', content: buildClassifierInput(envCtx) }],
      };

      let resp;
      try {
        // Anthropic SDK contract: `signal` is a request-option (second arg),
        // NOT a body param. Passing it inside baseReq triggers
        // `400 invalid_request_error: "signal: Extra inputs are not permitted"`
        // because the SDK strict-validates the body against the API schema.
        // Caught by Task 4.6 live-fire 2026-05-23.
        resp = await client.messages.create(baseReq, {
          signal: AbortSignal.timeout(timeoutMs),
        });
      } catch (e) {
        if (logger && logger.warn) {
          logger.warn(`[haiku-classifier] degraded: ${e && e.message ? e.message : String(e)}`);
        }
        return { ok: false, reason: (e && e.message) || String(e), fallthrough: 'forced' };
      }

      const toolUse = findToolUseBlock(resp);
      if (!toolUse) {
        return { ok: false, reason: 'no_tool_use_in_response', fallthrough: 'forced' };
      }

      const parsed = Classification.safeParse(toolUse.input);
      if (!parsed.success) {
        if (logger && logger.warn) {
          logger.warn(`[haiku-classifier] schema_invalid: ${parsed.error.message}`);
        }
        return {
          ok: false,
          reason: 'schema_invalid',
          fallthrough: 'forced',
          errors: parsed.error.issues,
        };
      }

      return {
        ok: true,
        is_event: parsed.data.is_event,
        kind: parsed.data.kind,
        confidence: parsed.data.confidence,
        usage: resp && resp.usage ? resp.usage : null,
      };
    },
  };
}

module.exports = { createHaikuClassifier };
