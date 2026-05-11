# Phase 37: Multi-farmer Routing - Pattern Map

**Mapped:** 2026-05-11
**Files analyzed:** 9 source + 6 fixtures + 4 tests
**Analogs found:** 9 / 9 (all in-repo, all exact role+flow matches)

## File Classification

| File | Role | Data Flow | Closest Analog | Match Quality |
|------|------|-----------|----------------|---------------|
| `src/agents/alerter/src/signal.js` (modify) | service (HTTP client) | request-response | itself (extend `send()`) | exact (in-place extension) |
| `src/agents/alerter/src/capture.js` (modify) | service (pipeline orchestrator) | event-driven | itself (extend send call at l.146) | exact |
| `src/agents/alerter/src/receive-loop.js` (modify) | service (poller) | event-driven | itself (extend whitelist gate at l.87-102) | exact |
| `src/agents/alerter/src/capture-db.js` (modify) | model (persistence) | CRUD | itself + `schema_migration.js` for ALTER pattern | exact |
| `src/agents/alerter/src/config.js` (modify) | config | boot-load | itself (`signalAdditionalSenders` at l.41-42) | exact |
| `src/agents/alerter/src/snooze.js`, `rules.js`, `heartbeat.js` | service (senders) | event-driven | N/A — no per-call change (D-02) | n/a |
| `docker-compose.override.yml` (modify) | config | boot-load | line 77 (`SIGNAL_ADDITIONAL_SENDERS` from commit `c8e9ac1`) | exact |
| `test/fixtures/envelopes/group-*.json` (new ×6) | test fixture | static | `test/fixtures/envelopes/text.json` | exact (extend DM shape with `groupInfo`) |
| `test/{signal,capture,capture-db,receive-loop}.test.js` (extend) | test | unit | themselves | exact |

## Pattern Assignments

### `src/agents/alerter/src/signal.js` (modify)

**Self-analog: extend the existing `send()` shape at lines 5–54.**

**Constructor signature pattern** (line 5):
```javascript
function createSignalClient({ apiUrl, sender, recipient, maxSendsPerHour, getMaxSendsPerHour, logger = console, timeoutMs = 10000 }) {
```
**Change:** add `defaultTarget` parameter (string phone OR `{ groupId }`). Falls back to `recipient` (legacy) if absent. Wire from `config.signalGroupId ? { groupId: config.signalGroupId } : config.signalRecipient`.

**Existing send() options object** (line 25):
```javascript
async function send(body, { bypassCap = false } = {}) {
```
**Change per D-01:** extend to `async function send(body, { bypassCap = false, to } = {})`. Resolve effective target: `const target = to ?? defaultTarget;`.

**Recipients-array construction** (line 40):
```javascript
body: JSON.stringify({ message: body, number: sender, recipients: [recipient] }),
```
**Change:** build `recipients` from `target`:
```javascript
const recipients = typeof target === 'string'
  ? [target]
  : [`group.${target.groupId}`];
body: JSON.stringify({ message: body, number: sender, recipients }),
```

**Logging pattern with maskNumber** (line 49):
```javascript
logger.info(`[signal] sent -> ${maskNumber(recipient)} (${body.length} chars)`);
```
**Change:** branch on target shape:
```javascript
const label = typeof target === 'string'
  ? maskNumber(target)
  : `group:${target.groupId.slice(0,8)}…`;
logger.info(`[signal] sent -> ${label} (${body.length} chars)`);
```

---

### `src/agents/alerter/src/capture.js` (modify)

**Self-analog: the envelope unwrap at lines 60–64 + the single load-bearing send call at line 146.**

