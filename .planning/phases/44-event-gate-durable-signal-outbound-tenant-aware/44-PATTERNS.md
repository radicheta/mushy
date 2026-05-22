# Phase 44: Event-gate + Durable signal_outbound (tenant-aware) — Pattern Map

**Mapped:** 2026-05-21
**Files analyzed:** 18 new/modified (per CONTEXT.md `<canonical_refs>`)
**Analogs found:** 17 / 18 (only `tenants/<id>/config.yaml` is greenfield with no analog)

## File Classification

### Files this phase will MODIFY

| File | Role | Data Flow | Closest Analog | Match |
|------|------|-----------|----------------|-------|
| `src/agents/alerter/src/capture.js` (gate insertion :147 + convo gate :171) | pipeline-orchestrator | request-response | self (existing dispatch idiom at :147 + :171) | self-edit |
| `src/agents/alerter/src/signal.js` (wrap send, persistence fan-out) | wrapper / DAO-fanout | request-response | self (existing `send(body, opts)` shape, line :58) | self-extend |
| `src/agents/alerter/src/llm-client.js` (`fmtHistory` merge + 400-char cap) | LLM-client | transform | self (existing `fmtHistory` at :33-40) | self-extend |
| `src/agents/alerter/src/capture-history.js` (add `selectRecentOutboundByRecipient`) | DAO-read | CRUD-read | self (existing `selectRecentBySender` at :6-15) | self-extend |
| `src/agents/alerter/src/capture-db.js` (ALTER ADD COLUMN `extraction_gate`) | DAO-DDL | schema-migration | self (existing ALTER pattern at :32-41) | self-extend |
| `src/agents/alerter/src/config.js` (layered tenants/<id>/ → env → default) | config-loader | boot-time-read | self (existing `load(env)` at :50-139) | self-refactor |
| `src/agents/alerter/src/receive-loop.js` (8 send sites pass `intent`) | dispatcher | request-response | self | self-edit |
| `src/agents/alerter/src/index.js` (3 send sites pass `intent`) | bootstrapper | request-response | self | self-edit |
| `src/agents/alerter/src/confirm/outbound-confirm.js` (1 send site passes `intent`) | dispatcher | request-response | self | self-edit |
| `src/agents/alerter/src/extraction/outbound.js` (1 send site passes `intent`) | dispatcher | request-response | self | self-edit |

### Files this phase will CREATE

| File | Role | Data Flow | Closest Analog | Match |
|------|------|-----------|----------------|-------|
| `src/agents/alerter/src/event-gate/index.js` | gate-facade | request-response | `src/agents/alerter/src/extraction/pipeline.js` (factory style) | role-match |
| `src/agents/alerter/src/event-gate/rules.js` | classifier (pure) | transform | `src/agents/alerter/src/rules.js` (existing pure rules module) | exact |
| `src/agents/alerter/src/event-gate/haiku-classifier.js` | LLM-classifier | request-response | `src/agents/alerter/src/extraction/extractor.js:98-180` (Anthropic SDK + tool_use + cache) | exact |
| `src/agents/alerter/src/outbound-db.js` | DAO (DDL+insert+select) | CRUD-write+read | `src/agents/alerter/src/capture-db.js` + `src/agents/alerter/src/extraction/extraction-db.js` | exact |
| `src/agents/alerter/test/event-gate/rules.test.js` | unit-test | test | `src/agents/alerter/test/rules.test.js` | exact |
| `src/agents/alerter/test/event-gate/haiku-classifier.test.js` | unit-test (mocked SDK) | test | `src/agents/alerter/test/farmos/mock-client.js` mock pattern | role-match |
| `src/agents/alerter/test/event-gate/integration.test.js` | integration-test | test | `src/agents/alerter/test/integration.test.js` | exact |
| `src/agents/alerter/test/outbound-db.test.js` | DAO unit-test | test | `src/agents/alerter/test/capture-db.test.js` | exact |
| `src/agents/alerter/test/llm-client.outbound-merge.test.js` | unit-test | test | `src/agents/alerter/test/llm-client.test.js` | exact |
| `src/agents/alerter/test/event-gate/haiku-live.test.js` | live-API test | test | `src/agents/alerter/test/eval/ingestion/paperlog.test.js:14-15` (EVAL_RUN_LIVE gate) | exact |
| `tenants/mossrock/config.yaml` | tenant-config | boot-time-read | **none** (greenfield) | no-analog |
| `tenants/mossrock/strains.yaml` | tenant-vocab | boot-time-read | **none** (greenfield) | no-analog |
| `tenants/mossrock/secrets.env` (gitignored) | secrets | boot-time-read | existing `.env` posture (consumed by `process.env`) | partial |
| `tenants/example/config.yaml` | placeholder | boot-time-read | sibling of `tenants/mossrock/config.yaml` | sibling |

