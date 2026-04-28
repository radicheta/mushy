'use strict';

const { parseSnoozeCommand } = require('./snooze');

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
}) {
  let timer = null;

  // Sender whitelist (T-17-02 / R7): only process envelopes from the registered
  // Signal sender or recipient. All other sources are dropped.
  const allowedSenders = new Set(
    [config.signalSender, config.signalRecipient].filter(Boolean)
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
          capturePipeline.handle({ envelope: env, source, text, attachments }).catch((e) => logger.warn(`[capture] pipeline error: ${e.message}`));
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
