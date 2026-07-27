# Pitfalls Research

**Domain:** Big-bang Node->Python rewrite of a live LLM-extraction + Signal-messaging agent
**Researched:** 2026-06-14
**Confidence:** HIGH (grounded in codebase + documented post-mortems from this repo)

---

## Critical Pitfalls

### Pitfall 1: Silent LLM Schema Drift Between Zod and Pydantic

**What goes wrong:**
The Zod schemas are the source of truth for what the LLM is allowed to emit -- they drive `DRAFT_JSON_SCHEMA` / `SUBMISSION_JSON_SCHEMA` sent as the tool `input_schema` to Anthropic. A Python port that rebuilds these as Pydantic models (or regenerates JSON Schema via `model.model_json_schema()`) will produce subtly different JSON Schema output. Specific drift risks:

- `additionalProperties: false` (`.strict()` in Zod) must be preserved on every nested object. `SeedingSession`, `SeedingSessionGroup`, `ConflictEntry` all carry `.strict()`. Pydantic uses `model_config = ConfigDict(extra='forbid')` -- this is opt-in, not the default. Omitting it means the LLM can smuggle off-schema fields into `draft_json` silently.
- The discriminated union on `"type"` -- Pydantic's `Annotated[Union[...], Field(discriminator="type")]` serializes `$defs` rather than `definitions`, and may use `oneOf` instead of matching Zod's `anyOf` structure. Anthropic's tool `input_schema` must be a single plain JSON object; structural differences in the schema change what the LLM believes it can emit.
- `z.record(z.string(), z.number())` (per_field_confidence, confidence maps) -- Pydantic emits `additionalProperties: {type: number}`. Verify the key is `additionalProperties`, not `patternProperties`.
- The `ObservationLog` refine (state OR notes required) is not expressable in JSON Schema; `validator.js` re-applies it manually after `safeParse`. The Python port must replicate this as a `model_validator(mode='after')` and apply it outside the union (same split as `ObservationLogBase` vs. `ObservationLog` in Node).
- `z.string().datetime()` validates ISO-8601 with a T separator. Pydantic's `datetime` type accepts more forms and auto-coerces. If Python accepts a bare date (`2025-06-14`) where the LLM should emit a datetime, extraction passes validation but DB inserts fail or store a wrong value.
- `BLOCK_NAME_RE` (`/^[0-9]{6}_[A-Z]{2,4}_[0-9]+$/`) must be copied exactly. Python `re.match()` without a trailing `$` silently accepts `260522_SHI_1_EXTRA`. Use `re.fullmatch()` or `\A` / `\Z` anchors.

**Why it happens:**
Zod and Pydantic are not isomorphic. Developers port field by field and assume the emitted JSON Schema is equivalent without diffing it. The LLM then emits outputs that pass the Python validator but would have been rejected by the Node one (or vice versa), and the mismatch only surfaces as wrong farmOS writes, not as errors.

**How to avoid:**
- In the schema-parity phase, generate both JSON Schema documents (Node: `SUBMISSION_JSON_SCHEMA`, Python: `model.model_json_schema()`) and do a structural diff. Treat any difference as a blocker.
- Apply `model_config = ConfigDict(extra='forbid')` on every nested Pydantic model.
- Re-implement the ObservationLog cross-field validator explicitly; add a unit test for the `state=None, notes=None` case.
- Validate `event_timestamp` as a string with an explicit regex or `datetime.fromisoformat()` with T-separator enforcement, not as a native Python `datetime`.
- Test `BLOCK_NAME_RE` with `re.fullmatch()`.

**Warning signs:**
- Parity-harness output diff shows fields the Node validator rejects that the Python one accepts.
- LLM emits bare dates (`2025-06-14`) for `event_timestamp` that sail through Python validation.
- Block names like `260522_SHI_1_extra` pass Python regex.
- Missing `additionalProperties: false` in the emitted JSON Schema causes the LLM to include unrequested fields stored silently in `draft_json`.

**Phase to address:**
Schema-parity phase (first phase of the port, before any LLM calls in Python). JSON Schema structural diff must be a hard gate.

