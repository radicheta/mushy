'use strict';

const commitInput = require('../../src/farmos/commits/commit-input');
const { makeMockClient } = require('./mock-client');

describe('commit-input (Phase 40 Plan 04)', () => {
  it('zero resolved QRs -> reason no_target_asset_for_activity', async () => {
    const client = makeMockClient();
    const r = await commitInput(client, {
      id: 'd1', log_type: 'input',
      draft_json: { qr_codes: [], input_ingredients: ['oats'], timestamp: 1700000000 },
    }, {});
    expect(r.ok).toBe(false);
    expect(r.reason).toBe('no_target_asset_for_activity');
  });

  it('ingredient list serializes into notes in supplied order', async () => {
    const client = makeMockClient({ knownAssetsByQr: { Q: 'a' } });
    await commitInput(client, {
      id: 'd1', log_type: 'input',
      draft_json: {
        qr_codes: ['Q'], timestamp: 1700000000,
        input_ingredients: ['oat 1kg', 'gypsum 50g'],
      },
    }, {});
    const notes = client._created.logs[0].payload.data.attributes.notes.value;
    expect(notes).toMatch(/Ingredients:\n- oat 1kg\n- gypsum 50g/);
  });

  it('empty ingredients still creates a log', async () => {
    const client = makeMockClient({ knownAssetsByQr: { Q: 'a' } });
    const r = await commitInput(client, {
      id: 'd1', log_type: 'input',
      draft_json: { qr_codes: ['Q'], input_ingredients: [], timestamp: 1700000000 },
    }, {});
    expect(r.ok).toBe(true);
    expect(client._created.logs.length).toBe(1);
  });
});
