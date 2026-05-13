'use strict';

// Phase 41 Plan 01 Task 5: smoke tests for the harness wiring.
//
// Pure-JS. No Anthropic, no Whisper, no fixture loaders. Exercises:
//   * jsonl-writer per-run uniqueness + append-only
//   * mock-extractor fixture-id lookup
//   * mock-transcribe path lookup
//   * run-harness parseArgs defaults + overrides

const fs = require('fs');
const path = require('path');
const os = require('os');
const { createJsonlWriter, openRunMetadataLine } = require('./jsonl-writer');
const { createMockExtractor } = require('./mock-extractor');
const { createMockTranscribe } = require('./mock-transcribe');
const { parseArgs } = require('./run-harness');

function tmpDir() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'ingest-smoke-'));
}

describe('jsonl-writer', () => {
  test('two consecutive constructions yield two distinct paths', () => {
    const dir = tmpDir();
    const a = createJsonlWriter({ corpus: 'unit', baseDir: dir });
    const b = createJsonlWriter({ corpus: 'unit', baseDir: dir });
    expect(a.path).not.toBe(b.path);
  });

  test('appends; never truncates', () => {
    const dir = tmpDir();
    const w = createJsonlWriter({ corpus: 'unit', baseDir: dir });
    w.write({ a: 1 });
    w.write({ b: 2 });
    const lines = fs.readFileSync(w.path, 'utf8').trim().split('\n');
    expect(lines.length).toBe(2);
    expect(JSON.parse(lines[0])).toEqual({ a: 1 });
    expect(JSON.parse(lines[1])).toEqual({ b: 2 });
  });

  test('openRunMetadataLine includes all required keys', () => {
    const m = openRunMetadataLine({ corpus: 'unit', runId: 'abc', model: 'm', mode: 'mock', smoke: true, cap_usd: 5 });
    expect(m).toMatchObject({ corpus: 'unit', run_id: 'abc', mode: 'mock', smoke: true, model: 'm', cap_usd: 5 });
    expect(typeof m.ts).toBe('string');
  });
});

describe('mock-extractor', () => {
  test('returns expected.fields for fixture without mockResponse', async () => {
    const fixturesById = { fx1: { expected: { fields: { block_name: 'X', seq: 1 } } } };
    const e = createMockExtractor({ fixturesById });
    const r = await e.extract({ fixtureName: 'fx1' });
    expect(r.ok).toBe(true);
    expect(r.draft).toEqual({ block_name: 'X', seq: 1 });
  });

  test('returns mockResponse verbatim when present', async () => {
    const fixturesById = { fx1: { expected: { fields: {} }, mockResponse: { ok: false, reason: 'forced' } } };
    const e = createMockExtractor({ fixturesById });
    const r = await e.extract({ fixtureName: 'fx1' });
    expect(r).toEqual({ ok: false, reason: 'forced' });
  });
});

describe('mock-transcribe', () => {
  test('returns empty string for unknown path', async () => {
    const t = createMockTranscribe({ fixturesById: {} });
    const r = await t.transcribe({ audioPath: '/no/such.m4a' });
    expect(r.text).toBe('');
  });

  test('returns mock_transcript when audio path matches a fixture attachment', async () => {
    const fixturesById = {
      fx1: {
        mock_transcript: 'hello world',
        attachments: [{ type: 'audio', path: '/tmp/a.m4a' }],
      },
    };
    const t = createMockTranscribe({ fixturesById });
    const r = await t.transcribe({ audioPath: '/tmp/a.m4a' });
    expect(r.text).toBe('hello world');
  });
});

describe('run-harness parseArgs', () => {
  test('defaults: corpus=synthetic, smoke=false, live=false, capUsd=20', () => {
    const a = parseArgs(['node', 'h']);
    expect(a).toEqual({ corpus: 'synthetic', smoke: false, live: false, capUsd: 20, noReport: false });
  });

  test('overrides parsed correctly', () => {
    const a = parseArgs(['node', 'h', '--corpus', 'paper-log', '--smoke', '--live', '--cap-usd', '7.5', '--no-report']);
    expect(a).toEqual({ corpus: 'paper-log', smoke: true, live: true, capUsd: 7.5, noReport: true });
  });

  test('--corpus=X equals form', () => {
    const a = parseArgs(['node', 'h', '--corpus=audio']);
    expect(a.corpus).toBe('audio');
  });
});
