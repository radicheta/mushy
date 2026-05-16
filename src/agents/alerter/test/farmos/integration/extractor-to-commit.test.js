'use strict';

// Phase 43 Plan 05: 5-test chain integration suite.
//
// Decisions applied (from 43-CONTEXT.md):
//   D-13: file location; no FARMOS_INTEGRATION gate (SCHEMA-04)
//   D-14: LLM side mocked via jest.mock('@anthropic-ai/sdk') -- same pattern as extractor.test.js
//   D-15: farmOS side mocked via test/farmos/mock-client.js; no modification to mock-client
//   D-16: Test 2 uses the verbatim 2026-05-15 lion's-mane transcript from 43-FIXTURES.md
//   D-17: each test asserts (a) post-extract shape, (b) post-normalize shape, (c) commit result
//
// Phase 43 SCHEMA-04: this suite runs under `npm test` by default.
// Do NOT add a FARMOS_INTEGRATION=1 gate.
//
// Test 2 is the named 2026-05-15 regression guard: the lion's-mane audio produced
// asset_ref='<UNKNOWN>' because the farmer never named a specific block ID. Before
// normalize.js, commit-activity crashed on the wrong field names. After normalize.js,
// it reaches the no_target_asset_for_activity check cleanly -- a classifiable failure.

// --- Mock @anthropic-ai/sdk BEFORE any require of extractor.js ---
const mockCreate = jest.fn();
jest.mock('@anthropic-ai/sdk', () => {
  return jest.fn().mockImplementation(() => ({
    messages: { create: mockCreate },
  }));
});

const { createExtractor } = require('../../../src/extraction/extractor');
const { normalize } = require('../../../src/farmos/commits/normalize');
const { commit } = require('../../../src/farmos/commits/commit-router');
const { makeMockClient } = require('../mock-client');

const silentLogger = { warn: () => {}, info: () => {}, error: () => {} };

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// Build a canned Anthropic tool_use response wrapping the Submission envelope.
function toolUseResponse(draftPayload) {
  return {
    id: 'msg_test',
    type: 'message',
    role: 'assistant',
    model: 'claude-sonnet-4-6',
    content: [{
      type: 'tool_use',
      id: 'tu_test',
      name: 'submit_extraction',
      input: {
        drafts: [{
          draft: draftPayload,
          per_field_confidence: Object.fromEntries(
            Object.keys(draftPayload)
              .filter((k) => k !== 'type')
              .map((k) => [k, 0.9]),
          ),
        }],
        continuity: 'start_new',
        continuity_reason: 'Integration test fixture.',
      },
    }],
    stop_reason: 'tool_use',
    usage: { input_tokens: 50, output_tokens: 80 },
  };
}

// Build a minimal signal_draft envelope around a draft_json payload.
// log_type must be set at the top level (used by commit-router dispatch guard
// and normalize switch).
function makeDraft(logType, draftJson, extra) {
  return Object.assign({
    id: 'draft-integration-' + logType,
    log_type: logType,
    draft_json: draftJson,
    source_capture_ids: [],
  }, extra || {});
}

// ---------------------------------------------------------------------------
// Suite
// ---------------------------------------------------------------------------

