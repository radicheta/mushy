'use strict';

// Phase 40 D-01a / D-01b: farmOS HTTP client (JS twin of farmos_client.py).
//
// Session-cookie + X-CSRF-Token auth, 10s per-call timeout via AbortController,
// exponential backoff retry on transient (5xx + network) errors, single 401/403
// re-auth retry. Used by every later Phase 40 module (qr / files / assets / logs /
// commits / watchdog) via dependency injection. Never imports config directly --
// caller passes credentials in.
//
// No em-dashes (feedback_no_em_dashes_in_artifacts). No hardcoded creds.

function createFarmosClient({
  farmosUrl,
  username,
  password,
  fetchImpl,
  clock,
  logger = console,
  backoffMs = [1000, 4000, 16000],
  timeoutMs = 10000,
  retryMax = 3,
}) {
  if (!farmosUrl) throw new Error('createFarmosClient: farmosUrl is required');
  const _fetch = fetchImpl || (typeof globalThis !== 'undefined' ? globalThis.fetch : null);
  if (typeof _fetch !== 'function') {
    throw new Error('createFarmosClient: no fetch implementation available');
  }
  const _clock = clock || { now: () => Date.now(), sleep: (ms) => new Promise((res) => setTimeout(res, ms)) };
  if (typeof _clock.sleep !== 'function') {
    _clock.sleep = (ms) => new Promise((res) => setTimeout(res, ms));
  }

  const _session = { cookie: null, csrf: null, authedAt: null };

  async function _authenticate() {
    const ac = new AbortController();
    const t = setTimeout(() => ac.abort(), timeoutMs);
    try {
      const resp = await _fetch(`${farmosUrl}/user/login?_format=json`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ name: username, pass: password }),
        signal: ac.signal,
      });
      if (!resp.ok) {
        logger.warn && logger.warn(`[farmos] auth failed: status=${resp.status}`);
        throw new Error(`auth_failed_status_${resp.status}`);
      }
      const setCookie = resp.headers && resp.headers.get ? resp.headers.get('set-cookie') : null;
      const cookie = setCookie ? String(setCookie).split(';')[0] : null;
      const body = await resp.json();
      const csrf = body && body.csrf_token;
      if (!cookie || !csrf) {
        logger.warn && logger.warn('[farmos] auth response missing cookie or csrf_token');
        throw new Error('auth_response_malformed');
      }
      _session.cookie = cookie;
      _session.csrf = csrf;
      _session.authedAt = _clock.now();
    } finally {
      clearTimeout(t);
    }
  }

  function _isTransientError(e) {
    if (!e) return false;
    if (e.name === 'AbortError') return true;
    if (e.name === 'TypeError') return true; // fetch network error
    const msg = String(e.message || '');
    return /econnreset|econnrefused|etimedout|enotfound|network|abort/i.test(msg);
  }

  async function _doFetch(method, path, body, opts) {
    opts = opts || {};
    const url = path.startsWith('http') ? path : `${farmosUrl}${path}`;
    // Phase 51 UPSERT-04 (degraded): client honors opts.headers so callers may
    // send If-Match. Soft revision_id compare lives at the call site
    // (assets.js upsertFungiAsset); farmOS does not currently return 412 on
    // If-Match mismatch (see 51-RESEARCH.md A4) but plumbing exists for future
    // Drupal versions. Caller-supplied headers WIN over defaults.
    const headers = Object.assign({
      Accept: 'application/vnd.api+json',
      Cookie: _session.cookie || '',
      'X-CSRF-Token': _session.csrf || '',
    }, (opts && opts.headers) || {});
    let fetchBody = undefined;
    if (method !== 'GET' && method !== 'HEAD') {
      if (opts.binary) {
        headers['Content-Type'] = 'application/octet-stream';
        if (opts.filename) {
          headers['Content-Disposition'] = `file; filename="${opts.filename}"`;
        }
        fetchBody = body;
      } else if (body !== undefined && body !== null) {
        headers['Content-Type'] = 'application/vnd.api+json';
        fetchBody = JSON.stringify(body);
      }
    }
    const ac = new AbortController();
    const callTimeout = opts.timeoutMs || timeoutMs;
    const t = setTimeout(() => ac.abort(), callTimeout);
    try {
      return await _fetch(url, { method, headers, body: fetchBody, signal: ac.signal });
    } finally {
      clearTimeout(t);
    }
  }

  async function _request(method, path, body, opts) {
    opts = opts || {};
    if (_session.cookie == null && !opts.skipAuth) {
      await _authenticate();
    }
    let attempt = 0;
    let didReauth = false;
    const t0 = _clock.now();
    let lastError = null;
    while (true) {
      let resp = null;
      try {
        resp = await _doFetch(method, path, body, opts);
      } catch (e) {
        lastError = e;
        if (_isTransientError(e) && attempt < retryMax - 1) {
          const wait = backoffMs[Math.min(attempt, backoffMs.length - 1)];
          await _clock.sleep(wait);
          attempt += 1;
          continue;
        }
        return { ok: false, status: null, headers: null, body: null, latencyMs: _clock.now() - t0, error: e.message };
      }

      // 401 / 403 -> one-shot reauth
      if ((resp.status === 401 || resp.status === 403) && !didReauth) {
        didReauth = true;
        try {
          await _authenticate();
        } catch (e) {
          return { ok: false, status: resp.status, headers: resp.headers, body: null, latencyMs: _clock.now() - t0, error: 'reauth_failed' };
        }
        continue;
      }

      // 5xx -> transient retry
      if (resp.status >= 500 && attempt < retryMax - 1) {
        const wait = backoffMs[Math.min(attempt, backoffMs.length - 1)];
        await _clock.sleep(wait);
        attempt += 1;
        continue;
      }

      // Parse body
      let parsed = null;
      try {
        const ct = resp.headers && resp.headers.get ? resp.headers.get('content-type') || '' : '';
        if (method === 'HEAD') {
          parsed = null;
        } else if (/vnd\.api\+json|application\/json/i.test(ct)) {
          parsed = await resp.json();
        } else {
          parsed = await resp.text();
        }
      } catch (_) {
        parsed = null;
      }
      const ok = resp.status >= 200 && resp.status < 300;
      return { ok, status: resp.status, headers: resp.headers, body: parsed, latencyMs: _clock.now() - t0 };
    }
  }

  async function get(path, opts) { return _request('GET', path, null, opts); }
  async function post(path, body, opts) { return _request('POST', path, body, opts); }
  async function patch(path, body, opts) { return _request('PATCH', path, body, opts); }
  async function postBinary(path, bytes, opts) {
    opts = Object.assign({ binary: true, timeoutMs: 30000 }, opts || {});
    return _request('POST', path, bytes, opts);
  }
  async function head(path, opts) { return _request('HEAD', path, null, opts); }
  // Phase 48 Plan 02: orphan cleanup after partial commit failure in
  // commit-seeding-session. farmOS returns 204 on a successful asset delete
  // (no body), which _request still surfaces as ok=true.
  async function del(path, opts) { return _request('DELETE', path, null, opts); }

  return {
    get,
    post,
    patch,
    postBinary,
    head,
    delete: del,
    _session, // test introspection
  };
}

module.exports = { createFarmosClient };
