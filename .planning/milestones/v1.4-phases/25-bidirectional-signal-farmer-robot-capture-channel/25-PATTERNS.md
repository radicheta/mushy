# Phase 25: Bidirectional Signal — farmer↔robot capture channel — Pattern Map

**Mapped:** 2026-04-27
**Files analyzed:** 18 (10 new Node modules in alerter, 4 new tests + fixtures, 4 new files in `whisper-transcribe`)
**Analogs found:** 18 / 18 (all new files have a strong existing analog inside the repo)

## File Classification

### Created (new files)

| New File | Role | Data Flow | Closest Analog | Match Quality |
|----------|------|-----------|----------------|---------------|
| `src/agents/alerter/src/capture.js` | service (orchestrator) | request-response (envelope→DB+disk+downstream) | `src/agents/alerter/src/heartbeat.js` (orchestrator pattern) + `src/mission-control/timelapse/src/index.js` `runComposition()` | role-match |
| `src/agents/alerter/src/capture-db.js` | model (DB layer) | CRUD | `src/mission-control/timelapse/src/db.js` | exact |
| `src/agents/alerter/src/capture-history.js` | model (read-only query) | CRUD (SELECT) | `src/mission-control/timelapse/src/db.js` `fetchRhForDay` | exact |
| `src/agents/alerter/src/capture-retention.js` | service (cron job) | batch | `src/mission-control/timelapse/src/index.js` `cron.schedule(...)` block (lines 70-86) | exact |
| `src/agents/alerter/src/transcribe-client.js` | service (HTTP client) | request-response | `src/agents/alerter/src/signal.js` `send()` (fetch + AbortController + timeout) | exact |
| `src/agents/alerter/src/llm-client.js` | service (SDK wrapper) | request-response | `src/agents/alerter/src/signal.js` (factory + try/catch + degraded return) | role-match |
| `src/agents/alerter/test/capture.test.js` | test | unit + fake-server | `src/agents/alerter/test/receive-loop.test.js` | exact |
| `src/agents/alerter/test/transcribe-client.test.js` | test | unit (mock fetch) | `src/agents/alerter/test/signal.test.js` (assumed mirror) + `helpers/fake-signal-server.js` | role-match |
| `src/agents/alerter/test/llm-client.test.js` | test | unit (mock SDK) | `src/agents/alerter/test/heartbeat.test.js` | role-match |
| `src/agents/alerter/test/fixtures/envelopes/*.json` | test fixture | static | `src/agents/alerter/test/fixtures/` (existing dir) | exact |
| `src/whisper-transcribe/Dockerfile` | config | container build | `src/agents/alerter/Dockerfile` (structure) + `src/mission-control/timelapse/Dockerfile` (RUN apk pattern) | role-match (different base image) |
| `src/whisper-transcribe/main.py` | controller (FastAPI app) | request-response | RESEARCH.md Pattern 3 (no in-repo Python analog) | no analog (use research) |
| `src/whisper-transcribe/requirements.txt` | config | static | none | no analog |
| `src/whisper-transcribe/test/test_smoke.py` | test | integration (GPU) | none in repo | no analog (pytest standard) |

### Modified (existing files)

| Modified File | Role | Data Flow | Why Modified |
|---------------|------|-----------|--------------|
| `src/agents/alerter/src/signal.js` | service | request-response | extend `receive()` to `ignore_attachments=false`; add `fetchAttachment(id)` |
| `src/agents/alerter/src/receive-loop.js` | controller (poller + dispatcher) | event-driven | snooze fast-path BEFORE capture fan-out; capture is fire-and-forget |
| `src/agents/alerter/src/snooze.js` | utility (parser) | transform | accept `snooze\|mute\|quiet` simple grammar → all/24h |
| `src/agents/alerter/src/config.js` | config | env loader | new vars: `TIMESCALE_*`, `WHISPER_URL`, `ANTHROPIC_API_KEY`, `CAPTURE_BASE_PATH`, `BRIDGE_HTTP_URL` |
| `src/agents/alerter/src/index.js` | bootstrap | wiring | wire pool, capture, llm, transcribe-client, retention cron |
| `src/agents/alerter/package.json` | config | manifest | add `@anthropic-ai/sdk`, `ulid`, `node-cron` |
| `src/agents/alerter/test/snooze.test.js` | test | unit | new cases for `mute`/`snooze`/`quiet` |
| `src/agents/alerter/test/receive-loop.test.js` | test | unit | fast-path-before-capture assertion + R7 whitelist |
| `docker-compose.override.yml` | config | deployment | flip `MODE=json-rpc` → `MODE=normal`; add `whisper-transcribe` service; add alerter env vars |
| `docker-compose.yml` (or override) | config | deployment | add `whisper-transcribe` service definition |