describe('extractor -> normalize -> commit chain (Phase 43 Plan 05)', () => {
  let extractor;

  beforeEach(() => {
    mockCreate.mockReset();
    extractor = createExtractor({ apiKey: 'sk-test', logger: silentLogger });
  });

  // -------------------------------------------------------------------------
  // Test 1: seeding chain
  // -------------------------------------------------------------------------
  it('Test 1 (seeding): extractor-shape -> normalize -> commit_success with block created', async () => {
    // Extractor-shape payload for a seeding event.
    // Species 'SHI' -> normalize produces species_code: 'SHI'; mock-client has SHI in fungiTypeUuids.
    const extractorDraft = {
      type: 'seeding',
      species: 'SHI',
      block_name: '260516_SHI_1',
      qty: 1000,
      event_timestamp: '2026-05-16T10:00:00Z',
      confidence: { species: 0.95, block_name: 0.95, qty: 0.95, event_timestamp: 0.9 },
    };
    mockCreate.mockResolvedValueOnce(toolUseResponse(extractorDraft));

    // (a) Post-extract boundary -- extractor-shape markers must be present.
    const extractResult = await extractor.extract({
      captures: [{ text: 'Inoc-ed block 260516_DT_1 with 1kg shiitake grain' }],
      inFlightDraft: null,
    });
    // [extract boundary]
    expect(extractResult.ok).toBe(true);
    const draftJson = extractResult.draft;
    expect(draftJson.type).toBe('seeding');
    expect(draftJson.species).toBe('SHI');
    expect(draftJson.block_name).toBe('260516_SHI_1');
    expect(draftJson.qty).toBe(1000);
    expect(typeof draftJson.event_timestamp).toBe('string');

    // (b) Post-normalize boundary -- commit-shape markers must be present.
    const rawDraft = makeDraft('seeding', draftJson);
    const normalized = normalize(rawDraft);
    // [normalize boundary]
    expect(normalized.draft_json.species_code).toBe('SHI');
    expect(typeof normalized.draft_json.timestamp).toBe('number');
    expect(normalized.draft_json.timestamp)
      .toBe(Math.floor(Date.parse('2026-05-16T10:00:00Z') / 1000));
    // Seeding extractor-shape has no asset_ref field, so qr_codes guard doesn't fire.
    // Normalize leaves qr_codes absent; commit-seeding uses block_name + qr_codes=[] path.

    // (c) Post-commit boundary -- block created, seeding log POSTed.
    // [commit boundary]
    const client = makeMockClient();
    const result = await commit(client, rawDraft, {});
    expect(result.ok).toBe(true);
    expect(client._created.assets.length).toBe(1);
    expect(client._created.logs.length).toBe(1);
    expect(client._created.assets[0].name).toBe('260516_SHI_1');
  });

  // -------------------------------------------------------------------------
  // Test 2: activity chain -- 2026-05-15 REGRESSION GUARD (D-16)
  // -------------------------------------------------------------------------
  it('Test 2 (activity, 2026-05-15 regression guard): lion\'s-mane transcript -> classified failure', async () => {
    // --- VERBATIM 2026-05-15 transcript (43-FIXTURES.md, D-16) ---
    // Source: .planning/notes/2026-05-15-lion-mane-bridged-uat.md line 25 (Timeline, 23:30:51 UTC)
    // Draft ID: 1fb28e709118807ed301b4c3b45f5042f194eabb9ab0000f288e9163fec93733
    // Do NOT paraphrase. The extractor correctly returned asset_ref='<UNKNOWN>' because
    // the farmer never named a specific block ID in this audio note.
    const verbatimTranscript = "Two days ago, I put a lion's mane block into the fruiting chamber to fruiting Two days ago forgot to tell to tell you so yeah log it up Lion";

    // Live extractor output at 2026-05-15 23:30:57 UTC.
    const extractorDraft = {
      type: 'activity',
      name: 'relocate',
      asset_ref: '<UNKNOWN>',
      event_timestamp: '2026-05-13T00:00:00Z',
      confidence: { name: 0.9, asset_ref: 0.0, event_timestamp: 0.6 },
    };
    mockCreate.mockResolvedValueOnce(toolUseResponse(extractorDraft));

    // (a) Post-extract boundary -- extractor-shape markers (as captured live 2026-05-15).
    const extractResult = await extractor.extract({
      captures: [{ transcript: verbatimTranscript }],
      inFlightDraft: null,
    });
    // [extract boundary]
    expect(extractResult.ok).toBe(true);
    const draftJson = extractResult.draft;
    expect(draftJson.type).toBe('activity');
    expect(draftJson.name).toBe('relocate');
    expect(draftJson.asset_ref).toBe('<UNKNOWN>');
    expect(typeof draftJson.event_timestamp).toBe('string');
    expect(draftJson.event_timestamp).toBe('2026-05-13T00:00:00Z');

    // (b) Post-normalize boundary -- commit-shape markers (D-03 common transforms applied).
    const rawDraft = makeDraft('activity', draftJson);
    const normalized = normalize(rawDraft);
    // [normalize boundary]
    expect(normalized.draft_json.activity_subtype).toBe('relocate');   // name -> activity_subtype
    expect(Array.isArray(normalized.draft_json.qr_codes)).toBe(true);
    expect(normalized.draft_json.qr_codes).toEqual([]);                // <UNKNOWN> filtered -> []
    expect(typeof normalized.draft_json.timestamp).toBe('number');

    // (c) Post-commit boundary -- CLASSIFIED failure, not a crash.
    // Before normalize.js: commit-activity crashed on wrong field names (missing qr_codes, activity_subtype).
    // After normalize.js: reaches no_target_asset_for_activity check cleanly.
    // This is the regression this test guards.
    // [commit boundary]
    const client = makeMockClient();
    const result = await commit(client, rawDraft, {});
    expect(result.ok).toBe(false);
    expect(result.reason).toBe('no_target_asset_for_activity');
    expect(client._created.logs.length).toBe(0); // no log POSTed on failure
  });

  // -------------------------------------------------------------------------
  // Test 3: observation chain
  // -------------------------------------------------------------------------
  it('Test 3 (observation): extractor-shape -> normalize -> commit_success with notes containing state', async () => {
    const extractorDraft = {
      type: 'observation',
      asset_ref: '260513_SHI_2',
      state: 'pinning',
      event_timestamp: '2026-05-16T09:00:00Z',
      confidence: { asset_ref: 0.95, state: 0.9, event_timestamp: 0.8 },
    };
    mockCreate.mockResolvedValueOnce(toolUseResponse(extractorDraft));

    // (a) Post-extract boundary.
    const extractResult = await extractor.extract({
      captures: [{ text: 'pin emergence on 260513_SHI_2' }],
      inFlightDraft: null,
    });
    // [extract boundary]
    expect(extractResult.ok).toBe(true);
    const draftJson = extractResult.draft;
    expect(draftJson.type).toBe('observation');
    expect(draftJson.asset_ref).toBe('260513_SHI_2');
    expect(draftJson.state).toBe('pinning');
    expect(typeof draftJson.event_timestamp).toBe('string');

    // (b) Post-normalize boundary.
    const rawDraft = makeDraft('observation', draftJson);
    const normalized = normalize(rawDraft);
    // [normalize boundary]
    expect(Array.isArray(normalized.draft_json.qr_codes)).toBe(true);
    expect(normalized.draft_json.qr_codes).toEqual(['260513_SHI_2']);
    expect(typeof normalized.draft_json.timestamp).toBe('number');
    // D-observation: state appended to notes as "state: pinning"
    expect(normalized.draft_json.notes).toContain('state: pinning');

    // (c) Post-commit boundary.
    // Seed mock-client with asset by name (tests name-lookup path in resolveQr, D-06).
    const client = makeMockClient({ knownAssetsByName: { '260513_SHI_2': 'asset-shi-2' } });
    const result = await commit(client, rawDraft, {});
    // [commit boundary]
    expect(result.ok).toBe(true);
    expect(client._created.logs.length).toBe(1);
    const logPayload = client._created.logs[0].payload;
    const assetRels = logPayload.data.relationships.asset.data;
    expect(assetRels.some((a) => a.id === 'asset-shi-2')).toBe(true);
    // notes is {value, format} per logs.js:30
    expect(logPayload.data.attributes.notes.value).toContain('state: pinning');
  });

  // -------------------------------------------------------------------------
  // Test 4: input chain
  // -------------------------------------------------------------------------
  it('Test 4 (input): extractor-shape -> normalize -> commit_success with recipe_lot prepended in notes', async () => {
    // NOTE: multi-ingredient extractor schema extension is deferred (D-09 + v1.8 candidate).
    // This test exercises the recipe_lot PREPEND (D-09) to notes.
    const extractorDraft = {
      type: 'input',
      recipe_lot: 'RB-2026-05',
      asset_ref: '260514_KOY_3',
      event_timestamp: '2026-05-16T08:00:00Z',
      confidence: { recipe_lot: 0.9, asset_ref: 0.9, event_timestamp: 0.85 },
    };
    mockCreate.mockResolvedValueOnce(toolUseResponse(extractorDraft));

    // (a) Post-extract boundary.
    const extractResult = await extractor.extract({
      captures: [{ text: 'Mixed substrate for 260514_KOY_3 with oat 1kg, gypsum 50g, recipe RB-2026-05' }],
      inFlightDraft: null,
    });
    // [extract boundary]
    expect(extractResult.ok).toBe(true);
    const draftJson = extractResult.draft;
    expect(draftJson.type).toBe('input');
    expect(draftJson.recipe_lot).toBe('RB-2026-05');
    expect(draftJson.asset_ref).toBe('260514_KOY_3');
    expect(typeof draftJson.event_timestamp).toBe('string');

    // (b) Post-normalize boundary.
    const rawDraft = makeDraft('input', draftJson);
    const normalized = normalize(rawDraft);
    // [normalize boundary]
    expect(Array.isArray(normalized.draft_json.qr_codes)).toBe(true);
    expect(normalized.draft_json.qr_codes).toEqual(['260514_KOY_3']);
    expect(typeof normalized.draft_json.timestamp).toBe('number');
    // D-09: recipe_lot PREPENDED to notes (starts at position 0, not appended).
    expect(normalized.draft_json.notes).toMatch(/^recipe_lot: RB-2026-05/);

    // (c) Post-commit boundary.
    const client = makeMockClient({ knownAssetsByName: { '260514_KOY_3': 'asset-koy-3' } });
    const result = await commit(client, rawDraft, {});
    // [commit boundary]
    expect(result.ok).toBe(true);
    expect(client._created.logs.length).toBe(1);
    // notes is {value, format} per logs.js:30
    const logNotes = client._created.logs[0].payload.data.attributes.notes.value;
    expect(logNotes).toMatch(/^recipe_lot: RB-2026-05/);
  });

  // -------------------------------------------------------------------------
  // Test 5: harvest chain
  // -------------------------------------------------------------------------
  it('Test 5 (harvest): extractor-shape -> normalize -> commit_success with single synthesized bag via name-fallback', async () => {
    // NOTE: multi-bag model is a v1.8 candidate (D-12). This test exercises the single-bag
    // synthesis path: qty_g -> bags:[{weight_grams: qty_g}].
    //
    // source_block_refs=['260512_DT_11'] is seeded in mock-client by NAME only (no id_tag entry).
    // This exercises Plan 43-02 name-fallback: resolveQr id_tag miss -> name lookup succeeds.
    // Strain 'DT' is regex-extracted from harvest_batch_name 'HBATCH-2026-05-15-DT-001'.
    const extractorDraft = {
      type: 'harvest',
      harvest_batch_id: 'HBATCH-2026-05-15-DT-001',
      source_block_refs: ['260512_DT_11'],
      qty_g: 740,
      event_timestamp: '2026-05-16T07:00:00Z',
      confidence: { harvest_batch_id: 0.9, source_block_refs: 0.9, qty_g: 0.85, event_timestamp: 0.9 },
    };
    mockCreate.mockResolvedValueOnce(toolUseResponse(extractorDraft));

    // (a) Post-extract boundary.
    const extractResult = await extractor.extract({
      captures: [{ text: 'Picked 3 bags from 260512_DT_11: 250g, 230g, 260g, batch HBATCH-2026-05-15-DT-001' }],
      inFlightDraft: null,
    });
    // [extract boundary]
    expect(extractResult.ok).toBe(true);
    const draftJson = extractResult.draft;
    expect(draftJson.type).toBe('harvest');
    expect(draftJson.harvest_batch_id).toBe('HBATCH-2026-05-15-DT-001');
    expect(Array.isArray(draftJson.source_block_refs)).toBe(true);
    expect(draftJson.source_block_refs).toContain('260512_DT_11');
    expect(typeof draftJson.qty_g).toBe('number');
    expect(draftJson.qty_g).toBe(740);
    expect(typeof draftJson.event_timestamp).toBe('string');

    // (b) Post-normalize boundary.
    const rawDraft = makeDraft('harvest', draftJson);
    const normalized = normalize(rawDraft);
    // [normalize boundary]
    // D-05: source_block_refs -> source_qr_codes verbatim rename.
    expect(Array.isArray(normalized.draft_json.source_qr_codes)).toBe(true);
    expect(normalized.draft_json.source_qr_codes).toEqual(['260512_DT_11']);
    // D-12: qty_g -> bags single synthesized bag (multi-bag deferred to v1.8).
    expect(Array.isArray(normalized.draft_json.bags)).toBe(true);
    expect(normalized.draft_json.bags.length).toBe(1);
    expect(normalized.draft_json.bags[0].weight_grams).toBe(740);
    // harvest_batch_id -> harvest_batch_name.
    expect(normalized.draft_json.harvest_batch_name).toBe('HBATCH-2026-05-15-DT-001');
    expect(typeof normalized.draft_json.timestamp).toBe('number');

    // (c) Post-commit boundary.
    // Seed by name only (no id_tag) to exercise Plan 43-02 name-fallback.
    const client = makeMockClient({ knownAssetsByName: { '260512_DT_11': 'dt-block-src' } });
    const result = await commit(client, rawDraft, {});
    // [commit boundary]
    expect(result.ok).toBe(true);
    expect(result.asset_ids.length).toBe(1); // one bag asset created
    expect(client._created.logs.length).toBe(1);
    const logPayload = client._created.logs[0].payload;
    const assetRelIds = logPayload.data.relationships.asset.data.map((a) => a.id);
    // Source block must appear in harvest log's relationships.
    expect(assetRelIds).toContain('dt-block-src');
  });
});
