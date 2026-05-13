'use strict';

// Phase 41 Plan 01 Task 3: mocked LLM extractor factory.
//
// Same API surface as src/extraction/extractor.js createExtractor so the
// run-harness can swap mock vs live via dependency injection (no jest module
// mocking). See 41-RESEARCH.md section 9.
//
// Lookup:
//   1. fixturesById[fixtureName].mockResponse (loaded from mock-response.json)
//      returned verbatim.
//   2. else fixturesById[fixtureName].expected -> trivially-passing result
//      { ok: true, draft: expected.fields, per_field_confidence: {} }.

function createMockExtractor({ fixturesById = {}, logger = console } = {}) {
  return {
    async extract(payload = {}) {
      const name = payload.fixtureName;
      const fx = fixturesById[name];
      if (!fx) {
        return { ok: false, reason: `mock-extractor: no fixture for ${name}`, draft: null, per_field_confidence: {} };
      }
      if (fx.mockResponse) {
        return fx.mockResponse;
      }
      const exp = fx.expected || {};
      return {
        ok: true,
        draft: exp.fields || {},
        per_field_confidence: {},
        tokens: null,
        cost_usd: 0,
      };
    },
  };
}

module.exports = { createMockExtractor };
