---
phase: 57-signal-i-o
plan: "04"
subsystem: signal_io
tags: [live-fire, sc1, sc3, quote-bubble, shape-drift, sig-01, sig-04]
dependency_graph:
  requires: ["57-02", "57-03"]
  provides: [live_fire_57.py, 57-LIVE-FIRE.md]
  affects: ["58-*"]
tech_stack:
  added: []
  patterns:
    - self-send bot->bot live-fire harness (no /v1/receive poller; A3-safe)
    - LIVE_FIRE_TARGET opt-in override for SC#3 render-visibility
deviations:
  - "[57-04] SHAPE-DRIFT FIX (blocking, found live): SignalClient sent a nested `quote:{timestamp,author,message}` object; live signal-cli-rest-api 0.200-dev /v2/send takes FLAT `quote_timestamp`/`quote_author`/`quote_message` (confirmed via /swagger/doc.json api.SendMessageV2). Nested object silently dropped -> 201, no bubble. Fixed client.py to emit flat fields; updated test_signal_client.py outbound assertions. This is RESEARCH A2 materializing (spike was 0.14.2; API shape changed by 0.200)."
  - "[57-04] SC#3 render-visibility: self-send lands in the bot account Note-to-Self (operator has no client there). Added LIVE_FIRE_TARGET env override to live_fire_57.py so the outbound target can be re-pointed to a phone the operator can see (sender + quote.author stay the bot). Unset => original bot->bot self-send."
key_files:
  created: []
  modified:
    - src/farm-agent/farm_agent/signal_io/client.py
    - src/farm-agent/scripts/live_fire_57.py
    - src/farm-agent/tests/test_signal_client.py
    - .planning/phases/57-signal-i-o/57-LIVE-FIRE.md
metrics:
  completed_date: "2026-06-21"
  tasks_completed: 2
  files_modified: 4
---

# Phase 57 Plan 04: Live-Fire SC#1 + SC#3 Summary

**One-liner:** Live-fire against the real `signal-cli-rest-api:0.200-dev` container proved SC#1 (round-trip `signal_msg_ts` persisted as non-null bigint) and SC#3 (native quote bubble renders) — and caught a real outbound quote-payload shape-drift bug that the mocked-httpx unit tests could not.

## What Was Verified

**SC#1 — PASS (automated).** `live_fire_57.py` self-sent two messages bot->bot
through the live container (`/v2/send` -> 201 x2), then `SELECT`ed `signal_outbound`:
both rows showed `signal_msg_ts` non-null with `pg_typeof = bigint`
(`1782054669365`, `1782054675982`). Harness printed `SC#1 PASS`.

**SC#3 — PASS (manual, after fix).** First run: message arrived but NO native quote
bubble (container returned 201 but ignored the unrecognized `quote` field). Root
cause confirmed against the live container's own swagger (`/swagger/doc.json`,
`api.SendMessageV2`): `/v2/send` exposes FLAT quote fields
(`quote_timestamp`, `quote_author`, `quote_message`, `quote_mentions`) and has
no nested `quote` object. After fixing `SignalClient` to emit flat fields and
re-firing with `LIVE_FIRE_TARGET` set to the operator's phone, message 2 rendered
as a native quote bubble of message 1. Operator confirmed visually; screenshot
captured (to be attached as `57-04-sc3-quote.jpg`).

## Deviation: Outbound Quote Shape-Drift (blocking, fixed)

This is exactly the live-fire-as-ship-gate value (`[[feedback_unit_tests_dont_catch_wiring]]`).
RESEARCH A2 had flagged the 0.14.2 -> 0.200-dev version bump as the SC#3 risk; the
gate caught it. The ported `SignalClient` faithfully copied the Node original's
nested `payload.quote = {...}` shape — which renders only on the older 0.14.2 API.
Fix: flat `quote_timestamp`/`quote_author`/`quote_message`. 22 signal-client +
quote tests green.

## Carry-Forward / New Finding

- **Node prod alerter likely has the SAME bug.** The live Node `alerter` shares this
  `0.200-dev` container and builds the same nested `quote` object
  (`src/agents/alerter/src/signal.js:118-131`). Phase-50 native quote-threading is
  therefore probably silently degraded in prod (acks send as plain messages, no
  bubble) since the container was upgraded to 0.200. Out of scope for the Python
  port; logged as a backlog item for the Node side.

- Screenshot `57-04-sc3-quote.jpg` to be dropped into the phase dir from the
  operator's phone (evidence only; not gating).

- Live-fire left 4 `signal_outbound` rows tagged `intent='live_fire_57'` (2 self-send
  + 2 render-mode). Cleanable: `DELETE FROM signal_outbound WHERE intent='live_fire_57';`
</content>
</invoke>
