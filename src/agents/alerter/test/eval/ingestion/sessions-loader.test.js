'use strict';

// Phase 49 Plan 01: sessions-loader iterates test/eval/ingestion/fixtures/sessions/
// and yields one normalized entry per subdir containing ground-truth.json + MANIFEST.md.

const fs = require('fs');
const path = require('path');
const os = require('os');
const { loadSessionsCorpus } = require('./sessions-loader');

const FIXTURE_ROOT = path.resolve(__dirname, 'fixtures/sessions');

describe('sessions-loader', () => {
  describe('loadSessionsCorpus against committed May-22 fixture', () => {
    test('returns at least one entry', () => {
      const out = loadSessionsCorpus(FIXTURE_ROOT, { logger: { warn: () => {} } });
      expect(Array.isArray(out)).toBe(true);
      expect(out.length).toBeGreaterThanOrEqual(1);
    });

    test('May-22 entry has expected name + regression_guard:true', () => {
      const out = loadSessionsCorpus(FIXTURE_ROOT, { logger: { warn: () => {} } });
      const may22 = out.find((e) => e.name === '2026-05-22_inoc_santi');
      expect(may22).toBeTruthy();
      expect(may22.manifest).toBeTruthy();
      expect(may22.manifest.regression_guard).toBe(true);
      expect(may22.manifest.capture_date).toBe('2026-05-22');
    });

    test('May-22 ground-truth has 5 groups + 11 children, event_date 2026-05-22', () => {
      const out = loadSessionsCorpus(FIXTURE_ROOT, { logger: { warn: () => {} } });
      const may22 = out.find((e) => e.name === '2026-05-22_inoc_santi');
      expect(may22.groundTruth.type).toBe('seeding_session');
      expect(may22.groundTruth.event_date).toBe('2026-05-22');
      expect(may22.groundTruth.groups).toHaveLength(5);
      const totalChildren = may22.groundTruth.groups
        .reduce((n, g) => n + g.child_block_names.value.length, 0);
      expect(totalChildren).toBe(11);

      // The 11 expected child block names (sorted for stability).
      const allChildren = may22.groundTruth.groups
        .flatMap((g) => g.child_block_names.value)
        .sort();
      expect(allChildren).toEqual([
        '260522_KOY_10',
        '260522_KOY_11',
        '260522_KOY_4',
        '260522_KOY_5',
        '260522_KOY_6',
        '260522_KOY_7',
        '260522_KOY_8',
        '260522_KOY_9',
        '260522_SHI_1',
        '260522_SHI_2',
        '260522_SHI_3',
      ]);
    });

    test('May-22 entry surfaces audioPath + photoPath (symlinks resolve to prod corpus)', () => {
      const out = loadSessionsCorpus(FIXTURE_ROOT, { logger: { warn: () => {} } });
      const may22 = out.find((e) => e.name === '2026-05-22_inoc_santi');
      expect(may22.audioPath).toBeTruthy();
      expect(may22.audioPath).toMatch(/audio\.m4a$/);
      expect(may22.photoPath).toBeTruthy();
      expect(may22.photoPath).toMatch(/paper-log\.jpg$/);
    });

    test('parent + species set as expected on every group', () => {
      const out = loadSessionsCorpus(FIXTURE_ROOT, { logger: { warn: () => {} } });
      const may22 = out.find((e) => e.name === '2026-05-22_inoc_santi');
      const parents = may22.groundTruth.groups.map((g) => g.parent.value).sort();
      expect(parents).toEqual([
        '260118_KOY_12',
        '260118_SHI_23',
        '260118_SHI_26',
        '260304_SHI_5',
        '260425_KOY_4',
      ]);
      const species = new Set(may22.groundTruth.groups.map((g) => g.species.value));
      expect(species).toEqual(new Set(['SHI', 'KOY']));
    });
  });

  describe('loadSessionsCorpus error handling', () => {
    test('returns [] when dir does not exist (warn, no throw)', () => {
      const warn = jest.fn();
      const out = loadSessionsCorpus('/no/such/dir/here', { logger: { warn } });
      expect(out).toEqual([]);
      expect(warn).toHaveBeenCalled();
    });

    test('skips subdir missing ground-truth.json with a warning', () => {
      const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'sessions-loader-test-'));
      const sub = path.join(tmp, 'busted-fixture');
      fs.mkdirSync(sub);
      // No ground-truth.json, no MANIFEST.md
      const warn = jest.fn();
      const out = loadSessionsCorpus(tmp, { logger: { warn } });
      expect(out).toEqual([]);
      expect(warn).toHaveBeenCalled();
      fs.rmSync(tmp, { recursive: true, force: true });
    });

    test('skips subdir missing MANIFEST.md with a warning', () => {
      const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'sessions-loader-test-'));
      const sub = path.join(tmp, 'half-fixture');
      fs.mkdirSync(sub);
      fs.writeFileSync(path.join(sub, 'ground-truth.json'), JSON.stringify({ type: 'x' }));
      const warn = jest.fn();
      const out = loadSessionsCorpus(tmp, { logger: { warn } });
      expect(out).toEqual([]);
      expect(warn).toHaveBeenCalled();
      fs.rmSync(tmp, { recursive: true, force: true });
    });
  });
});
