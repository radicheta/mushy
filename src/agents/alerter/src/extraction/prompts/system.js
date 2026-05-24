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
  'Session vs single-event seeding:',
  '  - When a capture describes MORE THAN ONE child block (audio enumerates many',
  '    bags in one breath, or a paper-log photo shows a multi-row page with the',
  '    same event_date), emit ONE draft of type=seeding_session with groups[],',
  '    NOT N separate seeding drafts.',
  '  - Cardinality rule: total children across all groups > 1 => type=seeding_session.',
  '    total children == 1 AND no session context => legacy type=seeding.',
  '  - groups[] carries the per-parent rows: each group is {parent, species, qty,',
  '    child_block_names}. A single-parent multi-child session still emits',
  '    groups.length === 1 (the session shape is the canonical batch shape, not',
  '    the per-bag shape).',
  '  - event_date is day-grain YYYY-MM-DD on the seeding_session draft; per-bag',
  '    timestamps are derived downstream at commit time.',
  '',
  'Provenance (groups-shape only):',
  '  - On seeding_session, EVERY provenanced field is the object',
  '    {value, confidence, sources[]}. This applies to group.parent, group.species,',
  '    group.qty, and group.child_block_names. event_date, notes, type, conflicts,',
  '    and needs_input are NOT provenanced (single-source by construction).',
  '  - sources[] is a non-empty subset of:',
  '      audio, paper_log_photo, bag_label_photo, text, model_inference',
  '  - When multiple sources agree on a value, list ALL of them in sources[].',
  '  - When only one source contributed, list just that one.',
  '  - confidence is 0..1, your own estimate of how certain this fused value is.',
  '',
  'Conflict resolution (groups-shape only):',
  '  - When audio and paper_log_photo disagree on a value, PHOTO WINS silently.',
  '    Set the field .value to the photo value, include BOTH sources in .sources[],',
  '    set .confidence to the photo confidence.',
  '  - ALSO push an entry into draft.conflicts[]:',
  '      { path: "groups[i].<field>.value",',
  '        candidates: [ {value, source, confidence}, {value, source, confidence} ],',
  '        resolution: "photo_wins_implicit" }',
  '  - conflicts[] is internal forensics. NEVER mention conflicts in any human-',
  '    readable text. The farmer must never see the disagreement.',
  '',
  'Missing SEQ ask-back:',
  '  - When child block_names have no source (NO paper_log_photo AND audio did',
  '    not enumerate SEQ numbers), do NOT guess a starting SEQ.',
  '  - Emit child_block_names.value as an array of the literal string "NEEDS_SEQ"',
  '    with length === qty.value for that group.',
  '  - Set draft.needs_input = "starting_seq". The pipeline asks the farmer back',
  '    and fills the real block_names from their reply.',
  '  - If parent cannot be identified from any source (e.g. fresh-grain inoc with',
  '    no parent batch), set group.parent.value = "NO_PARENT". Sources[] still',
  '    reflects which source(s) confirmed the absence (usually ["audio"]).',
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
  // (3) Multi-parent multi-species seeding_session (Phase 47 Plan 02).
  // Canonical May-22 shape: 11 children across 5 groups (3 SHI singletons + 2 KOY
  // multi-child groups). Session-wide SEQ counter: SHI_1..3, KOY_4..7, KOY_8..11.
  // Demonstrates: (a) type=seeding_session emitted instead of N separate seeding
  // drafts, (b) inline {value, confidence, sources[]} provenance on every group
  // field, (c) photo_wins_implicit conflict resolution with conflicts[] entry,
  // (d) child_block_names sources = ['paper_log_photo'] when SEQ comes from photo.
  {
    role: 'user',
    content: [
      { type: 'tool_result', tool_use_id: 'tu_fewshot_2', content: [{ type: 'text', text: 'accepted' }] },
      { type: 'text', text: 'corpus_context: {"default_year": 2026}' },
      { type: 'text', text: 'In-flight draft: none' },
      {
        type: 'text',
        text: [
          'Audio transcript: "May 22, inoc day, 11 blocks total. Three shiitakes,',
          'one from 260103_SHI_5, one from 260210_SHI_8, one from 260318_SHI_12.',
          'Then eight king oysters, four from 260118_KOY_23, four from 260425_KOY_4."',
          'Paper-log photo (multi-row page, header dated 22/5):',
          '  Row 1: SHI, parent 260103_SHI_5, qty 1, block 260522_SHI_1',
          '  Row 2: SHI, parent 260210_SHI_8, qty 1, block 260522_SHI_2',
          '  Row 3: SHI, parent 260318_SHI_12, qty 1, block 260522_SHI_3',
          '  Row 4: KOY, parent 260118_KOY_25, qty 4, blocks 260522_KOY_4..7',
          '  Row 5: KOY, parent 260425_KOY_4, qty 4, blocks 260522_KOY_8..11',
          'Note: audio says KOY parent is 260118_KOY_23 but photo shows 260118_KOY_25.',
        ].join('\n'),
      },
    ],
  },
  {
    role: 'assistant',
    content: [
      {
        type: 'tool_use',
        id: 'tu_fewshot_4',
        name: 'submit_extraction',
        input: {
          drafts: [
            {
              draft: {
                type: 'seeding_session',
                event_date: '2026-05-22',
                groups: [
                  {
                    parent: { value: '260103_SHI_5', confidence: 0.95, sources: ['audio', 'paper_log_photo'] },
                    species: { value: 'SHI', confidence: 0.98, sources: ['audio', 'paper_log_photo'] },
                    qty: { value: 1, confidence: 0.98, sources: ['audio', 'paper_log_photo'] },
                    child_block_names: { value: ['260522_SHI_1'], confidence: 0.95, sources: ['paper_log_photo'] },
                  },
                  {
                    parent: { value: '260210_SHI_8', confidence: 0.95, sources: ['audio', 'paper_log_photo'] },
                    species: { value: 'SHI', confidence: 0.98, sources: ['audio', 'paper_log_photo'] },
                    qty: { value: 1, confidence: 0.98, sources: ['audio', 'paper_log_photo'] },
                    child_block_names: { value: ['260522_SHI_2'], confidence: 0.95, sources: ['paper_log_photo'] },
                  },
                  {
                    parent: { value: '260318_SHI_12', confidence: 0.95, sources: ['audio', 'paper_log_photo'] },
                    species: { value: 'SHI', confidence: 0.98, sources: ['audio', 'paper_log_photo'] },
                    qty: { value: 1, confidence: 0.98, sources: ['audio', 'paper_log_photo'] },
                    child_block_names: { value: ['260522_SHI_3'], confidence: 0.95, sources: ['paper_log_photo'] },
                  },
                  {
                    // Conflict: audio said 260118_KOY_23, photo said 260118_KOY_25. Photo wins.
                    parent: { value: '260118_KOY_25', confidence: 0.95, sources: ['audio', 'paper_log_photo'] },
                    species: { value: 'KOY', confidence: 0.98, sources: ['audio', 'paper_log_photo'] },
                    qty: { value: 4, confidence: 0.98, sources: ['audio', 'paper_log_photo'] },
                    child_block_names: { value: ['260522_KOY_4', '260522_KOY_5', '260522_KOY_6', '260522_KOY_7'], confidence: 0.95, sources: ['paper_log_photo'] },
                  },
                  {
                    parent: { value: '260425_KOY_4', confidence: 0.95, sources: ['audio', 'paper_log_photo'] },
                    species: { value: 'KOY', confidence: 0.98, sources: ['audio', 'paper_log_photo'] },
                    qty: { value: 4, confidence: 0.98, sources: ['audio', 'paper_log_photo'] },
                    child_block_names: { value: ['260522_KOY_8', '260522_KOY_9', '260522_KOY_10', '260522_KOY_11'], confidence: 0.95, sources: ['paper_log_photo'] },
                  },
                ],
                conflicts: [
                  {
                    path: 'groups[3].parent.value',
                    candidates: [
                      { value: '260118_KOY_23', source: 'audio', confidence: 0.7 },
                      { value: '260118_KOY_25', source: 'paper_log_photo', confidence: 0.95 },
                    ],
                    resolution: 'photo_wins_implicit',
                  },
                ],
              },
              per_field_confidence: {
                event_date: 0.98,
                'groups[0].parent': 0.95,
                'groups[0].child_block_names': 0.95,
                'groups[3].parent': 0.95,
                'groups[4].child_block_names': 0.95,
              },
            },
          ],
          continuity: 'start_new',
          continuity_reason: 'Multi-parent inoc session with no in-flight draft.',
        },
      },
    ],
  },
  // (4) Continuity = replace (correction to in-flight draft).
  {
    role: 'user',
    content: [
      { type: 'tool_result', tool_use_id: 'tu_fewshot_4', content: [{ type: 'text', text: 'accepted' }] },
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
