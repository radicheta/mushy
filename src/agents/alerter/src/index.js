'use strict';

/**
 * Alerter entrypoint — wires config, state machine, signal client, bridge client,
 * heartbeat scheduler, and receive loop.
 *
 * Exports createAlerter({env, clock, logger}) as a test seam.
 * In container execution, require.main === module calls main() which also
 * registers unhandledRejection / uncaughtException handlers (Pitfall 4 / T-17-04).
 */

const { load, maskNumber } = require('./config');
const stateLib = require('./state');
const { createSignalClient } = require('./signal');
const { createBridgeClient } = require('./bridge-client');
const { createHeartbeatScheduler } = require('./heartbeat');
const { createReceiveLoop } = require('./receive-loop');

/**
 * createAlerter({ env, clock, logger }) -> { dispatch, close, _state }
 *
 * @param {object} [opts]
 * @param {object} [opts.env]    - env vars (default: process.env)
 * @param {Function} [opts.clock] - () => nowMs (default: Date.now)
 * @param {object} [opts.logger] - logger (default: console)
 * @returns {{ dispatch: Function, close: Function, _state: Function }}
 */
function createAlerter({ env = process.env, clock = Date.now, logger = console } = {}) {
  const config = load(env);

  logger.info(`[boot] alerter starting — sender=${maskNumber(config.signalSender)} recipient=${maskNumber(config.signalRecipient)}`);
  logger.info(`[boot] bridge=${config.bridgeWsUrl} signal=${config.signalApiUrl} tz=${config.timezone}`);

  const signalClient = createSignalClient({
    apiUrl: config.signalApiUrl,
    sender: config.signalSender,
    recipient: config.signalRecipient,
    maxSendsPerHour: config.maxSendsPerHour,
    logger,
  });

  let state = stateLib.initialState(clock());

  async function applyEvent(event) {
    const result = stateLib.transition(state, event, clock(), config);
    state = result.next;
    for (const action of result.actions) {
      try {
        if (action.kind === 'send' || action.kind === 'recovery') {
          await signalClient.send(action.body);
        } else if (action.kind === 'heartbeat') {
          // Heartbeat bypasses the hourly send cap (bypassCap: true)
          await signalClient.send(action.body, { bypassCap: true });
        } else if (action.kind === 'snooze_ack') {
          await signalClient.send(action.body);
        }
      } catch (e) {
        logger.error(`[apply] action ${action.kind} failed: ${e.message}`);
      }
    }
  }

  const bridge = createBridgeClient({
    wsUrl: config.bridgeWsUrl,
    healthUrl: config.bridgeHealthUrl,
    onMessage(msg) {
      // Route bridge WS shapes into state machine event shapes.
      // temperature and co2 are store-only events (Plan 02 contract — no state.js modification).
      if (msg.humidity !== undefined) {
        applyEvent({ type: 'humidity', value: msg.humidity });
      } else if (msg.temperature !== undefined) {
        applyEvent({ type: 'temperature', value: msg.temperature });
      } else if (msg.co2 !== undefined) {
        applyEvent({ type: 'co2', value: msg.co2 });
      } else if (msg.humidifier !== undefined) {
        applyEvent({ type: 'humidifier', value: msg.humidifier });
      } else if (msg.sensor_health) {
        applyEvent({
          type: 'sensor_health',
          level: msg.sensor_health.level,
          message: msg.sensor_health.message,
          values: msg.sensor_health.values,
        });
      } else if (msg.temperature_2 !== undefined || msg.humidity_2 !== undefined) {
        // Phase 26 Plan 03: slot-2 WS arrival = SCD41 freshness signal
        // (Option C hybrid). SHT30 freshness lives in sensor_health.values.
        applyEvent({ type: 'sensor_freshness', sensor: 'scd41', lastSeenMs: clock() });
      }
    },
    onLiveness({ wsConnected, rosConnected, humidifierLastMsgTs }) {
      applyEvent({ type: 'pi_liveness', wsConnected, rosConnected, humidifierLastMsgTs });
    },
    logger,
  });

  const heartbeat = createHeartbeatScheduler({
    config,
    getSummary() {
      // Consume Plan 02's declared state surface: currentTemp, currentCo2, humidifierCyclesLast24h
      return {
        rh: state.currentRh,
        temp: state.currentTemp,
        co2: state.currentCo2,
        humidifier: state.humidifierOnSinceMs ? 'ON' : 'OFF',
        humidifierCycles: state.humidifierCyclesLast24h || 0,
        piLastSeenSec: state.humidifierLastMsgTs
          ? Math.round((clock() - state.humidifierLastMsgTs) / 1000)
          : null,
      };
    },
    dispatch: applyEvent,
    clock,
    logger,
  });

  const receiveLoop = createReceiveLoop({
    signalClient,
    dispatch: applyEvent,
    config,
    logger,
    clock,
  });

  // Periodic tick to keep Pi-offline and humidifier-stuck detectors alive during quiet periods
  const tickTimer = setInterval(() => applyEvent({ type: 'tick' }), 30000);

  bridge.start();
  heartbeat.start();
  receiveLoop.start();

  return {
    dispatch: applyEvent,
    close() {
      bridge.close();
      heartbeat.stop();
      receiveLoop.stop();
      clearInterval(tickTimer);
    },
    _state() { return state; }, // test-only introspection
  };
}

/**
 * main() — container entrypoint.
 * Registers crash handlers and runs the alerter.
 */
function main() {
  const alerter = createAlerter();

  process.on('unhandledRejection', (err) => {
    console.error(`[fatal] unhandledRejection: ${err?.message || err}`);
    alerter.close();
    process.exit(1);
  });

  process.on('uncaughtException', (err) => {
    console.error(`[fatal] uncaughtException: ${err?.message || err}`);
    alerter.close();
    process.exit(1);
  });

  console.log('[boot] alerter running');
}

if (require.main === module) main();

module.exports = { createAlerter };
