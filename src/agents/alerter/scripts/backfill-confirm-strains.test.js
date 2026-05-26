'use strict';

// Phase 54.1 Plan 02 Task 3: backfill-confirm-strains.js follow-up pass.
// Hermetic unit tests -- no real DB, no real farmOS client.

const fs = require('fs');
const path = require('path');
const os = require('os');

const {
  parseStrainReply,
  applyStrainConfirmations,
  main,
} = require('./backfill-confirm-strains');

// Curated set matching tenants/mossrock/strains.yaml (14 codes).
const CURATED = ['SHI', 'SH2', 'KOY', 'MAI', 'MALI', 'KOS', 'DT', 'CAS', 'CAZ', 'WIN', 'ALM', 'MOR', 'BP', 'LIMA'];

// ============================================================================
// parseStrainReply
// ============================================================================

describe('parseStrainReply', () => {
  test('NEW <code>: goes into mint array', () => {
    const r = parseStrainReply('NEW LIM');
    expect(r.mint).toContain('LIM');
    expect(Object.keys(r.remap)).toHaveLength(0);
  });

  test('NEW <code> case-normalized to uppercase', () => {
    const r = parseStrainReply('new lim');
    expect(r.mint).toContain('LIM');
  });

  test('<bad>=<good>: goes into remap', () => {
    const r = parseStrainReply('SHITAKE=SHI');
    expect(r.remap['SHITAKE']).toBe('SHI');
    expect(r.mint).toHaveLength(0);
  });

  test('combined: "NEW LIM; SHITAKE=SHI"', () => {
    const r = parseStrainReply('NEW LIM; SHITAKE=SHI');
    expect(r.mint).toContain('LIM');
    expect(r.remap['SHITAKE']).toBe('SHI');
  });

  test('case-normalizes remap tokens', () => {
    const r = parseStrainReply('shitake=shi');
    expect(r.remap['SHITAKE']).toBe('SHI');
  });

  test('unrecognized tokens ignored (no crash)', () => {
    const r = parseStrainReply('garbage junk 123');
    expect(r.mint).toHaveLength(0);
    expect(Object.keys(r.remap)).toHaveLength(0);
  });

  test('empty reply: empty mint and remap', () => {
    const r = parseStrainReply('');
    expect(r.mint).toHaveLength(0);
    expect(Object.keys(r.remap)).toHaveLength(0);
  });
});

// ============================================================================
// applyStrainConfirmations
// ============================================================================

