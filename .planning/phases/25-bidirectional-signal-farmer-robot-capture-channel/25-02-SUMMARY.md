---
phase: 25
plan: 02
subsystem: alerter/capture-backbone
tags: [signal, capture, timescaledb, ulid, tdd, wave-1]
one_liner: "Capture-persistence backbone: pg table + ULID filenames + orchestrator factory; capture.test.js GREEN (6/6)"
dependency_graph:
  requires: [25-01]
  provides: [capture-db, capture-history, capture-pipeline, signal-fetchAttachment]
  affects: [alerter-src, alerter-tests]
tech_stack:
  added:
    - "@anthropic-ai/sdk@0.91.1"
    - "ulid@3.0.2"
    - "node-cron@4.0.0"
  patterns:
    - "Factory + closure + named export (all new alerter modules)"
    - "Pure DB module + injected pool (mirrors timelapse/src/db.js)"
    - "Error isolation at every external boundary (D-03 enforced)"
    - "ULID-derived filenames; per-day directory; safeExt sanitizes content-type (T-25-02-02)"
    - "Parameterized SQL only — no string-concat of user input (T-25-02-01)"
key_files:
  created:
    - src/agents/alerter/src/capture-db.js
    - src/agents/alerter/src/capture-history.js
    - src/agents/alerter/src/capture.js
    - src/agents/alerter/test/capture-db.test.js
    - src/agents/alerter/test/capture-history.test.js
  modified:
    - src/agents/alerter/package.json
    - src/agents/alerter/src/config.js
    - src/agents/alerter/src/signal.js
    - src/agents/alerter/test/capture.test.js
    - src/agents/alerter/test/config.test.js
    - src/agents/alerter/test/signal.test.js
    - src/agents/alerter/test/helpers/fake-signal-server.js
decisions:
  - "Regular table (not hypertable) for signal_capture — per-farmer write volume too low for TimescaleDB hypertable (RESEARCH Open Q #1)"
  - "handle() extracts source/text/attachments from signal-cli envelope wrapper shape { envelope: { source, dataMessage: { message, attachments } } }"
  - "insertCapture called before LLM compose so row is durable even if LLM hangs"
  - "llm_reply UPDATE is best-effort (Step 7) — row already persisted from Step 3"
  - "package-lock.json is gitignored — not committed"
metrics:
  duration: "~25 min"
  completed: "2026-04-27"
  tasks_completed: 3
  tasks_total: 3
  files_created: 5
  files_modified: 7
---

# Phase 25 Plan 02: Capture Persistence Backbone Summary

## What Was Built

Wave 1 of the bidirectional Signal capture channel. Three new pure modules + extended config/signal client + GREEN tests.

**Pinned dependency versions installed:**
- `@anthropic-ai/sdk@0.91.1`
- `ulid@3.0.2`
- `node-cron@4.0.0`

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Install deps + extend config.js + signal.js | 0262f19 | package.json, config.js, signal.js, config.test.js, signal.test.js, fake-signal-server.js |
| 2 | Build capture-db.js + capture-history.js | aef3b11 | capture-db.js, capture-history.js, capture-db.test.js, capture-history.test.js |
| 3 | Build capture.js + turn capture.test.js GREEN | 78df8f7 | capture.js, capture.test.js |

## Contract Signatures (for Waves 3–4)

```javascript
// capture-db.js
initDb(pool: pg.Pool) → Promise<void>
insertCapture(pool, {
  id, captured_at, sender, message_type, raw_text,
  attachment_paths, transcript, llm_session_tag, llm_reply, degraded
}) → Promise<void>
markExpiredOlderThan(pool, ageMs: number) → Promise<{ rowCount: number }>

// capture-history.js
createCaptureHistory({ pool })
  → { selectRecentBySender(sender: string, sinceMs: number) → Promise<row[]> }

// capture.js
createCapturePipeline({ pool, signalClient, transcribeClient, llmClient,
  captureHistory, sensorSnapshot, baseDir, logger, clock })
  → { handle(envWrapper: SignalEnvelopeWrapper) → Promise<void> }
  // handle() NEVER throws; envelope shape: { envelope: { source, dataMessage: { message, attachments } } }

// signal.js (extended)
signalClient.receive({ timeoutSec, ignoreAttachments = false }) → Promise<envelope[]>
signalClient.fetchAttachment(id: string) → Promise<Buffer>
```

## Test Counts

| Test File | Tests | Status |
|-----------|-------|--------|
| capture.test.js | 6 | GREEN |
| capture-db.test.js | 4 | GREEN |
| capture-history.test.js | 2 | GREEN |
| config.test.js | 9/10 | 9 GREEN, 1 pre-existing fail (dashboardUrl default mismatch — out of scope) |
| signal.test.js | 15 | GREEN |

**Total new tests added: 17** (6 capture + 4 capture-db + 2 capture-history + 5 signal/config)

## Security Surface (Threat Model)

All STRIDE mitigations applied:

| Threat | Mitigation Applied |
|--------|-------------------|
| T-25-02-01 SQL injection | All queries use `$N` placeholders; zero `${var}` in SQL strings |
| T-25-02-02 Path traversal | `buildPath()` ignores client filename; uses ULID + `safeExt()` with `replace(/[^a-z0-9]/gi,'')` |
| T-25-02-03 Phone number in logs | `maskNumber()` from config.js used in logger calls |
| T-25-02-04 Bad attachment crashes | Per-attachment try/catch; `degraded=true` set on partial failure |

## Deviations from Plan

**1. [Rule 1 - Bug] envelope wrapper shape**
- Found during: Task 3 implementation
- Issue: Plan pseudocode showed `handle({ envelope, source, text, attachments })` as destructured params, but test fixtures pass `{ envelope: { source, dataMessage: { message, attachments } } }` — the full wrapper object
- Fix: `handle(envWrapper)` extracts `env = envWrapper.envelope || envWrapper`, then reads `env.source` and `env.dataMessage.{message,attachments}`
- No plan deviation needed — test fixtures drove the correct shape

## Known Stubs

None. All modules are fully implemented. `transcribeClient` and `llmClient` are injected fakes in tests (Wave 2 and Wave 3 implement the real clients respectively).

## Self-Check

### Files exist
- `src/agents/alerter/src/capture-db.js` — FOUND
- `src/agents/alerter/src/capture-history.js` — FOUND
- `src/agents/alerter/src/capture.js` — FOUND

### Commits exist
- 0262f19 (Task 1) — FOUND
- aef3b11 (Task 2) — FOUND
- 78df8f7 (Task 3) — FOUND

## Self-Check: PASSED
