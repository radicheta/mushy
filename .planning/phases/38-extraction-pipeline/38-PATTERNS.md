# Phase 38: Extraction Pipeline — Pattern Map

**Mapped:** 2026-05-12
**Files analyzed:** 24 new + 6 modified = 30
**Analogs found:** 28 / 30 (2 with no direct analog → propose)

All new code lives in `src/agents/alerter/` (extends the alerter agent in-process per CONTEXT D-02 / D-05 / D-06). CommonJS, `'use strict'`, factory functions returning `{ method, method }`. Logger via injected `logger = console`. Pool injection only — no module-local DB connections. Never-throw discipline on outbound IO (return `{ ok, reason }`).

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match |
|---|---|---|---|---|
| `src/extraction/extractor.js` | entry point | request-response (LLM call) | `src/llm-client.js` | exact |
| `src/extraction/state-machine.js` | state machine | event-driven | `src/snooze.js` (parse+transition) + `src/capture.js` (status field) | role-match |
| `src/extraction/schemas/index.js` | schema (Zod) | transform | none — propose | none |
| `src/extraction/schemas/{seeding,activity,input,observation,harvest}.js` | schema | transform | none — propose | none |
| `src/extraction/validator.js` | validator | transform | none — propose; mirror `llm-client.compose` `{ok,reason}` shape | partial |
| `src/extraction/multimodal.js` | utility | file-I/O + transform | `src/capture.js` (attachment download + path handling) | partial |
| `src/extraction/extraction-db.js` | DB module | CRUD | `src/capture-db.js` | exact |
| `src/extraction/prompts/system.js` | config (constants) | n/a | `src/llm-client.js` `SYSTEM_PROMPT` | exact |
| `src/extraction/index.js` | module wiring | n/a | none — small barrel | propose |
| `test/extraction/schemas.test.js` | test | n/a | `test/config.test.js` (pure-unit jest) | role-match |
| `test/extraction/extractor.test.js` | test | n/a | `test/llm-client.test.js` (mocks `@anthropic-ai/sdk`) | exact |
| `test/extraction/state-machine.test.js` | test | n/a | `test/snooze.test.js` | role-match |
| `test/extraction/multimodal.test.js` | test | n/a | `test/llm-client.test.js` | role-match |
| `test/extraction/sanitize.test.js` | test | n/a | `test/message.test.js` (fmtNum / em-dash sweep) | role-match |
| `test/extraction/extraction-db.test.js` | test | n/a | `test/capture-db.test.js` | exact |
| `test/extraction/validator.test.js` | test | n/a | `test/llm-client.test.js` | role-match |
| `test/extraction/helpers/fake-anthropic-server.js` | test helper | n/a | `test/helpers/fake-whisper-server.js` | exact |
| `test/eval/extraction/jest.config.js` | config | n/a | none — propose (separate jest project) | propose |
| `test/eval/extraction/mushdatadump.test.js` | eval | batch | `test/transcribe-client.test.js` (fixture-loop pattern) | partial |
| `test/eval/extraction/scoring.js` | utility | transform | none — propose | propose |
| `test/eval/extraction/report.js` | utility | file-I/O | none — propose | propose |
| **MOD** `src/capture-db.js` | DB module | CRUD | self | self |
| **MOD** `src/config.js` | config | n/a | self | self |
| **MOD** `src/receive-loop.js` | controller | event-driven | self | self |
| **MOD** `src/message.js` | utility | transform | self | self |
| **MOD** `src/index.js` | entry point | wiring | self | self |
| **MOD** `package.json` | config | n/a | self | self |

---

## Pattern Assignments — NEW Files

### `src/extraction/extractor.js` (entry point, request-response)

**Analog:** `src/agents/alerter/src/llm-client.js` (80 lines)

