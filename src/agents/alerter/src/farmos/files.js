'use strict';

// Phase 40 D-05 / D-05a / D-05b: two-step file upload (octet-stream POST -> file UUID).
// Skip-on-missing semantics so a deleted attachment doesn't fail the whole commit.
// No re-encoding / no thumbnailing -- bytes uploaded as-is.

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

module.exports = { uploadAttachment, uploadAttachments };
