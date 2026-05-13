'use strict';

// Phase 40 D-04 / D-04a: QR binding via farmos_asset_link module OR farm_id_tag
// fallback. resolveQr/probe-driven dispatch; bindQrOnCreate mutates asset POST
// payload for fallback path; bindQrPostCreate POSTs to /api/asset_link after
// asset creation when module is present.

async function resolveQr(client, qrCode) {
  try {
    const present = await client.probeAssetLinkModule();
    const enc = encodeURIComponent(qrCode);
    if (present) {
      const r = await client.get(`/api/asset_link/farmos_asset_link?filter[qr_code]=${enc}`);
      if (!r.ok) return { found: false, error: 'http_' + (r.status || 'network'), path: 'asset_link' };
      const arr = r.body && r.body.data;
      if (Array.isArray(arr) && arr.length > 0) {
        const entry = arr[0];
        const assetId = entry.relationships && entry.relationships.asset && entry.relationships.asset.data && entry.relationships.asset.data.id;
        return { found: !!assetId, assetId, path: 'asset_link' };
      }
      return { found: false, path: 'asset_link' };
    }
    // fallback path
    const r2 = await client.get(`/api/asset/fungi?filter[farm_id_tag.qr_code][value]=${enc}`);
    if (!r2.ok) return { found: false, error: 'http_' + (r2.status || 'network'), path: 'farm_id_tag' };
    const arr = r2.body && r2.body.data;
    if (Array.isArray(arr) && arr.length > 0) {
      return { found: true, assetId: arr[0].id, path: 'farm_id_tag' };
    }
    return { found: false, path: 'farm_id_tag' };
  } catch (e) {
    return { found: false, error: e.message };
  }
}

function bindQrOnCreate(payload, qrCodes, opts) {
  opts = opts || {};
  if (!opts.fallback) return payload;
  if (!qrCodes || qrCodes.length === 0) return payload;
  if (!payload || !payload.data || !payload.data.attributes) return payload;
  payload.data.attributes.farm_id_tag = qrCodes.map((c) => ({ qr_code: c }));
  return payload;
}

async function bindQrPostCreate(client, assetId, qrCodes) {
  const bindings = [];
  let okAll = true;
  for (const qr of qrCodes || []) {
    try {
      const r = await client.post('/api/asset_link/farmos_asset_link', {
        data: {
          type: 'asset_link--farmos_asset_link',
          attributes: { qr_code: qr },
          relationships: {
            asset: { data: { type: 'asset--fungi', id: assetId } },
          },
        },
      });
      if (r.ok) {
        const linkId = r.body && r.body.data && r.body.data.id;
        bindings.push({ qr_code: qr, ok: true, link_id: linkId });
      } else {
        okAll = false;
        bindings.push({ qr_code: qr, ok: false, http_status: r.status });
      }
    } catch (e) {
      okAll = false;
      bindings.push({ qr_code: qr, ok: false, error: e.message });
    }
  }
  return { ok: okAll, bindings };
}

module.exports = { resolveQr, bindQrOnCreate, bindQrPostCreate };
