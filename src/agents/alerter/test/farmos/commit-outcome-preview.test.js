'use strict';

// Phase 45 Plan 02: snapshot tests pinning the 10 (5 log_types x 2 outcomes)
// + 3 farm-level no-target ack templates = 13 templates total, plus style-lock
// loop test (no em-dash / no en-dash), plus reasonMap fallback test, plus
// no-name greeting test.

const {
  renderOutcomeAck,
  reasonMap,
  reasonFor,
} = require('../../src/farmos/commit-outcome-preview');

function row(overrides) {
  return Object.assign(
    {
      id: 'abcdef1234',
      sender_e164: '+59891000001',
      sender_name: 'Santi',
      log_type: 'seeding',
      target: '260512_SHI_4',
    },
    overrides || {}
  );
}

// 13 fixtures, each is [name, draftRow, options]. The 5 failure rows
// intentionally use 5 different reason codes to exercise the map.
const FIXTURES = [
  // 5 success-with-target (one per log_type)
  ['success: seeding with target', row({ log_type: 'seeding', target: '260512_SHI_4' }),
    { outcome: 'success', farmosLink: 'https://farmos.example/log/1001' }],
  ['success: activity with target', row({ sender_name: 'Vikki', log_type: 'activity', target: '260512_SHI_4' }),
    { outcome: 'success', farmosLink: 'https://farmos.example/log/1002' }],
  ['success: input with target', row({ sender_name: 'Selina', log_type: 'input', target: '260512_SHI_4' }),
    { outcome: 'success', farmosLink: 'https://farmos.example/log/1003' }],
  ['success: observation with target', row({ log_type: 'observation', target: '260512_SHI_4' }),
    { outcome: 'success', farmosLink: 'https://farmos.example/log/1004' }],
  ['success: harvest with target', row({ log_type: 'harvest', target: 'H260520_SHI_A' }),
    { outcome: 'success', farmosLink: 'https://farmos.example/log/1005' }],

  // 5 failed-with-reason (one per log_type, 5 different reason codes)
  ['failed: seeding / schema_invalid', row({ log_type: 'seeding', target: '260512_SHI_4' }),
    { outcome: 'failed', reason: 'schema_invalid' }],
  ['failed: activity / no_target_asset_for_activity', row({ sender_name: 'Vikki', log_type: 'activity', target: null }),
    { outcome: 'failed', reason: 'no_target_asset_for_activity' }],
  ['failed: input / taxonomy_term_missing', row({ log_type: 'input', target: '260512_SHI_4' }),
    { outcome: 'failed', reason: 'taxonomy_term_missing' }],
  ['failed: observation / observation_requires_target', row({ sender_name: 'Vikki', log_type: 'observation', target: null }),
    { outcome: 'failed', reason: 'observation_requires_target' }],
  ['failed: harvest / duplicate_log', row({ log_type: 'harvest', target: 'H260520_SHI_A' }),
    { outcome: 'failed', reason: 'duplicate_log' }],

  // 3 farm-level no-target success variants (observation / activity / input)
  ['success no-target: observation farm-level', row({ sender_name: 'Vikki', log_type: 'observation', target: null }),
    { outcome: 'success' }],
  ['success no-target: activity farm-level', row({ log_type: 'activity', target: null }),
    { outcome: 'success' }],
  ['success no-target: input farm-level', row({ sender_name: 'Selina', log_type: 'input', target: null }),
    { outcome: 'success' }],
];

