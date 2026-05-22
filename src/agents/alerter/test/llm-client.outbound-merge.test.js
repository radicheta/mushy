'use strict';

// Phase 44 Wave 0 stub — filled in by Plan-05 (fmtHistory outbound merge).
// Covers OUTBOUND-02 per CONTEXT D-17/D-18/D-19:
//   - fmtHistory merges signal_capture (inbound, 200-char cap) + signal_outbound
//     (outbound, 400-char cap) by timestamp
//   - buildUserBlock exposes lastBotOutbound as distinct prompt field

describe('llm-client outbound-merge (stub)', () => {
  test.skip('Plan-05: fmtHistory merges inbound + outbound streams by timestamp', () => {});
  test.skip('Plan-05: outbound rows truncate at 400 chars; inbound rows at 200 chars (D-18)', () => {});
  test.skip('Plan-05: buildUserBlock exposes lastBotOutbound as distinct field (D-19)', () => {});
  test.skip('Plan-05: lastBotOutbound is freshest signal_outbound row for recipient', () => {});
});
