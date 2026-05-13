'use strict';

// Phase 40 B7.5 harvest (D-03b): resolve N source-block QRs, create 1 harvest
// batch + M bag assets each QR-bound, post harvest log referencing all.
// Missing source block aborts BEFORE any farmOS write. Bag QR collision is
// terminal (qr_already_bound_for_bag); bags are new units, never reused.

const assets = require('../assets');
const logs = require('../logs');
const qrMod = require('../qr');

async function commitHarvest(client, draft, ctx) {
  const dj = draft.draft_json || {};
  const draftId = draft.id;
  const timestamp = typeof dj.timestamp === 'number' ? dj.timestamp : (Date.now() / 1000);

  const sourceQrs = Array.isArray(dj.source_qr_codes) ? dj.source_qr_codes : [];
  const bags = Array.isArray(dj.bags) ? dj.bags : [];

  // 1. Resolve source blocks. Pre-check ALL before any write.
  const sourceIds = [];
  for (const qr of sourceQrs) {
    const r = await qrMod.resolveQr(client, qr);
    if (!r.found || !r.assetId) {
      return { ok: false, reason: 'missing_source_block' };
    }
    sourceIds.push(r.assetId);
  }
  if (sourceIds.length === 0) {
    return { ok: false, reason: 'missing_source_block' };
  }

  // 1b. Pre-check bag QRs are unbound (no collision).
  for (const bag of bags) {
    if (!bag || !bag.qr_code) continue;
    const r = await qrMod.resolveQr(client, bag.qr_code);
    if (r.found && r.assetId) {
      return { ok: false, reason: 'qr_already_bound_for_bag' };
    }
  }

  // 2. Create harvest batch.
  const batchName = dj.harvest_batch_name;
  if (!batchName) return { ok: false, reason: 'missing_harvest_batch_name' };
  const batchRes = await assets.createFungiAsset(client, {
    name: batchName, parentIds: sourceIds, fungiTypeName: 'batch', draftId,
  });
  if (!batchRes.ok) return { ok: false, reason: batchRes.reason || 'harvest_batch_create_failed', http_status: batchRes.http_status };
  const batchId = batchRes.assetId;

  // 3. Create bag assets.
  const bagIds = [];
  for (const bag of bags) {
    const bagName = bag.name || `${batchName}-bag-${bagIds.length + 1}`;
    const bagRes = await assets.createFungiAsset(client, {
      name: bagName,
      parentIds: [batchId],
      fungiTypeName: 'bag',
      qrCodes: bag.qr_code ? [bag.qr_code] : [],
      draftId,
    });
    if (!bagRes.ok) return { ok: false, reason: bagRes.reason || 'bag_create_failed', http_status: bagRes.http_status, asset_ids: [batchId, ...bagIds] };
    bagIds.push(bagRes.assetId);
  }

  // 4. Harvest log: order = source blocks, batch, bags.
  const assetIds = [...sourceIds, batchId, ...bagIds];
  const weightLines = bags
    .map((b, i) => `bag${i + 1}: ${b.weight_grams != null ? b.weight_grams + 'g' : 'n/a'}`)
    .join('\n');
  const notes = (dj.notes ? dj.notes + '\n' : '') + (weightLines ? 'Weights:\n' + weightLines : '');
  const name = `harvest ${new Date(timestamp * 1000).toISOString().slice(0, 10)}`;
  const logRes = await logs.createLog(client, 'harvest', {
    name, timestamp, assetIds, notes, draftId,
  });
  if (!logRes.ok) return { ok: false, reason: logRes.reason, http_status: logRes.http_status, asset_ids: [batchId, ...bagIds] };

  return {
    ok: true,
    asset_ids: [batchId, ...bagIds],
    log_ids: [logRes.logId],
    file_ids: [],
    http_status: logRes.http_status,
  };
}

module.exports = commitHarvest;