---

## Pattern Assignments

### `src/agents/alerter/src/outbound-db.js` (NEW — DAO, CRUD-write+read)

**Analog A (module shape):** `src/agents/alerter/src/capture-db.js`
**Analog B (DDL+index idempotence + module export shape):** same file, lines 5-60

**Module skeleton pattern** (`capture-db.js:1-5, 119`):
```javascript
'use strict';
// Phase 44: signal_outbound persistence (regular table; per-farmer volume too low for hypertable).
// Pure module — pool injected by caller (mirrors capture-db.js).

async function initDb(pool) { /* DDL + indexes here */ }
// ...
module.exports = { initDb, insertOutbound, selectRecentByRecipient };
```

**DDL idempotence pattern** (`capture-db.js:5-28`):
```javascript
await pool.query(`
  CREATE TABLE IF NOT EXISTS signal_outbound (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       text NOT NULL,
    sent_at         timestamptz NOT NULL DEFAULT now(),
    recipient_e164  text NOT NULL,
    intent          text NOT NULL,
    body            text NOT NULL,
    attachments     jsonb,
    source_module   text NOT NULL,
    source_line     integer,
    related_capture_id uuid,
    related_draft_id   uuid
  )
`);
await pool.query(`CREATE INDEX IF NOT EXISTS idx_signal_outbound_tenant_sent ON signal_outbound(tenant_id, sent_at DESC)`);
await pool.query(`CREATE INDEX IF NOT EXISTS idx_signal_outbound_recipient_sent ON signal_outbound(recipient_e164, sent_at DESC)`);
await pool.query(`CREATE INDEX IF NOT EXISTS idx_signal_outbound_intent ON signal_outbound(intent)`);
```
Note pgcrypto for `gen_random_uuid()` may need `CREATE EXTENSION IF NOT EXISTS pgcrypto;` first (RESEARCH A2).

**Parameterised INSERT pattern** (mirror `capture-db.js:62-83`):
```javascript
async function insertOutbound(pool, row) {
  await pool.query(
    `INSERT INTO signal_outbound
       (tenant_id, sent_at, recipient_e164, intent, body, attachments,
        source_module, source_line, related_capture_id, related_draft_id)
     VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, $9, $10)`,
    [row.tenant_id, row.sent_at, row.recipient_e164, row.intent, row.body,
     row.attachments ? JSON.stringify(row.attachments) : null,
     row.source_module, row.source_line ?? null,
     row.related_capture_id ?? null, row.related_draft_id ?? null]
  );
}
```

**Read query pattern** (mirror `capture-history.js:6-15`):
```javascript
async function selectRecentByRecipient(pool, recipient, sinceMs) {
  const since = new Date(sinceMs);
  const r = await pool.query(
    `SELECT sent_at, body, intent
     FROM signal_outbound
     WHERE recipient_e164 = $1 AND sent_at > $2
     ORDER BY sent_at ASC`,
    [recipient, since]
  );
  return r.rows;
}
```

---

### `src/agents/alerter/src/event-gate/haiku-classifier.js` (NEW — LLM-classifier)

**Analog:** `src/agents/alerter/src/extraction/extractor.js` + `src/agents/alerter/src/extraction/prompts/system.js`

**Imports + client construction** (mirror `extractor.js:21, 98-113`):
```javascript
const Anthropic = require('@anthropic-ai/sdk');
const { CACHEABLE_SYSTEM_BLOCKS } = require('./prompts');  // classifier prompts module

function createHaikuClassifier({
  apiKey,
  logger = console,
  model = 'claude-haiku-4-5-20251001',
  maxTokens = 100,
  timeoutMs = 2000,
  client: injectedClient = null,
} = {}) {
  const client = injectedClient || new Anthropic({ apiKey, maxRetries: 2 });
  // ...
}
```

