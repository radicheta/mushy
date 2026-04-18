'use strict';

const { maskNumber } = require('./config');

function createSignalClient({ apiUrl, sender, recipient, maxSendsPerHour, logger = console, timeoutMs = 10000 }) {
  const sendHistory = []; // array of ms timestamps within the last hour

  function pruneHistory(now) {
    const cutoff = now - 3600000;
    while (sendHistory.length && sendHistory[0] < cutoff) sendHistory.shift();
  }

  async function send(body, { bypassCap = false } = {}) {
    const now = Date.now();
    pruneHistory(now);
    if (!bypassCap && sendHistory.length >= maxSendsPerHour) {
      logger.warn(`[signal] cap reached (${sendHistory.length}/${maxSendsPerHour}/h) — dropping`);
      return { ok: false, reason: 'rate-cap' };
    }

    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      const res = await fetch(`${apiUrl}/v2/send`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: body, number: sender, recipients: [recipient] }),
        signal: ctrl.signal,
      });
      if (!res.ok) {
        const text = await res.text().catch(() => '');
        throw new Error(`signal-cli ${res.status}: ${text.slice(0, 200)}`);
      }
      const json = await res.json().catch(() => ({}));
      sendHistory.push(now);
      logger.info(`[signal] sent -> ${maskNumber(recipient)} (${body.length} chars)`);
      return { ok: true, timestamp: json.timestamp || now };
    } finally {
      clearTimeout(timer);
    }
  }

  async function receive({ timeoutSec = 1 } = {}) {
    const url = `${apiUrl}/v1/receive/${encodeURIComponent(sender)}?timeout=${timeoutSec}&ignore_attachments=true`;
    const res = await fetch(url);
    if (!res.ok) throw new Error(`signal-cli receive ${res.status}`);
    return await res.json();
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

  return { send, receive, accounts, sendsThisHour };
}

module.exports = { createSignalClient };
