'use strict';

// Phase 38 Plan 07 Task 1: Markdown report writer for the D-07 ship-gate.
//
// writeReport(reportPath, scores, fixtureCount, verdict, meta): sync write.
//   reportPath: parameterized so Plan 08 can point at 38-PRODLOG-REPORT.md.
//   scores: shape per mushdatadump.test.js driver.
//   verdict: 'PASS' or 'FAIL' (computed by caller).
//   meta: {model, fixtureDir, timestamp, costEstimateUsd?, costNote?, adaptations?, skipped?, errors?}
//
// Verdict line must be EXACTLY `## Verdict: [PASS]` or `## Verdict: [FAIL]` (grep-parseable).
// No em-dashes. fmtNum on every numeric.

const fs = require('fs');
const path = require('path');
const { fmtNum } = require('../../../src/message');

function pct(x) {
  if (typeof x !== 'number' || Number.isNaN(x)) return 'n/a';
  return `${fmtNum(x * 100)}%`;
}

function num(x, digits) {
  if (typeof x !== 'number' || Number.isNaN(x)) return 'n/a';
  return fmtNum(Number(x.toFixed(digits != null ? digits : 4)));
}

function buildReport(scores, fixtureCount, verdict, meta = {}) {
  const lines = [];
  lines.push(`# Phase 38 Plan 07: D-07 Ship-Gate Eval Report`);
  lines.push('');
  lines.push(`**Generated:** ${meta.timestamp || new Date().toISOString()}`);
  lines.push(`**Model:** ${meta.model || 'claude-sonnet-4-6'}`);
  lines.push(`**Fixture dir:** \`${meta.fixtureDir || 'n/a'}\``);
  lines.push(`**Fixture count:** ${fmtNum(fixtureCount)}`);
  if (meta.skipped != null) lines.push(`**Skipped (load errors):** ${fmtNum(meta.skipped)}`);
  if (meta.errors != null) lines.push(`**Hard API errors:** ${fmtNum(meta.errors)}`);
  if (meta.costNote) lines.push(`**Cost note:** ${meta.costNote}`);
  lines.push('');

  if (meta.adaptations) {
    lines.push('## Ground-Truth Adaptations');
    lines.push('');
    lines.push(meta.adaptations);
    lines.push('');
  }

  lines.push('## Pass Bar (CONTEXT D-07)');
  lines.push('');
  lines.push('- Schema conformance >= 90%');
  lines.push('- Required-field exact-match OR appropriate ask-back >= 75%');
  lines.push('');

  lines.push('## Per-Dimension Scores');
  lines.push('');
  lines.push('| Dimension | Score | Raw |');
  lines.push('|-----------|-------|-----|');
  lines.push(`| Schema conformance | ${pct(scores.schemaConformance)} | ${fmtNum(Math.round((scores.schemaConformance || 0) * fixtureCount))} / ${fmtNum(fixtureCount)} |`);
  const efm = scores.requiredFieldMatch || {};
  lines.push(`| Required-field exact-match | ${pct(efm.aggregate)} | ${fmtNum(efm.matched || 0)} / ${fmtNum(efm.totalReq || 0)} |`);
  lines.push(`| Required-field OR appropriate ask-back | ${pct(scores.requiredFieldOrAppropriateAskBack)} | (the D-07 OR-bar denominator) |`);
  lines.push(`| Appropriate ask-back | ${pct(scores.appropriateAskBack)} | (per-fixture) |`);
  const setEq = scores.setEquality || {};
  lines.push(`| Harvest set-equality (lineage) | ${pct(setEq.aggregate)} | over ${fmtNum(setEq.count || 0)} harvest fixtures |`);
  const b5 = scores.b5 || {};
  lines.push(`| B5 block_name precision | ${pct(b5.precision)} | ${fmtNum(b5.correct || 0)} / ${fmtNum(b5.extracted || 0)} extracted |`);
  lines.push(`| B5 block_name recall | ${pct(b5.recall)} | ${fmtNum(b5.correct || 0)} / ${fmtNum(b5.expected || 0)} expected |`);
  lines.push(`| Brier score (confidence vs correct) | ${num(scores.brier, 4)} | lower is better |`);
  lines.push(`| ECE (expected calibration error) | ${num(scores.ece, 4)} | lower is better |`);
  lines.push('');

  if (efm.perField && Object.keys(efm.perField).length) {
    lines.push('### Per-Field Exact-Match Breakdown');
    lines.push('');
    lines.push('| Field | Accuracy | Raw |');
    lines.push('|-------|----------|-----|');
    for (const [f, v] of Object.entries(efm.perField)) {
      const acc = v.total === 0 ? 0 : v.match / v.total;
      lines.push(`| ${f} | ${pct(acc)} | ${fmtNum(v.match)} / ${fmtNum(v.total)} |`);
    }
    lines.push('');
  }

  if (meta.notes) {
    lines.push('## Notes');
    lines.push('');
    lines.push(meta.notes);
    lines.push('');
  }

  // Grep-parseable verdict line is the absolute last non-empty line.
  lines.push(`## Verdict: [${verdict}]`);
  lines.push('');
  return lines.join('\n');
}

function writeReport(reportPath, scores, fixtureCount, verdict, meta = {}) {
  const out = buildReport(scores, fixtureCount, verdict, meta);
  fs.mkdirSync(path.dirname(reportPath), { recursive: true });
  fs.writeFileSync(reportPath, out, 'utf8');
  return reportPath;
}

module.exports = { writeReport, buildReport };
