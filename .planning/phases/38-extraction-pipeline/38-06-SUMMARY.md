---
phase: 38
plan: 06
subsystem: alerter / extraction
tags: [extraction, outbound, signal, ask-back, needs-review]
requires: [38-04, 38-05]
provides:
  - outbound-dispatcher-real-sends
  - ext-04-closeout
affects:
  - src/agents/alerter/src/extraction/outbound.js
  - src/agents/alerter/src/index.js
tech-stack:
  added: []
  patterns:
    - factory-returns-handle
    - never-throw outbound envelope ({ok, reason})
    - defense-in-depth sanitization (preview-builder + outbound)
    - per-call target override via signal.js {to} parameter
key-files:
  created:
    - src/agents/alerter/src/extraction/outbound.js
    - src/agents/alerter/test/extraction/outbound.test.js
  modified:
    - src/agents/alerter/src/index.js
decisions:
  - operatorRecipient is sourced from config.signalRecipient (existing SIGNAL_RECIPIENT env, currently Don Santiago in elder-plops .env). No new env var introduced.
  - Ask-back target resolution: reply_target_kind === 'group' -> { groupId: draftRow.group_id }; else DM to draftRow.sender_e164. Group_id stays in bare internal_id form; signal.js owns id-b64 translation (Phase 37 D-16 / 37-04).
  - dispatch() is async and never throws. Outbound failures (signal-cli down, missing target) return { ok:false, reason } so the pipeline keeps the draft row in its persisted state for retry on the next farmer message.
  - Operator-ping text addresses "Don Santiago" by name. The lowercase string "operator" never appears in farmer/operator-facing text (only in code-internal identifiers like operatorRecipient).
  - send.body / send.target shape mirrors existing alerter usage: signalClient.send(body, { to }) with `to` being a string E.164 or { groupId } object.
metrics:
  completed: 2026-05-12
  tasks: 2
  files-touched: 3
---

# Phase 38 Plan 06: Outbound Dispatcher (real Signal sends) Summary

Replace Plan 05's logging stub `outboundDispatcher` with real Signal sends. Closes EXT-04: ask-back replies reach the originating farmer (DM or group); operator pings reach Don Santiago when the 3-turn cap fires.

## What shipped

**`src/agents/alerter/src/extraction/outbound.js`** -- `createOutboundDispatcher({signalClient, config, logger, previewBuilder, operatorRecipient}) -> { dispatch }`. Side-effect routing table:

| side_effect | target | text |
|-------------|--------|------|
| `send_ask_back` | DM to `sender_e164` if `reply_target_kind==='dm'`; `{groupId: draftRow.group_id}` if `'group'` | sanitized `draftRow.farmer_facing_preview` |
| `send_needs_review_ping` | `operatorRecipient` (DM) | `"Hey Don Santiago, draft <id10> for <sender> hit the 3-turn ask-back cap. Marked for manual review. Reason: <reason>."` (sanitized) |
| `mark_expired` / `handoff_to_phase_39` / `noop` | -- | logger.debug, no send, `{ok:true, noop:true}` |
| unknown | -- | logger.warn, no send, `{ok:false, reason:'unknown_side_effect'}` |

Guarantees:
- `dispatch()` is async and never throws. signal-cli rejections are caught and returned as `{ok:false, reason}`.
- Missing target (null/empty `sender_e164` on DM, null `group_id` on group, null `operatorRecipient`) returns `{ok:false, reason:'no_target'}` without calling `signalClient.send`.
- All farmer/operator-facing text passes through `previewBuilder.sanitizeFarmerText` (em-dash strip, en-dash to ASCII hyphen). Defense-in-depth -- preview-builder already sanitizes its output.
- "Don Santiago" referent enforced by test (lowercase "operator" must not appear in the ping text).

**`src/agents/alerter/src/index.js`** -- swap the Plan 05 logging stub for the real dispatcher:

```js
const outboundDispatcher = createOutboundDispatcher({
  signalClient,
  config,
  logger,
  previewBuilder: previewBuilderMod,
  operatorRecipient: config.signalRecipient,
});
logger.info(`[boot] extraction outbound dispatcher ready -> ${maskNumber(config.signalRecipient)}`);
```

`config.signalRecipient` is already Don Santiago in elder-plops .env; no new env var. `previewBuilderMod` was already imported by Plan 05.

## Tests

`test/extraction/outbound.test.js` -- 14 cases, all green:

- send_ask_back DM -> target = sender_e164
- send_ask_back group -> target = { groupId: draftRow.group_id }
- send_ask_back strips em-dash from farmer_facing_preview
- send_needs_review_ping -> target = operatorRecipient
- send_needs_review_ping text addresses Don Santiago (not "operator")
- send_needs_review_ping text contains truncated draft id (first 10 chars) + sender E.164
- send_needs_review_ping text has no em-dash
- handoff_to_phase_39 -> no send
- mark_expired -> no send
- noop -> no send, returns ok
- unknown side effect -> logger.warn, returns ok:false
- signalClient.send rejects -> dispatch returns ok:false, never throws
- send_ask_back with missing target -> ok:false, no send
- send_needs_review_ping with missing operatorRecipient -> ok:false, no send

Full alerter suite: **401/402 green** (1 pre-existing config.test.js dashboardUrl failure tolerated per Plan 05 baseline).

## Deviations from Plan

None. The plan's `behavior` block was followed verbatim. One minor implementation detail worth surfacing:

1. **send signature** -- the plan suggested `signalClient.send({target, text})`. Existing alerter code calls `signalClient.send(body, { to })` (string body + options bag with `to`). The dispatcher uses the existing call shape; tests pin to `signalClient.send.mock.calls[i][0]` (body) and `[i][1]` (`{ to }`). Not a deviation in intent -- same wire effect.

No auth gates, no Rule-1/2/3 fixes triggered.

## Verification

- `cd src/agents/alerter && npx jest test/extraction/outbound.test.js` -- 14/14 green
- `cd src/agents/alerter && npm test` -- 401/402 green (1 pre-existing config.test.js failure unrelated to this plan)
- `cd src/agents/alerter && grep -P "—" src/extraction/outbound.js` -- no matches (em-dash discipline)
- `cd src/agents/alerter && grep -c "Don Santiago" src/extraction/outbound.js` -- 3
- `cd src/agents/alerter && grep -c "createOutboundDispatcher" src/index.js` -- 2 (import + construction)
- `cd src/agents/alerter && grep -c "outboundDispatcher" src/index.js` -- 2 (created + passed to pipeline)
- Smoke boot: `timeout 5 node -e "...require('./src/index')"` -- exit=0

## Commits

- `4cc1954` test(38-06): outbound dispatcher for ask-back + needs-review (RED)
- `c2d9f89` feat(38-06): outbound dispatcher for ask-back + needs-review
- `c2741d6` feat(38-06): wire real outbound dispatcher into pipeline

## What's next

EXT-04 closed end-to-end: capture -> extraction pipeline -> state-machine verdict -> outbound -> Signal. The full ask-back loop now reaches farmers in DM or group, and 3-turn cap exits route to Don Santiago for manual review. Plan 07 ships the eval/ship gate (corpus replay over the structured-extract pipeline).

## Self-Check: PASSED

- `src/agents/alerter/src/extraction/outbound.js` -- FOUND
- `src/agents/alerter/test/extraction/outbound.test.js` -- FOUND
- `src/agents/alerter/src/index.js` -- modified (real dispatcher wired)
- commit `4cc1954` -- FOUND
- commit `c2d9f89` -- FOUND
- commit `c2741d6` -- FOUND
