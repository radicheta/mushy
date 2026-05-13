'use strict';

// Phase 41 Plan 01 Task 1: Isolated jest config for the ingestion eval harness.
//
// Mirrors src/agents/alerter/test/eval/extraction/jest.config.js shape: separate
// jest project rooted at the alerter package, NOT triggered by default `npm test`.
// Run explicitly via `npm run test:eval-ingestion`.

module.exports = {
  displayName: 'eval-ingestion',
  testEnvironment: 'node',
  testMatch: ['<rootDir>/test/eval/ingestion/**/*.test.js'],
  testTimeout: 600000,
  maxWorkers: 1,
  rootDir: '../../..',
  verbose: true,
};
