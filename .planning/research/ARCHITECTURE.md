# Architecture: v1.12 Farm-Agent Python Port

**Domain:** Python rewrite of a live Node.js Signal/LLM/farmOS alerter agent with Foray OSS seams
**Researched:** 2026-06-14
**Confidence:** HIGH (derived directly from reading the live Node source; no speculation needed)

---

## Overview

The Node alerter is a single-process, event-driven agent with three concurrent
event sources that all funnel into one shared Postgres pool:

1. Signal-cli HTTP polling (receive loop -- farmer inbound messages)
2. WebSocket to the ROS bridge (chamber telemetry -- humidity/CO2/mode updates)
3. Scheduled watchdogs (confirm timeout nudges, commit drainer, heartbeat)

The Python port preserves this topology using `asyncio` as the event loop
instead of Node's libuv. All three event sources become coroutines scheduled
on a single event loop. No threads. No multiprocessing. One pool (asyncpg or
psycopg3 async).

The critical structural constraint is the Foray seam: the extractable slice
(signal I/O + extraction + confirm + farmos client + persistence + tenancy)
must form a dependency island that carries zero imports from the chamber side
(ROS bridge, state machine, heartbeat, sensor snapshot).

---

## System Overview

```
                         ┌────────────────────────────────────────────┐
                         │         FORAY EXTRACTABLE SLICE            │
                         │                                            │
   signal-cli REST  ───► │  signal_io/  ──► receive_loop.py          │
                         │                      │                    │
                         │                      ▼                    │
                         │              event_router.py              │
                         │               │           │               │
                         │               ▼           ▼               │
                         │        extraction/    confirm/             │
                         │        pipeline.py  state_machine.py      │
                         │               │           │               │
                         │               ▼           ▼               │
                         │         farmos_client/  persistence/      │
                         │         commit.py       repos.py          │
                         │                                            │
                         │         tenancy/   ◄── all modules above  │
                         │         tenant.py       read from here    │
                         └────────────────────────────────────────────┘
                                          │
                                          ▼
                              ┌──────────────────────┐
                              │   MUSHY-PRIVATE ONLY  │
                              │                       │
   ROS bridge WS  ─────────► │  bridge_client.py     │
                              │  chamber_state.py     │
                              │  alerter_state_machine│
                              │  (RH/sensor/pi/       │
                              │   humidifier alerts)  │
                              │  heartbeat.py         │
                              │  sensor_snapshot.py   │
                              └──────────────────────┘
                                          │
                                          ▼
                              ┌──────────────────────┐
                              │   SHARED INFRA        │
                              │                       │
                              │  asyncpg pool         │
                              │  Postgres/TimescaleDB │
                              │  Whisper HTTP client  │
                              │  Anthropic SDK        │
                              └──────────────────────┘
```

---

## Recommended Package Layout