**Forced-tool-use + cache_control pattern** (mirror `extractor.js:122-134` + `prompts/system.js:217-219`):
```javascript
// In prompts module:
const CACHEABLE_SYSTEM_BLOCKS = [
  { type: 'text', text: SYSTEM_PROMPT, cache_control: { type: 'ephemeral' } },
];

// In classifier:
const resp = await client.messages.create({
  model,
  max_tokens: maxTokens,
  system: CACHEABLE_SYSTEM_BLOCKS,
  tools: [{
    name: 'classify_capture',
    description: 'Classify whether this capture is an event worth extracting.',
    input_schema: { /* zod-to-json-schema for {is_event, kind, confidence} */ },
  }],
  tool_choice: { type: 'tool', name: 'classify_capture' },
  messages: [{ role: 'user', content: buildClassifierInput(envCtx) }],
});
```
**Caching threshold gotcha (RESEARCH Pitfall 1):** Haiku 4.5 cache min = 4,096 tokens. Size the system prompt + few-shot accordingly or accept cache no-op.

**Fail-open error handling** (mirror `extractor.js:132-138` + D-03):
```javascript
try {
  resp = await client.messages.create(baseReq);
} catch (e) {
  logger.warn && logger.warn(`[haiku-classifier] degraded: ${e.message}`);
  return { ok: false, reason: e.message, fallthrough: 'forced' };  // D-03: fail-OPEN
}
```

**Tool-use extraction** (mirror `extractor.js:93-96, 142-149`):
```javascript
function findToolUseBlock(msg, toolName) {
  if (!msg || !Array.isArray(msg.content)) return null;
  return msg.content.find((b) => b && b.type === 'tool_use' && b.name === toolName) || null;
}
const toolUse = findToolUseBlock(resp, 'classify_capture');
if (!toolUse) return { ok: false, reason: 'no_tool_use_in_response', fallthrough: 'forced' };
```

---

### `src/agents/alerter/src/event-gate/rules.js` (NEW — pure classifier)

**Analog:** `src/agents/alerter/src/rules.js` (existing pure-functions style; no I/O).

**Pure function pattern** (single-file pure module, exports named functions):
```javascript
'use strict';

const STRAIN_RE = /\b[A-Z]{2,4}\b/;
const BLOCK_RE = /\b\d{6}_[A-Z]{2,4}_\d+\b/;
const ACK_RE = /^(ok|yes|got it|thanks|gracias|si|sí|👍)$/i;

function rulePositive(envCtx) {
  if ((envCtx.attachmentCount || 0) > 0) return { hit: true, kind: 'image_or_audio' };
  const body = envCtx.text || envCtx.transcript || '';
  if (body.length > 200) return { hit: true, kind: 'long_text' };
  if (STRAIN_RE.test(body)) return { hit: true, kind: 'strain_code' };
  if (BLOCK_RE.test(body)) return { hit: true, kind: 'block_name' };
  return { hit: false };
}

function ruleNegative(envCtx, lastBotOutbound, nowMs) {
  if (!lastBotOutbound || lastBotOutbound.intent !== 'attestation_kickoff') return { hit: false };
  if (nowMs - new Date(lastBotOutbound.sent_at).getTime() > 30 * 60 * 1000) return { hit: false };
  const body = (envCtx.text || '').trim();
  if (body.length >= 40) return { hit: false };
  if (!ACK_RE.test(body)) return { hit: false };
  return { hit: true, kind: 'short_ack_within_30m' };
}

module.exports = { rulePositive, ruleNegative };
```

---

### `src/agents/alerter/src/event-gate/index.js` (NEW — gate facade)

**Analog:** Factory-shape mirror of `src/agents/alerter/src/extraction/pipeline.js` and `src/agents/alerter/src/confirm/outbound-confirm.js` (create+return-object idiom).

Mirrors capture-history factory shape:
```javascript
function createEventGate({ haikuClassifier, rules, logger = console }) {
  return {
    async classify(envCtx, lastBotOutbound, nowMs) {
      const pos = rules.rulePositive(envCtx);
      if (pos.hit) return { gate: 'fast_event', allow_extract: true, allow_convo: true };
      const neg = rules.ruleNegative(envCtx, lastBotOutbound, nowMs);
      if (neg.hit) return { gate: 'skipped_rule_neg', allow_extract: false, allow_convo: false };
      // gray zone → Haiku (fail-open per D-03)
      const r = await haikuClassifier.classify(envCtx);
      if (!r.ok) return { gate: 'forced', allow_extract: true, allow_convo: true };
      if (r.is_event || r.confidence < 0.7) return { gate: 'haiku_event', allow_extract: true, allow_convo: true };
      return { gate: 'haiku_chitchat', allow_extract: false, allow_convo: false };
    },
  };
}
```

