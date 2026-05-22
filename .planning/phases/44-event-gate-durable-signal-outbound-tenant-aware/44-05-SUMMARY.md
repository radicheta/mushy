---
phase: 44-event-gate-durable-signal-outbound-tenant-aware
plan: 05
subsystem: alerter
tags: [outbound, fmtHistory, llm-prompt, capture-history, D-17, D-18, D-19]
requires: [44-02]
provides:
  - selectRecentOutboundByRecipient (capture-history.js)
  - fmtHistory(history, outboundHistory) merged-stream rendering
  - buildUserBlock lastBotOutbound prompt field
  - compose() signature: outboundHistory + lastBotOutbound (call-site wired by Plan-04)
affects:
  - src/agents/alerter/src/capture-history.js
  - src/agents/alerter/src/llm-client.js
tech-stack:
  added: []
  patterns:
    - "Mirror selectRecentBySender shape verbatim for outbound sibling query"
    - "Tag-and-merge-sort pattern for two-stream timeline rendering"
key-files:
  created: []
  modified:
    - src/agents/alerter/src/capture-history.js
    - src/agents/alerter/src/llm-client.js
    - src/agents/alerter/test/capture-history.test.js
    - src/agents/alerter/test/llm-client.test.js
    - src/agents/alerter/test/llm-client.outbound-merge.test.js
decisions:
  - "D-17 closed: fmtHistory no longer reads signal_capture.llm_reply (column kept for audit, invisible to prompt)"
  - "D-18 closed: per-stream truncation 200 inbound / 400 outbound"
  - "D-19 closed: lastBotOutbound rendered before history as distinct '## Last thing you said to the farmer' block"
  - "B3 Option A respected: zero capture.js modifications — Plan-04 owns the convo branch wiring via depends_on: [44-05]"
metrics:
  duration_min: ~12
  completed: 2026-05-22
  tasks_completed: 2
  commits: 4
  tests_added: 11
  tests_total_alerter: 759 passed / 29 skipped (regression-free)
---

# Phase 44 Plan 05: fmtHistory outbound merge + selectRecentOutboundByRecipient + lastBotOutbound Summary

JWT-of-the-farmer-prompt: outbound rows now flow back into the conversational LLM prompt via a sibling capture-history query + merged-stream fmtHistory, closing finding 1b proper and superseding the v1.7.x `llm_reply` band-aid.

## What shipped

### 1. `selectRecentOutboundByRecipient(recipient, sinceMs)` — capture-history.js
- Mirrors `selectRecentBySender` shape verbatim per PATTERNS.md §capture-history.js.
- SELECT projects only `sent_at, body, intent` — the three fields fmtHistory consumes.
- Filters by `recipient_e164 = $1 AND sent_at > $2 ORDER BY sent_at ASC`.
- Commit `64d3754` (GREEN) following `a3fb500` (RED, 4 failing tests).

### 2. `fmtHistory(history, outboundHistory = [])` — llm-client.js
- Tag-and-merge pattern: each row gets `{ts, body, type, cap}` then sorted by `new Date(ts)` ASC.
- Inbound cap stays 200 chars (Phase 25 invariant); outbound cap is 400 chars (bot replies are longer — D-18).
- Outbound rows render with `bot:<intent>` type prefix so the LLM can distinguish self vs farmer.
- `slice(-MAX_HISTORY_ROWS)` keeps newest 20 across the merged stream.
- D-17 supersession: rows carrying `llm_reply` are processed via `transcript || raw_text || ''` — the `llm_reply` field is never referenced. Verified via grep (0 hits on uncommented `llm_reply` in llm-client.js).

### 3. `buildUserBlock` — llm-client.js
- New signature: `{history, outboundHistory = [], lastBotOutbound = null, sensorSnapshot, currentMessage}`.
- Renders `## Last thing you said to the farmer` block (with `(none)` fallback) BEFORE the history block per D-19.
- Renames history header to `## Recent history (last 24h, oldest first, merged streams)` to reflect the new two-stream merge.
- Defaults keep back-compat: pre-Phase-44 callers passing only `{history, sensorSnapshot, currentMessage}` continue to work without modification — verified by `(back-compat)` test in `llm-client.test.js`.

