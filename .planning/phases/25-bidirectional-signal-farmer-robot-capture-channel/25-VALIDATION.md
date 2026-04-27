---
phase: 25
slug: bidirectional-signal-farmer-robot-capture-channel
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-27
---

# Phase 25 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | jest 29.x (Node — alerter) + pytest 7.x (Python — whisper-transcribe) |
| **Config file** | `src/agents/alerter/jest.config.js` (existing) + `src/agents/whisper-transcribe/pytest.ini` (Wave 0 creates) |
| **Quick run command** | `cd src/agents/alerter && npm test -- --findRelatedTests` |
| **Full suite command** | `cd src/agents/alerter && npm test && cd ../whisper-transcribe && pytest` |
| **Estimated runtime** | ~30s alerter / ~15s whisper unit / ~120s with real-Whisper smoke |

---

## Sampling Rate

- **After every task commit:** Run `npm test -- --findRelatedTests` (or `pytest <file>` for Python tasks)
- **After every plan wave:** Run full suite
- **Before `/gsd-verify-work`:** Full suite green + Wave 0 receive smoke + end-to-end Signal roundtrip
- **Max feedback latency:** 30s for unit tests; 120s for full suite

---

## Per-Task Verification Map

> Populated by gsd-planner during PLAN.md generation. Each task gets one row.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 25-01-01 | 01 | 0 | R1 | — | signal-cli pipe accepts /v1/receive HTTP poll after MODE=normal flip + primary re-reg | smoke | `curl -s http://localhost:8080/v1/receive/+59891840205 \| jq` | ❌ W0 | ⬜ pending |

---

## Wave 0 Requirements

- [ ] `src/agents/alerter/test/fixtures/signal-envelopes/` — captured real envelopes for text/audio/image fixture replay
- [ ] `src/agents/alerter/test/capture.test.js` — stubs for capture pipeline (mocked Whisper + Anthropic)
- [ ] `src/agents/alerter/test/signal-receive.test.js` — receive-loop dispatch fan-out (snooze fast-path vs capture)
- [ ] `src/agents/whisper-transcribe/tests/test_transcribe.py` — FastAPI route + tiny audio fixture (model not loaded in CI)
- [ ] `src/agents/whisper-transcribe/pytest.ini` — pytest config
- [ ] `scripts/wave0-signal-receive-smoke.sh` — verifies `/v1/receive` returns HTTP 200 + envelope shape after MODE=normal + re-registration
- [ ] Migration script for `signal_capture` table (sql or db.js extension) — runnable idempotently

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Primary re-registration via B310s-518 SMS | R1 (pre-gate execution) | Requires physical SIM access + SMS verification code from router admin UI | Per spike 001 README: SSH to elder-plops, exec into signal-cli container, `signal-cli register +59891840205`, retrieve SMS code from `http://192.168.8.1` admin → `signal-cli verify +59891840205 <code>` |
| Farmer trust restoration | R1 | One-time identity refresh after primary re-reg breaks safety number | `curl -X PUT http://localhost:8080/v1/identities/+59891840205/trust/+59892893012 -H 'Content-Type: application/json' -d '{"trust_all_known_keys": true}'` |
| Real-Whisper transcription quality | R3 | Quality is subjective; ASR output varies; compare to farmer's known utterance | Send a 30s voice note saying a known phrase via Signal; verify transcript text matches within reasonable WER |
| LLM session-tag plausibility | R4, R5 | Quality is subjective and stochastic | Send 5 representative messages (inoc, harvest, tray check, vent question, photo+caption); verify replies are ≤2 lines, session tag is plausible, latency < SPEC budget |
| Latency budgets met under live conditions | R6 (60s text / 3min audio / 60s degraded) | Wall-clock measurement requires real Signal/Whisper/Anthropic | Manual stopwatch on 3 messages of each type; record in UAT |
| Snooze fast-path 30s ack survives Whisper outage | R6 (degraded) | Requires deliberately stopping whisper-transcribe container | `docker stop mushy-whisper-transcribe-1`, send `mute` text, verify ack arrives < 30s |
| Operator visibility of capture errors (sensor_health-style indicator) | D-03 | UI presence check on Mission Control panel | Stop whisper container, send audio, verify capture-error indicator shows on the system health panel within poll interval |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (envelope fixtures, pytest config, migration runner, receive smoke)
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s for unit; < 120s for full suite
- [ ] `nyquist_compliant: true` set in frontmatter (planner sets after per-task map populated)

**Approval:** pending
