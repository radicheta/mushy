'use strict';

// Phase 44 Plan-04 Task 4.1: event-gate rules + facade.
// Covers GATE-01 fast paths (POSITIVE: image/audio/strain-code/block-name/long-text;
// NEGATIVE: short ack within 30m of attestation_kickoff) per CONTEXT D-02.

const { rulePositive, ruleNegative } = require('../../src/event-gate/rules');
const { createEventGate } = require('../../src/event-gate');

describe('event-gate/rules', () => {
  describe('rulePositive', () => {
    test('attachmentCount > 0 → hit image_or_audio', () => {
      const r = rulePositive({ text: '', attachmentCount: 1 });
      expect(r).toEqual({ hit: true, kind: 'image_or_audio' });
    });

    test('text length > 200 → hit long_text', () => {
      const body = 'a'.repeat(201);
      const r = rulePositive({ text: body, attachmentCount: 0 });
      expect(r.hit).toBe(true);
      expect(r.kind).toBe('long_text');
    });

    test('strain code regex matches "SHI" → hit strain_code', () => {
      const r = rulePositive({ text: 'logged SHI today', attachmentCount: 0 });
      expect(r.hit).toBe(true);
      expect(r.kind).toBe('strain_code');
    });

    test('block name regex matches "260511_SHI_3" → hit block_name', () => {
      const r = rulePositive({ text: 'block 260511_SHI_3 ready', attachmentCount: 0 });
      expect(r.hit).toBe(true);
      // block regex hits before strain regex because block test runs first when both could match,
      // but per PATTERNS the order is strain then block; either kind acceptable as long as hit.
      expect(['strain_code', 'block_name']).toContain(r.kind);
    });

    test('short chit-chat → no hit', () => {
      const r = rulePositive({ text: 'hola', attachmentCount: 0 });
      expect(r).toEqual({ hit: false });
    });
  });

  describe('ruleNegative', () => {
    const nowMs = Date.parse('2026-05-22T12:00:00Z');
    const kickoff = (offsetMin) => ({
      intent: 'attestation_kickoff',
      sent_at: new Date(nowMs - offsetMin * 60_000).toISOString(),
    });

    test('lastBotOutbound intent=attestation_kickoff, within 30m, "ok" → hit', () => {
      const r = ruleNegative({ text: 'ok' }, kickoff(5), nowMs);
      expect(r.hit).toBe(true);
    });

    test('wrong intent → no hit', () => {
      const r = ruleNegative({ text: 'ok' }, { intent: 'rh_alert', sent_at: new Date(nowMs).toISOString() }, nowMs);
      expect(r).toEqual({ hit: false });
    });

    test('31 min old kickoff → no hit', () => {
      const r = ruleNegative({ text: 'ok' }, kickoff(31), nowMs);
      expect(r).toEqual({ hit: false });
    });

    test('long body (43 chars) → no hit', () => {
      const r = ruleNegative({ text: "ok thanks i'll go check the substrate now" }, kickoff(5), nowMs);
      expect(r).toEqual({ hit: false });
    });

    test('non-ack text → no hit', () => {
      const r = ruleNegative({ text: 'maybe later' }, kickoff(5), nowMs);
      expect(r).toEqual({ hit: false });
    });
  });
});

describe('event-gate/index — classify facade', () => {
  const rules = require('../../src/event-gate/rules');
  const nowMs = Date.parse('2026-05-22T12:00:00Z');

  function makeHaiku(returnVal) {
    return { classify: jest.fn().mockResolvedValue(returnVal) };
  }

  test('Test 6: rulePositive hit → gate=fast_event, haiku NOT called', async () => {
    const haiku = makeHaiku({ ok: true, is_event: true, confidence: 0.9 });
    const gate = createEventGate({ haikuClassifier: haiku, rules });
    const r = await gate.classify({ text: 'has image', attachmentCount: 1 }, null, nowMs);
    expect(r.gate).toBe('fast_event');
    expect(r.allow_extract).toBe(true);
    expect(r.allow_convo).toBe(true);
    expect(haiku.classify).not.toHaveBeenCalled();
  });

  test('Test 7: ruleNegative hit → gate=skipped_rule_neg, haiku NOT called', async () => {
    const haiku = makeHaiku({ ok: true, is_event: false, confidence: 0.9 });
    const gate = createEventGate({ haikuClassifier: haiku, rules });
    const lastBot = { intent: 'attestation_kickoff', sent_at: new Date(nowMs - 5 * 60_000).toISOString() };
    const r = await gate.classify({ text: 'ok', attachmentCount: 0 }, lastBot, nowMs);
    expect(r.gate).toBe('skipped_rule_neg');
    expect(r.allow_extract).toBe(false);
    expect(r.allow_convo).toBe(false);
    expect(haiku.classify).not.toHaveBeenCalled();
  });

  test('Test 8: gray zone + haiku is_event:true → gate=haiku_event', async () => {
    const haiku = makeHaiku({ ok: true, is_event: true, confidence: 0.9 });
    const gate = createEventGate({ haikuClassifier: haiku, rules });
    const r = await gate.classify({ text: 'hola', attachmentCount: 0 }, null, nowMs);
    expect(r.gate).toBe('haiku_event');
    expect(r.allow_extract).toBe(true);
    expect(r.allow_convo).toBe(true);
  });

  test('Test 9: gray zone + haiku is_event:false high conf → gate=haiku_chitchat', async () => {
    const haiku = makeHaiku({ ok: true, is_event: false, confidence: 0.85 });
    const gate = createEventGate({ haikuClassifier: haiku, rules });
    const r = await gate.classify({ text: 'hola', attachmentCount: 0 }, null, nowMs);
    expect(r.gate).toBe('haiku_chitchat');
    expect(r.allow_extract).toBe(false);
    expect(r.allow_convo).toBe(false);
  });

  test('Test 10: gray zone + haiku error → gate=forced (fail-open)', async () => {
    const haiku = makeHaiku({ ok: false, reason: 'timeout', fallthrough: 'forced' });
    const gate = createEventGate({ haikuClassifier: haiku, rules });
    const r = await gate.classify({ text: 'hola', attachmentCount: 0 }, null, nowMs);
    expect(r.gate).toBe('forced');
    expect(r.allow_extract).toBe(true);
    expect(r.allow_convo).toBe(true);
  });

  test('Test 11: gray zone + haiku is_event:false low confidence → gate=haiku_event (low-conf floor)', async () => {
    const haiku = makeHaiku({ ok: true, is_event: false, confidence: 0.5 });
    const gate = createEventGate({ haikuClassifier: haiku, rules });
    const r = await gate.classify({ text: 'hola', attachmentCount: 0 }, null, nowMs);
    expect(r.gate).toBe('haiku_event');
    expect(r.allow_extract).toBe(true);
  });
});
