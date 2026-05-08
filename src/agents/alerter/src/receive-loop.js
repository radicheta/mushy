'use strict';

const { parseSnoozeCommand } = require('./snooze');
const { parseExperimentCommand } = require('./experiment_commands');

/**
 * createReceiveLoop — polls signal-cli /v1/receive, parses snooze commands,
 * dispatches valid snooze events, replies with help text for invalid commands,
 * and silently drops envelopes from unwhitelisted senders (T-17-02).
 *
 * The loop never dies silently: errors are logged as warnings and the next
 * tick proceeds normally (Pitfall 4).
 *
 * @param {object} opts
 * @param {object} opts.signalClient      - from createSignalClient: .receive(), .send()
 * @param {Function} opts.dispatch        - (event) => void
 * @param {object} opts.config            - from config.load()
 * @param {object} [opts.logger]          - logger
 * @param {Function} [opts.clock]         - () => nowMs (default Date.now)
 * @returns {{ start: Function, stop: Function }}
 */
function createReceiveLoop({
  signalClient,
  dispatch,
  config,
  capturePipeline = null,
  logger = console,
  clock = Date.now,
  // Phase 31: bridge URL for experiment dispatch + fetch seam for tests.
  bridgeUrl = process.env.BRIDGE_URL || 'http://bridge:8080',
  fetchImpl = (typeof fetch !== 'undefined' ? fetch : null),
}) {
  let timer = null;

  // Phase 31 D-15: dispatch a parsed experiment command to the bridge HTTP
  // endpoints (Plan 31-03 contract). Always replies via Signal so the
  // operator sees feedback within receive-loop's 30s budget; never throws
  // (the loop must never die on a single dispatch failure).
  async function dispatchExperiment(exp) {
    if (!fetchImpl) {
      logger.warn('[receive] no fetch impl — cannot dispatch experiment');
      await signalClient.send('experiment dispatch unavailable (bridge unreachable)').catch(() => {});
      return;
    }
    try {
      if (exp.kind === 'start') {
        const resp = await fetchImpl(`${bridgeUrl}/control/experiment`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ name: exp.name, duration_minutes: exp.duration_minutes }),
        });
        const body = await resp.json().catch(() => ({}));
        if (resp.status === 200 && body.ok) {
          await signalClient.send(
            `${exp.name} started for ${exp.duration_minutes} min; reverts at ${body.reverts_at_iso} (prior=${body.prior_mode})`,
          );
          logger.info(`[receive] experiment dispatched: ${exp.name} ${exp.duration_minutes}min`);
        } else {
          const err = body.error || body.message || `bridge returned ${resp.status}`;
          await signalClient.send(`experiment rejected: ${err}`);
          logger.warn(`[receive] experiment rejected by bridge: ${err}`);
        }
      } else if (exp.kind === 'cancel') {
        const resp = await fetchImpl(`${bridgeUrl}/control/cancel-experiment`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({}),
        });
        const body = await resp.json().catch(() => ({}));
        if (resp.status === 200 && body.ok) {
          await signalClient.send(`experiment cancelled (ended_at=${body.ended_at_iso})`);
          logger.info('[receive] experiment cancelled');
        } else {
          const err = body.error || body.message || `bridge returned ${resp.status}`;
          await signalClient.send(`cancel rejected: ${err}`);
          logger.warn(`[receive] cancel rejected by bridge: ${err}`);
        }
      }
    } catch (e) {
      logger.warn(`[receive] experiment dispatch network error: ${e.message}`);
      await signalClient.send('experiment dispatch failed; check bridge logs').catch(() => {});
    }
  }

  // Sender whitelist (T-17-02 / R7): only process envelopes from the registered
  // Signal sender or recipient. All other sources are dropped.
  const allowedSenders = new Set(
    [config.signalSender, config.signalRecipient, ...(config.signalAdditionalSenders || [])].filter(Boolean)
  );

  async function tick() {
    try {
      const envelopes = await signalClient.receive({ timeoutSec: 1 });
      for (const env of envelopes) {
        const source = env?.envelope?.source;
        const dm = env?.envelope?.dataMessage;
        if (!source) continue;

        // R7 — whitelist gate BEFORE both snooze and capture branches
        if (!allowedSenders.has(source)) {
          logger.warn(`[receive] rejected sender (not in whitelist)`);
          continue;
        }

        const text = dm?.message ?? null;
        const attachments = dm?.attachments || [];

        // PHASE 31 D-15 — experiment command (must precede snooze so /force-*
        // isn't fuzzy-routed by snooze's prefix branch). Both /force-* and
        // /cancel-experiment short-circuit out of this iteration.
        if (text) {
          const exp = parseExperimentCommand(text);
          if (exp.ok) {
            await dispatchExperiment(exp).catch((e) =>
              logger.warn(`[receive] experiment dispatch unexpected error: ${e.message}`),
            );
            continue;
          }
          if (exp.reply) {
            logger.info('[receive] invalid experiment command — replying with help text');
            await signalClient.send(exp.reply).catch((e) =>
              logger.warn(`[receive] experiment help-reply send failed: ${e.message}`),
            );
            continue;
          }
          // exp.reply === null → passthrough to snooze + capture below.
        }

        // FAST PATH — snooze (R4 / Pitfall 6 / R6 30s budget)
        if (text) {
          const parsed = parseSnoozeCommand(text, clock());
          if (parsed.ok) {
            logger.info(`[receive] snooze ${parsed.alertType} for ${parsed.durationMs}ms`);
            dispatch({ type: 'snooze', alertType: parsed.alertType, untilMs: parsed.untilMs });
            // Send ack reply (≤30s budget; ack only — no capture work in this branch)
            await signalClient
              .send(parsed.ackText || 'snoozed')
              .catch((e) => logger.warn(`[receive] ack send failed: ${e.message}`));
            continue;
          }
          if (parsed.reply) {
            logger.info(`[receive] invalid snooze — replying with help text`);
            await signalClient.send(parsed.reply).catch((e) =>
              logger.warn(`[receive] reply send failed: ${e.message}`)
            );
            continue;
          }
        }

        // SLOW PATH — capture (D-03 — error-isolated, fire-and-forget; NEVER awaited)
        if (capturePipeline && (text || attachments.length)) {
          capturePipeline.handle(env).catch((e) => logger.warn(`[capture] pipeline error: ${e.message}`));
        }
      }
    } catch (e) {
      // Pitfall 4: never die silently — log and continue
      logger.warn(`[receive] loop tick error: ${e.message}`);
    }
  }

  return {
    start() {
      tick(); // immediate poll on start
      timer = setInterval(tick, config.receivePollSec * 1000);
    },
    stop() {
      if (timer) {
        clearInterval(timer);
        timer = null;
      }
    },
  };
}

module.exports = { createReceiveLoop };