```
src/agents/alerter-py/
├── alerter/                      # top-level package (pip-installable)
│   ├── __main__.py               # entrypoint: asyncio.run(main())
│   ├── boot.py                   # wire all components, start event loop
│   │
│   ├── tenancy/                  # FORAY -- tenant primitive (no other imports)
│   │   ├── __init__.py
│   │   ├── tenant.py             # TenantConfig dataclass + load(tenant_id, env)
│   │   └── loader.py             # load_tenant_file(tenant_id, filename)
│   │
│   ├── persistence/              # FORAY -- DB access layer (no business logic)
│   │   ├── __init__.py
│   │   ├── pool.py               # build_pool(config) -> asyncpg.Pool
│   │   ├── migrations.py         # run_migrations(pool) -- CREATE TABLE IF NOT EXISTS
│   │   ├── capture_repo.py       # signal_capture CRUD
│   │   ├── draft_repo.py         # signal_draft CRUD
│   │   ├── outbound_repo.py      # signal_outbound CRUD
│   │   └── commit_repo.py        # commit columns on signal_draft
│   │
│   ├── signal_io/                # FORAY -- signal-cli I/O only; no extraction logic
│   │   ├── __init__.py
│   │   ├── client.py             # SignalClient: send/receive/fetch_attachment
│   │   ├── router.py             # group/DM trigger detection, sender whitelist
│   │   └── receive_loop.py       # async poll loop -> yields Envelope
│   │
│   ├── extraction/               # FORAY -- multimodal extract -> draft
│   │   ├── __init__.py
│   │   ├── pipeline.py           # ExtractionPipeline: enqueue/run
│   │   ├── extractor.py          # Anthropic tool_use call + Zod-equiv Pydantic
│   │   ├── multimodal.py         # build_content_blocks(captures)
│   │   ├── state_machine.py      # pure: draft status transitions
│   │   ├── seq_helper.py         # SEQ mint per-session
│   │   ├── validator.py          # Pydantic schema validation + retry builder
│   │   ├── preview_builder.py    # farmer-facing text renderers
│   │   ├── event_gate/           # Haiku classifier + rule engine
│   │   │   ├── classifier.py
│   │   │   └── rules.py
│   │   └── schemas/              # Pydantic models (seeding, observation, etc.)
│   │       ├── seeding.py
│   │       ├── seeding_session.py
│   │       ├── observation.py
│   │       ├── harvest.py
│   │       ├── activity.py
│   │       ├── input.py
│   │       └── provenance.py
│   │
│   ├── confirm/                  # FORAY -- draft confirm/discard/edit loop
│   │   ├── __init__.py
│   │   ├── state_machine.py      # pure: awaiting_farmer transitions
│   │   ├── parser.py             # parse YES/NO/EDIT from farmer text
│   │   ├── outbound.py           # ConfirmOutbound: dispatch send_confirm_ack etc.
│   │   ├── edit_handler.py       # EDIT turn handler (re-extraction)
│   │   ├── watchdog.py           # async periodic: nudge/expire timed-out drafts
│   │   └── strain_ask_back.py    # strain-unknown intercept
│   │
│   ├── farmos_client/            # FORAY -- farmOS HTTP write path
│   │   ├── __init__.py
│   │   ├── client.py             # FarmosClient: session-cookie auth + retries
│   │   ├── assets.py             # asset get/create/patch
│   │   ├── logs.py               # log create
│   │   ├── files.py              # field-scoped image route (v1.11 fix)
│   │   ├── fungi_type_cache.py   # fungi_type term cache
│   │   ├── strain_resolver.py    # curated-code validation
│   │   ├── merge.py              # upsert-by-stable-identity
│   │   ├── audit_logger.py       # commit audit trail
│   │   ├── commit_watchdog.py    # async periodic: drain confirmed drafts
│   │   └── commits/              # per-type commit handlers
│   │       ├── router.py
│   │       ├── seeding.py
│   │       ├── seeding_session.py
│   │       ├── observation.py
│   │       ├── harvest.py
│   │       ├── activity.py
│   │       └── input.py
│   │
│   ├── capture/                  # FORAY -- inbound capture + transcription
│   │   ├── __init__.py
│   │   ├── pipeline.py           # CapturePipeline: handle(envelope)
│   │   ├── history.py            # CaptureHistory: recent-N context window
│   │   ├── retention.py          # async cron: expire old captures
│   │   └── transcribe_client.py  # Whisper HTTP client
│   │
│   ├── llm/                      # FORAY -- shared Anthropic client wrapper
│   │   ├── __init__.py
│   │   └── client.py             # LlmClient: chat reply (distinct from extractor)
│   │
│   ├── chamber/                  # MUSHY-PRIVATE -- ROS bridge + alerter state
│   │   ├── __init__.py
│   │   ├── bridge_client.py      # async WS client to Mission Control bridge
│   │   ├── state.py              # RH/sensor/pi/humidifier alert state machine
│   │   ├── rules.py              # isRhOob, isPiOffline, etc.
│   │   ├── heartbeat.py          # daily heartbeat scheduler
│   │   ├── sensor_snapshot.py    # HTTP fetch current sensor values from bridge
│   │   └── message.py            # alert message formatters
│   │
│   └── config.py                 # Config dataclass: load(env) with tenant layer
│
├── tests/
│   ├── unit/                     # pure module tests (no DB, no network)
│   ├── integration/              # real asyncpg pool against isolated DB
│   └── parity/                   # Node vs Python output comparison harness
│       ├── replay.py             # read-only replay from snapshot DB
│       ├── compare.py            # diff Node vs Python draft outputs
│       └── fixtures/             # captured Node outputs for regression
│
├── pyproject.toml
├── Dockerfile
└── docker-compose.override-py.yml   # runs the Python alerter alongside the old one
                                      # during parity validation (different ports, isolated DB)
```

---

## Dependency Direction

