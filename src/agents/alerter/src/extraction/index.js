'use strict';

// Phase 38 extraction module barrel. Re-exports the public factory and the
// per-module submodules for convenient test wiring.

const pipeline = require('./pipeline');
const extractionDb = require('./extraction-db');
const stateMachine = require('./state-machine');
const previewBuilder = require('./preview-builder');
const extractor = require('./extractor');

module.exports = {
  createExtractionPipeline: pipeline.createExtractionPipeline,
  extractionDb,
  stateMachine,
  previewBuilder,
  extractor,
};
