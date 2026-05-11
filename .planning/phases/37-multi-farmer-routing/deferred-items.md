
## Phase 37 Plan 03 — deferred items

### ~~test/integration.test.js heartbeat_fires_and_bypasses_cap failure~~ — RESOLVED
- Originally introduced by commit 3bc11cb (heartbeat deferral on empty bridge summary).
- **Resolved post-Plan-03:** test now dispatches `heartbeat_tick` directly with a populated summary, matching the test's actual intent (validate cap=0 doesn't suppress heartbeat sends). Suite back to 268/269 with only the dashboardUrl drift remaining.

### test/config.test.js Test A — dashboardUrl drift
- **Status:** pre-existing (carried from Plan 37-01)
- **Root cause:** `config.js:87` default `http://100.96.10.66:8080/` no longer matches the test assertion `http://elder-plops-ts:8081/farmer`.
- **Fix:** One-line update — either fix the default or update the test. Bundle with next alerter PR.

### Mention OBJ-char (￼) breaks command-keyword dispatch (Attestation D live finding)
- **Status:** new, surfaced live 2026-05-11 during Phase 37 Attestation D.
- **Symptom:** f1 sent `@bot mute` to the Mush Farm group. Capture row stored text as `￼ mute` (U+FFFC + space + "mute"). The Plan 03 `@<token><space>` prefix-strip didn't strip the OBJ char, so the command-keyword regex didn't match `mute`, and the message routed to the LLM session instead of the snooze/mute handler.
- **Fix:** Extend the strip regex in `src/agents/alerter/src/receive-loop.js` (or wherever Plan 03 added it) to also strip `￼\s*` from the head of the message before passing to the snooze/experiment parsers. Add a fixture-based test case (the `group-mention-and-command.json` fixture has been carrying the OBJ-char form since 37-01 — currently asserted to dispatch the mute handler, but apparently doesn't).
- **Note:** D-09 dedupe still PASSED (one reply, one capture row) — only the dispatch routing missed.

### LLM reply contains em-dashes (memory `feedback_no_em_dashes_in_artifacts.md` violation)
- **Status:** new, surfaced live 2026-05-11 during Phase 37 Attestation D.
- **Symptom:** LLM session reply read: "Got it — no active farm session to tag right now. Are you trying to mute notifications from me specifically, or silence chamber alerts?" The em-dash is exactly the LLM tell the user called out earlier in the session.
- **Fix:** Update the LLM system prompt (likely in `src/agents/alerter/src/capture-pipeline.js` or wherever the Anthropic call is constructed) to instruct: "Do not use em-dashes. Avoid LLM-tell vocabulary (delve, comprehensive, leverage). Plain prose only — your replies appear in a farmer-facing Signal channel."
- **Reference:** `feedback_no_em_dashes_in_artifacts.md` documents the operator preference.
