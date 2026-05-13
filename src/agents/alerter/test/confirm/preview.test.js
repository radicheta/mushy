'use strict';

const p = require('../../src/confirm/preview');

const ALL_FNS = [
  'buildPreviewWithSuffix',
  'buildConfirmAck',
  'buildIdempotentAck',
  'buildDiscardAck',
  'buildEditCapMsg',
  'buildNudge',
  'buildExpiredNote',
];

function sampleDraft() {
  return {
    type: 'seeding',
    species: 'SHI',
    block_name: '260512_SHI_1',
    qty: 7,
    event_timestamp: '2026-05-12T10:00:00Z',
  };
}

function callWithDefaults(fn) {
  switch (fn) {
    case 'buildPreviewWithSuffix':
      return p.buildPreviewWithSuffix({
        draft: sampleDraft(),
        perFieldConfidence: { species: 0.95, block_name: 0.9, qty: 0.95, event_timestamp: 0.9 },
        requiredFields: ['species', 'block_name', 'qty', 'event_timestamp'],
        threshold: 0.7,
      });
    case 'buildConfirmAck':
      return p.buildConfirmAck('abcdef1234ghijk');
    case 'buildIdempotentAck':
      return p.buildIdempotentAck();
    case 'buildDiscardAck':
      return p.buildDiscardAck();
    case 'buildEditCapMsg':
      return p.buildEditCapMsg(3);
    case 'buildNudge':
      return p.buildNudge({ minutesRemaining: 6 });
    case 'buildExpiredNote':
      return p.buildExpiredNote();
    default:
      return '';
  }
}

describe('preview renderers (Phase 39 D-05)', () => {
  describe('Style locks', () => {
    it('no em-dash (\\u2014) in any renderer output', () => {
      for (const fn of ALL_FNS) {
        const out = callWithDefaults(fn);
        expect(out).not.toMatch(/—/);
      }
    });
    it('no en-dash (\\u2013) in any renderer output', () => {
      for (const fn of ALL_FNS) {
        const out = callWithDefaults(fn);
        expect(out).not.toMatch(/–/);
      }
    });
  });

  describe('buildNudge number rounding', () => {
    it('5.7 -> "6 min"', () => {
      expect(p.buildNudge({ minutesRemaining: 5.7 })).toMatch(/\b6 min\b/);
    });
    it('0.4 -> "0 min"', () => {
      expect(p.buildNudge({ minutesRemaining: 0.4 })).toMatch(/\b0 min\b/);
    });
    it('appends previewSummary line when provided', () => {
      const out = p.buildNudge({ minutesRemaining: 3, previewSummary: 'seeding 260512_SHI_1 x7' });
      expect(out).toContain('seeding 260512_SHI_1');
    });
  });

  describe('buildConfirmAck', () => {
    it('contains "Locked in" and the 10-char truncated draft id', () => {
      const out = p.buildConfirmAck('abcdef1234ghijklmno');
      expect(out).toContain('Locked in');
      expect(out).toContain('abcdef1234');
      expect(out).not.toContain('abcdef1234ghij');
    });
  });

  describe('buildIdempotentAck', () => {
    it('contains "Already locked in"', () => {
      expect(p.buildIdempotentAck()).toContain('Already locked in');
    });
  });

  describe('buildDiscardAck', () => {
    it('contains "Discarded"', () => {
      expect(p.buildDiscardAck()).toContain('Discarded');
    });
  });

  describe('buildEditCapMsg', () => {
    it('contains the cap number via fmtNum', () => {
      expect(p.buildEditCapMsg(3)).toMatch(/\b3\b/);
    });
    it('does not refer to "operator" (memory: dont-say-operator)', () => {
      expect(p.buildEditCapMsg(3)).not.toMatch(/\boperator\b/i);
    });
  });

  describe('buildExpiredNote', () => {
    it('contains "expired" + "Nothing was written" + instruction to send a fresh message', () => {
      const out = p.buildExpiredNote();
      expect(out).toMatch(/expired/i);
      expect(out).toContain('Nothing was written');
      expect(out.toLowerCase()).toContain('fresh message');
    });
  });

  describe('buildPreviewWithSuffix', () => {
    it('appends the reply-instructions suffix', () => {
      const out = callWithDefaults('buildPreviewWithSuffix');
      expect(out).toMatch(/Reply YES to commit, NO to discard, EDIT/);
    });
    it('strips [?] markers from the body (D-05)', () => {
      const out = p.buildPreviewWithSuffix({
        draft: { type: 'seeding', species: null, block_name: null, qty: null, event_timestamp: null },
        perFieldConfidence: {},
        requiredFields: ['species', 'block_name', 'qty', 'event_timestamp'],
        threshold: 0.7,
      });
      expect(out).not.toMatch(/\[\?\]/);
    });
  });
});
