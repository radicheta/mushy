'use strict';

const logs = require('../../src/farmos/logs');

function mockClient() {
  return {
    post: jest.fn(async () => ({ ok: true, status: 201, body: { data: { id: 'log-1' } } })),
  };
}

describe('logs.js (Phase 40 Plan 03)', () => {
  // Phase 48 Plan 01: iterate NATIVE_LOG_TYPES (createLog allow-list), not LOG_TYPES
  // which now also includes the composite 'seeding_session' (router-only).
  for (const t of logs.NATIVE_LOG_TYPES) {
    it(`createLog "${t}" posts to /api/log/${t} with correct payload shape`, async () => {
      const client = mockClient();
      await logs.createLog(client, t, {
        name: `${t} test`,
        timestamp: 1700000000.7,
        assetIds: ['a1'],
        notes: 'hi',
        draftId: 'd1',
      });
      const url = client.post.mock.calls[0][0];
      const body = client.post.mock.calls[0][1];
      expect(url).toBe('/api/log/' + t);
      expect(body.data.type).toBe('log--' + t);
      expect(body.data.attributes.timestamp).toBe(1700000000); // Math.floor
      expect(body.data.attributes.notes.value).toMatch(/mushy:draft:d1/);
      expect(body.data.relationships.asset.data[0].id).toBe('a1');
    });
  }

  it('unsupported logType throws UnsupportedLogTypeError without fetch', async () => {
    const client = mockClient();
    await expect(logs.createLog(client, 'garbage', { name: 'x', timestamp: 0, draftId: 'd' })).rejects.toThrow(/unsupported_log_type/);
    expect(client.post).not.toHaveBeenCalled();
  });

  it('fileIds embedded in relationships.file when supplied', async () => {
    const client = mockClient();
    await logs.createLog(client, 'observation', {
      name: 'obs', timestamp: 1000, assetIds: ['a1'], fileIds: ['f1', 'f2'], draftId: 'd',
    });
    const body = client.post.mock.calls[0][1];
    expect(body.data.relationships.file.data.map((d) => d.id)).toEqual(['f1', 'f2']);
  });
});

// ============================================================================
// Phase 51 UPSERT-02: LOG_STABLE_KEYS table + upsertLog
// ============================================================================

describe('LOG_STABLE_KEYS table (Phase 51 UPSERT-02)', () => {
  it('seeding is a function that builds the asset.id filter path', () => {
    expect(typeof logs.LOG_STABLE_KEYS.seeding).toBe('function');
    const k = logs.LOG_STABLE_KEYS.seeding({ assetIds: ['a1'] });
    expect(k).toEqual({ path: '/api/log/seeding?filter[asset.id][value]=a1' });
  });

  it('seeding with empty assetIds returns null', () => {
    expect(logs.LOG_STABLE_KEYS.seeding({ assetIds: [] })).toBe(null);
    expect(logs.LOG_STABLE_KEYS.seeding({})).toBe(null);
  });

  it('seeding URL-encodes the asset id', () => {
    const k = logs.LOG_STABLE_KEYS.seeding({ assetIds: ['a/b c'] });
    expect(k.path).toBe('/api/log/seeding?filter[asset.id][value]=' + encodeURIComponent('a/b c'));
  });

  it('activity is null (POST-only)', () => {
    expect(logs.LOG_STABLE_KEYS.activity).toBe(null);
  });
  it('input is null', () => { expect(logs.LOG_STABLE_KEYS.input).toBe(null); });
  it('observation is null', () => { expect(logs.LOG_STABLE_KEYS.observation).toBe(null); });
  it('harvest is null', () => { expect(logs.LOG_STABLE_KEYS.harvest).toBe(null); });
});

