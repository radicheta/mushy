#!/usr/bin/env node
// mushy-heartbeat-receiver — Phase 33
//
// Single-file Node.js service. Listens on 127.0.0.1:9000 + 10.66.0.1:9000.
// Accepts POST /heartbeat with HMAC-signed body; writes last_seen.json;
// internal timer detects staleness; fires Tier 1 alert via bridge
// /heartbeat-alert endpoint over wg-hub.
//
// No external deps. Uses Node 18+ built-in fetch + crypto + http + fs.

const http = require('http');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

// ──────────────────────────────────────────────────────────────────────────
// Config (env-overridable; sane defaults for the VPS deployment)
// ──────────────────────────────────────────────────────────────────────────
const PORT = parseInt(process.env.HEARTBEAT_PORT || '9000', 10);
const BIND_ADDRS = (process.env.HEARTBEAT_BIND || '127.0.0.1,10.66.0.1').split(',').map(s => s.trim());
const DATA_DIR = process.env.HEARTBEAT_DATA_DIR || '/var/lib/mushy-heartbeat';
const STATE_FILE = path.join(DATA_DIR, 'last_seen.json');
const ALERT_LOG = path.join(DATA_DIR, 'alerts.log');
const SECRET_FILE = process.env.HEARTBEAT_SECRET_FILE || '/etc/mushy-heartbeat/secret';
const BRIDGE_URL = process.env.BRIDGE_URL || 'http://10.66.0.12:8081';
const CHECK_INTERVAL_MS = parseInt(process.env.CHECK_INTERVAL_MS || '30000', 10);

// Per-source staleness thresholds (ms). Sources not in here use DEFAULT.
const STALENESS_THRESHOLDS = {
  'fc1':         3 * 60 * 1000,
  'elder-plops': 3 * 60 * 1000,
  DEFAULT:       5 * 60 * 1000,
};

// Alert backoff: 1m → 5m → 15m → 60m, then stays at 60m
const BACKOFF_SCHEDULE_MS = [60_000, 300_000, 900_000, 3_600_000];

// ──────────────────────────────────────────────────────────────────────────
// State
// ──────────────────────────────────────────────────────────────────────────
let SECRET = null;            // loaded from SECRET_FILE at startup
let lastSeen = {};            // { source: { ts: ms, extras: {...} } }
let alertState = {};          // { source: { fired_count: N, last_alert_ms: ms } }

function log(level, ...args) {
  console.log(new Date().toISOString(), `[${level}]`, ...args);
}

// ──────────────────────────────────────────────────────────────────────────
// Storage (atomic file ops)
// ──────────────────────────────────────────────────────────────────────────
function ensureDataDir() {
  fs.mkdirSync(DATA_DIR, { recursive: true });
}

function loadState() {
  try {
    const raw = fs.readFileSync(STATE_FILE, 'utf8');
    lastSeen = JSON.parse(raw);
    log('info', `loaded last_seen for ${Object.keys(lastSeen).length} sources from ${STATE_FILE}`);
  } catch (e) {
    if (e.code !== 'ENOENT') log('warn', 'failed to load state, starting fresh:', e.message);
    lastSeen = {};
  }
}

function persistState() {
  const tmp = STATE_FILE + '.tmp';
  fs.writeFileSync(tmp, JSON.stringify(lastSeen, null, 2));
  fs.renameSync(tmp, STATE_FILE);
}

function appendAlertLog(entry) {
  fs.appendFileSync(ALERT_LOG, JSON.stringify({ ...entry, ts: new Date().toISOString() }) + '\n');
}

// ──────────────────────────────────────────────────────────────────────────
// HMAC verify
// ──────────────────────────────────────────────────────────────────────────
function loadSecret() {
  try {
    SECRET = fs.readFileSync(SECRET_FILE, 'utf8').trim();
    if (!SECRET) throw new Error('empty');
    log('info', `loaded HMAC secret from ${SECRET_FILE} (${SECRET.length} chars)`);
  } catch (e) {
    log('error', `cannot read HMAC secret from ${SECRET_FILE}: ${e.message}`);
    process.exit(1);
  }
}

function verifyHmac(body, providedHex) {
  if (!providedHex) return false;
  const expected = crypto.createHmac('sha256', SECRET).update(body).digest('hex');
  // timingSafeEqual requires equal-length buffers
  const a = Buffer.from(expected, 'hex');
  let b;
  try { b = Buffer.from(providedHex, 'hex'); } catch { return false; }
  if (a.length !== b.length) return false;
  return crypto.timingSafeEqual(a, b);
}

