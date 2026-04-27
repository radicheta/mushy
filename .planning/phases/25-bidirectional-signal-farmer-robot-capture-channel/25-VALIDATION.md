---
phase: 25
slug: bidirectional-signal-farmer-robot-capture-channel
status: planned
nyquist_compliant: true
wave_0_complete: false
created: 2026-04-27
last_updated: 2026-04-27
---

# Phase 25 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution. Populated after PLAN.md generation.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | jest 29.x (Node — alerter) + pytest 8.x (Python — whisper-transcribe) |
| **Config file** | `src/agents/alerter/jest.config.js` (existing) + `src/whisper-transcribe/pytest.ini` (Wave 2) |
| **Quick run command (Node)** | `cd src/agents/alerter && npm test -- --testPathPattern=<module>` |
| **Full suite (Node)** | `cd src/agents/alerter && npm test` |
| **Full suite (Python, no GPU)** | `cd src/whisper-transcribe && pytest -m 'not gpu'` |
| **GPU smoke (opt-in)** | `WHISPER_URL=http://localhost:8090 pytest -m gpu src/whisper-transcribe/test/test_smoke.py` |
| **Estimated runtime** | ~30s alerter / ~5s whisper unit / ~30s GPU smoke |

---

## Sampling Rate

- **After every task commit:** Run `npm test -- --testPathPattern=<module>` (or `pytest <file>` for Python)
- **After every plan wave:** Full Node + Python (non-GPU) suite
- **Before `/gsd-verify-work`:** Above + GPU smoke + farmer UAT (Plan 25-05 Task 3)
- **Max feedback latency:** 30s for unit tests; 120s for full suite + smoke

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 25-01-01 | 01 | 0 | R1 | T-25-01-01..06 | MODE=normal flip + primary re-reg + farmer trust + receive smoke | live smoke (operator) | `bash scripts/wave0-signal-receive-smoke.sh` | ❌ → ✅ W0 T2 | ⬜ pending |
| 25-01-02 | 01 | 0 | R1,R2,R3,R5,R6 | T-25-02-02 | Wave-0 fixtures + smoke script + fake-whisper helper | static + syntax | `jq -e '.[0].envelope.source' fixtures/...` + `bash -n scripts/wave0-...sh` | ❌ → ✅ W0 T2 | ⬜ pending |
| 25-01-03 | 01 | 0 | R2,R3,R5,R6 | — | RED skeleton tests for capture/transcribe-client/llm-client | jest list-tests | `cd src/agents/alerter && npx jest --listTests test/{capture,transcribe-client,llm-client}.test.js` | ❌ → ✅ W0 T3 | ⬜ pending |
| 25-02-01 | 02 | 1 | R2,R7 | T-25-02-06 | deps installed + config fail-fast + signal.js fetchAttachment | unit | `npm test -- --testPathPattern="config.test\|signal.test"` | ❌ → ✅ W1 T1 | ⬜ pending |
| 25-02-02 | 02 | 1 | R2 | T-25-02-01 | capture-db.js + capture-history.js parameterized SQL + indexes | unit (mock pool) | `npm test -- --testPathPattern="capture-db.test\|capture-history.test"` | ❌ → ✅ W1 T2 | ⬜ pending |
| 25-02-03 | 02 | 1 | R2,R6 | T-25-02-02,03,04,07,08 | capture.js orchestrator + ULID paths + degraded branches | unit (mocks + tmp dir) | `npm test -- --testPathPattern=capture.test` | ❌ → ✅ W1 T3 | ⬜ pending |
| 25-03-01 | 03 | 2 | R3 | T-25-03-01,02,06 | whisper-transcribe FastAPI + V12 path safety + lazy load | unit (TestClient) | `cd src/whisper-transcribe && pytest -m 'not gpu'` | ❌ → ✅ W2 T1 | ⬜ pending |
| 25-03-02 | 03 | 2 | R3 | T-25-03-03 | transcribe-client.js timeout + error-isolated returns | unit (fake server) | `npm test -- --testPathPattern=transcribe-client.test` | ❌ → ✅ W2 T2 | ⬜ pending |
| 25-03-03 | 03 | 2 | R3 | T-25-03-02,05 | compose wiring + GPU smoke live | live smoke | `curl -fsS http://localhost:8090/health` + `pytest -m gpu` | ❌ → ✅ W2 T3 | ⬜ pending |
| 25-04-01 | 04 | 3 | R5,R6 | T-25-04-06 | sensor-snapshot fetcher with timeout + null-on-failure | unit | `npm test -- --testPathPattern=sensor-snapshot.test` | ❌ → ✅ W3 T1 | ⬜ pending |
| 25-04-02 | 04 | 3 | R5 | T-25-04-01,02,07 | llm-client.js prompt shape + degraded path + key not logged | unit (mocked SDK) | `npm test -- --testPathPattern=llm-client.test` | ❌ → ✅ W3 T2 | ⬜ pending |
| 25-05-01 | 05 | 4 | R4,R6,R7 | T-25-05-01,02 | snooze grammar + receive-loop fast-path + fan-out | unit | `npm test -- --testPathPattern="snooze.test\|receive-loop.test"` | ❌ → ✅ W4 T1 | ⬜ pending |
| 25-05-02 | 05 | 4 | D-03,D-06 | T-25-05-03,05 | retention cron + state captureHealth slot | unit (mocked cron) | `npm test -- --testPathPattern="capture-retention.test\|state.test"` | ❌ → ✅ W4 T2 | ⬜ pending |
| 25-05-03 | 05 | 4 | R3,R4,R5,R6,R7 | T-25-05-04 | live deploy + farmer UAT 1–7 | live + operator | UAT 1–7 from Plan 25-05 Task 3 | ❌ → ✅ W4 T3 | ⬜ pending |

