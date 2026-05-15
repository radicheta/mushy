
## Phase 37 Plan 03 — deferred items

### ~~test/integration.test.js heartbeat_fires_and_bypasses_cap failure~~ — RESOLVED
- Originally introduced by commit 3bc11cb (heartbeat deferral on empty bridge summary).
- **Resolved post-Plan-03:** test now dispatches `heartbeat_tick` directly with a populated summary, matching the test's actual intent (validate cap=0 doesn't suppress heartbeat sends). Suite back to 268/269 with only the dashboardUrl drift remaining.

### ~~test/config.test.js Test A -- dashboardUrl drift~~ -- RESOLVED 2026-05-15 (commit 3c7c723)
- ~~Status: pre-existing (carried from Plan 37-01)~~
- **Resolved:** `config.js:93` default updated to `http://elder-plops-ts:8081/farmer` (tailscale hostname + bridge port + /farmer path). 626/626 GREEN.

### ~~Mention OBJ-char (￼) breaks command-keyword dispatch~~ -- RESOLVED 2026-05-15 (commit 3c7c723)
- ~~Status: new, surfaced live 2026-05-11 during Phase 37 Attestation D~~
- **Resolved:** detector regex in `collectGroupTriggers` (receive-loop.js:19) extended to tolerate `￼` (with optional whitespace) before the @mention. commandText strip extended to remove leading `￼` form. New fixture `test/fixtures/envelopes/group-mention-ios-obj.json` + two new tests (detector + end-to-end snooze dispatch) green. The 2026-05-11 false-routing-to-LLM class is closed.

### ~~LLM reply contains em-dashes~~ -- RESOLVED 2026-05-15 (commit 3c7c723)
- ~~Status: new, surfaced live 2026-05-11 during Phase 37 Attestation D~~
- ~~A second live em-dash leak observed 2026-05-15 during Plan 36-04 T+24h round-trip (recurrent, not one-time)~~
- **Resolved:** `llm-client.js` SYSTEM_PROMPT now explicitly forbids em-dashes (U+2014) and LLM-tell vocabulary; defense-in-depth `sanitizeReply()` strips em-dashes from the SDK response before return (mirrors `src/extraction/preview-builder.js` pattern). Two new tests: prompt-pin assertion + output-sanitize assertion. Reference: `feedback_no_em_dashes_in_artifacts.md`.

### NEW 2026-05-15: LLM has no memory of its own outbound messages
- **Status:** new, surfaced live 2026-05-15 during Plan 36-04 T+24h reply.
- **Symptom:** Bot sent T+24h kickoff at 23:15:34Z ("reply ok to confirm Signal trust is still good"). Santi's "Ok" capture at 23:28:20Z routed to LLM (no pending draft to absorb). LLM replied "Is this message confirming a specific session ?? inoculation, harvest, or chamber check ?? so I can log it correctly?" -- did not realize it had asked the question 12m46s earlier.
- **Why:** `fmtHistory()` in `llm-client.js` feeds only inbound `signal_capture` rows. The bot's own outbound `signal.send()` calls are not persisted anywhere accessible to the next composition.
- **Fix candidates:**
  - **(a) Ring buffer** of last N bot-sent messages per recipient, scoped per loop instance (lost on restart; cheap).
  - **(b) Persist outbound** to a new `signal_outbound` table (durable across restarts; minor schema change).
  - **(c) Hybrid**: ring buffer for hot path + DB write for audit/replay.
- **Filing:** NOT in this PR. Don Santiago wants to discuss scope. Recommend (c) but defer to discussion.
- **Reference:** `.planning/notes/2026-05-15-rambo-th-window-unscripted-run.md` finding 1b; mirrors the "post-confirm silence" UX class seen in Phase 40 commit_failed.