---

### Pitfall 2: Idempotency / Upsert Key Drift -- ULID vs. UUID vs. Hex SHA

**What goes wrong:**
The Node codebase uses three distinct ID types across tables:
- `signal_capture.id` -- ULID (text, e.g. `01KS9HSSJZYC6QHNKFT8Y3RF1H`)
- `signal_draft.id` -- hex SHA (text, e.g. `f87eb1e0...`)
- `signal_outbound.id` -- UUID via `gen_random_uuid()` (Postgres-generated)

This is documented in `outbound-db.js`: "Plan-02 D-12 originally declared `related_*_id` as uuid, but `signal_capture.id` is a ULID (text) ... Postgres rejected every insert with `invalid input syntax for type uuid`; the `insertOutbound` fail-open mask hid the breakage until a live capture went through post-cutover."

The upsert-by-stable-identity in `merge.js` unions array-refs by `.id` field -- if the Python commit path generates a different stable identity hash for the same logical event (different field ordering, different serialization of floats, different null vs. absent handling), a re-run produces a duplicate farmOS asset instead of an idempotent patch.

JS `JSON.stringify` and Python `json.dumps` differ on: key ordering, float representation (JS `1.0` -> `"1"`, Python `json.dumps(1.0)` -> `"1.0"`), and `undefined` vs. `null` (JS omits `undefined`-valued keys; Python has no equivalent).

**Why it happens:**
Python's `uuid` module generates UUIDs, `python-ulid` generates ULIDs -- but these are not interchangeable with the Node formats. Naive SHA hashing of a dict depends on key insertion order and serialization, which are not guaranteed to match Node's `JSON.stringify` output.

**How to avoid:**
- Audit every table's PK type before starting the Python port. Write it down in a reference doc.
- For ULID generation: use `python-ulid` (`pip install python-ulid`) with `ULID()`.
- For the stable-identity hash (`signal_draft.id`): extract the Node hash function, write a cross-language fixture test -- same input JSON must produce the same hex digest from both Node and Python. Hash function, field ordering, and serialization must match exactly.
- For the farmOS upsert (port of `merge.js`): `unionArrayRef` by `.id` and `mergeNotes` by `STABLE_NOTES_SEPARATOR` (`\n---\n`) must be ported with the same whitespace semantics. Test with a real farmOS asset fetched via the Python client.
- The `IdentityMutationError` logic (name/type must never change on PATCH) must be preserved with the same field coverage.

**Warning signs:**
- A second run of the Python commit path creates a new farmOS asset instead of patching the existing one.
- `signal_outbound` insert failures logged (fail-open hides these -- check logs explicitly).
- `related_capture_id` or `related_draft_id` insertions fail silently (same uuid/text mismatch pattern as the historical bug).
- Duplicate seeding logs in farmOS for the same block_name on the same date.

**Phase to address:**
Idempotency phase -- before any farmOS writes go to prod. Must include a cross-language fixture test of the stable-identity hash and a round-trip test against farmOS dev.

---

### Pitfall 3: Shared-Prod-DB Leak During Validation Runs

**What goes wrong:**
The Timescale DB on elder-plops is shared between the live Node alerter (prod :8082 farmOS) and any shadow/validation stack. The Node commit-watchdog polls `signal_draft` for `status='confirmed'` every 30 seconds and drains ALL confirmed rows to prod farmOS -- it has no origin guard.

This already caused a real prod leak: backfill auto-confirmed drafts leaked 2025 data to prod farmOS because the live alerter drained them. The runbook assumption "dev DB != prod DB" was false.

During v1.12 validation (Python stack writing drafts, Node watchdog still live), any `confirmed` row the Python stack writes to the shared DB will be committed to prod farmOS by the live Node watchdog within 30 seconds -- even if the Python run was intended as a dry run.

**Why it happens:**
Big-bang rewrites validate the new stack by pointing it at the same infrastructure to "see if it works." The shared-DB drain hazard is not obvious until it fires. The fail-open DAO pattern means insert failures are logged but don't surface -- so the Python stack may be inserting rows the Node watchdog then commits, with no visible error anywhere.

