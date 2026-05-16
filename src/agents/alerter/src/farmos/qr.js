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

// D-06: id_tag-first, name-on-miss fallback.
// Flow: try filter[id_tag.id][value]=<qrCode> (existing path). If ok:true but
// data:[] (empty -- no asset matches the id_tag), retry against
// filter[name][value]=<qrCode>. The returned `path` field indicates which
// lookup matched ('id_tag' or 'name').
//
// D-08: Name collisions are a farmer-side discipline risk, not a structural
// concern for v1.7. If two fungi assets share a name, the first JSON:API
// result wins (same first-result-wins behavior as id_tag). No programmatic
// dedup in Phase 43.
//
// Transport failures (http_* on the id_tag call) are NOT a "miss" -- return
// immediately without falling back to the name lookup.
async function resolveQr(client, qrCode) {
  try {
    const enc = encodeURIComponent(qrCode);
    const r = await client.get(`/api/asset/fungi?filter[id_tag.id][value]=${enc}`);
    if (!r.ok) return { found: false, error: 'http_' + (r.status || 'network'), path: 'id_tag' };
    const arr = r.body && r.body.data;
    if (Array.isArray(arr) && arr.length > 0) {
      return { found: true, assetId: arr[0].id, path: 'id_tag' };
    }
    // id_tag lookup returned empty -- fall back to name lookup (D-06).
    const r2 = await client.get(`/api/asset/fungi?filter[name][value]=${enc}`);
    if (!r2.ok) return { found: false, error: 'http_' + (r2.status || 'network'), path: 'name' };
    const arr2 = r2.body && r2.body.data;
    if (Array.isArray(arr2) && arr2.length > 0) {
      return { found: true, assetId: arr2[0].id, path: 'name' };
    }
    return { found: false, path: 'name' };
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
