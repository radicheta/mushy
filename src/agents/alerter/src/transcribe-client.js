'use strict';

/**
 * createTranscribeClient — HTTP client for the whisper-transcribe sibling container.
 *
 * Mirrors the shape of signal.js `send()` (factory + AbortController + timeout +
 * try/catch returning a discriminated `{ ok }` result). Never throws.
 *
 * Accepts both calling conventions:
 *   client.transcribe('/path/to/audio.aac')          // capture.js (string)
 *   client.transcribe({ audio_path: '/path/...' })   // wave-0 RED test (object)
 *
 * Resolves `apiUrl` from { apiUrl } OR { baseUrl } for symmetry with the
 * fake-whisper-server harness, which exposes `server.url`.
 *
 * Returns:
 *   { ok: true, text, duration_ms, language }
 *   { ok: false, reason: 'timeout' | 'whisper 500: ...' | <error message> }
 */
function createTranscribeClient({ apiUrl, baseUrl, timeoutMs = 200000, logger = console } = {}) {
  const url = apiUrl || baseUrl;
  if (!url) throw new Error('createTranscribeClient: apiUrl (or baseUrl) is required');

  async function transcribe(arg) {
    const audioPath = typeof arg === 'string' ? arg : (arg && arg.audio_path);
    if (!audioPath) {
      return { ok: false, reason: 'missing audio_path' };
    }

    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      const res = await fetch(`${url}/transcribe`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ audio_path: audioPath }),
        signal: ctrl.signal,
      });
      if (!res.ok) {
        const text = await res.text().catch(() => '');
        return { ok: false, reason: `whisper ${res.status}: ${text.slice(0, 200)}` };
      }
      const json = await res.json();
      return {
        ok: true,
        text: json.text || '',
        duration_ms: json.duration_ms ?? 0,
        language: json.language || 'unknown',
      };
    } catch (e) {
      logger.warn(`[transcribe] ${e.name}: ${e.message}`);
      return { ok: false, reason: e.name === 'AbortError' ? 'timeout' : e.message };
    } finally {
      clearTimeout(timer);
    }
  }

  return { transcribe };
}

module.exports = { createTranscribeClient };
