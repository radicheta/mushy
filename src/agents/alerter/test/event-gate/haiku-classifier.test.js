'use strict';

// Phase 44 Wave 0 stub — filled in by Plan-04 (Haiku 4.5 classifier).
// Covers GATE-02 mocked-SDK shape per CONTEXT D-02 (gray-zone classify_capture
// tool_use returns {is_event, kind, confidence}). Mirror mock pattern from
// test/farmos/mock-client.js and extractor.js injected-client pattern.

describe('event-gate/haiku-classifier (stub)', () => {
  test.skip('Plan-04: classifies event with mocked tool_use response', () => {});
  test.skip('Plan-04: fail-OPEN on SDK error (D-03) — returns fallthrough=forced', () => {});
  test.skip('Plan-04: fail-OPEN on timeout (2s default) — returns fallthrough=forced', () => {});
  test.skip('Plan-04: zod-validates tool_use input shape {is_event, kind, confidence}', () => {});
});
