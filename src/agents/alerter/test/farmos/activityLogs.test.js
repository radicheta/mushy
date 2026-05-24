'use strict';

// Phase 52 Plan 02: activityLogs.js hermetic unit tests.
//
// The single membership log per session is a log--activity with the stock
// farmOS is_group_assignment flag set true (per farmos team correction --
// there is no log--group bundle). Children + group are bound via this log.

const activityLogs = require('../../src/farmos/activityLogs');

function mockClient({ postImpl, deleteImpl } = {}) {
  return {
    post: jest.fn(postImpl || (async () => ({ ok: true, status: 201, body: { data: { id: 'act-new' } } }))),
    delete: jest.fn(deleteImpl || (async () => ({ ok: true, status: 204, body: null }))),
  };
}

describe('activityLogs.js (Phase 52 Plan 02)', () => {
  describe('createGroupAssignmentLog', () => {
    it('POSTs to /api/log/activity with type log--activity', async () => {
      const client = mockClient();
      await activityLogs.createGroupAssignmentLog(client, {
        childIds: ['c1'],
        sessionGroupId: 'g1',
        eventDate: '2026-05-22',
        name: 'inoc 2026-05-22 (1 bags)',
        draftId: 'd1',
      });
      const [path, body] = client.post.mock.calls[0];
      expect(path).toBe('/api/log/activity');
      expect(body.data.type).toBe('log--activity');
    });

    it('payload attributes.is_group_assignment === true (boolean, not 1 or "true")', async () => {
      const client = mockClient();
      await activityLogs.createGroupAssignmentLog(client, {
        childIds: ['c1', 'c2'],
        sessionGroupId: 'g1',
        eventDate: '2026-05-22',
        name: 'x',
        draftId: 'd',
      });
      const body = client.post.mock.calls[0][1];
      expect(body.data.attributes.is_group_assignment).toBe(true);
      expect(typeof body.data.attributes.is_group_assignment).toBe('boolean');
    });

    it('attributes.timestamp === Math.floor(Date.parse(eventDate+T00:00:00Z)/1000)', async () => {
      const client = mockClient();
      await activityLogs.createGroupAssignmentLog(client, {
        childIds: ['c1'],
        sessionGroupId: 'g1',
        eventDate: '2026-05-22',
        name: 'x',
        draftId: 'd',
      });
      const body = client.post.mock.calls[0][1];
      const expected = Math.floor(Date.parse('2026-05-22T00:00:00Z') / 1000);
      expect(body.data.attributes.timestamp).toBe(expected);
      expect(expected).toBe(1779408000); // sanity: 2026-05-22T00:00:00Z
    });

    it('attributes.status === "done"', async () => {
      const client = mockClient();
      await activityLogs.createGroupAssignmentLog(client, {
        childIds: ['c1'], sessionGroupId: 'g1', eventDate: '2026-05-22', name: 'x', draftId: 'd',
      });
      const body = client.post.mock.calls[0][1];
      expect(body.data.attributes.status).toBe('done');
    });

    it('attributes.name passed through verbatim', async () => {
      const client = mockClient();
      await activityLogs.createGroupAssignmentLog(client, {
        childIds: ['c1'], sessionGroupId: 'g1', eventDate: '2026-05-22',
        name: 'inoc 2026-05-22 (11 bags)', draftId: 'd',
      });
      const body = client.post.mock.calls[0][1];
      expect(body.data.attributes.name).toBe('inoc 2026-05-22 (11 bags)');
    });

    it('notes.value contains "mushy:draft:<draftId>"; notes opt precedes trailer with newline', async () => {
      const client = mockClient();
      await activityLogs.createGroupAssignmentLog(client, {
        childIds: ['c1'], sessionGroupId: 'g1', eventDate: '2026-05-22', name: 'x',
        draftId: 'd-xyz',
        notes: 'membership log',
      });
      const body = client.post.mock.calls[0][1];
      expect(body.data.attributes.notes.value).toBe('membership log\nmushy:draft:d-xyz');
      expect(body.data.attributes.notes.format).toBe('plain_text');
    });

    it('notes opt absent -> just "mushy:draft:<draftId>"', async () => {
      const client = mockClient();
      await activityLogs.createGroupAssignmentLog(client, {
        childIds: ['c1'], sessionGroupId: 'g1', eventDate: '2026-05-22', name: 'x',
        draftId: 'd-bare',
      });
      const body = client.post.mock.calls[0][1];
      expect(body.data.attributes.notes.value).toBe('mushy:draft:d-bare');
    });

    it('relationships.asset.data lists every childId as asset--fungi', async () => {
      const client = mockClient();
      const childIds = ['c1', 'c2', 'c3', 'c4'];
      await activityLogs.createGroupAssignmentLog(client, {
        childIds, sessionGroupId: 'g1', eventDate: '2026-05-22', name: 'x', draftId: 'd',
      });
      const body = client.post.mock.calls[0][1];
      expect(body.data.relationships.asset.data).toHaveLength(4);
      for (let i = 0; i < childIds.length; i++) {
        expect(body.data.relationships.asset.data[i]).toEqual({ type: 'asset--fungi', id: childIds[i] });
      }
    });

    it('relationships.group.data === [{type:asset--group, id:sessionGroupId}]', async () => {
      const client = mockClient();
      await activityLogs.createGroupAssignmentLog(client, {
        childIds: ['c1'], sessionGroupId: 'group-uuid-abc', eventDate: '2026-05-22', name: 'x', draftId: 'd',
      });
      const body = client.post.mock.calls[0][1];
      expect(body.data.relationships.group.data).toEqual([
        { type: 'asset--group', id: 'group-uuid-abc' },
      ]);
    });

    it('success returns {ok:true, logId, http_status:201}', async () => {
      const client = mockClient({
        postImpl: async () => ({ ok: true, status: 201, body: { data: { id: 'act-real-id' } } }),
      });
      const r = await activityLogs.createGroupAssignmentLog(client, {
        childIds: ['c1'], sessionGroupId: 'g1', eventDate: '2026-05-22', name: 'x', draftId: 'd',
      });
      expect(r.ok).toBe(true);
      expect(r.logId).toBe('act-real-id');
      expect(r.http_status).toBe(201);
    });

    it('POST failure returns {ok:false, reason:http_<status>, http_status}', async () => {
      const client = mockClient({
        postImpl: async () => ({ ok: false, status: 422, body: { errors: [{}] } }),
      });
      const r = await activityLogs.createGroupAssignmentLog(client, {
        childIds: ['c1'], sessionGroupId: 'g1', eventDate: '2026-05-22', name: 'x', draftId: 'd',
      });
      expect(r.ok).toBe(false);
      expect(r.reason).toBe('http_422');
      expect(r.http_status).toBe(422);
    });

    it('payload has no file relationship', async () => {
      const client = mockClient();
      await activityLogs.createGroupAssignmentLog(client, {
        childIds: ['c1'], sessionGroupId: 'g1', eventDate: '2026-05-22', name: 'x', draftId: 'd',
      });
      const body = client.post.mock.calls[0][1];
      expect(body.data.relationships.file).toBeUndefined();
    });
  });

  describe('deleteActivityLog', () => {
    it('DELETE /api/log/activity/<id> ok -> {ok:true}', async () => {
      const client = mockClient();
      const r = await activityLogs.deleteActivityLog(client, 'act-123');
      expect(r.ok).toBe(true);
      expect(r.http_status).toBe(204);
      expect(client.delete).toHaveBeenCalledWith('/api/log/activity/act-123');
    });

    it('DELETE failure -> {ok:false, reason:http_<status>}', async () => {
      const client = mockClient({
        deleteImpl: async () => ({ ok: false, status: 404, body: { errors: [{}] } }),
      });
      const r = await activityLogs.deleteActivityLog(client, 'act-gone');
      expect(r.ok).toBe(false);
      expect(r.reason).toBe('http_404');
      expect(r.http_status).toBe(404);
    });

    it('missing logId -> {ok:false, reason:missing_log_id}', async () => {
      const client = mockClient();
      const r = await activityLogs.deleteActivityLog(client, null);
      expect(r.ok).toBe(false);
      expect(r.reason).toBe('missing_log_id');
      expect(client.delete).not.toHaveBeenCalled();
    });
  });
});
