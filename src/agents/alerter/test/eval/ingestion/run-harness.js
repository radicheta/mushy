#!/usr/bin/env node
'use strict';

// Phase 41 ingestion harness CLI.
//
// Cites: CONTEXT D-01 (single harness binary), D-01a (single results JSONL per run),
// D-07 (cost cap), D-07a (smoke before batch), D-07b (JSONL append-only).
// Memory rules honored:
//   * feedback_persist_paid_results_default -- per-run unique JSONL paths via
//     jsonl-writer; never overwrite paid results.
//   * feedback_smoke_before_expensive_batch -- --smoke flag caps fixture count.
//
// Invocation:
//   node run-harness.js --corpus <synthetic|paper-log|audio|all> [--smoke]
//                       [--live] [--cap-usd <N>] [--no-report]
//
// Default mode is MOCKED (no ANTHROPIC_API_KEY required). --live wires the real
// createExtractor + createTranscribeClient and enforces the cost cap.
//
// Wave 0 scope (this plan): CLI + dispatch table + JSONL writer + cost-cap
// scaffolding. Per-fixture pipeline call wires in Plan 02. Corpus loaders wire
// in Plans 03 / 04 / 05. Cross-stream + report wire in Plans 06 / 07.

const path = require('path');
const { createJsonlWriter, openRunMetadataLine } = require('./jsonl-writer');
const { createMockExtractor } = require('./mock-extractor');
const { createMockTranscribe } = require('./mock-transcribe');
const fixturesLoader = require('./fixtures-loader');

// fmtNum: lazy require to avoid pulling alerter deps in CI smoke runs.
let _fmtNum = null;
function fmtNum(n) {
  if (!_fmtNum) {
    try { _fmtNum = require('../../../src/message').fmtNum; }
    catch (_) { _fmtNum = (x) => (typeof x === 'number' ? (Math.round(x * 10) / 10).toString().replace(/\.0$/, '') : String(x)); }
  }
  return _fmtNum(n);
}

// Loader registry. Plans 03 / 04 / 05 wire their loaders in.
const LOADERS = {
  synthetic: () => fixturesLoader.loadSyntheticCorpus(path.resolve(__dirname, 'fixtures/synthetic')),
  'paper-log': () => fixturesLoader.loadPaperLogCorpus(),
  audio: () => fixturesLoader.loadAudioCorpus(),
};

function parseArgs(argv) {
  const out = {
    corpus: 'synthetic',
    smoke: false,
    live: false,
    capUsd: 20,
    noReport: false,
  };
  const a = argv.slice(2);
  for (let i = 0; i < a.length; i += 1) {
    const tok = a[i];
    if (tok === '--smoke') out.smoke = true;
    else if (tok === '--live') out.live = true;
    else if (tok === '--no-report') out.noReport = true;
    else if (tok === '--corpus') { out.corpus = a[++i]; }
    else if (tok === '--cap-usd') { out.capUsd = parseFloat(a[++i]); }
    else if (tok.startsWith('--corpus=')) out.corpus = tok.slice('--corpus='.length);
    else if (tok.startsWith('--cap-usd=')) out.capUsd = parseFloat(tok.slice('--cap-usd='.length));
  }
  return out;
}

function selectedCorpora(corpus) {
  if (corpus === 'all') return Object.keys(LOADERS);
  return [corpus];
}

function buildFixturesById(fixtures) {
  const out = {};
  for (const f of fixtures) out[f.name] = f;
  return out;
}