**Envelope unwrap pattern** (lines 60–64) — already in place:
```javascript
const env = envWrapper.envelope || envWrapper;
const source = env.source || env.sourceNumber || '';
const dm = env.dataMessage || {};
const text = dm.message || null;
const attachments = dm.attachments || [];
```
**Add per D-02 + D-13:**
```javascript
const groupId = dm.groupInfo?.groupId ?? null;
const replyTarget = groupId ? { groupId } : source;
const farmosPerson = config.signalFarmerMap.get(source) ?? '(unassigned)';
const replyTargetKind = groupId ? 'group' : 'dm';   // 'none' set by receive-loop when D-08 silent-capture path
```

**Send-reply call site** (line 146 — the 999.20 load-bearing line):
```javascript
await signalClient.send(replyText).catch((e) => logger.warn(`[capture] reply send failed: ${e.message}`));
```
**Change per D-01:**
```javascript
await signalClient.send(replyText, { to: replyTarget }).catch((e) => logger.warn(`[capture] reply send failed: ${e.message}`));
```

**insertCapture row shape** (lines 102–113):
```javascript
await insertCapture(pool, {
  id, captured_at: new Date(capturedAtMs), sender: source,
  message_type: messageType, raw_text: text ?? null,
  attachment_paths: attachmentPaths, transcript,
  llm_session_tag: null, llm_reply: null, degraded,
});
```
**Add three fields per D-14:** `group_id: groupId, farmos_person: farmosPerson, reply_target_kind: replyTargetKind`.

---

### `src/agents/alerter/src/receive-loop.js` (modify)

**Self-analog: whitelist gate at lines 87–105.**

**Whitelist Set construction** (lines 89–91):
```javascript
const allowedSenders = new Set(
  [config.signalSender, config.signalRecipient, ...(config.signalAdditionalSenders || [])].filter(Boolean)
);
```
**Pattern to extend** per D-06: introduce a `botPhone = config.signalSender` reference for mention/quote matching.

**Per-envelope gate body** (lines 96–105):
```javascript
for (const env of envelopes) {
  const source = env?.envelope?.source;
  const dm = env?.envelope?.dataMessage;
  if (!source) continue;

  // R7 — whitelist gate BEFORE both snooze and capture branches
  if (!allowedSenders.has(source)) {
    logger.warn(`[receive] rejected sender (not in whitelist)`);
    continue;
  }
```
**Insert after l.105 per D-08/D-09:**
```javascript
const groupId = dm?.groupInfo?.groupId ?? null;
const groupType = dm?.groupInfo?.type ?? null;        // DELIVER vs UPDATE/QUIT (Risk #11)
const isGroup = !!groupId && groupType !== 'UPDATE' && groupType !== 'QUIT';

// D-09 — collect ALL triggers once, fire ONCE
const triggers = isGroup ? collectGroupTriggers(env, botPhone) : new Set(['dm']);
const shouldReply = triggers.size > 0;
```
Then gate the existing command + capture branches on `shouldReply`/`triggers.has('command')` instead of letting them parse independently. The capture branch (l.153) still runs whenever `(text || attachments.length)` per D-08 — passing `replyTargetKind = (isGroup ? (shouldReply ? 'group' : 'none') : 'dm')`.

**Pure helper to add (unit-testable):**
```javascript
function collectGroupTriggers(env, botPhone) {
  const out = new Set();
  const dm = env.envelope?.dataMessage || {};
  const text = dm.message || '';
  if ((dm.mentions || []).some((m) => m.number === botPhone)) out.add('mention');
  if (/^\s*(mute|snooze|quiet|status)\b/i.test(text)
      || /^\/(force-|cancel-)/i.test(text)) out.add('command');
  const q = dm.quote || {};
  if ((q.author || q.authorNumber) === botPhone) out.add('quote');
  return out;
}
```

---

### `src/agents/alerter/src/capture-db.js` (modify)

**Self-analog: `initDb()` pattern at lines 5–29 + `insertCapture()` at 31–49.**

