'use strict';

// Phase 52 Plan 02: log--activity with is_group_assignment=true.
//
// Per farmos team correction (2026-05-24 design note): there is NO log--group
// bundle in stock farmOS. The canonical membership-assignment pattern is a
// log--activity with attributes.is_group_assignment=true plus relationships:
// asset[]=childIds, group[]=[sessionGroupId].
//
// CREATION-ONLY for v1.10.1 -- no upsert/merge/lookup. Duplicate calls on
// retry are acceptable (both logs reference the same children + group, no
// semantic harm). Phase 51's upsert-by-stable-identity layer (separate
// milestone) will dedupe these later.

function epochSecondsForDate(dateStr) {
  const ms = Date.parse(dateStr + 'T00:00:00Z');
  if (!Number.isFinite(ms)) return Math.floor(Date.now() / 1000);
  return Math.floor(ms / 1000);
}

async function createGroupAssignmentLog(client, opts) {
  const {
    childIds = [],
    sessionGroupId,
    eventDate,
    name,
    draftId,
    notes,
  } = opts || {};

  const noteValue = (notes ? notes + '\n' : '') + 'mushy:draft:' + draftId;
  const timestamp = epochSecondsForDate(eventDate);

  const payload = {
    data: {
      type: 'log--activity',
      attributes: {
        name,
        timestamp,
        status: 'done',
        is_group_assignment: true,
        notes: { value: noteValue, format: 'plain_text' },
      },
      relationships: {
        asset: { data: childIds.map((id) => ({ type: 'asset--fungi', id })) },
        group: { data: [{ type: 'asset--group', id: sessionGroupId }] },
      },
    },
  };

  const r = await client.post('/api/log/activity', payload);
  if (!r.ok) {
    return { ok: false, reason: 'http_' + (r.status || 'network'), http_status: r.status };
  }
  const logId = r.body && r.body.data && r.body.data.id;
  if (!logId) {
    return { ok: false, reason: 'no_log_id_in_response', http_status: r.status };
  }
  return { ok: true, logId, http_status: r.status };
}

async function deleteActivityLog(client, logId) {
  if (!logId) return { ok: false, reason: 'missing_log_id' };
  if (typeof client.delete !== 'function') {
    return { ok: false, reason: 'client_delete_unavailable' };
  }
  const r = await client.delete('/api/log/activity/' + logId);
  if (!r.ok) return { ok: false, reason: 'http_' + (r.status || 'network'), http_status: r.status };
  return { ok: true, http_status: r.status };
}

module.exports = {
  createGroupAssignmentLog,
  deleteActivityLog,
};
