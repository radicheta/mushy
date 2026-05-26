'use strict';

const { resolveStrain, nearestKnown } = require('../../src/farmos/strain-resolver');

// The 14 curated codes from tenants/mossrock/strains.yaml.
// Seeded inline so the test is hermetic and does not load config.
const CURATED = ['SHI', 'SH2', 'KOY', 'MAI', 'MALI', 'KOS', 'DT', 'CAS', 'CAZ', 'WIN', 'ALM', 'MOR', 'BP', 'LIMA'];

describe('resolveStrain -- exact-match against curated set', () => {
  describe('known codes (all 14 curated codes resolve known:true)', () => {
    it.each(CURATED)('resolveStrain(%s) -> known:true', (code) => {
      const r = resolveStrain(code, CURATED);
      expect(r.known).toBe(true);
      expect(r.code).toBe(code);
    });
  });

  describe('case/whitespace insensitivity', () => {
    it("lowercase 'shi' resolves known:true for SHI", () => {
      const r = resolveStrain('shi', CURATED);
      expect(r.known).toBe(true);
      expect(r.code).toBe('SHI');
    });

    it("' SHI ' (padded) resolves known:true for SHI", () => {
      const r = resolveStrain(' SHI ', CURATED);
      expect(r.known).toBe(true);
      expect(r.code).toBe('SHI');
    });
  });

  describe('Cycle-1 variant codes -- all must resolve known:false', () => {
    it('LIM (truncation of LIMA) -> known:false, nearest LIMA', () => {
      const r = resolveStrain('LIM', CURATED);
      expect(r.known).toBe(false);
      expect(r.code).toBe('LIM');
      expect(r.nearest).toBe('LIMA');
    });

    it('SHIITAKE (full name for SHI) -> known:false, nearest SHI', () => {
      const r = resolveStrain('SHIITAKE', CURATED);
      expect(r.known).toBe(false);
      expect(r.code).toBe('SHIITAKE');
      expect(r.nearest).toBe('SHI');
    });

    it('SHITAKE (variant full name for SHI) -> known:false, nearest SHI', () => {
      const r = resolveStrain('SHITAKE', CURATED);
      expect(r.known).toBe(false);
      expect(r.code).toBe('SHITAKE');
      expect(r.nearest).toBe('SHI');
    });

    it('OYS (oyster synonym) -> known:false', () => {
      const r = resolveStrain('OYS', CURATED);
      expect(r.known).toBe(false);
      expect(r.code).toBe('OYS');
      expect(r.nearest).toBeDefined();
    });

    it('KOY is in the curated set -- resolves known:true (not a variant for POY)', () => {
      // KOY IS one of the 14 curated codes; it is not a POY variant in the
      // exact-match model.  This test documents the design decision explicitly.
      const r = resolveStrain('KOY', CURATED);
      expect(r.known).toBe(true);
      expect(r.code).toBe('KOY');
    });

    it('POY (CSV ground-truth code NOT in curated 14) -> known:false', () => {
      const r = resolveStrain('POY', CURATED);
      expect(r.known).toBe(false);
      expect(r.code).toBe('POY');
      expect(r.nearest).toBeDefined();
    });
  });

  describe('edge cases', () => {
    it('null input -> known:false, code:null, no throw', () => {
      const r = resolveStrain(null, CURATED);
      expect(r.known).toBe(false);
      expect(r.code).toBeNull();
    });

    it('empty string -> known:false, code:null, no throw', () => {
      const r = resolveStrain('', CURATED);
      expect(r.known).toBe(false);
      expect(r.code).toBeNull();
    });

    it('non-string (number) -> known:false, code:null, no throw', () => {
      const r = resolveStrain(42, CURATED);
      expect(r.known).toBe(false);
      expect(r.code).toBeNull();
    });

    it('unknown code with empty curated set -> known:false, no nearest', () => {
      const r = resolveStrain('POY', []);
      expect(r.known).toBe(false);
      expect(r.nearest).toBeUndefined();
    });

    it('unknown code gets nearest field; known code does not', () => {
      const unknown = resolveStrain('LIM', CURATED);
      expect('nearest' in unknown).toBe(true);
      const known = resolveStrain('LIMA', CURATED);
      expect('nearest' in known).toBe(false);
    });
  });
});

describe('nearestKnown -- Levenshtein nearest-neighbor (display only)', () => {
  it('LIM -> LIMA (1 insertion)', () => {
    expect(nearestKnown('LIM', CURATED)).toBe('LIMA');
  });

  it('SHIITAKE -> SHI (smallest distance; not SHITAKE/SHITAKE in curated)', () => {
    expect(nearestKnown('SHIITAKE', CURATED)).toBe('SHI');
  });

  it('returns null for empty curated set', () => {
    expect(nearestKnown('LIM', [])).toBeNull();
  });

  it('tie-break by array order -- first minimum wins', () => {
    // 'SHI' and 'SH2' are both distance 1 from 'SHA'; SHI is first in CURATED
    expect(nearestKnown('SHA', CURATED)).toBe('SHI');
  });
});
