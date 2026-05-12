'use strict';

// Phase 38 Plan 07 Task 1: Eval-tier jest config (D-07 ship-gate).
//
// This config is INTENTIONALLY isolated from the default `npm test` run.
// Default jest.config.js at the alerter root uses testMatch '**/test/**/*.test.js'
// but ignores nothing under test/eval, so we shipped a global testPathIgnorePatterns
// update at the same time as this file. See package.json `eval:extraction` script.

module.exports = {
  displayName: 'eval:extraction',
  testEnvironment: 'node',
  testMatch: ['<rootDir>/test/eval/extraction/**/*.test.js'],
  testTimeout: 600000,
  maxWorkers: 1,
  rootDir: '../../..',
  verbose: true,
};