**How to avoid:**
- Before any Python validation run against the shared TimescaleDB, confirm the Node commit-watchdog is stopped: `docker compose ps` on elder-plops, verify the alerter container is not running.
- Use a throwaway Postgres instance (`:5433`) for all validation runs -- same pattern as the backfill harness Option A. Never point the Python validation stack at the prod TimescaleDB.
- If the Python stack must read from prod TimescaleDB (e.g. for quote-threading lookups), it must only read, never write `signal_draft` rows with `status='confirmed'`.
- Add an `--allow-prod-write` opt-in flag to the Python stack (mirrors the backfill harness pattern); leave it off by default.
- The cutover sequence must be: stop Node alerter -> drain in-flight queue -> start Python alerter -> verify. There is no safe dual-run period on the shared DB.

**Warning signs:**
- 2025 or test data appearing in prod farmOS.
- `signal_draft` rows with `status='confirmed'` that were not farmer-confirmed.
- Node watchdog log shows unexpectedly high commit throughput.

**Phase to address:**
Pre-cutover validation phase. The throwaway-DB rule must be in the phase checklist. The cutover phase must specify the stop-Node / start-Python sequence with no overlap window.

---

### Pitfall 4: Timezone and Number Formatting Regressions in Farmer-Facing Messages

**What goes wrong:**
The Node alerter has a documented timezone bug since Phase 13: `hhmm()` renders UTC and ignores the configured TZ. The alerter TZ is stuck on America/Toronto despite the farm being in Uruguay (UYT, UTC-3). A Python port that faithfully reproduces the broken behavior will pass parity tests but continue delivering wrong times. A Python port that fixes TZ will fail parity tests even though it is correct.

Additional formatting risks:
- `fmtNum(n)` (1 decimal, strip trailing `.0`) -- Python `f"{n:.1f}"` does not strip trailing `.0` by default. `str(round(n, 1))` does strip it but can produce unexpected edge cases. The farmer-visible format must match exactly.
- em-dashes are forbidden in farmer-facing artifacts (universal LLM tell) -- Python f-strings or LLM prompt outputs may introduce them.
- Message body line endings: `\r\n` vs. `\n`. The Node stack uses `\n` exclusively.
- Humidity values are displayed as percentages (multiply by 100). The Node stack has places where this is implicit. A Python port that misses it produces "RH: 0.93%" instead of "93%".

**Why it happens:**
Formatting code is scattered across the Node codebase and often not unit-tested. Timezone handling in Python requires explicit `zoneinfo.ZoneInfo` and `datetime.now(tz)` -- naive `datetime.now()` silently produces local-system time which may be UTC on the elder-plops Docker container.

**How to avoid:**
- Document explicitly: TZ fix (Toronto -> `America/Montevideo`) is an intentional behavioral change, not a parity failure. Capture it as a known intentional delta before parity testing begins so parity tests are not miscounted as failures.
- Use `zoneinfo.ZoneInfo("America/Montevideo")` consistently; never use naive datetimes in farmer-message formatting paths.
- Port `fmtNum` as a unit-tested helper. Verify against the Node source: `fmtNum(1.0)` -> `"1"`, `fmtNum(93.0)` -> `"93"`, etc.
- Run a message-body snapshot test: take a real recent Signal capture, run it through the Node preview-builder, save the output, run the same input through the Python preview-builder, diff. Any whitespace/em-dash/number format difference is a bug.
- Enforce `\n` line endings. Do not use `os.linesep`.
- Add a pre-send lint that rejects outbound message bodies containing `--` (em-dash U+2014) or `--` (en-dash U+2013).

**Warning signs:**
- Parity snapshot diffs show time-of-day fields in wrong timezone.
- RH values appearing as `0.9x` instead of `9x%` in farmer messages.
- em-dashes in extraction previews or ask-back messages.
- Signal quote-reply timestamps wrong (ms-since-epoch vs. seconds-since-epoch confusion).

