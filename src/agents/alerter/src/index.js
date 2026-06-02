'use strict';

/**
 * Alerter entrypoint — wires config, state machine, signal client, bridge client,
 * heartbeat scheduler, and receive loop.
 *
 * Exports createAlerter({env, clock, logger}) as a test seam.
 * In container execution, require.main === module calls main() which also
 * registers unhandledRejection / uncaughtException handlers (Pitfall 4 / T-17-04).
 */

const { Pool } = require('pg');
const { load, maskNumber } = require('./config');
const stateLib = require('./state');
const { createSignalClient } = require('./signal');
const { createBridgeClient } = require('./bridge-client');
const { createHeartbeatScheduler } = require('./heartbeat');
const { createReceiveLoop } = require('./receive-loop');
const captureDb = require('./capture-db');
const outboundDb = require('./outbound-db');
const extractionDb = require('./extraction/extraction-db');
const { createTranscribeClient } = require('./transcribe-client');
const { createLlmClient } = require('./llm-client');
const { createCaptureHistory } = require('./capture-history');
const { createSensorSnapshotFetcher } = require('./sensor-snapshot');
const { createCapturePipeline } = require('./capture');
const { createRetentionJob } = require('./capture-retention');
const { createExtractor } = require('./extraction/extractor');
const stateMachineMod = require('./extraction/state-machine');
const previewBuilderMod = require('./extraction/preview-builder');
const { createExtractionPipeline } = require('./extraction');
const { createOutboundDispatcher } = require('./extraction/outbound');
// Phase 44 Plan-04: event-gate (hybrid rules + Haiku 4.5).
const { createEventGate } = require('./event-gate');
const { createHaikuClassifier } = require('./event-gate/haiku-classifier');
const eventGateRules = require('./event-gate/rules');
// Phase 39 confirm-loop.
const confirm = require('./confirm');
// Phase 40 farmOS write path.
const farmos = require('./farmos');

/**
 * createAlerter({ env, clock, logger }) -> { dispatch, close, _state }
 *
 * @param {object} [opts]
 * @param {object} [opts.env]    - env vars (default: process.env)
 * @param {Function} [opts.clock] - () => nowMs (default: Date.now)
 * @param {object} [opts.logger] - logger (default: console)
 * @returns {{ dispatch: Function, close: Function, _state: Function }}
 */
