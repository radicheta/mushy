'use strict';

// Phase 44 Wave 0 stub — filled in by Plan-04 (Haiku 4.5 live-fire).
// Covers GATE-02 on real API. Mirrors EVAL_RUN_LIVE gate idiom from
// test/eval/ingestion/paperlog.test.js:14-15.

const liveMode = process.env.EVAL_RUN_LIVE === '1' && !!process.env.ANTHROPIC_API_KEY;
const describeMaybe = liveMode ? describe : describe.skip;

describeMaybe('event-gate/haiku-live (stub)', () => {
  test.skip('Plan-04: classifies 10 gray-zone fixtures with ≥80% agreement', () => {}, 60000);
  test.skip('Plan-04: cache_creation_input_tokens > 0 confirms ≥4096-token prompt (Pitfall 1)', () => {}, 60000);
});