**Phase to address:**
Message-formatting parity phase. The TZ delta must be pre-accepted before parity testing. Snapshot tests of preview-builder output must be a ship gate.

---

### Pitfall 5: signal-cli Interop Differences -- Quote Threading, Attachment Handling, Send Attribution

**What goes wrong:**
The Node `signal.js` has documented complexity around group ID translation (`internal_id-b64` vs. `id-b64`), quote validation (timestamp may be a finite number OR a numeric string), and send attribution. A Python port risks three failure modes:

1. **Quote threading shape**: `isValidQuote` validates `{timestamp, author, message}` with `Number(q.timestamp)` coercion. A Python port using `int(q['timestamp'])` fails on string timestamps (`"1718000000000"`) if not explicitly coerced. The lock: `timestamp` is ms-since-epoch and may arrive as string; `author` is non-empty e164; `message` is string (empty allowed). Invalid shapes must fail-open (send without quote), not raise.

2. **Group ID translation**: The lazy `ensureGroupsLoaded` / `groupIdMap` pattern translates `internal_id` to `id-b64` at send time. A Python port that skips this and sends `internal_id` form to signal-cli `/v2/send` gets a 400 or silently drops the group message. The translation call hits `/v1/groups/{sender}` and must be cached to avoid hammering signal-cli on every send.

3. **Send attribution**: The memory note is explicit: "Verify Signal send attribution before attestation -- 91 chars = sht30, ~147 = pi+chamber-dark; reconstruct body, don't infer from timing." In the Python receive-loop, `envelope.source` must be read from envelope data, not inferred from message sequence or arrival order. An asyncio receive loop that processes envelopes with `gather()` or a task queue can silently misassign attribution.

4. **Attachment paths**: signal-cli downloads attachments to a local path. The Python receive-loop must wait for download completion before passing the path to the extractor. A loop that fires extraction immediately may race the download.

**Why it happens:**
signal-cli's REST API has quirks (group-id duality, string-vs-number timestamp) that are handled in one place in Node but must be re-learned in Python. asyncio's `gather()` is natural for concurrent message processing but breaks attribution ordering guarantees.

**How to avoid:**
- Port `isValidQuote` as a Python function with explicit isinstance + `int(str(ts))` coercion and the same fail-open behavior (send without quote on invalid shape, log warning).
- Port group ID translation as a lazy-cache Python async function. Test against the actual signal-cli `/v1/groups` response shape (not assumed from docs).
- In the asyncio receive-loop, process envelopes sequentially (one `await` per envelope), not with `gather()`. Parallelism can be added later for specific non-attribution-sensitive tasks.
- Add a `signal_msg_ts` roundtrip test: send a message from the Python stack, capture the `/v2/send` response `timestamp`, verify stored in `signal_outbound.signal_msg_ts` as a bigint.
- For attachment handling: verify `dataMessage.attachments[].localFilename` exists on disk before passing to extractor. Poll with a short timeout (signal-cli is fast) rather than assuming synchronous delivery.

**Warning signs:**
- Group messages get HTTP 400 from signal-cli or are silently not received by group members.
- Quote replies from farmer not matched to the correct draft (quote_msg_ts lookup returns null).
- Extraction fires on an attachment path that does not yet exist (empty transcript, extractor error).
- Attribution logged as `unknown` or wrong farmer for group-thread messages.

**Phase to address:**
Signal I/O phase -- before any LLM calls. Attribution and quote threading must pass a live-fire test (real signal-cli, real group message) before extraction wiring begins.

---

### Pitfall 6: asyncio Concurrency Model -- Watchdog and Outbound Queue Races

**What goes wrong:**
The Node watchdog (`confirm/watchdog.js`) uses `setInterval` + async callbacks. Node's event loop is single-threaded and cooperative -- even with `setInterval` and async functions, ticks are serialized because the event loop does not interrupt an in-progress `async` function. The Python equivalent using `asyncio.create_task()` + `asyncio.sleep()` can behave differently: `asyncio.gather()` or `create_task()` inside a callback can launch concurrent ticks.

