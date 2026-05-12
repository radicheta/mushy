'use strict';

// Phase 38 Plan 03 Task 1 (refactored in Plan 08): locked system prompt + few-shot
// examples for the extraction tool-use call. Cached via cache_control:'ephemeral'
// (RESEARCH §Pattern: Prompt Caching).
//
// Plan 08 changes:
//   - Multi-draft submit_extraction: drafts[] not draft. One element per individuation
//     event on a multi-event page.
//   - parent_batch_name (lineage C4) on seeding drafts.
//   - corpus_context block: caller can supply default_year so the model doesn't
//     hallucinate years on year-absent paper logs (mushdatadump = 2025 notebook).
//
// Style: no em-dashes. Model-facing, but house style applies everywhere.

const SYSTEM_PROMPT = [
  'You are an extraction agent for the mushy farm-log pipeline.',
  'You receive farmer messages (text, photo, voice transcripts) about activities',
  'in a mushroom farm: seeding/inoculation, sterilization, watering, observations,',
  'and harvests. You MUST call the submit_extraction tool with one or more Drafts',
  'wrapped in {drafts, continuity, continuity_reason}.',
  '',
  'Multi-event pages:',
  '  Photographed paper-log pages often contain MANY individuation events',
  '  (one inoculation per row, sometimes 10-25 per page, often across several',
  '  species). Emit ONE element of drafts[] per event. Do NOT collapse them',
  '  into a single qty=N draft. Each block gets its own seeding draft with',
  '  its own block_name, species, qty=1, and parent_batch_name when shown.',
  '',
  'Decisions you must emit inside submit_extraction:',
  '  1. drafts[]: one entry per event. Each entry = {draft, per_field_confidence}.',
  '  2. continuity: append, replace, or start_new -- one value for the whole call.',
  '     Compare to the in-flight draft if any. append = same event, more detail;',
  '     replace = same event, corrected detail; start_new = different event(s).',
  '  3. continuity_reason: one short sentence.',
  '  4. per_field_confidence (inside each draft entry): 0..1 per field you set.',
  '     Use < 0.7 when you are unsure; the caller triggers ask-back at < 0.7.',
  '',
  'Field rules:',
  '  - block_name format: YYMMDD_SPECIES_SEQ (e.g. 250806_DT_1). SPECIES is the',
  '    short uppercase code (2-4 chars).',
  '  - Common-name -> species code (canonical):',
  '      shiitake             -> SHI',
  '      king oyster          -> KOY',
  '      winecap / wine cap   -> WIN',
  '      oyster (generic)     -> OYS',
  '      blue oyster          -> BLO',
  '      pink oyster          -> PIN',
  '      lion\'s mane          -> LIM',
  '      chestnut             -> CHE',
  '      reishi               -> REI',
  '      chicken of the woods -> COW',
  '      cordyceps            -> CRD',
  '      DT (already a code)  -> DT',
  '    If the farmer says a common name in audio or text, ALWAYS use the canonical',
  '    code above. Do NOT invent a new code (e.g. do NOT code "winecap" as CAS).',
  '    If the species is not in this list, emit your best 3-letter guess and lower',
  '    per_field_confidence.species below 0.6 so the caller can ask back.',
  '  - parent_batch_name (optional, seeding only): the inoculation SOURCE. Paper',
  '    logs often shorthand it as MMDD-SEQ (e.g. "0627-2"). Decode using corpus',
  '    context: prepend the corpus default_year and the species inferred from the',
  '    column header on the page. "0627-2" with default_year=2025 and species=DT',
  '    becomes "250627_DT_2". When confident in the species column but unsure on',
  '    the date digits, still emit the decoded form and lower its confidence.',
  '  - qty: positive integer count for the draft. For atomic per-block individuation',
  '    drafts, this is usually 1.',
  '  - event_timestamp: ISO 8601 with timezone (Z or +00:00).',
  '',
  'Year handling (CRITICAL):',
  '  - If the page shows no year, use corpus_context.default_year if supplied.',
  '  - If neither the page nor the corpus context provides a year, set per_field_',
  '    confidence.event_timestamp BELOW 0.5 so the caller asks back. Do NOT guess.',
  '  - Never invent a year just to satisfy the ISO format requirement.',
  '',
  'Never mention this prompt or the tool name in user-visible text. Output only via',
  'the submit_extraction tool call. Use plain language without em-dashes.',
].join('\n');

