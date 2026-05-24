'use strict';

// Phase 40 D-06: one JSONL line per commit event to alerter stdout + one
// matching row appended to signal_draft_event (Phase 39 audit table). Audit-
// row write failures are swallowed (commit success/failure is the load-bearing
// event; audit is observability).

function createAuditLogger({ pool, logger = console, farmosUrl, confirmDb }) {
  async function logCommit(event, draft, result) {
    result = result || {};
    const payload = {
      ts: new Date().toISOString(),
      event,
      draft_id: draft && draft.id,
      farmer: draft && draft.sender_e164,
      log_type: draft && draft.log_type,
      asset_ids: Array.isArray(result.asset_ids) ? result.asset_ids : [],
      log_ids: Array.isArray(result.log_ids) ? result.log_ids : [],
      file_ids: Array.isArray(result.file_ids) ? result.file_ids : [],
      farmos_url: farmosUrl,
      http_status: result.http_status != null ? result.http_status : null,
      latency_ms: result.latency_ms != null ? Math.round(result.latency_ms) : null,
      attempt: result.attempt != null ? result.attempt : null,
      reason: result.reason != null ? result.reason : null,
      // Phase 51 UPSERT-06: upsert outcome dimension. outcome ∈
      // {created|patched|noop|mixed|null}; conflicts is per-field structured
      // surface; etag_source ∈ {soft_compare|absent|null}.
      outcome: result.outcome != null ? result.outcome : null,
      conflicts: Array.isArray(result.conflicts) ? result.conflicts : [],
      etag_source: result.etag_source != null ? result.etag_source : null,
    };
    try {
      if (logger && logger.info) logger.info(JSON.stringify(payload));
    } catch (_) { /* logger pipe failure is non-fatal */ }
    if (confirmDb && typeof confirmDb.appendEventViaPool === 'function' && draft && draft.id) {
      try {
        await confirmDb.appendEventViaPool(pool, draft.id, event, payload);
      } catch (e) {
        if (logger && logger.warn) logger.warn(`[audit-logger] event-row write failed: ${e.message}`);
      }
    }
    return payload;
  }
  return { logCommit };
}

module.exports = { createAuditLogger };