Strict one-way. No cycles.

```
config.py
    ^
    |
tenancy/  (reads config; emits TenantConfig)
    ^
    |
persistence/  (reads TenantConfig for tenant_id; no business-logic imports)
    ^
    |
signal_io/  (reads TenantConfig + persistence for outbound writes)
    ^
    |
capture/ + llm/ + extraction/  (reads signal_io + persistence + tenancy)
    ^
    |
confirm/  (reads extraction schemas + persistence + signal_io)
    ^
    |
farmos_client/  (reads confirm state, persistence, tenancy)
    ^
    |
chamber/  (reads signal_io + config; NEVER imports extraction/confirm/farmos_client)
    ^
    |
boot.py  (wires everything; the only file allowed to import from all packages)
```

The chamber/ package is the ONLY mushy-private package. Every package above
it in this diagram is part of the Foray extractable slice. The Foray boundary
is the horizontal line between `farmos_client/` and `chamber/`.

**Enforcement:** chamber/ has no __init__ re-export into the foray packages.
A grep for `from alerter.chamber` in any foray package is a CI gate failure.

---

## Where the Tenant Primitive Lives

`tenancy/tenant.py` defines `TenantConfig` and `load()`. It is the lowest
node in the dependency graph -- it imports nothing from the other packages.

```python
# tenancy/tenant.py (sketch)
@dataclass(frozen=True)
class TenantConfig:
    tenant_id: str
    signal_sender: str
    signal_recipient: str
    signal_group_id: str | None
    signal_farmer_map: dict[str, str]   # e164 -> slug
    farmos_url: str
    farmos_username: str
    farmos_integration: bool
    strains: list[str]
    event_gate_convo_mode: str
    # ... (mirrors config.js load() output)
```

`load(tenant_id, env)` applies the layered resolution: read
`tenants/<tenant_id>/config.yaml` + `strains.yaml` first, then env fallback,
then hardcoded defaults. Secrets (ANTHROPIC_API_KEY, FARMOS_PASSWORD,
SIGNAL_SENDER, TIMESCALE_PASSWORD) are env-only, never from tenant YAML.

For Foray, a tenant is a directory under `tenants/`. Clone `tenants/example/`
for a second tenant. The rest of the system reads only from the `TenantConfig`
object, not from env directly.

---

## Async Event Loop Organization

Single `asyncio` event loop in `boot.py`. No threads.

```
asyncio.run(main())
    |
    ├── asyncpg pool (shared connection pool)
    |
    ├── receive_loop()          -- asyncio.create_task
    |     polls signal-cli every RECEIVE_POLL_SEC seconds
    |     yields Envelope objects to event_router()
    |
    ├── bridge_loop()           -- asyncio.create_task  [chamber/ only]
    |     async WS client to Mission Control bridge
    |     yields telemetry events to chamber state machine
    |
    ├── periodic_tick()         -- asyncio.create_task  [chamber/ only]
    |     asyncio.sleep(30) loop
    |     fires 'tick' into chamber state machine (pi-offline + stuck detectors)
    |
    ├── confirm_watchdog()      -- asyncio.create_task  [foray]
    |     asyncio.sleep(DRAFT_WATCHDOG_INTERVAL_MS/1000) loop
    |     nudge/expire awaiting_farmer drafts
    |
    ├── commit_watchdog()       -- asyncio.create_task  [foray]
    |     asyncio.sleep(COMMIT_WATCHDOG_INTERVAL_MS/1000) loop
    |     drain confirmed drafts to farmOS
    |
    ├── retention_job()         -- asyncio.create_task  [foray]
    |     aiocron or asyncio.sleep-based cron
    |     expire old signal_capture rows
    |
    └── heartbeat_scheduler()   -- asyncio.create_task  [chamber/ only]
          checks clock at each tick, fires daily heartbeat at heartbeatHour
```

All tasks share the single asyncpg pool. All tasks use structured concurrency
(`asyncio.gather` with `return_exceptions=True`) so one crashed watchdog does
not bring down the receive loop.

The receive loop is the only place where Signal inbound messages are consumed.
It is a simple poll-sleep loop, not a streaming coroutine, which mirrors the
Node architecture exactly. Poll interval stays at 30s for battery/rate reasons.

---

## Integration Points