## Pattern Assignments

### `src/agents/alerter/src/capture-db.js` (model, CRUD)

**Analog:** `src/mission-control/timelapse/src/db.js` — pure module, pool injected by caller, parameterized queries, `CREATE TABLE IF NOT EXISTS` bootstrap.

**Module shape pattern** (timelapse/src/db.js lines 1-26):
```javascript
// Phase 23: timelapses registry + RH lookup helpers.
// Pure module — pool injected by caller.

async function initDb(pool) {
    await pool.query(`
        CREATE TABLE IF NOT EXISTS timelapses (
            camera_id    TEXT        NOT NULL,
            ...
            PRIMARY KEY (camera_id, date)
        )
    `);
}

async function insertTimelapse(pool, { camera_id, date, file_path, ... }) {
    await pool.query(
        `INSERT INTO timelapses (camera_id, date, file_path, ...)
         VALUES ($1, $2, $3, $4, $5)
         ON CONFLICT (camera_id, date) DO UPDATE
           SET file_path=$3, ...`,
        [camera_id, date, file_path, ...]
    );
}

module.exports = { initDb, insertTimelapse, lookupTimelapse, ... };
```

**Why this analog:** Identical role (Timescale write/read helpers exposed as a pure module); planner mirrors `initDb`, `insertCapture`, `selectByExpiredAndAge` shape. Use **regular table, not hypertable** (per RESEARCH Open Question #1).

**Indexed bootstrap reference:** `src/mission-control/bridge/src/index.js` lines 204-220 (CREATE TABLE + create_hypertable + CREATE INDEX inside an `initDb()` wrapped in try/catch — copy the index DDL pattern).

---

### `src/agents/alerter/src/capture.js` (service, request-response orchestrator)

**Analog:** `src/agents/alerter/src/heartbeat.js` (factory + start/stop) + `src/mission-control/timelapse/src/index.js` `runComposition()` (lines 28-52, orchestrator with try/catch + status state).

**Factory pattern from `signal.js` lines 5-62:**
```javascript
function createSignalClient({ apiUrl, sender, recipient, ..., logger = console, timeoutMs = 10000 }) {
  // ... closures
  return { send, receive, accounts, sendsThisHour };
}
module.exports = { createSignalClient };
```

**Orchestrator pattern from `timelapse/src/index.js` lines 28-52:**
```javascript
async function runComposition(jobId, { from, to, camera_id }) {
    const job = jobs.get(jobId);
    if (!job) return;
    job.status = 'running';
    try {
        const r = await composeDay(date, camera_id, pool, { fps, timelapseDir });
        if (r.skipped) { job.status = 'failed'; job.error = `skipped: ${r.reason}`; }
        else { job.status = 'done'; job.file_path = r.file_path; }
    } catch (e) {
        job.status = 'failed';
        job.error = e.message;
        console.error('[job] composition failed:', e.message);
    }
}
```

**Apply this:** `capture.js` exports `createCapturePipeline({ pool, signalClient, transcribeClient, llmClient, captureHistory, sensorSnapshot, baseDir, logger })` returning `{ handle(envelope) }`. `handle()` is the `runComposition`-shaped orchestrator: ULID + INSERT + download attachments + transcribe + LLM + reply, with each downstream step in its own try/catch so capture errors never escape (D-03).

**Error-isolation pattern (CRITICAL — D-03):** mirror `receive-loop.js` lines 36-65 outer try/catch:
```javascript
async function tick() {
    try { /* ... */ } catch (e) {
      // Pitfall 4: never die silently — log and continue
      logger.warn(`[receive] loop tick error: ${e.message}`);
    }
}
```

---

### `src/agents/alerter/src/capture-retention.js` (service, batch / cron)

**Analog:** `src/mission-control/timelapse/src/index.js` lines 70-86 (verbatim cron pattern).

**Cron pattern (verbatim copy target):**
```javascript
const cron = require('node-cron');

cron.schedule(config.cronSchedule, async () => {
    const date = previousDayInTz(config.timezone);
    console.log(`[cron] firing for ${date}`);
    try {
        const r = await composeDay(date, config.cameraId, pool, { fps, timelapseDir });
        healthState.last_nightly_at = new Date().toISOString();
        healthState.last_nightly_status = r.skipped ? `skipped: ${r.reason}` : 'ok';
    } catch (e) {
        healthState.last_nightly_at = new Date().toISOString();
        healthState.last_nightly_status = `failed: ${e.message}`;
        console.error('[cron] nightly composition failed:', e.message);
    }
}, { timezone: config.timezone });
```

**Apply this:** schedule once-daily; UPDATE `signal_capture SET expired=true WHERE captured_at < now() - interval '30 days' AND expired=false`. Soft flag only (D-06) — never DELETE rows or files.

---

### `src/agents/alerter/src/transcribe-client.js` (service, HTTP client)

**Analog:** `src/agents/alerter/src/signal.js` lines 13-41 (`send()`).

**Fetch + AbortController + timeout pattern (verbatim copy target):**
```javascript
async function send(body, { bypassCap = false } = {}) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      const res = await fetch(`${apiUrl}/v2/send`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: body, ... }),
        signal: ctrl.signal,
      });
      if (!res.ok) {
        const text = await res.text().catch(() => '');
        throw new Error(`signal-cli ${res.status}: ${text.slice(0, 200)}`);
      }
      const json = await res.json().catch(() => ({}));
      return { ok: true, ... };
    } finally {
      clearTimeout(timer);
    }
}
```

**Apply this:** factory `createTranscribeClient({ apiUrl, timeoutMs, logger })` exposing `transcribe(audio_path) → { ok, text, duration_ms, language } | { ok: false, reason }`. POST `/transcribe` with `{ audio_path }`, default timeout ~200000ms (3min SPEC budget). Return `{ ok: false }` on any error (caller composes degraded reply per R6).

---

### `src/agents/alerter/src/llm-client.js` (service, SDK wrapper)

**Analog:** `src/agents/alerter/src/signal.js` (factory shape) + RESEARCH.md Pattern 2 (Anthropic SDK).

**Factory + try/catch + degraded return pattern (RESEARCH-cited, mirroring signal.js shape):**
```javascript
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
          messages: [{ role: 'user', content: buildUserBlock(history, sensorSnapshot, currentMessage) }],
        });
        return { ok: true, text: msg.content[0].text };
      } catch (e) {
        logger.warn(`[llm] degraded: ${e.message}`);
        return { ok: false, reason: e.message };
      }
    },
  };
}

module.exports = { createLlmClient };
```

**Why this shape:** matches existing `createSignalClient` export idiom (every alerter service module is a factory) — keeps `index.js` wiring uniform.

---

### `src/agents/alerter/src/capture-history.js` (model, SELECT)

**Analog:** `src/mission-control/timelapse/src/db.js` `fetchRhForDay()` lines 40-49.

**Time-range SELECT pattern (verbatim copy target):**
```javascript
async function fetchRhForDay(pool, date) {
    const result = await pool.query(
        `SELECT time AS captured_at, value FROM telemetry
         WHERE topic = 'fc.humidity'
           AND time >= $1 AND time < $2
         ORDER BY time ASC`,
        [`${date}T00:00:00Z`, `${date}T23:59:59.999Z`]
    );
    return result.rows;
}
```

**Apply this:** `selectRecentBySender(pool, sender, sinceMs)` → SELECT raw_text, transcript, captured_at FROM signal_capture WHERE sender=$1 AND captured_at > $2 ORDER BY captured_at ASC. Use the index `idx_signal_capture_sender_time` declared in capture-db.js.

---

### `src/agents/alerter/src/signal.js` (modifications — service, request-response)

**Analog:** itself (extend in place).

**Current `receive()` lines 43-48 — flip default to NOT ignore attachments:**
```javascript
async function receive({ timeoutSec = 1 } = {}) {
    const url = `${apiUrl}/v1/receive/${encodeURIComponent(sender)}?timeout=${timeoutSec}&ignore_attachments=true`;
    // ...
}
```

**Required change:** parameterize `ignoreAttachments` (default `false`) and add a sibling `fetchAttachment(id)` method that GETs `/v1/attachments/{id}` and returns the binary stream / buffer. Pattern for the new method follows the same `fetch + !res.ok throw` shape as `accounts()` (lines 50-54):
```javascript
async function accounts() {
    const res = await fetch(`${apiUrl}/v1/accounts`);
    if (!res.ok) throw new Error(`signal-cli accounts ${res.status}`);
    return await res.json();
}
```

---

### `src/agents/alerter/src/receive-loop.js` (modifications — controller, event-driven)

**Analog:** itself + RESEARCH.md "Receive-loop fan-out" example.

**Current dispatch logic lines 36-65** — current flow: parseSnooze → if ok dispatch, if not ok send help text. Required new flow per RESEARCH:

```javascript
// FAST PATH: snooze keyword (≤30s ack budget — Pitfall 6)
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
```

**Critical:** `capturePipeline.handle(...)` is **NOT awaited**. Use `.catch(log)` to keep tick non-blocking (Pitfall 6).

---

### `src/agents/alerter/src/snooze.js` (modifications — utility, transform)

**Analog:** itself + RESEARCH.md "Snooze grammar extension".

**Current grammar lines 14-15:**
```javascript
const STRICT = /^snooze\s+(rh|sensor|pi|humidifier|sht30|scd41|all)\s+(30m|1h|2h|4h|8h|24h)\s*$/i;
```

**Add parallel simple grammar (RESEARCH-cited):**
```javascript
const SIMPLE = /^\s*(snooze|mute|quiet)\b\s*$/i;

function parseSnoozeCommand(text, nowMs) {
  if (typeof text !== 'string') return fuzzyReply();
  const t = text.trim();

  if (SIMPLE.test(t)) {
    return {
      ok: true, alertType: 'all',
      durationMs: VALID_DURATIONS['24h'],
      untilMs: nowMs + VALID_DURATIONS['24h'],
      ackText: 'alerts muted for 24h',
    };
  }
  // existing STRICT path unchanged
}
```

**Behavior change:** non-snooze text no longer returns help text — capture pipeline owns that surface now. `fuzzyReply()` only fires when text starts with `snooze` but is malformed (planner can decide exact heuristic).

---

### `src/agents/alerter/src/config.js` (modifications — config)

**Analog:** itself + `src/mission-control/timelapse/src/config.js` (TIMESCALE_PASSWORD fail-fast pattern).

**Existing pattern lines 3-6 (verbatim — no change):**
```javascript
function mustEnv(env, key) {
  const v = env[key];
  if (!v) throw new Error(`[config] Required env var ${key} is missing`);
  return v;
}
```

**New env vars to add to `load()` body (lines 23-46):**
```javascript
// Phase 25 capture pipeline
timescaleHost:        env.TIMESCALE_HOST     || 'host.docker.internal',
timescaleDb:          env.TIMESCALE_DB       || 'postgres',
timescaleUser:        env.TIMESCALE_USER     || 'postgres',
timescalePassword:    mustEnv(env, 'TIMESCALE_PASSWORD'),
whisperUrl:           env.WHISPER_URL        || 'http://host.docker.internal:8090',
anthropicApiKey:      mustEnv(env, 'ANTHROPIC_API_KEY'),
captureBaseDir:       env.CAPTURE_BASE_PATH  || '/data/signal-capture',
bridgeHttpUrl:        env.BRIDGE_HTTP_URL    || 'http://host.docker.internal:8081',
captureRetentionDays: parseIntEnv(env, 'CAPTURE_RETENTION_DAYS', 30),
captureRetentionCron: env.CAPTURE_RETENTION_CRON || '15 3 * * *',  // 03:15 daily
```

**Reuse `maskNumber()`** (lines 52-55) for sender logging — already correct, no change.

---

### `src/agents/alerter/src/index.js` (modifications — bootstrap)

**Analog:** itself + `src/mission-control/timelapse/src/index.js` lines 17-23 (Pool construction) + lines 63-91 (main wiring).

**Add Pool construction immediately after `load(env)` at line 29:**
```javascript
const { Pool } = require('pg');
const pool = new Pool({
  host: config.timescaleHost,
  database: config.timescaleDb,
  user: config.timescaleUser,
  password: config.timescalePassword,
  port: 5432,
});
```

**Wire new modules between existing `signalClient` (line 34) and `bridge` (line 63):**
```javascript
const captureDb = require('./capture-db');
await captureDb.initDb(pool);  // bootstrap signal_capture table

const transcribeClient = createTranscribeClient({ apiUrl: config.whisperUrl, logger, timeoutMs: 200000 });
const llmClient        = createLlmClient({ apiKey: config.anthropicApiKey, logger });
const captureHistory   = createCaptureHistory({ pool });
const fetchSensorSnapshot = makeSensorSnapshotFetcher(config.bridgeHttpUrl);

const capturePipeline = createCapturePipeline({
  pool, signalClient, transcribeClient, llmClient, captureHistory,
  sensorSnapshot: fetchSensorSnapshot,
  baseDir: config.captureBaseDir,
  logger,
});

const retentionJob = createRetentionJob({ pool, config, logger });
retentionJob.start();
```

**Caveat:** `createAlerter` is currently sync (line 28). Either flip to `async` (preferred, matches timelapse `main()`) or move `await captureDb.initDb(pool)` into a fire-and-forget startup IIFE with proper error handling. Planner picks.

**Pass `capturePipeline` into `createReceiveLoop`** so receive-loop can fan out (extend `receive-loop.js` factory signature).

---

### `src/whisper-transcribe/Dockerfile` (config, container build)

**Analog:** `src/agents/alerter/Dockerfile` (structure) + `src/mission-control/timelapse/Dockerfile` (apk install pattern); RESEARCH.md gives the CUDA base.

**Structural pattern (alerter Dockerfile lines 1-7 — copy ordering, ENV, CMD):**
```dockerfile
FROM node:20-alpine
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci --omit=dev || npm install --omit=dev
COPY src/ ./src/
ENV NODE_ENV=production
CMD ["node", "src/index.js"]
```

**Apply with CUDA base + Python (verbatim from RESEARCH.md):**
```dockerfile
FROM nvidia/cuda:12.3.2-cudnn9-runtime-ubuntu22.04
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip ffmpeg curl \
 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt
COPY main.py .
ENV PYTHONUNBUFFERED=1 WHISPER_MODEL=medium WHISPER_DEVICE=cuda WHISPER_COMPUTE_TYPE=float16
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8090"]
```

---

### `src/whisper-transcribe/main.py` (controller, FastAPI)

**Analog:** none in repo (no existing Python services). Use **RESEARCH.md Pattern 3 verbatim** (lines 274-313 of RESEARCH.md): lazy-loaded `WhisperModel` singleton, `POST /transcribe` and `GET /health` endpoints. No additional pattern extraction needed — RESEARCH.md is canonical.

---

### `src/agents/alerter/test/capture.test.js` + `transcribe-client.test.js` + `llm-client.test.js` (test)

**Analog:** `src/agents/alerter/test/receive-loop.test.js` + `src/agents/alerter/test/helpers/fake-signal-server.js`.

**Fake-server harness pattern (helpers/fake-signal-server.js verbatim):**
```javascript
const http = require('http');
function start({ port = 0 } = {}) {
  return new Promise((resolve, reject) => {
    const sent = [];
    const received = [];
    const handle = { sent, received, statusOverride: null, delayMs: 0 };
    const server = http.createServer((req, res) => {
      // pattern: parse URL, dispatch on method+path, push to arrays, return 200/201
    });
    server.listen(port, '127.0.0.1', () => {
      handle.url = `http://127.0.0.1:${server.address().port}`;
      handle.close = () => new Promise((res) => server.close(res));
      resolve(handle);
    });
  });
}
```

**Test driver pattern (receive-loop.test.js lines 31-71):**
```javascript
describe('createReceiveLoop', () => {
  let server, loop;
  beforeEach(async () => { server = await fakeSignalServer.start(); });
  afterEach(async () => { if (loop) loop.stop(); await server.close(); });

  test('Test A: ...', async () => {
    server.received.push({ envelope: { source: '+1111111111', dataMessage: { message: '...' } } });
    // build subject under test, exercise, assert on server.sent[] / dispatched[]
  });
});
```

**Apply this:**
- `transcribe-client.test.js` — start a tiny fake whisper server (HTTP POST /transcribe returns canned JSON; can override status/delay like fake-signal-server). Cover: success, timeout (server delay > timeoutMs), 5xx error → `{ ok: false }`.
- `llm-client.test.js` — mock `@anthropic-ai/sdk` via `jest.mock('@anthropic-ai/sdk', ...)`. Cover: success returns `{ ok: true, text }`; thrown error returns `{ ok: false, reason }`; prompt assembly receives expected history + sensorSnapshot + currentMessage shape (assert via the mock's call args).
- `capture.test.js` — mock pool (`{ query: jest.fn() }`), inject fake transcribeClient/llmClient/signalClient, assert: row insertion call args (R2), attachment file written under tmp baseDir (R2), reply sent (R5), R6 degraded path when transcribeClient returns `{ ok: false }`.

**Snooze test extensions** — add to `test/snooze.test.js` (verbatim test shape from lines 6-12):
```javascript
test('mute keyword → all/24h', () => {
  const r = parseSnoozeCommand('mute', 1000);
  expect(r.ok).toBe(true);
  expect(r.alertType).toBe('all');
  expect(r.durationMs).toBe(VALID_DURATIONS['24h']);
});
// repeat for 'snooze' and 'quiet' alone, case-insensitive variants
```

---

### Compose service additions (config, deployment)

**Analog:** `docker-compose.yml` `timelapse` service (lines 66-84) and `bridge` service (lines 7-32); `docker-compose.override.yml` `signal-cli` + `alerter` blocks.

**Critical compose pattern from override.yml lines 21-22 (host network):**
```yaml
timelapse:
  network_mode: "host"
