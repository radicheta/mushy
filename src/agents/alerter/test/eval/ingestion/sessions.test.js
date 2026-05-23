'use strict';

// Phase 49 Plan 02: named-regression CI gate for real-data inoc sessions.
//
// Iterates the sessions/ corpus (loaded via sessions-loader), filters to
// entries with manifest.regression_guard === true, and asserts the
// extractor produces a draft matching ground-truth.json on the key fields:
//   { type, event_date, groups[].parent.value, groups[].species.value,
//     groups[].qty.value, groups[].child_block_names.value }
//
// Default (hermetic CI): the real extractor is instantiated with a mock
// Anthropic client that returns the fixture's mock-extraction.json verbatim.
// This exercises the actual extractor.extract() code path (validator,
// retry logic, packResult shape) -- a regression in any of those surfaces
// here.
//
// EVAL_RUN_LIVE=1 branch: real Anthropic client + real Whisper (Plan 04
// scope). Wired here for completeness; this plan does NOT invoke it.
//
// Mock-extraction.json shape: the raw @anthropic-ai/sdk tool_use response
// (mirrors src/agents/alerter/test/extraction/integration/seeding-session-may22.test.js
// makeMockAnthropicClient pattern from Phase 47-05).

const fs = require('fs');
const path = require('path');

const { loadSessionsCorpus } = require('./sessions-loader');
const { createExtractor } = require('../../../src/extraction/extractor');

const SESSIONS_DIR = path.resolve(__dirname, 'fixtures/sessions');

const liveMode = process.env.EVAL_RUN_LIVE === '1' && !!process.env.ANTHROPIC_API_KEY;

// --- helpers ----------------------------------------------------------------

function makeMockAnthropicClient(mockResponse) {
  // Mimics @anthropic-ai/sdk's client.messages.create() -> tool_use response.
  // Returns the loaded mock-extraction.json verbatim on every call.
  return {
    messages: {
      create: jest.fn(async () => mockResponse),
    },
  };
}

// Project a draft down to the key-fields tuple the equality assertion keys off.
// per-field confidence + sources arrays legitimately drift across runs (mock
// vs live, different model versions); only the .value of each provenanced
// field participates in equality.
function projectKeyFields(draft) {
  if (!draft) return null;
  return {
    type: draft.type,
    event_date: draft.event_date,
    groups: (draft.groups || []).map((g) => ({
      parent: g && g.parent && g.parent.value,
      species: g && g.species && g.species.value,
      qty: g && g.qty && g.qty.value,
      child_block_names: (g && g.child_block_names && g.child_block_names.value) || [],
    })),
  };
}

function buildCaptures(session) {
  // Best-effort capture envelope: one capture with a placeholder transcript
  // string (under mock-mode the extractor never reads it -- the canned response
  // ignores input). The shape mirrors what pipeline.js builds on the live path.
  return [
    {
      captureId: `CAP_${session.name}`,
      text: null,
      transcript: `[mock] ${session.name} -- see fixture/transcript.txt for the real text under EVAL_RUN_LIVE=1`,
      images: [],
    },
  ];
}

// --- gate ------------------------------------------------------------------

const ALL = loadSessionsCorpus(SESSIONS_DIR, { logger: { warn: () => {} } });
const NAMED = ALL.filter((s) => s.manifest && s.manifest.regression_guard === true);

if (NAMED.length === 0) {
  // Surface as a hard failure rather than a silently-empty describe block.
  // Discovering zero named regression entries means the loader broke OR the
  // fixtures were deleted -- both are CI red.
  describe('Phase 49 named-regression gate', () => {
    test('must discover at least one named-regression fixture', () => {
      throw new Error(
        `sessions-loader found 0 manifest.regression_guard:true entries under ${SESSIONS_DIR}. ` +
          'This plan ships two: 2026-05-22_inoc_santi and 2026-05-12_inoc_santi.',
      );
    });
  });
}