---

### `src/agents/alerter/src/capture-db.js` (MODIFIED — add `extraction_gate` column)

**Analog:** self, lines 32-34.

**ALTER pattern to copy** (`capture-db.js:32`):
```javascript
await pool.query(`ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS extraction_gate text`);
```
Note RESEARCH Pattern 2: D-04 says `VARCHAR(32)` but project convention is plain `text`. Use `text` for consistency; document deviation in PLAN.md.

---

### `src/agents/alerter/src/signal.js` (MODIFIED — wrap send with persistence hook)

**Analog:** self, lines 58-113 (existing `send(body, opts)` signature is THE wrapper choke point).

**Signature extension** (preserve back-compat at `signal.js:58`):
```javascript
// BEFORE:
async function send(body, { bypassCap = false, to } = {}) {

// AFTER (D-15):
async function send(body, {
  bypassCap = false, to,
  intent, relatedCaptureId = null, relatedDraftId = null, sourceModule = null,
} = {}) {
  if (!intent) {
    logger.warn('[signal] send() called without intent — defaulting to "unknown" (v1.9 will require)');
  }
```

**Post-send persistence hook** (insert after `sendHistory.push(now)` at `signal.js:104`):
```javascript
sendHistory.push(now);
// Phase 44 D-14: single durable-outbound hook. Failure logged, send return unchanged.
try {
  await outboundDb.insertOutbound(pool, {
    tenant_id: config.tenantId,
    sent_at: new Date(now),
    recipient_e164: isStringTarget ? target : `group:${resolvedGroupId || target.groupId}`,
    intent: intent || 'unknown',
    body,
    source_module: sourceModule,
    source_line: null,
    related_capture_id: relatedCaptureId,
    related_draft_id: relatedDraftId,
  });
} catch (e) {
  logger.warn(`[signal] outbound persistence failed: ${e.message} — send succeeded, audit row missed`);
}
```
**OPEN Q from RESEARCH:** D-12 schema has `recipient_e164 NOT NULL` — group sends must encode group id into the field (prefix `group:`) OR planner adds a `recipient_group_id` column. Recommend prefix-into-recipient_e164 to preserve D-12 verbatim.

---

### `src/agents/alerter/src/capture-history.js` (MODIFIED — add outbound query)

**Analog:** self, the existing `selectRecentBySender` is the literal template.

**Existing pattern to mirror** (`capture-history.js:5-17`):
```javascript
function createCaptureHistory({ pool }) {
  return {
    async selectRecentBySender(sender, sinceMs) {
      const since = new Date(sinceMs);
      const r = await pool.query(
        `SELECT captured_at, raw_text, transcript, message_type
         FROM signal_capture
         WHERE sender = $1 AND captured_at > $2
         ORDER BY captured_at ASC`,
        [sender, since]
      );
      return r.rows;
    },
    // ADD per D-18:
    async selectRecentOutboundByRecipient(recipient, sinceMs) {
      const since = new Date(sinceMs);
      const r = await pool.query(
        `SELECT sent_at, body, intent
         FROM signal_outbound
         WHERE recipient_e164 = $1 AND sent_at > $2
         ORDER BY sent_at ASC`,
        [recipient, since]
      );
      return r.rows;
    },
  };
}
```

---

### `src/agents/alerter/src/llm-client.js` (MODIFIED — `fmtHistory` merge + 400-char outbound cap)

**Analog:** self, lines 33-40 (the existing `fmtHistory`).

**Existing pattern** (`llm-client.js:33-40`):
```javascript
function fmtHistory(history) {
  if (!history || !history.length) return '  (none)';
  return history.slice(-MAX_HISTORY_ROWS).map((r) => {
    const ts = (r.captured_at instanceof Date ? r.captured_at : new Date(r.captured_at)).toISOString();
    const body = r.transcript || r.raw_text || '';
    return `  [${ts}] ${r.message_type}: '${String(body).replace(/\n/g, ' ').slice(0, 200)}'`;
  }).join('\n');
}
```

