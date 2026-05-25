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

  describe('attachment-failure note (no-silent-failure)', () => {
    it('success ack appends a heads-up when attachmentsFailed > 0 (count)', () => {
      const out = renderOutcomeAck(
        row({ log_type: 'observation', target: '260512_SHI_4' }),
        { outcome: 'success', attachmentsFailed: 2, farmosLink: 'https://farmos.example/log/1' }
      );
      expect(out).toContain('saved'); // base success preserved
      expect(out).toContain('2 photos did not attach');
      expect(out).toContain('re-send them');
    });

    it('singular wording + accepts the raw failed[] array', () => {
      const out = renderOutcomeAck(
        row({ log_type: 'observation', target: '260512_SHI_4' }),
        { outcome: 'success', attachmentsFailed: [{ reason: 'http_500' }] }
      );
      expect(out).toContain('1 photo did not attach');
      expect(out).toContain('re-send it');
    });

    it('no heads-up when nothing failed (clean ack unchanged)', () => {
      const out = renderOutcomeAck(
        row({ log_type: 'observation', target: '260512_SHI_4' }),
        { outcome: 'success', attachmentsFailed: 0 }
      );
      expect(out).not.toContain('did not attach');
    });

    it('failed outcome never shows an attachment note', () => {
      const out = renderOutcomeAck(
        row({ log_type: 'observation', target: null }),
        { outcome: 'failed', reason: 'observation_requires_target', attachmentsFailed: 3 }
      );
      expect(out).not.toContain('did not attach');
    });

    it('the note carries no em-dash or en-dash', () => {
      const out = renderOutcomeAck(
        row({ log_type: 'observation', target: '260512_SHI_4' }),
        { outcome: 'success', attachmentsFailed: 2 }
      );
      expect(out).not.toContain('—');
      expect(out).not.toContain('–');
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

  describe('Disambiguator (Plan 06)', () => {
    it('failed ack includes event date when draft_json.event_timestamp is present', () => {
      const out = renderOutcomeAck(
        row({
          log_type: 'observation',
          target: null,
          draft_json: { event_timestamp: '2026-05-21T15:00:00Z', notes: 'block contaminated on the back shelf' },
        }),
        { outcome: 'failed', reason: 'observation_requires_target' }
      );
      expect(out).toContain('May 21');
      expect(out).toContain('observation');
      expect(out).toContain('block contaminated on the back shelf');
    });

    it('failed ack falls back to created_at when event_timestamp absent', () => {
      const out = renderOutcomeAck(
        row({
          log_type: 'activity',
          target: null,
          created_at: '2026-05-13T12:37:00Z',
          draft_json: { name: 'sterilize' },
        }),
        { outcome: 'failed', reason: 'no_target_asset_for_activity' }
      );
      expect(out).toContain('May 13');
      expect(out).toContain('(sterilize)');
    });

    it('rejects sentinel date 1970-01-01', () => {
      const out = renderOutcomeAck(
        row({
          log_type: 'observation',
          target: null,
          draft_json: { event_timestamp: '1970-01-01T00:00:00Z', notes: 'thumbs up' },
        }),
        { outcome: 'failed', reason: 'observation_requires_target' }
      );
      expect(out).not.toMatch(/Jan 1\b/);
      expect(out).toContain('thumbs up');
    });

    it('rejects year-boundary midnight sentinel (2026-01-01T00:00:00Z)', () => {
      const out = renderOutcomeAck(
        row({
          log_type: 'observation',
          target: null,
          draft_json: { event_timestamp: '2026-01-01T00:00:00Z', notes: 'UX comment' },
        }),
        { outcome: 'failed', reason: 'observation_requires_target' }
      );
      expect(out).not.toMatch(/Jan 1\b/);
      expect(out).toContain('UX comment');
    });

    it('truncates long notes at word boundary with ellipsis', () => {
      const longNotes = 'Farmer commented at length about every single thing they observed today including detailed measurements';
      const out = renderOutcomeAck(
        row({
          log_type: 'observation',
          target: null,
          draft_json: { event_timestamp: '2026-05-21T10:00:00Z', notes: longNotes },
        }),
        { outcome: 'failed', reason: 'observation_requires_target' }
      );
      expect(out).toMatch(/\.\.\.\)/); // truncated, closes paren
      expect(out.length).toBeLessThan(200);
    });

    it('hallucinated event_timestamp (>30 days before created_at) falls back to created_at', () => {
      // Reproduces the Phase 45 Plan-06 dry-run bug: draft 0c5533f9 had
      // event_timestamp=2026-01-01T23:30:00Z but created_at=2026-05-21.
      const out = renderOutcomeAck(
        row({
          log_type: 'activity',
          target: null,
          created_at: '2026-05-21T02:33:00Z',
          draft_json: { event_timestamp: '2026-01-01T23:30:00Z', name: 'sterilize' },
        }),
        { outcome: 'failed', reason: 'no_target_asset_for_activity' }
      );
      expect(out).toContain('May 21');
      expect(out).not.toContain('Jan 1');
    });

    it('bare log_type fallback when no date and no summary', () => {
      const out = renderOutcomeAck(
        { log_type: 'observation', target: null, sender_name: 'Santi' },
        { outcome: 'failed', reason: 'observation_requires_target' }
      );
      // No date, no draft_json -> disambiguator collapses to label
      expect(out).toContain('about the observation:');
    });
  });

  // -------------------------------------------------------------------------
  // Phase 48 Plan 04: seeding_session ack contract
  // -------------------------------------------------------------------------
  describe('seeding_session (Phase 48 Plan 04)', () => {
    // May 22 fixture: 5 groups, 11 children total.
    function may22Draft(overrides) {
      return Object.assign(
        {
          id: 'sess1',
          sender_e164: '+59891000001',
          sender_name: 'Santi',
          log_type: 'seeding_session',
          target: null,
          created_at: '2026-05-22T15:00:00Z',
          draft_json: {
            type: 'seeding_session',
            event_date: '2026-05-22',
            groups: [
              { child_block_names: { value: ['260522_KOY_4', '260522_KOY_5', '260522_KOY_6'] } },
              { child_block_names: { value: ['260522_SHI_7', '260522_SHI_8'] } },
              { child_block_names: { value: ['260522_MAI_1', '260522_MAI_2'] } },
              { child_block_names: { value: ['260522_KOS_3', '260522_KOS_4'] } },
              { child_block_names: { value: ['260522_DT_1', '260522_DT_2'] } },
            ],
          },
        },
        overrides || {}
      );
    }

    it('Test A: success renders clean session-shaped ack (no general-farm-note boilerplate)', () => {
      const out = renderOutcomeAck(may22Draft(), { outcome: 'success' });
      // Must include date + label + counts disambiguator
      expect(out).toContain('2026-05-22');
      expect(out).toContain('Inoc session');
      expect(out).toContain('11 blocks across 5 parents');
      // Must NOT use the legacy farm-level boilerplate (would be misleading)
      expect(out).not.toContain('general farm note');
      expect(out).not.toContain("couldn't match a specific block");
      // Named greeting present
      expect(out.startsWith('Hi Santi, ')).toBe(true);
      // Clean closing: "saved {what}."
      expect(out).toMatch(/saved 2026-05-22 Inoc session \(11 blocks across 5 parents\)\.$/);
    });

    it('Test B: failed / partial_commit_failed', () => {
      const out = renderOutcomeAck(may22Draft(), { outcome: 'failed', reason: 'partial_commit_failed' });
      expect(out).toContain('about the 2026-05-22 Inoc session (11 blocks across 5 parents):');
      expect(out).toContain("couldn't save it because a write partway through failed, nothing saved");
      expect(out).toContain('Send EDIT to fix or NO to drop.');
    });

    it('Test C: failed / session_name_exhausted', () => {
      const out = renderOutcomeAck(may22Draft(), { outcome: 'failed', reason: 'session_name_exhausted' });
      expect(out).toContain('too many same-day session names already exist');
    });

    it('Test D: failed / session_fungi_type_term_missing', () => {
      const out = renderOutcomeAck(may22Draft(), { outcome: 'failed', reason: 'session_fungi_type_term_missing' });
      expect(out).toContain('farmOS session taxonomy term missing');
    });

    it('Test E: failed / unknown reason falls back to generic_validation_error phrasing', () => {
      const out = renderOutcomeAck(may22Draft(), { outcome: 'failed', reason: 'totally_unknown_session_code' });
      expect(out).toContain(reasonMap.generic_validation_error);
      expect(out).not.toContain('totally_unknown_session_code');
    });

    it('Test F: legacy seeding ack remains byte-identical (regression guard)', () => {
      // Pre-Phase-48 expected output for a seeding success ack.
      const out = renderOutcomeAck(
        {
          id: 'abcdef1234',
          sender_e164: '+59891000001',
          sender_name: 'Santi',
          log_type: 'seeding',
          target: '260512_SHI_4',
        },
        { outcome: 'success', farmosLink: 'https://farmos.example/log/1001' }
      );
      expect(out).toBe('Hi Santi, saved seeding for 260512_SHI_4. Open in farmOS: https://farmos.example/log/1001');
    });

    // Hotfix 2026-05-24: row.target is never populated by the pipeline,
    // so the renderer must derive target from draft_json.{asset_ref|qr_codes}
    // instead. Pre-hotfix, every successful observation commit (with a real
    // block match!) fell through to "general farm note" -- misleading the
    // farmer that the block wasn't matched when it actually was.
    it('hotfix-2026-05-24: success ack derives target from draft_json.asset_ref when row.target absent', () => {
      const out = renderOutcomeAck(
        {
          id: 'bb34475403',
          sender_name: 'Santi',
          log_type: 'observation',
          // NO row.target -- only draft_json.asset_ref (production shape)
          draft_json: {
            type: 'observation',
            asset_ref: '260519_DT_1',
            state: 'mycelium visible, colonization in progress',
            event_timestamp: '2026-05-19T00:00:00Z',
          },
        },
        { outcome: 'success' }
      );
      expect(out).toContain('260519_DT_1');
      expect(out).not.toContain('general farm note');
      expect(out).not.toContain("couldn't match a block");
    });

    it('hotfix-2026-05-24: success ack derives target from draft_json.qr_codes (post-normalize)', () => {
      const out = renderOutcomeAck(
        {
          id: 'aabbccddee',
          sender_name: 'Vikki',
          log_type: 'observation',
          draft_json: {
            type: 'observation',
            qr_codes: ['260512_SHI_4'], // post-normalize shape
            state: 'fruiting',
            event_timestamp: '2026-05-12T12:00:00Z',
          },
        },
        { outcome: 'success' }
      );
      expect(out).toContain('260512_SHI_4');
      expect(out).not.toContain('general farm note');
    });

    it('hotfix-2026-05-24: success ack falls back to general farm note when no target available', () => {
      const out = renderOutcomeAck(
        {
          id: '1fb28e7091',
          sender_name: 'Santi',
          log_type: 'activity',
          draft_json: {
            type: 'activity',
            // genuinely no asset_ref / qr_codes -- prior-style farm-level activity
            event_timestamp: '2026-05-15T12:00:00Z',
            notes: 'general farm work',
          },
        },
        { outcome: 'success' }
      );
      // Preserves the original no-target fallback for legitimately farm-level events
      expect(out).toContain('general farm note');
    });

    it('hotfix-2026-05-24: <UNKNOWN> sentinel does not become a fake target', () => {
      const out = renderOutcomeAck(
        {
          log_type: 'observation',
          sender_name: 'Santi',
          draft_json: { type: 'observation', asset_ref: '<UNKNOWN>' },
        },
        { outcome: 'success' }
      );
      expect(out).not.toContain('<UNKNOWN>');
      expect(out).toContain('general farm note'); // sentinel = no-target
    });

    it('Test G: no em-dash, no en-dash, no emoji in any seeding_session ack', () => {
      const cases = [
        { outcome: 'success' },
        { outcome: 'failed', reason: 'partial_commit_failed' },
        { outcome: 'failed', reason: 'session_name_exhausted' },
        { outcome: 'failed', reason: 'session_fungi_type_term_missing' },
      ];
      for (const opts of cases) {
        const out = renderOutcomeAck(may22Draft(), opts);
        expect(out).not.toMatch(/—/); // em-dash
        expect(out).not.toMatch(/–/); // en-dash
        // No emoji (loose check: any character in the Misc Symbols / Emoji blocks)
        expect(out).not.toMatch(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u);
      }
    });

    it('counts: blocks total uses sum of child_block_names lengths', () => {
      // Two groups, 3 + 4 = 7 children.
      const draft = {
        log_type: 'seeding_session',
        sender_name: 'Vikki',
        target: null,
        draft_json: {
          type: 'seeding_session',
          event_date: '2026-05-23',
          groups: [
            { child_block_names: { value: ['a', 'b', 'c'] } },
            { child_block_names: { value: ['d', 'e', 'f', 'g'] } },
          ],
        },
      };
      const out = renderOutcomeAck(draft, { outcome: 'success' });
      expect(out).toContain('7 blocks across 2 parents');
    });

    it('counts: falls back to qty.value when child_block_names is absent', () => {
      const draft = {
        log_type: 'seeding_session',
        sender_name: 'Vikki',
        target: null,
        draft_json: {
          type: 'seeding_session',
          event_date: '2026-05-23',
          groups: [
            { qty: { value: 4 } },
            { qty: { value: 6 } },
          ],
        },
      };
      const out = renderOutcomeAck(draft, { outcome: 'success' });
      expect(out).toContain('10 blocks across 2 parents');
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
      expect(out.toLowerCase().startsWith('saved')).toBe(true);
    });

    it('omits greeting when sender_name is empty string', () => {
      const out = renderOutcomeAck(
        { log_type: 'seeding', target: '260512_SHI_4', sender_name: '' },
        { outcome: 'success', farmosLink: 'https://farmos.example/log/1' }
      );
      expect(out.startsWith('Hi')).toBe(false);
      expect(out.toLowerCase().startsWith('saved')).toBe(true);
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
