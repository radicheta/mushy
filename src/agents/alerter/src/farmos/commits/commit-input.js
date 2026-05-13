'use strict';

// Phase 40 B7.3 input: ingredient list serialized into notes (as-supplied order,
// deterministic). Existing-asset-only path; QRs must resolve.

const logs = require('../logs');
const qrMod = require('../qr');

async function commitInput(client, draft, ctx) {
  const dj = draft.draft_json || {};
  const draftId = draft.id;
  const qrCodes = Array.isArray(dj.qr_codes) ? dj.qr_codes : [];
  const timestamp = typeof dj.timestamp === 'number' ? dj.timestamp : (Date.now() / 1000);
  const ingredients = Array.isArray(dj.input_ingredients) ? dj.input_ingredients : [];

  const assetIds = [];
  for (const qr of qrCodes) {
    const r = await qrMod.resolveQr(client, qr);
    if (r.found && r.assetId) assetIds.push(r.assetId);
  }
  if (assetIds.length === 0) {
    return { ok: false, reason: 'no_target_asset_for_activity' };
  }
  const lines = ingredients.map((s) => '- ' + String(s)).join('\n');
  const notes = (dj.notes ? dj.notes + '\n' : '') + (lines ? 'Ingredients:\n' + lines : '');
  const name = `input ${new Date(timestamp * 1000).toISOString().slice(0, 10)}`;
  const r = await logs.createLog(client, 'input', {
    name, timestamp, assetIds, notes, draftId,
  });
  if (!r.ok) return { ok: false, reason: r.reason, http_status: r.http_status };
  return { ok: true, asset_ids: [], log_ids: [r.logId], file_ids: [], http_status: r.http_status };
}

module.exports = commitInput;