**Extension shape** (per D-17/D-18):
```javascript
function fmtHistory(history, outboundHistory = []) {
  // Tag each row with stream kind + normalised timestamp for merge-sort.
  const tagged = [
    ...history.map((r) => ({ ts: r.captured_at, kind: 'in', body: r.transcript || r.raw_text || '', type: r.message_type, cap: 200 })),
    ...outboundHistory.map((r) => ({ ts: r.sent_at, kind: 'out', body: r.body, type: `bot:${r.intent}`, cap: 400 })),
  ].sort((a, b) => new Date(a.ts) - new Date(b.ts));
  if (!tagged.length) return '  (none)';
  return tagged.slice(-MAX_HISTORY_ROWS).map((r) => {
    const ts = new Date(r.ts).toISOString();
    return `  [${ts}] ${r.type}: '${String(r.body).replace(/\n/g, ' ').slice(0, r.cap)}'`;
  }).join('\n');
}
```

**`buildUserBlock` exposes `lastBotOutbound`** (per D-19, extend `llm-client.js:49-62`):
```javascript
function buildUserBlock({ history, outboundHistory, lastBotOutbound, sensorSnapshot, currentMessage }) {
  // ...existing blocks...
  return [
    // ...
    '## Last thing you said to the farmer',
    lastBotOutbound
      ? `  [${new Date(lastBotOutbound.sent_at).toISOString()}] ${lastBotOutbound.intent}: '${String(lastBotOutbound.body).replace(/\n/g, ' ').slice(0, 400)}'`
      : '  (none)',
    '## Recent history (last 24h, oldest first, merged streams)',
    fmtHistory(history, outboundHistory),
  ].join('\n');
}
```

---

### `src/agents/alerter/src/config.js` (MODIFIED — layered tenants → env → default loader)

**Analog:** self, `load(env)` at lines 50-139 is the single env-read point today.

**Existing single-source-of-truth pattern** (`config.js:50-62`):
```javascript
function load(env = process.env) {
  return Object.freeze({
    bridgeWsUrl:         env.BRIDGE_WS_URL      || 'ws://host.docker.internal:8081',
    signalSender:        mustEnv(env, 'SIGNAL_SENDER'),
    signalRecipient:     mustEnv(env, 'SIGNAL_RECIPIENT'),
    signalFarmerMap:     parseFarmerMap(env.SIGNAL_FARMER_MAP || ''),
    // ...
```

**Refactor pattern** (preserve `load(env)` signature so existing tests still pass — RESEARCH A6):
```javascript
const YAML = require('yaml');
const fs = require('fs');
const path = require('path');

function loadTenantFile(tenantId, filename) {
  const p = path.join(__dirname, '..', '..', '..', '..', 'tenants', tenantId, filename);
  if (!fs.existsSync(p)) return {};
  try { return YAML.parse(fs.readFileSync(p, 'utf8')) || {}; }
  catch (e) { console.warn(`[config] ${p} parse failed: ${e.message}`); return {}; }
}

function pick(tenantConfig, env, key, def) {
  if (tenantConfig[key] !== undefined && tenantConfig[key] !== null) return tenantConfig[key];
  if (env[key] !== undefined) return env[key];
  return def;
}

function load(env = process.env) {
  const tenantId = env.TENANT_ID || 'mossrock';
  const tenantConfig = {
    ...loadTenantFile(tenantId, 'config.yaml'),
    ...loadTenantFile(tenantId, 'strains.yaml'),
  };
  return Object.freeze({
    tenantId,
    signalSender:    pick(tenantConfig, env, 'SIGNAL_SENDER', undefined) || mustEnv(env, 'SIGNAL_SENDER'),
    // ...every existing field swapped from `env.X` to `pick(tenantConfig, env, 'X', default)`
    eventGateConvoMode: pick(tenantConfig, env, 'EVENT_GATE_CONVO_MODE', 'silent'),
  });
}
```
**Critical constraint:** the `load(env)` signature MUST remain (existing tests call `config.load({...})` with synthetic env — see `test/config.test.js`). The tenant-file layer is read once at boot; tests can opt out via `TENANT_ID=__none__` (no such dir → empty layer).

---

### Send-site updates (10 call sites pass `intent`)

**Sites enumerated:** `receive-loop.js:73, 85, 91, 102, 106, 112, 189, 211` | `index.js:180, 183, 185` | `capture.js:197` | `confirm/outbound-confirm.js:33` | `extraction/outbound.js:55`.

