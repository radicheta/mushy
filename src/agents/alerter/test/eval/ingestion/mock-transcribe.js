'use strict';

// Phase 41 Plan 01 Task 3: mocked Whisper transcribe factory.
//
// Same API surface as src/transcribe-client.js createTranscribeClient.
// Returns fixture.mock_transcript when the audio path matches an attachment
// in any registered fixture; else empty string.

function createMockTranscribe({ fixturesById = {} } = {}) {
  // Build a path-to-transcript lookup so transcribe({audioPath}) can resolve
  // without the caller passing the fixture id.
  const pathToTranscript = {};
  for (const name of Object.keys(fixturesById)) {
    const fx = fixturesById[name];
    const transcript = fx.mock_transcript || (fx.envelope && fx.envelope.mock_transcript) || '';
    for (const att of (fx.attachments || [])) {
      if (att && att.type === 'audio' && att.path) {
        pathToTranscript[att.path] = transcript;
      }
    }
  }

  async function transcribe(arg) {
    const p = typeof arg === 'string' ? arg : (arg && (arg.audioPath || arg.audio_path));
    const text = (p && pathToTranscript[p]) || '';
    return { ok: true, text };
  }

  return { transcribe };
}

module.exports = { createMockTranscribe };
