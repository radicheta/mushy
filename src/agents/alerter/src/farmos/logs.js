'use strict';

// Phase 40 D-03 / D-03c: B7 log creation. Native types only (C5):
// seeding | activity | input | observation | harvest. Any other log_type
// throws UnsupportedLogTypeError BEFORE any farmOS call (commit-router catches).

const LOG_TYPES = ['seeding', 'activity', 'input', 'observation', 'harvest'];

class UnsupportedLogTypeError extends Error {
  constructor(logType) {
    super('unsupported_log_type:' + logType);
    this.name = 'UnsupportedLogTypeError';
    this.logType = logType;
  }
}

async function createLog(client, logType, opts) {
  if (!LOG_TYPES.includes(logType)) {
    throw new UnsupportedLogTypeError(logType);
  }
  const { name, timestamp, assetIds = [], fileIds = [], notes = '', draftId } = opts;
  const noteTrailer = (notes ? notes + '\n' : '') + 'mushy:draft:' + draftId;
  const payload = {
    data: {
      type: 'log--' + logType,
      attributes: {
        name,
        timestamp: Math.floor(timestamp),
        status: 'done',
        notes: { value: noteTrailer, format: 'plain_text' },
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
  const r = await client.post('/api/log/' + logType, payload);
  if (!r.ok) {
    return { ok: false, reason: 'http_' + (r.status || 'network'), http_status: r.status };
  }
  const logId = r.body && r.body.data && r.body.data.id;
  return { ok: true, logId, http_status: r.status };
}

module.exports = { LOG_TYPES, UnsupportedLogTypeError, createLog };