| Integration | Protocol | Python library | Notes |
|-------------|----------|---------------|-------|
| signal-cli daemon | HTTP REST | `httpx` (async) | /v1/receive, /v2/send, /v1/attachments; same API as Node |
| Postgres/TimescaleDB | TCP | `asyncpg` | async pool; mirrors node-postgres Pool |
| Whisper | HTTP REST | `httpx` | POST to /transcribe; 200s timeout preserved |
| Anthropic LLM | HTTPS | `anthropic` SDK (official) | tool_use for extraction; streaming not needed |
| farmOS | HTTP REST | `httpx` | session-cookie + X-CSRF-Token; same pattern as farmos_client.py |
| ROS bridge | WebSocket | `websockets` | WS reconnect with exponential backoff; chamber/ only |
| ROS bridge health | HTTP | `httpx` | /health poll for fc1LastMsgTs; chamber/ only |

`httpx` is the async equivalent of `requests`. The existing
`src/farmos-agent/farmos_agent/farmos_client.py` uses `requests` (sync);
the Python alerter uses `httpx.AsyncClient` everywhere so nothing blocks the
event loop.

---

## Parity Validation Harness (Prod-Timescale-Leak-Safe)

**The prod-leak problem:** The live Node commit-watchdog drains ALL
`status='confirmed'` rows from the shared Timescale every 30 seconds. Any
Python shadow process sharing that same DB will either (a) race the watchdog
and commit test drafts to prod farmOS, or (b) have its confirmed rows drained
by the Node watchdog before the Python commit path fires. Either outcome
corrupts the parity signal.

**Solution: isolated snapshot DB on a separate port.**

```
Parity validation topology:

  prod Postgres :5432          snapshot Postgres :5434
  (Node alerter live)          (Python alerter parity)
        |                              |
        |  pg_dump --schema-only       |
        |  + copy signal_draft/        |
        |    signal_capture rows       |
        └─────────────────────────────►│
          (one-time or nightly sync)   |
                                       |
                           Python alerter (parity mode)
                             TIMESCALE_PORT=5434
                             FARMOS_INTEGRATION=0   <- no farmOS writes
                             PARITY_MODE=1          <- emit diffs, not commits
                                       |
                                       ▼
                           parity/replay.py
                             read signal_capture rows
                             feed each capture to Python extraction
                             compare draft_json to Node's stored draft_json
                             emit diff report
```

The parity harness does NOT run the Python alerter as a live process. It runs
`parity/replay.py` as a batch script against the snapshot DB. The script:

1. Reads `signal_capture` rows from the snapshot (read-only; no writes to snapshot)
2. For each capture, calls the Python extraction pipeline in-process
3. Compares the Python `draft_json` output to the stored `signal_draft.draft_json`
   (which was written by the Node alerter)
4. Writes a diff report (JSONL, one entry per capture) to a local file
5. Exits 0 if diff rate is below the configured threshold (default: <5% field-level divergence)

The snapshot DB is created fresh with `pg_dump | psql` from a prod snapshot taken
at a specific timestamp, then left read-only. The Python process connecting to it
uses a read-only Postgres role that cannot INSERT or UPDATE.

This approach is identical to the Option A throwaway-pg pattern used during the
backfill ([[project_backfill_confirmed_drafts_leak_to_prod_via_live_watchdog]]).

---

## Chamber Watchdog Decoupling

The chamber alerting watchdogs (RH OOB, pi-offline, sensor-offline,
humidifier-stuck) depend on:
- The ROS bridge WebSocket (chamber telemetry)
- The chamber state machine (state.py, rules.py)
- The bridge health poller (sensor_snapshot.py)

None of these exist in Foray. The decoupling is enforced by:

1. `chamber/` is a sibling package to the foray packages, not a parent or child.
2. No foray package imports from `chamber/`.
3. `boot.py` wires the chamber event sources to the chamber state machine
   separately from the foray event sources.
4. The chamber state machine's output (alert send actions) uses the same
   `SignalClient` instance as the foray receive loop, but only via the
   `boot.py`-injected reference, never via a direct import.

In the future Foray repo, `chamber/` is simply absent. The `boot.py` in Foray
does not start `bridge_loop()`, `heartbeat_scheduler()`, or `periodic_tick()`.

---

## Safe Big-Bang Cutover Sequence

The cutover is a container swap: Node alerter container stops, Python alerter
container starts, pointing at the same Postgres.

