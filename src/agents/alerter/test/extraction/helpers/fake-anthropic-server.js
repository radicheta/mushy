'use strict';

// Phase 38 Plan 03 Task 2: minimal fake Anthropic /v1/messages server.
// Mirrors fake-whisper-server.js factory shape.
//
// Returned handle exposes:
//   url               base URL of the server
//   requests[]        parsed JSON bodies received by POST /v1/messages (oldest-first)
//   responseQueue[]   array of canned response bodies; first push = first served
//   statusOverride    if number, /v1/messages returns that status once then clears
//   delayMs           if > 0, server sleeps this many ms before responding
//   close()           shuts down the server

const http = require('http');

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

function defaultMessageBody() {
  return {
    id: 'msg_fake',
    type: 'message',
    role: 'assistant',
    model: 'claude-sonnet-4-6',
    content: [{ type: 'text', text: 'ok' }],
    stop_reason: 'end_turn',
    usage: { input_tokens: 0, output_tokens: 0 },
  };
}

function start({ port = 0 } = {}) {
  return new Promise((resolve, reject) => {
    const requests = [];
    const responseQueue = [];
    const handle = {
      requests,
      responseQueue,
      statusOverride: null,
      delayMs: 0,
    };

    const server = http.createServer((req, res) => {
      const url = new URL(req.url, 'http://127.0.0.1');
      const p = url.pathname;

      if (req.method === 'POST' && p === '/v1/messages') {
        let body = '';
        req.on('data', (c) => { body += c; });
        req.on('end', async () => {
          try {
            if (handle.delayMs > 0) await sleep(handle.delayMs);
            const statusCode = handle.statusOverride || 200;
            handle.statusOverride = null;
            let parsed;
            try { parsed = JSON.parse(body); } catch (_) { parsed = {}; }
            requests.push(parsed);
            if (statusCode !== 200) {
              res.writeHead(statusCode, { 'Content-Type': 'text/plain' });
              res.end(`error ${statusCode}`);
              return;
            }
            const responseBody = responseQueue.length ? responseQueue.shift() : defaultMessageBody();
            res.writeHead(200, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify(responseBody));
          } catch (e) {
            res.writeHead(500);
            res.end('internal error');
          }
        });
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

// Helper: build a canned Anthropic response body that contains a single tool_use block.
function buildToolUseResponse(input, { toolUseId = 'tu_1', name = 'submit_extraction' } = {}) {
  return {
    id: 'msg_' + Math.random().toString(36).slice(2, 8),
    type: 'message',
    role: 'assistant',
    model: 'claude-sonnet-4-6',
    content: [{ type: 'tool_use', id: toolUseId, name, input }],
    stop_reason: 'tool_use',
    usage: { input_tokens: 100, output_tokens: 50 },
  };
}

module.exports = { start, buildToolUseResponse };
