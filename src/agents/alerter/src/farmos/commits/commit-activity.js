'use strict';

// Phase 40 B7.2 activity: resolve QRs to existing assetIds (no asset creation),
// post activity log with subtype-as-leading-token in attributes.name.

const logs = require('../logs');
const qrMod = require('../qr');

function _ymd(unixSec) {
  const d = new Date(unixSec * 1000);
  return d.toISOString().slice(0, 10);
}

async function commitActivity(client, draft, ctx) {
  const dj = draft.draft_json || {};
  const draftId = draft.id;
  const qrCodes = Array.isArray(dj.qr_codes) ? dj.qr_codes : [];
  const timestamp = typeof dj.timestamp === 'number' ? dj.timestamp : (Date.now() / 1000);
  const subtype = dj.activity_subtype || 'activity';

  const assetIds = [];
  for (const qr of qrCodes) {
    const r = await qrMod.resolveQr(client, qr);
    if (r.found && r.assetId) assetIds.push(r.assetId);
  }
  if (assetIds.length === 0) {
    return { ok: false, reason: 'no_target_asset_for_activity' };
  }
  const name = `${subtype} ${_ymd(timestamp)}`;
  const r = await logs.createLog(client, 'activity', {
    name, timestamp, assetIds, notes: dj.notes || '', draftId,
  });
  if (!r.ok) return { ok: false, reason: r.reason, http_status: r.http_status };
  return { ok: true, asset_ids: [], log_ids: [r.logId], file_ids: [], http_status: r.http_status };
}

module.exports = commitActivity;
