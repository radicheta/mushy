'use strict';

// Phase 41 Plan 05 Task 3: audio corpus eval (operator-run; live LLM + Whisper).
//
// describe.skip unless the full env quartet is set + AUDIO_FIXTURE_DIR has content:
//   EVAL_RUN_LIVE=1
//   ANTHROPIC_API_KEY
//   WHISPER_URL
//   AUDIO_FIXTURE_DIR (existing, non-empty)

const fs = require('fs');
const path = require('path');
const os = require('os');
const { runCorpus } = require('./run-harness');

const liveMode = process.env.EVAL_RUN_LIVE === '1'
  && !!process.env.ANTHROPIC_API_KEY
  && !!process.env.WHISPER_URL
  && !!process.env.AUDIO_FIXTURE_DIR
  && fs.existsSync(process.env.AUDIO_FIXTURE_DIR)
  && fs.readdirSync(process.env.AUDIO_FIXTURE_DIR).length > 0;

const describeMaybe = liveMode ? describe : describe.skip;

describeMaybe('audio ingestion eval (operator-run; live LLM + Whisper)', () => {
  test('smoke run (5 recordings)', async () => {
    const baseDir = fs.mkdtempSync(path.join(os.tmpdir(), 'audio-smoke-'));
    const summary = await runCorpus({ corpus: 'audio', smoke: true, live: true, capUsd: 10, noReport: true, baseDir });
    const c = summary.byCorpus.audio;
    expect(c).toBeTruthy();
    if (c.fixtureCount < 5) {
      console.warn(`[audio.test] only ${c.fixtureCount} recording(s) supplied (CONTEXT D-04b: target 5)`);
    }

    const okCount = (c.results || []).filter((r) => r.actual && r.actual.ok).length;
    const conformance = c.results.length ? (okCount / c.results.length) : 0;
    expect(conformance).toBeGreaterThanOrEqual(0.9);

    // Whisper actually called for each fixture with audio attachments.
    for (const r of (c.results || [])) {
      expect(r.transcribe_latency_ms).toBeGreaterThanOrEqual(0);
    }
  }, 600000);

  test('full run', async () => {
    const baseDir = fs.mkdtempSync(path.join(os.tmpdir(), 'audio-full-'));
    const summary = await runCorpus({ corpus: 'audio', smoke: false, live: true, capUsd: 10, noReport: true, baseDir });
    const c = summary.byCorpus.audio;
    expect(c).toBeTruthy();
    const okCount = (c.results || []).filter((r) => r.actual && r.actual.ok).length;
    const conformance = c.results.length ? (okCount / c.results.length) : 0;
    expect(conformance).toBeGreaterThanOrEqual(0.9);
  }, 1800000);
});
