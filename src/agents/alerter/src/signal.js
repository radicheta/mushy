'use strict';

const { maskNumber } = require('./config');

function createSignalClient({ apiUrl, sender, recipient, defaultTarget, maxSendsPerHour, getMaxSendsPerHour, logger = console, timeoutMs = 10000, outboundDb = null, pool = null, tenantId = 'mossrock' }) {
  // Phase 37 D-01: single choke-point send. defaultTarget can be a string phone
  // OR { groupId } object; falls back to legacy `recipient` if absent (back-compat).
  const effectiveDefault = defaultTarget !== undefined ? defaultTarget : recipient;
  if (effectiveDefault === undefined || effectiveDefault === null || effectiveDefault === '') {
    throw new Error('createSignalClient: defaultTarget or recipient is required');
  }

  const sendHistory = []; // array of ms timestamps within the last hour

  // Phase 37 send-id fix: signal-cli's /v2/send accepts `group.<id-b64>`, but
  // received envelopes carry the DIFFERENT `internal_id-b64` in dataMessage.
  // groupInfo.groupId. Wrap-and-ship works for SIGNAL_GROUP_ID (operator
  // chose the id-b64 form) but BREAKS for envelope-driven group replies.
  // We lazy-load /v1/groups on first need and translate internal_id→id-b64.
  const groupIdMap = new Map(); // internal_id-b64 → id-b64 (no "group." prefix)
  let groupsLoaded = false;
  async function ensureGroupsLoaded(force = false) {
    if (groupsLoaded && !force) return;
    try {
      const res = await fetch(`${apiUrl}/v1/groups/${encodeURIComponent(sender)}`, { signal: AbortSignal.timeout(timeoutMs) });
      if (!res.ok) throw new Error(`groups list ${res.status}`);
      const groups = await res.json();
      groupIdMap.clear();
      for (const g of groups) {
        if (!g || !g.id || !g.internal_id) continue;
        const idStripped = g.id.startsWith('group.') ? g.id.slice('group.'.length) : g.id;
        groupIdMap.set(g.internal_id, idStripped);
      }
      groupsLoaded = true;
      logger.info(`[signal] groups loaded (${groupIdMap.size} entries) for id translation`);
    } catch (e) {
      logger.warn(`[signal] groups list failed: ${e.message} — send may fail if recipient is internal_id form`);
    }
  }

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

  // Phase 44 Plan-02 D-14: single persistence hook. Wrapper opts-bag extends
  // pre-Phase-44 {bypassCap, to} with {intent, relatedCaptureId, relatedDraftId,
  // sourceModule}. Callers without intent get a warn-and-default-to-'unknown'
  // shim (RESEARCH Pitfall 3) during the Plan-02→Plan-03 rollout window.
  // Group sends encode recipient as `group:<id>` prefix in recipient_e164
  // (operator decision 2026-05-21 per 44-group-send-encoding-decision.md — path b).
  // Phase 50 Plan-02: validate quote opt. Locked shape (CONTEXT D-01, spike
  // 2026-05-23, signal-cli REST 0.14.2): { timestamp, author, message }.
  // timestamp may be a finite number OR a numeric string (signal-cli returns
  // ms-ts stringified). author non-empty e164 string. message a string (empty
  // allowed -- Signal accepts empty body). Invalid shapes log warn and the
  // send proceeds WITHOUT the quote field (fail-open per CONTEXT D-05;
  // [[feedback_no_silent_failure_after_farmer_confirm]] -- vague ack beats no ack).
  function isValidQuote(q) {
    return (
      q !== null &&
      typeof q === 'object' &&
      Number.isFinite(Number(q.timestamp)) &&
      typeof q.author === 'string' &&
      q.author.length > 0 &&
      typeof q.message === 'string'
    );
  }

  async function send(body, { bypassCap = false, to, intent, relatedCaptureId, relatedDraftId, sourceModule, quote } = {}) {
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
    let resolvedGroupId = isGroupTarget ? target.groupId : null;
    if (isGroupTarget) {
      // First send to any group needs the id-b64 form, not internal_id-b64.
      await ensureGroupsLoaded(false);
      if (groupIdMap.has(target.groupId)) {
        resolvedGroupId = groupIdMap.get(target.groupId);
      }
      // If groupId isn't in the map (configured SIGNAL_GROUP_ID may already be
      // the id-b64 form, or groups-list fetch failed), pass through as-is.
      // signal-cli will reject with 400 if wrong — and on a fresh-group case
      // we force-refresh once and retry.
    }
    const recipients = isStringTarget
      ? [target]
      : [`group.${resolvedGroupId}`];

    // Phase 50 Plan-02: build payload with optional quote.
    // - quote === undefined or null  -> no quote key in payload (back-compat)
    // - quote present + valid        -> FLAT quote_timestamp/quote_author/quote_message
    // - quote present + invalid      -> warn + unquoted send (fail-open)
    //
    // signal-cli-rest-api /v2/send takes FLAT quote fields, NOT a nested `quote`
    // object. The nested shape (used since Phase 50) renders only on signal-cli
    // 0.14.2; on the live 0.200 container it is silently dropped (201, no bubble).
    // Confirmed via the container's /swagger/doc.json (api.SendMessageV2) and the
    // Phase 57-04 Python live-fire (2026-06-21). See todo
    // 2026-05-24-phase50-quote-rendering-broken-end-to-end.md.
    const payload = { message: body, number: sender, recipients };
    if (quote !== undefined && quote !== null) {
      if (isValidQuote(quote)) {
        payload.quote_timestamp = Number(quote.timestamp);
        payload.quote_author = quote.author;
        payload.quote_message = quote.message;
      } else {
        let dump;
        try { dump = JSON.stringify(quote); } catch (_) { dump = '[unstringifiable]'; }
        logger.warn(`[signal] invalid quote arg, sending without quote: ${dump}`);
      }
    }

    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      const res = await fetch(`${apiUrl}/v2/send`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
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

      // Phase 44 Plan-02 D-14: durable signal_outbound persistence (single hook).
      // Fail-open per D-03 — outbound insert failures NEVER affect send's return
      // value. outboundDb is optional for back-compat with tests/callers that
      // pre-date Plan-02 wiring; once index.js passes outboundDb everywhere,
      // every successful send writes exactly one row.
      if (outboundDb && pool) {
        let effectiveIntent = intent;
        if (!effectiveIntent) {
          logger.warn(`[signal] send() missing intent — defaulting to 'unknown' (Plan-03 wires the 14 callsites)`);
          effectiveIntent = 'unknown';
        }
        // Recipient encoding (operator decision path b — prefix):
        // 1:1 sends → `recipient_e164 = '+15551234567'`
        // group sends → `recipient_e164 = 'group:<id-b64>'` using the resolved
        //   id-b64 (matches what signal-cli accepts + receive-loop log format).
        const recipientCol = isStringTarget
          ? target
          : `group:${resolvedGroupId || target.groupId}`;
        try {
          const result = await outboundDb.insertOutbound(pool, {
            tenant_id: tenantId,
            sent_at: new Date(now),
            recipient_e164: recipientCol,
            intent: effectiveIntent,
            body,
            attachments: null,
            source_module: sourceModule || null,
            source_line: null,
            related_capture_id: relatedCaptureId ?? null,
            related_draft_id: relatedDraftId ?? null,
            // Phase 50 Plan-02: persist Signal-native ms-ts so future inbound
            // quotes can resolve quote.timestamp -> related_draft_id. signal-cli
            // returns this stringified ("1779562666675") in 0.14.2 -- Number()
            // coerces. Missing field -> NULL (best-effort; never invent ts).
            signal_msg_ts: json.timestamp ? Number(json.timestamp) : null,
          });
          if (result && result.ok === false) {
            logger.warn(`[signal] outbound persist failed (fail-open): ${result.reason}`);
          }
        } catch (e) {
          // Defense in depth — insertOutbound is documented never-throw, but
          // a thrown exception here MUST NOT propagate (D-03 fail-open).
          logger.warn(`[signal] outbound persist threw (fail-open): ${e.message}`);
        }
      }

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
