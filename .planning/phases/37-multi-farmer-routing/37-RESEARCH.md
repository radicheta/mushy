# Phase 37: Multi-farmer Routing — Research

**Researched:** 2026-05-11
**Domain:** Signal envelope routing + signal-cli REST shape + sqlite/Timescale schema migration on `signal_capture`
**Confidence:** HIGH on code shape (read in-repo); MEDIUM on signal-cli envelope field naming (cross-checked against AsamK + Signal-Bot docs but no live group fixture in repo); HIGH on send-to-group request body shape (confirmed via bbernhard issues)

---

## Overview

Phase 37 is plumbing on a well-mapped stack. The four real unknowns going in were:

1. **What field/value identifies "this is a group message" in the envelope?** → `envelope.dataMessage.groupInfo.groupId` (string, base64). Presence of `groupInfo` IS the group signal. `groupInfo.type === "DELIVER"` for a normal message; other types (`UPDATE`, `QUIT`) exist but aren't relevant here. [VERIFIED: signal-cli envelope example from AsamK community examples; [search source](https://github.com/AsamK/signal-cli/issues/388)]
2. **How does `/v2/send` target a group?** → Same `POST /v2/send` endpoint. The group ID goes into `recipients[]` as a single string with the `group.<base64>` prefix. **There is no separate `groupId` body field** — passing one yields `"please provide at least one recipient"`. [VERIFIED: [bbernhard issues #719, #694, discussion #351](https://github.com/bbernhard/signal-cli-rest-api/issues/719)]
3. **Mention field shape:** `dataMessage.mentions` is an array of `{ name, number, uuid, start, length }`. The bot phone match is `mention.number === botPhone` (i.e. `config.signalSender`). [CITED: [Signal-Bot framework types docs](https://signal-bot.readthedocs.io/en/stable/signal_bot_framework.types.html)] — Note: the signal-cli-rest-api JSON-RPC mode has had bugs where `mentions` was missing ([issue #805](https://github.com/bbernhard/signal-cli-rest-api/issues/805)) — we are on the REST receive path (`/v1/receive`), which appears unaffected, but Plan should include a fixture-based unit test plus a single live group `@mention` smoke probe before declaring SC#2 met.
4. **Quote field shape:** `dataMessage.quote.author` exists in signal-cli output. `[ASSUMED]` the value is the E.164 phone string (matches the form `envelope.source` takes on the REST API); some signal-cli versions expose `quote.authorNumber` and `quote.authorUuid` separately. **Plan must include defensive matching: accept any of `quote.author`, `quote.authorNumber` matching `botPhone`.** No live quote fixture available in repo.

**Primary recommendation:** Refactor `signalClient.send()` to take `{ to }` and a constructor-level `defaultTarget`; thread routing decision through `capture.js` only (D-02); ALTER TABLE `signal_capture` with three `ADD COLUMN IF NOT EXISTS`; envelope-level dedupe in receive-loop by hoisting the trigger evaluators to "compute all → fire once". Everything else is mechanical.

---

## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01** `signalClient.send(body, { to } = {})` — single send() method, optional `to`; when omitted, defaults to constructor `defaultTarget`. `to` is phone string (DM) OR `{ groupId }` (group).
- **D-02** `capture.js` is the only call site that picks `to` from envelope; all other senders (snooze, heartbeat, rules) pass no `to` and inherit the new default.
- **D-03** Global `sendsThisHour` rate-limit cap stays — no per-recipient bucket.
- **D-04** Default non-reply destination flips from `SIGNAL_RECIPIENT` to `SIGNAL_GROUP_ID` for ALL alerter-originated sends. `signal.js` constructor takes `defaultTarget` = `SIGNAL_GROUP_ID` (preferred) else `SIGNAL_RECIPIENT` (fallback).
- **D-05** Phase 33 VPS heartbeat path UNCHANGED — direct VPS→f1, never through alerter.
- **D-06** Reply triggers in group: (1) `@mention` of bot by phone number in `mentions[]`, (2) message starts with command keyword (existing DM command surface: `mute`, `snooze`, `status`, snooze grammar, experiment commands), (3) `dataMessage.quote.author == botPhone` (reply-to-bot).
- **D-07** LLM-classifier "directed at bot?" gate is v2 — deferred.
- **D-08** Bot captures EVERY group message into `signal_capture` regardless of trigger; reply fires only on D-06 triggers. Untriggered → `reply_target_kind='none'`.
- **D-09** SC#2: dedupe within a single envelope — message with both `@mention` AND command keyword fires ONE reply, not two.
- **D-10** Group `mute`/`snooze` accepted from any whitelisted farmer; mute applies globally; ack reply lands in-group.
- **D-11** `SIGNAL_FARMER_MAP` env, format `+phone:slug,+phone:slug,...` — three entries (f1, zoy, f3).
- **D-12** Unknown whitelisted phone → `farmos_person = '(unassigned)'` (B6 sentinel). Reply path still fires.
- **D-13** Person ID resolved + stamped on `signal_capture` row at capture time.
- **D-14** Three new nullable TEXT columns: `group_id`, `farmos_person`, `reply_target_kind` (`'dm' | 'group' | 'none'`).
- **D-15** Plain `ALTER TABLE ADD COLUMN`; no backfill; existing rows = NULL across all three.
- **D-16** Single `SIGNAL_GROUP_ID` env (base64 from `signal-cli --list-groups`).

### Claude's Discretion
- Internal shape of new options object on `send()` (extension fields beyond `to`).
- Where `SIGNAL_FARMER_MAP` parser lives (config.js vs new lookup module).
- How `dataMessage.groupInfo` is sniffed across signal-cli versions (verify with fixture-based unit test).
- Logging cardinality on routing decisions (default: per-decision at debug level).

### Deferred Ideas (OUT OF SCOPE)
- LLM-classifier group-reply gate (v2).
- Live farmOS API person lookup (composed with Phase 40 write-path).
- Per-recipient rate-limit buckets.
- Multi-group support (`SIGNAL_GROUP_IDS`).
- Group-thread richer behavior (per REQUIREMENTS.md l.76).
- Per-alert-class routing (group vs DM per category).
- First-time "register me" reply for unassigned senders.

---

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| **ROUTE-01** | Bot replies to `envelope.source`, not fixed recipient | `capture.js:146` is the single load-bearing call site (verified); thread `{ to: env.source }` through new `send()` opts (D-01/D-02). Existing envelope fixtures already include `source` so unit tests are trivial. |
| **ROUTE-02** | Bot participates in group thread, distinguishes DM vs group, no spam | `envelope.dataMessage.groupInfo.groupId` is the gate (verified shape). Trigger predicates: mention (`mentions[].number === botPhone`), command (existing parse functions already factored — `parseSnoozeCommand`, `parseExperimentCommand`), reply (`quote.author === botPhone`). Dedupe in receive-loop per D-09 by routing through a single `resolveReplyContext(env)` that returns `{ shouldReply, replyTarget, triggerKind }`. |
| **ROUTE-03** | Tag each message with farmOS person; unknown = `(unassigned)`, never silently dropped | `SIGNAL_FARMER_MAP` parsed once at boot into a `Map<phone, slug>`; lookup at capture time; row written regardless of trigger (D-08); `(unassigned)` literal is B6 sentinel — already a project convention. The "never silently dropped" property is satisfied by the capture row existing, even when `reply_target_kind='none'`. |

---

## Implementation Approach

### File-by-file change set

| File | Change | Pattern to Follow |
|------|--------|-------------------|
| `src/agents/alerter/src/config.js` | Add `signalGroupId` (optional env `SIGNAL_GROUP_ID`), `signalFarmerMap` (parsed `Map<E164, slug>` from `SIGNAL_FARMER_MAP`); add helper `resolveDefaultTarget()` returning `{ groupId }` if set, else phone string `signalRecipient`. | Same shape as `signalAdditionalSenders` parse landed in commit `c8e9ac1`. |
| `src/agents/alerter/src/signal.js` | (1) Constructor accepts `defaultTarget`. (2) `send(body, { to, bypassCap } = {})` — if `to` omitted, uses `defaultTarget`. (3) Translate `to` to recipients-array string: phone → `[phone]`; `{ groupId }` → `[\`group.${groupId}\`]`. (4) `maskNumber` log path branches for group ("[signal] sent -> group:<8-char-prefix>…"). | Existing `send()` shape (line 25). Recipients array stays length-1. |
| `src/agents/alerter/src/capture.js` | Compute `replyTarget` once at top of `handle()` from envelope. Replace `signalClient.send(replyText)` (line 146) with `signalClient.send(replyText, { to: replyTarget })`. Pass `replyTargetKind`, `groupId`, `farmosPerson` to `insertCapture()` (new columns). | Existing envelope unwrap at line 60-64 is the template. |
| `src/agents/alerter/src/receive-loop.js` | New helper `resolveGroupReplyContext(env, config)` → `{ shouldReply, triggerKind }`. Group gate (`dataMessage.groupInfo?.groupId`) inserted AFTER whitelist (line 102) and BEFORE the command/snooze/capture branches. In group: only fall through to command + capture branches if `shouldReply` per D-06 triggers; else go straight to capture-only path (D-08). Trigger evaluation MUST be done ONCE per envelope and reused by both the command branch and capture (D-09). | Existing whitelist set at line 89-91 — extend to also expose group_id. |
| `src/agents/alerter/src/capture-db.js` | `initDb()` adds `ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS group_id text`, `... farmos_person text`, `... reply_target_kind text`. Add params to `insertCapture()` row shape + INSERT SQL. | Postgres native `ADD COLUMN IF NOT EXISTS` — idempotent, no DO-block needed (contrast `schema_migration.js:24` which only needs the wrapper for `ADD CONSTRAINT`). `signal_capture` is a regular table per file comment line 2, NOT a hypertable, so no partitioning constraints apply. |
| `src/agents/alerter/src/index.js` (boot wire-up) | Pass `signalGroupId`, `signalFarmerMap` from config to `createSignalClient` (defaultTarget) and `createCapturePipeline` (person lookup). No change to `applyEvent` action handling at line 99-115 — heartbeat/snooze_ack/send actions all inherit group default via constructor (D-04). | Existing config-threading pattern. |
| `src/agents/alerter/src/snooze.js`, `rules.js`, `heartbeat.js` | NO CHANGE at refactor time (D-02). Their `signalClient.send()` calls in `index.js:99-115` inherit the new group default. | — |
| `docker-compose.override.yml` (alerter env block ~l.75-77) | Add `SIGNAL_GROUP_ID=${SIGNAL_GROUP_ID}` and `SIGNAL_FARMER_MAP=${SIGNAL_FARMER_MAP}`. | Mirror SIGNAL_ADDITIONAL_SENDERS at line 77 — exactly the Phase 36 commit `c8e9ac1` pattern. |
| `.env` (operator side, not committed) | Operator sets `SIGNAL_GROUP_ID` from `signal-cli --list-groups` (or REST `GET /v1/groups/<number>` returns `internal_id`) and populates `SIGNAL_FARMER_MAP=+phoneF1:f1,+phoneZoy:zoy,+phoneF3:f3`. | Document in 37-RUNBOOK.md (planner to author). |

### Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|--------------|----------------|-----------|
| Pick reply target from envelope | alerter `capture.js` | — | D-02; only place with both source + groupInfo in scope |
| Group vs DM trigger gate | alerter `receive-loop.js` | — | Already where whitelist gate lives |
| farmOS person resolution | alerter `config.js` (static map) | — | Live API lookup deferred to Phase 40 |
| Schema migration | alerter `capture-db.js` `initDb()` | — | Boot-time idempotent ALTER, mirrors existing init pattern |
| Group target translation (`{groupId}` → REST recipients string) | alerter `signal.js` | — | Single choke point; bridge is not involved |
| Compose env wiring | `docker-compose.override.yml` | — | Pattern from Phase 36 `c8e9ac1` |

### Trigger-evaluation flow (for receive-loop dedupe — D-09)

```
tick():
  for env in receive():
    if not whitelisted(env.source): drop, continue
    isGroup = !!env.dataMessage?.groupInfo?.groupId
    groupId = env.dataMessage?.groupInfo?.groupId ?? null

    if isGroup:
      triggers = collectTriggers(env, botPhone)   // → Set<'mention'|'command'|'quote'>
      shouldReply = triggers.size > 0
    else:
      triggers = new Set(['dm'])
      shouldReply = true

    replyTarget = isGroup ? { groupId } : env.source
    replyTargetKind = isGroup ? (shouldReply ? 'group' : 'none') : 'dm'

    // command branch — ONLY run if (DM) OR (group + 'command' in triggers)
    // capture branch — ALWAYS run if text||attachments (D-08), passing replyTarget+kind
```

`collectTriggers` is pure and unit-testable in isolation. It is called ONCE per envelope. The command branch checks set membership rather than re-parsing/re-firing, eliminating double-reply.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | jest (Node 20, used throughout alerter) |
| Config file | `src/agents/alerter/package.json` (jest config inline) |
| Quick run command | `cd src/agents/alerter && npx jest <pattern>` |
| Full suite command | `cd src/agents/alerter && npx jest` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|--------------|
| ROUTE-01 | DM reply lands on `envelope.source`, not `signalRecipient` | unit | `npx jest test/capture.test.js -t "replies to envelope.source"` | ⚠ Wave 0 — add case to existing capture.test.js |
| ROUTE-01 | `signalClient.send(body, { to })` overrides default target | unit | `npx jest test/signal.test.js -t "send to override target"` | ⚠ Wave 0 — extend signal.test.js |
| ROUTE-01 | DM reply does NOT leak to group when `SIGNAL_GROUP_ID` set | unit | `npx jest test/capture.test.js -t "DM stays DM under group default"` | ⚠ Wave 0 |
| ROUTE-02 | Untriggered group message produces capture row but NO send | unit | `npx jest test/receive-loop.test.js -t "silent group listener"` | ⚠ Wave 0 |
| ROUTE-02 | `@mention` of bot phone in group fires exactly ONE reply to groupId | unit | `npx jest test/receive-loop.test.js -t "mention triggers single reply"` | ⚠ Wave 0 |
| ROUTE-02 | Command keyword in group fires reply to groupId (not sender DM) | unit | `npx jest test/receive-loop.test.js -t "group command reply lands in group"` | ⚠ Wave 0 |
| ROUTE-02 | `quote.author === botPhone` fires reply to groupId | unit | `npx jest test/receive-loop.test.js -t "quote-to-bot triggers reply"` | ⚠ Wave 0 |
| ROUTE-02 D-09 | Envelope with `@mention` AND command keyword fires ONE reply | unit | `npx jest test/receive-loop.test.js -t "envelope dedupe — mention+command"` | ⚠ Wave 0 |
| ROUTE-02 D-10 | `mute`/`snooze` in group from any whitelisted farmer succeeds; ack lands in group | unit | `npx jest test/receive-loop.test.js -t "any farmer can mute in group"` | ⚠ Wave 0 |
| ROUTE-03 | Known phone resolves to slug in `farmos_person` column | unit | `npx jest test/capture-db.test.js -t "farmos_person stamped from map"` | ⚠ Wave 0 |
| ROUTE-03 | Unknown whitelisted phone → `farmos_person='(unassigned)'`; reply STILL fires | unit | `npx jest test/capture-db.test.js -t "unassigned sentinel and still replies"` | ⚠ Wave 0 |
| D-04 | Heartbeat send (no `to` arg) targets group when `SIGNAL_GROUP_ID` set | unit | `npx jest test/signal.test.js -t "default target = group when configured"` | ⚠ Wave 0 |
| D-04 | Heartbeat falls back to `signalRecipient` when `SIGNAL_GROUP_ID` unset | unit | `npx jest test/signal.test.js -t "default target = phone when group unset"` | ⚠ Wave 0 |
| D-14/D-15 | `ALTER TABLE ADD COLUMN IF NOT EXISTS` idempotent across two boots | unit | `npx jest test/capture-db.test.js -t "schema migration idempotent"` | ⚠ Wave 0 |
| D-14 | Existing pre-migration rows have NULL `group_id` / `farmos_person` / `reply_target_kind`, downstream treats as DM/unknown | unit | `npx jest test/capture-db.test.js -t "historical rows readable post-migration"` | ⚠ Wave 0 |
| 999.20 proof-of-fix | f2 DMs bot; bot reply lands on f2 only | live UAT | manual: f2 sends `ping P37-<rand>`; verify reply to f2; verify no Signal traffic to f1 in window | manual |
| D-04 visibility | Next alert/heartbeat lands in group, not f1 DM | live UAT | wait for next heartbeat (or simulate via state) | manual |
| ROUTE-03 unassigned | Send DM from non-mapped whitelisted number; verify row in DB with `(unassigned)` | live UAT | psql query: `select sender, farmos_person from signal_capture order by captured_at desc limit 1` | manual |
| D-09 envelope-level dedupe (live) | f2 group message: `@bot mute` — verify ONE Signal ack, ONE capture row | live UAT | manual replay; count sends in signal-cli sent log | manual |

### Fixture Requirements (Wave 0)

The existing `test/fixtures/envelopes/` has `text.json`, `snooze.json`, `photo-batch.json`, `audio.json` — all DM shape. Wave 0 must add:

- `group-silent.json` — group message, no trigger, no @mention, not a command, no quote-to-bot
- `group-mention.json` — `dataMessage.mentions: [{name, number: BOT_PHONE, uuid: "...", start: 0, length: 1}]`
- `group-command.json` — `dataMessage.message: "mute"` inside a group
- `group-reply-to-bot.json` — `dataMessage.quote: { author: BOT_PHONE, authorNumber: BOT_PHONE, id: 12345, text: "alerts muted for 24h" }`
- `group-mention-and-command.json` — both triggers in one envelope (dedupe target)
- `group-unknown-sender.json` — whitelisted but not in `SIGNAL_FARMER_MAP`

### Sampling Rate
- **Per task commit:** `npx jest test/signal.test.js test/receive-loop.test.js test/capture.test.js test/capture-db.test.js` (~12 sec)
- **Per wave merge:** `cd src/agents/alerter && npx jest` (full suite)
- **Phase gate:** Full suite green + four live UAT lines above before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `test/fixtures/envelopes/group-*.json` (six new fixtures)
- [ ] `test/receive-loop.test.js` extended with group cases + dedupe
- [ ] `test/signal.test.js` extended with `{ to }` override + default-target precedence
- [ ] `test/capture.test.js` extended with reply-target threading
- [ ] `test/capture-db.test.js` extended with migration idempotency + new-column shape
- [ ] No new framework install needed — jest already in package.json

---

## Risks & Landmines

### Codebase-specific

1. **Rate-limit cap is global, not per-target — group migration could starve alerts.** With `SIGNAL_GROUP_ID` set, ALL alerter sends count against the same `sendsThisHour` bucket (default 20/h, configurable). If the group becomes chatty and triggers many command-acks, the next CRITICAL RH alert could be dropped silently. **Mitigation:** keep `bypassCap=true` on heartbeat (already there at index.js:107) and add a follow-up note to operator: bump `ALERT_MAX_SENDS_PER_HOUR` if observed group traffic crowds out alerts. Per-recipient buckets are explicitly deferred.

2. **`feedback_alerter_env_convention_bridge_http_url`** — Phase 37 doesn't introduce new bridge HTTP calls (it touches alerter↔signal-cli only), so the BRIDGE_HTTP_URL pitfall doesn't directly bite. BUT: the existing receive-loop experiment dispatch at line 32 reads `BRIDGE_HTTP_URL`; any new dispatch added during this phase MUST follow the same convention. **Risk: LOW.**

3. **Phase 33 VPS heartbeat path (D-05) MUST NOT inherit group default.** Verified: the VPS heartbeat receiver path does NOT route through alerter — it's direct VPS→f1 via signal-cli. Since this phase changes only the alerter's `defaultTarget`, the VPS path is untouched. **No code change needed; document explicitly in plan to prevent regression.**

4. **`signal-cli deviceId=2` blocker (project_phase31_shipped).** PRE-01 is the prerequisite — it puts signal-cli as primary (deviceId=1). Phase 37 PRESUMES PRE-01/02 are closed. If PRE is still pending: group sends MAY or MAY NOT work on deviceId=2 (it's plausible they do for groups while DM receive-400 was a separate constraint, but this is unverified). **Plan must include a one-shot live group-send probe AS THE FIRST WAVE 0 STEP** before committing to the full implementation — fail-fast if signal-cli linked-device mode rejects group sends.

5. **Bot phone number source for mention matching.** `config.signalSender` is the bot's own E.164 (used as the `number=` in `/v2/send` body at signal.js:40 and `/v1/receive/<number>` at line 57). Mention matching is `mentions[].number === config.signalSender`. **No new env needed.**

6. **`SIGNAL_FARMER_MAP` parsing ambiguity around colon.** Phone strings start with `+`, no colons internally. Safe to split each comma-separated entry on the first `:`. Empty/whitespace entries should be dropped (mirror the `signalAdditionalSenders` parse at config.js:42). Document the grammar in a comment.

7. **`signal_capture` schema migration on a populated table during a hot alerter restart.** Table is small (per file comment: "regular table; per-farmer volume too low for hypertable"). `ALTER TABLE ADD COLUMN IF NOT EXISTS ... text` on Postgres adds a NULL column with no rewrite — fast and non-blocking. **Risk: LOW.** No special hypertable syntax needed.

8. **Group send timestamp/ack semantics.** signal-cli's group send response shape matches DM (returns `{ timestamp }`). No change to send() ok/return-value contract.

### Envelope-shape risks (MEDIUM confidence)

9. **`quote.author` vs `quote.authorNumber` cross-version drift.** `[ASSUMED]` author is E.164 phone. Some signal-cli versions populate `authorNumber` and `authorUuid` separately. **Mitigation:** match on `(quote.author || quote.authorNumber) === botPhone`. Add a fixture-based test for both shapes.

10. **`mentions[]` reportedly missing in some signal-cli-rest-api builds (issue #805, JSON-RPC mode only — REST mode appears unaffected).** Add a live group `@mention` smoke probe to Wave 0 to fail-fast if the in-prod signal-cli image returns no `mentions` field. If absent, fall back to "exact textual `@botname` match" is NOT acceptable (D-06 explicitly says match by phone, not display name) — would need to upgrade the signal-cli-rest-api image.

11. **`groupInfo.type === "DELIVER"` vs `"UPDATE"`/`"QUIT"`.** Capture-and-ignore non-DELIVER types (admin events). The whitelist gate at receive-loop.js:102 currently doesn't filter on this — fine, just ensure trigger-collection rejects envelopes lacking `dataMessage.message` and `dataMessage.attachments` (which UPDATE/QUIT envelopes lack). Easy.

---

## Open Questions

1. **Should `farmos_person` map be live-reloadable, or boot-only?** D-12 says "operator updates env + restart to map them" → boot-only is the locked decision. Confirmed; no question.

2. **`reply_target_kind='none'` rows — does Phase 38 extraction skip them or process them?** Out of scope for Phase 37 (we just write the column). Flag for Phase 38 discuss-phase.

3. **What's the `SIGNAL_GROUP_ID` raw value format the operator pastes into `.env`?** Operator gets it via `signal-cli --list-groups -d`, which prints lines like `Id: <base64>=`. The REST API also exposes it via `GET /v1/groups/<number>` returning `internal_id`. **The env value should be the bare base64 string (no `group.` prefix); signal.js prepends `group.` when building the recipients array.** Document this in the runbook explicitly — easy to get wrong.

4. **Do we need to acknowledge an unknown sender's first message ("hi, I see you but you're not in my map")?** D-12 rejected this in favor of plain reply + unassigned tag. Closed.

---

## Sources

### Primary (HIGH confidence — in-repo)
- `src/agents/alerter/src/signal.js` lines 5-83 — current `send()` shape, `recipients: [recipient]` array
- `src/agents/alerter/src/receive-loop.js` lines 87-155 — whitelist gate, command + capture branches
- `src/agents/alerter/src/capture.js` lines 57-159 — envelope unwrap, single send call site at line 146
- `src/agents/alerter/src/capture-db.js` lines 1-62 — current schema, `initDb()` pattern
- `src/agents/alerter/src/config.js` lines 34-81 — env parsing, `signalAdditionalSenders` template
- `src/agents/alerter/src/index.js` lines 99-115 — all send-action call sites (`send`/`recovery`/`heartbeat`/`snooze_ack`)
- `src/agents/alerter/test/fixtures/envelopes/*.json` — DM envelope shapes (no group fixtures yet)
- `src/mission-control/bridge/src/schema_migration.js` lines 24-40 — idempotent migration pattern (DO-block for ADD CONSTRAINT; ADD COLUMN IF NOT EXISTS doesn't need it)
- `docker-compose.override.yml` lines 75-77 — Phase 36 `SIGNAL_ADDITIONAL_SENDERS` env-wiring template

### Secondary (MEDIUM confidence — external)
- [signal-cli-rest-api issue #719 — Help sending to a group](https://github.com/bbernhard/signal-cli-rest-api/issues/719) — confirms `recipients: ["group.<base64>"]` shape on `/v2/send`
- [signal-cli-rest-api discussion #351 — How do you send a message to a group?](https://github.com/bbernhard/signal-cli-rest-api/discussions/351)
- [signal-cli-rest-api issue #805 — mentions missing in JSON-RPC mode](https://github.com/bbernhard/signal-cli-rest-api/issues/805) — confirms mentions array exists in REST mode
- [AsamK signal-cli issue #388 — example envelope JSON with groupInfo](https://github.com/AsamK/signal-cli/issues/388) — confirms `dataMessage.groupInfo.{groupId, type, members, name}` shape
- [Signal-Bot framework types docs](https://signal-bot.readthedocs.io/en/stable/signal_bot_framework.types.html) — Mention shape: `{name, number, uuid, start, length}`

### Tertiary (LOW — `[ASSUMED]`)
- `quote.author` value is E.164 phone matching `envelope.source` format — no live fixture; must be verified in Wave 0 smoke

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `dataMessage.quote.author` is E.164 phone matching `envelope.source` format | Risks #9, Open Q | Reply-to-bot trigger silently broken; mitigated by matching `quote.author \|\| quote.authorNumber` AND adding live smoke |
| A2 | signal-cli-rest-api REST receive (`/v1/receive`) populates `dataMessage.mentions[]` reliably (issue #805 affects JSON-RPC only) | Risks #10 | `@mention` trigger broken; mitigated by Wave 0 live smoke probe |
| A3 | signal-cli deviceId=1 (post-PRE-01) supports group sends with same `/v2/send` shape as DMs | Risks #4 | Whole phase blocked; mitigated by Wave 0 group-send probe as first task |
| A4 | The `SIGNAL_GROUP_ID` operator pastes from `signal-cli --list-groups` is the bare base64 string, with code prepending `group.` | Open Q #3 | Misconfig at deploy time; mitigated by runbook screenshot + boot-time format validation in config.js |

---

## Metadata

**Confidence breakdown:**
- Code-level touch points + responsibility map: **HIGH** — all paths read in-repo
- Send-to-group request body shape: **HIGH** — multiple bbernhard issues confirm
- Envelope groupInfo shape: **HIGH** — confirmed in AsamK envelope example
- Mention shape: **MEDIUM-HIGH** — Signal-Bot docs confirm; one live group `@mention` smoke needed
- Quote shape: **MEDIUM** — `[ASSUMED]` field name `author`; defensive matching planned
- ALTER TABLE migration: **HIGH** — Postgres native idempotent syntax; signal_capture is regular table, not hypertable

**Research date:** 2026-05-11
**Valid until:** 2026-06-10 (signal-cli ecosystem moves slowly; in-repo facts don't expire)

## RESEARCH COMPLETE
