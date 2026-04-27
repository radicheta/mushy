# Phase 25: Bidirectional Signal — farmer↔robot capture channel — Research

**Researched:** 2026-04-27
**Domain:** Node.js (alerter container) + Python (whisper container) + signal-cli REST API + TimescaleDB + Anthropic SDK
**Confidence:** HIGH on signal-cli endpoints, faster-whisper, GPU compose, Anthropic SDK; MEDIUM on json-rpc-vs-normal-mode receive contract specifics; HIGH on existing-code patterns (verified by grep).

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Container topology**
- **D-01:** Capture pipeline lives **inside** the existing `alerter` container. New modules: `capture.js`, `transcribe-client.js`, `llm-client.js`. Alerter becomes the comms hub.
- **D-02:** Transcription in dedicated `whisper-transcribe` container (sibling of alerter). HTTP API `POST /transcribe { audio_path }` → `{ text, duration_ms, language }`.
- **D-03:** Alerts must keep flowing if capture fails. All capture-pipeline errors caught + logged; existing send path + heartbeat continue. Capture failure → degraded reply per SPEC R6. Operator visibility via sensor_health-style indicator (Phase 16 panel).

**Storage layer**
- **D-04:** Capture metadata in TimescaleDB, table `signal_capture`. Reuse bridge's `Pool` pattern; alerter on host network → `TIMESCALE_HOST=localhost`. Hypertable on `(captured_at)`. Schema sketch: `(id ULID PK, captured_at timestamptz, sender text, message_type text, raw_text text, attachment_paths text[], transcript text NULLABLE, llm_session_tag text NULLABLE, llm_reply text NULLABLE, expired boolean default false)`.
- **D-05:** Attachment files at `/data/signal-capture/YYYY-MM-DD/HH-MM-SS-{ULID}.{ext}`. `/data` is the RAID symlink.
- **D-06:** Soft 30-day flag, never auto-delete. Daily job sets `expired=true`; rows + files stay.

**Whisper variant + model**
- **D-07:** faster-whisper (CTranslate2), medium model, CUDA `float16` on elder-plops NVIDIA GPU.
- **D-08:** Auto-detect language per message.
- **D-09:** Whisper container declares GPU via docker-compose `deploy.resources.reservations.devices`.

**LLM session/context**
- **D-10:** Rolling 24-hour window from same sender as LLM context.
- **D-11:** LLM prompt includes current sensor snapshot (latest temp/humidity/CO2 + active alerts in last hour) — raw values only.
- **D-12:** Anthropic model `claude-sonnet-4-6`, `max_tokens=150`.

### Claude's Discretion

- Exact `signal_capture` schema column types and indexes (within sketch)
- LLM system prompt wording and few-shot examples
- Whisper container healthcheck design
- Retention job mechanism (cron / systemd / in-process scheduler)
- Receive-loop poll cadence after primary re-registration
- Log format / verbosity for capture pipeline events
- Concurrency model in `capture.js`

### Deferred Ideas (OUT OF SCOPE)

- FarmOS event creation from captured sessions
- Image content understanding by LLM (metadata only this phase)
- Trend summaries in LLM context (raw values only)
- Multi-recipient routing / farmOS people directory
- Hard retention / cold archival
- GPU contention design with Phase 24+ CV
- Robot-initiated conversations
</user_constraints>

<phase_requirements>
## Phase Requirements (from 25-SPEC.md)

| ID | Description | Research Support |
|----|-------------|------------------|
| R1 | Receive channel unblocked (no HTTP 400) | Section: signal-cli MODE + primary re-registration recipe |
| R2 | Raw capture persistence (Timescale row + disk attachment) | Section: TimescaleDB schema, attachment fetch flow |
| R3 | Audio transcription locally on GPU within 3min | Section: faster-whisper container + GPU compose |
| R4 | Snooze still works (snooze/mute/quiet → 24h global mute, ≤30s ack) | Section: snooze grammar extension + fast-path ordering |
| R5 | Capture-pipeline LLM reply with session tag or clarifier | Section: Anthropic SDK + prompt structure |
| R6 | Degraded-mode reply when whisper or LLM unavailable | Section: error isolation in capture pipeline |
| R7 | Sender whitelist preserved | Already enforced in `receive-loop.js`; keep as-is |
</phase_requirements>

## Summary

Phase 25 turns the alerter container into the comms hub by adding three new modules (`capture.js`, `transcribe-client.js`, `llm-client.js`), one new Python container (`whisper-transcribe`), and one new TimescaleDB hypertable (`signal_capture`). The single biggest unknown going into research was the receive contract: the spike proved SMS roundtrip on the 4G router, but the spike was an *infrastructure prerequisite* (proving SMS can deliver verification codes to the SIM). The actual signal-cli receive path still has two layered issues that must be addressed in Wave 0:

1. **Primary re-registration** of `+59891840205` (linked-secondary mode is the originally-blamed cause of the HTTP 400). [VERIFIED: spike 001 README]
2. **MODE switch from `json-rpc` to `normal`/`native`** — the current `docker-compose.override.yml` sets `MODE=json-rpc`, which makes `/v1/receive/{number}` a **WebSocket** endpoint, not HTTP GET. The existing `receive-loop.js` calls HTTP GET, so even after primary re-registration, the receive loop will still fail unless MODE changes OR the loop is rewritten to use the WebSocket. [CITED: deepwiki signal-cli-rest-api API Reference; multiple GitHub discussions]

This second finding is **load-bearing** and the planner must decide between (a) flipping MODE to `normal`/`native` (low risk, preserves existing HTTP polling code), or (b) implementing a WebSocket client (more reactive, but new code path). Recommendation: (a) — change MODE first, plus a Wave-0 task to verify outbound `/v2/send` still works in `normal` mode (it should; `/v2/send` is HTTP in all modes).

**Primary recommendation:** Wave 0 = signal-cli pipe unblock (re-register primary + switch MODE to `normal` + re-trust farmer with `trust_all_known_keys`). Wave 1 = TimescaleDB schema + capture orchestration + ULID + attachment download. Wave 2 = whisper-transcribe container (CUDA + FastAPI). Wave 3 = Anthropic LLM integration + sensor snapshot prompt. Wave 4 = degraded-mode + snooze fast-path + sensor_health indicator.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Signal envelope reception | signal-cli container | alerter (HTTP poller) | signal-cli owns the protocol; alerter polls |
| Raw text + attachment persistence (DB) | alerter (`capture.js`) | timescale (storage) | alerter has the envelope; timescale stores |
| Attachment file download from signal-cli | alerter (`capture.js`) | signal-cli (`/v1/attachments/{id}`) | alerter copies to `/data/signal-capture/...` |
| Audio transcription | whisper-transcribe container | alerter (HTTP client) | GPU isolation; reusable for non-Signal sources |
| LLM session inference + reply composition | alerter (`llm-client.js`) | Anthropic API | code lives where envelope lives; prompt assembled once |
| Sensor snapshot for LLM context | bridge (`/farmer/summary`) | alerter (consumer) | bridge already serves this exact shape |
| Snooze fast-path detection | alerter (`receive-loop.js` → `snooze.js`) | — | runs BEFORE capture pipeline |
| Capture-error operator visibility | alerter (sensor_health-style indicator) | bridge WS broadcast | mirror Phase 16 indicator pattern |
| Outbound reply (Signal send) | alerter (`signal.js` → `/v2/send`) | signal-cli | already proven in prod |
| Daily expired-flag job | alerter (in-process node-cron) | timescale | low-frequency, no need for separate container |

