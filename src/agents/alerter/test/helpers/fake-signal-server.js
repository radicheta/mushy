const http = require('http');

/**
 * Minimal fake signal-cli-rest-api server for integration tests.
 * Implements:
 *   POST /v2/send   -> 201 { timestamp }; pushes body into sent[]
 *   GET  /v1/receive/:sender -> 200; drains received[]
 *   GET  /v1/accounts -> 200 ["+15551234567"]
 *
 * @param {object} [options]
 * @param {number} [options.port=0] - Port to bind; 0 = ephemeral
 * @returns {Promise<{url: string, sent: Array, received: Array, close: Function}>}
 */
function start({ port = 0 } = {}) {
  return new Promise((resolve, reject) => {
    const sent = [];
    const received = [];

    const server = http.createServer((req, res) => {
      const url = new URL(req.url, 'http://127.0.0.1');
      const path = url.pathname;

      if (req.method === 'POST' && path === '/v2/send') {
        let body = '';
        req.on('data', (chunk) => { body += chunk; });
        req.on('end', () => {
          try {
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

      res.writeHead(404);
      res.end('not found');
    });

    server.listen(port, '127.0.0.1', () => {
      const { port: boundPort } = server.address();
      const url = `http://127.0.0.1:${boundPort}`;
      resolve({
        url,
        sent,
        received,
        close: () => new Promise((res) => server.close(res))
      });
    });

    server.on('error', reject);
  });
}

module.exports = { start };