describe('upsertLog (Phase 51 UPSERT-02)', () => {
  // Build a richer mock with controllable GET-by-filter, GET-by-id, PATCH.
  // seedLogs: array of full log bodies returned by the seeding filter lookup.
  // logsById: keyed by id, full body returned by GET /api/log/seeding/<id>
  function richMock({ seedLogs = [], logsById = {}, patchFails412Once = new Set(), createLogIdSeq = 'log-new-1' } = {}) {
    const calls = [];
    let _seq = 1;
    const _force412 = new Set(patchFails412Once);
    const client = {
      _calls: calls,
      get: jest.fn(async (path) => {
        calls.push({ method: 'GET', path });
        let m = /^\/api\/log\/seeding\?filter\[asset\.id\]\[value\]=([^&]+)$/.exec(path);
        if (m) {
          return { ok: true, status: 200, body: { data: seedLogs } };
        }
        m = /^\/api\/log\/seeding\/([A-Za-z0-9-]+)$/.exec(path);
        if (m) {
          const id = m[1];
          if (logsById[id]) return { ok: true, status: 200, body: { data: logsById[id] } };
          return { ok: false, status: 404, body: {} };
        }
        return { ok: true, status: 200, body: { data: [] } };
      }),
      post: jest.fn(async (path, body) => {
        calls.push({ method: 'POST', path, body });
        const id = createLogIdSeq + '-' + (_seq++);
        return { ok: true, status: 201, body: { data: { id, type: 'log--seeding' } } };
      }),
      patch: jest.fn(async (path, body, opts) => {
        calls.push({ method: 'PATCH', path, body, headers: opts && opts.headers });
        const m = /^\/api\/log\/[a-z_]+\/([A-Za-z0-9-]+)$/.exec(path);
        const id = m ? m[1] : null;
        if (id && _force412.has(id)) {
          _force412.delete(id);
          return { ok: false, status: 412, body: { errors: [{ status: '412' }] } };
        }
        return { ok: true, status: 200, body: { data: { id, type: 'log--seeding', attributes: { drupal_internal__revision_id: 2 } } } };
      }),
    };
    return client;
  }

  it('seeding miss: no existing log -> creates new via POST, outcome=created', async () => {
    const client = richMock({ seedLogs: [] });
    const r = await logs.upsertLog(client, 'seeding', {
      name: 'inoc', timestamp: 1700000000, assetIds: ['a1'], draftId: 'd1',
    });
    expect(r.ok).toBe(true);
    expect(r.outcome).toBe('created');
    expect(r.conflicts).toEqual([]);
    expect(r.etag_source).toBe(null);
    expect(r.http_status).toBe(201);
    expect(client.post).toHaveBeenCalledTimes(1);
    expect(client.patch).not.toHaveBeenCalled();
    // Lookup happened
    expect(client.get).toHaveBeenCalledWith(expect.stringContaining('/api/log/seeding?filter[asset.id][value]=a1'));
  });

  it('seeding hit: existing log + new fileIds -> PATCH merges file set-union, outcome=patched', async () => {
    const existing = {
      id: 'L1',
      type: 'log--seeding',
      attributes: {
        name: 'inoc',
        timestamp: 1700000000,
        status: 'done',
        notes: { value: 'mushy:draft:d_old', format: 'plain_text' },
        created: '2026-05-22T10:00:00+00:00',
        drupal_internal__revision_id: 7,
      },
      relationships: {
        asset: { data: [{ type: 'asset--fungi', id: 'a1' }] },
        file: { data: [] },
      },
    };
    const client = richMock({
      seedLogs: [{ id: 'L1', attributes: { created: existing.attributes.created } }],
      logsById: { L1: existing },
    });
    const r = await logs.upsertLog(client, 'seeding', {
      name: 'inoc',
      timestamp: 1700000000,
      assetIds: ['a1'],
      fileIds: ['f1'],
      notes: '',
      draftId: 'd_new',
    });
    expect(r.ok).toBe(true);
    expect(r.outcome).toBe('patched');
    expect(r.logId).toBe('L1');
    expect(r.conflicts).toEqual([]);
    expect(r.etag_source).toBe('soft_compare');
    expect(r.http_status).toBe(200);
    expect(client.patch).toHaveBeenCalledTimes(1);
    const patchCall = client.patch.mock.calls[0];
    expect(patchCall[0]).toBe('/api/log/seeding/L1');
    const body = patchCall[1];
    const fileIds = body.data.relationships.file.data.map((d) => d.id).sort();
    expect(fileIds).toEqual(['f1']);
    expect(body.data.relationships.file.data[0]).toEqual({ type: 'file--file', id: 'f1' });
  });

  it('seeding noop: incoming brings no new fields -> outcome=noop, no PATCH', async () => {
    const existing = {
      id: 'L1',
      type: 'log--seeding',
      attributes: {
        name: 'inoc',
        timestamp: 1700000000,
        status: 'done',
        notes: { value: 'mushy:draft:d_old', format: 'plain_text' },
        created: '2026-05-22T10:00:00+00:00',
        drupal_internal__revision_id: 7,
      },
      relationships: {
        asset: { data: [{ type: 'asset--fungi', id: 'a1' }] },
        file: { data: [{ type: 'file--file', id: 'f1' }] },
      },
    };
    const client = richMock({
      seedLogs: [{ id: 'L1', attributes: { created: existing.attributes.created } }],
      logsById: { L1: existing },
    });
    const r = await logs.upsertLog(client, 'seeding', {
      name: 'inoc',
      timestamp: 1700000000,
      assetIds: ['a1'],
      fileIds: ['f1'],
      notes: '',
      draftId: 'd_old', // same trailer
    });
    expect(r.ok).toBe(true);
    expect(r.outcome).toBe('noop');
    expect(r.logId).toBe('L1');
    expect(r.conflicts).toEqual([]);
    expect(client.patch).not.toHaveBeenCalled();
    expect(client.post).not.toHaveBeenCalled();
  });

  it('seeding collision (>1 match): picks oldest by created, emits LogIdentityCollision warning', async () => {
    const olderId = 'L_OLDER';
    const newerId = 'L_NEWER';
    const olderBody = {
      id: olderId,
      type: 'log--seeding',
      attributes: {
        name: 'inoc',
        timestamp: 1700000000,
        status: 'done',
        notes: { value: '', format: 'plain_text' },
        created: '2026-05-22T10:00:00+00:00',
        drupal_internal__revision_id: 1,
      },
      relationships: {
        asset: { data: [{ type: 'asset--fungi', id: 'a1' }] },
        file: { data: [] },
      },
    };
    const newerBody = Object.assign({}, olderBody, {
      id: newerId,
      attributes: Object.assign({}, olderBody.attributes, { created: '2026-05-22T11:00:00+00:00' }),
    });
    // Provide in REVERSE order to ensure sort is what picks the oldest.
    const seedLogs = [
      { id: newerId, attributes: { created: newerBody.attributes.created } },
      { id: olderId, attributes: { created: olderBody.attributes.created } },
    ];
    const client = richMock({
      seedLogs,
      logsById: { [olderId]: olderBody, [newerId]: newerBody },
    });
    const auditLogger = { logCommit: jest.fn(async () => undefined) };
    const r = await logs.upsertLog(client, 'seeding', {
      name: 'inoc',
      timestamp: 1700000000,
      assetIds: ['a1'],
      fileIds: ['f_new'],
      notes: '',
      draftId: 'd1',
      auditLogger,
    });
    expect(r.ok).toBe(true);
    expect(r.logId).toBe(olderId); // older wins
    expect(r.warnings).toEqual(expect.arrayContaining([expect.stringMatching(/LogIdentityCollision/)]));
    // PATCH on the older id
    expect(client.patch).toHaveBeenCalledTimes(1);
    expect(client.patch.mock.calls[0][0]).toBe('/api/log/seeding/' + olderId);
    // Audit logger received the collision event
    expect(auditLogger.logCommit).toHaveBeenCalled();
    const auditCalls = auditLogger.logCommit.mock.calls;
    const collisionCall = auditCalls.find((c) => c[0] === 'log_identity_collision');
    expect(collisionCall).toBeDefined();
    expect(collisionCall[1]).toMatchObject({ log_type: 'seeding', asset_id: 'a1' });
    expect(collisionCall[1].matched_ids).toEqual(expect.arrayContaining([olderId, newerId]));
  });

  it('seeding collision tie-break: same created -> lexicographic by id ASC', async () => {
    const idA = 'L_A';
    const idB = 'L_B';
    const created = '2026-05-22T10:00:00+00:00';
    const bodyA = {
      id: idA, type: 'log--seeding',
      attributes: { name: 'inoc', timestamp: 1700000000, status: 'done', notes: { value: '', format: 'plain_text' }, created, drupal_internal__revision_id: 1 },
      relationships: { asset: { data: [{ type: 'asset--fungi', id: 'a1' }] }, file: { data: [] } },
    };
    const bodyB = Object.assign({}, bodyA, { id: idB });
    const client = richMock({
      seedLogs: [
        { id: idB, attributes: { created } },
        { id: idA, attributes: { created } },
      ],
      logsById: { [idA]: bodyA, [idB]: bodyB },
    });
    const r = await logs.upsertLog(client, 'seeding', {
      name: 'inoc', timestamp: 1700000000, assetIds: ['a1'], fileIds: ['f_new'], draftId: 'd1',
    });
    expect(r.logId).toBe(idA); // lexicographic ASC -> L_A
  });

  it('seeding hit: 412 on first PATCH -> soft-compare retry succeeds once', async () => {
    const existing = {
      id: 'L1', type: 'log--seeding',
      attributes: {
        name: 'inoc', timestamp: 1700000000, status: 'done',
        notes: { value: '', format: 'plain_text' },
        created: '2026-05-22T10:00:00+00:00',
        drupal_internal__revision_id: 7,
      },
      relationships: {
        asset: { data: [{ type: 'asset--fungi', id: 'a1' }] },
        file: { data: [] },
      },
    };
    const client = richMock({
      seedLogs: [{ id: 'L1', attributes: { created: existing.attributes.created } }],
      logsById: { L1: existing },
      patchFails412Once: new Set(['L1']),
    });
    const r = await logs.upsertLog(client, 'seeding', {
      name: 'inoc', timestamp: 1700000000, assetIds: ['a1'], fileIds: ['f1'], draftId: 'd1',
    });
    expect(r.ok).toBe(true);
    expect(r.outcome).toBe('patched');
    // 2 PATCHes (1st fails 412, 2nd succeeds)
    expect(client.patch).toHaveBeenCalledTimes(2);
  });

  it('seeding identity mismatch: incoming assetIds differ from existing -> ok:false reason log_identity_mismatch', async () => {
    const existing = {
      id: 'L1', type: 'log--seeding',
      attributes: { name: 'inoc', timestamp: 1700000000, status: 'done', notes: { value: '', format: 'plain_text' }, created: '2026-05-22T10:00:00+00:00', drupal_internal__revision_id: 1 },
      relationships: {
        asset: { data: [{ type: 'asset--fungi', id: 'a1' }, { type: 'asset--fungi', id: 'a2' }] },
        file: { data: [] },
      },
    };
    const client = richMock({
      seedLogs: [{ id: 'L1', attributes: { created: existing.attributes.created } }],
      logsById: { L1: existing },
    });
    const r = await logs.upsertLog(client, 'seeding', {
      name: 'inoc', timestamp: 1700000000, assetIds: ['a1'], draftId: 'd1', // missing a2
    });
    expect(r.ok).toBe(false);
    expect(r.reason).toBe('log_identity_mismatch');
  });

  it('seeding without assetIds: returns ok:false reason missing_stable_key', async () => {
    const client = richMock({});
    const r = await logs.upsertLog(client, 'seeding', {
      name: 'inoc', timestamp: 1700000000, assetIds: [], draftId: 'd1',
    });
    expect(r.ok).toBe(false);
    expect(r.reason).toBe('missing_stable_key');
    expect(client.get).not.toHaveBeenCalled();
    expect(client.post).not.toHaveBeenCalled();
  });

  it('non-seeding pass-through: activity delegates to createLog (POST), no lookup', async () => {
    const client = richMock({});
    const r = await logs.upsertLog(client, 'activity', {
      name: 'act', timestamp: 1700000000, assetIds: ['a1'], draftId: 'd1',
    });
    expect(r.ok).toBe(true);
    expect(r.outcome).toBe('created');
    expect(r.conflicts).toEqual([]);
    expect(r.etag_source).toBe(null);
    expect(client.post).toHaveBeenCalledTimes(1);
    expect(client.post.mock.calls[0][0]).toBe('/api/log/activity');
    // No filter GET for activity
    const getCalls = client.get.mock.calls.map((c) => c[0]);
    expect(getCalls.find((p) => /^\/api\/log\/activity\?/.test(p))).toBeUndefined();
  });

  it('non-seeding pass-through: harvest delegates to createLog (POST)', async () => {
    const client = richMock({});
    const r = await logs.upsertLog(client, 'harvest', {
      name: 'hv', timestamp: 1700000000, assetIds: ['a1'], draftId: 'd1',
    });
    expect(r.ok).toBe(true);
    expect(r.outcome).toBe('created');
    expect(client.post).toHaveBeenCalledTimes(1);
    expect(client.post.mock.calls[0][0]).toBe('/api/log/harvest');
  });

  it('non-native type: upsertLog throws UnsupportedLogTypeError', async () => {
    const client = richMock({});
    await expect(logs.upsertLog(client, 'bogus', { name: 'x', timestamp: 0, draftId: 'd' }))
      .rejects.toThrow(/unsupported_log_type/);
    expect(client.post).not.toHaveBeenCalled();
    expect(client.patch).not.toHaveBeenCalled();
  });

  it('module.exports includes upsertLog, LOG_STABLE_KEYS, LogIdentityCollision', () => {
    expect(typeof logs.upsertLog).toBe('function');
    expect(typeof logs.LOG_STABLE_KEYS).toBe('object');
    expect(typeof logs.LogIdentityCollision).toBe('function');
    const err = new logs.LogIdentityCollision('seeding', 'a1', ['L1', 'L2']);
    expect(err.name).toBe('LogIdentityCollision');
    expect(err.logType).toBe('seeding');
    expect(err.assetId).toBe('a1');
    expect(err.matchedIds).toEqual(['L1', 'L2']);
  });
});
