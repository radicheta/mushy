'use strict';

// Phase 40 B7.5 harvest (D-03b). Option A hybrid shape (2026-05-14):
//   * Bag assets ARE fungi assets: fungi_type=<strain>, fungi_xing='fruit',
//     parent=source blocks (C4 lineage).
//   * NO harvest_batch fungi asset under the new schema -- 'batch' is not
//     a valid fungi_xing value, and the harvest log itself bundles the
//     bags + source blocks together. harvest_batch_name (if present) is
//     preserved in the log notes for human-readable lineage.
//   * Missing source block aborts BEFORE any farmOS write. Bag QR
//     collision is terminal.
//
// Strain resolution: drafts don't carry an explicit strain field;
// extract from harvest_batch_name (HBATCH-...-{STRAIN}-...) or fall back
// to draft.strain / draft.species_code. Document missing-strain as a
// terminal failure -- caller must include it.
//
// Cross-ref: .planning/notes/2026-05-14-reply-from-farmos-fungi-schema.md

const assets = require('../assets');
const logs = require('../logs');
const qrMod = require('../qr');

// HBATCH-2026-05-13-DT-001 -> 'DT'.  Matches B5 strain codes (2-4 chars).
const HBATCH_STRAIN_RE = /-([A-Z]{2,4})-[0-9]+$/;

function resolveStrain(dj) {
  if (dj.strain) return dj.strain;
  if (dj.fungi_type) return dj.fungi_type;
  if (dj.species_code) return dj.species_code;
  if (dj.species) return dj.species;
  if (dj.harvest_batch_name) {
    const m = HBATCH_STRAIN_RE.exec(dj.harvest_batch_name);
    if (m) return m[1];
  }
  return null;
}

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

  // 2. Strain required for bag fungi_type.
  const strain = resolveStrain(dj);
  if (!strain) return { ok: false, reason: 'missing_strain' };

  // 3. Create bag assets (parents = source blocks).
  const batchName = dj.harvest_batch_name; // labelling only; not an asset.
  const bagIds = [];
  for (const bag of bags) {
    const bagName = bag.name || `${batchName || 'harvest'}-bag-${bagIds.length + 1}`;
    // Phase 51 UPSERT-01: bag asset goes through upsertFungiAsset so re-runs
    // converge instead of duplicating bags. Bag QR pre-check above already
    // ensures the QR slot is free; upsert semantics make name-based idempotency
    // safe for accidental replay.
    const bagRes = await assets.upsertFungiAsset(client, {
      name: bagName,
      parentIds: sourceIds,
      fungiTypeName: strain,
      fungiXingName: 'fruit',
      qrCodes: bag.qr_code ? [bag.qr_code] : [],
      draftId,
    });
    if (!bagRes.ok) return { ok: false, reason: bagRes.reason || 'bag_upsert_failed', http_status: bagRes.http_status, asset_ids: [...bagIds] };
    bagIds.push(bagRes.assetId);
  }

  // 4. Harvest log: order = source blocks, bags.
  const assetIds = [...sourceIds, ...bagIds];
  const weightLines = bags
    .map((b, i) => `bag${i + 1}: ${b.weight_grams != null ? b.weight_grams + 'g' : 'n/a'}`)
    .join('\n');
  const noteParts = [];
  if (dj.notes) noteParts.push(dj.notes);
  if (batchName) noteParts.push('harvest_batch: ' + batchName);
  if (weightLines) noteParts.push('Weights:\n' + weightLines);
  const notes = noteParts.join('\n');
  const name = `harvest ${new Date(timestamp * 1000).toISOString().slice(0, 10)}`;
  const logRes = await logs.createLog(client, 'harvest', {
    name, timestamp, assetIds, notes, draftId,
  });
  if (!logRes.ok) return { ok: false, reason: logRes.reason, http_status: logRes.http_status, asset_ids: [...bagIds] };

  return {
    ok: true,
    asset_ids: [...bagIds],
    log_ids: [logRes.logId],
    file_ids: [],
    http_status: logRes.http_status,
  };
}

module.exports = commitHarvest;
