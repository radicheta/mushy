'use strict';

// Phase 38 Plan 03 Task 1: Zod safeParse envelope + tool_result retry helper.
//
// validateDraft(rawToolInput, schema):
//   - Runs schema.safeParse.
//   - When the parsed type is 'observation', re-applies the state-or-notes refine
//     (per Plan 01 deviation: ObservationLogBase has no .refine() so it can live in
//     the discriminated union; this validator re-applies the rule).
//   - Returns {ok:true, draft} | {ok:false, reason:'schema_invalid', errors}.
//
// buildToolResultRetry(toolUseId, errors):
//   - Returns an Anthropic content block for the next user-message turn carrying
//     is_error:true plus a compact human-readable error string. Per RESEARCH §
//     "Anthropic Multi-Turn with tool_result for Schema-Validation Retry".

const { hasStateOrNotes } = require('./schemas/observation');

function validateDraft(rawToolInput, schema) {
  const result = schema.safeParse(rawToolInput);
  if (!result.success) {
    return {
      ok: false,
      reason: 'schema_invalid',
      errors: result.error.issues.map((i) => ({ path: i.path, message: i.message })),
    };
  }
  const parsed = result.data;
  // New Submission shape: walk drafts[] and re-apply the observation refine.
  if (parsed && Array.isArray(parsed.drafts)) {
    for (let i = 0; i < parsed.drafts.length; i += 1) {
      const d = parsed.drafts[i] && parsed.drafts[i].draft;
      if (d && d.type === 'observation' && !hasStateOrNotes(d)) {
        return {
          ok: false,
          reason: 'schema_invalid',
          errors: [{ path: ['drafts', i, 'draft', 'state'], message: 'observation requires state or notes' }],
        };
      }
    }
    return { ok: true, draft: parsed };
  }
  // Legacy shape (single draft) -- still used by some unit tests / callers.
  if (parsed && parsed.type === 'observation' && !hasStateOrNotes(parsed)) {
    return {
      ok: false,
      reason: 'schema_invalid',
      errors: [{ path: ['state'], message: 'observation requires state or notes' }],
    };
  }
  return { ok: true, draft: parsed };
}

function buildToolResultRetry(toolUseId, errors) {
  const list = Array.isArray(errors) && errors.length
    ? errors.map((e) => {
        const p = Array.isArray(e.path) ? e.path.join('.') : String(e.path || '');
        return `- ${p || '(root)'}: ${e.message}`;
      }).join('\n')
    : '(no specific errors reported)';
  const content = [
    'Your submit_extraction call did not match the schema. Errors:',
    list,
    'Please call submit_extraction again with a corrected draft.',
  ].join('\n');
  return {
    type: 'tool_result',
    tool_use_id: toolUseId,
    is_error: true,
    content,
  };
}

module.exports = {
  validateDraft,
  buildToolResultRetry,
};
