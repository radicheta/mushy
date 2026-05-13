'use strict';

// Phase 41 Plan 07 Task 1: ingestion EVAL-REPORT writer.
//
// Cites CONTEXT D-06 (single Markdown report per run, per-run unique path),
// D-06a (per-corpus tables), D-06b (regression detection via compare-runs.js),
// D-09 (CI synthetic on every push), D-09a (ship-gate: synthetic + paper-log
// v1.6 PASS). Append-only paper trail per `feedback_keep_paper_trail_of_intermediates`.
//
// writeIngestReport(reportPath, summary, meta) -> 'PASS' | 'FAIL'.

const fs = require('fs');
const path = require('path');

// Lazy fmtNum: avoids alerter dep at unit-test time.
let _fmtNum = null;
function fmtNum(n) {
  if (!_fmtNum) {
    try { _fmtNum = require('../../../src/message').fmtNum; }
    catch (_) { _fmtNum = (x) => (typeof x === 'number' ? (Math.round(x * 10) / 10).toString().replace(/\.0$/, '') : String(x)); }
  }
  return _fmtNum(n);
}

function pct(x) {
  if (typeof x !== 'number' || Number.isNaN(x)) return 'n/a';
  return `${fmtNum(x * 100)}%`;
}

function corpusScores(corpus) {
  if (!corpus || !corpus.results) return null;
  const total = corpus.results.length;
  if (total === 0) return null;
  const okCount = corpus.results.filter((r) => r.actual && r.actual.ok).length;
  return {
    schemaConformance: okCount / total,
    okCount,
    total,
    costUsd: corpus.costUsd || 0,
    errors: corpus.errors || 0,
    skipped: corpus.skipped || 0,
  };
}

function shipGateVerdict(summary) {
  // D-09a: synthetic schema >= 90% AND paper-log curated schema >= 90% if run.
  const synth = corpusScores(summary.byCorpus.synthetic);
  const paper = corpusScores(summary.byCorpus['paper-log']);
  if (!synth) return { verdict: 'FAIL', reason: 'synthetic corpus not run' };
  if (synth.schemaConformance < 0.9) return { verdict: 'FAIL', reason: `synthetic schemaConformance ${pct(synth.schemaConformance)} < 90%` };
  if (paper) {
    if (paper.schemaConformance < 0.9) return { verdict: 'FAIL', reason: `paper-log schemaConformance ${pct(paper.schemaConformance)} < 90%` };
  }
  return { verdict: 'PASS', reason: paper ? 'synthetic + paper-log both >= 90%' : 'synthetic >= 90% (paper-log not run; stretch)' };
}

function writeIngestReport(reportPath, summary, meta = {}) {
  const lines = [];
  const ts = meta.timestamp || new Date().toISOString();
  lines.push('# Phase 41 Ingestion Harness EVAL Report');
  lines.push('');
  lines.push(`**Generated:** ${ts}`);
  lines.push(`**Run ID:** ${meta.runId || summary.runId || 'n/a'}`);
  lines.push(`**Mode:** ${meta.mode || summary.mode || 'mock'}`);
  lines.push(`**Smoke:** ${meta.smoke || summary.smoke ? 'yes' : 'no'}`);
  lines.push(`**Total cost (USD):** ${fmtNum(summary.totalCostUsd || 0)}`);
  lines.push('');

  // Ship-Gate Decision (D-09a)
  const sg = shipGateVerdict(summary);
  lines.push('## Ship-Gate Decision (CONTEXT D-09a)');
  lines.push('');
  lines.push('Phase 41 ships when synthetic schemaConformance >= 90% AND, if run, paper-log curated schemaConformance >= 90%. Audio + cross-stream are stretch goals.');
  lines.push('');
  lines.push(`- Status: ${sg.verdict}`);
  lines.push(`- Reason: ${sg.reason}`);
  lines.push('');

  // Per-Corpus Tables (D-06a)
  lines.push('## Per-Corpus Results');
  lines.push('');
  for (const name of ['synthetic', 'paper-log', 'audio']) {
    const corpus = summary.byCorpus && summary.byCorpus[name];
    lines.push(`### ${name}`);
    lines.push('');
    if (!corpus || corpus.notWired) {
      lines.push('Not run (loader not wired).');
      lines.push('');
      continue;
    }
    if (corpus.fixtureCount === 0) {
      if (name === 'audio') {
        lines.push('human_needed (operator action: see 41-RUNBOOK.md section 4)');
      } else if (name === 'paper-log') {
        lines.push('human_needed (operator action: see 41-RUNBOOK.md section 3)');
      } else {
        lines.push('Not run (loader returned no fixtures).');
      }
      lines.push('');
      continue;
    }
    const s = corpusScores(corpus);
    lines.push(`- Fixtures: ${fmtNum(corpus.fixtureCount)}`);
    lines.push(`- Schema conformance: ${s ? pct(s.schemaConformance) : 'n/a'} (${fmtNum(s ? s.okCount : 0)}/${fmtNum(s ? s.total : 0)})`);
    lines.push(`- Errors: ${fmtNum(corpus.errors || 0)}`);
    lines.push(`- Skipped: ${fmtNum(corpus.skipped || 0)}`);
    lines.push(`- Cost (USD): ${fmtNum(corpus.costUsd || 0)}`);
    if (corpus.jsonlPath) lines.push(`- JSONL: \`${corpus.jsonlPath}\``);
    lines.push('');
  }

  // Cross-Stream Consistency
  lines.push('## Cross-Stream Consistency');
  lines.push('');
  if (!summary.crossStream || summary.crossStream.totalPairs === 0) {
    lines.push('human_needed (no paired peers supplied; see 41-RUNBOOK.md section 5)');
  } else {
    const cs = summary.crossStream;
    lines.push(`- Aggregate: ${pct(cs.aggregate)} (${fmtNum(cs.identicalPairs)}/${fmtNum(cs.totalPairs)} pairs)`);
    lines.push('');
    if (cs.divergences.length > 0) {
      lines.push('### Divergences');
      lines.push('');
      for (const d of cs.divergences) {
        lines.push(`- session=\`${d.session_id}\` ${d.kind_a}/${d.fixture_a} vs ${d.kind_b}/${d.fixture_b}:`);
        for (const x of (d.diff || []).slice(0, 5)) {
          lines.push(`  - \`${x.path}\`: ${JSON.stringify(x.a)} vs ${JSON.stringify(x.b)}`);
        }
      }
    }
  }
  lines.push('');

  // Per-Run Artifacts
  lines.push('## Per-Run Artifacts');
  lines.push('');
  for (const name of Object.keys(summary.byCorpus || {})) {
    const corpus = summary.byCorpus[name];
    if (corpus && corpus.jsonlPath) {
      lines.push(`- ${name}: \`${corpus.jsonlPath}\``);
    }
  }
  if (summary.crossStreamJsonl) {
    lines.push(`- cross-stream: \`${summary.crossStreamJsonl}\``);
  }
  lines.push('');

  // Verdict line (grep-parseable)
  lines.push(`## Verdict: [${sg.verdict}]`);
  lines.push('');

  fs.mkdirSync(path.dirname(reportPath), { recursive: true });
  fs.writeFileSync(reportPath, lines.join('\n'));
  return sg.verdict;
}

module.exports = { writeIngestReport, shipGateVerdict, corpusScores, fmtNum, pct };