## Standard Stack

### Core (verify versions before committing)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `@anthropic-ai/sdk` | 0.91.1 | LLM client for capture-reply composition | Official SDK; built-in retries; RateLimitError class. [VERIFIED: `npm view @anthropic-ai/sdk version` → 0.91.1] |
| `ulid` | 3.0.2 | Time-sortable IDs for capture rows + filenames | Existing canonical lib; crypto.randomBytes RNG. [VERIFIED: `npm view ulid version`] |
| `pg` | 8.20.0 | TimescaleDB connection pool | Already in `alerter/package.json`; same pattern as bridge + timelapse. [VERIFIED: `package.json`] |
| `node-cron` | (existing in stack) | Daily expired-flag retention job | Reused pattern from timelapse container. [VERIFIED: 23-CONTEXT.md] |
| `faster-whisper` | latest (Python) | Audio transcription, CTranslate2-backed | Standard local-Whisper; 4× faster than openai/whisper, fp16 on GPU. [CITED: pypi.org/project/faster-whisper] |
| `fastapi` + `uvicorn` | latest (Python) | HTTP wrapper for whisper container | Smallest viable Python web framework; async-friendly; one file. [CITED: linuxserver/whisper-fastapi pattern] |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `ulidx` | 2.4.1 | Alternative ULID lib (better maintained) | Use this instead of `ulid` if Wave 1 hits the dead-fork issue. [CITED: github.com/perry-mitchell/ulidx README] |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `@anthropic-ai/sdk` | raw `fetch` to `api.anthropic.com/v1/messages` | Avoids dep; loses retry/backoff + typed errors. Not worth saving 200KB. |
| `faster-whisper` + custom FastAPI | `linuxserver/faster-whisper` image (Wyoming protocol port 10300) | Wyoming requires a custom client (not HTTP REST). Build our own FastAPI for one HTTP endpoint. [VERIFIED: linuxserver docker hub page] |
| `node-cron` for retention | systemd timer on host | In-process is simpler, survives container rebuilds, matches timelapse pattern. |

**Installation (Node side):**
```bash
cd src/agents/alerter
npm install @anthropic-ai/sdk ulid
# pg already installed
```

**Installation (Python side, in whisper Dockerfile):**
```dockerfile
FROM nvidia/cuda:12.3.2-cudnn9-runtime-ubuntu22.04
RUN apt-get update && apt-get install -y python3 python3-pip ffmpeg && rm -rf /var/lib/apt/lists/*
RUN pip3 install --no-cache-dir faster-whisper fastapi uvicorn[standard]
```

**Version verification:** Run `npm view @anthropic-ai/sdk version` and `pip index versions faster-whisper` immediately before Wave 2 — versions move fast.

## Architecture Patterns

### System Architecture Diagram

```
┌─────────────────┐    SMS verify        ┌─────────────────────┐
│ Huawei B310s-518│◄─────────────────────│ signal-cli register │
│  (4G + SIM)     │                      │  primary (Wave 0)   │
└─────────────────┘                      └─────────────────────┘
        │ farmer's phone (+59892893012)
        ▼
┌──────────────────────────────────────────────────────────────┐
│ Signal infrastructure                                         │
└──────────────────────────────────────────────────────────────┘
        │ inbound to +59891840205
        ▼
┌──────────────────────────────────────────────────────────────┐
│ signal-cli container (MODE=normal/native, HTTP /v1/receive)  │
│   - persists account state in named volume signal-cli-data   │
│   - downloads attachments to /home/.local/share/.../attach/  │
└──────────────────────────────────────────────────────────────┘
        │ HTTP GET /v1/receive/{number}?ignore_attachments=false
        ▼
┌──────────────────────────────────────────────────────────────┐
│ alerter container (host network)                              │
│   ┌──────────────┐                                            │
│   │ receive-loop │ ──┬─► snooze.js  (fast-path, ≤30s ack)    │
│   └──────────────┘   │                                        │
│                      └─► capture.js (async, error-isolated)  │
│                          │                                    │
│                          ├─► download attachments via         │
│                          │   GET /v1/attachments/{id}         │
│                          │   → /data/signal-capture/...       │
│                          │                                    │
│                          ├─► INSERT signal_capture (Timescale)│
│                          │                                    │
│                          ├─► transcribe-client.js ──HTTP─►   │
│                          │                       whisper      │
│                          │                                    │
│                          ├─► llm-client.js (Anthropic SDK)   │
│                          │   prompt = system + 24h history  │
│                          │            + sensor snapshot     │
│                          │            + this message        │
│                          │                                    │
│                          └─► signal.js → /v2/send (reply)   │
└──────────────────────────────────────────────────────────────┘
        │                                       │
        ▼                                       ▼
┌────────────────────────┐          ┌─────────────────────────┐
│ TimescaleDB             │          │ whisper-transcribe       │
│  signal_capture         │          │  container (host net)    │
│  hypertable on          │          │   FastAPI:8090           │
│  captured_at            │          │   POST /transcribe       │
│                          │          │   GPU 0 (RTX 2060 6GB)   │
│ telemetry (read-only,    │          │   medium fp16 ~3GB VRAM  │
│  for sensor snapshot)    │          └─────────────────────────┘
└────────────────────────┘
```

### Component Responsibilities

| Component | File(s) | Owns |
|-----------|---------|------|
| receive-loop | `src/agents/alerter/src/receive-loop.js` | poll cadence, sender whitelist, fan-out to snooze + capture |
| snooze parser | `src/agents/alerter/src/snooze.js` | parse `snooze\|mute\|quiet [args]` → snooze action |
| capture orchestrator | `src/agents/alerter/src/capture.js` (NEW) | ULID, attachment download, DB insert, fan-out to whisper + LLM |
| transcribe client | `src/agents/alerter/src/transcribe-client.js` (NEW) | HTTP POST to whisper container; timeout + retry |
| llm client | `src/agents/alerter/src/llm-client.js` (NEW) | Anthropic SDK wrapper; prompt assembly; degraded-fallback |
| sensor snapshot | reuse bridge `GET /farmer/summary` | latest temp/humidity/CO2/sensor_health for LLM prompt |
| capture history | `src/agents/alerter/src/capture-history.js` (NEW) | SELECT 24h rows by sender for prompt context |
| retention job | `src/agents/alerter/src/capture-retention.js` (NEW) | daily node-cron sets `expired=true` on rows ≥30d |
| whisper service | `src/whisper-transcribe/main.py` (NEW) | FastAPI POST `/transcribe`, lazy-load WhisperModel singleton |