**Existing initDb idempotent CREATE pattern** (lines 6–20):
```javascript
await pool.query(`
  CREATE TABLE IF NOT EXISTS signal_capture (
    id              text PRIMARY KEY,
    ...
    degraded        boolean NOT NULL DEFAULT false,
    expired         boolean NOT NULL DEFAULT false
  )
`);
```
**Append per D-14/D-15** (Postgres native — no DO-block needed for `ADD COLUMN`):
```javascript
await pool.query(`ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS group_id text`);
await pool.query(`ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS farmos_person text`);
await pool.query(`ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS reply_target_kind text`);
```
Place AFTER existing CREATE TABLE + CREATE INDEX calls so a fresh deploy gets the columns on first boot, and an upgrade gets them idempotently.

**Existing insertCapture INSERT shape** (lines 32–48):
```javascript
await pool.query(
  `INSERT INTO signal_capture
     (id, captured_at, sender, message_type, raw_text, attachment_paths, transcript, llm_session_tag, llm_reply, degraded)
   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)`,
  [row.id, row.captured_at, row.sender, row.message_type, row.raw_text ?? null,
   row.attachment_paths ?? [], row.transcript ?? null, row.llm_session_tag ?? null,
   row.llm_reply ?? null, row.degraded === true]
);
```
**Change:** extend column list + VALUES `$11..$13`, append `row.group_id ?? null, row.farmos_person ?? null, row.reply_target_kind ?? null`.

---

### `src/agents/alerter/src/config.js` (modify)

**Self-analog: `signalAdditionalSenders` parse at lines 41–42 (commit `c8e9ac1` template).**

**Comma-separated env parse pattern** (line 41–42):
```javascript
signalAdditionalSenders: (env.SIGNAL_ADDITIONAL_SENDERS || '')
                          .split(',').map((s) => s.trim()).filter(Boolean),
```
**Add per D-11/D-16:**
```javascript
signalGroupId: env.SIGNAL_GROUP_ID || null,  // bare base64; signal.js prepends `group.`
signalFarmerMap: parseFarmerMap(env.SIGNAL_FARMER_MAP || ''),
```
**New helper at module top (mirror parse shape):**
```javascript
function parseFarmerMap(raw) {
  const m = new Map();
  for (const entry of raw.split(',').map((s) => s.trim()).filter(Boolean)) {
    const idx = entry.indexOf(':');     // split on FIRST colon only (phones contain no ':')
    if (idx <= 0) continue;             // drop malformed
    const phone = entry.slice(0, idx).trim();
    const slug  = entry.slice(idx + 1).trim();
    if (phone && slug) m.set(phone, slug);
  }
  return m;
}
```

---

### `docker-compose.override.yml` (modify)

**Analog: Phase 36 commit `c8e9ac1` (the single line added at l.77).**

**Pattern** (line 77, alerter env block):
```yaml
      - SIGNAL_ADDITIONAL_SENDERS=${SIGNAL_ADDITIONAL_SENDERS}
```
**Add two lines immediately after l.77:**
```yaml
      - SIGNAL_GROUP_ID=${SIGNAL_GROUP_ID}
      - SIGNAL_FARMER_MAP=${SIGNAL_FARMER_MAP}
```
**No default value (intentional — both are operator-set in `.env`; absence is detected by config.js and falls back to legacy DM behavior).**

---

### `src/agents/alerter/src/index.js` (boot wire-up — minor)

**Self-analog: capture-pipeline boot at lines 81–94, `applyEvent` at 98–115.**

**Existing config-threading pattern** (line ~89):
```javascript
const pipeline = createCapturePipeline({
  pool, signalClient, transcribeClient, llmClient,
  captureHistory, sensorSnapshot,
  baseDir: config.captureBaseDir, logger, clock,
});
```
**Change:** pass `config` (or specifically `signalFarmerMap`) so capture.js can resolve farmer slug at row insert time.

**Existing signalClient construction** (boot, earlier in file):
**Change:** pass `defaultTarget: config.signalGroupId ? { groupId: config.signalGroupId } : config.signalRecipient`.

