'use strict';

/**
 * RED skeleton tests for transcribe-client (Wave 2 implements the subject).
 * Skip-guard: if ../src/transcribe-client doesn't exist yet, all tests are skipped.
 * Remove the try/catch wrapper in Wave 2 when replacing with direct require.
 */

const fakeWhisperServer = require('./helpers/fake-whisper-server');

let createTranscribeClient;
let subjectMissing = false;

try {
  ({ createTranscribeClient } = require('../src/transcribe-client'));
} catch (_) {
  subjectMissing = true;
}

const describeFn = subjectMissing ? describe.skip : describe;

describeFn('createTranscribeClient', () => {
  let server;
  let client;

  beforeEach(async () => {
    server = await fakeWhisperServer.start();
    client = createTranscribeClient({ baseUrl: server.url, timeoutMs: 2000 });
  });

  afterEach(async () => {
    await server.close();
  });

  test('(R3) success — returns { ok: true, text, duration_ms, language } matching server canned response', async () => {
    const result = await client.transcribe({ audio_path: '/tmp/test.aac' });
    expect(result.ok).toBe(true);
    expect(typeof result.text).toBe('string');
    expect(typeof result.duration_ms).toBe('number');
    expect(typeof result.language).toBe('string');
  });

  test('(R3) server returns 500 — returns { ok: false, reason } without throwing', async () => {
    server.statusOverride = 500;
    const result = await client.transcribe({ audio_path: '/tmp/test.aac' });
    expect(result.ok).toBe(false);
    expect(typeof result.reason).toBe('string');
  });

  test('(R3) server delay > timeoutMs — returns { ok: false, reason: /abort|timeout/i } without throwing', async () => {
    server.delayMs = 5000;
    const fastClient = createTranscribeClient({ baseUrl: server.url, timeoutMs: 100 });
    const result = await fastClient.transcribe({ audio_path: '/tmp/test.aac' });
    expect(result.ok).toBe(false);
    expect(result.reason).toMatch(/abort|timeout/i);
  });

  test('(R3) POST body contains audio_path field equal to the value passed in', async () => {
    const audioPath = '/data/captures/abc123.aac';
    await client.transcribe({ audio_path: audioPath });
    expect(server.requests).toHaveLength(1);
    expect(server.requests[0].audio_path).toBe(audioPath);
  });
});
