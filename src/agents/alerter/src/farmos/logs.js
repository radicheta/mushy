'use strict';

// Phase 40 D-03 / D-03c: B7 log creation. Native types only (C5):
// seeding | activity | input | observation | harvest. Any other log_type
// throws UnsupportedLogTypeError BEFORE any farmOS call (commit-router catches).
//
// Phase 48 Plan 01: 'seeding_session' is a COMPOSITE log_type recognized by the
// commit-router (so the guard does not bounce it) but NOT a native farmOS log
// type. createLog rejects it -- the seeding_session handler (Plan 02) writes
// one asset + N child seeding logs by calling createLog(client, 'seeding', ...).
// NATIVE_LOG_TYPES is the createLog allow-list; LOG_TYPES is the router guard.
//
// Phase 51 UPSERT-02: upsertLog(client, type, opts) -- lookup-by-stable-key
// then PATCH-merge-or-POST-create. Only 'seeding' migrates this phase (B5
// invariant: one seeding log per child asset makes (type='seeding',
// asset.id == assetIds[0]) an unambiguous stable key). All other log types
// map to null in LOG_STABLE_KEYS and fall through to createLog POST behavior.

const { STABLE_NOTES_SEPARATOR } = require('./merge');

const NATIVE_LOG_TYPES = ['seeding', 'activity', 'input', 'observation', 'harvest'];
const LOG_TYPES = [...NATIVE_LOG_TYPES, 'seeding_session'];

class UnsupportedLogTypeError extends Error {
  constructor(logType) {
    super('unsupported_log_type:' + logType);
    this.name = 'UnsupportedLogTypeError';
    this.logType = logType;
  }
}

class LogIdentityCollision extends Error {
  constructor(logType, assetId, matchedIds) {
    super('log_identity_collision:' + logType + ':' + assetId);
    this.name = 'LogIdentityCollision';
    this.logType = logType;
    this.assetId = assetId;
    this.matchedIds = matchedIds;
  }
}

// Phase 51 UPSERT-02: per-type stable-key resolvers. Only 'seeding' migrates
// to upsert in this phase (B5 invariant: one seeding log per child asset).
// Other types map to null -> POST-only path preserved.
const LOG_STABLE_KEYS = {
  seeding: ({ assetIds } = {}) => (assetIds && assetIds[0]
    ? { path: '/api/log/seeding?filter[asset.id][value]=' + encodeURIComponent(assetIds[0]) }
    : null),
  activity: null,
  input: null,
  observation: null,
  harvest: null,
};

function _buildNoteValue(notes, draftId) {
  return (notes ? notes + '\n' : '') + 'mushy:draft:' + draftId;
}

function _buildLogBody(logType, opts) {
  const { name, timestamp, assetIds = [], fileIds = [], notes = '', draftId } = opts;
  const payload = {
    data: {
      type: 'log--' + logType,
      attributes: {
        name,
        timestamp: Math.floor(timestamp),
        status: 'done',
        notes: { value: _buildNoteValue(notes, draftId), format: 'plain_text' },
      },
      relationships: {
        asset: { data: assetIds.map((id) => ({ type: 'asset--fungi', id })) },
      },
    },
  };
  if (fileIds && fileIds.length > 0) {
    payload.data.relationships.file = {
      data: fileIds.map((id) => ({ type: 'file--file', id })),
    };
  }
  return payload;
}

async function createLog(client, logType, opts) {
  if (!NATIVE_LOG_TYPES.includes(logType)) {
    throw new UnsupportedLogTypeError(logType);
  }
  const payload = _buildLogBody(logType, opts);
  const r = await client.post('/api/log/' + logType, payload);
  if (!r.ok) {
    return { ok: false, reason: 'http_' + (r.status || 'network'), http_status: r.status };
  }
  const logId = r.body && r.body.data && r.body.data.id;
  return { ok: true, logId, http_status: r.status };
}

// ---- Phase 51 UPSERT-02 helpers ----

function _setUnionRefs(existingArr, incomingArr) {
  const existing = Array.isArray(existingArr) ? existingArr : [];
  const incoming = Array.isArray(incomingArr) ? incomingArr : [];
  const byId = new Map();
  for (const ref of existing) {
    if (ref && ref.id != null && !byId.has(ref.id)) byId.set(ref.id, ref);
  }
  for (const ref of incoming) {
    if (ref && ref.id != null && !byId.has(ref.id)) byId.set(ref.id, ref);
  }
  return Array.from(byId.values());
}

