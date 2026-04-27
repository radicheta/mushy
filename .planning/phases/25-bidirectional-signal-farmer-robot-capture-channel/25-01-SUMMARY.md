---
phase: 25-bidirectional-signal-farmer-robot-capture-channel
plan: 01
subsystem: infra
tags: [signal-cli, signal, docker-compose, jest, tdd, whisper, fixtures]

# Dependency graph
requires:
  - phase: spike-001-huawei-router-sms-roundtrip
    provides: "SMS roundtrip proof on B310s-518; confirmed Shiitake1 password (no !)"
provides:
  - "signal-cli running in MODE=normal with /v1/receive returning HTTP 200"
  - "+59891840205 registered as PRIMARY (device_id=1) on signal-cli"
  - "Farmer identity +59892893012 trusted via trust_all_known_keys"
  - "4 envelope fixtures (text, audio, photo-batch, snooze) in signal-cli REST shape"
  - "fake-whisper-server.js test harness mirroring fake-signal-server factory shape"
  - "wave0-signal-receive-smoke.sh: validates receive pipe health"
  - "3 RED skeleton test files (capture, transcribe-client, llm-client) with skip-guards"
affects:
  - 25-02 (capture persistence — consumes fixtures + receive pipe)
  - 25-03 (whisper transcription — consumes fake-whisper-server harness)
  - 25-04 (llm-client compose — consumes llm-client.test.js skeleton)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "skip-guard idiom: try { require.resolve(...) } catch { describeFn = describe.skip } — lets RED test files parse and list without failing when subjects don't exist"
    - "jest.doMock (not jest.mock) inside try block — avoids hoisting failure when SDK not installed"
    - "fake-server factory: start({port=0}) → Promise<{url, requests[], statusOverride, delayMs, close()}>"

key-files:
  created:
    - src/agents/alerter/test/fixtures/envelopes/text.json
    - src/agents/alerter/test/fixtures/envelopes/audio.json
    - src/agents/alerter/test/fixtures/envelopes/photo-batch.json
    - src/agents/alerter/test/fixtures/envelopes/snooze.json
    - src/agents/alerter/test/helpers/fake-whisper-server.js
    - scripts/wave0-signal-receive-smoke.sh
    - src/agents/alerter/test/capture.test.js
    - src/agents/alerter/test/transcribe-client.test.js
    - src/agents/alerter/test/llm-client.test.js
  modified:
    - docker-compose.override.yml (Task 1 — committed c21d125)

key-decisions:
  - "Use jest.doMock (not hoisted jest.mock) inside try block so @anthropic-ai/sdk absence doesn't crash suite"
  - "Smoke script runs from host via SIGNAL_API_URL=http://172.22.0.2:8080 (signal-cli not on published host port)"
  - "Round-trip farmer envelope check deferred to one-shot ping at Wave 1 end (machine-verifiable truths sufficient for Wave 0)"

patterns-established:
  - "skip-guard idiom: wrap require of missing subjects in try/catch; set describeFn = describe.skip on catch"
  - "fake-whisper-server mirrors fake-signal-server factory shape for test symmetry across waves"

requirements-completed: [R1]

# Metrics
duration: 45min
completed: 2026-04-27
---

# Phase 25 Plan 01: Wave 0 — Receive Pipe Unblocked + Skeleton Tests Summary

**signal-cli MODE flipped to normal, /v1/receive returning HTTP 200 for PRIMARY +59891840205, 4 envelope fixtures + fake-whisper-server harness + 3 RED skeleton tests committed**

## Performance

- **Duration:** ~45 min
- **Started:** 2026-04-27T00:00:00Z
- **Completed:** 2026-04-27
- **Tasks:** 3 (Task 1 completed by orchestrator; Tasks 2–3 by this agent)
- **Files modified/created:** 10

## Accomplishments

- Task 1 (orchestrator): MODE=json-rpc → MODE=normal in docker-compose.override.yml; signal-cli container recreated; /v1/receive returns 200; farmer trust restored; outbound /v2/send regression passed
- Task 2: 4 signal-cli-shaped envelope fixtures + fake-whisper-server.js harness + receive smoke script
- Task 3: 3 RED skeleton test files with skip-guards and requirement IDs; no new red failures in existing suite

## Task Commits

1. **Task 1: Flip MODE=normal + re-register + trust farmer + receive smoke** — `c21d125` (chore) — committed by orchestrator
2. **Task 2: Fixtures + fake-whisper-server + smoke script** — `cb7a739` (test)
3. **Task 3: RED skeleton tests** — `9c93c8d` (test)

**Plan metadata:** committed with SUMMARY (docs)

## Task 1 Evidence (verbatim from orchestrator)

**MODE flip:** committed at `c21d125` (`chore(25-01): flip signal-cli MODE=json-rpc → MODE=normal`). docker-compose.override.yml now has `MODE=normal` on the `signal-cli` service.

**Container recreated** with the new env: `docker compose up -d --force-recreate signal-cli` succeeded; `docker compose logs --tail 30 signal-cli` shows `+ [ normal = json-rpc ]` (the conditional fell through correctly) and `level=info msg="Started Signal Messenger REST API"`.

**Primary registration already in place** from spike 001 (2026-04-27): `curl http://172.22.0.2:8080/v1/devices/+59891840205` → `[{"id":1,...},{"id":2,"name":"mushy-alerter",...}]` — +59891840205 is device_id=1 (PRIMARY); mushy-alerter is the linked secondary at id=2. The SMS re-registration step was NOT needed — the spike already accomplished it.

