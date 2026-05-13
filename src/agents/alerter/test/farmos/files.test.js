'use strict';

const fs = require('fs');
const path = require('path');
const os = require('os');
const files = require('../../src/farmos/files');

function mockClient(postBinaryImpl) {
  return {
    postBinary: jest.fn(postBinaryImpl || (async () => ({ ok: true, status: 201, body: { data: { id: 'file-1' } } }))),
  };
}

describe('files.js (Phase 40 Plan 03)', () => {
  let tmpDir;
  let realPath;
  beforeAll(async () => {
    tmpDir = await fs.promises.mkdtemp(path.join(os.tmpdir(), 'farmos-files-'));
    realPath = path.join(tmpDir, 'pic.jpg');
    await fs.promises.writeFile(realPath, Buffer.from([0xff, 0xd8, 0xff]));
  });
  afterAll(async () => { try { await fs.promises.rm(tmpDir, { recursive: true }); } catch (_) {} });

  it('missing file returns skipped:true; no postBinary call', async () => {
    const client = mockClient();
    const r = await files.uploadAttachment(client, '/nonexistent/x.jpg');
    expect(r.skipped).toBe(true);
    expect(r.reason).toBe('attachment_missing');
    expect(client.postBinary).not.toHaveBeenCalled();
  });

  it('successful upload returns fileId', async () => {
    const client = mockClient();
    const r = await files.uploadAttachment(client, realPath);
    expect(r.ok).toBe(true);
    expect(r.fileId).toBe('file-1');
  });

  it('uploadAttachments aggregates partial results', async () => {
    let n = 0;
    const client = mockClient(async () => {
      n++;
      return { ok: true, status: 201, body: { data: { id: 'file-' + n } } };
    });
    const r = await files.uploadAttachments(client, [realPath, '/nope/x.jpg', realPath]);
    expect(r.fileIds).toEqual(['file-1', 'file-2']);
    expect(r.skipped).toEqual(['/nope/x.jpg']);
    expect(r.failed).toEqual([]);
  });

  it('30s timeout option propagated to postBinary', async () => {
    const client = mockClient();
    await files.uploadAttachment(client, realPath);
    const opts = client.postBinary.mock.calls[0][2];
    expect(opts.timeoutMs).toBe(30000);
  });
});
