'use strict';

// Phase 44 Plan-04 Task 4.5: EVAL_RUN_LIVE-gated Haiku 4.5 live-fire smoke.
// Runs ONLY when EVAL_RUN_LIVE=1 AND ANTHROPIC_API_KEY is set (mirrors
// test/eval/ingestion/paperlog.test.js:14-15). Otherwise skipped.
//
// Targets the 10-row HOLDOUT_ROW_IDS from prompts.js (W10 invariant: those
// rows' text NEVER appears in any few-shot example). Persists per-run results
// to .planning/phases/44-event-gate-durable-signal-outbound-tenant-aware/44-04-haiku-live-results-<ts>.jsonl
// per [[feedback_persist_paid_results_default]]. Asserts ≥80% live agreement
// with hand labels + cache_creation_input_tokens > 0 on at least one response
// (the real ship-gate for RESEARCH Pitfall 1's 4096-token threshold).

const fs = require('fs');
const path = require('path');

const { createHaikuClassifier } = require('../../src/event-gate/haiku-classifier');
const { HOLDOUT_ROW_IDS } = require('../../src/event-gate/prompts');

const FIXTURE_PATH = path.join(
  __dirname, '..', '..', '..', '..', '..',
  '.planning', 'phases', '44-event-gate-durable-signal-outbound-tenant-aware',
  '44-hand-classified-100.jsonl'
);

const RESULTS_DIR = path.join(
  __dirname, '..', '..', '..', '..', '..',
  '.planning', 'phases', '44-event-gate-durable-signal-outbound-tenant-aware'
);

const liveMode = process.env.EVAL_RUN_LIVE === '1' && !!process.env.ANTHROPIC_API_KEY;
const describeMaybe = liveMode ? describe : describe.skip;

function loadFixture() {
  const raw = fs.readFileSync(FIXTURE_PATH, 'utf8');
  return raw.trim().split('\n').map((l) => JSON.parse(l));
}

function expectedIsEvent(cls) {
  // Map fixture class tag to expected is_event truth label.
  switch (cls) {
    case 'hard-event': return true;
    case 'soft-obs': return true;
    case 'phantom-ack': return false;
    case 'greetings': return false;
    case 'UX-meta': return false;
    default: return null;
  }
}

describeMaybe('event-gate/haiku-live — 10 gray-zone holdout rows', () => {
  test('≥80% agreement + cache_creation_input_tokens > 0 on at least one call', async () => {
    const rows = loadFixture();
    const byId = new Map(rows.map((r) => [r.capture_id, r]));
    const holdout = HOLDOUT_ROW_IDS.map((id) => byId.get(id)).filter(Boolean);
    expect(holdout.length).toBe(HOLDOUT_ROW_IDS.length);

    const classifier = createHaikuClassifier({ apiKey: process.env.ANTHROPIC_API_KEY });

    const ts = new Date().toISOString().replace(/[:.]/g, '-');
    const resultsPath = path.join(RESULTS_DIR, `44-04-haiku-live-results-${ts}.jsonl`);
    const out = fs.createWriteStream(resultsPath);

    let agreed = 0;
    let cacheCreationSeen = 0;
    const records = [];

    for (const row of holdout) {
      const envCtx = {
        text: row.raw_text || null,
        transcript: row.transcript || null,
        attachmentCount: typeof row.attachment_count === 'number' ? row.attachment_count : 0,
      };
      const r = await classifier.classify(envCtx);
      const expected = expectedIsEvent(row.class);
      const ok = r.ok === true && r.is_event === expected;
      if (ok) agreed += 1;
      const cci = r.usage && r.usage.cache_creation_input_tokens
        ? r.usage.cache_creation_input_tokens
        : 0;
      if (cci > 0) cacheCreationSeen += 1;
      const record = {
        capture_id: row.capture_id,
        class: row.class,
        expected_is_event: expected,
        result: r,
        agreed: ok,
      };
      records.push(record);
      out.write(JSON.stringify(record) + '\n');
    }
    out.end();

    // Wait for flush.
    await new Promise((resolve) => out.on('finish', resolve));

    const agreementPct = agreed / holdout.length;
    console.log(`[haiku-live] agreement = ${agreed}/${holdout.length} (${(agreementPct * 100).toFixed(1)}%)`);
    console.log(`[haiku-live] cache_creation_input_tokens > 0 on ${cacheCreationSeen}/${holdout.length} calls`);
    console.log(`[haiku-live] results persisted to ${resultsPath}`);

    expect(agreementPct).toBeGreaterThanOrEqual(0.8);

    if (cacheCreationSeen === 0) {
      throw new Error(
        'cache no-op detected — system prompt is under 4096 token threshold (RESEARCH Pitfall 1). ' +
        'Extend prompts.js SYSTEM_PROMPT with more few-shot material and re-run.'
      );
    }
    expect(cacheCreationSeen).toBeGreaterThan(0);
  }, 60000);
});
