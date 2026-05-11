# Phase 37: Multi-farmer Routing - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-11
**Phase:** 37-multi-farmer-routing
**Areas discussed:** Reply routing shape, Group participation policy, farmOS person resolution, Group ID + capture schema

---

## Area Selection

| Option | Description | Selected |
|--------|-------------|----------|
| Reply routing shape | How signalClient.send() takes per-call recipient | ✓ |
| Group participation policy | Trigger for bot reply in group | ✓ |
| farmOS person resolution | Phone → farmOS person ID mapping | ✓ |
| Group ID + capture schema | env + signal_capture column additions | ✓ |

---

## Reply Routing Shape

| Option | Description | Selected |
|--------|-------------|----------|
| send(body, {to}) | Single send(), optional `to` override; defaults to SIGNAL_RECIPIENT | ✓ |
| sendTo(target, body) | New explicit method | |
| send() + sendToGroup() | Split DM and group paths | |

**User's choice:** `send(body, {to})` — minimal blast radius.

| Option | Description | Selected |
|--------|-------------|----------|
| capture.js threads source | capture() reads envelope.source/groupInfo and passes to send | ✓ |
| receive-loop computes + injects | receive-loop builds replyTarget object | |

**User's choice:** capture.js threads source.

| Option | Description | Selected |
|--------|-------------|----------|
| Default to SIGNAL_RECIPIENT (f1) | Alerts continue to f1 | |
| Broadcast to all whitelisted | f1+f2+f3 | |
| New SIGNAL_ALERT_RECIPIENT env | Decouple alert destination | |

**User's choice:** *Other* — "we will want to migrate the alarms to the group where f123 and bot share thread. this group is the heart of the farm btw" → captured as D-04 (alert migration to group is in-scope).
**Notes:** Triggered the follow-up batch on Alert Migration scope.

| Option | Description | Selected |
|--------|-------------|----------|
| Keep single global cap | Existing sendsThisHour stays global | ✓ |
| Per-target cap | Per-recipient/group bucket | |

**User's choice:** single global cap.

---

## Alert Migration (follow-up batch)

| Option | Description | Selected |
|--------|-------------|----------|
| In Phase 37, alerts → group | Default destination flips to SIGNAL_GROUP_ID | ✓ |
| Phase 37 ships group reply only | Migrate alerts in follow-up | |
| Configurable per category | Per-alert-class routing | |

**User's choice:** In Phase 37, alerts → group.

| Option | Description | Selected |
|--------|-------------|----------|
| VPS → f1 (operator) only | Outage stays direct-to-operator | ✓ |
| VPS → group | Outage also hits group | |

**User's choice:** VPS → f1 only.

---

## Group Participation Policy

| Option | Description | Selected |
|--------|-------------|----------|
| @mention of bot | mentions[] match on bot phone | ✓ |
| Explicit slash/keyword commands | mute/status/snooze/etc. | ✓ |
| Replies-to-bot-message | quote.author == bot | ✓ |
| Every group message | Always reply | |

**User's choice:** *Other* — "silently listen in to all comms, and reply when appropriate heuristically".
**Notes:** Triggered follow-up to bound the heuristic; the three checked options are the v1 hard-triggers under D-06. The "heuristic" was interpreted as the v2 LLM classifier and deferred (see next batch).

| Option | Description | Selected |
|--------|-------------|----------|
| Capture all, reply only on trigger | Every group msg → signal_capture row | ✓ |
| Capture only triggered messages | Smaller DB | |
| Capture only known senders | Drop unknowns at receive-loop | |

**User's choice:** Capture all.

| Option | Description | Selected |
|--------|-------------|----------|
| Any group member can mute | Whole-farm shared awareness | ✓ |
| Only operator (f1) can mute | Ops control on f1 | |
| Mute is per-farmer (DM-only) | No group mute | |

**User's choice:** Any group member can mute.

| Option | Description | Selected |
|--------|-------------|----------|
| Match bot's phone in mentions[] | Robust to profile changes | ✓ |
| Match configurable display name | Substring match on "mushy"/"bot" | |
| Both | Mention OR keyword | |

**User's choice:** Phone in mentions[].

---

## Reply Heuristic Bounding (follow-up batch)

| Option | Description | Selected |
|--------|-------------|----------|
| Hard triggers v1 + LLM-gate v2 | Phase 37 hard-triggers only; LLM classifier deferred | ✓ |
| LLM gates every group message now | Classifier on every message | |
| Hard triggers + name keyword | Triggers + substring match | |

**User's choice:** Hard triggers v1 + LLM-gate v2.

| Option | Description | Selected |
|--------|-------------|----------|
| 1 reply per envelope (already SC#2) | No special cooldown | ✓ |
| Per-trigger cooldown | Suppress duplicate triggers within N seconds | |

**User's choice:** 1 reply per envelope.

---

## farmOS Person Resolution

| Option | Description | Selected |
|--------|-------------|----------|
| Env map for v1.7, farmOS API follow-up | SIGNAL_FARMER_MAP static config | ✓ |
| Live farmOS API on every message | Query /api/user/people per envelope | |
| Local cache, refresh on miss | Disk cache + TTL | |

**User's choice:** Env map (live API deferred).

| Option | Description | Selected |
|--------|-------------|----------|
| New column on signal_capture | farmos_person column, populated at capture | ✓ |
| Computed at extraction time | Phase 38 resolves per row | |
| Both — store and re-resolve | | |

**User's choice:** New column.

| Option | Description | Selected |
|--------|-------------|----------|
| Capture, tag (unassigned), reply normally | Whitelisted-but-unmapped still gets a reply | ✓ |
| Capture, tag (unassigned), one-time "register me" reply | Friendly onboarding | |
| Capture but no reply for unassigned | Silent capture | |

**User's choice:** Capture + reply normally with (unassigned) tag.

---

## Group ID + Capture Schema

| Option | Description | Selected |
|--------|-------------|----------|
| Single SIGNAL_GROUP_ID env | One canonical group | ✓ |
| Comma-separated SIGNAL_GROUP_IDS | Future-proof multi-group | |
| Group whitelist file | JSON/YAML config | |

**User's choice:** Single env.

| Option | Description | Selected |
|--------|-------------|----------|
| group_id + farmos_person + reply_target_kind | Three columns | ✓ |
| group_id + farmos_person only | Skip reply_target_kind | |
| Single context JSON column | routing_context JSON | |

**User's choice:** Three columns.

| Option | Description | Selected |
|--------|-------------|----------|
| ALTER TABLE, NULL for old rows | No backfill | ✓ |
| ALTER + backfill from sender map | Backfill historical rows | |

**User's choice:** ALTER + NULL.

---

## Claude's Discretion

- Internal `send()` option-object extensions beyond `to` (mentions, quote)
- `SIGNAL_FARMER_MAP` parser placement (config.js vs new lookup module)
- `dataMessage.groupInfo` cross-version sniff strategy
- Routing-decision logging cardinality

## Deferred Ideas

- LLM-classifier group-reply gate (v2)
- Live farmOS API person lookup (compose with Phase 40)
- Per-recipient rate-limit buckets
- Multi-group support
- Group richer behavior (proactive nudges, multi-farmer collaboration on draft)
- Per-alert-class routing
- First-time "register me" reply for unassigned senders
