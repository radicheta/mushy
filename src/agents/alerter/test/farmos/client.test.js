'use strict';

const { createFarmosClient } = require('../../src/farmos/client');

// Build a Response-shaped mock. Body can be object (json) or string (text).
function mockResponse({ status = 200, body = {}, headers = {}, contentType = 'application/vnd.api+json' }) {
  const h = new Map(Object.entries(Object.assign({ 'content-type': contentType }, headers || {})));
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: (k) => h.get(String(k).toLowerCase()) },
    json: async () => (typeof body === 'string' ? JSON.parse(body) : body),
    text: async () => (typeof body === 'string' ? body : JSON.stringify(body)),
  };
}

function authResponse() {
  return mockResponse({
    status: 200,
    body: { csrf_token: 'csrf-xyz' },
    headers: { 'set-cookie': 'SSESS1234=abcd; path=/; HttpOnly' },
    contentType: 'application/json',
  });
}

function makeClient(fetchImpl, opts) {
  return createFarmosClient(Object.assign({
    farmosUrl: 'http://farmos.test',
    username: 'u', password: 'p',
    fetchImpl,
    clock: { now: () => 1000, sleep: async () => {} },
    backoffMs: [1, 1, 1],
    retryMax: 3,
    timeoutMs: 50,
    logger: { warn() {}, info() {} },
  }, opts || {}));
}

