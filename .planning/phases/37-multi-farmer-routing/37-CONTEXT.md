# Phase 37: Multi-farmer Routing - Context

**Gathered:** 2026-05-11
**Status:** Ready for planning

<domain>
## Phase Boundary

Route Signal **replies** to `envelope.source` (the actual sender), migrate **alerts** to the "Mushroom Farm" group thread, participate in that group via hard triggers (mention/command/reply-to-bot), and tag every captured message with a farmOS person ID resolved through a static env map. Closes ROUTE-01/02/03 + the (a) sub-part of backlog 999.20; the LLM-classifier group-reply gate is explicitly v2.

</domain>

<decisions>
## Implementation Decisions

### Reply Routing Shape
- **D-01:** `signalClient.send(body, { to } = {})` — keep the single `send()` method on `signal.js`, add an optional `to` option. When `to` is omitted, behavior is unchanged (defaults to the existing recipient — i.e. alert/heartbeat call sites stay byte-stable at refactor time; their *target value* migrates to the group via env, see D-04). `to` accepts either a phone-number string (DM) or `{ groupId }` (group).
- **D-02:** `capture.js` is the one place that picks the reply target. It already has `envelope.source` and `envelope.dataMessage.groupInfo`; it threads that to `signalClient.send(replyText, { to: <source or groupId> })`. Other senders (snooze, heartbeat, rules) do NOT participate in per-call targeting — they rely on the new default.
- **D-03:** Global rate-limit cap (`sendsThisHour`) stays single/global across all targets. No per-recipient bucket in this phase.

### Alert Migration to Group
- **D-04:** Default non-reply destination flips from `SIGNAL_RECIPIENT` (f1) to `SIGNAL_GROUP_ID` for ALL alerter-originated sends — alerts, heartbeat banner, snooze acks, rule fires. The group is "the heart of the farm"; this is where f1/f2/f3 already coordinate. Implementation: `signal.js` constructor takes a `defaultTarget` parameter built from `SIGNAL_GROUP_ID` (preferred) else `SIGNAL_RECIPIENT` (fallback). Existing callers that pass no `to` now hit the group.
- **D-05:** Phase 33 VPS outage path is UNCHANGED — it never went through alerter; it remains direct VPS→f1 (operator). Loss-of-bot still alerts the operator personally; group can't help when alerter is the dead component.

### Group Participation Policy
- **D-06:** v1.7 reply triggers (hard, deterministic):
  1. `@mention` of bot — matched against bot's **phone number** in `dataMessage.mentions[]` (NOT against display name — robust to Signal profile changes)
  2. Message starts with an explicit command keyword (same surface as DM commands today: `mute`, `snooze`, `status`, plus existing Phase 25/29 commands)
  3. Reply-to-bot — `envelope.dataMessage.quote.author == bot_number`
- **D-07:** LLM-classifier "is this directed at the bot?" gate is **v2** — explicitly deferred. Captured as deferred idea. SC#2 stays falsifiable on hard triggers only.
- **D-08:** Bot **captures every group message** into `signal_capture` (silent listener) regardless of trigger. Reply fires only on D-06 triggers. Honors ROUTE-03 "never silently dropped" via the capture row. Untriggered messages have `reply_target_kind='none'`.
- **D-09:** SC#2 "exactly one reply per envelope" — receive-loop must dedupe within a single envelope (e.g. message that contains both `@mention` AND a command keyword fires ONE reply, not two). No cross-message cooldown beyond the global cap.
- **D-10:** Group `mute` / `snooze` commands accepted from **any whitelisted farmer** in the group, not just operator. Mute applies globally for the chamber; ack reply lands in-group so all see who muted. Matches the whole-farm shared-awareness framing.

### farmOS Person Resolution
- **D-11:** `SIGNAL_FARMER_MAP` env, format `+phone:slug,+phone:slug,...` — three entries for v1.7 (f1, zoy, f3). Static config; live farmOS API lookup is deferred to a Phase 40-adjacent task (write-path needs `/api/user/people` anyway, can build the cache then).
- **D-12:** Unknown phone (whitelisted but not in `SIGNAL_FARMER_MAP`) → `farmos_person = '(unassigned)'` (B6 sentinel literal). Reply path **still fires** — they're a real farmer, just not mapped yet. Operator updates env + restart to map them.
- **D-13:** Person ID is resolved and stamped on the `signal_capture` row at capture time. Phase 38 reads `farmos_person` directly. No re-resolution at extraction.

### Signal Capture Schema Additions
- **D-14:** Three new nullable TEXT columns on `signal_capture`:
  - `group_id` — base64 Signal group ID when source is the group; NULL for DM
  - `farmos_person` — farmOS person slug from `SIGNAL_FARMER_MAP`, or `(unassigned)` literal, or NULL for system rows
  - `reply_target_kind` — `'dm' | 'group' | 'none'`, captures the routing decision for audit ("why didn't the bot reply to this?")
