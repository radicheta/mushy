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

describe('files.js field-scoped upload (Phase 55B)', () => {
  let tmpDir;
  let realPath;
  beforeAll(async () => {
    tmpDir = await fs.promises.mkdtemp(path.join(os.tmpdir(), 'farmos-fieldfiles-'));
    realPath = path.join(tmpDir, 'page.jpg');
    await fs.promises.writeFile(realPath, Buffer.from([0xff, 0xd8, 0xff]));
  });
  afterAll(async () => { try { await fs.promises.rm(tmpDir, { recursive: true }); } catch (_) {} });

  it('POSTs to /{collection}/{uuid}/{field} and returns fileId', async () => {
    const client = mockClient();
    const r = await files.uploadFieldAttachment(client, '/api/asset/group', 'g-1', 'image', realPath);
    expect(r.ok).toBe(true);
    expect(r.fileId).toBe('file-1');
    const [url] = client.postBinary.mock.calls[0];
    expect(url).toBe('/api/asset/group/g-1/image');
  });

  it('missing file returns skipped:true; no postBinary call', async () => {
    const client = mockClient();
    const r = await files.uploadFieldAttachment(client, '/api/asset/group', 'g-1', 'image', '/nope/x.jpg');
    expect(r.skipped).toBe(true);
    expect(client.postBinary).not.toHaveBeenCalled();
  });

  it('extracts the newest id when the field echoes a multi-value list', async () => {
    const client = mockClient(async () => ({
      ok: true, status: 200,
      body: { data: [{ id: 'old' }, { id: 'new' }] },
    }));
    const r = await files.uploadFieldAttachment(client, '/api/asset/group', 'g-1', 'image', realPath);
    expect(r.fileId).toBe('new');
  });

  it('non-ok upload returns canonical error shape', async () => {
    const client = mockClient(async () => ({ ok: false, status: 422 }));
    const r = await files.uploadFieldAttachment(client, '/api/asset/group', 'g-1', 'image', realPath);
    expect(r.ok).toBe(false);
    expect(r.reason).toBe('http_422');
  });

  it('uploadFieldAttachments aggregates fileIds / skipped / failed', async () => {
    let n = 0;
    const client = mockClient(async () => {
      n++;
      if (n === 2) return { ok: false, status: 500 };
      return { ok: true, status: 200, body: { data: { id: 'f-' + n } } };
    });
    const r = await files.uploadFieldAttachments(
      client, '/api/asset/group', 'g-1', 'image', [realPath, realPath, '/nope/x.jpg'],
    );
    expect(r.fileIds).toEqual(['f-1']);
    expect(r.failed.map((f) => f.reason)).toEqual(['http_500']);
    expect(r.skipped).toEqual(['/nope/x.jpg']);
  });
});