---

## Wave 0 Requirements (gaps closed by Plan 25-01)

- [x] `src/agents/alerter/test/fixtures/envelopes/text.json`
- [x] `src/agents/alerter/test/fixtures/envelopes/audio.json`
- [x] `src/agents/alerter/test/fixtures/envelopes/photo-batch.json`
- [x] `src/agents/alerter/test/fixtures/envelopes/snooze.json`
- [x] `src/agents/alerter/test/capture.test.js` (RED skeleton — GREEN in W1)
- [x] `src/agents/alerter/test/transcribe-client.test.js` (RED skeleton — GREEN in W2)
- [x] `src/agents/alerter/test/llm-client.test.js` (RED skeleton — GREEN in W3)
- [x] `src/agents/alerter/test/helpers/fake-whisper-server.js`
- [x] `scripts/wave0-signal-receive-smoke.sh`
- [x] `src/whisper-transcribe/Dockerfile` (W2 T1)
- [x] `src/whisper-transcribe/main.py` (W2 T1)
- [x] `src/whisper-transcribe/requirements.txt` (W2 T1)
- [x] `src/whisper-transcribe/test/test_smoke.py` (W2 T1)
- [x] `src/whisper-transcribe/test/test_unit.py` (W2 T1)
- [x] `src/whisper-transcribe/test/fixtures/sample-30s.wav` (W2 T1)
- [x] `src/whisper-transcribe/pytest.ini` (W2 T1)

Note: Wave 0 in Plan 25-01 only creates the alerter-side fixtures + RED skeletons. The whisper-transcribe files live in Wave 2 (Plan 25-03) since they share the container build dependency. This is a deliberate split — keeps Wave 0 focused on the signal-cli unblock + Node-side test scaffolding.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Primary re-registration via B310s-518 SMS | R1 | Requires physical SIM access + SMS code from router admin UI | Plan 25-01 Task 1 STEP D — operator reads code from `http://192.168.8.1` |
| Farmer trust restoration | R1 | One-time identity refresh after primary re-reg | `curl PUT /v1/identities/.../trust/...` with `trust_all_known_keys: true` |
| Real-Whisper transcription quality | R3 | ASR quality is subjective | Plan 25-05 UAT-4 — farmer-known phrase, compare WER |
| LLM session-tag plausibility | R5 | Quality is subjective + stochastic | Plan 25-05 UAT-3, UAT-4 — verify replies ≤2 lines, plausible session tag |
| Latency budgets met under live conditions | R6 (60s/3min) | Wall-clock measurement | Plan 25-05 UAT-1..5 stopwatch |
| Snooze fast-path 30s ack survives Whisper outage | R6 | Requires deliberately stopping whisper-transcribe | UAT-2 |
| Operator visibility of capture errors | D-03 | UI presence on Phase-16 system health panel | UAT-7 |
| LLM-degraded reply when API key invalid | R6 | Requires temporary .env manipulation | UAT-5 |
| Whitelist drops silently | R7 | Requires non-whitelisted sender access | UAT-6 |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies populated
- [x] Sampling continuity: no 3 consecutive tasks without automated verify (every task has either unit or live smoke)
- [x] Wave 0 covers all MISSING references (envelope fixtures, fake whisper helper, smoke script, RED skeletons)
- [x] No watch-mode flags
- [x] Feedback latency < 30s for unit; < 120s for full suite + smoke
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** ready (planner)
