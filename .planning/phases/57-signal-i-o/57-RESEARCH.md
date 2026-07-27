# Phase 57: Signal I/O - Research

**Researched:** 2026-06-15
**Domain:** 1:1 behavior-preserving port of the live Node alerter's Signal send/receive layer (`signal.js` + `receive-loop.js` + `outbound-db.js` + the farmer-map/`(unassigned)` routing) into the Python `signal_io/` package, gated by a Phase-64 parity check.
**Confidence:** HIGH (transport decision empirically verified from live source + compose + signal-cli-rest-api mode semantics; all other findings grounded in committed code and prior in-repo research)

## Summary

This phase ports the Node alerter's Signal I/O layer to Python `signal_io/`, preserving behavior for the Phase-64 parity gate. The single dominant question — what transport to use — resolves decisively in favor of **porting `fetch()` → `httpx.AsyncClient` 1:1 against the same `bbernhard/signal-cli-rest-api` HTTP container.** The ROADMAP/SIG-01 "JSON-RPC UNIX socket" language and STACK.md's "Option A (raw socket)" recommendation are both built on a factually wrong premise: STACK.md asserts "the existing Node alerter already uses the JSON-RPC socket," but the live alerter uses HTTP `fetch()` against `/v2/send`, `/v1/receive`, `/v1/groups`, `/v1/attachments`, `/v1/accounts` on `http://signal-cli:8080` (verified in `signal.js` and `docker-compose.override.yml`). Switching to a socket/WS transport is not merely non-parity risk — it is **incompatible with the running container configuration**: the compose service runs `MODE=normal`, which makes `/v1/receive` an HTTP GET endpoint. A raw JSON-RPC socket or WS receive would require `MODE=json-rpc`, which (per upstream) **disables HTTP GET `/v1/receive` and disables device registration** — a hard blocker, not a tradeoff. ARCHITECTURE.md (the broader research doc) already lists signal-cli as "HTTP REST / httpx" and PITFALLS.md already references the REST endpoints; only STACK.md's standalone "Interop Decision" section retains the stale Option-A premise. It should be treated as superseded.

The port is near-mechanical: `signal.js` is ~234 LOC in a single factory. The five success criteria map to five concrete, already-understood mechanisms (bigint coercion via `int()`, `/v1/groups` lazy-cache translation, quote primitive with `int(str(ts))` fail-open, `asyncio.Lock`-guarded rate-cap, farmer-map `(unassigned)` resolution). Phase 56 already created the `signal_outbound` table (additive migrations) and locked **psycopg3** (D-01) over ARCHITECTURE.md's asyncpg lean — the planner must use psycopg3, not asyncpg, for the `signal_outbound` write.