### 4. `compose()` — llm-client.js
- Signature extended to accept `outboundHistory` and `lastBotOutbound`, threaded straight through to `buildUserBlock`.
- Defaults preserve back-compat. The actual call-site wiring (fetching outbound rows in the convo branch of capture.js and passing them in) is **deferred to Plan-04 Task 4.3** per B3 Option A — this plan ships only the helpers.

## Test coverage added

| File | Tests added | Cases |
|------|-------------|-------|
| `test/capture-history.test.js` | 4 | factory exposure, SELECT shape, row projection, return shape |
| `test/llm-client.outbound-merge.test.js` | 7 (replacing 4 skip-stubs) | empty case, merge ordering, per-stream truncation (200/400), `bot:<intent>` tag, slice tail at MAX_HISTORY_ROWS, no llm_reply leak (D-17), lastBotOutbound section render + null |
| `test/llm-client.test.js` | 3 | lastBotOutbound section present, `(none)` when null, back-compat without new args |

Full alerter suite remains green: **759 passed, 29 skipped (pre-existing), 0 failures** in 8.3s.

## D-17 transition note (band-aid supersession)

The v1.7.x band-aid wrote `signal_capture.llm_reply` at `capture.js:206` and `fmtHistory` read it back. Per D-17:
- The `capture.js:206` UPDATE stays (Plan-04's territory; not touched here) — `llm_reply` column remains populated as audit trail.
- `fmtHistory` STOPS reading it. The LLM now sees bot replies via `signal_outbound` rows (intent='convo_reply', etc.) instead.
- v2.0 may drop the column once we've validated this transition in prod.

The regression test `D-17: rows carrying llm_reply field do NOT leak into output` is the explicit guardrail.

## What's NOT in this plan (Plan-04 territory)

Per B3 Option A (round-2 revision), Task 5.3 was **removed** from this plan. The capture.js convo branch wiring — calling `selectRecentOutboundByRecipient` + threading `outboundHistory` + `lastBotOutbound` into `compose()` — is owned solely by Plan-04 Task 4.3, which depends on this plan. This eliminates same-file edit overlap between Plan-04 (event-gate insertion) and Plan-05 (history wiring).

## Deviations from Plan

None. The two tasks executed exactly as specified. The signature defaults on `compose()` (`outboundHistory = []`, `lastBotOutbound = null`) and `buildUserBlock` were added beyond the strict task text to preserve back-compat with the existing `test/llm-client.test.js` (prompt shape) test, which calls `compose` without the new fields. This is in-scope per Rule 2 (correctness — would have broken the regression suite otherwise).

## Commits

| Hash | Type | Description |
|------|------|-------------|
| `a3fb500` | test | failing tests for selectRecentOutboundByRecipient (RED) |
| `64d3754` | feat | selectRecentOutboundByRecipient implementation (GREEN) |
| `6da9c39` | test | failing tests for fmtHistory merge + lastBotOutbound (RED) |
| `b718dbd` | feat | fmtHistory merge + buildUserBlock lastBotOutbound + compose threading (GREEN) |

## Known Stubs

None. Helpers ship complete; call-site wiring is intentionally deferred to Plan-04 per documented B3 scope split (not a stub — a planned hand-off).

## Self-Check: PASSED

- `src/agents/alerter/src/capture-history.js` — FOUND, contains `selectRecentOutboundByRecipient` + `FROM signal_outbound`
- `src/agents/alerter/src/llm-client.js` — FOUND, contains `outboundHistory` + `lastBotOutbound`, 0 uncommented `llm_reply` references
- `test/llm-client.outbound-merge.test.js` — FOUND, 7 active tests (no skips)
- Commits `a3fb500`, `64d3754`, `6da9c39`, `b718dbd` — all present in `git log`
- Full alerter suite: 759 passed / 29 skipped (pre-existing) / 0 failed
