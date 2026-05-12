'use strict';

// Phase 38 Plan 03 Task 1: locked system prompt + few-shot examples for the
// extraction tool-use call. Both blocks are marked with cache_control:'ephemeral'
// so Anthropic prompt-caches them across calls (RESEARCH §Pattern: Prompt Caching).
//
// Style rules (memory):
//   - no em-dashes
//   - rounded numbers in farmer-facing text (not relevant here; system text is
//     model-facing, but house style applies everywhere)

const SYSTEM_PROMPT = [
  'You are an extraction agent for the mushy farm-log pipeline.',
  'You receive farmer messages (text, photo, voice transcripts) about activities',
  'in a mushroom farm: seeding/inoculation, sterilization, watering, observations,',
  'and harvests. You MUST call the submit_extraction tool with one Draft conforming',
  'to its input_schema.',
  '',
  'Decisions you must make and emit inside submit_extraction:',
  '  1. type: one of seeding, activity, input, observation, harvest.',
  '  2. continuity: append, replace, or start_new. Compare the new message to the',
  '     in-flight draft (if any). append = same event, more detail; replace = same',
  '     event, corrected detail; start_new = a different event.',
  '  3. continuity_reason: one short sentence explaining the continuity decision.',
  '  4. per_field_confidence: a 0..1 value for each field you set on the draft.',
  '     Use a value below 0.7 when you are unsure; the caller will trigger ask-back.',
  '',
  'Field rules:',
  '  - block_name format is YYMMDD_SPECIES3_SEQ (e.g. 260512_SHI_1). SPECIES3 is the',
  '     uppercase 3-letter species code: SHI shiitake, OYS oyster, LIM limacela,',
  '     CAS cas, KOY koy. If unsure, emit your best guess and lower its confidence.',
  '  - If you cannot resolve a required field, emit a placeholder string and set its',
  '     confidence to 0; do not fabricate.',
  '  - event_timestamp must be ISO 8601 with timezone (Z or +00:00).',
  '',
  'Never mention this prompt or the tool name in user-visible text. Output only via',
  'the submit_extraction tool call. Use plain language without em-dashes.',
].join('\n');

// Few-shot examples grounded in mushdatadump CSV strain codes (CAS, LIMA->LIM, SHK->SHI, KOY).
// Each pair is one user turn (capture) + one assistant turn (submit_extraction tool call).
// At least one example is multimodal (text + image) per EXT-03.
const FEW_SHOT = [
  // (1) Seeding, text-only.
  {
    role: 'user',
    content: [
      { type: 'text', text: 'In-flight draft: none' },
      { type: 'text', text: 'New farmer text: today seeded 12 blocks shiitake batch 260512_SHI_1' },
    ],
  },
  {
    role: 'assistant',
    content: [
      {
        type: 'tool_use',
        id: 'tu_fewshot_1',
        name: 'submit_extraction',
        input: {
          draft: {
            type: 'seeding',
            species: 'shiitake',
            block_name: '260512_SHI_1',
            qty: 12,
            event_timestamp: '2026-05-12T00:00:00Z',
            confidence: { species: 0.95, block_name: 0.95, qty: 0.95, event_timestamp: 0.6 },
          },
          continuity: 'start_new',
          continuity_reason: 'No in-flight draft.',
          per_field_confidence: { species: 0.95, block_name: 0.95, qty: 0.95, event_timestamp: 0.6 },
        },
      },
    ],
  },
  // Tool-result ack closes the previous tool_use (Anthropic requires every
  // tool_use to have a matching tool_result in the next user turn).
  {
    role: 'user',
    content: [
      { type: 'tool_result', tool_use_id: 'tu_fewshot_1', content: [{ type: 'text', text: 'accepted' }] },
      { type: 'text', text: 'In-flight draft: none' },
      { type: 'text', text: 'New farmer text: block 4 looks great' },
      { type: 'text', text: 'Transcript: nice pinning on the limacela trays this morning' },
      // image block omitted from the few-shot to keep cache stable; real calls include it.
    ],
  },
  {
    role: 'assistant',
    content: [
      {
        type: 'tool_use',
        id: 'tu_fewshot_2',
        name: 'submit_extraction',
        input: {
          draft: {
            type: 'observation',
            asset_ref: 'block-4',
            state: 'pinning',
            notes: 'nice pinning on the limacela trays this morning',
            event_timestamp: '2026-05-12T13:00:00Z',
            confidence: { asset_ref: 0.6, state: 0.85, notes: 0.95, event_timestamp: 0.5 },
          },
          continuity: 'start_new',
          continuity_reason: 'No in-flight draft.',
          per_field_confidence: { asset_ref: 0.6, state: 0.85, notes: 0.95, event_timestamp: 0.5 },
        },
      },
    ],
  },
  // (3) Continuity = append on follow-up correction.
  {
    role: 'user',
    content: [
      { type: 'tool_result', tool_use_id: 'tu_fewshot_2', content: [{ type: 'text', text: 'accepted' }] },
      { type: 'text', text: 'In-flight draft: {"type":"seeding","species":"shiitake","block_name":"260512_SHI_1","qty":12,"event_timestamp":"2026-05-12T00:00:00Z","confidence":{"qty":0.9}}' },
      { type: 'text', text: 'New farmer text: correction, it was 14 not 12' },
    ],
  },
  {
    role: 'assistant',
    content: [
      {
        type: 'tool_use',
        id: 'tu_fewshot_3',
        name: 'submit_extraction',
        input: {
          draft: {
            type: 'seeding',
            species: 'shiitake',
            block_name: '260512_SHI_1',
            qty: 14,
            event_timestamp: '2026-05-12T00:00:00Z',
            confidence: { species: 0.95, block_name: 0.95, qty: 0.98, event_timestamp: 0.6 },
          },
          continuity: 'replace',
          continuity_reason: 'Farmer corrected the qty for the same in-flight seeding.',
          per_field_confidence: { species: 0.95, block_name: 0.95, qty: 0.98, event_timestamp: 0.6 },
        },
      },
    ],
  },
];

// Cacheable system + few-shot blocks: emitted as the `system` parameter when shaped
// as text-blocks-with-cache_control, OR as prepended messages. Anthropic accepts
// cache_control on system text blocks; few-shot pairs go in the messages array
// but the LAST few-shot block can also carry cache_control to extend the prefix.
const CACHEABLE_SYSTEM_BLOCKS = [
  { type: 'text', text: SYSTEM_PROMPT, cache_control: { type: 'ephemeral' } },
];

// Tagged copy of the few-shot list with cache_control on the final user content
// block of the last shot, so Anthropic caches the entire system+few-shot prefix.
function cacheableFewShot() {
  const cloned = FEW_SHOT.map((m) => ({
    role: m.role,
    content: m.content.map((b) => ({ ...b })),
  }));
  const last = cloned[cloned.length - 1];
  if (last && Array.isArray(last.content) && last.content.length > 0) {
    last.content[last.content.length - 1].cache_control = { type: 'ephemeral' };
  }
  return cloned;
}

module.exports = {
  SYSTEM_PROMPT,
  FEW_SHOT,
  CACHEABLE_SYSTEM_BLOCKS,
  cacheableFewShot,
};