async function runCorpus({ corpus, smoke, live, capUsd, noReport, logger = console, baseDir, loaderOverride } = {}) {
  const opts = {
    corpus: corpus || 'synthetic',
    smoke: !!smoke,
    live: !!live,
    capUsd: typeof capUsd === 'number' ? capUsd : 20,
    noReport: !!noReport,
  };
  const corpora = selectedCorpora(opts.corpus);
  const summary = { byCorpus: {}, totalCostUsd: 0, runId: null, mode: opts.live ? 'live' : 'mock', smoke: opts.smoke };
  const allResults = [];

  for (const name of corpora) {
    const loader = (loaderOverride && loaderOverride[name]) || LOADERS[name];
    if (!loader) {
      logger.warn(`[harness] loader for ${name} not yet wired (Plan 03/04/05)`);
      summary.byCorpus[name] = { scores: null, fixtureCount: 0, errors: 0, skipped: 0, costUsd: 0, tokens: null, notWired: true };
      continue;
    }

    let fixtures;
    try {
      fixtures = await loader();
    } catch (e) {
      logger.error(`[harness] loader threw for ${name}: ${e.message}`);
      summary.byCorpus[name] = { scores: null, fixtureCount: 0, errors: 1, skipped: 0, costUsd: 0, tokens: null, error: e.message };
      continue;
    }

    const smokeSize = opts.smoke ? (parseInt(process.env.EVAL_SMOKE_SIZE, 10) || 5) : Infinity;
    const sliced = Number.isFinite(smokeSize) ? fixtures.slice(0, smokeSize) : fixtures;

    const writer = createJsonlWriter({ corpus: name, baseDir, logger });
    if (!summary.runId) summary.runId = writer.runId;

    writer.write(openRunMetadataLine({
      corpus: name,
      runId: writer.runId,
      model: opts.live ? (process.env.EVAL_MODEL || 'claude-sonnet-4-6') : null,
      mode: opts.live ? 'live' : 'mock',
      smoke: opts.smoke,
      cap_usd: opts.capUsd,
    }));

    // Build extractor + transcribe factories (mock by default; live shim Plan 02).
    const fixturesById = buildFixturesById(sliced);
    let extractor;
    let transcribe;
    if (opts.live) {
      const { createExtractor } = require('../../../src/extraction/extractor');
      const { createTranscribeClient } = require('../../../src/transcribe-client');
      const apiKey = process.env.ANTHROPIC_API_KEY;
      if (!apiKey) {
        logger.error('[harness] --live requires ANTHROPIC_API_KEY');
        process.exitCode = 2;
        return summary;
      }
      const whisperUrl = process.env.WHISPER_URL || 'http://host.docker.internal:8090';
      extractor = createExtractor({ apiKey, logger, model: process.env.EVAL_MODEL || 'claude-sonnet-4-6' });
      transcribe = createTranscribeClient({ apiUrl: whisperUrl, logger });
    } else {
      extractor = createMockExtractor({ fixturesById, logger });
      transcribe = createMockTranscribe({ fixturesById });
    }

    // Plan 02 will wire pipelineAdapter.runFixtureThroughPipeline here. For now
    // the loop emits a stub result line per fixture so the JSONL contract is
    // exercised end-to-end. We attempt to lazy-require pipeline-adapter; if it
    // exists (Plan 02 landed) we use it.
    let adapter = null;
    try { adapter = require('./pipeline-adapter'); } catch (_) { adapter = null; }

    let totalCost = 0;
    let errors = 0;
    let skipped = 0;
    const t0 = Date.now();
    const corpusResults = [];

    for (let i = 0; i < sliced.length; i += 1) {
      const fx = sliced[i];
      const elapsed = ((Date.now() - t0) / 1000).toFixed(1);
      logger.info(`[harness] ${name} ${i + 1}/${sliced.length} (${elapsed}s) ${fx.name}`);

      let result;
      if (adapter && typeof adapter.runFixtureThroughPipeline === 'function') {
        try {
          result = await adapter.runFixtureThroughPipeline(fx, { extractor, transcribe, logger });
        } catch (e) {
          errors += 1;
          result = {
            fixture_id: fx.name,
            kind: fx.kind || name,
            session_id: fx.session_id || null,
            expected: fx.expected || null,
            actual: { ok: false, draft: null, per_field_confidence: {} },
            tokens: null,
            cost_usd: 0,
            transcribe_latency_ms: 0,
            extract_latency_ms: 0,
            harness_confirmed: true,
            error: `thrown: ${e.message}`,
          };
        }
      } else {
        result = {
          fixture_id: fx.name,
          kind: fx.kind || name,
          session_id: fx.session_id || null,
          status: 'pending-plan-02',
        };
      }

      const line = { ts: new Date().toISOString(), ...result };
      writer.write(line);
      corpusResults.push(result);
      allResults.push(result);

      totalCost += (result && result.cost_usd) || 0;
      summary.totalCostUsd += (result && result.cost_usd) || 0;
      if (opts.live && summary.totalCostUsd > opts.capUsd) {
        const capLine = { ts: new Date().toISOString(), event: 'cap_exceeded', cap_usd: opts.capUsd, spent_usd: summary.totalCostUsd };
        writer.write(capLine);
        logger.error(`[harness] cost cap exceeded (cap=$${opts.capUsd}, spent=$${summary.totalCostUsd.toFixed(2)})`);
        writer.close();
        summary.byCorpus[name] = { scores: null, fixtureCount: i + 1, errors, skipped, costUsd: totalCost, results: corpusResults, capExceeded: true };
        process.exitCode = 1;
        return summary;
      }
    }

    writer.close();
    summary.byCorpus[name] = {
      scores: null,
      fixtureCount: sliced.length,
      errors,
      skipped,
      costUsd: totalCost,
      tokens: null,
      results: corpusResults,
      jsonlPath: writer.path,
    };
    logger.info(`[harness] corpus=${name} n=${sliced.length} mode=${opts.live ? 'live' : 'mock'} jsonl=${writer.path}`);
  }

  // Plan 06 Task 3: cross-stream consistency runs whenever 2+ corpora produced
  // fixtures (or --corpus all). Single-corpus runs skip silently.
  const wiredCorpora = corpora.filter((n) => summary.byCorpus[n] && !summary.byCorpus[n].notWired && summary.byCorpus[n].fixtureCount > 0);
  if (wiredCorpora.length >= 2) {
    const { crossStreamConsistency } = require('./cross-stream');
    const csSummary = crossStreamConsistency(allResults);
    summary.crossStream = csSummary;
    try {
      const csWriter = createJsonlWriter({ corpus: 'cross-stream', baseDir, runId: summary.runId, logger });
      csWriter.write({ ts: new Date().toISOString(), event: 'cross_stream_summary', aggregate: csSummary.aggregate, totalPairs: csSummary.totalPairs, identicalPairs: csSummary.identicalPairs });
      for (const d of csSummary.divergences) {
        csWriter.write({ ts: new Date().toISOString(), event: 'divergence', ...d });
      }
      csWriter.close();
      summary.crossStreamJsonl = csWriter.path;
    } catch (e) {
      logger.warn(`[harness] cross-stream JSONL write failed: ${e.message}`);
    }
    logger.info(`[harness] cross-stream consistency: ${fmtNum(csSummary.aggregate * 100)}% (${fmtNum(csSummary.identicalPairs)}/${fmtNum(csSummary.totalPairs)} pairs)`);
  }

  summary.allResults = allResults;

  // Plan 07 Task 4: write Markdown report unless --no-report.
  if (!opts.noReport) {
    try {
      const { writeIngestReport } = require('./report');
      const tsSafe = new Date().toISOString().replace(/[:.]/g, '-');
      const corpusTag = corpora.length === 1 ? corpora[0] : 'all';
      const reportPath = path.resolve(__dirname, '..', '..', '..', '..', '..', '..', '.planning', 'phases', '41-ingestion-harness', `41-EVAL-REPORT-${corpusTag}-${tsSafe}.md`);
      const verdict = writeIngestReport(reportPath, summary, { runId: summary.runId, mode: summary.mode, smoke: opts.smoke });
      logger.info(`[harness] report: ${reportPath}`);
      logger.info(`[harness] ## Verdict: [${verdict}]`);
      summary.reportPath = reportPath;
      summary.verdict = verdict;
    } catch (e) {
      logger.warn(`[harness] report write failed: ${e.message}`);
    }
  }
  return summary;
}

async function main() {
  const args = parseArgs(process.argv);
  try {
    await runCorpus(args);
  } catch (e) {
    console.error(`[harness] internal error: ${e.stack || e.message}`);
    process.exitCode = 2;
  }
}

if (require.main === module) {
  main();
}

module.exports = { parseArgs, runCorpus, selectedCorpora, LOADERS };
