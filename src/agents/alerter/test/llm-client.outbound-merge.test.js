'use strict';

// Phase 44 Plan-05 Task 5.2: fmtHistory merges signal_capture (inbound) + signal_outbound
// (outbound) streams by timestamp. Per D-17, the v1.7.x band-aid (reading
// signal_capture.llm_reply) is superseded — fmtHistory now reads convo_reply rows from
// signal_outbound instead. Per D-18: inbound cap=200, outbound cap=400. Per D-19:
// buildUserBlock surfaces lastBotOutbound as a distinct prompt field.

const { _internal } = require('../src/llm-client');
const { fmtHistory, buildUserBlock, MAX_HISTORY_ROWS } = _internal;

describe('fmtHistory (merged streams)', () => {
  test('empty inbound + empty outbound returns "(none)"', () => {
    expect(fmtHistory([], [])).toBe('  (none)');
  });

  test('merges streams sorted by timestamp ASC across kinds', () => {
    const inbound = [
      { captured_at: new Date('2026-05-20T10:00:00Z'), message_type: 'text', raw_text: 'first inbound' },
      { captured_at: new Date('2026-05-20T10:02:00Z'), message_type: 'text', raw_text: 'third inbound' },
    ];
    const outbound = [
      { sent_at: new Date('2026-05-20T10:01:00Z'), body: 'second outbound', intent: 'convo_reply' },
    ];
    const out = fmtHistory(inbound, outbound);
    const lines = out.split('\n');
    expect(lines).toHaveLength(3);
    expect(lines[0]).toMatch(/first inbound/);
    expect(lines[1]).toMatch(/second outbound/);
    expect(lines[2]).toMatch(/third inbound/);
  });

  test('inbound bodies truncate at 200 chars; outbound at 400 chars (D-18)', () => {
    const longIn = 'I'.repeat(500);
    const longOut = 'O'.repeat(500);
    const inbound = [{ captured_at: new Date('2026-05-20T10:00:00Z'), message_type: 'text', raw_text: longIn }];
    const outbound = [{ sent_at: new Date('2026-05-20T10:01:00Z'), body: longOut, intent: 'convo_reply' }];
    const out = fmtHistory(inbound, outbound);
    const inMatches = out.match(/I+/);
    const outMatches = out.match(/O+/);
    expect(inMatches[0]).toHaveLength(200);
    expect(outMatches[0]).toHaveLength(400);
  });

  test('outbound rows render with bot:<intent> type prefix', () => {
    const outbound = [{ sent_at: new Date('2026-05-20T10:00:00Z'), body: 'hi farmer', intent: 'convo_reply' }];
    const out = fmtHistory([], outbound);
    expect(out).toMatch(/bot:convo_reply/);
    expect(out).toMatch(/hi farmer/);
  });

  test('after merge + sort, slice keeps newest MAX_HISTORY_ROWS (=20)', () => {
    const inbound = [];
    for (let i = 0; i < 30; i++) {
      inbound.push({
        captured_at: new Date(Date.parse('2026-05-20T08:00:00Z') + i * 60000),
        message_type: 'text',
        raw_text: `in-${i}`,
      });
    }
    const outbound = [];
    for (let j = 0; j < 10; j++) {
      outbound.push({
        sent_at: new Date(Date.parse('2026-05-20T09:30:00Z') + j * 30000),
        body: `out-${j}`,
        intent: 'convo_reply',
      });
    }
    const out = fmtHistory(inbound, outbound);
    const lines = out.split('\n');
    expect(lines).toHaveLength(MAX_HISTORY_ROWS);
    // Newest tail should still include the very last inbound (in-29).
    expect(out).toMatch(/in-29/);
    // Oldest inbound (in-0) should be dropped.
    expect(out).not.toMatch(/'in-0'/);
  });

  test('D-17: rows carrying llm_reply field do NOT leak into output', () => {
    const inbound = [
      {
        captured_at: new Date('2026-05-20T10:00:00Z'),
        message_type: 'text',
        raw_text: 'farmer text here',
        llm_reply: 'BAND-AID-LEAK-SHOULD-NOT-APPEAR',
      },
    ];
    const out = fmtHistory(inbound, []);
    expect(out).toMatch(/farmer text here/);
    expect(out).not.toMatch(/BAND-AID-LEAK-SHOULD-NOT-APPEAR/);
  });
});

describe('buildUserBlock — lastBotOutbound (D-19)', () => {
  function baseArgs(overrides = {}) {
    return {
      history: [],
      outboundHistory: [],
      lastBotOutbound: null,
      sensorSnapshot: null,
      currentMessage: {
        text: 'hi',
        transcript: '',
        attachmentCount: 0,
        capturedAtMs: Date.parse('2026-05-20T11:00:00Z'),
      },
      ...overrides,
    };
  }

  test('renders "## Last thing you said to the farmer" header with body when lastBotOutbound present', () => {
    const block = buildUserBlock(baseArgs({
      lastBotOutbound: {
        sent_at: new Date('2026-05-20T10:30:00Z'),
        body: 'hello farmer',
        intent: 'convo_reply',
      },
    }));
    expect(block).toMatch(/## Last thing you said to the farmer/);
    expect(block).toMatch(/hello farmer/);
    expect(block).toMatch(/convo_reply/);
  });

  test('renders "(none)" in last-bot-outbound section when null', () => {
    const block = buildUserBlock(baseArgs({ lastBotOutbound: null }));
    expect(block).toMatch(/## Last thing you said to the farmer/);
    const sectionStart = block.indexOf('## Last thing you said to the farmer');
    const after = block.slice(sectionStart);
    expect(after).toMatch(/\(none\)/);
  });
});
