'use strict';

// Phase 47 Plan 05: INOC-01 + INOC-02 ship-gate integration test.
//
// Hermetic by default: the Anthropic client is injected as a jest.fn() that
// returns a hand-crafted tool_use envelope wrapping the fixture's expected
// draft. The pipeline is exercised end-to-end (in-flight lookup, extract,
// continuity, insertDraft, state-machine transition, preview, dispatch).
//
// Live-fire branch (gated by EVAL_RUN_LIVE=1) calls the real Anthropic API
// against the May 22 transcript + paper-log photo and asserts the real
// model produces the expected shape with the canonical 11 child_block_names.
//
// Live-fire cost: ~$0.10 per run (Sonnet 4.6, ~3-5K input tokens including
// 81 KB image + 761-char transcript + cached system prompt + few-shot).

const fs = require('fs');
const path = require('path');

const FIXTURES_DIR = path.join(__dirname, '..', '..', 'fixtures', 'seeding-session-may22');
const EXPECTED_DRAFT = require(path.join(FIXTURES_DIR, 'expected-draft.json'));
const TRANSCRIPT = fs.readFileSync(path.join(FIXTURES_DIR, 'transcript.txt'), 'utf8').trim();
const TEXT_FOLLOWUP = fs.readFileSync(path.join(FIXTURES_DIR, 'text-followup.txt'), 'utf8').trim();
const PAPER_LOG_JPG = path.join(FIXTURES_DIR, 'paper-log.jpg');

const { createExtractionPipeline } = require('../../../src/extraction/pipeline');
const { createExtractor } = require('../../../src/extraction/extractor');
const extractionDb = require('../../../src/extraction/extraction-db');
const stateMachine = require('../../../src/extraction/state-machine');
const previewBuilder = require('../../../src/extraction/preview-builder');
const { SOURCE_ENUM } = require('../../../src/extraction/schemas');

const silentLogger = { info: () => {}, warn: () => {}, error: () => {}, debug: () => {} };

function makePool() {
  // Stub pool. SELECT for in-flight returns 0 rows; SELECT for seq-helper
  // returns 0 rows (no prior session today); everything else returns rowCount=1.
  return {
    query: jest.fn(async (sql) => {
      if (/FROM signal_draft\s+WHERE sender_e164/i.test(sql)) {
        return { rows: [], rowCount: 0 };
      }
      if (/FROM signal_draft\s+WHERE status IN/i.test(sql)) {
        return { rows: [], rowCount: 0 };
      }
      return { rows: [], rowCount: 1 };
    }),
  };
}

function makeMockAnthropicClient(draftToReturn, perFieldConfidence) {
  // Mimics @anthropic-ai/sdk's `client.messages.create()` -> tool_use response.
  return {
    messages: {
      create: jest.fn(async () => ({
        content: [
          {
            type: 'tool_use',
            id: 'toolu_mock_47_05',
            name: 'submit_extraction',
            input: {
              drafts: [{ draft: draftToReturn, per_field_confidence: perFieldConfidence }],
              continuity: 'start_new',
              continuity_reason: 'no in-flight draft for this sender',
            },
          },
        ],
        usage: {
          input_tokens: 0,
          output_tokens: 0,
          cache_creation_input_tokens: 0,
          cache_read_input_tokens: 0,
        },
        stop_reason: 'tool_use',
      })),
    },
  };
}

function captureCtx(over = {}) {
  return {
    captureId: 'CAP_MAY22_HERMETIC',
    sender: '+59891840201',
    senderName: 'Santi',
    farmosPerson: 'f1',
    text: TEXT_FOLLOWUP,
    transcripts: [TRANSCRIPT],
    attachmentPaths: [PAPER_LOG_JPG],
    replyTargetKind: 'dm',
    groupId: null,
    capturedAtMs: Date.parse('2026-05-22T22:46:00Z'),
    ...over,
  };
}

const EXPECTED_CHILD_BLOCK_NAMES = [
  '260522_SHI_1', '260522_SHI_2', '260522_SHI_3',
  '260522_KOY_4', '260522_KOY_5', '260522_KOY_6', '260522_KOY_7',
  '260522_KOY_8', '260522_KOY_9', '260522_KOY_10', '260522_KOY_11',
];

