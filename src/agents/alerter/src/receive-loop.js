'use strict';

const { parseSnoozeCommand } = require('./snooze');
const { parseExperimentCommand } = require('./experiment_commands');

// Phase 37 D-06/D-09 — pure helper for unit-testable trigger evaluation.
// Defensive against both envelope wrapper shapes (env.envelope.dataMessage AND
// env.dataMessage) — the receive loop sometimes forwards the inner shape and
// callers in tests build either form. Risk #9: quote field cross-version drift —
// accept both `quote.author` and `quote.authorNumber`.
function collectGroupTriggers(env, botPhone) {
  const out = new Set();
  const dm = env?.envelope?.dataMessage || env?.dataMessage || {};
  const text = dm.message || '';
  if ((dm.mentions || []).some((m) => m && m.number === botPhone)) out.add('mention');
  // Command keyword surface aligns with actual handlers in snooze.js (no 'status' —
  // unwired; PATTERNS.md listed it as planner conjecture). Accepts optional
  // `@mention<space>` prefix so '@bot mute' is recognized as a command in groups.
  if (/^\s*(?:@\S+\s+)?(mute|snooze|quiet)\b/i.test(text)
      || /^\/(force-|cancel-)/i.test(text)) out.add('command');
  const q = dm.quote || {};
  if ((q.author || q.authorNumber) === botPhone) out.add('quote');
  return out;
}

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
  // Uses BRIDGE_HTTP_URL (project convention; already set in docker-compose.override.yml
  // alongside BRIDGE_WS_URL). BRIDGE_URL kept as legacy fallback.
  bridgeUrl = process.env.BRIDGE_HTTP_URL || process.env.BRIDGE_URL || 'http://bridge:8080',
  fetchImpl = (typeof fetch !== 'undefined' ? fetch : null),
  // Phase 39: confirm-loop wiring. Null defaults preserve back-compat for
  // existing Phase 37/38 tests that don't supply these.
  pool = null,
  confirmDb = null,
  confirmParser = null,
  confirmOutbound = null,
  editHandler = null,
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

        // Phase 37 D-06/D-08/D-09 — group-context gate.
        // D-05: VPS heartbeat is direct-to-f1, not via this loop.
        const groupId = dm?.groupInfo?.groupId ?? null;
        const groupType = dm?.groupInfo?.type ?? null;
        // Risk #11 — UPDATE/QUIT envelopes treated as non-group (no triggers, no group reply).
        const isGroup = !!groupId && groupType !== 'UPDATE' && groupType !== 'QUIT';
        const botPhone = config.signalSender;
        const triggers = isGroup ? collectGroupTriggers(env, botPhone) : new Set(['dm']);
        const shouldReply = triggers.size > 0;
        const replyTargetKind = isGroup ? (shouldReply ? 'group' : 'none') : 'dm';
        const captureCtx = {
          replyTargetKind,
          groupId: isGroup ? groupId : null,
          // Suppress capture-branch reply send when:
          //  - group + no triggers (silent listener, D-08)
          // Command-triggered groups don't reach the capture branch (snooze/experiment
          // branches end with `continue`); mention/quote-only triggered groups DO reach
          // capture and SHOULD reply, so suppressReply=false in that case.
          suppressReply: isGroup && !shouldReply,
        };

        // Phase 37 D-09 — only run command branches when:
        //   - DM (existing behavior), OR
        //   - group + 'command' trigger fired
        // This prevents an arbitrary @mention text from getting fuzzy-parsed as a snooze
        // help reply and double-firing alongside the capture branch's reply.
        const commandBranchAllowed = !isGroup || triggers.has('command');

        // Phase 37 — in group context, strip an optional leading '@mention ' prefix
        // so '@bot mute' is parsed as 'mute' by the existing snooze/experiment parsers.
        // DM text passes through unchanged.
        const commandText = (isGroup && text)
          ? text.replace(/^\s*@\S+\s+/, '')
          : text;

        // PHASE 31 D-15 — experiment command (must precede snooze so /force-*
        // isn't fuzzy-routed by snooze's prefix branch). Both /force-* and
        // /cancel-experiment short-circuit out of this iteration.
        if (commandText && commandBranchAllowed) {
          const exp = parseExperimentCommand(commandText);
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
        if (commandText && commandBranchAllowed) {
          const parsed = parseSnoozeCommand(commandText, clock());
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

        // Phase 39 confirm-reply branch (between snooze and capture).
        // Skip when wiring is incomplete (defensive back-compat for legacy tests).
        if (pool && confirmDb && confirmParser && confirmOutbound && editHandler && text) {
          let draftRow = null;
          try {
            draftRow = await confirmDb.findAwaitingForSender(pool, source);
          } catch (e) {
            logger.warn(`[receive] confirm lookup failed: ${e.message}`);
          }
          if (draftRow) {
            const parsed = confirmParser.parseReply(text);
            if (parsed.kind === 'YES') {
              const r = await confirmDb.confirmDraft(pool, draftRow.id);
              if (r.ok && r.rowCount === 1) {
                await confirmOutbound.dispatch('send_confirm_ack', draftRow);
              } else if (r.ok && r.rowCount === 0) {
                await confirmOutbound.dispatch('send_confirm_idempotent_ack', draftRow);
              } else {
                logger.warn(`[receive] confirm error: ${r.reason}`);
              }
              continue;
            }
            if (parsed.kind === 'NO') {
              const r = await confirmDb.discardDraft(pool, draftRow.id);
              if (r.ok && r.rowCount === 1) {
                await confirmOutbound.dispatch('send_discard_ack', draftRow);
              }
              continue;
            }
            if (parsed.kind === 'EDIT') {
              const editText = parsed.editText || '';
              const eh = await editHandler.handleEdit(draftRow, editText);
              if (eh.ok && eh.sideEffect === 'send_edit_cap_msg') {
                await confirmDb.expireDraft(pool, draftRow.id, 'edit_cap_exceeded');
                await confirmOutbound.dispatch('send_edit_cap_msg', draftRow, { maxEditTurns: config.maxEditTurns });
              } else if (eh.ok && eh.sideEffect === 'send_preview_resend') {
                await confirmOutbound.dispatch('send_preview_resend', draftRow, { newPreview: eh.newPreview });
              } else if (eh.ok && eh.sideEffect === 'noop') {
                logger.info(`[receive] edit noop: ${eh.reason}`);
              } else {
                logger.warn(`[receive] edit failed: ${eh && eh.reason}`);
              }
              continue;
            }
            // parsed.kind === 'NOOP' -- fall through to capture pipeline.
          }
        }

        // SLOW PATH — capture (D-03 — error-isolated, fire-and-forget; NEVER awaited)
        // Phase 37: thread routing context (replyTargetKind, groupId, suppressReply)
        // so capture.js can populate row fields + pick reply target.
        if (capturePipeline && (text || attachments.length)) {
          capturePipeline.handle(env, captureCtx).catch((e) =>
            logger.warn(`[capture] pipeline error: ${e.message}`),
          );
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

module.exports = { createReceiveLoop, collectGroupTriggers };
