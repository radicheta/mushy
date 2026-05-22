---
phase: 44
plan: 02
subsystem: alerter
tags: [outbound, signal, persistence, tenant-aware, schema]
status: complete
completed: 2026-05-22
requires: [44-00]
provides:
  - signal_outbound table (D-12 schema verbatim + 3 indexes + pgcrypto)
  - outboundDb.insertOutbound / selectRecentByRecipient DAO (never-throw)
  - single persistence hook in signal.js (D-14 — one hook, not 14 callsites)
  - opts-bag wrapper API (W8) — explicit contract below
affects:
  - src/agents/alerter/src/outbound-db.js (new)
  - src/agents/alerter/src/signal.js (extended)
  - src/agents/alerter/src/index.js (boot wiring)
  - src/agents/alerter/test/outbound-db.test.js
  - src/agents/alerter/test/signal.test.js
tech-stack:
  added: [pgcrypto extension on elder-plops mushy db]
  patterns: [Pattern S1 never-throw DAO, D-03 fail-open, D-14 single-hook]
key-files:
  created: [src/agents/alerter/src/outbound-db.js, src/agents/alerter/test/outbound-db.test.js]
  modified: [src/agents/alerter/src/signal.js, src/agents/alerter/src/index.js, src/agents/alerter/test/signal.test.js]
decisions:
  - "D-2: group-send recipient encoding = prefix (b) — recipient_e164 = 'group:<id-b64>'; preserves D-12 NOT NULL"
  - "D-14: single persistence hook in signal.js post-sendHistory.push; no fan-out to 14 callsites"
  - "Pitfall 3 shim: callers omitting intent get warn + intent='unknown' during Plan-02→Plan-03 window"
metrics:
  task_count: 3
  files_touched: 5
requirements: [OUTBOUND-01, TENANT-01]
---

# Phase 44 Plan 02: signal_outbound durable persistence + single send-hook Summary

Shipped the `signal_outbound` table, never-throw DAO, and single persistence
hook inside `signal.js` — every successful Signal send now writes exactly one
durable row tagged with `tenant_id`, ready for Plan-03's 14-site intent rollout
and Plan-05's `fmtHistory` merge.

## Wrapper API contract (W8 — Plan-03 references this)

```
signalClient.send(body, opts) -> Promise<{ok, timestamp, ...} | {ok:false, reason}>
  body:  string                                       (required)
  opts:  {
    bypassCap?:        boolean         // default false (existing — rate-cap bypass for heartbeats)
    to?:               string | { groupId: string }   // default = factory defaultTarget
    intent?:           string          // D-13 enum — defaults to 'unknown' w/ warn (Pitfall 3 shim)
    relatedCaptureId?: uuid | null     // default null
    relatedDraftId?:   uuid | null     // default null
    sourceModule?:     string | null   // default null (RESEARCH Open Q2: caller passes; no stack-walk)
  }
```

**Recipient encoding rule** (operator decision 2026-05-21, path b — see
`44-group-send-encoding-decision.md`):

- 1:1 send: `recipient_e164 = '+15551234567'`
- group send: `recipient_e164 = 'group:<id-b64>'` where `<id-b64>` is the
  resolved id-b64 form (same string signal-cli's `/v2/send` accepts after the
  `group.` prefix is stripped, same form the receive-loop logs already use).

Downstream consumers (Plan-04 `lastBot`, Plan-05 `fmtHistory`) query with a
single `WHERE recipient_e164 = $1` and pass `'group:<id>'` for group lookups.

## Intent enum (reserved for Plan-03's 14-site wire-up)

Plan-03 will replace `intent='unknown'` with the canonical enum at each of the
14 callsites. The shim emits a `[signal] send() missing intent` warn line so
the rollout window is observable in alerter logs.