**Receive smoke:** `curl -sS -o /tmp/recv.json -w "%{http_code}\n" 'http://172.22.0.2:8080/v1/receive/+59891840205?timeout=1'` → HTTP 200, body `[]` (empty envelope queue — expected). The pre-flip 400 error is gone.

**Farmer trust restored:** `curl -X PUT 'http://172.22.0.2:8080/v1/identities/+59891840205/trust/+59892893012' -d '{"trust_all_known_keys": true}'` → HTTP 204 (success).

**Outbound regression PASS:** `curl -X POST 'http://172.22.0.2:8080/v2/send' -d '{"message":"phase 25 wave 0 smoke — please ignore","number":"+59891840205","recipients":["+59892893012"]}'` → HTTP 201, `{"timestamp":"1777331014092"}` — Signal accepted the message for delivery.

**nvidia-container-toolkit:** PRESENT on elder-plops (`docker info` shows `nvidia` runtime). Wave 2 GPU compose will work without extra setup.

**Huawei admin password:** Confirmed `Shiitake1` (no `!`); the README body had a typo (`Shiitake1!`) — memory updated.

**signal-cli network note:** REST API is on the internal compose network only (NOT published to host:8080 — that port is OpenMCT). From the host, use `SIGNAL_API_URL=http://172.22.0.2:8080` with the smoke script.

## Files Created/Modified

- `docker-compose.override.yml` — MODE=normal on signal-cli service (Task 1)
- `src/agents/alerter/test/fixtures/envelopes/text.json` — text-only envelope fixture
- `src/agents/alerter/test/fixtures/envelopes/audio.json` — audio/aac voiceNote attachment fixture
- `src/agents/alerter/test/fixtures/envelopes/photo-batch.json` — 3-image batch fixture
- `src/agents/alerter/test/fixtures/envelopes/snooze.json` — 4 snooze keyword envelopes (mute/snooze/quiet/snooze rh 4h)
- `src/agents/alerter/test/helpers/fake-whisper-server.js` — POST /transcribe + GET /health fake server, mirrors fake-signal-server factory shape
- `scripts/wave0-signal-receive-smoke.sh` — validates device_id=1, /v1/receive=200, /v2/send timestamp
- `src/agents/alerter/test/capture.test.js` — 6 RED tests (R2 x4, R6 x2)
- `src/agents/alerter/test/transcribe-client.test.js` — 4 RED tests (R3 x4)
- `src/agents/alerter/test/llm-client.test.js` — 3 RED tests (R5 x3)

## Decisions Made

- `jest.doMock` (not the hoisted `jest.mock`) used inside the try block for llm-client.test.js — `jest.mock` at top level fails at parse time when `@anthropic-ai/sdk` is absent; `jest.doMock` is non-hoisted and only runs if `require.resolve` succeeds first.
- Smoke script defaults to `http://localhost:8080` but must be run with `SIGNAL_API_URL=http://172.22.0.2:8080` from the host (signal-cli not on a published host port in the override).
- Round-trip farmer-phone receive check (acceptance criterion 6) deferred to a one-shot ping at the end of Wave 1 — machine-verifiable HTTP truths are sufficient for Wave 0 completion.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] jest.mock hoisting causes suite-fail when @anthropic-ai/sdk is absent**
- **Found during:** Task 3 (llm-client.test.js)
- **Issue:** `jest.mock('@anthropic-ai/sdk', ...)` is hoisted before any code runs; when the SDK is not installed, the entire test file fails to load instead of being skipped
- **Fix:** Replaced `jest.mock` with `require.resolve` check + `jest.doMock` inside the try block; the skip-guard catches the resolution failure and uses `describe.skip`
- **Files modified:** `src/agents/alerter/test/llm-client.test.js`
- **Verification:** `npm test` shows llm-client.test.js as skipped (not FAIL); `npx jest --listTests` lists the file without parse errors
- **Committed in:** `9c93c8d`

---

**Total deviations:** 1 auto-fixed (Rule 1 bug)
**Impact on plan:** Fix required for test file to be parseable; no scope creep.

## Issues Encountered

- Pre-existing `config.test.js` failure: `dashboardUrl` mismatch between test expectation (`http://elder-plops-ts:8081/farmer`) and current env value (`http://100.96.10.66:8080/`). Not caused by this plan. Out of scope.

## Open / Deferred Items

- **Round-trip farmer envelope** (acceptance criterion 6): operator sends a Signal message from +59892893012; next /v1/receive call should return at least one envelope with `source=+59892893012`. Deferred to Wave 1 integration check.
- **config.test.js dashboardUrl** mismatch: pre-existing, out of scope for this plan.

## Next Phase Readiness

- Receive pipe live: /v1/receive returns 200 — Wave 1 (capture persistence) can consume envelopes immediately
- 4 envelope fixtures ready for Wave 1–4 test driver injection
- fake-whisper-server.js ready for Wave 2 (transcription client)
- RED skeleton tests committed: Waves 1–4 have clear GREEN targets with requirement IDs embedded
- nvidia-container-toolkit confirmed present: Wave 2 GPU compose will work

---
*Phase: 25-bidirectional-signal-farmer-robot-capture-channel*
*Completed: 2026-04-27*
