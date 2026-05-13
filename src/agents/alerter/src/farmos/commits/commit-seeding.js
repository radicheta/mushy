'use strict';

// Phase 40 B7.1 seeding (inoc): resolve-or-create BATCH-* (B1) + create block
// (B2, parent=batch, species, QR) + post seeding log referencing [batch, block].
// Path B: if any qr_code already resolves to an existing block, skip block
// creation and append-log-only. Multiple Path-B QRs in one draft is ambiguous.

const assets = require('../assets');
const logs = require('../logs');
const qrMod = require('../qr');
const speciesCache = require('../species-cache');

async function commitSeeding(client, draft, ctx) {
  const dj = draft.draft_json || {};
  const draftId = draft.id;
  const qrCodes = Array.isArray(dj.qr_codes) ? dj.qr_codes : [];
  const timestamp = typeof dj.timestamp === 'number' ? dj.timestamp : (Date.now() / 1000);

  // 1. Batch resolve-or-create
  const batchName = dj.batch_name;
  if (!batchName) return { ok: false, reason: 'missing_batch_name' };
  const batchRes = await assets.resolveOrCreateAsset(client, { name: batchName, draftId });
  if (!batchRes.ok) return { ok: false, reason: batchRes.reason || 'batch_create_failed', http_status: batchRes.http_status };
  const batchId = batchRes.assetId;

  // 2. Path A vs Path B (QR resolution)
  const pathBIds = [];
  const pathAQrs = [];
  for (const qr of qrCodes) {
    const r = await qrMod.resolveQr(client, qr);
    if (r.found && r.assetId) pathBIds.push(r.assetId);
    else pathAQrs.push(qr);
  }
  if (pathBIds.length > 1) {
    return { ok: false, reason: 'ambiguous_qr_seeding' };
  }

  let blockId;
  let createdAssets = [];
  if (pathBIds.length === 1) {
    blockId = pathBIds[0];
  } else {
    // 3. Species lookup (only needed when creating a block)
    const speciesCode = dj.species_code || dj.species;
    if (!speciesCode) return { ok: false, reason: 'missing_species_code' };
    const sp = await speciesCache.getSpeciesUuid(client, speciesCode);
    if (!sp.ok) return { ok: false, reason: sp.reason || 'species_lookup_failed' };

    // 4. Block create
    const blockName = dj.block_name;
    if (!blockName) return { ok: false, reason: 'missing_block_name' };
    const blockRes = await assets.createFungiAsset(client, {
      name: blockName,
      parentIds: [batchId],
      speciesUuid: sp.uuid,
      qrCodes: pathAQrs,
      draftId,
    });
    if (!blockRes.ok) return { ok: false, reason: blockRes.reason || 'block_create_failed', http_status: blockRes.http_status };
    blockId = blockRes.assetId;
    createdAssets.push(blockId);
  }
  if (!batchRes.reused) createdAssets.unshift(batchId);

  // 5. Seeding log
  const logRes = await logs.createLog(client, 'seeding', {
    name: 'Inoc ' + (dj.block_name || blockId),
    timestamp,
    assetIds: [batchId, blockId],
    notes: dj.notes || '',
    draftId,
  });
  if (!logRes.ok) return { ok: false, reason: logRes.reason || 'log_create_failed', http_status: logRes.http_status, asset_ids: createdAssets };

  return {
    ok: true,
    asset_ids: createdAssets,
    log_ids: [logRes.logId],
    file_ids: [],
    http_status: logRes.http_status,
  };
}

module.exports = commitSeeding;