**Module header pattern (lines 1-8):**
```javascript
'use strict';

// Phase 25 R5: Anthropic LLM client for the farmer capture-channel reply.
// Locked: model=claude-sonnet-4-6, max_tokens=150, system prompt + user-block shape.
// Never throws — SDK errors are caught and surfaced as { ok:false, reason }.
// V2: ANTHROPIC_API_KEY only crosses into `new Anthropic({ apiKey })`; never logged.

const Anthropic = require('@anthropic-ai/sdk');
```

**Factory + never-throw envelope (lines 53-75):**
```javascript
function createLlmClient({ apiKey, logger = console, model = 'claude-sonnet-4-6', maxTokens = 150 }) {
  const client = new Anthropic({ apiKey, maxRetries: 2 });
  return {
    async compose({ history, sensorSnapshot, currentMessage }) {
      try {
        const msg = await client.messages.create({
          model,
          max_tokens: maxTokens,
          system: SYSTEM_PROMPT,
          messages: [
            { role: 'user', content: buildUserBlock({ history, sensorSnapshot, currentMessage }) },
          ],
        });
        const text = (msg.content?.[0]?.text || '').trim();
        if (!text) return { ok: false, reason: 'empty response' };
        return { ok: true, text };
      } catch (e) {
        logger.warn(`[llm] degraded: ${e.message}`);
        return { ok: false, reason: e.message };
      }
    },
  };
}

module.exports = {
  createLlmClient,
  _internal: { SYSTEM_PROMPT, buildUserBlock, fmtHistory, fmtSnapshot, MAX_HISTORY_ROWS },
};
```

**Copy:** Factory signature, try/catch+`{ok,reason}` envelope, `_internal` export of helpers for test introspection, `logger.warn('[component] degraded: ...')` tag. New extractor adds `tool_use` block to the request and returns `{ ok, draft, per_field_confidence, continuity_decision }` on success.

---

### `src/extraction/state-machine.js` (state machine, event-driven)

**Analog A:** `src/agents/alerter/src/snooze.js` (63 lines — parse + transition)
**Analog B:** `src/agents/alerter/src/capture.js` (status orchestration; lines 60-185)

**Parse-then-transition return shape (snooze.js lines 35-61):**
```javascript
function parseSnoozeCommand(text, nowMs) {
  if (typeof text !== 'string') return { ok: false, reply: null };
  const t = text.trim();
  if (SIMPLE.test(t)) {
    const durationMs = VALID_DURATIONS['24h'];
    return { ok: true, alertType: 'all', durationMs, untilMs: nowMs + durationMs, ackText: 'alerts muted for 24h' };
  }
  const m = t.match(STRICT);
  if (m) {
    const alertType = m[1].toLowerCase();
    const durationMs = VALID_DURATIONS[m[2].toLowerCase()];
    return { ok: true, alertType, durationMs, untilMs: nowMs + durationMs };
  }
  if (/^snooze\b/i.test(t)) return fuzzyReply();
  return { ok: false, reply: null };
}

module.exports = { parseSnoozeCommand, VALID_ALERT_TYPES, VALID_DURATIONS };
```

**Copy:** Discriminated-result return `{ok:true, ...}` | `{ok:false, reply}`. Pure, no side effects. Top-of-file `const VALID_*` whitelists. Export ENUM-like constants alongside the function for downstream consumers.

**Transitions reference (capture.js status-bearing branches):** Steps 1-7 in `capture.js` (lines 89-184) show the durable-before-LLM ordering — `INSERT` row first (line 117), then attempt LLM (line 142), then `UPDATE` with result (line 175). New extractor `state-machine.js` mirrors this: insert `signal_draft` row in `pending` BEFORE LLM extract; transition to `awaiting_farmer` / `needs_review` / `expired` only on completion.

**Status enum constants (CONTEXT D-02b):**
```javascript
const DRAFT_STATUS = Object.freeze({
  PENDING: 'pending',
  AWAITING_FARMER: 'awaiting_farmer',
  NEEDS_REVIEW: 'needs_review',
  EXPIRED: 'expired',
  // Phase 39: confirmed | discarded
  // Phase 40: committed
});
```

