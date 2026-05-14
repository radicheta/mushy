'use strict';

// Phase 40 B7.1 seeding (inoc). Option A hybrid shape (2026-05-14):
//   * Block (B2) is the only fungi asset this module creates. fungi_type
//     carries the strain code, fungi_xing='block'.
//   * The pre-inoc sterilization batch (B1) is NOT a fungi asset under
//     the new schema -- it lives as a pasteurization log on the farmOS
//     side (log type TBD by farmOS team) or as a material asset for euc
//     logs. The alerter does not write it for now; batch_name is
//     preserved in the seeding log notes so lineage is recoverable from
//     the log when pasteurization-log wiring lands.
//   * Path B (QR resolves to existing block): append-log-only.
//
// Cross-ref: .planning/notes/2026-05-14-reply-from-farmos-fungi-schema.md

const assets = require('../assets');
const logs = require('../logs');
const qrMod = require('../qr');

async function commitSeeding(client, draft, ctx) {
  const dj = draft.draft_json || {};
  const draftId = draft.id;
  const qrCodes = Array.isArray(dj.qr_codes) ? dj.qr_codes : [];
  const timestamp = typeof dj.timestamp === 'number' ? dj.timestamp : (Date.now() / 1000);

  // Path A vs Path B (QR resolution).
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
  const createdAssets = [];
  if (pathBIds.length === 1) {
    blockId = pathBIds[0];
  } else {
    // Strain (= fungi_type) required when creating a new block.
    const strain = dj.species_code || dj.species || dj.strain || dj.fungi_type;
    if (!strain) return { ok: false, reason: 'missing_strain' };

    const blockName = dj.block_name;
    if (!blockName) return { ok: false, reason: 'missing_block_name' };
    const blockRes = await assets.createFungiAsset(client, {
      name: blockName,
      fungiTypeName: strain,
      fungiXingName: 'block',
      qrCodes: pathAQrs,
      draftId,
    });
    if (!blockRes.ok) return { ok: false, reason: blockRes.reason || 'block_create_failed', http_status: blockRes.http_status };
    blockId = blockRes.assetId;
    createdAssets.push(blockId);
  }

  // Seeding log. batch_name preserved in notes (pasteurization log not
  // wired yet on farmOS side -- see header comment).
  const batchName = dj.batch_name;
  const noteParts = [];
  if (dj.notes) noteParts.push(dj.notes);
  if (batchName) noteParts.push('sterilization_batch: ' + batchName);
  const notes = noteParts.join('\n');

  const logRes = await logs.createLog(client, 'seeding', {
    name: 'Inoc ' + (dj.block_name || blockId),
    timestamp,
    assetIds: [blockId],
    notes,
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
