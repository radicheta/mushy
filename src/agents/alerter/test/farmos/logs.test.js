'use strict';

const logs = require('../../src/farmos/logs');

function mockClient() {
  return {
    post: jest.fn(async () => ({ ok: true, status: 201, body: { data: { id: 'log-1' } } })),
  };
}

describe('logs.js (Phase 40 Plan 03)', () => {
  for (const t of logs.LOG_TYPES) {
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
