'use strict';

// Phase 40 D-04 / D-04a -- QR binding via the upstream `farm_id_tag`
// field (JSON:API attribute name: `id_tag`). Each tag entry has the
// shape `{type, id, location}` where `id` carries the QR value and
// `type` is the tag-system label (we use 'qr').
//
// 2026-05-14 (farmOS prod-cutover): superseded the previous
// `farmos_asset_link` dispatch. That module is a PWA frontend, not a
// JSON:API backend -- there is no `/api/asset_link/...` resource type,
// so the probe and POST paths can never succeed. Removed. The previous
// fallback's attribute name (`farm_id_tag`) was also wrong; the real
// upstream JSON:API attribute is `id_tag`.

// 'other' rather than 'qr': prod-farmOS's farm_id_tag module configures
// a restricted set of allowed id_tag types and 'qr' isn't in it. 'other'
// matches the type already in use on the pre-existing asset 31 from the
// prod backfill. If farmOS later adds 'qr' to the allowed list, flip
// this constant -- no other code change needed.
const ID_TAG_TYPE = 'other';

async function resolveQr(client, qrCode) {
  try {
    const enc = encodeURIComponent(qrCode);
    const r = await client.get(`/api/asset/fungi?filter[id_tag.id][value]=${enc}`);
    if (!r.ok) return { found: false, error: 'http_' + (r.status || 'network'), path: 'id_tag' };
    const arr = r.body && r.body.data;
    if (Array.isArray(arr) && arr.length > 0) {
      return { found: true, assetId: arr[0].id, path: 'id_tag' };
    }
    return { found: false, path: 'id_tag' };
  } catch (e) {
    return { found: false, error: e.message };
  }
}

function bindQrOnCreate(payload, qrCodes) {
  if (!qrCodes || qrCodes.length === 0) return payload;
  if (!payload || !payload.data || !payload.data.attributes) return payload;
  payload.data.attributes.id_tag = qrCodes.map((c) => ({ id: c, type: ID_TAG_TYPE, location: '' }));
  return payload;
}

module.exports = { resolveQr, bindQrOnCreate };
