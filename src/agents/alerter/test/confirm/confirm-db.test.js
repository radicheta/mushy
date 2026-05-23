'use strict';

const confirmDb = require('../../src/confirm/confirm-db');
const { makeFakePool } = require('./fake-pool');

describe('confirm-db (Phase 39 D-07/D-07a)', () => {
  describe('initDb', () => {
    it('is idempotent -- two invocations do not throw', async () => {
      const pool = makeFakePool();
      await confirmDb.initDb(pool);
      await confirmDb.initDb(pool);
    });
  });

  describe('confirmDraft', () => {
    it('on awaiting_farmer returns rowCount=1 and emits a yes event with seq=1', async () => {
      const pool = makeFakePool();
      pool.seedDraft({ id: 'd1' });
      const r = await confirmDb.confirmDraft(pool, 'd1');
      expect(r).toEqual({ ok: true, rowCount: 1 });
      expect(pool.getDraft('d1').status).toBe('confirmed');
      const events = pool.getEvents('d1');
      expect(events).toHaveLength(1);
      expect(events[0].event).toBe('yes');
      expect(events[0].seq).toBe(1);
    });

    it('on already-confirmed returns rowCount=0 and emits NO event (D-02 idempotency)', async () => {
      const pool = makeFakePool();
      pool.seedDraft({ id: 'd1', status: 'confirmed', terminal_reason: 'farmer_yes' });
      const r = await confirmDb.confirmDraft(pool, 'd1');
      expect(r.ok).toBe(true);
      expect(r.rowCount).toBe(0);
      expect(pool.getEvents('d1')).toHaveLength(0);
    });
  });

  describe('discardDraft', () => {
    it('transitions status to discarded and emits no event', async () => {
      const pool = makeFakePool();
      pool.seedDraft({ id: 'd2' });
      const r = await confirmDb.discardDraft(pool, 'd2');
      expect(r).toEqual({ ok: true, rowCount: 1 });
      expect(pool.getDraft('d2').status).toBe('discarded');
      expect(pool.getEvents('d2')[0].event).toBe('no');
    });
  });

  describe('expireDraft', () => {
    it('reason=timeout_expired -> status expired, expired_at set, expired event', async () => {
      const pool = makeFakePool();
      pool.seedDraft({ id: 'd3' });
      const r = await confirmDb.expireDraft(pool, 'd3', 'timeout_expired');
      expect(r.rowCount).toBe(1);
      const row = pool.getDraft('d3');
      expect(row.status).toBe('expired');
      expect(row.expired_at).not.toBeNull();
      expect(pool.getEvents('d3')[0].event).toBe('expired');
    });

    it('reason=edit_cap_exceeded -> status needs_review, expired_at IS NULL, event=edit_cap_exceeded', async () => {
      const pool = makeFakePool();
      pool.seedDraft({ id: 'd4' });
      const r = await confirmDb.expireDraft(pool, 'd4', 'edit_cap_exceeded');
      expect(r.rowCount).toBe(1);
      const row = pool.getDraft('d4');
      expect(row.status).toBe('needs_review');
      expect(row.expired_at).toBeNull();
      expect(pool.getEvents('d4')[0].event).toBe('edit_cap_exceeded');
    });

    it('reason=superseded_by_newer_draft -> status expired, event=superseded', async () => {
      const pool = makeFakePool();
      pool.seedDraft({ id: 'd5' });
      const r = await confirmDb.expireDraft(pool, 'd5', 'superseded_by_newer_draft');
      expect(r.rowCount).toBe(1);
      expect(pool.getDraft('d5').status).toBe('expired');
      expect(pool.getEvents('d5')[0].event).toBe('superseded');
    });
  });

  describe('markNudgeSent', () => {
    it('twice returns rowCount=1 then rowCount=0', async () => {
      const pool = makeFakePool();
      pool.seedDraft({ id: 'd6' });
      const r1 = await confirmDb.markNudgeSent(pool, 'd6');
      expect(r1.rowCount).toBe(1);
      const r2 = await confirmDb.markNudgeSent(pool, 'd6');
      expect(r2.rowCount).toBe(0);
    });
  });

  describe('bumpEditTurn', () => {
    it('returns incremented value across three calls', async () => {
      const pool = makeFakePool();
      pool.seedDraft({ id: 'd7' });
      const r1 = await confirmDb.bumpEditTurn(pool, 'd7');
      const r2 = await confirmDb.bumpEditTurn(pool, 'd7');
      const r3 = await confirmDb.bumpEditTurn(pool, 'd7');
      expect(r1.edit_turn_count).toBe(1);
      expect(r2.edit_turn_count).toBe(2);
      expect(r3.edit_turn_count).toBe(3);
    });
  });

  describe('findAwaitingForSender', () => {
    it('returns null when no awaiting_farmer row matches', async () => {
      const pool = makeFakePool();
      const r = await confirmDb.findAwaitingForSender(pool, '+15550009999');
      expect(r).toBeNull();
    });

    it('returns the most recent updated_at row when two awaiting_farmer rows exist (D-01a defensive)', async () => {
      const pool = makeFakePool();
      const t0 = new Date(2026, 0, 1, 12, 0, 0);
      const t1 = new Date(2026, 0, 1, 12, 5, 0);
      pool.seedDraft({ id: 'old', sender_e164: '+15550001234', updated_at: t0 });
      pool.seedDraft({ id: 'new', sender_e164: '+15550001234', updated_at: t1 });
      const r = await confirmDb.findAwaitingForSender(pool, '+15550001234');
      expect(r.id).toBe('new');
    });

    // Phase 45 Plan 04 follow-on (from Plan 03 hand-off):
    // EDIT-from-commit_failed (Plan 03 Option X) requires receive-loop lookup
    // to surface commit_failed drafts. Without this, the wired transition is
    // unreachable at runtime from a real Signal reply.
    it('returns commit_failed draft when no awaiting_farmer exists for sender (Plan 03 Option X reachability)', async () => {
      const pool = makeFakePool();
      pool.seedDraft({
        id: 'failed1',
        sender_e164: '+15550002222',
        status: 'commit_failed',
        commit_failed_reason: 'observation_requires_target',
        updated_at: new Date(2026, 0, 1, 12, 0, 0),
      });
      const r = await confirmDb.findAwaitingForSender(pool, '+15550002222');
      expect(r).not.toBeNull();
      expect(r.id).toBe('failed1');
      expect(r.status).toBe('commit_failed');
    });

    it('prefers awaiting_farmer over commit_failed when both exist for same sender', async () => {
      const pool = makeFakePool();
      const tFailedNewer = new Date(2026, 0, 1, 13, 0, 0);
      const tAwaitingOlder = new Date(2026, 0, 1, 12, 0, 0);
      pool.seedDraft({ id: 'failed-newer', sender_e164: '+15550003333', status: 'commit_failed', updated_at: tFailedNewer });
      pool.seedDraft({ id: 'awaiting-older', sender_e164: '+15550003333', status: 'awaiting_farmer', updated_at: tAwaitingOlder });
      const r = await confirmDb.findAwaitingForSender(pool, '+15550003333');
      expect(r.id).toBe('awaiting-older');
      expect(r.status).toBe('awaiting_farmer');
    });
  });

  describe('findNudgeCandidates', () => {
    it('excludes rows with nudge_sent_at set', async () => {
      const pool = makeFakePool();
      const old = new Date(pool._now().getTime() - 30 * 60 * 1000);
      pool.seedDraft({ id: 'a', updated_at: old, nudge_sent_at: null });
      pool.seedDraft({ id: 'b', updated_at: old, nudge_sent_at: pool._now() });
      const rows = await confirmDb.findNudgeCandidates(pool, 24);
      const ids = rows.map((r) => r.id);
      expect(ids).toContain('a');
      expect(ids).not.toContain('b');
    });
  });

  describe('findExpireCandidates', () => {
    it('includes only awaiting_farmer rows older than threshold; pending excluded', async () => {
      const pool = makeFakePool();
      const old = new Date(pool._now().getTime() - 40 * 60 * 1000);
      pool.seedDraft({ id: 'a', updated_at: old, status: 'awaiting_farmer' });
      pool.seedDraft({ id: 'b', updated_at: old, status: 'pending' });
      pool.seedDraft({ id: 'c', updated_at: pool._now(), status: 'awaiting_farmer' });
      const rows = await confirmDb.findExpireCandidates(pool, 30);
      const ids = rows.map((r) => r.id);
      expect(ids).toContain('a');
      expect(ids).not.toContain('b');
      expect(ids).not.toContain('c');
    });
  });

  describe('signal_draft_event seq', () => {
    it('is per-draft monotonic across two drafts', async () => {
      const pool = makeFakePool();
      pool.seedDraft({ id: 'd-a' });
      pool.seedDraft({ id: 'd-b' });
      await confirmDb.appendEventViaPool(pool, 'd-a', 'preview_sent', null);
      await confirmDb.appendEventViaPool(pool, 'd-a', 'nudge_sent', null);
      await confirmDb.appendEventViaPool(pool, 'd-b', 'preview_sent', null);
      const seqsA = pool.getEvents('d-a').map((e) => e.seq);
      const seqsB = pool.getEvents('d-b').map((e) => e.seq);
      expect(seqsA).toEqual([1, 2]);
      expect(seqsB).toEqual([1]);
    });
  });

  describe('appendEventViaPool', () => {
    it('returns the inserted seq', async () => {
      const pool = makeFakePool();
      pool.seedDraft({ id: 'd9' });
      const r1 = await confirmDb.appendEventViaPool(pool, 'd9', 'preview_sent', { hi: 1 });
      expect(r1).toEqual({ ok: true, seq: 1 });
      const r2 = await confirmDb.appendEventViaPool(pool, 'd9', 'edit', { ok: true });
      expect(r2).toEqual({ ok: true, seq: 2 });
    });
  });
});
