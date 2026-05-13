'use strict';

// Phase 41 Plan 02 Task 1: pipeline adapter.
//
// Cites CONTEXT D-01b (reuse Phase 38 pipeline.loadImageBlocks) + Phase 38
// Plan 09 Task 2 lineage (the harness exercises the SAME image-loading code
// path as the live alerter; pipeline.js bugs surface in the harness).
//
// runFixtureThroughPipeline(fixture, { extractor, transcribe, logger, loadImageBlocks? }):
//   * pulls image attachments through loadImageBlocks
//   * pulls audio attachments through transcribe.transcribe({audioPath})
//   * composes envelope.body + transcript and calls extractor.extract
//   * returns the uniform per-fixture result line shape

const defaultPipeline = require('../../../src/extraction/pipeline');

async function runFixtureThroughPipeline(fixture, opts = {}) {
  const {
    extractor,
    transcribe,
    logger = console,
    loadImageBlocks = defaultPipeline.loadImageBlocks,
  } = opts;
  if (!extractor) throw new Error('runFixtureThroughPipeline: extractor required');
  if (!transcribe) throw new Error('runFixtureThroughPipeline: transcribe required');

  const attachments = fixture.attachments || [];
  const imagePaths = attachments.filter((a) => a && a.type === 'image').map((a) => a.path);
  const audioPaths = attachments.filter((a) => a && a.type === 'audio').map((a) => a.path);

  let transcript = '';
  let transcribe_latency_ms = 0;
  if (audioPaths.length > 0) {
    const t0 = Date.now();
    const parts = [];
    for (const ap of audioPaths) {
      const r = await transcribe.transcribe({ audioPath: ap });
      if (r && r.ok !== false && r.text) parts.push(r.text);
      else if (r && r.text) parts.push(r.text);
    }
    transcript = parts.join('\n').trim();
    transcribe_latency_ms = Date.now() - t0;
  }

  let imageBlocks = [];
  if (imagePaths.length > 0) {
    imageBlocks = await loadImageBlocks(imagePaths, logger);
  }

  const envelopeBody = (fixture.envelope && fixture.envelope.body) || '';
  const composedText = [envelopeBody, transcript].filter(Boolean).join('\n').trim();

  const t1 = Date.now();
  let result;
  try {
    result = await extractor.extract({
      text: composedText,
      imageBlocks,
      fixtureName: fixture.name,
    });
  } catch (e) {
    result = { ok: false, reason: `thrown: ${e.message}` };
  }
  const extract_latency_ms = Date.now() - t1;

  const ok = !!(result && result.ok);
  return {
    fixture_id: fixture.name,
    kind: fixture.kind || null,
    session_id: (fixture.session_id) || (fixture.expected && fixture.expected.session_id) || null,
    expected: fixture.expected || null,
    actual: {
      ok,
      draft: (result && result.draft) || null,
      per_field_confidence: (result && result.per_field_confidence) || {},
    },
    tokens: (result && result.tokens) || null,
    cost_usd: (result && result.cost_usd) || 0,
    transcribe_latency_ms,
    extract_latency_ms,
    harness_confirmed: true,
    error: ok ? null : ((result && result.reason) || 'unknown'),
  };
}

module.exports = { runFixtureThroughPipeline };