### Recommended Project Structure

```
src/
├── agents/alerter/
│   ├── src/
│   │   ├── capture.js                    # NEW (D-01)
│   │   ├── capture-history.js            # NEW (24h prompt context)
│   │   ├── capture-retention.js          # NEW (daily expired flag)
│   │   ├── transcribe-client.js          # NEW (D-02)
│   │   ├── llm-client.js                 # NEW (D-12)
│   │   ├── capture-db.js                 # NEW (Pool + INSERT/SELECT)
│   │   ├── signal.js                     # extend: receive() returns attachments
│   │   ├── snooze.js                     # extend: snooze|mute|quiet → all/24h
│   │   ├── receive-loop.js               # extend: fast-path snooze, then capture fan-out
│   │   ├── config.js                     # extend: TIMESCALE_*, WHISPER_URL, ANTHROPIC_API_KEY, CAPTURE_BASE_PATH
│   │   └── ...existing files
│   └── test/
│       ├── capture.test.js               # NEW
│       ├── snooze.test.js                # extend
│       └── ...
└── whisper-transcribe/                   # NEW container
    ├── Dockerfile
    ├── main.py
    └── requirements.txt
```

### Pattern 1: Pg Pool (verbatim from timelapse + bridge)

**What:** Single Pool per process; pass to query helpers.
**When to use:** All Timescale access from Node.

```javascript
// Source: src/mission-control/timelapse/src/index.js (verified)
const { Pool } = require('pg');
const pool = new Pool({
  host: config.timescaleHost,        // 'localhost' on host network
  database: config.timescaleDb,       // 'postgres'
  user: config.timescaleUser,         // 'postgres'
  password: config.timescalePassword, // from TIMESCALE_PASSWORD env
  port: 5432,
});
```

### Pattern 2: Anthropic SDK call (system + user, retry-by-default)

```javascript
// Source: github.com/anthropics/anthropic-sdk-typescript README (CITED)
const Anthropic = require('@anthropic-ai/sdk');
const client = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });

const msg = await client.messages.create({
  model: 'claude-sonnet-4-6',
  max_tokens: 150,
  system: SYSTEM_PROMPT,
  messages: [
    { role: 'user', content: userBlock },
  ],
});
const replyText = msg.content[0].text;
```

The SDK retries 429/503 automatically with exponential backoff; tune via `new Anthropic({ maxRetries: 2 })` if needed. [CITED: claude-api-rate-limit guide; SDK README]

Wrap in `try/catch (Anthropic.APIError)` and degrade per SPEC R6 on any error.

### Pattern 3: faster-whisper FastAPI wrapper

```python
# Source: SYSTRAN/faster-whisper README + linuxserver/whisper-fastapi pattern
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from faster_whisper import WhisperModel
import os, time

MODEL_NAME   = os.getenv("WHISPER_MODEL", "medium")
DEVICE       = os.getenv("WHISPER_DEVICE", "cuda")
COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "float16")

app = FastAPI()
_model = None  # lazy-load on first call to keep startup fast
def get_model():
    global _model
    if _model is None:
        _model = WhisperModel(MODEL_NAME, device=DEVICE, compute_type=COMPUTE_TYPE)
    return _model

class TranscribeReq(BaseModel):
    audio_path: str  # path inside the container's bind-mount of /data

@app.post("/transcribe")
def transcribe(req: TranscribeReq):
    if not os.path.exists(req.audio_path):
        raise HTTPException(404, f"audio not found: {req.audio_path}")
    t0 = time.time()
    segments, info = get_model().transcribe(req.audio_path)  # auto-detect lang per D-08
    text = " ".join(s.text.strip() for s in segments).strip()
    return {
        "text": text,
        "duration_ms": int((time.time() - t0) * 1000),
        "language": info.language,
        "language_probability": info.language_probability,
    }

@app.get("/health")
def health():
    return {"ok": True, "model_loaded": _model is not None}
```

**Lazy-load tradeoff (Discretion):** Lazy = first transcription pays ~3-5s model-load tax (one-time per container life), but startup is instant and idle containers don't hold VRAM. Eager (`get_model()` at startup) = first call is fast, but startup is ~5s and idle holds 3GB VRAM. Recommend lazy; Wave-2 verification is a smoke test that hits `/transcribe` before farmer-facing UAT so the model is warm by then.

### Pattern 4: GPU declaration in compose

```yaml
# Source: docs.docker.com/compose/how-tos/gpu-support/ (CITED)
services:
  whisper-transcribe:
    build: ./src/whisper-transcribe
    restart: unless-stopped
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    environment:
      - WHISPER_MODEL=medium
      - WHISPER_DEVICE=cuda
      - WHISPER_COMPUTE_TYPE=float16
    volumes:
      - /data/signal-capture:/data/signal-capture:ro   # read audio files alerter wrote
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://localhost:8090/health"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s
```

Override file (host network) addition:
```yaml
  whisper-transcribe:
    network_mode: "host"
```

With host network, alerter reaches whisper at `http://localhost:8090`. [VERIFIED: Phase 23 timelapse precedent]

### Anti-Patterns to Avoid

- **Polling /v1/receive in JSON-RPC mode** — silently 4xx because endpoint is WebSocket only. [CITED: bbernhard discussions]
- **Hand-rolling Anthropic retry/backoff** — SDK does it correctly with retry-after header parsing.
- **Synchronous capture in receive-loop tick** — would block snooze fast-path. Capture must be `Promise.then().catch()`-style fan-out, not awaited.
- **Re-registering primary every container restart** — registration is one-shot; state lives in `signal-cli-data` named volume.
- **Storing attachments inside the container** — write to `/data/signal-capture/...` (RAID via symlink) so rebuilds preserve them.
- **Using `process.exit` on capture errors** — receive loop must continue ticking (Pitfall 4 already documented in `receive-loop.js`).
- **Using openai/whisper instead of faster-whisper** — 4× slower, more VRAM, no fp16 advantage.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Time-sortable unique IDs | UUID + timestamp prefix scheme | `ulid` (or `ulidx`) | Crypto-safe, monotonic, 26-char canonical; integrates as filename + DB PK |
| Anthropic retry/backoff | custom 429/503 handler | `@anthropic-ai/sdk` built-in retry | Parses `retry-after` header correctly; surfaces RateLimitError |
| Whisper transcription | calling python from node, or porting to Node | dedicated FastAPI container | GPU isolation, separate restart, reusable |
| Postgres connection mgmt | new client per query | `pg.Pool` (already pattern) | reconnect, pooling, BYO transaction support |
| Hypertable creation | manual migration tooling | `CREATE TABLE IF NOT EXISTS` + `SELECT create_hypertable(... if_not_exists => TRUE)` at alerter startup | matches bridge `index.js` pattern (verified line 205-219) |
| signal-cli identity trust restoration | manual safety-number entry | `PUT /v1/identities/{ours}/trust/{theirs}` body `{"trust_all_known_keys": true}` | Documented param; recovery path per memory `project_signal_cli_rebuild_breaks_trust` |
| Cron scheduling for retention | systemd timer | `node-cron` in-process | Already in stack (timelapse), simpler |

