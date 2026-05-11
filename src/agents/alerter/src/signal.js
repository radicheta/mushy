'use strict';

const { maskNumber } = require('./config');

function createSignalClient({ apiUrl, sender, recipient, defaultTarget, maxSendsPerHour, getMaxSendsPerHour, logger = console, timeoutMs = 10000 }) {
  // Phase 37 D-01: single choke-point send. defaultTarget can be a string phone
  // OR { groupId } object; falls back to legacy `recipient` if absent (back-compat).
  const effectiveDefault = defaultTarget !== undefined ? defaultTarget : recipient;
  if (effectiveDefault === undefined || effectiveDefault === null || effectiveDefault === '') {
    throw new Error('createSignalClient: defaultTarget or recipient is required');
  }

  const sendHistory = []; // array of ms timestamps within the last hour

  function pruneHistory(now) {
    const cutoff = now - 3600000;
    while (sendHistory.length && sendHistory[0] < cutoff) sendHistory.shift();
  }

  // Phase 29 plan 29-04 BLOCKER 3 — resolve cap dynamically so Tier C
  // alerter_globals.max_sends_per_hour takes effect on the next send().
  function currentCap() {
    if (typeof getMaxSendsPerHour === 'function') {
      try {
        const v = getMaxSendsPerHour();
        if (typeof v === 'number' && Number.isFinite(v)) return v;
      } catch (_) { /* fall through */ }
    }
    return maxSendsPerHour;
  }

  async function send(body, { bypassCap = false, to } = {}) {
    const now = Date.now();
    pruneHistory(now);
    const cap = currentCap();
    if (!bypassCap && sendHistory.length >= cap) {
      logger.warn(`[signal] cap reached (${sendHistory.length}/${cap}/h) — dropping`);
      return { ok: false, reason: 'rate-cap' };
    }

    // Phase 37 D-01: resolve target — per-call {to} overrides defaultTarget.
    const target = to !== undefined ? to : effectiveDefault;
    const isStringTarget = typeof target === 'string' && target.length > 0;
    const isGroupTarget = target && typeof target === 'object' && typeof target.groupId === 'string' && target.groupId.length > 0;
    if (!isStringTarget && !isGroupTarget) {
      throw new Error('invalid send target');
    }
    const recipients = isStringTarget
      ? [target]
      : [`group.${target.groupId}`];

    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      const res = await fetch(`${apiUrl}/v2/send`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: body, number: sender, recipients }),
        signal: ctrl.signal,
      });
      if (!res.ok) {
        const text = await res.text().catch(() => '');
        throw new Error(`signal-cli ${res.status}: ${text.slice(0, 200)}`);
      }
      const json = await res.json().catch(() => ({}));
      sendHistory.push(now);
      const label = isStringTarget
        ? maskNumber(target)
        : `group:${String(target.groupId).slice(0, 8)}…`;
      logger.info(`[signal] sent -> ${label} (${body.length} chars)`);
      return { ok: true, timestamp: json.timestamp || now };
    } finally {
      clearTimeout(timer);
    }
  }

  async function receive({ timeoutSec = 1, ignoreAttachments = false } = {}) {
    const url = `${apiUrl}/v1/receive/${encodeURIComponent(sender)}?timeout=${timeoutSec}&ignore_attachments=${ignoreAttachments}`;
    const res = await fetch(url);
    if (!res.ok) throw new Error(`signal-cli receive ${res.status}`);
    return await res.json();
  }

  async function fetchAttachment(id) {
    const url = `${apiUrl}/v1/attachments/${encodeURIComponent(id)}`;
    const res = await fetch(url);
    if (!res.ok) throw new Error(`signal-cli attachment ${id} ${res.status}`);
    const buf = await res.arrayBuffer();
    return Buffer.from(buf);
  }

  async function accounts() {
    const res = await fetch(`${apiUrl}/v1/accounts`);
    if (!res.ok) throw new Error(`signal-cli accounts ${res.status}`);
    return await res.json();
  }

  function sendsThisHour() {
    pruneHistory(Date.now());
    return sendHistory.length;
  }

  return { send, receive, accounts, fetchAttachment, sendsThisHour };
}

module.exports = { createSignalClient };