**Pre-conditions (all must hold before flip):**
- Parity harness passes (<5% field divergence on the live corpus snapshot)
- Python alerter runs cleanly in a staging compose profile for 30 minutes
  with FARMOS_INTEGRATION=0 (no farmOS writes, but DB reads/writes active)
- No in-flight `status='awaiting_farmer'` or `status='confirmed'` drafts in prod
  (drain or manually expire them -- check with a SELECT before flip)

**Cutover steps:**

1. **Drain the Node outbound queue.** Wait for `signal_outbound` rows with
   `sent_at IS NULL` to reach zero, or force-drain with a manual trigger.

2. **Stop Node alerter.** `docker compose stop alerter`. The commit-watchdog
   stops. The receive loop stops. No more Signal polling.

3. **Verify quiescence.** `SELECT COUNT(*) FROM signal_draft WHERE status IN
   ('confirmed', 'awaiting_farmer')` should be 0. If not, wait 30 more seconds
   or manually inspect.

4. **Start Python alerter.** `docker compose up -d alerter-py`. The Python
   boot sequence runs migrations idempotently (all `CREATE TABLE IF NOT EXISTS`,
   all `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`). The Python alerter connects
   to the same Postgres pool and resumes where the Node alerter left off.

5. **Smoke test.** Send a test Signal message from f1. Verify it appears in
   `signal_capture`. Verify extraction fires. Verify preview arrives via Signal.

6. **Remove old Node alerter service** from compose after 24h of clean Python
   operation.

**Config-flag gate (PYTHON_ALERTER=1):** Not needed for a big-bang cutover.
The compose service name is the gate -- `alerter` vs `alerter-py`. Keep both
service definitions in the compose file for the 24h observation window, but
only one runs at a time.

**Rollback:** `docker compose stop alerter-py && docker compose start alerter`.
The Node alerter picks up from Postgres state. Any drafts created by the Python
alerter during the observation window are compatible (same schema). The Node
watchdogs will drain them correctly.

---

## Build Order (Respects Dependencies)

Each phase builds on the previous. Integration points are tested before the
layer that depends on them.

```
Phase 1: Foundation
  - tenancy/ (TenantConfig, load, layered YAML/env resolution)
  - persistence/ (asyncpg pool, all migrations, all repos)
  - config.py (full env load, mirrors config.js, includes all knobs)
  Verify: pytest unit tests; run migrations against a test DB

Phase 2: Signal I/O
  - signal_io/client.py (send, receive, fetch_attachment, group id translation)
  - signal_io/router.py (whitelist, group trigger detection, quote resolution)
  - signal_io/receive_loop.py (async poll loop)
  Verify: integration test with real signal-cli (or httpx mock)

Phase 3: Capture + Transcription
  - capture/transcribe_client.py (Whisper HTTP)
  - capture/history.py
  - capture/pipeline.py (handle -> insert signal_capture, transcribe, LLM reply)
  - capture/retention.py
  - llm/client.py (Anthropic chat reply, not extractor)
  Verify: send a voice note, confirm signal_capture row + transcript

Phase 4: Extraction Pipeline
  - extraction/schemas/ (Pydantic models for all log types)
  - extraction/validator.py
  - extraction/multimodal.py
  - extraction/extractor.py (Anthropic tool_use)
  - extraction/event_gate/ (Haiku classifier + rules)
  - extraction/state_machine.py (pure)
  - extraction/seq_helper.py
  - extraction/preview_builder.py
  - extraction/pipeline.py
  Verify: parity harness Phase A (extraction output vs stored Node drafts)

Phase 5: Confirm Loop
  - confirm/parser.py (YES/NO/EDIT)
  - confirm/state_machine.py (pure)
  - confirm/outbound.py
  - confirm/edit_handler.py
  - confirm/strain_ask_back.py
  - confirm/watchdog.py (async periodic)
  Verify: send YES to a pending draft; verify signal_draft.status='confirmed'

Phase 6: farmOS Commit Path
  - farmos_client/client.py (session-cookie, retries, httpx)
  - farmos_client/assets.py, logs.py, files.py
  - farmos_client/fungi_type_cache.py, strain_resolver.py
  - farmos_client/merge.py (upsert-by-stable-identity)
  - farmos_client/audit_logger.py
  - farmos_client/commits/ (all per-type handlers)
  - farmos_client/commit_watchdog.py
  Verify: confirm a seeding draft; verify seeding log appears in dev farmOS

Phase 7: Chamber Alerter (Mushy-Private)
  - chamber/bridge_client.py (async WS + reconnect)
  - chamber/state.py + chamber/rules.py (RH/sensor/pi/humidifier)
  - chamber/heartbeat.py
  - chamber/sensor_snapshot.py
  - chamber/message.py
  Verify: induce fc-core stop; verify pi-offline alert fires via Signal

Phase 8: Parity Harness + Cutover Gate
  - tests/parity/replay.py (batch replay against snapshot DB)
  - tests/parity/compare.py (field-level diff)
  - parity gate: <5% divergence on live corpus snapshot
  Verify: parity harness passes; then execute cutover sequence

Phase 9: Cutover + Observation Window
  - Drain Node queue, stop Node alerter, start Python alerter
  - 24h observation with rollback option
  - Remove Node alerter service after observation passes
```