A concurrent tick race means:
- Two ticks find the same `awaiting_farmer` row simultaneously.
- Both call `markNudgeSent()` -- the Node version has a `rowCount === 0` restart-race guard. The Python version must use the same conditional UPDATE pattern, not just check row existence.
- Result: duplicate nudge sends or duplicate expire messages to the farmer.

The outbound queue has an additional risk: `maxSendsPerHour` cap is enforced by an in-memory `sendHistory` array. A Python port with concurrent sends will have a race on this shared state unless protected by `asyncio.Lock`.

**Why it happens:**
Developers assume Node event-loop serialization semantics carry over to asyncio. They do for sequential `await` chains but not for `gather()` or `create_task()`.

**How to avoid:**
- Implement the watchdog as `while True: await asyncio.sleep(interval); await tick_once()` -- not as `asyncio.create_task(tick_once())` inside a scheduled callback.
- The `markNudgeSent` DB call must use a conditional UPDATE (`UPDATE ... WHERE nudge_sent IS FALSE RETURNING id`) and check `rowcount == 0` to abort on race -- same as the Node guard.
- Protect `sendHistory` / rate-cap state with `asyncio.Lock` if any concurrent send paths exist.
- Add a test that fires two concurrent `tick_once()` calls against the same DB row and verifies exactly one nudge is sent.

**Warning signs:**
- Duplicate nudge or expiry messages sent to farmer for the same draft.
- Rate cap exceeded (more sends than `maxSendsPerHour` within an hour) after cutover.
- DB constraint violations on `signal_outbound` from concurrent ticks.

**Phase to address:**
Watchdog + outbound queue phase. A concurrency unit test (two concurrent ticks against the same row) must be a ship gate.

---

### Pitfall 7: Datetime / Decimal / JSON Serialization Mismatches vs. Postgres Schema

**What goes wrong:**
Several Postgres column types require careful Python serialization:

- `signal_capture.captured_at` is `timestamptz`. `psycopg2` auto-converts `datetime` objects with tzinfo to timestamptz correctly. A naive `datetime.now()` (no tzinfo) is stored as local time -- on the elder-plops Docker container this is likely UTC, but is not guaranteed. The Node stack passes `new Date().toISOString()` (always UTC with `Z`). The Python equivalent is `datetime.now(timezone.utc).isoformat()`.

- `signal_outbound.signal_msg_ts` is `bigint` (ms-since-epoch). signal-cli returns this as a JSON number. Python `json.loads()` parses large integers correctly, but if the value flows through a `float` (e.g. `float(response['timestamp'])`) it loses precision at > 2^53. ms-since-epoch in 2026 is ~1.75e12, safely under 2^53 (~9e15), but this must be explicitly tested and the coercion must use `int()` not `float()`.

- `draft_json` is `jsonb`. Python `json.dumps()` of a dict containing `Decimal` fields raises `TypeError: Object of type Decimal is not JSON serializable`. If any field (e.g. `qty_g` for harvest) is extracted as `Decimal`, it must be coerced to `float` or `int` before `json.dumps()`.

- `attachment_paths` is `text[]`. `psycopg2` accepts a Python `list[str]` for an array column, but a list containing `None` inserts NULL elements. Filter `None` before inserting.

- The `notes` field in farmOS assets uses `{value, format}` shape (see `merge.js` `mergeNotes`). The Python port must serialize this as a JSON object, not a plain string. Storing `"some text"` instead of `{"value": "some text", "format": "plain_text"}` causes silent notes loss on the next merge.

**Why it happens:**
Python's type system and JSON serialization have no automatic conventions for these. `json.dumps()` is strict about unknown types. `psycopg2` has implicit conversions for datetime but TZ behavior depends on connection settings and is not obvious.

**How to avoid:**
- Use `datetime.now(timezone.utc)` everywhere, never `datetime.now()`. Set `psycopg2` connection option `options='-c timezone=UTC'` to enforce UTC at the connection level.
- Write a serialization fixture: serialize a representative draft (all field types) to JSON and back, then insert to a test DB with the same schema. Verify round-trip fidelity for bigint timestamps, array fields, nested JSON.
- Add a custom JSON encoder class that raises on unexpected types (never silently converts `Decimal` to string).
- Filter `None` from all `text[]` fields before insert.
- Test the `notes` field merge round-trip: create a farmOS asset via Python, patch it, fetch it back, verify `notes.value` and `notes.format` are correct.

