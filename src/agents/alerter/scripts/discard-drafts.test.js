'use strict';

const { parseArgs, discardDrafts } = require('./discard-drafts');

function makeLogger() {
  const lines = [];
  return {
    lines,
    info: (m) => lines.push(['info', m]),
    warn: (m) => lines.push(['warn', m]),
  };
}

// In-memory pool stub modelling just the parts of signal_draft this script
// touches: id, status, discarded_reason, discarded_at, log_type, sender_e164,
// updated_at. Recognizes the three SQL shapes the script issues: BEGIN/COMMIT/
// ROLLBACK, the SELECT classifier, and the UPDATE ... RETURNING.
function makePool(initialRows = []) {
  const rows = initialRows.map((r) => Object.assign({}, r));
  const calls = [];

  function query(sql, params) {
    calls.push({ sql, params });
    const s = sql.replace(/\s+/g, ' ').trim();
    if (/^BEGIN$|^COMMIT$|^ROLLBACK$/i.test(s)) {
      return Promise.resolve({ rows: [], rowCount: 0 });
    }
    if (/^SELECT id, status, log_type, sender_e164 FROM signal_draft/i.test(s)) {
      const ids = params[0];
      const matched = rows
        .filter((r) => ids.includes(r.id))
        .map((r) => ({
          id: r.id,
          status: r.status,
          log_type: r.log_type || null,
          sender_e164: r.sender_e164 || null,
        }));
      return Promise.resolve({ rows: matched, rowCount: matched.length });
    }
    if (/^UPDATE signal_draft/i.test(s)) {
      const reason = params[0];
      const ids = params[1];
      const updated = [];
      for (const r of rows) {
        if (ids.includes(r.id) && r.status !== 'discarded') {
          r.status = 'discarded';
          r.discarded_reason = reason;
          r.discarded_at = new Date();
          r.updated_at = new Date();
          updated.push({
            id: r.id,
            status: r.status,
            discarded_reason: r.discarded_reason,
            discarded_at: r.discarded_at,
          });
        }
      }
      return Promise.resolve({ rows: updated, rowCount: updated.length });
    }
    return Promise.reject(new Error(`unexpected sql: ${s}`));
  }

  return { query, calls, _rows: rows };
}

describe('discard-drafts parseArgs', () => {
  test('1. happy path: multiple --uuid + --reason + --apply', () => {
    const args = parseArgs([
      'node', 'discard-drafts.js',
      '--uuid', 'a', '--uuid', 'b',
      '--reason', 'wrong session',
      '--apply',
    ]);
    expect(args).toEqual({
      uuids: ['a', 'b'],
      reason: 'wrong session',
      apply: true,
      help: false,
    });
  });

  test('2. missing --reason throws usage error', () => {
    expect(() => parseArgs([
      'node', 'discard-drafts.js', '--uuid', 'a',
    ])).toThrow(/--reason/);
  });

  test('3. missing --uuid throws usage error', () => {
    expect(() => parseArgs([
      'node', 'discard-drafts.js', '--reason', 'x',
    ])).toThrow(/--uuid/);
  });

  test('4. --help returns { help: true }', () => {
    const args = parseArgs(['node', 'discard-drafts.js', '--help']);
    expect(args.help).toBe(true);
  });

  test('rejects empty --reason', () => {
    expect(() => parseArgs([
      'node', 'discard-drafts.js', '--uuid', 'a', '--reason', '',
    ])).toThrow(/--reason/);
  });

  test('rejects unknown args', () => {
    expect(() => parseArgs([
      'node', 'discard-drafts.js', '--uuid', 'a', '--reason', 'x', '--bogus',
    ])).toThrow(/unknown|--bogus/i);
  });
});

