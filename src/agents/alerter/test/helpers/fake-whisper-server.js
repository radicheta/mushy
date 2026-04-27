const http = require('http');

/**
 * Minimal fake Whisper transcription server for integration tests.
 * Mirrors the factory shape of fake-signal-server.js.
 *
 * Implements:
 *   POST /transcribe -> 200 { text, duration_ms, language, language_probability }
 *                       or statusOverride if set; sleeps delayMs first if > 0
 *   GET  /health     -> 200 { ok: true, model_loaded: true }
 *
 * Returned handle exposes:
 *   url               - base URL of the server
 *   requests[]        - bodies received by POST /transcribe
 *   statusOverride    - if set to a number, /transcribe returns that status once, then clears
 *   delayMs           - if > 0, /transcribe sleeps this many ms before responding
 *   transcribeResponse - if set, overrides the default canned transcription response
 *   close()           - shuts down the server
 *
 * @param {object} [options]
 * @param {number} [options.port=0] - Port to bind; 0 = ephemeral
 * @returns {Promise<{url: string, requests: Array, statusOverride: null|number, delayMs: number, transcribeResponse: null|object, close: Function}>}
 */
function start({ port = 0 } = {}) {
  return new Promise((resolve, reject) => {
    const requests = [];
    const handle = {
      requests,
      statusOverride: null,
      delayMs: 0,
      transcribeResponse: null,
    };

    function sleep(ms) {
      return new Promise((r) => setTimeout(r, ms));
    }

    const defaultTranscribeResponse = {
      text: 'hello world',
      duration_ms: 1234,
      language: 'en',
      language_probability: 0.98,
    };

    const server = http.createServer((req, res) => {
      const url = new URL(req.url, 'http://127.0.0.1');
      const path = url.pathname;

      if (req.method === 'POST' && path === '/transcribe') {
        let body = '';
        req.on('data', (chunk) => { body += chunk; });
        req.on('end', async () => {
          try {
            if (handle.delayMs > 0) {
              await sleep(handle.delayMs);
            }
            const statusCode = handle.statusOverride || 200;
            handle.statusOverride = null;
            if (statusCode !== 200) {
              res.writeHead(statusCode, { 'Content-Type': 'text/plain' });
              res.end(`error ${statusCode}`);
              return;
            }
            let parsed;
            try {
              parsed = JSON.parse(body);
            } catch (_) {
              parsed = {};
            }
            requests.push(parsed);
            const responseBody = handle.transcribeResponse || defaultTranscribeResponse;
            res.writeHead(200, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify(responseBody));
          } catch (e) {
            res.writeHead(500);
            res.end('internal error');
          }
        });
        return;
      }

      if (req.method === 'GET' && path === '/health') {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ ok: true, model_loaded: true }));
        return;
      }

      res.writeHead(404);
      res.end('not found');
    });

    server.listen(port, '127.0.0.1', () => {
      const { port: boundPort } = server.address();
      handle.url = `http://127.0.0.1:${boundPort}`;
      handle.close = () => new Promise((res) => server.close(res));
      resolve(handle);
    });

    server.on('error', reject);
  });
}

module.exports = { start };