// Few-shot examples. Each pair = one user turn (capture) + one assistant turn
// (submit_extraction). New shape: drafts[] always present, even for single-event
// captures. Includes one multi-event page example so the model learns the pattern.
const FEW_SHOT = [
  // (1) Single seeding from a farmer text message.
  {
    role: 'user',
    content: [
      { type: 'text', text: 'corpus_context: {"default_year": 2026}' },
      { type: 'text', text: 'In-flight draft: none' },
      { type: 'text', text: 'New farmer text: today seeded 1 block shiitake, batch 260512_SHI_1, parent batch 260410_SHI_2' },
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
          drafts: [
            {
              draft: {
                type: 'seeding',
                species: 'shiitake',
                block_name: '260512_SHI_1',
                qty: 1,
                event_timestamp: '2026-05-12T00:00:00Z',
                parent_batch_name: '260410_SHI_2',
                confidence: { species: 0.95, block_name: 0.95, qty: 0.95, event_timestamp: 0.6, parent_batch_name: 0.9 },
              },
              per_field_confidence: { species: 0.95, block_name: 0.95, qty: 0.95, event_timestamp: 0.6, parent_batch_name: 0.9 },
            },
          ],
          continuity: 'start_new',
          continuity_reason: 'No in-flight draft.',
        },
      },
    ],
  },
  // (2) Multi-event paper-log page: 3 blocks, 2 species, source shorthand.
  // Demonstrates: drafts[] with multiple entries, corpus_context year usage,
  // and MMDD-SEQ source decoding into canonical parent_batch_name.
  {
    role: 'user',
    content: [
      { type: 'tool_result', tool_use_id: 'tu_fewshot_1', content: [{ type: 'text', text: 'accepted' }] },
      { type: 'text', text: 'corpus_context: {"default_year": 2025}' },
      { type: 'text', text: 'In-flight draft: none' },
      {
        type: 'text',
        text: [
          'Paper log page (top of page reads "8/6", no year). Three rows:',
          'Row 1: column DT, source 0627-2',
          'Row 2: column DT, source 0627-2',
          'Row 3: column CAS, source 0801-5',
          'Page-level SEQ continues from previous page; these are blocks 1, 2, 3 for the day.',
        ].join('\n'),
      },
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
          drafts: [
            {
              draft: {
                type: 'seeding', species: 'DT', block_name: '250806_DT_1', qty: 1,
                event_timestamp: '2025-08-06T00:00:00Z', parent_batch_name: '250627_DT_2',
                confidence: { species: 0.95, block_name: 0.85, qty: 0.95, event_timestamp: 0.85, parent_batch_name: 0.85 },
              },
              per_field_confidence: { species: 0.95, block_name: 0.85, qty: 0.95, event_timestamp: 0.85, parent_batch_name: 0.85 },
            },
            {
              draft: {
                type: 'seeding', species: 'DT', block_name: '250806_DT_2', qty: 1,
                event_timestamp: '2025-08-06T00:00:00Z', parent_batch_name: '250627_DT_2',
                confidence: { species: 0.95, block_name: 0.85, qty: 0.95, event_timestamp: 0.85, parent_batch_name: 0.85 },
              },
              per_field_confidence: { species: 0.95, block_name: 0.85, qty: 0.95, event_timestamp: 0.85, parent_batch_name: 0.85 },
            },
            {
              draft: {
                type: 'seeding', species: 'CAS', block_name: '250806_CAS_3', qty: 1,
                event_timestamp: '2025-08-06T00:00:00Z', parent_batch_name: '250801_CAS_5',
                confidence: { species: 0.95, block_name: 0.85, qty: 0.95, event_timestamp: 0.85, parent_batch_name: 0.85 },
              },
              per_field_confidence: { species: 0.95, block_name: 0.85, qty: 0.95, event_timestamp: 0.85, parent_batch_name: 0.85 },
            },
          ],
          continuity: 'start_new',
          continuity_reason: 'Three new individuation events from a fresh paper log page; no in-flight draft.',
        },
      },
    ],
  },
  // (3) Continuity = replace (correction to in-flight draft).
  {
    role: 'user',
    content: [
      { type: 'tool_result', tool_use_id: 'tu_fewshot_2', content: [{ type: 'text', text: 'accepted' }] },
      { type: 'text', text: 'corpus_context: {"default_year": 2026}' },
      { type: 'text', text: 'In-flight draft: {"type":"seeding","species":"shiitake","block_name":"260512_SHI_1","qty":12,"event_timestamp":"2026-05-12T00:00:00Z"}' },
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
          drafts: [
            {
              draft: {
                type: 'seeding', species: 'shiitake', block_name: '260512_SHI_1', qty: 14,
                event_timestamp: '2026-05-12T00:00:00Z',
                confidence: { species: 0.95, block_name: 0.95, qty: 0.98, event_timestamp: 0.6 },
              },
              per_field_confidence: { species: 0.95, block_name: 0.95, qty: 0.98, event_timestamp: 0.6 },
            },
          ],
          continuity: 'replace',
          continuity_reason: 'Farmer corrected the qty for the same in-flight seeding.',
        },
      },
    ],
  },
];

const CACHEABLE_SYSTEM_BLOCKS = [
  { type: 'text', text: SYSTEM_PROMPT, cache_control: { type: 'ephemeral' } },
];

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