describe('discardDrafts behavior', () => {
  test('5. dry-run: classifies but does not mutate', async () => {
    const pool = makePool([
      { id: 'u1', status: 'pending', log_type: 'seeding_session', sender_e164: '+1' },
    ]);
    const logger = makeLogger();
    const r = await discardDrafts({
      pool, uuids: ['u1'], reason: 'wrong', apply: false, logger,
    });
    expect(r.dryRun).toBe(true);
    expect(r.candidates.length).toBe(1);
    expect(r.candidates[0].id).toBe('u1');
    expect(r.updated.length).toBe(0);
    // No UPDATE/BEGIN issued.
    const sqls = pool.calls.map((c) => c.sql);
    expect(sqls.some((s) => /UPDATE signal_draft/i.test(s))).toBe(false);
    expect(sqls.some((s) => /^BEGIN/i.test(s))).toBe(false);
    // Row unchanged.
    expect(pool._rows[0].status).toBe('pending');
  });

  test('6. apply: writes status=discarded + discarded_reason + discarded_at', async () => {
    const pool = makePool([
      { id: 'u1', status: 'pending', log_type: 'seeding_session', sender_e164: '+1' },
    ]);
    const logger = makeLogger();
    const r = await discardDrafts({
      pool, uuids: ['u1'], reason: 'wrong session', apply: true, logger,
    });
    expect(r.dryRun).toBe(false);
    expect(r.updated.length).toBe(1);
    expect(r.updated[0].id).toBe('u1');
    expect(r.updated[0].status).toBe('discarded');
    expect(r.updated[0].discarded_reason).toBe('wrong session');
    expect(r.updated[0].discarded_at).not.toBeNull();
    expect(pool._rows[0].status).toBe('discarded');
    // Transactional shape.
    const sqls = pool.calls.map((c) => c.sql.replace(/\s+/g, ' ').trim());
    expect(sqls).toContain('BEGIN');
    expect(sqls).toContain('COMMIT');
  });

  test('7. idempotent: re-run on already-discarded uuid is a no-op', async () => {
    const pool = makePool([
      { id: 'u1', status: 'pending', log_type: 'seeding_session', sender_e164: '+1' },
    ]);
    // First apply: discards.
    await discardDrafts({
      pool, uuids: ['u1'], reason: 'first', apply: true, logger: makeLogger(),
    });
    expect(pool._rows[0].status).toBe('discarded');
    const firstReason = pool._rows[0].discarded_reason;
    const firstAt = pool._rows[0].discarded_at;
    // Second apply: no rows updated, alreadyDiscarded has the row.
    const logger = makeLogger();
    const r = await discardDrafts({
      pool, uuids: ['u1'], reason: 'second', apply: true, logger,
    });
    expect(r.updated.length).toBe(0);
    expect(r.alreadyDiscarded.length).toBe(1);
    expect(r.alreadyDiscarded[0].id).toBe('u1');
    // Row state preserved -- the first reason still stands.
    expect(pool._rows[0].discarded_reason).toBe(firstReason);
    expect(pool._rows[0].discarded_at).toBe(firstAt);
  });

  test('8. unknown uuid: surfaces in unknown[], no error', async () => {
    const pool = makePool([]);
    const logger = makeLogger();
    const r = await discardDrafts({
      pool, uuids: ['ghost'], reason: 'x', apply: true, logger,
    });
    expect(r.unknown.length).toBe(1);
    expect(r.unknown[0]).toBe('ghost');
    expect(r.updated.length).toBe(0);
    expect(r.candidates.length).toBe(0);
  });

  test('mixed batch: candidates + already-discarded + unknown in one call', async () => {
    const pool = makePool([
      { id: 'u1', status: 'pending', log_type: 'seeding_session', sender_e164: '+1' },
      { id: 'u2', status: 'discarded', log_type: 'seeding_session', sender_e164: '+1' },
    ]);
    const r = await discardDrafts({
      pool, uuids: ['u1', 'u2', 'u3'], reason: 'mixed', apply: true, logger: makeLogger(),
    });
    expect(r.updated.map((x) => x.id)).toEqual(['u1']);
    expect(r.alreadyDiscarded.map((x) => x.id)).toEqual(['u2']);
    expect(r.unknown).toEqual(['u3']);
  });

  test('rollback on UPDATE failure', async () => {
    const pool = makePool([
      { id: 'u1', status: 'pending', log_type: 'seeding_session', sender_e164: '+1' },
    ]);
    // Override query to throw on UPDATE.
    const origQuery = pool.query;
    pool.query = (sql, params) => {
      if (/^UPDATE signal_draft/i.test(sql.replace(/\s+/g, ' ').trim())) {
        return Promise.reject(new Error('boom'));
      }
      return origQuery(sql, params);
    };
    await expect(discardDrafts({
      pool, uuids: ['u1'], reason: 'x', apply: true, logger: makeLogger(),
    })).rejects.toThrow(/boom/);
    const sqls = pool.calls.map((c) => c.sql.replace(/\s+/g, ' ').trim());
    expect(sqls).toContain('ROLLBACK');
  });
});