---

### `src/extraction/schemas/index.js` + per-type files (schema, transform)

**Analog:** None in alerter — first Zod use. **Propose new pattern.**

Match the prevailing `module.exports = { name1, name2 }` style. One file per B7 log type returning a Zod schema:

```javascript
'use strict';
const { z } = require('zod');

const SeedingLog = z.object({
  type: z.literal('seeding'),
  species: z.string(),
  block_name: z.string().regex(/^\d{6}_[A-Z]{3}_\d+$/),  // B5: {YYMMDD}_{SPECIES3}_{SEQ}
  qty: z.number().int().positive(),
  event_timestamp: z.string().datetime(),
  notes: z.string().optional(),
  confidence: z.record(z.string(), z.number().min(0).max(1)),  // per-field
});

module.exports = { SeedingLog };
```

`schemas/index.js` builds a discriminated union and the Anthropic `input_schema` via `zod-to-json-schema` (RESEARCH §Pattern 1). Reuse the `Object.freeze` constant style from `config.js:51` for the union descriptor.

---

### `src/extraction/validator.js` (validator, transform)

**Analog:** No direct precedent. Closest shape: the `{ok, reason}` envelope from `llm-client.js`.

**Propose:** `validate(rawToolInput, schema) → { ok:true, draft } | { ok:false, errors:[...] }`. The retry-envelope variant (`validateWithRetry`) does up to 2 `safeParse` retries appending an Anthropic `tool_result` error block per RESEARCH §"Anthropic Multi-Turn with `tool_result` for Schema-Validation Retry" (lines 427-460 of RESEARCH.md).

---

### `src/extraction/multimodal.js` (utility, file-I/O + transform)

**Analog:** `src/agents/alerter/src/capture.js` lines 89-102 (attachment fetch + sanitized path build).

**Attachment-path pattern to mirror (lines 38-44):**
```javascript
function buildPath(baseDir, capturedAtMs, id, ext) {
  const d = new Date(capturedAtMs);
  const day = d.toISOString().slice(0, 10);
  const time = d.toISOString().slice(11, 19).replace(/:/g, '-');
  // V12 file/resource: never trust client filename — derive from server-controlled ULID + sanitized ext only
  return path.join(baseDir, day, `${time}-${id}.${ext.replace(/[^a-z0-9]/gi, '')}`);
}
```

**Copy:** Server-controlled IDs only, sanitized ext, `fs/promises`. New module reads paths off `signal_capture.attachment_paths[]` (already populated by capture pipeline), downscales JPEG to ≤1.15MP per RESEARCH Pitfall 3, base64-encodes, returns Anthropic image content blocks.

---

### `src/extraction/extraction-db.js` (DB module, CRUD)

**Analog:** `src/agents/alerter/src/capture-db.js` (70 lines — exact pattern to clone)

**Idempotent migration block (capture-db.js lines 5-35):**
```javascript
async function initDb(pool) {
  await pool.query(`
    CREATE TABLE IF NOT EXISTS signal_capture (
      id              text PRIMARY KEY,
      captured_at     timestamptz NOT NULL DEFAULT now(),
      sender          text NOT NULL,
      ...
    )
  `);
  await pool.query(`
    CREATE INDEX IF NOT EXISTS idx_signal_capture_sender_time
    ON signal_capture (sender, captured_at DESC)
  `);
  // Phase 37 D-14/D-15: three nullable columns added idempotently.
  await pool.query(`ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS group_id text`);
  await pool.query(`ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS farmos_person text`);
  await pool.query(`ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS reply_target_kind text`);
}
```

**Insert pattern (lines 37-58):**
```javascript
async function insertCapture(pool, row) {
  await pool.query(
    `INSERT INTO signal_capture
       (id, captured_at, sender, message_type, raw_text, ...)
     VALUES ($1, $2, $3, $4, $5, ...)`,
    [row.id, row.captured_at, row.sender, row.message_type, row.raw_text ?? null, ...]
  );
}

module.exports = { initDb, insertCapture, markExpiredOlderThan };
```

