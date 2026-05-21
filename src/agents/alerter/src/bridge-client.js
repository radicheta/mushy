'use strict';

const WebSocket = require('ws');

function createBridgeClient({
  wsUrl,
  healthUrl,
  onMessage,
  onLiveness,
  logger = console,
  minBackoffMs = 1000,
  maxBackoffMs = 30000,
}) {
  let ws = null;
  let backoffMs = minBackoffMs;
  let reconnectTimer = null;
  let healthTimer = null;
  let closed = false;
  let lastHealth = null;

  async function pollHealth() {
    try {
      const res = await fetch(healthUrl);
      if (!res.ok) throw new Error(`health ${res.status}`);
      const h = await res.json();
      lastHealth = h;
      onLiveness({
        wsConnected: true,
        rosConnected: !!(h.ros && h.ros.connected),
        humidifierLastMsgTs: h.humidifier ? h.humidifier.last_msg_ts : null,
        // Phase 46 D-02 consumer: forward bridge-aggregated fc1 liveness.
        // null when /health has no fc1 block (old bridge -- graceful degradation).
        fc1LastMsgTs: h.fc1 ? h.fc1.last_msg_ts : null,
        nowMs: Date.now(),
      });
    } catch (e) {
      logger.warn(`[bridge-client] /health poll failed: ${e.message}`);
      onLiveness({ wsConnected: true, rosConnected: false, humidifierLastMsgTs: null, fc1LastMsgTs: null, nowMs: Date.now() });
    }
  }

  function open() {
    if (closed) return;
    logger.info(`[bridge-client] connecting ${wsUrl}`);
    ws = new WebSocket(wsUrl);

    ws.on('open', async () => {
      logger.info('[bridge-client] ws_open');
      backoffMs = minBackoffMs;
      await pollHealth();
      // Phase 46 — keep state.fc1LastMsgTs warm. ws messages from the bridge
      // never carry fc1.last_msg_ts (it's a /health aggregate), so without a
      // periodic poll the alerter would snapshot it once at ws_open and stale
      // out. 10s cadence matches the chamber-dark trigger granularity.
      if (healthTimer) clearInterval(healthTimer);
      healthTimer = setInterval(pollHealth, 10000);
    });

    ws.on('message', (data) => {
      try {
        onMessage(JSON.parse(data.toString()));
      } catch (e) {
        logger.error(`[bridge-client] parse error: ${e.message}`);
      }
    });

    ws.on('close', () => {
      logger.warn(`[bridge-client] ws_close; backoff=${backoffMs}ms`);
      if (healthTimer) { clearInterval(healthTimer); healthTimer = null; }
      onLiveness({
        wsConnected: false,
        rosConnected: !!(lastHealth && lastHealth.ros && lastHealth.ros.connected),
        humidifierLastMsgTs: lastHealth && lastHealth.humidifier ? lastHealth.humidifier.last_msg_ts : null,
        // Phase 46: mirror pollHealth's fc1LastMsgTs from cached health snapshot.
        fc1LastMsgTs: lastHealth && lastHealth.fc1 ? lastHealth.fc1.last_msg_ts : null,
        nowMs: Date.now(),
      });
      if (closed) return;
      reconnectTimer = setTimeout(open, backoffMs);
      backoffMs = Math.min(backoffMs * 2, maxBackoffMs);
    });

    ws.on('error', (err) => {
      logger.error(`[bridge-client] ws_error: ${err.message}`);
      // 'close' will follow — don't double-schedule reconnect
    });
  }

  return {
    start() { open(); },
    close() {
      closed = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (healthTimer) { clearInterval(healthTimer); healthTimer = null; }
      if (ws) ws.terminate();
    },
    isConnected() { return !!(ws && ws.readyState === WebSocket.OPEN); },
  };
}

module.exports = { createBridgeClient };