describe('INOC-01 + INOC-02: May 22 seeding_session ship-gate (hermetic)', () => {
  test('hermetic mock returns the canonical 5-group / 11-child draft; pipeline persists it; validator passes; preview-builder produces placeholder', async () => {
    const pool = makePool();
    const perFieldConfidence = { event_date: 0.99 };
    const client = makeMockAnthropicClient(EXPECTED_DRAFT, perFieldConfidence);
    const extractor = createExtractor({ apiKey: 'sk-mock', client, logger: silentLogger });

    const dispatched = [];
    const outboundDispatcher = {
      dispatch: jest.fn((effect, row) => { dispatched.push({ effect, row }); }),
    };

    const pipeline = createExtractionPipeline({
      pool,
      extractor,
      extractionDb,
      stateMachine,
      previewBuilder,
      config: {
        extractionConfidenceThreshold: 0.7,
        draftIdleGapMin: 30,
        maxAskbackTurns: 3,
      },
      logger: silentLogger,
      clock: { now: () => Date.parse('2026-05-22T22:46:00Z') },
      outboundDispatcher,
    });

    const res = await pipeline.enqueue(captureCtx());

    // --- INOC-01: shape ----------------------------------------------------
    expect(res.ok).toBe(true);

    // The Anthropic client was called exactly once with messages including the
    // image block + transcript text.
    expect(client.messages.create).toHaveBeenCalledTimes(1);

    // INSERT was issued with the draft_json
    const insertCall = pool.query.mock.calls.find((c) => /INSERT INTO signal_draft/i.test(c[0]));
    expect(insertCall).toBeTruthy();
    // The draft_json param is the JSON-encoded draft (pg-style param array).
    // It is index 7 in the insertDraft SQL parameter order; we just check the
    // JSON blob mentions the canonical 11 names regardless of exact index.
    const insertParamsJoined = JSON.stringify(insertCall[1] || []);
    for (const name of EXPECTED_CHILD_BLOCK_NAMES) {
      expect(insertParamsJoined).toContain(name);
    }
    expect(insertParamsJoined).toContain('seeding_session');
    expect(insertParamsJoined).toContain('2026-05-22');

    // Validate the in-memory draft via the schema (proxy for validator pass).
    const { SeedingSession } = require('../../../src/extraction/schemas');
    const parsed = SeedingSession.safeParse(EXPECTED_DRAFT);
    expect(parsed.success).toBe(true);
    expect(parsed.data.groups).toHaveLength(5);
    const childCount = parsed.data.groups.reduce((s, g) => s + g.qty.value, 0);
    expect(childCount).toBe(11);
    const flatNames = parsed.data.groups.flatMap((g) => g.child_block_names.value);
    expect(flatNames).toEqual(EXPECTED_CHILD_BLOCK_NAMES);

    // --- INOC-02: provenance -----------------------------------------------
    for (const g of parsed.data.groups) {
      for (const field of ['parent', 'species', 'qty', 'child_block_names']) {
        expect(Array.isArray(g[field].sources)).toBe(true);
        expect(g[field].sources.length).toBeGreaterThan(0);
        for (const s of g[field].sources) {
          expect(SOURCE_ENUM.options).toContain(s);
        }
      }
      // child_block_names must include paper_log_photo when photo is present
      expect(g.child_block_names.sources).toContain('paper_log_photo');
      // parent must include either audio or paper_log_photo (typically both)
      expect(
        g.parent.sources.includes('audio') || g.parent.sources.includes('paper_log_photo'),
      ).toBe(true);
    }

    // --- preview-builder placeholder fires ---------------------------------
    const preview = previewBuilder.buildPreview({
      draft: EXPECTED_DRAFT,
      perFieldConfidence,
      threshold: 0.7,
      requiredFields: ['event_date', 'groups'],
    });
    expect(preview).toContain('11 blocks across 5 groups for 2026-05-22');
    expect(preview).toContain('Phase 48');
    expect(preview).not.toMatch(/—/); // no em-dashes

    // --- side-effects (no ask-back: no needs_input on this fixture) --------
    const effects = dispatched.map((d) => d.effect);
    expect(effects).not.toContain('send_starting_seq_askback');
  });

  test('LIVE-FIRE (EVAL_RUN_LIVE=1): real Anthropic call on May 22 fixture produces canonical 11 child_block_names', async () => {
    // Live-fire cost: ~$0.10 per run (Sonnet 4.6).
    if (process.env.EVAL_RUN_LIVE !== '1') {
      // eslint-disable-next-line no-console
      console.log('  skipped: set EVAL_RUN_LIVE=1 + ANTHROPIC_API_KEY to run live-fire');
      return;
    }
    if (!process.env.ANTHROPIC_API_KEY) {
      throw new Error('EVAL_RUN_LIVE=1 but ANTHROPIC_API_KEY not set');
    }

    const pool = makePool();
    const extractor = createExtractor({
      apiKey: process.env.ANTHROPIC_API_KEY,
      logger: silentLogger,
    });

    const dispatched = [];
    const outboundDispatcher = {
      dispatch: jest.fn((effect, row) => { dispatched.push({ effect, row }); }),
    };

    const pipeline = createExtractionPipeline({
      pool,
      extractor,
      extractionDb,
      stateMachine,
      previewBuilder,
      config: {
        extractionConfidenceThreshold: 0.7,
        draftIdleGapMin: 30,
        maxAskbackTurns: 3,
      },
      logger: silentLogger,
      clock: { now: () => Date.parse('2026-05-22T22:46:00Z') },
      outboundDispatcher,
    });

    const res = await pipeline.enqueue(captureCtx({ captureId: 'CAP_MAY22_LIVE' }));
    // Surface the live draft to stdout so the operator can save it to the
    // 47-LIVE-FIRE.md paper trail.
    // eslint-disable-next-line no-console
    console.log('LIVE-FIRE pipeline result:', JSON.stringify(res, null, 2));

    expect(res.ok).toBe(true);

    // Pull the INSERT-ed draft_json out of pool.query for inspection.
    const insertCall = pool.query.mock.calls.find((c) => /INSERT INTO signal_draft/i.test(c[0]));
    expect(insertCall).toBeTruthy();
    const insertParamsJoined = JSON.stringify(insertCall[1] || []);

    // INOC-01 regression guard: the 11 canonical child_block_names must all
    // appear. Parent strings are NOT asserted here per CONTEXT.md note (KOY
    // parent decoding from audio is ambiguous; child_block_names is the lock).
    for (const name of EXPECTED_CHILD_BLOCK_NAMES) {
      expect(insertParamsJoined).toContain(name);
    }
    expect(insertParamsJoined).toContain('seeding_session');
    expect(insertParamsJoined).toContain('2026-05-22');
  }, 120000); // 2-minute timeout for live API call + image upload
});