| Callsite (Plan-03 target)           | Intent (reserved)        |
| ----------------------------------- | ------------------------ |
| state.js RH alert                   | `rh_alert`               |
| state.js sensor-health alert        | `sensor_health_alert`    |
| state.js pi-offline / chamber-dark  | `pi_offline_alert`       |
| state.js humidifier-stuck           | `humidifier_stuck_alert` |
| heartbeat.js daily summary          | `heartbeat`              |
| receive-loop snooze ack             | `snooze_ack`             |
| capture pipeline LLM reply          | `capture_reply`          |
| extraction outbound ask-back        | `extraction_askback`     |
| extraction outbound needs-review    | `extraction_review_ping` |
| confirm-loop preview                | `confirm_preview`        |
| confirm-loop edit ack               | `confirm_edit_ack`       |
| confirm-loop watchdog re-ping       | `confirm_repreview`      |
| commit watchdog success ack         | `commit_ack`             |
| commit watchdog failure alert       | `commit_failed_alert`    |

(14 sites — RESEARCH §"signal.js call-site audit". Plan-03 owns the mapping commit.)

## pgcrypto disposition (Task 2.1)

Operator confirmed "pgcrypto present" at Task 2.1 checkpoint, but the
implementation prepends `CREATE EXTENSION IF NOT EXISTS pgcrypto` to `initDb`
anyway — it's a no-op when present and gives us cheap durability against future
fresh-DB bootstraps (e.g. tenant carve-out for v2.0 Foray). The statement
requires superuser only on a first-ever run, and we know the elder-plops mushy
db already has it.

## Group-send encoding (Task 2.3a — operator decision)

**Path (b) — prefix encoding** (see `44-group-send-encoding-decision.md`).
Preserves D-12 schema verbatim including `recipient_e164 text NOT NULL`. The
downside (column name "lies" about its content for group rows) is local to two
downstream consumers — `fmtHistory` (Plan-05) and `lastBot` lookup (Plan-04) —
both of which were already going to gain the prefix convention anyway since
the receive-loop logs use `group:<prefix>…` today.

## Tasks executed

| # | Task                                                            | Commit  |
| - | --------------------------------------------------------------- | ------- |
| 2.1 | Confirm pgcrypto on elder-plops (checkpoint — operator)         | n/a     |
| 2.2 | outbound-db.js DAO — initDb + insertOutbound + selectRecent     | 9997179 |
| 2.3a | Group-send encoding decision (checkpoint — operator chose b)   | f457159 |
| 2.3 | signal.js persistence hook + index.js boot wiring (RED → GREEN) | a670827, bc83d0c |

## Deviations from Plan

**None — Rule 0.**

The plan's Task 2.3 `<action>` lists both path (a) and path (b) wire-up code
sketches and instructs the executor to "implement the chosen encoding exactly
as documented in `44-group-send-encoding-decision.md`". Operator chose path
(b) prefix, so the path (a) ALTER TABLE / DROP NOT NULL branch was not
implemented — that's plan-driven, not a deviation.

## Verification

```
cd src/agents/alerter && npm test -- signal       # 32/32 green (6 new behaviors + 26 pre-existing)
cd src/agents/alerter && npm test -- outbound-db  # green (Task 2.2 — 6+ assertions)
cd src/agents/alerter && npm test                 # 766 passed, 29 skipped, 0 failed
```

## Known Stubs

None. The `intent='unknown'` default is a documented shim (RESEARCH Open Q3 +
T-44-02-03 accepted), not a stub — rows are real, durable, and queryable; Plan-03
closes the window within one wave.

## Self-Check: PASSED

- FOUND: src/agents/alerter/src/outbound-db.js (Task 2.2)
- FOUND: src/agents/alerter/src/signal.js (extended; contains `outboundDb.insertOutbound`)
- FOUND: src/agents/alerter/src/index.js (contains `outboundDb.initDb`)
- FOUND commit 9997179 (Task 2.2 — outbound-db DAO)
- FOUND commit f457159 (Task 2.3a decision doc)
- FOUND commit a670827 (Task 2.3 RED)
- FOUND commit bc83d0c (Task 2.3 GREEN — wrapper + boot wiring)