**Copy literally** for `signal_draft`. Mirror `pool.query` injection, `CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`, parameterized `VALUES ($N)`, and `ADD COLUMN IF NOT EXISTS` for any future columns. CONTEXT D-02c demands a partial unique index — express it as:
```javascript
await pool.query(`
  CREATE UNIQUE INDEX IF NOT EXISTS idx_signal_draft_in_flight_per_sender
  ON signal_draft (sender) WHERE status IN ('pending','awaiting_farmer')
`);
```

`signal_draft` columns per CONTEXT D-02 / D-02a / D-02b: `id text PRIMARY KEY` (sha256 of sorted source capture ids), `created_at timestamptz`, `sender text`, `farmos_person text`, `source_capture_ids text[]`, `status text`, `draft_json jsonb`, `farmer_facing_preview text`, `askback_turns int DEFAULT 0`, `last_updated_at timestamptz`, `reply_target_kind text`, `group_id text`.

**Export set:** `{ initDb, insertDraft, updateDraft, markExpired, findInFlightBySender, getById }`.

---

### `src/extraction/prompts/system.js` (config constants)

**Analog:** `src/llm-client.js` lines 10-18:
```javascript
const SYSTEM_PROMPT = [
  'You are mushy, a farm assistant for a single farmer.',
  '...',
].join('\n');
```
**Copy:** Multi-line `[...].join('\n')` style. Export as named const plus a `FEW_SHOT` array of `{role, content}` for prompt-cache slots (RESEARCH §Pattern: Prompt Caching for System + Few-Shot, lines 477-495).

---

### `test/extraction/extractor.test.js` (test)

**Analog:** `test/llm-client.test.js` (164 lines — exact match)

**Anthropic-SDK mock pattern (lines 8-13):**
```javascript
const mockCreate = jest.fn();
jest.mock('@anthropic-ai/sdk', () => {
  return jest.fn().mockImplementation(() => ({
    messages: { create: mockCreate },
  }));
});

const { createLlmClient, _internal } = require('../src/llm-client');
const silentLogger = { warn: () => {}, info: () => {}, error: () => {} };
```

**Per-test arrange (lines 32-66):**
```javascript
beforeEach(() => {
  mockCreate.mockReset();
  client = createLlmClient({ apiKey: 'sk-test-key', logger: silentLogger });
});

test('(R5) success — SDK returns text → compose() returns { ok: true, text }', async () => {
  mockCreate.mockResolvedValueOnce({
    content: [{ type: 'text', text: 'logged inoc-2026-04-27' }],
  });
  const result = await client.compose({ ... });
  expect(result).toEqual({ ok: true, text: 'logged inoc-2026-04-27' });
});

test('(R6) SDK throws → compose() returns { ok: false, reason } without throwing', async () => {
  mockCreate.mockRejectedValueOnce(new Error('rate limit'));
  // assert no throw + { ok:false, reason } shape
});
```

**Copy:** `jest.mock('@anthropic-ai/sdk', ...)` factory, `mockCreate.mockResolvedValueOnce({ content: [...] })` for tool_use blocks, never-throw assertion (`try { } catch { threw = true }`), API-key-never-leaks test (lines 136-150 of llm-client.test.js).

For tool_use: mock returns `content: [{ type: 'tool_use', name: 'emit_draft', input: {...} }]`.

---

### `test/extraction/extraction-db.test.js` (test)

**Analog:** `test/capture-db.test.js` (exact)

