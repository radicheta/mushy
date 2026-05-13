'use strict';

const fs = require('fs');
const path = require('path');
const os = require('os');
const commitObservation = require('../../src/farmos/commits/commit-observation');
const { makeMockClient } = require('./mock-client');

describe('commit-observation (Phase 40 Plan 04)', () => {
  let tmpDir; let realPath;
  beforeAll(async () => {
    tmpDir = await fs.promises.mkdtemp(path.join(os.tmpdir(), 'co-obs-'));
    realPath = path.join(tmpDir, 'p.jpg');
    await fs.promises.writeFile(realPath, Buffer.from([0xff]));
  });
  afterAll(async () => { try { await fs.promises.rm(tmpDir, { recursive: true }); } catch (_) {} });

  it('2 valid attachments + 1 missing -> fileIds.length===2 + commit ok', async () => {
    const client = makeMockClient({ knownAssetsByQr: { Q: 'a' } });
    const realPath2 = path.join(tmpDir, 'p2.jpg');
    await fs.promises.writeFile(realPath2, Buffer.from([0xfe]));
    let captureCalled = 0;
    const ctx = {
      capturePathsFor: async () => { captureCalled++; return [realPath, '/nope/x.jpg', realPath2]; },
    };
    const r = await commitObservation(client, {
      id: 'd1', log_type: 'observation', source_capture_ids: ['cap-1'],
      draft_json: { qr_codes: ['Q'], timestamp: 1700000000 },
    }, ctx);
    expect(r.ok).toBe(true);
    expect(r.file_ids.length).toBe(2);
    expect(captureCalled).toBe(1);
  });

  it('zero attachments -> log POSTed without relationships.file', async () => {
    const client = makeMockClient({ knownAssetsByQr: { Q: 'a' } });
    const r = await commitObservation(client, {
      id: 'd2', log_type: 'observation', source_capture_ids: [],
      draft_json: { qr_codes: ['Q'], timestamp: 1700000000 },
    }, {});
    expect(r.ok).toBe(true);
    const log = client._created.logs[0];
    expect(log.payload.data.relationships.file).toBeUndefined();
  });

  it('no QR target -> reason observation_requires_target', async () => {
    const client = makeMockClient();
    const r = await commitObservation(client, {
      id: 'd3', log_type: 'observation', source_capture_ids: [],
      draft_json: { qr_codes: [], timestamp: 1700000000 },
    }, {});
    expect(r.ok).toBe(false);
    expect(r.reason).toBe('observation_requires_target');
  });
});