---

## New vs Modified Components

| Component | Status | Notes |
|-----------|--------|-------|
| `tenancy/` | New | Replaces `config.js` tenant layer; Foray-first |
| `persistence/` | New | Replaces 5 separate `*-db.js` files; asyncpg |
| `signal_io/` | New | Replaces `signal.js` + `receive-loop.js` |
| `extraction/` | New | Port of `extraction/*.js`; Pydantic replaces Zod |
| `confirm/` | New | Port of `confirm/*.js`; includes Phase-50 quote fixes |
| `farmos_client/` | New | Port of `farmos/*.js` + `farmos_agent/farmos_client.py`; httpx |
| `capture/` | New | Port of `capture.js`, `capture-db.js`, `transcribe-client.js` |
| `chamber/` | New | Port of `bridge-client.js`, `state.js`, `rules.js`, `heartbeat.js` |
| `config.py` | New | Port of `config.js` |
| Postgres schema | Unchanged | Same tables; Python runs idempotent migrations on boot |
| `tenants/` directory | Unchanged | Same YAML structure; no migration needed |
| signal-cli daemon | Unchanged | External; not part of this port |
| `src/farmos-agent/` | Unchanged | Remains; Python alerter does NOT replace it |
| `src/agents/alerter/` | Retired | Removed after 24h observation window passes |

---

## Key Architectural Decisions

**asyncio over threading:** The Node alerter is single-threaded with a libuv
event loop. asyncio is the direct Python equivalent. Using threads would
introduce lock complexity with no benefit -- all I/O is network/DB, none is
CPU-bound.

**asyncpg over psycopg2:** asyncpg is the correct async Postgres driver for
asyncio (native protocol, no sync wrappers). psycopg3 is also async-capable
but asyncpg has more production usage at this scale.

**httpx over aiohttp:** httpx has a requests-compatible API, which mirrors the
existing `farmos_client.py` pattern closely. Less boilerplate for session
management.

**Pydantic v2 over Zod:** Direct Python equivalent. JSON Schema generation is
built in (needed for Anthropic tool_use input_schema). Pydantic v2's
`model_json_schema()` replaces `zodToJsonSchema()`.

**Single process, no worker queue:** The Node alerter uses no worker queue
(no Redis, no Celery). The Python port stays the same. The commit watchdog
IS the queue: it drains `status='confirmed'` rows on an interval. This
simplicity is correct for the current scale (one farm, ~3 farmers).

**Foray seam enforced by package structure, not runtime flag:** There is no
`FORAY_MODE` env var. The seam is structural -- `chamber/` is a separate
package with no downstream dependents in the foray slice. The Foray extraction
is a filesystem operation (delete `chamber/`, delete chamber imports from
`boot.py`), not a code path switch.

---

## Sources

- Live source: `/mnt/slime-kingdom/opt/mushy/src/agents/alerter/src/` (read 2026-06-14)
- Precedent: `/mnt/slime-kingdom/opt/mushy/src/farmos-agent/` (async patterns, farmOS client shape)
- SEED-010: `.planning/seeds/SEED-010-foray-oss-extraction.md` (what lifts out vs stays)
- PROJECT.md: `.planning/PROJECT.md` (v1.12 strategy decisions locked 2026-06-14)
- Memory: `project_backfill_confirmed_drafts_leak_to_prod_via_live_watchdog` (Option A pattern)

---
*Architecture research for: v1.12 Farm-Agent Python Port*
*Researched: 2026-06-14*