**applyEvent send-action dispatch** (lines 103–110) — NO CHANGE per D-02; the new constructor default makes heartbeat/snooze_ack/recovery hit the group automatically.

---

### `src/agents/alerter/src/{snooze,rules,heartbeat}.js`

**NO CHANGE per D-02 + D-04.** These modules don't call `signalClient.send()` directly — they produce action objects that `index.js:applyEvent` dispatches. The new `defaultTarget` constructor parameter on signal.js inherits transparently for all of them.

Documented here to be explicit for the planner: no per-file plan section needed beyond a sentence in the wire-up plan.

---

### Test fixtures (`test/fixtures/envelopes/group-*.json` — new ×6)

**Analog: `test/fixtures/envelopes/text.json`.**

**Existing DM fixture shape:**
```json
[
  { "envelope": {
      "source": "+59892893012",
      "sourceNumber": "+59892893012",
      "sourceUuid": "11111111-1111-1111-1111-111111111111",
      "timestamp": 1714240000000,
      "dataMessage": {
        "timestamp": 1714240000000,
        "message": "logged 3 jars in tent A",
        "expiresInSeconds": 0,
        "viewOnce": false,
        "attachments": []
      }
    }
  }
]
```
**Group variant — add `dataMessage.groupInfo`:**
```json
"groupInfo": { "groupId": "Z3JvdXBfYmFzZTY0X2lkX2hlcmU=", "type": "DELIVER" }
```
**Per-fixture additions:**
- `group-silent.json` — only `message: "hey did anyone water tent B"` (no triggers)
- `group-mention.json` — `dataMessage.mentions: [{ name: "bot", number: "+BOTPHONE", uuid: "...", start: 0, length: 5 }]`
- `group-command.json` — `message: "mute"`
- `group-reply-to-bot.json` — `dataMessage.quote: { author: "+BOTPHONE", authorNumber: "+BOTPHONE", id: 1714, text: "alerts muted for 24h" }`
- `group-mention-and-command.json` — both mentions[] AND command-keyword text (dedupe target)
- `group-unknown-sender.json` — `source: "+15550009999"` (whitelisted but not in SIGNAL_FARMER_MAP)

---

### Tests

**Analog: `test/capture-db.test.js` (mock pool pattern), `test/signal.test.js` (fake server pattern), `test/receive-loop.test.js` (envelope-push pattern), `test/capture.test.js` (mocked deps pattern).**

**capture-db mock pool pattern** (test/capture-db.test.js l.7–24):
```javascript
pool = { query: jest.fn().mockResolvedValue({ rows: [], rowCount: 0 }) };
await initDb(pool);
expect(pool.query).toHaveBeenCalledTimes(3);   // was 3 — becomes 6 (3 CREATEs + 3 ALTERs)
const allSql = pool.query.mock.calls.map((c) => c[0]).join('\n');
expect(allSql).toMatch(/ALTER TABLE signal_capture ADD COLUMN IF NOT EXISTS group_id text/);
```
Extend to verify three new ALTERs + that insertCapture VALUES is now `$1..$13` and params length is 13.

**signal.test.js fake-server pattern** (l.13–38):
```javascript
client = createSignalClient({ apiUrl: server.url, sender: SENDER, recipient: RECIPIENT, maxSendsPerHour: 20 });
const result = await client.send('hello');
expect(server.sent[0]).toMatchObject({ message: 'hello', number: SENDER, recipients: [RECIPIENT] });
```
Extend with:
- `client.send('x', { to: { groupId: 'ABC=' } })` → `recipients: ['group.ABC=']`
- `createSignalClient({ ..., defaultTarget: { groupId: 'ABC=' } })` + `client.send('x')` → `recipients: ['group.ABC=']`
- `defaultTarget = '+15551112222'` + no `to` → `recipients: ['+15551112222']`

