'use strict';

const commitActivity = require('../../src/farmos/commits/commit-activity');
const { makeMockClient } = require('./mock-client');

describe('commit-activity (Phase 40 Plan 04)', () => {
  it('resolved QRs become the log asset relationship', async () => {
    const client = makeMockClient({ knownAssetsByQr: { Q1: 'asset-1' } });
    const r = await commitActivity(client, {
      id: 'd1', log_type: 'activity',
      draft_json: { activity_subtype: 'water', qr_codes: ['Q1'], timestamp: 1700000000 },
    }, {});
    expect(r.ok).toBe(true);
    expect(client._created.logs[0].payload.data.relationships.asset.data[0].id).toBe('asset-1');
  });

  it('zero resolved QRs -> reason=no_target_asset_for_activity, no log POSTed', async () => {
    const client = makeMockClient();
    const r = await commitActivity(client, {
      id: 'd1', log_type: 'activity',
      draft_json: { activity_subtype: 'water', qr_codes: [], timestamp: 1700000000 },
    }, {});
    expect(r.ok).toBe(false);
    expect(r.reason).toBe('no_target_asset_for_activity');
    expect(client._created.logs.length).toBe(0);
  });

  it('name leads with activity_subtype', async () => {
    const client = makeMockClient({ knownAssetsByQr: { Q: 'a' } });
    await commitActivity(client, {
      id: 'd1', log_type: 'activity',
      draft_json: { activity_subtype: 'sterilize', qr_codes: ['Q'], timestamp: 1700000000 },
    }, {});
    expect(client._created.logs[0].payload.data.attributes.name).toMatch(/^sterilize /);
  });

  it('multi-QR multi-asset case', async () => {
    const client = makeMockClient({ knownAssetsByQr: { Q1: 'a1', Q2: 'a2' } });
    await commitActivity(client, {
      id: 'd1', log_type: 'activity',
      draft_json: { activity_subtype: 'relocate', qr_codes: ['Q1', 'Q2'], timestamp: 1700000000 },
    }, {});
    const ids = client._created.logs[0].payload.data.relationships.asset.data.map((a) => a.id);
    expect(ids).toEqual(['a1', 'a2']);
  });
});
