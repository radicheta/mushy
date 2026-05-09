---
phase: 25
plan: 03
subsystem: whisper-transcribe / alerter-bridge
tags: [whisper, faster-whisper, fastapi, gpu, cuda, docker-compose, transcribe-client, wave-2, tdd]
one_liner: "GPU transcription sibling live on elder-plops: faster-whisper medium fp16, 30s WAV → 475ms warm; transcribe-client.js GREEN (4/4); R3 satisfied at smoke level"
dependency_graph:
  requires: [25-01]
  provides: [whisper-transcribe-service, transcribe-client]
  affects: [25-04, 25-05]
tech_stack:
  added:
    - "faster-whisper==1.0.3 (CTranslate2 backend)"
    - "fastapi==0.115.6 + uvicorn[standard]==0.32.1"
    - "pydantic==2.10.3"
    - "nvidia/cuda:12.3.2-cudnn9-runtime-ubuntu22.04 base image"
  patterns:
    - "Lazy-load model singleton (Pitfall 5): get_model() guards a module-level _model; first call warms ~3GB VRAM"
    - "V12 path safety: Path.resolve() then relative_to(ALLOWED_ROOT) → 400 on any escape"
    - "Discriminated never-throws HTTP client: createTranscribeClient mirrors signal.js send() shape"
    - "Dual-shape ergonomic API: transcribe('/path') OR transcribe({audio_path}) — accommodates capture.js (string) and the wave-0 RED test (object) without breaking either contract"
    - "Lazy faster-whisper import inside get_model() so unit tests with monkey-patched stub don't need CUDA libs"
key_files:
  created:
    - src/whisper-transcribe/Dockerfile
    - src/whisper-transcribe/main.py
    - src/whisper-transcribe/requirements.txt
    - src/whisper-transcribe/pytest.ini
    - src/whisper-transcribe/test/test_unit.py
    - src/whisper-transcribe/test/test_smoke.py
    - src/whisper-transcribe/test/fixtures/sample-30s.wav
    - src/agents/alerter/src/transcribe-client.js
  modified:
    - docker-compose.yml
    - docker-compose.override.yml
decisions:
  - "Lazy faster-whisper import inside get_model() (defensive): keeps test_unit.py runnable on any host without CUDA"
  - "transcribe(arg) accepts string OR {audio_path} object: bridges capture.js (Wave 1) and the locked wave-0 RED test contract without modifying either"
  - "Smoke test sends literal /data/signal-capture path (no .resolve()) because /data is a symlink on elder-plops — resolve() would point at /mnt/slime-kingdom/data and trip the V12 ALLOWED_ROOT check inside the container"
  - "Cold-start time (322s) is one-shot medium-model download from HuggingFace; subsequent container restarts will be near-instant (CTranslate2 caches in /root/.cache/huggingface/). Warm transcribe (475-512 ms) is the operational metric for R3."
metrics:
  duration: "~28 min"
  completed: "2026-04-27"
  tasks_completed: 3
  tasks_total: 3
  files_created: 8
  files_modified: 2
  test_count: 4_python_unit + 4_node_jest + 1_gpu_smoke
---

# Phase 25 Plan 03: whisper-transcribe Container + Node Client + R3 Round-Trip Summary

GPU transcription sibling stood up on elder-plops with full V12 path-traversal mitigation; Node-side `transcribe-client.js` mirrors the proven `signal.js` shape and turns the Wave-0 RED test file GREEN (4/4); a real 30-second WAV round-trips through the live container in ~500ms warm — orders of magnitude under the 3-minute SPEC R3 budget.

## What Was Built