**Warning signs:**
- `psycopg2 DataError: invalid input syntax for type timestamptz` on inserts.
- `TypeError: Object of type Decimal is not JSON serializable` during draft serialization.
- `signal_outbound` rows with `signal_msg_ts = NULL` when signal-cli returned a non-null timestamp.
- farmOS asset notes appearing blank after a Python commit.

**Phase to address:**
DB integration phase (before farmOS writes). A serialization fixture test must be a ship gate alongside the idempotency tests.

---

### Pitfall 8: Cutover / Rollback Risk with No Dual-Stack Fallback

**What goes wrong:**
The big-bang strategy means the Node alerter is stopped and the Python alerter is started in a single switch. There is no dual-stack period. Risks:

1. **In-flight drafts abandoned**: Any `awaiting_farmer` or `confirmed` rows in `signal_draft` at cutover time will be invisible to the Python stack unless it is designed to consume the existing schema. If the Python draft state machine uses different status strings or expects different `draft_json` shape, old rows will be skipped or error silently.

2. **Signal message loss during cutover gap**: signal-cli is independent -- messages arrive to the local socket regardless of which stack is running. If there is any gap between stopping Node and starting Python, messages that arrive in the gap are buffered by signal-cli but must be explicitly drained by the Python receive-loop on startup.

3. **Rollback requires schema compatibility**: If the Python stack writes new columns or new `draft_json` shapes that the Node stack does not understand, rolling back to Node means encountering unknown rows that the Node stack may error on or silently skip.

4. **No A/B comparison period**: The parity harness validates against the live corpus before cutover but cannot cover edge cases that arise in the first 48h of live traffic.

**Why it happens:**
Big-bang was chosen for simplicity (no dual-stack infrastructure). The risks are manageable but must be explicitly planned, not assumed to be handled by the parity gate alone.

