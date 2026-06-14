'use strict';

// Phase 40 D-05 / D-05a / D-05b: two-step file upload (octet-stream POST -> file UUID).
// Skip-on-missing semantics so a deleted attachment doesn't fail the whole commit.
// No re-encoding / no thumbnailing -- bytes uploaded as-is.
//
// WARNING (2026-06-14): uploadAttachment(s) POST octet-stream to /api/file/file, which
// this farmOS does NOT route (415 "No route found that matches Content-Type:
// application/octet-stream" -- verified dev AND prod). This path has never worked live.
// The correct mechanism is the field-scoped binary route below (uploadFieldAttachment).
// commit-observation.js still uses the legacy path and needs the same migration.
// See memory project_farmos_image_upload_needs_field_scoped_route.

const fs = require('fs');
const path = require('path');

async function uploadAttachment(client, absPath, filename, opts) {
  opts = opts || {};
  const logger = opts.logger;
  try {
    await fs.promises.access(absPath, fs.constants.R_OK);
  } catch (e) {
    if (logger && logger.warn) {
      logger.warn(`[farmos] attachment missing, skipping: ${absPath}`);
    }
    return { ok: false, reason: 'attachment_missing', skipped: true, path: absPath };
  }
  let bytes;
  try {
    bytes = await fs.promises.readFile(absPath);
  } catch (e) {
    return { ok: false, reason: 'read_failed', error: e.message, path: absPath };
  }
  const fn = filename || path.basename(absPath);
  const r = await client.postBinary('/api/file/file', bytes, { filename: fn, timeoutMs: opts.timeoutMs || 30000 });
  if (r.ok) {
    const fileId = r.body && r.body.data && r.body.data.id;
    return { ok: true, fileId };
  }
  return { ok: false, reason: 'http_' + (r.status || 'network'), http_status: r.status };
}

async function uploadAttachments(client, paths, opts) {
  const fileIds = [];
  const skipped = [];
  const failed = [];
  for (const p of paths || []) {
    const r = await uploadAttachment(client, p, null, opts);
    if (r.ok) fileIds.push(r.fileId);
    else if (r.skipped) skipped.push(p);
    else failed.push({ path: p, reason: r.reason });
  }
  return { fileIds, skipped, failed };
}

// Phase 55B (2026-06-14): correct farmOS binary-upload mechanism. POST octet-stream to
// the field-scoped route  POST /api/{type}/{bundle}/{uuid}/{field}  (ct=bin). This CREATES
// the file AND links it to the entity's field in ONE call -- no separate relationship
// PATCH. Photos go on the `image` field (the `file` field rejects jpg/png with a 422).
// `collectionPath` is the resource collection, e.g. '/api/asset/group'.
function _extractFileId(body) {
  const d = body && body.data;
  if (!d) return undefined;
  // Multi-value field uploads can echo the field's full file list; the just-added file
  // is last. Single-resource uploads echo one object.
  if (Array.isArray(d)) return d.length ? d[d.length - 1].id : undefined;
  return d.id;
}

async function uploadFieldAttachment(client, collectionPath, uuid, field, absPath, filename, opts) {
  opts = opts || {};
  const logger = opts.logger;
  try {
    await fs.promises.access(absPath, fs.constants.R_OK);
  } catch (e) {
    if (logger && logger.warn) {
      logger.warn(`[farmos] attachment missing, skipping: ${absPath}`);
    }
    return { ok: false, reason: 'attachment_missing', skipped: true, path: absPath };
  }
  let bytes;
  try {
    bytes = await fs.promises.readFile(absPath);
  } catch (e) {
    return { ok: false, reason: 'read_failed', error: e.message, path: absPath };
  }
  const fn = filename || path.basename(absPath);
  const url = `${collectionPath}/${uuid}/${field}`;
  const r = await client.postBinary(url, bytes, { filename: fn, timeoutMs: opts.timeoutMs || 30000 });
  if (r.ok) {
    return { ok: true, fileId: _extractFileId(r.body) };
  }
  return { ok: false, reason: 'http_' + (r.status || 'network'), http_status: r.status };
}

async function uploadFieldAttachments(client, collectionPath, uuid, field, paths, opts) {
  const fileIds = [];
  const skipped = [];
  const failed = [];
  for (const p of paths || []) {
    const r = await uploadFieldAttachment(client, collectionPath, uuid, field, p, null, opts);
    if (r.ok) fileIds.push(r.fileId);
    else if (r.skipped) skipped.push(p);
    else failed.push({ path: p, reason: r.reason });
  }
  return { fileIds, skipped, failed };
}

module.exports = {
  uploadAttachment,
  uploadAttachments,
  uploadFieldAttachment,
  uploadFieldAttachments,
};