**Key insight:** All of the above have battle-tested libraries. The phase's net-new code is the *integration*, not any of the building blocks.

## Common Pitfalls

### Pitfall 1: signal-cli MODE=json-rpc breaks /v1/receive HTTP polling

**What goes wrong:** `GET /v1/receive/{number}` returns 400 even after primary re-registration.
**Why it happens:** In json-rpc mode, the receive endpoint is a WebSocket, not HTTP. Current `docker-compose.override.yml` has `MODE=json-rpc`. [CITED: bbernhard deepwiki API Reference; discussion #361]
**How to avoid:** Set `MODE=normal` (or `MODE=native`) in override.yml during Wave 0. Confirm `/v2/send` still works after the flip (it does — send endpoints are HTTP in all modes).
**Warning signs:** 400 response body says something like "Endpoint not available in this mode."

### Pitfall 2: Linked-secondary mode cannot use /v1/receive at all

**What goes wrong:** Even with MODE=normal, /v1/receive 400s if the account is a linked secondary device.
**Why it happens:** Signal protocol limitation; only the primary device can receive on signal-cli. [CITED: signal-cli quickstart wiki]
**How to avoid:** Wave 0 task — register `+59891840205` as **primary** via SMS verification through the B310s-518 admin UI (spike 001 proved the SMS path).
**Warning signs:** `GET /v1/accounts` shows the number with a `device_id != 1`.

### Pitfall 3: Re-registration wipes farmer identity trust

**What goes wrong:** After re-registering primary, sending a reply to `+59892893012` fails with `untrusted_identity`.
**Why it happens:** Account state in `signal-cli-data` volume is replaced; previously-trusted keys forgotten. [VERIFIED: memory `project_signal_cli_rebuild_breaks_trust`]
**How to avoid:** Wave 0 final step — `PUT /v1/identities/+59891840205/trust/+59892893012` with body `{"trust_all_known_keys": true}`. [CITED: bbernhard discussion #722, #554]
**Warning signs:** First post-rebuild send returns "untrusted identities for: +59892893012".

### Pitfall 4: Attachments not auto-downloaded with `ignore_attachments=true`

**What goes wrong:** Capture rows have `attachment_paths=[]` even though the farmer sent a photo.
**Why it happens:** Existing `signal.js` calls receive with `ignore_attachments=true` (line 44). Need to flip to `false` for capture path. [VERIFIED: file read]
**How to avoid:** Add a second receive call shape (or change the default), and parse attachment IDs from envelope, then GET `/v1/attachments/{id}` to fetch bytes.
**Warning signs:** envelope has `dataMessage.attachments[]` with IDs but no local files.

### Pitfall 5: Whisper container holds GPU even when idle

**What goes wrong:** RTX 2060 6GB shows 3GB allocated permanently after warm-up; future Phase 24 CV work has only 3GB headroom.
**Why it happens:** Eager model load at startup keeps tensors in VRAM. [CITED: faster-whisper PyPI]
**How to avoid:** Lazy-load (recommended) or add `idle_unload_after_sec` env var. Acceptable for v1.4 since CV work is later. Document the headroom in the Phase 25 verification report.
**Warning signs:** `nvidia-smi` shows whisper python process holding ~3GB after no transcription for hours.

### Pitfall 6: Snooze ack delayed because capture pipeline is awaited

**What goes wrong:** Farmer texts `mute` during a Whisper outage; reply takes 60s instead of 30s.
**Why it happens:** receive-loop awaits the capture pipeline before processing the snooze.
**How to avoid:** Detect snooze keyword first; dispatch snooze action and reply BEFORE invoking capture. Capture runs async (fire-and-forget with `.catch(log)`).
**Warning signs:** Snooze ack latency > 30s in logs when whisper is down.

### Pitfall 7: nvidia-container-toolkit not installed on host

**What goes wrong:** `docker compose up whisper-transcribe` fails with "could not select device driver nvidia".
**Why it happens:** Host needs the NVIDIA Container Toolkit installed and Docker daemon configured. [CITED: docs.docker.com gpu-support]
**How to avoid:** Wave-0 environment check — `docker info | grep nvidia` should show the runtime. If missing: `sudo apt install nvidia-container-toolkit && sudo systemctl restart docker`.
**Warning signs:** Compose error on first up; `docker info` lacks `Runtimes: nvidia runc`.

### Pitfall 8: TIMESCALE_HOST=localhost works only on host network

**What goes wrong:** alerter on `signal-net` bridge can't reach Timescale at `localhost:5432`.
**Why it happens:** Current alerter is on a bridge network, not host. [VERIFIED: docker-compose.override.yml line 70]
**How to avoid:** Move alerter to `network_mode: host` (matching bridge/timelapse). Drop `signal-net`. Verify alerter still reaches signal-cli at `http://localhost:8080` (signal-cli will need a host port published, OR keep signal-cli internal and have alerter use service hostname — but host-network alerter can't reach internal compose hostnames). **Decision:** Either (a) put both alerter + signal-cli on host network, or (b) keep current networking and use `host.docker.internal` for Timescale (extra_hosts is already set in current override). Option (b) is lower-blast-radius. Confirm in plan-check.
**Warning signs:** `ECONNREFUSED 127.0.0.1:5432` from alerter on first capture write.

## Runtime State Inventory

> Phase 25 is mostly greenfield — only signal-cli account state and farmer trust are pre-existing runtime state that the phase mutates.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | signal-cli account state in `signal-cli-data` named volume (currently linked-secondary) | **Re-registration wipes this.** Backup before, or accept loss. Phase 26 trust state will also be wiped. |
| Live service config | `MODE=json-rpc` in `docker-compose.override.yml` line 31 | Change to `MODE=normal` and rebuild signal-cli container. |
| OS-registered state | None — all state is in containers/volumes. | None — verified by inspecting host systemd. |
| Secrets/env vars | New: `ANTHROPIC_API_KEY`, `TIMESCALE_PASSWORD` (already exists), `WHISPER_URL`, `CAPTURE_BASE_PATH` | Add `ANTHROPIC_API_KEY` to host `.env`; SOPS encrypt if pattern in repo. |
| Build artifacts | None pre-existing for new containers; `signal-cli-data` volume should be checked for orphan keys post-re-registration | After Wave 0, `docker volume inspect signal-cli-data` to confirm new account is primary (device_id=1). |

## Code Examples

### signal_capture schema bootstrap (mirror bridge pattern)

```javascript
// Source: src/mission-control/bridge/src/index.js lines 205-219 (VERIFIED)
async function ensureCaptureSchema(pool) {
  await pool.query(`
    CREATE TABLE IF NOT EXISTS signal_capture (
      id              text PRIMARY KEY,
      captured_at     timestamptz NOT NULL DEFAULT now(),
      sender          text NOT NULL,
      message_type    text NOT NULL,           -- 'text' | 'audio' | 'image' | 'mixed'
      raw_text        text,
      attachment_paths text[] DEFAULT ARRAY[]::text[],
      transcript      text,
      llm_session_tag text,
      llm_reply       text,
      degraded        boolean NOT NULL DEFAULT false,
      expired         boolean NOT NULL DEFAULT false
    )
  `);
  await pool.query(`
    SELECT create_hypertable('signal_capture', 'captured_at',
      if_not_exists => TRUE, migrate_data => TRUE)
  `);
  await pool.query(`
    CREATE INDEX IF NOT EXISTS idx_signal_capture_sender_time
    ON signal_capture (sender, captured_at DESC)
  `);
  await pool.query(`
    CREATE INDEX IF NOT EXISTS idx_signal_capture_expired
    ON signal_capture (expired) WHERE expired = false
  `);
}
```

Note: Hypertable PK must include the partitioning column. With `id` text PK, Timescale 2.x requires `(id, captured_at)` composite. Either change PK to `(captured_at, id)` or skip the hypertable conversion (a regular table is fine — query patterns are sender + time-range, indexed). **Recommend regular table** since volume is tiny (single farmer); hypertable buys nothing here. Discuss in plan-check.

### ULID file-path generation

```javascript
// Source: ulid npm README (CITED)
const { ulid } = require('ulid');
const path = require('path');

function captureFilePath(baseDir, capturedAtMs, ext) {
  const id = ulid(capturedAtMs);  // monotonic if timestamp same
  const d  = new Date(capturedAtMs);
  const day  = d.toISOString().slice(0, 10);                  // YYYY-MM-DD
  const time = d.toISOString().slice(11, 19).replace(/:/g, '-'); // HH-MM-SS
  return {
    id,
    file_path: path.join(baseDir, day, `${time}-${id}.${ext}`),
  };
}
```

### Snooze grammar extension

```javascript
// Source: extends src/agents/alerter/src/snooze.js (VERIFIED current code)
const SIMPLE = /^\s*(snooze|mute|quiet)\b\s*$/i;
const STRICT = /^snooze\s+(rh|sensor|pi|humidifier|sht30|scd41|all)\s+(30m|1h|2h|4h|8h|24h)\s*$/i;

function parseSnoozeCommand(text, nowMs) {
  if (typeof text !== 'string') return fuzzyReply();
  const t = text.trim();

  // NEW: simple keyword → all/24h
  if (SIMPLE.test(t)) {
    return {
      ok: true,
      alertType: 'all',
      durationMs: VALID_DURATIONS['24h'],
      untilMs: nowMs + VALID_DURATIONS['24h'],
      ackText: 'alerts muted for 24h',
    };
  }

  // EXISTING: strict grammar (legacy, still accepted)
  const m = t.match(STRICT);
  if (m) { /* unchanged */ }

  return fuzzyReply();   // CHANGED: only triggers for non-snooze, non-empty text — capture pipeline takes over
}
```

**Critical change in receive-loop:** when `parseSnoozeCommand` returns `ok: false`, don't immediately reply with help text — *that's now the capture path's job*. Help text becomes a fallback only when capture pipeline degrades AND text was clearly attempting a snooze (e.g., starts with "snooze" but malformed).

### Receive-loop fan-out (snooze fast-path + capture)

```javascript
// Source: extension of src/agents/alerter/src/receive-loop.js (VERIFIED current shape)
async function tick() {
  try {
    const envelopes = await signalClient.receive({ timeoutSec: 1, ignoreAttachments: false });
    for (const env of envelopes) {
      const source = env?.envelope?.source;
      const dm     = env?.envelope?.dataMessage;
      if (!source) continue;
      if (!allowedSenders.has(source)) {
        logger.warn('[receive] rejected sender (not in whitelist)');
        continue;
      }

      const text = dm?.message;
      const attachments = dm?.attachments || [];

      // FAST PATH: snooze keyword (≤30s ack budget)
      if (text) {
        const parsed = parseSnoozeCommand(text, clock());
        if (parsed.ok) {
          dispatch({ type: 'snooze', alertType: parsed.alertType, untilMs: parsed.untilMs });
          continue;  // do not capture snooze commands per SPEC R4
        }
      }

      // SLOW PATH: capture (async, error-isolated per D-03)
      if (text || attachments.length) {
        capturePipeline.handle({ envelope: env, source, text, attachments })
          .catch((e) => logger.warn(`[capture] pipeline error: ${e.message}`));
      }
    }
  } catch (e) {
    logger.warn(`[receive] loop tick error: ${e.message}`);
  }
}
```

### Anthropic LLM client with degraded fallback

```javascript
// Source: github.com/anthropics/anthropic-sdk-typescript README (CITED)
const Anthropic = require('@anthropic-ai/sdk');

function createLlmClient({ apiKey, logger = console }) {
  const client = new Anthropic({ apiKey, maxRetries: 2 });
  return {
    async compose({ history, sensorSnapshot, currentMessage }) {
      try {
        const msg = await client.messages.create({
          model: 'claude-sonnet-4-6',
          max_tokens: 150,
          system: SYSTEM_PROMPT,
          messages: [{
            role: 'user',
            content: buildUserBlock(history, sensorSnapshot, currentMessage),
          }],
        });
        return { ok: true, text: msg.content[0].text };
      } catch (e) {
        logger.warn(`[llm] degraded: ${e.message}`);
        return { ok: false, reason: e.message };  // capture caller composes fallback receipt
      }
    },
  };
}
```

### Sensor snapshot fetch (reuse bridge endpoint)

```javascript
// Source: src/mission-control/bridge/src/index.js line 320 (VERIFIED)
async function fetchSensorSnapshot(bridgeUrl) {
  const res = await fetch(`${bridgeUrl}/farmer/summary`, { signal: AbortSignal.timeout(2000) });
  if (!res.ok) return null;
  return await res.json();   // { sensors: { humidity, temperature, co2 }, sensor_health, ... }
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| openai/whisper Python | faster-whisper (CTranslate2) | 2023+ | 4× faster, fp16, less VRAM |
| MODE=json-rpc with HTTP polling | MODE=normal with HTTP polling, OR json-rpc with WS | bbernhard ~2024 | json-rpc made /v1/receive WS-only |
| Manual curl for trust | `trust_all_known_keys: true` body field | bbernhard recent | Single-call recovery; no safety number needed |
| `device="cuda"` + `compute_type="default"` | `compute_type="float16"` | faster-whisper 1.0+ | Half VRAM, similar accuracy |

**Deprecated/outdated:**
- `/v1/send` endpoint — use `/v2/send` (already in alerter code).
- `huawei-lte-api` for SMS — only used in spike 001 to verify SMS path; not used in Phase 25 runtime (signal-cli does its own SMS via Signal infra, not via the 4G modem). The 4G router SIM is only relevant during the one-shot primary re-registration.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | MODE=normal supports all current send endpoints alerter uses | Pitfall 1 | If wrong, alerter outbound sends break in Wave 0; mitigation: smoke test send before merging the MODE flip |
| A2 | Existing `signal-cli-data` volume is fine to wipe (no farmer-side ratchet to preserve) | Pitfall 3 | If farmer has Signal session keys, re-registration produces "session reset" notice on his phone — cosmetic, expected |
| A3 | RTX 2060 6GB has enough headroom for medium fp16 (~3GB) AND background OS GPU usage (~1.4GB shown in nvidia-smi) | D-09 | If hits OOM, fall back to `small` model or `int8_float16` compute |
| A4 | Anthropic API has reliable enough latency (3-5s typical) to fit 60s text budget | D-12 | If slower, degraded mode (R6) absorbs it cleanly |
| A5 | Existing alerter network mode (signal-net bridge) can reach Timescale via host.docker.internal | Pitfall 8 | Confirmed pattern in existing override (extra_hosts already present); low risk |
| A6 | TimescaleDB hypertable conversion of `signal_capture` is unnecessary at single-farmer volume | Code Examples / signal_capture schema | Small risk: skipping hypertable means no automatic chunk pruning, but volume is ~10s of rows/day max |
| A7 | faster-whisper auto-detect language adds <500ms per call | D-08 | Light load test in Wave 2 verifies |
| A8 | `node-cron` already in alerter's dependency tree | Standard Stack | If not, add it; trivial |

## Open Questions

1. **Should `signal_capture` be a Timescale hypertable or a regular table?**
   - What we know: hypertable PK must include partitioning column → composite PK `(captured_at, id)` instead of `id` PK.
   - What's unclear: does the planner want chunk pruning + retention policies, or accept that volume is too low to matter?
   - Recommendation: regular table this phase; convert later if volume justifies it. Locks in simpler code now.

2. **alerter network mode: keep `signal-net` bridge or move to host?**
   - What we know: bridge/timelapse use host net for `TIMESCALE_HOST=localhost`. Alerter is currently bridge with `host.docker.internal` + internal `signal-net` for signal-cli reachability.
   - What's unclear: if alerter goes host net, signal-cli must also be host (which exposes its port unintentionally) OR alerter must reach signal-cli some other way.
   - Recommendation: keep current alerter bridge net + `extra_hosts: host.docker.internal:host-gateway`. Set `TIMESCALE_HOST=host.docker.internal`. Lower blast radius than re-architecting compose. **Confirm in plan-check.**

3. **Lazy vs eager Whisper model load?**
   - What we know: lazy = first call slower (~3-5s), idle containers don't hold VRAM. Eager = consistent latency but always-allocated.
   - What's unclear: farmer-perceived first-message latency tolerance.
   - Recommendation: lazy with a Wave-2 warm-up smoke test that runs at end of deploy. Documented in Pitfall 5.

4. **Should the daily expired-flag job live in alerter or whisper or its own container?**
   - What we know: D-06 says "soft 30-day flag, never auto-delete." Mechanism is Claude's discretion.
   - Recommendation: in-process node-cron in alerter. Simpler than a new container; matches timelapse pattern.

5. **Sensor snapshot: pull from bridge `/farmer/summary` or query Timescale directly?**
   - What we know: `/farmer/summary` is the canonical surface (Phase 18). Bridge maintains an in-process cache of latest values.
   - Recommendation: HTTP `/farmer/summary` — single source of truth, already built, includes sensor_health.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Docker | All containers | ✓ | 28.2.2 | — |
| NVIDIA GPU + driver | whisper-transcribe | ✓ | RTX 2060 6GB, driver 580.126.18, CUDA 13.0 | Skip GPU → `device="cpu" compute_type="int8"` (10× slower; medium might miss 3min budget) |
| nvidia-container-toolkit | whisper-transcribe | UNVERIFIED | — | If missing: `apt install nvidia-container-toolkit` then `systemctl restart docker` |
| TimescaleDB | signal_capture | ✓ | latest-pg14 (compose) | — |
| signal-cli REST API container | receive + send | ✓ | bbernhard 0.200-dev | Upgrade to latest if MODE flip alone doesn't fix /v1/receive |
| Anthropic API key | LLM | UNVERIFIED in repo | — | None — phase requires it; user must provision and add to host `.env` |
| Huawei B310s-518 admin (SMS verify) | one-shot primary re-registration | ✓ | proven by spike 001 | If unavailable when Wave 0 runs: postpone re-registration, R1 stays blocked |
| Tailscale connectivity | farmer phone routing | independent of phase | — | — |

**Missing dependencies with no fallback:**
- `ANTHROPIC_API_KEY` env var — Wave 0 task: confirm provisioning before plan-check.

**Missing dependencies with fallback:**
- nvidia-container-toolkit — install during Wave 2 if absent.

## Validation Architecture

> Required by `workflow.nyquist_validation: true` in `.planning/config.json` (verified).

### Test Framework
| Property | Value |
|----------|-------|
| Framework (Node) | Jest 29 (existing in `src/agents/alerter`) |
| Framework (Python) | pytest (NEW in `src/whisper-transcribe/test/`) |
| Config file (Node) | `src/agents/alerter/jest.config.js` (verified exists) |
| Config file (Python) | `src/whisper-transcribe/pytest.ini` (Wave 0 NEW) |
| Quick run command (Node) | `cd src/agents/alerter && npm test -- --testPathPattern=capture` |
| Full suite (Node) | `cd src/agents/alerter && npm test` |
| Full suite (Python) | `cd src/whisper-transcribe && pytest` |
| Phase gate | Node + Python both green before `/gsd-verify-work` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|--------------|
| R1 | `/v1/receive` returns 200 with envelopes | integration (live) | `curl http://localhost:8080/v1/receive/+59891840205` after Wave 0 | ❌ Wave 0 (manual smoke; capture exit code in deploy script) |
| R1 | receive-loop parses dataMessage + attachments | unit | `npm test -- receive-loop.test.js` (extend) | ✅ existing |
| R2 | DB row written with sender + ULID + paths | unit (fake pg client) | `npm test -- capture.test.js` | ❌ Wave 0 |
| R2 | attachment file copied to /data/signal-capture/... | integration (tmp dir) | `npm test -- capture.test.js` | ❌ Wave 0 |
| R3 | Whisper container transcribes a 30s clip in <3min | integration (real GPU) | `pytest test/test_smoke.py -m gpu` | ❌ Wave 0 |
| R3 | transcribe-client times out gracefully | unit (mock fetch) | `npm test -- transcribe-client.test.js` | ❌ Wave 0 |
| R4 | `mute` / `snooze` / `quiet` → 24h all-mute | unit | `npm test -- snooze.test.js` (extend with new cases) | ✅ existing — extend |
| R4 | snooze fast-path runs before capture | unit (call-order assertion) | `npm test -- receive-loop.test.js` | ✅ existing — extend |
| R4 | snooze ack within 30s when whisper down | integration (whisper stopped) | manual smoke + log assertion | ❌ Wave 4 |
| R5 | LLM reply contains session tag for clear inoc batch | integration (live API + fixture transcript) | `npm test -- llm-client.integration.test.js` (gated by ANTHROPIC_API_KEY) | ❌ Wave 3 |
| R5 | LLM client constructs prompt with 24h history + sensor snapshot | unit (mock SDK) | `npm test -- llm-client.test.js` | ❌ Wave 3 |
| R6 | Whisper down → reply within 60s naming receipt | integration | manual smoke; log timestamp diff | ❌ Wave 4 |
| R6 | LLM down → reply with raw counts | unit (mock SDK throws) | `npm test -- capture.test.js` | ❌ Wave 4 |
| R7 | Non-whitelist sender → no row, no reply, warn log | unit | `npm test -- receive-loop.test.js` (extend) | ✅ existing — extend |

### Sampling Rate
- **Per task commit:** `cd src/agents/alerter && npm test -- --testPathPattern=<module>` (≤5s)
- **Per wave merge:** `cd src/agents/alerter && npm test` + `cd src/whisper-transcribe && pytest -m 'not gpu'` (≤30s)
- **Phase gate:** Above + GPU smoke test (`pytest -m gpu`) + manual end-to-end farmer sends 1 audio + 3 photos + 1 text → ≥4 attachments persisted, transcript appears, LLM reply received within 3min.

### Wave 0 Gaps
- [ ] `src/agents/alerter/test/capture.test.js` — covers R2, R6 LLM-down branch
- [ ] `src/agents/alerter/test/transcribe-client.test.js` — covers R3 timeout/error mock
- [ ] `src/agents/alerter/test/llm-client.test.js` — covers R5 prompt construction, R6 LLM-down branch
- [ ] `src/agents/alerter/test/fixtures/envelopes/text.json` — fake signal-cli envelope, text only
- [ ] `src/agents/alerter/test/fixtures/envelopes/audio.json` — fake envelope with audio attachment
- [ ] `src/agents/alerter/test/fixtures/envelopes/photo-batch.json` — 3 photos batch
- [ ] `src/agents/alerter/test/fixtures/envelopes/snooze.json` — fast-path test cases (`mute`, `snooze`, `quiet`)
- [ ] `src/whisper-transcribe/Dockerfile` — CUDA + faster-whisper + FastAPI
- [ ] `src/whisper-transcribe/main.py` — FastAPI app
- [ ] `src/whisper-transcribe/requirements.txt` — pinned versions
- [ ] `src/whisper-transcribe/test/test_smoke.py` — `@pytest.mark.gpu` 30s clip transcription
- [ ] `src/whisper-transcribe/test/fixtures/sample-30s.wav` — short audio sample for smoke
- [ ] `src/whisper-transcribe/pytest.ini` — `markers = gpu: requires NVIDIA GPU`
- [ ] Extend `src/agents/alerter/test/snooze.test.js` — `mute`/`snooze`/`quiet` cases
- [ ] Extend `src/agents/alerter/test/receive-loop.test.js` — fast-path-before-capture, R7 whitelist

## Security Domain

> Required by `security_enforcement` (default enabled).

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | Anthropic API key in env (.env, never logged); SOPS encryption if pattern in repo |
| V3 Session Management | partial | Signal session keys live in `signal-cli-data` volume; treat as secret |
| V4 Access Control | yes | Sender whitelist enforced (R7); already in receive-loop |
| V5 Input Validation | yes | Validate envelope shape before insert; cap raw_text length (Signal max ~2000); sanitize attachment filenames |
| V6 Cryptography | no (we don't roll any) | Signal handles E2E; we only consume plaintext post-decryption |
| V7 Error Handling | yes | Mask phone numbers in logs (existing `maskNumber` pattern in `config.js` line 52, VERIFIED) |
| V12 File / Resource | yes | Attachment paths are server-controlled (filename = ULID + sanitized ext); never trust client filename |
| V13 API Security | yes | Whisper container only listens on `localhost:8090` (host net); not LAN-exposed |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SQL injection in capture insert | Tampering | Parameterized queries via `pg` Pool (existing pattern) |
| Path traversal via attachment filename | Tampering | Use ULID-derived path; ignore client-supplied filename component |
| Prompt injection via farmer message into LLM | Tampering | Bound LLM in system prompt to "≤2 lines", "session-tag receipt only"; max_tokens=150 caps blast radius; LLM has no tool-call surface |
| Anthropic API key leak in logs | Info disclosure | Never log request bodies; SDK does not log key by default |
| Phone number disclosure in logs | Info disclosure | Reuse existing `maskNumber()` for sender/recipient |
| Untrusted identity DoS (farmer's keys rotate) | DoS | Catch `untrusted_identity` send error → re-trust via `trust_all_known_keys: true` automatically; alert operator |
| Disk fill via large attachments | DoS | Cap attachment size at signal-cli's default (Signal limit ~100MB); /data on RAID has ~TB; soft-cap by warning if any file > 50MB |
| Whisper service exhaustion (huge audio) | DoS | Reject `audio_path` > 5min duration in transcribe-client BEFORE calling whisper; 5min × medium fp16 ≈ 30s wall clock, well within 3min budget |

## Sources

### Primary (HIGH confidence)
- `src/mission-control/bridge/src/index.js` — Pool pattern, hypertable bootstrap, /farmer/summary shape (lines 5-27, 200-219, 320-343)
- `src/mission-control/timelapse/src/index.js` — sibling-container pg pattern, node-cron pattern (lines 1-23)
- `src/agents/alerter/src/{signal,receive-loop,snooze,config,index}.js` — existing alerter shape (all VERIFIED via direct read)
- `docker-compose.yml` + `docker-compose.override.yml` — verified live deployment target (host network bridge/timelapse, MODE=json-rpc on signal-cli)
- `.planning/spikes/001-huawei-router-sms-roundtrip/README.md` — pre-gate VERDICT: PASS (2026-04-27)
- `nvidia-smi` output on elder-plops — RTX 2060 6GB, 1.4GB used, driver 580.126.18, CUDA 13.0 (VERIFIED)
- `npm view` for `@anthropic-ai/sdk` (0.91.1), `ulid` (3.0.2), `ulidx` (2.4.1), `pg` (8.20.0) — VERIFIED 2026-04-27

### Secondary (MEDIUM confidence)
- bbernhard signal-cli-rest-api API Reference (deepwiki, GitHub README + EXAMPLES.md)
- bbernhard discussions #722 (trust endpoint), #361 (json-rpc receive WebSocket), #160 (json-rpc beta)
- AsamK signal-cli wiki — register/verify quickstart
- SYSTRAN/faster-whisper PyPI page + README — install, GPU compute_type
- Docker docs: compose deploy resources reservations devices (GPU)
- anthropic-sdk-typescript GitHub README — messages.create, retries

### Tertiary (LOW confidence — flagged for live verification)
- "MODE=normal" enables HTTP /v1/receive as opposed to WebSocket — validated by deepwiki summary; NOT directly tested in this session. Wave 0 must verify by curl.
- `trust_all_known_keys: true` body field name — confirmed in two sources but not direct API doc fetch. Verify via Wave 0 curl smoke.

## Metadata

**Confidence breakdown:**
- Standard stack (versions, install): HIGH — verified via npm + nvidia-smi
- Architecture (alerter extension + new whisper container): HIGH — direct code reads
- signal-cli MODE/receive contract: MEDIUM — multiple sources agree, but live verification deferred to Wave 0 (assumption A1)
- Pitfalls: HIGH — most are documented in existing memory or verified upstream
- LLM prompt design: LOW — Claude's discretion per CONTEXT; planner will iterate

**Research date:** 2026-04-27
**Valid until:** 2026-05-27 (signal-cli-rest-api is fast-moving; if the project sits >30d, re-verify MODE/receive behavior against latest image)

## RESEARCH COMPLETE

**Phase:** 25 - Bidirectional Signal — farmer↔robot capture channel
**Confidence:** HIGH overall, with two MEDIUM-confidence assumptions (A1: MODE=normal HTTP /v1/receive works; A2: signal-cli-data volume safe to wipe) that Wave 0 explicitly verifies before downstream waves commit.

### Key Findings
- **Load-bearing finding the spike did NOT cover:** current `MODE=json-rpc` makes `/v1/receive` a WebSocket endpoint, not HTTP GET. Even after primary re-registration, the existing `receive-loop.js` HTTP poller will fail until MODE flips to `normal`/`native`. Recommend MODE flip in Wave 0 alongside re-registration.
- Trust recovery for the farmer (`+59892893012`) post-rebuild is a single PUT call with body `{"trust_all_known_keys": true}` — no safety number ceremony required.
- faster-whisper medium fp16 needs CUDA 12 + cuDNN 9 (`nvidia/cuda:12.3.2-cudnn9-runtime-ubuntu22.04` base); ~3GB VRAM out of 6GB on RTX 2060 leaves ~3GB headroom.
- `pg` and `node-cron` patterns are already in the stack (bridge + timelapse) — Phase 25 just clones them. New deps are `@anthropic-ai/sdk` and `ulid` only.
- Signal_capture as regular table (not hypertable) is the simpler choice at single-farmer volume — composite-PK requirement of hypertables forces complexity for no benefit yet.
- Snooze fast-path must run before capture fan-out so `mute` keeps its 30s ack budget even when whisper or LLM is degraded.

### File Created
`/mnt/slime-kingdom/opt/mushy/.planning/phases/25-bidirectional-signal-farmer-robot-capture-channel/25-RESEARCH.md`

### Confidence Assessment
| Area | Level | Reason |
|------|-------|--------|
| Standard Stack | HIGH | versions verified via npm registry; existing patterns in repo |
| Architecture | HIGH | direct code reads of all canonical refs |
| Pitfalls | HIGH | documented in memory + multiple upstream sources |
| signal-cli MODE behavior | MEDIUM | strong consensus across deepwiki + 2 GH discussions; deserves a Wave-0 curl smoke before committing the rest |
| LLM prompt + reply quality | LOW | Claude's discretion; iteration expected |

### Open Questions
- Hypertable vs regular table for `signal_capture` (recommend regular)
- alerter network mode (recommend keep current bridge + host.docker.internal)
- Lazy vs eager Whisper load (recommend lazy + Wave-2 warm-up smoke)
- Daily expired-flag job location (recommend in-process node-cron in alerter)

### Ready for Planning
Research complete. Planner can create PLAN.md files. Recommend wave decomposition:
- **Wave 0:** signal-cli pipe unblock (MODE flip + primary re-registration + trust restoration + smoke test)
- **Wave 1:** Capture persistence (DB schema, ULID, attachment download, capture orchestrator)
- **Wave 2:** Whisper container (CUDA Dockerfile, FastAPI, GPU compose, smoke test)
- **Wave 3:** Anthropic LLM integration (prompt assembly, sensor snapshot fetch, 24h history query)
- **Wave 4:** Snooze fast-path + degraded-mode + sensor_health-style operator indicator + UAT

Sources:
- [bbernhard/signal-cli-rest-api README](https://github.com/bbernhard/signal-cli-rest-api)
- [bbernhard signal-cli-rest-api API Reference (deepwiki)](https://deepwiki.com/bbernhard/signal-cli-rest-api/4-api-reference)
- [bbernhard discussion #722 — trust endpoint](https://github.com/bbernhard/signal-cli-rest-api/discussions/722)
- [bbernhard discussion #361 — json-rpc receive WebSocket](https://github.com/bbernhard/signal-cli-rest-api/discussions/361)
- [AsamK signal-cli quickstart](https://github.com/AsamK/signal-cli/wiki/Quickstart)
- [faster-whisper on PyPI](https://pypi.org/project/faster-whisper/)
- [SYSTRAN/faster-whisper README](https://github.com/SYSTRAN/faster-whisper)
- [Docker Compose GPU support](https://docs.docker.com/compose/how-tos/gpu-support/)
- [anthropic-sdk-typescript](https://github.com/anthropics/anthropic-sdk-typescript)
- [ulid on npm](https://www.npmjs.com/package/ulid)
- [ulidx on npm](https://www.npmjs.com/package/ulidx)