describe('Phase 49 named-regression gate (mock-mode hermetic CI)', () => {
  if (liveMode) {
    // Live-fire belongs to Plan 04. Loud signal here that we did NOT cross the
    // network on this run.
    // eslint-disable-next-line no-console
    console.log(
      '[sessions.test] EVAL_RUN_LIVE=1 detected -- live branch is Plan 04 scope. Running mock-mode in this plan; live invocation deferred to 49-04.',
    );
  }

  it.each(NAMED.map((s) => [s.name, s]))(
    'named regression: %s extractor draft matches ground-truth on key fields',
    async (_name, session) => {
      // Load the canned mock-extraction.json that the mock Anthropic client
      // will return. Fail loud if missing.
      const mockPath = path.join(session.dir, 'mock-extraction.json');
      expect(fs.existsSync(mockPath)).toBe(true);
      const mockResponse = JSON.parse(fs.readFileSync(mockPath, 'utf8'));

      const client = makeMockAnthropicClient(mockResponse);
      const extractor = createExtractor({
        apiKey: 'sk-mock-49-02',
        client,
        logger: { warn: () => {}, info: () => {}, error: () => {}, debug: () => {} },
      });

      const result = await extractor.extract({
        captures: buildCaptures(session),
        inFlightDraft: null,
      });

      // Sanity: extractor reports ok + the mock client was hit exactly once
      // (no retry path needed because the mock returns a schema-valid draft).
      expect(result.ok).toBe(true);
      expect(client.messages.create).toHaveBeenCalledTimes(1);

      // The packResult back-compat field surfaces drafts[0].draft on .draft.
      expect(result.draft).toBeTruthy();
      expect(result.draft.type).toBe('seeding_session');

      // Equality on key fields against ground-truth.
      const actualKey = projectKeyFields(result.draft);
      const expectedKey = projectKeyFields(session.groundTruth);

      // Diagnostic surface BEFORE the strict equality, so test output
      // explains the failure shape if the structure drifts (group count,
      // child count, individual field). toEqual on the projected tuples is
      // the actual ship-gate assertion.
      expect(actualKey.type).toBe(expectedKey.type);
      expect(actualKey.event_date).toBe(expectedKey.event_date);
      expect(actualKey.groups).toHaveLength(expectedKey.groups.length);
      const totalChildrenActual = actualKey.groups.reduce(
        (n, g) => n + (g.child_block_names ? g.child_block_names.length : 0),
        0,
      );
      const totalChildrenExpected = expectedKey.groups.reduce(
        (n, g) => n + (g.child_block_names ? g.child_block_names.length : 0),
        0,
      );
      expect(totalChildrenActual).toBe(totalChildrenExpected);

      expect(actualKey).toEqual(expectedKey);
    },
  );
});

// --- EVAL_RUN_LIVE wiring (Plan 04 ship-gate scope) -------------------------
//
// Documents the live-fire path without exercising it here. Plan 04 will
// extend this with a real Whisper transcript + real Anthropic client and
// remove the .skip / early-return.
describe('Phase 49 named-regression gate (live-fire path -- Plan 04 scope)', () => {
  it('LIVE-FIRE: documents the EVAL_RUN_LIVE=1 invocation path', () => {
    if (process.env.EVAL_RUN_LIVE !== '1') {
      // eslint-disable-next-line no-console
      console.log(
        '  skipped: set EVAL_RUN_LIVE=1 + ANTHROPIC_API_KEY + WHISPER_URL to run live-fire (Plan 04 scope)',
      );
      return;
    }
    // Plan 04 will implement: load session.audioPath through Whisper,
    // load session.photoPath through pipeline.loadImageBlocks, build
    // real captures, instantiate createExtractor with apiKey from env,
    // assert the live model produces a draft equal-on-key-fields to
    // session.groundTruth. Until Plan 04 lands, EVAL_RUN_LIVE=1 here is
    // explicitly a no-op (the mock-mode it.each above is the real gate).
    // eslint-disable-next-line no-console
    console.log(
      '[sessions.test] EVAL_RUN_LIVE=1 set but live-fire wiring is Plan 04 scope; see 49-04 PLAN/SUMMARY.',
    );
  });
});
