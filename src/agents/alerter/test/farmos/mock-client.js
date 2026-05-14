'use strict';

// Mock farmOS client for commit-module unit tests. Records every call;
// returns canned responses keyed by (method, urlPattern). Supports:
//   - probeAssetLinkModule (boolean toggle, default false = fallback path)
//   - get(/api/asset/fungi?filter[name][value]=...) -> name -> assetId lookup
//   - get(/api/asset_link/farmos_asset_link?filter[qr_code]=...) -> qr -> assetId
//   - get(/api/asset/fungi?filter[farm_id_tag.qr_code]...) -> qr -> assetId
//   - get(/api/taxonomy_term/fungi_type?filter[name][value]=...) -> strain -> uuid
//   - get(/api/taxonomy_term/fungi_xing?filter[name][value]=...) -> xing -> uuid
//   - post(/api/asset/fungi)        -> assigns a unique id, records name
//   - post(/api/asset_link/farmos_asset_link) -> success
//   - post(/api/log/<type>)         -> assigns a unique log id
//   - postBinary(/api/file/file)    -> assigns a unique file id

function makeMockClient({
  present = false,
  knownAssetsByName = {},    // name -> assetId for pre-existing assets
  knownAssetsByQr = {},      // qrCode -> assetId for pre-existing bindings
  fungiTypeUuids = {
    SHI: 'ft-shi', SH2: 'ft-sh2', KOY: 'ft-koy', MAI: 'ft-mai', MALI: 'ft-mali',
    KOS: 'ft-kos', DT: 'ft-dt', CAS: 'ft-cas', CAZ: 'ft-caz', WIN: 'ft-win',
    ALM: 'ft-alm', MOR: 'ft-mor', BP: 'ft-bp', LIMA: 'ft-lima',
  },
  fungiXingUuids = { block: 'fx-block', fruit: 'fx-fruit' },
} = {}) {
  const created = { assets: [], logs: [], files: [], links: [] };
  let assetSeq = 1; let logSeq = 1; let fileSeq = 1; let linkSeq = 1;
  const calls = [];

  function _ok(status, body) { return { ok: status >= 200 && status < 300, status, body }; }

  const client = {
    _created: created,
    _calls: calls,
    present,
    probeAssetLinkModule: jest.fn(async () => present),

    get: jest.fn(async (path, opts) => {
      calls.push({ method: 'GET', path });
      let m;
      m = /\/api\/asset\/fungi\?filter\[name\]\[value\]=([^&]+)/.exec(path);
      if (m) {
        const name = decodeURIComponent(m[1]);
        if (knownAssetsByName[name]) return _ok(200, { data: [{ id: knownAssetsByName[name] }] });
        return _ok(200, { data: [] });
      }
      m = /\/api\/asset_link\/farmos_asset_link\?filter\[qr_code\]=([^&]+)/.exec(path);
      if (m) {
        const qr = decodeURIComponent(m[1]);
        if (knownAssetsByQr[qr]) {
          return _ok(200, { data: [{
            type: 'asset_link--farmos_asset_link',
            relationships: { asset: { data: { type: 'asset--fungi', id: knownAssetsByQr[qr] } } },
          }] });
        }
        return _ok(200, { data: [] });
      }
      m = /\/api\/asset\/fungi\?filter\[farm_id_tag\.qr_code\]\[value\]=([^&]+)/.exec(path);
      if (m) {
        const qr = decodeURIComponent(m[1]);
        if (knownAssetsByQr[qr]) return _ok(200, { data: [{ id: knownAssetsByQr[qr] }] });
        return _ok(200, { data: [] });
      }
      m = /\/api\/taxonomy_term\/fungi_type\?filter\[name\]\[value\]=([^&]+)/.exec(path);
      if (m) {
        const typeName = decodeURIComponent(m[1]);
        if (fungiTypeUuids[typeName]) return _ok(200, { data: [{ id: fungiTypeUuids[typeName] }] });
        return _ok(200, { data: [] });
      }
      m = /\/api\/taxonomy_term\/fungi_xing\?filter\[name\]\[value\]=([^&]+)/.exec(path);
      if (m) {
        const xingName = decodeURIComponent(m[1]);
        if (fungiXingUuids[xingName]) return _ok(200, { data: [{ id: fungiXingUuids[xingName] }] });
        return _ok(200, { data: [] });
      }
      return _ok(200, { data: [] });
    }),

    post: jest.fn(async (path, body, opts) => {
      calls.push({ method: 'POST', path, body });
      if (path === '/api/asset/fungi') {
        const id = 'asset-' + (assetSeq++);
        created.assets.push({ id, name: body.data.attributes.name, payload: body });
        return _ok(201, { data: { id, type: 'asset--fungi' } });
      }
      if (path === '/api/asset_link/farmos_asset_link') {
        const id = 'link-' + (linkSeq++);
        created.links.push({ id, payload: body });
        return _ok(201, { data: { id } });
      }
      if (/^\/api\/log\//.test(path)) {
        const id = 'log-' + (logSeq++);
        const t = path.split('/').pop();
        created.logs.push({ id, type: t, payload: body });
        return _ok(201, { data: { id, type: 'log--' + t } });
      }
      return _ok(404, {});
    }),

    postBinary: jest.fn(async (path, bytes, opts) => {
      calls.push({ method: 'POST_BINARY', path, opts });
      const id = 'file-' + (fileSeq++);
      created.files.push({ id });
      return _ok(201, { data: { id } });
    }),
  };
  return client;
}

module.exports = { makeMockClient };