// ──────────────────────────────────────────────────────────────────────────
// HTTP handler
// ──────────────────────────────────────────────────────────────────────────
function handleRequest(req, res) {
  const url = new URL(req.url, `http://${req.headers.host}`);

  if (req.method === 'GET' && url.pathname === '/health') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({
      status: 'ok',
      sources_known: Object.keys(lastSeen).length,
      now: new Date().toISOString(),
      last_seen: lastSeen,
    }));
    return;
  }

  if (req.method === 'POST' && url.pathname === '/heartbeat') {
    let chunks = [];
    let totalLen = 0;
    req.on('data', c => {
      chunks.push(c);
      totalLen += c.length;
      if (totalLen > 64 * 1024) { // 64KB ceiling
        res.writeHead(413).end('payload too large');
        req.destroy();
      }
    });
    req.on('end', () => {
      const body = Buffer.concat(chunks).toString('utf8');
      const hmacHeader = req.headers['x-heartbeat-hmac'];
      if (!verifyHmac(body, hmacHeader)) {
        log('warn', `HMAC mismatch from ${req.socket.remoteAddress}`);
        res.writeHead(401, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ ok: false, error: 'hmac mismatch' }));
        return;
      }
      let payload;
      try { payload = JSON.parse(body); }
      catch { res.writeHead(400).end(JSON.stringify({ ok: false, error: 'invalid json' })); return; }
      if (!payload.source || typeof payload.source !== 'string') {
        res.writeHead(400).end(JSON.stringify({ ok: false, error: 'missing source' }));
        return;
      }
      const now = Date.now();
      lastSeen[payload.source] = {
        ts: now,
        ts_iso: new Date(now).toISOString(),
        extras: payload.extras || {},
      };
      // Reset alert state for this source — it's alive again
      if (alertState[payload.source] && alertState[payload.source].fired_count > 0) {
        log('info', `${payload.source} recovered after ${alertState[payload.source].fired_count} alerts`);
        appendAlertLog({ event: 'recovery', source: payload.source, after_alerts: alertState[payload.source].fired_count });
      }
      delete alertState[payload.source];
      persistState();
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ ok: true, ts_iso: new Date(now).toISOString() }));
    });
    return;
  }

  res.writeHead(404).end('not found');
}

// ──────────────────────────────────────────────────────────────────────────
// Staleness checker + alert dispatch
// ──────────────────────────────────────────────────────────────────────────
function backoffMsForCount(n) {
  const idx = Math.min(n, BACKOFF_SCHEDULE_MS.length - 1);
  return BACKOFF_SCHEDULE_MS[idx];
}

async function dispatchAlertTier1(source, message) {
  // POST to bridge /heartbeat-alert; returns true on success.
  try {
    const res = await fetch(`${BRIDGE_URL}/heartbeat-alert`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source, message }),
      signal: AbortSignal.timeout(5000),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return true;
  } catch (e) {
    log('warn', `Tier 1 dispatch failed for ${source}: ${e.message}`);
    return false;
  }
}

function dispatchAlertTier2(source, message) {
  // OUT-OF-BAND placeholder. Phase 999.43.1 wires ntfy.sh / Twilio here.
  // For tonight, log clearly so operator sees the gap on next inspection.
  appendAlertLog({
    event: 'OUT_OF_BAND_ALERT_MISSED',
    source,
    message,
    note: 'Tier 2 not yet implemented — install ntfy and wire here (Phase 999.43.1)',
  });
  log('error', `[OUT-OF-BAND ALERT MISSED — install ntfy and wire here] source=${source} msg="${message}"`);
}

async function checkStaleness() {
  const now = Date.now();
  for (const [source, state] of Object.entries(lastSeen)) {
    const threshold = STALENESS_THRESHOLDS[source] || STALENESS_THRESHOLDS.DEFAULT;
    const age = now - state.ts;
    if (age <= threshold) continue;

    // stale — should we alert?
    const a = alertState[source] || { fired_count: 0, last_alert_ms: 0 };
    const ageSinceLastAlert = now - a.last_alert_ms;
    const requiredBackoff = a.fired_count === 0 ? 0 : backoffMsForCount(a.fired_count - 1);
    if (ageSinceLastAlert < requiredBackoff) continue;

    const ageMin = (age / 60000).toFixed(1);
    const message = `🚨 ${source} silent for ${ageMin} min (last seen ${state.ts_iso})`;
    log('error', message);
    appendAlertLog({ event: 'alert_fired', source, age_ms: age, fired_count: a.fired_count + 1, message });

    const tier1Ok = await dispatchAlertTier1(source, message);
    if (!tier1Ok) dispatchAlertTier2(source, message);

    a.fired_count += 1;
    a.last_alert_ms = now;
    alertState[source] = a;
  }
}

// ──────────────────────────────────────────────────────────────────────────
// Boot
// ──────────────────────────────────────────────────────────────────────────
function main() {
  ensureDataDir();
  loadSecret();
  loadState();

  for (const addr of BIND_ADDRS) {
    const server = http.createServer(handleRequest);
    server.on('error', e => log('error', `bind ${addr}:${PORT} failed: ${e.message}`));
    server.listen(PORT, addr, () => log('info', `listening on ${addr}:${PORT}`));
  }

  setInterval(checkStaleness, CHECK_INTERVAL_MS);
  log('info', `staleness checker every ${CHECK_INTERVAL_MS}ms; thresholds=${JSON.stringify(STALENESS_THRESHOLDS)}; backoff=${JSON.stringify(BACKOFF_SCHEDULE_MS)}`);
  log('info', `Tier 1 alert path: ${BRIDGE_URL}/heartbeat-alert`);
}

main();
