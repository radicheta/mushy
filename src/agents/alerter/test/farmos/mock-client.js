'use strict';

// Mock farmOS client for commit-module unit tests. Records every call;
// returns canned responses keyed by (method, urlPattern). Supports:
//   - get(/api/asset/fungi?filter[name][value]=...) -> name -> assetId lookup
//   - get(/api/asset/fungi?filter[id_tag.id][value]=...) -> qr -> assetId
//   - get(/api/taxonomy_term/fungi_type?filter[name][value]=...) -> strain -> uuid
//   - get(/api/taxonomy_term/fungi_xing?filter[name][value]=...) -> xing -> uuid
//   - get(/api/asset/fungi/<uuid>) -> full asset body by id  [Phase 51 Wave 0]
//   - get(/api/log/<type>/<uuid>)  -> full log body by id    [Phase 51 Wave 0]
//   - post(/api/asset/fungi)        -> assigns a unique id, records name
//   - post(/api/log/<type>)         -> assigns a unique log id
//   - postBinary(/api/{type}/{bundle}/{uuid}/{field}) -> assigns a unique file id
//   - postBinary(/api/file/file)    -> 415, as the real farmOS does (MUSHY-36)
//   - patch(/api/asset/fungi/<uuid> | /api/log/<type>/<uuid>) [Phase 51 Wave 0]
//   - delete(<path>)                                          [Phase 51 Wave 0]
//
// Phase 51 Wave 0 extension keeps back-compat with the legacy
// knownAssetsByName: { name: 'asset-id' } string-value shape AND accepts
// the new richer shape: { name: { id, attributes, relationships } }.