**Pool-stub + per-call assertions:**
```javascript
beforeEach(() => {
  pool = { query: jest.fn().mockResolvedValue({ rows: [], rowCount: 0 }) };
});

test('initDb issues CREATE TABLE + 2 CREATE INDEX + 3 ALTER TABLE ADD COLUMN IF NOT EXISTS', async () => {
  await initDb(pool);
  expect(pool.query).toHaveBeenCalledTimes(6);
  const sql0 = pool.query.mock.calls[0][0];
  expect(sql0).toMatch(/CREATE TABLE IF NOT EXISTS signal_capture/);
  ...
});

test('initDb is idempotent — second invocation also issues 6 queries with same shape', async () => {
  await initDb(pool); await initDb(pool);
  expect(pool.query).toHaveBeenCalledTimes(12);
});
```

**Copy:** Pool-jest-fn stub, `mock.calls[N][0]` SQL substring assertions, idempotency-on-second-call test, parameter-array assertions (`expect(params).toHaveLength(N); expect(params[0]).toBe(...)`).

---

### `test/extraction/state-machine.test.js`

**Analog:** `test/snooze.test.js` (parse-result shape tests). Pure-unit, no fixtures, no DB.

---

### `test/extraction/sanitize.test.js`

**Analog:** `test/message.test.js`. Assert outputs never contain `—`, all floats pass through `fmtNum`. Sanitizer reuses `fmtNum` from `src/message.js` (memory: `feedback_no_em_dashes_in_artifacts.md`, `feedback_round_farmer_numbers.md`). Excerpt from `message.js` lines 16-19:
```javascript
function fmtNum(n) {
  if (n == null || Number.isNaN(Number(n))) return '?';
  return String(+Number(n).toFixed(1));
}
```

---

### `test/extraction/helpers/fake-anthropic-server.js` (test helper)

**Analog:** `test/helpers/fake-whisper-server.js` (103 lines — exact pattern)