**Edit pattern** (additive, per RESEARCH Pattern 3):
```javascript
// BEFORE (receive-loop.js:73):
await signalClient.send('experiment dispatch unavailable (bridge unreachable)').catch(() => {});

// AFTER (D-15 — pass intent):
await signalClient.send('experiment dispatch unavailable (bridge unreachable)',
  { intent: 'experiment_reject', sourceModule: 'receive-loop.js' }).catch(() => {});
```
Intent mapping table goes in PLAN RUNBOOK per D-13.

---

### `src/agents/alerter/src/capture.js` (MODIFIED — gate insertion + convo gate)

**Insertion sites:** `:147` (extractor enqueue) and `:171` (llmClient.compose).

**Existing dispatch pattern** (`capture.js:147-159`):
```javascript
if (extractionPipeline && farmosPerson && farmosPerson !== '(unassigned)') {
  extractionPipeline.enqueue({...}).catch((e) => logger.warn(`[capture] extraction enqueue failed: ${e.message}`));
}
```

**Wrap with gate** (per D-02/D-04/D-05):
```javascript
// BEFORE :147 — call gate once, persist audit, then branch.
let gateDecision = { gate: 'forced', allow_extract: true, allow_convo: true };
if (eventGate) {
  const lastBot = await captureHistory.selectRecentOutboundByRecipient(source, capturedAtMs - 30 * 60 * 1000)
    .then((rows) => rows[rows.length - 1] || null).catch(() => null);
  gateDecision = await eventGate.classify({ text, transcript, attachmentCount: attachmentPaths.length }, lastBot, capturedAtMs);
  // Audit column (D-04) — best-effort.
  await pool.query(`UPDATE signal_capture SET extraction_gate = $1 WHERE id = $2`,
    [gateDecision.gate, id]).catch((e) => logger.warn(`[capture] gate audit failed: ${e.message}`));
}

if (gateDecision.allow_extract && extractionPipeline && farmosPerson && farmosPerson !== '(unassigned)') {
  extractionPipeline.enqueue({...});
}
```

**Convo gate at :171** (per D-05/D-06):
```javascript
if (gateDecision.allow_convo || config.eventGateConvoMode === 'off') {
  const r = await llmClient.compose({ history, outboundHistory, lastBotOutbound: lastBot, sensorSnapshot: snapshot, currentMessage: {...} });
  // ...
} else {
  logger.info(`[capture] convo suppressed by gate=${gateDecision.gate} mode=${config.eventGateConvoMode}`);
}
```

---

## Test Patterns

### `test/outbound-db.test.js` (NEW)

**Analog:** `src/agents/alerter/test/capture-db.test.js:1-50`.

**Pattern to copy verbatim** (test/capture-db.test.js:5-12):
```javascript
const { initDb, insertOutbound, selectRecentByRecipient } = require('../src/outbound-db');

describe('outbound-db', () => {
  let pool;
  beforeEach(() => {
    pool = { query: jest.fn().mockResolvedValue({ rows: [], rowCount: 0 }) };
  });

  test('initDb issues CREATE TABLE + 3 CREATE INDEX', async () => {
    await initDb(pool);
    expect(pool.query).toHaveBeenCalledTimes(4);
    const sql0 = pool.query.mock.calls[0][0];
    expect(sql0).toMatch(/CREATE TABLE IF NOT EXISTS signal_outbound/);
    expect(sql0).toMatch(/tenant_id\s+text NOT NULL/);
    // ... assert each idx_signal_outbound_* exists
  });
});
```

---

### `test/event-gate/haiku-classifier.test.js` (NEW — mocked SDK)

**Analog:** `src/agents/alerter/test/farmos/mock-client.js` (the mock-client idiom) + extractor tests (injected-client pattern at `extractor.js:110` `client: injectedClient = null`).

**Mock-client injection pattern** (mirror `extractor.js:111-112`):
```javascript
const fakeAnthropic = {
  messages: {
    create: jest.fn(async () => ({
      content: [{
        type: 'tool_use',
        name: 'classify_capture',
        input: { is_event: true, kind: 'observation', confidence: 0.91 },
      }],
      usage: { input_tokens: 10, output_tokens: 5 },
    })),
  },
};
const classifier = createHaikuClassifier({ apiKey: 'test', client: fakeAnthropic });
const r = await classifier.classify({ text: 'block 251109_SHI_3 ready' });
expect(r.is_event).toBe(true);
```