| Layer | Artifact | Purpose |
|-------|----------|---------|
| Container | `src/whisper-transcribe/{Dockerfile, main.py, requirements.txt}` | FastAPI HTTP service in front of `faster-whisper` medium fp16 on CUDA |
| Tests (CI) | `test/test_unit.py` (4 cases) | Health, 404 on missing, 400 on absolute escape, 400 on `..` traversal — runs without GPU via monkey-patched `get_model` |
| Tests (GPU) | `test/test_smoke.py` (1 case, opt-in `-m gpu`) | Drives live container with 30s WAV; asserts duration_ms < 60_000 |
| Fixture | `test/fixtures/sample-30s.wav` | 30s 16kHz mono PCM, 440Hz sine — proves round-trip without external download |
| Node client | `src/agents/alerter/src/transcribe-client.js` | `createTranscribeClient` factory: AbortController + timeout + never-throws |
| Compose | `docker-compose.yml` + `.override.yml` | New `whisper-transcribe` service (nvidia GPU reservation, RO `/data/signal-capture` mount, host networking, curl healthcheck); alerter env extended with Phase-25 vars |

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | whisper-transcribe container (Dockerfile + main.py + V12 + 4 unit tests + 30s WAV fixture) | `cdaa027` | 7 created in `src/whisper-transcribe/` |
| 2 | transcribe-client.js — turn wave-0 RED tests GREEN | `113dbde` | `src/agents/alerter/src/transcribe-client.js` |
| 3 | Compose wiring + live deploy on elder-plops + GPU smoke verification + R3 evidence | `ba30c4e` | `docker-compose.yml`, `docker-compose.override.yml`, `test_smoke.py` (path fix) |

## Live Deployment Evidence (elder-plops)

```
$ docker images mushy-whisper-transcribe --format '{{.Repository}}:{{.Tag}} {{.Size}}'
mushy-whisper-transcribe:latest  4.19GB

$ docker compose ps whisper-transcribe
NAME                         STATUS                            PORTS
mushy-whisper-transcribe-1   Up (healthy)                      

$ ss -tnlp | grep :8090
LISTEN 0 2048  0.0.0.0:8090  0.0.0.0:*

$ curl -fsS http://localhost:8090/health   # cold
{"ok":true,"model_loaded":false}

$ time curl -X POST http://localhost:8090/transcribe \
    -d '{"audio_path":"/data/signal-capture/sample-30s.wav"}' \
    -H 'Content-Type: application/json'
{"text":"","duration_ms":322154,"language":"en","language_probability":0.574}
real    5m22s          # ← cold: includes one-time medium-model HF download (~1.5GB)

$ curl -fsS http://localhost:8090/health   # warm
{"ok":true,"model_loaded":true}

$ time curl -X POST http://localhost:8090/transcribe \
    -d '{"audio_path":"/data/signal-capture/sample-30s.wav"}' ...
{"text":"","duration_ms":475,"language":"en","language_probability":0.574}
real    0m0.479s       # ← warm: 30s clip → 475ms (R3 ✅)

$ nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader
1626179, /usr/bin/python3, 2050 MiB
   # ← whisper holds 2050 MiB warm; well under 3GB target; 4.6GB free on RTX 2060

$ WHISPER_URL=http://localhost:8090 pytest -m gpu -q test/test_smoke.py
.    1 passed
```

`text` is empty for the pure-tone fixture (Whisper correctly emits nothing for non-speech). Speech fixtures will yield non-empty transcripts in operational use; the round-trip plumbing is proven.

## R3 Compliance

| Metric | Budget (SPEC R3) | Test Threshold | Measured (warm) |
|--------|------------------|----------------|-----------------|
| 30s audio → text | 180 s | 60 s | **475 ms** |

Cold-start cost (~5 min) is a **one-shot** model download per container lifecycle; CTranslate2 caches the model under `/root/.cache/huggingface/` inside the container layer (will persist across restarts; recreate-on-rebuild forces re-download — backlog item if it bites). Operational latency for any inference after the first is sub-second.

## Contract Signature (for Wave 3 capture.js consumers)

```javascript
createTranscribeClient({
  apiUrl: string,           // OR baseUrl (alias for symmetry with fake-whisper-server.url)
  timeoutMs?: number,       // default 200_000 (200s, fits 3min SPEC budget with margin)
  logger?: { warn, info }
}) → {
  transcribe(arg: string | { audio_path: string })
    → Promise<{ ok: true,  text: string, duration_ms: number, language: string }
            | { ok: false, reason: string }>
  // NEVER throws. Aborted on timeout → reason='timeout'.
  // HTTP non-2xx → reason='whisper {status}: {body[:200]}'.
}
```