async function createAlerter({ env = process.env, clock = Date.now, logger = console } = {}) {
  const config = load(env);

  logger.info(`[boot] alerter starting — sender=${maskNumber(config.signalSender)} recipient=${maskNumber(config.signalRecipient)}`);
  logger.info(`[boot] bridge=${config.bridgeWsUrl} signal=${config.signalApiUrl} tz=${config.timezone}`);

  // Phase 25 capture pipeline: Pool + DB bootstrap (D-08 idempotent CREATE TABLE IF NOT EXISTS)
  const pool = new Pool({
    host: config.timescaleHost,
    database: config.timescaleDb,
    user: config.timescaleUser,
    password: config.timescalePassword,
    port: 5432,
  });
  // initDb is best-effort: if Postgres is unreachable at boot the alerter still
  // starts (alerts continue to flow). The capture path will degrade per insertCapture
  // try/catch (capture.js step 3). Tests can run without a real DB.
  try {
    await captureDb.initDb(pool);
    logger.info(`[boot] signal_capture schema initialized (db=${config.timescaleDb} host=${config.timescaleHost})`);
  } catch (e) {
    logger.warn(`[boot] signal_capture initDb failed (capture pipeline will degrade): ${e.message}`);
  }
  // Phase 44 Plan-02 D-12/D-14: signal_outbound durable persistence schema.
  // Mirrors captureDb best-effort pattern — if Postgres is unreachable at boot
  // the alerter still starts and the send-path persistence hook fails open
  // (D-03) per insertOutbound's {ok, reason} contract.
  try {
    await outboundDb.initDb(pool);
    logger.info('[boot] signal_outbound schema initialized');
  } catch (e) {
    logger.warn(`[boot] signal_outbound initDb failed (outbound persistence will degrade): ${e.message}`);
  }
  // Phase 38 Plan 02: signal_draft schema (extraction pipeline persistence).
  // Best-effort, mirrors captureDb pattern. Extraction will degrade if DB unreachable.
  try {
    await extractionDb.initDb(pool);
    logger.info('[boot] signal_draft schema initialized');
  } catch (e) {
    logger.warn(`[boot] signal_draft initDb failed (extraction will degrade): ${e.message}`);
  }
  // Phase 39 D-07/D-07a: confirm-loop schema additions + signal_draft_event audit table.
  try {
    await confirm.confirmDb.initDb(pool);
    logger.info('[boot] signal_draft_event + confirm columns initialized');
  } catch (e) {
    logger.warn(`[boot] confirm-loop initDb failed (confirm loop will degrade): ${e.message}`);
  }
  // Phase 40 D-02/D-07: commit-pipeline schema additions on signal_draft.
  try {
    await farmos.commitDb.initDb(pool);
    logger.info('[boot] signal_draft commit columns + index initialized');
  } catch (e) {
    logger.warn(`[boot] commit-db initDb failed (commit pipeline will degrade): ${e.message}`);
  }

  // Phase 29 plan 29-04 BLOCKER 3 / ALRT-09 — Tier C runtime overrides for
  // signal egress cap. signalClient reads getMaxSendsPerHour() on each send;
  // accessor returns the effective.maxSendsPerHour from current state if
  // alerter_globals has arrived, else falls back to bootstrap config.maxSendsPerHour.
  // Phase 37 D-04: default non-reply destination flips from SIGNAL_RECIPIENT (f1)
  // to SIGNAL_GROUP_ID when set. Falls back to phone recipient when env unset —
  // back-compat with pre-Phase-37 DM-only behavior.
  const signalClient = createSignalClient({
    apiUrl: config.signalApiUrl,
    sender: config.signalSender,
    recipient: config.signalRecipient,
    defaultTarget: config.signalGroupId
      ? { groupId: config.signalGroupId }
      : config.signalRecipient,
    maxSendsPerHour: config.maxSendsPerHour,
    getMaxSendsPerHour: () => stateLib.resolveEffectiveConfig(state, config, clock()).maxSendsPerHour,
    logger,
    // Phase 44 Plan-02 D-14: single persistence hook deps. Without these the
    // wrapper is a no-op (back-compat for tests). With them, every successful
    // send writes one signal_outbound row (intent='unknown' until Plan-03 wires
    // the 14 callsites).
    outboundDb,
    pool,
    tenantId: config.tenantId,
  });
  logger.info(`[boot] signal defaultTarget = ${config.signalGroupId
    ? `group:${config.signalGroupId.slice(0, 8)}…`
    : 'DM:' + maskNumber(config.signalRecipient)}`);
  logger.info(`[boot] farmer-map entries = ${config.signalFarmerMap.size}`);

  // Phase 25 capture pipeline factories
  const captureHealth = stateLib.createCaptureHealth();
  const transcribeClient = createTranscribeClient({ apiUrl: config.whisperUrl, timeoutMs: 200000, logger });
  const llmClient = createLlmClient({ apiKey: config.anthropicApiKey, logger });
  const captureHistory = createCaptureHistory({ pool });
  const sensorSnapshot = createSensorSnapshotFetcher({ bridgeUrl: config.bridgeHttpUrl, timeoutMs: 2000, logger });

  // Phase 38 Plan 05: extraction pipeline. Separate extractor instance keeps
  // the alerter-reply LLM (llm-client.js) decoupled from the structured-extract
  // LLM (extractor.js). Both reuse ANTHROPIC_API_KEY.
  const extractor = createExtractor({ apiKey: config.anthropicApiKey, logger });
  // Phase 38 Plan 06: real outbound dispatcher. Ask-back replies route to the
  // originating capture's reply_target_kind (DM vs group); needs-review pings
  // go to operatorRecipient (Don Santiago via SIGNAL_RECIPIENT). The dispatcher
  // never throws -- signal-cli outages return {ok:false} and the draft row
  // stays in its persisted state for retry on the next farmer message.
  const outboundDispatcher = createOutboundDispatcher({
    signalClient,
    config,
    logger,
    previewBuilder: previewBuilderMod,
    operatorRecipient: config.signalRecipient,
  });
  logger.info(`[boot] extraction outbound dispatcher ready -> ${maskNumber(config.signalRecipient)}`);
  // Phase 54.2 Plan 01: lift farmosClient construction to before the pipeline so
  // the strain-detection gate (Wave 2) can call getFungiTypeUuid. Constructed
  // here only when credentials are present; null when absent (the Wave 2 gate
  // guards `if (farmosClient)` and skips, mirroring the commit-watchdog WARN
  // below). The same instance is reused by the commit-watchdog block -- never
  // constructed twice.
  let farmosClient = null;
  if (config.farmosUsername && config.farmosPassword) {
    farmosClient = farmos.createFarmosClient({
      farmosUrl: config.farmosUrl,
      username: config.farmosUsername,
      password: config.farmosPassword,
      logger,
      backoffMs: config.commitRetryBackoffMs,
      retryMax: config.commitRetryMax,
    });
  } else {
    logger.warn('[farmosClient] not constructed: farmOS credentials missing');
  }
  const extractionPipeline = createExtractionPipeline({
    pool,
    extractor,
    extractionDb,
    stateMachine: stateMachineMod,
    previewBuilder: previewBuilderMod,
    config,
    logger,
    clock: { now: () => clock() },
    outboundDispatcher,
    farmosClient,
  });

  // Phase 44 Plan-04 D-01: event-gate boot wiring. Haiku 4.5 classifier reads
  // ANTHROPIC_API_KEY via config; rules are pure functions injected for testability.
  const haikuClassifier = createHaikuClassifier({ apiKey: config.anthropicApiKey, logger });
  const eventGate = createEventGate({ haikuClassifier, rules: eventGateRules, logger });
  logger.info(`[boot] event-gate ready (convo mode=${config.eventGateConvoMode})`);

  const capturePipeline = createCapturePipeline({
    pool,
    signalClient,
    transcribeClient,
    llmClient,
    captureHistory,
    sensorSnapshot,
    baseDir: config.captureBaseDir,
    logger,
    clock,
    // Phase 37 D-11/D-13: farmer-slug resolution at capture time.
    signalFarmerMap: config.signalFarmerMap,
    // Phase 38 Plan 05: fire-and-forget extraction enqueue for known farmers.
    extractionPipeline,
    // Phase 44 Plan-04 D-02/D-04/D-06: hybrid event-gate + convo-mode steering.
    eventGate,
    config,
  });

  const retentionJob = createRetentionJob({ pool, config, state: captureHealth, logger });
  retentionJob.start();
  logger.info(`[boot] retention cron scheduled "${config.captureRetentionCron}" tz=${config.timezone} retention=${config.captureRetentionDays}d`);

  let state = stateLib.initialState(clock());

  async function applyEvent(event) {
    const result = stateLib.transition(state, event, clock(), config);
    state = result.next;
    for (const action of result.actions) {
      try {
        // D-04: non-reply sends inherit defaultTarget (group when SIGNAL_GROUP_ID set).
        if (action.kind === 'send' || action.kind === 'recovery') {
          await signalClient.send(action.body, { intent: 'rh_alert', sourceModule: 'index.js' });
        } else if (action.kind === 'heartbeat') {
          // Heartbeat bypasses the hourly send cap (bypassCap: true).
          // Phase 46 D-09: heartbeat doubles as the attestation_kickoff carrier.
          await signalClient.send(action.body, { bypassCap: true, intent: 'attestation_kickoff', sourceModule: 'index.js' });
        } else if (action.kind === 'snooze_ack') {
          await signalClient.send(action.body, { intent: 'command_echo', sourceModule: 'index.js' });
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
      } else if (msg.current_mode) {
        // Phase 29 plan 29-04: bridge envelopes for mode + Tier B/C overrides.
        applyEvent({ type: 'mode_update', mode: msg.current_mode });
      } else if (msg.alerter_overrides) {
        applyEvent({ type: 'overrides_update', overrides: msg.alerter_overrides });
      } else if (msg.alerter_globals) {
        applyEvent({ type: 'globals_update', globals: msg.alerter_globals });
      }
    },
    onLiveness({ wsConnected, rosConnected, humidifierLastMsgTs, fc1LastMsgTs }) {
      // Phase 46 D-02 — forward bridge-aggregated fc1 publisher freshness so
      // state.js's third OR-trigger (chamber-dark) can fire. Live-fire
      // attestation 2026-05-21 showed this wiring was missing: pi-alert never
      // reached FIRING during a real induced fc-core stop, so D-07 per-sensor
      // suppression never engaged. Both module-level unit tests passed
      // (bridge-client forwards it; state.js consumes it), but the index.js
      // glue dropped the field on destructure.
      applyEvent({ type: 'pi_liveness', wsConnected, rosConnected, humidifierLastMsgTs, fc1LastMsgTs });
    },
    logger,
  });

  const heartbeat = createHeartbeatScheduler({
    config,
    // Phase 29 plan 29-04 BLOCKER 3 / ALRT-09 — Tier C runtime override for
    // heartbeat hour. Scheduler reads getEffective().heartbeatHour on each tick;
    // falls back to bootstrap config.heartbeatHour when accessor undefined.
    getEffective: () => stateLib.resolveEffectiveConfig(state, config, clock()),
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

  // Phase 39: confirm-loop wiring.
  // Phase 50 Plan 03: pool + confirmDb passed so send_commit_outcome_ack and
  // send_confirm_ack can resolve source-capture quote targets at dispatch time.
  const confirmOutbound = confirm.createConfirmOutbound({
    signalClient,
    previewBuilderConfirm: confirm.preview,
    operatorRecipient: config.signalRecipient,
    logger,
    pool,
    confirmDb: confirm.confirmDb,
  });
  const editHandler = confirm.createEditHandler({
    pool,
    extractor,
    confirmDb: confirm.confirmDb,
    previewBuilderConfirm: confirm.preview,
    previewBuilderExtraction: previewBuilderMod,
    stateMachineExtraction: stateMachineMod,
    config,
    logger,
  });
  const watchdog = confirm.createWatchdog({
    pool,
    confirmDb: confirm.confirmDb,
    outboundConfirm: confirmOutbound,
    config,
    logger,
  });

  // Phase 40: commit watchdog. Constructed only if FARMOS_USERNAME +
  // FARMOS_PASSWORD are both set; otherwise the alerter still runs (Phase
  // 39 confirm watchdog + receive loop stay alive) and a single WARN line
  // surfaces the gate to the operator.
  let commitWatchdog = null;
  if (config.farmosUsername && config.farmosPassword) {
    // farmosClient was lifted above the pipeline construction (Phase 54.2 Plan 01)
    // and is reused here -- not constructed again.
    const auditLogger = farmos.createAuditLogger({
      pool, logger, farmosUrl: config.farmosUrl, confirmDb: confirm.confirmDb,
    });
    const commitCtx = {
      commitDb: farmos.commitDb,
      capturePathsFor: async (ids) => {
        const r = await captureDb.getAttachmentPathsForIds(pool, ids);
        return r.ok ? r.paths : [];
      },
      logger,
      clock: { now: () => Date.now() },
    };
    commitWatchdog = farmos.createCommitWatchdog({
      pool,
      commitDb: farmos.commitDb,
      farmosClient,
      commitRouter: farmos.commitRouter,
      ctx: commitCtx,
      config,
      auditLogger,
      // Phase 45 Plan 04: outboundConfirm plumbed in so commit-watchdog can
      // dispatch send_commit_outcome_ack on T4 (commit_success) and T6
      // (commit_failed terminal). Gated by Plan 01's tryMarkOutcomeAckSent CAS
      // claim for ACK-04 idempotency.
      outboundConfirm: confirmOutbound,
      logger,
    });
  } else {
    logger.warn('[commit-watchdog] disabled: farmOS credentials missing');
  }

  const receiveLoop = createReceiveLoop({
    signalClient,
    dispatch: applyEvent,
    config,
    capturePipeline,
    logger,
    clock,
    pool,
    confirmDb: confirm.confirmDb,
    confirmParser: confirm.parser,
    confirmOutbound,
    editHandler,
    extractionDb,
  });

  // Periodic tick to keep Pi-offline and humidifier-stuck detectors alive during quiet periods
  const tickTimer = setInterval(() => applyEvent({ type: 'tick' }), 30000);

  bridge.start();
  heartbeat.start();
  receiveLoop.start();
  // Phase 39 D-04d: start watchdog AFTER receive-loop is up (first tick fires immediately).
  watchdog.start().catch((e) => logger.warn(`[boot] watchdog start failed: ${e.message}`));
  // Phase 40: start commit watchdog AFTER confirm watchdog so the read seam (Phase 39
  // 'confirmed' transitions) is up before the commit pipeline starts draining.
  if (commitWatchdog) {
    commitWatchdog.start().catch((e) => logger.warn(`[boot] commit-watchdog start failed: ${e.message}`));
  }

  return {
    dispatch: applyEvent,
    close() {
      bridge.close();
      heartbeat.stop();
      receiveLoop.stop();
      watchdog.stop();
      if (commitWatchdog) commitWatchdog.stop();
      retentionJob.stop();
      clearInterval(tickTimer);
      pool.end().catch(() => {});
    },
    _state() { return state; }, // test-only introspection
    _captureHealth() { return captureHealth; }, // operator visibility (D-03)
  };
}

/**
 * main() — container entrypoint.
 * Registers crash handlers and runs the alerter.
 */
async function main() {
  const alerter = await createAlerter();

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

if (require.main === module) {
  main().catch((e) => { console.error('[boot] fatal:', e?.stack || e); process.exit(1); });
}

module.exports = { createAlerter };