---

### `test/event-gate/haiku-live.test.js` (NEW — live API gate)

**Analog:** `src/agents/alerter/test/eval/ingestion/paperlog.test.js:14-15`.

**Pattern to copy** (exact two lines from analog):
```javascript
const liveMode = process.env.EVAL_RUN_LIVE === '1' && !!process.env.ANTHROPIC_API_KEY;
const describeMaybe = liveMode ? describe : describe.skip;

describeMaybe('Haiku 4.5 classifier (live)', () => {
  test('classifies 10 gray-zone fixtures with ≥80% agreement', async () => {
    // ...
  }, 60000);
});
```

---

## Shared Patterns

### Pattern S1: Never-throw on DB writes
**Source:** `src/agents/alerter/src/extraction/extraction-db.js:60-75` (and confirm-db.js `_runTransition`).
**Apply to:** `outbound-db.js insertOutbound` (return `{ok, reason}` instead of throwing); `signal.js` persistence hook wraps in try/catch.

```javascript
try {
  const r = await pool.query(/* ... */);
  return { ok: true, /* ... */ };
} catch (e) {
  return { ok: false, reason: e.message };
}
```

### Pattern S2: Anthropic SDK construction
**Source:** `src/agents/alerter/src/llm-client.js:64-65` + `src/agents/alerter/src/extraction/extractor.js:112`.
**Apply to:** `event-gate/haiku-classifier.js`.

```javascript
const Anthropic = require('@anthropic-ai/sdk');
const client = injectedClient || new Anthropic({ apiKey, maxRetries: 2 });
```
**Constraint:** `ANTHROPIC_API_KEY` must NEVER cross into logger (RESEARCH security V14).

### Pattern S3: ALTER TABLE ADD COLUMN IF NOT EXISTS
**Source:** `src/agents/alerter/src/capture-db.js:32-41`.
**Apply to:** `capture-db.js` addition of `extraction_gate text` column.

```javascript
await pool.query(`ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS extraction_gate text`);
```

### Pattern S4: Factory createX({deps}) → returns object
**Source:** every existing module — `createSignalClient`, `createCaptureHistory`, `createLlmClient`, `createConfirmOutbound`, `createOutboundDispatcher`, `createExtractor`.
**Apply to:** `createEventGate`, `createHaikuClassifier`.
**Why:** dependency injection enables unit tests with pool/client mocks.

### Pattern S5: `module.exports = { ... }` at bottom; no default export
**Source:** every alerter `src/*.js` file.
**Apply to:** every new file in this phase.

### Pattern S6: Logger contract — `{ info, warn }`, default `console`
**Source:** `signal.js:5`, `llm-client.js:64`, `extractor.js:100`.
**Apply to:** every new factory.

```javascript
function createX({ logger = console, /* ... */ }) { /* ... */ }
```

---

## No Analog Found

| File | Role | Reason |
|------|------|--------|
| `tenants/mossrock/config.yaml` | tenant-config | Greenfield. No YAML config files exist in repo today (only `.env`). Follow RESEARCH § "Code Examples — Layered config loader" — the loader is the only consumer. |
| `tenants/mossrock/strains.yaml` | tenant-vocab | Greenfield. Source-of-truth for the 14 strain codes is currently the test fixture `test/farmos/mock-client.js:17-20` — copy that list. |
| `tenants/mossrock/secrets.env` | secrets | Resembles existing `.env` consumption; only difference is path. Critical: `.gitignore` MUST add `tenants/*/secrets.env` BEFORE the file exists (RESEARCH Pitfall 7). |
| `tenants/example/config.yaml` | placeholder | Sibling of `tenants/mossrock/config.yaml`. Use commented placeholder values per Foray v0.1 posture. |

---

## Metadata

**Analog search scope:**
- `src/agents/alerter/src/` (all modules)
- `src/agents/alerter/test/` (test scaffolding patterns)
- `src/agents/alerter/src/extraction/` and `confirm/` subtrees

**Files scanned:** 14 source files + 6 test files.
**Pattern extraction date:** 2026-05-21.
**Key insight:** Almost every primitive Phase 44 needs already exists in `src/agents/alerter/`. Work is composition + DI, not invention (RESEARCH § Don't Hand-Roll).