## Test Counts

| File | Tests | Status |
|------|-------|--------|
| `src/whisper-transcribe/test/test_unit.py` | 4 | GREEN (`pytest -m 'not gpu'`) |
| `src/whisper-transcribe/test/test_smoke.py` | 1 | GREEN against live container |
| `src/agents/alerter/test/transcribe-client.test.js` | 4 | GREEN (turned RED→GREEN, skip-guard removed) |
| `src/agents/alerter` full suite | 122 total: 118 pass, 3 skip (RED placeholders for 25-04), 1 pre-existing fail (`config.test.js dashboardUrl` — out of scope, noted in 25-02) | unchanged |

## Threat Model Status

| Threat ID | Mitigation Status | Evidence |
|-----------|-------------------|----------|
| T-25-03-01 path traversal | **MITIGATED** — `_resolve_safe()` raises 400; covered by `test_400_on_path_traversal` and `test_400_on_dotdot`; verified live via failed `.resolve()` smoke run that returned `{"detail":"path not allowed: outside /data/signal-capture"}` |
| T-25-03-02 LAN exposure on host network | accepted per plan — port 8090 binds 0.0.0.0; Tailscale firewall is the gate. `ss -tnlp` confirms listener; no LAN IP test performed (in-scope for Wave 4 verifier) |
| T-25-03-03 huge audio DoS | partial — `transcribe-client.js` `timeoutMs=200000` caps wall-clock; in-container audio-duration cap deferred (backlog) |
| T-25-03-04 concurrent VRAM exhaustion | accepted per plan — single-farmer, serial envelope processing in capture.js |
| T-25-03-05 silent CPU fallback | **MITIGATED** — base image is CUDA-only; `WHISPER_DEVICE=cuda` hard-coded in env; container would fail to start on CPU-only host. nvidia-container-toolkit confirmed present (Wave 0). |
| T-25-03-06 audit trail | accepted — uvicorn access log to `docker logs` |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] transcribe() arg-shape mismatch between Wave-1 capture.js and Wave-0 RED test**
- **Found during:** Task 2 (transcribe-client.js)
- **Issue:** `capture.js` (committed in 25-02) calls `transcribeClient.transcribe(audioPath)` with a string. The locked Wave-0 RED test calls `client.transcribe({ audio_path: '/tmp/...' })` with an object. The plan's pseudocode used the string form, which would have broken the test contract.
- **Fix:** `transcribe(arg)` checks `typeof arg === 'string'` and falls back to `arg.audio_path`. Both consumers work unchanged.
- **Files modified:** `src/agents/alerter/src/transcribe-client.js`
- **Commit:** `113dbde`

**2. [Rule 1 - Bug] createTranscribeClient option name mismatch**
- **Found during:** Task 2 (running test against fake-whisper-server)
- **Issue:** Plan specified `apiUrl` parameter; the locked Wave-0 RED test passes `{ baseUrl: server.url }` (the fake-whisper-server returns `.url` as its handle field).
- **Fix:** Accept BOTH `apiUrl` (canonical, used in capture.js wiring per PATTERNS line 380) and `baseUrl` (RED test).
- **Files modified:** `src/agents/alerter/src/transcribe-client.js`
- **Commit:** `113dbde`

**3. [Rule 1 - Bug] test_smoke.py .resolve() defeats V12 check on symlinked /data**
- **Found during:** Task 3 (live smoke run)
- **Issue:** Smoke test built `fix.resolve()` from a path under `/data/signal-capture`; on elder-plops `/data` is a symlink to `/mnt/slime-kingdom/data` (per project memory `project_data_path_on_raid`), so `.resolve()` returned `/mnt/slime-kingdom/data/signal-capture/sample-30s.wav`. Inside the container `/data` is a real directory (the bind mount), so `ALLOWED_ROOT.resolve()` is just `/data/signal-capture`. The mismatch correctly tripped the V12 check (returned 400) but caused the smoke to fail.
- **Fix:** Send the literal in-mount path; added `WHISPER_SMOKE_PATH` env override; documented the symlink trap in the test docstring.
- **Files modified:** `src/whisper-transcribe/test/test_smoke.py`
- **Commit:** `ba30c4e`