**How to avoid:**
- Before cutover, enumerate all in-flight `signal_draft` rows. Decide explicitly: force-expire them or migrate them. Do not leave them in ambiguous state.
- Design the Python receive-loop to drain the signal-cli backlog on startup (verify signal-cli's WebSocket push delivers buffered messages automatically, or send an explicit receive command).
- Keep the Node stack's Docker image tagged and the compose file ready to revert. Document the rollback procedure: stop Python, start Node, verify watchdog draining. Target rollback time under 2 minutes.
- Add a `--dry-run` mode to the Python stack that processes messages and logs what it would do but writes nothing to DB or farmOS. Use this for the first 10 messages after cutover before switching to live mode.
- All schema additions from the Python stack must be additive-only (new columns with defaults, new optional fields in `draft_json`). No column renames or type changes that break Node compatibility.
- For the first 48h post-cutover, monitor `signal_draft` for `status='needs_review'` rows (messages the stack could not handle) and `signal_outbound` for zero-send gaps.

**Warning signs:**
- `signal_draft` rows from before cutover with `status='awaiting_farmer'` that are never processed.
- `signal_capture` rows with no corresponding `signal_draft` (messages received, extraction skipped).
- farmOS writes stop with no farmer-facing indication (watchdog silently erroring).
- First farmer message after cutover gets no reply within 60s (wiring seam broken).

**Phase to address:**
Cutover phase (final, separate from the validation/parity phase). The rollback procedure must be written and tested before cutover day.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Port fail-open DAO pattern without adding observability | Fast port, same error-masking behavior | Silent insert failures (the uuid-vs-ULID bug repeats); bugs ship to prod with no signal | Never -- add `logger.warning` and a counter on every fail-open path |
| Skip the JSON Schema diff, trust Pydantic "does the same thing" | Saves 1-2h | LLM emits off-schema fields; farmOS gets corrupt drafts | Never |
| Point Python validation at prod TimescaleDB to "see real data" | Convenient | Shared-prod-DB leak; 2025 data in prod farmOS | Never without Node watchdog confirmed stopped |
| Use naive `datetime.now()` | Saves an import | Wrong timestamps for UYT farmers; subtle TZ bugs on Docker containers | Never |
| Keep Toronto TZ to maintain parity with the broken Node behavior | Parity tests pass | Wrong times continue being sent to the farmer for another milestone | Never -- accept TZ fix as intentional delta, document it |
| Use `asyncio.gather()` for concurrent tick processing | Higher throughput | Watchdog races, duplicate nudges/expires | Only for read-only lookups, never for write paths |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| signal-cli `/v2/send` | Passing `internal_id` form of group ID directly | Translate via `/v1/groups/{sender}` lookup; cache the map |
| signal-cli quote threading | Treating `timestamp` as always an integer | Coerce with `int(str(ts))` -- may arrive as string or number |
| farmOS PATCH asset | Sending `notes` as a plain string | Send as `{"value": "...", "format": "plain_text"}` |
| farmOS image upload | POST to `/api/file/file` (returns 415) | POST to `/api/asset/{type}/{uuid}/image` with `Content-Type: application/octet-stream` |
| Postgres `timestamptz` | Inserting naive Python datetime | Always pass `datetime.now(timezone.utc)` or set connection `timezone=UTC` |
| Postgres `text[]` | Passing a list containing `None` | Filter: `[p for p in paths if p is not None]` |
| Anthropic tool use retry | Returning schema errors as a new `user` message | Return as `tool_result` with `is_error: true` and the correct `tool_use_id` |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Group ID translation on every send | signal-cli `/v1/groups` hammered; sends slow or rate-limited | Lazy-load + in-memory cache; invalidate on 404 | First send after startup if cache is cold |
| Synchronous Whisper transcription blocking the asyncio event loop | New Signal messages queue up; farmer waits minutes for reply | Run Whisper in a `ProcessPoolExecutor`; await with `loop.run_in_executor()` | First audio message after cutover |
| SEQ lookup scanning all `signal_draft` rows for a date | Slow commit path on large draft tables | Index on `draft_json->>'event_date'` (already in Node; verify ported and index exists) | After ~1000 draft rows |

## "Looks Done But Isn't" Checklist

- [ ] **JSON Schema parity:** Python Pydantic generates the same `additionalProperties: false` shape as Node Zod -- verified by structural diff of emitted schemas.
- [ ] **Stable-identity hash parity:** Same input produces the same hex digest from both Node and Python -- verified with a cross-language fixture test.
- [ ] **TZ fix documented as intentional delta:** Alerter TZ set to `America/Montevideo` (not Toronto) and marked as known behavioral difference, not a parity failure.
- [ ] **Fail-open paths are observable:** Every `except` block that returns `{ok: False}` instead of raising also logs at WARNING level.
- [ ] **Node watchdog confirmed stopped before any validation run:** `docker compose ps` on elder-plops confirms the alerter container is not running before Python writes any `signal_draft` row.
- [ ] **signal-cli group ID translation ported and tested:** Live group message from Python stack lands in the correct Signal group (not silently dropped).
- [ ] **In-flight draft disposition plan written:** All `awaiting_farmer` rows at cutover time are explicitly force-expired or migrated before Python starts.
- [ ] **Rollback procedure tested:** Node stack can be restarted from tagged image in under 2 minutes with no data loss.
- [ ] **Attachment download race guard:** Python extractor does not receive a path until signal-cli has confirmed the file exists on disk.
- [ ] **`fmtNum` snapshot tests pass:** Python formatting of edge cases (1.0, 1.15, 93.0) matches Node output character-for-character.

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| LLM schema drift ships to prod | HIGH | Roll back to Node; audit all `draft_json` rows written by Python for off-schema fields; clean up farmOS assets created from corrupt drafts |
| Shared-prod-DB leak | HIGH | Same as backfill leak: identify leaked rows by `captured_at` window; manually archive in farmOS; alert farmer |
| Duplicate farmOS assets (idempotency drift) | MEDIUM | Use farmOS admin to identify duplicates by asset name + date; delete extras; fix the stable-identity hash and re-run |
| TZ regression in farmer messages | LOW | Deploy TZ fix; no data cleanup needed (messages already sent cannot be unsent) |
| Watchdog race (duplicate nudges) | LOW | Farmer receives double message; add `asyncio.Lock` or conditional UPDATE guard; restart Python stack |
| Cutover gap (messages missed) | MEDIUM | signal-cli buffers missed messages; restart Python receive-loop; drain backlog; verify no messages dropped via signal-cli unread count |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| LLM schema drift (Zod->Pydantic) | Schema-parity phase (first phase of port) | Structural JSON Schema diff is clean; ObservationLog cross-field validator unit test passes |
| Idempotency / upsert key drift | Idempotency phase (before farmOS writes) | Cross-language stable-identity hash fixture; farmOS dev round-trip creates no duplicates on re-run |
| Shared-prod-DB leak | Pre-cutover validation phase | Compose `ps` shows Node alerter stopped; Python runs against throwaway `:5433` DB |
| TZ / number formatting regression | Message-formatting parity phase | Snapshot diff of preview-builder output clean (TZ delta pre-accepted as intentional) |
| signal-cli interop | Signal I/O phase | Live group message received, attributed, and replied to via Python stack |
| asyncio watchdog races | Watchdog phase | Concurrent-tick test: two simultaneous `tick_once()` calls produce exactly one nudge per row |
| Datetime / Decimal / JSON serialization | DB integration phase | Serialization fixture: all field types round-trip through Python encoder and Postgres schema |
| Cutover / rollback | Cutover phase | Rollback drill: Node restarted from tagged image in <2min; in-flight draft drain executed |

## Sources

- `src/agents/alerter/src/outbound-db.js` -- uuid-vs-ULID schema bug post-mortem (inline comment, 2026-05-23 hotfix)
- `src/agents/alerter/src/farmos/merge.js` -- upsert-by-stable-identity logic, notes merge semantics
- `src/agents/alerter/src/extraction/schemas/` -- Zod schema shapes for parity reference (seeding.js, observation.js, seeding-session.js, index.js)
- `src/agents/alerter/src/extraction/validator.js` -- ObservationLog cross-field refine pattern
- `src/agents/alerter/src/extraction/state-machine.js` -- draft lifecycle, REQUIRED_FIELDS map
- `src/agents/alerter/src/confirm/watchdog.js` -- setInterval tick pattern, restart-race guard
- `src/agents/alerter/src/signal.js` -- isValidQuote, group ID translation, rate-cap in-memory state
- `src/agents/alerter/src/capture-db.js` -- signal_capture schema, ULID id, column history
- `src/agents/alerter/src/extraction/seq-helper.js` -- SEQ lookup pattern, skip-on-error semantics
- Memory: [[project_backfill_confirmed_drafts_leak_to_prod_via_live_watchdog]] -- prod DB leak post-mortem
- Memory: [[project_alerter_tz_toronto_legacy]] -- TZ stuck since Phase 13
- Memory: [[feedback_unit_tests_dont_catch_wiring]] -- wiring seam hazard
- Memory: [[feedback_fail_open_masks_schema_bugs]] -- fail-open DAO pattern masks bugs
- Memory: [[project_backfill_extraction_fidelity_38pct_silent_misattribution]] -- POY-as-KOY silent misattribution
- Memory: [[feedback_compose_env_file_object_form_silently_drops]] -- compose env passthrough footgun
- Memory: [[project_node_cron_4x_breaks_non_utc_tz]] -- TZ-related prod outage
- Memory: [[project_phase55b_hard_gate_green_2026_06_14]] -- fidelity gate + image route fix
- Memory: [[project_farmos_image_upload_needs_field_scoped_route]] -- correct image upload route

---
*Pitfalls research for: v1.12 Farm-Agent Python Port (big-bang Node->Python rewrite)*
*Researched: 2026-06-14*