function _mergeNotes(existing, incoming) {
  const ev = (existing && existing.value) || '';
  const iv = (incoming && incoming.value) || '';
  const sep = STABLE_NOTES_SEPARATOR;
  const entries = ev.split(sep).map((s) => s.trim()).filter((s) => s.length > 0);
  for (const e of iv.split(sep).map((s) => s.trim()).filter((s) => s.length > 0)) {
    if (!entries.includes(e)) entries.push(e);
  }
  return { value: entries.join(sep), format: 'plain_text' };
}

function _arraysEqualById(a, b) {
  const aa = Array.isArray(a) ? a : [];
  const bb = Array.isArray(b) ? b : [];
  if (aa.length !== bb.length) return false;
  const aIds = aa.map((r) => r && r.id).sort();
  const bIds = bb.map((r) => r && r.id).sort();
  for (let i = 0; i < aIds.length; i++) if (aIds[i] !== bIds[i]) return false;
  return true;
}

function _sortMatches(matches) {
  return matches.slice().sort((a, b) => {
    const ca = (a.attributes && a.attributes.created) || '';
    const cb = (b.attributes && b.attributes.created) || '';
    if (ca !== cb) return ca < cb ? -1 : 1;
    if (a.id < b.id) return -1;
    if (a.id > b.id) return 1;
    return 0;
  });
}

async function _emitAudit(auditLogger, event, payload) {
  if (auditLogger && typeof auditLogger.logCommit === 'function') {
    try { await auditLogger.logCommit(event, payload); } catch (_) { /* non-fatal */ }
  }
}