describe('createFarmosClient (Phase 40 Plan 02)', () => {
  it('first call triggers auth then the actual request', async () => {
    const calls = [];
    const fetchImpl = jest.fn(async (url, init) => {
      calls.push({ url, method: init.method });
      if (calls.length === 1) return authResponse();
      return mockResponse({ status: 201, body: { data: { id: 'u1' } } });
    });
    const c = makeClient(fetchImpl);
    const r = await c.post('/api/asset/fungi', { data: {} });
    expect(r.ok).toBe(true);
    expect(r.status).toBe(201);
    expect(calls.length).toBe(2);
    expect(calls[0].url).toMatch(/\/user\/login/);
    expect(calls[1].url).toMatch(/\/api\/asset\/fungi/);
  });

  it('second request reuses session (no re-auth)', async () => {
    const fetchImpl = jest.fn()
      .mockResolvedValueOnce(authResponse())
      .mockResolvedValueOnce(mockResponse({ status: 200, body: { data: [] } }))
      .mockResolvedValueOnce(mockResponse({ status: 200, body: { data: [] } }));
    const c = makeClient(fetchImpl);
    await c.get('/api/asset/fungi');
    await c.get('/api/asset/fungi');
    expect(fetchImpl).toHaveBeenCalledTimes(3); // 1 auth + 2 GETs
  });

  it('successful 201 returns parsed JSON body', async () => {
    const fetchImpl = jest.fn()
      .mockResolvedValueOnce(authResponse())
      .mockResolvedValueOnce(mockResponse({ status: 201, body: { data: { id: 'asset-1' } } }));
    const c = makeClient(fetchImpl);
    const r = await c.post('/api/asset/fungi', { data: {} });
    expect(r.body.data.id).toBe('asset-1');
  });

  it('single 500 then 200 succeeds with attempt=2', async () => {
    const fetchImpl = jest.fn()
      .mockResolvedValueOnce(authResponse())
      .mockResolvedValueOnce(mockResponse({ status: 500, body: {} }))
      .mockResolvedValueOnce(mockResponse({ status: 200, body: { data: [] } }));
    const c = makeClient(fetchImpl);
    const r = await c.get('/api/asset/fungi');
    expect(r.ok).toBe(true);
    expect(fetchImpl).toHaveBeenCalledTimes(3);
  });

  it('3 consecutive 500s exhaust retries', async () => {
    const fetchImpl = jest.fn()
      .mockResolvedValueOnce(authResponse())
      .mockResolvedValue(mockResponse({ status: 500, body: {} }));
    const c = makeClient(fetchImpl);
    const r = await c.get('/api/asset/fungi');
    expect(r.ok).toBe(false);
    expect(r.status).toBe(500);
  });

  it('AbortError is transient and retried', async () => {
    const abort = Object.assign(new Error('aborted'), { name: 'AbortError' });
    const fetchImpl = jest.fn()
      .mockResolvedValueOnce(authResponse())
      .mockRejectedValueOnce(abort)
      .mockResolvedValueOnce(mockResponse({ status: 200, body: { ok: true } }));
    const c = makeClient(fetchImpl);
    const r = await c.get('/api/asset/fungi');
    expect(r.ok).toBe(true);
  });

  it('401 triggers one reauth then retry success', async () => {
    const fetchImpl = jest.fn()
      .mockResolvedValueOnce(authResponse())                                  // initial auth
      .mockResolvedValueOnce(mockResponse({ status: 401, body: {} }))         // first call: 401
      .mockResolvedValueOnce(authResponse())                                  // reauth
      .mockResolvedValueOnce(mockResponse({ status: 200, body: { ok: 1 } })); // retry
    const c = makeClient(fetchImpl);
    const r = await c.get('/api/asset/fungi');
    expect(r.ok).toBe(true);
    expect(fetchImpl).toHaveBeenCalledTimes(4);
  });

  it('two 401s return ok:false (no infinite reauth)', async () => {
    const fetchImpl = jest.fn()
      .mockResolvedValueOnce(authResponse())
      .mockResolvedValueOnce(mockResponse({ status: 401, body: {} }))
      .mockResolvedValueOnce(authResponse())
      .mockResolvedValueOnce(mockResponse({ status: 401, body: {} }));
    const c = makeClient(fetchImpl);
    const r = await c.get('/api/asset/fungi');
    expect(r.ok).toBe(false);
    expect(r.status).toBe(401);
  });

  it('422 returns ok:false with NO retry', async () => {
    const fetchImpl = jest.fn()
      .mockResolvedValueOnce(authResponse())
      .mockResolvedValueOnce(mockResponse({ status: 422, body: { errors: [] } }));
    const c = makeClient(fetchImpl);
    const r = await c.post('/api/asset/fungi', { data: {} });
    expect(r.ok).toBe(false);
    expect(r.status).toBe(422);
    expect(fetchImpl).toHaveBeenCalledTimes(2); // 1 auth + 1 call only
  });

  it('postBinary sends application/octet-stream + Content-Disposition', async () => {
    let captured = null;
    const fetchImpl = jest.fn(async (url, init) => {
      if (/login/.test(url)) return authResponse();
      captured = init;
      return mockResponse({ status: 201, body: { data: { id: 'f1' } } });
    });
    const c = makeClient(fetchImpl);
    await c.postBinary('/api/file/file', Buffer.from('hi'), { filename: 'pic.jpg' });
    expect(captured.headers['Content-Type']).toBe('application/octet-stream');
    expect(captured.headers['Content-Disposition']).toMatch(/filename="pic.jpg"/);
  });

  it('probeAssetLinkModule caches across two invocations', async () => {
    const fetchImpl = jest.fn()
      .mockResolvedValueOnce(authResponse())
      .mockResolvedValueOnce(mockResponse({ status: 200, body: {} }));
    const c = makeClient(fetchImpl);
    const r1 = await c.probeAssetLinkModule();
    const r2 = await c.probeAssetLinkModule();
    expect(r1).toBe(true);
    expect(r2).toBe(true);
    expect(fetchImpl).toHaveBeenCalledTimes(2); // 1 auth + 1 HEAD only
  });

  it('probeAssetLinkModule 404 sets present=false', async () => {
    const fetchImpl = jest.fn()
      .mockResolvedValueOnce(authResponse())
      .mockResolvedValueOnce(mockResponse({ status: 404, body: {} }));
    const c = makeClient(fetchImpl);
    const r = await c.probeAssetLinkModule();
    expect(r).toBe(false);
  });
});
