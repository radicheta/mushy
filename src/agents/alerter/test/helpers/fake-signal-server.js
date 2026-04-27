const http = require('http');

/**
 * Minimal fake signal-cli-rest-api server for integration tests.
 * Implements:
 *   POST /v2/send   -> 201 { timestamp }; pushes body into sent[]
 *   GET  /v1/receive/:sender -> 200; drains received[]
 *   GET  /v1/accounts -> 200 ["+15551234567"]
 *
 * Returned handle exposes:
 *   sent[]          - requests received by /v2/send
 *   received[]      - queue to drain via /v1/receive
 *   statusOverride  - if set to a number, /v2/send returns that status code once, then clears
 *   delayMs         - if > 0, /v2/send sleeps this many ms before responding
 *
 * @param {object} [options]
 * @param {number} [options.port=0] - Port to bind; 0 = ephemeral
 * @returns {Promise<{url: string, sent: Array, received: Array, close: Function}>}
 */
function start({ port = 0 } = {}) {
  return new Promise((resolve, reject) => {
    const sent = [];
    const received = [];
    const handle = { sent, received, statusOverride: null, delayMs: 0 };

    function sleep(ms) {
      return new Promise((r) => setTimeout(r, ms));
    }

    const server = http.createServer((req, res) => {
      const url = new URL(req.url, 'http://127.0.0.1');
      const path = url.pathname;

      if (req.method === 'POST' && path === '/v2/send') {
        let body = '';
        req.on('data', (chunk) => { body += chunk; });
        req.on('end', async () => {
          try {
            if (handle.delayMs > 0) {
              await sleep(handle.delayMs);
            }
            const statusCode = handle.statusOverride || 201;
            handle.statusOverride = null;
            if (statusCode !== 201) {
              res.writeHead(statusCode, { 'Content-Type': 'text/plain' });
              res.end(`error ${statusCode}`);
              return;
            }
            const parsed = JSON.parse(body);
            sent.push(parsed);
            res.writeHead(201, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify({ timestamp: Date.now() }));
          } catch (e) {
            res.writeHead(400);
            res.end('bad json');
          }
        });
        return;
      }

      if (req.method === 'GET' && path.startsWith('/v1/receive/')) {
        const drained = received.splice(0);
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify(drained));
        return;
      }

      if (req.method === 'GET' && path === '/v1/accounts') {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify(['+15551234567']));
        return;
      }

      if (req.method === 'GET' && path.startsWith('/v1/attachments/')) {
        const attId = decodeURIComponent(path.slice('/v1/attachments/'.length));
        if (attId === 'not-found-sentinel') {
          res.writeHead(404, { 'Content-Type': 'text/plain' });
          res.end('not found');
          return;
        }
        // Return a fixed 3-byte buffer body for any other attachment id
        const body = Buffer.from([0x41, 0x42, 0x43]); // "ABC"
        res.writeHead(200, { 'Content-Type': 'application/octet-stream' });
        res.end(body);
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