function makeMockClient({
  knownAssetsByName = {},    // name -> assetId (string) OR { id, attributes?, relationships? }
  knownAssetsByQr = {},      // qrCode -> assetId for pre-existing bindings
  fungiTypeUuids = {
    SHI: 'ft-shi', SH2: 'ft-sh2', KOY: 'ft-koy', MAI: 'ft-mai', MALI: 'ft-mali',
    KOS: 'ft-kos', DT: 'ft-dt', CAS: 'ft-cas', CAZ: 'ft-caz', WIN: 'ft-win',
    ALM: 'ft-alm', MOR: 'ft-mor', BP: 'ft-bp', LIMA: 'ft-lima',
  },
  fungiXingUuids = { block: 'fx-block', fruit: 'fx-fruit' },
  force412Ids = [],          // asset/log ids that 412 on first PATCH then succeed
  revisionIds = {},          // name -> revision_id override (default 1)
  knownLogsByAssetId = {},   // assetId -> { id, type } seed for log GET-by-id (Plan 02+)
  knownGroupsByName = {},    // Phase 52: name -> { id, attributes? } for asset--group seeding
} = {}) {
  const created = { assets: [], logs: [], files: [], groups: [], activityLogs: [] };
  let assetSeq = 1; let logSeq = 1; let fileSeq = 1;
  let groupSeq = 1;
  const calls = [];
  const _force412 = new Set(force412Ids || []);

  // Build _byId registry from knownAssetsByName accepting both shapes.
  // String value -> { id: '<string>' } with default attributes + relationships.
  // Object value -> use as-is, defaulting missing attrs/rels.
  const _byId = {};
  // Also a flat name -> id map for the filter[name] dispatcher.
  const _idByName = {};
  for (const [name, val] of Object.entries(knownAssetsByName || {})) {
    const id = typeof val === 'string' ? val : (val && val.id);
    if (!id) continue;
    _idByName[name] = id;
    const revId = (revisionIds && revisionIds[name] != null) ? revisionIds[name] : 1;
    const baseAttrs = (typeof val === 'object' && val.attributes) ? val.attributes : {};
    const baseRels = (typeof val === 'object' && val.relationships) ? val.relationships : {};
    _byId[id] = {
      id,
      type: 'asset--fungi',
      attributes: Object.assign({ name, drupal_internal__revision_id: revId }, baseAttrs),
      relationships: baseRels,
    };
  }

  const _logsByAssetId = knownLogsByAssetId || {};

  // Phase 52: asset--group registry (name <-> id + body).
  const _groupById = {};
  const _groupIdByName = {};
  for (const [name, val] of Object.entries(knownGroupsByName || {})) {
    const id = typeof val === 'string' ? val : (val && val.id);
    if (!id) continue;
    _groupIdByName[name] = id;
    const baseAttrs = (typeof val === 'object' && val.attributes) ? val.attributes : {};
    _groupById[id] = {
      id,
      type: 'asset--group',
      attributes: Object.assign({ name }, baseAttrs),
      relationships: {},
    };
  }

  function _ok(status, body) { return { ok: status >= 200 && status < 300, status, body }; }

  function _mergeForPatch(existing, incoming) {
    const mergedAttrs = Object.assign({}, existing.attributes || {}, (incoming && incoming.attributes) || {});
    const mergedRels = Object.assign({}, existing.relationships || {}, (incoming && incoming.relationships) || {});
    return { id: existing.id, type: existing.type, attributes: mergedAttrs, relationships: mergedRels };
  }

  const client = {
    _created: created,
    _calls: calls,
    _byId,
    _idByName,
    _logsByAssetId,
    _groupById,
    _groupIdByName,
    _force412,

    get: jest.fn(async (path, opts) => {
      calls.push({ method: 'GET', path });
      let m;
      m = /\/api\/asset\/fungi\?filter\[name\]\[value\]=([^&]+)/.exec(path);
      if (m) {
        const name = decodeURIComponent(m[1]);
        if (_idByName[name]) return _ok(200, { data: [{ id: _idByName[name] }] });
        return _ok(200, { data: [] });
      }
      // Phase 52: asset--group lookup by name.
      m = /\/api\/asset\/group\?filter\[name\]\[value\]=([^&]+)/.exec(path);
      if (m) {
        const name = decodeURIComponent(m[1]);
        if (_groupIdByName[name]) return _ok(200, { data: [{ id: _groupIdByName[name] }] });
        return _ok(200, { data: [] });
      }
      // Phase 52: asset--group GET by id.
      m = /^\/api\/asset\/group\/([A-Za-z0-9-]+)$/.exec(path);
      if (m) {
        const id = m[1];
        if (_groupById[id]) return _ok(200, { data: _groupById[id] });
        return _ok(404, { errors: [{ status: '404', title: 'Not Found' }] });
      }
      m = /\/api\/asset\/fungi\?filter\[id_tag\.id\]\[value\]=([^&]+)/.exec(path);
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
      // Phase 51 Wave 0: asset GET-by-id (regex accepts both UUID-v4 and
      // shorter test ids so legacy fixtures like 'a-1' still work).
      m = /^\/api\/asset\/fungi\/([A-Za-z0-9-]+)$/.exec(path);
      if (m) {
        const id = m[1];
        if (_byId[id]) return _ok(200, { data: _byId[id] });
        return _ok(404, { errors: [{ status: '404', title: 'Not Found' }] });
      }
      // Phase 51 Wave 0: log filter by asset.id (upsertLog stable-key lookup).
      m = /^\/api\/log\/([a-z_]+)\?filter\[asset\.id\]\[value\]=([^&]+)/.exec(path);
      if (m) {
        const logType = m[1];
        const assetId = decodeURIComponent(m[2]);
        const matches = [];
        for (const v of Object.values(_logsByAssetId)) {
          if (v && v.type === logType && Array.isArray(v.assetIds) && v.assetIds.includes(assetId)) {
            matches.push({
              id: v.id,
              type: 'log--' + logType,
              attributes: v.attributes || { drupal_internal__revision_id: 1 },
              relationships: v.relationships || {},
            });
          }
        }
        return _ok(200, { data: matches });
      }
      // Phase 51 Wave 0: log GET-by-id
      m = /^\/api\/log\/([a-z_]+)\/([A-Za-z0-9-]+)$/.exec(path);
      if (m) {
        const logType = m[1];
        const id = m[2];
        for (const v of Object.values(_logsByAssetId)) {
          if (v && v.id === id) {
            return _ok(200, {
              data: {
                id,
                type: 'log--' + logType,
                attributes: v.attributes || { drupal_internal__revision_id: 1 },
                relationships: v.relationships || {},
              },
            });
          }
        }
        return _ok(404, { errors: [{ status: '404', title: 'Not Found' }] });
      }
      return _ok(200, { data: [] });
    }),

    post: jest.fn(async (path, body, opts) => {
      calls.push({ method: 'POST', path, body });
      if (path === '/api/asset/group') {
        const id = 'group-' + (groupSeq++);
        const name = body.data.attributes.name;
        created.groups.push({ id, name, payload: body });
        _groupIdByName[name] = id;
        _groupById[id] = {
          id,
          type: 'asset--group',
          attributes: Object.assign({}, body.data.attributes || {}),
          relationships: (body.data && body.data.relationships) || {},
        };
        return _ok(201, { data: { id, type: 'asset--group' } });
      }
      if (path === '/api/asset/fungi') {
        const id = 'asset-' + (assetSeq++);
        const name = body.data.attributes.name;
        created.assets.push({ id, name, payload: body });
        // Phase 51 idempotency support: register POSTed asset into _byId and
        // _idByName so subsequent findAssetByName + GET-by-id hit and upsert
        // replays converge instead of erroring 'lookup_missing_after_find'.
        _idByName[name] = id;
        _byId[id] = {
          id,
          type: 'asset--fungi',
          attributes: Object.assign({ drupal_internal__revision_id: 1 }, body.data.attributes || {}),
          relationships: (body.data && body.data.relationships) || {},
        };
        return _ok(201, { data: { id, type: 'asset--fungi' } });
      }
      if (/^\/api\/log\//.test(path)) {
        const id = 'log-' + (logSeq++);
        const t = path.split('/').pop();
        const entry = { id, type: t, payload: body };
        created.logs.push(entry);
        // Phase 52: parallel index for group-assignment activity logs.
        const isGroupAssign = body && body.data && body.data.attributes
          && body.data.attributes.is_group_assignment === true;
        if (t === 'activity' && isGroupAssign) {
          created.activityLogs.push(entry);
        }
        // Register POSTed log so upsertLog stable-key lookup + GET-by-id hit.
        const relAsset = body.data && body.data.relationships && body.data.relationships.asset;
        const assetIds = (relAsset && Array.isArray(relAsset.data))
          ? relAsset.data.map((r) => r && r.id).filter(Boolean)
          : [];
        _logsByAssetId[id] = {
          id,
          type: t,
          assetIds,
          attributes: Object.assign({ drupal_internal__revision_id: 1 }, body.data.attributes || {}),
          relationships: (body.data && body.data.relationships) || {},
        };
        return _ok(201, { data: { id, type: 'log--' + t } });
      }
      return _ok(404, {});
    }),

    postBinary: jest.fn(async (path, bytes, opts) => {
      calls.push({ method: 'POST_BINARY', path, opts });
      // MUSHY-36: this farmOS has NO octet-stream route at /api/file/file. It
      // answers 415 "No route found that matches Content-Type:
      // application/octet-stream" -- verified on dev AND prod. The mock used to
      // return 201 here, so every caller of the legacy route looked healthy in
      // tests while failing 100% of the time in production. Reject it the way
      // the real server does.
      if (path === '/api/file/file') {
        return _ok(415, {
          errors: [{
            status: '415',
            detail: 'No route found that matches "Content-Type: application/octet-stream"',
          }],
        });
      }
      // Field-scoped binary route: POST /api/{type}/{bundle}/{uuid}/{field}.
      // Creates the file AND links it to the entity field in one call.
      const id = 'file-' + (fileSeq++);
      created.files.push({ id });
      return _ok(201, { data: { id } });
    }),

    // Phase 51 Wave 0: PATCH with merged-body return + force412 first-fail protocol.
    patch: jest.fn(async (path, body, opts) => {
      calls.push({ method: 'PATCH', path, body, headers: opts && opts.headers });
      let m = /^\/api\/asset\/fungi\/([A-Za-z0-9-]+)$/.exec(path);
      let isLog = false;
      if (!m) {
        m = /^\/api\/log\/([a-z_]+)\/([A-Za-z0-9-]+)$/.exec(path);
        if (m) isLog = true;
      }
      if (!m) return _ok(404, {});
      const id = isLog ? m[2] : m[1];
      if (_force412.has(id)) {
        _force412.delete(id); // first PATCH fails; subsequent succeed
        return _ok(412, { errors: [{ status: '412', title: 'Precondition Failed' }] });
      }
      if (isLog) {
        const logType = m[1];
        const existingLog = _logsByAssetId[id] || {
          id, type: logType, assetIds: [], attributes: { drupal_internal__revision_id: 1 }, relationships: {},
        };
        const mergedAttrs = Object.assign({}, existingLog.attributes || {}, (body.data && body.data.attributes) || {});
        const mergedRels = Object.assign({}, existingLog.relationships || {}, (body.data && body.data.relationships) || {});
        _logsByAssetId[id] = Object.assign({}, existingLog, { attributes: mergedAttrs, relationships: mergedRels });
        return _ok(200, { data: { id, type: 'log--' + logType, attributes: mergedAttrs, relationships: mergedRels } });
      }
      const existing = _byId[id] || {
        id, type: 'asset--fungi', attributes: { drupal_internal__revision_id: 1 }, relationships: {},
      };
      const merged = _mergeForPatch(existing, body && body.data);
      _byId[id] = merged; // persist for subsequent GET
      return _ok(200, { data: merged });
    }),

    // Phase 51 Wave 0: DELETE returns 204 no-body.
    delete: jest.fn(async (path, opts) => {
      calls.push({ method: 'DELETE', path });
      return _ok(204, null);
    }),
  };
  return client;
}

module.exports = { makeMockClient };
