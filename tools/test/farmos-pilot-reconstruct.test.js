'use strict';

const { parseArgs, gatherAllLogs, fmtRow, fmtTimeline } = require('../farmos-pilot-reconstruct');

function makeMockClient(byPath) {
  return {
    get: async (path) => {
      for (const [pattern, body] of byPath) {
        if (path.includes(pattern)) {
          return { ok: true, status: 200, body };
        }
      }
      return { ok: true, status: 200, body: { data: [] } };
    },
  };
}

function log(id, type, name, ts, refs) {
  return {
    id,
    type: `log--${type}`,
    attributes: { name, timestamp: ts },
    relationships: { asset: { data: (refs || []).map((u) => ({ id: u, type: 'asset' })) } },
  };
}

describe('parseArgs', () => {
  test('help when no args', () => {
    expect(parseArgs(['node', 'x']).help).toBe(true);
  });
  test('uuid positional', () => {
    expect(parseArgs(['node', 'x', 'block-1']).uuid).toBe('block-1');
  });
});

describe('fmtRow', () => {
  test('formats with type + name + refs', () => {
    const r = fmtRow(log('a1', 'activity', 'cold_shock', '2026-06-10T10:00Z', ['block-1']));
    expect(r).toBe('[2026-06-10T10:00Z] activity cold_shock refs=block-1');
  });
  test('omits name when missing', () => {
    const r = fmtRow({ id: 'x', type: 'log--observation', attributes: { timestamp: '2026-05-20T10:00Z' } });
    expect(r).toBe('[2026-05-20T10:00Z] observation');
  });
});

describe('gatherAllLogs: full pilot lifecycle', () => {
  test('sorted ascending by timestamp; surfaces bag logs via harvest refs', async () => {
    const byPath = [
      // Block-side logs
      ['/api/log/seeding?filter[asset.id]=block-1', { data: [log('s1', 'seeding', 'inoculation', '2026-05-13T10:00Z', ['block-1'])] }],
      ['/api/log/observation?filter[asset.id]=block-1', { data: [log('o1', 'observation', 'no_contam', '2026-05-20T10:00Z', ['block-1'])] }],
      ['/api/log/activity?filter[asset.id]=block-1', { data: [
        log('a1', 'activity', 'relocate', '2026-06-09T10:00Z', ['block-1']),
        log('a2', 'activity', 'cold_shock', '2026-06-10T10:00Z', ['block-1']),
        log('a3', 'activity', 'archive_spent', '2026-07-15T10:00Z', ['block-1']),
      ]}],
      ['/api/log/harvest?filter[asset.id]=block-1', { data: [log('h1', 'harvest', 'bagging', '2026-07-01T10:00Z', ['block-1', 'bag-1'])] }],
      ['/api/log/input?filter[asset.id]=block-1', { data: [] }],

      // Bag-side logs (discovered via harvest ref)
      ['/api/log/seeding?filter[asset.id]=bag-1', { data: [] }],
      ['/api/log/observation?filter[asset.id]=bag-1', { data: [] }],
      ['/api/log/activity?filter[asset.id]=bag-1', { data: [] }],
      ['/api/log/harvest?filter[asset.id]=bag-1', { data: [log('h1', 'harvest', 'bagging', '2026-07-01T10:00Z', ['block-1', 'bag-1'])] }], // duplicate; should dedupe
      ['/api/log/input?filter[asset.id]=bag-1', { data: [] }],
    ];
    const client = makeMockClient(byPath);
    const logs = await gatherAllLogs(client, 'block-1');
    const ids = logs.map((l) => l.id);
    expect(ids).toEqual(['s1', 'o1', 'a1', 'a2', 'h1', 'a3']);
    // h1 should appear exactly once even though it showed up via both block-1 and bag-1.
    expect(ids.filter((i) => i === 'h1')).toHaveLength(1);
  });

  test('empty block produces empty timeline', async () => {
    const client = makeMockClient([]);
    const logs = await gatherAllLogs(client, 'block-empty');
    expect(logs).toEqual([]);
    expect(fmtTimeline(logs)).toBe('(no logs)');
  });
});

describe('fmtTimeline: no Signal refs', () => {
  test('output contains no signal/whatsapp/sms strings', async () => {
    const logs = [
      log('s1', 'seeding', 'inoculation', '2026-05-13T10:00Z', ['block-1']),
      log('a1', 'activity', 'cold_shock', '2026-06-10T10:00Z', ['block-1']),
    ];
    const out = fmtTimeline(logs);
    expect(out).not.toMatch(/signal/i);
    expect(out).not.toMatch(/whatsapp/i);
    expect(out).not.toMatch(/sms/i);
  });
});
