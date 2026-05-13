'use strict';

// Phase 42 plan 42-01: jest project for tools/.
// Mocked farmOS responses only; no live HTTP.

module.exports = {
  rootDir: '..',
  testEnvironment: 'node',
  testMatch: ['<rootDir>/test/**/*.test.js'],
  verbose: true,
};