describe('applyStrainConfirmations', () => {
  // Helper: build pending object matching the structure written by backfill-notebook.
  function makePending(unknowns) {
    return { runId: 'test-run', unknowns };
  }

  test('confirmed-new code: ensureFungiTypeUuid called with create:true, commit called with createMissingFungiType:true', async () => {
    const pending = makePending([
      { code: 'LIM', nearest: 'LIMA', draftIds: ['d1'] },
    ]);
    const parsed = { mint: ['LIM'], remap: {} };

    // Held draft (needs_review, strain=LIM)
    const heldDraft = { id: 'd1', log_type: 'seeding', draft_json: { species_code: 'LIM' } };

    const ensureFungiTypeUuid = jest.fn().mockResolvedValue({ ok: true, uuid: 'uuid-1' });
    const fungiTypeCache = { ensureFungiTypeUuid };

    const extractionDb = {
      getDraftById: jest.fn().mockResolvedValue(heldDraft),
      updateDraftStatus: jest.fn().mockResolvedValue({ ok: true }),
    };

    const commitRouter = {
      commit: jest.fn().mockResolvedValue({ ok: true, asset_ids: ['a1'], log_ids: ['l1'] }),
    };

    const result = await applyStrainConfirmations({
      pending,
      parsed,
      client: {},
      pool: {},
      extractionDb,
      commitRouter,
      curatedStrains: CURATED,
      fungiTypeCache,
    });

    // ensureFungiTypeUuid must be called with create:true for LIM
    expect(ensureFungiTypeUuid).toHaveBeenCalledWith({}, 'LIM', { create: true });
    // commit called with createMissingFungiType:true
    expect(commitRouter.commit).toHaveBeenCalledTimes(1);
    const commitCtx = commitRouter.commit.mock.calls[0][2];
    expect(commitCtx.createMissingFungiType).toBe(true);
    // draft flipped to confirmed
    expect(extractionDb.updateDraftStatus).toHaveBeenCalledWith({}, 'd1', 'confirmed', {
      needs_review_reason: 'strain_confirmed_backfill',
    });
    expect(result.committed).toContain('d1');
  });

  test('remap correction: draft strain rewritten to canonical, NO mint, commit with createMissingFungiType:true', async () => {
    const pending = makePending([
      { code: 'SHITAKE', nearest: 'SHI', draftIds: ['d2'] },
    ]);
    const parsed = { mint: [], remap: { SHITAKE: 'SHI' } };

    const heldDraft = { id: 'd2', log_type: 'seeding', draft_json: { species_code: 'SHITAKE' } };

    const ensureFungiTypeUuid = jest.fn().mockResolvedValue({ ok: true, uuid: 'uuid-2' });
    const fungiTypeCache = { ensureFungiTypeUuid };

    const extractionDb = {
      getDraftById: jest.fn().mockResolvedValue(heldDraft),
      updateDraftStatus: jest.fn().mockResolvedValue({ ok: true }),
    };

    const commitRouter = {
      commit: jest.fn().mockResolvedValue({ ok: true, asset_ids: [], log_ids: [] }),
    };

    await applyStrainConfirmations({
      pending,
      parsed,
      client: {},
      pool: {},
      extractionDb,
      commitRouter,
      curatedStrains: CURATED,
      fungiTypeCache,
    });

    // No mint for remap corrections
    expect(ensureFungiTypeUuid).not.toHaveBeenCalled();
    // commit still called with createMissingFungiType:true
    expect(commitRouter.commit).toHaveBeenCalledTimes(1);
    expect(commitRouter.commit.mock.calls[0][2].createMissingFungiType).toBe(true);
    // draft_json updated: species_code should be SHI (the canonical code)
    const updateCall = extractionDb.updateDraftStatus.mock.calls[0];
    expect(updateCall[2]).toBe('confirmed');
  });

  test('anti-injection: code in reply but NOT in pending is ignored -- no mint, no commit for it', async () => {
    // pending only has LIM; reply claims NEW POY (not held)
    const pending = makePending([
      { code: 'LIM', nearest: 'LIMA', draftIds: ['d1'] },
    ]);
    const parsed = { mint: ['LIM', 'POY'], remap: {} };  // POY is injected

    const heldDraft = { id: 'd1', log_type: 'seeding', draft_json: { species_code: 'LIM' } };

    const ensureFungiTypeUuid = jest.fn().mockResolvedValue({ ok: true, uuid: 'uuid-lim' });
    const fungiTypeCache = { ensureFungiTypeUuid };

    const extractionDb = {
      getDraftById: jest.fn().mockResolvedValue(heldDraft),
      updateDraftStatus: jest.fn().mockResolvedValue({ ok: true }),
    };

    const commitRouter = {
      commit: jest.fn().mockResolvedValue({ ok: true, asset_ids: [], log_ids: [] }),
    };

    await applyStrainConfirmations({
      pending,
      parsed,
      client: {},
      pool: {},
      extractionDb,
      commitRouter,
      curatedStrains: CURATED,
      fungiTypeCache,
    });

    // ensureFungiTypeUuid called ONLY for LIM (which is in pending), NOT for POY
    const mintedCodes = ensureFungiTypeUuid.mock.calls.map((c) => c[1]);
    expect(mintedCodes).toContain('LIM');
    expect(mintedCodes).not.toContain('POY');
  });

  test('non-curated remap target rejected: no draft rewrite, no commit for that draft', async () => {
    // SHITAKE=BOGUS where BOGUS is not in CURATED -> rejection
    const pending = makePending([
      { code: 'SHITAKE', nearest: 'SHI', draftIds: ['d3'] },
    ]);
    const parsed = { mint: [], remap: { SHITAKE: 'BOGUS' } };

    const heldDraft = { id: 'd3', log_type: 'seeding', draft_json: { species_code: 'SHITAKE' } };

    const ensureFungiTypeUuid = jest.fn();
    const fungiTypeCache = { ensureFungiTypeUuid };

    const extractionDb = {
      getDraftById: jest.fn().mockResolvedValue(heldDraft),
      updateDraftStatus: jest.fn().mockResolvedValue({ ok: true }),
    };

    const commitRouter = {
      commit: jest.fn().mockResolvedValue({ ok: true, asset_ids: [], log_ids: [] }),
    };

    const result = await applyStrainConfirmations({
      pending,
      parsed,
      client: {},
      pool: {},
      extractionDb,
      commitRouter,
      curatedStrains: CURATED,
      fungiTypeCache,
    });

    // No commit for the draft with a rejected remap target
    expect(commitRouter.commit).not.toHaveBeenCalled();
    expect(ensureFungiTypeUuid).not.toHaveBeenCalled();
    expect(result.rejected).toContain('SHITAKE');
  });
});

// ============================================================================
// main: guards
// ============================================================================

describe('main (backfill-confirm-strains)', () => {
  let tmpDir;
  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'bcs-'));
  });

  test('prod-guard: exits 3 when FARMOS_URL contains :8082', async () => {
    const logger = { log: () => {}, warn: () => {}, error: jest.fn() };
    const r = await main(
      ['--run-id=x', '--farmer=santi', '--reply=NEW SHI'],
      { env: { FARMOS_URL: 'http://farm:8082', DATABASE_URL: 'x' }, logger }
    );
    expect(r.code).toBe(3);
  });

  test('farmer-gate: exits 4 when farmer is not santi', async () => {
    const logger = { log: () => {}, warn: () => {}, error: jest.fn() };
    const r = await main(
      ['--run-id=x', '--farmer=vikki', '--reply=NEW SHI'],
      { env: { FARMOS_URL: 'http://farm:18080', DATABASE_URL: 'x' }, logger }
    );
    expect(r.code).toBe(4);
  });

  test('missing --run-id exits 5', async () => {
    const logger = { log: () => {}, warn: () => {}, error: jest.fn() };
    const r = await main(
      ['--farmer=santi', '--reply=NEW SHI'],
      { env: { FARMOS_URL: 'http://farm:18080', DATABASE_URL: 'x' }, logger }
    );
    expect(r.code).toBe(5);
  });

  test('missing pending file exits 7', async () => {
    const logger = { log: () => {}, warn: () => {}, error: jest.fn() };
    const cwd = process.cwd();
    process.chdir(tmpDir);
    try {
      const r = await main(
        ['--run-id=no-such-run', '--farmer=santi', '--reply=NEW SHI'],
        {
          env: { FARMOS_URL: 'http://farm:18080', DATABASE_URL: 'x' },
          logger,
        }
      );
      expect(r.code).toBe(7);
    } finally {
      process.chdir(cwd);
    }
  });
});