describe('renderOutcomeAck (Phase 45 Plan 02)', () => {
  describe('13 template snapshots', () => {
    for (const [name, draftRow, options] of FIXTURES) {
      it(name, () => {
        const out = renderOutcomeAck(draftRow, options);
        expect(out).toMatchSnapshot();
      });
    }
  });

  describe('Style locks', () => {
    it('no em-dash (\\u2014) in any rendered output across all 13 fixtures', () => {
      for (const [, draftRow, options] of FIXTURES) {
        const out = renderOutcomeAck(draftRow, options);
        expect(out).not.toMatch(/—/);
      }
    });

    it('no en-dash (\\u2013) in any rendered output across all 13 fixtures', () => {
      for (const [, draftRow, options] of FIXTURES) {
        const out = renderOutcomeAck(draftRow, options);
        expect(out).not.toMatch(/–/);
      }
    });

    it('numeric target is rendered via fmtNum (1 decimal, strip .0)', () => {
      // target=7 should render as "7", not "7.0". Confirms fmtNum is on the path.
      const out = renderOutcomeAck(
        row({ log_type: 'harvest', target: 7 }),
        { outcome: 'success', farmosLink: 'https://farmos.example/log/9' }
      );
      expect(out).toContain(' for 7.');
      expect(out).not.toContain(' for 7.0');
    });

    it('numeric target with decimal rounds via fmtNum', () => {
      const out = renderOutcomeAck(
        row({ log_type: 'harvest', target: 12.34 }),
        { outcome: 'success', farmosLink: 'https://farmos.example/log/10' }
      );
      expect(out).toContain(' for 12.3.');
    });
  });

  describe('reasonMap fallback', () => {
    it('all 8 reason codes are present in reasonMap', () => {
      const expected = [
        'observation_requires_target',
        'no_target_asset_for_activity',
        'asset_not_found',
        'duplicate_log',
        'farmos_unreachable',
        'schema_invalid',
        'taxonomy_term_missing',
        'generic_validation_error',
      ];
      for (const code of expected) {
        expect(reasonMap[code]).toBeDefined();
        expect(typeof reasonMap[code]).toBe('string');
      }
    });

    it('reasonFor(unknown_code) falls back to generic_validation_error phrasing', () => {
      const fallback = reasonFor('totally_unknown_code');
      expect(fallback).toBe(reasonMap.generic_validation_error);
      expect(fallback).not.toBe('totally_unknown_code');
    });

    it('unknown reason code in failed render uses fallback phrasing, never bare code', () => {
      const out = renderOutcomeAck(
        row({ log_type: 'observation', target: null }),
        { outcome: 'failed', reason: 'some_brand_new_code' }
      );
      expect(out).toContain(reasonMap.generic_validation_error);
      expect(out).not.toContain('some_brand_new_code');
    });

    it('missing reason (undefined) falls back to generic_validation_error', () => {
      const out = renderOutcomeAck(
        row({ log_type: 'seeding' }),
        { outcome: 'failed' }
      );
      expect(out).toContain(reasonMap.generic_validation_error);
    });
  });

  describe('Named address', () => {
    it('omits greeting when sender_name is undefined; never emits "undefined" or leading comma', () => {
      const out = renderOutcomeAck(
        { log_type: 'seeding', target: '260512_SHI_4', sender_name: undefined },
        { outcome: 'success', farmosLink: 'https://farmos.example/log/1' }
      );
      expect(out).not.toMatch(/undefined/);
      expect(out.startsWith(', ')).toBe(false);
      expect(out.startsWith('Hi ,')).toBe(false);
      expect(out.startsWith('saved')).toBe(true);
    });

    it('omits greeting when sender_name is empty string', () => {
      const out = renderOutcomeAck(
        { log_type: 'seeding', target: '260512_SHI_4', sender_name: '' },
        { outcome: 'success', farmosLink: 'https://farmos.example/log/1' }
      );
      expect(out.startsWith('Hi')).toBe(false);
      expect(out.startsWith('saved')).toBe(true);
    });

    it('uses named greeting when sender_name is present', () => {
      const out = renderOutcomeAck(
        row({ sender_name: 'Don Santiago' }),
        { outcome: 'success', farmosLink: 'https://farmos.example/log/1' }
      );
      expect(out.startsWith('Hi Don Santiago, ')).toBe(true);
    });
  });
});