**Primary recommendation:** Port `fetch → httpx.AsyncClient` 1:1 against the existing `signal-cli-rest-api` HTTP container (`MODE=normal`, HTTP GET long-poll receive). Do NOT switch transports. Lock this as the resolution of D-01. Treat STACK.md's Option A as superseded by the verified live topology.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-02 (Outbound durability, SIG-02):** Persist-after-send, 1:1. Send first, then write the `signal_outbound` row (incl. `signal_msg_ts` from the send response) best-effort / fail-open — an outbound-insert failure NEVER affects the send return value or throws. No persist-first "pending → sent" queue in this phase. Cross-phase flag: Phase 65 cutover "drain" reduces to a sanity check (no drainable queue exists by design).
- **D-04 (Rate-cap state, SC#4):** In-memory `sendHistory` list of ms-timestamps pruned to the last hour, guarded by an `asyncio.Lock` so two concurrent `send` coroutines cannot exceed `maxSendsPerHour`. Cap resets on restart (matches Node). The dynamic-cap `getMaxSendsPerHour` hook (Tier-C `alerter_globals.max_sends_per_hour`) ports as-is. NOT DB-derived.
- **D-05 (Quote primitive, SIG-04):** Phase 57 ports the intent-agnostic quote primitive in `signal_io`: any caller may pass `quote={timestamp, author, message}`; `timestamp` coerced via `int(str(ts))`; valid-shape check (`isValidQuote`); fail-open to unquoted send + `warn` log on invalid shape (never throw, never silently drop). Verbatim port of `signal.js`'s `isValidQuote` + `payload.quote` logic. Phase-50 wire-level fixes folded in.

### Claude's Discretion
- **D-01 (Transport):** Explicitly deferred to planning/research with the REST→httpx default stated. **This research resolves it: port REST→httpx, do not switch.** (See Transport Decision section.)
- **D-03 (Receive model):** Follows D-01 transport. Default = long-poll `/v1/receive?timeout=1`. Resolved: long-poll, since D-01 lands on REST.
- Group-ID `internal_id`↔`id-b64` translation (lazy-load `/v1/groups`, cache, force-refresh-once-on-miss) ports as-is from `ensureGroupsLoaded` — no decision needed.
- Recipient encoding for `signal_outbound.recipient_e164` (1:1 = `+NNN`; group = `group:<id-b64>` prefix, the Phase-44 path-b decision) ports verbatim.

### Deferred Ideas (OUT OF SCOPE)
- **Quote-threading coverage expansion to `extraction_preview` + `ask_back`** — Phase 57 ships only the intent-agnostic quote *primitive* (D-05). The wiring of these two intents (and the new `ask_back` resolver) lives in `confirm/outbound-confirm.js` and carries forward to the confirm-path port phase. NOT a Phase 57 deliverable despite the todo's `resolves_phase: 57` tag.
- **Persist-first durable outbound queue** (true pending→sent lifecycle with retry/drain): not needed for parity; revisit only if a future phase needs crash-safe re-send.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SIG-01 | Python sends and receives Signal messages via signal-cli (same compose topology), including attachment fetch, with send attribution verified by round-trip (not inferred from timing). | Transport Decision: port `fetch→httpx` against the live REST container. `send`/`receive`/`fetch_attachment`/`accounts` map 1:1 (Code Examples). Attribution = read `envelope.source` directly, process envelopes sequentially (not `gather()`) — PITFALLS #5/#6. NOTE: SIG-01 text says "JSON-RPC UNIX socket"; this is contradicted by the live topology — see Transport Decision; "same compose topology" is satisfied by REST→httpx, NOT by a socket. |
| SIG-02 | Outbound sends persisted to `signal_outbound` (durable) and rate-capped; rate-cap history concurrency-safe under asyncio. | D-02 persist-after-send fail-open (verbatim from `signal.js` lines 158-197). `signal_msg_ts` bigint coercion (SC#1, see Pitfall: bigint). `asyncio.Lock`-guarded rate-cap (D-04, SC#4). Table already exists (Phase 56). |
| SIG-03 | Envelope routing reproduces multi-farmer behavior — replies to `envelope.source`; DM vs group distinguished; group-ID `internal_id`↔`id` translation ported (no silent drops); unknown numbers tagged `(unassigned)`, never dropped. | Group translation = `ensureGroupsLoaded` lazy-cache (Code Examples). DM-vs-group + sender whitelist = `receive-loop.js` `tick()`. `(unassigned)` = farmer-map `.get(source) ?? '(unassigned)'` — see Scope Boundary note (currently in `capture.js`, but the *farmer-map resolution primitive* belongs in `signal_io/router.py`). |
| SIG-04 | Native quote threading on outbound acks, Phase-50 fixes folded in (`quote.timestamp` coerced via `int(str(ts))`, fail-open on invalid shape); verified live. | D-05 quote primitive. `isValidQuote` shape check + `Number()`→`int(str(ts))` coercion + fail-open warn (verbatim from `signal.js` lines 71-131). Quote payload shape `{timestamp,author,message}` empirically accepted by signal-cli REST 0.14.2 (Phase 50 spike). |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Signal send/receive transport | `signal_io/client.py` (SignalClient) | — | Wire-level I/O against the REST container; sole choke-point per Phase-37 D-01 |
| Outbound durable persistence | `persistence/outbound_repo.py` | `signal_io/client.py` (calls it fail-open) | DB writes live in persistence/; signal_io calls the repo but never owns DDL |
| Rate-cap state | `signal_io/client.py` (in-memory + asyncio.Lock) | — | In-process state, matches Node `sendHistory`; resets on restart |
| Group-ID translation | `signal_io/client.py` (lazy `/v1/groups` cache) | — | Wire-level concern; cache is per-client-instance like Node |
| Quote primitive | `signal_io/client.py` (`isValidQuote` + payload build) | — | Intent-agnostic; callers pass `quote=` opt; wiring deferred (confirm-path phase) |
| Envelope routing / whitelist / DM-vs-group | `signal_io/router.py` + `receive_loop.py` | — | Source extraction, trigger detection, sender whitelist |
| `(unassigned)` farmer-map resolution | `signal_io/router.py` (the primitive) | `capture/pipeline.py` (Phase 58 *consumer*) | SC#5 requires the tagging primitive HERE; the capture-row write that uses it is Phase 58. See Scope Boundary. |
| TenantConfig (sender/recipient/group/farmer-map/maxSends) | `tenancy/tenant.py` (Phase 56) | `signal_io/*` reads it | Config primitive is lowest in dep graph; signal_io consumes, never reads env directly |

## The Transport Decision (resolves D-01 — the central research task)

### What the Node alerter ACTUALLY uses (verified empirically)

`signal.js` reaches signal-cli exclusively via `fetch()` against HTTP REST endpoints on `apiUrl` (= `SIGNAL_API_URL` = `http://signal-cli:8080` per `config.js:132` and compose `:90`):

| Operation | Endpoint | Method | signal.js line |
|-----------|----------|--------|---------------|
| Send | `${apiUrl}/v2/send` | POST JSON | `:136` |
| Receive | `${apiUrl}/v1/receive/{sender}?timeout=N&ignore_attachments=B` | GET | `:206` |
| Groups | `${apiUrl}/v1/groups/{sender}` | GET | `:25` |
| Attachment | `${apiUrl}/v1/attachments/{id}` | GET (arrayBuffer) | `:213` |
| Accounts | `${apiUrl}/v1/accounts` | GET | `:221` |

`[VERIFIED: src/agents/alerter/src/signal.js]` — There is NO socket, NO `StreamReader`, NO JSON-RPC framing anywhere in the Node Signal layer.

The container is `bbernhard/signal-cli-rest-api:0.200-dev` with `MODE=normal` `[VERIFIED: docker-compose.override.yml:43-57]`. The compose comment itself documents the constraint: *"MODE=normal: /v1/receive is HTTP GET (not WebSocket). Required for receive-loop HTTP polling. Primary registration required (device_id=1); linked-secondary cannot use /v1/receive."*

### Why STACK.md Option A is wrong

STACK.md §"The signal-cli Interop Decision" recommends "Option A: Raw JSON-RPC over UNIX socket" with the stated rationale (line 59): *"The existing Node alerter already uses the JSON-RPC socket. This preserves the deployment topology... exactly."* **This is factually false.** The Node alerter uses the REST HTTP container, not a raw socket. The raw UNIX socket is `signal-cli daemon` — a *different* deployment (different image/mode) that the repo does not run. `[VERIFIED: signal.js + compose contradict STACK.md:59]`

Corroborating: ARCHITECTURE.md (same research batch, `c702eea`) line 320 already lists the integration as **"signal-cli daemon | HTTP REST | httpx (async) | /v1/receive, /v2/send, /v1/attachments; same API as Node"** — i.e., the broader research already landed on REST→httpx. PITFALLS.md §Integration Gotchas references `/v2/send` and `/v1/groups/{sender}` directly. **Only STACK.md's standalone Option-A section retains the stale premise; it is superseded.** `[CITED: .planning/research/ARCHITECTURE.md:320]`

### Why switching transports is a hard blocker, not just risk

Switching to a raw JSON-RPC socket or WebSocket receive requires the container to run `MODE=json-rpc`. Per upstream: in `MODE=json-rpc`, *"it's no longer possible to poll for incoming messages via the HTTP GET receive endpoint — you must use websockets,"* and *"Registering, verifying and linking devices only works in normal/native mode."* `[CITED: github.com/bbernhard/signal-cli-rest-api discussions #160/#361]` The Mossrock account is a primary registration (device_id=1) that depends on `MODE=normal` for `/v1/receive` and registration. Flipping the mode to enable a socket transport would:
1. Break HTTP GET `/v1/receive` (the entire receive loop), forcing a WS rewrite — pure non-parity surface.
2. Break the device registration / identity-trust posture (the Phase-36 `post-rebuild-trust-check.sh` healthcheck).
3. Affect the live Node `alerter` and `bridge` services, which share the same `signal-cli` container during the coexistence window (both reach `signal-cli:8080` / `localhost:8085`).

There is no parity-worth-it upside. The whole point of Phase 64 is to prove behavioral equivalence; a transport switch maximizes the diff surface for zero functional gain at this scale (one farm, ~3 farmers, 30s poll).

### Recommendation (unambiguous — planner may lock as D-01 resolution)

**Port `fetch()` → `httpx.AsyncClient` 1:1 against the existing `signal-cli-rest-api` HTTP container at `http://signal-cli:8080`, keeping `MODE=normal` and HTTP GET long-poll receive (`/v1/receive/{sender}?timeout=1`). Do NOT switch transports. Do NOT introduce a raw socket, WS, signalbot, or DBus path.** "Same compose topology" (SIG-01) is satisfied literally by the REST container — NOT by a socket. The `alerter-py` service already joins `signal-net` alongside `signal-cli` `[VERIFIED: docker-compose.override.yml:175-221]`, so no new Signal infra is needed.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python | 3.12 | Runtime | `python:3.12-slim-bookworm` base, asyncio native. `[CITED: STACK.md]` |
| asyncio (stdlib) | built-in | Async event loop + `asyncio.Lock` for rate-cap | Direct equivalent of Node libuv loop; single-process. `[CITED: STACK.md/ARCHITECTURE.md]` |
| httpx | 0.28.1 | Async HTTP client to signal-cli REST | Replaces Node `fetch()`; `httpx.AsyncClient` maps 1:1 onto fetch calls; requests-compatible API. `[ASSUMED]` (version from STACK.md PyPI check 2026-06-14; not re-verified this session) |
| psycopg (with [binary]) | 3.3.4 | Postgres driver for `signal_outbound` write | **Phase 56 D-01 LOCKED psycopg3** over ARCHITECTURE.md's asyncpg lean. Use `AsyncConnectionPool`. `[CITED: 56-CONTEXT.md D-01]` |
| psycopg-pool | 3.3.1 | Async connection pool | Required for `AsyncConnectionPool`; major version must match psycopg. `[CITED: STACK.md]` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest + pytest-asyncio | 9.1.0 / 1.4.0 | Async test runner | `asyncio_mode = "auto"` in pyproject. `[CITED: STACK.md]` |
| ruff | 0.15.17 | Lint + format | `[CITED: STACK.md]` |

### Alternatives Considered (and rejected for this phase)
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| httpx REST | raw asyncio JSON-RPC socket (STACK.md Option A) | REJECTED: not the live topology; requires `MODE=json-rpc` which breaks HTTP receive + registration. Hard blocker. |
| httpx REST | signalbot 1.2.2 | REJECTED: framework abstraction fights envelope-level control; still needs the REST sidecar. |
| httpx REST | DBus (pydbus) | REJECTED: Docker-hostile; not the existing stack's approach. |
| httpx | aiohttp | Either works; httpx chosen for requests-compatible API and consistency with farmos_client. |
| psycopg3 | asyncpg (ARCHITECTURE.md lean) | REJECTED: Phase 56 D-01 locked psycopg3 for repo-wide idiom continuity with farmos-agent. |

**Installation:** Already covered by Phase 56's `pyproject.toml` (httpx + psycopg already declared in STACK.md's dependency list). No new install in this phase.

**Version verification note:** httpx 0.28.1 / psycopg 3.3.4 were verified live from PyPI on 2026-06-14 in STACK.md but could NOT be re-verified this session (sandbox has no pip network access). Tagged `[ASSUMED]` accordingly — the planner should `pip index versions httpx psycopg` before pinning if drift matters, but since Phase 56 already pinned them this is moot for Phase 57.

## Package Legitimacy Audit

> No NEW external packages are installed in this phase. `httpx`, `psycopg`, `psycopg-pool` were introduced and pinned in Phase 56. slopcheck not run (no new install surface).

| Package | Registry | Disposition |
|---------|----------|-------------|
| httpx | PyPI | Pre-existing (Phase 56); widely-used (Encode project, same authors as Starlette/uvicorn); no Phase-57 install |
| psycopg / psycopg-pool | PyPI | Pre-existing (Phase 56); official successor to psycopg2; no Phase-57 install |

**Packages removed due to slopcheck [SLOP] verdict:** none (no new installs)
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```
  Signal app (farmer phone)
        │  ▲
        ▼  │
  ┌─────────────────────────────────────┐
  │  signal-cli-rest-api container       │   MODE=normal
  │  (bbernhard/...:0.200-dev)           │   on signal-net @ signal-cli:8080
  └─────────────────────────────────────┘
        ▲  │ HTTP REST (httpx.AsyncClient)
        │  ▼
  ┌──────────────────────────────────────────────────────────┐
  │  signal_io/  (Foray island package)                       │
  │                                                            │
  │   receive_loop.py ──poll──► GET /v1/receive?timeout=1     │
  │        │  (sequential, NOT gather() — attribution)        │
  │        ▼                                                   │
  │   router.py: source extract ─► whitelist gate             │
  │        │      DM-vs-group, group-trigger detect            │
  │        │      farmer_map.get(source) ?? '(unassigned)'    │
  │        ▼                                                   │
  │   dispatch(envelope) ──► [Phase 58+ consumers]            │
  │                                                            │
  │   client.py SignalClient.send(body, {to, quote, ...})    │
  │        │  1. asyncio.Lock: prune + cap check              │
  │        │  2. resolve target (str | {groupId})            │
  │        │  3. ensure_groups_loaded() → translate id        │
  │        │  4. build payload (+ optional valid quote)       │
  │        │  5. POST /v2/send                                │
  │        │  6. push now into sendHistory (under lock)       │
  │        │  7. fail-open persist row ──────────┐            │
  └────────────────────────────────────────────┼────────────┘
                                                 ▼
                              persistence/outbound_repo.py (psycopg3)
                              INSERT signal_outbound (signal_msg_ts = int(ts))
```

### Recommended Project Structure (from ARCHITECTURE.md, Phase 56 scaffold)
```
src/farm-agent/alerter/
├── signal_io/                # FORAY island; no chamber imports
│   ├── client.py             # SignalClient: send / receive / fetch_attachment / accounts
│   │                         #   + ensure_groups_loaded, is_valid_quote, rate-cap+Lock
│   ├── router.py             # whitelist, DM-vs-group, group-trigger detect,
│   │                         #   farmer_map → (unassigned) resolution primitive
│   └── receive_loop.py       # async poll loop -> dispatch(envelope)
├── persistence/
│   └── outbound_repo.py      # insert_outbound (already has table from Phase 56)
└── tenancy/tenant.py         # TenantConfig (Phase 56): sender/recipient/group/farmer_map/max_sends
```

### Pattern 1: Single send choke-point with per-call target override
**What:** All sends route through one `send(body, opts)`; `opts.to` overrides the constructor `default_target`; target may be a `str` phone OR `{"groupId": ...}`. (Phase 37 D-01.)
**When:** Every outbound. Preserve verbatim.
```python
# Source: signal.js:82-97 (port)
target = opts.to if opts.to is not None else effective_default
is_string_target = isinstance(target, str) and len(target) > 0
is_group_target = isinstance(target, dict) and isinstance(target.get("groupId"), str) and target["groupId"]
if not is_string_target and not is_group_target:
    raise ValueError("invalid send target")
```

### Pattern 2: asyncio.Lock-guarded rate-cap (SC#4 / D-04)
**What:** In-memory list of ms-timestamps pruned to the last hour; the prune + cap-check + append must be atomic across concurrent send coroutines.
**When:** Every send. The Node version is race-free because of the JS event loop's run-to-completion on synchronous sections; in Python the `await fetch` between the cap-check and the `sendHistory.push` yields the loop, so two coroutines can both pass the cap check before either appends. `asyncio.Lock` closes this.
```python
# Source: signal.js:41-44, 82-89, 147 (port + Lock per PITFALLS #6 / D-04)
self._lock = asyncio.Lock()
self._send_history: list[int] = []

async def send(self, body, *, bypass_cap=False, to=None, quote=None, **opts):
    now = int(time.time() * 1000)
    async with self._lock:
        self._prune_history(now)                       # drop entries < now - 3_600_000
        cap = self._current_cap()                       # getMaxSendsPerHour() hook, fallback max_sends_per_hour
        if not bypass_cap and len(self._send_history) >= cap:
            self._logger.warning(f"[signal] cap reached ({len(self._send_history)}/{cap}/h) — dropping")
            return {"ok": False, "reason": "rate-cap"}
        self._send_history.append(now)                  # reserve the slot BEFORE the await
    # ... build payload, POST /v2/send OUTSIDE the lock (don't hold lock across network I/O) ...
```
**IMPORTANT design note for the planner:** The Node code appends to `sendHistory` only *after* a successful POST (`signal.js:147`). A naive 1:1 port that holds the lock only for the check-then-appends-after-success leaves the same race. Two correct options: (a) reserve the slot inside the lock *before* the await (shown above; slightly more conservative — a failed send still consumes a slot), or (b) keep append-after-success but make check+append a single locked critical section by re-checking. Option (a) is simpler and the over-count is at most transient. Either way, **do not hold the lock across the `await client.post(...)`** — that would serialize all sends. The SC#4 acceptance test (two concurrent `send()` coroutines must not exceed `maxSendsPerHour`) must pass; flag the append-timing choice as a parity micro-delta to note for Phase 64 (Node counts only successful sends toward the cap; option (a) counts attempts).

### Pattern 3: Lazy group-ID translation cache with force-refresh-once
**What:** `internal_id-b64` (from received envelopes) → `id-b64` (accepted by `/v2/send` as `group.<id-b64>`). Lazy-load `/v1/groups/{sender}` on first group send, cache in a dict, force-refresh once on miss.
**When:** First group send after startup, and on a fresh-group miss.
```python
# Source: signal.js:22-39, 98-112 (port)
async def ensure_groups_loaded(self, force=False):
    if self._groups_loaded and not force:
        return
    try:
        r = await self._client.get(f"{self._api_url}/v1/groups/{quote_plus(self._sender)}",
                                    timeout=self._timeout_s)
        r.raise_for_status()
        self._group_id_map.clear()
        for g in r.json():
            if not g or not g.get("id") or not g.get("internal_id"):
                continue
            id_stripped = g["id"][len("group."):] if g["id"].startswith("group.") else g["id"]
            self._group_id_map[g["internal_id"]] = id_stripped
        self._groups_loaded = True
        self._logger.info(f"[signal] groups loaded ({len(self._group_id_map)} entries)")
    except Exception as e:
        self._logger.warning(f"[signal] groups list failed: {e} — send may fail if recipient is internal_id form")
```

### Anti-Patterns to Avoid
- **`asyncio.gather()` over received envelopes:** breaks send-attribution ordering (PITFALLS #5/#6, memory `feedback_verify_signal_send_attribution`). Process envelopes **sequentially** (one `await` per envelope), exactly like the Node `for (const env of envelopes)` loop.
- **Holding the rate-cap lock across the network POST:** serializes all sends; only guard the check+reserve.
- **`int(q['timestamp'])` without `str()`:** raises on a numeric-string timestamp. Always `int(str(ts))`.
- **`float()` coercion of `signal_msg_ts`:** loses precision / makes it a float; must be `int()` for the bigint column.
- **Letting an outbound-persist exception escape `send()`:** violates D-02 fail-open; wrap in try/except → warn.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Signal transport framing | Raw asyncio JSON-RPC socket reader/writer | `httpx.AsyncClient` against the existing REST container | The container already does the signal-cli wrapping; a socket needs `MODE=json-rpc` which breaks HTTP receive + registration |
| HTTP timeouts / aborts | Manual `AbortController`/timer translation | `httpx` `timeout=` param + `httpx.TimeoutException` | httpx has first-class timeout config; no need to port the `setTimeout(()=>ctrl.abort())` dance literally |
| Group-ID translation | Re-deriving b64 forms by hand | Port `ensure_groups_loaded` lazy cache | signal-cli's id duality is a known quirk; the cache is the tested solution |
| Quote validation | New schema lib | Port `isValidQuote` (4-field shape check) | The shape is locked (Phase 50); 6 lines of isinstance checks |
| Rate limiting | Token bucket / external limiter | In-memory list + `asyncio.Lock` (D-04) | Matches Node exactly; parity-preserving; resets on restart by design |
| Outbound persistence | ORM / queue | psycopg3 `insert_outbound` (Phase 56 table) | Table + index already exist; raw parameterized INSERT |

**Key insight:** Every "hard" part of this phase (group duality, quote shape, string-vs-int timestamp, rate-cap) is already solved once in `signal.js`. The job is faithful translation, not invention. The ONE genuinely new mechanism is `asyncio.Lock` (Node didn't need it) — and that is the only place the port deviates from "copy the logic."

## Runtime State Inventory

> This is a rename/port phase touching a live shared service (`signal-cli`) and a live shared DB. Inventory of runtime state that a code port alone does not migrate:

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `signal_outbound` table (incl. `signal_msg_ts bigint`, `recipient_e164`, `intent`, related-id text columns) already exists in the shared TimescaleDB, created by Node + Phase-56 additive migrations. Python writes rows to the SAME table. | Code edit only (write rows). No data migration. Verify the `signal_msg_ts` column + index exist (they do per `outbound-db.js:50-51`); Phase 56 ports the DDL. |
| Live service config | The `signal-cli` container: `MODE=normal`, named volume `signal-cli-data` holds the **primary account registration + identity trust state**. This is NOT in git. The Python `alerter-py` shares this exact container (joins `signal-net`). | None — Python reuses the running container as-is. Do NOT flip `MODE`. Do NOT re-register. The Phase-36 `post-rebuild-trust-check.sh` identity-trust posture is preserved by not touching the container. |
| OS-registered state | None — no Task Scheduler / systemd / pm2 entries embed Signal state for this phase. | None — verified: Signal layer is fully containerized. |
| Secrets/env vars | `SIGNAL_SENDER` (secret, from `tenants/mossrock/secrets.env`), `SIGNAL_RECIPIENT`, `SIGNAL_GROUP_ID`, `SIGNAL_ADDITIONAL_SENDERS`, `SIGNAL_FARMER_MAP`, `ALERT_MAX_SENDS_PER_HOUR`, `ALERT_RECEIVE_POLL_SEC`, `SIGNAL_API_URL` (defaults `http://signal-cli:8080`). The `alerter-py` compose block already wires these (`docker-compose.override.yml:186-218`). | Code reads them via `TenantConfig` (Phase 56), NOT `os.environ` directly. `SIGNAL_SENDER` MUST resolve env-only (mustEnv equivalent), never tenant YAML (W9 policy). Note `alerter-py` block does NOT set `SIGNAL_API_URL` — defaults to `http://signal-cli:8080`, correct for `signal-net`. |
| Build artifacts | None for this phase (no compiled output; the `src/farm-agent/` Dockerfile is Phase 56's). | None. |

**The canonical question — after every file is ported, what runtime state still carries the old behavior?** Answer: the `signal-cli` container's account registration and identity-trust volume, which the Python port deliberately reuses unchanged. The only behavioral state the Python process owns is the in-memory `sendHistory` (resets on restart, by design — matches Node).

## Common Pitfalls

### Pitfall 1: signal_msg_ts coerced to float, not bigint (SC#1)
**What goes wrong:** signal-cli returns `/v2/send` `timestamp` as a **stringified** number (`"1779562666675"`, confirmed Phase 50 spike). Python `float(ts)` makes it a float; storing into the `bigint` column either errors or silently stores a float-ish value. `int(ts)` works, but `int("1779562666675.0")` would raise — and JSON numbers are safe but a string with a decimal is not.
**Why:** JS `Number(ts)` is forgiving; Python is type-strict.
**How to avoid:** Coerce with `int(json_resp["timestamp"]) if json_resp.get("timestamp") else None`. ms-since-epoch in 2026 (~1.75e12) is far under 2^63, so bigint is safe. Never route through `float()`.
**Warning signs:** `signal_outbound` rows with `signal_msg_ts` NULL when signal-cli returned a value, or psycopg `invalid input syntax for type bigint`.
**Verification (SC#1):** Round-trip test — send a message, capture `/v2/send` response timestamp, assert the stored `signal_outbound.signal_msg_ts` is a Python `int` equal to it.

### Pitfall 2: Group message silently dropped (SC#2)
**What goes wrong:** Sending the `internal_id-b64` form (from a received envelope's `groupInfo.groupId`) directly to `/v2/send` gets a 400 or a silent non-delivery. The configured `SIGNAL_GROUP_ID` env is the `id-b64` form (operator-chosen) and works wrapped as `group.<id>`; but envelope-driven group replies carry the DIFFERENT `internal_id-b64`.
**Why:** signal-cli's id duality.
**How to avoid:** Port `ensure_groups_loaded` lazy cache + `internal_id → id-b64` translation (Pattern 3). On a cache miss, pass through as-is (the configured form may already be id-b64) and force-refresh once on a fresh-group failure.
**Warning signs:** HTTP 400 from `/v2/send` on group target, or group members never receive a message that logged "sent".
**Verification (SC#2):** Live group message from the Python stack lands in the Signal group, translated via `/v1/groups` cache, not 400, not dropped.

### Pitfall 3: Quote `timestamp` string-vs-int + non-fail-open (SC#3 / SIG-04)
**What goes wrong:** A Python `int(q['timestamp'])` raises on a numeric-string; raising inside the quote path would block the entire send (violating fail-open).
**Why:** signal-cli may return / callers may pass `timestamp` as either a number or a numeric string (locked Phase 50). The `isValidQuote` gate uses `Number.isFinite(Number(q.timestamp))` in Node.
**How to avoid:** Port `is_valid_quote` with a tolerant numeric check, then coerce with `int(str(q["timestamp"]))`. On invalid shape: log `warn`, send WITHOUT the quote field (never throw). Empty `message` is allowed; `author` must be a non-empty string.
```python
# Source: signal.js:71-80, 119-131 (port)
def is_valid_quote(q) -> bool:
    if not isinstance(q, dict):
        return False
    try:
        ts_ok = math.isfinite(float(str(q.get("timestamp"))))
    except (TypeError, ValueError):
        return False
    return (ts_ok
            and isinstance(q.get("author"), str) and len(q["author"]) > 0
            and isinstance(q.get("message"), str))
# in send(): if quote is not None: if is_valid_quote(quote): payload["quote"] =
#   {"timestamp": int(str(quote["timestamp"])), "author": quote["author"], "message": quote["message"]}
#   else: logger.warning(...); (send unquoted)
```
**Note:** Node coerces the payload timestamp via `Number(quote.timestamp)` (→ JS number). The locked Phase-50 wire shape is `{timestamp, author, message}`, empirically accepted by REST 0.14.2. `int(str(ts))` is the SC#3-mandated coercion and produces an integer the JSON serializer emits as a bare number — equivalent on the wire.
**Verification (SC#3):** String-timestamp quote passes coercion and renders a native quote bubble on the client; invalid shape → unquoted send + warning, no exception.

### Pitfall 4: asyncio concurrency overrunning the rate-cap (SC#4)
**What goes wrong:** Without a lock, two concurrent `send` coroutines both pass the cap check before either records its send (the `await` on the POST yields the loop). Node is immune because its synchronous check-then-(later)-push windows don't interleave the same way.
**How to avoid:** `asyncio.Lock` per Pattern 2. See the IMPORTANT design note about append timing.
**Verification (SC#4):** Two concurrent `send()` coroutines do not exceed `maxSendsPerHour`.

### Pitfall 5: Attribution inferred instead of read (SIG-01)
**What goes wrong:** Reading `envelope.source` is correct; inferring the sender from arrival order / message length is the documented anti-pattern (memory `feedback_verify_signal_send_attribution`). Concurrent envelope processing with `gather()` can misassign.
**How to avoid:** Process envelopes sequentially; read `env["envelope"]["source"]` directly; whitelist gate BEFORE any branch (`receive-loop.js:139`).

### Pitfall 6: `(unassigned)` tagging lives across a phase boundary (SC#5 / SIG-03)
**What goes wrong:** The literal `farmosPerson = signalFarmerMap.get(source) ?? '(unassigned)'` lookup currently lives in `capture.js` (`:86`, `:335`) — which is Phase 58 territory. A literal-only reading of the port boundary would push SC#5 out of Phase 57. But SIG-03/SC#5 explicitly require "unknown numbers tagged `(unassigned)`, never dropped" in THIS phase.
**How to avoid:** Land the **farmer-map resolution primitive** (`resolve_farmer(source) -> slug | "(unassigned)"`) in `signal_io/router.py` in Phase 57, and verify SC#5 at the router level (unknown sender is NOT dropped by the whitelist when it's an additional-sender/recipient, and resolves to `(unassigned)`). The Phase-58 capture pipeline then *consumes* this primitive. See Scope Boundary below. Flag for the planner: confirm with the success-criteria author whether SC#5 is satisfied by (a) the router primitive + a unit test, or (b) requires a live unknown-sender round-trip — the latter may need a Phase-58 consumer to observe. Recommended: ship the primitive + unit test here; full live observation is naturally a Phase-58 live-fire.

## Scope Boundary Note (planner must resolve)

CONTEXT lists `message.js` as a port target "envelope routing (source extraction, DM vs group, `(unassigned)` tagging)". **`message.js` is actually the alert-message FORMATTER** (`formatProblem`/`formatRecovery`/`formatHeartbeat`/`fmtNum`) — `[VERIFIED: src/agents/alerter/src/message.js]` — it has NO envelope routing and NO `(unassigned)` logic. The actual routing lives in:
- `receive-loop.js` — source extraction, whitelist, DM-vs-group, group-trigger detection.
- `capture.js:86,335` — the `(unassigned)` farmer-map resolution (Phase 58 file).

`message.js` (alert formatters) belongs to `chamber/message.py` (Phase 63, CHM), NOT `signal_io`. The planner should:
1. Port envelope routing from `receive-loop.js` → `signal_io/router.py` + `receive_loop.py` (the relevant, attribution-sensitive subset; the confirm/snooze/experiment/capture dispatch branches are LATER phases — extract only the source/whitelist/group-trigger/`(unassigned)`-resolution skeleton + a `dispatch(envelope)` seam).
2. Land the `(unassigned)` resolution primitive in `signal_io/router.py` (not wait for Phase 58).
3. NOT port `message.js` here.

## Code Examples

### Send (1:1 fetch → httpx)
```python
# Source: signal.js:133-203 (port). httpx replaces fetch + AbortController.
r = await self._client.post(
    f"{self._api_url}/v2/send",
    json=payload,                       # {"message": body, "number": sender, "recipients": [...], [optional "quote"]}
    timeout=self._timeout_s,            # replaces setTimeout(()=>ctrl.abort())
)
if r.status_code >= 400:
    raise RuntimeError(f"signal-cli {r.status_code}: {r.text[:200]}")
data = r.json() if r.content else {}
# under lock: self._send_history.append(now)  (see Pattern 2 for timing)
return {"ok": True, "timestamp": data.get("timestamp") or now}
```

### Receive (HTTP GET long-poll)
```python
# Source: signal.js:205-210 (port)
async def receive(self, *, timeout_sec=1, ignore_attachments=False):
    url = (f"{self._api_url}/v1/receive/{quote_plus(self._sender)}"
           f"?timeout={timeout_sec}&ignore_attachments={str(ignore_attachments).lower()}")
    r = await self._client.get(url, timeout=timeout_sec + 5)   # request timeout > server long-poll
    r.raise_for_status()
    return r.json()
```

### Fetch attachment (binary)
```python
# Source: signal.js:212-218 (port). arrayBuffer -> .content (bytes)
async def fetch_attachment(self, attachment_id) -> bytes:
    r = await self._client.get(f"{self._api_url}/v1/attachments/{quote_plus(attachment_id)}")
    r.raise_for_status()
    return r.content
```

### Outbound persist (psycopg3, fail-open — D-02)
```python
# Source: signal.js:158-197 + outbound-db.js:54-82 (port to psycopg3)
if self._outbound_repo is not None and self._pool is not None:
    effective_intent = intent or "unknown"
    if not intent:
        self._logger.warning("[signal] send() missing intent — defaulting to 'unknown'")
    recipient_col = target if is_string_target else f"group:{resolved_group_id or target['groupId']}"
    try:
        await self._outbound_repo.insert_outbound(self._pool, {
            "tenant_id": self._tenant_id,
            "sent_at": datetime.now(timezone.utc),          # PITFALLS #7: tz-aware, never naive
            "recipient_e164": recipient_col,
            "intent": effective_intent,
            "body": body,
            "attachments": None,
            "source_module": source_module,
            "source_line": None,
            "related_capture_id": related_capture_id,
            "related_draft_id": related_draft_id,
            "signal_msg_ts": int(data["timestamp"]) if data.get("timestamp") else None,  # bigint, int() not float()
        })
    except Exception as e:
        self._logger.warning(f"[signal] outbound persist threw (fail-open): {e}")  # NEVER propagate
```

## State of the Art

| Old (Node) | New (Python) | Notes |
|------------|--------------|-------|
| `fetch()` + `AbortController` + `setTimeout` | `httpx.AsyncClient` + `timeout=` | Native timeout; no manual abort plumbing |
| `Buffer.from(arrayBuffer)` | `response.content` (bytes) | Direct |
| `Number(ts)` coercion | `int(str(ts))` | String-safe; bigint-preserving |
| Synchronous `sendHistory` push (no lock) | `asyncio.Lock`-guarded | NEW mechanism; Node didn't need it |
| `pg` Pool | psycopg3 `AsyncConnectionPool` | Phase 56 D-01 |
| `Map` group cache | `dict` group cache | Direct |

**Deprecated/outdated:**
- STACK.md §"Option A: Raw JSON-RPC UNIX socket" — superseded by verified live topology (REST container, `MODE=normal`). Do not implement.
- ARCHITECTURE.md asyncpg recommendation — superseded by Phase 56 D-01 (psycopg3).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | httpx 0.28.1 / psycopg 3.3.4 are current and pinned | Standard Stack | LOW — Phase 56 already pinned these; sandbox couldn't re-verify PyPI this session. Planner can `pip index versions` if it matters. |
| A2 | signal-cli REST `0.200-dev` accepts the same `{quote:{timestamp,author,message}}` payload that `0.14.2` accepted in the Phase-50 spike | Pitfall 3 / SIG-04 | MEDIUM — version bumped from 0.14.2 (spike) to 0.200-dev (live). The SC#3 live-fire verification will catch any shape drift; recommend the planner make the quote round-trip a live-fire gate, not just a mock test. |
| A3 | The `alerter-py` service reusing the running `signal-cli` container (shared with live Node `alerter` + `bridge`) is acceptable during coexistence | Runtime State Inventory | MEDIUM — both stacks polling `/v1/receive` on the same primary account could double-consume envelopes. signal-cli `/v1/receive` is destructive (drains the queue). Two concurrent pollers WILL race for messages. **Flag for planner:** Phase 57 live round-trip (SC#1) likely needs the Node `alerter` receive loop stopped, OR a self-send-to-bot test (as the Phase-50 spike did: `+59891840205 → +59891840205`) to avoid stealing the farmer's messages from the live stack. This is the same "no safe dual-run" hazard as PITFALLS #3/#8. |
| A4 | SC#5 `(unassigned)` is satisfiable at the `signal_io/router.py` level without the Phase-58 capture consumer | Pitfall 6 / Scope Boundary | LOW-MEDIUM — depends on the success-criteria author's intent. Recommend confirming; default plan ships the router primitive + unit test here. |

## Open Questions (RESOLVED)

1. **Dual receive-loop contention on the shared `signal-cli` account (A3).**
   - What we know: `/v1/receive` drains the queue; the live Node `alerter` polls it every 30s; the bridge also dispatches via the same container.
   - What's unclear: whether the SC#1 live round-trip can run while the Node alerter is live without stealing the test message.
   - Recommendation: Use the Phase-50 spike pattern — self-send bot→bot (`+59891840205`) and verify via a `signal_outbound` SELECT, OR briefly stop the Node alerter receive loop for the round-trip. Do NOT have two pollers compete on a farmer-facing account. Make this explicit in the SC#1 plan.
   - RESOLVED: Plan 04 self-send bot→bot with a `default_target == signal_sender` guard, no receive loop started (avoids the /v1/receive drain race).

2. **SC#5 acceptance shape (A4).**
   - What we know: the `(unassigned)` resolution is a 1-line farmer-map lookup; the consumer (capture row) is Phase 58.
   - Recommendation: ship the resolution primitive + a unit test (known sender → slug; unknown → `(unassigned)`; never dropped) in `signal_io/router.py`; treat full live unknown-sender observation as a Phase-58 live-fire.
   - RESOLVED: Plan 03 router unit test asserts unknown sender → `(unassigned)` not dropped; live consumer deferred to Phase 58 capture.

3. **Rate-cap append timing parity (Pattern 2 note).**
   - What we know: Node appends only on success; the asyncio-safe options differ on whether a failed send consumes a slot.
   - Recommendation: pick option (a) reserve-before-await for simplicity; note the micro-delta (counts attempts vs successes) for the Phase-64 parity author. At 20/h this never matters in practice.
   - RESOLVED: Plan 02 uses reserve-before-await (append timestamp before the network POST); attempts-vs-successes micro-delta documented as a known Phase-64 parity delta.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `signal-cli-rest-api` container | All Signal I/O | ✓ (live, `signal-net`) | `bbernhard/...:0.200-dev`, `MODE=normal` | — (do not change) |
| TimescaleDB (shared) | `signal_outbound` write | ✓ (live) | — | Phase-64 uses isolated `:5434` for parity (do NOT write to prod DB in parity) |
| httpx | REST client | (Phase 56 dep) | 0.28.1 | — |
| psycopg3 | outbound write | (Phase 56 dep) | 3.3.4 | — |
| Python 3.12 | runtime | (Phase 56 base image) | 3.12-slim | — |

**Missing dependencies with no fallback:** none — all infra is the existing live stack.
**Note:** Sandbox runtime here is Python 3.10 with no pip network; the actual target is the `src/farm-agent/` Docker base (3.12-slim). Version claims rely on Phase 56's prior PyPI verification.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.1.0 + pytest-asyncio 1.4.0 (`asyncio_mode = "auto"`) |
| Config file | `src/farm-agent/pyproject.toml` (Phase 56) |
| Quick run command | `cd src/farm-agent && uv run pytest tests/unit/signal_io -x` |
| Full suite command | `cd src/farm-agent && uv run pytest` |

### Phase Requirements → Test Map
| Req | Behavior | Test Type | Automated Command | File Exists? |
|-----|----------|-----------|-------------------|-------------|
| SIG-01 | send/receive/fetch_attachment/accounts shape; sequential attribution | unit (httpx mock via `respx` or monkeypatched AsyncClient) | `uv run pytest tests/unit/signal_io/test_client.py -x` | ❌ Wave 0 |
| SIG-01 | live round-trip, `signal_msg_ts` bigint non-null | live-fire (manual, autonomous:false) | self-send bot→bot; SELECT signal_outbound | ❌ Wave 0 (manual) |
| SIG-02 | persist-after-send fail-open; insert never blocks send | unit (fake repo that raises) | `uv run pytest tests/unit/signal_io/test_persist.py -x` | ❌ Wave 0 |
| SIG-02/SC#4 | asyncio.Lock prevents cap overrun | unit (two concurrent send coroutines) | `uv run pytest tests/unit/signal_io/test_ratecap.py -x` | ❌ Wave 0 |
| SIG-03 | group internal_id→id-b64 translation; no drop | unit (mock /v1/groups) | `uv run pytest tests/unit/signal_io/test_groups.py -x` | ❌ Wave 0 |
| SIG-03/SC#5 | unknown sender → `(unassigned)`, not dropped | unit (router) | `uv run pytest tests/unit/signal_io/test_router.py -x` | ❌ Wave 0 |
| SIG-04/SC#3 | valid quote payload; string-ts coercion; invalid → fail-open | unit | `uv run pytest tests/unit/signal_io/test_quote.py -x` | ❌ Wave 0 |
| SIG-04/SC#3 | native quote bubble renders | live-fire (visual) | self-send w/ quote; screenshot | ❌ Wave 0 (manual) |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/unit/signal_io -x`
- **Per wave merge:** `uv run pytest` (full unit suite)
- **Phase gate:** full unit suite green + SC#1 and SC#3 live-fire passes before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/unit/signal_io/test_client.py` — send/receive/fetch_attachment/accounts (SIG-01)
- [ ] `tests/unit/signal_io/test_ratecap.py` — concurrent-send cap test (SC#4)
- [ ] `tests/unit/signal_io/test_groups.py` — group translation (SC#2)
- [ ] `tests/unit/signal_io/test_quote.py` — quote shape + coercion + fail-open (SC#3)
- [ ] `tests/unit/signal_io/test_router.py` — whitelist + DM/group + `(unassigned)` (SC#5)
- [ ] `tests/unit/signal_io/test_persist.py` — fail-open outbound (SIG-02)
- [ ] `tests/conftest.py` — httpx mock fixture (respx or monkeypatched AsyncClient) + fake outbound repo
- [ ] Decide httpx mocking approach: `respx` (declarative, recommended) vs monkeypatched `AsyncClient` — `respx` is NOT yet in Phase 56 deps; if used, add to dev deps (run slopcheck/verify before pinning).

## Security Domain

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | partial | signal-cli holds the Signal identity; Python does not authenticate users — it trusts the sender whitelist (`allowedSenders`). |
| V4 Access Control | yes | Sender whitelist gate (`receive-loop.js:126-128,139`): only `signalSender` + `signalRecipient` + `signalAdditionalSenders` are processed; all others dropped (R7/T-17-02). Port verbatim. Unknown-but-whitelisted → `(unassigned)`, NOT dropped (SC#5). |
| V5 Input Validation | yes | `isValidQuote` shape check; envelope field defensive reads (`env?.envelope?.dataMessage` both shapes); quote spoof guard (sender-equality) lives in the confirm-path phase, NOT here. |
| V6 Cryptography | no (delegated) | All Signal E2E crypto is inside signal-cli; Python never touches keys. The `signal-cli-data` volume + Phase-36 identity-trust check own this. |
| V7 Logging | yes | `maskNumber()` masks phone numbers in logs (`config.js:258`); port it — never log full e164. Group labels truncated to 8 chars. |

### Known Threat Patterns for signal_io
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Spoofed/unknown sender driving the bot | Spoofing | Sender whitelist gate before any branch; `(unassigned)` for unknown-but-allowed |
| Quote spoofing (reply to another farmer's draft) | Tampering | Sender-equality guard on quote-resolution — lives in the confirm-path phase (receive-loop.js:263), NOT this primitive phase; note for planner |
| PII leak in logs | Information Disclosure | `maskNumber()` on every send/route log line |
| Outbound flood / cost | DoS | `maxSendsPerHour` rate-cap (asyncio.Lock-guarded) |
| Secret in tenant YAML | Information Disclosure | `SIGNAL_SENDER` env-only via mustEnv-equivalent, never tenant YAML (W9) |

## Sources

### Primary (HIGH confidence)
- `src/agents/alerter/src/signal.js` — the port target; transport (REST `fetch`), `isValidQuote`, group translation, rate-cap, fail-open persist `[VERIFIED]`
- `src/agents/alerter/src/receive-loop.js` — envelope routing, whitelist, DM-vs-group, sequential processing `[VERIFIED]`
- `src/agents/alerter/src/outbound-db.js` — `signal_outbound` schema, `signal_msg_ts bigint`, ULID-vs-uuid history `[VERIFIED]`
- `src/agents/alerter/src/config.js` — config tiers, farmer-map parse, `maskNumber` `[VERIFIED]`
- `src/agents/alerter/src/capture.js:86,335` — `(unassigned)` farmer-map resolution (Phase 58 consumer) `[VERIFIED]`
- `docker-compose.override.yml` — `signal-cli` `MODE=normal`, `signal-net`, `alerter-py` env block `[VERIFIED]`
- `.planning/phases/57-signal-i-o/57-CONTEXT.md`, `56-foundation/56-CONTEXT.md`, `50-.../50-CONTEXT.md` — locked decisions `[VERIFIED]`
- `.planning/research/ARCHITECTURE.md:320` — REST/httpx integration (contradicts STACK.md Option A) `[VERIFIED]`
- `.planning/research/PITFALLS.md` #5 (signal-cli interop), #6 (asyncio races), #7 (serialization) `[VERIFIED]`
- `.planning/ROADMAP.md` §Phase 57, `.planning/REQUIREMENTS.md` SIG-01..04 `[VERIFIED]`

### Secondary (MEDIUM confidence)
- `.planning/phases/50-.../50-CONTEXT.md` spike findings — `{quote:{timestamp,author,message}}` accepted by signal-cli REST 0.14.2; returned `"1779562666675"` `[VERIFIED: in-repo spike record]`
- bbernhard/signal-cli-rest-api discussions #160/#361 — `MODE=json-rpc` makes `/v1/receive` WebSocket-only and disables registration; `MODE=normal` = HTTP GET `[CITED]`
- `.planning/research/STACK.md` PyPI version checks (2026-06-14): httpx 0.28.1, psycopg 3.3.4 `[CITED, not re-verified this session]`

### Tertiary (LOW confidence)
- signal-cli-rest-api Swagger/GitHub README — could not extract endpoint-level detail via WebFetch (content truncated); endpoint shapes taken from the verified Node usage instead.

## Metadata

**Confidence breakdown:**
- Transport decision: HIGH — empirically verified from live source + compose + upstream mode semantics; three independent confirmations (signal.js, compose comment, ARCHITECTURE.md).
- Standard stack: HIGH (locked by Phase 56) — version strings MEDIUM (not re-verified this session).
- Architecture/patterns: HIGH — direct port of read source.
- Pitfalls: HIGH — grounded in in-repo PITFALLS.md + post-mortems.
- Quote shape on 0.200-dev: MEDIUM — spike was on 0.14.2; recommend live-fire gate (A2).

**Research date:** 2026-06-15
**Valid until:** 2026-07-15 (stable; signal-cli container pinned, source frozen). Re-check only if the `signal-cli` image tag or `MODE` changes.