**4. [Rule 1 - Bug] faster-whisper import broke unit-test collectability without CUDA libs**
- **Found during:** Task 1 unit test wiring
- **Issue:** Top-level `from faster_whisper import WhisperModel` would force any host running `pytest` to have faster-whisper + libcudnn installed even though tests monkey-patch `get_model`.
- **Fix:** Moved import inside `get_model()` (lazy). Unit tests now run on any python with fastapi + httpx + pydantic + pytest — no GPU stack required.
- **Files modified:** `src/whisper-transcribe/main.py`
- **Commit:** `cdaa027`

### Non-deviation Notes

- **`/data/signal-capture` directory** was created automatically by Docker at first compose-up (root-owned). RO mount on whisper-transcribe is fine; alerter's RW mount (compose-override) will be exercised in Wave 3.
- **Fixture deploy** (`docker run --rm -v ... alpine cp ...`) was needed because the live RO mount blocks `docker cp` to the bind path. The recipe is documented in `test_smoke.py` docstring.

## Known Stubs

None. Both `transcribe()` and `/transcribe` produce real outputs end-to-end.

## Deferred Items

- **In-container audio-duration cap** (T-25-03-03 partial mitigation): caller-side timeout is in place; rejecting > 5min audio at the FastAPI layer is a future hardening (RESEARCH Pitfall 5 / Security V13).
- **HuggingFace model cache persistence**: medium model lives inside the container layer; a `docker compose build --no-cache` would force a 5-minute redownload. Adding a named volume on `/root/.cache/huggingface` would eliminate cold-start cost across rebuilds. Backlog.
- **GPU contention design** for v1.4 CV phases — current ~2GB of 6GB is fine; revisit if Phase 24+ pressures VRAM.

## Issues Encountered

- Local pyenv (`mushroom_farm`) was missing → created an isolated `/tmp/whisper-test-venv` with bootstrapped pip for pytest runs. Not committed; CI uses the container's pinned `requirements.txt`.
- `sudo` not available non-interactively in this session → relied on Docker's auto-create-bind-source behavior to make `/data/signal-capture` (root-owned, fine).

## Next Phase Readiness

- **25-04 (LLM client + capture wire-up):** `transcribe-client.js` factory ready to inject into `capture.js`; HTTP contract proven; never-throws guarantee documented.
- **25-05 (integration + retention + heartbeat):** whisper-transcribe is a healthy compose service; alerter env vars are pre-staged in `.override.yml` (TIMESCALE_*, ANTHROPIC_API_KEY, CAPTURE_BASE_PATH, retention vars) — no further compose churn expected for the next two waves.

## Self-Check

### Files exist
- `src/whisper-transcribe/Dockerfile` — FOUND
- `src/whisper-transcribe/main.py` — FOUND
- `src/whisper-transcribe/requirements.txt` — FOUND
- `src/whisper-transcribe/pytest.ini` — FOUND
- `src/whisper-transcribe/test/test_unit.py` — FOUND
- `src/whisper-transcribe/test/test_smoke.py` — FOUND
- `src/whisper-transcribe/test/fixtures/sample-30s.wav` — FOUND
- `src/agents/alerter/src/transcribe-client.js` — FOUND

### Commits exist
- `cdaa027` (Task 1) — FOUND
- `113dbde` (Task 2) — FOUND
- `ba30c4e` (Task 3) — FOUND

### Live container
- `mushy-whisper-transcribe-1` UP, healthcheck passing
- `/health` returns `{ok:true, model_loaded:true}` (warm)
- GPU smoke 1/1 PASS, warm transcribe 475ms

## Self-Check: PASSED

---

*Phase: 25-bidirectional-signal-farmer-robot-capture-channel*
*Completed: 2026-04-27*
