'use strict';

// Phase 44 Wave 0 stub — filled in by Plan-04 (capture-pipeline-with-gate).
// Covers GATE-01 + GATE-02 integration: gate runs at capture.js:147 BEFORE
// extractionPipeline.enqueue; gate decision shared with convo path at :171
// per CONTEXT D-02 + D-05.

describe('event-gate/integration (stub)', () => {
  test.skip('Plan-04: rule POSITIVE → extraction enqueued + convo allowed', () => {});
  test.skip('Plan-04: rule NEGATIVE → extraction skipped + convo silenced (silent mode)', () => {});
  test.skip('Plan-04: haiku_chitchat → extraction skipped + convo silenced (silent mode)', () => {});
  test.skip('Plan-04: haiku_event → extraction enqueued + convo allowed', () => {});
  test.skip('Plan-04: EVENT_GATE_CONVO_MODE=off → convo always runs (D-06)', () => {});
  test.skip('Plan-04: extraction_gate audit column written before dispatch (D-04)', () => {});
});