**receive-loop.test.js envelope-push pattern** (l.49–71):
```javascript
server.received.push({
  envelope: { source: '+1111111111', dataMessage: { message: 'snooze rh 4h' } }
});
loop = createReceiveLoop({ signalClient, dispatch, config, logger, clock });
loop.start();
await new Promise((r) => setTimeout(r, 300));
expect(dispatched).toHaveLength(1);
```
Extend with the six group-fixture cases per RESEARCH.md test map (l.137–151); count send calls on the signalClient mock to assert "exactly one reply per envelope" (D-09).

**capture.test.js mocked-deps pattern** (l.30–49):
```javascript
signalClient = { fetchAttachment: jest.fn().mockResolvedValue(Buffer.from('AAA')),
                 send: jest.fn().mockResolvedValue({ ok: true }) };
```
Extend to verify `signalClient.send.mock.calls[0][1]` (the `{ to }` opts argument) matches `envelope.source` for DM and `{ groupId: ... }` for group fixtures.

---

## Shared Patterns

### Env-driven config (Phase 36 c8e9ac1 template)
**Source:** `src/agents/alerter/src/config.js:41-42` (parse) + `docker-compose.override.yml:77` (plumb)
**Apply to:** `SIGNAL_GROUP_ID`, `SIGNAL_FARMER_MAP`
```javascript
// config.js
foo: (env.FOO || '').split(',').map((s) => s.trim()).filter(Boolean),
```
```yaml
# override.yml
- FOO=${FOO}
```

### Whitelist-by-Set boot pattern
**Source:** `src/agents/alerter/src/receive-loop.js:89-91`
**Apply to:** any new per-envelope membership check (none added this phase, but `botPhone` is now a reference variable beside `allowedSenders`).

### Single-choke-point send (D-01 architectural pivot)
**Source:** `src/agents/alerter/src/signal.js:25-54`
**Apply to:** all alerter outbound. After this phase, every `signalClient.send(body)` call without `{ to }` inherits the group default; only `capture.js:146` passes `{ to }` explicitly.

### Idempotent ALTER TABLE on Postgres
**Source:** `src/mission-control/bridge/src/schema_migration.js:24-40` (DO-block pattern for ADD CONSTRAINT) — **NOT needed for ADD COLUMN**
**Apply to:** `capture-db.js initDb()` — plain `ADD COLUMN IF NOT EXISTS` is sufficient and is the lighter pattern Postgres supports natively.

### Envelope fixture extension
**Source:** `test/fixtures/envelopes/text.json`
**Apply to:** all six new `group-*.json` fixtures — add `dataMessage.groupInfo` (and `mentions`/`quote` as needed) to the existing DM template; preserve `source`, `sourceNumber`, `sourceUuid`, `timestamp` shape.

### Error-isolated fire-and-forget reply (R6)
**Source:** `src/agents/alerter/src/capture.js:146`
```javascript
await signalClient.send(replyText).catch((e) => logger.warn(`[capture] reply send failed: ${e.message}`));
```
**Apply to:** new `dispatchExperiment`-style branches if any are added; the loop must never die on a single send failure.

---

## No Analog Found

None. Every file in scope has either an in-place self-analog (extension) or a Phase-36-template analog (compose env, additional senders parser).

The only gray-area item — `collectGroupTriggers(env, botPhone)` as a new pure helper — has no direct analog, but its shape mirrors `parseSnoozeCommand`/`parseExperimentCommand` (pure, text-in / structured-out, fully unit-testable from fixtures).

---

## Metadata

**Analog search scope:** `src/agents/alerter/{src,test,test/fixtures/envelopes}/`, `docker-compose.override.yml`, `git show c8e9ac1`, `src/mission-control/bridge/src/schema_migration.js`
**Files scanned:** 14 source + 6 tests + 4 fixtures + 1 compose + 1 historical commit
**Pattern extraction date:** 2026-05-11
