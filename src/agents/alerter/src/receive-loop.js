'use strict';

const { parseSnoozeCommand } = require('./snooze');
const { parseExperimentCommand } = require('./experiment_commands');
// Phase 54.1 Plan 03 Task 3: per-encounter strain ask-back reply parser + resolver.
const { parseStrainAskBackReply } = require('./confirm/strain-ask-back');
const { resolveStrain } = require('./farmos/strain-resolver');

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
  // Command keyword surface aligns with actual handlers in snooze.js (no 'status'
  // unwired; PATTERNS.md listed it as planner conjecture). Accepts optional
  // `@mention<space>` prefix so '@bot mute' is recognized as a command in groups.
  // Also tolerates U+FFFC (Signal iOS mention-attachment marker) before the @mention
  // or in place of it, after Attestation D live finding 2026-05-11.
  if (/^\s*￼?\s*(?:@\S+\s+)?(mute|snooze|quiet)\b/i.test(text)
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
  // Phase 54.1 Plan 03: extractionDb.updateDraftStatus for strain-pending
  // draft authorization (approval marker) and correction remap. Optional;
  // when absent the strain-pending branch degrades to the normal YES path.
  extractionDb = null,
}) {
  let timer = null;

  // Phase 31 D-15: dispatch a parsed experiment command to the bridge HTTP
  // endpoints (Plan 31-03 contract). Always replies via Signal so the
  // operator sees feedback within receive-loop's 30s budget; never throws
  // (the loop must never die on a single dispatch failure).
  async function dispatchExperiment(exp) {
    if (!fetchImpl) {
      logger.warn('[receive] no fetch impl — cannot dispatch experiment');
      await signalClient.send('experiment dispatch unavailable (bridge unreachable)', { intent: 'experiment_reject', sourceModule: 'receive-loop.js' }).catch(() => {});
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
            { intent: 'experiment_ack', sourceModule: 'receive-loop.js' },
          );
          logger.info(`[receive] experiment dispatched: ${exp.name} ${exp.duration_minutes}min`);
        } else {
          const err = body.error || body.message || `bridge returned ${resp.status}`;
          await signalClient.send(`experiment rejected: ${err}`, { intent: 'experiment_reject', sourceModule: 'receive-loop.js' });
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
          await signalClient.send(`experiment cancelled (ended_at=${body.ended_at_iso})`, { intent: 'experiment_cancel', sourceModule: 'receive-loop.js' });
          logger.info('[receive] experiment cancelled');
        } else {
          const err = body.error || body.message || `bridge returned ${resp.status}`;
          await signalClient.send(`cancel rejected: ${err}`, { intent: 'experiment_reject', sourceModule: 'receive-loop.js' });
          logger.warn(`[receive] cancel rejected by bridge: ${err}`);
        }
      }
    } catch (e) {
      logger.warn(`[receive] experiment dispatch network error: ${e.message}`);
      await signalClient.send('experiment dispatch failed; check bridge logs', { intent: 'experiment_reject', sourceModule: 'receive-loop.js' }).catch(() => {});
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

        // Phase 37 -- in group context, strip an optional leading '@mention ' prefix
        // so '@bot mute' is parsed as 'mute' by the existing snooze/experiment parsers.
        // Also strip U+FFFC (Signal iOS mention-attachment marker), which Signal iOS
        // inserts in place of the rendered @mention. Captured live 2026-05-11.
        // DM text passes through unchanged.
        const commandText = (isGroup && text)
          ? text.replace(/^\s*￼?\s*@\S+\s+/, '').replace(/^\s*￼\s*/, '')
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
            await signalClient.send(exp.reply, { intent: 'experiment_reject', sourceModule: 'receive-loop.js' }).catch((e) =>
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
              .send(parsed.ackText || 'snoozed', { intent: 'command_echo', sourceModule: 'receive-loop.js' })
              .catch((e) => logger.warn(`[receive] ack send failed: ${e.message}`));
            continue;
          }
          if (parsed.reply) {
            logger.info(`[receive] invalid snooze — replying with help text`);
            await signalClient.send(parsed.reply, { intent: 'command_echo', sourceModule: 'receive-loop.js' }).catch((e) =>
              logger.warn(`[receive] reply send failed: ${e.message}`)
            );
            continue;
          }
        }

        // Phase 39 confirm-reply branch (between snooze and capture).
        // Skip when wiring is incomplete (defensive back-compat for legacy tests).
        if (pool && confirmDb && confirmParser && confirmOutbound && editHandler && text) {
          // 2026-05-24 fix (signal-capture-missing-followup-messages): every
          // confirm-branch path below ends in `continue`, skipping the SLOW PATH
          // capture write -- so follow-up replies (YES/NO/EDIT/strain) were never
          // persisted to signal_capture. Persist the raw inbound paper trail right
          // before we consume the message. Best-effort, never-throw; the NOOP
          // fall-through still goes through full handle() (no double-persist).
          const recordReply = () =>
            (capturePipeline && typeof capturePipeline.recordReplyCapture === 'function'
              ? capturePipeline.recordReplyCapture(env, captureCtx).catch((e) =>
                  logger.warn(`[capture] reply persist error: ${e.message}`))
              : Promise.resolve());
          // Phase 50 Plan-04 (CONTEXT D-04): quote-first routing. When the
          // farmer's incoming message carries a quote target, prefer the
          // resolved draft over the most-recent-active heuristic.
          const dmQuote = dm && dm.quote ? dm.quote : null;
          const quoteMsgTsRaw = dmQuote
            ? (dmQuote.id != null ? dmQuote.id : dmQuote.timestamp)
            : null;
          const quoteMsgTs = quoteMsgTsRaw != null && Number.isFinite(Number(quoteMsgTsRaw))
            ? Number(quoteMsgTsRaw)
            : null;

          let draftRow = null;
          let quoteResolved = false;
          if (quoteMsgTs != null && typeof confirmDb.findDraftByQuotedMsgTs === 'function') {
            let qr = null;
            try {
              qr = await confirmDb.findDraftByQuotedMsgTs(pool, quoteMsgTs);
            } catch (e) {
              logger.warn(`[receive] quote-resolve failed: ${e.message}`);
            }
            if (qr) {
              // T-50-04-01: sender-equality guard. If the quoted draft belongs
              // to a different farmer, do NOT route -- treat as orphan quote.
              if (qr.sender_e164 && qr.sender_e164 !== source) {
                logger.warn(`[receive] quote spoof guard: draft sender mismatch (drop)`);
              } else if (qr.status === 'awaiting_farmer' || qr.status === 'commit_failed') {
                draftRow = qr;
                quoteResolved = true;
              } else if (qr.status === 'committed' || qr.status === 'discarded' || qr.status === 'expired' || qr.status === 'needs_review' || qr.status === 'confirmed') {
                // Terminal-state quote: polite "already closed" ack; do not mutate.
                await confirmOutbound.dispatch('send_quote_closed', qr);
                await recordReply();
                continue;
              }
              // Other transitional statuses fall through to the most-recent-active path.
            }
          }

          // Quote did not pin a draft -> fall back to active-draft lookup.
          // Use the list-shape variant so we can detect the >1-active ambiguity
          // and emit a numbered ask-back (CONTEXT D-06).
          let activeDrafts = [];
          if (!draftRow) {
            if (typeof confirmDb.findActiveDraftsForSender === 'function') {
              try {
                activeDrafts = await confirmDb.findActiveDraftsForSender(pool, source) || [];
              } catch (e) {
                logger.warn(`[receive] active-drafts lookup failed: ${e.message}`);
                activeDrafts = [];
              }
            } else {
              // Back-compat for tests / wiring that don't expose the list helper.
              try {
                const single = await confirmDb.findAwaitingForSender(pool, source);
                if (single) activeDrafts = [single];
              } catch (e) {
                logger.warn(`[receive] confirm lookup failed: ${e.message}`);
              }
            }
            if (activeDrafts.length > 1 && !quoteResolved) {
              // Numbered ask-back: one-shot response, no state tracking.
              // Hotfix 2026-05-23: staleness filter lives in confirm-db
              // (findActiveDraftsForSender ages out commit_failed >6h old)
              // so 10-day-old ack-debt drafts no longer trap fresh captures.
              await confirmOutbound.dispatch('send_ask_back', null, {
                activeDrafts,
                senderE164: source,
              });
              await recordReply();
              continue;
            }
            draftRow = activeDrafts[0] || null;
          }
          if (draftRow) {
            // Phase 54.1 Plan 03 Task 3: strain-pending intercept.
            // When the draft is held for farmer strain confirmation, route the
            // reply through parseStrainAskBackReply instead of the standard
            // confirmParser.parseReply YES path.
            if (draftRow.needs_review_reason === 'strain_unknown_pending_confirm' &&
                extractionDb && typeof extractionDb.updateDraftStatus === 'function') {
              const strainReply = parseStrainAskBackReply(text);
              if (strainReply.kind === 'confirm_new') {
                // YES -> set approval marker so commit-watchdog passes createMissingFungiType=true
                await extractionDb.updateDraftStatus(
                  pool, draftRow.id, draftRow.status,
                  { needs_review_reason: 'strain_confirm_approved' }
                );
                const r = await confirmDb.confirmDraft(pool, draftRow.id);
                if (r.ok && r.rowCount === 1) {
                  await confirmOutbound.dispatch('send_confirm_ack', draftRow);
                } else if (r.ok && r.rowCount === 0) {
                  await confirmOutbound.dispatch('send_confirm_idempotent_ack', draftRow);
                } else {
                  logger.warn(`[receive] strain confirm error: ${r.reason}`);
                }
                await recordReply();
                continue;
              } else if (strainReply.kind === 'correction') {
                // Validate the correction target against the curated set.
                const curatedSet = (config && Array.isArray(config.strains)) ? config.strains : [];
                const resolved = resolveStrain(strainReply.code, curatedSet);
                if (resolved.known) {
                  // Rewrite draft_json.species_code to the canonical curated code.
                  // Preserve all other draft_json fields (logs, attachments, etc.).
                  const updatedDraftJson = Object.assign({}, draftRow.draft_json || {}, {
                    species_code: resolved.code,
                  });
                  await extractionDb.updateDraftStatus(
                    pool, draftRow.id, draftRow.status,
                    { draft_json: updatedDraftJson }
                  );
                  // Confirm WITHOUT approval marker -- no mint.
                  const r = await confirmDb.confirmDraft(pool, draftRow.id);
                  if (r.ok && r.rowCount === 1) {
                    await confirmOutbound.dispatch('send_confirm_ack', draftRow);
                  } else if (r.ok && r.rowCount === 0) {
                    await confirmOutbound.dispatch('send_confirm_idempotent_ack', draftRow);
                  } else {
                    logger.warn(`[receive] strain correction confirm error: ${r.reason}`);
                  }
                  await recordReply();
                  continue;
                } else {
                  // Non-curated correction target: re-ask (do not confirm, do not mint).
                  const seenCode = (draftRow.draft_json && draftRow.draft_json.species_code) || strainReply.code;
                  await confirmOutbound.dispatch('send_strain_ask_back', draftRow, {
                    seenCode,
                    nearest: resolved.nearest || null,
                  });
                  await recordReply();
                  continue;
                }
              }
              // strainReply.kind === 'unknown': fall through to NOOP -> capture pipeline.
            }
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
              await recordReply();
              continue;
            }
            if (parsed.kind === 'NO') {
              const r = await confirmDb.discardDraft(pool, draftRow.id);
              if (r.ok && r.rowCount === 1) {
                await confirmOutbound.dispatch('send_discard_ack', draftRow);
              }
              await recordReply();
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
              await recordReply();
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