async function upsertLog(client, type, opts) {
  // Reject non-native types up front (mirror createLog).
  if (!NATIVE_LOG_TYPES.includes(type)) {
    throw new UnsupportedLogTypeError(type);
  }

  const keyFn = LOG_STABLE_KEYS[type];

  // Pass-through: types with null stable key go straight to POST.
  if (keyFn === null) {
    const r = await createLog(client, type, opts);
    if (r.ok) return Object.assign({}, r, { outcome: 'created', conflicts: [], etag_source: null });
    return r;
  }

  const key = keyFn(opts);
  if (key === null) {
    return { ok: false, reason: 'missing_stable_key', http_status: null };
  }

  // Lookup by stable key.
  const lookup = await client.get(key.path);
  if (!lookup.ok) {
    return { ok: false, reason: 'http_' + (lookup.status || 'network'), http_status: lookup.status };
  }
  const rawMatches = (lookup.body && lookup.body.data) || [];

  // Miss: POST via createLog.
  if (rawMatches.length === 0) {
    const r = await createLog(client, type, opts);
    if (r.ok) return Object.assign({}, r, { outcome: 'created', conflicts: [], etag_source: null });
    return r;
  }

  // Hit (>=1 match): sort, pick oldest, surface collision warning if >1.
  const sorted = _sortMatches(rawMatches);
  const canonical = sorted[0];
  const warnings = [];
  if (sorted.length > 1) {
    const matchedIds = sorted.map((m) => m.id);
    warnings.push('LogIdentityCollision:' + sorted.length);
    await _emitAudit(opts.auditLogger, 'log_identity_collision', {
      log_type: type,
      asset_id: opts.assetIds && opts.assetIds[0],
      matched_ids: matchedIds,
    });
  }

  // GET full body for merge.
  const fullResp = await client.get('/api/log/' + type + '/' + canonical.id);
  if (!fullResp.ok) {
    return { ok: false, reason: 'http_' + (fullResp.status || 'network'), http_status: fullResp.status, warnings };
  }
  const existing = fullResp.body && fullResp.body.data;
  const preMergeRevisionId = existing && existing.attributes && existing.attributes.drupal_internal__revision_id;

  // Build incoming and merge.
  const incomingPayload = _buildLogBody(type, opts);
  const incoming = incomingPayload.data;

  // Identity check: asset.data must match between existing and incoming (the stable key).
  const existingAssetData = (existing.relationships && existing.relationships.asset && existing.relationships.asset.data) || [];
  const incomingAssetData = incoming.relationships.asset.data || [];
  if (!_arraysEqualById(existingAssetData, incomingAssetData)) {
    return {
      ok: false,
      reason: 'log_identity_mismatch',
      http_status: null,
      logId: canonical.id,
      warnings,
    };
  }

  // Merge file.data: set-union by id.
  const existingFileData = (existing.relationships && existing.relationships.file && existing.relationships.file.data) || [];
  const incomingFileData = (incoming.relationships.file && incoming.relationships.file.data) || [];
  const mergedFiles = _setUnionRefs(existingFileData, incomingFileData);
  const filesChanged = mergedFiles.length !== existingFileData.length;

  // Merge notes (split-dedup-join).
  const mergedNotes = _mergeNotes(
    existing.attributes && existing.attributes.notes,
    incoming.attributes.notes
  );
  const notesChanged = !(existing.attributes && existing.attributes.notes &&
    existing.attributes.notes.value === mergedNotes.value);

  // Scalar conflicts: timestamp / status / name -- equal=noop, differ=conflict.
  const conflicts = [];
  for (const field of ['timestamp', 'status', 'name']) {
    const ev = existing.attributes && existing.attributes[field];
    const iv = incoming.attributes[field];
    if (iv == null) continue;
    if (ev != null && ev !== iv) {
      conflicts.push({ field, existing: ev, incoming: iv, kind: 'scalar_conflict' });
    }
  }

  if (!filesChanged && !notesChanged) {
    return {
      ok: true,
      logId: canonical.id,
      outcome: 'noop',
      conflicts,
      etag_source: 'soft_compare',
      http_status: null,
      warnings,
    };
  }

  // Build PATCH body with merged file + notes (preserve asset identity).
  const patchBody = {
    data: {
      type: 'log--' + type,
      id: canonical.id,
      attributes: {
        notes: mergedNotes,
      },
      relationships: {
        asset: { data: existingAssetData },
        file: { data: mergedFiles },
      },
    },
  };

  // PATCH with If-Match; soft-compare retry once on 412.
  const ifMatch = preMergeRevisionId != null ? String(preMergeRevisionId) : null;
  const patchOpts = ifMatch ? { headers: { 'If-Match': ifMatch } } : undefined;

  let patchResp = await client.patch('/api/log/' + type + '/' + canonical.id, patchBody, patchOpts);
  if (!patchResp.ok && patchResp.status === 412) {
    // Soft-compare retry: re-GET, rebuild merge, PATCH once more.
    const reGet = await client.get('/api/log/' + type + '/' + canonical.id);
    if (!reGet.ok) {
      return { ok: false, reason: 'http_' + (reGet.status || 'network'), http_status: reGet.status, warnings };
    }
    const refreshed = reGet.body && reGet.body.data;
    const refreshedRev = refreshed && refreshed.attributes && refreshed.attributes.drupal_internal__revision_id;
    const refreshedFiles = (refreshed.relationships && refreshed.relationships.file && refreshed.relationships.file.data) || [];
    const refreshedNotes = refreshed.attributes && refreshed.attributes.notes;
    const remergeFiles = _setUnionRefs(refreshedFiles, incomingFileData);
    const remergeNotes = _mergeNotes(refreshedNotes, incoming.attributes.notes);
    const retryBody = {
      data: {
        type: 'log--' + type,
        id: canonical.id,
        attributes: { notes: remergeNotes },
        relationships: {
          asset: { data: existingAssetData },
          file: { data: remergeFiles },
        },
      },
    };
    const retryHeaders = refreshedRev != null ? { headers: { 'If-Match': String(refreshedRev) } } : undefined;
    patchResp = await client.patch('/api/log/' + type + '/' + canonical.id, retryBody, retryHeaders);
  }

  if (!patchResp.ok) {
    return { ok: false, reason: 'http_' + (patchResp.status || 'network'), http_status: patchResp.status, warnings };
  }

  return {
    ok: true,
    logId: canonical.id,
    outcome: 'patched',
    conflicts,
    etag_source: 'soft_compare',
    http_status: patchResp.status,
    warnings,
  };
}

module.exports = {
  LOG_TYPES,
  NATIVE_LOG_TYPES,
  UnsupportedLogTypeError,
  LogIdentityCollision,
  LOG_STABLE_KEYS,
  createLog,
  upsertLog,
};