```

**MODE flip in override.yml line 32 (REQUIRED — Pitfall 1):**
```yaml
signal-cli:
  environment:
    - MODE=normal     # was: MODE=json-rpc
```

**Whisper service skeleton (verbatim from RESEARCH.md Pattern 4):**
```yaml
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
    - /data/signal-capture:/data/signal-capture:ro
  healthcheck:
    test: ["CMD", "curl", "-fsS", "http://localhost:8090/health"]
    interval: 30s
    timeout: 5s
    retries: 3
    start_period: 10s
```

**Override addition (host net so alerter reaches it at `localhost:8090`):**
```yaml
whisper-transcribe:
  network_mode: "host"
```

**Alerter env additions in override.yml (around line 50-68):**
```yaml
- TIMESCALE_HOST=host.docker.internal
- TIMESCALE_PASSWORD=${TIMESCALE_PASSWORD}
- ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
- WHISPER_URL=http://host.docker.internal:8090
- CAPTURE_BASE_PATH=/data/signal-capture
volumes:
  - /data/signal-capture:/data/signal-capture
```

---

## Shared Patterns

### Factory + closure + named export

**Source:** every module under `src/agents/alerter/src/` (signal.js, receive-loop.js, heartbeat.js, bridge-client.js)
**Apply to:** `capture.js`, `transcribe-client.js`, `llm-client.js`, `capture-history.js`, `capture-retention.js`

```javascript
function createXxx({ depA, depB, logger = console, ...opts }) {
  // private state via closure
  return { method1, method2 };
}
module.exports = { createXxx };
```

### Error isolation — never crash the loop

**Source:** `src/agents/alerter/src/receive-loop.js` lines 36-65 (Pitfall 4 explicitly documented)
**Apply to:** `capture.js`, `transcribe-client.js`, `llm-client.js` — every external-call boundary

```javascript
try {
  // ... external call (DB, HTTP, SDK)
} catch (e) {
  logger.warn(`[<module>] error: ${e.message}`);
  // return degraded result, never throw upward into receive-loop
}
```

### Phone number masking in logs (security V7)

**Source:** `src/agents/alerter/src/config.js` lines 52-55 — `maskNumber()`
**Apply to:** every log line in `capture.js` that mentions `source` / `sender`

```javascript
const { maskNumber } = require('./config');
logger.info(`[capture] ${maskNumber(source)} ...`);
```

### Pg Pool — host network → localhost; bridge network → host.docker.internal

**Source:** `src/mission-control/timelapse/src/index.js` lines 17-23 (host net example) + `docker-compose.override.yml` line 49 `host.docker.internal:host-gateway` (bridge net example)
**Apply to:** alerter's new Pool construction in `index.js`

Per RESEARCH Open Question #2: alerter stays on `signal-net` bridge → use `TIMESCALE_HOST=host.docker.internal`.

```javascript
const pool = new Pool({
  host: config.timescaleHost,        // 'host.docker.internal' for alerter
  database: config.timescaleDb,
  user: config.timescaleUser,
  password: config.timescalePassword,
  port: 5432,
});
```

### Parameterized SQL (security V5)

**Source:** `src/mission-control/timelapse/src/db.js` lines 18-25 — `pool.query(sql, [params])`
**Apply to:** every query in `capture-db.js`, `capture-history.js`, `capture-retention.js`. Never string-concat a sender or text into SQL.

### Fail-fast on required env

**Source:** `src/agents/alerter/src/config.js` `mustEnv()` (lines 3-7) + `src/mission-control/timelapse/src/config.js` lines 2-5 (early `process.exit(1)`)
**Apply to:** `ANTHROPIC_API_KEY`, `TIMESCALE_PASSWORD` (both `mustEnv` in alerter config.js).

### Cron in-process (no separate container)

**Source:** `src/mission-control/timelapse/src/index.js` lines 70-86
**Apply to:** `capture-retention.js` daily expired-flag job (D-06 + RESEARCH Open Q #4 recommendation).

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `src/whisper-transcribe/main.py` | controller (FastAPI) | request-response | First Python service in repo. Use RESEARCH.md Pattern 3 verbatim. |
| `src/whisper-transcribe/requirements.txt` | config | static | First Python pin file in repo. RESEARCH.md install block is canonical. |
| `src/whisper-transcribe/test/test_smoke.py` | test | integration (GPU) | First pytest in repo. Use standard pytest + `@pytest.mark.gpu` marker (RESEARCH-cited in Wave-0 gaps). |
| `src/whisper-transcribe/Dockerfile` | config (CUDA base) | container build | Closest in-repo Dockerfile is alerter's (node:20-alpine), structurally similar but base image differs. Use RESEARCH.md CUDA Dockerfile. |

For these four files, planner should cite **RESEARCH.md Pattern 3 + Pattern 4** as the source of truth instead of an in-repo analog.

## Metadata

**Analog search scope:** `src/agents/alerter/`, `src/mission-control/bridge/src/`, `src/mission-control/timelapse/src/`, repo-root `docker-compose*.yml`
**Files scanned:** 18 source files + 3 compose files + 4 test fixtures dirs
**Pattern extraction date:** 2026-04-27

---

## PATTERN MAPPING COMPLETE

**Phase:** 25 - Bidirectional Signal — farmer↔robot capture channel
**Files classified:** 18 (10 new alerter modules/tests, 4 new whisper-transcribe files, 4 modifications)
**Analogs found:** 14 / 18 (4 Python whisper files have no in-repo analog — RESEARCH.md is canonical)

### Coverage
- Files with exact analog: 11
- Files with role-match analog: 3
- Files with no in-repo analog: 4 (all Python in `src/whisper-transcribe/`)

### Key Patterns Identified
- **Factory + closure + named export** is the universal alerter module shape — every new Node module must follow it
- **Pure DB module + injected pool** (timelapse/src/db.js) is the canonical Timescale access pattern; reuse for `capture-db.js` and `capture-history.js`
- **Error isolation at every external boundary** — `try/catch` + `logger.warn` + degraded return value, never throw upward (Pitfall 4 + D-03)
- **Fast-path-before-slow-path in receive-loop** — snooze must dispatch and `continue` BEFORE capture fan-out (Pitfall 6)
- **Capture is fire-and-forget**, not awaited, so a single bad envelope cannot block the next tick or starve the snooze ack budget
- **Compose: alerter stays on bridge network**, whisper goes host network; both reach Timescale via `host.docker.internal` and `localhost` respectively (RESEARCH Open Q #2)
- **MODE=normal flip in override.yml is load-bearing** (Pitfall 1) — receive-loop will still 400 even after primary re-registration unless this changes

### File Created
`/mnt/slime-kingdom/opt/mushy/.planning/phases/25-bidirectional-signal-farmer-robot-capture-channel/25-PATTERNS.md`

### Ready for Planning
Pattern mapping complete. Planner can now reference analog file paths + line numbers in PLAN.md actions.