**Factory-with-handle pattern (lines 24-99):**
```javascript
function start({ port = 0 } = {}) {
  return new Promise((resolve, reject) => {
    const requests = [];
    const handle = {
      requests,
      statusOverride: null,
      delayMs: 0,
      transcribeResponse: null,
    };

    const server = http.createServer((req, res) => {
      const url = new URL(req.url, 'http://127.0.0.1');
      const path = url.pathname;

      if (req.method === 'POST' && path === '/transcribe') {
        let body = '';
        req.on('data', (chunk) => { body += chunk; });
        req.on('end', async () => {
          if (handle.delayMs > 0) await sleep(handle.delayMs);
          const statusCode = handle.statusOverride || 200;
          handle.statusOverride = null;
          ...
          requests.push(parsed);
          const responseBody = handle.transcribeResponse || defaultTranscribeResponse;
          res.writeHead(200, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify(responseBody));
        });
        return;
      }
      ...
    });

    server.listen(port, '127.0.0.1', () => {
      const { port: boundPort } = server.address();
      handle.url = `http://127.0.0.1:${boundPort}`;
      handle.close = () => new Promise((res) => server.close(res));
      resolve(handle);
    });
  });
}
module.exports = { start };
```

**Usage in tests (from transcribe-client.test.js lines 22-32):**
```javascript
let server;
beforeEach(async () => {
  server = await fakeWhisperServer.start();
  client = createTranscribeClient({ baseUrl: server.url, timeoutMs: 2000 });
});
afterEach(async () => { await server.close(); });
```

**Copy:** Ephemeral port (`port: 0`), mutable `handle` exposing `requests[]` / `statusOverride` / `delayMs` / `*Response` overrides, `handle.url` populated after listen, async `close()`. Implement `POST /v1/messages` returning canned Anthropic response envelopes including `content: [{type:'tool_use', name:'emit_draft', input:{...}}]` and `stop_reason: 'tool_use'`.

---

### `test/eval/extraction/*.test.js` (eval harness)

**Analogs:**
- `test/eval/extraction/jest.config.js` — no precedent. Propose minimal jest config with `testTimeout: 600000` and `testMatch: ['**/eval/extraction/*.test.js']`. Excluded from default `npm test` by being in a sibling directory (default jest only matches `test/*.test.js`).
- `test/eval/extraction/mushdatadump.test.js` — loop over `EXTRACTION_FIXTURE_DIR` (env), call real extractor with real Anthropic key. Pattern echoes the table-driven shape in `test/llm-client.test.js` lines 87-112 (loop builds inputs, asserts on grouped outputs).
- `test/eval/extraction/scoring.js` + `report.js` — propose. Scoring helpers per RESEARCH §Eval Tooling (Brier, ECE, set-equality). `report.js` writes `38-EVAL-REPORT.md` via `fs.writeFileSync` to phase dir; format mirrors PROBLEM/RECOVERY message templates in `message.js` for tone (rounded numbers, no em-dashes — though this is a dev artifact, keep house style).

---

## Pattern Assignments — MODIFIED Files

### MOD `src/capture-db.js`

**Current `initDb` body** (already shown above; lines 5-35).

**Insertion point:** After line 34 (last `ADD COLUMN IF NOT EXISTS` for `reply_target_kind`), before `}` on line 35. Append:

```javascript
// Phase 38 D-02: signal_draft table — one draft can span multiple captures;
// FK array references signal_capture(id). Deterministic id (sha256 of sorted
// source_capture_ids) per D-02a. Status enum per D-02b.
await pool.query(`
  CREATE TABLE IF NOT EXISTS signal_draft (
    id                    text PRIMARY KEY,
    created_at            timestamptz NOT NULL DEFAULT now(),
    last_updated_at       timestamptz NOT NULL DEFAULT now(),
    sender                text NOT NULL,
    farmos_person         text,
    source_capture_ids    text[] NOT NULL DEFAULT ARRAY[]::text[],
    status                text NOT NULL,
    draft_json            jsonb NOT NULL,
    farmer_facing_preview text,
    askback_turns         integer NOT NULL DEFAULT 0,
    reply_target_kind     text,
    group_id              text
  )
`);
await pool.query(`
  CREATE INDEX IF NOT EXISTS idx_signal_draft_sender_status
  ON signal_draft (sender, status)
`);
// D-02c: at most one in-flight draft per sender.
await pool.query(`
  CREATE UNIQUE INDEX IF NOT EXISTS idx_signal_draft_in_flight_per_sender
  ON signal_draft (sender) WHERE status IN ('pending','awaiting_farmer')
`);
```

**Test impact:** `test/capture-db.test.js:14` asserts `toHaveBeenCalledTimes(6)` and `:33` asserts `12`. Update both to `9` / `18` (3 new queries) when the migration lands.

**Alternative:** Move the `signal_draft` migration into `src/extraction/extraction-db.js:initDraftDb(pool)` and call it from `src/index.js` after `captureDb.initDb(pool)`. This keeps `capture-db.js` untouched. **Recommended** — fewer test cascades and cleaner module boundaries.

---

### MOD `src/config.js`

**Current pattern** (lines 50-100 — env-driven, frozen object, `parseFloatEnv` / `parseIntEnv` helpers).

**Insertion point:** Inside the `Object.freeze({...})` returned by `load(env)`, after `captureRetentionCron` (line 99). Add:

```javascript
// Phase 38: extraction pipeline knobs.
// D-03: per-field confidence ask-back threshold.
extractionConfidenceThreshold: parseFloatEnv(env, 'EXTRACTION_CONFIDENCE_THRESHOLD', 0.7),
// D-01a: idle-gap cap — any new message after this many minutes forces start-new.
draftIdleGapMin: parseIntEnv(env, 'DRAFT_IDLE_GAP_MIN', 30),
// D-05: hard cap on ask-back turns before status -> needs_review.
maxAskbackTurns: parseIntEnv(env, 'MAX_ASKBACK_TURNS', 3),
// D-06: eval-only — fixture root for offline harness. Unused in prod.
extractionFixtureDir: env.EXTRACTION_FIXTURE_DIR || '/mnt/mossrock/shared/mushdatadump',
```

**Test impact:** Add cases to `test/config.test.js` mirroring `Test H/I` (defaults + overrides).

---

### MOD `src/receive-loop.js`

**Current enqueue point** (lines 207-214):
```javascript
// SLOW PATH — capture (D-03 — error-isolated, fire-and-forget; NEVER awaited)
// Phase 37: thread routing context (replyTargetKind, groupId, suppressReply)
// so capture.js can populate row fields + pick reply target.
if (capturePipeline && (text || attachments.length)) {
  capturePipeline.handle(env, captureCtx).catch((e) =>
    logger.warn(`[capture] pipeline error: ${e.message}`),
  );
}
```

**Insertion strategy (RECOMMENDED — async chain inside capture pipeline, not receive-loop):**
The right seam for "after capture row lands and `farmos_person != NULL`, enqueue extraction" is **inside `capture.js`** at the end of step 3 (line 137), NOT here. `capture.js` already has `farmosPerson` resolved and the row inserted. Adding it here would require re-resolving farmer slug + waiting for the insert. **Plan should hook `capture.js`, leaving `receive-loop.js` untouched.**

If the planner still wants a `receive-loop.js` hook (e.g. for direct ask-back-reply DMs that don't flow through capture), the same fire-and-forget pattern applies:
```javascript
if (extractionPipeline && farmosPerson !== '(unassigned)') {
  extractionPipeline.enqueue({ captureId: id, sender: source, ... }).catch((e) =>
    logger.warn(`[extraction] enqueue error: ${e.message}`),
  );
}
```
Mirror the `capturePipeline.handle(...).catch(...)` never-await / never-throw pattern verbatim.

---

### MOD `src/message.js`

**Current sanitizer shape** (already complete — lines 16-19 `fmtNum`).

**No structural change needed.** Extraction reply path imports `fmtNum` from `./message.js` for any numeric rendering, and the eval harness asserts the output contains no `—` characters (zero-tolerance per memory). The new `src/extraction/sanitize.js` (optional thin wrapper) can re-export `fmtNum` + add `sanitizeFarmerText(s)` that strips em-dashes.

---

### MOD `src/index.js`

**Current startup sequence** (lines 36-108):
1. `load(env)` → config
2. `new Pool({...})` → Timescale pool
3. `await captureDb.initDb(pool)` (try/catch — best effort)
4. `createSignalClient`, `createTranscribeClient`, `createLlmClient`, `createCaptureHistory`, `createSensorSnapshotFetcher`
5. `createCapturePipeline({...})`
6. `createRetentionJob` + `.start()`

**Insertion point:** After line 102 (`createCapturePipeline` returns), before `createRetentionJob`. Insert:

```javascript
// Phase 38: extraction pipeline. Reuses pool, llmClient (extended with extract()),
// and signalClient. initExtractionDb is idempotent and best-effort like initDb above.
const extractionDb = require('./extraction/extraction-db');
try {
  await extractionDb.initDb(pool);
  logger.info(`[boot] signal_draft schema initialized`);
} catch (e) {
  logger.warn(`[boot] signal_draft initDb failed (extraction will degrade): ${e.message}`);
}
const { createExtractionPipeline } = require('./extraction');
const extractionPipeline = createExtractionPipeline({
  pool,
  llmClient,            // extended with extract()
  signalClient,
  config,
  logger,
  clock,
});
```

**Copy:** `try/await initDb/.catch + logger.warn` shape (lines 53-58). Pool/logger/clock injection. Factory-returns-handle pattern matches existing `createCapturePipeline` (line 90).

Then thread `extractionPipeline` into `createCapturePipeline` (or `createReceiveLoop`) constructor arg so the capture path can enqueue. Match existing constructor-args shape.

**Close hook:** No new close needed — pipeline has no timers/sockets; pool closes via existing `pool.end()` on line 218.

---

### MOD `package.json`

**Current** (full file shown earlier — `dependencies` + `scripts` minimal).

**Add to `dependencies`:**
```json
"zod": "^3.23.0",
"zod-to-json-schema": "^3.23.0"
```

**Add to `scripts`:**
```json
"eval:extraction": "jest --config test/eval/extraction/jest.config.js --runInBand"
```

`--runInBand` because each fixture hits the live Anthropic API; parallel jest workers would burst rate limits.

---

## Shared Patterns

### Never-throw outbound IO
**Source:** `src/llm-client.js:69-72`, `src/transcribe-client.js:50-55`, `src/capture.js:134-136`
**Apply to:** `extractor.js`, `validator.js`, `extraction-db.js` insert/update functions, `multimodal.js` (image-read failures)
```javascript
try {
  // outbound call
  return { ok: true, ... };
} catch (e) {
  logger.warn(`[component] degraded: ${e.message}`);
  return { ok: false, reason: e.message };
}
```

### Pool injection
**Source:** `src/capture-db.js`, `src/capture-history.js`, `src/index.js:43-49`
**Apply to:** `extraction-db.js` — accept `pool` as constructor arg or function parameter; never construct one internally.

### Idempotent DB migration
**Source:** `src/capture-db.js:5-35`
**Apply to:** `extraction-db.js:initDb`
- `CREATE TABLE IF NOT EXISTS`
- `CREATE INDEX IF NOT EXISTS`
- `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` for any future-added column
- Best-effort at boot — wrap in try/catch in `src/index.js`; alerter starts even if init fails.

### Farmer-facing text sanitization
**Source:** `src/message.js:16-19` (`fmtNum`); memory rule (no em-dashes)
**Apply to:** Any code path that produces a string sent via `signalClient.send(...)` — preview text, ask-back questions, "needs review" reply. Test in `test/extraction/sanitize.test.js`.

### Factory + `_internal` test seam
**Source:** `src/llm-client.js:77-80`
**Apply to:** `extractor.js`, `state-machine.js`, `validator.js`, `multimodal.js`. Always export public factory plus `_internal: { ... }` for direct unit tests of helpers.

### Fire-and-forget enqueue (never await, always `.catch(logger.warn)`)
**Source:** `src/receive-loop.js:210-214`
**Apply to:** Capture → extraction enqueue. Receive-loop's 30s budget cannot be blocked by extraction (multi-turn LLM, image upload).

### Jest mock for Anthropic SDK
**Source:** `test/llm-client.test.js:8-13`
**Apply to:** `test/extraction/extractor.test.js`, `test/extraction/validator.test.js`.

### Fake HTTP server with mutable `handle`
**Source:** `test/helpers/fake-whisper-server.js`
**Apply to:** `test/extraction/helpers/fake-anthropic-server.js` — verbatim factory pattern, swap `/transcribe` → `/v1/messages`, swap response shape.

---

## No Analog Found

| File | Role | Reason |
|---|---|---|
| `src/extraction/schemas/*.js` | Zod schema | First Zod usage in alerter. Pattern proposed from RESEARCH §"Pattern 1: Anthropic Tool-Use Forced Call with Zod-emitted Schema". |
| `test/eval/extraction/jest.config.js` + `scoring.js` + `report.js` | Eval harness | No existing eval-style test infrastructure in alerter. Pattern proposed from RESEARCH §5 Evaluation Strategy. |

For these, the planner should reference RESEARCH.md sections directly rather than an analog file.

---

## Metadata

**Analog search scope:** `src/agents/alerter/src/`, `src/agents/alerter/test/`, `src/agents/alerter/test/helpers/`
**Files scanned in full:** llm-client.js, capture-db.js, capture.js, config.js, receive-loop.js, snooze.js, index.js, message.js, capture-history.js, transcribe-client.js, fake-whisper-server.js, llm-client.test.js, capture-db.test.js, config.test.js, transcribe-client.test.js
**Pattern extraction date:** 2026-05-12