- **D-15:** Migration is plain `ALTER TABLE ADD COLUMN`. Existing rows get NULL across all three (they're historical f1 DMs; downstream code treats NULL `group_id` as DM, NULL `farmos_person` as unknown). No backfill.

### Group Config
- **D-16:** Single `SIGNAL_GROUP_ID` env (base64 from signal-cli `--list-groups`). One canonical "Mushroom Farm" group. Future expansion to comma-separated list is trivial and deferred until a second group exists.

### Claude's Discretion
- Internal API shape of the new options object on `send()` — extension fields beyond `to` (e.g. `mentions`, `quote`) are Claude's call as needed; not user-facing.
- Where the `SIGNAL_FARMER_MAP` parser lives (config.js vs new lookup module) — Claude's call.
- How `dataMessage.groupInfo` is sniffed across signal-cli versions — Claude's call; verify with a unit test against captured fixture envelopes.
- Logging cardinality on the new routing decision (log every routing pick? sample?) — Claude's call, default to per-decision at debug level.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase + Requirements
- `.planning/ROADMAP.md` §"Phase 37" — goal + success criteria (l.154–163)
- `.planning/ROADMAP.md` §"Phase 999.20" (l.423) — original 999.20 backlog entry; this phase implements sub-part (a) (reply routing + group participation). Re-read for the embedded code-path notes.
- `.planning/REQUIREMENTS.md` §ROUTE (l.20–24) — ROUTE-01/02/03 verbatim
- `.planning/REQUIREMENTS.md` §non-goals (l.76) — group-thread richer behavior is explicitly out

### Schema + Conventions
- `/mnt/slime-kingdom/shared/farmos/.planning/notes/` (lock commit `d4e5a30`, 2026-05-11) — FarmOS schema strawman + session-chat; specifically the **B6 sentinel pattern** (`(unassigned)` literal) and **B7 log type catalog**. farmOS people directory shape lives here.

### Code-Level Touch Points (for planner)
- `src/agents/alerter/src/signal.js` — `createSignalClient()` constructor + `send()` signature change
- `src/agents/alerter/src/capture.js:146` — the load-bearing site flagged in 999.20; now threads `envelope.source`/group context to `send({ to })`
- `src/agents/alerter/src/receive-loop.js:87–102` — whitelist + group-id gate; envelope-level dedupe per D-09
- `src/agents/alerter/src/capture-db.js` — `signal_capture` schema; ALTER TABLE for D-14
- `src/agents/alerter/src/snooze.js`, `rules.js`, `heartbeat.js` — all senders that will inherit the new group default via D-04 (no per-call change required at refactor time)
- `docker-compose.override.yml` — env plumbing for `SIGNAL_GROUP_ID` + `SIGNAL_FARMER_MAP` (Phase 36 commit `c8e9ac1` is the pattern to follow for `SIGNAL_ADDITIONAL_SENDERS`)

### Prior-Phase Context
- `.planning/phases/36-*/36-CONTEXT.md` — primary re-registration shipped; whitelist now operational for f2/f3
- Phase 33 group migration constraint: VPS heartbeat receiver path (`project_phase33_shipped`) stays direct-to-f1; do NOT route through alerter group default.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `signal.js` already has clean `send(body, opts)` shape (today's `opts` is just `{bypassCap}`) — adding `to` slots into existing options object
- `receive-loop.js` already filters envelopes by whitelist (`allowedSenders` Set, l.102) — group-id gate is a parallel check on `dataMessage.groupInfo.groupId`
- `capture-db.js` ULID + sender pattern already in place — adding columns is mechanical
- `config.js` is the conventional landing zone for new env (`SIGNAL_GROUP_ID`, `SIGNAL_FARMER_MAP`) — follow the `SIGNAL_ADDITIONAL_SENDERS` template just landed in commit `c8e9ac1`

### Established Patterns
- Whitelist-by-env (Phase 36): comma-separated phone list parsed into a Set at boot. `SIGNAL_FARMER_MAP` follows same shape with `:slug` suffix.
- Alerter ↔ bridge ↔ signal-cli compose-network topology is settled; this phase touches alerter only.
- Rate-limit cap stays global (cf. `feedback_alerter_env_convention_bridge_http_url` and existing `sendsThisHour` pattern).

### Integration Points
- `signalClient.send()` is the choke point — every alerter outbound passes through it. Refactor here, everything downstream gets the new routing for free.
- `signal_capture` is the choke point for Phase 38 — extraction will read `group_id`, `farmos_person`, `reply_target_kind` to compose extraction context.

</code_context>

<specifics>
## Specific Ideas

- User language: the Mushroom Farm group is "**the heart of the farm**" — emphasizes that the group migration of alerts (D-04) is not just plumbing, it's matching the social locus of farm coordination.
- 999.20 embarrassment vector: f2 (zoy) DM'd "pong P36-181143", reply landed on f1, who saw "three replies in a row to messages they didn't all send." This is the failure mode the phase exists to retire — the proof-of-fix UAT should replay this exact shape (f2 DMs → reply to f2 only) before any soak.
- The Phase 36 commit `c8e9ac1` (`SIGNAL_ADDITIONAL_SENDERS` plumbed through compose) MADE this bug user-visible by default for the first time — it was theoretical before zoy was whitelisted. Phase 37 closes the loop opened by 36.

</specifics>

<deferred>
## Deferred Ideas

- **LLM-classifier group-reply gate (v2)** — "is this group message directed at the bot?" classifier on every group message, gating the reply path beyond hard triggers. Cost + latency tradeoff to revisit once group volume is measurable. Goes into a follow-up phase or 999.x.
- **Live farmOS API person lookup** — replace static `SIGNAL_FARMER_MAP` with `/api/user/people` query + local cache. Compose with Phase 40 write-path (which already needs the people endpoint).
- **Per-recipient rate-limit buckets** — current global cap is fine for v1.7; revisit if a chatty group thread starves alert-class sends.
- **Multi-group support** — comma-separated `SIGNAL_GROUP_IDS` + per-group config. One group today; trivial to extend when a second appears.
- **Group-thread richer behavior** (already out per REQUIREMENTS.md l.76) — proactive nudges, multi-farmer collaboration on the same draft. v1.8+.
- **Per-alert-class routing** (group vs DM per category) — keep all alerts on group for v1.7; revisit if heartbeat-noise complaint surfaces.
- **First-time "register me" reply for unassigned senders** — rejected D-12 in favor of plain reply + unassigned tag; revisit if onboarding ergonomics need it.

</deferred>

---

*Phase: 37-multi-farmer-routing*
*Context gathered: 2026-05-11*
